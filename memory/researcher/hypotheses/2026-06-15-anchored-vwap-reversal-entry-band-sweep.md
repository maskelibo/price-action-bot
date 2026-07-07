---
doc_id: researcher-20260615T000000-anchored-vwap-reversal-entry-band-sweep
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-15T00:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, adversary_engineer, risk_officer]
tags: [hypothesis, mean_reversion, anchored_vwap, parameter_sweep, curve_fit_risk]
supersedes: null
hash: null
---

# Hypothesis: HYP-2026-06-15-AVWAP-REVERSAL-BAND-SWEEP

## 0. Curve-Fit Warning (UPFRONT)

> **Bu hipotez bir parametre süpürme çalışmasıdır.** Anchored VWAP "entry-band distance" parametresinin Sharpe vs. distance eğrisini çıkarmak amacıyla 5 anchor noktası × 7 band değeri × 3 timeframe = **105 trial** koşulacak. Bonferroni (α=0.05/105 = **4.76e-4**) ve Benjamini-Hochberg FDR (q=0.10) zorunlu. **Tek bir trial'ın "best Sharpe"i kabul edilmez** — band-distance fonksiyonunun sürekli, fizik-uyumlu (uçlarda monoton) bir yapısı varsa edge gerçek olabilir; tek-pik (tek band değerinde patlama) → overfit.

## 1. Iddia (pre-registered, ölçülebilir)

> "Crypto USDT-perpetual evreninde (3y, 30 likit sembol), `session_open` anchor'lı VWAP'ın ±k×σ_vwap entry band'ında oluşan **anti-trend reversal entry** (long: price ≤ AVWAP − k·σ, short: price ≥ AVWAP + k·σ), close'da girişle, 1.0×ATR(14) SL ve 1.0×ATR(14) TP ile, 2026-06-15 öncesi son 36 ay üzerinde:
>
> Hangi `k ∈ {0.5, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5}` değeri için aşağıdaki **tümü** sağlanır:
> - Net annualized return (fee+slip dahil) > **%25**
> - OOS Sharpe > **1.0**
> - MaxDD < **%30**
> - Profit factor > **1.3**
> - Trade sayısı N ≥ **300** (istatistik yeterliliği)
> - Win rate ∈ [%55, %72] (Kaufman beklentisi — yüksek WR mean-reversion paterni)
> - Shuffle baseline p-value < **0.01** (Bonferroni öncesi)
> - **Adjacent-k coherence:** seçilen k için k±1 step'teki Sharpe ≥ 0.5 × peak (yalnız izole pik → curve-fit reddi)
> - Bonferroni-corrected p < **4.76e-4** VEYA BH-FDR (q=0.10) altında kalmalı."

**Net hipotez kabulü:** Yukarıdaki **9 koşulun tamamı** karşılayan **en az 1 ve en fazla 3** ardışık k değeri bulunmalı. Bulunamazsa H0 reddedilemez → hipotez **RED**.

## 2. Null Hipotez (H0)

> "Anchored VWAP band-distance'ın hiçbir değeri (k ∈ test seti), shuffle baseline'a karşı net OOS Sharpe avantajı sağlamaz; ya da sağlasa bile yalnız izole bir k'da gözükür (curve-fit imzası)."

**H0 reddi için gereken delil:** § 1'deki 9 koşulun tamamı + adjacent-k coherence.

## 3. Gerekçe (RAG referansları)

| Ref | İçerik | Hipoteze katkısı |
|---|---|---|
| [Kaufman §mean_reversion, #9] | "Mean reversion: WR %55-70, düşük R-multiple, range-bound rejimlerde mükemmel, trending'de catastrophic" | Win rate beklentisi + rejim filtresinin zorunlu olduğu uyarısı (regime split robustness suite'te) |
| [Stockcharts S/R + candlestick, #1] | Confluence (S/R + candle + momentum + volume) false signal'ı düşürür | k'nın düşük değerlerinde (0.5σ) confluence yetersizliğinden gürültü beklenir → düşük k'da Sharpe düşmesi öngörüsü |
| [Daily Price Action pin bar, #2] | "Reversal pattern range high/low veya pullback'lerde oluşur" | AVWAP band uçlarının pullback geometrisi ile uyumu |
| [Outside bar Bulkowski, #3] | Bullish outside %63, bearish %65 reversal — "S/R veya EMA temas şart" | Anchored VWAP, dinamik S/R rolü oynar → benzer geometri varsayımı |
| [Market structure EQH sweep, #7] | Sweep + same-bar reversal close → 3-5 bar içinde ≥1 ATR düşüş | Yüksek k (≥2.0σ) için sweep-benzeri davranış beklentisi |
| [SMC/ICT BOS-OB, #5] | "OB mitigation ≈ Brooks second pullback" | k orta değerlerde (1.0-1.5σ) mitigation analogu |

**Hipotez kaynak çekirdek:** Kaufman'ın "z-score reversion" mantığı (#9) + Brooks-style failed-breakout (sweep) hibridi.

## 4. Dependent Variables (önceden kayıtlı, sıralı önemde)

| Sıra | Variable | Hedef | Reddedici eşik |
|---|---|---|---|
| 1 | OOS Sharpe (walk-forward 12 dilim ortalaması) | > 1.0 | < 0.7 → RED |
| 2 | Bonferroni-corrected p-value (n=105) | < 4.76e-4 | ≥ 4.76e-4 → RED |
| 3 | Adjacent-k Sharpe coherence | k±1 ≥ 0.5×peak | tek-pik → RED (curve-fit) |
| 4 | Net annualized return (fee 7.5bps + slip 5bps) | > %25 | < %15 → RED |
| 5 | MaxDD (account-equity bazlı, **kümülatif PnL bazlı DEĞİL** — [[backtest-compounding-inflation]] ders) | < %30 | > %40 → RED |
| 6 | Profit factor | > 1.3 | < 1.1 → RED |
| 7 | Trade sayısı | ≥ 300 | < 200 → istatistik yetersiz, RED |
| 8 | IS/OOS Sharpe farkı | < %30 | > %50 → overfit RED ([[lookahead-bias-zero-tolerance]] + [[overfitting-red-flags]]) |
| 9 | Regime split (bull/bear/range) | en az 2'sinde pozitif Sharpe | yalnız 1'inde pozitif → kırılgan, RED |
| 10 | Shuffle baseline p-value | < 0.01 | ≥ 0.01 → şans, RED |

## 5. Independent Variables (parametre uzayı — pre-frozen)

| Parametre | Set | Adım | Trial sayısı |
|---|---|---|---|
| `anchor_type` | {session_open, week_open, prev_swing_high, prev_swing_low, listing_date} | discrete | 5 |
| `band_k` (sigma çarpanı) | {0.5, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5} | non-uniform (kasıtlı: makul fizik) | 7 |
| `timeframe` | {15m, 1h, 4h} | discrete | 3 |
| **Toplam** | — | — | **5 × 7 × 3 = 105** |

**Kasıtlı olarak DAR uzay:**
- `band_k` adımı 0.25 (ince değil) — [[overfitting-red-flags]] §3 uyarısı.
- ATR çarpanları (SL/TP) **OPTIMIZE EDİLMEZ** — 1.0/1.0 sabit. Optimize edersek parametre uzayı 105 → 105 × 9 = 945 olur, FDR kaybedilir.
- `risk_pct = 0.005` sabit (literatür standardı + [[leverage-discipline]]).

**Lookahead sıfır tolerans:** [[lookahead-bias-zero-tolerance]] §causality testi tüm trial'lara zorunlu.

## 6. Beklenen p-value

- **Pre-correction beklenti:** En iyi 3 trial için p < 0.01 (Kaufman mean-reversion edge'inin literatürde bilinen büyüklüğü).
- **Bonferroni eşiği (105 trial):** p < 4.76e-4 — sert, ama tek-trial istatistiksel yanılsamayı keser.
- **BH-FDR (q=0.10) eşiği:** Daha yumuşak; en az 5 trial geçerse hipotez "yön doğru ama büyüklük belirsiz" kategorisine girer → terfi YOK, **Lab tournament'a değil, ek-veri talebine** geçer.

**Beklenti senaryoları (Bayesian prior, pre-registered):**
- P(hipotez **tam** kabul) = 0.15 — mean-reversion crypto'da 2022 sonrası kırılgan.
- P(hipotez **kısmi** kabul; yalnız 1 timeframe×anchor) = 0.30 — muhtemelen 4h + session_open kombinasyonu.
- P(red — H0 tutar) = 0.55 — modal beklenti.

## 7. Stop Criteria (research terminasyon koşulları — sıralı)

1. **Erken-stop A (data quality):** Backtest universe survivorship-clean değilse ([[survivorship-bias-crypto]]) — durdur, Data Engineer'a geri gönder.
2. **Erken-stop B (lookahead):** Causality testi başarısız olursa — durdur, Signal Chief'e detector audit talep et.
3. **In-sample stop:** Hiçbir 105 trial'ın IS Sharpe'ı > 0.5 değilse → araştırma terkedilir, **OOS koşmaya gerek yok**. Token harcama.
4. **Coherence stop:** Tüm IS-positive trial'lar izole pik (komşuları negatif) → **curve-fit imzası kesin**, OOS koşmadan red.
5. **Regime stop:** IS sonuçları yalnızca 2020-2021 bull rejiminden geliyorsa (>%80 PnL katkısı) → "tek-rejim artifaktı", red.
6. **Trade volume stop:** Toplam trade < 150 (tüm 105 trial üzerinden minimum) — istatistik anlamsız, red.
7. **Compute stop:** 4 saat compute süresini aşarsa, ara durdur ve scope daralt.

## 8. Robustness Suite (zorunlu — terfi adayı olursa)

[[know_how.md]] §Playbook: Walk-Forward + §Stress Test Periyodları + SOP-3:

- Walk-forward: 24m train + 6m test, step 3m (12 dilim).
- Random param perturbation: band_k ±%10, 50 seed → ort. Sharpe kayıp < %25.
- Symbol-out CV: 30 sembolün her birini dışarıda bırak.
- Regime split: bull (2020Q4-2021Q4), bear (2022), range (2023, 2024H2).
- Stress periyodları: **2022-05 (LUNA), 2022-11 (FTX), 2023-03 (USDC depeg), 2024-08 (Yen carry)**. Bu dilimlerde yıkıcı kayıp yok.
- Shuffle baseline: returns shuffle × 1000 → empirik p-value.
- Multiple testing: Bonferroni (4.76e-4) + BH-FDR (q=0.10) **ikisi de** uygulanır.

## 9. Reproducibility Çıpaları

```
git_hash: <fill at execution>
config_hash: <fill at execution — anchor_set, band_set, tf_set, sym_universe, fee/slip>
data_hash: <fill at execution — DuckDB snapshot at 2026-06-15T00:00Z>
backtest_engine: backtest/engine.py vectorbt
walk_forward: backtest/walk_forward.py
rag_query: "anchored vwap mean reversion entry band z-score" k=10
```

## 10. Bias Pre-Mortem (kendime soruyorum)

- **Confirmation bias riski:** "Kaufman'a göre mean-reversion %55-70 WR" varsayımı beni red için yüksek eşik koymaktan vazgeçirmeye eğilimli. Karşı önlem: WR aralığını **dar** ([%55, %72]) bağladım — bunun dışında da hipotez RED.
- **Narrative bias riski:** "AVWAP institutional reference" anlatısı çekici. Karşı önlem: hipotez tamamen sayısal; anlatı kabul gerekçesi değildir.
- **Recency bias:** Son 6 ayda BTC range-bound — mean-reversion görsel olarak iyi görünür. Karşı önlem: 36 aylık pencere; rejim split zorunlu.
- **P-hacking riski:** 105 trial yüksek. Karşı önlem: ATR çarpanları SABIT (0/9× artış engellendi); Bonferroni + FDR zorunlu; adjacent-k coherence kuralı (tek-pik RED).

## 11. İterate Politikası (SOP-4b)

Eğer aylık ROI > 0 ama DD veya başka risk metriği gate'i geçemezse → **RED EDİLMEZ**, v2 iterate hipotezi açılır:
- v2-risk: `risk_pct` 0.005 → 0.002.
- v3-regime: range-only rejim filtresi.
- v4-confluence: + S/R confluence (#1) veya + outside bar confirm (#3).
- v5-meta-label: López meta-labeling (#10) ile P(win) > 0.55 ek filtre.

İterate budget: maks 5 versiyon (SOP-4b standart).

## 12. Dependencies / Bloklayanlar

- **Data:** USDT-perp 15m/1h/4h, 30 sembol, 36 ay, survivorship-clean ([[survivorship-bias-crypto]]).
- **Signal:** `anchored_vwap` detector mevcut mu? — kontrol: `signals/anchored_vwap.py`. Yoksa Signal Chief'ten request.
- **Backtest:** `backtest/engine.py` vectorbt + `walk_forward.py` hazır olmalı.

## 13. Tahmin Edilen Sonuç (kayıt — kendi kalibrasyonum için)

> Modal tahminim: **kısmi kabul** (15% × 0.3 / 0.45 normalize ≈ 67% conditional). En olası kazanan: `anchor=session_open, timeframe=4h, band_k=1.25` veya `1.5`. En olası tuzak: `anchor=listing_date` — survivorship contamination'a açık.

## 14. Sign-off

- **Author:** researcher
- **Pre-registered at:** 2026-06-15T00:00Z
- **Frozen — değiştirmek için yeni doc + supersedes**

---

> ⚠️ **Bu hipotez kod yazılmadan önce dondurulmuştur.** Backtest sonuçları geldiğinde § 1'deki 9 koşula bakılır — koşullar sonradan revize edilmez. Revize edilirse [[overfitting-red-flags]] §3'e göre overfit olarak işaretlenir ve red edilir.
