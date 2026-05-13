"""SEC8: Forex Dedicated Retest + Crypto+Forex Combined Portfolio.

Forex preset (configs/risk_forex.yaml): %1 risk + 30x lev + gevsek breakers.
Crypto champion (v0.9.7 BALANCED+F&G): yıllık +33.6% / DD -33% / r-adj 1.029.

Senaryolar:
  A) Forex preset standalone walk-forward (12 pencere 3y rolling)
  B) Crypto champion standalone (referans, 13 pencere)
  C) Crypto + Forex 50/50 portfoy (uncorrelated, ayri equity)
  D) Crypto + Forex 70/30 portfoy

Output: reports/lab/sec8_forex_dedicated.md
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from statistics import mean, median

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig, production_replay, _lazy_build_funding_filters
from price_action.backtest.regime import compute_btc_capitulation_halt
from scripts.sec7_forex_survey import _gather_forex
from scripts.v09_optimize_top10 import _gather, TOP_10
from scripts.v097_balanced_optimization import DROP_PAIRS, build_fng_short_skip

REPORT_OUT = ROOT / "reports" / "lab" / "sec8_forex_dedicated.md"


def main() -> None:
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = "") -> None:
        print(line)
        out_lines.append(line)

    w("# SEC8: Forex Dedicated + Crypto+Forex Combined — 2026-05-13")
    w("")
    w(f"**Generated:** {pd.Timestamp.now('UTC').isoformat()}")
    w("")

    # =========================================================
    # 1) Trade collection
    # =========================================================
    print("Crypto trade topluyor (TOP_10 × 11 sym)...")
    crypto_trades = []
    for m, c in TOP_10:
        crypto_trades.extend(_gather(m, c))
    crypto_trades.sort(key=lambda x: x["entry_ts"])
    print(f"  Crypto: {len(crypto_trades)} trade")

    print("Forex trade topluyor (TOP_10 × 3 sym)...")
    forex_trades = []
    for m, c in TOP_10:
        forex_trades.extend(_gather_forex(m, c))
    forex_trades.sort(key=lambda x: x["entry_ts"])
    print(f"  Forex: {len(forex_trades)} trade")

    w(f"**Crypto pool:** {len(crypto_trades)} trade")
    w(f"**Forex pool:** {len(forex_trades)} trade")
    w("")

    # =========================================================
    # 2) Configs
    # =========================================================
    base_bal = ProductionConfig.from_yaml("configs/risk_balanced.yaml")
    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({
        "funding_filter_enabled": True,
        "funding_aggregation_mode": "00:00_only",
    })
    fng_short_20 = build_fng_short_skip(20)
    fund_short_dict = dict(fund_short or {})
    combined_short_skip = {**fund_short_dict, **dict(fng_short_20)}

    # CHAMPION crypto
    cfg_crypto = base_bal.with_overrides(
        alt_data_skip_long=fund_long,
        alt_data_skip_short=combined_short_skip,
        drop_pairs=DROP_PAIRS,
    )

    # FOREX preset (forex_balanced.yaml hazır degil, with_overrides ile kur)
    cfg_forex = base_bal.with_overrides(
        risk_pct=0.010,
        leverage=30,
        confidence_risk_tiers=None,
        leverage_tiers=None,
        max_notional_pct_equity=None,
        daily_dd=0.10,
        weekly_dd=0.20,
        monthly_dd=0.30,
        consecutive_loss_n=999,
        same_symbol_side_cooldown_days=1,
        max_concurrent=6,
        drop_pairs=frozenset(),
        alt_data_skip_long=None,
        alt_data_skip_short=None,
        btc_halt_calendar=None,
    )

    # =========================================================
    # 3) Walk-forward windows (3y rolling, 60g step)
    # =========================================================
    crypto_start = crypto_trades[0]["entry_ts"]
    crypto_end = crypto_trades[-1]["exit_ts"]
    forex_start = forex_trades[0]["entry_ts"]
    forex_end = forex_trades[-1]["exit_ts"]
    common_start = max(crypto_start, forex_start)
    common_end = min(crypto_end, forex_end)

    w(f"**Tarih araligi:**")
    w(f"- Crypto: {crypto_start} -> {crypto_end}")
    w(f"- Forex:  {forex_start} -> {forex_end}")
    w(f"- Common: {common_start} -> {common_end}")
    w("")

    crypto_windows = []
    cur = crypto_start
    while cur + pd.Timedelta(days=3*365) <= crypto_end:
        crypto_windows.append((cur, cur + pd.Timedelta(days=3*365)))
        cur += pd.Timedelta(days=60)

    forex_windows = []
    cur = forex_start
    while cur + pd.Timedelta(days=3*365) <= forex_end:
        forex_windows.append((cur, cur + pd.Timedelta(days=3*365)))
        cur += pd.Timedelta(days=60)

    # Common windows for combined portfolio
    common_windows = []
    cur = common_start
    while cur + pd.Timedelta(days=3*365) <= common_end:
        common_windows.append((cur, cur + pd.Timedelta(days=3*365)))
        cur += pd.Timedelta(days=60)

    w(f"**Crypto windows:** {len(crypto_windows)} (3y rolling)")
    w(f"**Forex windows:**  {len(forex_windows)}")
    w(f"**Common windows:** {len(common_windows)}")
    w("")

    # =========================================================
    # 4) Per-portfolio walk-forward
    # =========================================================
    def run_walkforward(trades, cfg, windows, label):
        anns, dds = [], []
        for ws, we in windows:
            ww_t = [t for t in trades if ws <= t["entry_ts"] < we]
            r = production_replay(ww_t, cfg)
            if r is None or r.trades == 0:
                continue
            anns.append(r.annualized(3.0) * 100)
            dds.append(r.max_drawdown * 100)
        if not anns:
            return None
        return {
            "label": label,
            "n_windows": len(anns),
            "yearly_mean": mean(anns),
            "yearly_median": median(anns),
            "yearly_min": min(anns),
            "yearly_max": max(anns),
            "dd_mean": mean(dds),
            "dd_min": min(dds),
            "neg": sum(1 for a in anns if a < 0),
            "anns": anns,
            "dds": dds,
        }

    # A) Crypto champion (referans)
    print("\n[A] Crypto champion (1d, 13 pencere)...")
    res_crypto = run_walkforward(crypto_trades, cfg_crypto, crypto_windows, "Crypto Champion (v0.9.7)")

    # B) Forex preset standalone
    print("[B] Forex preset (1d, 12 pencere)...")
    res_forex = run_walkforward(forex_trades, cfg_forex, forex_windows, "Forex Preset (r%1 + lev 30x)")

    # =========================================================
    # 5) Combined portfolio (capital allocation)
    # =========================================================
    # Combined approach: 50/50 capital, ayri equity track
    # crypto $5000 ile, forex $5000 ile -- ayri replay et, equity'leri topla
    def run_combined(crypto_trades, forex_trades, cfg_c, cfg_f, c_alloc, f_alloc, windows):
        cfg_c_alloc = cfg_c.with_overrides(initial_capital=10000.0 * c_alloc)
        cfg_f_alloc = cfg_f.with_overrides(initial_capital=10000.0 * f_alloc)
        anns, dds = [], []
        for ws, we in windows:
            c_ww = [t for t in crypto_trades if ws <= t["entry_ts"] < we]
            f_ww = [t for t in forex_trades if ws <= t["entry_ts"] < we]
            r_c = production_replay(c_ww, cfg_c_alloc)
            r_f = production_replay(f_ww, cfg_f_alloc)
            if r_c is None or r_f is None:
                continue
            # Combined final equity = c.final + f.final
            final = r_c.final_equity + r_f.final_equity
            initial = 10000.0
            total_ret = final / initial - 1
            ann = (1 + total_ret) ** (1/3.0) - 1
            anns.append(ann * 100)
            # Combined DD: portfoy seviyesinde, basit yaklasim sum_DD
            # Realistic: max(c_dd, f_dd) seviye yaklasimi (portfoy DD genellikle individual DD'lerden dusuk)
            combined_dd = (r_c.max_drawdown * c_alloc + r_f.max_drawdown * f_alloc)
            dds.append(combined_dd * 100)
        if not anns:
            return None
        return {
            "label": f"Combined Crypto {int(c_alloc*100)}/{int(f_alloc*100)} Forex",
            "n_windows": len(anns),
            "yearly_mean": mean(anns),
            "yearly_median": median(anns),
            "yearly_min": min(anns),
            "yearly_max": max(anns),
            "dd_mean": mean(dds),
            "dd_min": min(dds),
            "neg": sum(1 for a in anns if a < 0),
            "anns": anns,
            "dds": dds,
        }

    print("[C] Crypto+Forex 50/50 portfoy...")
    res_5050 = run_combined(crypto_trades, forex_trades, cfg_crypto, cfg_forex, 0.5, 0.5, common_windows)

    print("[D] Crypto+Forex 70/30 portfoy...")
    res_7030 = run_combined(crypto_trades, forex_trades, cfg_crypto, cfg_forex, 0.7, 0.3, common_windows)

    # =========================================================
    # 6) Report
    # =========================================================
    w("## Sonuclar")
    w("")
    w(f"| Senaryo | n_win | Yillik | Median | Min | Max | DD | r-adj | Negatif |")
    w(f"|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    print(f"\n{'scenario':<48} {'n':>3} {'yillik':>8} {'med':>7} {'DD':>7} {'r-adj':>7} {'neg':>5}")
    print("-" * 95)

    for r in [res_crypto, res_forex, res_5050, res_7030]:
        if r is None:
            continue
        ra = r["yearly_mean"] / abs(r["dd_mean"]) if r["dd_mean"] != 0 else 0
        print(f"  {r['label']:<48} {r['n_windows']:>3} {r['yearly_mean']:>+7.1f}% {r['yearly_median']:>+5.1f}% {r['dd_mean']:>+5.1f}% {ra:>6.3f} {r['neg']:>3}/{r['n_windows']}")
        w(f"| {r['label']} | {r['n_windows']} | {r['yearly_mean']:+.1f}% | {r['yearly_median']:+.1f}% | {r['yearly_min']:+.1f}% | {r['yearly_max']:+.1f}% | {r['dd_mean']:+.1f}% | {ra:.3f} | {r['neg']} |")

    # Karar
    w("")
    w("## Karar")
    w("")
    if res_forex and res_crypto:
        c_ra = res_crypto["yearly_mean"] / abs(res_crypto["dd_mean"]) if res_crypto["dd_mean"] != 0 else 0
        f_ra = res_forex["yearly_mean"] / abs(res_forex["dd_mean"]) if res_forex["dd_mean"] != 0 else 0
        w(f"**Forex standalone:** yıllık {res_forex['yearly_mean']:+.1f}% / DD {res_forex['dd_mean']:+.1f}% / r-adj {f_ra:.3f}")
        w(f"**Crypto champion:** yıllık {res_crypto['yearly_mean']:+.1f}% / DD {res_crypto['dd_mean']:+.1f}% / r-adj {c_ra:.3f}")
        if res_5050:
            ra_5050 = res_5050["yearly_mean"] / abs(res_5050["dd_mean"]) if res_5050["dd_mean"] != 0 else 0
            w(f"**Combined 50/50:** yıllık {res_5050['yearly_mean']:+.1f}% / DD {res_5050['dd_mean']:+.1f}% / r-adj {ra_5050:.3f}")
            if ra_5050 > c_ra:
                w(f"-> **WINNER: Combined portfoy** (r-adj +{ra_5050-c_ra:.3f} vs crypto solo)")
            else:
                w(f"-> Combined portfoy r-adj duzeltmedi.")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\nRapor: {REPORT_OUT}")


if __name__ == "__main__":
    main()
