---
doc_id: researcher-20260601T130000-grimes-anti-rsi-div-climax-fade
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-01T13:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [grimes_anti, counter_trend, climax_fade, rsi_divergence, confluence, high_curve_fit_risk]
supersedes: null
hash: null
---

# HYP-2026-06-01 — Grimes "Anti" + RSI Divergence Climax Fade (Crypto Perpetual)

## 0. Pre-registration kimliği
- ID: `grimes-anti-rsi-div-climax-fade`
- Versiyon: **0.1 — DRAFT** (kod yazmadan önce dondurulacak)
- Author: researcher
- RAG seed: günlük tarama (2026-06-01); Grimes ch.“Anti” + Kaufman ch.“RSI Divergence”

## 1. İddia (ölçülebilir, tek cümle)
> **1H** timeframe'de, top-15 likit USDT-perp evreninde, son **20 bar** içinde **ATR(14) > 2.0×** ve **Bollinger(20, 2σ) dışına basan** bir climax bar oluştuğunda, climax bar yönünde **bearish/bullish RSI(14) divergence** (lookback 14 bar) varsa, climax bar kapanış yönünün **TERSİNE**, climax ekstrem'in **0.25×ATR ötesi**'nde stop ve **2R fixed TP** ile alınan pozisyon — son **3 yıl** (2023-06-01 → 2026-06-01) survivorship-clean evrende:
>
> - Net annualized return (fee+slip dahil) **> %25**
> - Sharpe (252×24 saatlik bar annualized) **> 0.8**
> - MaxDD on **equity-base** **< %20**
> - Profit factor **> 1.3**
> - Trade sayısı **N ≥ 300** (istatistik için minimum)
> - Win rate **35-50%** aralığında (Grimes claim ~%40-45 dışına çıkarsa setup ya farklı işliyor ya da kalıp bozulmuş)
>
> üretir.

## 2. Null hipotez (ne olursa çürür)
- H0a: Aynı evrende **shuffle baseline** (climax bar sonrası rastgele yönde aynı SL/TP) ile pozitif fark **p ≥ 0.05** → edge tesadüf.
- H0b: Bonferroni düzeltmesi sonrası (n=parametre kombinasyon sayısı) anlamlılık kaybolursa → curve-fit.
- H0c: In-sample ↔ OOS Sharpe farkı **> %50** → overfit.
- H0d: 6 yıllık walk-forward dilimlerin **≥ %50**'sinde net negatif → istikrarsız edge.
- H0e: Mean R per trade **< 0.05R** (gross) → fee+slip altında negatife düşer.

## 3. Gerekçe (RAG referansları)
- **[Grimes 2012 “Anti” setup]** (RAG #3): overextended hareket sonrası ilk pullback'te kontra-trend pozisyon — climax bar, BB >2σ, ATR >2× tetik; win rate ~%40-45, R ~2-3, slight positive EV. **Uyarı: Grimes "deneyimli trader, yüksek iskontolu setup" diyor → mekanik backtest'te edge erimesi olağan.**
- **[Kaufman — RSI Divergence + Confirmation]** (RAG #6): trend-exhaustion noktalarında confluence; "RSI can stay overbought longer than you can stay solvent" — yani RSI tek başına yetmez, climax + price confirmation gerekli.
- **[Grimes — Transaction Cost & Over-leverage]** (RAG #4): backtest'te fee/slip ihmal etmek, leverage'i abartmak en yaygın illüzyon → konservatif (7.5bps taker + 5bps slip) zorunlu.
- **[Lopez DSR]** (RAG #9): trial sayısı arttıkça Sharpe deflate edilmeli; DSR > 0.6 minimum kabul.
- **[Chan — Half-life]** (RAG #5): mean-reversion yapılarda half-life kısa olmalı; "Anti" 1-3 bar hedefli kısa pullback fade — 1H'de half-life ~6-24 bar bekliyoruz.

## 4. Dependent variables (önceden taahhüt)
| Metric | Eşik | Yön |
|---|---|---|
| Net annualized return (fee+slip net) | > %25 | büyük iyi |
| Sharpe (annualized) | > 0.8 | büyük iyi |
| **DSR (Lopez)** | > 0.6 | büyük iyi |
| MaxDD (equity-base) | < %20 | küçük iyi |
| Profit factor | > 1.3 | büyük iyi |
| Trade sayısı N | ≥ 300 | büyük iyi |
| Win rate | 35-50% | aralık kontrolü |
| Mean R per trade (net) | > 0.05R | büyük iyi |
| Shuffle p-value | < 0.05 | küçük iyi |
| IS/OOS Sharpe farkı | < %50 | küçük iyi |

## 5. Independent variables (parametre uzayı — DONDURULDU)
| Param | Range | Adım | Cardinality |
|---|---|---|---|
| ATR-overextension threshold | [1.5, 2.5] | 0.25 | 5 |
| BB sigma threshold | [1.5, 2.5] | 0.5 | 3 |
| RSI lookback | [10, 20] | 5 | 3 |
| RSI divergence min angle (price/RSI) | [5°, 15°] | 5° | 3 |
| Stop multiplier (× climax-extreme dist) | [0.2, 0.4] | 0.1 | 3 |
| TP (fixed R) | [1.5, 3.0] | 0.5 | 4 |
| Entry tetik (close-of-confirm vs next-open) | {close, next_open} | — | 2 |

**Toplam grid:** 5×3×3×3×3×4×2 = **3 240 kombinasyon**.
Bonferroni eşiği: **α = 0.05 / 3240 ≈ 1.54e-5** → bu seviyede anlamlılık zor, **FDR (Benjamini-Hochberg) q=0.05 kullanılacak.**

## 6. Beklenen p-value
- Shuffle baseline p ön-taahhüdü: **< 0.01** (raw)
- Bonferroni sonrası: **< 0.05** (q-value, BH-FDR)
- Eğer raw p < 0.05 ama BH-FDR sonrası p > 0.10 → hipotez **REJECT** (curve-fit).

## 7. Stop criteria (araştırmayı bırakma koşulları)
- **A.** In-sample Sharpe **< 0.5** → terkedilir, iterate yok (gerçek edge yok).
- **B.** Trade sayısı 3 yıl × 15 sembol × 1H universe'de **N < 100** → setup çok nadir, istatistik anlamsız.
- **C.** Mean R per trade gross **< 0.1R** → fee+slip kapasitemiz altında, ölü.
- **D.** Best parametreler grid'in **sınırında** (örn ATR-overext = 2.5 max, BB-σ = 2.5 max) → uzay yetersiz, **GENİŞLET** ve yeniden test; 2. tur da sınırda kalırsa terkedilir.
- **E.** Lookahead causality testi başarısız → **derhal reject** (kod hatası, yeniden yaz).
- **F.** Sembol-out CV'de **min Sharpe < 0** ve bu single coin tüm P&L'in **> %40**'ını taşıyor → tek-sembol artefakt.

## 8. İterate niyeti (SOP-4b — proaktif)
Eğer aylık ROI > 0 ama MaxDD > %30 → **REDDETME, ITERATE**:
- v2: risk_pct 0.005 → 0.002
- v3: + confluence_score filtre (sadece RSI div angle > 10°)
- v4: + regime filter (yalnız sideways/range rejim — climax fade trend'de zayıf)
- v5: + BE-protect 1R sonrası SL→entry

## 9. Curve-fit kırmızı bayrakları (SELF-FLAG — proaktif)
**Bu hipotezde overfit riski YÜKSEKtir. Sebepler:**

1. **7 parametre × 3 240 kombinasyon** — TPE optimizer kolayca 1.5+ Sharpe "bulur"; FDR olmadan kabul etmek p-hacking olur.
2. **"Confluence" stack** — overextension + BB + RSI div + confirmation 4 koşul; her biri bağımsız filtre değil, korelasyonlu; etkilerini ayıklamak için **ablation study** zorunlu (her koşulu tek tek çıkar, Sharpe düşüşünü ölç; düşmüyorsa koşul fuzuli).
3. **Grimes'ın orijinal evreni** equity/futures, **bizim evrenimiz** crypto perpetual — climax bar frekansı farklı (crypto'da %2σ outside daha sık), Grimes claim'i direkt taşınamaz.
4. **Counter-trend kategorisi crypto'da tarihsel olarak kötü performans gösterdi** (LUNA, FTX, USTC, post-ATH 2024 koşulları kontra-trend short'u yedi). Stress test (SOP-3 #6) bu setup için kritik.
5. **"First pullback"** subjektif kavramı — operasyonalizasyonda iki seçenek (close-of-confirm vs next-open) zaten lookahead riski taşır; nasıl tanımlandığı dondurulmalı.
6. **Win rate beklentisi %40-45** ile **N ≥ 300** birleşince standard error ~%2.8 → "%50 üzeri kazandı" gibi marjinal sapmalar şans olabilir.
7. **High-discount setup** (Grimes'ın kendi tabiri) — yıllarda 5-15 kez tetiklenmesi normal, mekanik tetikçi (every-bar evaluator) bunu **suni şekilde sıklaştırırsa** edge erir.

**Bu bayrakların 4+'sı yakalanırsa hipotez Bonferroni öncesi reject — gate'i geçse bile.**

## 10. Reproducibility çapaları
- Universe snapshot: `data/universe/2026-06-01_top15_usdtperp.parquet`
- Data hash: TBD (backtest run-time'da yazılır)
- Code hash: TBD
- Config hash: TBD
- Random seed: 42 (Optuna ve shuffle için sabit)

## 11. Robustness suite checklist (SOP-3 — tamamı zorunlu)
- [ ] Walk-forward 3y/6m, step 3m (8 dilim)
- [ ] Param perturb ±%10, 50 seed → mean Sharpe loss < %25
- [ ] Symbol-out CV (15 fold) → min OOS Sharpe > 0
- [ ] Regime split (bull/bear/range, 2023-2026) → ≥ 2 rejimde pozitif
- [ ] Stress periods: 2024-03 (ATH), 2024-08 (Yen carry), 2025-Q1-Q4 koşul ne olursa
- [ ] Shuffle baseline p < 0.05
- [ ] Bonferroni / BH-FDR (n=3240)
- [ ] Lookahead causality test
- [ ] Ablation study (4 confluence koşulunu tek tek çıkar)

## 12. Karar matrisi (önceden tanımlı)
| Sonuç | Karar |
|---|---|
| Tüm DV ✓ + tüm robustness ✓ | TERFI → Lab tournament |
| ROI > 0 ama MaxDD > %30 | İTERATE (SOP-4b) |
| ROI ≤ 0 veya lookahead bulundu | REJECT — gerekçeli arşiv |
| Bonferroni/FDR fail | REJECT — curve-fit |
| Trade N < 100 | REJECT — setup yok |
| 4+ kırmızı bayrak yakalandı | REJECT — yapı sorunlu |

## 13. İmza
Pre-registered by: researcher
Hash freeze (commit): bu doc commit edildikten sonra parametre uzayı değiştirilemez; değişirse v0.2 yazılır ve `supersedes` ile bağlanır.

---

**NOT (kendime):** Bu hipotezin RAG'de %40-45 win rate "claim"i Grimes'ın equity evreni içindi. Crypto'da bunu replikasyon **çok zor** — büyük olasılıkla SOP-4'te REJECT veya İTERATE'e düşeceğini şimdiden tahmin ediyorum (`learning.md`'ye not: counter-trend hipotezlerinin %80'i red oldu, beklenti calibrate edilmiş).
