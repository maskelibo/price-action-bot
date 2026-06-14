---
doc_id: researcher-20260531T091500-bearish-marubozu-continuation-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-31T09:15:00Z
status: DRAFT
confidence: low
depends_on:
  - shared-fact-vsa-climax-test-active
blocks: []
requested_review_from:
  - lab_scientist
  - risk_officer
  - adversary_engineer
tags:
  - hypothesis
  - cross-strategy
  - continuation
  - marubozu
  - low-correlation
  - bulkowski
  - vsa-diversifier
supersedes: null
hash: null
---

# HYP-2026-05-31 — Bearish Marubozu Continuation (Low-Corr Diversifier to `vsa_climax_test`)

## 0. Motivation (cross-strategy edge, seed konu)

Aktif `vsa_climax_test`, **range-end exhaustion / reversal** mantığına oturuyor (yüksek hacimli climax bar → reversal). Portföye 1ρ negatif veya |ρ| < 0.30 olan **structural continuation** profili lazım. RAG corpus'unda Bulkowski'nin yayınladığı tek-bar continuation istatistiği olan **bearish marubozu** (Performance rank 22/103, %64 bearish continuation, ortalama %4.9 hareket — RAG #8) bu profile en yakın aday: tek-bar momentum imprint, hacim koşulu opsiyonel; tetiklenme rejimi vsa_climax_test'inkinden farklı (climax değil, **trend-içi full-body imza**).

Bugün hipotez tabanında denenmemiş; mat-hold (continuation, #10) ve donchian breakout zaten ya seed-abort ya da kapalı.

## 1. İddia (pre-registered, ölçülebilir)

> **1D timeframe'de, son 200 barda close < EMA50 olan ayı rejiminde, gövde / range ≥ 0.90 VE wick toplamı / range ≤ 0.10 koşullarını sağlayan bearish marubozu bar'ının kapanışından sonra, t+1 open'da short giriş, 1.5×ATR(14) initial stop, 1.0R BE-protect 0.7R sonrası, 2.5×ATR(14) hard TP, 24-bar time-exit, son 3 yıl (2023-05-31 → 2026-05-31) tüm USDT-perpetual liquid evreninde (delisting'ler dahil, fee 7.5 bps taker, slip 5 bps) aşağıdaki TÜM eşikleri sağlar:**
>
> 1. **OOS net annualized return ≥ %35** (fee+slip sonrası)
> 2. **OOS Sharpe ≥ 1.0** (günlük strateji-getirileri, yıllıklaştırma √365)
> 3. **OOS MaxDD ≤ %22** (account equity bazında, ADR-RSK-01 ile uyumlu)
> 4. **Profit factor ≥ 1.35**
> 5. **Trade sayısı ≥ 250** (3 yıl × evren, istatistiksel anlamlılık tabanı)
> 6. **Daily strategy-return correlation with active `vsa_climax_test` ≤ 0.30** (Pearson, OOS dilim) — birincil **diversifier** kriteri; bu sağlanmazsa diğer 5 metrik geçilse bile **terfi edilmez**.

## 2. Null hipotez (H0)

H0: Bearish marubozu post-bar t+1 open short, **shuffle baseline** (returns rastgele karıştırılmış null) ile karşılaştırıldığında bootstrap Sharpe dağılımının %95 CI'sından dışarı çıkmaz (p ≥ 0.05). Bulkowski'nin %64 continuation oranı, ücretsiz/küresel hisse senedi tablosunun raporu olup **kripto perpetual fee/slip modelinde anlamlı sıfır pozitif beklenti** üretmez.

H0 reddedilirse (yani p < 0.05 ve §1'in 6 maddesi gerçekleşirse) → H1 geçici olarak kabul edilir; Lab tournament'a aday gönderilir.

## 3. Gerekçe (RAG referansları)

- **[Bulkowski – Candlestick Statistics, RAG #8]:** Bearish marubozu Performance rank 22/103, **%64 bearish continuation**, ortalama hareket **%4.9**. Tanım: "Gövde range'in %90'ından büyük, kapanış ≈ Low, açılış ≈ High." → mekanik kodlama doğrudan.
- **[Brooks – Deep Catalog, RAG #3]:** Trend-içi reversal bar kalitesi yüksek + HTF opposition → test edilebilirlik skoru 5/5. Marubozu bu kategorinin tipik "yüksek-imza" bar'ı.
- **[Market Structure / Order Flow, RAG #6]:** BOS close-based n=3 yüksek mekanik çalışabilirlik (crypto 1D); marubozu bar bir mini-BOS imzasıdır ve close-bazlı tanım lookahead'siz vektörlenebilir.
- **[Kaufman, RAG #4]:** MA-filtered trend continuation; "Düşük frekans, düşük commission yükü, major trend'leri yakalar." → EMA50-filtered rejim koşulu marubozu sinyalini yapısal trend ile birleştirir.
- **[Lopez de Prado, RAG #1]:** DSR/PBO/serbest-param disiplini — bu hipotez 4 serbest parametre kullanır (body_ratio, wick_ratio, atr_sl_mult, atr_tp_mult), sample/param > 30 tabanını korumak için min trade 250 zorunlu.

## 4. Değişkenler

### Dependent (ölçüm hedefleri, pre-registered)

| # | Metrik | Hesap | Eşik |
|---|---|---|---|
| D1 | OOS annualized net return | (1 + sum_daily_ret)^(365/N_days) − 1 | ≥ 0.35 |
| D2 | OOS Sharpe | mean(daily_strat_ret) / std(daily_strat_ret) · √365 | ≥ 1.0 |
| D3 | OOS MaxDD | peak-to-trough on **account equity** (Lesson: kümülatif zero-base **YASAK**, CT-RSK-01) | ≤ 0.22 |
| D4 | Profit factor | sum(W) / |sum(L)| | ≥ 1.35 |
| D5 | Trade count | N closed positions | ≥ 250 |
| D6 | Corr w/ vsa_climax_test | Pearson daily-return correlation, OOS dilim | ≤ 0.30 |

### Independent (parametre uzayı — pre-registered grid; ince adım YASAK)

| Param | Aralık | Adım | Not |
|---|---|---|---|
| `body_ratio_min` | [0.85, 0.95] | 0.05 (3 değer) | Bulkowski default 0.90 |
| `wick_ratio_max` | [0.05, 0.15] | 0.05 (3 değer) | tamamlayıcı kısıt |
| `atr_sl_mult` | [1.0, 1.5, 2.0] | (3 değer) | konservatif tarafta |
| `atr_tp_mult` | [2.0, 2.5, 3.0] | (3 değer) | 1.5R+ asimetri |
| `regime_ema_window` | {50} | tek değer (sabit) | overfit ihtimalini kapat |
| `time_exit_bars` | {24} | tek değer (sabit) | dimension azalt |
| `be_trigger_R` | {0.7} | tek değer (sabit) | dimension azalt |

**Toplam Optuna trial üst sınırı:** 81 (3^4 grid + 0 sürekli param). Bonferroni düzeltmesi → effective α = 0.05 / 81 = **6.17e-4**. Shuffle baseline p-value bu eşiğin altına inmek zorunda.

## 5. Beklenen p-value ve etki büyüklüğü

- **Beklenen Sharpe (point estimate):** 1.1–1.4 (Bulkowski %64 → kripto fee/slip + EMA filtre sonrası agresif olmayan tahmin)
- **Beklenen p-value (shuffle baseline, ham):** < 0.01
- **Bonferroni sonrası hedef:** p < 6.17e-4 — bu çok katı; **muhtemelen geçemez** (curve-fit beklentisi yüksek, aşağı bakınız)
- **Effect size (Sharpe(strat) − Sharpe(buy-hold equal-weight basket)):** ≥ +0.5

## 6. Stop Criteria (kod yazarken hipotezi terk noktaları)

Aşağıdakilerden **herhangi biri** tetiklenirse hipotez **TERK** edilir (`-seed-abort.md` rename), Lab'e adayı dahi gönderilmez:

1. **IS Sharpe < 0.8** (ilk smoke backtest, default params) → araştırma terkedilir.
2. **IS / OOS Sharpe oranı > 3** (Lopez kırmızı bayrak #4, RAG #1).
3. **PBO > 0.5** (combinatorially symmetric cross-validation).
4. **Best parameters parametre uzayının sınırında** (örn body_ratio_min = 0.85 sınırda → daha geniş aralık dene; sınırda kalırsa kalıp robust değil).
5. **Trade sayısı < 250** (örnek yetersiz, istatistik geçersiz).
6. **Symbol-out CV: top-3 sembol P&L'in > %60'ını üretiyor** → tek-vaka edge.
7. **Stress dilimleri** (2022-05 LUNA, 2022-11 FTX, 2024-03 BTC ATH, 2024-08 Yen carry) **herhangi birinde** dilim MaxDD > %30 → yıkıcı tail bulunmuş.
8. **Corr(vsa_climax_test) > 0.50** → diversifier amacı çürür, raison d'être yok.

## 7. Curve-Fit Şüphesi (zorunlu — pre-registered)

### Kırmızı bayraklar (a priori farkındalık)

1. **Bulkowski istatistikleri equity (US stocks) ortamında üretildi** — kripto perpetual'a transfer iddiası **otomatik geçerli değil**. RAG #8 sayıları bir hipotez tetikleyicisi, kanıt değil.
2. **body_ratio_min = 0.90 "popüler" eşik** — RAG corpus'unda yayınlandığı için yaygın kullanılıyor → muhtemelen kripto'da arbitraje uğramış olabilir. Bu hipotezin kabulü için "0.90'ın özel bir şey olmadığını, 0.85 ve 0.95'in de yakın Sharpe ürettiğini" doğrulamak zorunlu (param-perturb suite).
3. **Tek-bar pattern hassasiyeti** — gövde %90 vs %89.9: tanım eşiğine 1 bps'lik hassasiyet → fee/slip noise'ı sinyali boğabilir. Bu yüzden `body_ratio_min` ızgarası 0.05 step ile **geniş** tutuldu; daha ince adım YASAK.
4. **EMA50 rejim filtresi** klasik "denenmiş, başarısız" parametre uzayında bulunur — multiple-testing inflation riski. `regime_ema_window` tek değer (50) sabit, optimize edilmiyor.
5. **Bearish-only tarama** seçildi (long/short asimetri) — şampiyonun aksine, sadece short. Ayı yönlü bias riski: 2023-2024 net bull yıllarında trade sayısı çok düşük olabilir → §6/5 stop kriteri tetiklenir.

### Curve-fit savunma planı

- Param grid kapalı / küçük (81 noktada Bonferroni).
- Walk-forward 12 dilim (3y / 6m test, 3m step), dilim-bazında Sharpe varyansı / ortalama < 1.0 olmazsa **red**.
- Symbol-out CV (her sembolü tek tek dışarıda bırak).
- Shuffle baseline p < α/N.
- Stress dilim 4'ünde max DD ≤ %30.
- Param-perturb (±%10, 50 seed) Sharpe ortalama kayıp < %25.
- `vsa_climax_test` ile günlük getiri korelasyonu ölçülecek ve **birincil diversifier kriteri** olarak gate'in parçası.

## 8. Operational

- **Veri kaynağı:** DuckDB `data/perp_ohlcv_1d.duckdb`, universe = `build_universe(2023-05-31, liquid_filter='all_liquid', include_delisted=True)` (CT-DAT-01 ile uyumlu, survivorship'siz).
- **Backtest engine:** `backtest/engine.py` (vectorbt). Pattern detector: vektörize, lookahead testi zorunlu (CT-RES-01).
- **Reproducibility:** `(git_hash, config_hash, data_hash)` sonuç raporuna ek olarak gömülecek.
- **Lab handoff:** §1'in 6 maddesi + §6 stop criteria HİÇBİRİ tetiklenmezse → Lab tournament aday'ı (`reports/research/HYP-2026-05-31-bearish-marubozu-cont.html`); aksi halde gerekçeli arşiv (`learning.md`).

## 9. Karar (boş — backtest sonrası doldurulacak)

- [ ] Terfi adayı (Lab tournament)
- [ ] İterate (SOP-4b — pozitif edge var ama risk gate'i geçemedi)
- [ ] Red (gerekçe: ...)

## 10. Future-self note (anti-narrative)

"Bulkowski %64 diyor" cümlesi bu hipotezin kabul gerekçesi DEĞİLDİR. Yalnızca bir tetikleyicidir. Sayı kazanır. §1'in 6 maddesinden biri bile geçmezse — kalıp Bulkowski'de ne yazarsa yazsın — **bu hipotez reddedilir**.
