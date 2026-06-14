---
doc_id: researcher-20260602T090000-kaufman-rsi-divergence-sr-confluence-forex-4h
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-02T09:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [kaufman, rsi_divergence, sr_confluence, forex, 4h, mean_reversion, high_curve_fit_risk, multiple_testing_risk]
supersedes: null
hash: null
---

# HYP-2026-06-02 — Kaufman RSI Divergence + S/R Confluence (Forex 4H Majors)

## 0. Pre-registration kimliği
- ID: `kaufman-rsi-divergence-sr-confluence-forex-4h`
- Versiyon: **0.1 — DRAFT** (kod yazmadan önce dondurulacak)
- Author: researcher
- RAG seed: günlük tarama (2026-06-02); Kaufman ch. "RSI Divergence" + Lopez "DSR" + Grimes "art and science" framework
- Differentiation: 2026-06-01-grimes-anti-rsi-div-climax-fade (CRYPTO 1H, climax-bar tabanlı) ile ÖRTÜŞMEZ. Bu hipotez **forex 4H**, **climax-bar filtresi YOK**, **S/R yakınlığı zorunlu**.

## 1. İddia (ölçülebilir, tek cümle)
> **4H** timeframe'de, **EUR/USD, GBP/USD, USD/JPY, AUD/USD** evreninde, son **20 swing-bar** içinde **RSI(14) bullish/bearish divergence** (price LL + RSI HL / price HH + RSI LH) tespit edildiğinde, divergence noktası **son 200 barlık yatay S/R çizgisinden ≤ 0.5×ATR(14)** mesafedeyse, divergence yönünde **confirmation candle** (engulf veya pin) close'unda giriş, stop divergence ekstrem'inin **0.25×ATR ötesi**, hedef **2R fixed**, son **6 yıl** (2020-01-01 → 2026-01-01) survivorship-clean (delisting yok — major pairs) HistData evrende:
>
> - Net annualized return (fees 2.5 bps + slippage 1.5 bps dahil) **> %8** (forex modest)
> - Sharpe (4H bar annualized) **> 0.8**
> - MaxDD on **equity-base** (zero-base PnL DEĞİL — bkz. CT-RSK-01 dersi) **< %12**
> - Profit factor **> 1.4**
> - Trade sayısı **N ≥ 120** (toplam, 4 pair × 6yıl)
> - Win rate **40-55%** aralığı (Kaufman claim için sanity bound; dışına çıkarsa kalıp farklı işliyor)
>
> üretir.

## 2. Null hipotezler (ne olursa çürür)
- **H0a — direction shuffle:** Aynı evrende, aynı entry/exit kurallarıyla ama divergence yönü **rastgele** (50/50 long/short) atanırsa, gerçek edge ile shuffle baseline arası fark **p ≥ 0.05** (1000 seed) → yön sinyali tesadüf, RED.
- **H0b — multiple testing:** Walk-forward + parametre sweep'in toplam trial sayısı `n_trials`'a göre **Benjamini-Hochberg FDR düzeltmesi** uygulanır; düzeltme sonrası `p ≥ 0.05` → curve-fit, RED.
- **H0c — IS/OOS gap:** In-sample Sharpe ↔ OOS Sharpe **fark > %50** → overfit, RED. (memory/shared/lessons/lesson-2026-05-08-overfit-redflags.md §1)
- **H0d — walk-forward stability:** 6 yıl / 6 dilim (1y train / 6m test, step 6m) içinde dilimlerin **≥ %50**'sinde net negatif → istikrarsız edge, RED.
- **H0e — DSR (Lopez):** Deflated Sharpe Ratio **< 0.6** → "kararsız, daha çok veri" — terfi BLOCK.
- **H0f — Anti-edge symbol:** 4 sembolün **≥ 2**'sinde OOS Sharpe < 0 → sinyal pair-spesifik, generalize değil, RED.
- **H0g — Half-life sanity (Chan):** Eğer entry sonrası ortalama bar-tutuş > 30 bar (≈ 120 saat → 5 gün) → mean-reversion DEĞİL, drift/random walk → setup yanlış sınıflandırılmış, RED.

## 3. Dependent variables (ölçülen metrikler)
| Metrik | Hedef | Reddetme eşiği |
|---|---|---|
| Net annualized return | > 8% | < 4% veya negatif → RED |
| Sharpe (OOS) | > 0.8 | < 0.4 → RED |
| MaxDD (equity-base) | < 12% | > 20% → RED veya SOP-4b iterate |
| Profit factor | > 1.4 | < 1.1 → RED |
| Trade sayısı | ≥ 120 | < 80 → istatistiksel anlamsız, REJECT or DEFER |
| Win rate | 40-55% | aralık dışı → manifest hata |
| DSR | > 0.6 | < 0.5 → DEFER |
| Shuffle p-value | < 0.05 | ≥ 0.05 → RED |
| Bonferroni/FDR sonrası p | < 0.05 | ≥ 0.05 → RED |
| Walk-forward pozitif dilim oranı | ≥ %60 | < %50 → RED |
| Avg bar holding time | ≤ 30 bar | > 30 bar → setup yanlış, RED |

## 4. Independent variables (parametre uzayı — DAR tutuldu; curve-fit riskini sınırla)
| Parametre | Aralık | Adım | Justification |
|---|---|---|---|
| RSI period | {14} | tek değer | Kaufman klasik, optimize ETME (literatür sabit) |
| Divergence lookback | {10, 14, 20} | 3 nokta | minimal sweep |
| S/R proximity (×ATR) | {0.25, 0.5, 0.75} | 3 nokta | sıkı bant |
| ATR period | {14} | tek değer | klasik |
| SL buffer (×ATR) | {0.15, 0.25, 0.40} | 3 nokta | dar |
| TP (R-multiple) | {1.5, 2.0, 2.5} | 3 nokta | dar |
| Confirmation candle | {engulf, pin, either} | 3 nokta | enum |

**Toplam trial: 3×3×3×3×3 = 243.** Bu sayı **Bonferroni eşiği için: 0.05 / 243 = 0.00021**, FDR (BH) sonrası ~0.05/log(243) ≈ 0.009.

**Curve-fit kırmızı bayrak ön-bildirimi:** En iyi parametre kombinasyonu aralık ekstremlerinde çıkarsa (örn TP=2.5 veya S/R proximity=0.25 sınırda) **otomatik DEFER** — aralık genişlet, tekrar test.

## 5. Beklenen p-value (önceden taahhüt)
- **Raw shuffle p < 0.01** beklenmektedir (eğer hipotez doğruysa).
- **FDR düzeltmesi sonrası p < 0.009** olmak ZORUNDA; üstündeyse hipotez RED.
- **Direction-shuffle gerçek edge farkı**: en az **0.05R / trade** (≈ 5 bps net), aksi takdirde "yön bilgisi yok" — memory'deki SMC/Fabio dersi.

## 6. Stop criteria (araştırma terkedilir)
1. **Erken IS Sharpe < 0.3** → Optuna'dan önce abort.
2. **Causality testi fail** (`detector(df.iloc[:t+1])[t] != detector(df)[t]` herhangi bir bar'da) → kod hatası, lookahead → ABORT.
3. **Direction-shuffle gross edge** ≥ real gross edge → yön sinyali yok, ABORT. (memory/shared/lessons SMC ve Fabio'da bu ile öldü.)
4. **HistData veri kalite raporu** 4H için major gap > %1 ise → DEFER (data_engineer ticketle).
5. **Holding time > 30 bar ortalama** → Chan half-life sanity fail, RED.
6. **2 sembolde negatif OOS** → pair-spesifik, sistem değil, RED.

## 7. Curve-fit / data-leakage / multiple-testing risk envanteri (şeffaflık)
| Risk | Skor (1-5) | Mitigation |
|---|---|---|
| Multiple testing (243 trial) | **4/5** | BH-FDR düzeltmesi zorunlu, DSR (Lopez §9) ek gate |
| Pair-spesifik overfit (4 major) | **3/5** | symbol-out CV her sembol için tekrar |
| Divergence lookback p-hack riski | **3/5** | sadece 3 nokta, ekstremde DEFER kuralı |
| Lookahead (RSI divergence retrospective swing tanımı) | **5/5** | divergence detector causality testi şart — swing high/low **causal**: t bar'da sadece t-2 ve geçmiş swing'ler |
| HistData survivorship | **1/5** | major pairs delisting yok |
| Regime overfit (2020-2026 pencere) | **3/5** | walk-forward 6 dilim + COVID-2020, USD strength 2022, Yen 2024 stress dilimleri ayrı raporlanır |
| "Mantıklı hikâye" bias (Kaufman'a sempati) | **3/5** | shuffle null + DSR gate; narrative gerekçe ile yatkınlık önleme |

## 8. Robustness suite (SOP-3 — zorunlu)
- [ ] Walk-forward 6 dilim (1y train / 6m test, step 6m)
- [ ] Parameter perturbation ±%10, 50 seed → avg Sharpe loss < %25
- [ ] Symbol-out CV (4 pair leave-one-out)
- [ ] Regime split: USD up-trend / USD down-trend / range
- [ ] Stress dilimleri: 2020-03 COVID, 2022-09/10 USD strength, 2024-08 Yen carry unwind
- [ ] Shuffle baseline (direction shuffle, 1000 seed) — p < 0.05
- [ ] DSR > 0.6 zorunlu
- [ ] FDR (BH) düzeltmesi 243 trial üzerinden

## 9. Karar matrisi (taahhüt — sonradan kayma yok)
| Sonuç | Karar |
|---|---|
| Tüm hedef metrikler ✓ + tüm robustness ✓ | Lab tournament adayı (forex 4H champion challenge) |
| ROI > 0 ama MaxDD > %20 veya Sharpe 0.4-0.8 arası | **SOP-4b iterate** — risk azaltma / confluence filter / regime subset (RED YASAK, pozitif edge'i koru) |
| Direction-shuffle p ≥ 0.05 | RED, gerekçeli arşiv |
| FDR sonrası p ≥ 0.05 | RED — curve-fit |
| Holding time > 30 bar | RED — kalıp yanlış sınıflandırılmış |
| ≥ 2 pair OOS negatif | RED — generalize değil |

## 10. RAG referansları (alıntı)
- **[Kaufman, "RSI Divergence" bölümü]** — Setup: bullish div (price LL + RSI HL) → confirmation candle (engulf/hammer) → long. Stop: divergence low altı. Hedef: 2-3R. Failure: "strong trend'de divergence saatlerce/günlerce devam eder; filtrelenmemiş tek başına RS[I]…" → ben S/R confluence + 4H'de filtreliyorum, ama hâlâ failure modunu açık raporlayacağım.
- **[Lopez, "DSR" §9]** — DSR < 0.5: rastlantı; [0.5, 0.6]: kararsız; [0.6, 0.95]: kabul edilebilir; > 0.95: güçlü. Ben **≥ 0.6** eşiği koydum; bu literatür-taahhütlü, sonradan kayma yapamam.
- **[Grimes, "art and science" çerçevesi]** — istatistiksel disiplin + price action sezgisi; null hipotez ve walk-forward zorunlu. Ben Grimes'ın disiplinine uyuyorum.
- **[Chan, half-life]** — mean-reversion Sharpe ∝ 1/√half-life. Beklenen holding time ≤ 30 bar (≈ 120 saat ≈ 5 gün) ise edge gerçek mean-rev; üstüyse drift, setup yanlış sınıflandırılmış. Bu **H0g**'yi otomatik kontrol eder.

## 11. Reproducibility
- git_hash: <fill after commit>
- config_hash: <fill after config freeze>
- data_hash: HistData 4H major pairs 2020-01-01 → 2026-01-01 MD5
- backtest engine version: <vectorbt vX.Y>

## 12. Şüphe çerçevesi (kendi kendine "strong opinions, loosely held")
- **En büyük şüphem:** "RSI divergence + S/R" çok popüler bir setup; piyasada bu kadar arbitraj edilmiş olabilir → edge sıfır beklemeliyim. Kaufman da başarı için "confluence-based" diyor — yalın divergence yetmez. S/R proximity 0.5×ATR bandı bunu test ediyor.
- **İkinci şüphem:** Divergence detector swing-high/low tanımı **lookahead-kapı**. Causal swing (sadece geçmiş 5 bar üzerinden teyitli swing) implementasyonu yapılmazsa rapor şişer. Signal Chief audit isteyeceğim.
- **Üçüncü şüphem:** 4 pair = küçük örneklem; pair-spesifik şans yüksek. Symbol-out CV ile filtre. Eğer EUR/USD edge'i tüm Sharpe'ı üretiyorsa → RED, USDJPY/AUDUSD/GBPUSD ayrı pozitif olmalı.

## 13. Tahmini etki (eğer hipotez doğru çıkarsa)
- Forex 4H paper bot adayı — düşük frekans (≈ 30 trade/yıl/pair), düşük capital cost.
- Mevcut crypto portfolio ile **düşük korelasyon** (farklı market, farklı saat) → marginal Sharpe **pozitif** beklentisi.
- Forex live SPK-bloklu (memory: forex-4h-research-status.md) → sadece paper-only deploy. Live deploy = kapsam dışı.

## 14. Sonraki adım (kod öncesi)
1. Bu doc commit edilir (hash dondurulur).
2. Lab Scientist + Risk Officer + Adversary Engineer review (SLA 24h, Risk 6h).
3. Signal Chief'a "causal RSI divergence detector lookahead audit" ticketı.
4. Data Engineer'a "HistData 4H major pairs 2020-2026 manifest + gap raporu" ticketı.
5. Tüm onaylar ve veri OK → backtest config'i türet ve `backtest/engine.py` çalıştır.

---
**Kabul kriteri yeniden taahhüt (kayma engelle):**
Bu hipotezin numerik hedefleri (§1, §3) bir kez commit edildikten sonra, backtest sonucu zayıf çıkarsa hedefleri **AŞAĞI çekemem** — RED ya da SOP-4b iterate.
