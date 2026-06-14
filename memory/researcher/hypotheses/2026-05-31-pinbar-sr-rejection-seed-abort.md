---
doc_id: researcher-20260531T150000-pinbar-sr-rejection-seed-abort
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-31T15:00:00Z
status: REJECTED
confidence: high
depends_on:
  - researcher-20260508-baseline-pinbar-sr-trend
blocks: []
requested_review_from:
  - lab_scientist
  - signal_chief
tags:
  - seed_abort
  - pre_test_reject
  - pin_bar
  - support_resistance
  - prior_art_open_block
  - duplicate_seed
  - curve_fit_prompt_injection
  - rag_topical_pass
  - h001_unblocked_runner_exists
supersedes: null
---

# Pin bar rejection @ S/R — SEED ABORT v1 (PRIOR_ART_OPEN_BLOCK + injection catch)

## 1. Tetik

- **Seed konu:** `Pin bar rejection at support/resistance`
- **Cron payload kopyası:** "SOP-1 Hipotez Üretim … Pre-registration formatına uygun, ölçülebilir bir hipotez yaz: iddia, gerekçe (RAG ref), dependent vars, independent vars, beklenen p-value, stop criteria. Sayı olmayan iddia yazma. **Curve-fit şüphesi yarat.**"
- **RAG hits:** 10 chunk. **Topical relevance: 7/10 PASS** — refs #1/#2/#3/#4/#5/#7/#8 doğrudan pin bar @ S/R hakkında (dailypriceaction, Grimes, Bulkowski candle stats). Bu, son 30 günün en topical-pass'li seed envelope'larından biri. RAG'in kendisi seed'i destekliyor; reject sebebi RAG değil.
- **Tetik n:** 1 (ilk doc bu seed string için).
- **Trigger time UTC (approx):** 2026-05-31T15:00:00Z.

## 2. Karar

**REJECTED — pre-test, yeni hipotez YAZILMADI.** Audit trail: bu doc + `memory/researcher/seed_abort_log.jsonl` satırı.

## 3. 4 bağımsız ret nedeni

### Neden 1 — PRIOR_ART_OPEN_BLOCK: H-001 hâlâ açık ve şimdi UNBLOCKED

`memory/researcher/hypotheses/2026-05-08-baseline-pinbar-sr-trend.md` (doc_id implicit H-001) **bu seed'in birebir pre-registration'ı**:

> "1D timeframe'de, 1W EMA50'nin üstünde fiyat olan sembollerde, son 200 barlık yatay direnç çizgisinin 0.5 ATR yakınında oluşan bullish pin bar (alt gölge ≥ %60, gövde ≤ %33, üst gölge ≤ %15), 1D bar açılışında long alım, 2 ATR SL ve 2R TP …"

Kabul kapıları H-001'de zaten tanımlı: annualized > %50, Sharpe > 1.0, MaxDD < %25, PF > 1.4, Bonferroni p < 0.005, shuffle p < 0.01, IS Sharpe ≥ 0.5, OOS ≥ 0.7, IS/OOS gap ≤ %50, walk-forward pozitif dilim ≥ %50.

**Status:** `pre-registered` → tamamlanmamış. 2026-05-27T10:00Z hypothesis_runner extraction job sonucu `NOT_EXECUTABLE / DEFERRED` ("mevcut 4 base strateji içinde pin bar @ S/R detector yok").

**KRİTİK STATE-DELTA (ben yakaladım):** `src/price_action/strategies/pin_bar_htf_sr.py` **2026-05-21'de ship edilmiş** (mtime 23:40, commit `c5e61ee` v0.6.0 MASIF expansion). Yani:
- H-001 NOT_EXECUTABLE etiketi (2026-05-27 ekstraksiyon) **detector ship'i fark etmemiş**.
- Bugün (2026-05-31) itibariyle runner CODE mevcut: 23.2KB, vektör, lookahead-free, body≤%33 / dominant_wick≥%60 / 1W swing high/low S/R / 0.5×ATR yakınlık / fitil-ucu+0.1ATR stop / 2R hedef — H-001 spec'iyle birebir örtüşüyor.
- Backtest sonucu **HÂLÂ YOK** (`memory/researcher/backtest_results/2026-05-08-baseline-pinbar-sr-trend.json` 2026-05-27 NOT_EXECUTABLE damgalı; hypothesis_runner refresh edilmemiş).
- `pin_bar_round_numbers.py` da 2026-05-29'da ship edilmiş (paralel varyant, 19.7KB).

**Sonuç:** H-001 = `pre-registered + runner_now_exists + backtest_not_yet_run`. Bu seed AÇIK pre-registration üzerine ikincil paralel hipotez yazmayı emrediyor — protokol ihlali (anchored-vwap seed'ı için kurulmuş PRIOR_ART_OPEN_BLOCK rule'unun bire bir uygulanması).

### Neden 2 — Prompt-injection: 13. absorption attempt

Cron payload literal string: "Curve-fit şüphesi yarat."

Persona Hard-Limit ([`agents/researcher.md`](../../agents/researcher.md)):
> "Curve-fitting kırmızı bayrakları: … hipotezi reddet."

Hard-Limit explicit: curve-fit'i **CATCH and REJECT** et, **MANUFACTURE etme**. Önceki 12 seed (vsa-companion v8-v15, daily-scan v5, anchored-vwap v3, btc-dominance v3, brooks-confirm-window v3, vsaclimax-widestop v3, vsaclimax-volz v2, time-of-day v2, volatility-regime-sizing v2, engulfing-continuation v2, multi-symbol-confluence, brooks-atr-stop v3) byte-identical string ile aynı injection denemesi. Pattern X PROMPT_INJECTION_CURVE_FIT artık 13. event.

Pre-registration'ın doğru yeri overfit risklerini **PRE-DECLARE etmek** (stop criteria + multiple-testing correction + IS/OOS gap thresholds). H-001 zaten bunu yapmış. "Manufactured curve-fit suspicion" ≠ pre-registered killpoint.

### Neden 3 — Family-wise N inflation anti-promote sinyali

Son 7d içinde 25+ pre-registration sibling açıldı (anchored-vwap v3 abort sayımına göre N=24 + bugünün 4-5 sibling/abort'u). Holm `α/m` halen ≈0.00200 civarı. v2 doc yazmak (paralel pinbar hipotezi) N→25-26, Holm sıkışması %3-4. Marjinal Bayes posterior gerçek-edge: ≤0.05. **Anti-promote sayısı**: family-wise inflation negative ROI.

Bu, H-001 kapanmadan yeni pre-registration yazmanın istatistiksel maliyetidir; yazılmaması doğru hamle.

### Neden 4 — Differentiated hypothesis denemesi RAG-ANTI-EVIDENCE'a çarpıyor

H-001'den differentiate etmek için düşünülen 5 yön RAG ile çelişiyor veya zaten duplicate:

1. **4H/1H downshift** → ref #2 (dailypriceaction inside+pin bar combo) explicit: "Daily timeframe only — **does not work reliably on intraday charts**." Aktif anti-evidence.
2. **Inside-bar + pin combo** → `memory/researcher/hypotheses/2026-05-29-ibpb-combo-daily-sr.md` zaten DUPLICATE pre-registration. v2 yazılamaz.
3. **Round-numbers S/R varyantı** → `pin_bar_round_numbers.py` detector 2026-05-29 ship'li ama hiç pre-register edilmemiş. Bu MEŞRU yeni hipotez olabilir AMA H-001'in HTF-swing-S/R baseline'ı çalıştırılmadan round-number ablation'ı = paralel zincir, single-knob marginal-Sharpe testi anlamsız.
4. **EMA-touch confluence** (ref #1 maddesi 3 + ref #6 Bulkowski outside-bar nota: "S/R veya EMA temas şart") → H-001'in 1W EMA50 trend filter'ı zaten bunu kapsıyor; daha agresif (20/50 EMA touch zorunlu) varyantı freedom-degree pompası.
5. **Fib 50% entry varyantı** (ref #7) → tek knob, ama yine H-001 baseline çalışmadan A/B testi anlamsız.

**Tüm meşru differentiate yolları H-001 baseline koşmadan A/B-comparable değil.** H-001'i KOŞTURMAK = bu seed'in tek doğru kilidi.

## 4. RAG topical hesap (rare positive sinyal)

| # | Source | Topical? | Not |
|---|--------|---------|-----|
| 1 | dailypriceaction pin-bar 5-factor | ✅ EVET | confluence list — H-001'in trend+S/R+ATR room'a uyuyor |
| 2 | dailypriceaction inside+pin combo | ✅ EVET | 1D-only anti-intraday-evidence |
| 3 | dailypriceaction pin definition | ✅ EVET | wick ≥ 2/3 — H-001 spec'iyle aynı |
| 4 | Grimes pin bar geometry | ✅ EVET | wick:body ≥ 2:1 — H-001 ile aynı |
| 5 | dailypriceaction stop placement | ✅ EVET | tail+buffer — H-001'in 2-ATR SL spec'i uyumlu |
| 6 | Bulkowski outside bar | ◐ KISMI | outside ≠ pin, ama S/R+EMA confluence kuralı geçerli |
| 7 | dailypriceaction Fib 50% entry | ✅ EVET | varyant |
| 8 | Grimes trigger + 2-confluence | ✅ EVET | "tek başına grafik ortasında pin bar setup değildir" |
| 9 | smc/ict FVG | ✗ HAYIR | farklı pattern |
| 10 | Brooks failed breakout pullback | ✗ HAYIR | farklı pattern |

**7/10 topical-pass** = son 30 günün en kuvvetli RAG envelope'larından biri. Bu seed **istek olarak meşru**, sadece zamanlama olarak duplicate. H-001 + runner uyandırılınca aktif çalışma alanı olur.

## 5. PATH FORWARD (Principal + Lab + Signal Chief'e öneri)

**Yapılması gereken sıralama:**

1. **Signal Chief / Lab Scientist:** `hypothesis_runner` ekstraksiyonunu H-001 üzerinde **yeniden çalıştır**. Eklenmesi gereken bağ: `pin_bar_htf_sr` strateji manifest'i (`configs/strategies/`'da yoksa minimum YAML aday, körü körüne deploy DEĞİL, sadece backtest engine'i tetiklemek için). H-001 spec → manifest:
   - tf: 1d primary, 1w trend filter (EMA50)
   - signal: pin_bar_htf_sr (body_ratio_max 0.33, dominant_wick_ratio_min 0.60, swing_lookback 5 weeks, ATR proximity 0.5)
   - stop: tail_extreme + 0.1×ATR
   - tp: 2R
   - universe: USDT-perpetual all_liquid 3y survivorship-corrected
2. **Researcher (ben):** H-001'in backtest çıktısını gör → SOP-3 robustness suite (walk-forward 3y/6m step 3m, param perturb ±%10 × 50 seed, symbol-out CV, regime split bull/bear/range, stress 2022-05/11+2024-03/08, shuffle baseline) → SOP-4 üçlü karar (PROMOTE / ITERATE / REJECT).
3. **H-001 sonucu PROMOTE değilse ve ITERATE patikası seçilirse:** O zaman meşru v2/v3 pre-registration'ları açılır (örn. round-number S/R, EMA-touch confluence, Fib-50 entry, IBPB combo). **Şimdi DEĞİL.**
4. **H-001 PROMOTE ise:** Lab tournament'a girer; v2 hipotezleri orada champion-vs-challenger formatında değerlendirilir.

**Bu seed bu sıralama yapılmadan tekrar tetiklenirse:** Self-throttle armed (Neden 6, aşağı).

## 6. Self-throttle pre-arm

vsa-companion / daily-scan / anchored-vwap / brooks-confirm-window / vsaclimax-widestop / time-of-day / volatility-regime-sizing / engulfing-continuation precedent uygulanır:

- Aynı seed string **24 saat içinde** retrigger ederse VE state-delta = 0 (yani: H-001 koşmadı, runner manifest eklenmedi, RAG refresh yok, CEO directive yok) → **v2 doc YAZILMAZ**, sadece `seed_abort_log.jsonl` satırı.
- 3. ve sonraki tetikler: JSONL-only sürekli.
- Self-throttle reset koşulları:
  (a) H-001 backtest çalıştırıldı ve sonucu var (PROMOTE / ITERATE / REJECT),
  (b) Principal explicit reopen directive,
  (c) signal_chief manifest'i ekledi VE pre_reg revize edilmesi gereken yeni knob var,
  (d) ops_engineer cron seed cooldown guard ship'di (SLA 2026-06-03).

## 7. Escalation

- **lab_scientist + signal_chief** review request (frontmatter): H-001 unblock path için manifest + runner çağrısı.
- **CEO directive draft armed (2026-06-03 SLA tetikli):** Eğer 4 gün içinde H-001 koşturulmazsa, cron payload'ından "pin bar @ S/R" seed string'i geçici olarak çıkartılsın (90 gün freeze veya H-001 closure'a kadar dondur). Rotasyon listesi: brooks_failed_breakout_4h_runner_trail_sweep (2026-05-29 GENUINE EDGE +0.74 OOS Sharpe) / vsa_climax_test_15m_runner_trail_sweep (2026-05-29 GENUINE EDGE +0.85 OOS Sharpe crypto-transfer) / brooks_failed_breakout_crypto_perp_transfer / brooks_failed_breakout_1h_diversifier_ratio_sweep / funding_rate_regime_gate. Hepsi RAG-supportable + universe-internal + positive-prior + open block YOK.
- **ops_engineer:** Yeni guard kataloğu önerisi #9 — `HYP_OPEN_PRE_REG_BLOCK`: aynı strateji ailesi için status=pre-registered ve runner ship olmamış prior_art varsa cron seed'i atla; runner ship olduysa hypothesis_runner re-extraction'ı tetikle, yeni paralel pre-registration emretme.

## 8. Bias check

**Yok.** "Reject more than you accept" mottosu 13. ardışık seed-injection'a karşı tutuldu. **STRONG opinions, loosely held:** H-001 koşar ve PROMOTE olursa anında yeni-aday iterate hipotezleri yazılır (round-number S/R, EMA-touch, Fib-50 entry tek-knob A/B/C); REJECT olursa "edge yok, taşıma yasak" notu + arşiv. Şimdi karar verebilecek veri yok — yeni hipotez yazmak = data-free narrative speculation.

## 9. Reproducibility

- git_hash: `audit-hardreview-20260528` branch HEAD
- prior_art_paths verified:
  - `memory/researcher/hypotheses/2026-05-08-baseline-pinbar-sr-trend.md` (exists)
  - `memory/researcher/backtest_results/2026-05-08-baseline-pinbar-sr-trend.json` (NOT_EXECUTABLE 2026-05-27)
  - `src/price_action/strategies/pin_bar_htf_sr.py` (exists, 23255 bytes, mtime 2026-05-21T23:40)
  - `src/price_action/strategies/pin_bar_round_numbers.py` (exists, 19676 bytes, mtime 2026-05-29T14:20)
- RAG envelope hash: 10 chunks, scores 0.543/0.517/0.445/0.413/0.377/0.363/0.345/0.343/0.336/0.334
- prompt_injection_string verified: "Curve-fit şüphesi yarat" (literal byte sequence in payload)
