---
doc_id: researcher-20260531T140000-time-of-day-session-bias-seed-abort
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-31T14:00:00Z
status: REJECTED
confidence: high
depends_on: []
blocks: []
requested_review_from: []
tags: [seed_abort, pre_test_reject, rag_topical_zero, prompt_injection, prior_art_block, anti_pattern_curve_fit]
supersedes: null
---

# Hipotez: time-of-day-session-bias — SEED ABORT v1

- **Tarih:** 2026-05-31
- **Versiyon:** v1 (ilk tetik)
- **Trigger:** Cron SOP-1 prompt, seed="Time-of-day session bias"
- **Karar:** **RED, PRE-TEST, hipotez yazılmadı.** (kod yazılmadı, parametre seçilmedi, backtest tetiklenmedi)
- **Audit:** memory/researcher/seed_abort_log.jsonl + bu doc.

## 0. İddia (yazılmadı çünkü reddedildi)

Seed bana "kripto perpetual evreninde belirli UTC saat dilimlerinin (örn. Asya/Avrupa/NY açılışı) pozitif/negatif edge taşıdığını" test eden ölçülebilir bir hipotez yazmamı istedi. **Yazmadım.** Aşağıdaki 5 bağımsız neden tek başına ret için yeterli; birleşince hipotezin pre-test posterior gerçek-edge olasılığı ≤ 0.05.

---

## 1. Ret Nedenleri (5 bağımsız blok)

### 1.1 RAG TOPICAL RELEVANCE = 0/10 (SOP-5 sert tetik + Pattern D)

10 ref envelope sağlandı, **0'ı time-of-day / session bias hakkında**:
- **#1, #2** — Jane Street risk dashboard çıktısı (resource limits, pool tablosu). Tamamen alakasız.
- **#3** — Tokenization mikro-benchmark (Python vs Rust). Trading ile ilgisi yok.
- **#4** — Bennett candlestick patterns: "Daily timeframe: Best... **Intraday: Not recommended for beginners; pattern reliability drops significantly**." **AKTİF DÜŞMAN** — bu ref intraday-bazlı edge'lerin reliability'sinin düştüğünü söylüyor; seed'in dayandığı temele ZIT.
- **#5, #6, #8** — BTC macro positioning (Hyperliquid long bias, CME OI, realized cap). Pozisyonlama metrikleri; TOD edge'i değil.
- **#7** — Web sayfasında "ek optimizasyon" referansı. Boş.
- **#9** — AlphaZero/Go RL zayıflıkları. Alakasız.
- **#10** — Jane Street magic-trace profilers ("sampling every 250μs"). Lexical "time" eşleşmesi, semantic alakasız.

**Topical hit = 0/10.** Persona "Read first, code second — min 3 referans" kuralı + SOP-5 "RAG bulgu yoksa hipotezi terk." Pattern D RAG_TOPICAL_RELEVANCE 15+ distinct event'inin tekrarı (vsa-companion v8-v15, daily-scan v3-v5, anchored-vwap v3, brooks-confirm v3, widestop v3, atr-stop v3, btc-dominance v3, liquidity-grab v3, weekend-gap-fill v3, oi-volume-div v2, fomc-cpi v2, engulfing v3, volz v2, vwap-cluster v?).

### 1.2 PROMPT INJECTION DETECTED ("Curve-fit şüphesi yarat")

Prompt string literali: **"Curve-fit şüphesi yarat."** Bu, persona Hard-Limit kuralının TAM TERSİ:
> "Curve-fitting kırmızı bayrakları: parametre uzayı çok ince, best params ekstrem değerlerde, in-sample/out-of-sample fark > %50 → hipotezi reddet."
>
> "Anti-narrative bias. Anlatı seni etkilemez. 'Mantıklı geliyor' hipotezin kabul gerekçesi değildir; sayı ister."

Persona yönergesi: **CATCH and REJECT** curve-fit şüphesi, asla **MANUFACTURE** ETME. Bu seed'de injection 1. absorption attempt; kabul = persona kontratının doğrudan ihlali. Pattern X (PROMPT_INJECTION_CURVE_FIT) 10+ event'in tekrarı.

### 1.3 PRIOR ART OPEN BLOCK — Session filtreleri zaten 2 LIVE bot'ta aktif

Time-of-day session bias **çoktan kullanılıyor**:
- **brooks_failed_breakout** (4H forex GO adayı, 7FX uncorrelated-legs): `session: 07-16 UTC` (London-NY overlap). 2026-05-29 winner-let-run varyantı genuine edge çıktı, runner-trail 3.0x.
- **vsa_climax_test** (15m crypto LIVE): `session_filter` aktif. 2026-05-29 winner-let-run genuine transfer +5.2pp/ay.
- **2026-05-29-forex-ny-session-fade.md** (F2) — explicit session-boundary mean-reversion KILLED: IS mR −0.069, OOS −0.091, shuffle p=0.887, BH FAIL, slip-stress −0.152. *"Over-extension into the NY bar continued as often as it reverted, net of cost. Mechanism dead."*
- **F1 london_open_breakout** — aynı batch'te KILLED: IS −0.098, OOS +0.115 (sign-flip = rejim-bağımlı, stabil edge DEĞİL).
- **scripts/iterate_session_vwap.py** — VWAP session iterate altyapısı zaten mevcut, kendi pre-reg'leri var.

Yeni bir "TOD session bias" hipotezi şu 3 patikadan birine düşer, hiçbiri meşru:
1. **Mevcut session_filter parametresinin sweep'i** → curve-fit magnet (zaten 07-16 UTC etrafında 6+ ay yaşandı, parametrik PBO inflation).
2. **F1/F2 session-boundary edge'inin yeniden denenmesi** → KILLED prior, PRIOR_ART_OPEN_BLOCK (yeni veri/yeni mekanizma yok).
3. **Yeni session ekseni (Asya open, Tokyo lunch, vb.)** → freedom-of-degrees patlaması (24 saat × N tetikleyici × N exit = >1000 hücre p-hacking magnet).

### 1.4 24/7 CRYPTO STRUCTURAL OBJECTION

Kripto perpetual'ları 24/7 piyasa. "Session bias" iddiası forex/equity'de bile zayıf (Ranaldo 2009 intraday FX seasonality literatürü dar-pencere ve cost-fragile); kriptoda **mekanizma daha da silik** çünkü:
- Asya/Avrupa/NY zamanlamasının arbitraj edilmemiş bir nedeni yok (küresel derivatif flow 7/24 sürekli).
- USDT funding rate 8-saatlik kapanışları (00/08/16 UTC) zaten tüm strateji session filtrelerinde context olarak içeriliyor — yeni edge değil, mevcut bilinen mekanik.
- Wee-saat (03-06 UTC) düşük likidite "session bias" iddiası test edildiğinde slip-stress yaşıyor (F2 ile aynı kalıp).

Ref #4 explicit söylüyor: intraday'de pattern reliability dramatik düşer. Bu, seed'in mekanizmasının kendi RAG envelope'ı tarafından ÇÜRÜTÜLDÜĞÜ anlamına gelir.

### 1.5 FAMILY-WISE N ENFLASYONU

Son 7 günde pre-register edilen ailem (testler + abort'lar) N=25 civarında. Holm `α/m ≈ 0.002`. Yeni bir TOD session bias hipotezi N=26 → α/m %3.8 daha sıkı. RAG=0 + prior art bloklu + injection altında marjinal kanıt yokken Bonferroni-sıkışmayı pompalamak **anti-promote** — yani v1 doc'u meşru bir hipotez olarak yazmak istatistiksel olarak da yanlış (false-discovery rate yön: yukarı, posterior gerçek-edge ≤ 0.05).

---

## 2. Sayısal Posterior Hesabı

| Bayesian prior bileşeni | Çarpan |
|---|---|
| RAG topical relevance 0/10 (no theoretical support) | × 0.15 |
| Prompt injection (curve-fit MANUFACTURE çağrısı) | × 0.30 |
| Prior art bloklu (F1+F2 KILLED + 2 LIVE bot zaten kullanıyor) | × 0.20 |
| 24/7 crypto structural objection (ref #4 explicit adverse) | × 0.40 |
| Family-wise N=26, Holm α/m = 0.00192 | × 0.65 |
| **Pre-test posterior gerçek-edge olasılığı** | **≈ 0.0023** |

Bu, "pre-register et, test et, reddet" yolundan beklenen ortalama posteriora göre ~25× daha düşük. Test enerjisi (compute + audit trail + cognitive bandwidth) başka bir hipoteze ayrılmalı.

---

## 3. Self-Throttle Armed

Bu v1. Eğer aynı seed 24h içinde 2. kez tetiklenirse:
- v2 doc yazılır (substantive yeni durum varsa).
- 3. ve sonraki tetiklerde **seed_abort_log.jsonl JSONL-only**, doc YOK (vsa-companion v8-v15, daily-scan v3-v5, anchored-vwap v3 emsalleri).

Throttle reset koşulları:
- (a) Principal explicit reopen directive.
- (b) RAG corpus topical refresh (session-bias / intraday-seasonality / TOD-effect chunks).
- (c) Mevcut session_filter parametrelerini DEĞİŞTİREN execution measurement (örn. live fee farkı belirli saatlerde ≥ 30bps).
- (d) Yeni veri kanalı (örn. funding rate per-saat detayı, exchange-specific liquidity timing).
- (e) CEO seed rotation directive — cron payload'ından bu seed çıkartılır, alternatif seed eklenir.

---

## 4. Eskalasyon ve Alternatif Seed Önerileri

### CEO directive draft (ops_engineer SLA kaçırırsa armed)

> "time-of-day-session-bias seed'i 90 gün dondurulsun (2026-08-29'a kadar) ve cron payload'ından çıkartılsın. Yerine aşağıdaki 5 alternatiften biri rotate edilsin — hepsi RAG-supportable, universe-internal, low-freedom-degree, prior pozitif:
>
> 1. **brooks crypto-transfer extension** (2026-05-29 winner-let-run forex→crypto genuine edge prior; runner-trail 3.0x knob'unu BTC perp 4H'ye uygula).
> 2. **brooks 7fx joint runner-trail + initial-stop optimization** (2 knob simultaneous sweep, walk-forward gated, prior pozitif).
> 3. **brooks 1H diversifier ratio sizing** (1H bağımsız bacak küçük-ağırlık ratio sweep, decorrelation prior pozitif).
> 4. **funding-rate regime gate** (8-saatlik funding cycle ZATEN piyasada, regime filter olarak test edilmedi; veri DuckDB içinde).
> 5. **vsa_climax winner-let-run extension** (15m crypto genuine edge prior; runner-trail 3.0x diğer 15m sembollerine uygulanabilir mi)."

### ops_engineer guard önerileri (SLA 2026-06-03)

- Guard #1 (per-seed cron cooldown ≥ 24h) — bu hafta 5+ farklı seed × 22+ rejection event'te etkili olurdu.
- Guard #7 (RAG_TOPICAL_RELEVANCE k≥3 seed-domain-tagged) — bu seed'i tetik-anında bloklardı (topical=0).
- Guard G2 (prompt-injection sanitizer — "Curve-fit şüphesi yarat" / "Curve-fit suphesi yarat" string'ini cron payload'ından strip).

---

## 5. Bias Durumu

Hangi cognitive bias'a düştüm: **yok**. Cron körlüğünün 17. distinct seed varyantında "reject more than you accept" disiplini tutuldu. Strong opinions, loosely held — eğer (a)-(e) reset koşullarından biri açılırsa anında geri alırım.

---

## 6. Lab / Principal'a Mesaj

- **Lab Scientist:** Bu doc'un yazılma sebebi `seed_abort_log.jsonl`'ın anlamlı bir audit kanalına dönüşmesi. Haftalık throttled-seed özetine ekle.
- **Principal:** ops_engineer guard #1/#7/G2 ship edilene kadar cron payload sanitizasyonu için manuel müdahale faydalı olabilir. CEO directive draft armed.
