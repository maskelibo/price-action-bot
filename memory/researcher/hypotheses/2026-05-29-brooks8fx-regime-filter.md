# Hipotez: HYP-2026-05-29-brooks8fx-regime-filter

**Status:** CLOSED — FALSIFIED (2026-05-29). H0 reddedilemedi. Tüm 5 filtre IS stop-criterion'da öldü; rejim metrikleri brooks'un kötü/iyi trade'ini ayırt edemedi; sağ-çarpık edge'te filtre kazananları kesti. Detay learning.md. Test: scripts/brooks_8fx_regime_filter.py
**PRE-REGISTERED (kod yazılmadan önce dondurulmuştur)**
**Reproducibility:** git=e7d0a90 (branch audit-hardreview-20260528), data=/tmp/rt_trades.pkl md5=52e42eabc79a4bdf3c542ee52b438cc1, engine=brooks_8fx_honest_cap.py (netUSD<=3, mc6, byte-identical)
**OHLC source:** data/forex_market.duckdb ohlcv 4h, 8 FX, 2020-2025

## 0. Bağlam / Baseline (filtresiz, dondurulmuş)
brooks_8fx failed-breakout, netUSD<=3 cap, mc6, eff_r=1%, honest cost.
- robust(winner-stripped) medyan ~ +7.1%/ay, raw medyan ~ +10.3%
- realized contDD ~ -14%, monthly Sharpe ~ 0.82, ~22/72 negatif ay
- Edge sağ-çarpık: kârın ~%40'ı top-5% trade.

## 1. İddia (a priori, ölçülebilir)
brooks bir breakout/momentum stratejisidir. Choppy/yatay/düşük-trend rejimlerde
sahte kırılımlar (failed-breakout edge'in TERSİ değil, ama momentum follow-through
yokken) zarar üretir. Bir trend-gücü / efficiency rejim filtresi (uygun OLMAYAN
rejimde GİRİŞ YAPMA) kayıp ayları azaltıp robust medyan ROI ve monthly Sharpe'ı
yükseltir — ÖNEMLİ KOŞUL: büyük kazananları (top-5%) ORANTISIZ kesmeden.

## 2. Null Hipotez (Popper — bu doğruysa şu OLMAMALI)
H0: Rejim filtresi, kesilen trade'lerin ortalama R'sini havuz ortalamasından
ANLAMLI ölçüde düşürmez (yani kötüyü iyiden ayırt edemez); OOS'ta filtreli
robust medyan ROI filtresizden YÜKSEK DEĞİLDİR ve/veya monthly Sharpe ARTMAZ.
- H0 doğruysa: kesilen trade'lerin mean R'si ~ havuz mean R; OOS robust medyan
  delta <= 0; OOS Sharpe delta <= 0.
- Filtre IS-overfit ise: IS'te güzel iyileşme, OOS'ta delta <= 0 veya negatif.

## 3. Test Edilecek Filtreler (her biri AYRI, IS=2020-2023 / OOS=2024-2025)
Tüm rejim metrikleri entry barından ÖNCEKİ kapanmış bara kadar (t-1) hesaplanır.
Lookahead YASAK: entry bar'ın kendisi rejim hesabına GİRMEZ.

### F1 — Trend-gücü gate (ADX)
- Sinyal: 4h ADX(14) at t-1 >= THR_ADX  → giriş izin; aksi pas.
- Pre-reg eşik: IS'te {15, 20, 25} arasından IS robust medyanı MAKSİMİZE eden
  TEK değer seçilir (grid OOS'a DOKUNULMAZ). Tie-break: en gevşek (en düşük) eşik
  (daha az overfit, daha çok trade tutar).

### F2 — Trend-hizalama gate (EMA50/200)
- Sinyal: long ise EMA50(t-1) > EMA200(t-1); short ise EMA50 < EMA200. Hizasızsa pas.
- Parametresiz (eşik yok) — overfit riski minimal. Tek varyant.

### F3 — Volatilite-rejim gate (ATR percentile, sembol bazlı)
- Sinyal: ATR(14)/close percentile rank (trailing 250 bar, sembol bazlı) at t-1
  THR_LO ile THR_HI bandı İÇİNDE ise giriş. Aşırı düşük vol = whipsaw, aşırı yüksek = haber riski.
- Pre-reg: IS'te THR_LO ∈ {0.20, 0.30}, THR_HI = 0.95 sabit. IS robust medyan max → seç.

### F4 — Efficiency Ratio gate (Kaufman ER / choppiness proxy)
- Sinyal: ER = |close(t-1)-close(t-1-N)| / sum(|close diff|) over N=20 bars at t-1.
  ER >= THR_ER → "yürüyor" → giriş; düşük ER = "zıplıyor" → pas.
- Pre-reg: IS'te THR_ER ∈ {0.20, 0.30, 0.40}. IS robust medyan max → seç. Tie-break: en düşük.

### F5 — Decayed-leg downweight (USD/CHF, EUR/GBP)
- (e) bölümü leg decay'i gösteriyorsa: decay'li bacaklara 0.5x risk. Parametresiz heuristik.

## 4. Pre-registered Karar Metrikleri (her filtre, HEM IS HEM OOS)
Dependent: robust(winner-stripped) medyan ROI%, raw medyan, STD%, realized contDD%,
monthly Sharpe, negatif-ay sayısı, n_trade, kesilen trade sayısı, kesilen trade mean R.

## 5. Terfi / Red Eşiği (a priori, OOS-only karar)
Bir filtre KABUL adayı SADECE şu üç koşul OOS'ta AYNI ANDA sağlanırsa:
  (i)  OOS robust medyan(filtreli) >= OOS robust medyan(filtresiz) + 0.5pp (anlamlı, gürültü değil)
  (ii) OOS monthly Sharpe(filtreli) > OOS monthly Sharpe(filtresiz)
  (iii) Kesilen trade'lerin mean R < havuz mean R (kötüyü kesmiş, iyiyi DEĞİL) — IS ve OOS'ta tutarlı işaret
Ek robustluk: top-5% kazanan trade'lerin >%30'unu kesmemeli (kazanan koruma).
Herhangi biri fail → RED, gerekçeyle arşiv. IS güzel + OOS fail = OVERFIT verdict.

## 6. Stop Criteria
IS'te bir filtre robust medyanı filtresizin ALTINA çekiyorsa o filtre IS'te ölür,
OOS'a taşınmaz (boşuna OOS yakma). Beklenen: filtrelerin çoğu ölür (%80 reject normal).

## 7. Çoklu test düzeltmesi
4 filtre x ~3 eşik = ~10 IS konfigürasyonu test edilir. IS'te seçim yapılır,
OOS'ta SADECE seçilen TEK eşik test edilir → OOS'ta multiple testing yok (1 test/filtre).
4 filtre OOS testi için Holm-Bonferroni aklında tutulur (yorumda).
