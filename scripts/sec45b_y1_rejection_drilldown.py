"""SEC45b: Y1 rejection drill-down.

baseline Y1 -> 82,831 trade pool -> 171 trade replay'a girdi (-%99.79 reject!).
Y3 ->  96,639 trade pool -> 1,209 trade replay (-%98.75 reject).

Hangi sebep en cok red ediyor?
- DD breaker (daily 2% / weekly 6%)?
- max_concurrent=20 doluluk?
- same_symbol_side cooldown_days=0.003 (~4 min)?
- consecutive_loss 8 @ 0.5d?

Tek-tek isolated test:
- baseline (her sey on)
- cooldown_only_off (same_symbol_side cooldown=0)
- mc_only_inf (mc=10000)
- daily_dd_off (daily=0.99)
- weekly_dd_off (weekly=0.99)
- conse_loss_off
- all_filters_off

Y1 + Y3 + Y5 senaryo replay -> tablo.
"""
from __future__ import annotations

import io
import os
import pickle
import sys
from datetime import timezone
from pathlib import Path

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
from price_action.backtest.lab import ProductionConfig, production_replay

CACHE = ROOT / "data" / "sec44_5m_top2_pool.pkl"

print("=" * 78)
print("SEC45b: Y1 Rejection Drill-Down")
print("=" * 78)

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


risk_yaml = ROOT / "configs" / "risk_phoenix_scalp_5m.yaml"
base = ProductionConfig.from_yaml(str(risk_yaml))
print(f"[BASE] risk={base.risk_pct} cap={base.max_notional_pct_equity} "
      f"mc={base.max_concurrent} cooldown={base.same_symbol_side_cooldown_days}d "
      f"daily_dd={base.daily_dd} weekly_dd={base.weekly_dd} "
      f"conse_loss={base.consecutive_loss_n}@{base.consecutive_loss_pause_days}d")

scens = {
    "baseline": base,
    "no_cooldown": base.with_overrides(same_symbol_side_cooldown_days=0),
    "mc_inf": base.with_overrides(max_concurrent=10000),
    "no_daily_dd": base.with_overrides(daily_dd=0.99),
    "no_weekly_dd": base.with_overrides(weekly_dd=0.99),
    "no_conse_loss": base.with_overrides(consecutive_loss_n=None),
    "all_breakers_off": base.with_overrides(
        daily_dd=0.99, weekly_dd=0.99, monthly_dd=0.99,
        monthly_dd_long=None, monthly_dd_short=None,
        consecutive_loss_n=None,
    ),
    "breakers_off_mc_inf": base.with_overrides(
        daily_dd=0.99, weekly_dd=0.99, monthly_dd=0.99,
        consecutive_loss_n=None, max_concurrent=10000,
    ),
    "breakers_off_mc_inf_nocd": base.with_overrides(
        daily_dd=0.99, weekly_dd=0.99, monthly_dd=0.99,
        consecutive_loss_n=None, max_concurrent=10000,
        same_symbol_side_cooldown_days=0,
    ),
    "full_open": base.with_overrides(
        daily_dd=0.99, weekly_dd=0.99, monthly_dd=0.99,
        consecutive_loss_n=None, max_concurrent=10000,
        same_symbol_side_cooldown_days=0,
        max_notional_pct_equity=None,
    ),
}

years_to_test = [1, 3, 5]

print(f"\n| Senaryo | Y{years_to_test[0]} n / ann / DD | "
      f"Y{years_to_test[1]} n / ann / DD | Y{years_to_test[2]} n / ann / DD |")
print(f"|---|---|---|---|")

table_rows = []
for name, cfg in scens.items():
    cells = [name]
    for y in years_to_test:
        ys, ye, yt = _y_bucket(y - 1)
        r = production_replay(yt, cfg)
        if r is None:
            cells.append("NONE")
            continue
        ann = r.annualized(1.0) * 100
        dd = r.max_drawdown * 100
        cells.append(f"{r.trades:,} / {ann:+.1f}% / {dd:+.1f}%")
    print(f"| {' | '.join(cells)} |")
    table_rows.append(cells)

print("\n" + "=" * 78)
print("INTERPRETATION")
print("=" * 78)
print("baseline = mevcut Phoenix-Scalp 5m config")
print("ARDA: hangi tek faktor en buyuk Y1 boost yapiyor?")
