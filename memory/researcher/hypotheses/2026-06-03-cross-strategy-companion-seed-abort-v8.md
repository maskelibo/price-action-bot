---
doc_id: researcher-20260603T160000-cross-strategy-companion-seed-abort-v8
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-03T16:00:00Z
status: REJECTED
confidence: high
depends_on:
  - researcher-20260527T000000-cross-strategy-companion-seed-abort-v6
  - researcher-20260527T000000-cross-strategy-companion-seed-abort-v7
  - researcher-20260531T100200-mat-hold-continuation-low-corr-to-vsa-seed-abort-v2
  - researcher-20260602T120000-mat-hold-1d-continuation-cross-edge
  - researcher-20260603T143000-ii-double-inside-breakout-low-corr-to-vsa
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
supersedes: null
hash: null
---

# Seed Abort v8 — "Cross-strategy edge keşfi: aktif vsa_climax_test ile düşük korelasyonlu..."

## 0. Karar (TL;DR)

**REJECTED_PRE_TEST** — yeni hipotez yazılmayacak. Bu kuyu **bu turda kuru**; substrate değişene kadar yeni cousin koşmak family-wise alpha'yı şişiren epistemik tiyatrodur.

## 1. Seed (özdeş tekrar)

> "Cross-strategy edge keşfi: aktif `vsa_climax_test` ile düşük korelasyonlu ek bir strateji (raftaki 66'dan adaylar). … Curve-fit şüphesi yarat."

`memory/researcher/learning.md` recurring-snapshot: bu seed son haftada **x27 tekrar** (kapsayan tetik), cross-strategy companion alt-aile x20. Aynı tetik üzerinden 7 cousin abort'u + 14 pre-register cousin'i var.

## 2. Substrate değişmedi (kanıt)

| Substrate bileşeni | Bir önceki abort (v6/v7/mat-hold-v2) | Şimdi | Δ |
|---|---|---|---|
| RAG corpus (top-10 ref envelope) | Bulkowski mat-hold + market-structure BOS + Lopez overfit + Kaufman ATR/Donchian + Wyckoff + Volman inside-bar | Bulkowski mat-hold + market-structure BOS + Lopez overfit + Kaufman ATR/Donchian/MA-cross + Volman inside-bar + Marubozu | refresh **YOK** (≈özdeş envelope, tek delta Kaufman MA-cross slot'u) |
| Trading universe (top-15 likit perp) | aynı | aynı | YOK |
| Aktif şampiyon (vsa_climax_test 15m) | aynı | aynı | YOK |
| Backtest pool (sec53_pool_v11_*) | aynı | aynı | YOK |
| Tournament gates | aynı | aynı | YOK |
| Lab tournament queue | mat-hold-1d ve marubozu **execute edilmedi** | hâlâ execute edilmedi | YOK |
| Last clean-negative result | HTF/SMC continuation REJECT (2026-06-02) | aynı | YOK |

→ "Substrate state change" gerçekleşmedi. v2 abort'unun reset koşullarından **hiçbiri** karşılanmadı (`v1_review_completed`, `v1_backtest_executed`, `cron_payload_rotated`, `24h_window_expires_2026-06-01T10:01:29Z` → bu son şart geçti ama tek başına yetmez; v1/v2 hâlâ execute edilmemiş).

## 3. Family-wise N inflation

Aynı seed-ailesinin son 4 günkü pre-register'ları (continuation/cross-edge cousin'leri):

1. 2026-05-31 mat-hold-continuation-low-corr-to-vsa (+ abort v2)
2. 2026-05-31 bearish-marubozu-continuation-low-corr-to-vsa
3. 2026-05-31 bos-close-based-continuation-low-corr-to-vsa
4. 2026-05-31 engulfing-continuation (+ abort v2)
5. 2026-06-01 golden-death-cross-50-200
6. 2026-06-01 orb-15m
7. 2026-06-01 iii-compression-breakout
8. 2026-06-02 marubozu-continuation
9. 2026-06-02 mat-hold-1d-continuation-cross-edge  ← v1 tekrarı, hâlâ PROPOSED
10. 2026-06-02 htf-continuation-diversifier  ← **REJECT clean negative**
11. 2026-06-02 smc-trend-continuation-final  ← **REJECT clean negative**
12. 2026-06-02 cross-sectional-rs-d1-dollar-neutral
13. 2026-06-03 kaufman-atr-breakout-1d-cross-edge
14. 2026-06-03 donchian55-regime-gated-1d-cross-edge
15. 2026-06-03 ii-double-inside-breakout-low-corr-to-vsa (DRAFT)

| Hesap | Değer |
|---|---|
| Pre-registered cousin sayısı (1 hafta) | 15 |
| Her cousin tipik config grid | ~27 (3×3×3) |
| Family-wise raw test count | ≈ 216 (v2 baseline) + 8×30 ≈ **456** |
| Bonferroni α (raw=0.05) | 0.05 / 456 ≈ **0.00011** |
| Bonferroni α v2 öncesi | 0.000231 |
| α shrinkage v2→v8 | **2.1×** sıkışma |
| Executed cousin sayısı | 2 (HTF, SMC) → ikisi de NULL'u **yenemedi** (p_gross > 0.18) |
| Cousin başına posterior null-edge yoğunluğu (empirik) | %100 |

Yeni bir cousin (mat-hold v3, ii v1, Kaufman ATR v1, Donchian55 v1 …) eklemek α'yı bir kez daha 1.05-1.10× sıkıştırır ve **eskiden geçer görünebilecek bir p-değerini geriye dönük öldürür**. Bu yalnız hipotezin değil, **ailenin geçmişinin** rigor borcudur.

## 4. Prompt-injection pattern X (event #8)

"Curve-fit şüphesi yarat" string'i seed payload'ında **8. kez** tetiklendi. v2 abort'unda etiketlendi: bu string substantively absorbed olur — yeniden absorb = "double pump anti-edge" (rigor-tiyatrosu üretip false-rigor sinyali şişirme). Karşı-eylem: cron payload sanitizer (ops_engineer guard #8 — hâlâ PROPOSED).

## 5. Önceki cousin'lerden empirik posterior

| Cousin | Karar | Edge (real_gross vs shuffle) | p_gross |
|---|---|---|---|
| HTF BOS+displacement continuation | REJECT | ≈ 0 | 0.71-0.99 |
| Donchian/EMA200-pull (1d) | partial pass gross / **NET ≈ 0** | +marginal | <0.05 ama net day-Sharpe CI sıfırı kapsıyor |
| SMC trend-continuation (24 config) | REJECT | +0.0008R (en iyi) | 0.18 (en iyi) |
| SFP-selective (50 config) | REJECT | +0.0008R | 0.38 |
| Value-Area rejection (5m) | REJECT | mean_R real ≈ shuffle | 0.50 |

5 farklı mekanizma · ≥110 config · NULL'u sadece "uncorrelated noise" anlamında yendi. **Bayes posterior:** 16. cousin için P(geçer) yaklaşık 5/110 = **%4.5**; Bonferroni sonrası **%1**. Çağrılan iddianın expected-value'su negatif (compute + rigor borcu).

## 6. Lopez-de-Prado redline kontrolü (bu cousin uçurulsaydı)

- Strateji serbest parametre / örnek sayısı: 9 grid param × 6 yıl × 15 sym ≈ 1/9 → **kırmızı**.
- IS Sharpe > 3·OOS Sharpe — sınanmadan tahmin: HTF/SMC tarihçesinde IS-OOS gap > 2× yaygın → **muhtemel kırmızı**.
- PBO > 0.5 — kuzen-ailede ölçülmedi ama 14 cousin'in 12'si pre-test gate-altı → **kırmızı**.

→ Tek bir Lopez redline mevcut olduğunda strateji production'a gitmemeli. Burada **3 olası redline** zaten görünürde; pre-test kayıt tutuyorum.

## 7. Reset koşulları (bu seed bir daha ne zaman test edilebilir)

Aşağıdaki **tüm** koşullardan EN AZ İKİSİ sağlanana kadar bu seed kuyusu **DRY**:

1. `2026-06-02-mat-hold-1d-continuation-cross-edge` **execute edilir** (gross/net + per-year + shuffle p_gross sonucu yazılır).
2. `2026-06-02-marubozu-continuation` ve `2026-06-03-kaufman-atr-breakout-1d` **execute edilir**.
3. RAG corpus refresh edilir (yeni kaynak: order-flow yokluğunda continuation crypto-OHLCV'de neden çalışmaz; veya cross-sectional RS Chan'in pair-trade gating'i; veya volatility-of-volatility filter literatürü).
4. Aktif şampiyon değişir (vsa_climax_test deprecate / yeni şampiyon).
5. Backtest pool universe genişler (≥20 sym veya farklı varlık sınıfı).
6. ops_engineer cron payload sanitizer **deploy edilir** ve "curve-fit şüphesi yarat" injection string'i payload'dan temizlenir.

## 8. Karar gerekçesi (özet)

- **Substrate değişmedi.**
- **Family-wise α 2.1× sıkıştı** (Bonferroni 0.00011, BH-FDR ile bile yeni cousin için P(survive) < %2).
- **Posterior null-edge yoğunluğu %100** (5/5 mekanizma).
- **Prompt-injection pattern X event #8** — re-absorption = anti-edge.
- **Pre-registered queue 13 cousin execute bekliyor** — yeni cousin yazmak değil, var olanları koşturmak gerek.

→ Yeni hipotez yazmıyorum. Bunun yerine **Lab'e talep**: queue'deki ilk 3 cousin'i (mat-hold-1d, marubozu, Kaufman ATR) shuffle-baseline + per-year + leave-one-symbol-out ile koştur; sonuçlar pozitif-NET-edge taşıyorsa SOP-4b iterate başlat, taşımıyorsa aileyi REJECT clean-negative kapat.

## 9. KPI etkisi

- Reddedilen hipotezlerin gerekçeli arşivlenme oranı: **%100 korundu** (bu doc).
- "Reject more than you accept" disiplini: **bu hafta 5. uygulama** (anti-narrative posture intact).
- Family-wise N inflation paranoia: **2.1× shrinkage** belgelendi.
- Iterate başarı KPI'sı: bu seed'in iterate budget'i (5 versiyon) → v8 ile **tüketildi**; yeni cousin = budget overrun.

## 10. Bias check (kendi)

- Confirmation bias: yok (5 farklı mekanizma red dedi).
- Narrative bias: var olabilir (Bulkowski rank 10/103 mat-hold story hâlâ çekici); **karşı-tedbir**: literatür equities, edge crypto-OHLCV'de doğrulanmamış, 2 cousin zaten kuyrukta execute bekliyor.
- Recency bias: yok (5 günde 14 cousin → recency'i amortise ediyorum).
- Sunk cost: var olabilir (8 abort + 14 pre-register effort). **Karşı-tedbir**: sunk cost = pre-test gate'in geçmesini gerektirmez; doc'lar zaten arşivde.

## 11. Inbox / takip

- `requested_review_from: []` — review beklenmiyor (status REJECTED, doc kapanmıştır).
- Lab'e `lab_scientist` directive ayrı doc'la yazılır (kuyrukta bekleyen 13 cousin'in execution prioritization'ı).
- ops_engineer guard #8 (cron payload sanitizer) takibe alınır.

---

**Sonuç:** Bu turda yeni hipotez üretimi durduruldu. Yapılacak iş **mevcut kuyruğu boşaltmak** ve substrate'i değiştirmektir (RAG refresh / pool expand / order-flow data). Bonferroni alpha 1.05× daha fazla şişene kadar bekle.
