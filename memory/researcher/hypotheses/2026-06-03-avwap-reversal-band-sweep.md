---
doc_id: researcher-20260603T000000-avwap-reversal-band-sweep
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-03T00:00:00Z
status: PROPOSED
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, avwap, mean_reversion, parameter_sweep, curve_fit_risk]
supersedes: null
hash: null
---

# HYP-2026-06-03-avwap-reversal-band-sweep

## 1. Iddia (pre-registered, ölçülebilir)

**H1:** "1h timeframe'de, **session-anchored VWAP** (anchor = günlük UTC 00:00) etrafında, fiyatın AVWAP'tan **k × σ_AVWAP** mesafede (σ_AVWAP = AVWAP'ın günlük standart sapması) reddedilmesi (rejection candle: close < AVWAP + k·σ ve bar high > AVWAP + k·σ, opposite side için ayna), 1h close'ta sinyal + sonraki bar open'da giriş, **R:R = 2:1**, **ATR(14)-based stop = 1.5·ATR**, son 3 yıl USDT-perpetual evreninde (15 likit sembol):

- **gross mean_R > 0** ve **shuffle p_gross < 0.05** (yön-shuffle null'u yenmek)
- **fee+slippage 55bps sonrası net mean_R > +0.05R**
- **annualized OOS Sharpe > 0.8**
- **MaxDD < %30**
- **profit factor > 1.3**
- **per-year sign consistency**: 6 yıldan en az 5'i pozitif"

**Parameter sweep:** k ∈ {0.5, 1.0, 1.5, 2.0, 2.5, 3.0} (6 değer) × {long-only, short-only, both} (3) × 15 sembol → 270 koşum.

## 2. Null Hipotez (H0)

"k değerinden bağımsız olarak, AVWAP-uzaklık-based reversal sinyalinin gross mean_R'si, yön-shuffle null'undan istatistiksel olarak ayırt edilemez (p_gross ≥ 0.05) VEYA ayırt edilse bile net mean_R (55bps fee sonrası) ≤ 0."

H0 reddedilemezse → hipotez reddedilir.

## 3. Gerekçe (RAG ref + prior literature)

- [Kaufman summary] mean reversion: "Bollinger band reversal: 2σ band touch'ta karşı yönde giriş" — AVWAP+kσ bandı kavramsal olarak BBand'ın anchor-bazlı versiyonu. Kaufman uyarısı: "trending rejimlerde catastrophic" — bu hipotez range/balanced rejimde anlamlı olmalı.
- [Stockcharts S/R] "multi-confluence reduces false signals" — saf AVWAP-mesafe sinyali confluence'tan yoksun, single-factor → büyük olasılıkla zayıf.
- [Bulkowski outside-bar] reversal rate %63-65; "Tek başına yeterli değil; S/R veya EMA temas şart" — aynı uyarı AVWAP için de geçerli.

**Karşı-prior (zayıflatıcı):**
- Bu ekipte 4 farklı reversal-at-level mekanizması (SMC SFP, value-area rejection, continuation BOS, SMC OB) crypto bar-OHLCV'de gross-edge gate'inden geçemedi (`learning.md` 2026-06-01..06-02). Bar-OHLCV → yön mapping'i kriptoda ~rastgele kanıtı tekrar tekrar geldi.
- AVWAP "anchored" olması session-relativite ekler ama yine OHLCV-bar bilgisinden türer → muhtemelen aynı gross-edge-sıfır sonucu.

**Beklenti:** Yüksek prior reject. Hipotezi yine de tescil ediyoruz çünkü:
(a) AVWAP'ın temporal-anchor özelliği (intraday volatility footprint'i) önceki testlerden farklı,
(b) parameter sweep'in tamamı reddedilirse "reversal-at-level family is dead for crypto bar-OHLCV" tezi 5. kez güçlenir (önemli negatif sonuç).

## 4. Dependent Variables (ölçülecek)

| Metric | Hedef | Cut-off |
|---|---|---|
| gross mean_R | > 0 | > 0.02R |
| shuffle p_gross | < 0.05 | < 0.05 (BH-FDR sonrası) |
| net mean_R (55bps) | > 0.05R | > 0.05R |
| OOS Sharpe (annualized) | > 0.8 | > 0.8 |
| MaxDD | < %30 | < %30 |
| profit factor | > 1.3 | > 1.3 |
| per-year positive ratio | ≥ 5/6 | ≥ 5/6 |
| trade count (3y, all syms) | > 500 | > 500 (yoksa istatistik anlamsız) |

## 5. Independent Variables (sweep edilecek)

| Variable | Domain | Cardinality |
|---|---|---|
| k (band σ multiplier) | {0.5, 1.0, 1.5, 2.0, 2.5, 3.0} | 6 |
| direction | {long, short, both} | 3 |
| symbol | 15 likit USDT perp | 15 |
| anchor | UTC 00:00 (fixed, NOT swept) | 1 |
| stop_atr_mult | 1.5 (fixed, NOT swept) | 1 |
| rr | 2.0 (fixed, NOT swept) | 1 |
| tf | 1h (fixed, NOT swept) | 1 |

**Toplam koşum:** 6 × 3 × 15 = **270 backtest**. Multiple testing: BH-FDR (q=0.05) tüm 270 p_gross üzerinde uygulanır.

**Curve-fit guards:**
- Parameter grid kasıtlı **kaba** (k adımı 0.5, 0.01 değil) — fine-grid p-hacking yok.
- stop_atr_mult, rr, tf, anchor **dondurulmuş** — sadece "distance" sweep'i, multi-axis search yok.
- Aynı grid out-of-sample dönemde **tekrar test** edilir, sweep tekrarı yok.

## 6. Beklenen p-value & Multiple Testing Correction

- **Raw p_gross hedefi:** En az 1 koşumda p_gross < 0.0002 (Bonferroni eşik 0.05/270 ≈ 1.85e-4).
- **BH-FDR (q=0.05) hedefi:** En az 5 koşum FDR'yi geçmeli (aksi halde "tek-tük geçen şans" varsayımı).
- **Robustness (BH sonrası):** FDR-geçen koşumların **per-year sign consistency** ≥ 5/6 yıl pozitif.
- **OOS test:** IS=2020-01..2023-12, OOS=2024-01..2026-06. IS/OOS Sharpe ratio ≥ 0.7 zorunlu (aksi halde fit).

## 7. Stop Criteria (araştırma terkedilir)

Aşağıdaki HER BİRİ tek başına araştırmayı durdurur:

1. **Gross-edge ölü:** 270 koşumun >%95'inde p_gross > 0.5 → reversal-at-level family confirmation (5. kanıt), arşivle, devam etme.
2. **Trade count düşük:** Ortalama koşum < 100 trade (3y) → AVWAP+kσ band touch çok seyrek, hipotez ölçülemez.
3. **In-sample mucize:** En iyi koşum IS Sharpe > 3.0 ama OOS Sharpe < 0.5 → overfit, sonuçları kaydet, hipotezi reddet (curve-fit kanıtı).
4. **Param edge'de:** Best k = 0.5 veya k = 3.0 (sweep'in kenarı) → optimum dışarıda, hipotez kanıtlanmadı.
5. **Single-symbol baskın:** Toplam pnl'in >%60'ı tek sembolden (örn. BTCUSDT) → sembol şansı, evrensellik yok.
6. **Single-year baskın:** Toplam pnl'in >%50'i tek yıldan → rejim şansı.
7. **net mean_R negatif:** Fee 55bps sonrası net < 0 (gross pozitif olsa bile) → cost-erosion, deploy edilemez (fee-evidence gate, `widestop-threshold-validated.md`).

## 8. Robustness Suite (zorunlu — SOP-3)

- [ ] Walk-forward: 3y IS / 6m OOS, step 3m, 12 dilim
- [ ] Random param perturb: k ±%10, 50 seed → ort. Sharpe kaybı < %25
- [ ] Symbol-out CV: her sembolü çıkar, ort. OOS değişmesin (±%20)
- [ ] Regime split: bull (2020-2021, 2024) / bear (2022) / range (2023, 2025) — en az 2 rejimde pozitif
- [ ] Stress: LUNA 2022-05, FTX 2022-11, Yen-carry 2024-08, BTC-ATH 2024-03 — yıkıcı kayıp yok
- [ ] Shuffle baseline (yön shuffle), p < 0.05 (BH-FDR sonrası)
- [ ] Bonferroni (n=270) ve BH-FDR (q=0.05) raporlama zorunlu
- [ ] Lookahead test: causality test (`detector(df.iloc[:t+1])[t] == detector(df)[t]`)

## 9. Curve-fit Şüphesi (explicit flag)

Bu hipotez 4 yönden curve-fit riskli:

1. **Parameter sweep**: 270 koşum → multiple testing inflation; BH-FDR uygulanmazsa "best k seçtim" en az 13-14 false positive üretir (270 × 0.05).
2. **Prior reject mass**: 4 önceki reversal-at-level family reddedildi; bu seed o prior'a karşı çıkıyor — gerekçesiz "bu defa farklı" sayılmaz.
3. **Fixed-axis seçimi**: stop_atr_mult=1.5, rr=2.0 sweep edilmiyor — bu değerler ÖNCE seçildi, sonrasında değişirse hipotez geçersiz olur. Eğer terfi adayı olur ama "1.5 yerine 2.0 stop daha iyi" çıkarsa, **yeni hipotez** yazılır.
4. **Anchor seçimi**: UTC 00:00 keyfi; weekly anchor, swing-high anchor gibi alternatifler bu sweep'in dışında — terfi olursa anchor sweep'i **ayrı bir hipotezdir**.

## 10. Reproducibility

- `git_hash`: backtest koşulduğunda hash dondurulur.
- `data_hash`: `data/market.duckdb` MD5 raporda.
- `config_hash`: backtest config sha256 raporda.
- Backtest engine: `backtest/engine.py` (vectorized, lookahead-safe).
- Sembol evreni: survivorship-aware (`lessons/survivorship_kripto.md`).

## 11. Beklenen Sonuç (apriori)

- **%75 prior:** Tüm sweep p_gross > 0.05, reversal-at-level family confirmation #5. Arşivle.
- **%20 prior:** 1-3 koşum p_gross < 0.0002 ama OOS / per-year / regime split yıkar. Curve-fit kanıtı, reddet.
- **%5 prior:** Robustness suite tamamen geçer → Lab tournament adayı. AVWAP'ın session-anchor özelliği gerçekten farklı bir bilgi taşıyor demektir.

## 12. Stop-criteria özeti (TL;DR)

Aşağıdakilerden HERHANGİ BİRİ → REJECT + arşiv:
- >%95 koşum p_gross > 0.5
- net mean_R ≤ 0
- IS Sharpe / OOS Sharpe > 1.5 (overfit)
- Best k sweep kenarında
- Single symbol/year >%50 baskın
- BH-FDR (q=0.05) sonrası 0 survivor
