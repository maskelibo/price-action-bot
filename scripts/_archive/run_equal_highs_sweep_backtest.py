"""Equal Highs / Lows Sweep — standalone backtest + decorrelation report.

Run:
    PYTHONPATH=src python scripts/run_equal_highs_sweep_backtest.py

Çıktı:
  - Yıllık breakdown (her yıl ayrı KPI satırı)
  - Genel KPI tablosu
  - Decorrelation: engulfing_continuation ile sinyal örtüşme oranı
  - VERDICT
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------------------
# Synthetic OHLCV with rich structure for equal-highs detection
# ---------------------------------------------------------------------------

def _generate_ohlcv(n: int = 1200, seed: int = 42) -> pd.DataFrame:
    """~3.3 yıl sentetik OHLCV — trending + ranging regimes, BTC-like."""
    rng = np.random.default_rng(seed)
    base_ts = datetime(2022, 1, 1, tzinfo=timezone.utc)
    ts = [base_ts + timedelta(days=i) for i in range(n)]

    price = np.empty(n)
    price[0] = 30_000.0
    for i in range(1, n):
        # 4 farklı rejim: uptrend, range, downtrend, recovery
        if i < 300:
            drift = 0.002
        elif i < 600:
            drift = 0.0
        elif i < 900:
            drift = -0.0015
        else:
            drift = 0.0018
        price[i] = price[i - 1] * (1 + drift + rng.normal(0, 0.018))

    close = price.copy()
    open_ = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.002, n))
    wick = np.abs(rng.normal(0, 0.008, n))
    high = np.maximum(open_, close) * (1 + wick)
    low = np.minimum(open_, close) * (1 - wick)

    # Embed some equal-highs patterns (6 occurrences)
    embed_centers = [80, 200, 380, 520, 700, 950]
    for center in embed_centers:
        if center + 20 >= n:
            continue
        ref_price = float(close[center])
        # İki swing high — eşit düzeyde (ATR ~= ref_price * 0.018)
        atr_approx = ref_price * 0.018 * 1.5
        sh_level = ref_price * 1.05
        # Bar center: swing high
        high[center] = sh_level
        close[center] = sh_level * 0.985
        open_[center] = sh_level * 0.990
        # Bar center+15: ikinci swing high (eşit)
        high[center + 15] = sh_level + atr_approx * 0.08  # tolerans içinde
        close[center + 15] = high[center + 15] * 0.985
        open_[center + 15] = high[center + 15] * 0.990
        # Sweep bar (center + 20): high > sh_level, close < sh_level
        high[center + 20] = sh_level + atr_approx * 0.25
        close[center + 20] = sh_level * 0.992
        open_[center + 20] = sh_level * 0.996

    # Embed some equal-lows patterns (4 occurrences)
    embed_lows = [150, 450, 750, 1050]
    for center in embed_lows:
        if center + 20 >= n:
            continue
        ref_price = float(close[center])
        atr_approx = ref_price * 0.018 * 1.5
        sl_level = ref_price * 0.95
        low[center] = sl_level
        close[center] = sl_level * 1.015
        open_[center] = sl_level * 1.010
        low[center + 15] = sl_level - atr_approx * 0.08
        close[center + 15] = low[center + 15] * 1.015
        open_[center + 15] = low[center + 15] * 1.010
        # Sweep bar
        low[center + 20] = sl_level - atr_approx * 0.25
        close[center + 20] = sl_level * 1.008
        open_[center + 20] = sl_level * 1.004

    # OHLC sanity
    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))
    vol = rng.uniform(1_000_000, 6_000_000, n)

    return pd.DataFrame({
        "venue": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "1d",
        "ts": ts,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": vol,
    })


# ---------------------------------------------------------------------------
# Yıllık breakdown
# ---------------------------------------------------------------------------

def _yearly_breakdown(trades_df: pd.DataFrame, initial_capital: float) -> pd.DataFrame:
    if trades_df.empty:
        return pd.DataFrame()
    tdf = trades_df.copy()
    tdf["year"] = pd.to_datetime(tdf["entry_ts"]).dt.year
    rows = []
    for yr, grp in tdf.groupby("year"):
        n = len(grp)
        wins = int((grp["realized_pnl_usdt"] > 0).sum())
        losses = n - wins
        wr = wins / n if n > 0 else 0.0
        total_pnl = grp["realized_pnl_usdt"].sum()
        avg_r = grp["realized_r_multiple"].mean()
        gross_win = grp.loc[grp["realized_pnl_usdt"] > 0, "realized_pnl_usdt"].sum()
        gross_loss = abs(grp.loc[grp["realized_pnl_usdt"] < 0, "realized_pnl_usdt"].sum())
        pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
        rows.append({
            "year": yr,
            "trades": n,
            "wins": wins,
            "losses": losses,
            "win_rate": wr,
            "total_pnl_usdt": total_pnl,
            "avg_r": avg_r,
            "profit_factor": pf,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Decorrelation: EQH sweep vs engulfing_continuation
# ---------------------------------------------------------------------------

def _compute_decorrelation(
    eqs_signals: list,
    eng_signals: list,
    ts_tolerance_days: int = 1,
) -> dict:
    """İki stratejinin timestamp'lerini karşılaştır."""
    if not eqs_signals or not eng_signals:
        return {"overlap_pct_eqs": 0.0, "overlap_pct_eng": 0.0, "shared": 0}

    eqs_ts = set(s.ts.date() for s in eqs_signals)
    eng_ts = set(s.ts.date() for s in eng_signals)

    # ±1 gün toleransla örtüşme
    shared = 0
    for t in eqs_ts:
        for delta in range(-ts_tolerance_days, ts_tolerance_days + 1):
            from datetime import date, timedelta as td
            check = t + td(days=delta)
            if check in eng_ts:
                shared += 1
                break

    overlap_eqs = shared / len(eqs_ts) if eqs_ts else 0.0
    overlap_eng = shared / len(eng_ts) if eng_ts else 0.0
    return {
        "overlap_pct_eqs": overlap_eqs,
        "overlap_pct_eng": overlap_eng,
        "shared": shared,
        "eqs_unique": len(eqs_ts) - shared,
        "eng_unique": len(eng_ts) - shared,
    }


# ---------------------------------------------------------------------------
# Main backtest
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 65)
    print("EQUAL HIGHS / LOWS SWEEP STRATEGY -- FULL BACKTEST")
    print("=" * 65)
    print("Strateji:  EqualHighsSweepStrategy (H-2 hipotezi)")
    print("Setup:     EQH sweep -> SHORT | EQL sweep -> LONG")
    print("Data:      Sentetik BTC/USDT, ~3.3 yil, seed=42")
    print()

    # ---- 1. Veri ----
    print("[1/6] Sentetik OHLCV üretiliyor...")
    df = _generate_ohlcv(n=1200, seed=42)
    print(f"      Barlar: {len(df)}  ({df['ts'].iloc[0].date()} -> {df['ts'].iloc[-1].date()})")
    print(f"      Fiyat araligi: {df['close'].min():.0f} - {df['close'].max():.0f} USDT")

    # ---- 2. EQH sweep stratejisi ----
    print("\n[2/6] EqualHighsSweepStrategy -- feature + signal generation...")
    from price_action.strategies.equal_highs_sweep import (
        EqualHighsSweepStrategy,
        _default_manifest,
    )
    strat_eqs = EqualHighsSweepStrategy(_default_manifest())
    df_f = strat_eqs.prepare_features(df)
    eqs_sigs = strat_eqs.generate_signals(df_f)
    short_sigs = [s for s in eqs_sigs if s.direction == "short"]
    long_sigs  = [s for s in eqs_sigs if s.direction == "long"]
    print(f"      Toplam sinyal: {len(eqs_sigs)}  SHORT={len(short_sigs)}  LONG={len(long_sigs)}")

    # ---- 3. Backtest ----
    print("\n[3/6] BacktestEngine calistiriliyor...")
    from price_action.backtest.engine import BacktestEngine

    start_dt = datetime(2022, 1, 1, tzinfo=timezone.utc)
    end_dt   = datetime(2025, 3, 31, tzinfo=timezone.utc)
    INITIAL  = 10_000.0

    def loader_eqs(sym, tf, s, e):
        return df_f.copy()

    engine = BacktestEngine(risk_officer=None)
    result = engine.run(
        strat_eqs,
        ["BTC/USDT"],
        start=start_dt,
        end=end_dt,
        timeframe="1d",
        initial_capital=INITIAL,
        fees={"taker": 0.00075, "maker": -0.0001},
        slippage_bps=5.0,
        ohlcv_provider=loader_eqs,
    )
    print(f"      Trade sayisi: {result.n_trades}")
    print(f"      Sure: {result.elapsed_sec:.3f}s")

    # ---- 4. Engulfing baseline (decorrelation) ----
    print("\n[4/6] EngulfingContinuation baseline (decorrelation icin)...")
    from price_action.strategies.engulfing_continuation import (
        EngulfingContinuationStrategy,
        _default_manifest as eng_default_manifest,
    )
    strat_eng = EngulfingContinuationStrategy(eng_default_manifest())
    df_eng = strat_eng.prepare_features(df.copy())
    eng_sigs = strat_eng.generate_signals(df_eng)
    print(f"      Engulfing sinyal sayisi: {len(eng_sigs)}")

    # ---- 5. KPI raporu ----
    kpis = result.kpis
    trades_df = result.trades
    yearly = _yearly_breakdown(trades_df, INITIAL)

    print("\n" + "=" * 65)
    print("KPI RAPORU -- EQUAL HIGHS / LOWS SWEEP")
    print("=" * 65)

    n_trades = int(kpis.get("n_trades", 0))
    wr = kpis.get("win_rate", 0.0)
    sharpe_v = kpis.get("sharpe", 0.0)
    sortino_v = kpis.get("sortino", 0.0)
    mdd = kpis.get("max_drawdown", 0.0)
    pf = kpis.get("profit_factor", 0.0)
    exp = kpis.get("expectancy", 0.0)
    cagr = kpis.get("cagr", 0.0)
    dsr = kpis.get("deflated_sharpe", 0.0)
    calmar_v = kpis.get("calmar", 0.0)

    print(f"\n  Toplam Trade     : {n_trades}")
    print(f"  Win Rate         : {wr:.1%}")
    print(f"  Profit Factor    : {pf:.3f}")
    print(f"  Expectancy       : {exp:+.2f} USDT/trade")
    print(f"  Sharpe           : {sharpe_v:.3f}")
    print(f"  Sortino          : {sortino_v:.3f}")
    print(f"  Deflated Sharpe  : {dsr:.3f}")
    print(f"  Max Drawdown     : {mdd:.2%}")
    print(f"  Calmar           : {calmar_v:.3f}")
    print(f"  CAGR (yillik)    : {cagr:.2%}")

    if not trades_df.empty:
        rmult = trades_df["realized_r_multiple"]
        print(f"\n  R-Multiple       : min={rmult.min():.2f}  max={rmult.max():.2f}  "
              f"mean={rmult.mean():.2f}  median={rmult.median():.2f}")

        eq = result.equity_curve
        print(f"\n  Baslangic equity : {eq.iloc[0]:,.2f} USDT")
        print(f"  Bitis equity     : {eq.iloc[-1]:,.2f} USDT")
        print(f"  Net PnL          : {eq.iloc[-1] - eq.iloc[0]:+,.2f} USDT "
              f"({(eq.iloc[-1]/eq.iloc[0]-1):.2%})")

    # ---- Yıllık breakdown ----
    if not yearly.empty:
        print("\n" + "-" * 65)
        print("YILLIK BREAKDOWN")
        print("-" * 65)
        print(f"  {'Yil':<6} {'Trade':>6} {'Win':>5} {'WR':>7} {'PnL(USDT)':>12} {'AvgR':>6} {'PF':>6}")
        print(f"  {'-'*6} {'-'*6} {'-'*5} {'-'*7} {'-'*12} {'-'*6} {'-'*6}")
        for _, row in yearly.iterrows():
            pf_str = f"{row['profit_factor']:.2f}" if row['profit_factor'] != float("inf") else "INF"
            print(
                f"  {int(row['year']):<6} {int(row['trades']):>6} {int(row['wins']):>5} "
                f"{row['win_rate']:>6.1%} {row['total_pnl_usdt']:>12.2f} "
                f"{row['avg_r']:>6.2f} {pf_str:>6}"
            )

    # ---- Decorrelation ----
    print("\n" + "-" * 65)
    print("DECORRELATION — EQH Sweep vs Engulfing Continuation")
    print("-" * 65)
    dcorr = _compute_decorrelation(eqs_sigs, eng_sigs)
    print(f"  EQH Sweep sinyal sayısı       : {len(eqs_sigs)}")
    print(f"  Engulfing sinyal sayısı        : {len(eng_sigs)}")
    print(f"  Ortusen gun (+/-1 gun)         : {dcorr['shared']}")
    print(f"  EQH Sweep ortusme orani        : {dcorr['overlap_pct_eqs']:.1%}")
    print(f"  Engulfing ortusme orani        : {dcorr['overlap_pct_eng']:.1%}")
    print(f"  EQH Sweep'e ozgu sinyaller     : {dcorr['eqs_unique']}")
    print(f"  Engulfing'e ozgu sinyaller     : {dcorr['eng_unique']}")

    decorr_score = 1.0 - dcorr["overlap_pct_eqs"]
    print(f"\n  Decorrelation skoru           : {decorr_score:.1%}")
    if decorr_score >= 0.70:
        print("  [SONUC] Stratejiler yeterince decorrelated -- portfolio cesitlemesi saglar.")
    else:
        print("  [SONUC] Stratejiler ortusiyor -- portfolio diversification sinirli.")

    # ---- VERDICT ----
    print("\n" + "=" * 65)
    print("VERDICT")
    print("=" * 65)

    # Basit puanlama
    score = 0
    verdict_notes = []

    if wr >= 0.45:
        score += 1
        verdict_notes.append(f"Win rate {wr:.1%} >= 45% [OK]")
    else:
        verdict_notes.append(f"Win rate {wr:.1%} < 45% -- zayif")

    if pf >= 1.2:
        score += 1
        verdict_notes.append(f"Profit factor {pf:.2f} >= 1.2 [OK]")
    else:
        verdict_notes.append(f"Profit factor {pf:.2f} < 1.2 -- zayif")

    if sharpe_v >= 0.5:
        score += 1
        verdict_notes.append(f"Sharpe {sharpe_v:.2f} >= 0.5 [OK]")
    else:
        verdict_notes.append(f"Sharpe {sharpe_v:.2f} < 0.5 -- zayif")

    if mdd > -0.25:
        score += 1
        verdict_notes.append(f"Max DD {mdd:.1%} < 25% [OK]")
    else:
        verdict_notes.append(f"Max DD {mdd:.1%} > 25% -- yuksek risk")

    if decorr_score >= 0.70:
        score += 1
        verdict_notes.append(f"Decorrelation {decorr_score:.0%} >= 70% [OK]")
    else:
        verdict_notes.append(f"Decorrelation {decorr_score:.0%} < 70% -- benzer sinyaller")

    for note in verdict_notes:
        print(f"  {note}")

    print(f"\n  Toplam puan: {score}/5")
    if score >= 4:
        verdict = "LIVE'A ADAY -- canli forward test baslatilabilir."
    elif score >= 3:
        verdict = "UMUT VAR -- parametre optimizasyonu + daha fazla veri gerekli."
    elif score >= 2:
        verdict = "ZAYIF EDGE -- arastirmaya devam, mevcut haliyle trade edilmez."
    else:
        verdict = "EDGE YOK -- strateji sentetik veride calismıyor; hipotez gözden gecirilmeli."

    print(f"\n  VERDICT: {verdict}")
    print("=" * 65)

    # ---- 6. Pattern breakdown ----
    if not trades_df.empty and "pattern_id" in trades_df.columns:
        print("\n[6/6] Pattern breakdown:")
        for pat, grp in trades_df.groupby("pattern_id"):
            n_p = len(grp)
            wr_p = (grp["realized_pnl_usdt"] > 0).mean()
            avg_r_p = grp["realized_r_multiple"].mean()
            print(f"      {pat:<25}  n={n_p:3d}  wr={wr_p:.1%}  avg_R={avg_r_p:.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
