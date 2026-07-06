# PROJE_RAPORU.md — Bağımsız Mimari Denetim

**Denetim tarihi:** 2026-07-06 · **Branch:** `audit-hardreview-20260528` · **Yöntem:** read-only inceleme (5 paralel keşif + canlı sistem gözlemi). Her iddia dosya:satır kanıtlıdır. Hiçbir kod değiştirilmedi.

---

## 1. Yönetici özeti

Proje, Binance USDM **testnet** üzerinde 15 dakikalık price-action stratejileri koşturan, deterministik bir emir/risk katmanının etrafına ~15 LLM ajanından oluşan bir "araştırma-denetim şirketi" örülmüş otonom bir trading sistemidir. Emir veren kod tamamen deterministik Python'dur; LLM'ler yalnızca araştırma, analiz, risk eleştirisi ve iç denetim raporu üretir ("LLM emir veremez", `src/price_action/agents/base.py:353`). Olgunluk: **çalışır prototip / pre-production** — canlı daemon (v15p2) bugün itibarıyla testnette pozisyon açıp yönetiyor, 2.396 test 2.9 saniyede toplanıyor, CI + iç denetim hattı var; ama gerçek parayla tek işlem yapılmamış, araştırma fabrikası 48 denemede 0 strateji terfi ettirmiş ve dokümantasyon fiili durumun 2 ay gerisinde. Tek cümlelik teşhis: **savunma hattı (risk/execution) production kalitesinde, hücum hattı (edge üretimi) ve operasyonel dayanıklılık (tek makine) zayıf; sistem şu an "çok iyi korunan küçük bir hiç"i işletiyor.**

## 2. Hedef hizası

`GOAL.md` **yok**. README'nin vaadi ile bugünkü gerçek arasındaki sapmalar:

- README "10 departmanlı otonom şirket" vaat ediyor (`README.md:31`) — **gerçekleşmiş**, hatta aşılmış (11 runtime ajan + 6 kişilik denetim ailesi + 3 deterministik departman).
- README **1D+1W swing** sistemi tarif ediyor (`README.md:3`); gerçekte canlı sistem **15m scalp** (v15p2, 2 strateji: grimes_abc + vsa_climax, `configs/risk_phoenix_scalp_15m_v15p2.yaml:156-164`). README'deki faz kapısı (OOS yıllık >%70 net, `README.md:5`) fiilen terk edilmiş; yerine lab kapıları (DSR p<0.05, robustness suite) geçmiş. README hâlâ "Faz 0 tamam, Faz 1-7 bekliyor" diyor (`README.md:59-66`) — **bayat**.
- Aktif config'in başlığında hâlâ **"AKTİF DEĞİL; robustness+OK bekler"** yazıyor (`risk_phoenix_scalp_15m_v15p2.yaml:2`) ama bu dosya canlı daemon'a bağlı (`scripts/futures_daemon_v14.py:51`). Doc-vs-deploy tutarsızlığı.
- Deploy edilen `com.priceaction.futures_v15p2.plist` (`~/Library/LaunchAgents/`) **repoya commit edilmemiş**; sadece `.sh` wrapper'ı izleniyor (`ops/launchd/run_futures_v15p2.sh`).
- "Her trade reproducibility manifest'li" vaadi (`README.md:70-73`) backtest tarafında tutuyor (bkz. §15), LLM raporları tarafında tutmuyor.
- Performans vaadi hizası: backtest %/ay sayılarının compounding ile ~10-25× şişik olduğu iç raporlarla tespit edilmiş; dürüst beklenti bandı canlıda +%8-12/ay olarak revize edilmiş (RESUME/memory kayıtları). README bu gerçekçi bandı hiç yansıtmıyor.

## 3. Mimari

**Uçtan uca veri akışı:**

```
Binance/Bybit (testnet+mainnet data)
  → ingest (5dk launchd + saatlik cron) → market_ingest.duckdb   [üretici]
  → market_snapshot (saatlik :05, atomik os.replace) → market.duckdb  [tüketici, RO]
  → futures_daemon_v14.py (launchd, 15dk bar-close tick)
      → detektörler (grimes/vsa) → RiskOfficer.evaluate() kapı zinciri
      → order router (idempotent client_order_id) → Binance TESTNET emri
      → TP/SL algo emirleri + journal (futures_journal_v15p2.duckdb)
  → izleme: DMS, reconcile (15dk), bot_monitor, freshness/promise watchdog
  → LLM ajan fabrikası (ceo_loop + APScheduler ~60 cron) → reports/ + Telegram
```

**Bileşenler:** `src/price_action/` altında 20 paket — `data/` (ingest+kalite), `signals/`+`strategies/` (vektörize detektörler), `risk/` (sizing/breaker/gates/regime), `execution/` (router'lar, idempotency, DMS, reconcile, slippage), `orchestrator/` (ceo_loop + 2.702 satırlık `scheduler.py`), `agents/` (LLM katmanı), `rag/`, `notifications/`, `backtest/`+`lab/`. **Entry point'ler:** `scripts/futures_daemon_v14.py` (faz seçimi `PA_V14_PHASE`, `:44-54`), `pa-ceo` → `orchestrator/ceo_loop.py`, `scripts/ingest_15m_live.py`, `scripts/dashboard/server.py`. **Dış bağımlılıklar:** ccxt (Binance/Bybit), Anthropic API + Claude CLI/Agent SDK, ChromaDB+sentence-transformers, CoinGecko/alternative.me/Coin Metrics (alt-data), Dukascopy/HistData (forex), YouTube transcript, Telegram Bot API, APScheduler, DuckDB/Parquet. Docker-compose'da postgres/prometheus/grafana tanımlı ama fiili runtime **launchd/macOS lokal**.

## 4. Agent envanteri

İki paralel ajan tanımı var (kritik bulgu): (a) **runtime Python ajanları** (`src/price_action/agents/*.py`, `LLMAgentBase` `base.py:281`) — gerçekten koşan bunlar; (b) `.claude/agents/*.md` Claude Code spec'leri — **daemon bunları hiç yüklemiyor**. Runtime persona `agents/<ad>.md`'den okunur (`base.py:314-315`); system prompt = persona + protokol + hafıza boot-context + izinli araçlar (`base.py:334-360`).

| Ajan | Sınıf | Model | Çıktı | Tetik (cron, UTC) |
|---|---|---|---|---|
| CEO | `ceo.py:30` | Opus 4.7 | `reports/ceo/` | brief 23:00 zinciri; state refresh :25 |
| Researcher | `researcher.py:32` | Opus | `memory/researcher/hypotheses/` | 02:00, 02:30, pulse 06/18 |
| Analyst | `analyst.py:25` | Opus | `reports/analytics/`, postmortems | 23:00, 23:30 |
| Lab Scientist | `lab_scientist.py:21` | Opus | `reports/lab/`, param_sweep | tournament 04:00 gün, 03:00 Paz |
| Risk Officer | `risk_officer.py:31` | **Sonnet** (hardcoded `:33`) | `reports/risk/` | inbox review :15 |
| Adversary Eng. | `adversary_engineer.py:28` | Opus | `reports/adversary/` | stress 04:00, red-team Paz |
| Bot Monitor | `bot_monitor.py:131` | **Haiku** | `reports/bot_monitor/` | :20 saatlik, cards 22:00 |
| Strategy Curator | `strategy_curator.py:187` | Opus | `reports/curator/` | corr 19:00, lifecycle Paz |
| Market Scout | `market_scout.py:37` | Opus | `reports/market_scout/` | aylık/haftalık |
| Ops Eng. | `ops_engineer.py:15` | Haiku | `reports/ops/` | incident-driven |
| Data Eng. | `data_engineer.py:23` | Haiku | `reports/data_engineer/` | 06:30 |
| audit_chief + 5 domain auditörü | `audit_base.py:99` ailesi | Opus | `reports/audit/` + `memory/audit/findings_register.jsonl` | 03:00-03:30 günlük/haftalık |

**Kusur:** `adversary_engineer`, `bot_monitor`, `market_scout` ve tüm `audit_*` için runtime persona dosyası **eksik** — `_load_rules` boş string döner (`base.py:319-322`); zengin personalar `.claude/agents/`'ta duruyor ama daemon'a hiç ulaşmıyor. Deterministik (LLM'siz) departmanlar: execution_chief, portfolio_manager, signal_chief (token kaydı sıfır, `token_budget.py:165-167`).

## 5. Orkestrasyon

Sıralı DAG değil, **cron-merkezli heartbeat** modeli: ceo_loop içinde in-process APScheduler, ~60 job (`scheduler.py:2500-2593`). Tetikler: launchd (daemon/ingest/backup/logrotate, KeepAlive+RunAtLoad), iç cron (LLM işleri), event bus (`data/events/*.jsonl`, 15dk'da bir dispatch, `scheduler.py:2538`), dosya-inbox protokolü (`memory/protocol/inbox.jsonl`, saatlik review). **Retry/timeout:** LLM circuit breaker (5 hata/5dk → 10dk açık, `base.py:66-206`), CLI eşzamanlılık semaforu 3 (`base.py:49-58`), ingest fail-loud exit-1, entry hataları async `pending_retries` kuyruğuna düşer (daemon logu `15M_ENTRY_DEFERRED`). Scheduler canary'si restart sonrası gerçekten koştuğunu doğrular (`ceo_loop.py:41-96`). **Paralellik:** ajanlar bağımsız cron'larda; context izolasyonu tam — her ajan kendi hafıza boot-context'iyle ayrı LLM çağrısı, sonuçlar frontmatter'lı protokol dokümanı olarak diske yazılıp inbox'a yayınlanır (`base.py:799-931`). **Yapısal zafiyet:** makine kapalıyken kaçan job'lar geri koşulmaz — 4-6 Tem ~44 saatlik kapanmada tüm hafta sonu job'ları kayboldu; catch-up elle yapıldı (bkz. §13).

## 6. Hafıza & durum

- **Sıcak (aktif context):** `MemoryStore.boot_context()` her çağrıda IDENTITY + KNOW-HOW + son 25 learning bloğu (24K karakter tavanı) + shared lessons'ı prompt'a enjekte eder (`memory/store.py:286-351`). Kod yorumu geçmiş bir bug'ı itiraf ediyor: eskiden birikimin ~%5'i yükleniyordu (`store.py:292-298`) — düzeltilmiş ama learning dosyaları büyümeye devam ediyor (researcher: 280KB).
- **Ilık (yapısal durum):** DuckDB'ler — journal (`futures_journal_v15p2.duckdb`; şema `execution/trade_journal.py:127`), idempotency (`execution/idempotency.py:48`), pyramid store, breaker state JSON (atomik yazım, `risk/breaker.py:235-256`), `logs/state/*.json`, findings register (append-only, last-line-wins, `audit_base.py:150-161`).
- **Soğuk (arşiv):** `reports/` (59MB, 25+ dizin), `data/backups/` (günlük, 3 gün retention), `RESUME_*.md` devir notları, episodic JSONL'ler.
- **Yeniden kullanım — evet:** learning/know_how sonraki çağrılara giriyor, inbox ACK döngüsü var (`researcher.py:605-640`), haftalık konsolidasyon cron'u var (`scheduler.py:2592`). Ama hafıza tamamı markdown-append; hiçbir zaman budanmıyor (24K cap dışında).

## 7. RAG

**Gerçek vektör RAG var:** ChromaDB persistent (`knowledge/index/chroma.sqlite3`, 17.6MB, **1.606 embedding**, koleksiyon `price_action_corpus`). Embedding: `all-MiniLM-L6-v2` (`rag/store.py:23`), cosine HNSW. Chunking: markdown başlık-hiyerarşisi duyarlı, 512 token / 64 overlap (`rag/chunker.py:46-47`). İçerik: 28 kitap özeti (`knowledge/books/`), RSS/web (trafilatura), YouTube transcript'leri; SHA-256 içerik dedup (`rag/store.py:127-148`). Retrieval noktaları: `researcher.py:141-159` (hipotez üretimi, k=10), `market_scout.py:225,348`, `lab_scientist.rag_refresh()` (Pazar 04:00, boş-korpus koruması `scheduler.py:502`). **Gözlem:** retrieval kalitesi ölçülmüyor (recall/precision izlemesi yok); LLM topic-tagging placeholder, keyword tagger'a düşüyor (`rag/ingest.py:151-156`); RAG metni prompt'a yalnızca delimiter ile giriyor — sanitizasyon yok (bkz. §12).

## 8. Veri katmanı

- **Kaynaklar:** OHLCV (Binance→Bybit fallback; 15m her 5dk launchd, saatlik delta cron), funding/OI/dominance/sentiment/stablecoin/on-chain (manuel backfill), forex 4H (Dukascopy→HistData; yfinance hattı **kanıtlanmış bozuk** ve terk edilmiş, `forex_ingest_dukascopy.py:6-11`), YouTube/RSS/kitap (RAG).
- **Gerçek/sentetik ayrımı disiplinli:** sentetik adversarial senaryolar açıkça etiketli (`scripts/adversarial_data_gen.py` → `data/adversarial/`); liquidation "proxy" olduğu belgelenmiş.
- **Depolama:** üretici/tüketici DuckDB ayrımı (lock-çakışması incident'i sonrası; `ingest_15m_live.py:180-186`, `store.py:40-53`) + atomik snapshot (`ingest_ccxt.py:287`). Parquet: `venue/symbol/tf/year/month` (binance 931, bybit 730 sembol). OHLCV DDL: `store.py:242-255`.
- **Doğrulama: flag-not-fix.** 6 kontrol (gap/duplicate/OHLC-ihlal/hacim-outlier/fiyat-sıçrama/stale, `data/quality.py:77-140`); forward-fill/clip/winsorize **yasak** (`ingest_15m_live.py:160`). Günlük manifest 39 gündür yazılıyor (`data/quality/*.json`).
- **Riskler:** `futures_signals` DDL'i merkezi modülde değil script'lerde (`scripts/bot_factory.py:203`) — şema kayması riski; `data/` 11GB (market+ingest+bak ≈ 4.5GB, düzinelerce versiyonlu journal/pool dosyası); BTC 15m'de 390 gap sadece loglanmış durumda. Lisans: borsa OHLCV kullanımı sorunsuz; YouTube/kitap içeriği için bkz. §16.

## 9. Sözleşmeler & dayanıklılık

Pydantic modeller sınırlarda var: `contracts.py` (Signal/Fill/RiskedOrder/Reject/Position), `settings.py` (BaseSettings), `sizing.py:122-136` `_RiskConfig`. **Zayıflık:** `_RiskConfig(extra="allow")` — yazım hatalı bir risk anahtarı sessizce yutulur; bunu kısmen daemon'un startup **VERIFY kapısı** telafi eder (risk_per_trade/sl_pct_min/breaker eşikleri/pyramid/strateji sayısı assert edilir, uyuşmazlıkta `SystemExit`, `futures_daemon_v14.py:113-173`). Doğrulama başarısızlığı = gürültülü çökme (fail-loud), sessiz devam yok. **Idempotency:** deterministik `PA_<fingerprint>` client_order_id + DuckDB `INSERT OR IGNORE` — restart-safe (`idempotency.py:65-114`). **Checkpoint/resume:** daemon bar-close döngüsünde stateless; durum journal+borsadadır, reconcile job'u 15 dakikada bir drift'i onarır (orphan close, phantom dedup, qty-drift, `scripts/reconcile_journal.py`). **Kısmi başarı:** entry hatası pozisyon döngüsünü durdurmaz (`pending_retries`); çıplak-pozisyon savunması 3 katman (ORPHAN 3-tick onay, JOURNAL_HEAL, PROT_WATCHDOG + -2022 fallback, `futures_daemon.py:987-1150, 1865-1881`).

## 10. Kalite & eval

- **Testler güçlü:** 135 dosya, 2.396 test (collect 2.9s). Lookahead korumaları sistematik (~39 dosya; `tests/test_lookahead.py:82`, regime causal-date testleri); numba-parity bit-for-bit; determinism suite; audit kontrolleri için 30 deterministik test (`tests/audit/test_audit_findings.py`).
- **CI var:** `.github/workflows/ci.yml` — ruff, mypy (kısmi, non-blocking), core-6 suite **blocking** + coverage ≥70, bandit (HIGH→fail), pip-audit, SEC53 pool-reproducibility kapısı. **Şerh:** tam suite `continue-on-error` ile yalnızca bilgilendirici — yeşil CI ≠ tüm testler yeşil; mypy `strict=false`.
- **Backtest kalite kapıları:** oracle-baseline lookahead alarmı (`backtest/engine.py:262-271`), EER leakage testleri, shuffle baseline + Bonferroni (`scripts/sec54_reproducibility_drift.py`).
- **En büyük boşluk:** **LLM çıktıları için hiçbir eval yok** — golden set yok, LLM-as-judge yok, prompt değişiminde regresyon testi yok. Kalite kapıları yalnızca sayısal backtest dünyasında.

## 11. Guardrails

- **Canlı-para kilidi dört katman:** `PA_RUN_MODE=live` + `PA_LIVE_CONFIRM=YES_I_KNOW` + `risk.yaml live_mode_enabled:true` + `binance_testnet=false` hepsi birden gerekli (`execution/ccxt_live.py:52-72`, `settings.py:113-114`); üstelik deploy edilen wrapper `PA_LIVE_CONFIRM` set edilmişse **çalışmayı reddeder** (`futures_daemon_v14.py:69-72`) — mevcut haliyle canlı emir **erişilemez**.
- **Kod-seviyesi sert limitler** (yorum: "CEO bile bypass edemez", `sizing.py:142-143`): risk/trade %1, WIDESTOP sl_pct_min 0.025 (startup assert), max 16 pozisyon / 4 aynı-yön, notional %15, sembol %15, kaldıraç ≤3x, likidite/korelasyon(>0.9 blok)/konsantrasyon/margin-güvenlik kapıları; breaker'lar günlük %4 / haftalık %8 / 5 ardışık zarar; regime cache bayatsa **fail-closed** (`sizing.py:525-555`).
- **İnsan onay kapıları:** canlıya geçiş (yukarıdaki 4 kilit), `configs/risk*.yaml` değişikliği kural olarak Principal'a ait; strateji terfisi lab kapıları + adversary kill-probe + Principal onayı.
- **Geri alınamaz aksiyonlar ve önlerindeki koruma:** (1) borsa emirleri — risk kapı zinciri + idempotency + kill-switch + testnet; (2) DMS acil flatten — tasarımı gereği otonom (30dk heartbeat timeout, `dead_mans_switch.py:56,221-286`); (3) Telegram gönderimi — throttle (1/5dk/tip); (4) backup prune / log rotate — retention kurallı; (5) git push — runtime kodda **yok**.
- **Boşluk:** token bütçesi yalnızca **soft** — `check_budget` WARN/CRIT üretir ama çağrıyı bloklamaz (`token_budget.py:175-211`); harcama tavanı fiilen alarm, fren değil.

## 12. Güvenlik

- **Secrets:** pydantic-settings ile `.env`'den (`settings.py:14-22`); `.env` git-ignored, `git ls-files`'ta yalnız `.env.example`; tracked dosyalarda hardcoded secret taraması **temiz**; pre-commit'te gitleaks var. Şerh: diskte `.env.backup-pre-rotate-20260528` duruyor (600 izinli, git dışı) ve loglara anahtar yazma yasağı prompt'ta (`base.py:355`).
- **Prompt injection yüzeyi (dıştan gelen her metin):** (1) **YouTube transcript → RAG → prompt** — `researcher.py:141-159`: metin + saldırgan-kontrollü author/source_id, yalnızca `--- RAG REFERENCES ---` delimiter'ıyla, **sanitizasyonsuz** giriyor (ana yüzey); (2) RSS/web makaleleri — aynı yol; (3) WebSearch/WebFetch — Claude CLI native, uygulama-seviyesi filtre yok; (4) borsa API cevapları LLM'e **girmiyor** (execution deterministik); (5) Telegram inbound **yok** (yalnız gönderim) — komut enjeksiyonu yüzeyi kapalı. Talimat/veri ayrımı: yalnızca delimiter konvansiyonu. **Blast radius sınırlı** çünkü ajanlar emir veremez; ama CLI `--permission-mode acceptEdits` ile çağrılıyor (`base.py:674-680`) — enjekte edilmiş talimat ajanın hafıza/rapor dosyalarını zehirleyebilir (kalıcı memory-poisoning vektörü).
- **API key kapsamları:** Binance anahtarları testnet; Anthropic anahtarı tam yetkili; Telegram bot tek chat'e kilitli.

## 13. Runtime & operasyon

**Tek lokal macOS makinesi** (launchd; container'lar tanımlı ama kullanılmıyor). Job'lar: `com.priceaction.{futures_v15p2, ceo, dashboard, ingest15m, dbbackup, logrotate}` + `com.peyman.caffeinate` (uyku engeli). **Healthcheck katmanları:** DMS (30dk timeout → flatten), freshness watchdog (:12), promise/reality detektörü (:55, `configs/promises.yaml`), scheduler canary, truth report (06:00 TR), bot_monitor saatlik. **Alerting:** Telegram, tip-başına throttle. **Çökme sonrası:** launchd KeepAlive+RunAtLoad ile otomatik ayağa kalkma — 6 Tem reboot'unda tüm sistem elle müdahalesiz döndü. **Kanıtlı zafiyet:** 4-6 Tem ~44 saat kapalılıkta tüm zamanlı işler kaçtı ve **geri koşulmadı** (veri backfill + denetim + yedek elle tamamlandı); tek-makine SPOF. **Log:** `app.log` loguru ile 200MB/14 gün rotasyonlu (`logging_config.py:140`) — 147MB henüz eşik altında, bug değil (raporun ilk sürümündeki "rotate bug" iddiası DÜZELTİLDİ); disk ~%90+ dolu (izlemede, asıl tazyik `data/backups` 3.5G + `market.duckdb.bak` 1.5G). 6 Tem'de promise-checker'da bulunan "donmuş log sonsuza dek PASS" kör noktası düzeltildi (`scripts/check_promises.py` mtime-gate).

## 14. Maliyet

- **Routing statik, ajan-başına:** Opus (muhakeme ajanları), Sonnet (risk_officer), Haiku (monitor/ops/data) — görev-bazlı dinamik routing yok (`base.py:302`). **Prompt caching kullanılmıyor** (`base.py`'de cache_control yok), **Batch API yok**.
- **Gerçek kullanım (son 7 gün, `data/llm_calls.jsonl`):** 61 çağrı, 8.41M input / 255K output. Model dağılımı: Opus 4.7 6.91M, Sonnet 4.6 1.60M, Haiku 156K token.
- **Fatura tahmini** (Opus $5/$25, Sonnet $3/$15, Haiku $1/$5 per MTok): bu hafta ≈ **$45**; ölçülen hafta ~44 saat kesinti içerdiğinden tam-uptime normalize ≈ $60/hafta → **≈ $180-260/ay**. Karşılaştırma: 2 Tem token-disiplini öncesi researcher tek başına 27.7M token/hafta yakıyordu (≈4× bugünkü toplam) — cadence kısıtları faturayı ~%75 düşürmüş.
- **Belirsizlik:** API anahtarı yoksa Claude CLI'ya düşülüyor (`base.py:376-385`) — o yolda maliyet aboneliğe gider; hangi yolun fiilen aktif olduğu env'e bağlı (Soru §20). Bütçe tavanı soft (bkz. §11).

## 15. Tekrarlanabilirlik

- **Sayısal dünyada güçlü:** config SHA-256 provenance her daemon başlangıcında loglanıyor (`ops/provenance.py:24`, banner'da `SHA256: 5e3ae4cb...`); trade/backtest hash'leri (`backtest/eer_score.py:418-439`); pool manifest + CI `pool-verify` (12/12 PASS zorunlu); hipotez **pre-registration** disiplini (`memory/researcher/hypotheses/`, kod yazılmadan önce).
- **LLM dünyasında zayıf:** rapor frontmatter'ında `model`, `prompt_version`, `prompt_hash` **yok** (`base.py:850-865`); `llm_calls.jsonl` modeli kaydediyor ama doc_id'ye bağlanmıyor. "Bu rapor neden böyle?" sorusu artifact'ten cevaplanamaz. Prompt'lar versiyonlanmıyor; üstelik runtime persona ile `.claude/agents/` personaları ayrışmış (§4) — aynı ajanın iki farklı kimliği var.

## 16. Gelir & uyum

**Gelir modeli tanımsız** — kod ve dokümanlarda hiçbir gelir hedefi yok; sistem $5K **sanal** testnet sermayesi işletiyor (v15p2 dönemi gerçekleşen: −$6.26, 5 kapanış). İlk gelire en kısa yol: v15p2'nin ≥4-8 haftalık testnet forward-testi → küçük gerçek sermayeyle (ör. $1-5K) canlı mikro-deploy → dürüst +%8-12/ay bandının doğrulanması. **Eksik halkalar:** canlı borsa hesabı/KYC, canlı-geçiş kriterlerinin yazılı tanımı, vergi muhasebesi (TR'de kripto kazançları), gerçek-para incident runbook'u. **Uyum:** kripto spot/vadeli kişisel trade TR'de lisans gerektirmiyor (üçüncü şahıs parası yönetilmediği sürece — mevcut durumda yönetilmiyor); **forex canlı SPK engeli nedeniyle bilinçli olarak paper-only bırakılmış** (doğru karar); KVKK/e-fatura kişisel projede uygulanmaz; telif: RAG korpusundaki YouTube transcript'leri ve kitap özetleri kişisel araştırma kapsamında savunulabilir ama korpus veya türev raporlar **yayınlanırsa** risk doğar.

## 17. Çalışan vs kırık

**Son başarılı uçtan uca çalıştırma — bugün, kanıtlı:** daemon PID 1166, 06:56 TR'de launchd ile kalktı, 15dk'da bir tarıyor (`logs/futures_daemon_v15p2.log`, son tick 11:15 TR); bugün DOGE short açtı, TP/SL borsada; `reports/truth/truth-2026-07-06.md` ve `data/quality/2026-07-06.json` üretildi; denetim turu koştu (0 yeni bulgu). *(Not: keşif ajanının "daemon çalışmıyor" pgrep bulgusu sandbox artefaktıdır; ps ile doğrudan doğrulandı.)*

**Bilinen kırık/açıklar:** disk ~%90+ (backups 3.5G + .bak 1.5G); denetim register'ında 5 açık / 5 overdue bulgu (en önemlisi "canlı PnL pace resmi bandın altında", AF-OPS-20260702-001); araştırma fabrikası 48 denemede 0 terfi; README + v15p2 header bayattı (P1-5'te düzeltildi, 2026-07-06); v15p2 plist untracked'dı (P1-5'te repoya alındı); `futures_signals` DDL merkezi değil; `market.duckdb.bak` 1.5GB. **TODO taraması:** toplam 15 (gerçek FIXME/HACK sıfır); yük taşıyanlar: multitf daemon'da DD takibi gerçek equity'ye bağlanmamış (`futures_daemon_multitf.py:250`) ve regime live/backtest parite notu (`regime_features_backfill.py:84`). **Ölü kod:** `scripts/` 588 dosyanın ~%60'ı tek-seferlik (118 `sec*`, 95 `tmp/`, 76 `_archive/`, 65 underscore); 9 daemon varyantı; ~30 `risk_phoenix_scalp_15m_*` config; kökte `.tmp_*` artıkları. `futures_daemon.py` 3.890 satırlık god-file.

## 18. Darboğaz analizi

1. **Edge üretimi durmuş (en kritik).** 195 seed-abort, 0 terfi; iç falsifikasyon raporları fiyat-only 15m kripto sinyal uzayının tükendiğini söylüyor. Kök neden: arama uzayı dar (tek veri modalitesi) + kapılar doğru ama hücum stratejisi yok — sistem hipotez *reddetmekte* dünya standardı, *üretmekte* değil.
2. **Tek-makine SPOF + kaçan-cron sorunu.** 44 saatlik kesinti tüm otomasyonu durdurdu; misfire backfill yok. Kök neden: launchd-lokal mimari; cloud/ikinci düğüm/dead-man alarmı (dış) yok.
3. **Kanıt tabanı çok küçükken güven yüksek.** Canlı örneklem 5 trade / −$2; backtest sayılarının 10-25× şişme geçmişi var. Kök neden: compounding hatası geç fark edildi; forward-test süresi henüz istatistiksel güç vermiyor.
4. **LLM katmanı ölçümsüz.** ~$200/ay harcanan fabrikanın çıktı kalitesi hiçbir metriğe bağlı değil; persona drift + prompt versiyonsuzluğu regresyonu görünmez kılar. Kök neden: eval harness hiç kurulmamış.
5. **Monorepo entropisi.** God-file daemon + %60 disposable scripts + 30 config varyantı yeni geliştirici (veya ajan) için işlem maliyetini büyütüyor. Kök neden: araştırma iterasyonu hijyen borcunu hep erteledi.

## 19. Skor kartı (1-10)

| Alan | Puan | Gerekçe |
|---|---|---|
| Mimari | **7** | Üretici/tüketici ayrımı, deterministik çekirdek, katmanlı savunma sağlam; god-file + tek makine düşürüyor |
| Hafıza & RAG | **6** | Gerçek Chroma RAG + ajan hafızası çalışıyor; retrieval kalitesi ölçümsüz, budama yok |
| Veri | **7** | Flag-not-fix disiplini, atomik snapshot, günlük manifest; DDL dağınık, depo şişkin |
| Kalite & eval | **6** | 2.396 test + lookahead disiplini mükemmel; LLM eval'ı sıfır, CI tam-suite bilgilendirici |
| Güvenlik & guardrails | **8** | Dört-kilitli canlı kapısı, bypass edilemez limitler, DMS, temiz secret hijyeni; injection sanitizasyonu ve token hard-cap eksik |
| Operasyon | **5** | Zengin izleme katmanı ama SPOF, kaçan-cron, log-rotate bug'ı, disk baskısı |
| Maliyet disiplini | **6** | Ölçüm ve tiering var, Temmuz kısıntısı etkili; caching/Batch yok, tavan soft |
| Gelire yakınlık | **3** | Gelir modeli tanımsız, gerçek para sıfır, edge henüz kanıtsız |

## 20. Cevaplayamadığım sorular

1. `risk_phoenix_scalp_15m_v15p2.yaml:2` başlığı neden hâlâ "AKTİF DEĞİL" — güncellenmesi mi unutuldu, yoksa deploy şartlı onaylı mı?
2. Canlıya (gerçek para) geçiş kriteri yazılı olarak nedir? Hangi forward-test süresi/PnL eşiği, hangi sermaye?
3. LLM çağrıları fiilen Anthropic API ile mi Claude CLI (abonelik) ile mi koşuyor (`base.py:376` dalı env'e bağlı) — fatura hangi kanaldan?
4. CLI `acceptEdits` izni ajanların yazabildiği dizinleri gerçekte neyle sınırlıyor? (Repo genelinde yazma mümkünse memory-poisoning yüzeyi büyür.)
5. UNI evren durumu çelişkili: 25 Haz'da evrenden çıkarıldığı kayıtlı, ancak `scripts/ingest_15m_live.py:62`'de UNI hâlâ 19 sembollük ingest listesinde ve bugün journal'da UNI kaydı yok ama v14 döneminde vardı — trading evreni fiilen 18 mi 19 mu, hangi dosya otoriter?
6. `audit-hardreview-20260528` branch'i ~5 haftadır main'den ayrı; main'e merge stratejisi ne, main hangi durumda?
7. Docker-compose'daki postgres/prometheus/grafana fiilen kullanılıyor mu, yoksa ölü altyapı mı?
8. Forex 4H (EUR/USD GO adayı) için hedef ne — süresiz paper mı, yurtdışı broker araştırması mı?

## 21. Öneriler

**Hızlı kazanımlar (≤1 gün):**
1. **Doküman-gerçek senkronu:** README faz tablosu + v15p2 header + v15p2 plist'in repoya alınması. Etki: yeni okuyucu (insan/ajan) sistemi yanlış anlamaz; deploy tek kaynaktan yeniden üretilebilir olur.
2. **LLM artifact metadata'sı:** `write_protocol_doc` frontmatter'ına `model`, `prompt_sha` (persona+protokol hash'i), `llm_call_id` ekle (`base.py:850` civarı tek nokta). Etki: her raporun kökeni izlenebilir; §15 zafiyeti büyük oranda kapanır.
3. **Token hard-cap + logrotate fix:** `check_budget` CRIT'te çağrıyı atlat (tek if, `base.py.run_full` girişi) ve app.log'u rotasyona dahil et. Etki: kaçak harcama ve disk baskısı yapısal olarak sınırlanır.

**Yapısal hamleler:**
1. **İkinci düğüm / cloud failover + misfire telafisi:** daemon'u küçük bir VPS'e taşı (veya sıcak yedek), APScheduler job'larına `misfire_grace_time`/catch-up runner ekle. Etki: §18-2 SPOF ortadan kalkar; 44-saatlik-kesinti sınıfı olaylar veri+denetim kaybı yaratmaz.
2. **LLM eval harness:** 20-30 örneklik golden set (geçmiş iyi/kötü raporlar), haftalık judge koşusu, persona dosyalarını tek kaynağa (`agents/`) birleştirip `.claude/agents/`'ı ondan üret. Etki: ~$200/ay'lık fabrikanın kalitesi ilk kez ölçülür; prompt regresyonları yakalanır.
3. **Edge arama uzayını genişlet (veri modalitesi):** fiyat-only tükenme falsifikasyonu ciddiye alınıp funding/OI/likidite mikroyapı feature'ları (altyapısı zaten `data/alt_data/`'da yarım duruyor) araştırma hattına bağlansın; paralelde `scripts/` arkeolojisi (sec*/tmp → `_archive/`) ve `futures_daemon.py`'nin modüllere bölünmesi. Etki: fabrikaya yeni hammadde + bakım maliyetinde kalıcı düşüş.

---
---

# EKLER

## EK-A: Repo ağacı (3 seviye, özet; .git/.venv/cache/parquet-altı hariç)

```
price-action-bot/
├── README.md, ARCHITECTURE.md, RUNBOOK.md, RECOVERY.md, CHANGELOG.md, RESUME_*.md (13)
├── pyproject.toml, Dockerfile, docker-compose.yml, Makefile, .pre-commit-config.yaml, .env.example
├── .github/workflows/ci.yml
├── .claude/{agents/ (11 md), skills/, worktrees/}
├── agents/            # runtime persona dosyaları (11 md; 4+ eksik — bkz §4)
├── configs/           # 53 yaml (≈30'u risk_phoenix_scalp_15m_* soyu; audit_universe, promises, token_budget…)
│   ├── _archive/  └── proposed/
├── data/              # 11 GB
│   ├── market.duckdb (1.5G) · market_ingest.duckdb (1.5G) · futures_journal_v15p2.duckdb
│   ├── idempotency_*.duckdb · pyramid_store_*.duckdb · funding/dominance/sentiment.duckdb
│   ├── parquet/{binance(931 sym), bybit(730 sym)}/… · sec53_*_pool_*.pkl (50-135M)
│   ├── adversarial/ · backups/20260706/ · quality/ (39 manifest) · state/ · events/
├── docs/{REFACTOR_BACKLOG, SECURITY, YOUTUBE_INGEST}.md
├── knowledge/{books/ (28 md), index/ (chroma 17.6M), cache/, seeds.yaml}
├── logs/{app.log(147M), futures_daemon_v15p2.log, launchd/, risk/, state/, execution/}
├── memory/            # 24 ajan dizini + audit/findings_register.jsonl + protocol/inbox.jsonl + shared/
├── monitoring/grafana/ · notebooks/ · analysis/ · dashboard/
├── ops/{launchd/ (plist+sh wrapper'lar), logrotate/}
├── reports/           # 59 MB — ceo, lab, research, audit, truth, promises, reconcile, bot_monitor…
├── scripts/           # 588 py — futures_daemon*.py (9 varyant), ingest_*, run_audit, truth_report,
│   │                  #   check_promises, reconcile_journal + sec* (118) / tmp (95) / _archive (76)
│   └── {cron, db, lib, research, one_time_corrections, dashboard, grafana}/
├── src/price_action/  # 205 py, 20 paket
│   ├── agents/ analytics/ api/ backtest/ config/ data/(alt_data) events/ execution/
│   ├── lab/ memory/ ml/ notifications/ ops/ orchestrator/ portfolio/ rag/ risk/
│   └── signals/ strategies/(manifests)
└── tests/             # 135 dosya, 2396 test — strategies/ execution/ risk/ audit/ ops/ scripts/
```

## EK-B: Kritik alıntılar

**Runtime persona ilk satırları** (`agents/*.md`; tam 15 satır yerine mevcut kimlik blokları — dosyalar kısa kimlik+kural formatında):
- `agents/ceo.md:1-3` — "Chief Executive Officer — Trading Desk Head" (sentez + tavsiye; emir/config yetkisi yok)
- `agents/researcher.md:1-3` — "Head of Quantitative Research" (pre-registration zorunlu, lookahead paranoyası)
- `agents/analyst.md:1-3` — "Head of Performance Analytics" (bias avcılığı; sinyal üretmez)
- `agents/risk_officer.md:1-3` — "Chief Risk Officer" (mutlak veto, en muhafazakâr)
- `agents/lab_scientist.md:1-3` — "Head of Self-Improvement Lab" (kapısız terfi yasak)
- `agents/ops_engineer.md`, `agents/data_engineer.md`, `agents/strategy_curator.md` — mevcut
- **EKSİK (runtime'da boş persona):** `adversary_engineer`, `bot_monitor`, `market_scout`, tüm `audit_*` (`base.py:319-322` → `agent.rules_missing`)
- Ortak sistem-prompt iskeleti: `base.py:334-360` — RULES + `memory/shared/protocol.md` + BOOT CONTEXT + ALLOWED TOOLS + "Trading kararı veya canlı emir vermezsin" (`:353`)

**Ana veri şemaları:**
```sql
-- OHLCV (store.py:242-255)
ohlcv(venue, symbol, timeframe, ts TIMESTAMPTZ, open, high, low, close, volume DOUBLE,
      PK(venue, symbol, timeframe, ts))

-- Journal (trade_journal.py:127; bot_factory.py:203)
futures_signals(signal_id PK, ts, symbol, strategy, side, sl_price, tp_price, confluence,
                leverage, status, order_id, fill_price, fill_qty, notional_usdt, margin_usdt, notes)
futures_trades_closed(trade_id PK, ts_open, ts_close, sym, side, strategy, entry_price,
                      exit_price, qty, realized_pnl_usdt, realized_r, win, close_reason)

-- Idempotency (idempotency.py:48): order_fingerprints(client_order_id PK = "PA_"+sha[:16], …)
```

**Config anahtar İSİMLERİ** (`.env.example`, 44 değişken — değerler asla):
`ANTHROPIC_API_KEY, CLAUDE_MODEL_DEFAULT/FAST/LIGHT, BINANCE_API_KEY, BINANCE_API_SECRET, BINANCE_TESTNET, BINANCE_TESTNET_API_KEY/SECRET, BYBIT_API_KEY/SECRET/TESTNET, POSTGRES_HOST/PORT/DB/USER/PASSWORD, DUCKDB_PATH, PARQUET_ROOT, CHROMA_PATH, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, YOUTUBE_API_KEY, PA_RUN_MODE, PA_LIVE_CONFIRM, PA_BACKTEST_YEARS, PA_TIMEFRAMES, PA_UNIVERSE_MODE, PA_MIN_VOL_USDT, PA_RISK_PER_TRADE, PA_MAX_LEVERAGE, PA_DAILY_DD_BREAKER, PA_WEEKLY_DD_BREAKER, PA_PAPER_INITIAL_CAPITAL, PA_PAPER_RISK_PER_TRADE, PA_PAPER_MAX_LEVERAGE, PA_LLM_BRIEF_TIME, PA_LLM_WEEKLY_DAY, PA_BREAKER_POLL_INTERVAL, LOG_LEVEL, LOG_FORMAT`
Runtime'da ek: `PA_V14_PHASE, PA_LLM_DRY_RUN, PA_LLM_USE_CLI, PA_CLI_MAX_CONCURRENT, PA_RESEARCH_AUTOPILOT, PA_REGIME_CACHE_STRICT, PA_DUCKDB_READ_ONLY, PA_ADMIN_TOKEN`

## EK-C: Çalıştırma kılavuzu

```bash
# 1) Kurulum (Python ≥3.11)
git clone <repo> && cd price-action-bot
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"                     # pyproject.toml
cp .env.example .env                        # EK-B'deki isimleri doldur (testnet anahtarları yeterli)

# 2) Testler (beklenen: 2396 collected, core suite yeşil)
.venv/bin/pytest -q                         # tam suite
.venv/bin/pytest tests/audit tests/risk -q  # hızlı çekirdek

# 3) Veri
.venv/bin/python scripts/backfill_5y.py            # ilk tarihsel yük (manuel)
.venv/bin/python scripts/ingest_15m_live.py        # tek atım 15m ingest (launchd: her 5dk)

# 4) Daemon (v15p2, testnet) — launchd ile:
cp ops/launchd/run_futures_v15p2.sh <kontrol et>   # plist untracked; §2'deki nota bak
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.priceaction.futures_v15p2.plist
tail -f logs/futures_daemon_v15p2.log              # beklenen: VERIFY_OK + CONFIG PROVENANCE
                                                   #   banner + 15dk'da bir "15M_SCAN: N sinyal"
# elle (launchd'siz): PA_V14_PHASE=v15p2 .venv/bin/python -u scripts/futures_daemon_v14.py --timeframe 15m

# 5) Ajan fabrikası
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.priceaction.ceo.plist   # pa-ceo daemon
.venv/bin/python scripts/run_audit.py       # tam denetim turu (beklenen: 5 domain + register özeti)
.venv/bin/python scripts/truth_report.py    # günlük ayna raporu → reports/truth/
.venv/bin/python scripts/check_promises.py  # SLA kontrolü → reports/promises/

# 6) RAG
pa-rag stats && pa-rag query "wyckoff spring"      # beklenen: ~1600 doc, ilgili chunk'lar
```
Beklenen uçtan uca çıktı: daemon her bar kapanışında tarar, sinyal risk kapısından geçerse testnet'te pozisyon + TP/SL açılır, `data/futures_journal_v15p2.duckdb`'ye yazılır, 06:00 TR'de truth report ve denetim raporları `reports/` altına düşer, alarmlar Telegram'a gider.

## EK-D: Veri örnekleri (gerçek, kısaltılmış; hassas alanlar maskeli)

**`data/llm_calls.jsonl`** (son satır):
```json
{"ts": "2026-07-06T04:18:11.699138+00:00", "agent": "risk_officer",
 "model": "claude-sonnet-4-6", "input_tokens": 43483, "output_tokens": 3255,
 "stop_reason": "end_turn"}
```

**`data/quality/2026-07-06.json`** (19 rapordan biri, kısaltıldı):
```json
{"venue": "binance", "symbol": "BTC/USDT", "timeframe": "15m",
 "row_count": 179836, "gaps": 390, "duplicates": 0,
 "ohlc_violations": 0, "volume_outliers": 323, "stale": false}
```

**`memory/audit/findings_register.jsonl`** (açık bulgu örneği):
```json
{"finding_id": "AF-OPS-20260702-001", "control_id": "CT-OPS-XX", "severity": "med",
 "owner": "ceo", "auditor": "audit_ops",
 "title": "canlı PnL pace resmi bandın altında", "status": "OPEN",
 "opened_at": "2026-07-02T…", "due_at": "…", "doc_path": "reports/audit/…"}
```

**`logs/risk/futures_breaker_state_15m_v15p2.json`** (kısaltıldı):
```json
{"daily_pnl": 0.0, "weekly_pnl": 0.0, "monthly_pnl": -6.04,
 "daily_anchor_equity": 4956.74, "last_reset_daily": "2026-07-06",
 "triggered_daily": false, "triggered_weekly": false, "consecutive_losses": 0}
```

**`logs/futures_daemon_v15p2.log`** (canlı tick, UTC):
```
[07:00:19Z] 15M_SCAN: 0 sinyal, latency=14.2s
[07:00:25Z] POS_CHECK: 1 pos, 3 algo (TP+SL) | DOGE=S9632.000@$0.0772->0.0766(+5.69)
[07:00:32Z] 15M_TICK_DONE: scan=14.2s pos_monitor=6.8s
```

**Protokol dokümanı frontmatter'ı** (`base.py:850-865` şablonu — `model`/`prompt_hash` alanlarının YOKLUĞU §15'in kanıtı):
```yaml
---
doc_id: <agent>-<ts>-<slug>
doc_type: critique | endorse | brief | audit_finding | …
agent_id: risk_officer
created_at: 2026-07-06T…
status: pending_review
confidence: 0.8
depends_on: [<doc_id>]
requested_review_from: [ceo]
tags: […]
---
```
