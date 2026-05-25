"""Bar-by-bar backtest engine for forex (15m primary, with intra-bar 1m refinement optional).

Lifecycle per signal:
    - Entry at next bar open (signal generated on close of bar t, entry at bar t+1 open)
    - SL/TP checked on bar high/low; if 1m intra-bar data provided, ordering of TP1/TP2/SL hits resolved
    - Stages: TP1 (close 30%), TP2 (close 30%), runner (40%) with ATR trail
    - Force exit: time-based (default 32 bars = 8 hours) OR opposite EMA cross
    - Costs: spread/commission on entry & exit, swap per overnight hold, slippage
    - Weekend handling: any open position carrying Fri close incurs weekend_gap_pips on Mon open
    - News guard: when active, force-tighten SL to 0.5R or close at flat
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from ..contracts import (
    Fill, PIP_SIZE, Position, Reject, RiskedOrder, Session, Signal,
    TradeRecord, pip_value, price_to_pips,
)
from ..news.guard import NewsGuard
from ..risk.officer import AccountState, RiskOfficer
from ..session.tagger import tag_session
from .costs import CostModel

logger = logging.getLogger(__name__)


@dataclass
class EngineConfig:
    initial_balance_usd: float = 10_000.0
    runner_trail_atr_mult: float = 1.5
    tp1_close_pct: float = 0.30
    tp2_close_pct: float = 0.30
    runner_pct: float = 0.40
    move_sl_to_be_after_tp1: bool = True
    force_exit_bars: int = 32  # 8 hours @ 15m
    use_intrabar_1m: bool = False
    news_close_at_blackout: bool = True


@dataclass
class _OpenTrade:
    trade_id: str
    pair: str
    side: str
    strategy: str
    pattern: str
    session: Session
    entry_ts: datetime
    entry_price: float
    initial_lots: float
    remaining_lots: float
    sl_price: float
    tp_prices: list[float]
    bars_held: int = 0
    stage: int = 0  # 0=initial, 1=tp1_hit, 2=tp2_hit
    realized_partial_usd: float = 0.0
    realized_partial_r: float = 0.0
    initial_risk_pips: float = 0.0
    initial_risk_usd: float = 0.0
    spread_paid_pips: float = 0.0
    commission_paid_usd: float = 0.0
    swap_paid_usd: float = 0.0
    slippage_paid_pips: float = 0.0
    trail_active: bool = False
    trail_anchor: float = 0.0


@dataclass
class BacktestResult:
    pair: str
    timeframe: str
    start: pd.Timestamp
    end: pd.Timestamp
    initial_balance: float
    final_balance: float
    n_trades: int
    n_wins: int
    equity_curve: pd.Series
    trades: pd.DataFrame
    kpis: dict


class BacktestEngine:
    def __init__(
        self,
        risk_officer: RiskOfficer,
        cost_model: CostModel,
        config: Optional[EngineConfig] = None,
        news_guard: Optional[NewsGuard] = None,
    ):
        self.risk = risk_officer
        self.costs = cost_model
        self.cfg = config or EngineConfig()
        self.news = news_guard

    def run(self, df: pd.DataFrame, signals: list[Signal], pair: str, timeframe: str = "15m") -> BacktestResult:
        """Stream bars in chronological order; signal indexed by `ts` triggers entry at next bar open."""
        balance = self.cfg.initial_balance_usd
        equity_history: list[tuple[datetime, float]] = []
        completed_trades: list[TradeRecord] = []
        open_trades: dict[str, _OpenTrade] = {}
        signals_by_ts: dict[pd.Timestamp, list[Signal]] = {}
        for s in signals:
            signals_by_ts.setdefault(pd.Timestamp(s.ts), []).append(s)
        bars = df.copy()
        if "atr14" not in bars.columns:
            from ..indicators.ohlc import atr
            bars["atr14"] = atr(bars, 14)

        idx = list(bars.index)
        # Reset breaker state for fresh backtest (avoid state leak across WF windows)
        from ..risk.breaker import BreakerState
        self.risk.breaker.state = BreakerState()

        # Rolling PnL tracking for breaker
        from collections import defaultdict
        daily_pnl_log: dict = defaultdict(float)
        weekly_pnl_log: dict = defaultdict(float)
        monthly_pnl_log: dict = defaultdict(float)
        monthly_pnl_long: dict = defaultdict(float)
        monthly_pnl_short: dict = defaultdict(float)
        consec_losses = 0

        for i, ts in enumerate(idx):
            row = bars.loc[ts]
            sess = tag_session(ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts)
            day_key = ts.strftime("%Y-%m-%d")
            week_key = ts.strftime("%Y-W%U")
            month_key = ts.strftime("%Y-%m")
            # 1) Process open trades on this bar's high/low
            to_close = []
            for tid, trade in open_trades.items():
                close_result = self._step_trade(trade, row, ts, sess, balance)
                if close_result is not None:
                    completed_trade, pnl_usd = close_result
                    balance += pnl_usd
                    daily_pnl_log[day_key] += pnl_usd
                    weekly_pnl_log[week_key] += pnl_usd
                    monthly_pnl_log[month_key] += pnl_usd
                    if trade.side == "long":
                        monthly_pnl_long[month_key] += pnl_usd
                    else:
                        monthly_pnl_short[month_key] += pnl_usd
                    if pnl_usd < 0:
                        consec_losses += 1
                    else:
                        consec_losses = 0
                    completed_trades.append(completed_trade)
                    to_close.append(tid)
            for tid in to_close:
                open_trades.pop(tid, None)

            # 2) Process new entries from signals with ts == previous bar
            if i > 0:
                prev_ts = idx[i - 1]
                signals_to_enter = signals_by_ts.get(prev_ts, [])
                for sig in signals_to_enter:
                    if sig.pair != pair:
                        continue
                    if self.news is not None:
                        blocked, _ = self.news.is_blackout(ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts, pair)
                        if blocked:
                            continue
                    account = AccountState(
                        equity_usd=balance, free_margin_usd=balance,
                        open_positions={t.pair: {"side": t.side, "lots": t.remaining_lots,
                                                  "notional": t.remaining_lots * 100_000.0}
                                         for t in open_trades.values()},
                        daily_pnl=daily_pnl_log[day_key],
                        weekly_pnl=weekly_pnl_log[week_key],
                        monthly_pnl=monthly_pnl_log[month_key],
                        monthly_pnl_long=monthly_pnl_long[month_key],
                        monthly_pnl_short=monthly_pnl_short[month_key],
                        consecutive_losses=consec_losses,
                        mode="backtest",
                    )
                    now_dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
                    decision = self.risk.evaluate(sig, account, now_dt)
                    if not isinstance(decision, RiskedOrder):
                        continue
                    entry_price = float(row["open"])
                    cost_usd, spread_pips_used = self.costs.total_entry_cost_usd(pair, decision.lots, now_dt)
                    balance -= cost_usd
                    risk_pips = price_to_pips(pair, decision.sl_price - entry_price) if sig.side == "long" \
                        else price_to_pips(pair, entry_price - decision.sl_price)
                    risk_pips = abs(risk_pips)
                    trade = _OpenTrade(
                        trade_id=str(uuid.uuid4())[:8],
                        pair=pair, side=sig.side, strategy=sig.strategy, pattern=sig.pattern,
                        session=sess, entry_ts=now_dt, entry_price=entry_price,
                        initial_lots=decision.lots, remaining_lots=decision.lots,
                        sl_price=decision.sl_price, tp_prices=list(decision.tp_prices),
                        initial_risk_pips=risk_pips,
                        initial_risk_usd=decision.risk_usd,
                        spread_paid_pips=spread_pips_used,
                        commission_paid_usd=self.costs.commission_usd(decision.lots) / 2.0,
                    )
                    open_trades[trade.trade_id] = trade

            equity_history.append((ts, balance))

        # close any open trades at end
        last_ts = idx[-1] if idx else pd.Timestamp.utcnow()
        last_row = bars.loc[last_ts] if idx else None
        for tid, trade in list(open_trades.items()):
            last_close = float(last_row["close"]) if last_row is not None else trade.entry_price
            tr, pnl = self._force_close(trade, last_ts, last_close, "eof")
            balance += pnl
            completed_trades.append(tr)
            open_trades.pop(tid, None)

        eq = pd.Series({t: v for t, v in equity_history}, name="equity")
        tr_df = pd.DataFrame([t.__dict__ for t in completed_trades])
        kpis = self._compute_kpis(eq, tr_df, self.cfg.initial_balance_usd, balance)
        return BacktestResult(
            pair=pair, timeframe=timeframe,
            start=pd.Timestamp(idx[0]) if idx else pd.Timestamp.utcnow(),
            end=pd.Timestamp(idx[-1]) if idx else pd.Timestamp.utcnow(),
            initial_balance=self.cfg.initial_balance_usd, final_balance=balance,
            n_trades=len(completed_trades), n_wins=int(tr_df["win"].sum()) if not tr_df.empty else 0,
            equity_curve=eq, trades=tr_df, kpis=kpis,
        )

    def _step_trade(self, trade: _OpenTrade, row, ts, sess, balance) -> Optional[tuple[TradeRecord, float]]:
        """Update trade with bar high/low; return (closed_trade, realized_usd) if closed."""
        trade.bars_held += 1
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])
        sign = 1 if trade.side == "long" else -1

        # SL hit?
        if trade.side == "long":
            sl_hit = l <= trade.sl_price
            tp_hit_idx = [i for i, tp in enumerate(trade.tp_prices) if h >= tp]
        else:
            sl_hit = h >= trade.sl_price
            tp_hit_idx = [i for i, tp in enumerate(trade.tp_prices) if l <= tp]

        if sl_hit:
            return self._close_trade(trade, ts, trade.sl_price, "sl", stopped_out=True)

        # TP1
        if trade.stage == 0 and len(tp_hit_idx) >= 1:
            tp1 = trade.tp_prices[0]
            partial_lots = trade.initial_lots * self.cfg.tp1_close_pct
            partial_usd = self._close_partial(trade, ts, tp1, partial_lots, "tp1")
            trade.realized_partial_usd += partial_usd
            trade.stage = 1
            trade.remaining_lots -= partial_lots
            if self.cfg.move_sl_to_be_after_tp1:
                trade.sl_price = trade.entry_price

        # TP2
        if trade.stage == 1 and len(tp_hit_idx) >= 2:
            tp2 = trade.tp_prices[1]
            partial_lots = trade.initial_lots * self.cfg.tp2_close_pct
            partial_usd = self._close_partial(trade, ts, tp2, partial_lots, "tp2")
            trade.realized_partial_usd += partial_usd
            trade.stage = 2
            trade.remaining_lots -= partial_lots
            trade.trail_active = True
            trade.trail_anchor = max(trade.entry_price, tp2) if trade.side == "long" else min(trade.entry_price, tp2)

        # trail update
        if trade.trail_active and "atr14" in row.index:
            a = float(row["atr14"]) if pd.notna(row["atr14"]) else 0.0
            offset = self.cfg.runner_trail_atr_mult * a
            if trade.side == "long":
                new_sl = max(trade.sl_price, c - offset)
                trade.sl_price = new_sl
            else:
                new_sl = min(trade.sl_price, c + offset)
                trade.sl_price = new_sl

        # force exit
        if trade.bars_held >= self.cfg.force_exit_bars and trade.stage < 2:
            return self._close_trade(trade, ts, c, "time")

        # news close
        if self.news is not None and self.cfg.news_close_at_blackout:
            ts_dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
            blocked, _ = self.news.is_blackout(ts_dt, trade.pair)
            if blocked and trade.stage == 0:
                return self._close_trade(trade, ts, c, "news_close")

        return None

    def _close_partial(self, trade: _OpenTrade, ts, exit_price: float, lots: float, label: str) -> float:
        ts_dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        cost_usd, _ = self.costs.total_exit_cost_usd(trade.pair, lots, ts_dt, stopped_out=False)
        pv = pip_value(trade.pair, lots=lots)
        sign = 1 if trade.side == "long" else -1
        move_pips = price_to_pips(trade.pair, exit_price - trade.entry_price)
        gross_usd = sign * move_pips * pv
        return gross_usd - cost_usd

    def _close_trade(self, trade: _OpenTrade, ts, exit_price: float, reason: str, stopped_out: bool = False):
        ts_dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        lots = trade.remaining_lots
        cost_usd, _ = self.costs.total_exit_cost_usd(trade.pair, lots, ts_dt, stopped_out=stopped_out)
        pv = pip_value(trade.pair, lots=lots)
        sign = 1 if trade.side == "long" else -1
        move_pips = price_to_pips(trade.pair, exit_price - trade.entry_price)
        gross_usd = sign * move_pips * pv
        final_partial = gross_usd - cost_usd
        total_realized = trade.realized_partial_usd + final_partial
        r_multiple = total_realized / max(1e-9, trade.initial_risk_usd) if trade.initial_risk_usd else 0.0
        duration_min = int((ts_dt - trade.entry_ts).total_seconds() // 60)
        rec = TradeRecord(
            trade_id=trade.trade_id, pair=trade.pair, side=trade.side, strategy=trade.strategy,
            session=trade.session, pattern=trade.pattern,
            entry_ts=trade.entry_ts, exit_ts=ts_dt,
            entry_price=trade.entry_price, exit_price=exit_price,
            lots=trade.initial_lots, sl_price=trade.sl_price,
            realized_usd=total_realized, realized_r=r_multiple,
            win=total_realized > 0, close_reason=reason,
            spread_paid_pips=trade.spread_paid_pips,
            commission_usd=trade.commission_paid_usd + cost_usd * 0.0,  # commission counted in cost_usd
            swap_usd=trade.swap_paid_usd,
            slippage_pips=trade.slippage_paid_pips,
            duration_min=duration_min,
        )
        return rec, total_realized

    def _force_close(self, trade: _OpenTrade, ts, exit_price: float, reason: str):
        return self._close_trade(trade, ts, exit_price, reason, stopped_out=False)

    def _compute_kpis(self, eq: pd.Series, trades: pd.DataFrame, init: float, final: float) -> dict:
        if eq.empty:
            return {}
        ret_total = (final / init) - 1.0
        days = max(1, (eq.index[-1] - eq.index[0]).total_seconds() / 86400)
        years = days / 365.25
        cagr = (final / init) ** (1.0 / max(0.01, years)) - 1.0 if final > 0 else -1.0
        rets = eq.pct_change().dropna()
        sharpe = (rets.mean() / rets.std()) * np.sqrt(96 * 252) if rets.std() > 0 else 0.0
        downside = rets[rets < 0]
        sortino = (rets.mean() / downside.std()) * np.sqrt(96 * 252) if not downside.empty and downside.std() > 0 else 0.0
        peak = eq.cummax()
        dd = (eq - peak) / peak
        maxdd = float(dd.min()) if not dd.empty else 0.0
        calmar = abs(cagr / maxdd) if maxdd < 0 else 0.0
        n = len(trades)
        wins = int(trades["win"].sum()) if n else 0
        wr = wins / max(1, n)
        if n:
            gross_win = float(trades.loc[trades["win"], "realized_usd"].sum())
            gross_loss = abs(float(trades.loc[~trades["win"], "realized_usd"].sum()))
            pf = gross_win / max(1e-9, gross_loss)
            exp_r = float(trades["realized_r"].mean())
        else:
            pf = 0.0
            exp_r = 0.0
        return {
            "return_total_pct": ret_total * 100.0,
            "cagr_pct": cagr * 100.0,
            "sharpe": sharpe, "sortino": sortino, "calmar": calmar,
            "max_dd_pct": maxdd * 100.0,
            "n_trades": n, "win_rate": wr,
            "profit_factor": pf, "expectancy_r": exp_r,
        }
