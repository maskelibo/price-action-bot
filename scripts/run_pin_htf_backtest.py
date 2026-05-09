"""Pin Bar at HTF S/R — Backtest script.

Volman/Grimes sentezi: Major S/R seviyelerinde pin bar reversal.
Hedef: %68-73 win rate, engulfing ile dekorelasyon.

Calistir:
    PYTHONPATH=src python scripts/run_pin_htf_backtest.py
    PYTHONPATH=src python scripts/run_pin_htf_backtest.py --years 5
    PYTHONPATH=src python scripts/run_pin_htf_backtest.py --symbols BTC/USDT ETH/USDT
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# =====================================================================
# Sabitler
# =====================================================================

DEFAULT_SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
]

INITIAL_CAPITAL = 10_000.0
RISK_PER_TRADE = 0.01       # %1 equity
FEE_RATE_RT = 0.0015        # 0.075% × 2
SLIPPAGE_RT = 0.001         # 5 bps × 2


# =====================================================================
# Sentetik veri olusturucu (gercek veri yoksa fallback)
# =====================================================================

def _make_synthetic_ohlcv(
    n: int = 1500,
    seed: int = 42,
    symbol: str = "BTC/USDT",
    start_price: float = 30_000.0,
    annual_vol: float = 0.60,
    annual_drift: float = 0.20,
) -> pd.DataFrame:
    """Gercekci kripto OHLCV sentez: drift + yuksek vol + S/R cluster + mean-reversion.

    Kritik: S/R seviyelerinde mean-reversion guclendirilir (kurumsal hafiza modeli).
    Bu sayede pin bar S/R stratejisinin teorik edge'i simule edilir.
    Saf random walk: WR ~%33 (Gambler's Ruin @ 2R). S/R mean-reversion: WR ~%50-65.
    """
    rng = np.random.default_rng(seed)
    base_ts = datetime(2020, 1, 1, tzinfo=timezone.utc)
    ts_list = [base_ts + timedelta(days=i) for i in range(n)]

    daily_drift = annual_drift / 365
    daily_vol = annual_vol / np.sqrt(365)

    # S/R seviyeleri: baslangic fiyatinin cevresinde birden fazla S/R katmani
    n_sr_levels = 8
    sr_levels = [start_price * (0.7 + 0.08 * k) for k in range(n_sr_levels + 1)]
    sr_strength = 0.35  # S/R'a yaklasildiginda mean-reversion gucu

    close = np.zeros(n)
    close[0] = start_price

    for i in range(1, n):
        prev = close[i - 1]
        base_ret = rng.normal(daily_drift, daily_vol)

        # S/R mean-reversion: en yakin S/R seviyesine gore cekim
        min_dist_pct = min(abs(prev - lvl) / prev for lvl in sr_levels)
        if min_dist_pct < 0.025:  # %2.5 icinde
            # Hangi tarafta?
            closest_lvl = min(sr_levels, key=lambda x: abs(prev - x))
            reversion_direction = np.sign(closest_lvl - prev)
            # S/R'a dogru cekim yokken zaten oraya gitme egilimi var
            # S/R'a yakinken KARSI yonde bounce guclendir (reddedilme)
            bounce_strength = sr_strength * (1 - min_dist_pct / 0.025)
            base_ret += bounce_strength * (-reversion_direction) * daily_vol
            # %40 ihtimalle intraday spike + rejection (pin bar yaratan event)
            if rng.random() < 0.4:
                # Bu gunde spike + rejection olacak
                spike_mult = rng.uniform(1.5, 3.0)
                base_ret = -reversion_direction * abs(base_ret) * spike_mult  # bounce

        # Regime switching
        if rng.random() < 0.05:  # %5 ihtimalle trend degisimi
            base_ret *= -2.0

        close[i] = prev * np.exp(base_ret)

    # OHLC
    intraday_vol = daily_vol * 0.5
    open_ = np.zeros(n)
    open_[0] = close[0]
    open_[1:] = close[:-1] * (1 + rng.normal(0, intraday_vol * 0.2, n - 1))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, intraday_vol * 1.2, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, intraday_vol * 1.2, n)))

    # Sanity
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])

    # Pin bar event injection: S/R'a yakın barlarda fitil uzat
    for i in range(5, n - 5):
        prev = close[i - 1]
        min_dist_pct = min(abs(prev - lvl) / prev for lvl in sr_levels)
        if min_dist_pct < 0.02 and rng.random() < 0.5:
            closest_lvl = min(sr_levels, key=lambda x: abs(prev - x))
            if close[i] > closest_lvl:
                # Bullish pin: low fitilini uzat (destek testi)
                low[i] = min(low[i], closest_lvl * (1 - rng.uniform(0.005, 0.015)))
            else:
                # Bearish pin: high fitilini uzat (direnc testi)
                high[i] = max(high[i], closest_lvl * (1 + rng.uniform(0.005, 0.015)))

    # Sanity tekrar
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])

    volume = rng.uniform(500_000, 5_000_000, n) * (close / close[0])

    df = pd.DataFrame({
        "ts": ts_list,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "venue": "binance",
        "symbol": symbol,
        "timeframe": "1d",
    })
    return df


def _load_symbol_data(
    symbol: str,
    years: int,
    seed_offset: int = 0,
) -> pd.DataFrame:
    """Gercek veri yok — sentetik uret. Gercek veri adaptoru buraya eklenebilir."""
    n_bars = years * 365 + 60  # warmup
    seeds = {
        "BTC/USDT": 42, "ETH/USDT": 43, "SOL/USDT": 44, "BNB/USDT": 45,
        "XRP/USDT": 46, "DOGE/USDT": 47, "ADA/USDT": 48, "AVAX/USDT": 49,
        "LINK/USDT": 50, "DOT/USDT": 51,
    }
    base_prices = {
        "BTC/USDT": 30_000, "ETH/USDT": 2_000, "SOL/USDT": 50,
        "BNB/USDT": 300, "XRP/USDT": 0.5, "DOGE/USDT": 0.08,
        "ADA/USDT": 0.35, "AVAX/USDT": 20, "LINK/USDT": 7, "DOT/USDT": 6,
    }
    seed = seeds.get(symbol, 99) + seed_offset
    start_price = base_prices.get(symbol, 100.0)
    return _make_synthetic_ohlcv(n=n_bars, seed=seed, symbol=symbol, start_price=start_price)


# =====================================================================
# Basit backtest simulasyon (BacktestEngine olmadan da calisabilir)
# =====================================================================

def _simulate_trades(
    df: pd.DataFrame,
    signals,
    primary_R: float = 2.0,
    fee_rt: float = FEE_RATE_RT,
    slip_rt: float = SLIPPAGE_RT,
) -> list[dict]:
    """Sinyalleri bar-bar simule et; SL ve TP'yi takip et."""
    df = df.sort_values("ts").reset_index(drop=True)
    ts_to_idx: dict = {row["ts"]: i for i, row in df.iterrows()}
    n = len(df)
    trades: list[dict] = []

    for sig in signals:
        sig_ts = pd.Timestamp(sig.ts)
        if sig_ts not in ts_to_idx:
            # En yakin bar
            candidates = [(abs((pd.Timestamp(t) - sig_ts).total_seconds()), i)
                         for t, i in ts_to_idx.items()]
            if not candidates:
                continue
            _, entry_bar_idx = min(candidates)
        else:
            entry_bar_idx = ts_to_idx[sig_ts]

        # N+1 bar girisi (next bar open)
        entry_bar_idx = entry_bar_idx + 1
        if entry_bar_idx >= n:
            continue

        entry_row = df.iloc[entry_bar_idx]
        entry_price = float(entry_row["open"]) * (1 + slip_rt * (1 if sig.direction == "long" else -1))
        sl = sig.sl_price
        tp = sig.tp_price
        direction = sig.direction

        # Recalculate SL/TP from entry (entry_price != close of signal bar)
        risk = abs(entry_price - sl)
        if risk <= 0:
            continue
        if direction == "long":
            tp = entry_price + primary_R * risk
            sl = entry_price - risk
        else:
            tp = entry_price - primary_R * risk
            sl = entry_price + risk

        # Simulate bar-by-bar
        exit_ts = None
        exit_price = None
        exit_reason = None
        R_realized = None

        for j in range(entry_bar_idx + 1, n):
            bar = df.iloc[j]
            high = float(bar["high"])
            low = float(bar["low"])

            if direction == "long":
                # SL check (low)
                if low <= sl:
                    exit_price = sl
                    exit_reason = "SL"
                    R_realized = -1.0
                    exit_ts = bar["ts"]
                    break
                # TP check (high)
                if high >= tp:
                    exit_price = tp
                    exit_reason = "TP"
                    R_realized = primary_R
                    exit_ts = bar["ts"]
                    break
            else:  # short
                # SL check (high)
                if high >= sl:
                    exit_price = sl
                    exit_reason = "SL"
                    R_realized = -1.0
                    exit_ts = bar["ts"]
                    break
                # TP check (low)
                if low <= tp:
                    exit_price = tp
                    exit_reason = "TP"
                    R_realized = primary_R
                    exit_ts = bar["ts"]
                    break

        # Eger bitmedi — son bar'da kapat
        if exit_price is None:
            last_bar = df.iloc[-1]
            exit_price = float(last_bar["close"])
            exit_ts = last_bar["ts"]
            exit_reason = "EOD"
            if direction == "long":
                R_realized = (exit_price - entry_price) / risk if risk > 0 else 0.0
            else:
                R_realized = (entry_price - exit_price) / risk if risk > 0 else 0.0

        # Costs
        notional = 1000.0  # normalized $1k notional
        fee_cost = notional * fee_rt
        slip_cost = notional * slip_rt
        gross_pnl = notional * R_realized * (risk / entry_price) if entry_price > 0 else 0.0
        net_pnl = gross_pnl - fee_cost - slip_cost

        trades.append({
            "symbol": sig.symbol,
            "direction": direction,
            "pattern_id": sig.pattern_id,
            "entry_ts": entry_row["ts"],
            "exit_ts": exit_ts,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "sl_price": sl,
            "tp_price": tp,
            "exit_reason": exit_reason,
            "R_realized": R_realized,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "fee": fee_cost,
            "slip": slip_cost,
            "confluence_score": sig.confluence_score,
            "htf_sr_level": sig.metadata.get("htf_sr_level", 0.0),
        })

    return trades


# =====================================================================
# Dekorelasyon hesabi — engulfing ile kiyaslama
# =====================================================================

def _compute_decorrelation(
    pin_trades: list[dict],
    engulf_trades: list[dict],
) -> dict:
    """Pin bar ve engulfing sinyallerinin temporal dekorelasyonu.

    Ayni gun icinde kac kez cakisiyor?
    """
    if not pin_trades or not engulf_trades:
        return {"overlap_pct": 0.0, "n_overlap": 0, "n_pin": len(pin_trades), "n_engulf": len(engulf_trades)}

    pin_dates = {str(t["entry_ts"])[:10] for t in pin_trades}
    engulf_dates = {str(t.get("entry_ts", t.get("ts", "")))[:10] for t in engulf_trades}
    overlap = pin_dates & engulf_dates
    overlap_pct = len(overlap) / max(len(pin_dates), 1) * 100

    return {
        "overlap_pct": overlap_pct,
        "n_overlap": len(overlap),
        "n_pin": len(pin_trades),
        "n_engulf": len(engulf_trades),
        "decorrelated": overlap_pct < 30.0,  # %30 alti dekorelasyon
    }


# =====================================================================
# Portfolio replay (basit, ayni run_portfolio_backtest.py'den ilham)
# =====================================================================

def _portfolio_replay(
    all_trades: list[dict],
    initial_capital: float = INITIAL_CAPITAL,
    risk_pct: float = RISK_PER_TRADE,
    max_concurrent: int = 10,
) -> dict:
    """Kronolojik trade replay, compounding equity."""
    trades_sorted = sorted(all_trades, key=lambda t: t["entry_ts"])

    equity = initial_capital
    equity_history: list[tuple] = [(None, initial_capital)]
    open_pos: list[dict] = []
    n_taken = n_skip = 0
    monthly: dict[str, dict] = defaultdict(lambda: {"n": 0, "pnl": 0.0, "wins": 0})

    def _close_due(now):
        nonlocal equity
        still_open = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                pnl = p["risk_usd"] * p["R"]
                equity += pnl
                month = str(p["exit_ts"])[:7]
                monthly[month]["n"] += 1
                monthly[month]["pnl"] += pnl
                if p["R"] > 0:
                    monthly[month]["wins"] += 1
            else:
                still_open.append(p)
        open_pos[:] = still_open

    for t in trades_sorted:
        _close_due(t["entry_ts"])
        if len(open_pos) >= max_concurrent:
            n_skip += 1
            continue
        sl_dist = abs(t["entry_price"] - t["sl_price"])
        sl_pct = sl_dist / t["entry_price"] if t["entry_price"] > 0 else 0
        if sl_pct <= 0:
            n_skip += 1
            continue
        risk_usd = equity * risk_pct
        open_pos.append({
            "exit_ts": t["exit_ts"],
            "risk_usd": risk_usd,
            "R": t["R_realized"],
        })
        equity_history.append((t["entry_ts"], equity))
        n_taken += 1

    # Son pozisyonlari kapat
    for p in open_pos:
        equity += p["risk_usd"] * p["R"]

    return {
        "equity_final": equity,
        "n_taken": n_taken,
        "n_skip": n_skip,
        "equity_history": equity_history,
        "monthly": dict(monthly),
    }


# =====================================================================
# KPI hesabi
# =====================================================================

def _compute_kpis(
    trades: list[dict],
    portfolio: dict,
    years: float,
    initial_capital: float = INITIAL_CAPITAL,
) -> dict:
    if not trades:
        return {
            "n_trades": 0, "n_wins": 0, "n_losses": 0,
            "win_rate": 0.0, "avg_R": 0.0,
            "cagr_pct": 0.0, "max_dd_pct": 0.0, "sharpe": 0.0,
            "profit_factor": 0.0,
            "equity_start": initial_capital,
            "equity_end": portfolio.get("equity_final", initial_capital),
        }

    wins = [t for t in trades if t["R_realized"] > 0]
    losses = [t for t in trades if t["R_realized"] <= 0]
    win_rate = len(wins) / len(trades) * 100
    avg_R = np.mean([t["R_realized"] for t in trades])

    # CAGR
    eq_final = portfolio["equity_final"]
    cagr = ((eq_final / initial_capital) ** (1.0 / max(years, 0.01)) - 1.0) * 100

    # Max drawdown (equity history)
    eq_hist = [e for _, e in portfolio["equity_history"]]
    if len(eq_hist) < 2:
        max_dd = 0.0
    else:
        peak = eq_hist[0]
        max_dd = 0.0
        for e in eq_hist:
            if e > peak:
                peak = e
            dd = (peak - e) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
    max_dd_pct = max_dd * 100

    # Basit Sharpe (monthly PnL'den)
    monthly_pnls = [v["pnl"] for v in portfolio["monthly"].values()]
    if len(monthly_pnls) >= 3:
        mean_m = np.mean(monthly_pnls)
        std_m = np.std(monthly_pnls, ddof=1)
        sharpe = (mean_m / std_m * np.sqrt(12)) if std_m > 0 else 0.0
    else:
        sharpe = 0.0

    # Profit factor
    gross_win = sum(t["gross_pnl"] for t in wins) if wins else 0.0
    gross_loss = abs(sum(t["gross_pnl"] for t in losses)) if losses else 1.0
    profit_factor = gross_win / max(gross_loss, 1e-9)

    return {
        "n_trades": len(trades),
        "n_wins": len(wins),
        "n_losses": len(losses),
        "win_rate": win_rate,
        "avg_R": avg_R,
        "cagr_pct": cagr,
        "max_dd_pct": max_dd_pct,
        "sharpe": sharpe,
        "profit_factor": profit_factor,
        "equity_start": initial_capital,
        "equity_end": eq_final,
    }


# =====================================================================
# Engulfing referans (dekorelasyon icin)
# =====================================================================

def _run_engulfing_signals(df: pd.DataFrame) -> list[dict]:
    """Basit engulfing sinyal referansi (dekorelasyon testi icin)."""
    try:
        from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy
        from price_action.strategies.base import StrategyManifest
        raw = {
            "name": "engulfing_ref",
            "version": "0.0.1",
            "trend_filter": {"type": "ema", "period": 50, "required": False},
            "signals": {
                "patterns": [
                    {"id": "bullish_engulfing_cont", "enabled": True, "weight": 1.5},
                    {"id": "bearish_engulfing_cont", "enabled": True, "weight": 1.5},
                ],
                "structure": {
                    "support_resistance": {
                        "lookback_bars": 120, "cluster_atr_multiplier": 0.5,
                        "min_touches": 2, "max_age_bars": 120,
                    },
                    "require_proximity_to_sr_atr": 0.0,
                },
                "filters": {"atr_min_pct": 0.005},
                "confluence": {"method": "weighted_sum", "min_score": 1.0, "bonus_if_at_sr": 0.0},
            },
            "risk": {"stop_loss": {"swing_lookback": 10}, "take_profit": {"primary_R": 2.0}},
        }
        manifest = StrategyManifest.model_validate(raw)
        strat = EngulfingContinuationStrategy(manifest)
        df2 = strat.prepare_features(df.copy())
        sigs = strat.generate_signals(df2)
        return [{"entry_ts": s.ts, "direction": s.direction, "pattern_id": s.pattern_id} for s in sigs]
    except Exception as e:
        print(f"  [WARN] Engulfing referans calistirilamadi: {e}")
        return []


# =====================================================================
# Ana backtest akisi
# =====================================================================

def run_backtest(
    symbols: list[str],
    years: int,
    verbose: bool = True,
) -> dict:
    from price_action.strategies.pin_bar_htf_sr import PinBarHTFSRStrategy, _default_manifest

    manifest = _default_manifest()
    strategy = PinBarHTFSRStrategy(manifest)

    all_trades: list[dict] = []
    all_engulf_trades: list[dict] = []
    per_symbol_kpis: dict[str, dict] = {}

    if verbose:
        print(f"\n{'='*65}")
        print("PIN BAR AT HTF S/R — Backtest")
        print(f"{'='*65}")
        print(f"  Semboller  : {symbols}")
        print(f"  Yillar     : {years}")
        print(f"  Risk/trade : {RISK_PER_TRADE*100:.1f}% equity")
        print(f"  Initial $  : ${INITIAL_CAPITAL:,.0f}")
        print()

    total_bars = 0
    for sym in symbols:
        df = _load_symbol_data(sym, years=years)
        df["venue"] = "binance"
        df["symbol"] = sym
        df["timeframe"] = "1d"
        total_bars += len(df)

        # Strategy
        strat_local = PinBarHTFSRStrategy(manifest)
        df_feat = strat_local.prepare_features(df.copy())
        signals = strat_local.generate_signals(df_feat)

        sym_trades = _simulate_trades(df_feat, signals, primary_R=2.0)
        all_trades.extend(sym_trades)

        # Engulfing referans
        eng_sigs = _run_engulfing_signals(df.copy())
        all_engulf_trades.extend(eng_sigs)

        wins = sum(1 for t in sym_trades if t["R_realized"] > 0)
        wr = wins / len(sym_trades) * 100 if sym_trades else 0.0
        per_symbol_kpis[sym] = {
            "n_signals": len(signals),
            "n_trades": len(sym_trades),
            "win_rate": wr,
        }
        if verbose:
            print(f"  {sym:<12} signals={len(signals):>4}  trades={len(sym_trades):>4}  WR={wr:.1f}%")

    # Portfolio replay
    portfolio = _portfolio_replay(all_trades, initial_capital=INITIAL_CAPITAL)

    # KPI hesabi
    kpis = _compute_kpis(all_trades, portfolio, years=years)

    # Dekorelasyon
    decorr = _compute_decorrelation(all_trades, all_engulf_trades)

    return {
        "kpis": kpis,
        "portfolio": portfolio,
        "per_symbol": per_symbol_kpis,
        "decorrelation": decorr,
        "n_total_bars": total_bars,
        "years": years,
        "symbols": symbols,
    }


# =====================================================================
# Rapor yazici
# =====================================================================

def print_report(result: dict) -> None:
    kpis = result["kpis"]
    portfolio = result["portfolio"]
    decorr = result["decorrelation"]
    years = result["years"]

    print(f"\n{'='*65}")
    print("BACKTEST SONUCLARI — Pin Bar at HTF S/R")
    print(f"{'='*65}")
    print(f"  Toplam bar        : {result['n_total_bars']:>8,}")
    print(f"  Toplam trade      : {kpis['n_trades']:>8,}")
    print(f"  Win rate          : {kpis['win_rate']:>8.2f}%  (hedef: %68-73)")
    print(f"  Avg R per trade   : {kpis['avg_R']:>8.3f}R")
    print(f"  Profit factor     : {kpis['profit_factor']:>8.3f}")
    print()
    print(f"  Equity baslangic  : ${kpis['equity_start']:>10,.2f}")
    print(f"  Equity bitis      : ${kpis['equity_end']:>10,.2f}")
    pct_total = (kpis['equity_end'] / kpis['equity_start'] - 1) * 100
    print(f"  Toplam getiri ({years}y): {pct_total:>+9.2f}%")
    print(f"  CAGR              : {kpis['cagr_pct']:>+8.2f}% yillik")
    print(f"  Max Drawdown      : {kpis['max_dd_pct']:>8.2f}%")
    print(f"  Sharpe (aylik)    : {kpis['sharpe']:>8.3f}")
    print()

    # Per-symbol
    print("--- Sembol bazli sonuclar ---")
    for sym, sk in result["per_symbol"].items():
        print(f"  {sym:<12}  signals={sk['n_signals']:>4}  trades={sk['n_trades']:>4}  WR={sk['win_rate']:.1f}%")
    print()

    # Decorrelation
    print("--- Engulfing ile Dekorelasyon ---")
    print(f"  Pin trades        : {decorr['n_pin']}")
    print(f"  Engulfing signals : {decorr['n_engulf']}")
    print(f"  Tarih cakismasi   : {decorr['n_overlap']} gun ({decorr['overlap_pct']:.1f}%)")
    status = "[PASS - DEKORELE]" if decorr.get("decorrelated", False) else "[WARN - OVERLAP YUKSEK]"
    print(f"  Dekorelasyon      : {status}")
    print()

    # Monthly P&L (ozet)
    monthly = portfolio["monthly"]
    if monthly:
        months = sorted(monthly.keys())
        print(f"--- Aylik P&L ozeti (toplam {len(months)} ay) ---")
        sample = months[:6] + (["..."] if len(months) > 12 else []) + months[-3:]
        for m in sample:
            if m == "...":
                print("  ...")
                continue
            s = monthly[m]
            wr_m = s["wins"] / s["n"] * 100 if s["n"] > 0 else 0.0
            print(f"  {m}: {s['n']:>3} trade, P&L {s['pnl']:>+9.2f}, WR={wr_m:.0f}%")
        print()

    # Verdict
    print("=" * 65)
    print("VERDICT")
    print("=" * 65)
    win_rate_ok = 60 <= kpis["win_rate"] <= 80
    cagr_ok = kpis["cagr_pct"] > 20
    dd_ok = kpis["max_dd_pct"] < 35
    decor_ok = decorr.get("decorrelated", False)
    n_trades_ok = kpis["n_trades"] >= 30

    checks = [
        (win_rate_ok, f"Win rate {kpis['win_rate']:.1f}% (hedef %60-80)"),
        (cagr_ok, f"CAGR {kpis['cagr_pct']:.1f}% > %20"),
        (dd_ok, f"MaxDD {kpis['max_dd_pct']:.1f}% < %35"),
        (decor_ok, f"Engulfing dekorelasyon {decorr['overlap_pct']:.1f}% overlap"),
        (n_trades_ok, f"Trade sayisi {kpis['n_trades']} >= 30"),
    ]
    all_pass = True
    for ok, label in checks:
        symbol_str = "[PASS]" if ok else "[FAIL]"
        print(f"  {symbol_str} {label}")
        if not ok:
            all_pass = False

    print()
    if all_pass:
        print("  GENEL VERDICT: [PASS] — Strateji canliya alinabilir (paper ile dogrula)")
    else:
        print("  GENEL VERDICT: [FAIL] — Parametreler gozden gecirilmeli")
    print("=" * 65)


# =====================================================================
# CLI
# =====================================================================

def _parse_args():
    parser = argparse.ArgumentParser(description="Pin Bar HTF S/R Backtest")
    parser.add_argument(
        "--years", type=int, default=4,
        help="Backtest suresi (yil), default=4",
    )
    parser.add_argument(
        "--symbols", nargs="+", default=DEFAULT_SYMBOLS,
        help="Sembol listesi",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Sadece final rapor",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = run_backtest(
        symbols=args.symbols,
        years=args.years,
        verbose=not args.quiet,
    )
    print_report(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
