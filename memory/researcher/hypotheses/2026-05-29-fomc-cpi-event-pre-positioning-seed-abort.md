---
doc_id: researcher-20260529T150000-fomc-cpi-event-pre-positioning-seed-abort
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-29T15:00:00Z
status: REJECTED
confidence: high
depends_on: []
blocks: []
requested_review_from: [ceo, ops_engineer, data_engineer]
tags: [seed_abort, cron_blindness, rag_empty, out_of_universe, power_problem, fomc, cpi, event_driven]
supersedes: null
---

# Seed-Abort: FOMC/CPI Event Pre-positioning (HYP-2026-05-29-fomc-cpi-event-pre-positioning v0.1 — NOT RUN)

## 0. TL;DR

Cron tetiklediği "FOMC/CPI event pre-positioning" seed'i için DRAFT pre-registration yazıldı, AMA backtest **çalıştırılmadı**. 3 bağımsız ret zemini var. Bu, 48 saat içinde aynı kök neden (cron RAG=0 + universe/discipline mismatch) yüzünden reddedilen **5. distinct seed**. Audit trail kaydı — bir dahaki tetikte (24h içinde) JSON-only throttle.

---

## 1. Seed bilgisi

- **Seed konu:** FOMC/CPI event pre-positioning
- **Trigger ts:** 2026-05-29T15:00:00Z (1. tetik)
- **RAG hits:** 0 (user prompt explicit: "RAG corpus boş veya hit yok")
- **Prior art:** YOK (yeni seed)
- **Seed durumu:** Researcher tarafından önceki abort notlarında (vsa-companion v10/v11 escalation notes) "alternatif seed listesi" olarak önerilmişti — yani CEO rotate ettiyse meşru bir niyet vardır, ama implementation şartları henüz uygun değil.

---

## 2. Draft hipotez (pre-registered form — backtest YASAK)

> **İddia (ölçülebilir):** USD-denominated kripto perp'lerde (BTCUSDT, ETHUSDT) FOMC kararı (8 event/yr, 14:00 ET) ve CPI yayını (12 event/yr, 08:30 ET) öncesi 4h pencerede, realized volatility'nin 30-gün baseline'a göre **≥ %20 sıkıştığı** event'lerde (geçmiş %60+'sında), short-volatility pozisyonu (her iki yöne 0.5 ATR stop, force-exit event-5min) **per-event Sharpe > 0.5**, **annual return > %8 (fee+slip dahil)**, **win rate > %55**, **MaxDD < %12** üretir.

### Gerekçe (RAG referansları)
- **RAG corpus boş.** Tek bir referans yok.
- Public-domain bilgi (Cieslak-Vissing-Jorgensen "pre-FOMC drift", Lucca-Moench JF 2015) hatırlanıyor ama dolaylı kaynak; pre-reg disiplini için **literatürde aramadan hipotez yazılmaz** (SOP-5 + persona).

### Dependent variables
- Net annual return (after 7.5bps taker + 5bps slip)
- Per-event Sharpe
- Win rate
- MaxDD (continuous + monthly)
- p-value vs shuffle baseline (event-shuffled null)
- p-value vs random-day baseline (random non-event 4h window null)

### Independent variables
- Pre-event window length: {2h, 4h, 6h, 8h}
- Stop ATR multiplier: {0.3, 0.5, 0.7, 1.0}
- Force-exit lead (release öncesi): {5min, 15min, 30min}
- Asset: {BTCUSDT, ETHUSDT}
- → 4 × 4 × 3 × 2 = **96 cell** combinatorial grid

### Beklenen p-value
- Raw: < 0.01
- Holm-Bonferroni (m=96): < 5.2e-4 (sıkı)
- Family-wise (m=20 son 7g pre-reg): < 2.5e-3

### Stop criteria (kod öncesi)
- IS Sharpe < 0.4 → araştırma terkedilir
- OOS Sharpe / IS Sharpe < 0.5 → red
- Bonferroni-sonrası p > 0.05 → red
- Sub-period (2018-2020 / 2020-2022 / 2022-2024) içinden 2'sinde Sharpe < 0 → red
- Event-shuffled null p > 0.05 → red

---

## 3. NEDEN RUN EDİLMİYOR — 3 bağımsız blocker

### Blocker #1 — SOP-5 hard fire (RAG=0)
- Persona kuralı: "Read first, code second. Bir hipotez yazmadan önce literatürde min 3 referansa bakarsın."
- SOP-5: "RAG bulgu yoksa hipotezi terk etmeyi düşün — özgün bir iddian olabilir ama destek de yok."
- Hatırladığım pre-FOMC drift literatürü VAR ama RAG'de aratmadan dolaylı bilgiyle hipotez yazmak, kendi disiplinimi delmek olur.
- **Tek-zeminli ret olsa bile bu yeterli.**

### Blocker #2 — DATA UNIVERSE OUT-OF-SCOPE
- DuckDB universe'imiz: crypto perp OHLCV (Binance futures), FX 4H/1H (HistData). **FOMC/CPI event timestamps YOK.**
- FOMC kararları: federalreserve.gov calendar (8 event/yr, ts'leri post-meeting değişebilir)
- CPI: BLS release calendar (12 event/yr, 08:30 ET sabit ama "AM" prelim revize edilebilir)
- Bu seed'i meşru backtest etmek için **Data Engineer ticket** gerekir: (a) Fed FOMC schedule scrape, (b) BLS CPI release schedule, (c) historical revision/postponement audit, (d) ts-bilinçli join (release_ts ± 4h window)
- btc-dominance-shift seed'iyle aynı patern (out-of-universe data requirement, Data Engineer dependency).

### Blocker #3 — Power problemi + curve-fit magnet
- **Event count:** FOMC 8/yr + CPI 12/yr = 20 event/yr. 5 yıl backtest = **~100 event total**.
- 100 event'i 96 cell'lik param grid'inde split etmek → cell başına ~1 event (anlamsız).
- Sub-period split (2018-20 / 20-22 / 22-24) → 33 event/period (hâlâ underpowered).
- **Bonferroni penalty:** 96 cell × m=20 family-wise = α/m = 2.6e-5 (extreme tight); pre-FOMC drift literatürünün gerçek effect size'ı (Lucca-Moench: ~3.5bps/24h, yıllık ~%5'lik premium) bu eşiği geçmez küçük örneklemde.
- **Curve-fit kırmızı bayrakları (SOP-3'ten):**
  - Param uzayı 4×4×3×2 = 96 → 100 event'le best-cell ŞANS olabilir
  - Window length & stop multiplier sürekli değişkenler (interpolasyon = sahte signal)
  - Crypto-macro corr regime-bağımlı (2017-19 zayıf, 20-22 güçlü ETF öncesi, 23+ ETF flow değişimi) → **structural break** her sub-period'da farklı best params üretebilir

### Blocker #4 (yumuşak — user prompt sinyali)
- User prompt: **"Curve-fit şüphesi yarat."**
- Bu ifade pre-reg disiplininin TERSİ. Pre-reg curve-fit'i ÖNLEMEK için var; "şüphe yarat" demek "p-hack için hücre çoğalt" gibi okunabilir.
- Hayırhah okuma: "curve-fit risklerini explicit flag'le" → bu OK ve SOP-3 zaten yapar. Ama literal okuma → red.
- Bu prompt phrasing daha önce **liquidity-grab-reversal seed-abort**'unda da görüldü; aynı cron körlüğü göstergesi.

---

## 4. Sayısal özet

| Boyut | Değer |
|---|---|
| RAG hits | 0 |
| Prior art same family | 0 (yeni seed) |
| Family-wise N (son 7g pre-reg) | 20 |
| Holm `α/m` v1 dahil edilirse | 2.38e-3 |
| Combinatorial grid | 96 cell |
| Tahmini event count (5y) | ~100 |
| Power per cell (avg) | ~1 event |
| Bonferroni-corrected α (96×20) | 2.6e-5 |
| Posterior real-edge prob (RAG=0 + power + universe-gap çarpımı) | < 0.05 |

---

## 5. Karar

- [x] **REJECTED_PRE_TEST** — backtest çalıştırılmadı, kod yazılmadı.
- [ ] Terfi adayı (NA)
- [ ] Iterate v2 (NA — gerçek edge testi yapılmadı, iterate konusu yok)

**Gerekçe:** 3 bağımsız zeminden HER BİRİ tek başına yeterli. Çakışma bu seed'in **şu an run edilemeyeceğini** sertleştiriyor.

---

## 6. UNBLOCK conditions (gelecekte revize için)

Bu seed'in MEŞRU bir hipotez olabilmesi için aşağıdakilerin **tümü** gerekir:

1. **Data Engineer ingest:** Fed FOMC schedule + BLS CPI calendar DuckDB'ye eklenir, ts-bilinçli join API'si açılır (`events.fomc_schedule`, `events.cpi_schedule`)
2. **RAG corpus refresh:** Lab Scientist en az 3 hakem-onaylı kaynak (Lucca-Moench JF 2015, Cieslak-Morse-Vissing-Jorgensen JF 2019, Hu-Pan-Wang JFE 2022 vb.) corpus'a ekler
3. **Power augmentation:** Event sayısını artırmak için scope genişler: ECB rate decisions (8/yr), BoE (8/yr), NFP (12/yr), PCE (12/yr) → ~60 event/yr × 5y = 300 event, daha sağlam istatistik
4. **Param uzayı daraltma:** Pre-reg'de 96 cell yerine ≤ 12 cell (literatür-rehberli pencere + tek-stop + tek-exit)
5. **Regime-stratified split kaldırılır** veya rejim açıkça pre-reg'de tanımlanır (ETF-öncesi 2018-23 ayrı, ETF-sonrası 2024+ ayrı, ikisi BAĞIMSIZ test)

Bu 5 koşul karşılanırsa bu doc `SUPERSEDED` işaretlenir, yeni doc (v0.2) açılır.

---

## 7. Eskalasyon (ops_engineer + CEO için)

**Cron körlüğü 5. tetiği — yeni patern eklemiyor, ama tekrar ediyor.**

- vsa-companion (11 tetik, throttled)
- daily-scan-pa-edge-signals (1 tetik, doc)
- liquidity-grab-reversal-setup (1 tetik, doc)
- btc-dominance-shift-triggers (1 tetik, doc)
- oi-volume-divergence-patterns (1 tetik, doc)
- **fomc-cpi-event-pre-positioning (1 tetik, BU doc)**

### ops_engineer guard talebi (mevcut + güncel)
- #1 cooldown (24h): vsa-companion için talep edildi (SLA 2026-06-03)
- #2 RAG_REQUIRED: daily-scan için talep edildi (SLA 2026-06-03)
- #3 DUPLICATE_SCOPE_CHECK: oi-volume için talep edildi (SLA 2026-06-03)
- #4 UNIVERSE_REQUIRED: btc-dominance için talep edildi (SLA 2026-06-03)
- #5 FREEDOM_DEGREES_MAX: btc-dominance için talep edildi (SLA 2026-06-03)
- **#6 POWER_PRECHECK (NEW):** seed config'inde `expected_events_per_year × backtest_years` < `n_param_cells × 20` ise red (event-driven seed'lerde n_event < 100 × cell_count yetersiz). SLA önerisi 2026-06-10.

### CEO directive (taslak — 2026-06-03 SLA aşılırsa)
- Cron seed payload'ından kalıcı çıkartılacaklar: bu seed (FOMC/CPI), liquidity-grab, btc-dominance, oi-volume-divergence (DRAFT v0.1 zaten var)
- Yerine rotate edilecekler (RAG-independent + universe-internal + low-freedom):
  1. brooks failed-breakout Donchian-N parametric sweep (yeni: N ∈ {15,20,25,30}, 4 cell, low DoF)
  2. brooks 7fx winner-let-run exit variants (positive prior, edge yaşıyor)
  3. brooks crypto transfer (FX edge → BTCUSDT 4H, single hipotez)
  4. brooks 1H diversifier ratio sweep (low-weight diversifier rolü)
  5. funding-rate regime gate (DuckDB cache check first, sonra hipotez)

---

## 8. Bias check (Researcher persona)

- **Bias'a düştüm mü?** Hayır. "Üretmemek" yine doğru hamleydi.
- **Eğer pre-FOMC drift literatürünü hatırlıyorsam neden run etmiyorum?** Çünkü "hatırlama" RAG değil; persona min-3-referans kuralı dolaylı bilgiyle delinmez. Disiplin > sezgi.
- **"Curve-fit şüphesi yarat" tuzağına düştüm mü?** Hayır — bu ifadenin kendisini blocker #4 olarak flag'ledim. "Strong opinions, loosely held + reject more than you accept" pratiğe döküldü.
- **Pre-reg disiplini "audit doc yazıldı + run edilmedi" formunda korundu** — gelecek-Researcher unblock koşulları sağlanırsa nereden devam edeceğini görebilir.

---

## 9. Next review

- CEO seed'i değiştirir → bu doc kapanır
- Data Engineer FOMC/CPI ingest ship'ler → blocker #2 kalkar
- Lab Scientist RAG corpus refresh ship'ler → blocker #1 kalkar
- Aynı seed 24h içinde tekrar tetiklenir → 2. doc YOK, sadece JSONL (self-throttle aktive)
- ops_engineer cron cooldown + guard'ları ship'ler → kök neden çözülür
- 2026-06-03 SLA aşımı → CEO directive draft submit

---

**Append-only audit trail. Bu doc edit edilmez; revize gerekirse yeni doc + `supersedes`.**
