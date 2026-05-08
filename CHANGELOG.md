# CHANGELOG

## [0.2.0] — 2026-05-08 — CLI Adapter + Book Corpus

### Added
- **LLM CLI adapter** (`agents/base.py`): `_call_cli` + `_find_claude_cli` — `claude` CLI'ı subprocess olarak çağırır, `ANTHROPIC_API_KEY` gerektirmez (Claude Max subscription üzerinden auth). Windows'ta `.cmd` wrapper'ı atlayıp `claude.exe`'yi doğrudan çağırır (CMD argv 8K limiti aşmak için).
- **PA literatür corpus**: `knowledge/books/` altında 9 deep summary (Brooks, Volman, Grimes, Wyckoff, Kaufman, Chan, López de Prado, Harris, SMC/ICT) — ~40,600 kelime, 311 RAG chunk. Her özet pattern başına testable rules (Tanım/Bağlam/Giriş/Stop/Hedef/Edge/Failure) + statistical edge conditions + cross-references içerir.
- **Books ingester** (`scripts/ingest_books.py`) — `gather_items` tarafından okunmayan `books/*.md`'yi RAG corpus'a ingest eder.
- **YouTube ingest hazırlığı** (`scripts/ingest_youtube.py` + `docs/YOUTUBE_INGEST.md`) — manual `cookies.txt` ile yt-dlp/transcript-api anti-bot bypass akışı.
- **Otonom araştırma döngüsü** (`scripts/autonomous_research.py`) — 8 seed topic için Researcher + Lab + Analyst + CEO 4-agent tartışma loop'u, sonuç markdown raporu.
- **CLI smoke + live test scripts** (`cli_smoke.py`, `live_agents_test.py`) — gerçek CLI çağrılarıyla end-to-end agent doğrulaması.
- **RAG explorer komutu** (`pa rag query <text>`) — `--k`, `--source-type`, `--topic`, `--full` filtreli interaktif sorgu.
- **Caffeine** (`scripts/caffeine.ps1`) — uzun otonom run'larda Windows uyku modunu engeller.
- **Pattern definition regression tests** (39 test) — book özetlerindeki kuralları detector koduna karşı kilitler. Lookahead-bias truncation parity testi tüm candle detector'ları kapsar.
- **CLI adapter tests** (16 test) — `_call_cli`, `_ensure_client`, `_find_claude_cli` için subprocess mock'lu unit testler.

### Changed
- **Backtest engine bug fix** (`backtest/engine.py`): equity curve initial capital point eksikti → CAGR/Sharpe yanlış başlangıç değeriyle hesaplanıyordu. tz-aware vs naive timestamp handling de düzeltildi.
- **Confluence emit_signals bug fix** (`signals/confluence.py`): SL/TP config key okuma yolu (`risk.stop_loss.atr_multiplier` nested vs `risk.stop_loss_atr_mult` flat) — externally-routed sinyaller hatalı 1.5x ATR SL kullanıyordu.
- **`retrieve_for_hypothesis` topic filter genişletildi** (`rag/retrieve.py`): `behavioral_finance` eklendi. Önceki filtre kitap chunk'larını alfabetik sıralamada `behavioral_finance` ilk gelince tamamen filtreliyordu — corpus dolduğu halde 0 hit veriyordu.

### Doğrulama (post-v0.2.0)
- **218 test geçti** (önceki 156 → +62 net), 4 integration/live skip.
- 5 LLM agent CLI üzerinden canlı çağrıldı (Haiku ve Sonnet) — episodic memory'ye yazıldı.
- 9 kitap corpus'a ingest edildi (311 chunk), `pin bar at S/R` sorgusu top 10/10 PA-kitap chunk dönüyor (önceki 0/10).
- Backtest pipeline sentetik 200-bar BTC verisinde end-to-end çalıştı: 16 trade, %62.5 win rate, +%12.14 net P&L, -4.23% MaxDD.

### Bilinmeyenler / Açık Sorular
- 3y gerçek OHLCV ingest sonrası Faz 2 ROI gate'i geçer mi? (yıllık net > %70 / Sharpe > 1.5 / DD < %20)
- YouTube transkript ingest çalışınca corpus 2-3x zenginleşir mi? Nasıl bir hipotez kalitesi etkisi olur?
- Otonom araştırma v2 raporu (Sonnet + 9-kitap) PROMOTE çıkarır mı?

---

## [0.1.0] — 2026-05-08 — Bootstrap

### Added (Faz 0)
- Mimari iskele: 10 departman, 4 LLM-şefli + 6 deterministik.
- Tüm agent rule dosyaları (`agents/*.md`) — CEO / Researcher / Analyst / Lab Scientist / Data / Signal / Risk / Portfolio / Execution / Ops.
- Memory layer (per-agent identity / know-how / learning + shared facts / lessons / decisions / glossary).
- RAG corpus seed (`knowledge/seeds.yaml`) — Brooks, Wyckoff, Volman, Grimes, López, akademik feed'ler, YouTube kanalları.
- Konfigürasyon: symbols.yaml (3y, all_liquid universe), risk.yaml, strategies/classic_pa.yaml.
- Docker compose (postgres + prometheus + grafana + app).
- Python paketleri (settings, logging, contracts; data, signals, strategies, backtest, risk, portfolio, execution, ml, analytics, agents, orchestrator, rag, memory, api).
- Test iskelesi (unit + integration + live skip kategorileri).
- 4 ADR (architecture-bootstrap, llm-no-orders, phased-gates).
- 4 paylaşılan ders (lookahead-bias, survivorship-bias, overfitting-red-flags, leverage-discipline).
- 1 pre-registered hipotez (H-001: Pin Bar @ S/R + Trend Filter Edge).
- RUNBOOK.md, CONTRIBUTING.md, ARCHITECTURE.md, README.md.

### Doğrulama (post-bootstrap)
- **156 test geçti, 0 fail.** 4 integration/live test default skip (network gerektirir).
- 30 modül import + pattern detector + lookahead causality + Risk Officer +
  LLM dry-run + memory boot + filesystem bütünlüğü — `scripts/morning_smoke.py` ile yeşil.
- Prometheus duplicate metric bug'ı düzeltildi (canonical kaynak `api/prometheus_metrics.py`).
- `datetime.utcnow()` deprecation tüm dosyalarda timezone-aware'e taşındı (Python 3.13 hazır).
- `tests/test_risk.py` make_signal fixture'ı 1D crypto için realistik SL'e güncellendi.

### Faz Gate
- Faz 0 gate (eksik mum < %0.1) bekleniyor — ilk veri çekimi sonrası ölçülecek.

### Bilinmeyenler / Açık Sorular
- Backtest'te ilk gate (Faz 2) hedefe ulaşıyor mu? — ilk run sonrası belli olur.
- ML signal filter (Faz 4) gerçekten uplift veriyor mu? — Faz 2-3 sonrası gözlemlenir.
- LLM brief kalitesi (Faz 5) insan tarafından nasıl değerlendiriliyor? — sürekli geri bildirim.
