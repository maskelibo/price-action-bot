"""BTC-ETH Pairs Trading Backtest.

Ernie Chan stilinde Engle-Granger cointegration + rolling OLS hedge ratio.
Dollar-neutral pairs trading: P&L = BTC_ret - beta * ETH_ret

Calistirma:
    PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/run_pairs_backtest.py

Karsilastirma: Engulfing solo Sharpe (onceki backtest icin 0.28 avg).
"""
from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# =====================================================================
# Veri yukleme
# =====================================================================

def _load_ohlcv(symbol: str, tf: str = "1d", venue: str = "binance") -> pd.DataFrame:
    """DuckDB'den OHLCV oku."""
    import duckdb
    db_path = ROOT / "data" / "market.duckdb"
    if not db_path.exists():
        print(f"  WARN: DuckDB dosyasi bulunamadi: {db_path}")
        return pd.DataFrame()
    con = duckdb.connect(str(db_path), read_only=True)
    df = con.execute(
        "SELECT ts, open, high, low, close, volume FROM ohlcv "
        "WHERE venue=? AND symbol=? AND timeframe=? ORDER BY ts",
        [venue, symbol, tf],
    ).fetchdf()
    con.close()
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["symbol"] = symbol
    df["timeframe"] = tf
    df["venue"] = venue
    return df


def _merge_btc_eth(df_btc: pd.DataFrame, df_eth: pd.DataFrame) -> pd.DataFrame:
    """BTC ve ETH verilerini ts üzerinden merge et."""
    if df_btc.empty or df_eth.empty:
        return pd.DataFrame()

    btc = df_btc[["ts", "close"]].rename(columns={"close": "btc_close"})
    eth = df_eth[["ts", "close"]].rename(columns={"close": "eth_close"})

    # ts'i normalize (sadece date, timezone-aware)
    btc["ts"] = btc["ts"].dt.normalize()
    eth["ts"] = eth["ts"].dt.normalize()

    merged = pd.merge(btc, eth, on="ts", how="inner")
    merged = merged.sort_values("ts").reset_index(drop=True)
    return merged


# =====================================================================
# ADF p-value dagilimi analizi
# =====================================================================

def _adf_distribution_analysis(adf_series: pd.Series) -> dict:
    """ADF p-value serisinin dagilimini analiz et."""
    valid = adf_series.dropna()
    if valid.empty:
        return {"error": "no data"}

    pct_cointegrated = float((valid < 0.05).mean())
    pct_marginal = float(((valid >= 0.05) & (valid < 0.10)).mean())
    pct_broken = float((valid >= 0.10).mean())

    return {
        "n_bars_with_adf": len(valid),
        "pct_cointegrated_p05": round(pct_cointegrated * 100, 1),
        "pct_marginal_p10": round(pct_marginal * 100, 1),
        "pct_broken_p10plus": round(pct_broken * 100, 1),
        "adf_p_mean": round(float(valid.mean()), 4),
        "adf_p_median": round(float(valid.median()), 4),
        "adf_p_min": round(float(valid.min()), 4),
        "adf_p_max": round(float(valid.max()), 4),
    }


def _find_cointegration_breaks(df: pd.DataFrame, window: int = 30) -> list[dict]:
    """ADF p-value > 0.10 uzun sureli kaldigi periyotlari bul."""
    if "adf_p_lag" not in df.columns:
        return []

    broken = df["adf_p_lag"] > 0.10
    breaks = []
    start = None
    for i, (ts, is_broken) in enumerate(zip(df["ts"], broken)):
        if is_broken and start is None:
            start = ts
        elif not is_broken and start is not None:
            duration = (ts - start).days
            if duration >= window:
                breaks.append({
                    "start": str(start.date()),
                    "end": str(ts.date()),
                    "duration_days": duration,
                })
            start = None
    # Kapanmamis son periyot
    if start is not None:
        last_ts = df["ts"].iloc[-1]
        duration = (last_ts - start).days
        if duration >= window:
            breaks.append({
                "start": str(start.date()),
                "end": str(last_ts.date()),
                "duration_days": duration,
                "ongoing": True,
            })
    return breaks


# =====================================================================
# Basit pairs backtest simülasyon
# =====================================================================

def _run_pairs_backtest(
    df: pd.DataFrame,
    initial_capital: float = 10_000.0,
    fee_rate: float = 0.00075,  # per leg (taker)
    slippage_bps: float = 5.0,
) -> dict:
    """Pairs trading P&L simulasyonu.

    Giriş: df ile btc_close, eth_close, spread_z, adf_p_lag, hedge_ratio kolonlari.

    Pozisyon modeli: dollar-neutral
      - LONG spread entry'de: 1 BTC birim long, hedge_ratio kadar ETH short
      - SHORT spread entry'de: 1 BTC birim short, hedge_ratio kadar ETH long
      - Her bacak icin notional = initial_capital / 2 (efektif dollar-neutral)

    P&L: btc_return - hedge_ratio * eth_return (log getiri farkı)
    Fee: her entry/exit'te her iki bacak icin.
    """
    from price_action.strategies.btc_eth_pairs import (
        BTCETHPairsStrategy,
        _default_manifest,
    )

    strategy = BTCETHPairsStrategy(_default_manifest())
    df_feats = strategy.prepare_features_pair(df)

    z_entry = strategy.spread_z_entry    # 2.0
    z_exit = strategy.exit_z             # 0.5
    z_stop = strategy.stop_z             # 3.5
    adf_thr = strategy.adf_threshold     # 0.05

    slippage_factor = slippage_bps / 10_000.0

    # Round-trip maliyet her bacak icin: 2 * fee + 2 * slippage
    cost_per_leg = 2 * fee_rate + 2 * slippage_factor
    round_trip_cost = 2 * cost_per_leg  # 2 bacak

    equity = initial_capital
    trades: list[dict] = []
    equity_curve: list[tuple] = [(df_feats["ts"].iloc[0], equity)]

    in_position = None  # None, "long_spread", "short_spread"
    entry_btc_price = 0.0
    entry_eth_price = 0.0
    entry_hedge = 1.0
    entry_ts = None
    entry_z = 0.0

    for i in range(1, len(df_feats)):
        row = df_feats.iloc[i]
        prev = df_feats.iloc[i - 1]

        z = float(row.get("spread_z", np.nan))
        adf_p = float(row.get("adf_p_lag", np.nan))
        hedge = float(row.get("hedge_ratio", np.nan))
        btc_price = float(row.get("btc_close", np.nan))
        eth_price = float(row.get("eth_close", np.nan))
        ts = row["ts"]

        if any(np.isnan(v) for v in [z, adf_p, hedge, btc_price, eth_price]):
            equity_curve.append((ts, equity))
            continue

        cointegrated = adf_p < adf_thr

        # --- EXIT ---
        if in_position == "long_spread":
            # Cikis: z geri dondu veya stop
            if z > -z_exit or z < -z_stop:
                # P&L hesabı: log return farkı
                btc_log_ret = np.log(btc_price / entry_btc_price)
                eth_log_ret = np.log(eth_price / entry_eth_price)
                spread_pnl = btc_log_ret - entry_hedge * eth_log_ret
                # Dollar P&L (nominal: initial_capital)
                dollar_pnl = spread_pnl * (equity / 2)
                dollar_pnl -= round_trip_cost * equity
                equity += dollar_pnl
                equity = max(equity, 0.01)  # ruin floor

                exit_type = "stop" if z < -z_stop else "normal"
                hold_bars = i - entry_idx  # type: ignore[name-defined]
                trades.append({
                    "direction": "long_spread",
                    "entry_ts": str(entry_ts.date() if hasattr(entry_ts, "date") else entry_ts),
                    "exit_ts": str(ts.date() if hasattr(ts, "date") else ts),
                    "entry_z": round(entry_z, 3),
                    "exit_z": round(z, 3),
                    "spread_pnl_pct": round(spread_pnl * 100, 4),
                    "dollar_pnl": round(dollar_pnl, 2),
                    "exit_type": exit_type,
                    "hold_bars": hold_bars,
                    "hedge_ratio": round(entry_hedge, 4),
                })
                in_position = None
                equity_curve.append((ts, equity))
                continue

        elif in_position == "short_spread":
            # Cikis: z geri dondu veya stop
            if z < z_exit or z > z_stop:
                btc_log_ret = np.log(btc_price / entry_btc_price)
                eth_log_ret = np.log(eth_price / entry_eth_price)
                spread_pnl = -(btc_log_ret - entry_hedge * eth_log_ret)  # short spread
                dollar_pnl = spread_pnl * (equity / 2)
                dollar_pnl -= round_trip_cost * equity
                equity += dollar_pnl
                equity = max(equity, 0.01)

                exit_type = "stop" if z > z_stop else "normal"
                hold_bars = i - entry_idx  # type: ignore[name-defined]
                trades.append({
                    "direction": "short_spread",
                    "entry_ts": str(entry_ts.date() if hasattr(entry_ts, "date") else entry_ts),
                    "exit_ts": str(ts.date() if hasattr(ts, "date") else ts),
                    "entry_z": round(entry_z, 3),
                    "exit_z": round(z, 3),
                    "spread_pnl_pct": round(spread_pnl * 100, 4),
                    "dollar_pnl": round(dollar_pnl, 2),
                    "exit_type": exit_type,
                    "hold_bars": hold_bars,
                    "hedge_ratio": round(entry_hedge, 4),
                })
                in_position = None
                equity_curve.append((ts, equity))
                continue

        # --- ENTRY ---
        if in_position is None and cointegrated:
            if z < -z_entry:
                in_position = "long_spread"
                entry_btc_price = btc_price
                entry_eth_price = eth_price
                entry_hedge = hedge
                entry_ts = ts
                entry_z = z
                entry_idx = i
            elif z > z_entry:
                in_position = "short_spread"
                entry_btc_price = btc_price
                entry_eth_price = eth_price
                entry_hedge = hedge
                entry_ts = ts
                entry_z = z
                entry_idx = i

        equity_curve.append((ts, equity))

    # Force-close açık pozisyon (son bar)
    if in_position is not None and len(df_feats) > 1:
        last = df_feats.iloc[-1]
        btc_price = float(last.get("btc_close", entry_btc_price))
        eth_price = float(last.get("eth_close", entry_eth_price))
        btc_log_ret = np.log(btc_price / entry_btc_price) if entry_btc_price > 0 else 0
        eth_log_ret = np.log(eth_price / entry_eth_price) if entry_eth_price > 0 else 0
        if in_position == "long_spread":
            spread_pnl = btc_log_ret - entry_hedge * eth_log_ret
        else:
            spread_pnl = -(btc_log_ret - entry_hedge * eth_log_ret)
        dollar_pnl = spread_pnl * (equity / 2)
        dollar_pnl -= round_trip_cost * equity
        equity += dollar_pnl
        equity = max(equity, 0.01)
        trades.append({
            "direction": in_position,
            "entry_ts": str(entry_ts.date() if hasattr(entry_ts, "date") else entry_ts),
            "exit_ts": str(last["ts"].date() if hasattr(last["ts"], "date") else last["ts"]),
            "entry_z": round(entry_z, 3),
            "exit_z": 0.0,
            "spread_pnl_pct": round(spread_pnl * 100, 4),
            "dollar_pnl": round(dollar_pnl, 2),
            "exit_type": "force_close",
            "hold_bars": len(df_feats) - 1 - entry_idx,
            "hedge_ratio": round(entry_hedge, 4),
        })

    # KPI hesapla
    trade_df = pd.DataFrame(trades)
    kpis = _compute_kpis(trade_df, equity_curve, initial_capital)

    return {
        "initial_capital": initial_capital,
        "final_equity": round(equity, 2),
        "n_trades": len(trades),
        "trades": trades,
        "equity_curve": [(str(ts.date() if hasattr(ts, "date") else ts), round(eq, 2))
                         for ts, eq in equity_curve[::5]],  # decimated
        "kpis": kpis,
        "features": {
            "adf_distribution": _adf_distribution_analysis(df_feats["adf_p_lag"]),
            "cointegration_breaks": _find_cointegration_breaks(df_feats),
            "half_life_days": _compute_half_life_from_features(df_feats),
        },
    }


def _compute_half_life_from_features(df: pd.DataFrame) -> float:
    """Spread serisinden half-life hesapla."""
    from price_action.strategies.btc_eth_pairs import _half_life
    if "spread" not in df.columns:
        return np.nan
    return round(_half_life(df["spread"].dropna()), 2)


def _compute_kpis(
    trade_df: pd.DataFrame,
    equity_curve: list[tuple],
    initial_capital: float,
) -> dict:
    """Temel backtest KPI'ları hesapla."""
    if trade_df.empty or len(trade_df) == 0:
        return {
            "n_trades": 0, "win_rate": 0.0, "avg_pnl": 0.0,
            "sharpe": 0.0, "max_drawdown": 0.0, "cagr": 0.0,
            "profit_factor": 0.0, "avg_hold_bars": 0.0,
        }

    pnls = trade_df["dollar_pnl"].values
    wins = pnls > 0
    n = len(pnls)
    win_rate = float(wins.mean())
    avg_pnl = float(pnls.mean())

    # Equity curve -> drawdown
    eq_vals = np.array([eq for _, eq in equity_curve])
    peak = np.maximum.accumulate(eq_vals)
    dd = (eq_vals - peak) / (peak + 1e-12)
    max_dd = float(dd.min())

    # Annualized returns from equity curve
    if len(equity_curve) >= 2:
        first_ts, _ = equity_curve[0]
        last_ts, last_eq = equity_curve[-1]
        try:
            if hasattr(first_ts, "date"):
                days = (last_ts - first_ts).days
            else:
                days = (pd.Timestamp(last_ts) - pd.Timestamp(first_ts)).days
        except Exception:
            days = 365
        years = max(days / 365.25, 0.1)
        final_eq = last_eq
        cagr = float(((final_eq / initial_capital) ** (1 / years)) - 1)
    else:
        cagr = 0.0

    # Sharpe (daily log returns from equity curve)
    if len(equity_curve) > 10:
        eq_series = np.array([eq for _, eq in equity_curve])
        daily_rets = np.diff(np.log(np.maximum(eq_series, 1e-6)))
        if np.std(daily_rets) > 0:
            sharpe = float(np.mean(daily_rets) / np.std(daily_rets) * np.sqrt(252))
        else:
            sharpe = 0.0
    else:
        sharpe = 0.0

    # Profit factor
    gross_win = float(pnls[pnls > 0].sum()) if any(pnls > 0) else 0.0
    gross_loss = float(abs(pnls[pnls < 0].sum())) if any(pnls < 0) else 1e-6
    pf = gross_win / max(gross_loss, 1e-6)

    avg_hold = float(trade_df["hold_bars"].mean()) if "hold_bars" in trade_df.columns else 0.0

    return {
        "n_trades": n,
        "win_rate": round(win_rate, 4),
        "avg_pnl_usd": round(avg_pnl, 2),
        "gross_profit": round(gross_win, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(pf, 4),
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(max_dd, 4),
        "cagr": round(cagr, 4),
        "avg_hold_bars": round(avg_hold, 1),
    }


# =====================================================================
# Main
# =====================================================================

def main() -> int:
    print("=" * 70)
    print("BTC-ETH Pairs Trading Backtest (Chan-style Cointegration)")
    print("=" * 70)
    print()

    # Veri yukle
    print("  Veri yukleniyor: BTC/USDT + ETH/USDT 1d...")
    df_btc = _load_ohlcv("BTC/USDT", "1d", "binance")
    df_eth = _load_ohlcv("ETH/USDT", "1d", "binance")

    if df_btc.empty or df_eth.empty:
        print("  FAIL: Veri bulunamadi. Oncelikle 'python scripts/seed_data.py' calistirin.")
        return 1

    print(f"  BTC: {len(df_btc)} bar ({df_btc['ts'].iloc[0].date()} - {df_btc['ts'].iloc[-1].date()})")
    print(f"  ETH: {len(df_eth)} bar ({df_eth['ts'].iloc[0].date()} - {df_eth['ts'].iloc[-1].date()})")

    # Merge
    df = _merge_btc_eth(df_btc, df_eth)
    if df.empty:
        print("  FAIL: BTC ve ETH zamanlamalari eslesmiyor.")
        return 1

    print(f"  Birlesik: {len(df)} bar")
    print()

    # Full Engle-Granger cointegration testi (tum veri uzerinde)
    print("--- Tum Donem Cointegration Testi (Engle-Granger) ---")
    try:
        from price_action.strategies.btc_eth_pairs import _adf_test
        from statsmodels.regression.linear_model import OLS
        from statsmodels.tools import add_constant
        import statsmodels.api as sm

        log_btc = np.log(df["btc_close"].clip(lower=1e-12))
        log_eth = np.log(df["eth_close"].clip(lower=1e-12))

        # Her iki serinin birim kok testi
        from statsmodels.tsa.stattools import adfuller
        res_btc = adfuller(log_btc.values, maxlag=1)
        res_eth = adfuller(log_eth.values, maxlag=1)
        print(f"  ADF log(BTC): p = {res_btc[1]:.4f}  (null: unit root — p>0.05 gerekli)")
        print(f"  ADF log(ETH): p = {res_eth[1]:.4f}  (null: unit root — p>0.05 gerekli)")

        # OLS rezidü
        X = sm.add_constant(log_eth.values)
        model = OLS(log_btc.values, X)
        fit = model.fit()
        beta = fit.params[1]
        resid = fit.resid
        res_spread = adfuller(resid, maxlag=1)
        print(f"  OLS beta (hedge ratio): {beta:.4f}")
        print(f"  ADF residual: p = {res_spread[1]:.4f}  (cointegration: p<0.05 gerekli)")
        cointegrated_full = res_spread[1] < 0.05
        verdict = "COINTEGRATED" if cointegrated_full else "NOT COINTEGRATED"
        print(f"  Tum Donem Verdict: {verdict}")
        print()
    except ImportError:
        print("  statsmodels yuklu degil — atlaniyor")
        print()

    # Pairs backtest calistir
    print("--- Pairs Backtest Simulasyonu ---")
    print("  Parametreler: z_entry=2.0, exit_z=0.5, stop_z=3.5, adf_thr=0.05")
    print("  Fee: 0.075% taker + 5bps slippage (round-trip ~0.2%)")
    print()

    result = _run_pairs_backtest(df, initial_capital=10_000.0)

    k = result["kpis"]
    adf_dist = result["features"]["adf_distribution"]
    breaks = result["features"]["cointegration_breaks"]
    hl = result["features"]["half_life_days"]

    print(f"  Toplam bar (birlesik)  : {len(df)}")
    print(f"  Toplam trade           : {k['n_trades']}")
    print(f"  Win rate               : {k['win_rate']*100:.1f}%")
    print(f"  Profit Factor          : {k['profit_factor']:.2f}")
    print(f"  Avg Hold (bar)         : {k['avg_hold_bars']:.1f}")
    print(f"  Sharpe                 : {k['sharpe']:.3f}")
    print(f"  Max Drawdown           : {k['max_drawdown']*100:.1f}%")
    print(f"  CAGR                   : {k['cagr']*100:.1f}%")
    print(f"  Initial Equity         : ${result['initial_capital']:,.0f}")
    print(f"  Final Equity           : ${result['final_equity']:,.0f}")
    print(f"  Net P&L                : ${result['final_equity'] - result['initial_capital']:+,.0f}")
    print()

    # ADF dagilimi
    print("--- ADF P-Value Dagilimi (Rolling 60-bar) ---")
    print(f"  Cointegrated (p<0.05)  : {adf_dist.get('pct_cointegrated_p05', 0):.1f}% barin")
    print(f"  Marginal (p 0.05-0.10) : {adf_dist.get('pct_marginal_p10', 0):.1f}% barin")
    print(f"  Broken (p>0.10)        : {adf_dist.get('pct_broken_p10plus', 0):.1f}% barin")
    print(f"  Median ADF p           : {adf_dist.get('adf_p_median', 0):.4f}")
    print(f"  Half-life (OU)         : {hl} gun")
    print()

    # Cointegration kırılmaları
    if breaks:
        print("--- Cointegration Kirilmalari (>30 gun p>0.10) ---")
        for b in breaks:
            ongoing = " (DEVAM EDIYOR)" if b.get("ongoing") else ""
            print(f"  {b['start']} -> {b['end']} ({b['duration_days']} gun){ongoing}")
        print()
    else:
        print("--- Cointegration Kirilmasi: Tespit edilmedi (>30 gun) ---\n")

    # Engulfing karsilastirma (onceki bilinen deger)
    print("--- Engulfing vs Pairs Karsilastirma ---")
    engulfing_sharpe = 0.28  # onceki backtest agregati
    engulfing_cagr = 2.1     # onceki backtest (%)
    print(f"  Metrik           engulfing_cont    btc_eth_pairs")
    print(f"  Sharpe           {engulfing_sharpe:>10.2f}    {k['sharpe']:>14.3f}")
    print(f"  CAGR%            {engulfing_cagr:>10.1f}    {k['cagr']*100:>14.1f}")
    print(f"  MaxDD%           {'N/A':>10}    {k['max_drawdown']*100:>14.1f}")
    print(f"  Win rate         {'N/A':>10}    {k['win_rate']*100:>14.1f}%")
    print()

    # Verdict
    print("=" * 70)
    sharpe = k["sharpe"]
    pct_coint = adf_dist.get("pct_cointegrated_p05", 0)
    n_breaks_long = sum(1 for b in breaks if b.get("duration_days", 0) > 60)

    print("VERDICT:")
    if sharpe >= 1.0 and pct_coint >= 60:
        verdict = "PROMOTE"
        rationale = (
            f"Sharpe {sharpe:.2f} >= 1.0 VE cointegration %{pct_coint:.0f} barin."
            " Market-neutral diversifier olarak portföye eklenebilir."
        )
    elif sharpe >= 0.5 and pct_coint >= 40:
        verdict = "DEFER"
        rationale = (
            f"Sharpe {sharpe:.2f} (hedef 1.0 altinda). "
            f"Cointegration sadece barin %{pct_coint:.0f}'inde gecerli. "
            "Kalman filter veya daha iyi hedge ratio ile iyilestirilmeli."
        )
    else:
        verdict = "REJECT"
        rationale = (
            f"Sharpe {sharpe:.2f} < 0.5 veya cointegration yetersiz (%{pct_coint:.0f}). "
            "BTC-ETH spreadi retailin ulasamayacagi hizda arbitraj edilmis. "
            "Pairs trade bu konfigurasyonda net negatif beklenti degeri."
        )

    print(f"  {verdict}")
    print(f"  {rationale}")
    if n_breaks_long > 0:
        print(f"  UYARI: {n_breaks_long} uzun cointegration kirilmasi (>60 gun) tespit edildi.")
    print()

    # Rapor kaydet
    report = {
        "strategy": "btc_eth_pairs",
        "date": datetime.now(timezone.utc).isoformat(),
        "backtest": result,
        "verdict": verdict,
        "rationale": rationale,
        "comparison": {
            "engulfing_sharpe": engulfing_sharpe,
            "pairs_sharpe": k["sharpe"],
            "decorrelation_note": (
                "Market-neutral — direksiyonel exposure yok; "
                "teorik korelasyon engulfing ile ~0"
            ),
        },
    }
    report_path = (
        ROOT
        / "reports"
        / "backtests"
        / f"btc_eth_pairs_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, default=str, indent=2), encoding="utf-8")
    print(f"Detay rapor: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
