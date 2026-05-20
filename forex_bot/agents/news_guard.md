# News Guard Agent (forex)

**Görev:** High-impact ekonomik event'ler etrafında [-30dk, +30dk] entry blackout; açık pozisyonlarda stop tightening / flat-close.

**Kaynaklar:**
1. ForexFactory haftalık JSON: `https://nfs.faireconomy.media/ff_calendar_thisweek.json` (otomatik)
2. Cached static CSV: `news/cached_calendar.csv` (offline + historical events)

**İçerik:**
- Currency (USD, EUR, GBP, JPY, ...), impact (high/medium/low), title, ts_utc.
- Yalnızca **high** impact filtrelenir (NFP, FOMC, ECB, BoE, BoJ, CPI, GDP).

**Etki:**
- `is_blackout(ts, pair) → bool`: event'in para birimi pair içinde geçiyorsa ±30dk blok.
- `should_tighten_stop(ts, pair) → bool`: lookahead 60dk, açık pozisyonu manage etmek için.
- Backtest engine: blackout başlangıcında stage 0 trade'leri flat kapatır (config-flagged).

**KPI:** False blackout oranı, NFP wick koruması, swap-day handling.
