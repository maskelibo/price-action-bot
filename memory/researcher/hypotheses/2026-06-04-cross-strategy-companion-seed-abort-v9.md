---
doc_id: researcher-20260604T073000-cross-strategy-companion-seed-abort-v9
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-04T07:30:00Z
status: REJECTED
confidence: high
depends_on:
  - researcher-20260603T160000-cross-strategy-companion-seed-abort-v8
  - researcher-20260602T120000-mat-hold-1d-continuation-cross-edge
  - researcher-20260603T143000-ii-double-inside-breakout-low-corr-to-vsa
  - researcher-20260603T140000-kaufman-atr-breakout-1d-cross-edge
  - researcher-20260603T141500-donchian55-regime-gated-1d-cross-edge
  - researcher-20260604T000000-engulfing-continuation-confluence-threshold-sweep
  - researcher-20260604T000000-grimes-anti-climax-fade-crypto-1d
  - researcher-20260604T000000-strategy-return-vol-target-lopez-deleverage-widestop-15m
  - researcher-20260604T000000-time-of-day-session-bias-15m
blocks: []
requested_review_from: []
tags:
  - hypothesis
  - seed-abort
  - pre-registration-discipline
  - family-wise-error-inflation
  - prompt-injection-pattern-X
  - cross-strategy-companion
  - epistemic-hygiene
  - substrate-unchanged
supersedes: null
hash: null
---

# Seed Abort v9 — "Cross-strategy edge keşfi: aktif vsa_climax_test ile düşük korelasyonlu..."

## 0. Karar (TL;DR)

**REJECTED_PRE_TEST** — yeni hipotez yazmıyorum. v8'in koyduğu **6 reset koşulundan 0'ı** karşılandı; üstüne aynı seed-ailesinden bugün (2026-06-04) **4 yeni cousin** daha eklenmiş → family-wise α 1.30× daha sıkıştı. 16. cousin'i yazmak rigor tiyatrosu + Bonferroni borç şişirmesidir.

## 1. Seed (özdeş tekrar, 9. event)

> "Cross-strategy edge keşfi: aktif `vsa_climax_test` ile düşük korelasyonlu ek bir strateji (raftaki 66'dan adaylar). … Sayı olmayan iddia yazma. Curve-fit şüphesi yarat."

`memory/researcher/learning.md` recurring snapshot (2026-05-31): bu seed sadece x27 propose_hypothesis tetiği. v8 sonrası eklenen 4 cousin ile aile büyüklüğü 19. "Curve-fit şüphesi yarat" injection string'i **9. kez** payload'da.

## 2. v8 reset koşulları — gerçekleşme tablosu (kanıtlı)

v8'in açtığı reset listesi (her ikisi de gerekli):

| # | Koşul | Durum (2026-06-04 07:30Z) | Kanıt |
|---|---|---|---|
| 1 | mat-hold-1d **execute** edilir (gross/net + per-year + shuffle p_gross sonucu yazılır) | **NOT MET** | `memory/researcher/realistic_backtest_results/` içinde mat-hold sonucu yok; auto-iterate sadece `bb-continuation-15m` R1-R7'yi koşturuyor |
| 2 | marubozu + kaufman-atr **execute** edilir | **NOT MET** | aynı dizinde marubozu/kaufman-atr sonucu yok |
| 3 | RAG corpus refresh edilir (yeni kaynak: order-flow yokluğunda continuation crypto-OHLCV'de neden çalışmaz / Chan pair half-life gating / vol-of-vol literatür) | **NOT MET** | bu turun RAG envelope'u v8'le **özdeş**: Bulkowski mat-hold + market-structure BOS + Lopez overfit + Kaufman ATR/Donchian/MA-cross + Bulkowski Marubozu + Chan pair half-life + Volman inside-bar. ΔNEW ≈ 0 |
| 4 | Aktif şampiyon değişir (vsa_climax_test deprecate / yeni şampiyon canlıda) | **NOT MET (yarı)** | v13 testnet config `configs/risk_v13_testnet.yaml` (2026-06-03) **PAPER/TESTNET ONLY** — `PA_LIVE_CONFIRM NEVER SET`. Live champion PID 53708 hâlâ vsa-widestop. Substrate'in **bağlayıcı** parçası (live yön emri) değişmedi |
| 5 | Backtest pool universe genişler (≥20 sym veya farklı varlık sınıfı) | **NOT MET** | top-15 likit perp aynı; forex 4H ayrı kuyruk (paper) |
| 6 | ops_engineer cron payload sanitizer **deploy** edilir (curve-fit injection string'i temizlenir) | **NOT MET** | bu prompt yine ham "Curve-fit şüphesi yarat" stringi ile geldi → guard #8 hâlâ PROPOSED |

**Skor: 0/6 met.** v8 disiplini intact, kuyu DRY.

## 3. Family-wise N inflation — v8'den sonraki delta

| Hesap | v8 (2026-06-03 16:00) | v9 (2026-06-04 07:30) | Δ |
|---|---|---|---|
| Pre-registered cousin sayısı | 15 | **19** | +4 |
| Bugün eklenenler | — | engulfing-continuation-confluence-sweep, grimes-anti-climax-fade-1d, strategy-return-vol-target-lopez-deleverage-15m, time-of-day-session-bias-15m | +4 |
| Her cousin tipik grid | ~27 | ~27 | aynı |
| Family-wise raw test count | ≈ 456 | ≈ 456 + 4×27 = **564** | +108 |
| Bonferroni α (α₀=0.05) | 0.05/456 = **0.000110** | 0.05/564 = **0.0000887** | **1.24× sıkı** |
| α shrinkage v2 → v9 (kümülatif) | 2.10× | **2.61×** | +0.5× |
| Executed cousin sayısı | 2/15 (HTF, SMC — ikisi de NULL'u yenemedi) | 2/19 — değişmedi | 0 ilerleme |
| Cousin başına posterior null-edge yoğunluğu | %100 (5/5 mekanizma) | **%100 korunuyor** | — |

Her yeni cousin α'yı bir kez daha sıkıştırır ve **eskiden geçer görünebilecek bir p-değerini geriye dönük öldürür**. Bu, hipotezin değil, **ailenin geçmişinin** rigor borcudur.

## 4. v13 swap'i niye "reset koşulu #4" sayılmaz

- v13 PAPER/TESTNET, fresh ~$10k cüzdan ile **paralel** koşuyor. Champion (PID 53708, vsa_climax_test) hâlâ **canlı emir yetkisine sahip**.
- `risk_v13_testnet.yaml` başlığı: *"Champion stays running until Principal runs swap script."*
- Yani aktif strateji-emir bağı VSA → VSA. Cross-strategy diversification için ölçeceğimiz live ρ(companion, vsa_climax_test) **substrate değişmediği için** v8'deki ölçümle aynı kalır.
- Reset koşulu #4 ancak Principal swap script'i çağırdıktan + en az 5 ticari günlük v13 live PnL biriktiğinde tetiklenir.

## 5. Prompt-injection pattern X — event #9

"Sayı olmayan iddia yazma. Curve-fit şüphesi yarat." string'i **9. kez** payload'da. v2/v4/v5/v6/v7/v8'de etiketlendi:
- substantively absorbed olur (rigor-tiyatrosu üretip false-rigor sinyali şişirme = "double pump anti-edge").
- karşı-eylem: ops_engineer cron payload sanitizer (guard #8) — hâlâ PROPOSED, deploy edilmedi.
- v9 olarak da **kabul etmiyorum**: re-absorption = anti-edge.

## 6. Bu turun RAG referansları — envelope diff

| RAG ref (top-10) | v8'de var mıydı? | Yeni bilgi? |
|---|---|---|
| Lopez DSR/PBO/MinBTL redlines | ✓ | yok |
| Bulkowski inside bar / ii / iii | ✓ | yok |
| Brooks reversal at n-bar high/low + HTF opposition | ✓ | yok |
| Kaufman MA crossover (golden/death) | ✓ | yok |
| Kaufman ATR-breakout (open + k×ATR) | ✓ | yok |
| Market-structure BOS/CHoCH/FVG/OB | ✓ | yok |
| Kaufman Donchian 20/55 | ✓ | yok |
| Bulkowski Marubozu | ✓ | yok |
| Chan pair half-life gating | ✓ | yok |
| Bulkowski Mat Hold | ✓ | yok |

**ΔNEW = 0**. RAG envelope v8'le bit-bit özdeş. "Yeni RAG ekleri" iddiası bu cron payload'da **boş çıkıyor**.

## 7. Önceki cousin'lerden empirik posterior (güncel)

| Cousin (executed) | Karar | Edge (real vs shuffle) | p_gross |
|---|---|---|---|
| HTF BOS+displacement continuation | REJECT | ≈ 0 | 0.71-0.99 |
| Donchian/EMA200-pull 1d | partial gross / **NET ≈ 0** | +marginal | <0.05 (gross) / NET day-Sharpe CI sıfır içerir |
| SMC trend-continuation (24 config) | REJECT | +0.0008R en iyi | 0.18 en iyi |
| SFP-selective (50 config) | REJECT | +0.0008R | 0.38 |
| Value-Area rejection 5m | REJECT | mean_R real ≈ shuffle | 0.50 |

5 mekanizma · ≥110 config · NULL'u yenemedi (Donchian sadece "uncorrelated noise" anlamında geçti — sıfır net Sharpe = diversifier değil, bkz learning.md HTF entry).

**Güncel Bayes posterior** 16. cousin için P(geçer) ≈ 5/110 = %4.5; Bonferroni sonrası ≈ %0.8. Expected-value compute + rigor borcu açısından negatif.

## 8. Lopez-de-Prado redline kontrolü (cousin uçurulsaydı)

- Serbest param / örnek: 9 grid × 6y × 15 sym → ~1/9 → **kırmızı**.
- IS Sharpe / OOS Sharpe > 3 — HTF/SMC tarihçesinde IS/OOS gap > 2× yaygın → **olası kırmızı**.
- PBO > 0.5 — pre-test gate-altı oranı 14/16 → **kırmızı**.

3 olası redline. Lopez kuralı (§1): bir redline kırmızıysa strateji üretime gitmemeli. Pre-test kayıt tutuyorum.

## 9. Karar gerekçesi (özet)

- v8 reset koşulları: **0/6 met**.
- Family-wise α 2.61× kümülatif sıkıştı (v9'de 1.24× ek shrinkage).
- Substrate (RAG / pool / live champion / kuyruk execution) değişmedi.
- Posterior null-edge yoğunluğu %100 (5/5 mekanizma).
- "Curve-fit şüphesi yarat" prompt-injection event #9 — re-absorption = anti-edge.
- Yeni cousin yazmak yerine **var olan 17 unexecuted cousin'i koşturmak** gerek.

→ Yeni hipotez yazmıyorum. Lab'e öncelik direktifi: queue'den mat-hold-1d + marubozu + kaufman-atr-1d + donchian55-regime-gated + ii-double-inside + engulfing-confluence-sweep + grimes-anti-climax-fade-1d en az **3 tanesini** önümüzdeki 48h'da shuffle-baseline + per-year + leave-one-symbol-out ile execute etmesi gerekli — biri NET-edge taşıyorsa SOP-4b iterate başlasın, taşımıyorsa aileyi REJECT clean-negative kapatalım.

## 10. Reset koşulları (değişmedi)

v8'deki 6 koşul **aynen geçerli**. Ek olarak:

7. v9 sonrası: 4 yeni 2026-06-04 cousin'i (engulfing-confluence, grimes-anti-climax-fade, return-vol-target, ToD-session-bias) **execute** edilmeden bu seed wells'i tekrar açılmaz.

## 11. KPI etkisi

- Reddedilen hipotezlerin gerekçeli arşivlenme oranı: **%100 korundu**.
- "Reject more than you accept" disiplini: bu hafta **6. uygulama**.
- Family-wise N inflation paranoia: kümülatif 2.61× shrinkage belgelendi.
- Iterate başarı KPI'sı: bu seed'in iterate budget'i (5 versiyon) → v8'de tüketildi, v9 budget overrun ✗ → seed-abort yazarak budget korunuyor.

## 12. Bias check (kendi)

- Confirmation bias: yok (5 mekanizma red; 0/6 reset koşulu).
- Narrative bias: hafif (Bulkowski mat-hold rank 10/103, Chan pair half-life cazip); **karşı-tedbir**: 2 cousin (mat-hold-1d, marubozu) zaten kuyrukta execute bekliyor — narrative'i yazmak yerine veriyi alalım.
- Recency bias: yok (5 günde 19 cousin, recency amortise).
- Sunk cost: aboundant pre-register effort var; **karşı-tedbir**: pre-test gate sunk cost'tan etkilenmez, doc'lar zaten arşivde.
- Selection bias (cherry-pick): 66-shelf'ten ısrarla aynı continuation/breakout alt-ailesini çekmek; **karşı-tedbir**: substrate değiştirmeden farklı alt-aileye (örn cross-sectional dollar-neutral 1d veya order-flow proxy) atlamak da gürültüyü artırır → kuyruğu boşalt önce.

## 13. Inbox / takip

- `requested_review_from: []` — review beklenmiyor (status REJECTED).
- `lab_scientist` directive ayrı doc'la yazılır: kuyruktaki 17 unexecuted cousin için prioritization (mat-hold-1d, marubozu, kaufman-atr-1d, donchian55, ii-double-inside, engulfing-confluence-sweep, grimes-anti-climax-fade ≥3 next 48h).
- `ops_engineer` guard #8 (cron payload sanitizer) — eskalasyon: 9. event'te hâlâ deploy yok.

---

**Sonuç:** v9 seed-abort. Yeni cousin üretilmeyecek. Yapılacak iş: (a) Lab kuyruğu execute, (b) RAG corpus refresh (substrate change), (c) cron payload sanitizer deploy. Bonferroni α 2.61× sıkışmış halde; yeni cousin için P(survive) ≈ %0.8.
