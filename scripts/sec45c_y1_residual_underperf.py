"""SEC45c: Why does Y1 STILL underperform after all-breakers-off?

H2 (DD breakers) Y1'i +7.9% -> +83% yapiyor, ama Y3-Y5 ayni fix'le
+35,288%, +88,733%, +2,064%'a firliyor. Y1 hala "az" -- neden?

Hipotezler:
- H4: Y1 pool'da SL% (entry-sl/entry) yuksek -> notional kuculuyor (risk_d / sl_pct, daha az dolar)
- H5: Y1 trade akisi farkli — sequence-dependent equity curve
- H6: Y1 fee/slip cesameti aritmetik olarak farkli (peak_R same ama mean R duzgun)

Y1 pool ile Y3 pool'unun SL% dagilimi, mean R, peak_R dagilimi karsilastir.
"""
from __future__ import annotations

import io
import os
import pickle
import sys
from datetime import timezone
from pathlib import Path
from statistics import mean, median, stdev

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

import pandas as pd

CACHE = ROOT / "data" / "sec44_5m_top2_pool.pkl"
with CACHE.open("rb") as f:
    pool = pickle.load(f)
pool.sort(key=lambda x: x["entry_ts"])
pool_start = pool[0]["entry_ts"]
pool_end = pool[-1]["entry_ts"]
if pool_start.tzinfo is None:
    pool_start = pool_start.replace(tzinfo=timezone.utc)
if pool_end.tzinfo is None:
    pool_end = pool_end.replace(tzinfo=timezone.utc)


def _y_bucket(y):
    ys = pool_start + pd.Timedelta(days=365 * y)
    ye = ys + pd.Timedelta(days=365)
    if ye > pool_end:
        ye = pool_end + pd.Timedelta(days=1)
    def _n(ts):
        return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)
    return ys, ye, [t for t in pool if ys <= _n(t["entry_ts"]) < ye]


print("=" * 78)
print("SEC45c: Y1 Residual Underperformance Analysis")
print("=" * 78)

print("\n## Pool SL% (entry-sl/entry) dagilimi (HAM POOL)")
print("| Y | n | SL% mean | median | p25 | p75 | p90 | std |")
print("|---|---:|---:|---:|---:|---:|---:|---:|")
for y in range(5):
    ys, ye, yt = _y_bucket(y)
    sls = [abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"] * 100 for t in yt
           if t["entry_price"] > 0]
    if not sls:
        continue
    sls_sorted = sorted(sls)
    p = lambda q: sls_sorted[int(len(sls_sorted) * q)]
    print(f"| Y{y+1} | {len(sls):,} | {mean(sls):.3f} | {median(sls):.3f} | "
          f"{p(0.25):.3f} | {p(0.75):.3f} | {p(0.90):.3f} | {stdev(sls):.3f} |")

print("\n## R*sl_pct = trade dollar PnL'in initial equity'e oranina yakin metrik")
print("(risk_pct=0.01, ayni yil ortalamasi -> trade basina beklenen $ getiri)")
print("| Y | n | mean(R*sl%) | median | sum(R*sl%) |")
print("|---|---:|---:|---:|---:|")
for y in range(5):
    ys, ye, yt = _y_bucket(y)
    rrr = []
    for t in yt:
        if t["entry_price"] > 0:
            slp = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
            # Position size = (equity * risk_pct) / slp ; PnL = position_size * slp * R
            # = equity * risk_pct * R; so $ getiri = R * risk_pct * equity (sl% iptal)
            # Yani Y1 sumR +24k * %1 = +%240 simple-compound (capatik birikim olmadan)
            rrr.append(t["R"] * slp * 100)  # bps cinsinden
    if rrr:
        print(f"| Y{y+1} | {len(rrr):,} | {mean(rrr):+.4f} | "
              f"{median(rrr):+.4f} | {sum(rrr):+.2f} |")

print("\n## EQUITY DELTA SIMULATION (no breakers, no cap, no concurrency)")
print("Sadece sirayla R * risk_pct equity uygula:")
print("equity *= (1 + R * risk_pct), risk_pct=0.01, initial=10000")
print("| Y | n | final$ | total% | min equity | max DD |")
print("|---|---:|---:|---:|---:|---:|")
for y in range(5):
    ys, ye, yt = _y_bucket(y)
    eq = 10000.0
    peak = eq
    mdd = 0.0
    minv = eq
    for t in yt:
        eq *= (1 + t["R"] * 0.01)
        if eq < 0:
            eq = 1
        peak = max(peak, eq)
        d = (eq - peak) / peak if peak > 0 else 0
        if d < mdd:
            mdd = d
        if eq < minv:
            minv = eq
    print(f"| Y{y+1} | {len(yt):,} | ${eq:,.0f} | {(eq/10000-1)*100:+.1f}% | "
          f"${minv:,.0f} | {mdd*100:+.1f}% |")

print("\n## Aciklama:")
print("Eger Y1 'simple compound' simulation'da Y3-5'ten DAHA AZ getiri veriyorsa,")
print("'engine bug' yok -- ham pool R dagilimi farkli (sirayla R'ler farkli)")
print("Eger Y1 simple-compound'da bile +%2400 cikiyorsa engine kayipari gercek.")

# Tum 5 yıl Y'lerini ardarda simule et (5-yil compound)
print("\n## 5-YIL COMPOUND (ham pool, no breakers/cap/concurrency, risk=1%)")
eq = 10000.0
peak = eq
mdd = 0.0
for t in pool:
    eq *= (1 + t["R"] * 0.01)
    if eq < 0:
        eq = 1
    peak = max(peak, eq)
    d = (eq - peak) / peak if peak > 0 else 0
    if d < mdd:
        mdd = d
print(f"5y compound final ${eq:,.0f} from $10k -> {(eq/10000-1)*100:+.1f}%, "
      f"MaxDD {mdd*100:+.1f}%")
