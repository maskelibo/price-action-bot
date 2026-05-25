# Data Ingestion Agent (forex)

**Görev:** 10 forex pair × 4-5 yıl × {15m, 1m, tick} OHLCV indir + DuckDB/Parquet store + quality check.

**Kaynak önceliği:**
1. **Dukascopy** (ücretsiz tick `.bi5` LZMA) — `data/dukascopy.py`
2. HistData CSV — `scripts/download_data.py` fallback (TODO Phase 1)
3. Broker MT5 export — manual JSON dump

**Kalite gate (Faz 0):** Eksik mum < %0.5 (weekend filtering hariç), OHLC violation = 0, DST geçiş tespiti raporlu.

**Tetik:** `scripts/download_data.py --pair EURUSD --start 2021-01-01 --end 2026-01-01 --tf 15m`

**Çıktı:** `data/forex/forex.duckdb` + `data/forex/parquet/{pair}/{tf}/year=YYYY/month=MM/data.parquet`

**KPI:** Eksik mum oranı, gap count, weekend filter ratio, ingest latency.
