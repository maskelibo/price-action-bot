"""Düşük volatilite stratejilerinin backtesti.

User: 'Dar piyasalarda iş yapacak bir bot yapsana, volatilite düşük
piyasalarda para kazanmak için.'

Test edilecek 8 düşük-vol kandidatı:
  1. bollinger_squeeze_breakout — BB darlık + breakout
  2. session_vwap_mean_reversion — Session VWAP geri çekilme
  3. naked_poc_mr — Volume Profile POC mean rev
  4. tpo_value_area — TPO value area extremes
  5. inside_day_failure — Inside bar pattern (low vol)
  6. liquidation_fade — Likidite avı fade
  7. cvd_spike_fade — CVD spike fade (range)
  8. bollinger_fade_mr — BB outer band mean rev

Karşılaştırma: live bot (vsa) ve v63 (rsi2) — ikisi de high-vol ortamlarda iyi.

Çıktı: tablo + en iyi 3 için iterate_targets.json'a manuel ekle.
"""
from __future__ import annotations
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
os.environ.setdefault("PA_LOG_QUIET", "1")
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
import logging
logging.getLogger("price_action").setLevel(logging.ERROR)
import pandas as pd
from datetime import datetime, timezone

from iterate_rsi2_variants import SYMBOLS, _load_ohlcv, _exit_with_be, _compute_metrics
from iterate_rsi2_v4 import _equity_with_loss_pause
from price_action.strategies.base import StrategyManifest


# Düşük-vol strateji adayları
LOW_VOL_STRATEGIES = [
    ("bollinger_squeeze_breakout", "BollingerSqueezeBreakoutStrategy", "BB squeeze + breakout"),
    ("session_vwap_mean_reversion", "SessionVWAPMeanReversionStrategy", "VWAP geri çekilme"),
    ("naked_poc_mr",                "NakedPOCMRStrategy",                "POC mean rev"),
    ("tpo_value_area",              "TPOValueAreaStrategy",              "Value Area extremes"),
    ("inside_day_failure",          "InsideDayFailureStrategy",          "Inside bar pattern"),
    ("liquidation_fade",            "LiquidationFadeStrategy",           "Likidite avı"),
    ("cvd_spike_fade",              "CVDSpikeFadeStrategy",              "CVD spike fade"),
    ("bollinger_fade_mr",           "BollingerFadeMRStrategy",           "BB outer mean rev"),
]


def test_strategy(module_name: str, class_name: str) -> dict:
    """Tek strategy backtest et."""
    try:
        mod = __import__(f"price_action.strategies.{module_name}", fromlist=[class_name])
        StrategyClass = getattr(mod, class_name)
    except (ImportError, AttributeError) as e:
        return {"status": "IMPORT_FAIL", "err": str(e)[:100]}

    manifest = StrategyManifest(name=module_name, version="low-vol-test")
    try:
        strategy = StrategyClass(manifest)
    except Exception as e:
        return {"status": "INIT_FAIL", "err": str(e)[:120]}

    all_trades = []
    n_signals = 0
    for sym in SYMBOLS:
        df = _load_ohlcv(sym, "15m")
        if df.empty:
            continue
        try:
            df_feats = strategy.prepare_features(df)
            signals = strategy.generate_signals(df_feats)
        except Exception:
            continue
        n_signals += len(signals)
        df_feats = df_feats.reset_index(drop=True)
        for sig in signals:
            sig_idx = df_feats.index[df_feats["ts"] == sig.ts]
            if len(sig_idx) == 0:
                continue
            i0 = sig_idx[0]
            if i0 >= len(df_feats) - 1:
                continue
            entry = float(df_feats["close"].iloc[i0])
            R, exit_price, exit_offset = _exit_with_be(
                df_feats, i0, entry, sig.sl_price,
                tp_r=1.5, direction=sig.direction,
            )
            all_trades.append({
                "entry_ts": sig.ts,
                "exit_ts": df_feats["ts"].iloc[i0 + exit_offset] if i0 + exit_offset < len(df_feats) else df_feats["ts"].iloc[-1],
                "R": float(R),
                "symbol": sym,
            })

    if not all_trades:
        return {"status": "NO_TRADES", "n_signals": n_signals}

    trades_df = pd.DataFrame(all_trades)
    # Baseline equity: risk=0.005, no halts, no concurrent cap (raw potential)
    eq, final_eq, n_taken = _equity_with_loss_pause(
        trades_df, risk_pct=0.005, max_concurrent=999, consecutive_loss_pause=None
    )
    m = _compute_metrics(eq, 10_000.0)
    return {
        "status": "OK",
        "n_trades_raw": len(trades_df),
        "n_taken": n_taken,
        "monthly_roi": m["monthly_roi"],
        "max_dd": m["max_dd"],
        "neg_count": m["neg_count"],
        "total_months": m["total_months"],
        "annualized": m["annualized"],
        "worst_month": m["worst_month"],
    }


def main() -> int:
    print("=== Düşük Vol Strateji Adayları ===")
    print()
    print(f"{'Strateji':35} {'Açıklama':28} {'aylık':>8} {'neg':>7} {'DD':>8} {'yıllık':>10} {'n':>6}")
    print("-" * 115)
    print(f"{'🟢 LIVE (vsa_climax_test)':35} {'high-vol trend':28} {'+12.99%':>8} {'4/61':>7} {'-15.48%':>8} {'+329%':>10} {'4458':>6}  baseline")
    print(f"{'🏆 v63 (rsi2)':35} {'high-vol mean rev':28} {'+20.08%':>8} {'11/61':>7} {'-16.95%':>8} {'+640%':>10} {'4610':>6}  rescue")
    print("-" * 115)

    results = []
    for module, cls, desc in LOW_VOL_STRATEGIES:
        r = test_strategy(module, cls)
        if r["status"] == "OK":
            promote = (r["monthly_roi"] >= 5.0 and r["max_dd"] >= -25.0)
            elite = (r["monthly_roi"] >= 10.0 and r["max_dd"] >= -20.0)
            flag = "🏆 ELITE" if elite else ("✅ promote" if promote else (
                "🟡 marg" if r["monthly_roi"] > 0 else "❌"))
            print(f"{module[:35]:35} {desc[:28]:28} "
                  f"{r['monthly_roi']:>+7.2f}% "
                  f"{r['neg_count']:>2}/{r['total_months']:<3} "
                  f"{r['max_dd']:>+7.2f}% "
                  f"{r['annualized']:>+9.2f}% "
                  f"{r['n_taken']:>6}  {flag}")
        else:
            print(f"{module[:35]:35} {desc[:28]:28} {r['status']} {r.get('err','')[:30]}")
        results.append({"module": module, "class": cls, "desc": desc, **r})

    # Sırala — best by monthly_roi
    viable = [r for r in results if r.get("status") == "OK" and r.get("monthly_roi", -999) > 0]
    viable.sort(key=lambda r: r["monthly_roi"], reverse=True)

    print()
    if viable:
        print("=== EN İYİ POZİTİF EDGE (iterate yapılması gereken) ===")
        for r in viable[:3]:
            print(f"  {r['module']:35} aylık +{r['monthly_roi']:.2f}% DD {r['max_dd']:.2f}% — iterate ile rescue edilebilir")

    # JSON dump
    out_path = ROOT / "memory" / "researcher" / "realistic_backtest_results" / "low-vol-strategy-survey.json"
    out_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nDetay: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
