---
agent: ops_engineer
type: know_how
created: 2026-05-08
---

# Ops Engineer Know-How

---

## Runbook: Servis Sağlık Kontrolü
| Servis | Komut | Beklenen |
|---|---|---|
| Postgres | `pg_isready -U pa` | accepting connections |
| DuckDB | `python -c "import duckdb; print(duckdb.connect('data/market.duckdb').execute('select count(*) from ohlcv').fetchone())"` | non-zero |
| ChromaDB | `python -c "import chromadb; c=chromadb.PersistentClient('knowledge/index'); print(c.list_collections())"` | listede |
| Scheduler | `prometheus_client` `pa_scheduler_last_tick` < 2dk | OK |
| Execution WS | `pa_execution_ws_heartbeat_seconds` < 60 | OK |
| API | `curl -fsS localhost:8000/health` | 200 |

---

## Runbook: Telegram Alarm Throttling
- Aynı `alert_id` 5 dk içinde max 1.
- 5 dk sonra digest mesajı: "(+N more X alerts)".
- CRIT seviyesi throttle muaf.

---

## Runbook: Incident Summary (LLM)
1. İlgili logu son 1 saat çek.
2. Metrik snapshot (5dk öncesi vs şimdi).
3. Haiku'ya 200 kelimelik şablonla özet yazdır:
   - trigger
   - kapsam
   - etki
   - kök neden hipotezi
   - takip aksiyon
4. `reports/ops/incidents/<id>.md` taslak; insan revize eder.

---

## Runbook: Backup
- Postgres: günlük `pg_dump`, son 7 gün + haftalık 4 ay tutulur.
- DuckDB: dosya kopyası + checksum.
- ChromaDB: dizin tar.gz.
- `data/parquet/`: append-only zaten; yedekleme isteğe bağlı.

---

## Runbook: Kill-Switch
- Telegram'dan `HALT_TRADING` komutu (chat_id whitelisted).
- Redis flag: `trading_halt = 1`.
- Execution flag'i okur, yeni emir red.
- CLI resume: `pa ops resume --confirm`.

---

> Yeni runbook ekle, eskisini silme.
