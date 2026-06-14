---
doc_id: researcher-20260602T093000-marubozu-continuation-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-02T09:30:00Z
status: PROPOSED
confidence: low
depends_on:
  - shared-lesson-smc-course-no-edge
  - shared-lesson-overfitting-red-flags
  - shared-lesson-lookahead-zero-tolerance
  - researcher-20260602-htf-continuation-diversifier
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, low-corr-to-vsa, single-bar-momentum, marubozu, pre-registration, curve-fit-watch]
supersedes: null
hash: null
---

# HYP-2026-06-02: Bearish Marubozu Continuation (low-corr-to-vsa-climax)

## 1. Pre-registration metadata
- **Hipotez ID:** HYP-2026-06-02-marubozu-continuation
- **Versiyon:** 0.1 (frozen by commit at write time)
- **Author:** researcher
- **Champion strateji (cross-corr referansı):** vsa_climax_test (active)
- **Pre-registration timestamp:** 2026-06-02T09:30:00Z

## 2. Çalışan iddia (tek cümle, ölçülebilir)

> 1h timeframe'de, **bearish marubozu** (gövde / range ≥ 0.90, kapanış low'un ≤ %5'i içinde, açılış high'ın ≤ %5'i içinde) tetiklendikten sonra **t+1 mumun open'ında short giriş**, 1.5×ATR(14) SL ve 1.5×ATR(14) TP ile, 15 sembollü USDT-perpetual evreninde, 55bps round-trip fee + 5bps slippage altında, son 3 yılda:
> - net mean R per trade > +0.05R
> - shuffle baseline p_gross < 0.05 (yön karıştırılmış null'u yenmek zorunda)
> - net daily-Sharpe bootstrap 95% CI alt sınırı > 0
> - vsa_climax_test ile günlük PnL korelasyonu |ρ| < 0.20
> - MaxDD < %25 (champion DD + %5 toleransı)
> üretir.

## 3. Null hipotez (NE OLURSA reddederim)

- H0a (yön-null): Bearish marubozu sinyalleri **kapanış-bazlı yön karıştırması** (per-symbol shuffle) ile beraber test edildiğinde, gerçek mean R, shuffle dağılımının %95 üstüne çıkamaz → **REJECT**.
- H0b (sıfır-Sharpe trap, HTF dersi): Korelasyon `|ρ| < 0.20` olsa bile **net daily-Sharpe bootstrap CI 0'ı kesiyorsa** ⇒ "uncorrelated noise" = diversifier DEĞİL → **REJECT**.
- H0c (fee-cinayeti): mean_R_gross > 0 ama 55bps sonrası mean_R_net ≤ 0 ise → **REJECT** (single-bar pattern fee floor'una takılır).
- H0d (rejim-bağlı): Sadece tek rejimde pozitif (örn sadece 2022 bear), bull/range rejimlerinde negatifse → **REJECT** (overfit to tail-regime).

## 4. Gerekçe (RAG referansları)

- **[Bulkowski via book_candlestick_statistics #8]:** "Closing Black Marubozu" — gövde range'in ≥%90'ı, bearish continuation rate **%64**, average move **%4.9**, performance rank **22/103**. Equity universe'de orta sınıf bir momentum continuation sinyali.
- **[book_candlestick_statistics #2 — kontrast]:** "Inside bar" breakout WR yalnızca %54 (rank 78/103) — yani tek-bar momentum (marubozu) > tek-bar consolidation (inside bar). Mantıklı prior farklılığı.
- **[Kaufman #5, ATR breakout]:** k×ATR-from-open ile entry — marubozu de facto bunun **kapanış-onaylı** versiyonu (intra-bar stop emir yerine bar-close onaylı stop emir). Daha geç giriş, ama lookahead riski düşük.
- **[López de Prado #1]:** PBO, DSR, IS-Sharpe>3·OOS-Sharpe kırmızı bayrakları zorunlu kontrol listemde.
- **[Shared lesson `smc-course-no-edge`]:** crypto bar-OHLCV → yön mapping'i 4 farklı SMC mekanizmasında ~rastgele çıktı; marubozu da **single bar OHLCV** → aynı tuzağa düşme prior olasılığı YÜKSEK. Kendi araştırmama karşı paranoid olmam gereken birinci sebep.

## 5. Korelasyon argümanı (vsa_climax_test ile düşük olmalı — neden?)

- vsa_climax_test → **reversal/exhaustion** prior (volume spike + reversal candle).
- marubozu continuation → **trend-strength / no-rejection** prior (uzun gövde, kuyruk yok).
- İkisi DESIGN olarak zıt iki market state'ten beslenir. Aynı barda her ikisi birden tetiklenemez (volume climax mum genelde uzun kuyruklu, marubozu kuyruksuz). **Beklenen ρ aralığı: -0.10 ila +0.15.**
- Eğer ρ > +0.20 çıkarsa: sinyallerden birinin tanımı diğerine sızıyor (kontamine pattern logic) → kod auditi başlat.

## 6. Backtest setup (donmuş)

| Parametre | Değer |
|---|---|
| Universe | 15 sembol, futures_universe_active_v2 (delisting-included) |
| Timeframe | 1h (primary) + 1d trend filter (none — pure intra-bar test) |
| Period | 2023-06-02 → 2026-06-02 (3y) |
| In-sample / OOS | walk-forward 4 fold (9m IS / 3m OOS, step 3m) |
| Side | short-only (marubozu bearish; long-only tarafı **AYRI** hipotezde test edilir, multiple-testing'i bozmasın) |
| Entry | t mum kapanış onayı, **t+1 mum open** |
| SL | 1.5×ATR(14) entry'den yukarı |
| TP | 1.5×ATR(14) entry'den aşağı (1R:1R baseline) |
| Position size | risk_pct=0.005, max_concurrent=8 |
| Fees | 7.5 bps taker (round-trip 15 → effective 55 bps incl slippage) |
| Slippage | 5 bps |
| Initial equity | 10,000 USDT |

## 7. Independent variables (parametre uzayı — DAR)

- **body_to_range_min:** {0.85, 0.90, 0.95} (3 değer)
- **close_to_low_pct:** {3, 5, 7} (3 değer)
- **atr_period:** {14} (sabit, optimize EDİLMEZ — kanonik Wilder)
- **atr_mult_sl_tp:** {1.0, 1.5, 2.0} (3 değer, SL=TP)

Toplam: **3 × 3 × 1 × 3 = 27 config**. n_trials cap = 27. **Bonferroni floor α' = 0.05/27 ≈ 0.00185.** Optuna kullanılmayacak — grid search, çünkü 27 nokta zaten makul, Optuna gradient illüzyonu yaratır.

## 8. Dependent variables (raporlanacak metrikler)

| Metrik | Hedef | Kapı tipi |
|---|---|---|
| mean_R_gross | > 0 (zaten triviyal) | sanity |
| mean_R_net (55bps) | > +0.05R | **hard gate** |
| shuffle p_gross (1000 seed, per-symbol direction-shuffle) | < 0.05 | **hard gate** |
| daily-Sharpe net | bootstrap 95% CI lower > 0 | **hard gate** |
| MaxDD (net, equity-based, NOT cumulative-PnL-based — CT-RSK-01 dersi) | < 25% | **hard gate** |
| Profit factor net | > 1.15 | soft |
| WR | n/a (yalnız report) | info |
| Trade count | ≥ 200 | sanity (yetersizse istatistik anlamsız) |
| ρ(daily PnL, vsa_climax_test daily PnL) | abs < 0.20 | **hard gate** (yoksa diversifier değil) |
| IS Sharpe / OOS Sharpe ratio | ≤ 3.0 (López kırmızı bayrak) | **hard gate** |
| PBO (Probability of Backtest Overfitting) | < 0.5 | **hard gate** |

## 9. Beklenen p-value & multiple testing

- **Pre-Bonferroni hedef:** p_gross < 0.01
- **Post-Bonferroni hedef** (27 trial): p < 0.00185
- **Benjamini-Hochberg FDR** ek olarak hesaplanacak (Bonferroni çok katı; rapor karşılaştırmalı olacak).

## 10. STOP CRITERIA (early-kill — para/zaman/iz tasarrufu)

Aşağıdakilerden biri tetiklenirse araştırma **derhal** terk edilir:

1. İlk 5 config'ten 5'inde **trade_count < 50** → marubozu tanımı bu evrende çok nadir, anlamlı istatistik kuramayız → STOP.
2. **Lookahead audit** (causal detector test): `detector(df[:t+1])[t] != detector(df)[t]` çıkarsa → STOP + sinyal kütüphanesine bug raporu.
3. mean_R_gross negatif AND shuffle baseline pozitif: yön ters olabilir; o zaman **long-marubozu** hipotezini ayrı dosyada test et, mevcut dosyayı RED kapat (yön-flip overfit kapısı **kabul edilmez**, aynı hipotezde "yön çevir" curve-fit).
4. **vsa_climax_test ile günlük PnL korelasyonu** ilk 3 fold OOS'ta **abs > 0.30** → hipotezin temel motivasyonu (diversifier) çürüdü → STOP.
5. IS/OOS Sharpe ratio > 5 (López kırmızı bayrak ekstrem) → overfit kesin → STOP.

## 11. Curve-fit ŞÜPHE NOKTALARI (peşinen ifşa)

> Bu bölümün varlığı pre-registration'ın özüdür. Bilerek aramamı yapacağım curve-fit'leri **şimdiden** yazıyorum ki rapor sonunda "bu zaten beklenmiyordu" diyebileyim.

1. **body_to_range eşiği aşırı parametreye duyarlıysa** (örn 0.90'da pozitif, 0.88'de negatif, 0.92'de negatif) → kesinlikle overfit; eşik gürültü kenarında.
2. **atr_mult tek ekstrem değerde (örn sadece 2.0'da)** pozitif → trade sayısı çok düşmüş, az sayıda büyük winner edge'i taşıyor → **shuffle p azalır ama daily-Sharpe CI 0'ı keser** (HTF dersi tekrarlanır).
3. **WR yüksek (>%55) ama mean_R düşük (<+0.02R)** → fee floor'una takılan asimetrik trade dağılımı → continuation prior fee'yi karşılamıyor.
4. **Pozitif edge'in %60+'ı bir tek sembolden (genelde 2022 BTC short trendinden)** → rejim-overfit. Symbol-out CV'de ortalama OOS düşer.
5. **Aynı bar'da hem entry hem exit** (intra-bar SL hit + TP hit) → backtest mantığı SL'i öncelikli sayıyor mu? Hipotetik MAE/MFE conservative-fill audit.
6. **Bulkowski rakamları (rank 22, %64) equities — crypto'da büyük sapma** prior'ı; eğer crypto'da %64 continuation çıkıyorsa o zaman **shuffle baseline'ı da yüksek çıkmalı** (long bear trend baseline'ı). Net edge shuffle'ı yenmiyorsa o %64 sadece market drift, sinyal değil.
7. **HTF continuation dersinden tekrar:** uncorrelated + zero-Sharpe = NOT diversifier. ρ<0.20 + net-Sharpe-CI-straddles-0 → REJECT zorunlu, "az korelasyon var, stack edelim" YASAK.

## 12. Robustness suite (zorunlu — SOP-3)

Tüm 27 config içinden hard-gate-survivor olanlar (varsa) için:
1. Walk-forward 4 fold OOS pozitif fold ≥ 3/4.
2. Param perturb: her parametre ±%10, 50 seed → ortalama net mean_R kaybı < %30.
3. Symbol-out CV: her sembolü dışarıda bırak; min Sharpe ortalamanın %50'sinden büyük.
4. Regime split: bull/bear/range — en az 2/3 pozitif net mean_R.
5. Stress periods: 2024-08 Yen carry, 2024-03 BTC ATH, 2025-Q1 (yeni dilim) — none < -%10 DD.
6. Shuffle baseline p_gross < 0.05 (1000 seed direction-shuffle).
7. Bonferroni 0.05/27 ≈ 0.00185 düzeltmesi raporlanacak.

## 13. Lab teslim koşulu

Tüm hard-gate'lerden (§8) + tüm robustness suite testlerinden (§12) geçen **EN FAZLA 1 config** Lab tournament'a teslim edilecek. 1'den fazla survivor varsa **en az parametrik ucta olan** seçilir (içe doğru, kenar değil).

## 14. Gelecek adımlar (otomatik takip)

- Backtest çalıştığında: `reports/research/marubozu-continuation/2026-06-02-baseline.html`
- Sonuç ne olursa olsun: `memory/researcher/learning.md`'ye 3 satırlık ders.
- RED ise: `memory/shared/lessons/`'a "single-bar momentum patterns in crypto OHLCV — REJECT" kümülatif dersini güncelle (3. red olursa **sınıfı kapat**).
- ACCEPT ise: SOP-4 + Lab tournament (vsa_climax_test challenger slot).

## 15. Skeptiğin notu (kendi kendime)

Crypto OHLCV bar-yön mapping'i son 4 araştırmada (SMC ×4, HTF continuation, Fabio order-flow) ~rastgele çıktı. Marubozu da **aynı modaliteden besleniyor**. Bu hipotezin **base-rate beklentisi REJECT**. ACCEPT çıkarsa şüphem 3 kat artar — Lab tournament'a teslim etmeden önce **adversary_engineer kill-probe** mecburi (bkz `requested_review_from`). Bulkowski'nin %64 sayısı 1980-2010 equities'den; crypto perpetual continuous-trading + funding mekaniği farklı oyun. Karar: literatür prior'ı **zayıf delil**, sayı kazanır.
