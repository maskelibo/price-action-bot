# memory/protocol/

Inter-agent message bus kalıcı backup'ı.

## Dosyalar

- `inbox.jsonl` — append-only mesaj log'u (gitignore'da, runtime). Her satır bir mesaj:
  ```json
  {"doc_id":"researcher-20260525T120000-vsa-only-d2","sender":"researcher","recipient":"lab_scientist","topic":"new_hypothesis","ref_path":"memory/researcher/hypotheses/2026-05-25-vsa-only-d2.md","created_at":"2026-05-25T12:00:00Z","ack_at":null}
  ```
- `archive/YYYY-WW.jsonl` — haftalık rotasyon (Faz 4 sonrası, `_job_weekly_consolidation` tarafından)

## Kurallar

- Append-only, satır silme YASAK
- doc_id duplicate olursa protokol ihlali — `ops_engineer` flag
- Reviewer ack ederken aynı doc_id ile yeni satır YAZMAZ; mevcut satırda `ack_at` doldurulur (atomik UPDATE — `tools/inbox_ack.py` helper)
- Manuel inspeksiyon: `jq` ile sorgu, örnek:
  ```bash
  jq 'select(.recipient == "risk_officer" and .ack_at == null)' memory/protocol/inbox.jsonl
  ```

Bkz: `memory/shared/protocol.md` — full spec.
