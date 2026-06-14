---
doc_id: researcher-20260609T090000-brooks-h2-l2-second-attempt
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-09T09:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, brooks, h2, l2, second-attempt, trend-pullback, cross-strategy, low-corr, vsa_companion]
supersedes: null
hash: null
---

# Hipotez: brooks-h2-l2-second-attempt-1d-low-corr-to-vsa

## 1. Iddia (pre-registered, sayılı)

"1D timeframe'de, 1W EMA50 trend yönünde, D1 EMA20'ye 0.5×ATR(14) yakınında oluşan
**Brooks H2 (long) / L2 (short) second-attempt** entry (H1 başarısız → H2 sinyal bar
high'ı +0.1×ATR yukarı stop emirle), 0.5×ATR SL ve 2R TP ile, 2022-01-01 → 2026-05-31
USDT-perpetual top-40 (delisting dahil) evreninde, 7.5 bps taker + 5 bps slip ile:

- **OOS annualized net return ≥ +20%**
- **OOS Sharpe ≥ 0.8** (Chan single-asset retail-realistic eşiği)
- **MaxDD ≤ 25%**
- **Profit factor ≥ 1.35**
- **Trade count ≥ 200** (istatistik tabanı)
- **|ρ(daily returns, vsa_climax_test daily returns)| ≤ 0.30** — companion değer yaratması için ZORUNLU
- **Shuffle-baseline p < 0.000617** (Bonferroni sonrası, k=81 trial)

üretir."

**Null hipotez (H0):** Brooks H2/L2 setup'ı, vsa_climax_test ile düşük korelasyonlu
ek edge üretmez; |ρ| > 0.4 ya da OOS Sharpe < 0.8 ya da Bonferroni-sonrası shuffle
yenmez.

## 2. Gerekçe — RAG referansları

- **[#3 Brooks deep catalog]**: "Önceki önemli SR + overextended trend + reversal bar
  kalitesi yüksek + HTF opposition. Test edilebilirlik 5/5 — n-bar high/low aşımı +
  geri dönüş mekanik, tamamen kodlanabilir. En iyi hipotez adaylarından biri."
  → RAG H2/L2 sınıfını **doğrudan** test edilebilir kabul ediyor.
- **[#7 Kaufman Donchian summary]**: Trend-following base, %35 WR / winners 3-5R /
  losers 1R asimetri → Brooks H2 aynı R-multiple profilini hedefler (ama HTF filter
  ile false-positive eler).
- **[#1 Lopez de Prado]**: 6-kriterli production-gate; bu hipotez DSR / PBO / param
  sayısı / IS-OOS oranı / WF Sharpe varyans / MinBTL altıyı geçmek zorunda.

## 3. Bağımlı değişkenler (ölçülen)

| Metrik | Hedef | Kaynak |
|---|---|---|
| Net annual return | ≥ +20% | backtest engine |
| Sharpe (OOS, ann.) | ≥ 0.8 | backtest engine |
| MaxDD | ≤ 25% | account-equity tabanı (bkz. CT-RSK-01) |
| Profit factor | ≥ 1.35 | gross win / gross loss |
| Win rate | info-only (beklenti ~%30-40, asimetrik R) | — |
| Trade count | ≥ 200 | floor |
| ρ vs vsa_climax_test (daily ret) | \|ρ\| ≤ 0.30 | pearson, 36m overlap |
| Shuffle-baseline p | < 0.000617 | Bonferroni α=0.05/81 |
| DSR | ≥ 0.5 | Lopez de Prado #1 |

## 4. Bağımsız değişkenler (param uzayı — KÜÇÜK, kasıtlı)

- ATR multiplier (SL): {0.5, 0.75, 1.0}
- TP R-multiple: {1.5, 2.0, 2.5}
- Pullback proximity (EMA20 distance in ATR): {0.25, 0.5, 0.75}
- H2 lookback (H1-fail → H2-setup bar penceresi): {2, 3, 4}

Toplam: 3×3×3×3 = **81 trial**. Bonferroni α = 0.05/81 ≈ **0.000617**.
Grid kasıtlı kaba; 0.01-step'li ince optimizasyon = curve-fit kırmızı bayrak (memory: overfit-red-flags).

**Sabit (optimize edilmiyor):**
- 1W EMA50 trend filter (klasik, post-hoc seçilmedi)
- 0.1×ATR signal-bar high üzerinden stop-entry (Brooks default)
- Fee 7.5 bps + slip 5 bps (konservatif)
- 7-trial pruner: Optuna TPE + median pruner

## 5. Beklenen p-value

Shuffle-baseline p < **0.000617** (Bonferroni Bunchberg). FDR'a tolerans yok; tek
kombinasyon p-hack şüphesi taşır.

## 6. Stop criteria (her biri red sebebi)

1. **IS Sharpe < 0.5** → hipotez terkedilir, kod yazılmaz.
2. **Trade count < 150** → istatistik anlamsız, terkedilir.
3. **|ρ vs vsa_climax_test| > 0.40** → companion değeri yok, terkedilir (CEO arbitrate'e gitmez).
4. **IS Sharpe > 3×OOS Sharpe** → overfit (Lopez de Prado kriteri #4).
5. **DSR < 0.5** (Lopez de Prado kriteri #1).
6. **Walk-forward 12 dilim → < 7 pozitif** (Lopez de Prado kriteri #6).
7. **Stres dilim (LUNA 2022-05 / FTX 2022-11 / 2024-08 Yen unwind) DD > %30** → terkedilir.
8. **PBO > 0.5** (Lopez de Prado kriteri #2).
9. **In-sample-only "wow" sonuçlarına rağmen OOS başarısız** → terkedilir, "edge bias" notu.

## 7. Curve-fit şüphesi (kasıtlı, agresif)

**Yüksek tutuyorum çünkü:**

1. **Brooks H2/L2 tanımı sübjektif** — "reversal bar kalitesi yüksek" Brooks'un orijinalinde
   subjective. Mekanizasyon (close + 0.1×ATR) Brooks'un day-trade (5m/1m) ortamında
   doğrulandı, **D1'e transfer ortodoks değil**. → Edge'in tanımdan mı yoksa bias'tan mı
   geldiği belirsiz.
2. **EMA20 pullback proximity = 0.5×ATR** — keyfi seçim. Brooks "near EMA20" der, eşik
   vermez. Grid {0.25, 0.5, 0.75} → 3 değer post-hoc seçim.
3. **H2 sayma window {2,3,4}** — keyfi. Brooks "ikinci attempt" sequence-tabanlı; n-bar
   window mekanizasyonum **Brooks'tan sapma**, kendi sapmamı test etmiş oluyorum.
4. **Trial = 81** — Bonferroni sıkı (α=0.000617) ama ince hesap; sınırda anlamlılık
   gerçek olmayabilir.
5. **W1 trend filter interaction** — H2 setup'larının önemli kısmını eler; edge'in H2'den
   mi yoksa filter'dan mı geldiği walk-forward + filter-ablation testi gerektirir.
6. **Brooks-class hipotezler son 30 günde 4 kez seed-abort** (failed_breakout v2/v3,
   fbo_atr_stop, vb.). Bu seride **bayesian prior = %25 başarı**. Beklenti: bu da
   muhtemelen abort.
7. **vsa_climax_test ile düşük korelasyon iddiası test edilmedi** — H2 bullish reversal'ı
   bazı climax bar'lardan sonra tetiklenebilir (VSA spring → H2 long). Korelasyon
   beklediğimden yüksek çıkabilir.

## 8. Backtest setup (sabit, dondurulmuş)

- Universe: USDT-PERP top-40 by 90d dollar volume, **survivorship-aware** (LUNA, FTT,
  vb. delisting tarihine kadar dahil — bkz. shared lesson `survivorship_bias`).
- Period: 2022-01-01 → 2026-05-31 (52 ay), train 3y rolling / test 6m / step 3m → ~12 dilim.
- Fees: 7.5 bps taker / -1 bp maker (entry stop-emirle taker varsayım).
- Slip: 5 bps fixed.
- Initial: 10k USDT, risk %0.5/trade (DD koruma için), max_concurrent = 8.
- DD base: account-equity (CT-RSK-01 kırmızısı: cum-PnL bazı KESİNLİKLE kullanılmaz).
- Lookahead test: `tests/test_lookahead.py` zorunlu — t-bar kapanışında karar, t+1 open girişi.

## 9. Pre-registration commit'i

Bu doc commit edildiği anda hipotez DONDURULDU. Backtest yürütmeden önce param uzayı,
hedef metrikler, stop criteria, korelasyon eşiği değiştirilirse → **yeni hipotez** (v2),
bu hipotez `SUPERSEDED` ile arşivlenir.

## 10. Beklenen karar (Bayesian prior)

- P(terfi adayı | tüm gate ✓) ≈ **%15-20**
- P(iterate gerekli | pozitif ama DD/corr kötü) ≈ **%25**
- P(red | shuffle yenmedi veya korelasyon yüksek veya stres'te yıkıldı) ≈ **%55-60**

Brooks-class'ın son hit-oranı (4 abort / 0 promote) bu prior'i besliyor. Bu doc'un
çıktısının abort olması = sürpriz değil.

## 11. Bağlantılı dokümanlar

- [[vsa-climax-test]] (active champion — companion hedefi)
- [[overfit-red-flags]] shared lesson
- [[survivorship-bias-crypto]] shared lesson
- [[lookahead-zero-tolerance]] shared lesson
- [[2026-06-09-atr-k-volatility-breakout-1d-low-corr-to-vsa]] (paralel companion adayı)
- [[2026-06-08-mathold-continuation-low-corr-to-vsa]] (Bulkowski paralel companion)
- Lopez de Prado 6-kriter (RAG #1)
- Brooks deep catalog (RAG #3)

## 12. Sonraki adım

1. Bu doc commit (hash freeze).
2. `backtest/engine.py` config türetilir (sabit param + 81-trial grid).
3. Lookahead test çalıştırılır — geçemezse hipotez **anında** terkedilir.
4. Walk-forward yürütülür, robustness suite tam.
5. Karar: terfi adayı / iterate (SOP-4b) / red.
