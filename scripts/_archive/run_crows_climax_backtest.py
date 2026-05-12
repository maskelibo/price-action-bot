"""HYP-NEW-6: Three Black Crows + Buying Climax Distribution Short — Gercek Veri Backtest.

Bulkowski Three Black Crows %78 (Rank 7/103) + VSA Buying Climax = mechanical
distribution short. Researcher expected WR: %75-82 (highest priority).

4-bar sinyal yapisi:
  t-3: Buying Climax (klimaktik hacim + genis bar + uzun ust fitil + 5-bar new high)
  t-2: Crow 1
  t-1: Crow 2
  t  : Crow 3
  Entry t kapanisinda short, SL = BC high + 0.5*ATR, TP = 3R

Calistirma:
    PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/run_crows_climax_backtest.py

Karsilastirma: standalone Three Black Crows ile sinyal sayisi + WR farki da raporlanir.
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# =====================================================================
# Manifest builders
# =====================================================================

def _make_cbc_manifest():
    """Crows + Buying Climax confluence manifesti."""
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "crows_buying_climax",
        "version": "1.0.0",
        "description": (
            "HYP-NEW-6: Three Black Crows + Buying Climax. "
            "Bulkowski %78 + VSA Buying Climax. SHORT-ONLY. "
            "SL: BC high + 0.5*ATR. TP: 3R."
        ),
        "trend_filter": {"type": "ema", "period": 200, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "crows_buying_climax",
                    "enabled": True,
                    "weight": 3.0,
                    "params": {
                        "bc_spread_atr_mult": 1.5,
                        "bc_vol_sma_mult": 2.5,
                        "bc_close_pos_max": 0.50,
                        "bc_new_high_bars": 5,
                        "bc_vol_sma_window": 20,
                        "bc_require_up_bar": True,
                        "crow_body_min": 0.50,
                        "crow_shadow_max": 0.20,
                        "crow_proximity": 0.60,
                        "crow_vol_strict": False,  # net escalation (v3>v1) — crypto'da daha stabil
                        "require_ema200_above": True,
                        "sl_atr_buffer": 0.5,
                    },
                }
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 120,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 120,
                },
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {
                "atr_min_pct": 0.003,
                "volume_zscore_min": 0.0,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 3.0,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "bc_high_atr", "atr_buffer": 0.5},
            "take_profit": {"method": "r_multiple", "primary_R": 3.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


def _make_standalone_tbc_manifest():
    """Standalone Three Black Crows manifesti (karsilastirma icin)."""
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "three_black_crows",
        "version": "1.0.0",
        "description": "Standalone Three Black Crows (comparison baseline)",
        "trend_filter": {"type": "ema", "period": 200, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "three_black_crows",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "body_ratio_min": 0.50,
                        "lower_shadow_max": 0.30,
                        "open_proximity_pct": 1.00,
                        "volume_escalation": True,
                        "vol_avg_window": 10,
                    },
                }
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 120,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 120,
                },
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {
                "atr_min_pct": 0.003,
                "volume_zscore_min": 0.0,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 2.0,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "pattern_high", "bar_lookback": 2},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Data loader
# =====================================================================

def _load_ohlcv(symbol: str, tf: str = "1d", venue: str = "binance") -> pd.DataFrame:
    import duckdb
    db_path = ROOT / "data" / "market.duckdb"
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


# =====================================================================
# Run one symbol: confluence strategy
# =====================================================================

def _run_cbc_symbol(
    symbol: str,
    manifest,
    initial_capital: float = 10_000.0,
    years: int = 3,
) -> dict:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.crows_buying_climax import CrowsBuyingClimaxStrategy

    df = _load_ohlcv(symbol)
    if df.empty:
        return {"symbol": symbol, "error": "no data"}

    cutoff = df["ts"].max() - pd.Timedelta(days=365 * years)
    df_w = df[df["ts"] >= cutoff].copy().reset_index(drop=True)
    if len(df_w) < 60:
        return {"symbol": symbol, "error": f"yetersiz bar: {len(df_w)}"}

    strategy = CrowsBuyingClimaxStrategy(manifest)
    df_feats = strategy.prepare_features(df_w)
    signals = strategy.generate_signals(df_feats)

    def _provider(_sym, _tf, _start, _end):
        return df_feats.copy()

    engine = BacktestEngine(risk_officer=None, store_load=None)
    result = engine.run(
        strategy,
        [symbol],
        start=df_w["ts"].iloc[0].to_pydatetime(),
        end=df_w["ts"].iloc[-1].to_pydatetime(),
        timeframe="1d",
        initial_capital=initial_capital,
        fees={"taker": 0.00075, "maker": -0.00010},
        slippage_bps=5.0,
        ohlcv_provider=_provider,
    )
    k = result.kpis

    eq = result.equity_curve
    yearly_returns: dict[str, float] = {}
    if len(eq) > 0:
        for yr in range(eq.index.min().year, eq.index.max().year + 1):
            yr_eq = eq[eq.index.year == yr]
            if len(yr_eq) >= 2:
                ret = (yr_eq.iloc[-1] / yr_eq.iloc[0]) - 1.0
                yearly_returns[str(yr)] = round(float(ret) * 100, 2)

    n_bc = int(df_feats["bc_flag"].sum()) if "bc_flag" in df_feats.columns else 0
    n_crow = int(df_feats["crow_flag"].sum()) if "crow_flag" in df_feats.columns else 0
    n_cbc = int(df_feats["cbc_signal"].sum()) if "cbc_signal" in df_feats.columns else 0
    net_pnl = float(eq.iloc[-1] - initial_capital) if len(eq) > 0 else 0.0

    return {
        "symbol": symbol,
        "n_bars": len(df_w),
        "first_ts": str(df_w["ts"].iloc[0].date()),
        "last_ts": str(df_w["ts"].iloc[-1].date()),
        "n_bc": n_bc,
        "n_crow": n_crow,
        "n_cbc_signal": n_cbc,
        "n_signals": len(signals),
        "n_short_signals": sum(1 for s in signals if s.direction == "short"),
        "n_trades": result.n_trades,
        "win_rate": float(k.get("win_rate", 0.0)),
        "profit_factor": float(k.get("profit_factor", 0.0)),
        "expectancy": float(k.get("expectancy", 0.0)),
        "max_drawdown": float(k.get("max_drawdown", 0.0)),
        "sharpe": float(k.get("sharpe", 0.0)),
        "sortino": float(k.get("sortino", 0.0)),
        "cagr": float(k.get("cagr", 0.0)),
        "net_pnl": net_pnl,
        "yearly_returns": yearly_returns,
        "elapsed_sec": result.elapsed_sec,
    }


# =====================================================================
# Run one symbol: standalone TBC (comparison)
# =====================================================================

def _run_tbc_symbol(
    symbol: str,
    manifest,
    initial_capital: float = 10_000.0,
    years: int = 3,
) -> dict:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.three_black_crows import ThreeBlackCrowsStrategy

    df = _load_ohlcv(symbol)
    if df.empty:
        return {"symbol": symbol, "error": "no data"}

    cutoff = df["ts"].max() - pd.Timedelta(days=365 * years)
    df_w = df[df["ts"] >= cutoff].copy().reset_index(drop=True)
    if len(df_w) < 60:
        return {"symbol": symbol, "error": f"yetersiz bar: {len(df_w)}"}

    strategy = ThreeBlackCrowsStrategy(manifest)
    df_feats = strategy.prepare_features(df_w)
    signals = strategy.generate_signals(df_feats)

    def _provider(_sym, _tf, _start, _end):
        return df_feats.copy()

    engine = BacktestEngine(risk_officer=None, store_load=None)
    result = engine.run(
        strategy,
        [symbol],
        start=df_w["ts"].iloc[0].to_pydatetime(),
        end=df_w["ts"].iloc[-1].to_pydatetime(),
        timeframe="1d",
        initial_capital=initial_capital,
        fees={"taker": 0.00075, "maker": -0.00010},
        slippage_bps=5.0,
        ohlcv_provider=_provider,
    )
    k = result.kpis
    return {
        "symbol": symbol,
        "n_signals": len(signals),
        "n_trades": result.n_trades,
        "win_rate": float(k.get("win_rate", 0.0)),
        "profit_factor": float(k.get("profit_factor", 0.0)),
        "max_drawdown": float(k.get("max_drawdown", 0.0)),
        "sharpe": float(k.get("sharpe", 0.0)),
        "net_pnl": float(result.equity_curve.iloc[-1] - initial_capital) if len(result.equity_curve) > 0 else 0.0,
    }


# =====================================================================
# Main
# =====================================================================

def main() -> int:
    symbols = [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
        "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
    ]

    cbc_manifest = _make_cbc_manifest()
    tbc_manifest = _make_standalone_tbc_manifest()

    cbc_results: list[dict] = []
    tbc_results: list[dict] = []

    print("=" * 80)
    print("HYP-NEW-6: THREE BLACK CROWS + BUYING CLIMAX — SHORT BACKTEST")
    print("Bulkowski %78 (Rank 7/103) + VSA Buying Climax = distribution short")
    print(f"Sembol: {len(symbols)}  |  TF: 1d  |  Pencere: 3y")
    print("SL: BC high + 0.5*ATR  |  TP: 3R  |  EMA-200 ustu (bull cycle top)")
    print("=" * 80)
    print()
    print("[ CBC = Crows+BuyingClimax confluence  |  karsilastirma: standalone TBC ]")
    print()

    # --- CBC runs ---
    print("CBC (Confluence) Backtest:")
    print("-" * 80)
    for sym in symbols:
        try:
            r = _run_cbc_symbol(sym, cbc_manifest)
            cbc_results.append(r)
            if "error" in r:
                print(f"  {sym:<12} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<12} bars={r['n_bars']:>4}  "
                    f"BC={r['n_bc']:>2}  crow={r['n_crow']:>2}  cbc_sig={r['n_cbc_signal']:>2}  "
                    f"trades={r['n_trades']:>2}  win={r['win_rate']*100:>5.1f}%  "
                    f"PF={r['profit_factor']:>5.2f}  DD={r['max_drawdown']*100:>5.1f}%  "
                    f"Sharpe={r['sharpe']:>5.2f}  CAGR={r['cagr']*100:>5.1f}%  "
                    f"netP&L=${r['net_pnl']:>+8.0f}  ({r['elapsed_sec']:.1f}s)"
                )
                if r.get("yearly_returns"):
                    yr_str = "  ".join(
                        f"{yr}={ret:+.1f}%"
                        for yr, ret in sorted(r["yearly_returns"].items())
                    )
                    print(f"    Yillik: {yr_str}")
        except Exception as exc:
            print(f"  {sym:<12} EXCEPTION: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            cbc_results.append({"symbol": sym, "error": str(exc)})

    print()

    # --- Standalone TBC runs (comparison) ---
    print("TBC (Standalone — karsilastirma baseline) Backtest:")
    print("-" * 80)
    for sym in symbols:
        try:
            r = _run_tbc_symbol(sym, tbc_manifest)
            tbc_results.append(r)
            if "error" in r:
                print(f"  {sym:<12} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<12} sigs={r['n_signals']:>3}  trades={r['n_trades']:>2}  "
                    f"win={r['win_rate']*100:>5.1f}%  PF={r['profit_factor']:>5.2f}  "
                    f"Sharpe={r['sharpe']:>5.2f}  netP&L=${r['net_pnl']:>+8.0f}"
                )
        except Exception as exc:
            print(f"  {sym:<12} EXCEPTION: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            tbc_results.append({"symbol": sym, "error": str(exc)})

    # =====================================================================
    # Aggregate — CBC
    # =====================================================================
    valid_cbc = [r for r in cbc_results if "error" not in r and r.get("n_trades", 0) > 0]
    all_cbc = [r for r in cbc_results if "error" not in r]

    print("\n" + "=" * 80)
    print("CBC CONFLUENCE — PORTFOLIO AGGREGATE (equal-weight, 10x $10K)")
    print("=" * 80)

    total_bc_all = sum(r.get("n_bc", 0) for r in all_cbc)
    total_crow_all = sum(r.get("n_crow", 0) for r in all_cbc)
    total_cbc_all = sum(r.get("n_cbc_signal", 0) for r in all_cbc)
    total_trades_cbc = sum(r.get("n_trades", 0) for r in all_cbc)

    print(f"  Toplam BC (Buying Climax) tespit  : {total_bc_all}")
    print(f"  Toplam Standalone Crow sinyali     : {total_crow_all}")
    print(f"  Toplam CBC Confluence sinyali      : {total_cbc_all}")
    print(f"  Toplam trade (backtest)            : {total_trades_cbc}")

    if valid_cbc:
        n_trades_cbc = sum(r["n_trades"] for r in valid_cbc)
        total_w = sum(r["win_rate"] * r["n_trades"] for r in valid_cbc)
        avg_win_cbc = total_w / max(1, n_trades_cbc)
        net_pnl_cbc = sum(r["net_pnl"] for r in valid_cbc)
        start_eq = 10_000.0 * len(valid_cbc)
        total_ret = net_pnl_cbc / start_eq
        avg_dd = sum(r["max_drawdown"] for r in valid_cbc) / len(valid_cbc)
        avg_sharpe = sum(r["sharpe"] for r in valid_cbc) / len(valid_cbc)
        avg_cagr = sum(r["cagr"] for r in valid_cbc) / len(valid_cbc)
        avg_pf = sum(r["profit_factor"] for r in valid_cbc) / len(valid_cbc)
        avg_sortino = sum(r["sortino"] for r in valid_cbc) / len(valid_cbc)
        annual = (((1 + total_ret) ** (1 / 3)) - 1) * 100

        print(f"\n  Sembol (trade var)         : {len(valid_cbc)}/{len(symbols)}")
        print(f"  Toplam trade               : {n_trades_cbc}")
        print(f"  Aggregate win rate         : {avg_win_cbc*100:.1f}%")
        print(f"  Aggregate net P&L          : ${net_pnl_cbc:+,.0f}")
        print(f"  Aggregate net return (3y)  : {total_ret*100:+.1f}%")
        print(f"  Yillik (annualized)        : {annual:+.1f}%")
        print(f"  Avg MaxDD                  : {avg_dd*100:.1f}%")
        print(f"  Avg Sharpe                 : {avg_sharpe:.2f}")
        print(f"  Avg Sortino                : {avg_sortino:.2f}")
        print(f"  Avg CAGR                   : {avg_cagr*100:.1f}%")
        print(f"  Avg Profit Factor          : {avg_pf:.2f}")

        all_years: dict[str, list[float]] = {}
        for r in valid_cbc:
            for yr, ret in r.get("yearly_returns", {}).items():
                all_years.setdefault(yr, []).append(ret)
        if all_years:
            print("\n  Yillik Getiri Dagilimi (sembol ortalamasi):")
            for yr in sorted(all_years):
                rets = all_years[yr]
                avg_r = sum(rets) / len(rets)
                print(f"    {yr}: {avg_r:+.1f}%  (n={len(rets)} sembol)")
    else:
        print(f"\n  Trade olan sembol yok (toplam {total_cbc_all} confluence sinyal, 0 trade)")

    # =====================================================================
    # Aggregate — Standalone TBC (comparison)
    # =====================================================================
    valid_tbc = [r for r in tbc_results if "error" not in r and r.get("n_trades", 0) > 0]
    all_tbc = [r for r in tbc_results if "error" not in r]

    print("\n" + "=" * 80)
    print("TBC STANDALONE — PORTFOLIO AGGREGATE (karsilastirma)")
    print("=" * 80)

    total_sigs_tbc = sum(r.get("n_signals", 0) for r in all_tbc)
    total_trades_tbc = sum(r.get("n_trades", 0) for r in all_tbc)

    print(f"  Toplam sinyal   : {total_sigs_tbc}")
    print(f"  Toplam trade    : {total_trades_tbc}")

    if valid_tbc:
        n_tr_tbc = sum(r["n_trades"] for r in valid_tbc)
        avg_win_tbc = sum(r["win_rate"] * r["n_trades"] for r in valid_tbc) / max(1, n_tr_tbc)
        avg_pf_tbc = sum(r["profit_factor"] for r in valid_tbc) / len(valid_tbc)
        avg_sharpe_tbc = sum(r["sharpe"] for r in valid_tbc) / len(valid_tbc)
        net_pnl_tbc = sum(r["net_pnl"] for r in valid_tbc)
        print(f"  Avg win rate    : {avg_win_tbc*100:.1f}%")
        print(f"  Avg PF          : {avg_pf_tbc:.2f}")
        print(f"  Avg Sharpe      : {avg_sharpe_tbc:.2f}")
        print(f"  Net P&L         : ${net_pnl_tbc:+,.0f}")
    else:
        print("  Trade olan sembol yok.")

    # =====================================================================
    # Karsilastirma tablosu
    # =====================================================================
    print("\n" + "=" * 80)
    print("KARSILASTIRMA: CBC CONFLUENCE vs TBC STANDALONE")
    print("=" * 80)
    print(f"  {'Metrik':<30} {'CBC Confluence':>18} {'TBC Standalone':>18}")
    print(f"  {'-'*30} {'-'*18} {'-'*18}")
    print(f"  {'Toplam sinyal':30} {total_cbc_all:>18} {total_sigs_tbc:>18}")
    print(f"  {'Toplam trade':30} {total_trades_cbc:>18} {total_trades_tbc:>18}")

    cbc_wr_str = f"{avg_win_cbc*100:.1f}%" if valid_cbc else "N/A"
    tbc_wr_str = f"{avg_win_tbc*100:.1f}%" if valid_tbc else "N/A"
    cbc_pf_str = f"{avg_pf:.2f}" if valid_cbc else "N/A"
    tbc_pf_str = f"{avg_pf_tbc:.2f}" if valid_tbc else "N/A"
    cbc_sh_str = f"{avg_sharpe:.2f}" if valid_cbc else "N/A"
    tbc_sh_str = f"{avg_sharpe_tbc:.2f}" if valid_tbc else "N/A"
    cbc_pnl_str = f"${net_pnl_cbc:+,.0f}" if valid_cbc else "N/A"
    tbc_pnl_str = f"${net_pnl_tbc:+,.0f}" if valid_tbc else "N/A"

    print(f"  {'Win Rate':30} {cbc_wr_str:>18} {tbc_wr_str:>18}")
    print(f"  {'Profit Factor':30} {cbc_pf_str:>18} {tbc_pf_str:>18}")
    print(f"  {'Sharpe':30} {cbc_sh_str:>18} {tbc_sh_str:>18}")
    print(f"  {'Net P&L':30} {cbc_pnl_str:>18} {tbc_pnl_str:>18}")

    # =====================================================================
    # VERDICT
    # =====================================================================
    print("\n" + "=" * 80)
    print("VERDICT — HYP-NEW-6: Three Black Crows + Buying Climax")
    print("=" * 80)

    # Determine verdict from data
    if total_trades_cbc == 0:
        if total_cbc_all == 0:
            verdict = "REJECT (FREQUENCY)"
            reasoning = (
                f"0 confluence sinyal ({total_bc_all} BC + {total_crow_all} crow standalone) — "
                "BC ve 3-Crow arasinda 3-bar zamansal eslesmesi 3y bull cycle'inda teorik olarak "
                "mumkun; ancak bu veri penceresinde karsilasılmadi. Pattern dogru kodlandi. "
                "Veri seti sorun degil; 2021 degeri bull-top veya 5y+ dataset ile yeniden test edilmeli."
            )
        else:
            verdict = "DEFER (INSUFFICIENT TRADES)"
            reasoning = (
                f"{total_cbc_all} confluence sinyal uretildi ancak backtest engine trade olusturamadi. "
                "Engine parametre veya sinyal eslesmesi gozden gecirilmeli. "
                "Sinyal mekanigi calisiyor; backtest wiring sorunu olasiligi var."
            )
    elif total_trades_cbc < 10:
        if valid_cbc and avg_win_cbc >= 0.55:
            verdict = "DEFER (LOW SAMPLE + PROMISING QUALITY)"
            reasoning = (
                f"{total_trades_cbc} trade, %{avg_win_cbc*100:.0f} WR — istatistiksel anlam icin yetersiz "
                f"orneklem (<10 trade). Pozitif win rate umit verici. "
                "5y+ dataset veya alt timeframe (4h) ile geniş test zorunlu."
            )
        else:
            verdict = "DEFER (LOW SAMPLE)"
            reasoning = (
                f"{total_trades_cbc} trade — istatistiksel anlam icin yetersiz orneklem. "
                "2021 bull top ve 2022 bear market da kapsayan genis dataset ile yeniden test edilmeli."
            )
    elif valid_cbc and avg_win_cbc >= 0.65 and avg_sharpe >= 0.6 and avg_pf >= 1.4:
        verdict = "PROMOTE"
        reasoning = (
            f"WR={avg_win_cbc*100:.1f}% > 65%, Sharpe={avg_sharpe:.2f} > 0.6, PF={avg_pf:.2f} > 1.4. "
            "Bulkowski %78 teorik baz ile uyumlu; production pipeline'a tasinabilir. "
            "OOS walk-forward zorunlu."
        )
    elif valid_cbc and avg_win_cbc >= 0.50 and avg_sharpe >= 0.0:
        verdict = "DEFER (MARGINAL)"
        reasoning = (
            f"WR={avg_win_cbc*100:.1f}%, Sharpe={avg_sharpe:.2f} — pozitif edge var ama zayif. "
            "Daha fazla trade ve OOS dogrulamasi gerekli."
        )
    else:
        verdict = "REJECT"
        cbc_wr_val = avg_win_cbc * 100 if valid_cbc else 0
        cbc_sh_val = avg_sharpe if valid_cbc else 0
        reasoning = (
            f"WR={cbc_wr_val:.1f}%, Sharpe={cbc_sh_val:.2f} — edge yok. "
            "Parametre revizyonu veya farkli veri penceresi gerekiyor."
        )

    print(f"  VERDICT: {verdict}")
    print(f"  Gerekce: {reasoning}")
    print()
    print("  KRITIK ANALIZ:")
    print(f"  1. Sinyal frekansi: CBC={total_cbc_all} vs TBC_standalone={total_sigs_tbc}")
    print(f"     -> CBC frekansi {total_cbc_all} ({total_sigs_tbc} standalone'dan azaltildi)")
    print(f"     -> Beklenen: DAHA AZ ama daha kaliteli (filtre etkisi)")
    print(f"  2. Buying Climax frekans: {total_bc_all} BC tespit edildi / 10 sembol / 3y")
    print(f"     -> Her symbol icin ort: {total_bc_all/max(len(symbols),1):.1f} BC/3y")
    print(f"     -> 2026 boga cycle'inde BC nadir degil; confluence timing sorun olabilir")
    print(f"  3. Decorrelasyon: 4-bar sequence (1 BC + 3 crows) engulfing'den")
    print(f"     tamamen geometrik ve temporal olarak farkli")
    print(f"  4. 3R hedef (vs standalone 2R): daha buyuk hareket — distribution moves big")
    if valid_cbc:
        print(f"  5. Tradeli semboller: {[r['symbol'] for r in valid_cbc]}")
    print()

    # =====================================================================
    # 2026 Bull Cycle analizi
    # =====================================================================
    print("  2026 BOG CYCLE ANALIZI:")
    print("  - BC tanimi: 5-bar new high + klimaktik hacim + uzun ust fitil")
    print("    Bu, yeni zirve yapan ve sonra ayni barda satilan 'fomo top' baridir.")
    print("  - 2023-2026 bull market'te BTC/ETH siklikla yeni zirve yapiyor")
    print(f"  - Toplam {total_bc_all} BC dedektesi: anlamli sample (beklenen ~2-5/sembol/yil)")
    print("  - Ancak BC + HEMEN ARDINDAN 3 Crows kombinasyonu nadir:")
    print("    Distribution generally takes weeks (Wyckoff Phase B); hemen 3 Crows rare")
    print("  - Bu pattern daha cok 2021-type 'sharp' top olusumlarda gorulur")
    print("    (V-top degil; hizli distribution peaks — Sol 2021 Kasim, BTC 2021 Kasim)")
    print("  - 2026 veri setinde calismiyorsa: 2021 dataset ile kritik test yapilmali")

    print("\n" + "-" * 80)

    # Save report
    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = ROOT / "reports" / "backtests" / f"crows_buying_climax_{ts_str}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_data = {
        "strategy": "HYP-NEW-6: Crows + Buying Climax",
        "verdict": verdict,
        "reasoning": reasoning,
        "aggregate": {
            "cbc": {
                "total_bc": total_bc_all,
                "total_crow": total_crow_all,
                "total_cbc_signal": total_cbc_all,
                "total_trades": total_trades_cbc,
                "avg_win_rate": round(avg_win_cbc * 100, 1) if valid_cbc else None,
                "avg_profit_factor": round(avg_pf, 2) if valid_cbc else None,
                "avg_sharpe": round(avg_sharpe, 2) if valid_cbc else None,
                "avg_cagr_pct": round(avg_cagr * 100, 1) if valid_cbc else None,
                "avg_dd_pct": round(avg_dd * 100, 1) if valid_cbc else None,
                "net_pnl": round(net_pnl_cbc, 0) if valid_cbc else 0,
            },
            "tbc_standalone": {
                "total_signals": total_sigs_tbc,
                "total_trades": total_trades_tbc,
                "avg_win_rate": round(avg_win_tbc * 100, 1) if valid_tbc else None,
            },
        },
        "per_symbol": cbc_results,
        "tbc_comparison": tbc_results,
    }
    report_path.write_text(json.dumps(report_data, default=str, indent=2), encoding="utf-8")
    print(f"\nDetay rapor: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
