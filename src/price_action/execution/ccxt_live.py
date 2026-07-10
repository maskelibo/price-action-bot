"""Canlı borsa broker (Binance + Bybit ccxt).

LIVE MODE GUARD'ları (her ikisi True olmalı):
  1) `settings.is_live` (yani PA_RUN_MODE=live AND PA_LIVE_CONFIRM=YES_I_KNOW)
  2) `risk.yaml -> live_mode_enabled: true`

Ek olarak:
  - Test API anahtarı varken (testnet=True) live'a geçiş yasak.
  - Slippage > 25 bps emirleri iptal et, resubmit etme.
  - Kademeli post-only limit → market fallback (timeout sonrası).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import yaml

from price_action.contracts import Fill, OrderInstruction, Position, stable_hash
from price_action.execution.broker_base import BrokerBase
from price_action.logging_config import logger
from price_action.settings import get_settings


class CCXTLiveBroker(BrokerBase):
    """Canlı borsa adaptörü — minimum yüzey, max guard."""

    mode = "live"

    def __init__(
        self,
        venue: str = "binance",
        *,
        risk_yaml_path: str | None = None,
        post_only_timeout_sec: int = 30,
        max_slippage_bps: float = 25.0,
    ) -> None:
        self.venue = venue
        self.post_only_timeout_sec = post_only_timeout_sec
        self.max_slippage_bps = max_slippage_bps
        self._log = logger.bind(component="ccxt_live", venue=venue)
        self._exchange: Any = None
        self._risk_yaml_path = risk_yaml_path
        self._verify_live_mode()

    # ----- guard -----
    def _verify_live_mode(self) -> None:
        s = get_settings()
        # Guard 1: settings
        if not s.is_live:
            raise RuntimeError(
                "LIVE_GUARD: settings.is_live False. "
                "PA_RUN_MODE=live ve PA_LIVE_CONFIRM=YES_I_KNOW gerekir."
            )
        # Guard 2: risk.yaml live_mode_enabled
        risk_path = self._risk_yaml_path or str(s.configs_dir / "risk.yaml")
        try:
            with open(risk_path, encoding="utf-8") as f:
                risk_cfg = yaml.safe_load(f) or {}
        except Exception:
            risk_cfg = {}
        if not bool(risk_cfg.get("live_mode_enabled", False)):
            raise RuntimeError(
                "LIVE_GUARD: risk.yaml live_mode_enabled=False. Live emir reddedildi."
            )
        # Guard 3: testnet anahtarı varken live yasak
        if self.venue == "binance" and s.binance_testnet:
            raise RuntimeError("LIVE_GUARD: Binance testnet=True iken live mode reddedildi.")
        if self.venue == "bybit" and s.bybit_testnet:
            raise RuntimeError("LIVE_GUARD: Bybit testnet=True iken live mode reddedildi.")
        self._log.info("ccxt_live.guards_passed")

    # ----- exchange -----
    def _get_exchange(self) -> Any:
        if self._exchange is not None:
            return self._exchange
        import ccxt  # type: ignore

        s = get_settings()
        kls = getattr(ccxt, self.venue, None)
        if kls is None:
            raise RuntimeError(f"ccxt venue desteklenmiyor: {self.venue}")
        cfg: dict[str, Any] = {"enableRateLimit": True}
        if self.venue == "binance":
            cfg["apiKey"] = s.binance_api_key
            cfg["secret"] = s.binance_api_secret
        elif self.venue == "bybit":
            cfg["apiKey"] = s.bybit_api_key
            cfg["secret"] = s.bybit_api_secret
        self._exchange = kls(cfg)
        return self._exchange

    # ----- API -----
    def place_order(self, instruction: OrderInstruction) -> Fill | None:
        ex = self._get_exchange()
        sig = instruction.risked_order.signal
        symbol = sig.symbol
        side_ccxt = "buy" if sig.direction == "long" else "sell"
        qty = instruction.risked_order.quantity

        # Pre-check: ticker'dan ref price
        try:
            ticker = ex.fetch_ticker(symbol)
            ref_price = float(ticker.get("last") or ticker.get("close") or 0.0)
        except Exception as exc:
            self._log.bind(err=str(exc)).error("live.ticker_fail")
            return None
        if ref_price <= 0:
            return None

        # Limit price
        if instruction.order_type == "post_only_limit":
            # v0.9.4 FIX (Lab Scientist O1): mid-tabanli offset post-only REJECT'e zorluyordu.
            # best_bid/best_ask + tick offset ile market'i cross etmeyen fiyat.
            # Maker rebate (Binance -%0.01) bu sayede gercekten kazanilir.
            try:
                ob = ex.fetch_order_book(symbol, limit=5)
                best_bid = float(ob["bids"][0][0]) if ob["bids"] else ref_price * 0.9995
                best_ask = float(ob["asks"][0][0]) if ob["asks"] else ref_price * 1.0005
            except Exception as exc:
                self._log.bind(err=str(exc)).warning("live.orderbook_fail_fallback")
                best_bid = ref_price * 0.9995
                best_ask = ref_price * 1.0005

            tick_offset = ref_price * 0.0001  # 1 bps tick
            if side_ccxt == "buy":  # noqa: SIM108 (yön-yorumları okunurluk için korunur)
                # Post-only buy: best_bid'in 1 tick altinda — market'i cross etmez,
                # passive limit emri olarak book'a eklenir.
                limit_price = best_bid - tick_offset
            else:
                # Post-only sell: best_ask'in 1 tick ustunde.
                limit_price = best_ask + tick_offset

            order_args: dict[str, Any] = {
                "symbol": symbol,
                "type": "limit",
                "side": side_ccxt,
                "amount": qty,
                "price": limit_price,
                "params": {"postOnly": True, "timeInForce": "GTC"},
            }
        elif instruction.order_type == "market":
            order_args = {
                "symbol": symbol,
                "type": "market",
                "side": side_ccxt,
                "amount": qty,
                "params": {},
            }
        else:
            order_args = {
                "symbol": symbol,
                "type": "limit",
                "side": side_ccxt,
                "amount": qty,
                "price": instruction.limit_price,
                "params": {},
            }

        # Place — tenacity retry isteniyor; burada kısa içsel retry
        order = self._place_with_retry(ex, order_args)
        if order is None:
            return None

        # Post-only timeout takibi
        order_id = str(order.get("id"))
        _prior_filled = 0.0  # limit-bacağı kısmi dolumu (yalnız market top-up'ta > 0)
        if instruction.order_type == "post_only_limit":
            t0 = time.time()
            filled = False
            while time.time() - t0 < self.post_only_timeout_sec:
                try:
                    o = ex.fetch_order(order_id, symbol)
                    if o.get("status") == "closed":
                        filled = True
                        order = o
                        break
                except Exception:
                    pass
                time.sleep(1.0)
            if not filled:
                # Fix A (çift-pozisyon önleme, 2026-07-10): cancel'ı YUTMA + körü
                # körüne tam-qty market ATMA. Cancel sonrası borsadan GERÇEĞİ tazele;
                # limit hâlâ açık/durum bilinmiyorsa ikiye katlamayı REDDET
                # (fail-closed); onaylı iptalse yalnız DOLMAYAN kalanı market at
                # (kısmi fill üstüne tam-qty = 2× maruziyet idi — naked-double sınıfı).
                cancel_ok = True
                try:
                    ex.cancel_order(order_id, symbol)
                except Exception as _ce:
                    cancel_ok = False
                    self._log.bind(err=str(_ce)[:120]).warning("live.post_only_cancel_failed")
                _partial = 0.0
                still_resting = not cancel_ok
                try:
                    o = ex.fetch_order(order_id, symbol)
                    _partial = float(o.get("filled") or 0.0)
                    _status = o.get("status")
                    if _status == "closed":
                        filled = True  # race: 30s sonrası tam doldu → market GEREKMEZ
                        order = o
                    elif _status == "open":
                        still_resting = True  # cancel etkisiz, limit hâlâ borsada
                except Exception as _fe:
                    still_resting = True  # durum bilinmiyor → fail-closed
                    self._log.bind(err=str(_fe)[:120]).error("live.post_only_status_unknown")
                if not filled:
                    if still_resting:
                        self._push_alert(
                            f"live post-only cancel doğrulanamadı {symbol} — "
                            f"çift-pozisyon riski, market fallback İPTAL",
                            source="ccxt_live_double_guard",
                        )
                        return None
                    remaining = max(0.0, qty - _partial)
                    if remaining <= 0.0:
                        filled = True  # zaten tümü dolmuş → order=o kullan
                        order = o
                    else:
                        _prior_filled = _partial  # kalan market'e; toplam = _partial+market
                        self._log.bind(remaining=remaining).info(
                            "live.post_only_timeout_market_fallback"
                        )
                        fb = self._place_with_retry(
                            ex,
                            {
                                "symbol": symbol,
                                "type": "market",
                                "side": side_ccxt,
                                "amount": remaining,
                                "params": {},
                            },
                        )
                        if fb is None:
                            return None
                        order = fb
                        order_id = str(order.get("id"))

        # Fix B (2026-07-10): fill'i BORSA GERÇEĞİNDEN kaydet, fail-closed.
        # Eskiden average/price yoksa ref_price'a (beklenen) + filled yoksa qty'ye
        # (istenen) düşüyordu → hayalet fiyat/miktar journal'landı, slippage sahte-0.
        # Artık gerçek yoksa None + alarm (asla uydurma değer).
        _mkt_filled = float(order.get("filled") or 0.0)
        total_filled = _prior_filled + _mkt_filled
        fill_price = float(order.get("average") or order.get("price") or 0.0)
        if total_filled <= 0.0 or fill_price <= 0.0:
            self._push_alert(
                f"live fill doğrulanamadı {symbol} order={order_id} "
                f"(filled={total_filled}, px={fill_price}) — kayıt YOK, reconcile gerek",
                source="ccxt_live_no_fill",
            )
            return None

        slip_bps = abs((fill_price - ref_price) / ref_price * 10_000)
        if slip_bps > self.max_slippage_bps:
            self._log.bind(slip_bps=slip_bps).error("live.slippage_too_high_no_resubmit")
            # Resubmit yasak — Analyst'e ticket bırak (caller halleder)
            return None

        fee_total = (
            float(order.get("fee", {}).get("cost", 0.0)) or total_filled * fill_price * 0.00075
        )
        return Fill(
            order_id=order_id,
            venue=self.venue,
            symbol=symbol,
            side=sig.direction,  # type: ignore[arg-type]
            price=fill_price,
            quantity=total_filled,
            fee_usdt=fee_total,
            timestamp=datetime.now(UTC),
            is_maker=instruction.order_type == "post_only_limit",
            expected_price=ref_price,
            slippage_bps=slip_bps,
            mode="live",
            manifest_hash=stable_hash(
                {
                    "order_id": order_id,
                    "symbol": symbol,
                    "qty": qty,
                    "fill_price": fill_price,
                }
            ),
        )

    def _push_alert(self, msg: str, source: str) -> None:
        """Fail-closed durum alarmı (log + Telegram, güvenli — asla raise etmez)."""
        self._log.error(msg)
        try:
            from price_action.orchestrator.notifications import push_critical

            push_critical(msg, source=source)
        except Exception:
            pass

    def _place_with_retry(self, ex: Any, kwargs: dict[str, Any], n_max: int = 5) -> Any:
        """Exponential backoff retry. ccxt rate-limit dostu."""
        from tenacity import (  # type: ignore
            retry,
            retry_if_exception_type,
            stop_after_attempt,
            wait_exponential,
        )

        @retry(
            stop=stop_after_attempt(n_max),
            wait=wait_exponential(multiplier=1, min=1, max=30),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        )
        def _do() -> Any:
            return ex.create_order(**kwargs)

        try:
            return _do()
        except Exception as exc:
            self._log.bind(err=str(exc)).error("live.place_retry_exhausted")
            return None

    def cancel(self, order_id: str) -> bool:
        ex = self._get_exchange()
        try:
            ex.cancel_order(order_id)
            return True
        except Exception as exc:
            self._log.bind(err=str(exc)).error("live.cancel_fail")
            return False

    def fetch_positions(self) -> list[Position]:
        ex = self._get_exchange()
        try:
            raw = ex.fetch_positions()
        except Exception as exc:
            self._log.bind(err=str(exc)).warning("live.fetch_positions_fail")
            return []
        out: list[Position] = []
        for r in raw or []:
            try:
                qty = float(r.get("contracts") or r.get("amount") or 0.0)
                if qty <= 0:
                    continue
                side = "long" if r.get("side") in ("long", "buy") else "short"
                out.append(
                    Position(
                        venue=self.venue,
                        symbol=r.get("symbol", ""),
                        side=side,  # type: ignore[arg-type]
                        quantity=qty,
                        entry_price=float(r.get("entryPrice") or 0.0),
                        current_price=float(r.get("markPrice") or 0.0),
                        unrealized_pnl_usdt=float(r.get("unrealizedPnl") or 0.0),
                        realized_pnl_usdt=0.0,
                        opened_at=datetime.now(UTC),
                        strategy_id="",
                        last_updated=datetime.now(UTC),
                    )
                )
            except Exception:  # pragma: no cover - defensive
                continue
        return out

    def fetch_balance(self) -> dict[str, float]:
        ex = self._get_exchange()
        try:
            b = ex.fetch_balance()
            return {k: float(v) for k, v in (b.get("free") or {}).items()}
        except Exception as exc:
            self._log.bind(err=str(exc)).error("live.fetch_balance_fail")
            return {}
