"""Per-sembol gerçekçi slippage backtest — EngulfingContinuation baseline'ı.

Görevler:
1. Her sembol için Binance orderbook'tan live slippage ölç (1 snapshot/sembol)
2. Flat 5bps baseline ile gerçekçi per-sembol slippage karşılaştır
3. Yıllık %1.6 → gerçekçi %? hesapla
4. Sembol eleme önerisi: hangileri atılmalı?

Çalıştırma:
    PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/run_realistic_slippage_backtest.py

Live API olmadan çalışmak için:
    PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/run_realistic_slippage_backtest.py --no-live
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
]

INITIAL_CAPITAL = 10_000.0
FEES = {"taker": 0.00075, "maker": -0.00010}
FLAT_SLIPPAGE_BPS = 5.0   # mevcut baseline


# ---------------------------------------------------------------------------
# Manifest (EngulfingContinuation — run_engulfing_backtest.py ile özdeş)
# ---------------------------------------------------------------------------

def _make_manifest():
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "engulfing_continuation",
        "version": "1.0.0",
        "description": "Engulfing bar after 20-EMA pullback in established trend",
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {"id": "bullish_engulfing_cont", "enabled": True, "weight": 1.5,
                 "params": {"body_ratio_min": 0.6, "pullback_window": 10, "pullback_touch_atr": 0.5}},
                {"id": "bearish_engulfing_cont", "enabled": True, "weight": 1.5,
                 "params": {"body_ratio_min": 0.6, "pullback_window": 10, "pullback_touch_atr": 0.5}},
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 120, "cluster_atr_multiplier": 0.5,
                    "min_touches": 2, "max_age_bars": 120,
                },
                "require_proximity_to_sr_atr": 0.5,
            },
            "filters": {
                "atr_min_pct": 0.005, "volume_zscore_min": 0.0,
                "kaufman_er_period": 14, "kaufman_er_min": 0.20,
                "bear_regime_size_factor": 0.5,
            },
            "confluence": {"method": "weighted_sum", "min_score": 1.5, "bonus_if_at_sr": 0.5},
        },
        "risk": {
            "stop_loss": {"method": "structural", "swing_lookback": 10},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# ---------------------------------------------------------------------------
# Data loader
# ---------------------------------------------------------------------------

def _load_symbol_ohlcv(symbol: str, tf: str = "1d", venue: str = "binance"):
    import duckdb
    import pandas as pd
    con = duckdb.connect(str(ROOT / "data" / "market.duckdb"), read_only=True)
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


# ---------------------------------------------------------------------------
# Single symbol runner — hem flat hem realistic slippage ile çalıştır
# ---------------------------------------------------------------------------

def _run_one_symbol(
    symbol: str,
    manifest,
    slippage_bps: float,
    symbol_slippage_map: Dict[str, float] | None = None,
) -> dict:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy

    df = _load_symbol_ohlcv(symbol, tf="1d")
    if df.empty:
        return {"symbol": symbol, "error": "no data"}

    strategy = EngulfingContinuationStrategy(manifest)
    df_feats = strategy.prepare_features(df)
    signals = strategy.generate_signals(df_feats)

    def ohlcv_provider(_sym, _tf, _start, _end):
        return df_feats.copy()

    engine = BacktestEngine(risk_officer=None, store_load=None)
    result = engine.run(
        strategy,
        [symbol],
        start=df["ts"].iloc[0].to_pydatetime(),
        end=df["ts"].iloc[-1].to_pydatetime(),
        timeframe="1d",
        initial_capital=INITIAL_CAPITAL,
        fees=FEES,
        slippage_bps=slippage_bps,
        symbol_slippage_map=symbol_slippage_map or {},
        ohlcv_provider=ohlcv_provider,
    )
    k = result.kpis
    _cagr = float(k.get("cagr", 0.0))
    _raw_net = float(k.get("net_pnl", 0.0))
    _net_pnl = _raw_net if _raw_net != 0.0 else INITIAL_CAPITAL * ((1 + _cagr) ** 3 - 1)
    return {
        "symbol": symbol,
        "n_bars": len(df),
        "n_signals": len(signals),
        "n_trades": result.n_trades,
        "win_rate": float(k.get("win_rate", 0.0)),
        "profit_factor": float(k.get("profit_factor", 0.0)),
        "max_drawdown": float(k.get("max_drawdown", 0.0)),
        "sharpe": float(k.get("sharpe", 0.0)),
        "cagr": _cagr,
        "net_pnl": _net_pnl,
        "elapsed_sec": result.elapsed_sec,
    }


# ---------------------------------------------------------------------------
# Aggregate helper
# ---------------------------------------------------------------------------

def _aggregate(results: List[dict]) -> dict:
    valid = [r for r in results if "error" not in r and r.get("n_trades", 0) > 0]
    if not valid:
        return {"n_symbols": 0}
    n_trades = sum(r["n_trades"] for r in valid)
    avg_win = sum(r["win_rate"] * r["n_trades"] for r in valid) / max(1, n_trades)
    net_pnl = sum(r["net_pnl"] for r in valid)
    starting = INITIAL_CAPITAL * len(valid)
    total_return = net_pnl / starting
    annual = (((1 + total_return) ** (1 / 3)) - 1) * 100
    return {
        "n_symbols": len(valid),
        "n_trades": n_trades,
        "avg_win_rate_pct": round(avg_win * 100, 2),
        "net_pnl": round(net_pnl, 2),
        "total_return_pct": round(total_return * 100, 2),
        "annual_return_pct": round(annual, 2),
        "avg_max_drawdown_pct": round(sum(r["max_drawdown"] for r in valid) / len(valid) * 100, 2),
        "avg_sharpe": round(sum(r["sharpe"] for r in valid) / len(valid), 3),
        "avg_cagr_pct": round(sum(r["cagr"] for r in valid) / len(valid) * 100, 2),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-live", action="store_true",
                        help="Live orderbook çekmeden fallback slippage kullan")
    parser.add_argument("--notional", type=float, default=5_000.0,
                        help="Referans emir büyüklügü USD (default 5000)")
    args = parser.parse_args()

    use_live = not args.no_live
    notional = args.notional

    # ── 1. Slippage map ────────────────────────────────────────────────────
    from price_action.backtest.slippage import build_slippage_map, SlippageModel, FALLBACK_SLIPPAGE_BPS

    print("=" * 72)
    print(f"ADIM 1: Per-Sembol Slippage Olcumu (live={use_live}, notional=${notional:,.0f})")
    print("=" * 72)

    bps_at_1k = build_slippage_map(SYMBOLS, notional_ref=1_000, use_live=use_live)
    model = SlippageModel(
        symbol_slippage_map=bps_at_1k,
        default_bps=15.0,
        notional=notional,
    )
    slip_table = model.summary()

    # Sembol slippage map notional bazında (production lot)
    symbol_slip_map = {row["symbol"]: model.get_bps(row["symbol"], notional) for row in slip_table}

    print(f"\n  {'SYMBOL':<12} {'1K bps':>8} {'5K bps':>8} {'10K bps':>9} {'Kat':>10} {'vs flat 5bps':>13}")
    print("  " + "-" * 65)
    for row in slip_table:
        sym = row["symbol"]
        bps_1k = row["spread_bps_1k"]
        bps_5k = row["slippage_bps_5k"]
        bps_10k = row["slippage_bps_10k"]
        cat = row["category"]
        vs_flat = symbol_slip_map[sym] - FLAT_SLIPPAGE_BPS
        print(f"  {sym:<12} {bps_1k:>8.2f} {bps_5k:>8.2f} {bps_10k:>9.2f} {cat:>10} {vs_flat:>+12.2f}bps")

    # ── 2. Backtest: Flat 5bps baseline ───────────────────────────────────
    print("\n" + "=" * 72)
    print(f"ADIM 2: Backtest — FLAT {FLAT_SLIPPAGE_BPS}bps (mevcut baseline)")
    print("=" * 72)

    manifest = _make_manifest()
    flat_results: list[dict] = []
    for sym in SYMBOLS:
        try:
            r = _run_one_symbol(sym, manifest, slippage_bps=FLAT_SLIPPAGE_BPS, symbol_slippage_map=None)
            flat_results.append(r)
            if "error" in r:
                print(f"  {sym:<12} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<12} trades={r['n_trades']:>3} "
                    f"win={r['win_rate']*100:>5.1f}% "
                    f"CAGR={r['cagr']*100:>+6.1f}% "
                    f"netP&L={r['net_pnl']:>+8.0f}"
                )
        except Exception as exc:
            print(f"  {sym:<12} EXCEPTION: {exc}")
            traceback.print_exc()
            flat_results.append({"symbol": sym, "error": str(exc)})

    flat_agg = _aggregate(flat_results)

    # ── 3. Backtest: Gerçekçi per-sembol slippage ─────────────────────────
    print("\n" + "=" * 72)
    print(f"ADIM 3: Backtest — REALISTIC per-sembol slippage (notional=${notional:,.0f})")
    print("=" * 72)

    realistic_results: list[dict] = []
    for sym in SYMBOLS:
        try:
            r = _run_one_symbol(
                sym, manifest,
                slippage_bps=FLAT_SLIPPAGE_BPS,     # fallback (map override eder)
                symbol_slippage_map=symbol_slip_map,
            )
            realistic_results.append(r)
            sym_bps = symbol_slip_map.get(sym, FLAT_SLIPPAGE_BPS)
            if "error" in r:
                print(f"  {sym:<12} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<12} [{sym_bps:>5.1f}bps] "
                    f"trades={r['n_trades']:>3} "
                    f"win={r['win_rate']*100:>5.1f}% "
                    f"CAGR={r['cagr']*100:>+6.1f}% "
                    f"netP&L={r['net_pnl']:>+8.0f}"
                )
        except Exception as exc:
            print(f"  {sym:<12} EXCEPTION: {exc}")
            traceback.print_exc()
            realistic_results.append({"symbol": sym, "error": str(exc)})

    real_agg = _aggregate(realistic_results)

    # ── 4. Karşılaştırma tablosu ──────────────────────────────────────────
    print("\n" + "=" * 72)
    print("ADIM 4: Before/After Karsilastirmasi")
    print("=" * 72)
    print(f"\n  {'METRIK':<28} {'FLAT 5bps':>12} {'REALISTIC':>12} {'DELTA':>10}")
    print("  " + "-" * 66)

    metrics = [
        ("Yillik return %",  "annual_return_pct",     True),
        ("Toplam net P&L $", "net_pnl",                True),
        ("Avg Sharpe",       "avg_sharpe",             True),
        ("Avg CAGR %",       "avg_cagr_pct",           True),
        ("Avg Max DD %",     "avg_max_drawdown_pct",   False),
        ("Sembol sayisi",    "n_symbols",              None),
        ("Toplam trade",     "n_trades",               None),
    ]
    for label, key, higher_better in metrics:
        fv = flat_agg.get(key, 0)
        rv = real_agg.get(key, 0)
        delta = rv - fv if isinstance(fv, (int, float)) and isinstance(rv, (int, float)) else "-"
        if isinstance(delta, float):
            delta_str = f"{delta:>+.2f}"
        elif isinstance(delta, int):
            delta_str = f"{delta:>+d}"
        else:
            delta_str = str(delta)
        print(f"  {label:<28} {fv:>12}  {rv:>12} {delta_str:>10}")

    # ── 5. Per-sembol P&L değişimi ────────────────────────────────────────
    print("\n" + "=" * 72)
    print("ADIM 5: Per-Sembol P&L Degisimi (flat vs realistic)")
    print("=" * 72)
    flat_map = {r["symbol"]: r for r in flat_results if "error" not in r}
    real_map = {r["symbol"]: r for r in realistic_results if "error" not in r}

    print(f"\n  {'SYMBOL':<12} {'slip_bps':>9} {'flat P&L':>10} {'real P&L':>10} {'delta':>10} {'impact':>8}")
    print("  " + "-" * 63)

    drop_candidates = []
    for sym in SYMBOLS:
        fr = flat_map.get(sym)
        rr = real_map.get(sym)
        if fr is None or rr is None:
            continue
        sym_bps = symbol_slip_map.get(sym, FLAT_SLIPPAGE_BPS)
        delta = rr["net_pnl"] - fr["net_pnl"]
        impact_pct = delta / INITIAL_CAPITAL * 100
        print(
            f"  {sym:<12} {sym_bps:>9.1f} "
            f"{fr['net_pnl']:>+10.0f} {rr['net_pnl']:>+10.0f} "
            f"{delta:>+10.0f} {impact_pct:>+7.1f}%"
        )
        if rr["net_pnl"] < 0 or impact_pct < -1.5:
            drop_candidates.append(sym)

    # ── 6. ROI Projection $200 → 3 yıl ──────────────────────────────────
    print("\n" + "=" * 72)
    print("ADIM 6: Gercekci ROI Projeksiyonu")
    print("=" * 72)
    START_CAPITAL = 200.0
    YEARS = 3
    flat_annual = flat_agg.get("annual_return_pct", 0) / 100
    real_annual = real_agg.get("annual_return_pct", 0) / 100

    flat_final = START_CAPITAL * (1 + flat_annual) ** YEARS
    real_final = START_CAPITAL * (1 + real_annual) ** YEARS

    # Gerçekçi (konservatif) tahmin: realistic backtest'in %50'si
    # (out-of-sample decay, live cost farkı, piyasa rejimleri)
    conservative_annual = real_annual * 0.50
    conservative_final = START_CAPITAL * (1 + conservative_annual) ** YEARS

    print(f"\n  Baslangic sermayesi : ${START_CAPITAL:,.0f}")
    print(f"  Proyeksiyon suresi  : {YEARS} yil")
    print()
    print(f"  {'SENARYO':<25} {'Yillik %':>10} {'3y Final':>12} {'Kar':>10}")
    print("  " + "-" * 60)
    print(f"  {'Backtest flat 5bps':<25} {flat_annual*100:>+10.1f}% ${flat_final:>11,.0f} ${flat_final-START_CAPITAL:>+9,.0f}")
    print(f"  {'Backtest realistic':<25} {real_annual*100:>+10.1f}% ${real_final:>11,.0f} ${real_final-START_CAPITAL:>+9,.0f}")
    print(f"  {'Conservative (x0.5)':<25} {conservative_annual*100:>+10.1f}% ${conservative_final:>11,.0f} ${conservative_final-START_CAPITAL:>+9,.0f}")

    # ── 7. Drop önerileri ─────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("ADIM 7: Sembol Eleme Onerileri")
    print("=" * 72)
    print(f"\n  Yuksek slippage + negatif P&L -> ATILMALI:")
    for sym in drop_candidates:
        rr = real_map.get(sym, {})
        sym_bps = symbol_slip_map.get(sym, 0)
        print(f"    - {sym:<12} [{sym_bps:.1f}bps] realP&L={rr.get('net_pnl', 0):>+.0f}")
    if not drop_candidates:
        print("    (Hicbiri eleme esigini asmadi — tumunu tut)")

    keep_candidates = [s for s in SYMBOLS if s not in drop_candidates]
    print(f"\n  Devam edilmesi onerilen semboller ({len(keep_candidates)}):")
    for sym in keep_candidates:
        rr = real_map.get(sym, {})
        sym_bps = symbol_slip_map.get(sym, 0)
        print(f"    + {sym:<12} [{sym_bps:.1f}bps] realP&L={rr.get('net_pnl', 0):>+.0f}")

    # ── Kaydet ───────────────────────────────────────────────────────────
    report = {
        "run_ts": datetime.now(timezone.utc).isoformat(),
        "config": {
            "symbols": SYMBOLS,
            "flat_slippage_bps": FLAT_SLIPPAGE_BPS,
            "notional_ref_usd": notional,
            "use_live_orderbook": use_live,
        },
        "slippage_table": slip_table,
        "symbol_slippage_map": symbol_slip_map,
        "flat_5bps": {
            "aggregate": flat_agg,
            "per_symbol": flat_results,
        },
        "realistic": {
            "aggregate": real_agg,
            "per_symbol": realistic_results,
        },
        "roi_projection": {
            "start_capital": START_CAPITAL,
            "years": YEARS,
            "flat_annual_pct": round(flat_annual * 100, 2),
            "realistic_annual_pct": round(real_annual * 100, 2),
            "conservative_annual_pct": round(conservative_annual * 100, 2),
            "flat_final": round(flat_final, 2),
            "realistic_final": round(real_final, 2),
            "conservative_final": round(conservative_final, 2),
        },
        "drop_candidates": drop_candidates,
        "keep_candidates": keep_candidates,
    }
    report_path = (
        ROOT / "reports" / "backtests"
        / f"realistic_slippage_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, default=str, indent=2), encoding="utf-8")
    print(f"\n[Detay rapor: {report_path}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
