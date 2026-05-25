"""SEC-SCALP P1 Step 4 — 1d champion replay parity (vol_target OFF/default).

1d Phoenix v2.0.4 YAML'da vol_target.enabled: false → replay path vol_target
yolundan geçmiyor. Bu test mevcut +%136.37 baseline'ı doğrular.

Reference: memory `Project v2.0.4 PHOENIX (current production)` — 13 pencere
ort yıllık +%136.37 / DD -42.2% / r-adj 3.229 (cached SEC21 baseline).

Pool: data/sec27_phoenix_pool.pkl (1d TOP-11 + FVG, cached SEC26.B replay)
Config: configs/risk_phoenix_v204.yaml
"""
from __future__ import annotations
import io
import os
import pickle
import sys
from pathlib import Path
from statistics import mean

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
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

# Try several candidate 1d caches
CANDIDATES = [
    ROOT / "data" / "v203_full_pool_peakR_2026-05-15.pkl",
    ROOT / "data" / "sec27_phoenix_pool.pkl",
    ROOT / "data" / "sec21_phoenix_pool.pkl",
    ROOT / "data" / "phoenix_pool_1d.pkl",
    ROOT / "data" / "production_pool_1d.pkl",
    ROOT / "data" / "sec12a_v12_pool.pkl",
]

YAML_1D = ROOT / "configs" / "risk_phoenix_v204.yaml"


def find_cache():
    for c in CANDIDATES:
        if c.exists():
            return c
    return None


def main():
    cache = find_cache()
    if cache is None:
        print("[WARN] 1d pool cache not found; trying glob ...", flush=True)
        # last-resort glob
        for p in sorted((ROOT / "data").glob("*phoenix*1d*.pkl")):
            cache = p
            break
        for p in sorted((ROOT / "data").glob("sec*_pool*.pkl")):
            # filter scalp
            if "15m" in p.name or "5m" in p.name or "1m" in p.name:
                continue
            cache = p
            break
    if cache is None:
        print("[FATAL] 1d cache yok — parity check yapilamaz (skipping)", flush=True)
        return

    print(f"[LOAD] {cache.name} ({cache.stat().st_size/1e6:.1f} MB)", flush=True)
    with cache.open("rb") as f:
        pool = pickle.load(f)
    print(f"[POOL] {len(pool):,} trade", flush=True)

    cfg = ProductionConfig.from_yaml(str(YAML_1D))
    print(f"[YAML] {YAML_1D.name}  vol_target_enabled={cfg.vol_target_enabled}",
          flush=True)

    # SEC21 walk-forward: 3y train + 3mo OOS + 3mo step = 13 pencere
    pool.sort(key=lambda x: x["entry_ts"])
    start = pool[0]["entry_ts"]
    end = pool[-1]["exit_ts"]
    TRAIN = pd.Timedelta(days=3 * 365)
    OOS = pd.Timedelta(days=90)
    STEP = pd.Timedelta(days=90)

    anns, dds, ras = [], [], []
    neg = 0
    cur = start
    while cur + TRAIN + OOS <= end:
        w = [t for t in pool if cur <= t["entry_ts"] < cur + TRAIN]
        if w:
            r = production_replay(w, cfg)
            if r is not None:
                ann = r.annualized(3.0) * 100
                dd = r.max_drawdown * 100
                ra = ann / abs(dd) if dd != 0 else 0
                anns.append(ann)
                dds.append(dd)
                ras.append(ra)
                if ann < 0:
                    neg += 1
        cur += STEP

    if not anns:
        print("[FATAL] no windows", flush=True)
        return

    ma, md, mr = mean(anns), mean(dds), mean(ras)
    print(f"\n[RESULT vol_target OFF] Windows: {len(anns)} (neg: {neg})", flush=True)
    print(f"  Mean Ann: {ma:+.2f}%   Mean DD: {md:+.2f}%   r-adj: {mr:.3f}",
          flush=True)

    # =====================================================================
    # CROSS-CHECK: vol_target_enabled override True vs False ile fark var mi
    # ile farklı target_atr_pct değerleri.
    # ÖNEMLİ: 1d Phoenix YAML'da vol_target.enabled=false. Eğer kullanıcı
    # override ile aktif ederse, sayı değişir — bu da modülün gerçekten
    # devreye girdiğini doğrular.
    # =====================================================================
    print(f"\n[CROSS-CHECK] vol_target sweep on same pool:", flush=True)
    for label, tgt in [("OFF", None), ("0.040 (default)", 0.04),
                        ("0.020", 0.02), ("0.080", 0.08)]:
        if tgt is None:
            cfg2 = cfg.with_overrides(vol_target_enabled=False)
        else:
            cfg2 = cfg.with_overrides(vol_target_enabled=True,
                                       vol_target_atr_pct=tgt)
        anns2 = []
        cur = start
        while cur + TRAIN + OOS <= end:
            w = [t for t in pool if cur <= t["entry_ts"] < cur + TRAIN]
            if w:
                r = production_replay(w, cfg2)
                if r is not None:
                    anns2.append(r.annualized(3.0) * 100)
            cur += STEP
        m = mean(anns2) if anns2 else 0
        print(f"  {label:<20}: mean ann {m:+.2f}%   delta_vs_OFF "
              f"{m - ma:+.2f}pp",
              flush=True)


if __name__ == "__main__":
    main()
