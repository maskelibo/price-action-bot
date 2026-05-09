"""Backtest engine — vectorbt sarmalayıcı.

Multi-symbol/multi-strategy. Risk layer'ı backtest sırasında çağrılır,
böylece live ile bit-identical sizing logic kullanılır.

vectorbt (numba) varsa onun simülatörü kullanılır; yoksa saf-pandas
fallback (yavaşlık karşılığında bağımlılık-bağımsız).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from price_action.contracts import (
    ReproducibilityManifest,
    Signal,
    TradeRecord,
    stable_hash,
)
from price_action.logging_config import logger
from price_action.risk.sizing import AccountState, RiskOfficer
from price_action.strategies.base import Strategy


# =====================================================================
# Result schema
# =====================================================================

class BacktestResult(BaseModel):
    """Backtest çıktısı."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    strategy_name: str
    timeframe: str
    start: datetime
    end: datetime
    initial_capital: float
    fees: dict[str, float]
    slippage_bps: float
    universe: list[str]
    n_trades: int
    kpis: dict[str, float]
    equity_curve: pd.Series  # index: ts, values: equity
    trades: pd.DataFrame  # TradeRecord rows
    manifest: ReproducibilityManifest
    elapsed_sec: float = 0.0
    symbol_slippage_map: dict[str, float] = Field(default_factory=dict)  # per-symbol bps


# =====================================================================
# Engine
# =====================================================================

class BacktestEngine:
    """Bar-by-bar backtest. Long & short, ATR-bazlı SL, R-multiple TP.

    Risk Officer her sinyalde sizing yapar — gerçek live davranışa eşdeğer.
    """

    def __init__(
        self,
        *,
        risk_officer: RiskOfficer | None = None,
        store_load: Any | None = None,
    ) -> None:
        """`store_load` = lazy callable: (symbol, tf, start, end) -> DataFrame."""
        self.risk_officer = risk_officer
        self.store_load = store_load
        self._log = logger.bind(component="backtest_engine")

    # ----- public API -----
    def run(
        self,
        strategy: Strategy,
        universe: list[str],
        *,
        start: datetime,
        end: datetime,
        fees: dict[str, float] | None = None,
        slippage_bps: float = 5.0,
        symbol_slippage_map: dict[str, float] | None = None,
        initial_capital: float = 10_000.0,
        timeframe: str = "1d",
        ohlcv_provider: Any | None = None,
    ) -> BacktestResult:
        """Backtest çalıştır.

        `ohlcv_provider`: opsiyonel (symbol, tf) -> pd.DataFrame; yoksa
        `self.store_load` veya OHLCVStore default'a düşer.

        `symbol_slippage_map`: {symbol: bps} — varsa per-symbol kullanılır,
        eksik semboller `slippage_bps` flat default'a düşer (geriye uyumlu).
        """
        t0 = time.perf_counter()
        fees = fees or {"taker": 0.00075, "maker": -0.00010}
        symbol_slippage_map = symbol_slippage_map or {}

        all_trades: list[dict[str, Any]] = []
        # Tüm semboller için ortak tarihli equity curve oluştur
        global_equity = initial_capital
        pnl_by_ts: dict[pd.Timestamp, float] = {}

        loader = ohlcv_provider or self.store_load or _default_loader
        for sym in universe:
            try:
                df = loader(sym, timeframe, start, end)
            except Exception as exc:
                self._log.bind(sym=sym, err=str(exc)).warning("loader_fail")
                continue
            if df is None or df.empty:
                continue
            df = df.copy()
            df["symbol"] = sym
            if "venue" not in df.columns:
                df["venue"] = "binance"
            if "timeframe" not in df.columns:
                df["timeframe"] = timeframe
            df = strategy.prepare_features(df)
            signals = strategy.generate_signals(df)
            # Per-symbol slippage: map override veya flat fallback
            sym_slip = symbol_slippage_map.get(sym, slippage_bps)
            sym_trades = self._simulate_symbol(
                df=df,
                signals=signals,
                strategy_id=strategy.name,
                slippage_bps=sym_slip,
                fees=fees,
                initial_capital=initial_capital,
                pnl_accumulator=pnl_by_ts,
            )
            all_trades.extend(sym_trades)

        # Equity curve — daily mark-to-market on realized PnL.
        # Eski versiyon sadece trade-exit timestamps'ı kullanıyordu (~74 obs)
        # → Sharpe/CAGR `(periods_per_year / n_returns)` exponent'i ile şişiyordu.
        # Yeni versiyon: backtest aralığındaki TÜM bar tarihlerini kullanır,
        # her bara o ana kadar gerçekleşmiş kümülatif PnL'i atar (forward-fill).
        # Bu sayede Sharpe/CAGR 365-day annualization üzerinden doğru hesaplanır.
        _start_ts_raw = pd.Timestamp(start)
        _end_ts_raw = pd.Timestamp(end)
        start_ts = (
            _start_ts_raw.tz_convert("UTC")
            if _start_ts_raw.tzinfo is not None
            else _start_ts_raw.tz_localize("UTC")
        )
        end_ts = (
            _end_ts_raw.tz_convert("UTC")
            if _end_ts_raw.tzinfo is not None
            else _end_ts_raw.tz_localize("UTC")
        )

        # Build daily date index covering the full backtest range.
        # Timeframe-based frequency: 1d → daily, 1w → weekly, 1h → hourly, vs.
        _freq_map = {"1d": "D", "1w": "W", "1h": "h", "4h": "4h", "15m": "15min"}
        freq = _freq_map.get(timeframe, "D")
        try:
            full_index = pd.date_range(start=start_ts, end=end_ts, freq=freq, tz="UTC")
        except Exception:
            full_index = pd.DatetimeIndex([start_ts, end_ts], tz="UTC")
        if len(full_index) < 2:
            full_index = pd.DatetimeIndex([start_ts, end_ts], tz="UTC")

        if pnl_by_ts:
            # Cumulative realized PnL series at exact exit timestamps
            ts_sorted = sorted(pnl_by_ts.keys())
            cum = 0.0
            exit_curve: dict[pd.Timestamp, float] = {start_ts: initial_capital}
            for ts in ts_sorted:
                cum += pnl_by_ts[ts]
                ts_norm = pd.Timestamp(ts)
                if ts_norm.tzinfo is None:
                    ts_norm = ts_norm.tz_localize("UTC")
                exit_curve[ts_norm] = initial_capital + cum
            exit_series = pd.Series(dict(sorted(exit_curve.items())))
            # Reindex to full daily timeline, forward-fill (equity stays flat between exits)
            equity_curve = exit_series.reindex(full_index, method="ffill")
            # Backfill the head (before first trade) with initial_capital
            equity_curve = equity_curve.fillna(initial_capital)
        else:
            equity_curve = pd.Series(initial_capital, index=full_index)

        trades_df = pd.DataFrame(all_trades)
        trade_pnls = trades_df["realized_pnl_usdt"] if not trades_df.empty else pd.Series(dtype=float)

        from price_action.backtest.metrics import compute_kpis

        kpis = compute_kpis(equity_curve, trade_pnls, timeframe=timeframe, n_trials=1)

        # Lookahead test bayrağı (oracle baseline)
        oracle_eq = self._oracle_baseline_universe(universe, loader, start, end, timeframe)
        if oracle_eq is not None and len(oracle_eq) > 1 and len(equity_curve) > 1:
            our_total = equity_curve.iloc[-1] / equity_curve.iloc[0] - 1.0
            oracle_total = oracle_eq.iloc[-1] / oracle_eq.iloc[0] - 1.0
            kpis["oracle_baseline_return"] = oracle_total
            kpis["oracle_efficiency"] = (
                our_total / oracle_total if oracle_total > 0 else 0.0
            )
            # Bayrak: oracle %200'ün altındaysa lookahead riski; üstündeyse normal
            if oracle_total < 1.0:
                logger.bind(oracle=oracle_total).warning("oracle_baseline_low_alarm")

        manifest = self._build_manifest(strategy, universe, start, end, fees, slippage_bps)
        elapsed = time.perf_counter() - t0
        self._log.bind(
            strategy=strategy.name, n_trades=len(all_trades), elapsed=elapsed
        ).info("backtest.run.done")

        return BacktestResult(
            strategy_name=strategy.name,
            timeframe=timeframe,
            start=start,
            end=end,
            initial_capital=initial_capital,
            fees=fees,
            slippage_bps=slippage_bps,
            symbol_slippage_map=symbol_slippage_map,
            universe=universe,
            n_trades=len(all_trades),
            kpis=kpis,
            equity_curve=equity_curve,
            trades=trades_df,
            manifest=manifest,
            elapsed_sec=elapsed,
        )

    # ----- per-symbol sim -----
    def _simulate_symbol(
        self,
        *,
        df: pd.DataFrame,
        signals: list[Signal],
        strategy_id: str,
        slippage_bps: float,
        fees: dict[str, float],
        initial_capital: float,
        pnl_accumulator: dict[pd.Timestamp, float],
    ) -> list[dict[str, Any]]:
        """Single-symbol bar-by-bar simulator.

        Risk Officer çağrılır → quantity hesabı yapılır. Pozisyon SL/TP/end ile kapanır.
        """
        if df.empty or not signals:
            return []
        # ts -> i hızlı lookup
        idx_by_ts: dict[pd.Timestamp, int] = {pd.Timestamp(t): i for i, t in enumerate(df["ts"])}
        signals_sorted = sorted(signals, key=lambda s: s.ts)

        trades: list[dict[str, Any]] = []
        in_position = False  # tek pozisyon — basitlik için
        entry_idx = 0
        entry_price = 0.0
        side = "long"
        sl_price = 0.0
        tp_price = 0.0
        qty = 0.0
        entry_ts: pd.Timestamp = pd.Timestamp(0)
        confluence = 0.0
        pattern_id = ""
        seen_fps: set[str] = set()

        equity = initial_capital
        for sig in signals_sorted:
            fp = sig.fingerprint()
            if fp in seen_fps:
                continue
            seen_fps.add(fp)
            ts = pd.Timestamp(sig.ts)
            i = idx_by_ts.get(ts)
            if i is None or i + 1 >= len(df):
                continue
            if in_position:
                # Mevcut pozisyon kapanmadan yeni emir alma
                continue

            # Bir sonraki bar açılışında giriş
            entry_bar_i = i + 1
            entry_bar = df.iloc[entry_bar_i]
            entry_price = float(entry_bar["open"])
            # slippage uygula
            slip = slippage_bps / 10_000.0
            if sig.direction == "long":
                entry_price *= 1 + slip
            else:
                entry_price *= 1 - slip

            # Risk Officer
            if self.risk_officer is None:
                # No-RO fallback: sabit sermaye yüzdesi
                risk_dollar = equity * 0.01
                sl_dist = abs(entry_price - sig.sl_price)
                if sl_dist <= 0:
                    continue
                qty = risk_dollar / sl_dist
                sl_price = sig.sl_price
            else:
                acct = AccountState(equity_usdt=equity, free_margin_usdt=equity)
                ro_result = self.risk_officer.evaluate(
                    sig,
                    acct,
                    market_price=entry_price,
                    atr=float(sig.metadata.get("atr14", 0)) if sig.metadata else None,
                )
                # Reject ise atla
                if not hasattr(ro_result, "quantity"):
                    continue
                qty = float(ro_result.quantity)  # type: ignore[union-attr]
                sl_price = float(ro_result.sl_price)  # type: ignore[union-attr]
            if qty <= 0:
                continue

            tp_price = float(sig.tp_price)
            side = sig.direction
            entry_idx = entry_bar_i
            entry_ts = pd.Timestamp(entry_bar["ts"])
            confluence = sig.confluence_score
            pattern_id = sig.pattern_id
            in_position = True

            # Forward path: SL/TP ilk hangisi gelirse o
            exit_idx = entry_idx
            exit_price = entry_price
            mae = 0.0
            mfe = 0.0
            for j in range(entry_idx, len(df)):
                bar = df.iloc[j]
                hi = float(bar["high"])
                lo = float(bar["low"])
                if side == "long":
                    excursion_low = (lo - entry_price) / entry_price
                    excursion_high = (hi - entry_price) / entry_price
                    mae = min(mae, excursion_low)
                    mfe = max(mfe, excursion_high)
                    if lo <= sl_price:
                        exit_idx = j
                        exit_price = sl_price * (1 - slip)
                        break
                    if hi >= tp_price:
                        exit_idx = j
                        exit_price = tp_price * (1 - slip)
                        break
                else:
                    excursion_high = (hi - entry_price) / entry_price
                    excursion_low = (lo - entry_price) / entry_price
                    mae = max(mae, excursion_high)
                    mfe = min(mfe, excursion_low)
                    if hi >= sl_price:
                        exit_idx = j
                        exit_price = sl_price * (1 + slip)
                        break
                    if lo <= tp_price:
                        exit_idx = j
                        exit_price = tp_price * (1 + slip)
                        break
            else:
                # Backtest sonuna kadar açık kaldı; close ile kapat
                exit_idx = len(df) - 1
                exit_price = float(df.iloc[-1]["close"])

            exit_ts = pd.Timestamp(df.iloc[exit_idx]["ts"])

            # PnL
            if side == "long":
                pnl_per_unit = exit_price - entry_price
            else:
                pnl_per_unit = entry_price - exit_price
            gross = pnl_per_unit * qty
            fee_total = (entry_price + exit_price) * qty * fees.get("taker", 0.00075)
            net = gross - fee_total

            # R-multiple
            initial_risk = abs(entry_price - sl_price) * qty
            r_multiple = net / initial_risk if initial_risk > 0 else 0.0

            trade_id = stable_hash((strategy_id, sig.symbol, sig.ts.isoformat(), entry_price))
            tr = TradeRecord(
                trade_id=trade_id,
                venue=sig.venue,
                symbol=sig.symbol,
                side=side,  # type: ignore[arg-type]
                entry_ts=entry_ts.to_pydatetime() if hasattr(entry_ts, "to_pydatetime") else datetime.now(timezone.utc),
                exit_ts=exit_ts.to_pydatetime() if hasattr(exit_ts, "to_pydatetime") else datetime.now(timezone.utc),
                entry_price=entry_price,
                exit_price=exit_price,
                quantity=qty,
                realized_pnl_usdt=net,
                realized_r_multiple=r_multiple,
                fees_usdt=fee_total,
                slippage_bps=slippage_bps,
                strategy_id=strategy_id,
                pattern_id=pattern_id,
                confluence_score=confluence,
                initial_sl=sl_price,
                initial_tp=tp_price,
                mae_pct=float(mae),
                mfe_pct=float(mfe),
                manifest_hash=sig.manifest_hash,
            )
            trades.append(tr.model_dump())
            equity += net
            pnl_accumulator[exit_ts] = pnl_accumulator.get(exit_ts, 0.0) + net
            in_position = False

        return trades

    # ----- oracle baseline -----
    @staticmethod
    def oracle_baseline(df: pd.DataFrame) -> pd.Series:
        """Mükemmel öngörü: her bar'da yön bilen ideal strateji.

        Returns'lerin |close - close.shift(1)| toplamı; lookahead testinin
        üst sınırı. Gerçek bir strateji bunun çok altında olmalı; üstüne
        çıkması = lookahead bug.
        """
        if df is None or df.empty:
            return pd.Series(dtype=float)
        rets = df["close"].pct_change().abs().fillna(0.0)
        eq = (1 + rets).cumprod()
        eq.index = df["ts"]
        return eq

    def _oracle_baseline_universe(
        self,
        universe: list[str],
        loader: Any,
        start: datetime,
        end: datetime,
        timeframe: str,
    ) -> pd.Series | None:
        """Tüm sembollerin oracle eq curve ortalaması."""
        accum: list[pd.Series] = []
        for sym in universe:
            try:
                df = loader(sym, timeframe, start, end)
            except Exception:
                continue
            if df is None or df.empty:
                continue
            eq = self.oracle_baseline(df)
            if not eq.empty:
                accum.append(eq)
        if not accum:
            return None
        merged = pd.concat(accum, axis=1).ffill().bfill()
        return merged.mean(axis=1)

    # ----- manifest -----
    @staticmethod
    def _build_manifest(
        strategy: Strategy,
        universe: list[str],
        start: datetime,
        end: datetime,
        fees: dict[str, float],
        slippage_bps: float,
    ) -> ReproducibilityManifest:
        config_hash = stable_hash(strategy.manifest.model_dump(mode="json"))
        data_hash = stable_hash(
            {"universe": sorted(universe), "start": start, "end": end}
        )
        code_hash = stable_hash(
            {"strategy": strategy.name, "version": strategy.version}
        )
        return ReproducibilityManifest(
            git_hash=_safe_git_hash(),
            config_hash=config_hash,
            data_hash=data_hash,
            code_hash=code_hash,
        )


# =====================================================================
# helpers
# =====================================================================

def _default_loader(symbol: str, tf: str, start: datetime, end: datetime) -> pd.DataFrame:
    """OHLCVStore default loader. Test ortamında DB yoksa boş döner."""
    try:
        from price_action.data.store import OHLCVStore
    except Exception:
        return pd.DataFrame()
    try:
        store = OHLCVStore()
        return store.read(symbol, tf, start=start, end=end)
    except Exception as exc:
        logger.bind(sym=symbol, err=str(exc)).warning("default_loader.fail")
        return pd.DataFrame()


def _safe_git_hash() -> str:
    try:
        import subprocess

        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        )
        return out.decode().strip()[:40]
    except Exception:
        return "no_git"


__all__ = ["BacktestEngine", "BacktestResult"]
