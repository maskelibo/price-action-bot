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
        runner_trail_mult: float = 1.5,   # v1.5 sec13.4 WIN: 1.0 -> 1.5 (artifact-free w/ time-exit)
        trail_activate_stage: int = 2,
        tp1_R: float = 1.0,
        tp2_R: float = 1.5,                # v1.2 sec11b WIN: 2.0 -> 1.5
        tp1_close_pct: float = 0.30,
        tp2_close_pct: float = 0.30,
        runner_force_exit_method: str = "time",  # v1.5 sec13.4 WIN: artifact prevention
        runner_force_exit_bars: int | None = 30,  # v1.5 sec13.4 WIN: 30bar force exit
        runner_force_exit_ema: int = 20,
        force_exit_from_entry: bool = False,  # SEC21: pre-trail-stage force-exit
    ) -> None:
        """`store_load` = lazy callable: (symbol, tf, start, end) -> DataFrame.

        `runner_trail_mult`: ATR multiplier for runner trailing stop.
            Default 1.0 = production v1.0 (effective trail = peak - 1.0*ATR).
            Higher = looser trail (let winners run more), lower = tighter trail.
        `trail_activate_stage`: stage threshold for trail engagement (sec11a grid).
            2 (default) = trail starts AFTER TP2 (2R) hit (production behavior).
            1 = trail starts AFTER TP1 (1R) hit (earlier trail).
            0 = trail from entry (NOT recommended, breaks initial SL semantics).
        `tp1_R` / `tp2_R`: R-multiple distances for partial close targets.
            Defaults 1.0 / 2.0 = production v1.0 (1R partial + 2R partial + runner).
            sec11b grid: tp1_R in {0.5, 1.0, 1.5}, tp2_R in {1.5, 2.0, 2.5, 3.0}.
        `tp1_close_pct` / `tp2_close_pct`: fraction of original qty closed at TP1/TP2.
            Defaults 0.30 / 0.30 = production v1.0 (30% / 30% / 40% runner).
            Runner fraction = 1 - tp1_close_pct - tp2_close_pct.
        `runner_force_exit_method`: extra runner exit guard (sec13.4 artifact prevention).
            "atr_only" (default) = sadece ATR trail, mevcut davranis.
            "time" = trail aktive olduktan sonra `runner_force_exit_bars` bar sonra force-exit (close).
            "ema_cross" = runner aktif iken EMA(`runner_force_exit_ema`) cross karsi yon -> exit.
            "combined" = time AND ema_cross — ikisi de tetiklenince exit (en gevsek).
            "either" = time OR ema_cross — biri tetiklenince exit (en siki).
        `runner_force_exit_bars`: time-based exit icin bar sayisi (None = devre disi).
            Sadece method in {"time", "combined", "either"} ile anlamli.
        `runner_force_exit_ema`: EMA cross icin period (default 20).
        `force_exit_from_entry`: SEC21 — force-exit clock'u entry bar'dan baslat
            (trail_activate_stage'i beklemeden). Default False = backward compat
            (mevcut davranis: force-exit yalnizca stage >= trail_activate_stage iken).
            True olunca:
              - "time": entry+N bar sonra hala acik trade -> close
              - "ema_cross": EMA cross karsi yon -> close (entry'den itibaren takip)
              - "combined"/"either": ikisi de entry'den baslatilir
            Stage<trail_activate_stage trade'leri (TP1'e bile ulasamayanlar) icin
            time-based "stuck trade" guard saglar. No-lookahead: t bar karari
            t-1 close bilgisiyle alinir (EMA causal, time t-entry_bar arithmetic).
        """
        self.risk_officer = risk_officer
        self.store_load = store_load
        self.runner_trail_mult = float(runner_trail_mult)
        self.trail_activate_stage = int(trail_activate_stage)
        self.tp1_R = float(tp1_R)
        self.tp2_R = float(tp2_R)
        self.tp1_close_pct = float(tp1_close_pct)
        self.tp2_close_pct = float(tp2_close_pct)
        self.runner_force_exit_method = str(runner_force_exit_method)
        self.runner_force_exit_bars = (
            int(runner_force_exit_bars) if runner_force_exit_bars is not None else None
        )
        self.runner_force_exit_ema = int(runner_force_exit_ema)
        self.force_exit_from_entry = bool(force_exit_from_entry)
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

        # Force-exit precompute: EMA series for runner exit (sec13.4)
        _force_exit_active = (
            self.runner_force_exit_method != "atr_only"
            and (
                self.runner_force_exit_bars is not None
                or self.runner_force_exit_method in ("ema_cross", "combined", "either")
            )
        )
        ema_close_arr: np.ndarray | None = None
        if _force_exit_active and "close" in df.columns:
            try:
                ema_period = max(2, int(self.runner_force_exit_ema))
                ema_close_arr = (
                    df["close"]
                    .ewm(span=ema_period, adjust=False, min_periods=ema_period)
                    .mean()
                    .to_numpy()
                )
            except Exception:
                ema_close_arr = None

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

            # Forward path: MULTI-TARGET TP — partial close at 1R/2R + RUNNER TRAIL
            # v0.8: %30 close at 1R + break-even SL
            #       %30 close at 2R + lock SL at +1R
            #       %40 runner with peak-1.5*ATR trail (NO TP3 hard cap)
            exit_idx = entry_idx
            exit_price = entry_price
            mae = 0.0
            mfe = 0.0
            initial_R_dist = abs(entry_price - sl_price)
            atr_for_trail = float(sig.metadata.get("atr14", 0)) if sig.metadata else 0.0
            if atr_for_trail <= 0:
                atr_for_trail = initial_R_dist * 0.5
            # sec11b: TP1/TP2 R-multiples ve partial close fractions parametrize
            tp1_R = self.tp1_R
            tp2_R = self.tp2_R
            tp1_close_pct = self.tp1_close_pct
            tp2_close_pct = self.tp2_close_pct
            tp1_price = entry_price + tp1_R * initial_R_dist if side == "long" else entry_price - tp1_R * initial_R_dist
            tp2_price = entry_price + tp2_R * initial_R_dist if side == "long" else entry_price - tp2_R * initial_R_dist

            qty1 = qty * tp1_close_pct  # TP1 partial
            qty2 = qty * tp2_close_pct  # TP2 partial
            qty_runner = qty - qty1 - qty2  # runner

            partial_pnls: list[tuple[int, float, float]] = []
            stage = 0  # 0=full open, 1=after TP1, 2=after TP2 (runner only)
            current_sl = sl_price
            peak = entry_price  # MFE tracking (high for long, low for short)
            trail_active_bar: int | None = None  # sec13.4 force-exit clock
            # SEC21: force_exit_from_entry -> clock starts at entry bar
            # so stage<trail_activate_stage trade'leri (stuck at TP0/TP1) bile
            # time-based exit'e tabi. Causal: t-bar karari t-entry_idx arithmetic.
            if self.force_exit_from_entry and _force_exit_active:
                trail_active_bar = entry_idx

            for j in range(entry_idx, len(df)):
                bar = df.iloc[j]
                hi = float(bar["high"])
                lo = float(bar["low"])
                close_j = float(bar["close"])
                if side == "long":
                    mae = min(mae, (lo - entry_price) / entry_price)
                    mfe = max(mfe, (hi - entry_price) / entry_price)
                    peak = max(peak, hi)
                    if lo <= current_sl:
                        remaining = qty - qty1 * (1 if stage >= 1 else 0) - qty2 * (1 if stage >= 2 else 0)
                        partial_pnls.append((j, remaining, current_sl * (1 - slip)))
                        exit_idx = j
                        break
                    if stage == 0 and hi >= tp1_price:
                        partial_pnls.append((j, qty1, tp1_price * (1 - slip)))
                        stage = 1
                    if stage >= 1 and hi >= tp2_price:
                        partial_pnls.append((j, qty2, tp2_price * (1 - slip)))
                        stage = 2
                    # Bar kapanisi sonrasi SL update (next bar'da etkili)
                    if stage >= 1:
                        current_sl = max(current_sl, entry_price)  # break-even
                    # SEC21 PRE-TRAIL FORCE-EXIT: stage<trail_activate_stage iken
                    # de time/ema-based exit calistir (stuck trade guard).
                    # Sadece force_exit_from_entry=True ise aktif.
                    if (
                        self.force_exit_from_entry
                        and _force_exit_active
                        and stage < self.trail_activate_stage
                    ):
                        time_hit_pre = (
                            self.runner_force_exit_bars is not None
                            and trail_active_bar is not None
                            and (j - trail_active_bar) >= self.runner_force_exit_bars
                        )
                        ema_hit_pre = False
                        if ema_close_arr is not None and not np.isnan(ema_close_arr[j]):
                            ema_hit_pre = close_j < float(ema_close_arr[j])
                        method_pre = self.runner_force_exit_method
                        should_exit_pre = False
                        if method_pre == "time":
                            should_exit_pre = time_hit_pre
                        elif method_pre == "ema_cross":
                            should_exit_pre = ema_hit_pre
                        elif method_pre == "combined":
                            should_exit_pre = time_hit_pre and ema_hit_pre
                        elif method_pre == "either":
                            should_exit_pre = time_hit_pre or ema_hit_pre
                        if should_exit_pre:
                            remaining = qty - qty1 * (1 if stage >= 1 else 0) - qty2 * (1 if stage >= 2 else 0)
                            if remaining > 0:
                                partial_pnls.append((j, remaining, close_j * (1 - slip)))
                            exit_idx = j
                            break
                    if stage >= self.trail_activate_stage:
                        # Trail: max(+1R, peak - mult*ATR) — runner kar lock + trail
                        trail_sl = peak - self.runner_trail_mult * atr_for_trail
                        current_sl = max(current_sl, tp1_price, trail_sl)
                        # sec13.4: runner force-exit (artifact prevention)
                        if _force_exit_active:
                            if trail_active_bar is None:
                                trail_active_bar = j
                            time_hit = (
                                self.runner_force_exit_bars is not None
                                and (j - trail_active_bar) >= self.runner_force_exit_bars
                            )
                            ema_hit = False
                            if ema_close_arr is not None and not np.isnan(ema_close_arr[j]):
                                ema_hit = close_j < float(ema_close_arr[j])
                            method = self.runner_force_exit_method
                            should_exit = False
                            if method == "time":
                                should_exit = time_hit
                            elif method == "ema_cross":
                                should_exit = ema_hit
                            elif method == "combined":
                                should_exit = time_hit and ema_hit
                            elif method == "either":
                                should_exit = time_hit or ema_hit
                            if should_exit:
                                remaining = qty - qty1 * (1 if stage >= 1 else 0) - qty2 * (1 if stage >= 2 else 0)
                                if remaining > 0:
                                    partial_pnls.append((j, remaining, close_j * (1 - slip)))
                                exit_idx = j
                                break
                else:
                    mae = max(mae, (hi - entry_price) / entry_price)
                    mfe = min(mfe, (lo - entry_price) / entry_price)
                    peak = min(peak, lo)
                    if hi >= current_sl:
                        remaining = qty - qty1 * (1 if stage >= 1 else 0) - qty2 * (1 if stage >= 2 else 0)
                        partial_pnls.append((j, remaining, current_sl * (1 + slip)))
                        exit_idx = j
                        break
                    if stage == 0 and lo <= tp1_price:
                        partial_pnls.append((j, qty1, tp1_price * (1 + slip)))
                        stage = 1
                    if stage >= 1 and lo <= tp2_price:
                        partial_pnls.append((j, qty2, tp2_price * (1 + slip)))
                        stage = 2
                    if stage >= 1:
                        current_sl = min(current_sl, entry_price)
                    # SEC21 PRE-TRAIL FORCE-EXIT (short side mirror)
                    if (
                        self.force_exit_from_entry
                        and _force_exit_active
                        and stage < self.trail_activate_stage
                    ):
                        time_hit_pre = (
                            self.runner_force_exit_bars is not None
                            and trail_active_bar is not None
                            and (j - trail_active_bar) >= self.runner_force_exit_bars
                        )
                        ema_hit_pre = False
                        if ema_close_arr is not None and not np.isnan(ema_close_arr[j]):
                            ema_hit_pre = close_j > float(ema_close_arr[j])
                        method_pre = self.runner_force_exit_method
                        should_exit_pre = False
                        if method_pre == "time":
                            should_exit_pre = time_hit_pre
                        elif method_pre == "ema_cross":
                            should_exit_pre = ema_hit_pre
                        elif method_pre == "combined":
                            should_exit_pre = time_hit_pre and ema_hit_pre
                        elif method_pre == "either":
                            should_exit_pre = time_hit_pre or ema_hit_pre
                        if should_exit_pre:
                            remaining = qty - qty1 * (1 if stage >= 1 else 0) - qty2 * (1 if stage >= 2 else 0)
                            if remaining > 0:
                                partial_pnls.append((j, remaining, close_j * (1 + slip)))
                            exit_idx = j
                            break
                    if stage >= self.trail_activate_stage:
                        trail_sl = peak + self.runner_trail_mult * atr_for_trail
                        current_sl = min(current_sl, tp1_price, trail_sl)
                        if _force_exit_active:
                            if trail_active_bar is None:
                                trail_active_bar = j
                            time_hit = (
                                self.runner_force_exit_bars is not None
                                and (j - trail_active_bar) >= self.runner_force_exit_bars
                            )
                            ema_hit = False
                            if ema_close_arr is not None and not np.isnan(ema_close_arr[j]):
                                ema_hit = close_j > float(ema_close_arr[j])
                            method = self.runner_force_exit_method
                            should_exit = False
                            if method == "time":
                                should_exit = time_hit
                            elif method == "ema_cross":
                                should_exit = ema_hit
                            elif method == "combined":
                                should_exit = time_hit and ema_hit
                            elif method == "either":
                                should_exit = time_hit or ema_hit
                            if should_exit:
                                remaining = qty - qty1 * (1 if stage >= 1 else 0) - qty2 * (1 if stage >= 2 else 0)
                                if remaining > 0:
                                    partial_pnls.append((j, remaining, close_j * (1 + slip)))
                                exit_idx = j
                                break
            else:
                exit_idx = len(df) - 1
                final_close = float(df.iloc[-1]["close"])
                remaining = qty - qty1 * (1 if stage >= 1 else 0) - qty2 * (1 if stage >= 2 else 0)
                partial_pnls.append((exit_idx, remaining, final_close))

            # Aggregate partials
            exit_ts = pd.Timestamp(df.iloc[exit_idx]["ts"])
            gross = 0.0
            fee_total = 0.0
            total_qty_closed = 0.0
            weighted_exit_sum = 0.0
            for _, q, ep in partial_pnls:
                if side == "long":
                    pnl_unit = ep - entry_price
                else:
                    pnl_unit = entry_price - ep
                gross += pnl_unit * q
                fee_total += (entry_price + ep) * q * fees.get("taker", 0.00075)
                total_qty_closed += q
                weighted_exit_sum += ep * q
            exit_price = weighted_exit_sum / total_qty_closed if total_qty_closed > 0 else entry_price
            net = gross - fee_total
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
