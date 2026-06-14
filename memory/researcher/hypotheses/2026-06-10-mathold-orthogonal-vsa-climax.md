---
doc_id: researcher-20260610T143000-mathold-orthogonal-vsa-climax
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-10T14:30:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, mathold, cross_strategy, low_correlation, momentum_continuation, pre_registration]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-10-mathold-orthogonal-vsa-climax

**Pre-registered — kod yazılmadan önce dondurulmuş hipotez.**

- Tarih: 2026-06-10
- Versiyon: 0.1
- Seed konu: Cross-strategy edge — aktif `vsa_climax_test` ile düşük korelasyonlu ek sleeve.

---

## 1. İddia (tek cümle, ölçülebilir)

> "1D timeframe'de, USDT-perpetual evreninde (delisting dâhil, 2023-01-01 → 2026-04-30), Mat Hold 5-bar continuation pattern'ı (Bar1 büyük bullish: body ≥ 1.50 × ATR20; Bar2–4 küçük inside: her biri body ≤ 0.50 × Bar1 body VE üçü de Bar1 body range içinde; Bar5 close > Bar1 close), Bar5 kapanışında alım — 1.5 ATR SL, 2.5 ATR TP, taker fee 7.5 bps + 5 bps slippage altında ŞUNLARI üretir:
> - Net annualized return > **%25**
> - OOS Sharpe (walk-forward 12-fold) > **0.8**
> - MaxDD (% equity) < **%20**
> - Profit factor > **1.3**
> - Trade sayısı ≥ **150** (istatistik güç eşiği)
> - **|ρ(mathold_daily_returns, vsa_climax_test_daily_returns)| < 0.25** (birincil cross-strategy hedefi)"

---

## 2. Null Hipotez (ne olursa hipotezim çürür)

- **H0-A:** Mat Hold sinyali shuffle baseline'ı yenemez → raw p ≥ 0.05.
- **H0-B:** |ρ(mathold, vsa_climax_test)| ≥ 0.40 → cross-strategy diversifikasyon değeri yok; ortogonal sleeve iddiası reddedilir.
- **H0-C:** López altı kriterinden ≥ 1 kırmızı (PBO > 0.5 VEYA IS/OOS Sharpe > 3× VEYA serbest_param/sample > 1/30).

---

## 3. Gerekçe (RAG referansları)

- **[book_candlestick_statistics — Mat Hold]:** Bulkowski stats: %74 bullish continuation rate, average move %6.1, rank **10/103**. "Flag pattern'ının mum versiyonu — konsolidasyon sonrası momentum korunur."
- **[book_brooks_deep_catalog]:** Mekanik kalıplar için skala 5 — "tamamen kodlanabilir, en iyi hipotez adaylarından biri."
- **[book_kaufman_summary]:** Trend/continuation ailesinin retail-realistic Sharpe band'ı 0.6–1.0; >1.5 iddiası suspicious. Hedefimiz (OOS > 0.8) bu band'ın alt yarısında — agresif değil.
- **[book_lopez_summary]:** Bu hipotez López altı kriterine tabi tutulacak; özellikle PBO ve IS/OOS oranı.
- **Cross-correlation prior:** vsa_climax_test bir **exhaustion/reversal** sinyali (yüksek hacim + range expansion + reversal bar). Mat Hold ise **continuation** sinyali (trend devamı). Mekanik yapı zıt → düşük korelasyon prior'u makul, ama garantili değil (aynı makro rejim ortak risk-on/off bileşeniyle yapay korelasyon doğurabilir — bkz §8).

---

## 4. Dependent Variables (önceden ilan, sonradan değişmez)

| Değişken | Tanım | Birincil/İkincil |
|---|---|---|
| Net annualized return | fee+slip dâhil, equity-curve CAGR | Birincil |
| OOS Sharpe | WF 12-fold ortalaması | Birincil |
| MaxDD | % equity peak-to-trough | Birincil |
| Profit factor | gross_win / gross_loss | Birincil |
| Trade count | toplam dolu trade | Gate |
| **ρ_mathold_vs_vsaclimax** | daily-aligned per-strategy return Pearson ρ | **Birincil (cross-strategy)** |
| Win rate | info-only | Bilgi |
| IS Sharpe | López §1 kriteri için | Bilgi |

---

## 5. Independent Variables (parametre uzayı — KASITLI DAR)

| Parametre | Aralık | Değer sayısı | Gerekçe |
|---|---|---|---|
| Bar1 body / ATR20 | {1.25, 1.50, 1.75} | 3 | "İri" tanımı |
| Inside body / Bar1 body | {0.40, 0.50, 0.60} | 3 | "Küçük" tanımı |
| Inside bar sayısı | **sabit 3** | — | Bulkowski mekanik tanımı; optimize EDİLMEZ |
| SL × ATR20 | {1.0, 1.5, 2.0} | 3 | |
| TP × ATR20 | {2.0, 2.5, 3.0} | 3 | |
| Yön | **sabit long-only** | — | Pattern bullish-only tanımlı |

**Toplam grid: 3 × 3 × 3 × 3 = 81 kombinasyon.** Bonferroni base = 81.
**Serbest parametre sayısı = 4.** López §1 (params / sample > 1/30) için trade sayısı ≥ 120 yeterli; ≥150 hedefliyoruz.

---

## 6. Beklenen p-value (önceden ilan)

- **Shuffle baseline** (returns shuffle, 1000 iter): raw p < **0.01** beklenir.
- **Bonferroni düzeltmesi** (n=81): adjusted p < **0.05** sınırında olmalı.
- **Bonferroni adjusted p ≥ 0.05 → "ilginç ama RED" — gate'i geçemez.**

---

## 7. Stop Criteria (araştırma terkedilir / aday değil)

| Kriter | Eşik | Sonuç |
|---|---|---|
| In-sample Sharpe | < 0.5 | DERHAL terk (zaman harcama) |
| IS Sharpe / OOS Sharpe oranı | > 3.0 | overfit — RED (López §1) |
| Trade sayısı | < 100 | istatistik güç yetersiz — RED |
| ⎮ρ_mathold_vs_vsaclimax⎮ | ≥ 0.40 | cross-strategy değeri yok — sleeve iddiası RED (ama strateji tek başına geçebilir) |
| WF dilimi pozitif oranı | < 7/12 | tutarsız — RED |
| Stress dönemleri (LUNA/FTX/USDC/Yen) | herhangi birinde dilim DD > %35 | tail risk — RED |
| Shuffle baseline raw p | ≥ 0.05 | gerçek edge yok — RED |
| Bonferroni adjusted p | ≥ 0.05 | aday değil — RED |
| Best params parametre grid sınırında (örn TP=3.0 OR SL=1.0) | true | grid genişletilmeli, ön sonuç REDDE yakın |

---

## 8. Curve-Fit Şüphesi (öz-eleştiri, önceden ilan)

**Bu hipotez yüksek curve-fit/repro riski taşıyor — önceden açıkça yazıyorum ki sonradan "p-hacked" suçlamasından kaçınayım:**

1. **Bulkowski stats stock-based (US equities, ~1990-2010).** Crypto 1D'de %74 continuation rate REPRODÜKE OLMAYABİLİR. Crypto intraday vol stoklara göre 3-5× yüksek; "küçük inside bar" stok evreninde anlamlı, kriptoda 3 ardışık %2'lik bar'ın "küçük" sayılması absürt olabilir.
2. **5-bar pattern → düşük sinyal yoğunluğu.** 3 yıl × ~40 sembol bile <150 trade üretebilir → istatistik güç düşer, Bonferroni'yi geçmek zor.
3. **Eşik hassasiyeti.** Bar1 body eşiği 1.25 → 1.75 arası geçişte sinyal sayısı 2-3× değişebilir; bu hassasiyet curve-fit risk sinyali.
4. **Cross-correlation hedefimle ilgili naif beklenti.** ρ < 0.25 hedefi mekanik-zıt-yapı prior'una dayanıyor; ama aynı evren + aynı makro rejim → ortak risk-on/off bileşeni ρ'yu yapay yükseltir. Gerçekte ρ ≈ 0.30-0.50 çıkması ihtimal yüksek.
5. **TP/SL grid'i geniş (9 kombinasyon)** → Bonferroni cezası şişer. Bu hipotez Bonferroni'yi atlatmak için tasarlanmadı; gerçek edge varsa geçer, yoksa geçmez.
6. **Survivorship riski:** Universe `data/universe.py::build_universe(date)` ile zaman-bilinçli kurulacak; delisting dâhil. Aksi takdirde RED.
7. **Lookahead riski:** Pattern detection vectorize, `df.shift(-1)` YOK, karar Bar5 close'da → giriş Bar5 close (1D bar'da close=open of next session simulator); bu kural CI'da `tests/test_lookahead.py`'a çakılacak.

**Bu öz-eleştirinin pre-registration'ı, hipotezi sonradan revize etmemi YASAKLAR.** Sonuç gelirse, yukarıdaki riskler ışığında okunur.

---

## 9. Robustness Suite (SOP-3, zorunlu)

- [ ] Walk-forward 12-fold (3y/6m, step 3m), Optuna n_trials=100 TPE + Median pruner
- [ ] In-sample / Out-of-sample Sharpe fark < %30
- [ ] Random param perturbation: ±%10, 50 seed, ortalama Sharpe kayıp < %25
- [ ] Symbol-out CV: leave-one-out, min OOS Sharpe > 0.5
- [ ] Regime split: bull/bear/range → en az 2'sinde pozitif Sharpe
- [ ] Stress: LUNA 2022-05, FTX 2022-11, USDC depeg 2023-03, Yen 2024-08 → dilim DD < %35
- [ ] Shuffle baseline (1000 iter): raw p < 0.05
- [ ] Bonferroni / FDR (n=81): adjusted p < 0.05
- [ ] **Cross-corr with vsa_climax_test:** 90-day rolling ρ, daily-aligned per-strategy returns; ortalama |ρ| < 0.25 → sleeve OK
- [ ] Lookahead test: `detector(df.iloc[:t+1])[t] == detector(df)[t]` her t için ✓
- [ ] Causality test: Bar5 close kararı → Bar5+1 open giriş (1D'de aynı bar close, intraday'de değil)

---

## 10. Karar Çerçevesi (run-after)

```
1. RAG'den ne öğrendim? — Mat Hold continuation, Bulkowski rank 10/103, stock'ta %74 continuation.
2. Hipotez? — Crypto 1D Mat Hold, vsa_climax_test'e ortogonal momentum sleeve.
3. Null? — Shuffle yenilemez VEYA |ρ| ≥ 0.40 VEYA López kırmızı.
4. Pre-registered metrikler? — §4
5. Backtest sonucu? — PENDING
6. Robustness suite? — PENDING
7. Karar? — PENDING (terfi adayı / iterate / RED)
8. Gerekçe? — PENDING
```

---

## 11. Reproducibility (run-time doldurulacak)

- git_hash: PENDING
- config_hash: PENDING
- data_hash: PENDING (universe snapshot date)
- random_seed: 42 (Optuna), 1337 (shuffle), 7 (perturbation)
- backtest engine: `backtest/engine.py` (vectorbt)
- universe builder: `data/universe.py::build_universe(date)`

---

## 12. SOP-4 / SOP-4b Iterate Bridge

**Eğer:** edge pozitif (aylık ROI > 0) AMA DD veya başka risk gate'i ihlal ederse → **RED YASAK** (SOP-4b). v2 patikası açılır:

- v2-risk-reduction: SL 1.5 → 1.0 ATR, TP 2.5 → 2.0 ATR (R:R sabit)
- v3-confluence: + 1W EMA50 trend filter (sadece bull HTF)
- v4-volz-filter: + vol_z(20) > 0 (sadece yüksek vol)
- v5-bb-cluster: vsa_climax_test ile aynı gün açılan trade'ler skip (decorrelate by exclusion)

Her v# yeni hipotez doc'u olarak pre-register edilir.

---

**Bu doküman `git commit` ile dondurulur. Sonuçtan sonra revizyon = yeni doc + `supersedes`.**
