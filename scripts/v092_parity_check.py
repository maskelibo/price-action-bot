"""Canonical replay vs eski replay'lerin parity check'i.

Beklenti: production_replay (lab.py) ayni input/parametrelerle eski
replay_fixed/replay_protected sonuclari ile aynı sayilari verir.

Aksi durumda canonical replay'de bug var demektir.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Stdout temizligi icin quiet logging
os.environ["PA_LOG_QUIET"] = "1"

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig, production_replay
from scripts.v09_dd_protect import replay_protected
from scripts.v091_fix_test import replay_fixed
from scripts.v09_optimize_top10 import _gather, TOP_10


def main():
    print("=" * 90)
    print("CANONICAL REPLAY PARITY CHECK")
    print("=" * 90)

    print("\nTrade'leri topluyor...")
    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"Toplam: {len(all_trades)} sinyal")

    # 1y OOS window
    ws = pd.Timestamp("2025-05-09", tz="UTC")
    we = pd.Timestamp("2026-05-09", tz="UTC")
    w = [t for t in all_trades if ws <= t["entry_ts"] < we]
    print(f"1y pencere: {len(w)} sinyal\n")

    # === Test A: v0.9.1 production (no cap) ===
    print("=" * 90)
    print("TEST A — v0.9.1 (cool-down 3/5 gun, NO CAP)")
    print("=" * 90)

    # canonical
    cfg_a = ProductionConfig(
        risk_pct=0.030, conf_min=0.20,
        max_notional_pct_equity=None,
        consecutive_loss_n=3, consecutive_loss_pause_days=5,
    )
    r_canon = production_replay(w, cfg_a)
    print(f"  canonical (lab.py)       : {r_canon.summary()}")

    # eski replay_fixed
    r_old = replay_fixed(w, risk_pct=0.030, conf_min=0.20,
                        consecutive_loss_n=3, consecutive_loss_pause=5,
                        max_notional_ratio=None)
    print(f"  eski replay_fixed        : final=${r_old['final']:,.0f}  return=N/A  DD={r_old['max_dd']*100:+.1f}%  n={r_old['trades']}  WR={r_old['wr']*100:.1f}%")

    # eski replay_protected
    r_protected = replay_protected(w, risk_pct=0.030, conf_min=0.20,
                                   consecutive_loss_n=3, consecutive_loss_pause=5)
    print(f"  eski replay_protected    : final=${r_protected['final']:,.0f}  DD={r_protected['max_dd']*100:+.1f}%  n={r_protected['trades']}  WR={r_protected['wr']*100:.1f}%")

    # parity tahlili
    canon_eq = round(r_canon.final_equity, 2)
    old_eq = round(r_old["final"], 2)
    prot_eq = round(r_protected["final"], 2)
    print(f"\n  PARITY: canonical={canon_eq} vs replay_fixed={old_eq} vs replay_protected={prot_eq}")
    if canon_eq == old_eq == prot_eq:
        print(f"  OK -- her uc replay TAM AYNI sonucu veriyor (Test A)")
    else:
        print(f"  HATA -- sonuclar uyusmuyor (Test A)")

    # === Test B: v0.9.2 production (cap 0.30) ===
    print()
    print("=" * 90)
    print("TEST B — v0.9.2 PRODUCTION (cool-down 3/5 + cap 0.30)")
    print("=" * 90)

    cfg_b = ProductionConfig.from_yaml()  # risk.yaml'dan otomatik
    print(f"  cfg.from_yaml label: {cfg_b.label()}")
    r_canon_b = production_replay(w, cfg_b)
    print(f"  canonical (yaml)         : {r_canon_b.summary()}")

    # Aynisini explicit override ile yap
    cfg_b2 = ProductionConfig(
        risk_pct=0.030, conf_min=0.20,
        max_notional_pct_equity=0.30,
        consecutive_loss_n=3, consecutive_loss_pause_days=5,
    )
    r_canon_b2 = production_replay(w, cfg_b2)
    print(f"  canonical (explicit)     : {r_canon_b2.summary()}")

    # eski replay_fixed cap
    r_old_b = replay_fixed(w, risk_pct=0.030, conf_min=0.20,
                          consecutive_loss_n=3, consecutive_loss_pause=5,
                          max_notional_ratio=0.30)
    print(f"  eski replay_fixed cap30  : final=${r_old_b['final']:,.0f}  DD={r_old_b['max_dd']*100:+.1f}%  n={r_old_b['trades']}  WR={r_old_b['wr']*100:.1f}%")

    canon_b_eq = round(r_canon_b.final_equity, 2)
    canon_b2_eq = round(r_canon_b2.final_equity, 2)
    old_b_eq = round(r_old_b["final"], 2)
    print(f"\n  PARITY: canon_yaml={canon_b_eq} vs canon_explicit={canon_b2_eq} vs replay_fixed={old_b_eq}")
    if canon_b_eq == canon_b2_eq == old_b_eq:
        print(f"  OK -- her uc varyant TAM AYNI sonucu veriyor (Test B)")
    else:
        print(f"  HATA -- sonuclar uyusmuyor (Test B)")

    # === Test C: from_yaml gercekten configs/risk.yaml'i okuyor mu? ===
    print()
    print("=" * 90)
    print("TEST C — ProductionConfig.from_yaml() icerigi")
    print("=" * 90)
    c = ProductionConfig.from_yaml()
    print(f"  risk_pct                : {c.risk_pct}")
    print(f"  max_notional_pct_equity : {c.max_notional_pct_equity}")
    print(f"  conf_min                : {c.conf_min}")
    print(f"  consecutive_loss_n      : {c.consecutive_loss_n}")
    print(f"  consecutive_loss_pause  : {c.consecutive_loss_pause_days} day")
    print(f"  max_concurrent          : {c.max_concurrent}")
    print(f"  daily/weekly/monthly DD : {c.daily_dd}/{c.weekly_dd}/{c.monthly_dd}")

    # === Test D: Annualized return hesap ===
    print()
    print("=" * 90)
    print("TEST D — Annualized return hesabi (1y, 3y, 5y)")
    print("=" * 90)
    print(f"\n  v0.9.2 production, 1y window:")
    print(f"    Total return: {r_canon_b.total_return*100:+.2f}%")
    print(f"    Annualized (1y): {r_canon_b.annualized(1.0)*100:+.2f}%")
    print(f"    (1y'de annualized == total return — beklenir)")


if __name__ == "__main__":
    main()
