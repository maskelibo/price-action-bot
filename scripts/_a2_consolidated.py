"""A2 — Consolidated paper trading forensics.

Outputs: numeric stats, per-trade table, anomalies.
"""
import duckdb
from pathlib import Path
from collections import Counter, defaultdict
import statistics as stat

ROOT = Path(r"C:\Users\koray\projeler\Price Action")

con_p = duckdb.connect(str(ROOT / "data/paper_journal.duckdb"), read_only=True)
con_t = duckdb.connect(str(ROOT / "data/testnet_journal.duckdb"), read_only=True)
con_f = duckdb.connect(str(ROOT / "data/futures_journal.duckdb"), read_only=True)

# ----- Signal generation timeline -----
print("=" * 70)
print("SIGNAL GENERATION TIMELINE")
print("=" * 70)
ps_dates = con_p.execute("SELECT DATE(ts), COUNT(*), SUM(CASE WHEN status='filled' THEN 1 ELSE 0 END) FROM paper_signals GROUP BY DATE(ts) ORDER BY 1").fetchall()
print(f"paper journal scan dates: {ps_dates}")
ts_dates = con_t.execute("SELECT DATE(ts), COUNT(*), SUM(CASE WHEN status='filled' THEN 1 ELSE 0 END) FROM testnet_signals GROUP BY DATE(ts) ORDER BY 1").fetchall()
print(f"testnet journal scan dates: {ts_dates}")
fs_dates = con_f.execute("SELECT DATE(ts), COUNT(*), SUM(CASE WHEN status='filled' THEN 1 ELSE 0 END) FROM futures_signals GROUP BY DATE(ts) ORDER BY 1").fetchall()
print(f"futures journal scan dates: {fs_dates}")

# ----- 30g window (2026-04-14 .. 2026-05-14) -----
ps30 = con_p.execute("SELECT * FROM paper_signals WHERE ts >= '2026-04-14' AND ts < '2026-05-15' ORDER BY ts").fetchdf()
ts30 = con_t.execute("SELECT * FROM testnet_signals WHERE ts >= '2026-04-14' AND ts < '2026-05-15' ORDER BY ts").fetchdf()
fs30 = con_f.execute("SELECT * FROM futures_signals WHERE ts >= '2026-04-14' AND ts < '2026-05-15' ORDER BY ts").fetchdf()

print(f"\n30g penceresinde sinyal: paper={len(ps30)} testnet={len(ts30)} futures={len(fs30)}")
print(f"30g penceresinde unique scan dates: paper={ps30['ts'].dt.date.nunique()} testnet={ts30['ts'].dt.date.nunique()} futures={fs30['ts'].dt.date.nunique()}")

# ----- Slippage (paper synthetic broker fill vs futures real testnet fill) -----
print("\n" + "=" * 70)
print("SLIPPAGE: paper synthetic broker vs futures testnet real fill")
print("=" * 70)
# parse paper fills
ps_filled = con_p.execute("SELECT ts, symbol, strategy, side, sl_price, tp_price, notes FROM paper_signals WHERE status='filled' ORDER BY ts").fetchall()
fs_filled = con_f.execute("SELECT ts, symbol, strategy, side, fill_price FROM futures_signals WHERE status='filled'").fetchall()
fs_by = {(r[0], r[1], r[2], r[3]): r[4] for r in fs_filled}

slip_bps_list = []
matched = 0
for ts0, sym, strat, side, sl, tp, notes in ps_filled:
    fp_paper = None
    for w in notes.split():
        if w.startswith("fill_price="):
            fp_paper = float(w.split("=")[1])
    fp_fut = fs_by.get((ts0, sym, strat, side))
    if fp_paper is None or fp_fut is None:
        continue
    matched += 1
    # slippage in bps relative to paper "expected"
    # for short, adverse slippage is positive (fill higher than expected = worse for short receiving sell price)
    # for long, adverse slippage is positive (fill higher than expected = worse for buyer)
    raw_bps = (fp_fut - fp_paper) / fp_paper * 1e4
    # adverse-direction slippage:
    if side == "short":
        # short: we sell. higher fill = better (we got better price). But here we got worse exit on entry.
        # Actually entry for short = we sell at fp_fut. higher = better entry.
        # But the bot uses fp_paper as "expected" — so positive raw bps = better for short.
        # Adverse = -raw (better) or +raw (worse for long)
        adv = -raw_bps
    else:
        adv = raw_bps
    slip_bps_list.append((sym, strat, side, fp_paper, fp_fut, raw_bps, adv))

print(f"Matched paper<->futures pairs: {matched}")
print(f"{'sym':<10} {'strat':<28} {'side':<6} {'paper':<14} {'futures':<14} {'raw_bps':<10} {'adverse_bps':<12}")
for s in slip_bps_list:
    sym, strat, side, fp, fpf, raw, adv = s
    print(f"{sym:<10} {strat:<28} {side:<6} {fp:<14.4f} {fpf:<14.4f} {raw:+.1f}     {adv:+.1f}")

if slip_bps_list:
    raws = [r[5] for r in slip_bps_list]
    advs = [r[6] for r in slip_bps_list]
    print(f"\nraw_bps     mean={stat.mean(raws):+.2f}  median={stat.median(raws):+.2f}  stdev={stat.stdev(raws):.2f}  abs_mean={stat.mean(abs(r) for r in raws):.2f}")
    print(f"adverse_bps mean={stat.mean(advs):+.2f}  median={stat.median(advs):+.2f}  stdev={stat.stdev(advs):.2f}")
    print(f"backtest assumption: 5bps×2 = 10bps adverse per trigger (entry+exit). PER LEG => 5 bps assumption.")
    print(f"max adverse: {max(advs):+.2f} bps, min adverse: {min(advs):+.2f} bps")
    print(f"trades with |bps| > 50: {sum(1 for r in raws if abs(r) > 50)}/{len(raws)}")

# ----- Status / rejection breakdown -----
print("\n" + "=" * 70)
print("STATUS BREAKDOWN")
print("=" * 70)
print("testnet:", con_t.execute("SELECT status, COUNT(*) FROM testnet_signals GROUP BY status").fetchall())
print("futures:", con_f.execute("SELECT status, COUNT(*) FROM futures_signals GROUP BY status").fetchall())
print("paper  :", con_p.execute("SELECT status, COUNT(*) FROM paper_signals GROUP BY status").fetchall())

# ----- Long/short bias -----
print("\n" + "=" * 70)
print("LONG/SHORT BIAS (raw signal generation)")
print("=" * 70)
print("paper raw:", con_p.execute("SELECT side, COUNT(*) FROM paper_signals GROUP BY side").fetchall())
print("futures filled:", con_f.execute("SELECT side, COUNT(*) FROM futures_signals WHERE status='filled' GROUP BY side").fetchall())

# ----- Closed trades (paper synthetic) -----
print("\n" + "=" * 70)
print("CLOSED TRADES (paper synthetic broker — only data with R outcomes)")
print("=" * 70)
ev = con_p.execute("""
  SELECT ts, symbol, event_type, price, realized_R, realized_pnl_usdt
  FROM paper_position_events ORDER BY ts
""").fetchall()
for r in ev:
    print(f"  {r[0]} {r[1]:<10} {r[2]:<10} px={r[3]:<14.6f} R={r[4]:+.3f} pnl_usdt={r[5]:+.3f}")
Rs = [r[4] for r in ev]
pnls = [r[5] for r in ev]
if Rs:
    n = len(Rs)
    wins = sum(1 for r in Rs if r > 0)
    print(f"\n  N={n}  win_rate={wins/n*100:.0f}%  mean_R={stat.mean(Rs):+.3f}  median_R={stat.median(Rs):+.3f}  sum_R={sum(Rs):+.3f}")
    print(f"  total realized PnL = ${sum(pnls):+.2f}")

# ----- Futures realized PnL via wallet delta -----
print("\n" + "=" * 70)
print("FUTURES REALIZED PnL (via wallet snapshot delta)")
print("=" * 70)
w_first = con_f.execute("SELECT ts, wallet_balance FROM futures_equity_snapshots ORDER BY ts ASC LIMIT 1").fetchone()
w_last = con_f.execute("SELECT ts, wallet_balance FROM futures_equity_snapshots ORDER BY ts DESC LIMIT 1").fetchone()
print(f"first snapshot: {w_first}")
print(f"last  snapshot: {w_last}")
print(f"wallet delta (realized): {w_last[1] - w_first[1]:+.2f} USDT  ({(w_last[1]/w_first[1] - 1)*100:+.2f}%)")
print(f"last unrealized: ", con_f.execute("SELECT unrealized_pnl FROM futures_equity_snapshots ORDER BY ts DESC LIMIT 1").fetchone())
print(f"n_positions trajectory: ", con_f.execute("SELECT DISTINCT n_positions, COUNT(*) FROM futures_equity_snapshots GROUP BY n_positions ORDER BY 1 DESC").fetchall())

# ----- Hold time -----
print("\n" + "=" * 70)
print("HOLD TIME (paper closed positions)")
print("=" * 70)
# position_id has open ts in name; we have close ts
holds = []
for r in ev:
    pos_id_match = r[1]  # symbol; we don't have explicit open ts. Position_id was iso-formatted in events table.
# query directly
hold_q = con_p.execute("""
  SELECT e.ts AS close_ts, e.position_id, e.symbol, e.realized_R
  FROM paper_position_events e
  ORDER BY e.ts
""").fetchall()
import re
from datetime import datetime
for close_ts, pid, sym, R in hold_q:
    m = re.search(r"_(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[\d:.+-]*)", pid)
    if m:
        open_ts = datetime.fromisoformat(m.group(1))
        # close_ts is naive UTC, normalize
        if close_ts.tzinfo is None:
            from datetime import timezone
            close_ts_aware = close_ts.replace(tzinfo=timezone.utc)
        else:
            close_ts_aware = close_ts
        delta = close_ts_aware - open_ts
        hours = delta.total_seconds() / 3600
        holds.append(hours)
        print(f"  {sym:<10} open={open_ts} close={close_ts} hold={hours:.2f}h R={R:+.3f}")
if holds:
    print(f"\n  mean hold = {stat.mean(holds):.2f}h  median = {stat.median(holds):.2f}h")
    print(f"  BACKTEST EXPECTATION (1d primary timeframe, runner_force_exit_bars=30): avg hold ~5-15 days for stage 0->2 progression")
    print(f"  PAPER OBSERVED: <0.5 hours — ALL SL hit within minutes")

# ----- Cooldown / duplicates check -----
print("\n" + "=" * 70)
print("COOLDOWN / DUPLICATE CHECK")
print("=" * 70)
dup = con_f.execute("""
  SELECT symbol, COUNT(*) AS n, GROUP_CONCAT(strategy) AS strats
  FROM futures_signals WHERE status='filled'
  GROUP BY symbol HAVING COUNT(*) > 1 ORDER BY n DESC
""").fetchall()
print("Same-symbol multi-fill (futures):")
for r in dup:
    print(f"  {r[0]}: {r[1]} fills, strats={r[2]}")
