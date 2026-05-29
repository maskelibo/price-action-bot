---
doc_id: researcher-20260529T143000-btc-dominance-shift-triggers-seed-abort
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-29T14:30:00Z
status: REJECTED
confidence: high
depends_on: []
blocks: []
requested_review_from: [ceo, ops_engineer]
tags: [seed_abort, pre_test_reject, rag_empty, premise_contradiction, btc_dominance, data_gap, audit_trail, first_trigger]
supersedes: null
hash: null
---

# Seed Abort — "BTC Dominance Shift Triggers" (v1, first trigger, audit-trail)

## 1. Trigger

- Cron / otomatik SOP-1 prompt'u, seed payload: **"BTC dominance shift triggers"**.
- Trigger ts: 2026-05-29T14:30:00Z.
- RAG context (user prompt verbatim): "(RAG corpus boş veya hit yok)".
- Daha önce bu seed için seed_abort_log.jsonl'da kayıt YOK → bu **ilk tetik**.

## 2. Karar

**RED — pre-test, kod yazılmadı, hipotez yazılmadı.**

`status: REJECTED` (PROTOCOL §2: REJECTED geri açılamaz; bu seed yeniden meşru olursa yeni doc + supersedes).

## 3. Üç Bağımsız Ret Nedeni

### 3.1 RAG=0 → SOP-5 sert tetik

Persona ve SOP-5:
> "RAG bulgu yoksa hipotezi terk etmeyi düşün — özgün bir iddian olabilir ama destek de yok."

Persona "Read first, code second" + "literatürde en az 3 referansa bakarsın". RAG hit = 0 → 3 referans yok → hipotez yazımı persona ihlali.

### 3.2 Veri kapsamı dışı — "BTC dominance" universe'de yok

- Bizim data/ DuckDB universe'imiz: crypto perpetuals (USDT) + FX 4H/1H (HistData).
- **BTC.D (BTC dominance) external bir sembol** — TradingView (`CRYPTOCAP:BTC.D`), CoinMarketCap, TradingEconomics gibi 3rd-party kaynaklardan gelir. Data Engineer envanterinde yok.
- Dominance = `BTC_market_cap / total_crypto_market_cap`; total_market_cap için **delisted/long-tail token universe** lazım → survivorship bias'lı seri (yeni listing'ler dominance paydasını şişiriyor, eski delisting'ler küçültüyor) — bizim survivorship-aware ingest pipeline'ımız dışında.
- Data Engineer'a ingest job açmadan hipotez yazmak = **boş kova** — backtest çalışmaz, robustness suite çalışmaz. Pre-registration anlamsız.
- Bu hipotez "Yes if data; pending data" formuna girer → kayıt değil iş kalemi (Data Engineer ticket'i konusu).

### 3.3 Curve-fit mıknatısı + narrative-driven yapı

"BTC dominance shift triggers" seed'i 4+ serbestlik derecesi taşıyor; hangi spesifik hipotezi yazsam p-hacking riski yüksek:

| Eksen | Tipik aday değerler | Serbestlik |
|---|---|---|
| Lookback | 7/14/21/30/60 gün | 5 |
| Shift threshold | ±0.5 / ±1.0 / ±1.5 / ±2.0 σ | 4 |
| Hold period | 1d / 3d / 7d / 14d | 4 |
| Trade direction | alt-long / alt-short / BTC-long / BTC-short | 4 |
| Symbol subset | top-10 alt / top-30 / DeFi cluster / L1 cluster | 4 |

Çapraz çarpım: 5×4×4×4×4 = **1280 cell**. Bonferroni `α/m` = 3.9×10⁻⁵, Holm benzeri. Bu hacimde "best cell" şans eseri pozitif Sharpe üretir; pre-reg disiplini olmadan post-hoc bir alt cell seçimi = klasik p-hacking.

3 olası "çıkış" patikası, üçü de illegitimate:

1. **"Dominance düşerken alt-coin long"** (klasik altseason narrative):
   - Anti-narrative bias ihlali. "Mantıklı geliyor" hipotez gerekçesi değildir.
   - Üstelik 2017-2018 ve 2021 altseason rejimine dayanır; 2024-25 yapısal olarak farklı (ETF akışları BTC-konsantre, alt-coin sezonu daha zayıf). Rejim-dışı genelleme.

2. **"Dominance Z-score crossover"** (teknik trigger):
   - 4 hyperparam (window, z-threshold, smoothing, holdtime). Optuna ile "best" ararsam multi-testing düzeltmesi sonrası anlamlılık erir.
   - Üstelik dominance serisi yüksek otokorelasyonlu → block-bootstrap / Politis-Romano stationary bootstrap gerekir, klasik shuffle null yanıltır.

3. **"Funding rate × dominance shift convergence"** (multi-feature):
   - 2 feature → daha fazla hyperparam → daha fazla curve-fit yüzeyi.
   - Funding rate de external (Coinglass / Binance funding history). Aynı data-gap problemi.

## 4. Sayısal Etki (yazsaydım)

- Family-wise hipotez sayısı (rolling 7d, kayıtlardan): 14 (daily-scan abort kaydındaki sayı baz alındı) + 1 = **15**.
- Holm `α/m` = 0.05/15 = **3.33×10⁻³** (önceki ile aynı, marjinal artış sıfır çünkü RED status).
- Beklenen edge posterior (RAG=0 + universe-out-of-scope + 4D curve-fit yüzeyi): **≤ 0.03**. Çok düşük.
- Compute maliyeti (yazsaydım): backtest engine çalışmaz (data yok) → 0 dk, ama Data Engineer'a 1-2 günlük ingest job açar. Lab tournament prior boş → bu da gürültü.

## 5. Önceki Vakalarla İlişki

- **vsa-companion seed-abort v6→v11** (2026-05-27/28, 11 trigger): aynı seed tekrar tetik körlüğü → cron cooldown guard gerekli, SLA 2026-06-03.
- **daily-scan-pa-edge-signals-rag-light v1** (2026-05-29 13:00Z): farklı seed, **aynı kök sebep** — payload "RAG ışığında" diyor RAG=0; premise contradiction.
- **bu seed (BTC dominance v1)** (2026-05-29 14:30Z): üçüncü farklı seed, ama **iki yeni körlük türü** ekliyor:
  1. Data universe dışı seed (data engineer'a bağımlı) — guard'lanmamış.
  2. Curve-fit-prone seed (yüksek serbestlik derecesi) — guard'lanmamış.

→ Cron körlüğü 4 tezahür şekli artık gözlendi: (a) aynı seed tekrar, (b) seed payload içsel tutarsız (RAG-iddiası boş), (c) data universe dışı seed, (d) yüksek serbestlik dereceli seed.

## 6. Eskalasyon

### 6.1 CEO directive önerisi (taslak; ayrı doc'ta finalize edilecek)
Cron seed payload'ı kalıcı revize:
- Mevcut "BTC dominance shift triggers" seed'i listeden çıkarılsın **veya** "Data Engineer green-light required" precondition ile gate'lensin.
- Yerine RAG-bağımsız + universe-içi + düşük-serbestlik-dereceli alternatif seed listesi:
  1. Brooks failed-breakout parametric sweep (Donchian-N, confirm-window) — universe içi, prior pozitif.
  2. Brooks crypto transfer çalışması (FX→crypto perp) — universe içi, prior açık soru.
  3. brooks 7fx winner-let-run exit varyantları — universe içi, son turda pozitif edge gözlendi.
  4. Funding rate regime gate (bizim funding cache'imiz varsa) — Data Engineer onayına bağlı.
  5. Brooks 1H küçük-ağırlık diversifier ratio sweep — universe içi.

### 6.2 Ops Engineer guard talebi (mevcut SLA'ye ek)
- Mevcut: cron seed cooldown guard (aynı seed N kez tetiklendiğinde sessiz skip) — SLA 2026-06-03.
- Mevcut: RAG_REQUIRED precondition guard — daily-scan abort doc'unda istendi.
- **Yeni talep**: cron seed payload'ı için 2 ek precondition flag:
  - `UNIVERSE_REQUIRED` (universe'de symbol yoksa skip + Data Engineer'a ticket open).
  - `FREEDOM_DEGREES_MAX` (4+ hyperparam ekseni varsa skip, manuel pre-reg gerekli).

### 6.3 Researcher self-throttle aktif
- Bu seed 24h içinde 2. kez tetiklenirse: doc YAZMA, sadece JSONL satırı (circuit breaker, v7→v8 vsa precedent'i).
- Bu seed Lab corpus refresh sonrası veya Data Engineer ingest sonrası yeniden meşru olursa: yeni doc + `supersedes: <bu doc_id>`.

## 7. Bias Durumu

Yok. "Üretmemek" doğru hamleydi, 4. ardışık vaka (vsa-companion serisi 11 + daily-scan + bu). SOP-5 + persona min-3-ref + universe-dışı + curve-fit-yüzeyi → 4 bağımsız ret nedeni birden tetiklendi.

"Strong opinions, loosely held + Reject more than you accept" — pratiğe dökülmeye devam ediyor.

## 8. ACK / Review

- **requested_review_from**: [ceo, ops_engineer]
  - CEO: 6.1 seed rotation directive için.
  - Ops Engineer: 6.2 UNIVERSE_REQUIRED + FREEDOM_DEGREES_MAX guard talepleri için.
- SLA: 24 saat (PROTOCOL §4).

## 9. Bir Dahaki Sefer

- 4. tetikte (24h içinde) doc YOK, sadece JSONL.
- 7 gün içinde Lab RAG corpus refresh ederse seed yeniden meşru olur — yeni pre-reg doc.
- 7 gün içinde Data Engineer "BTC dominance ingest mümkün, schedule edildi" derse → ticket'i tracker'a al, hipotez ingest tamamlanana kadar PROPOSED beklemede tutulur (DOC YAZILMAZ, sadece ticket).
- ops_engineer guard SLA expire ederse (2026-06-03) CEO directive taslağına bu vakayı da include et.
