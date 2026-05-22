"""WIRE-widestop parity check — DEPLOY_widestop_15m.md WIRE step 4.

Verifies that running the backtest engine with the wide-stop config
(configs/risk_phoenix_scalp_15m_widestop.yaml, which carries sl_pct_min=0.025)
reproduces scripts/lab_15m_widestop_dd_opt.py's conservative row.

Two paths, must be byte-identical:
  Path A — lab-script method: externally pre-filter the pool (sl_pct >= 0.025),
           run production_replay with sl_pct_min OFF.
  Path B — engine method: feed the FULL honest pool, let the engine's
           cfg.sl_pct_min (read from the wide-stop YAML) do the filtering.

Target (DEPLOY_widestop_15m.md, conservative +55bps taker):
  continuous-curve DD  ~= -20.7%
  per-month mean ROI   ~= +12.67%   (tolerance +/-2%, per the deploy spec)

NOTE: honest cost (+55bps) is baked into trade R by build_pool(); the engine's
own fee_bps_per_trade is therefore overridden to 0.0 to avoid double-counting.

Reproduce: python scripts/verify_widestop_parity.py
Requires: data/sec53_15m_pool_v11.pkl (gitignored — restore from the data host).
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig
# Reuse the lab script's honest-pool builder + replay helpers (single source of truth).
from scripts.lab_15m_widestop_dd_opt import (
    POOL,
    build_pool,
    continuous_replay,
    per_month,
    sl_pct_of,
)

WIDESTOP_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_widestop.yaml"
EXTRA_BPS = 55.0          # conservative taker scenario
THRESHOLD = 0.025         # wide-stop sl_pct_min (must match the YAML)
TARGET_DD = -20.7         # DEPLOY_widestop_15m.md conservative row
TARGET_MONTHLY = 12.67
TOL_PCT = 2.0             # +/-2% tolerance (deploy spec)


def _approx_eq(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def main() -> int:
    if not POOL.exists():
        print(f"[BLOCKED] pool not found: {POOL}")
        print("  data/ is gitignored and did not migrate to this machine.")
        print("  Restore data/sec53_15m_pool_v11.pkl, then re-run.")
        return 2

    print(f"[load] {POOL.name}")
    with POOL.open("rb") as f:
        raw_pool = pickle.load(f)
    print(f"  raw pool: {len(raw_pool)} trades\n")

    # Honest pool — +55bps cost baked into R (conservative taker scenario).
    honest = build_pool(raw_pool, EXTRA_BPS)

    # Engine config: wide-stop YAML carries sl_pct_min=0.025. fee OFF (cost in R).
    cfg_engine = ProductionConfig.from_yaml(str(WIDESTOP_YAML)).with_overrides(
        fee_bps_per_trade=0.0,
    )
    # Sanity: the YAML must actually carry the threshold.
    if not _approx_eq(cfg_engine.sl_pct_min, THRESHOLD):
        print(f"[FAIL] {WIDESTOP_YAML.name} sl_pct_min={cfg_engine.sl_pct_min} "
              f"!= expected {THRESHOLD}")
        return 1
    # Lab-script config: same config but sl_pct_min OFF (filter done externally).
    cfg_extfilter = cfg_engine.with_overrides(sl_pct_min=0.0)

    print(f"config: {WIDESTOP_YAML.name}")
    print(f"  sl_pct_min={cfg_engine.sl_pct_min}  risk_pct={cfg_engine.risk_pct}  "
          f"daily_dd={cfg_engine.daily_dd}  weekly_dd={cfg_engine.weekly_dd}  "
          f"pyramid={cfg_engine.pyramid_enabled}\n")

    # ----- Path A: external pre-filter (lab-script method) -----
    sub = [t for t in honest if sl_pct_of(t) >= THRESHOLD]
    print(f"Path A (external pre-filter): {len(sub)}/{len(honest)} trades kept")
    crA = continuous_replay(sub, cfg_extfilter)
    pmA = per_month(sub, cfg_extfilter)

    # ----- Path B: engine filter (deploy method) -----
    print("Path B (engine cfg.sl_pct_min): full pool, engine filters internally")
    crB = continuous_replay(honest, cfg_engine)
    pmB = per_month(honest, cfg_engine)

    if crA is None or crB is None or pmA is None or pmB is None:
        print("[FAIL] a replay returned None — pool too small / over-filtered")
        return 1

    # ----- Parity: continuous replay must be byte-identical -----
    print("\n" + "=" * 72)
    print("PARITY — continuous replay (canonical deploy metric)")
    print("=" * 72)
    fields = ("total_return", "annual", "dd")
    parity_ok = True
    for k in fields:
        a, b = crA[k], crB[k]
        ok = _approx_eq(a, b)
        parity_ok &= ok
        print(f"  {k:14s} A={a:+10.4f}  B={b:+10.4f}  {'OK' if ok else 'MISMATCH'}")
    print(f"  per-month mean   A={pmA['mean']:+8.2f}%  B={pmB['mean']:+8.2f}%  "
          f"(may differ slightly: per_month <10-trade month gate)")

    # ----- Target check (engine path = deploy reality) -----
    print("\n" + "=" * 72)
    print("TARGET — engine path vs DEPLOY_widestop_15m.md conservative row")
    print("=" * 72)
    dd_ok = abs(crB["dd"] - TARGET_DD) <= TOL_PCT
    mo_ok = abs(pmB["mean"] - TARGET_MONTHLY) <= TOL_PCT
    print(f"  continuous DD    {crB['dd']:+7.2f}%  target {TARGET_DD:+.2f}%  "
          f"{'OK' if dd_ok else 'OUT OF TOL'}  (+/-{TOL_PCT})")
    print(f"  per-month mean   {pmB['mean']:+7.2f}%  target {TARGET_MONTHLY:+.2f}%  "
          f"{'OK' if mo_ok else 'OUT OF TOL'}  (+/-{TOL_PCT})")

    ok = parity_ok and dd_ok and mo_ok
    print("\n" + ("[PASS] WIRE-4 parity verified." if ok
                   else "[FAIL] parity or target check failed — see above."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
