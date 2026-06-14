---
doc_id: researcher-20260604T100000-engulfing-continuation-confluence-threshold-sweep
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-04T10:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, engulfing_continuation, confluence_score, threshold_sweep, curve_fit_risk, multiple_testing]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-04-engulfing-continuation-confluence-threshold-sweep

## 0. Curve-Fit Pre-Warning (kritik)

> **Bu hipotezin kendi yapısı multiple-testing tuzağı.** Confluence-score threshold sweep'i `θ ∈ {0.40, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90}` 10 noktada yapılırsa, **rasgele bir threshold ailesinde dahi p ≈ 0.05 düzeyinde 1 false positive bekleniyor** (10 × 0.05 = 0.5 beklenen yanlış pozitif). Bu yüzden:
>
> - Her sonuç **BH-FDR q<0.05** ile düzeltilecek.
> - Threshold ailesi **önceden donmuş 10 nokta** — adaptif eşik aranmayacak, "best" raporlanmayacak.
> - Aile içindeki **monotonluk testi** zorunlu: confluence_score yükseldikçe mean_R **monoton artmalı**. Eğer "tek bir nokta sivri" ise (örn. θ=0.65'te +0.05R ama 0.60 ve 0.70'te ≤0) **otomatik kill** — sivri tepe = curve-fit imzası.
> - Geçmiş ders (V12 entry-quality, 2026-06-02): `confluence_score` HARDCODED 2.0 idi → varyans sıfır → kaldıraç ölü. Bu sweep'i koşturmadan önce **confluence_score üretici fonksiyonun gerçekten varyans verdiğini** doğrula; vermiyorsa hipotez kod-öncesi kapanır.

## 1. İddia (Pre-Registered, ölçülebilir)

> **Iddia:** 1h timeframe'de, 1d EMA50 üzerinde (htf_1d_aligned=True), trend yönüne (close > EMA20 + son 20 bar HH/HL dizisi) uyumlu **bullish engulfing continuation** sinyali, Brooks-skoru ailesinden türetilmiş `confluence_score ∈ [0, 1]` filtresi `θ ≥ 0.65` ile koşulurken, 2021-01-01..2026-05-31 dönemi, 15 sembol (BTC, ETH, BNB, SOL, ADA, AVAX, MATIC, LINK, DOT, UNI, ATOM, XRP, DOGE, LTC, NEAR) USDT-perpetual evreninde:
>
> - Entry: t+1 open (close-based decision @ t).
> - Stop: 1.5 × ATR(14) altı.
> - TP: 2.0R (fixed multiple).
> - Fee: 7.5 bps taker round-trip × 2 = 15 bps; slippage 5 bps.
> - **Aşağıdaki rakamların TÜMÜ aynı anda tutturulmalı:**
>   - GROSS (0 bps) **mean_R > 0.030** ve **shuffle-baseline p_gross < 0.05** (direction-shuffle null).
>   - NET (55 bps round-trip) **mean_R > 0.020** ve **BH-FDR q < 0.05** (10-nokta aile içinde).
>   - **Annualized day-Sharpe (NET) > 0.6** ve bootstrap 95% CI **alt sınırı > 0**.
>   - **Monotonluk:** θ=0.50 → 0.65 → 0.80 üçlüsünde NET mean_R **kesin monoton artmalı** (Δ ≥ 0.005R her adımda).
>   - **Per-yıl pozitiflik:** 2021..2026 yıllarının **en az 5'inde** mean_R > 0.
>   - **Leave-one-symbol-out:** 15 sembolün her birini tek tek dışarıda bırakırken **min NET Sharpe > 0.3**.

## 2. Null Hipotez (ne olursa çürür)

H₀: `confluence_score` filtresi engulfing_continuation üzerinde **bilgi taşımıyor** — yani threshold'u yükseltmek sadece örneklem küçültür, gross mean_R değişmez veya rasgele dalgalanır (monoton değil).

H₀ doğrulandığının kanıtları (ihtimaller, çoklu olabilir):
- Tüm 10 threshold'ta direction-shuffle p_gross ≥ 0.05 (yön bilgisi yok).
- Monotonluk testi: 10 thresholdda mean_R sıralaması Spearman ρ < 0.5.
- BH-FDR sonrası q < 0.05 olan threshold sayısı = 0.
- Geçmiş ders tekrarı: confluence_score varyansı (std) < 0.05 → lever ölü.

## 3. Gerekçe (RAG referansları)

- **[Brooks 2012 ch.18 — "A/B/C grading"]** Brooks setup_type × htf_alignment × signal_bar_quality × confluence_count komponentlerinden ağırlıklı toplam üretir; thresholds A=0.85, B=0.65, C<0.65 → size_multiplier {1.0, 0.5, 0.0}. Bizim θ ailesi (0.40..0.90) **Brooks'un kendi raporladığı 0.65 break-point'ini** içerir — yani sweep, Brooks'un literatür-eşiğini empirik olarak sınamaktadır.
- **[Grimes 2012 / blog 2018 — "Engulfing"]** Engulfing standalone WR ~%50, R≈1.0 → **net edge sıfıra yakın, fee sonrası negatif olabilir**. "Engulfing + reference bar size + trend continuation" WR ~%58-62 — yani trend-confluence olmadan engulfing'in tek başına edge'i **yoktur**. Bizim hipotez bu literatürle uyumlu: confluence filtresi olmadan beklenti = 0.
- **[Bulkowski — "Bullish 3-bar engulfing + confirmation"]** Bullish reversal rate %68, average move %5.7, rank 14/103. Confirmation bar şartı (Bar 3 close > Bar 2 close) bizim continuation tanımımıza yakın; ancak Bulkowski daily, biz 1h test ediyoruz → **timeframe-transferability riski** var.
- **[SMC topluluk claims, book_smc_ict_summary]** "Confluence 3+ → 60-70% WR" iddiaları **out-of-sample test edilmemiş, survivorship-bias kontrolsüz** → bizim test bu iddiayı **falsification testine** sokuyor.
- **[Daily Price Action — "pin bar confluence"]** "Patience to wait for high-confluence setups is the primary edge" — pattern-perfeksiyon değil context taşıyıcı edge → confluence_score'un yön taşımasını test etmek tam bu iddianın empirik karşılığı.

**Anti-gerekçe (ihtiyat):** Geçen ay (2026-06-02) "smc-trend-continuation-final-smc-test" ve "v12-entry-quality-vsa-widestop" testleri **continuation kalıplarının kripto 1h/4h bar-OHLCV'de net edge üretmediğini** kanıtladı. Bu hipotez aynı patikayı dener — başarısız olması beklenebilir, bu yüzden eşik 1h (saatlik) ve sembol seti farklı (15 sembol) seçildi ki "negative coverage" bilgi katsın.

## 4. Bağımlı Değişkenler (dependent vars)

| Metric | Hedef | Notlar |
|---|---|---|
| mean_R (gross, 0bps) | > 0.030 | direction-shuffle null'a göre p_gross < 0.05 |
| mean_R (net, 55bps) | > 0.020 | BH-FDR q < 0.05 |
| Annualized day-Sharpe (net) | > 0.6 | bootstrap 1000-iter, CI alt sınırı > 0 |
| Profit factor (net) | > 1.20 | tek başına yeterli değil — kanıt-zinciri |
| MaxDD (sabit-fraksiyon %0.5/trade) | < 25% | leverage_per_symbol = 3, risk_pct=0.005 |
| Trade sayısı | > 200 | her threshold'ta; aksi halde istatistik anlamsız |
| Per-yıl pozitif yıl sayısı | ≥ 5/6 | 2021..2026 |
| Leave-one-symbol-out min Sharpe | > 0.3 | tek sembol bağımlılığı yok |
| Spearman(θ, mean_R) | > 0.5 | monotonluk |
| Confluence_score std | > 0.10 | lever varyansı (lever-ölü kontrolü) |

## 5. Bağımsız Değişkenler (independent vars — DONDURULMUŞ)

- **Threshold ailesi (DONDURULMUŞ, sweep ekseni):** `θ ∈ {0.40, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90}` — 10 nokta, başka eşik aranmayacak.
- **Engulfing tanımı (DONDURULMUŞ):**
  - Bar(t-1): bearish (close < open), |body| ≥ 0.3 × ATR(14).
  - Bar(t): bullish (close > open), Bar(t) gövdesi Bar(t-1) gövdesini kapsar (open_t ≤ close_{t-1} ve close_t ≥ open_{t-1}).
  - Continuation şartı: HTF trend up (1d close > EMA50_1d) AND son 20 bar HH/HL dizisi.
- **Confluence score komponentleri (Brooks ağırlık, DONDURULMUŞ):**
  - htf_alignment: trend_match=1.0 / neutral=0.5 / counter=0.0 (ağırlık 0.30)
  - signal_bar_quality: bar_body/ATR > 0.6 → 1.0; 0.3..0.6 → 0.6; <0.3 → 0.3 (ağırlık 0.25)
  - context: after_pullback_in_trend (EMA20 reclaim) → 1.0 / mid_range → 0.4 (ağırlık 0.20)
  - confluence_count (S/R, EMA20, EMA50, swing low): 3+ → 1.0 / 2 → 0.7 / 1 → 0.4 (ağırlık 0.15)
  - vol_z (vol/SMA20(vol)) > 1.0 → 1.0 / 0.6..1.0 → 0.6 / <0.6 → 0.3 (ağırlık 0.10)
  - **Toplam ∈ [0, 1]; std hedef > 0.10 (lever-ölü kontrolü).**
- **Universe:** 15 sembol, listing-date'i 2021-01-01 öncesi olanlar; delisting yok (kripto evreni stabil bu set için).
- **Timeframe:** 1h primary; htf_alignment için 1d.
- **Dönem:** 2021-01-01..2026-05-31; train 2021-2024, OOS 2025-01-01..2026-05-31 (17 ay).

## 6. Beklenen p-value ve Düzeltme

- **Raw p-target:** Her threshold için p_gross (direction-shuffle, 1000 iter) < 0.01.
- **Multiple testing:** 10-threshold ailesi → **BH-FDR q < 0.05**. Bonferroni eşdeğeri α/10 = 0.005, conservative tarafta. **Raporlanan "best threshold" tek başına anlamsız** — aile genelinde monotonluk + BH-FDR survivor sayısı raporlanır.
- **Beklenti (kişisel prior):** Geçmiş engulfing/continuation testleri (en az 4 negatif) ışığında, **hipotezin reddedilme ihtimali %70-80**. Buna rağmen test ediliyor çünkü:
  - confluence-monoton kanıtı **negatif coverage** olarak bile değerli.
  - V12 entry-quality'de `confluence_score` HARDCODED idi — gerçek varyanslı bir test bizde **hiç** yapılmadı.

## 7. Stop Criteria (kod-öncesi)

Hipotezi koşmadan ÖNCE iptal kriterleri:
- **C1 (lever-ölü kontrolü):** confluence_score üretici fonksiyonu 1000 örnek sinyalde std < 0.05 verirse → hipotez kapanır, kod yazılmaz. (V12 dersi tekrar etmesin.)
- **C2 (data sufficiency):** En düşük threshold'ta (θ=0.40) trade sayısı < 1000 ise universe yetersiz; sweep iptal.

Hipotezi koştuktan sonra abort kriterleri:
- **A1 (no-edge):** Tüm 10 threshold'ta p_gross ≥ 0.05 → red. (Yön bilgisi yok, fee düzelmesi yararsız.)
- **A2 (sivri tepe / curve-fit imzası):** Yalnızca 1 threshold q<0.05, komşuları 2× q düzeyinde → red. Monoton değil = curve-fit.
- **A3 (regime-luck):** Spearman(θ, mean_R) > 0.5 ama per-yıl 3+ yıl negatifse → red.
- **A4 (single-symbol carry):** Leave-one-symbol-out'ta tek bir sembol çıktığında Sharpe > 0.3 → 0 oluyorsa → red.
- **A5 (IS/OOS divergence):** IS mean_R / OOS mean_R > 2.0 → overfit, red.

Hipotez terfi adayı olmak için (3-yol: terfi / iterate / red):
- **TERFİ ADAYI:** Tüm gate'ler ✓ + monotonluk ✓ + leave-one-symbol-out ✓ → Lab tournament.
- **İTERATE (SOP-4b):** Aylık ROI > 0 ama MaxDD > 25% veya tek bir sembol/yıl dominasyonu → v2 (risk_pct 0.005→0.002 veya symbol-subset).
- **RED:** A1-A5'ten herhangi biri → gerekçeli arşiv `learning.md`'ye 3 satır.

## 8. Reproducibility

- git_hash: (run sırasında doldurulacak)
- data_hash: `data/market.duckdb`'nin SHA256 (run sırasında)
- config_hash: bu doc'un SHA256 (committed)
- shuffle seed: 42 (default), bootstrap için 1000 farklı seed

## 9. Tahmini Compute

- 15 sembol × 5y × 1h = ~657k bar
- 10 threshold × 1000 shuffle × forward-fill simulation ≈ 10M kez vectorized signal check
- Tahmini wall-clock: ~20-30 dakika (vectorized, no for-loop)

## 10. Karar Çerçevesi (post-run)

```
1. C1/C2 stop'ları geçti mi? → hayırsa iptal, sebep logla.
2. Her threshold için: gross mean_R, p_gross, NET mean_R, BH-FDR q.
3. Monotonluk tablosu (Spearman + 3-nokta delta testi).
4. Per-yıl + leave-one-symbol-out tabloları.
5. IS/OOS Sharpe oranı.
6. Karar: TERFI / ITERATE / RED.
7. Gerekçeli arşiv (her 3 yol için zorunlu).
```

## 11. Notlar (Adversary için)

`adversary_engineer`'a critique için ön sorular:
- **Q1:** htf_alignment 1d trend filtresi survivorship-bias'lı mı? (2021 öncesi delisted olmuş 15 sembol var mı? — Hayır, evrenim 2021-stable; doğrula.)
- **Q2:** Engulfing detector'da `body_t >= |open_{t-1}, close_{t-1}|` mi `body_t >= |body_{t-1}|` mi? Spec'i sıkılaştır.
- **Q3:** Vol_z (vol/SMA20) komponenti gelecek bilgisi sızdırıyor mu? — Hayır, SMA20 t'de close-based, ama paranoid ol: causality test zorunlu.
- **Q4:** Threshold ailesi `0.40..0.90` çok geniş mi? Tek bir aralık (`0.55..0.75` 5-nokta) daha az aile-error verir ama Brooks 0.65 break-point literatür anchorlu, koruyoruz.

---

**Bu hipotez REDDEDILMEYE HAZIR.** Beklentim: 10 threshold'tan 1-2'si raw p_gross < 0.05 verir, BH-FDR sonrası 0-1 hayatta kalır, monotonluk testi başarısız olur, hipotez ARCHIVE → `learning.md`'ye "confluence_score 1h engulfing-continuation'da yön taşımıyor" notu.

Eğer aksi olursa (monoton + BH-FDR q<0.05 ≥3 threshold + per-yıl 5+ + leave-one-symbol-out OK) — **bu, V12'den beri konfluans-skoruna inandığımız ilk gerçek kanıt olur** ve Lab tournament'a tam hızla gider. Skeptisizmi koruyorum.
