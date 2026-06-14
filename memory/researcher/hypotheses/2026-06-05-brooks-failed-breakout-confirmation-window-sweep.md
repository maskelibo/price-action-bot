---
doc_id: researcher-20260605T130000-brooks-failed-breakout-confirmation-window-sweep
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-05T13:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, brooks_failed_breakout, confirmation_window, parameter_sweep, curve_fit_risk, multiple_testing, forex_4h, crypto_15m_robustness]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-05-brooks-failed-breakout-confirmation-window-sweep

## 0. Curve-Fit Pre-Warning (kritik)

> **Confirmation-window parametre sweep'i, single en yaygın p-hack imzasıdır.** "Kaç bar bekleyince trap kanıtlanır?" sorusuna 8-12 farklı cevap denersen, **rastgele bir parametrede dahi p≈0.05 düzeyinde 1 false positive bekleniyor** (8×0.05=0.4 beklenen yanlış pozitif). Bu yüzden:
>
> - Aile **önceden donmuş 8 nokta**: `cw ∈ {1, 2, 3, 4, 5, 6, 8, 10}`. Başka eşik aranmayacak, "best cw raporlanmayacak."
> - Sonuçlar **BH-FDR q<0.05** ile düzeltilir.
> - **Monotonluk veya tek-tepe testi zorunlu**: confirmation-window mantığı eğer gerçekse, *çok küçük cw* (1-2 bar) noise'dan zarar görmeli, *çok büyük cw* (8-10 bar) gecikmeden zarar görmeli → **iç-bükey tepe** bekleniyor (örn. cw=3-5 max). Eğer "tek bir nokta sivri ama komşuları çok zayıf" ise (Δ > 2× komşu) → otomatik kill.
> - **Brooks'un edebi tanımında konfirmasyon "1-2 bar" der**; eğer empirik tepe cw=7 çıkarsa **literatür-discordant survivor = curve-fit imzası**, ekstra adversarial bootstrap zorunlu.
> - Geçmiş ders (2026-06-02 SMC iter-2, 2026-06-04 engulfing-confluence sweep): parametre sweep'lerinin **%80'i shuffle-baseline'ı geçemedi**, bu hipotezin de aynı kaderi taşıması default beklentidir.

## 1. İddia (Pre-Registered, ölçülebilir)

> **Iddia:** Forex 4h timeframe'de (HistData), EUR/USD + GBP/USD + USD/JPY 3-sembol evreninde, 2018-01-01..2026-05-31 dönemi, Brooks failed-breakout (FBR) pattern'i şu mekanikle uygulanır:
>
> 1. **Range tanımı:** Son N=20 bar içinde en az 2 swing-high (range_top) ve 2 swing-low (range_bot) yakın seviyede (her ikisi de ±0.5×ATR(14) içinde benzer), |range| ≥ 1.0×ATR(14).
> 2. **Breakout tetiği:** Bar(t) close > range_top + 0.1×ATR (bullish BO) VEYA close < range_bot − 0.1×ATR (bearish BO).
> 3. **Confirmation window (SWEEP EKSENİ):** Bar(t+1..t+cw) içinde **herhangi bir bar** close'u range_top'un altına (range_bot'un üstüne, bear için) **kapatırsa** → FBR onayı (trap).
> 4. **Entry:** Onaylanan barın close'unda **ters yönde** (bullish BO → short, bearish BO → long).
> 5. **Stop:** Range_top + 1×ATR (long için range_bot − 1×ATR).
> 6. **TP:** 2.0R fixed.
> 7. **Fee:** 4h forex → broker simulation = 1.5 pip round-trip avg ≈ 2 bps; slippage 1 pip ≈ 1.5 bps. Total ~3.5 bps round-trip.
>
> **Aşağıdaki rakamların TÜMÜ aynı anda tutturulmalı (her cw için):**
>   - GROSS (0 bps) **mean_R > 0.040** ve **shuffle-baseline p_gross < 0.05** (direction-shuffle null).
>   - NET (3.5 bps) **mean_R > 0.030** ve **BH-FDR q < 0.05** (8-nokta aile içinde).
>   - **Annualized day-Sharpe (NET) > 0.7** ve bootstrap 95% CI alt sınır > 0.
>   - **Tek-tepe / iç-bükey:** cw=1 ve cw=10'da mean_R **strikt olarak** tepe-cw'den düşük; tepe-cw'nin Δ mean_R komşularına göre ≤2× (sivri zirve banı).
>   - **Per-yıl pozitiflik:** 2018..2026 (8 yıl) içinden **en az 6 yıl** mean_R > 0.
>   - **Leave-one-symbol-out:** 3 sembolden hiçbirini çıkarınca min NET Sharpe > 0.3.
>   - **Trade sayısı:** her cw'de N ≥ 150 (3 sembol × 8 yıl × 4h ~17.5k bar, FBR oranı ~%1-2 → ~200-400 trade beklenir; <150 ise istatistik anlamsız).

## 2. Null Hipotez (ne olursa çürür)

H₀: Confirmation-window parametresi FBR mean_R'i üzerinde **bilgisi yok** — yani cw'yi değiştirmek sadece sample shrink/grow yapar, gerçek edge sıfırdır.

H₀ kanıtları:
- Tüm 8 cw'de p_gross ≥ 0.05.
- Mean_R(cw) sıralaması düz/random — Spearman ρ(|cw − tepe|, mean_R) > -0.4 değil.
- BH-FDR sonrası q<0.05 survivor sayısı = 0.
- Tek-tepe testi başarısız: ya monoton-artan (cw arttıkça hep daha iyi → muhtemelen başka şey ölçülüyor) ya monoton-azalan ya da çok sivri (curve-fit).

## 3. Gerekçe (RAG referansları)

- **[Brooks 2012 ch.7 — "Failed breakout = trap = reverse trade"]** RAG #1 ve #5: "Failed breakouts are very high probability." Brooks'un explicit edge claim'i: failed BO → opposite direction, "%65-75 WR strong trend'de." Bu, sweep'in **literatür-anchor noktası**: Brooks 1-2 bar within range close'u "fail" kabul ediyor → bizim cw=1,2 testleri Brooks-faithful, cw=8-10 testleri "Brooks'un dediğinden uzaklaşma" diagnostic.
- **[Volman, RAG #2]** FBR (Failed Breakout Reversal) pip-tabanlı sınır koyar (Brooks daha gevşek). Volman 70-tick chart'ta 1-3 bar within range close'u "fail" der → 1h-4h timeframe equivalent ~1-3 bar = bizim cw=1,2,3.
- **[Brooks deep_catalog, RAG #6]** Range-top fade: signal bar range top'un %85-100 bandında, bear karakterli. "Default davranış fade extremes — kanıtlanana kadar breakout bekle." Bu, FBR'ın aslında "range-fade içinde özel bir tetik" olduğunu söylüyor → 4h forex'in trending olmayan range-mean-reverting karakteri (kripto'ya kıyasla) bu setup için **a priori uygun**.
- **[SMC/ICT, RAG #8 ve #10 — "Liquidity grab + inducement"]** Range-top sweep + close-back-inside = SMC "inducement"ı; mekanik olarak FBR ile aynı, sadece terim farkı. SMC topluluk claim'leri "60-70% WR" (test edilmemiş) bizim test bu iddiayı **falsification altına** sokuyor.
- **[Bizim 2026-06-01 fabio-orderflow-valuearea-crypto REJECT]** Crypto 5m OHLCV'de value-area rejection (FBR'ın yakın akrabası) shuffle null'a göre p=0.50 — yön bilgisi sıfır. Forex 4h'a geçme nedenim: (a) 4h fee/spread oranı 5m'den çok daha iyi, (b) Brooks'un original setting'i 5m E-mini değil 5m-60m mix, (c) forex 4h'da swing range yapısı daha temiz/repeatable.
- **[Memory: forex-4h-research-status.md]** EUR/USD 4h brooks_failed_breakout daha önce GO adayı işaretlenmiş ama canlı SPK-bloklu, paper-only. Bu sweep o GO işaretinin **tek bir cw parametresine bağımlı olup olmadığını** test ediyor — eğer monotonluk yoksa GO statüsü sahteydi.

**Anti-gerekçe (ihtiyat):**
- Forex 4h evreni küçük (3 sembol, 8 yıl) → istatistik gücü düşük; cw başına ~200-400 trade demek per-yıl 25-50 trade, regime-luck ihtimali yüksek.
- HistData broker-spread modellemesi gerçek ECN execution'ı tam yansıtmaz → NET edge ~%30 sub-estimate olabilir (bizim tarafta konservatif olmamızı garanti eder).
- "Brooks didn't backtest" — Brooks'un edge claim'leri **discretionary observation**, statistical inference değil; bu sweep'in default beklentisi reject.

## 4. Bağımlı Değişkenler (dependent vars)

| Metric | Hedef | Notlar |
|---|---|---|
| mean_R (gross, 0bps) | > 0.040 | direction-shuffle null'a göre p_gross < 0.05 |
| mean_R (net, 3.5bps) | > 0.030 | BH-FDR q < 0.05 |
| Annualized day-Sharpe (net) | > 0.7 | bootstrap 1000-iter, CI alt sınırı > 0 |
| Profit factor (net) | > 1.25 | kanıt zinciri |
| MaxDD (sabit-fraksiyon %0.5/trade) | < 20% | 8-yıl forex equity curve |
| Trade sayısı (her cw) | ≥ 150 | <150 = istatistik anlamsız, kill |
| Per-yıl pozitif yıl sayısı | ≥ 6/8 | 2018-2026 |
| Leave-one-symbol-out min Sharpe | > 0.3 | EUR/USD, GBP/USD, USD/JPY ayrı ayrı |
| Tek-tepe testi | tepe-cw, Δ ≤ 2× komşu | sivri tepe = curve-fit |
| Spearman ρ(|cw − tepe|, mean_R) | < -0.4 | iç-bükey tepe sinyali |
| IS/OOS Sharpe oranı | < 1.5 | IS=2018-2023, OOS=2024-2026 (29 ay) |

## 5. Bağımsız Değişkenler (independent vars — DONDURULMUŞ)

- **Confirmation window ailesi (DONDURULMUŞ, sweep ekseni):** `cw ∈ {1, 2, 3, 4, 5, 6, 8, 10}` — 8 nokta. 7 ve 9 dahil değil (Brooks/Volman 1-3 anchor, 4-6 mid, 8-10 outlier). Aile genişletilmeyecek.
- **Range tanımı (DONDURULMUŞ):**
  - Lookback N = 20 bar.
  - Swing high/low pivot: ±2 bar local extreme.
  - Range geçerlilik: top-bot ≥ 1.0×ATR(14), benzer-seviye toleransı 0.5×ATR.
- **Breakout tetiği (DONDURULMUŞ):**
  - bullish: close > range_top + 0.1×ATR.
  - bearish: close < range_bot − 0.1×ATR.
  - One-shot: aynı range içinde 2. BO trigger sayılmaz (ilk fail edilmesi yeterli).
- **FBR onay mekaniği (DONDURULMUŞ):**
  - bullish BO sonrası: bar(t+k), k∈[1,cw] içinde herhangi bir bar close < range_top → SHORT FBR.
  - bearish BO sonrası: bar(t+k), k∈[1,cw] içinde herhangi bar close > range_bot → LONG FBR.
  - Entry: onay barı close'unda.
- **Stop/TP (DONDURULMUŞ):**
  - SL: range_top + 1×ATR (long: range_bot − 1×ATR).
  - TP: 2.0R fixed.
  - Time-stop: 24 bar (96h) sonra force-exit (4h × 24 = 4 gün max hold).
- **Universe (DONDURULMUŞ):** EUR/USD, GBP/USD, USD/JPY — HistData minute → 4h aggregated. Listing-life her birinde tam dönem (8 yıl).
- **Timeframe:** 4h.
- **Dönem:** 2018-01-01..2026-05-31 (8.4 yıl). IS = 2018-2023 (6 yıl), OOS = 2024-01-01..2026-05-31 (29 ay).

## 6. Beklenen p-value ve Düzeltme

- **Raw p-target:** Her cw için p_gross (direction-shuffle, 1000 iter) < 0.01.
- **Multiple testing:** 8-cw ailesi → **BH-FDR q < 0.05**. Bonferroni eşdeğeri α/8 = 0.00625, çok conservative tarafta.
- **Beklenti (prior):** Geçmiş 4 reversal/continuation sweep'inin tamamı (4/4) gross gate'inde düştü. Bu hipotezin **reddedilme ihtimali %70-75**. Buna rağmen test ediliyor çünkü:
  - Forex 4h'da edge testi crypto'ya kıyasla **bizim tarafta first-of-kind** — negative coverage bile değerli.
  - Memory'deki "forex 4h brooks_failed_breakout GO" işareti **single-cw cherry-pick mi yoksa robust mu** sorusunun cevabı bize lazım.

## 7. Stop Criteria (kod-öncesi)

Hipotezi koşmadan ÖNCE iptal:
- **C1 (veri yetkinliği):** HistData EUR/USD 4h 2018-2026 dönem kapsamı tam mı? Eksik > %2 ise iptal.
- **C2 (range-detector varyans):** Range-detector son 3 yılda 3 sembol başına min 500 range bulmazsa, FBR örneklem yetersiz → iptal.
- **C3 (shuffle null implementation sanity):** Direction-shuffle harness'i bilinen pozitif edge (vsa-widestop) üzerinde p<0.01 veriyor mu? Vermiyorsa harness bozuk, iptal.

Hipotezi koştuktan sonra abort:
- **A1 (no-edge):** Tüm 8 cw'de p_gross ≥ 0.05 → red. Brooks/Volman'ın "high probability" claim'i 4h forex'te falsified.
- **A2 (sivri tepe / curve-fit):** Yalnızca 1 cw q<0.05, komşuları q>0.20 → red. Δ > 2× komşu = curve-fit.
- **A3 (monoton-artan eğri):** cw arttıkça mean_R hep artıyor → "confirmation" lever'i aslında **trade-count azalma** lever'i, edge sample-shrink artifact'i → red.
- **A4 (monoton-azalan eğri):** cw=1 max, cw=10 min → "1-bar onay" Brooks-uyumlu ama eğri çok düz, gradient < 0.005R/bar → marjinal edge, ITERATE değil RED.
- **A5 (per-yıl):** Spearman ρ var ama per-yıl 3+ yıl negatif → regime-luck.
- **A6 (LOSO):** Tek bir sembol çıkarılınca Sharpe > 0.3 → 0 oluyorsa → red (single-symbol carry).
- **A7 (IS/OOS):** IS mean_R / OOS mean_R > 2.0 → overfit, red.

3-yol kararı (SOP-4):
- **TERFI ADAYI:** Tüm gate ✓ + tek-tepe iç-bükey ✓ + LOSO ✓ + per-yıl ≥6/8 ✓ → Lab tournament. Memory'deki "forex 4h GO" işareti onaylanır.
- **ITERATE (SOP-4b):** Aylık ROI > 0 ama MaxDD > 20% veya per-yıl 4-5/8 → v2 (risk_pct 0.005 → 0.002, time-stop 24 → 12 bar, ya da symbol-subset).
- **RED:** A1-A7'den biri → gerekçeli arşiv `learning.md`'ye 3-satır ders + memory'deki "forex 4h GO" işaretini **REVOKE** et.

## 8. Reproducibility

- git_hash: (run sırasında)
- data_hash: HistData forex bundle SHA256
- config_hash: bu doc'un SHA256
- shuffle seed: 42 (default), bootstrap 1000 farklı seed
- Determinism testi: aynı seed iki kez koşulunca bit-identical mean_R

## 9. Tahmini Compute

- 3 sembol × 8 yıl × 6 bar/gün × 365 = ~52.5k bar; tüm bar üzerinden FBR detector vectorized.
- 8 cw × 1000 shuffle = 8000 perm.
- Tahmini wall-clock: ~10-15 dakika.

## 10. Karar Çerçevesi (post-run)

```
1. C1/C2/C3 stop'lar geçti mi? → hayırsa iptal logla.
2. Her cw için tablo: trade_n, mean_R_gross, p_gross, mean_R_net, q_BHFDR, Sharpe_net, MaxDD.
3. Monotonluk + tek-tepe analizi (Spearman + Δ-komşu testi).
4. Per-yıl tablosu (8 yıl × 8 cw).
5. LOSO tablosu (3 sembol × 8 cw).
6. IS/OOS Sharpe oranı.
7. Karar: TERFI / ITERATE / RED.
8. Gerekçeli arşiv (her 3 yol için zorunlu).
9. Memory update: "forex 4h GO" işaretinin durumu (confirm / revoke / qualify).
```

## 11. Adversary için sorular

`adversary_engineer`'a önceden:
- **Q1:** HistData 4h aggregation broker session-gap handling'i (Sun 22:00 UTC açılış, Fri 22:00 UTC kapanış) sızıntı yapıyor mu? Causality test zorunlu.
- **Q2:** Range-detector lookahead-safe mi? Swing pivot ±2 bar local extreme = bar(t)'ı görmek için bar(t+2)'ye bakmak gerek. Pivot'ı **t+2'de teyit** ediyoruz, t'de değil → FBR onayı en erken t+2+cw'de gelir; entry t+2+cw+1 close. Kod harness'ı bu offset'i kesin uygulamalı.
- **Q3:** Time-stop 24 bar = 4 gün; haftasonu boşluğu sırasında time-stop hesaplanırken bar-sayma vs takvim-saat hangisi? Bar-sayma kullan, takvim değil.
- **Q4:** USD/JPY pip değeri (0.01) vs EUR/USD (0.0001) — fee modeli pip-tabanlı yapılırsa USD/JPY'da yanlış scale → fee modeli **bps-tabanlı** olmalı (notional × 0.000035).
- **Q5:** 8-yıl forex evreninde 2020-03 COVID flash spike, 2022 Yen carry-unwind, 2024-08 mini-flash dönemlerinde drawdown nasıl davrandı? Stress periyot raporu ek tablo.

---

**Bu hipotez REDDEDILMEYE HAZIR.** Default beklenti: 8 cw'den 1-2'si raw p_gross < 0.05 verir, BH-FDR sonrası 0-1 hayatta kalır, tek-tepe testi başarısız olur (ya monoton-artan ya sivri), hipotez RED → memory'deki "forex 4h brooks_failed_breakout GO" işareti **REVOKE** edilir.

Eğer aksi olursa (iç-bükey tepe + BH-FDR q<0.05 ≥2 komşu cw + per-yıl ≥6/8 + LOSO ✓) — bu **Brooks/Volman'ın FBR claim'inin bizim tarafta ilk istatistiksel doğrulaması** olur ve Lab tournament'a tam hızla gider. Skeptisizmi koruyorum.

**Notlar:** Eğer Lab pre-registration aşamasından önce memory'deki "GO" işaretinin kaynağı (önceki backtest config + sonuç) bulunamazsa, o işaret **kendisinin pre-register olmadan yazıldığı** anlamına gelir ve hipotez bağımsız olarak başlangıçtan değerlendirilir (önceki sonuca uydurma yapılmaz).
