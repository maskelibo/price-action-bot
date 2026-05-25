"""SEC45: Y1 Engine Capital Allocation Forensic.

5m TOP-2 pool: Y1 sumR +24,310 ama dolarda sadece +%7.9.
Y3 sumR ~+15k ama +%893. Strateji R kazandi, engine $$ tahsisi basarisiz.

3 hipotez:
- H1 Notional cap (0.25) Y1 DD -%37 sonrasi pozisyon kuculttu
- H2 DD breaker (daily 2%, weekly 6%) Y1 basinda trade'leri reddetti
- H3 Pyramid right-tail bull/bear asimetrisi (Y1 bear -> az lift)

Senaryolar (Y1 + sanity check Y2-Y5):
- baseline: mevcut config
- H1_fix: notional_cap 1.0 (kaldir) — pyramid OFF (default Phoenix-Scalp pyramid off)
- H2_fix: DD breakers DISABLED
- H3_fix: pyramid ON (1.0R, 2.0R triggers — Phoenix v2.0.4 default)
- H1+H2_fix: cap + breakers acik degil
- H1+H2+H3_fix: all-fix

Output: reports/analyst/2026-05-17_y1_engine_loss_forensic.md
"""
from __future__ import annotations

import io
import os
import pickle
import sys
from collections import defaultdict
from datetime import timezone
from pathlib import Path
from statistics import mean, median

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

import pandas as pd

from price_action.backtest.lab import ProductionConfig, production_replay

CACHE = ROOT / "data" / "sec44_5m_top2_pool.pkl"
REPORT = ROOT / "reports" / "analyst" / "2026-05-17_y1_engine_loss_forensic.md"


def _y_bucket(pool, y_idx, pool_start, pool_end):
    """365-day window starting at pool_start + y_idx*365 days."""
    y_start = pool_start + pd.Timedelta(days=365 * y_idx)
    y_end = y_start + pd.Timedelta(days=365)
    if y_end > pool_end:
        y_end = pool_end + pd.Timedelta(days=1)

    def _norm(ts):
        return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)
    out = [t for t in pool if y_start <= _norm(t["entry_ts"]) < y_end]
    return y_start, y_end, out


def _annual_pct(result, years=1.0):
    return result.annualized(years) * 100 if result else 0.0


def _dd_pct(result):
    return result.max_drawdown * 100 if result else 0.0


def _summary_pool(trades):
    if not trades:
        return None
    Rs = [t["R"] for t in trades]
    peakRs = [t.get("peak_R", t["R"]) for t in trades]
    return {
        "n": len(trades),
        "sumR": sum(Rs),
        "meanR": sum(Rs) / len(Rs),
        "wr": sum(1 for x in Rs if x > 0) / len(Rs) * 100,
        "peakR_ge_1": sum(1 for x in peakRs if x >= 1.0) / len(Rs) * 100,
        "peakR_ge_2": sum(1 for x in peakRs if x >= 2.0) / len(Rs) * 100,
        "max_R": max(Rs),
        "min_R": min(Rs),
    }


def build_scenarios(base_cfg: ProductionConfig) -> dict[str, ProductionConfig]:
    """6 senaryo: baseline + H1/H2/H3 fix + combos."""
    s = {}
    s["baseline"] = base_cfg
    s["H1_fix_no_cap"] = base_cfg.with_overrides(max_notional_pct_equity=None)
    s["H2_fix_no_breaker"] = base_cfg.with_overrides(
        daily_dd=0.99,
        weekly_dd=0.99,
        monthly_dd=0.99,
        monthly_dd_long=None,
        monthly_dd_short=None,
        consecutive_loss_n=None,
    )
    s["H3_fix_pyramid_on"] = base_cfg.with_overrides(
        pyramid_enabled=True,
        pyramid_triggers=(1.0, 2.0),
        pyramid_sizes=(0.50, 0.30),
    )
    s["H1+H2_fix"] = s["H1_fix_no_cap"].with_overrides(
        daily_dd=0.99, weekly_dd=0.99, monthly_dd=0.99,
        monthly_dd_long=None, monthly_dd_short=None,
        consecutive_loss_n=None,
    )
    s["H1+H2+H3_fix"] = s["H1+H2_fix"].with_overrides(
        pyramid_enabled=True,
        pyramid_triggers=(1.0, 2.0),
        pyramid_sizes=(0.50, 0.30),
    )
    return s


def position_size_diagnostics(trades, cfg):
    """Trade'leri cfg ile replay et ama position size+cap-binding say.
    Hizli olsun diye sadece notional + sl_pct dynamics izle.
    """
    if not trades:
        return None

    # Filter (same as replay)
    filtered = [
        t for t in trades
        if t["conf"] >= cfg.conf_min
        and t["strategy"] not in cfg.drop_strategies
        and t["symbol"] not in cfg.drop_symbols
    ]
    filtered = sorted(filtered, key=lambda x: x["entry_ts"])

    # Run replay to get equity trajectory; we re-implement only sizing tracking.
    # The full replay logic is too complex to mirror; instead, run replay,
    # capture trade count, then use a separate pass for sizing analysis.

    # Run replay (real)
    r = production_replay(filtered, cfg)
    if r is None:
        return None

    # Quick sizing sketch: assume equity ~= initial * (cumulative R-pnl trace)
    # We'll just count cap-binding events using a coarse equity proxy.
    # NOT exact, but indicative.
    equity = cfg.initial_capital
    cap_bound_count = 0
    size_dollars = []
    sl_pcts = []
    for t in filtered:
        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0:
            continue
        risk_d = equity * cfg.risk_pct
        notional = risk_d / sl_pct
        if cfg.max_notional_pct_equity is not None:
            cap = equity * cfg.max_notional_pct_equity
            if notional > cap:
                notional = cap
                cap_bound_count += 1
        size_dollars.append(notional)
        sl_pcts.append(sl_pct * 100)
        # crude equity update (no DD breakers, no concurrency, no compounding)
        pnl = (notional * sl_pct) * t["R"]  # = risk_d * R when no cap
        equity = max(equity + pnl, cfg.initial_capital * 0.1)

    if not size_dollars:
        return None

    return {
        "n_filtered": len(filtered),
        "n_sized": len(size_dollars),
        "cap_bound_count": cap_bound_count,
        "cap_bound_pct": cap_bound_count / len(size_dollars) * 100,
        "size_mean": mean(size_dollars),
        "size_median": median(size_dollars),
        "size_min": min(size_dollars),
        "size_max": max(size_dollars),
        "sl_pct_mean": mean(sl_pcts),
        "sl_pct_median": median(sl_pcts),
    }


def main():
    print("=" * 78)
    print("SEC45: Y1 Engine Capital Allocation Forensic")
    print("=" * 78)

    if not CACHE.exists():
        print(f"[FATAL] {CACHE} not found")
        return
    with CACHE.open("rb") as f:
        pool = pickle.load(f)
    print(f"[LOAD] {len(pool):,} trade")
    pool.sort(key=lambda x: x["entry_ts"])

    pool_start = pool[0]["entry_ts"]
    pool_end = pool[-1]["entry_ts"]
    if pool_start.tzinfo is None:
        pool_start = pool_start.replace(tzinfo=timezone.utc)
    if pool_end.tzinfo is None:
        pool_end = pool_end.replace(tzinfo=timezone.utc)

    risk_yaml = ROOT / "configs" / "risk_phoenix_scalp_5m.yaml"
    base_cfg = ProductionConfig.from_yaml(str(risk_yaml))
    print(f"[CFG] {risk_yaml.name}  risk_pct={base_cfg.risk_pct} "
          f"cap={base_cfg.max_notional_pct_equity} "
          f"mc={base_cfg.max_concurrent} pyr={base_cfg.pyramid_enabled} "
          f"daily_dd={base_cfg.daily_dd} weekly_dd={base_cfg.weekly_dd} "
          f"monthly_dd={base_cfg.monthly_dd}")

    # Build year buckets
    print("\n" + "=" * 78)
    print("YIL BAZLI POOL OZETI")
    print("=" * 78)
    print(f"| Y | start | end | n | sumR | mR | WR% | peakR>=1% | peakR>=2% |")
    print(f"|---|---|---|---:|---:|---:|---:|---:|---:|")
    year_pools = []
    for y in range(5):
        ys, ye, yt = _y_bucket(pool, y, pool_start, pool_end)
        year_pools.append((y + 1, ys, ye, yt))
        s = _summary_pool(yt)
        if s:
            print(f"| Y{y+1} | {ys.date()} | {ye.date()} | {s['n']:,} | "
                  f"{s['sumR']:+.0f} | {s['meanR']:+.3f} | {s['wr']:.1f} | "
                  f"{s['peakR_ge_1']:.1f} | {s['peakR_ge_2']:.1f} |")

    # H3 evidence: peak_R distribution per year
    print("\nH3 EVIDENCE — Pyramid eligible (peak_R>=1) per year:")
    for y, ys, ye, yt in year_pools:
        if not yt:
            continue
        s = _summary_pool(yt)
        print(f"  Y{y}: {s['peakR_ge_1']:.1f}% trades hit 1R MFE, "
              f"{s['peakR_ge_2']:.1f}% hit 2R MFE")

    # H1 evidence: position-size diagnostics for Y1 baseline
    print("\n" + "=" * 78)
    print("H1 EVIDENCE — Y1 Position Sizing under Baseline (cap=0.25)")
    print("=" * 78)
    y1_trades = year_pools[0][3]
    diag_y1_base = position_size_diagnostics(y1_trades, base_cfg)
    if diag_y1_base:
        print(f"Y1 baseline diag (coarse): {diag_y1_base}")
    diag_y1_nocap = position_size_diagnostics(
        y1_trades, base_cfg.with_overrides(max_notional_pct_equity=None)
    )
    if diag_y1_nocap:
        print(f"Y1 NO-CAP diag (coarse):   {diag_y1_nocap}")

    # Scenarios
    scenarios = build_scenarios(base_cfg)
    print("\n" + "=" * 78)
    print(f"SCENARIO REPLAY — Y1-Y5 x {len(scenarios)} scenarios")
    print("=" * 78)

    results = defaultdict(dict)  # results[scen_name][year_id] = {ann, dd, ra, sumR_realized}
    for scen_name, cfg in scenarios.items():
        print(f"\n[SCEN] {scen_name}")
        for y, ys, ye, yt in year_pools:
            if not yt:
                continue
            r = production_replay(yt, cfg)
            if r is None:
                results[scen_name][y] = None
                print(f"  Y{y}: NONE")
                continue
            ann = _annual_pct(r, 1.0)
            dd = _dd_pct(r)
            ra = ann / abs(dd) if dd != 0 else 0
            results[scen_name][y] = {
                "ann": ann, "dd": dd, "ra": ra,
                "sumR": r.sum_r, "trades": r.trades,
                "final_eq": r.final_equity, "wr": r.win_rate * 100,
            }
            print(f"  Y{y} [{ys.date()}..{ye.date()}] n={r.trades:,} "
                  f"ann={ann:+.1f}% DD={dd:+.1f}% ra={ra:.3f} sumR={r.sum_r:+.0f}")

    # CV calculation per scenario
    print("\n" + "=" * 78)
    print("CV (5-yil std/|mean|) per scenario")
    print("=" * 78)
    for scen_name in scenarios:
        anns = [results[scen_name][y]["ann"] for y in range(1, 6)
                if results[scen_name].get(y)]
        dds = [results[scen_name][y]["dd"] for y in range(1, 6)
               if results[scen_name].get(y)]
        if len(anns) < 2:
            continue
        mu = sum(anns) / len(anns)
        std = (sum((a - mu) ** 2 for a in anns) / (len(anns) - 1)) ** 0.5
        cv = std / abs(mu) if mu != 0 else 0
        print(f"  {scen_name:25s} mean={mu:+7.1f}% std={std:6.1f}pp "
              f"CV={cv*100:6.1f}% min={min(anns):+7.1f}% max={max(anns):+7.1f}% "
              f"dd_mean={sum(dds)/len(dds):+.1f}%")

    # Markdown report
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    out = []
    out.append("# SEC45 — Y1 Engine Capital Allocation Forensic\n\n")
    out.append("**Generated:** 2026-05-17  \n")
    out.append("**Pool:** sec44_5m_top2_pool.pkl (461,789 trade, 5y, TOP-2: vsa_climax_test + brooks_failed_breakout)  \n")
    out.append("**Risk YAML:** `configs/risk_phoenix_scalp_5m.yaml` (risk_pct=0.010, cap=0.25, mc=20, pyramid=OFF, daily_dd=0.02, weekly_dd=0.06, monthly_dd=0.99, conse_loss=8 @ 0.5d)\n\n")

    out.append("## 1. Yıllık Pool Özeti — H3 evidence (peak_R dağılımı)\n\n")
    out.append("| Y | Start | End | n | sumR | mR | WR% | peakR>=1 % | peakR>=2 % |\n")
    out.append("|---|---|---|---:|---:|---:|---:|---:|---:|\n")
    for y, ys, ye, yt in year_pools:
        s = _summary_pool(yt)
        if s:
            out.append(
                f"| Y{y} | {ys.date()} | {ye.date()} | {s['n']:,} | "
                f"{s['sumR']:+.0f} | {s['meanR']:+.3f} | {s['wr']:.1f} | "
                f"{s['peakR_ge_1']:.1f} | {s['peakR_ge_2']:.1f} |\n"
            )

    out.append("\n## 2. H1 Evidence — Y1 Position Sizing Diagnostics (coarse, no compounding)\n\n")
    if diag_y1_base and diag_y1_nocap:
        out.append("| Metric | Baseline (cap=0.25) | NO-CAP |\n|---|---:|---:|\n")
        out.append(f"| Trades sized | {diag_y1_base['n_sized']:,} | {diag_y1_nocap['n_sized']:,} |\n")
        out.append(f"| Cap-binding events | {diag_y1_base['cap_bound_count']:,} "
                   f"({diag_y1_base['cap_bound_pct']:.1f}%) | "
                   f"{diag_y1_nocap['cap_bound_count']:,} ({diag_y1_nocap['cap_bound_pct']:.1f}%) |\n")
        out.append(f"| Position size mean ($) | {diag_y1_base['size_mean']:,.0f} | "
                   f"{diag_y1_nocap['size_mean']:,.0f} |\n")
        out.append(f"| Position size median ($) | {diag_y1_base['size_median']:,.0f} | "
                   f"{diag_y1_nocap['size_median']:,.0f} |\n")
        out.append(f"| Position size max ($) | {diag_y1_base['size_max']:,.0f} | "
                   f"{diag_y1_nocap['size_max']:,.0f} |\n")
        out.append(f"| SL%% mean | {diag_y1_base['sl_pct_mean']:.2f} | "
                   f"{diag_y1_nocap['sl_pct_mean']:.2f} |\n")
        out.append(f"| SL%% median | {diag_y1_base['sl_pct_median']:.2f} | "
                   f"{diag_y1_nocap['sl_pct_median']:.2f} |\n")

    out.append("\n## 3. 6-Senaryo Y1-Y5 Replay\n\n")
    out.append("**Senaryolar:**\n")
    out.append("- `baseline` = mevcut config (cap=0.25, daily_dd=2%, weekly_dd=6%, monthly_dd=99%, pyr=OFF, cons_loss=8 @ 0.5d)\n")
    out.append("- `H1_fix_no_cap` = max_notional_pct_equity=None\n")
    out.append("- `H2_fix_no_breaker` = daily/weekly/monthly_dd=0.99, conse_loss=None (all DD breakers off)\n")
    out.append("- `H3_fix_pyramid_on` = pyramid (1.0R, 2.0R) triggers, (0.50, 0.30) sizes\n")
    out.append("- `H1+H2_fix` = no-cap + no-breakers\n")
    out.append("- `H1+H2+H3_fix` = all three\n\n")

    # Per-year scenario table
    for y in range(1, 6):
        out.append(f"\n### Y{y} — {year_pools[y-1][1].date()} → {year_pools[y-1][2].date()}\n\n")
        out.append("| Scenario | Annual % | DD % | r-adj | Trades | sumR realized | Final $ |\n")
        out.append("|---|---:|---:|---:|---:|---:|---:|\n")
        for scen_name in scenarios:
            r = results[scen_name].get(y)
            if not r:
                out.append(f"| {scen_name} | - | - | - | - | - | - |\n")
                continue
            out.append(
                f"| {scen_name} | {r['ann']:+.1f}% | {r['dd']:+.1f}% | "
                f"{r['ra']:.3f} | {r['trades']:,} | {r['sumR']:+.0f} | "
                f"${r['final_eq']:,.0f} |\n"
            )

    out.append("\n## 4. CV Karşılaştırma (5-yıl std/|mean|)\n\n")
    out.append("| Scenario | Mean % | Std (pp) | CV % | Min % | Max % | DD mean |\n")
    out.append("|---|---:|---:|---:|---:|---:|---:|\n")
    for scen_name in scenarios:
        anns = [results[scen_name][y]["ann"] for y in range(1, 6)
                if results[scen_name].get(y)]
        dds = [results[scen_name][y]["dd"] for y in range(1, 6)
               if results[scen_name].get(y)]
        if len(anns) < 2:
            continue
        mu = sum(anns) / len(anns)
        std = (sum((a - mu) ** 2 for a in anns) / (len(anns) - 1)) ** 0.5
        cv = std / abs(mu) if mu != 0 else 0
        out.append(f"| {scen_name} | {mu:+.1f} | {std:.1f} | {cv*100:.1f} | "
                   f"{min(anns):+.1f} | {max(anns):+.1f} | {sum(dds)/len(dds):+.1f} |\n")

    out.append("\n## 5. Bulgular ve Engine Fix Önerisi\n\n")
    out.append("Detaylı yorum için bot mesajındaki <350-kelime özet'e bakın. Reason chain:\n\n")
    out.append("1. **Y1 peakR>=1 oranı** ile Y3-Y5 arasındaki fark → H3 (pyramid asimetrisi) yapısal mı, yoksa yıl-bağımsız mı?\n")
    out.append("2. **H1 cap-binding event sayısı** → cap gerçekten kaç trade'de bağlayıcı?\n")
    out.append("3. **Senaryo Y1 ROI'leri** karşılaştırması → tek-faktör vs kombo açıklama gücü.\n")
    out.append("4. **CV %105 → %X** → engine düzeltmesi istikrar sağlıyor mu?\n\n")
    out.append("## Reproduce\n\n")
    out.append("```bash\npython scripts/sec45_y1_engine_forensic.py\n```\n")

    REPORT.write_text("".join(out), encoding="utf-8")
    print(f"\n[REPORT] {REPORT}")


if __name__ == "__main__":
    main()
