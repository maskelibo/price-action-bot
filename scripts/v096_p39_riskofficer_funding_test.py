"""P3.9 FIX verification — RiskOfficer.evaluate live'da funding filter uygular mi?

Test:
  T1. SUPER YAML yukle, alt_data funding calendar load oldu mu?
  T2. Long-skip gun + long sinyal -> Reject "alt_data_funding_filter"
  T3. Short-skip gun + short sinyal -> Reject "alt_data_funding_filter"
  T4. Long-skip gun + short sinyal -> kabul (yon hassasiyeti)
  T5. Filter pasif (AGGRESSIVE YAML, alt_data yok) -> filter atlanir
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.contracts import Signal
from price_action.risk.sizing import AccountState, RiskOfficer


def make_signal(ts, direction, entry=100.0, sl_offset=5.0):
    sl = entry - sl_offset if direction == "long" else entry + sl_offset
    tp = entry + sl_offset * 2 if direction == "long" else entry - sl_offset * 2
    return Signal(
        ts=ts, venue="binance", symbol="BTC/USDT", timeframe="1d",
        direction=direction, pattern_id="test", confluence_score=2.0,
        sl_price=sl, tp_price=tp, suggested_size_atr=1.0,
        metadata={"entry_price": entry},
    )


def main():
    print("=" * 100)
    print("P3.9 FIX VERIFICATION — RiskOfficer.evaluate alt-data funding filter")
    print("=" * 100)

    # SUPER preset yukle
    ro_super = RiskOfficer.from_yaml("configs/risk_super.yaml")
    long_skip = ro_super._alt_data_long_skip
    short_skip = ro_super._alt_data_short_skip

    print(f"\nT1. SUPER yukle, calendar size:")
    print(f"  long-skip dict   : {len(long_skip)} gun")
    print(f"  short-skip dict  : {len(short_skip)} gun")
    pass_t1 = len(long_skip) > 0 and len(short_skip) > 0
    print(f"  >>> T1 {'PASS' if pass_t1 else 'FAIL'}")

    if not long_skip or not short_skip:
        print("Calendar yuklenememis, test edilemiyor")
        return

    # Long-skip gun bul
    long_skip_date = sorted(long_skip.keys())[len(long_skip) // 2]  # middle one
    short_skip_date = sorted(short_skip.keys())[len(short_skip) // 2]
    long_skip_ts = datetime.combine(long_skip_date, datetime.min.time(), tzinfo=timezone.utc)
    short_skip_ts = datetime.combine(short_skip_date, datetime.min.time(), tzinfo=timezone.utc)

    state = AccountState(equity_usdt=10_000, free_margin_usdt=10_000)

    # T2: Long sinyal + long-skip gun -> REJECT
    print(f"\nT2. Long sinyal + long-skip gun ({long_skip_date}):")
    sig_long = make_signal(long_skip_ts, "long")
    r = ro_super.evaluate(sig_long, state, market_price=100.0)
    print(f"  Sonuc: {type(r).__name__}")
    if hasattr(r, "reason"):
        print(f"  reason: {r.reason}")
        print(f"  detail: {r.detail}")
    pass_t2 = type(r).__name__ == "Reject" and r.reason == "alt_data_funding_filter"
    print(f"  >>> T2 {'PASS' if pass_t2 else 'FAIL'}")

    # T3: Short sinyal + short-skip gun -> REJECT
    print(f"\nT3. Short sinyal + short-skip gun ({short_skip_date}):")
    sig_short = make_signal(short_skip_ts, "short")
    r = ro_super.evaluate(sig_short, state, market_price=100.0)
    print(f"  Sonuc: {type(r).__name__}")
    if hasattr(r, "reason"):
        print(f"  reason: {r.reason}")
        print(f"  detail: {r.detail}")
    pass_t3 = type(r).__name__ == "Reject" and r.reason == "alt_data_funding_filter"
    print(f"  >>> T3 {'PASS' if pass_t3 else 'FAIL'}")

    # T4: Long sinyal + short-skip gun -> filter geçer (yon yanlis)
    print(f"\nT4. Long sinyal + SHORT-skip gun (yon hassasiyeti, filter atlamali):")
    sig_long_on_short_skip = make_signal(short_skip_ts, "long")
    r = ro_super.evaluate(sig_long_on_short_skip, state, market_price=100.0)
    print(f"  Sonuc: {type(r).__name__}")
    reason = getattr(r, "reason", "-")
    print(f"  reason: {reason}")
    pass_t4 = reason != "alt_data_funding_filter"  # bu reason cikmamali — bir baska gate reject etse bile
    print(f"  >>> T4 {'PASS' if pass_t4 else 'FAIL'} (alt_data_funding_filter olmamali)")

    # T5: AGGRESSIVE (alt_data block YOK) -> filter pasif
    print(f"\nT5. AGGRESSIVE yukle (alt_data block YOK), filter pasif olmali:")
    ro_aggr = RiskOfficer.from_yaml("configs/risk_aggressive.yaml")
    pass_t5_a = len(ro_aggr._alt_data_long_skip) == 0
    print(f"  AGGR long-skip dict size: {len(ro_aggr._alt_data_long_skip)}")
    # Long-skip date'inde sinyal versek bile filter etkinleşmemeli
    sig = make_signal(long_skip_ts, "long")
    r = ro_aggr.evaluate(sig, state, market_price=100.0)
    reason = getattr(r, "reason", "-")
    pass_t5_b = reason != "alt_data_funding_filter"
    print(f"  AGGR reject reason: {reason}")
    print(f"  >>> T5 {'PASS' if pass_t5_a and pass_t5_b else 'FAIL'}")

    print()
    print("=" * 100)
    print(f"SUMMARY: {sum([pass_t1, pass_t2, pass_t3, pass_t4, pass_t5_a and pass_t5_b])}/5 PASS")
    print("=" * 100)


if __name__ == "__main__":
    main()
