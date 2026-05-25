"""SEC32 helper — Trade-level cooldown reject statistics (no full replay).

Quick (~5s) analysis: pool'da kaç trade kaç farklı cooldown eşiğinde
sym+side bazında reddedilir? Bu sayılar sweep'in mekanizmasını açıklar.
"""
from __future__ import annotations
import io, os, pickle, sys
from pathlib import Path

if __name__ == "__main__":
    try: sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception: pass

ROOT = Path(__file__).resolve().parents[1]
POOL_R4 = ROOT / "data" / "sec31_15m_pool.pkl"

TOP4 = {"vsa_climax_test", "brooks_failed_breakout",
        "anchored_vwap_reversal", "engulfing_continuation"}
SYMS = {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
        "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"}


def main():
    print(f"[load] {POOL_R4.name}")
    with POOL_R4.open("rb") as f:
        r4 = pickle.load(f)
    pool = [t for t in r4 if t.get("strategy") in TOP4 and t.get("symbol") in SYMS]
    pool.sort(key=lambda x: x["entry_ts"])
    n = len(pool)
    print(f"  TOP-4 trades: {n:,}")

    thresholds_days = [0.003, 0.010, 0.020, 0.040, 0.063, 0.125, 0.250, 1.0, 3.0]
    rejects = {td: 0 for td in thresholds_days}
    last_by_key = {}

    for t in pool:
        key = (t["symbol"], t["side"])
        prev = last_by_key.get(key)
        if prev is not None:
            dt_sec = (t["entry_ts"] - prev).total_seconds()
            for td in thresholds_days:
                if dt_sec < td * 86400:
                    rejects[td] += 1
        last_by_key[key] = t["entry_ts"]

    print(f"\nCooldown reject statistics (cumulative):")
    print(f"{'Cooldown':>14} | {'Reject':>10} | {'%':>6} | {'Survive':>10}")
    print("-" * 50)
    for td in thresholds_days:
        r = rejects[td]
        print(f"{td:>8.3f} day | {r:>10,} | {r/n*100:>5.1f}% | {n-r:>10,}")

    print(f"\nTotal pool: {n:,}")
    print("\nMechanism note:")
    print("- 0.010d (15dk) cooldown WHICH FRACTION of trades is killed?")
    print("- Compare to 3.0d (1d champion default)")


if __name__ == "__main__":
    main()
