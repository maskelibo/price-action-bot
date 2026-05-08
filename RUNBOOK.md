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
cd "C:\Users\koray\projeler\Price Action"
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
cd "C:\Users\koray\projeler\Price Action"

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

### Sorun Giderme

**"ccxt not found"**:
```bash
uv add ccxt
```

**"duckdb not found"** (journal devre dışı kalır, log dosyasına düşer):
```bash
uv add duckdb
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

## Yardım

- Sistem mimarisi: `ARCHITECTURE.md`
- Departman kuralları: `agents/<name>.md`
- Kararlar: `memory/shared/decisions/ADR-*.md`
- Geçmiş dersler: `memory/shared/lessons/`
- RAG corpus durumu: `reports/lab/rag-refresh-*.md`
- Faz durumu: `README.md` "Faz durumu" bölümü
