# Session Agent (forex)

**Görev:** Her bara seans etiketi yapıştır (Asia / London / London-NY overlap / NY / Off), session-aware ATR percentile regimes hesapla.

**UTC eşik (DST tolere):**
- 21:00-07:00 → asia
- 07:00-12:00 → london
- 12:00-16:00 → london_ny_overlap (en yüksek vol)
- 16:00-21:00 → ny
- Fri 21:00 – Sun 21:00 → off

**Pair × Session quality score** (config'de tablolu): EURUSD/GBPUSD London-heavy, USDJPY/AUDUSD/NZDUSD Asia-aktif, EURGBP London-only.

**Sinyal pipeline'da rol:**
- Strategy `sessions_allowed` listesi dışındaki sinyaller reject.
- Confluence ağırlığında `session_score` 0.10 katkı.
