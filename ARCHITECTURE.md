# Mimari — Price Action Otonom Trading Şirketi

## 0. Tek Cümle Özet
10 departman → her biri net girdi/çıktı kontratlı bir Python paketi → 4 LLM-şeflik departmanı (CEO / Researcher / Analyst / Lab) Claude Agent SDK üzerinde çalışır → CEO orkestrasyonu raporları konsolide eder → **emir veren tek katman deterministik koddur** (LLM emir vermez).

## 1. Tasarım İlkeleri (DEĞİŞMEZ)

1. **LLM ≠ trader.** LLM agent'lar yalnızca araştırma, hipotez, raporlama yapar. Order veren tek yol `execution/` içindeki deterministik kod.
2. **Faz gate'leri nümerik.** Her faz sayısal eşikle biter; eşik düşerse ileri gidilmez.
3. **Reproducibility.** Her backtest ve trade `(git_hash, config_hash, data_hash)` manifestosu ile diske yazılır.
4. **Lookahead-bias-free.** Pattern detector'lar yalnızca `t-1` kapanışını kullanır; karar `t` mumu açılışından sonra üretilir; engine'de explicit shift testi.
5. **Risk her zaman önce.** Sinyal üretimi serbest, risk katmanı tüm sinyalleri red edebilir; bu hak yalnızca insan onayı ile devre dışı bırakılır.
6. **Kademeli sermaye.** Backtest gate → paper gate → mikro canlı → ölçek. Her adım ek gate.
7. **Local-first.** Tüm bağımlılıklar lokal (DuckDB, ChromaDB, Postgres). Cloud Faz 7 sonrasında.
8. **Secrets izole.** API anahtarı git'e girmez; `.env` + docker secrets + 600 izinli memory/runtime/.

## 2. Veri Akışı (High-Level)

```
                                  ┌──────────────────┐
                                  │  knowledge/      │ (RAG corpus: makaleler,
                                  │   ChromaDB       │  YouTube transkriptleri)
                                  └────────┬─────────┘
                                           │ retrieve
                                           ▼
┌────────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────────┐    ┌──────────────┐
│ Exchange   │───▶│  Data        │───▶│  Signals    │───▶│  Strategies  │───▶│  Risk        │
│ (ccxt WS)  │    │  ingest+QC   │    │  patterns + │    │  composition │    │  sizing+DD   │
└────────────┘    └──────────────┘    │  ML filter  │    └──────────────┘    └──────┬───────┘
                          │           └─────────────┘                                │
                          ▼                                                          ▼
                  ┌──────────────┐                                           ┌──────────────┐
                  │  DuckDB +    │◀──────── tüm departmanlar okur ──────────│  Portfolio   │
                  │  Parquet     │                                           │  allocator   │
                  └──────────────┘                                           └──────┬───────┘
                          ▲                                                          │
                          │ journal                                                  ▼
                          │                                                  ┌──────────────┐
                          │                                                  │  Execution   │
                          │                                                  │  paper/live  │
                          │                                                  └──────┬───────┘
                          │                                                          │ fills
                          │                                                          ▼
                  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
                  │  Analytics   │◀───│  CEO loop    │◀───│  Lab         │    │  Postgres    │
                  │  KPI + LLM   │    │  (orchestr.) │    │  self-improve│    │  trade DB    │
                  │  postmortem  │    │              │    │              │    │              │
                  └──────┬───────┘    └──────────────┘    └──────────────┘    └──────────────┘
                         │
                         ▼ Telegram / Grafana
                 (rapor + alarm)
```

## 3. Departmanlar

### 3.1 CEO Office (`agents/ceo`)
**Persona:** Tier-1 yatırım bankası (BofA / Goldman Sachs) prop trading desk başkanı. Risk-bilinçli, sayısal, soğukkanlı. Sermayeyi koruma > getiri maksimizasyonu. Sürekli "downside scenario"yu sorgular.
**Girdi:** Analytics günlük raporu, Researcher hipotez listesi, Risk DD durumu, Lab tournament sonucu.
**Çıktı:** Günlük direktif (markdown, `reports/ceo/YYYY-MM-DD.md`), sermaye tahsis önerisi, kriz protokolü tetikleme.
**Karar yetkisi:** Yalnızca **öneri**. Otomatik pozisyon limiti / breaker eşiği değişimi insan onayı sonrası deterministik koda yazılır.

### 3.2 Data Engineering (`data/`)
**Şef:** Yok — saf deterministik. Loglar Ops izler.
**Görev:**
- ccxt ile Binance + Bybit'ten USDT-margin perpetual + spot OHLCV (1d, 1w) — son 3+ yıl.
- Sembol evreni: `min_volume_usdt > 1M`, listing > 1 yıl önce, delisting bayrağı yok.
- DuckDB ana store + Parquet partition (`venue/symbol/timeframe/year=YYYY/month=MM`).
- Kalite kontrol: gap, duplicate, anomali (z-score > 8 hacim), forward-fill stratejisi.
**KPI:** Eksik mum oranı < %0.1, ingest gecikmesi < 5dk.

### 3.3 Research & Quant (`agents/researcher` + `backtest/`)
**Persona:** Renaissance / Two Sigma stilinde quantitative researcher. Hipotez → backtest → walk-forward → red ya da terfi. Veri sızıntısına paranoid yaklaşır. Confounding'i her şart altında izole eder.
**Girdi:** RAG bilgi tabanı (price action makaleleri, YouTube transkriptleri), data layer.
**Çıktı:** Yeni strateji manifestosu (`configs/strategies/<name>.yaml`), backtest raporu (HTML), hipotez gerekçesi (`memory/researcher/learning.md`'ye yazılır).
**Süreç:**
1. RAG'den ilgili literatürü çek.
2. Hipotez yaz: "X koşulunda Y kalıbı Z istatistiksel anlamlılıkla pozitif edge sağlar."
3. Backtest + walk-forward (3y train / 6m test, rolling).
4. Çoklu hipotez testi düzeltmesi (Bonferroni / Bartlett).
5. Gate geçen → terfi adayı; düşen → red gerekçeli arşivlenir.
**KPI:** Üretilen aday strateji sayısı, OOS Sharpe ortalaması, terfi oranı, gerekçeli red oranı.

### 3.4 Signal Engineering (`signals/`)
**Şef:** Yok — saf deterministik (vektörize pandas/numba).
**Görev:**
- **Mum kalıpları:** engulfing (bullish/bearish), pin bar (alt/üst), inside bar, doji (klasifikasyonlu), morning/evening star.
- **Yapı:** swing high/low (fractal n=2), yatay S/R (kümeleme), trendline, BOS / CHoCH (opsiyonel — Faz 1+).
- **Filtreler:** ATR threshold, hacim z-score, MA/EMA trend filter, volatilite rejimi.
- **Confluence skoru:** ağırlıklı toplam (ör. pin bar @ S/R + uptrend = 3 pt).
**KPI:** Detector precision (manuel etiketli set), false positive oranı, pattern başına edge.

### 3.5 Risk Management (`risk/`)
**Şef:** Yok — saf deterministik. Mikro-DSL (yaml) ile parametreler.
**Görev:**
- **Sizing:** Fixed-fractional %1 (configurable) → ATR bazlı SL → quantity.
- **Kelly cap:** %0.25 (paranoid); confidence belirsizliği yüksekse %0.10.
- **Kaldıraç tavanı:** sembol başına 3x (configurable, perp için).
- **Korelasyon kapısı:** Eğer açılacak pozisyon, mevcut açıklarla > 0.7 korelasyonluysa boyut yarıya iner.
- **DD breaker:** günlük %5, haftalık %10, aylık %15 → tüm yeni emirler durdurulur, açıklar manuel kapatılır.
- **Likidite kontrolü:** emir size'ı 1-dk hacmin %1'inden büyükse parçalama veya iptal.
**KPI:** Realize edilen MaxDD, breaker tetikleme sayısı, slippage uyumu.

### 3.6 Portfolio Management (`portfolio/`)
**Şef:** Yok — deterministik allocator.
**Görev:**
- Sembol evrenini Risk + likidite ile filtrele.
- Aktif pozisyon sayısı tavanı (örn. eşzamanlı 8).
- Eşit-ağırlık başlangıç; korelasyon-bazlı ayarlama.
- Sektör/tema concentration (örn. tüm pozisyonlar L1 olamaz).
**KPI:** Açık pozisyon korelasyonu ortalaması, pozisyon başına ağırlık varyansı.

### 3.7 Execution (`execution/`)
**Şef:** Yok.
**Görev:**
- ccxt unified API (`broker_base.py` ABC → `ccxt_paper.py` / `ccxt_live.py`).
- Smart order routing: market vs post-only limit (config'e göre).
- Kısmi fill yönetimi, retry (tenacity), dead man's switch.
- Slippage telemetrisi → Analytics'e besleme.
**KPI:** Slippage bps, doldurma oranı, retry sayısı.

### 3.8 Analytics & Performance Mgmt (`agents/analyst` + `analytics/`)
**Persona:** Çok deneyimli risk/perf analisti (BofA Quantitative Analytics ekibi tarzı). Sayıları yorumlar, anlatıya çevirir, gizli bias'ları yakalar.
**Görev:**
- Trade journal (Postgres), her trade için manifest.
- KPI: Sharpe, Sortino, Calmar, MaxDD, profit factor, win rate, expectancy, MAE/MFE.
- Günlük & haftalık LLM brief (markdown + Telegram).
- Trade post-mortem: kayıplı işlemleri kategorize et (yanlış kalıp / yanlış zaman / yanlış boyut / piyasa rejim değişimi).
**KPI:** Brief kalitesi (insan değerlendirmesi 1-5), yanlış kategorizasyon oranı.

### 3.9 Operations / SRE (`agents/ops_engineer` + ops scripts)
**Persona:** Trading firma SRE'si. Uptime > özellik. Alarm yorgunluğunu yönetir, sinyal-gürültü oranını korur.
**Görev:**
- Docker compose health, scheduler (APScheduler), log rotation.
- Prometheus metrics: ingest gecikmesi, agent çağrı sayısı, LLM token tüketimi, hata oranı.
- Grafana dashboard'ları sağlar.
- Telegram alert (sembol bazlı throttling ile).
**KPI:** MTTR, alarm SNR, uptime.

### 3.10 Self-Improvement Lab (`agents/lab_scientist`)
**Persona:** "AlphaZero-tarzı" araştırmacı. Mevcut canlıya saygılı, ama sürekli sorgulayan. Kazanan adayları cesurca terfi ettirir.
**Görev (haftalık):**
1. Walk-forward yenile.
2. Drift detection: canlı Sharpe vs backtest Sharpe (KS testi).
3. Tournament: aday stratejiler vs canlı; OOS Sharpe + DD.
4. RAG'i tazele (yeni makale/video crawl).
5. CEO'ya brief.
**KPI:** Aday üretim hızı, terfi başarı oranı (terfi sonrası canlı Sharpe), drift erken-tespit oranı.

## 4. Memory Mimarisi

`memory/` klasörü 4 katman + paylaşılan alan:

```
memory/
├── shared/                        # tüm departmanlar
│   ├── facts/                     # değişmez/yarı-değişmez gerçekler
│   │   ├── market_microstructure.md
│   │   ├── exchange_behaviors.md
│   │   └── crypto_calendar.md
│   ├── lessons/                   # post-mortem'den çıkan dersler
│   │   └── YYYY-MM-DD-<slug>.md
│   ├── decisions/                 # ADR — Architecture Decision Records
│   │   └── ADR-NNN-<slug>.md
│   └── glossary.md
│
└── <agent_name>/                  # her LLM-şefli departman
    ├── identity.md                # persona + rules + KPI
    ├── learning.md                # öğrenilen kalıplar (fail/success)
    ├── know_how.md                # tekrarlanan iş akışları (playbook)
    ├── decisions/                 # bu departmanın aldığı kararlar
    │   └── YYYY-MM-DD-*.md
    └── runtime/                   # JSONL, gitignore (kısa vadeli scratch)
        └── episodic.jsonl
```

**Memory tipleri (semantik):**
- **Identity** — kim, ne için var, hangi kurallarla. (Statik; nadiren değişir.)
- **Know-how** — playbook: "X durumda Y adımları izle." Tekrarlanan iş akışı.
- **Learning** — özetlenmiş ders ("şu durumda şu yanılgıya düşmüştüm"). Süreç sonu güncellenir.
- **Episodic (runtime)** — JSONL, son N olay, kısa vadeli. Konsolidasyon sonrası lessons'a transfer.
- **Shared facts** — tüm agent'lara expose edilir; doğrulanmış gerçekler.

**Konsolidasyon:** Lab haftalık `runtime/episodic.jsonl` dosyalarını okur, tekrar eden başarısızlıkları `learning.md`'ye, tekrar eden başarıları `know_how.md`'ye, ekosistem-geneli dersleri `shared/lessons/`'a yazar.

## 5. RAG Mimarisi

`knowledge/` klasörü:
- `seeds.yaml` — canonical kaynak listesi (Brooks, Wyckoff, ICT, klasik makaleler, YouTube kanal+playlist URL'leri).
- `articles/raw/` — ham HTML/PDF.
- `articles/clean/` — markdown'a normalize edilmiş.
- `transcripts/` — YouTube transcript-api ile çıkartılan markdown.
- `index/` — ChromaDB persistent (embedding: `sentence-transformers/all-MiniLM-L6-v2` veya `BAAI/bge-large-en-v1.5`).

**İngest pipeline (`rag/ingest.py`):**
1. `seeds.yaml` oku.
2. Yeni / güncellenmiş kaynakları indir (etag + hash).
3. Trafilatura ile temizle, markdown'a çevir.
4. Chunk (512 token, 64 overlap), metadata: `source, type, author, date, topic_tags, hash`.
5. Embed → ChromaDB. Aynı hash varsa skip.

**Sorgu (`rag/retrieve.py`):**
- Researcher hipotez yazarken ilgili k=8 chunk çeker.
- Lab haftalık özet için yeni eklenenlerin top-N özetini Analyst'e geçirir.

**Tazeleme:** Lab haftalık çalıştırır; günlük olarak yeni RSS / yeni YouTube videoları taranır.

## 6. Orchestrator (CEO Loop)

`orchestrator/ceo_loop.py` — APScheduler:

| Job | Sıklık | Açıklama |
|---|---|---|
| `ingest_data` | Saatlik / günlük TF kapanışı | OHLCV güncelle |
| `daily_research` | 02:00 UTC | Researcher → yeni hipotez taraması |
| `signal_scan` | 1D kapanışı | Sinyal üret, Risk + Portfolio onayla |
| `execute_orders` | signal_scan sonrası | Paper/live execution |
| `daily_kpi` | 23:00 UTC | Analytics raporu + Telegram |
| `weekly_lab` | Pazar 03:00 UTC | Lab tournament + drift |
| `weekly_rag_refresh` | Pazar 04:00 UTC | RAG yeni içerik tarama |
| `monthly_review` | Ay sonu | CEO derinlemesine inceleme |

## 7. Faz Gate'leri (Tekrar)

| Faz | Gate | Eşik |
|---|---|---|
| 0 | Veri kalitesi | Eksik mum < %0.1 |
| 1 | Pattern precision | Manuel etiketli sette > %75 |
| 2 | Backtest ROI (3y, tüm coinler) | Yıllık net > %70 / Sharpe > 1.5 / MaxDD < %20 / WF dilimleri %70+ pozitif |
| 3 | Risk sonrası ROI | Sharpe değişimi > -%10 / MaxDD < %15 |
| 4 | ML uplift | OOS Sharpe ML+ vs ML- > +%15 |
| 5 | LLM brief | 1 hafta kesintisiz brief, ≥1 onaylı aksiyon |
| 6 | Paper trading | 4 hafta, P&L sapma < %20 |
| 7 | Mikro canlı | Aylık net pozitif (mikro sermaye) |

## 8. Doğrulama Mimarisi

- **Unit:** Pattern detector'lar bilinen mum dizisinde.
- **Property-based:** Hypothesis ile rastgele OHLC üret, invariant kontrolü (örn. equity monotonik artar mı yalnızca kâr trade'de).
- **Lookahead testi:** Geleceği bilen oracle stratejisi tüm gate'leri katlar; gerçek strateji shuffle'lı returns baseline'ı yenmeli.
- **Reproducibility:** Aynı manifest → bit-identical equity curve.
- **Stress:** 2022 Mart (LUNA çöküşü), 2022 Kasım (FTX), 2024 Mart (BTC ATH) sahneleri ayrı ayrı analiz edilir.
