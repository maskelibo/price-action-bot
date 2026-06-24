"""Check market data freshness and run live signal scan to see actual rejects."""
from __future__ import annotations
import duckdb
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MKT = ROOT / "data" / "market.duckdb"

print("=== market.duckdb son 1d bar (her sym) ===")
con = duckdb.connect(str(MKT), read_only=True)
df = con.execute("""
    SELECT symbol, MAX(ts) AS last_bar, COUNT(*) AS rows
    FROM ohlcv
    WHERE timeframe='1d'
    GROUP BY symbol
    ORDER BY symbol
""").fetchdf()
print(df.to_string())
print()

print("=== Son 7 günün bar sayısı (data sağlığı) ===")
df2 = con.execute("""
    SELECT CAST(ts AS DATE) AS bar_date, COUNT(*) AS sym_count
    FROM ohlcv
    WHERE timeframe='1d' AND ts >= CURRENT_DATE - INTERVAL '7 days'
    GROUP BY bar_date
    ORDER BY bar_date DESC
""").fetchdf()
print(df2.to_string())
con.close()
print()

print("=== paper_trading.log günlük istatistik ===")
log_path = ROOT / "logs" / "paper_trading.log"
days = {}
total = 0
with log_path.open() as fh:
    for line in fh:
        try:
            obj = json.loads(line)
            day = obj.get("run_ts", "")[:10]
            sigs = obj.get("signals_found", 0)
            orders = obj.get("orders_placed", 0)
            rejects = obj.get("rejects", 0)
            d = days.setdefault(day, {"runs": 0, "signals": 0, "orders": 0, "rejects": 0})
            d["runs"] += 1
            d["signals"] += sigs
            d["orders"] += orders
            d["rejects"] += rejects
            total += 1
        except Exception:
            pass
print(f"Toplam paper_trading.log entry: {total}")
print(f"{'date':12} {'runs':>5} {'signals':>8} {'orders':>7} {'rejects':>8}")
for day in sorted(days.keys())[-10:]:
    d = days[day]
    print(f"{day:12} {d['runs']:>5} {d['signals']:>8} {d['orders']:>7} {d['rejects']:>8}")
