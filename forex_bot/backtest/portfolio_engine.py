"""Multi-pair portfolio backtest — single shared equity, chronological compounding.

Unlike BacktestEngine (single pair), this runs N pairs against ONE balance:
 - Signals from all pairs merged chronologically
 - Each fill/close updates the shared balance → compounding across pairs
 - max_open_positions enforced portfolio-wide
 - Per-trade leverage capped at target_leverage (each position uses ≤ 5x)
 - Total portfolio leverage = sum of open positions (can exceed 5x with multiple pairs)

This is the realistic way to compound a multi-pair forex book.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from ..contracts import Signal, TradeRecord, pip_value, price_to_pips
from ..backtest.costs import CostModel
from ..indicators.ohlc import atr
from ..risk.officer import AccountState, RiskedOrder, RiskOfficer, Reject
from ..session.tagger import tag_session


@dataclass
class PortfolioConfig:
    initial_balance_usd: float = 10_000.0
    runner_trail_atr_mult: float = 1.5
    tp1_close_pct: float = 0.30
    tp2_close_pct: float = 0.30
    move_sl_to_be_after_tp1: bool = True
    force_exit_bars: int = 32
    pyramid_enabled: bool = False
    pyramid_max_adds: int = 2
    pyramid_add_at_r: float = 1.0  # add when position +1R


@dataclass
class _Pos:
    trade_id: str
    pair: str
    side: str
    strategy: str
    session: str
    pattern: str
    entry_ts: datetime
    entry_price: float
    lots: float
    sl_price: float
    initial_sl: float
    tp_prices: list
    bars_held: int = 0
    stage: int = 0
    realized_partial: float = 0.0
    initial_risk_usd: float = 0.0
    pyramid_adds: int = 0
    trail_active: bool = False


@dataclass
class PortfolioResult:
    pairs: list
    start: pd.Timestamp
    end: pd.Timestamp
    initial_balance: float
    final_balance: float
    n_trades: int
    equity_curve: pd.Series
    trades: pd.DataFrame
    kpis: dict


class PortfolioEngine:
    def __init__(self, risk_officer: RiskOfficer, cost_model: CostModel,
                 config: Optional[PortfolioConfig] = None, news_guard=None):
        self.risk = risk_officer
        self.costs = cost_model
        self.cfg = config or PortfolioConfig()
        self.news = news_guard

    def run(self, dfs: dict[str, pd.DataFrame], signals_by_pair: dict[str, list[Signal]]) -> PortfolioResult:
        # Prepare per-pair bar frames with ATR
        bars = {}
        for pair, df in dfs.items():
            d = df.copy()
            if "atr14" not in d.columns:
                d["atr14"] = atr(d, 14)
            bars[pair] = d

        # Build a unified chronological timeline (union of all pair indices)
        all_ts = sorted(set().union(*[set(d.index) for d in bars.values()]))

        # signal lookup: (pair, ts) -> list[Signal]
        sig_lookup: dict = {}
        for pair, sigs in signals_by_pair.items():
            for s in sigs:
                sig_lookup.setdefault((pair, pd.Timestamp(s.ts)), []).append(s)

        balance = self.cfg.initial_balance_usd
        open_pos: dict[str, _Pos] = {}  # keyed by pair (one position per pair)
        completed: list[TradeRecord] = []
        equity_hist: list = []

        from collections import defaultdict
        daily_pnl = defaultdict(float)
        weekly_pnl = defaultdict(float)
        monthly_pnl = defaultdict(float)
        consec_losses = 0

        from ..risk.breaker import BreakerState
        self.risk.breaker.state = BreakerState()

        prev_ts_idx = {pair: None for pair in bars}

        for ti, ts in enumerate(all_ts):
            day_k = ts.strftime("%Y-%m-%d")
            week_k = ts.strftime("%Y-W%U")
            month_k = ts.strftime("%Y-%m")

            # 1) Process open positions on bars that exist at this ts
            for pair in list(open_pos.keys()):
                if ts not in bars[pair].index:
                    continue
                row = bars[pair].loc[ts]
                pos = open_pos[pair]
                result = self._step(pos, row, ts)
                if result is not None:
                    rec, pnl = result
                    balance += pnl
                    daily_pnl[day_k] += pnl
                    weekly_pnl[week_k] += pnl
                    monthly_pnl[month_k] += pnl
                    consec_losses = consec_losses + 1 if pnl < 0 else 0
                    completed.append(rec)
                    del open_pos[pair]

            # 2) New entries — signals at previous bar of each pair
            for pair in bars:
                if ts not in bars[pair].index:
                    continue
                pidx = bars[pair].index
                pos_i = pidx.get_loc(ts)
                if pos_i == 0:
                    continue
                prev_ts = pidx[pos_i - 1]
                cands = sig_lookup.get((pair, prev_ts), [])
                if not cands or pair in open_pos:
                    continue
                row = bars[pair].loc[ts]
                for sig in cands:
                    if self.news is not None:
                        blk, _ = self.news.is_blackout(ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts, pair)
                        if blk:
                            continue
                    account = AccountState(
                        equity_usd=balance, free_margin_usd=balance,
                        open_positions={p: {"side": o.side, "lots": o.lots,
                                            "notional": o.lots * 100_000.0}
                                        for p, o in open_pos.items()},
                        daily_pnl=daily_pnl[day_k], weekly_pnl=weekly_pnl[week_k],
                        monthly_pnl=monthly_pnl[month_k], consecutive_losses=consec_losses,
                        mode="backtest",
                    )
                    now_dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
                    decision = self.risk.evaluate(sig, account, now_dt)
                    if not isinstance(decision, RiskedOrder):
                        continue
                    entry = float(row["open"])
                    cost, spr = self.costs.total_entry_cost_usd(pair, decision.lots, now_dt)
                    balance -= cost
                    open_pos[pair] = _Pos(
                        trade_id=str(uuid.uuid4())[:8], pair=pair, side=sig.side,
                        strategy=sig.strategy, session=tag_session(now_dt), pattern=sig.pattern,
                        entry_ts=now_dt, entry_price=entry, lots=decision.lots,
                        sl_price=decision.sl_price, initial_sl=decision.sl_price,
                        tp_prices=list(decision.tp_prices),
                        initial_risk_usd=decision.risk_usd,
                    )
                    break

            equity_hist.append((ts, balance))

        # close residual
        for pair, pos in list(open_pos.items()):
            last_ts = bars[pair].index[-1]
            last_close = float(bars[pair].loc[last_ts]["close"])
            rec, pnl = self._close(pos, last_ts, last_close, "eof")
            balance += pnl
            completed.append(rec)

        eq = pd.Series({t: v for t, v in equity_hist}, name="equity")
        tr_df = pd.DataFrame([t.__dict__ for t in completed])
        kpis = self._kpis(eq, tr_df, self.cfg.initial_balance_usd, balance)
        return PortfolioResult(
            pairs=list(bars.keys()),
            start=pd.Timestamp(all_ts[0]), end=pd.Timestamp(all_ts[-1]),
            initial_balance=self.cfg.initial_balance_usd, final_balance=balance,
            n_trades=len(completed), equity_curve=eq, trades=tr_df, kpis=kpis,
        )

    def _step(self, pos: _Pos, row, ts):
        pos.bars_held += 1
        h, l, c = float(row["high"]), float(row["low"]), float(row["close"])
        if pos.side == "long":
            if l <= pos.sl_price:
                return self._close(pos, ts, pos.sl_price, "sl", stopped=True)
            tp_hits = [i for i, tp in enumerate(pos.tp_prices) if h >= tp]
        else:
            if h >= pos.sl_price:
                return self._close(pos, ts, pos.sl_price, "sl", stopped=True)
            tp_hits = [i for i, tp in enumerate(pos.tp_prices) if l <= tp]

        if pos.stage == 0 and len(tp_hits) >= 1:
            partial = pos.lots * self.cfg.tp1_close_pct
            pos.realized_partial += self._partial_pnl(pos, ts, pos.tp_prices[0], partial)
            pos.lots -= partial
            pos.stage = 1
            if self.cfg.move_sl_to_be_after_tp1:
                pos.sl_price = pos.entry_price
        if pos.stage == 1 and len(tp_hits) >= 2:
            partial = pos.lots * self.cfg.tp2_close_pct / (1 - self.cfg.tp1_close_pct)
            pos.realized_partial += self._partial_pnl(pos, ts, pos.tp_prices[1], partial)
            pos.lots -= partial
            pos.stage = 2
            pos.trail_active = True

        if pos.trail_active and pd.notna(row.get("atr14")):
            a = float(row["atr14"])
            off = self.cfg.runner_trail_atr_mult * a
            if pos.side == "long":
                pos.sl_price = max(pos.sl_price, c - off)
            else:
                pos.sl_price = min(pos.sl_price, c + off)

        if pos.bars_held >= self.cfg.force_exit_bars and pos.stage < 2:
            return self._close(pos, ts, c, "time")
        return None

    def _partial_pnl(self, pos, ts, exit_price, lots):
        ts_dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        cost, _ = self.costs.total_exit_cost_usd(pos.pair, lots, ts_dt)
        pv = pip_value(pos.pair, lots=lots)
        move = price_to_pips(pos.pair, exit_price - pos.entry_price)
        sign = 1 if pos.side == "long" else -1
        return sign * move * pv - cost

    def _close(self, pos, ts, exit_price, reason, stopped=False):
        ts_dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        cost, _ = self.costs.total_exit_cost_usd(pos.pair, pos.lots, ts_dt, stopped_out=stopped)
        pv = pip_value(pos.pair, lots=pos.lots)
        move = price_to_pips(pos.pair, exit_price - pos.entry_price)
        sign = 1 if pos.side == "long" else -1
        final = sign * move * pv - cost
        total = pos.realized_partial + final
        r_mult = total / max(1e-9, pos.initial_risk_usd) if pos.initial_risk_usd else 0.0
        dur = int((ts_dt - pos.entry_ts).total_seconds() // 60)
        rec = TradeRecord(
            trade_id=pos.trade_id, pair=pos.pair, side=pos.side, strategy=pos.strategy,
            session=pos.session, pattern=pos.pattern, entry_ts=pos.entry_ts, exit_ts=ts_dt,
            entry_price=pos.entry_price, exit_price=exit_price, lots=pos.lots,
            sl_price=pos.initial_sl, realized_usd=total, realized_r=r_mult,
            win=total > 0, close_reason=reason, spread_paid_pips=0.0,
            commission_usd=0.0, swap_usd=0.0, slippage_pips=0.0, duration_min=dur,
        )
        return rec, total

    def _kpis(self, eq, trades, init, final):
        if eq.empty:
            return {}
        days = max(1, (eq.index[-1] - eq.index[0]).total_seconds() / 86400)
        years = days / 365.25
        cagr = (final / init) ** (1 / max(0.01, years)) - 1 if final > 0 else -1.0
        rets = eq.pct_change().dropna()
        sharpe = (rets.mean() / rets.std()) * np.sqrt(96 * 252) if rets.std() > 0 else 0.0
        peak = eq.cummax()
        dd = (eq - peak) / peak.replace(0, np.nan)
        maxdd = float(dd.min()) if not dd.empty else 0.0
        n = len(trades)
        wins = int(trades["win"].sum()) if n else 0
        if n:
            gw = float(trades.loc[trades["win"], "realized_usd"].sum())
            gl = abs(float(trades.loc[~trades["win"], "realized_usd"].sum()))
            pf = gw / max(1e-9, gl)
        else:
            pf = 0.0
        monthly = ((final / init) ** (1 / max(0.01, years * 12)) - 1) if final > 0 else -1.0
        return {
            "return_total_pct": (final / init - 1) * 100,
            "cagr_pct": cagr * 100, "monthly_pct": monthly * 100,
            "sharpe": sharpe, "max_dd_pct": maxdd * 100,
            "n_trades": n, "win_rate": wins / max(1, n), "profit_factor": pf,
        }
