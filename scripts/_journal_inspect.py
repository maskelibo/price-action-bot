"""Inspect Phoenix journals."""
from __future__ import annotations
import duckdb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

for f in ["paper_journal_phoenix.duckdb", "paper_journal_atlas.duckdb", "futures_journal_phoenix.duckdb"]:
    print(f"=== {f} ===")
    path = DATA / f
    if not path.exists():
        print("  (missing)")
        continue
    con = duckdb.connect(str(path), read_only=True)
    tables = [t[0] for t in con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
    ).fetchall()]
    print("Tables:", tables)
    for tbl in tables:
        try:
            cnt = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            print(f"  {tbl}: {cnt} rows")
            if 0 < cnt:
                cols = [c[0] for c in con.execute(
                    f"SELECT column_name FROM information_schema.columns WHERE table_name='{tbl}'"
                ).fetchall()]
                ts_col = next((c for c in cols if "ts" in c.lower() or "time" in c.lower() or "date" in c.lower()), cols[0])
                last = con.execute(f"SELECT MAX({ts_col}) FROM {tbl}").fetchone()[0]
                print(f"    last {ts_col}: {last}")
                if cnt <= 100:
                    print("    sample (last 5):")
                    df = con.execute(f"SELECT * FROM {tbl} ORDER BY {ts_col} DESC LIMIT 5").fetchdf()
                    print(df.to_string(max_cols=6, max_colwidth=25))
        except Exception as e:
            print(f"  {tbl}: ERR {e}")
    con.close()
    print()
