---
doc_id: researcher-20260629T000000-trm-continuation-vsa-decorrelator
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-29T00:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, continuation, three_rising_methods, decorrelator, cross_strategy_edge]
supersedes: null
---

# Hipotez: HYP-2026-06-29-trm-continuation-vsa-decorrelator

- Tarih: 2026-06-29
- Versiyon: 0.1
- Seed: "Cross-strategy edge keşfi — aktif vsa_climax_test ile düşük korelasyonlu ek bir aday"
- Aday: **Three Rising Methods (TRM, bullish continuation)** — Bulkowski Performance rank 10/103.

## 1. Aday Seçim Mantığı (kısa)

Aktif tek bot `vsa_climax_test` → **volume-exhaustion reversal**. Portföye eklenecek aday için aranan özellik: aynı bar setinde tetiklenmemesi (mekanik ortogonal) + rejim ortogonalliği (reversal vs continuation). Bulkowski katalog + Volman + Brooks taraması içinden:

| Aday | Tip | Korelasyon Riski | Mekanik Skor |
|---|---|---|---|
| Three Rising Methods | Trend-continuation | DÜŞÜK (climax-bar üstüne 5-bar konsolidasyon) | 5/5 (rank 10/103) |
| ii / iii breakout (Volman) | Breakout/contin. | ORTA | 4/5 |
| Donchian 20-bar | Breakout/contin. | ORTA-DÜŞÜK (whipsaw rejim ortogonal) | 4/5 |
| Equal-High Sweep + CHoCH | Reversal | YÜKSEK (vsa ile aynı rejim) | 3/5 — REDDET |
| Marubozu cont. | Cont. | DÜŞÜK ama %64 rate zayıf | 3/5 |

→ TRM seçildi. Yedek: Donchian-20.

## 2. İddia (Pre-registered, Ölçülebilir)

> **15m timeframe, USDT-perpetual evreninde (v14 evreni, 18 sembol), Three Rising Methods bullish continuation pattern (Bar1: ≥1.5×ATR(14) bullish body; Bar2-4: tamamen Bar1 gövde aralığında, herhangi rengi; Bar5: bullish, kapanış > Bar1 kapanışı), Bar5 kapanışında girişle, 2.0×ATR(14) SL ve 2R TP, time-exit 24 saat, 2024-01-01 → 2026-05-31 OOS evrenindeki backtest aşağıdakileri SAĞLAR:**
>
> - Annualized net return > **%25** (fee 7.5 bps taker + slippage 5 bps dahil)
> - OOS Sharpe > **0.8** (Chan tek-varlık eşiği)
> - MaxDD < **%25** (account equity bazlı, CT-RSK-01 düzeltmesi)
> - **vsa_climax_test ile günlük log-return korelasyonu |ρ| < 0.30** (Pearson, çakışan 250+ gün)
> - Profit factor > **1.3**
> - Trade sayısı ≥ **150** (istatistik power'ı için)

## 3. Null Hipotez

H₀: TRM pattern returns shuffle-baseline'dan istatistiksel olarak farklı değildir (p ≥ 0.05). Yani pattern hiçbir bilgi taşımıyor; aynı bar setinde rastgele giriş ile aynı dağılım.

H₀ reddedilemezse hipotez TERK edilir.

## 4. Gerekçe (RAG Referansları)

- **[Bulkowski 2008 / candlestick_statistics #10]**: Three Rising Methods continuation rate %74, average move %6.1, performance rank 10/103. US equities tarihsel; crypto 15m'de muhtemelen aşınır — beklentim %55-62 rate (curve-fit anti-bias).
- **[Bulkowski / candlestick_statistics #2]**: Inside-bar sıkışma yapısı zayıf (rank 78), ama "ii/iii"-tipi consolidation breakout güçlenir. TRM bunun 5-bar sürümü, aynı mekanik ailesi.
- **[Brooks deep_catalog #3]**: Continuation setup'larında HTF aynı-yön + reversal-bar kalitesi kritik. TRM Bar5 kapanışı = "büyük yeşil bar after consolidation" Brooks "breakout bar" kriterini karşılar.
- **[Chan summary #9]**: Yeni stratejilerin OOS Sharpe > 0.8 (single-asset) eşiği. Eşik buradan alındı, p-hacking değil.
- **[López de Prado #1]**: 6 production-block kriteri (DSR<0.5, PBO>0.5, T<MinBTL, IS>3×OOS Sharpe, params/samples>1/30, WF variance > mean). Stop criteria buradan türetildi.
- **[Kaufman summary #7]**: Donchian-20 (yedek aday) %35 WR + 3-5R asimetri ile pozitif beklenti. TRM hedefimiz daha simetrik (~%50 WR + 2R fixed).

## 5. Dependent Variables (Pre-registered Metrikler)

| Metrik | Hedef | Kaynak |
|---|---|---|
| Annual net return | > %25 | engine |
| OOS Sharpe (annualized, √(365×96) bars/yr) | > 0.8 | engine (CT-RES-01 düzeltmesi: 365 takvim, 96 = 15m/day) |
| MaxDD (equity-based) | < %25 | engine |
| ρ(TRM_daily, vsa_climax_daily) | |ρ| < 0.30 | Pearson, çakışan 250+ gün |
| Profit factor | > 1.3 | engine |
| Win rate | info-only (NOT optimized) | engine |
| Trade count | ≥ 150 | engine |
| IS/OOS Sharpe ratio | < 3.0 | López de Prado |
| PBO (combinatorial CV) | < 0.5 | López de Prado |
| Bonferroni-adjusted p | < 0.05 | shuffle baseline ile |

## 6. Independent Variables (Curve-Fit Anti-Pattern — Sınırlı Grid)

| Parametre | Aralık | Adım | Kardinalite | Gerekçe |
|---|---|---|---|---|
| Bar1 min body (×ATR14) | {1.0, 1.5, 2.0} | — | 3 | "Büyük bullish bar" tanımı |
| Inside kriteri (Bar2-4) | {Bar1 body, Bar1 full range} | — | 2 | Bulkowski body, Brooks range — iki tanım test |
| SL multiplier (×ATR14) | {1.5, 2.0, 2.5} | — | 3 | Standart risk-bantı |
| TP R-multiple | **2.0 (FIXED)** | — | 1 | p-hacking önleme — TP optimize ETMİYORUM |
| Time-exit | **24h (FIXED)** | — | 1 | TRM continuation 1 günde tamamlanır beklentisi |

**Total grid: 3 × 2 × 3 = 18 kombinasyon.** Bonferroni n=18. Optuna KULLANILMAYACAK — bilerek grid (fewer DoF + reproducibility). Best-trial seçimi OOS Sharpe ile, sonra DSR+PBO ile re-doğrulama.

**Free params / sample size (López de Prado kriteri):** 3 parametre / ~150 trade = 1/50 — sınırın altında ✓.

## 7. Beklenen p-value

- Shuffle-baseline (returns'leri zaman içinde permutasyon, N=1000) yenmesi için: p < 0.01.
- 18 grid noktası için Bonferroni: adj-p eşiği 0.05/18 = 0.00278. Bir grid noktası bile bunu sağlarsa pattern bilgi taşıyor.
- Eğer hiçbir grid noktası adj-p < 0.05 sağlamıyorsa → RED.

## 8. Stop Criteria (kesin)

Aşağıdakilerden HERHANGİ biri tetiklenirse araştırma durur, hipotez RED arşivlenir:

1. **IS Sharpe < 0.5** → terk.
2. **IS/OOS Sharpe oranı > 3** → López de Prado kriteri.
3. **PBO > 0.5** → kombinatoryel out-of-sample fail.
4. **Trade sayısı < 100** → istatistik power yok.
5. **|ρ(TRM, vsa)| ≥ 0.5** → korelasyon hedefi tutturulamadı (ana motivasyon çürür — decorrelator değil).
6. **Walk-forward 12 dilimin > 5'i negatif** → edge tutarsız.
7. **2022-05 LUNA + 2022-11 FTX + 2024-08 Yen carry dilimlerinin herhangi birinde -%30+ DD** → tail-fragile.
8. **In-sample/out-of-sample Sharpe farkı > %50** → overfit.

## 9. Curve-Fit Şüphesi (Proaktif, Pre-Registered)

Kendime karşı 5 kırmızı bayrak şu anda:

1. **Bulkowski %74 sayısı US equities** — crypto 15m'de PROBABLY %55-65. Beklenti aşağı, beklentiyi backtest çıktısı %74'e yaklaştırıyorsa şüphelen (data-fitted vs structural).
2. **Pattern seyrek** — 18 sembol × 2.5 yıl × 15m'de TRM kaç defa? Hızlı tahmin: ~6 trade/sembol/ay × 18 × 30 ay ≈ 3240 candidate ama "büyük Bar1" + "tam inside Bar2-4" + "Bar5 kapanış üstü" kısıtlarıyla %3-5'i kalır → ~100-160 trade. **Sınırda.** Az trade = curve-fit kolaylaşır.
3. **15m'de inside-range tanım belirsizliği** — gövde mi total range mi? İki tanımı (body vs full range) ayrı test edip "iyi olanı" seçmek p-hacking. Bu yüzden **her ikisini Bonferroni'ye dahil edeceğim**.
4. **Bull-only pattern → asymmetric exposure.** Bear rejimde TRM hiç tetiklenmez → equity yatay. vsa_climax_test bear'da çalışıyorsa korelasyon zaten doğal olarak düşük çıkar; bu **trivially low correlation** olabilir, gerçek bir decorrelator değil. → Karar: korelasyonu **shared-non-flat-days only** (her iki strateji de aynı gün trade etmişse) hesaplayacağım.
5. **TP=2R, SL=2×ATR fixed kombinasyonu** — bu rakamlar "popüler" rakamlar. Backtest'te bu kombinasyon 1.5R/1.5×ATR'den belirgin iyi çıkıyorsa "doğru kombinasyon yakaladım" yerine "popüler kombinasyon literatür-baş-bias'lı" diye düşüneceğim.

## 10. Robustness Suite (SOP-3 tam liste)

| Test | Kabul Eşiği |
|---|---|
| Walk-forward 3y train / 6m test, step 3m | ≥7/12 dilim pozitif Sharpe |
| Param perturbation (±%10, 50 seed) | ortalama Sharpe kayıp < %25 |
| Symbol-out CV (18 LOO) | min OOS Sharpe > 0.4 |
| Regime split (bull/bear/range) | en az 2'sinde pozitif |
| Stress: 2022-05 LUNA, 2022-11 FTX, 2024-08 Yen | max dilim DD > -%30 değil |
| Shuffle baseline (N=1000) | p < 0.01 |
| Bonferroni (n=18) | adj-p < 0.05 |
| Lookahead test (causality) | %100 ✓ zorunlu |
| **ρ_vsa (shared-active-days only)** | |ρ| < 0.30 |

## 11. Iterate Yolu (SOP-4b kapsamı)

Eğer ROI > 0 ama DD veya korelasyon hedefi tutturulamazsa REDDETMEK YASAK. Önceden tasarlanmış iterate patikası:

- **v2-risk:** risk_pct düşür (0.5% → 0.3%), max_concurrent kısıtla
- **v3-confluence:** Bar5 hacim filtresi ekle (>1.5×20-bar avg vol) → fewer/sharper entries
- **v4-regime:** sadece HTF (1h EMA50 üstü) onaylı tetikler → bull-only daraltma
- **v5-be-protect:** 1R'de SL → entry (DD kalkanı)

Iterate budget: 5 versiyon. Sonra gate'i geçen aday → Lab tournament; geçmeyen → "deferred" arşiv (RED değil).

## 12. Reproducibility

- Backtest config: `configs/research/HYP-2026-06-29-trm.yaml` (henüz yazılmadı — hipotez commit'i sonrası)
- Data: `data/perp_ohlcv/15m_v14_universe_2024-01-01_2026-05-31.parquet`
- Git hash: commit'te otomatik
- Config hash: SHA256 grid YAML
- Engine: `backtest/engine.py` (vectorbt)
- Seed: 42 (numpy + shuffle baseline)

## 13. Karar Çerçevesi (sonradan doldurulacak)

- [ ] Terfi adayı (Lab tournament'a gönder)
- [ ] İterate (v2-v5 patikası)
- [ ] Red (gerekçeli arşiv)

---

**Pre-registration commit:** Bu doc commit edildikten sonra config yazılır ve engine çalıştırılır. Hipotez parametreleri / metrikleri / stop-criteria backtest sonrasında DEĞİŞTİRİLEMEZ.
