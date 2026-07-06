# RUNBOOK — İlk Gün

> Sabah uyandığında bu dosyayı oku. Sistem kuruldu; aşağıdaki adımlarla canlandır.

## 1. Hızlı Tur (5 dk)

Şu klasörleri kısa kısa gez:

| Klasör/Dosya | Ne işe yarar |
|---|---|
| `README.md` | Sistemin tek-cümle özeti + komutlar |
| `ARCHITECTURE.md` | Mimari bütünü, departmanlar, akış diyagramları |
| `agents/*.md` | 10 departman kuralları (CEO / Researcher / Analyst / Lab / Data / Signal / Risk / Portfolio / Execution / Ops) |
| `memory/` | Kurumsal hafıza (agent identity, know-how, learning, shared lessons + decisions) |
| `knowledge/seeds.yaml` | RAG corpus seed listesi (Brooks, Volman, Wyckoff, akademik feed'ler, YouTube) |
| `configs/` | symbols.yaml, risk.yaml, strategies/classic_pa.yaml |
| `src/price_action/` | Python paketleri (data, signals, strategies, backtest, risk, portfolio, execution, ml, analytics, agents, orchestrator, rag, memory, api) |

## 2. Ortam Kurulumu (10 dk)

```bash
# 1) Python 3.11+ ve uv kur (yoksa)
#    uv: https://github.com/astral-sh/uv

# 2) Bağımlılıkları kur
cd /path/to/price-action-bot   # macOS/Linux: typically ~/price-action-bot
uv sync

# 3) .env hazırla
cp .env.example .env
# - ANTHROPIC_API_KEY  (Claude için, varsa)
# - BINANCE_API_KEY/SECRET  (testnet anahtarları, ücretsiz)
# - TELEGRAM_BOT_TOKEN/CHAT_ID  (alarm istiyorsan, opsiyonel)
# - PA_RUN_MODE=backtest  (faz sonuna kadar burada kalır)

# 4) Sistem hızlı kontrol (ANTHROPIC_API_KEY olmadan da çalışır)
PYTHONPATH=src PA_LLM_DRY_RUN=true python scripts/morning_smoke.py
# Beklenen: "OK — Sistem ayağa kalktı, ilk ingest'e hazır."
# Bu: 30 modül import + pattern detector + lookahead causality + Risk Officer
#     + LLM dry-run + memory boot + filesystem — hepsi yeşil olmalı.

# 5) (Opsiyonel) Tüm test paketi
PYTHONPATH=src PA_LLM_DRY_RUN=true python -m pytest tests/ -q
# Beklenen: 156 passed, 4 skipped (integration/live test'leri default skip).

# 6) Klasörleri ve servisleri ayağa kaldır
docker compose up -d  # postgres + prometheus + grafana
uv run python scripts/validate_setup.py  # ortam check
```

## 3. İlk Veri Çekimi (30-60 dk, internete bağlı)

```bash
# Sembol evrenini kur (likidite filtreli)
uv run pa universe build

# 3 yıllık 1d + 1w veriyi çek (Binance + Bybit)
uv run pa ingest --venue binance --tf 1d 1w --years 3
uv run pa ingest --venue bybit  --tf 1d 1w --years 3

# Veri kalite raporu
uv run python -m price_action.data.quality
```

## 4. İlk Backtest (Faz 2 Gate Sınaması)

```bash
# Classic PA stratejisi, 3y, all_liquid evren
uv run pa backtest run --strategy classic_pa --years 3 --universe all_liquid

# HTML raporu reports/research/<strategy>-<date>.html
```

**Sonuç değerlendirme:**

- Yıllık net > %70? Sharpe > 1.5? MaxDD < %20? Walk-forward dilim %70+ pozitif?
  - **EVET → Faz 3'e geç:** Risk + portföy katmanı backtest'e dahil edilip yeniden çalıştırılır.
  - **HAYIR → Faz 1'e dön:** Pattern parametreleri / strateji manifesto rafine edilmeli. Researcher agent'ı çağır:
    ```
    uv run pa ceo daily   # CEO'dan önce günün durumunu al
    # Sonra Researcher'ı tetikle (yeni hipotez)
    uv run python -c "from price_action.agents.researcher import ResearcherAgent; r = ResearcherAgent(); r.propose_hypothesis(seed_topic='pin_bar at S/R refinement')"
    ```

## 5. RAG Corpus İlk Yüklemesi (15-30 dk)

```bash
# Seed listesinden ilk crawl
uv run pa rag ingest --since 30d
# Sonuç: knowledge/index/ (ChromaDB) doldu, Researcher kullanabiliyor
```

## 6. LLM Agent'ları Test (5 dk)

```bash
# CEO morning brief simülasyonu (ANTHROPIC_API_KEY gerekli)
uv run pa ceo daily

# Researcher hipotez üretimi
uv run python -c "from price_action.agents.researcher import ResearcherAgent; r = ResearcherAgent(); print(r.propose_hypothesis(seed_topic='engulfing at trend continuation'))"

# Analyst günlük rapor
uv run python -c "from price_action.agents.analyst import AnalystAgent; a = AnalystAgent(); print(a.daily_kpi_brief())"
```

API key yoksa `PA_LLM_DRY_RUN=true` env ile mock cevap alabilirsin.

## 7. Dashboard

```bash
# FastAPI server
uv run python -m price_action.api.server

# Tarayıcıda:
# - http://localhost:8000/health     → 200
# - http://localhost:8000/dashboard  → equity + open positions
# - http://localhost:3000            → Grafana (admin/admin)
# - http://localhost:9090            → Prometheus
```

## 8. Sürekli İyileştirme — Haftalık Lab Toplantısı

```bash
# Bir hafta veri biriktikten sonra:
uv run python -c "from price_action.agents.lab_scientist import LabScientistAgent; l = LabScientistAgent(); l.weekly_tournament(); l.drift_detect(); l.rag_refresh()"
# Sonuç: reports/lab/ altında tournament, drift, RAG raporu
```

## Karar Akış Şeması

```
[ Researcher ]──hipotez──▶[ Backtest ]──gate?──▶[ Lab tournament ]──▶[ CEO brief ]
                                                       ▲
                                                       │ haftalık RAG refresh
                                                       │
                                                  [ knowledge/ ]
```

## Sıkça Karşılaşılan Sorunlar

### "ccxt rate limit (429)"
ccxt'nin `enableRateLimit: True` ile zaten yumuşak. Persistent ise:
```bash
sleep 60 && uv run pa ingest ...
```

### "ChromaDB persistent path conflict"
`knowledge/index/` boşalt + tekrar ingest:
```bash
rm -rf knowledge/index/  # dikkat: tüm RAG corpus silinir
uv run pa rag ingest --full
```

### "Postgres connection refused"
```bash
docker compose ps     # servisleri kontrol et
docker compose up -d postgres
```

### "DuckDB lock"
DuckDB tek-yazıcılı; başka süreç açık ise:
```bash
ps -ef | grep duckdb
# pid'i kapat
```

### "API key missing"
`.env` doğru yerde mi? `Settings.anthropic_api_key` değeri:
```bash
uv run python -c "from price_action.settings import get_settings; print(bool(get_settings().anthropic_api_key))"
```

## Faz 5 — LLM Orchestration + Telegram Alerts

### Genel Bakış

Faz 5 katmanı, 5 LLM agent'ı (CEO, Researcher, Analyst, Lab, Ops) zamanlanmış
görevlerle çalıştırır ve Telegram üzerinden alert gönderir.

| Bileşen | Dosya | Görev |
|---|---|---|
| Telegram modülü | `src/price_action/notifications/telegram.py` | HTTP alert gönderimi |
| LLM Orchestrator | `scripts/llm_orchestrator.py` | Zamanlanmış brief'ler |
| Breaker Monitor | `scripts/breaker_monitor.py` | DD izleme + kriz tetikleme |

### Adım 1: Telegram Bot Kurulumu

1. Telegram'da [@BotFather](https://t.me/BotFather)'a git
2. `/newbot` yaz → bot adını ve username'ini gir
3. Verilen **Bot Token**'i kopyala
4. Chat ID almak için [@userinfobot](https://t.me/userinfobot)'a `/start` yaz

```bash
# .env dosyasına ekle
TELEGRAM_BOT_TOKEN=123456789:AABBccDDeeFFggHH...
TELEGRAM_CHAT_ID=-100123456789   # grup için - ile başlar, kişisel için pozitif sayı
```

**Test:**
```bash
PYTHONPATH=src python -c "
from price_action.notifications.telegram import send_telegram
send_telegram('Faz 5 test mesajı — sistem ayakta!', level='INFO')
"
```

### Adım 2: Ortam Değişkenlerini Ayarla

```bash
# .env dosyasına ekle (yoksa cp .env.example .env)
PA_LLM_BRIEF_TIME=09:00       # Daily brief UTC saati
PA_LLM_WEEKLY_DAY=Sunday      # Haftalık özet günü
PA_BREAKER_POLL_INTERVAL=300  # Breaker poll sıklığı (saniye)
```

### Adım 3: Dry-run Testi

Gerçek LLM veya Telegram çağrısı yapılmaz:

```bash
PYTHONPATH=src PA_LLM_DRY_RUN=true python scripts/llm_orchestrator.py --mode daily-brief --dry-run
```

Beklenen çıktı: JSON `{"status": "dry_run", "date": "...", "report_path": "..."}`
Rapor dosyası `reports/ceo/YYYY-MM-DD-brief.md` oluşturulur.

### Adım 4: Manuel Modlar

```bash
# Günlük brief (CEO morning brief)
PYTHONPATH=src python scripts/llm_orchestrator.py --mode daily-brief

# Haftalık özet (CEO + Researcher + Lab)
PYTHONPATH=src python scripts/llm_orchestrator.py --mode weekly-summary

# Trade post-mortem (belirli bir trade için)
PYTHONPATH=src python scripts/llm_orchestrator.py --mode post-mortem --trade-id paper-faz6-abc123

# Kriz alarmı (manuel tetikleme)
PYTHONPATH=src python scripts/llm_orchestrator.py --mode crit-alarm --reason "Manuel test alarmı"
```

### Adım 5: Watchdog (Sürekli Mod)

APScheduler ile otomatik zamanlama:

```bash
PYTHONPATH=src python scripts/llm_orchestrator.py --watchdog
```

Bu komut:
- Her gün `PA_LLM_BRIEF_TIME` (varsayılan 09:00) UTC'de CEO daily brief çalıştırır
- Her `PA_LLM_WEEKLY_DAY` (varsayılan Sunday) 18:00 UTC'de haftalık özet çalıştırır
- Tüm raporları `reports/ceo/` altına kaydeder
- Telegram'a gönderir

### Adım 6: Breaker Monitor

DD (drawdown) izleyici — her 5 dakikada bir journal'ı kontrol eder:

```bash
PYTHONPATH=src python scripts/breaker_monitor.py
```

**Breaker eşikleri:**

| Tip | Eşik |
|---|---|
| Günlük kayıp | %5 |
| Haftalık kayıp | %10 |
| Aylık kayıp | %15 |

**Breaker tetiklendiğinde otomatik olarak:**
1. `logs/kill_switch.json` güncellenir (`"active": true`)
2. `llm_orchestrator.py --mode crit-alarm` spawn edilir
3. Telegram'a 🚨 CRIT alert gönderilir

**Idempotent:** Breaker aktifken tekrar tetiklenmez (spam yok).

**Manuel reset (breaker düzeldikten sonra):**
```bash
PYTHONPATH=src python scripts/breaker_monitor.py --reset
# "YES" yazarak onayla
```

### Kriz Senaryosu — Breaker Tetiklendiğinde Ne Olur

```
[paper_trading_loop.py]
    ↓ DD > %5 eşiği aşıldı
[breaker_monitor.py]
    ↓ poll_once() → breaker tetiklendi
    ↓ logs/kill_switch.json → {"active": true, ...}
    ↓ Telegram: 🚨 "BREAKER TETİKLENDİ — GÜNLÜK DD: 6.20% >= 5% limit"
    ↓ subprocess: llm_orchestrator.py --mode crit-alarm --reason "..."
[llm_orchestrator.py]
    ↓ CEO.crisis_protocol(reason) çağrılır
    ↓ reports/ceo/crisis-YYYYMMDD-HHMMSS.md oluşturulur
    ↓ Telegram: 🚨 CEO'nun öneri metni gönderilir
```

Kritik not: CEO sadece **öneri** üretir. Pozisyon kapatma veya emir
gönderimi **insan onayı** gerektirir.

### Birim Testler

```bash
# Telegram modülü testleri (mock — gerçek HTTP yok)
PYTHONPATH=src PA_LLM_DRY_RUN=true python -m pytest tests/test_telegram.py -v

# Tüm test paketi
PYTHONPATH=src PA_LLM_DRY_RUN=true python -m pytest tests/ -q
```

### Sorun Giderme

**"requests kütüphanesi bulunamadı"**:
```bash
uv add requests
```

**"apscheduler yüklü değil"** (watchdog modu):
```bash
uv add apscheduler
```

**"Telegram mesaj gitmiyor"**:
```bash
# Token test (curl ile)
curl "https://api.telegram.org/bot<TOKEN>/getMe"
# Chat ID test
curl "https://api.telegram.org/bot<TOKEN>/getUpdates"
```

**"Kill-switch aktif ama reset etmek istiyorum"**:
```bash
PYTHONPATH=src python scripts/breaker_monitor.py --reset
# Konsolda "YES" yazarak onayla
```

---

## Faz 6'ya Geçiş Kontrol Listesi (paper trading öncesi)

- [ ] Faz 2 gate geçildi (yıllık net > %70 / Sharpe > 1.5 / DD < %20)
- [ ] Faz 3 risk katmanı sonrası gate korundu
- [ ] (Opsiyonel) Faz 4 ML uplift > %15
- [ ] Faz 5 LLM brief 1 hafta kesintisiz çalışıyor
- [ ] `agents/risk_officer.md` veto akışı testten geçti
- [ ] Telegram alarm calışıyor (CRIT seviyesi test edildi)
- [ ] Backup script çalışıyor (Postgres günlük dump)
- [ ] Kill-switch test edildi (`pa ops halt` + `pa ops resume`)

## Faz 6 — Paper Trading Run (engulfing_continuation)

### Genel Bakış

Engulfing continuation stratejisini Binance testnet üzerinde 4 hafta çalıştır.
Backtest beklentisi: yıllık +%68, aylık ~%5.6. Sapma <%20 ise Faz 7 kapısı açılır.

**Production config (walk-forward 2/3 gate geçti):**

| Parametre | Değer |
|---|---|
| Risk per trade | %2 sermaye |
| Leverage | 1x-5x dinamik (confidence-based) |
| Confidence < 0.32 | 1x |
| 0.32–0.42 | 2x |
| 0.42–0.52 | 3x |
| 0.52–0.58 | 4x |
| ≥ 0.58 | 5x |
| Semboller | BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, LINK, DOT (USDT pairs) |
| Timeframe | 1d (karar bar kapanışı sonrası 00:30 UTC) |
| Max eş zamanlı pozisyon | 5 |
| Breaker — günlük | %5 |
| Breaker — haftalık | %10 |
| Breaker — aylık | %15 |

### Adım 1: Binance Testnet Anahtarları

1. https://testnet.binance.vision/ adresine git
2. GitHub ile giriş yap → "Generate HMAC_SHA256 Key" tıkla
3. API Key ve Secret'i kopyala
4. `.env` dosyasına yaz:

```bash
BINANCE_TESTNET_API_KEY=<testnet_api_key>
BINANCE_TESTNET_API_SECRET=<testnet_api_secret>
PA_PAPER_INITIAL_CAPITAL=10000
PA_PAPER_RISK_PER_TRADE=0.02
PA_PAPER_MAX_LEVERAGE=5
```

> NOT: Testnet anahtarları mainnet'ten farklıdır. Karıştırma.

### Adım 2: Çevre Hazırlığı

```bash
cd /path/to/price-action-bot   # macOS/Linux: typically ~/price-action-bot

# Loglar ve data klasörlerini oluştur (script otomatik oluşturur ama elle de yapılabilir)
mkdir -p logs/execution logs/risk data reports/paper

# Bağımlılıkları kontrol et
uv sync

# Dry-run ile sistemi test et (network bağlantısı gerekmez)
PYTHONPATH=src PA_LLM_DRY_RUN=true python scripts/paper_trading_loop.py --once --dry-run
```

Beklenen çıktı: JSON özet — hangi sembollerde sinyal bulundu, hangi leverage atandı.

### Adım 3: Sürekli Mod (Watchdog)

Gerçek paper trading için:

```bash
# Sürekli mod: her gün 00:30 UTC'de otomatik çalışır
PYTHONPATH=src python scripts/paper_trading_loop.py --watchdog

# Veya cron-friendly tek çalıştırma (cron ile 00:30 UTC'ye zamanla):
PYTHONPATH=src python scripts/paper_trading_loop.py --once
```

Cron örneği (Linux/WSL):
```cron
30 0 * * * cd /path/to/project && PYTHONPATH=src python scripts/paper_trading_loop.py --once >> logs/cron.log 2>&1
```

Windows Task Scheduler için: her gün 02:30 yerel saat (UTC+2 varsayımıyla).

### Adım 4: Durum İzleme

```bash
# Günlük özet (terminal)
PYTHONPATH=src python scripts/paper_status_report.py

# Haftalık markdown raporu kaydet
PYTHONPATH=src python scripts/paper_status_report.py --markdown

# Ham JSON çıktı
PYTHONPATH=src python scripts/paper_status_report.py --json
```

Raporlar `reports/paper/faz6_status_<timestamp>.md` altına kaydedilir.

### Adım 5: Logları Takip Et

```bash
# Canlı log akışı
Get-Content logs/paper_trading.log -Wait   # PowerShell
# veya
tail -f logs/paper_trading.log             # WSL/bash

# Pozisyon durumu (JSON)
cat logs/execution/paper_state_faz6.json

# DuckDB journal (interaktif sorgu)
duckdb data/paper_journal.duckdb
> SELECT symbol, side, confidence, leverage, entry_price, status FROM paper_trades ORDER BY entry_ts DESC;
```

### Durdurma Kriterleri (Faz 7 Kapısı)

Aşağıdaki her iki kriter de karşılandığında Faz 7'ye geçilebilir:

- [ ] **4 hafta tamamlandı** (28 gün, en az 10 işlem günü)
- [ ] **Sapma < %20**: Gerçek aylık getiri, backtest beklentisinden (%5.6/ay) <%20 sapar

`paper_status_report.py` bu kriterleri otomatik hesaplar:
```
"stopping_criteria": {
  "four_weeks_done": true/false,
  "deviation_within_20pct": true/false,
  "all_met": true/false   ← Faz 7 kapısı
}
```

### Adım 6: Orderbook Imbalance Logging (Microstructure Research)

Faz 6 paper trading sırasında, her engulfing sinyali tetiklendiğinde
gerçek zamanlı orderbook snapshot otomatik olarak loglanır.
Bu, **perp-orderbook-imbalance** hipotezinin forward validation verisidir.

**Nasıl çalışır:**
- `scripts/paper_trading_loop.py` sinyal bulunca defansif hook tetikler
- `src/price_action/data/orderbook_logger.py` REST ile Binance orderbook çeker
- Top-5 seviyede bid/ask imbalance hesaplanır
- `data/orderbook_snapshots.duckdb` tablosuna append edilir
- Herhangi bir hata (network, exchange down) → sessizce geçer, loop durmaz

**Durum sorgulama:**
```python
from price_action.data.orderbook_logger import OrderbookLogger
ob = OrderbookLogger()

# Son 20 snapshot
print(ob.query_recent(limit=20))

# Alignment özeti (4 hafta sonra)
print(ob.correlation_summary())
# {'total_snapshots': N, 'aligned_count': X, 'misaligned_count': Y, 'neutral_count': Z}
```

**DuckDB direkt sorgu:**
```bash
duckdb data/orderbook_snapshots.duckdb
> SELECT symbol, direction, imbalance, confidence, ts
  FROM orderbook_snapshots
  ORDER BY ts DESC
  LIMIT 20;
```

**Forward validation takvimi:**
- Başlangıç: 2026-05-09
- Bitiş: 2026-06-06 (4 hafta)
- Minimum hedef: 30 snapshot
- Analiz sorusu: |imbalance| > 0.6 olduğunda win rate artıyor mu?

**Hipotez belgesi:** `memory/researcher/hypotheses/2026-05-09-perp-orderbook-imbalance.md`

### Sorun Giderme

**"ccxt not found"**:
```bash
uv add ccxt
```

**"duckdb not found"** (journal devre dışı kalır, log dosyasına düşer):
```bash
uv add duckdb
```

**Orderbook logging çalışmıyor (sessizce skip):**
```bash
# Modülü manuel test et (network bağlantısı gerekli)
PYTHONPATH=src python -c "
from price_action.data.orderbook_logger import fetch_orderbook_snapshot
result = fetch_orderbook_snapshot('BTC/USDT', venue='binance', limit=10)
print(result)
"
```

**Breaker tetiklendi**:
`logs/risk/breaker_state_faz6.json` dosyasını gör. Manuel sıfırlama için:
```python
from price_action.risk.breaker import DDBreaker
b = DDBreaker(state_path="logs/risk/breaker_state_faz6.json")
b.reset()  # dikkat: insan onayı gerekir
```

**"paper_state sıfırlanmalı"** (temiz başlangıç):
```bash
del logs\execution\paper_state_faz6.json
```
İlk çalıştırmada $10,000 USDT ile yeniden başlar.

---

## Faz 7'ye Geçiş Kontrol Listesi (mikro canlı öncesi)

- [ ] Paper trading 4 hafta tamamlandı
- [ ] Beklenen P&L'den sapma < %20
- [ ] `PA_RUN_MODE=live` + `PA_LIVE_CONFIRM=YES_I_KNOW`
- [ ] `configs/risk.yaml::live_mode_enabled: true`
- [ ] Canlı API anahtarları (testnet değil)
- [ ] Mikro sermaye (örn. $200) — risk per trade %1 = $2
- [ ] İnsan principal her gün ilk 2 hafta brief'i okur

---

## Faz 7 — Mikro Canlı Operations Playbook

> Bu bölüm Faz 6 paper trading 4 hafta başarıyla tamamlandıktan sonra okunur.
> Hiçbir adımı atlatma. Her check kutusu insan onayı gerektirir.

### A. Pre-flight Kontrol (Faz 6 → 7 Geçiş Kriterleri)

Aşağıdaki her madde PASS olmadan sistemi CANLI AÇMA.

```bash
# Otomatik kontrol (tüm kriterleri tek komutla çalıştır)
PYTHONPATH=src python scripts/faz7_preflight.py
```

Manuel kontrol listesi:

- [ ] **4 hafta tamamlandı** — `paper_status_report.py` çıktısında `"four_weeks_done": true`
- [ ] **P&L sapması < %20** — Gerçek aylık getiri, backtest beklentisi (%5.6/ay) ile <%20 farklı
- [ ] **Slippage gerçekçilik kontrolü** — Paper ortalama slippage bps, backtest 5 bps varsayımından <%100 sapıyor mu? (2x üstü → sorun; `paper_status_report.py --json` ile kontrol et)
- [ ] **Kill-switch testi yapıldı** — `pa ops halt` → sistem durdu → `pa ops resume` → sistem devam etti — her ikisi de kayıt altında
- [ ] **Telegram CRIT alarm calıştı** — En az 1 kez gerçek breaker tetiklenip Telegram mesajı geldi
- [ ] **Manifest hash** — Her paper trade kaydında `manifest_hash` alanı dolu (DuckDB journal sorgula)
- [ ] **Postgres journal aktif** — `docker compose ps` postgres UP, audit trail sorgusu çalışıyor
- [ ] **İnsan principal taahhüdü** — İlk 2 hafta her sabah CEO brief'i insan tarafından okunacak (kalender'a yaz)

Preflight başarısız çıktıysa Faz 7'ye geçme. Nedenini düzelt, tekrar çalıştır.

---

### B. Binance LIVE API Setup

> UYARI: Testnet anahtarları ile mainnet anahtarlarını ASLA karıştırma.
> Testnet key mainnet'te 0 bakiye döndürür, mainnet key testnet'te çalışmaz.

#### B.1 API Key Oluşturma

1. https://www.binance.com → Profil → API Management → "Create API"
2. Label: `price-action-faz7` (tanımlayıcı bir isim)
3. **API Key Type: System Generated**
4. E-posta / 2FA doğrulama tamamla
5. "IP Access Restriction" → **"Restrict access to trusted IPs only"** → sunucu IP'ni ekle (VPS veya sabit ev IP'n)
6. İzinler: sadece **"Enable Spot & Margin Trading"** işaretle
   - "Enable Withdrawals" → **KAPALI BIRAK** (güvenlik: bot para çekemez)
   - "Enable Futures" → Faz 7 başlangıcı için KAPALI (önce spot test)
   - Read-only ayrı key mi lazım? Monitoring için ikinci bir key oluşturabilirsin

#### B.2 Spot vs USD-M Perp Seçimi

| Özellik | Spot | USD-M Perp |
|---|---|---|
| Leverage | 1x (kaldıraçsız) | 1x-5x dinamik |
| Funding Rate | Yok | Her 8 saat |
| Likidasyon Riski | Yok | Var (%50 margin safety zorunlu) |
| Faz 7 başlangıç önerisi | **EVET — daha güvenli** | Lev >1x istiyorsan |

> **Faz 7 Tavsiyesi:** İlk ay Spot ile başla (leverage=1x). Sistem gerçek ortamda
> davranışını kanıtlasın. 2. aydan itibaren Futures açabilirsin.

#### B.3 Futures (USD-M Perp) Açmak İstiyorsan

```
Binance → Futures → Aç → Uyarıları kabul et
API Management → Key'e "Enable Futures" ekle
.env → PA_LIVE_USE_FUTURES=true
```

Ancak: leverage >1x için margin_safety_ratio=%50 (`configs/risk.yaml`) zorunlu.
Likidasyon fiyatı her zaman entry'den en az %50 uzakta olmalı.

#### B.4 Güvenlik Checklist

- [ ] IP restriction aktif (sadece runner IP)
- [ ] 2FA hesap düzeyinde aktif (Google Authenticator / Yubikey)
- [ ] Withdrawal disable (API üzerinden para çekilemiyor)
- [ ] API secret sadece `.env` dosyasında — Git history'e girmiyor
- [ ] `.env` dosyası `.gitignore` içinde → `git status` ile kontrol et

---

### C. Sermaye Protokolü

> Bu bölüm para transferi ve kayıp toleransı konusundadır. Her madde bilinçli kararla yapılmalı.

#### C.1 Başlangıç Transferi

- Mikro başlangıç: **$200 USDT** (banka hesabından ayrı bir Binance hesabına — veya ayrı bir sub-account)
- Bu $200 piyasada kaybedilebilir. Hayat standardını etkilemeyecek bir miktar olmalı.
- Binance sub-account önerisi: Ana hesap ile Faz 7 hesabı ayrı olsun (risk izolasyonu).

#### C.2 Risk Per Trade — Faz 7 Defansif Başlangıç

| Faz | Risk/Trade | Neden |
|---|---|---|
| Faz 6 Paper | %2 | Backtest production config |
| **Faz 7 Başlangıç** | **%1** | **Canlı ortam bilinmezleri — DAHA SIKI başla** |
| Faz 7 → 3 ay sonra | %1.5 | DD < %20 ise kademe |
| Faz 7 → 6 ay sonra | %2 | Paper'daki seviye — sadece track record varsa |

$200 × %1 = **$2 maksimum kayıp per trade** (SL'e kadar)

> Neden paper'dan daha sıkı? Gerçek piyasada slippage, funding rate, network
> latency ve psikoloji backtesti ezer. İlk aylarda sisteme güven kazandır.

#### C.3 Leverage Limiti — Faz 7

```yaml
# Faz 7 başlangıcı için configs/risk.yaml override
leverage:
  max_leverage_per_symbol: 3   # Faz 7 ilk 3 ay (paper'daki 5x yerine 3x)
  # 3 ay sonra 5x'e çık — sadece DD < %20 ise
```

Notional maksimum (5x ile): $200 × %1 risk × leverage/sl_distance formülü.
Ancak tek pozisyon notional'i $1,000'i geçmemeli (equity'nin 5x'i hard limit).

#### C.4 Withdrawal Protokolü

- **$250 eşiği:** Hesap $250'a ulaştığında ilk %20'yi geri çek ($50)
- Çekilen para geri konmaz — kâr realize edildi, sisteme devam et kalan ile
- **$300 eşiği:** Tekrar %20 çek ($60) → banka hesabına
- Bu protokol psikolojik öneme sahip: gerçek para görmek motivasyon verir

#### C.5 ASLA Yapma

- Kayıp sonrası ek sermaye koyma ("averaging down" trapı)
- Paper'daki $10K beklentisini $200'e ölçekleme (lineer değil — psikoloji farklı)
- Breaker tetiklendiğinde override etme — sistem duyduysa sebebi var

---

### D. .env LIVE Konfigürasyonu

Mevcut `.env` dosyasını aşağıdakilerle güncelle. Testnet key'leri SİLME — yorum satırına al:

```bash
# === FAZ 7: CANLI MOD ===

# Çalışma modu — live olarak değiştir
PA_RUN_MODE=live

# Explicit onay — bu satır olmadan sistem live emir atmaz
PA_LIVE_CONFIRM=YES_I_KNOW

# Binance MAINNET anahtarları (testnet değil!)
BINANCE_API_KEY=<mainnet_api_key_buraya>
BINANCE_API_SECRET=<mainnet_api_secret_buraya>
BINANCE_TESTNET=false

# Live sermaye
PA_LIVE_INITIAL_CAPITAL=200

# Faz 7 defansif risk — paper'daki %2'den DAHA SIKI başla
PA_LIVE_RISK_PER_TRADE=0.01

# Faz 7: leverage max 3x (3 ay sonra 5x'e çık)
PA_LIVE_MAX_LEVERAGE=3

# Testnet key'leri devre dışı bırak (silme — Faz 6'ya dönüş gerekirse lazım)
# BINANCE_TESTNET_API_KEY=...
# BINANCE_TESTNET_API_SECRET=...
```

> KRITIK: `.env` dosyası Git'e girmesin. Kontrol et:
> ```bash
> git status  # .env görünmemeli
> git check-ignore -v .env  # ".gitignore:X:.env" çıktısı beklenir
> ```

---

### E. İlk Hafta Protokolü

İlk 7 gün sistem "yürüyüş testi" modunda. Fazla işlem bekleme — temiz veri topla.

#### E.1 Her Sabah Rutini (Zorunlu — İlk 2 Hafta)

```bash
# 1. CEO brief oku (2-3 dk)
PYTHONPATH=src python scripts/llm_orchestrator.py --mode daily-brief
# Raporlar: reports/ceo/YYYY-MM-DD-brief.md

# 2. Açık pozisyon durumuna bak
PYTHONPATH=src python scripts/paper_status_report.py   # live için yakında live_status_report

# 3. Breaker durumu kontrol et
PYTHONPATH=src python scripts/breaker_monitor.py --status
```

#### E.2 Trade Limiti

| Hafta | Max Trade/Hafta | Neden |
|---|---|---|
| Hafta 1 | 5 | Sample küçük tut — her trade'i elle incele |
| Hafta 2 | 7 | Sistem güven kazandıysa |
| Hafta 3+ | Sınırsız (strateji sinyaline bırak) | Track record var |

İlk 5 işlem içinde 3 kayıp görürsen → DUR. Sbab araştır, devam etme.

#### E.3 Her Trade İçin After-Action Review

Her kapanan trade sonrası:

```bash
PYTHONPATH=src python scripts/llm_orchestrator.py --mode post-mortem --trade-id live-faz7-<id>
```

- Analyst ajanı: entry timing, slippage, R-multiple gerçek vs beklenti
- Sapma > %50 → Lab'a ilet, sistemi durdur, incele

#### E.4 DD Alarm Eşikleri

| Eşik | Tepki |
|---|---|
| DD %3 | Telegram INFO uyarısı — izle |
| DD %5 | Breaker tetiklenir → Sistem otomatik durur → İnsan manuel incele |
| DD %7 | Sistemi açma — önce yazılı post-mortem |
| DD %10 | Hafta kapatıldı — o hafta yeni pozisyon yok |

```bash
# Breaker sonrası MANUEL inceleme olmadan AÇMA
PYTHONPATH=src python scripts/breaker_monitor.py --reset
# "YES" yazarak onayla — bu onay "incelediğimi teyit ediyorum" anlamına gelir
```

#### E.5 Telegram Alarm Kontrol Listesi

Her aşağıdaki olay Telegram'a mesaj atmalı:

- [ ] Yeni pozisyon açıldı (LONG/SHORT, sembol, fiyat, leverage)
- [ ] Pozisyon kapandı (TP/SL, P&L, R-multiple)
- [ ] Breaker tetiklendi (CRIT seviye)
- [ ] Günlük brief tamamlandı
- [ ] Sistem başladı / durdu

Telegram mesajı gelmiyorsa sistemi AÇIK BIRAKMA — kör uçuyorsun.

---

### F. Aylık Review + Ölçek Protokolü

Her ay sonunda Analyst ajanı ile gözden geçir:

```bash
PYTHONPATH=src python scripts/llm_orchestrator.py --mode weekly-summary
# (haftalık summary — aylık için 4 haftalık özet al)
```

#### F.1 Performans Değerlendirme Matrisi

| Aylık Sapma | Karar |
|---|---|
| > %30 (beklentiden kötü) | 1 ay daha bekle, sermaye artırma, nedeni araştır |
| %20–%30 sapma | Devam et ama leverage artırma; 1 ay daha gözlem |
| < %20 sapma (iyi aralık) | Sermaye %50 artır: $200 → $300 |
| < %10 sapma (harika) | Sermaye %100 artır: $200 → $400 |

Sapma = `abs(gerçek_getiri - beklenen_getiri) / beklenen_getiri`

#### F.2 Risk Per Trade Kademe Planı

```
Başlangıç (Faz 7, Ay 1-3):  %1  — defansif
3. aydan sonra (DD < %20):   %1.5 — orta
6. aydan sonra (DD < %20):   %2  — production config
```

> Önemli: Risk arttırma kararı sayısal — "hissediyorum iyi gidiyor" değil.
> DuckDB journal'dan gerçek DD değerini çek, karar ver.

#### F.3 Sermaye Büyüme Planı

```
Ay  1-3:  $200 (değiştirme)
Ay  4:    $300 (sapma < %20 ise +%50)
Ay  7:    $500 (sapma < %20 ise +%67)
Ay 10:    $800 (sapma < %20 ise +%60)
Ay 13:    $1,200 (Faz 8 eşiği)
```

Her adımda ilave sermaye banka hesabından gelir — sisteme yeniden yatırım değil.

---

### G. Acil Durum Protokolü

> Panik yaparken doğru karar alınmaz. Bu adımlar soğukkanlılıkla takip edilir.

#### G.1 Kill-Switch Tetikleme

```bash
# Sistemi DERHAL durdur
pa ops halt

# Veya doğrudan:
PYTHONPATH=src python scripts/breaker_monitor.py --force-halt

# Kill-switch dosyası güncellenir:
# logs/kill_switch.json → {"active": true, "reason": "manual_halt", ...}
```

#### G.2 Manuel Pozisyon Kapatma

Sistem dursa da açık pozisyonlar exchange'de kalır. Manuel kapat:

```
Binance → Futures/Spot → Pozisyonlar → Her birini manuel kapat (Market order)
```

Alternatif (script varsa):
```bash
PYTHONPATH=src python -c "
from price_action.execution.order_manager import OrderManager
# MVP: Bu placeholder — live broker implement edildiğinde flattenAll() çağrısı
print('Manual close required via Binance web/app')
"
```

> NOT: `order_manager.py`'deki `_maybe_place_protective_orders` şu an placeholder.
> Live broker implementasyonu tamamlanana kadar pozisyon kapatma Binance UI'dan yapılır.

#### G.3 Audit Trail Export

```bash
# DuckDB journal'ı CSV'ye aktar
duckdb data/paper_journal.duckdb -c "COPY (SELECT * FROM paper_trades) TO 'exports/faz7_audit_$(date +%Y%m%d).csv' (HEADER, DELIMITER ',')"

# Postgres journal backup
docker compose exec postgres pg_dump price_action > exports/faz7_postgres_$(date +%Y%m%d).sql
```

#### G.4 Post-Mortem Protokolü

Acil durdurma sonrası 24 saat içinde:

```bash
PYTHONPATH=src python scripts/llm_orchestrator.py --mode crit-alarm --reason "Emergency halt — post-mortem başlıyor"
```

Post-mortem soruları:
1. Hangi trade / sinyal tetikledi?
2. Slippage beklentinin kaç katıydı?
3. Breaker eşiği doğru muydu?
4. Kod mu yoksa piyasa koşulu mu?

**Sebep netleşmeden sistemi tekrar açma.** "Bir daha olmaz" geçerli sebep değil.

---

### H. Beklentiler vs Gerçeklik

> Backtest rakamları laboratuvar koşullarında. Gerçek piyasa farklıdır.

#### H.1 Neden Backtest > Gerçek?

| Sorun | Backtest Varsayımı | Gerçek Etki |
|---|---|---|
| Slippage | 5 bps sabit | 5–50 bps arası (volatile piyasada daha fazla) |
| Funding rate | 0 | Her 8 saatte %0.01–0.1 (uzun vadede %15-30/yıl maliyet) |
| Downtime | %0 | Sunucu çökmesi, network, API limit |
| Lookahead bias | Yok (kontrollü) | Olası gerçek sinyal gecikmesi |
| Borrow/short kısıtı | Yok | Spot shortlama yok, perp gerekir |
| Psikoloji | Yok | Manuel müdahale → kuralları kırma riski |

#### H.2 Realist ROI Tablosu

Backtest: yıllık **%68** compound (3y, $10K base)
Gerçek beklenti (slippage, funding, downtime): **%35-50** arası

| Dönem | Backtest (teorik) | Realist (%35/yıl) | Realist (%50/yıl) |
|---|---|---|---|
| 6 ay | $272 (+%36) | $233 (+%17) | $249 (+%24) |
| 1 yıl | $336 (+%68) | $270 (+%35) | $300 (+%50) |
| 2 yıl | $560 (+%180) | $365 (+%82) | $450 (+%125) |
| 3 yıl | $946 (+%373) | $493 (+%147) | $675 (+%238) |

> Tablo: $200 başlangıç, %1 risk/trade, sermaye artışı olmadan compound.
> Sermaye ölçeklendirme yapılırsa (F.3 planı) rakamlar daha yüksek olur.

#### H.3 Psikolojik Hazırlık

- **MaxDD %65 gerçek olabilir.** $200'ün %65'i = $130 kayıp. Bu noktada $70 kalır.
  Sistem matematiksel olarak doğru çalışıyor olabilir — drawdown stratejinin parçası.
- **Ay 1'de para kazanmayabilirsin.** Normal. 1d timeframe'de ayda 4-8 trade.
- **Compound yavaşdır.** $200 → $300 bir yılı alabilir. Bu bir emeklilik fonu değil — kanıt sistemi.
- **Gerçek kazanç sermaye artışından gelir.** $200 ile $946'ya ulaşmak 3 yıl.
  $5,000 ile başlasaydın: $23,650. Faz 8'in amacı sermaye büyütmek.

---

### I. Faz 8 Hazırlığı (3+ Ay Sonra, Sapma < %20 ise)

Faz 8 bu playbook'un kapsamı dışındadır — sadece genel plan:

#### I.1 Geçiş Kriterleri (Faz 7 → 8)

- [ ] Faz 7'de en az 3 ay gerçek piyasa track record
- [ ] Aylık sapma < %20 (3 ay ortalaması)
- [ ] Hiç elle müdahale yok (tam otomatik)
- [ ] Postgres journal eksiksiz (her trade audit trail'de)
- [ ] Sermaye $1,000+ (organik büyüme veya ek sermaye)

#### I.2 Faz 8 Hedefleri

```
Multi-account:
  - Sub-account 1: engulfing_continuation (mevcut strateji)
  - Sub-account 2: Donchian breakout (yeni strateji araştırılacak)
  - Sub-account 3: Funding rate arbitrage (araştırma aşamasında)

Sermaye kademesi:
  $1K → $5K → $25K (her adım 6 ay + sapma < %20 kriteriyle)

Altyapı:
  - Cloud-hosted runner (VPS — kesintisiz)
  - Prometheus/Grafana 7/24 izleme
  - Otomatik pozisyon kapatma (order_manager live implementasyon)
  - Portföy-düzey korelasyon izleme (çoklu strateji)
```

---

### Sıkça Karşılaşılan Sorunlar (Faz 7)

**"Live trade yapamıyorum / emir gitmiyor"**

En yaygın sebep `PA_LIVE_CONFIRM` eksikliği:
```bash
# .env kontrol:
grep PA_LIVE_CONFIRM .env
# Beklenen: PA_LIVE_CONFIRM=YES_I_KNOW
# Eksikse → OrderManager "live_guard_failed" ile reject eder
```

**"Funding rate beklenenden yüksek"**

Perp pozisyon tutarken her 8 saatte funding rate ödenir/alınır.
Yüksek funding pozisyonu pahalıya getirir:
```bash
# Anlık funding rate kontrol (ccxt ile):
PYTHONPATH=src python -c "
import ccxt
b = ccxt.binance({'enableRateLimit': True})
fr = b.fetch_funding_rate('BTC/USDT:USDT')
print(fr['fundingRate'], fr['nextFundingTime'])
"
# Funding > %0.1 ise (8 saatlik) → yüksek long cost → strateji avantajı azalır
```

**"Slippage backtest'ten çok farklı çıkıyor"**

Paper/backtest 5 bps varsaydı, gerçekte 20+ bps çıkıyor:
```bash
# DuckDB'den ortalama slippage sorgula:
duckdb data/paper_journal.duckdb -c "
SELECT AVG(slippage_bps), MAX(slippage_bps), COUNT(*)
FROM paper_trades
WHERE status='closed' AND dry_run=false
"
# > 15 bps ortalama → strateji parametrelerini slippage ile yeniden backtest et
```

Çözüm: `configs/risk.yaml` → `execution.max_slippage_bps` değerini 25'ten 15'e düşür.
Sistem yüksek slippage'da emir reddetsin.

**"Açık pozisyon görünmüyor ama exchange'de var" (Sync sorunu)**

Paper state ile exchange state senkron değil:
```bash
# Exchange'deki gerçek pozisyonları kontrol et:
PYTHONPATH=src python -c "
import ccxt, os
b = ccxt.binance({
  'apiKey': os.environ['BINANCE_API_KEY'],
  'secret': os.environ['BINANCE_API_SECRET'],
  'enableRateLimit': True,
})
pos = b.fetch_positions()
for p in pos:
    if float(p.get('contracts', 0)) > 0:
        print(p['symbol'], p['side'], p['contracts'], p['unrealizedPnl'])
"
# Görülen ama local state'de olmayan pozisyonu Manuel kapat (Binance UI)
# Sonra local state'i sıfırla: del logs\execution\paper_state_faz6.json
```

Bu sorun `order_manager.py` live broker implemente edildiğinde ortadan kalkar.
Şu an için manuel senkronizasyon gerekir.

---

## Yardım

- Sistem mimarisi: `ARCHITECTURE.md`
- Departman kuralları: `agents/<name>.md`
- Kararlar: `memory/shared/decisions/ADR-*.md`
- Geçmiş dersler: `memory/shared/lessons/`
- RAG corpus durumu: `reports/lab/rag-refresh-*.md`
- Faz durumu: `README.md` "Faz durumu" bölümü

## GO/NO-GO — Mikro-Canlıya Geçiş Kriterleri (Principal onayı: 2026-07-06)

> **Kapsam:** v15p2 (veya halefi) testnet forward-test'inden **mikro-canlıya**
> ($1-2K gerçek sermaye, kaldıraç ≤2x) geçiş kararı. Bu bölüm karar SABİTİDİR;
> tartışma yeri değil, kontrol listesidir.

**GEÇİŞ = aşağıdakilerin HEPSİ birden sağlanır:**

| # | Kriter | Eşik | Ölçüm kaynağı |
|---|---|---|---|
| 1 | Forward test süresi | ≥ **6 hafta** (kesintisiz, aynı config) | deploy ts → bugün (borsa income API) |
| 2 | Kapanmış trade sayısı | ≥ **40** | borsa income REALIZED_PNL event'leri |
| 3 | Net PnL (fee+funding dahil) | > **0** | borsa-truth income toplamı |
| 4 | Max drawdown (dönem) | < **%2** (günlük breaker %4'ün yarısı) | equity eğrisi, borsa-truth |
| 5 | Gerçekleşen slippage | backtest varsayımının **±%25** içinde | slippage_tracker vs config bps |
| 6 | Açık overdue denetim bulgusu | **0** | memory/audit/findings_register.jsonl |

**Kurallar:**
- Herhangi biri sağlanmadıkça süre uzar — kriter geriye dönük **gevşetilemez**.
- Gevşetme ihtiyacı doğarsa: KARAR-GUNLUGU'ne gerekçeli kayıt + **1 hafta zorunlu
  bekleme** sonrası ancak yeni kriter setiyle değerlendirme (aynı gün karar yasak).
- Config değişikliği (parametre/strateji/evren) forward-test saatini **sıfırlar**.
- Forex: SPK gereği **paper-only kalır** — bu tablo forex'e uygulanmaz.
- Mikro-canlı geçtikten sonra sermaye artışı ayrı bir GO/NO-GO turu gerektirir
  (bu tablo + canlı dönemin kendi 6 haftası).
