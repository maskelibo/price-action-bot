---
doc_id: researcher-20260629T060000-kaufman-rsi-divergence-chan-halflife-filter-4h
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-29T06:00:00Z
status: DRAFT
confidence: low
depends_on:
  - researcher-20260601T130000-grimes-anti-rsi-div-climax-fade
  - researcher-20260614T020100-chan-halflife-filtered-climax-fade-1d
  - researcher-20260612T000000-grimes-anti-climax-fade-4h-chan-halflife-prescreen
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags:
  - hypothesis
  - rsi-divergence
  - kaufman
  - chan-halflife
  - mean-reversion
  - crypto-4h
  - pre-registration
  - confluence-stacking-risk
  - high-curve-fit-risk
supersedes: null
hash: null
---

# HYP-2026-06-29 — Kaufman RSI Divergence × Chan Half-life Filter (4H Crypto Perp)

## 0. Niyet ve A Priori Beklenti

- **Versiyon:** 0.1 (pre-registration; kod yazılmadan ve veriye bakmadan dondurulur).
- **Seed konu:** Günlük tarama — yeni RAG ekleri ışığında PA edge sinyalleri.
- **Tetik farkı (önceki Anti/climax denemelerinden):** Bu hipotezin **giriş tetiği RSI bullish/bearish divergence** (Kaufman RAG #6). Climax-fade (Grimes Anti) hipotezleri ATR-tabanlı "extension bar" tetiği kullanıyordu; bu farklı. Half-life filtresi *sembol seçim ekseni* olarak ortak kalıyor (multiple-trial inflation riski açık).
- **A priori beklenti:** **NEGATİF**. Kaufman'ın kendi uyarısı bağlayıcı: *"RSI can stay overbought longer than you can stay solvent."* Trend rejiminde divergence aylarca yanlış sinyal verir. Chan filtresi bunu *kısmen* azaltır (sadece kısa-half-life sembollerde fade alır) ama tek başına kurtarmaz. Confluence-stacking (Kaufman + Chan) klasik overfit yatağıdır; bu hipotezin **terfi olasılığı düşük tahmin ediliyor**.

## 1. İddia (TEK CÜMLE, ölçülebilir, sayılı)

> 4H timeframe'de, USDT-perpetual delisting-aware evrende (2021-01-01 → 2026-05-01), her sembol için trailing **240-bar (40 gün) AR(1) lag-1 katsayısı β** üzerinden hesaplanan **half-life = −log(2) / log(β)** **[12 bar, 96 bar]** (yani 2–16 gün) aralığında olan sembollerde, **RSI(14)** üzerinde son **30 bar penceresinde bir bullish divergence** (fiyat lower-low, RSI higher-low, swing-point ZigZag tepe-dip pencere=5) tespit edildiğinde, **divergence-confirming candle** (engulfing veya hammer; *kapanış bilgisi sadece*) bir sonraki barın **açılışında long** açılır (mirror bearish için short); **SL = divergence low/high ± 0.30 × ATR_120**, **TP = 2R**, **risk_pct = 0.005**, **fee + slip round-trip 55 bps**, **per-symbol max 1 açık poz**. Bu setup 5y OOS walk-forward'da AYNI ANDA:
>
> - **mean_R_net > +0.08 R** (Kaufman'ın "low frequency / high edge per trade" iddiasıyla uyumlu güvenlik payı)
> - **annual_return_net (compounded) > %12**
> - **MaxDD (account-equity bazlı) < %22**
> - **N_trades ≥ 200** (4H + dar evren → power gereksinimi)
> - **shuffle-direction p_gross < 0.05** (50 seed)
> - **DSR (López, trial-count = 5) > 0.6**
> - **Filtre-içi Sharpe / Filtre-dışı Sharpe ≥ 1.4** (yani Chan half-life ekseni gerçekten değer kattı — yoksa filtre gürültü)
> - **Plasebo (rastgele yönlü entry, aynı evren+filtre) Sharpe < 0.3** (sembol-seçimi confound yok)
>
> sağlar.

## 2. Null Hipotezleri (ne olursa çürür)

- **H0a:** shuffle-direction baseline'da p_gross ≥ 0.05 → yön sinyali yok.
- **H0b:** Filtre-içi / Filtre-dışı Sharpe < 1.4 → Chan ekseninin marjinal katkısı yok; RSI div tek başına kalır — Kaufman'ın "yalnız RSI yetmez" uyarısı kanıtlanır.
- **H0c:** Plasebo (rastgele-yön) Sharpe ≥ 0.3 → kazanç sembol-seçimi confound'undan; RSI div sinyali değil.
- **H0d:** IS / OOS Sharpe farkı > %50 → overfit.
- **H0e:** Aile düzeyinde (3 climax-fade + 1 RSI-div + Chan filtreli = 4 deneme; aile FDR=BH α=0.05) p ≥ düzeltilmiş eşik → multiple-trial inflation.
- **H0f:** Half-life bandı perturbasyonunda {[8,72], [16,120], [10,80]} Sharpe sıralaması zıt → eşik gürültü.
- **H0g:** Divergence ZigZag pencere parametresi {3, 7} alternatiflerinde mean_R işaret değiştirirse → tetik tanımı gürültü.

## 3. Gerekçe (RAG referansları)

- **[Kaufman book_summary, RAG #6]** — RSI divergence: trend-exhaustion sinyali; **confluence-based; düşük frekans ama yüksek edge per trade**. Confirmation candle (engulfing/hammer) ZORUNLU. Açık uyarı: *"RSI can stay overbought longer than you can stay solvent — filtrelenmemiş tek başına RSI div yetmez."* → Chan filtresi bu uyarıya cevap girişimi.
- **[Chan book_summary, RAG #5]** — Mean-reversion Sharpe ∝ 1/√half-life. RSI divergence MEKANİĞİ mean-reversion; half-life [12, 96 bar 4H] = 2-16 gün; Chan'ın 1-60 gün "tradeable" aralığının orta-kısa bölmesi.
- **[Grimes book_summary, RAG #3, #4, #8]** — Anti-setup mantığı (kontre-trend, climax sonrası) yapısal benzer; ama bizim tetiğimiz ATR-climax DEĞİL RSI div. Grimes'ın WR ~%40-45 / R ~2-3 beklentisi bu hipotez için baseline tahmin (mean_R_net > +0.08 hedefi muhafazakar).
- **[López book_summary, RAG #9]** — DSR > 0.6 zorunlu; trial-count = 5 (3 climax-fade + 1 RSI-div + 1 Chan-filtreli volman varyantı) varsayımıyla deflated.
- **[Grimes book_summary, RAG #4]** — "Ignoring transaction costs in backtests" → 55 bps round-trip muhafazakar.

## 4. Dependent Variables (önceden kilitli — backtest sonrası dolacak)

| Metrik | Tanım | Hesap |
|---|---|---|
| `mean_R_net` | Trade başına ort. R, fee+slip dahil | Trade close |
| `annual_return_net` | Compounded annualized net return | Equity curve |
| `max_dd_equity` | Account-equity bazlı MaxDD | Equity curve |
| `n_trades` | Filtre-içi toplam trade sayısı | Backtest sonu |
| `win_rate` | (R>0) / N | Tüm trade |
| `p_gross_shuffle` | 50 seed direction-shuffle null karşı p | Bootstrap |
| `sharpe_in_filter` | Half-life ∈ [12,96] evrendeki Sharpe (OOS) | WF |
| `sharpe_out_filter` | Half-life ∉ [12,96] evrendeki Sharpe (OOS) | WF |
| `filter_value_ratio` | sharpe_in / sharpe_out (≥ 1.4 hedef) | Hesaplanmış |
| `dsr` | Deflated Sharpe (trial = 5) | López formülü |
| `placebo_sharpe` | Rastgele-yön entry aynı evren+filtre Sharpe | 50 seed |
| `per_year_pos_count` | 5 yılın kaçında yıllık R_net > 0 | Yıllık dilim |
| `is_oos_sharpe_ratio` | IS Sharpe / OOS Sharpe | WF |

## 5. Independent Variables (DAR tut — multiple-testing kontrolü)

**KİLİTLİ baseline:**
- `tf`: **4H**
- `rsi_period`: **14**
- `divergence_lookback`: **30 bar** (5 gün; Kaufman "swing-to-swing" pratiğine uyumlu)
- `zigzag_swing_window`: **5 bar** (swing-point algılama)
- `confirmation_candle`: **engulfing OR hammer** (kapanış tespit, *next-bar open entry*)
- `atr_window`: **120 bar**
- `sl_offset_atr`: **0.30 × ATR_120**
- `tp_R`: **2.0**
- `risk_pct`: **0.005**
- `fee_round_trip_bps`: **55**
- `halflife_lookback`: **240 bar (40 gün)**
- `halflife_band`: **[12, 96] bar = [2, 16] gün** (4H bağlamında Chan'ın 1-60 gün aralığının orta-kısa dilimi)
- `per_symbol_max_open`: **1**

**Robustness (post-baseline; SOP-3 zorunlu; kararı DEĞİŞTİRMEZ):**
- `rsi_period` ∈ {9, 21} — perturbation
- `divergence_lookback` ∈ {20, 40} — perturbation
- `zigzag_swing_window` ∈ {3, 7} — H0g testi
- `halflife_band` alternatif: {[8,72], [16,120], [10,80]} — H0f testi
- `sl_offset_atr` ∈ {0.20, 0.40} — perturbation
- `tp_R` ∈ {1.5, 2.5} — perturbation
- `confirmation_candle` alternatif: **engulfing-only** ve **hammer-only** — confluence-katmanı kırılganlığı

## 6. Curve-fit Şüpheleri (a priori AÇIK BEYAN)

> Bu hipotez **özellikle yüksek curve-fit risklidir**. Aşağıdaki riskler kayda geçirilir; backtest sonucu bunların hiçbirini "şanslı" çıkmış sayılmamalı:

1. **Confluence-stacking.** RSI div + Chan half-life + confirmation candle = 3 katmanlı filtre. Her ek katman post-hoc seçim alanı genişletir. SOP-3'te HER katmanın *tek başına* etkisi ayrı raporlanmalı; bir katmanın katkısı yoksa sadeleştirilmiş alternatif öncelikli.
2. **Half-life bandı [12, 96] keyfi.** Chan 1-60 gün dedi; "4H için orta-kısa" diye [12, 96] bar = 2-16 gün seçtim → veriye göre ayarlanırsa overfit. H0f testi zorunlu.
3. **ZigZag swing-window = 5 keyfi.** Swing-point algoritması parametre-duyarlı; {3, 7} testleri ile kırılganlık kontrolü H0g.
4. **AR(1) tahmini gürültülü.** 240 barlık trailing pencerede β'nın SE'i geniş. Rolling şart (look-ahead riski yok); ama tahmin gürültüsü → filtre kararı gürültülü → edge yok olabilir.
5. **5. trial.** 3 climax-fade denemesi + 1 Volman 4H + bu = 5 deneme ailesi. BH FDR α=0.05 ile düzeltilmiş eşik kullanılacak. Düzeltme sonrası anlamlılık kalmazsa RED.
6. **Sembol-seçimi confound.** Half-life filtresi tüm stratejilerde tutarlı şekilde "daha iyi semboller" üretiyor olabilir → bu hipotezdeki Sharpe iyileşmesi tetiğe atfedilemez. **Plasebo testi zorunlu** (rastgele-yön Sharpe < 0.3 gate; H0c).
7. **4H "no man's land".** 4H, 1D ve 15m'in arasında, ikisinde de güçlü olmayan bir rejim olabilir. Önceki 4H Volman-iii denemesi sonucu bu seçim için tahsisli prior değil.
8. **Kaufman'ın açık uyarısı.** *"RSI can stay overbought longer than you can stay solvent."* Bu hipotezin Chan filtresi olmadan **yenilmesi beklenir** — filtre gerçekten kurtarıyor mu, yoksa filtre + tetik kombinasyonu sadece şanslı bir N=küçük örnekte iyi göründü mü? Plasebo + H0b birlikte bunu test eder.

## 7. Beklenen p-value & Sample Size

- **Naive shuffle:** p < 0.01
- **Family-corrected (n = 5 deneme, BH FDR α=0.05):** düzeltilmiş eşik backtest sonucunda hesaplanır; geçilmezse RED.
- **DSR (López, trial = 5):** > 0.6 zorunlu.
- **N_trades:** ≥ 200 zorunlu; 4H + filtre ile bu eşiğin altına düşme riski yüksek → düşerse "power yok → terk" (RED değil).

## 8. Stop Criteria (kod yazmadan dondurulur)

| Tetik | Aksiyon |
|---|---|
| IS Sharpe < 0.4 | terk (araştırma durdurulur) |
| N_trades < 150 | terk (power yok) |
| IS/OOS Sharpe farkı > %50 | RED (overfit) |
| Walk-forward 10 diliminin ≥ %50'si negatif | RED (istikrarsız) |
| LUNA (2022-05) veya FTX (2022-11) diliminde DD > %30 | RED (stres dayanıksız) |
| Filtre-içi / filtre-dışı Sharpe < 1.4 | RED (Chan ekseni gürültü, H0b) |
| Plasebo Sharpe ≥ 0.3 | RED (sembol-seçimi confound, H0c) |
| ZigZag swing-window perturbasyonunda mean_R işaret değişimi | RED (tetik gürültü, H0g) |
| Half-life bandı perturbasyonunda Sharpe sıralaması zıt | RED (eşik gürültü, H0f) |
| BH FDR (aile=5) sonrası anlamsız | RED (multiple-trial inflation) |
| DSR < 0.6 | RED (López şüphe eşiği) |
| Best param parametre uzayının uç köşesinde | RED (overfit kırmızı bayrak) |

## 9. Robustness Plan (SOP-3 alt küme — zorunlu)

1. **Walk-forward:** 3y train + 6m test, step 3m (10 dilim, 5y span).
2. **Symbol-out CV:** her sembol tek tek dışlandığında ortalama OOS değişmemeli (max %15 sapma).
3. **Regime split:** bull (2021-Q1, 2024-Q1) / bear (2022-H1, 2025-Q1) / range (2023-H2, 2024-H2) — en az 2'sinde net pozitif.
4. **Stress periodları:** 2022-05 LUNA, 2022-11 FTX, 2024-08 Yen carry — yıkıcı kayıp yok (DD < %12 dilim-içi).
5. **Shuffle baseline:** direction-shuffle 50 seed, p < 0.05.
6. **Half-life bandı perturbasyonu:** {[8,72], [16,120], [10,80]} — Sharpe sıralaması istikrarlı mı?
7. **ZigZag swing-window perturbasyonu:** {3, 7} — mean_R işaret istikrarlı mı?
8. **Plasebo:** rastgele-yön entry, filtre-içi/dışı Sharpe oranı (H0c gate).
9. **Katman-ablasyon:** (a) sadece RSI div + confirm (Chan KAPALI), (b) sadece Chan filtre + rastgele yön, (c) tam stack — hangi katman kaç bps katıyor?
10. **Multiple-testing düzeltme:** BH FDR aile=5 climax-fade/RSI/Chan denemeleri.

## 10. Karar Çerçevesi (post-backtest doldurulacak)

```
1. 8 gate'in tümü sağlandı mı? ✓/✗
2. Stop criteria'dan herhangi biri tetiklendi mi? ✓/✗
3. Filtre-içi/dışı Sharpe ≥ 1.4? ✓/✗ (kritik)
4. Plasebo Sharpe < 0.3? ✓/✗ (kritik)
5. Katman-ablasyon: hangi katman gerçekten katkı sağlıyor? (kayda geç)
6. BH FDR sonrası anlamlılık? ✓/✗
7. Karar: terfi adayı / iterate (SOP-4b) / RED / deferred
```

## 11. Iterate Politikası (SOP-4b — Pozitif Edge'i KORU)

Eğer **mean_R_net > 0** AMA gate'lerden ≥1'i RED (özellikle MaxDD veya DSR):

- **v2-tighter-band:** halflife_band [16, 72] (daha seçici evren); risk_pct 0.005 → 0.003
- **v3-confirmation-strictest:** sadece engulfing (hammer çıkar) + RSI extreme zorunlu (>70 / <30)
- **v4-time-exit:** 24 bar (4 gün) içinde TP/SL değilse pozisyon kapat (mean-reversion thesis süresi dolar)
- **v5-be-protect:** 1R sonrası SL → BE; trailing %30 peak'ten
- **v6-regime-gate:** sadece trend-NEUTRAL rejimde aç (200-EMA flat ± %5)

Edge gerçek ama gate'lerde değilse → **"deferred"** arşiv (RED değil). Iterate budget = 5 versiyon.

## 12. Reproducibility

- git_hash: (backtest çalıştırılırken doldurulur)
- config_hash: bu doc'un SHA-256'sı (Lab tarafından dondurulacak)
- data_hash: 2021-01-01 → 2026-05-01 OHLCV USDT-perpetual 4H snapshot (delisting-aware)
- backtest seed: 42 (sabit)
- backtest engine: backtest/engine.py @ HEAD
- universe builder: data/universe.py::build_universe(asof=t) — zaman-bilinçli (CT-DAT-01 uyumlu)
