---
doc_id: researcher-20260608T093000-mathold-continuation-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-08T09:30:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, mat_hold, continuation, cross_edge, low_correlation, vsa_companion, curve_fit_risk]
supersedes: null
---

# Hipotez: HYP-2026-06-08-mathold-continuation-low-corr-to-vsa

- Tarih: 2026-06-08
- Versiyon: 0.1
- Pre-registration commit: pending (kod yazılmadan önce dondurulacak)

## 1. Bağlam ve Motivasyon

Aktif champion: **vsa_climax_test** — VSA tipi exhaustion/reversal edge'i (climax volume + wide-spread → mean-reversion). Portföye **düşük korelasyonlu** (|ρ| ≤ 0.20) bir companion strateji aranıyor. Rafta 66 aday var; bu hipotez bunlardan **Mat Hold** (Bulkowski candlestick #10) için pre-registration.

Yapısal cross-edge mantığı: vsa_climax_test bir **reversal** edge'idir; Mat Hold ise bir **trend-continuation** patternidir (büyük bullish bar → 3 inside konsolidasyon → breakout). Aynı bar üzerinde nadiren birlikte tetiklenmeleri beklenir → daily-return korelasyon düşük olmalı. Bu **yapısal hipotezdir, sayısal değil** — backtest ile teyit edilecek.

## 2. Iddia (ölçülebilir, pre-registered)

> 15m timeframe'de, top-30 likit USDT-perpetual evreninde (delisting-aware), 2023-01-01 → 2024-12-31 in-sample / 2025-01-01 → 2025-12-31 out-of-sample (walk-forward 6m train + 3m test, step 3m), aşağıdaki mekanik tanımlı Mat Hold stratejisi:
>
> - **Net annual return (OOS, fee+slip dahil)** ≥ **%30**
> - **OOS Sharpe** ≥ **1.0**
> - **MaxDD (OOS)** ≤ **%20**
> - **Live (daily-return) Pearson correlation with vsa_climax_test PnL** ≤ **|0.20|**
> - **OOS trade sayısı** ≥ **80** (istatistik yeterliliği)
> - **Profit factor (OOS)** ≥ **1.4**
>
> ÜRETIR.

### Mekanik Kural (dondurulmuş)

- **Bar 1:** Bullish bar; gövde / range ≥ 0.70 VE gövde ≥ 1.0 × ATR(14).
- **Bar 2–4:** 3 ardışık bar, hepsinin High ≤ Bar 1.High VE Low ≥ Bar 1.Low (gövde aralığı içinde sıkışmış).
- **Bar 5:** Bullish bar; Close > Bar 1.High; volume ≥ 1.2 × SMA20(volume).
- **Trend filtresi:** Bar 1 öncesi 20-bar slope (lineer reg) > 0 (yükseliş trend bağlamı zorunlu).
- **Giriş:** Bar 5 close + 1 bar sonra open (lookahead-safe).
- **Stop:** Bar 1.Low - 0.25 × ATR(14).
- **Hedef:** 2R fixed take-profit (tek tier).
- **Position sizing:** risk_pct = 0.5%, max_concurrent = 8, single-symbol cap %15.
- **Fees:** 7.5 bps taker, 5 bps slippage (konservatif).

### Gerekçe (RAG referansları)

- **[Bulkowski Candlestick Statistics, Mat Hold]** (RAG #10) — bullish continuation %74, average move %6.1, performance rank 10/103. EQUITY MARKET istatistikleri; crypto perpetual'e direkt aktarılamaz (bkz §5 curve-fit endişeleri).
- **[Brooks Deep Catalog]** (RAG #3) — failed-breakout / consolidation-breakout mekanikleri 5/5 testable score; Mat Hold yapısal olarak benzer ailededir (sıkışma sonrası breakout).
- **[Kaufman Channel Breakout]** (RAG #7) — asymmetric R-multiple breakout edge; %35 win rate ile pozitif beklenti — Mat Hold de tipik trend-continuation breakout sınıfı.
- **[Market Structure SMC]** (RAG #6) — BOS (close-based, n=3) "Yüksek mekanik çalışabilirlik"; Mat Hold de close-based & n=4 bar window, vektörize edilebilir.
- **[López de Prado]** (RAG #1) — DSR, PBO, IS/OOS Sharpe ratio kriterleri zorunlu olarak uygulanacak; bkz §6 stop criteria.

## 3. Null Hipotez

H0: Mat Hold sinyali random bar seçiminden farkı yoktur (Sharpe ≤ 0, profit factor ≤ 1.0, correlation rastgele).
Reddetmek için shuffle baseline p < 0.05 (Bonferroni sonrası) gerekir.

## 4. Değişkenler

**Dependent (raporlanacak metrikler):**
- Annualized net return (OOS)
- Sharpe ratio (IS, OOS)
- MaxDD (OOS, equity-base — cumulative-PnL-base DEĞİL; bkz lessons #2 yanlış-base bug)
- Profit factor (IS, OOS)
- Win rate, ortalama R, trade sayısı
- Pearson daily-return correlation with vsa_climax_test (live + paper)
- DSR (Deflated Sharpe), PBO (Probability of Backtest Overfitting)

**Independent (sweep edilebilecek, AMA ÖNCEDEN SINIRLI):**
- Bar 1 body/range eşiği ∈ {0.60, 0.70, 0.80} — 3 değer
- Bar 1 body/ATR eşiği ∈ {0.8, 1.0, 1.2} — 3 değer
- Konsolidasyon bar sayısı ∈ {3} — TEK değer (overfit önleme; 2/3/4 sweep yasak)
- Volume confirmation eşiği ∈ {1.0, 1.2, 1.5} — 3 değer
- ATR window ∈ {14} — TEK değer (sabitlenmiş)
- SL ATR çarpanı ∈ {0.25, 0.5} — 2 değer
- TP R-multiple ∈ {2.0} — TEK değer (sabitlenmiş)

**Toplam trial uzayı: 3 × 3 × 3 × 2 = 54 kombinasyon.** Bonferroni düzeltmesi α = 0.05 / 54 ≈ **0.000926**. Tek hipotez başına raw p-value bu eşiğin altında olmalı.

## 5. Curve-Fit ve Overfit Şüpheleri (PARANOYA NOTLARI)

Bu hipotezi yazarken kendime şu kırmızı bayrakları açıkça koyuyorum:

1. **Domain transfer riski:** Bulkowski'nin %74 continuation rate **US equity** 1990-2010 verisinden. Crypto perpetual 24/7, leverage'lı, market-maker baskın → istatistik tabanı dejenere olabilir. Hipotez crypto evreninde **kanıtlanmamış**.

2. **Survivorship bias (Bulkowski Performance Rank 10/103):** "En iyi 10'da" olması selection bias prone — Bulkowski yalnız "çalışan" pattern'leri yayınlamış olabilir. Rank tek başına edge kanıtı değil.

3. **Pattern karmaşıklığı = parametre boyutu:** 5-bar pattern × multiple geometric constraints (body/range, body/ATR, inside-bar tightness, volume confirmation, trend filtre) → López de Prado #1: "serbest parametre sayısı / örnek sayısı > 1/30" riski. 80+ trade hedefi bu eşiği zorlar.

4. **In-sample / OOS divergence eşiği sıkı:** IS Sharpe > 3 × OOS Sharpe ise (López #1) reddet. Mat Hold gibi nadiren tetiklenen patternlerde bu eşiğin aşılması olası — pre-register ile elimde kalmasın diye **şimdiden** taahhüt ediyorum.

5. **15m timeframe seçimi:** Bulkowski istatistikleri ağırlıkla daily. 15m'e taşıma intuition'a dayanıyor; gürültü/fee oranı bozulabilir. Ek olarak 15m fee+slip yükü trade başına ~%0.15 = MaxDD'ye direkt bindirir.

6. **Volume confirmation kripto güvenilmez:** Spot-perp split, MM wash, exchange-specific quirks → volume eşiği overfittable. Bu yüzden volume eşiği 3 değerden fazla taranamaz (üstte sınırlandı).

7. **vsa_climax_test korelasyon ölçümü:** Live PnL serisi henüz uzun değil (vsa_climax_test 30 gün altında olabilir) → 0.20 eşik testi düşük güçlü. Min 60 gün overlap olmadan correlation gate ÇIKARILMAZ.

## 6. Stop Criteria (zorunlu — geçilemez)

Aşağıdakilerden HERHANGI BIRI tetiklenirse hipotez **terk edilir** (Lab tournament'e ya da iterate-rescue pipeline'a gönderilmez):

- IS Sharpe < 0.5 → terk (yeterli baseline edge yok).
- IS/OOS Sharpe oranı > 3 → terk (López de Prado overfit kriteri).
- DSR < 0.5 → terk.
- PBO > 0.5 → terk.
- Walk-forward 8 dilimden 4'ten azı pozitif → terk.
- Shuffle baseline p > 0.05 (Bonferroni sonrası) → terk.
- Symbol-out CV minimum OOS Sharpe < 0.3 → terk.
- Param perturbation (±%10, 50 seed) ortalama Sharpe kaybı > %25 → terk.
- Stress periyot (LUNA / FTX / 2024-08 Yen carry / 2024-03 BTC ATH) içinde tek dönem MaxDD > %15 → terk.
- **vsa_climax_test ile |Pearson daily-return corr| > 0.20** → terk (cross-edge AMACI ÇÖKER; tek başına Sharpe iyi olsa bile pos-rank veremez).
- Aylık ROI ≤ 0 → terk (gerçek edge yok).
- Aylık ROI > 0 fakat DD > %30 → İterate (SOP-4b: risk reduction v2, confluence filter v3, position management v4). REDDETMEK YASAK.

## 7. Beklenen p-value

- Raw p (shuffle baseline) hedefi: **< 0.01**
- Bonferroni sonrası (54 trial): **< 0.000926**
- DSR p: **< 0.05**

## 8. Reproducibility

- git_hash: pending (kod yazılınca commit edilecek)
- config_hash: pending
- data_hash: pending (DuckDB snapshot hash)
- Backtest engine: `backtest/engine.py` vectorbt
- Walk-forward: `backtest/walk_forward.py` 6m train / 3m test, step 3m, Optuna TPE + Median pruner, n_trials ≤ 54 (parametre uzayı sınırı).

## 9. Çıktı Hedefi

- Eğer tüm gate'ler geçilirse → Lab tournament aday manifesto taslağı (insan onayı gerekir).
- Eğer pozitif edge + kötü risk → İterate pipeline (SOP-4b) maks 5 versiyon.
- Eğer null reddedilemez → gerekçeli arşiv, `learning.md`'ye 3 satırlık not.

## 10. İlgili Önceki Çalışmalar (cross-edge VSA companion ailesi)

- `2026-06-07-bos-close-based-1d-low-corr-to-vsa.md`
- `2026-06-07-donchian-20-1d-low-corr-to-vsa.md`
- `2026-06-07-equal-highs-lows-sweep-1d-low-corr-to-vsa.md`
- `2026-06-07-marubozu-continuation-low-corr-to-vsa.md`
- `2026-06-08-bos-close-3bar-1d-low-corr-to-vsa.md`

Bu aile 1D timeframe'de tarandı; Mat Hold deliberately 15m seçildi (vsa_climax_test 15m üzerinde çalışıyor — aynı timeframe'de doğrudan portföy companion testi mümkün). 1D taramasının sonuçları gözden geçirildikten sonra eğer 15m null çıkarsa 1D'ye düşülecek (post-hoc değil, **fallback olarak pre-register**).

---

**STATUS:** DRAFT — Lab Scientist + Risk Officer + Adversary Engineer review beklenmektedir. Kod yazılmadan önce hipotez **dondurulacak** (commit + hash). Sonuç manifestosu çıktıktan sonra `decisions/` altına ADR.
