---
doc_id: researcher-20260611T120000-bearish-marubozu-1d-momentum-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-11T12:00:00Z
status: PROPOSED
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, pre-registration, candlestick, bearish-marubozu, 1d, momentum-continuation, cross-strategy, low-correlation, vsa-diversifier, short-bias]
supersedes: null
hash: null
---

# Hipotez HYP-2026-06-11-bearish-marubozu-1d-momentum-low-corr-to-vsa

## 0. Seed Konu

> "Cross-strategy edge keşfi: aktif `vsa_climax_test` ile düşük korelasyonlu ek bir strateji (raftaki 66'dan adaylar)."

Aktif şampiyon `vsa_climax_test` = **15m**, **volume-climax mean-reversion**, fiilen LONG+SHORT iki yönlü ama edge'inin çoğunluğu uzun kuyruktan dönüşler. Diversifier olarak **timeframe (15m → 1D)**, **mekanizma (mean-reversion → momentum continuation)** ve **bar-kaynağı (volume-driven → price-shape-driven)** ortogonal aday gerekiyor.

**Aday: Bearish Marubozu, 1D**, single-bar bearish-continuation. RAG #8 (Bulkowski): %64 continuation, rank 22/103, avg move %4.9. Mat Hold (rank 10, %74) zaten 3 kez denendi (2026-05-31, 2026-05-31-v2-abort, 2026-06-02) ve tükendi; equal-highs-sweep / Kaufman vol-break / Chan-halflife bugün denendi. Marubozu rafımızda DAHA ÖNCE pre-register edilmemiş, RAG'te referansı net, mekanizma minimum parametreli.

**Curve-fit şüphesi peşinen:** Bulkowski %64 rakamı equity universe (NYSE/Nasdaq daily) — crypto perpetual'a aktarım PRIOR YOKTUR; %90 body eşiği keyfi; perpetual'da fee asymmetric (round-trip ≈15bps taker + ≈10bps slip = 25bps); 2020-2026 evreni yapısal bull bias → short-only stratejinin net negatif çıkma riski yüksek. Bu hipotez **olası null** olarak yola çıkıyor.

## 1. Iddia (PRE-REGISTERED, ÖLÇÜLEBİLİR)

**Universe:** top-15 likit USDT-perpetual (delisting-inclusive, survivorship-bias düzeltilmiş; data/universe.py::build_universe(date) zaman-bilinçli olarak). **Timeframe:** 1D primary, 1W trend confirm. **Dönem:** 2020-01-01 → 2026-06-01 (≈6.4 yıl, ≈35.000 sembol-gün).

**Bearish Marubozu sinyal mekaniği (close-based, lookahead-safe):**

Bar `t` için tanım:
- `body = open - close` (bearish, > 0)
- `range = high - low`
- `body / range ≥ body_ratio_min` (yani neredeyse hiç fitil yok)
- `(high - open) / range ≤ tail_tol` (üst fitil ≈ 0 → open ≈ high)
- `(close - low) / range ≤ tail_tol` (alt fitil ≈ 0 → close ≈ low)
- `|body| / close_t ≥ body_pct_min` (mutlak hareket eşiği; pseudo-marubozu süpürmek için)
- **Trend onayı:** `close_t < EMA(close, ema_len)_t` (downtrend içinde continuation)
- **Volume onayı:** `volume_t > vol_mult × SMA(volume, 20)_t`

Sinyal `t` close'da emit, **giriş `t+1` open'da kısa pozisyon** (causality).
- **SL:** `high_t + sl_atr_mult × ATR(14)_t`
- **TP:** `entry - tp_R × (SL − entry)` (R-multiple)
- **Risk:** %1 sermaye / trade
- **Fee:** 7.5 bps taker, **Slippage:** 5 bps (her bacak)
- **Initial:** 10k USDT, fixed-fraction (NO compounding inflation)

### Pre-registered ölçülebilir eşikler

| Metric | Hedef | Gate |
|---|---|---|
| Net annualized return (fee+slip dahil) | **> %30** | terfi şartı |
| OOS Sharpe (walk-forward 12 dilim) | **> 0.8** | terfi şartı |
| MaxDD (account-equity bazlı) | **< %22** | terfi şartı |
| Profit factor | **> 1.3** | terfi şartı |
| Win rate | n/a (asimetrik 2R hedef) | info |
| Trade sayısı (min) | **N ≥ 250** | istatistik gücü |
| **Pearson |ρ(daily_pnl_vsa, daily_pnl_marubozu)|** | **< 0.30** | **diversifier şartı** |
| **Marginal Sharpe** (Sharpe(ensemble) − Sharpe(vsa_alone)) | **> +0.15** | **diversifier şartı** |
| Bull/Bear/Range rejim ayrı pozitif | en az **2 / 3** | robustness |
| Stress dönem (LUNA, FTX, BTC ATH 2024-03, Yen 2024-08) | **hiç birinde -%15+ dik kayıp yok** | robustness |

## 2. Gerekçe (RAG referansları)

- **[RAG #8 — book_candlestick_statistics]:** Bearish Marubozu, body range'in %90'ından büyük, kapanış ≈ low, açılış ≈ high. **Bulkowski continuation rate %64, avg move %4.9, rank 22/103.** Tanım mekanik, kodlanabilir.
- **[RAG #1 — Lopez de Prado statistical gates]:** **DSR < 0.5, PBO > 0.5, IS/OOS Sharpe > 3, params/sample > 1/30** kriterlerinden biri kırmızıysa production'a gitmemeli — gate uygulayacağım.
- **[RAG #6 — book_market_structure_order_flow, crypto 1D mechanic-testability tablosu]:** crypto perpetual 1D'de mekanik tanımlı pattern'lar (BOS/CHoCH/sweep) "yüksek testability"; Marubozu da bu sınıfın tek-bar üyesi.
- **[RAG #9 — book_chan, Sharpe-based strategy gating]:** **OOS Sharpe > 0.8** eşiği single-asset için Chan'in retail-realistic edge tablosuyla uyumlu — gate olarak alıyorum.

**Beklenen prior:** zayıf — Bulkowski equity-tabanlı, crypto'ya aktarım kanıtlanmamış. Hipotez büyük olasılıkla **null bulgu** verecek; verirse "OK, raftan düşür" diye temiz arşivleyeceğim.

## 3. Null Hipotez (H0)

H0: "Bearish Marubozu (1D, yukarıdaki parametre dağılımı) USDT-perpetual evreninde, **shuffle baseline'a göre istatistiksel olarak ayırt edilemez** (p ≥ 0.05) ya da **ensemble'a marginal Sharpe katkısı ≤ +0.05**'tir."

H0 reddi için her ikisi de gerekli:
1. Returns-shuffle baseline'a karşı one-sided permutation test p < 0.05
2. Marginal Sharpe ≥ +0.15

## 4. Dependent Variables (ölçtüğüm sonuç değişkenleri)

- `net_annual_return` (fee+slip dahil)
- `oos_sharpe` (walk-forward 12 dilim ortalaması)
- `max_dd_equity` (cum-PnL DEĞİL, account-equity bazlı — bkz audit_risk CT-RSK-01 dersi)
- `profit_factor`
- `win_rate`, `avg_R_winner`, `avg_R_loser`
- `trade_count_total`
- `pearson_rho_daily_pnl_vs_vsa_climax_test` (aynı 6.4y dilim, günlük net PnL)
- `marginal_sharpe_vs_vsa_alone` (ensemble = 50/50 risk-allocated)
- `regime_split_sharpe` (bull/bear/range)
- `stress_period_drawdown` (LUNA, FTX, BTC ATH 2024-03, Yen 2024-08)
- `shuffle_baseline_p_value` (1000 permutation, one-sided)
- `dsr`, `pbo` (Lopez de Prado)

## 5. Independent Variables (parametre ızgarası — KASITLI KALIN)

Curve-fit'i bastırmak için ızgara KASITLI KALIN. Toplam trial = **3 × 3 × 2 × 2 × 3 = 108**.

| Parametre | Grid | Gerekçe |
|---|---|---|
| `body_ratio_min` | {0.80, 0.85, 0.90} | Bulkowski 0.90'dan başla; 0.85/0.80 daha gevşek |
| `vol_mult` | {1.0, 1.2, 1.5} | volume onayı katmanlı |
| `ema_len` | {50, 100} | trend filtre uzunluğu |
| `sl_atr_mult` | {0.25, 0.50} | tight SL (marubozu high yakın) vs medium |
| `tp_R` | {1.5, 2.0, 2.5} | asimetrik kazanç skalası |

**Sabit:** `tail_tol = 0.05` (Bulkowski tanımı zaten "≈"), `body_pct_min = 0.015` (≥ 1.5% mutlak hareket — pseudo-marubozu süpürür), `atr_len = 14`, `risk_pct = 0.01`, fee=7.5bps, slip=5bps.

**Optuna YOK.** Tam grid (108 trial), Bonferroni n=108 / Benjamini-Hochberg FDR 0.05 düzeltmesi sonrası gate.

## 6. Beklenen p-value & Multiple-Testing Correction

- **Pre-Bonferroni hedef:** shuffle baseline permutation p < 0.01 (en iyi trial); OOS Sharpe > 0.8 ile.
- **Post-Bonferroni (n=108) gate:** p < 0.05 / 108 = **0.000463** → gerçekten istisnai bir sonuç gerekir.
- **Daha gerçekçi:** **Benjamini-Hochberg FDR 0.05** (paralel hipotezler arasında bağımlılık var → BH daha uygun) gate uygulanacak.
- **DSR ≥ 0.5** (Deflated Sharpe Ratio, n=108 trial için) zorunlu.
- **PBO ≤ 0.5** (combinatorially symmetric CV) zorunlu.

Eğer post-BH p > 0.05 VE DSR < 0.5 → **red** (terfi etmez).

## 7. Stop Criteria (kod çalışmadan önce yazılı durdurma noktaları)

Aşağıdakilerden herhangi biri tetiklenirse araştırma **derhal terkedilir** ve gerekçeyle `learning.md`'ye 3 satır yazılır:

1. **IS Sharpe < 0.6** → temel edge yok, devam etmenin anlamı yok
2. **IS/OOS Sharpe oranı > 3:1** → tipik overfit profili (RAG #1)
3. **|ρ| ≥ 0.50 vsa_climax_test ile** → mutlak korelasyon çok yüksek (pozitif veya negatif), diversifier başarısız (NOT: negatif yüksek korelasyon da iyi değil — ensemble'da net Sharpe katkısı sıfıra yaklaşır)
4. **Marginal Sharpe < +0.05** → ensemble katkısı yok, "tek başına iyi" bile olsa eklemenin anlamı yok
5. **min(walk-forward dilim Sharpe) < -1.0** → kırılgan, tek dilim kaybı pre-registered eşikleri yiyor
6. **Best params parametre uzayının uç noktasında** (örn. tüm en iyi 5 trial body_ratio=0.80 VEYA hepsi 0.90'da) → uzayı genişletmeden hipotezi savunamayız
7. **Stress dönemlerin ≥ 3/4'ünde -%20+ kayıp** → tail-risk uyumsuz
8. **Trade count < 250 toplam** → istatistiksel güç yetersiz; eşikleri gevşetmek = curve-fit
9. **Lookahead test başarısız** (`detector(df.iloc[:t+1])[t] != detector(df)[t]`) → kod hatası, hipotez değil mekanizma sorunu — kodu düzelt, sonuçları çöp

## 8. Curve-Fit Kırmızı Bayrakları (önceden işaretliyorum)

Sonuçlarda şu desenlerden biri görülürse "şüpheli" etiketi koyacağım:

- **Bulkowski equity-prior'a aşırı bağımlılık:** crypto'da çalışmama olasılığı yüksek; "çalışıyor" çıkarsa shuffle baseline'a karşı en az 3 farklı seed ile çapraz doğrulama
- **Single regime artifact:** P&L'in %50+'sı 2022 (LUNA + FTX) bear-dilim short'larından geliyorsa, bull-only ve range-only dilimlerde de pozitif olmadan terfi YOK
- **Single symbol artifact:** P&L'in %40+'sı tek sembolden geliyorsa, symbol-out CV'de tüm semboller pozitif olmalı
- **Tight grid escape:** body_ratio_min=0.90 best ise 0.95 trial'ını da koş; eğer 0.95 yıkılırsa "knife edge", red
- **Fee sensitivity:** taker 7.5 → 10 bps simülasyonunda Sharpe'in > %40'ı silinirse → real-world live'da edge kalmaz
- **Marubozu volume confounding:** vol_mult ≥ 1.5'te en iyi sonuç ÇIKARSA "asıl edge volume spike'tan, marubozu shape'inden değil" diye not düş — bu durumda VSA ile mekanik örtüşme tehlikesi (yani diversifier hedefi de boşa düşer)

## 9. Test Planı (sırayla)

1. **Lookahead test** (zorunlu): `tests/test_lookahead.py::test_marubozu_causality`
2. **Pattern verify:** rastgele 50 sinyal mum görsel olarak kontrol (sample, log dosyasına PNG ekran-görüntüsü değil; mekanik unit test)
3. **Single-symbol pilot:** BTCUSDT 1D, baseline parametrelerle (0.90/1.2/50/0.25/2.0) ham backtest — net negatif çıkarsa STOP (criterion #1)
4. **Pilot başarılıysa full grid (108 trial):** 15 sembol × 6.4y
5. **Robustness suite (zorunlu, SOP-3 tamamı):**
   - Walk-forward 3y/6m step 3m (12 dilim)
   - Param perturbation ±%10 / 50 seed
   - Symbol-out CV (LOO)
   - Regime split (bull/bear/range)
   - Stress (LUNA / FTX / BTC ATH 2024-03 / Yen 2024-08)
   - Shuffle baseline (1000 perm)
   - BH-FDR 0.05 düzeltmesi
   - DSR + PBO
6. **Diversifier ölçüm:** `vsa_climax_test`'in aynı dönem günlük PnL serisini çek (canlı + paper birleşik) → Pearson ρ ve marginal Sharpe hesapla
7. **Karar:**
   - Tüm gate ✓ + diversifier ✓ → Lab tournament aday (terfi)
   - Aylık ROI > 0 ama bir gate fail → **SOP-4b iterate** (red yasak): risk reduction / vol filter / regime subset versiyonları
   - ROI ≤ 0 veya lookahead/leakage tespit → gerekçeli arşiv (red)

## 10. Reproducibility

- git_hash: `<runtime_doldurulacak>`
- config_hash: `<runtime_doldurulacak>`
- data_hash: `<runtime_doldurulacak>` (universe snapshot + OHLCV manifest)
- random seed: 42 (shuffle baseline), 1..50 (perturbation)
- Tüm sonuç manifest'i `reports/research/bearish-marubozu-1d-<date>.html` + raw JSON

## 11. Pre-registration commit notu

Bu doc commit edildikten sonra hipotez **donduruluyor**. Aşağıdaki herhangi bir değişiklik **yeni doc gerektirir** (`supersedes: <bu doc_id>` ile):
- Universe değişikliği (sembol ekleme/çıkarma)
- Parametre ızgarası değişikliği
- Gate eşiği değişikliği
- Stop criteria gevşetme

Eşik **sıkılaştırmak** ise OK (pre-commitment'a sadık kalır, daha agresif red kabul). Gevşetme = p-hacking, kabul edilemez.

---

**Tahmin (prior gücü = düşük):** %60 olasılıkla H0 reddedilemeyecek (Bulkowski edge crypto'ya transfer olmayacak); %25 olasılıkla edge var ama vsa_climax_test ile |ρ| > 0.30 çıkacak (diversifier başarısız); %10 olasılıkla iterate gerekli (pozitif ROI, kötü DD); %5 olasılıkla terfi adayı çıkar. Reject etmeye hazırım.
