"""Parse futures_daemon.log for position transitions, fills, and wallet jumps."""
import re
from pathlib import Path

LOG = Path(r"C:\Users\koray\projeler\Price Action\logs\futures_daemon.log")

lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
print(f"total log lines: {len(lines)}")

# Track POS_CHECK syms over time
import collections

pc_re = re.compile(r'\[(\d+:\d+:\d+)\] POS_CHECK: (\d+) pos.*\| (.*)$')
sn_re = re.compile(r'\[(\d+:\d+:\d+)\] SNAPSHOT: wallet=\$([\d.]+),')

last_syms = None
last_wallet = None
events = []  # transitions
for i, line in enumerate(lines):
    m = pc_re.search(line)
    if m:
        t, npos, body = m.group(1), int(m.group(2)), m.group(3)
        # extract symbol -> qty (catch dup syms; XRP appears twice with different qty)
        sym_qty = []
        for s, qty in re.findall(r'([A-Z]+)=[SL]([\d.]+)', body):
            sym_qty.append((s, float(qty)))
        sym_count = tuple(sorted([(s, q) for s, q in sym_qty]))
        if last_syms is not None and sym_count != last_syms:
            old_set = set(last_syms)
            new_set = set(sym_count)
            removed = old_set - new_set
            added = new_set - old_set
            events.append((t, 'POSCHG', f'removed={removed} added={added} npos={npos}'))
        last_syms = sym_count
        continue
    m = sn_re.search(line)
    if m:
        t, w = m.group(1), float(m.group(2))
        if last_wallet is not None and abs(w - last_wallet) > 0.5:
            events.append((t, 'WALLET', f'{last_wallet:.2f} -> {w:.2f} delta={w-last_wallet:+.2f}'))
        last_wallet = w

for e in events:
    print(e)
