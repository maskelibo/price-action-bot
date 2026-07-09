"""Ad-hoc borsa-truth PnL status (v14). Income-based, LAST-price unrealized, TR time."""
from __future__ import annotations
import os, sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)
from scripts.futures_trade_daily import get_futures_exchange

ANCHOR_MS = int(datetime(2026, 6, 10, 22, 4, 44, tzinfo=UTC).timestamp() * 1000)  # v14 $5000 start
CLEAN_MS = int(datetime(2026, 6, 14, 21, 53, 0, tzinfo=UTC).timestamp() * 1000)   # champion retired
NOW_MS = int(datetime.now(UTC).timestamp() * 1000)

def tr(ts_ms):
    return (datetime.fromtimestamp(ts_ms / 1000, UTC) + timedelta(hours=3)).strftime("%d %b %H:%M")

ex = get_futures_exchange()

# --- income (paginate) ---
def fetch_income(start_ms):
    out = []; cur = start_ms
    while cur < NOW_MS:
        batch = ex.fapiPrivateGetIncome({"startTime": cur, "endTime": NOW_MS, "limit": 1000})
        if not batch:
            break
        out.extend(batch)
        last = int(batch[-1]["time"])
        if len(batch) < 1000:
            break
        cur = last + 1
    # dedup by tranId+time+type
    seen = set(); uniq = []
    for r in out:
        k = (r.get("tranId"), r.get("time"), r.get("incomeType"), r.get("income"))
        if k in seen: continue
        seen.add(k); uniq.append(r)
    return uniq

inc = fetch_income(ANCHOR_MS)
def summ(rows):
    rp = sum(float(r["income"]) for r in rows if r["incomeType"] == "REALIZED_PNL")
    cm = sum(float(r["income"]) for r in rows if r["incomeType"] == "COMMISSION")
    fn = sum(float(r["income"]) for r in rows if r["incomeType"] == "FUNDING_FEE")
    return rp, cm, fn

rp, cm, fn = summ(inc)
clean = [r for r in inc if int(r["time"]) >= CLEAN_MS]
crp, ccm, cfn = summ(clean)

# realized closes: REALIZED_PNL rows (net of their commission by symbol)
closes = [r for r in inc if r["incomeType"] == "REALIZED_PNL" and float(r["income"]) != 0.0]
# per-symbol net realized (clean period)
from collections import defaultdict
sym_net = defaultdict(float); sym_n = defaultdict(int)
clean_closes = [r for r in closes if int(r["time"]) >= CLEAN_MS]
for r in clean_closes:
    sym_net[r["symbol"]] += float(r["income"]); sym_n[r["symbol"]] += 1
# attach commission to realized for net-per-trade view (approx: realized only here)

# --- positions ---
poss = [p for p in ex.fetch_positions() if abs(float(p["info"].get("positionAmt", 0))) > 0]
tickers = {}
rows_pos = []
for p in poss:
    s = p["symbol"]
    amt = float(p["info"]["positionAmt"]); entry = float(p["info"]["entryPrice"])
    try:
        last = float(ex.fetch_ticker(s)["last"])
    except Exception:
        last = float(p["info"].get("markPrice", entry))
    side = "LONG" if amt > 0 else "SHORT"
    upnl = (last - entry) * amt
    rows_pos.append((s, side, abs(amt), entry, last, upnl))
rows_pos.sort(key=lambda x: -x[5])

bal = ex.fetch_balance()
wallet = float(bal["info"]["totalWalletBalance"]); margin = float(bal["info"]["totalMarginBalance"])
upnl_total = sum(x[5] for x in rows_pos)

print("=" * 62)
print(f"BORSA-TRUTH PnL  ·  {tr(NOW_MS)} TR")
print("=" * 62)
print(f"NET realized (TÜM v14, {len([r for r in closes])} kapanış, anchor {tr(ANCHOR_MS)}):")
print(f"   REALIZED {rp:+.2f}  COMMISSION {cm:+.2f}  FUNDING {fn:+.2f}  => NET {rp+cm+fn:+.2f}")
print(f"└ TEMİZ dönem (champion sonrası {tr(CLEAN_MS)}, {len(clean_closes)} kapanış):")
print(f"   REALIZED {crp:+.2f}  COMMISSION {ccm:+.2f}  FUNDING {cfn:+.2f}  => NET {crp+ccm+cfn:+.2f}")
print(f"UNREALIZED (LAST): {upnl_total:+.2f}")
print(f"TOPLAM equity vs $5000: {(wallet+upnl_total)-5000:+.2f}")
print(f"Cüzdan(wallet) {wallet:.2f} | Margin(equity) {margin:.2f}")
print("=" * 62)
print(f"AÇIK POZİSYONLAR ({len(rows_pos)}):")
for s, side, q, e, l, u in rows_pos:
    print(f"   {s:<12} {side:<5} qty={q:<10g} entry={e:<10g} last={l:<10g} uPnL {u:+.2f}")
print("=" * 62)
print("KAPANANLAR — TEMİZ dönem sembol-bazlı (realized, fee hariç):")
for s in sorted(sym_net, key=lambda k: -sym_net[k]):
    print(f"   {s:<12} {sym_net[s]:+.2f}  ({sym_n[s]} kapanış)")
print("-" * 62)
print("Son ~10 kapanış (kronolojik, realized):")
for r in sorted(clean_closes, key=lambda r: int(r["time"]))[-10:]:
    print(f"   {tr(int(r['time']))} TR  {r['symbol']:<12} {float(r['income']):+.2f}")
