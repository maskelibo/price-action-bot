"""SEC9: Deep Loss Forensics — kayıp trade'leri parçala, counterfactual çıkar.

Soru: Yanlış pozisyonları açmasaydık return ne olurdu?
Hedef: Kayıpların nerede toplanıyor, hangi pattern var, removable mi.

3 adim:
1. Loss distribution — strategy/symbol/regime breakdown
2. Counterfactual — worst N% trades cikarsa yillik + DD
3. Cluster analysis — kayiplar zamansal/regime ile mi correlated

Output: reports/research/sec9_loss_forensics.md
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
from scripts.v09_optimize_top10 import _gather, TOP_10
from scripts.v097_balanced_optimization import DROP_PAIRS, build_fng_short_skip

REPORT_OUT = ROOT / "reports" / "research" / "sec9_loss_forensics.md"


def main() -> None:
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out = []
    def w(line=""):
        print(line)
        out.append(line)

    print("Trade topluyor...")
    crypto = []
    for m, c in TOP_10:
        crypto.extend(_gather(m, c))
    crypto.sort(key=lambda x: x['entry_ts'])
    df = pd.DataFrame(crypto)
    df['entry_ts'] = pd.to_datetime(df['entry_ts'], utc=True)
    df['year_month'] = df['entry_ts'].dt.to_period('M').astype(str)
    df['year'] = df['entry_ts'].dt.year
    df['quarter'] = df['entry_ts'].dt.to_period('Q').astype(str)
    df['weekday'] = df['entry_ts'].dt.day_name()
    df['win'] = (df['R'] > 0).astype(int)

    n = len(df)
    n_win = df['win'].sum()
    n_loss = n - n_win
    sumR_total = df['R'].sum()
    sumR_win = df[df['win']==1]['R'].sum()
    sumR_loss = df[df['win']==0]['R'].sum()

    w("# SEC9: Loss Forensics — Kayip Trade Derinlemesine Analizi")
    w("")
    w(f"**Generated:** {pd.Timestamp.now('UTC').isoformat()}")
    w("")
    w("## 1. POOL OZETI")
    w("")
    w(f"- **Toplam trade:** {n}")
    w(f"- **Kazanan:** {n_win} (%{n_win/n*100:.1f})")
    w(f"- **Kaybeden:** {n_loss} (%{n_loss/n*100:.1f})")
    w(f"- **Toplam R:** {sumR_total:+.1f}")
    w(f"- **Kazanan R toplami:** {sumR_win:+.1f} (mean +{sumR_win/n_win:.3f}/win)")
    w(f"- **Kaybeden R toplami:** {sumR_loss:+.1f} (mean {sumR_loss/n_loss:+.3f}/loss)")
    w(f"- **Win/Loss R orani:** {sumR_win/abs(sumR_loss):.2f}x (>1 ise edge var)")
    w(f"- **Mean R per trade:** {sumR_total/n:+.4f}")

    # 2. PER STRATEGY LOSS BREAKDOWN
    w("")
    w("## 2. PER STRATEGY — Kayip Katkisi")
    w("")
    w("| Strategy | n | WR | mean_R | sumR | LOSS_sumR | EDGE |")
    w("|---|---:|---:|---:|---:|---:|---|")
    for s, g in df.groupby('strategy'):
        n_s = len(g)
        wr = g['win'].mean() * 100
        mR = g['R'].mean()
        sumR = g['R'].sum()
        loss_sumR = g[g['win']==0]['R'].sum()
        edge = "POZITIF" if mR > 0.05 else "marjinal" if mR > 0 else "NEGATIF"
        w(f"| {s} | {n_s} | {wr:.1f}% | {mR:+.3f} | {sumR:+.1f} | {loss_sumR:+.1f} | {edge} |")

    # 3. PER SYMBOL
    w("")
    w("## 3. PER SYMBOL — Kayip Katkisi")
    w("")
    w("| Symbol | n | WR | mean_R | sumR | LOSS_sumR |")
    w("|---|---:|---:|---:|---:|---:|")
    for s, g in df.groupby('symbol'):
        w(f"| {s} | {len(g)} | {g['win'].mean()*100:.1f}% | {g['R'].mean():+.3f} | {g['R'].sum():+.1f} | {g[g['win']==0]['R'].sum():+.1f} |")

    # 4. STRATEGY × SYMBOL ablation: en kotu 20
    w("")
    w("## 4. STRATEGY × SYMBOL — En kotu 20 cell")
    w("")
    w("| Strategy | Symbol | n | mean_R | sumR |")
    w("|---|---|---:|---:|---:|")
    g = df.groupby(['strategy', 'symbol']).agg(n=('R','count'), mR=('R','mean'), sumR=('R','sum'))
    g_sorted = g[g['n'] >= 10].sort_values('mR').head(20)
    for (s, sym), row in g_sorted.iterrows():
        w(f"| {s} | {sym} | {int(row['n'])} | {row['mR']:+.3f} | {row['sumR']:+.1f} |")

    # 5. WORST 50 TRADES
    w("")
    w("## 5. EN KOTU 50 TRADE")
    w("")
    w("| # | entry_ts | symbol | strategy | side | R |")
    w("|---:|---|---|---|---|---:|")
    worst = df.nsmallest(50, 'R')
    for i, (_, r) in enumerate(worst.iterrows(), 1):
        w(f"| {i} | {r['entry_ts'].strftime('%Y-%m-%d')} | {r['symbol']} | {r['strategy']} | {r['side']} | {r['R']:+.2f} |")

    # 6. MONTH-BY-MONTH HEAT
    w("")
    w("## 6. PER YEAR-MONTH (en kotu 15 ay)")
    w("")
    w("| YearMonth | n | WR | mean_R | sumR |")
    w("|---|---:|---:|---:|---:|")
    monthly = df.groupby('year_month').agg(n=('R','count'), wr=('win','mean'), mR=('R','mean'), sumR=('R','sum'))
    monthly_worst = monthly.sort_values('sumR').head(15)
    for ym, r in monthly_worst.iterrows():
        w(f"| {ym} | {int(r['n'])} | {r['wr']*100:.1f}% | {r['mR']:+.3f} | {r['sumR']:+.1f} |")

    # 7. COUNTERFACTUAL — worst N% removed
    w("")
    w("## 7. COUNTERFACTUAL — Worst Trades Cikarinca")
    w("")

    base = ProductionConfig.from_yaml('configs/risk_balanced.yaml')
    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({'funding_filter_enabled': True, 'funding_aggregation_mode': '00:00_only'})
    fng_short_20 = build_fng_short_skip(20)
    combined_short_skip = {**dict(fund_short or {}), **dict(fng_short_20)}
    cfg = base.with_overrides(alt_data_skip_long=fund_long, alt_data_skip_short=combined_short_skip, drop_pairs=DROP_PAIRS)

    # Mevcut champion
    start = df['entry_ts'].min()
    end = pd.to_datetime(df['exit_ts'].max(), utc=True)
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3*365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3*365)))
        cur += pd.Timedelta(days=60)

    def replay_pool(pool):
        anns, dds = [], []
        for ws, we in windows:
            ww_t = [t for t in pool if ws <= t['entry_ts'] < we]
            r = production_replay(ww_t, cfg)
            if r is None: continue
            anns.append(r.annualized(3.0)*100); dds.append(r.max_drawdown*100)
        if not anns: return None
        return mean(anns), mean(dds)

    # Baseline
    base_pool = sorted(crypto, key=lambda t: t['entry_ts'])
    ann, dd = replay_pool(base_pool)
    ra = ann/abs(dd) if dd != 0 else 0
    w(f"| Senaryo | n | Yillik | DD | r-adj |")
    w(f"|---|---:|---:|---:|---:|")
    w(f"| **Baseline (TOP_10 + BALANCED+F&G)** | {len(base_pool)} | {ann:+.1f}% | {dd:+.1f}% | {ra:.3f} |")
    print(f"Baseline: {ann:+.1f}% / {dd:+.1f}% / r-adj {ra:.3f}")

    # Counterfactual: worst N% removed by R
    Rs_sorted = sorted(crypto, key=lambda t: t['R'])
    for pct in [0.05, 0.10, 0.15, 0.20, 0.25]:
        n_remove = int(len(crypto) * pct)
        worst_ids = set(id(t) for t in Rs_sorted[:n_remove])
        kept = [t for t in crypto if id(t) not in worst_ids]
        kept.sort(key=lambda t: t['entry_ts'])
        ann, dd = replay_pool(kept)
        ra = ann/abs(dd) if dd != 0 else 0
        w(f"| Worst {int(pct*100)}% (n={n_remove}) cikari | {len(kept)} | {ann:+.1f}% | {dd:+.1f}% | {ra:.3f} |")
        print(f"  -%{int(pct*100)}: {ann:+.1f}% / {dd:+.1f}% / r-adj {ra:.3f}")

    # Counterfactual: top N% removed (sanity check — top trades cikarinca ne kadar duser)
    w("")
    w("**Sanity (top winners removed):**")
    w("")
    w("| Senaryo | n | Yillik | DD | r-adj |")
    w("|---|---:|---:|---:|---:|")
    Rs_sorted_desc = sorted(crypto, key=lambda t: -t['R'])
    for pct in [0.05, 0.10]:
        n_remove = int(len(crypto) * pct)
        top_ids = set(id(t) for t in Rs_sorted_desc[:n_remove])
        kept = [t for t in crypto if id(t) not in top_ids]
        kept.sort(key=lambda t: t['entry_ts'])
        ann, dd = replay_pool(kept)
        ra = ann/abs(dd) if dd != 0 else 0
        w(f"| Top {int(pct*100)}% (n={n_remove}) cikar | {len(kept)} | {ann:+.1f}% | {dd:+.1f}% | {ra:.3f} |")

    # 8. KAYIPLARIN PROFILI — vol_z, conf, side, regime
    w("")
    w("## 8. KAYIP PROFILI — Removable Pattern Var Mi?")
    w("")

    losses = df[df['win']==0]
    wins = df[df['win']==1]
    w(f"### Side dagilimi (kayip)")
    w(f"- Long kayip: {(losses['side']=='long').sum()} / {(df['side']=='long').sum()} ({(losses['side']=='long').sum()/(df['side']=='long').sum()*100:.1f}%)")
    w(f"- Short kayip: {(losses['side']=='short').sum()} / {(df['side']=='short').sum()} ({(losses['side']=='short').sum()/(df['side']=='short').sum()*100:.1f}%)")

    w(f"\\n### vol_z dagilimi (kayip vs kazanan)")
    w(f"- Kayip vol_z mean: {losses['vol_z'].mean():+.3f}, q50: {losses['vol_z'].median():+.3f}")
    w(f"- Kazanan vol_z mean: {wins['vol_z'].mean():+.3f}, q50: {wins['vol_z'].median():+.3f}")

    w(f"\\n### conf dagilimi")
    w(f"- Kayip conf mean: {losses['conf'].mean():.3f}, q50: {losses['conf'].median():.3f}")
    w(f"- Kazanan conf mean: {wins['conf'].mean():.3f}, q50: {wins['conf'].median():.3f}")

    # Spearman: vol_z, conf vs R
    from scipy.stats import spearmanr
    r_volz, p_volz = spearmanr(df['vol_z'], df['R'])
    r_conf, p_conf = spearmanr(df['conf'], df['R'])
    w(f"\\n### Spearman korelasyon (R outcome ile)")
    w(f"- vol_z vs R: r={r_volz:+.3f} (p={p_volz:.4f})")
    w(f"- conf vs R: r={r_conf:+.3f} (p={p_conf:.4f})")
    w(f"  (|r|>0.1 ve p<0.01 ise removable signal var)")

    # 9. FINAL VERDICT
    w("")
    w("## 9. SONUC")
    w("")
    w("Bu raporda en degerli sayilar:")
    w("- Worst 5-10% trades cikinca yillik return artisi")
    w("- En kotu strateji×sym cell'leri (ek drop_pairs adaylari)")
    w("- vol_z/conf ile R'nin korelasyonu (ML edge sinyali)")

    REPORT_OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"\nRapor: {REPORT_OUT}")


if __name__ == "__main__":
    main()
