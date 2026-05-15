"""A2 paper forensics — compare paper/testnet/futures journals."""
import duckdb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

con_p = duckdb.connect(str(ROOT/'data/paper_journal.duckdb'), read_only=True)
con_t = duckdb.connect(str(ROOT/'data/testnet_journal.duckdb'), read_only=True)
con_f = duckdb.connect(str(ROOT/'data/futures_journal.duckdb'), read_only=True)

ps = con_p.execute("SELECT ts, symbol, strategy, side, notes, sl_price, tp_price FROM paper_signals WHERE status='filled' ORDER BY ts").fetchall()
ts_rows = con_t.execute("SELECT ts, symbol, strategy, side, status, fill_price, cost_usdt, notes FROM testnet_signals ORDER BY ts").fetchall()
fs = con_f.execute("SELECT ts, symbol, strategy, side, status, fill_price, notional_usdt FROM futures_signals ORDER BY ts").fetchall()

print(f'paper_filled={len(ps)} testnet_all={len(ts_rows)} futures_all={len(fs)}')
print()

# build maps
def key(r):
    return (r[0], r[1], r[2], r[3])

tn_by = {key(r): r for r in ts_rows}
fn_by = {key(r): r for r in fs}

# Compare paper vs futures fills (both have signal fills)
print(f"{'ts':<20} {'sym':<10} {'strat':<28} {'side':<6} {'sl':<10} {'tp':<10} {'paper_fill':<12} {'tn_fill':<12} {'fut_fill':<12} {'slip_bps_paper_vs_fut':<10}")
print('-'*150)
for r in ps:
    ts0, sym, strat, side, notes, sl, tp = r
    # parse paper fill price from notes
    fp = None
    for w in notes.split():
        if w.startswith('fill_price='):
            fp = float(w.split('=')[1]); break
    tn = tn_by.get(key(r))
    fn = fn_by.get(key(r))
    tn_fp = tn[5] if tn else None
    fn_fp = fn[5] if fn else None
    slip_bps = None
    if fp is not None and fn_fp is not None:
        slip_bps = (fn_fp - fp) / fp * 10000
    fp_s = f'{fp:.6f}' if fp is not None else 'NA'
    tn_s = f'{tn_fp:.6f}' if tn_fp is not None else 'NA'
    fn_s = f'{fn_fp:.6f}' if fn_fp is not None else 'NA'
    sb = f'{slip_bps:+.1f}' if slip_bps is not None else 'NA'
    print(f'{str(ts0):<20} {sym:<10} {strat:<28} {side:<6} {sl:<10.4f} {tp:<10.4f} {fp_s:<12} {tn_s:<12} {fn_s:<12} {sb:<10}')

print()
print('=== status counts ===')
print(con_t.execute("SELECT status, COUNT(*) FROM testnet_signals GROUP BY status").fetchall())
print(con_f.execute("SELECT status, COUNT(*) FROM futures_signals GROUP BY status").fetchall())

# closed trades in paper (with R)
print()
print('=== paper closed events (real R outcomes) ===')
events = con_p.execute("""
  SELECT e.ts, e.symbol, e.event_type, e.price, e.realized_R, e.realized_pnl_usdt, e.notes
  FROM paper_position_events e ORDER BY e.ts
""").fetchall()
for ev in events:
    print(ev)
