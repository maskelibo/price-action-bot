import json

inbox_path = 'memory/protocol/inbox.jsonl'
lines = open(inbox_path).readlines()

critique_entry = {
    "doc_id": "risk_officer-20260624T040106-critique-tournament-2026-w26",
    "sender": "risk_officer",
    "recipient": "ceo",
    "topic": "critique",
    "ref_path": "memory/risk_officer/decisions/risk_officer-20260624T040106-critique-tournament-2026-w26.md",
    "created_at": "2026-06-24T04:01:06Z",
    "ack_at": None
}

updated = []
for line in lines:
    line = line.strip()
    if not line:
        continue
    entry = json.loads(line)
    if (entry['doc_id'] == 'lab_scientist-20260624T040106-tournament-2026-w26'
            and entry['recipient'] == 'risk_officer'):
        entry['ack_at'] = '2026-06-24T04:01:06Z'
    updated.append(json.dumps(entry, ensure_ascii=False))

updated.append(json.dumps(critique_entry, ensure_ascii=False))

with open(inbox_path, 'w') as f:
    f.write('\n'.join(updated) + '\n')

print(f'inbox updated: {len(updated)} lines')
