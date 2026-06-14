---
doc_id: researcher-20260609T053100-atr-k-volatility-breakout-1d-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-09T05:31:00Z
status: PROPOSED
confidence: med
depends_on:
  - hyp-2026-06-08-mathold-continuation-low-corr-to-vsa
  - hyp-2026-06-07-marubozu-continuation-low-corr-to-vsa
  - hyp-2026-06-07-bos-close-based-1d-low-corr-to-vsa
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, cross-strategy, low-correlation, momentum, atr-breakout, kaufman]
supersedes: null
hash: d513795c09ca
---

# Hipotez: HYP-2026-06-09-ATR-K-VOLATILITY-BREAKOUT-1D

- **Tarih:** 2026-06-09
- **Versiyon:** 0.1 (pre-registration, kod yazılmadan önce)
- **Reproducibility:** git=`d513795c09ca`, config_hash=tbd, data_hash=tbd
- **Kayıt Tarihi:** 2026-06-09T05:31:00Z (UTC)

## 1. İddia (ölçülebilir, tek cümle)

> 1D timeframe'de, **`close[t-1] + k·ATR14[t-1]`** seviyesinin üzerine `t` mumunun **kapanışıyla** çıkış (long) — veya `close[t-1] − k·ATR14[t-1]` altına kapanış (short) — `t+1` open'ında piyasa emriyle giriş, **1.5·ATR14 SL** ve **2.0·ATR14 TP** ile; 2022-06-01 → 2025-12-31 (3.5y) USDT-perpetual evreninde, **k ∈ {0.5, 0.7, 1.0}** (Bonferroni n=3 düzeltmesi sonrası), aşağıdaki eşikleri **EŞZAMANLI** karşılar:
>
> | Metrik | Hedef |
> | --- | --- |
> | Net annualized return (fee+slip dahil) | ≥ **30%** |
> | OOS Sharpe (walk-forward 12 dilim ortalaması) | ≥ **0.8** |
> | MaxDD (account-equity bazında) | ≤ **25%** |
> | Profit factor | ≥ **1.30** |
> | Trade sayısı (test dönemi) | ≥ **200** |
> | **Pearson(daily-returns, vsa_climax_test)** | ∈ **(−0.30, +0.30)** |
> | Shuffle baseline p-value (1000 perm) | < **0.05** |

> Bonferroni sonrası en az **bir** `k` değeri tüm eşikleri geçerse hipotez **TERFİ ADAYI**; aksi halde **RED**.

## 2. Gerekçe (RAG referansları)

- **[Kaufman summary, §ATR-K Volatility Breakout, RAG#5]** — Kaufman'ın klasik volatility breakout reçetesi: `Open + k·ATR(14)` stop emriyle giriş, k tipik 0.5–1.0. **Belirtilen edge:** ~%55 WR, küçük R asimetrik beklenti. **Belirtilen failure modes:** düşük-vol günlerinde tetiklenmez (zaten istenen) + trend-day'de erken kâr alır.
  - **Sapma notu:** Kaufman intraday entry için open kullanıyor; biz 1D bar'da kapanış-bazlı sinyal + `t+1` open giriş. Açık olarak gevşek bir uyarlamadır → curve-fit riski.
- **[Brooks deep catalog, RAG#3]** — n-bar high/low aşımı + geri dönüş skala-5 (en yüksek) test edilebilirlik. ATR-K breakout, "geri dönüş kabul edilmeyen" yönüdür (continuation tarafı).
- **[Market Structure / Order Flow, RAG#6]** — Equal Highs/Lows Sweep "Yüksek" mekanik çalışabilirlik. ATR-K breakout, stop-hunt sonrası **continuation** mekaniğiyle örtüşen close-confirmation gerektirir.
- **[Lopez de Prado, RAG#1]** — **Bonferroni / PBO / DSR** zorunlu. `k` 3-parametreli grid → DSR FDR düzeltmesi gerekli; PBO > 0.5 RED.
- **vsa_climax_test mekaniği (in-house active strategy):** climax bar'da fade (exhaustion reversal). Yapısal olarak **ATR-K breakout'un tam tersi yön** — continuation tarafı; a-priori düşük return-korelasyonu beklentisi makul. (Doğrulama §4.6'da.)

## 3. Null Hipotez (ne çürütür)

1. **H0a (no edge):** k ∈ {0.5, 0.7, 1.0} hiçbiri net annual return ≥ 30% üretmez (fee+slip dahil).
2. **H0b (correlation overlap):** Pearson(returns, vsa_climax_test) ≥ +0.30 — yeni edge eklemenin portföy çeşitlendirme katkısı yok.
3. **H0c (overfit):** IS Sharpe > 3·OOS Sharpe (Lopez kriteri #4 kırmızı).
4. **H0d (random):** Shuffle baseline p ≥ 0.05 → sinyal random'dan ayırt edilemez.
5. **H0e (regime narrow):** Sadece bull rejimde pozitif; bear ve range negatif → "trend-day asymmetry lost" failure mode (RAG#5).

Yukarıdakilerden **herhangi biri** doğruysa → RED.

## 4. Pre-Registered Metrikler & Test Tasarımı

### 4.1. Dependent Variables (sayısal)

- Net annualized return (compounding, fee+slip net)
- Out-of-sample Sharpe (annualization: √(365·24·60/1440) = √365 ≈ 19.10 — 1D bar)
- MaxDD (account-equity bazında — **NOT** zero-base cumulative; bkz. CT-RSK-01)
- Profit factor (gross_win / gross_loss)
- Win rate, ortalama R (winners), ortalama R (losers), asimetri = avg_W / avg_L
- Trade sayısı (toplam, sembol-bazlı)
- Pearson korelasyon (daily-returns vs vsa_climax_test daily-returns, same window)
- Spearman korelasyon (robustness check)
- Walk-forward Sharpe varyansı (Lopez kriteri #6)

### 4.2. Independent Variables

- `k` ∈ {0.5, 0.7, 1.0} — **3 değer, daha ince grid YASAK** (curve-fit önlem)
- `sl_atr_mult` = 1.5 (sabit — Kaufman default)
- `tp_atr_mult` = 2.0 (sabit — Kaufman'ın "2x ATR target" varyantı)
- `atr_window` = 14 (sabit — Kaufman default)
- Sembol evreni: top-20 USDT-perp by 30d ADV (survivorship-corrected — listing/delisting tarihleri dahil)
- Fee: 7.5 bps taker, slip: 5 bps konservatif

### 4.3. Test Dönemi & Splits

- **Toplam:** 2022-06-01 → 2025-12-31 (3.5y)
- **Walk-forward:** 2y train + 6m test, step 3m → **~6 dilim**
- **Final OOS:** 2026-01-01 → 2026-05-31 (5 ay, hiç dokunulmaz)

### 4.4. Beklenen p-value

- Shuffle baseline: **p < 0.05** her k için
- **Bonferroni düzeltmesi:** Test edilen k sayısı n=3 → kabul eşiği p < **0.0167** (0.05/3)
- **DSR (Deflated Sharpe Ratio):** ≥ 0.5
- **PBO (Probability of Backtest Overfitting):** ≤ 0.5

### 4.5. Robustness Suite (SOP-3 zorunlu)

| Test | Eşik |
| --- | --- |
| Walk-forward dilim tutarlılığı | 6/6 dilimden ≥4 pozitif Sharpe |
| Param perturbation (k ±10%, 50 seed) | OOS Sharpe kaybı < 25% |
| Symbol-out CV | min OOS Sharpe ≥ 0.5 |
| Regime split (bull/bear/range) | en az 2 rejimde pozitif Sharpe |
| Stress periyodları (LUNA, FTX, USDC, Yen carry) | tek dilimde DD < 15% |
| Shuffle baseline (1000 perm) | p < 0.05 / Bonferroni n=3 → p < 0.0167 |
| Bonferroni / FDR (k=3 trial) | en az bir k geçer |
| In-sample vs OOS Sharpe ratio | < **3.0** (Lopez kriteri #4) |

### 4.6. Korelasyon Doğrulama (özel)

- vsa_climax_test'in son **180 gün** günlük PnL serisi (paper veya backtest) ile aynı dönemde bu hipotezin günlük PnL serisi → **Pearson |ρ| < 0.30**
- Rolling 30-bar korelasyon: max |ρ| < 0.50 (clustering yok)

## 5. Curve-Fit Şüphesi (red bayrağı self-disclosure)

> **DÜŞÜK GÜVEN — şu noktalarda overfit riski var:**

1. **Kaufman intraday→1D adaptasyonu literatürde sığ:** Volatility breakout aslında intraday momentum yakalama için tasarlandı; 1D bar'da `t+1` open giriş, Kaufman'ın "open + k·ATR" formülüne **gevşek bir uyarlama**. RAG#5'in edge iddiası 1D'ye otomatik transfer edilemez.
2. **k ∈ {0.5, 0.7, 1.0} grid yine de 3 trial:** Bonferroni düzeltmesi yapılsa bile, 6 dilim × 3 k × 20 sembol = 360 trial-symbol payı uçar. PBO testi olmazsa "best k" şans olabilir.
3. **`tp_atr_mult=2.0` ve `sl_atr_mult=1.5` Kaufman default'ları — bu da serbest parametre.** Hipotez bu iki değeri **kilitliyor**; SOP-3 perturbation testinde bunları da ±20% perturb etmek istiyorum (yan-doğrulama).
4. **Bull-piyasa bias riski:** ATR-K breakout trend günlerinde patlar. 2023 H2 + 2024 boğa, edge'in çoğunu sağlayabilir. **Regime split testi (§4.5) zorunlu kabul kapısı.**
5. **VSA climax_test ile korelasyon a-priori düşük varsayımı, mekanik ters-yönlü olsa bile, ortak bull-piyasa beta'sından dolayı %30'u aşabilir.** Eğer aşarsa → portföy ekleme önerisi RED (sadece edge değil, çeşitlendirme de gerekli).

## 6. Stop Criteria (terkedilme eşiği)

Aşağıdakilerden **herhangi biri** doğrulanırsa araştırma **derhal terkedilir** — daha fazla parametre denemesi YASAK:

1. **In-sample Sharpe < 0.5** her üç k için → edge yok, devam etme.
2. **In-sample Sharpe > 3·OOS Sharpe** (Lopez #4) → overfit, devam etme.
3. **Shuffle baseline p > 0.10** her k için → sinyal random'dan ayırt edilemiyor.
4. **Pearson(returns, vsa_climax_test) > +0.50** → portföy çeşitlendirme sıfır, kabul edilemez.
5. **Trade sayısı < 100** test döneminde → istatistik anlamsız.
6. **Best k uzayın sınırında (k=0.5 veya k=1.0)** → grid genişletme yasağı: terk et veya bu sınırın dışında ayrı pre-registered hipotez aç.

## 7. Beklenen Sonuç (subjective prior)

- **P(terfi):** ~%20 — bull-bias riski + 1D adaptasyon zayıflığı + korelasyon gate çift kapı.
- **En olası red sebebi:** Regime split (bear/range negatif).
- **En olası terfi nedeni:** k=0.7 sweet-spot + ortalama R asimetrisi (RAG#5'in vaadi).

## 8. Bağlantılı Hipotezler (depends_on context)

- `2026-06-08-mathold-continuation-low-corr-to-vsa.md` — continuation pattern denemesi (5-bar)
- `2026-06-07-marubozu-continuation-low-corr-to-vsa.md` — tek-bar continuation
- `2026-06-07-bos-close-based-1d-low-corr-to-vsa.md` — structural break edge
- `2026-06-07-donchian-20-1d-low-corr-to-vsa.md` — channel breakout edge

Bu set "VSA-climax'a düşük korelasyonlu continuation/breakout aile araştırması"nın 5. üyesi. Aile üyelerinin **arada da** düşük korelasyonlu olması beklenir (yoksa hepsi birbirinin proxy'si). Eğer hepsi bir-birine ρ > 0.6 ise → "tek faktör" hipotezine geçilir (PCA-1 trend-beta).

## 9. Sonraki Adımlar (kod yazımı için kilitli)

1. `backtest/configs/atr_k_breakout_1d.yaml` taslağı (DRAFT).
2. `backtest/engine.py` ile in-sample full-run (3 k değeri, 20 sembol).
3. Walk-forward (6 dilim) — OOS metrikleri.
4. Robustness suite §4.5 — tek tek tablo.
5. Korelasyon paneli §4.6 — vsa_climax_test journal'i ile cross-check.
6. Karar yazımı: Terfi adayı / İterate (SOP-4b) / Red.

---

**Not (Researcher şerhi):**
> Bu hipotezin **a-priori başarı olasılığı düşük**. Kaufman'ın intraday-momentum edge'i 1D bar'a sınırlı transfer eder; üstüne kripto bull-bias riski bindirilirse "yıllık %30 net" şüpheli bir bar. **Yine de pre-registration disiplini gereği şartlar net yazıldı**; çürürse log'a 3-satır gerekçe + `learning.md`'ye "1D ATR breakout Kaufman-adaptasyon zayıflığı" notu eklenecek.
