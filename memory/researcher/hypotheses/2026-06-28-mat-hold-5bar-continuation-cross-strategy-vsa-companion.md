---
doc_id: researcher-20260628T060000-mat-hold-5bar-continuation-cross-strategy-vsa-companion
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-28T06:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, pre-registration, cross-strategy, mat-hold, candlestick, continuation, vsa-companion]
supersedes: null
hash: null
---

# HYP-2026-06-28-mat-hold-5bar-continuation-cross-strategy-vsa-companion

## 1. Hipotez (pre-registered, ölçülebilir)

> "**1D timeframe**'de, mevcut 18-sembol kripto perpetual evreninde, **Mat Hold 5-bar bullish continuation** kalıbı (Bulkowski tanımı: Bar1 büyük bullish bullish bar; Bar2-4 Bar1 gövdesinin %110 aralığında kalan küçük bar'lar; Bar5 Bar1 close'unu aşan büyük bullish bar) — Bar5 close'unda alımla, SL = setup-low − 0.5×ATR(14), TP = 2R, max-hold 10 bar, risk = %0.5/trade, fee = 7.5 bps taker + 5 bps slip — 2023-01-01 → 2025-12-31 dönemi out-of-sample tarama sonucunda:
> - **Net annual return > %18** (fee + slip dahil)
> - **OOS Sharpe > 0.8** (Chan single-asset eşiği, RAG #9)
> - **MaxDD < %22** (account equity üzerinden, hesaplanma CT-RSK-01 standardı)
> - **Profit factor > 1.35**
> - **vsa_climax_test ile günlük getiri korelasyonu |ρ| < 0.20** (1D resample, son 250 ortak trade-günü)
> - **Trade sayısı ≥ 80** (istatistik anlamlılık eşiği)
> - **Bullish continuation realized rate ≥ %58** (Bulkowski'nin %74'ü kripto'da bir miktar zayıflar varsayımı; bu eşik %58'in altına düşerse "kalıp kripto'da bozulmuş" hükmü)
> üretir."

**Null hipotez (H0):** Mat Hold 5-bar continuation kalıbının kripto perpetual 1D evrenindeki net annual return'ü, shuffle baseline'dan (returns rastgele yer değiştirilmiş) istatistiksel olarak ayırt edilemez (p ≥ 0.05, shuffle 1000 iter).

## 2. Gerekçe (RAG referansları)

- **[RAG #10 — book_candlestick_statistics, Bulkowski Mat Hold]** Bullish continuation rate %74, average move %6.1, performance rank **10/103** — Bulkowski'nin en güçlü continuation kalıplarından biri. "Flag pattern'ının mum çubuğu versiyonu, konsolidasyon sonrası momentum korunur."
- **[RAG #6 — book_market_structure_order_flow]** "Wyckoff Phase C Spring" gibi yapısal kalıpların kripto 1D'de mekanik çalışabilirliği "Orta-Yüksek" — Mat Hold da benzer kategoride: net kural, backtestable, az parametrik.
- **[RAG #9 — book_chan_summary]** Sharpe-based strategy gating: yeni stratejiler için OOS Sharpe > 0.8 (single asset) eşiği. Bu hipotezdeki gate buradan türedi (hand-pick değil, literatür referansı).
- **[RAG #1 — book_lopez_summary]** López de Prado'nun 6-kriter overfit kontrol listesi (DSR < 0.5, PBO > 0.5, IS Sharpe > 3·OOS Sharpe, params/sample > 1/30) — robustness suite buna uyumlu olacak.

**Cross-strategy edge gerekçesi:** vsa_climax_test = volume climax + reversal (mean-reversion karakter). Mat Hold = consolidation + continuation breakout (momentum karakter). Mekanik olarak ters yönlü sinyaller → negatif veya düşük korelasyon **a priori** bekleniyor. Bu bir hipotezdir, ispat değil; **ρ < 0.20 koşulu** ayrı bir test olarak ölçülecek.

## 3. Dependent Variables (önceden belirlenmiş metrikler)

| Metrik | Hedef |
|---|---|
| Net annualized return | > %18 |
| OOS Sharpe (annualized, equity-based) | > 0.8 |
| MaxDD (account equity, CT-RSK-01) | < %22 |
| Profit factor | > 1.35 |
| Win rate | info-only (no gate) |
| Trade sayısı | ≥ 80 |
| Realized continuation rate | ≥ %58 |
| Daily-return correlation vs vsa_climax_test | \|ρ\| < 0.20 |
| Shuffle-baseline p-value | < 0.05 |
| Bonferroni-düzeltilmiş p-value (n=66 shelf) | < 0.05 → α_individual < 0.000758 |

## 4. Independent Variables (önceden kilitli — perturbation listesi)

**Sabitlenen (fix-locked):**
- Timeframe = 1D
- Universe = mevcut 18-sembol futures evreni (uni-watchlist-candidate-cut sonrası)
- Bar1 büyüklük eşiği = ATR(14) × 1.0 (gövde ≥ 1×ATR)
- Bar2-4 inside-range tolerance = Bar1 gövdesinin %110'u (hafif overflow Volman varyantına izinli)
- Bar5 trigger = Bar1 close'unu kapanışta aşma
- SL multiplier = 0.5×ATR(14) (setup-low altına)
- TP = 2R fixed
- Max-hold = 10 bar
- Risk = %0.5/trade
- Fee = 7.5 bps taker, slip = 5 bps

**Perturbation grid (robustness suite — sweep için):**
- Bar1 gövde eşiği ∈ {0.75, 1.0, 1.25} × ATR
- Bar2-4 inside tolerance ∈ {%100, %110, %120}
- SL multiplier ∈ {0.3, 0.5, 0.7} × ATR
- TP-R ∈ {1.5, 2.0, 2.5}
- Max-hold ∈ {7, 10, 14} bar

**Toplam param uzayı = 3^5 = 243 kombinasyon** — bu sayı **kasıtlı olarak küçük** (over-fit yüzeyini sınırlamak için). Optuna kullanılmayacak; full grid, sonra Bonferroni.

## 5. Beklenen p-value & Multiple Testing Düzeltmesi

- **Shuffle-baseline H0 reddi:** p < 0.05 (1000 iter)
- **Bonferroni (243 grid kombinasyonu için):** α_individual = 0.05/243 = **0.000206** → t-stat ≥ ~3.7
- **Bonferroni (66-aday shelf seçim baskısı için, üst-katman):** α_individual = 0.05/66 = **0.000758** → Mat Hold'un 66 aday içinden seçilmesi de bir "trial"; bu nedenle iç-grid p-value'sunun aynı zamanda bu üst eşiği de geçmesi gerekir.
- **Birleşik etkili eşik:** α = 0.000206 × 0.000758 ≈ **1.6e-7** (konservatif, ortak Bonferroni). Bu sıkı eşiği geçen herhangi bir param kombinasyonu bulunamazsa hipotez **DROP**.

## 6. Stop Criteria (terkedilme koşulları — sıkı)

Hipotez aşağıdaki herhangi bir koşulda **anında terk edilir** (iterate dahi denenmez):

1. **In-sample Sharpe < 0.5** (default param ile 2023-2024 dilimi)
2. **Trade sayısı < 50** in-sample dilim sonunda → istatistik anlamsız
3. **Correlation gate fail:** |ρ| ≥ 0.30 vs vsa_climax_test → cross-edge amacı kayboldu (hipotez ana motivasyonu invalid)
4. **Realized continuation rate < %50** → Bulkowski'nin kalıbı kripto'da kırılmış demektir; hipotezin temel iddiası yanlış
5. **IS/OOS Sharpe farkı > %50** → overfit kırmızı bayrağı (RAG #1, López)
6. **Walk-forward 12 dilimden < 6'sı pozitif** → temporal stability yok
7. **Bonferroni-düzeltilmiş p-value > 0.05** → istatistik anlamsız
8. **Param uzayında "best" değer sınırda** (örn. SL=0.3 veya 0.7'de) → parametre uzayının dışında daha iyi olabilir, hipotez sınırlı; iterate v2 düşünülür AMA promote edilmez.

**Pozitif edge + kötü risk durumu:** SOP-4b devreye girer (iterate v2/v3). Pozitif aylık ROI ama DD > %30 ise REDDEDİLMEZ; risk-reduction iterate yazılır.

## 7. Curve-Fit Şüphesi & Pre-Mortem (zorunlu — kendime karşı)

**Bu hipotez neden başarısız olabilir / neden ben kendimi kandırıyor olabilirim:**

1. **Shelf-selection bias:** 66 aday içinden Mat Hold'u seçtim. "RAG'de rank 10/103" gerekçem güçlü görünüyor ama bu hâlâ bir cherry-pick — diğer 65 kalıp denenmeden bunun "en iyi olmaya yakın" olduğunu iddia edemem. Bonferroni n=66 düzeltmesi zorunlu (yukarıda).
2. **Bulkowski equities → crypto generalization:** Bulkowski stats hisse senedi piyasasından (US equities, daily, 1990-2010). Kripto perpetual'in 24/7 likidite, funding rate, microstructure açısından farklı olduğu kanıtlı. "%74 → %58'in üzerinde kalır" varsayımı kendi başına test edilmemiş bir alt-hipotez.
3. **5-bar pattern rare event problemi:** 1D evrende 3 yılda 18 sembol × ~750 bar = 13,500 bar; Bar1+Bar2-4+Bar5 spesifik geometriyi bekleyen kalıp seyrek tetiklenir. Trade sayısı 80'in altında çıkma riski yüksek → "istatistik anlamsız" tuzak.
4. **"Düşük korelasyon" iddiası timeframe asimmetrisinden gelir:** vsa_climax_test 15m'de çalışıyor, Mat Hold 1D'de. Korelasyonu 1D'ye resample ederken otomatik olarak düşürürüm — bu **mekanik artifact**, gerçek edge ayrışması değil. **Karşı önlem:** Mat Hold'u aynı zamanda 4H ve 1H'de de test et; korelasyon hâlâ < 0.20 mi? Sadece 1D'de düşükse hipotez "fake low correlation".
5. **"Continuation" kalıpları rejim-bağımlı:** Bull rejim'de continuation güçlü, bear/range rejim'de Bulkowski rank dramatik düşer. Regime split testinde 2'den fazla rejimde pozitif gerek; sadece bull'da iyi ise rejim-filtreli versiyon olarak iterate (rejim filtre içermesi hipotezi modifiye eder, ayrı hipotez sayılır).
6. **Inside-range tolerance %110 → Volman varyantı:** Bu "%110 hafif overflow" eşiğini ben hand-pick ettim çünkü Bulkowski'nin "tam inside" tanımı kripto'da çok dar olabilir. Bu zaten bir param-fitting tohumu. Perturbation grid'inde %100 / %110 / %120 her birini eşit ağırlık ile test edeceğim; tek bir değere ayar tutturmayacağım.

**Niçin hâlâ test ediyorum:**
- Bulkowski rank 10/103 nominal olarak güçlü bir prior
- Cross-strategy edge için yapısal olarak farklı (momentum vs reversal)
- 18+ önceki cross-companion hipotezimin çoğu seed-abort (negative edge) — Mat Hold daha önce denenmedi, gerçek bir "blank slate" test

**Beklentim:** %70 olasılıkla red (stop criteria 4 veya 6'dan), %20 iterate, **%10 promote**. Bu beklenti yüksek değil — sağlıklı.

## 8. Test Plan & Reproducibility

**Backtest engine:** `backtest/engine.py` (vectorbt, official)
**Walk-forward:** 3y train / 6m test, step 3m → 12 dilim
**Robustness suite:** SOP-3'ün tamamı (walk-forward, param perturb, symbol-out CV, regime split, stress periods 2022-05/2022-11/2024-03/2024-08, shuffle baseline, Bonferroni)
**Data:** DuckDB `data/ohlcv/futures_1d.parquet` (survivorship-bias-free; delisting'ler dahil — universe.build_universe(date) zaman-bilinçli)
**Hash:** git_hash + config_hash + data_hash sonuç raporuna yazılacak (`reports/research/mat-hold-5bar-2026-06-28.html`)

## 9. Beklenen Çıktılar

- `reports/research/mat-hold-5bar-cross-vsa-2026-06-28.html` — tam rapor
- Karar: **terfi adayı** / **iterate v2** (SOP-4b) / **red** (gerekçeli arşiv)
- Terfi durumunda → Lab tournament queue (`memory/lab_scientist/tournament_queue/`)
- Red durumunda → `learning.md`'ye 3 satır gerekçe + 66-aday shelf'ten "denendi → red" işareti

## 10. Lab/Risk Review Soruları

- **Lab Scientist'e:** Mat Hold'un drift detection profili nasıl olur? Tournament kabul için 80-trade alt-eşiğin DSR yeterli mi yoksa daha geniş window mu istersin?
- **Risk Officer'a:** %0.5 risk + 18-sembol evrende max-concurrent kaç olmalı? Mat Hold'un trigger seyrekliği nedeniyle aynı gün multiple tetik olası mı?

---

**Pre-registration commit:** Bu doküman commit edilmeden hiçbir kod yazılmayacak. Hash dondurulduktan sonra backtest başlar. Sonuç ne olursa olsun bu doküman **append-only** olarak `supersedes` ile bağlanır (revise → yeni doc).
