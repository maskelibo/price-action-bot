---
doc_id: researcher-20260613T000000-volman-ii-double-inside-bar-d1-vsa-diversifier
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-13T00:00:00Z
status: DRAFT
confidence: low
depends_on:
  - researcher-20260611-vsa-climax-volz-sweep
  - researcher-20260612T100101-turtle-channel-20bar-d1-cross-edge
  - configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, cross-edge, low-corr-to-vsa, volman, double-inside-bar, ii-breakout, compression-expansion, daily, pre-registered]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-13-volman-ii-double-inside-bar-d1-vsa-diversifier

## 0. Meta

- **Tarih:** 2026-06-13 (Asia/Istanbul)
- **Versiyon:** 0.1 (pre-registration, kod yazımından önce dondurulmuş)
- **Tema:** Aktif `vsa_climax_test` (15m, volume-climax exhaustion fade) ile **düşük korelasyonlu**, fundamentally farklı mekaniğe sahip bir aday.
  - VSA-climax = **volume-driven**, **mean-reversion**, **intraday (15m)**
  - Aday seçim kuralı: yapısal olarak (a) volume-bağımsız, (b) breakout (mean-reversion DEĞİL), (c) zaman çerçevesi farklı (1D) → ortogonal en yüksek olasılık.
- **Aday strateji:** Volman "ii" (double inside bar) breakout — RAG #2 doğrudan referans: *"Volman eklemi: Tekli inside bar zayıf; ancak 'ii' (double inside bar) veya 'iii' breakout daha güçlü."*
- **Neden bu, neden şimdi:** Klasik 1D evreninde halihazırda test edilmiş seçenekler tükeniyor (donchian, MA-cross, marubozu, mat hold, BOS, FVG, equal-highs sweep, iii-marubozu, turtle 20bar). Pure `ii` standalone 1D crypto perp'de kayıtlı **değil** (iii-marubozu confluence başka pattern). Bu hipotez tek başına olabilir ama deliller karışık → red beklentisi default %65.

## 1. İddia (Pre-Registered, Ölçülebilir)

> **"2022-01-01 ile 2025-05-31 arasında (in-sample 3y4ay), 19-sembollik USDT-perpetual evreninde (survivorship-free `build_pool_19sym`), 1D timeframe'de:**
>
> Üç ardışık bar `(t-2, t-1, t)` için **t-1 bar'ı t-2 bar'ının range'inde tamamen içeride** VE **t bar'ı t-1 bar'ının range'inde tamamen içeride** ise pattern oluştuğu kabul edilir (Volman "ii"). Tetik: bir sonraki bar (t+1) açılışında, eğer t+1 high > t-1 high → long stop emri tetikler; t+1 low < t-1 low → short stop emri tetikler. Aynı bar her iki yönü de tetiklerse iptal (ambiguous breakout, atla).
>
> **Giriş:** tetik bar'ının open + (kırılan tarafa göre) t-1 extreme + 1 tick'lik stop entry → market'e dönüşür.
> **Stop:** ters yöndeki t-1 extreme (long için t-1 low, short için t-1 high). Bu yapısal stop, ATR çarpanı **DEĞİL** — Volman'ın orijinal kuralı.
> **Hedef:** 2R fixed take-profit (TP1 = giriş + 2·initial_risk).
> **Fee:** 7.5 bps taker / 5 bps slippage. **Risk:** %1/trade fixed-fraction, account equity bazlı.
>
> Aşağıdaki TÜM eşikleri eşzamanlı tutturursa edge gerçek sayılır:
>
> 1. **Aylık net ROI ≥ %1.0** (fixed-fraction, taze-$10k ay başı, NO compounding inflation)
> 2. **Annualized Sharpe ≥ 0.80** (daily-bar return × √252, CT-RES-01 katalog)
> 3. **MaxDD ≤ %22** (rolling peak account equity, zero-base PnL DEĞİL)
> 4. **Profit factor ≥ 1.35**
> 5. **Win rate ∈ [%38, %52]** — bant. >%55 lookahead şüphesi, <%35 statistical noise
> 6. **n_trades_pool_total ≥ 120** (3y4ay × 19 sym; eğer < 120 → istatistik blöfü yok, red)
> 7. **Aylık return korelasyonu |ρ(volman_ii_1d, vsa_climax_test)| ≤ 0.20**
>
> Ayrıca **OOS pencerede (2025-06-01 → 2026-05-31, 12ay dokunulmaz)** Sharpe IS değerinin **≥ %55**'ini korumalı."

## 2. Null Hipotez (H0)

Çift inside bar breakout'un 1D crypto perp'de pozitif edge'i **yoktur**. Ölçülen P&L shuffle baseline (returns bootstrap, n=1000) ile p ≥ 0.05 düzeyinde ayırt edilemez VEYA Bulkowski'nin tek inside bar için verdiği %54 win rate (RAG #2) "double" katmanıyla anlamlı şekilde değişmez (yani ii ≈ i, edge yok).

**Alternatif H0:** Pattern istatistiksel olarak pozitif gözükür ama 2024-bull rejiminden tekil katkı → regime split'te bear/range negatif → "yapısal edge" hikâyesi çöker.

## 3. Gerekçe ve Literatür (RAG Referansları)

1. **[Bulkowski / Volman — Inside bar (RAG #2, score=0.581):** *"Tekli inside bar zayıf (%54 breakout WR, rank 78/103); ancak 'ii' (double inside bar) veya 'iii' breakout daha güçlü."* Bu **nicel olarak desteklenmemiş bir iddia** — Bulkowski tek inside bar için sayı veriyor ama ii için vermiyor. Volman'ın kendi yazınında ii daha "trade-edilebilir" diye geçer ama net win-rate yok. → **Bu hipotezin temel açığı: literatür "daha iyi" diyor ama "ne kadar iyi" demiyor.** Pre-mortem: %65 ihtimalle red beklenir.

2. **[Brooks — n-bar high/low aşımı + reversal (RAG #3, score=0.579):** Brooks'un "reversal bar" katalogu Volman ii pattern'ından farklı (Brooks reversal bar bir bar'ın kendisi, ii üç bar'lık sıkışma). Ama **breakout sonrası "failed breakout reversal" yapısı her iki ailede de var**. ii breakout başarısız olursa ne olur sorusu kritik — bu post-hoc, hipotezin gate'i değil ama rapor edilir.

3. **[Kaufman — Channel Breakout failure mode (RAG #7, score=0.563):** "Choppy/range-bound rejimde back-to-back whipsaw; **kümülatif %20-40 drawdown** mümkün." ii breakout da bir compression-expansion pattern → choppy rejimde **whipsaw kümülasyonu** aynı risk. **MaxDD ≤ %22 eşiğim sıkı**, çünkü 1D crypto choppy rejim sıklığı düşük değil.

4. **[Lopez de Prado (RAG #1, score=0.582):** Altı kırmızı bayrak. Tek parametre seti (sweep yok) → PBO ve "Sharpe>3·OOS" otomatik koruma. DSR, MinBTL, walk-forward Sharpe varyansı raporlanacak.

## 4. Independent Variables (Pre-Registered, KİLİTLİ — sweep yasak)

| Param | Değer | Sweep? | Gerekçe |
|---|---|---|---|
| `inside_depth_N` | **2** (yani ii) | **HAYIR** | RAG #2 doğrudan: ii vs iii. iii zaten test edilmiş (`2026-06-12-iii-marubozu-confluence-1d`). Sweep yapmak iii ile retro-comparison cherry-pick olur. |
| `entry_trigger` | **t-1 extreme + 1 tick stop entry → fill ise market** | HAYIR | Volman orijinal kuralı |
| `stop_rule` | **t-1 opposite extreme** (yapısal, ATR DEĞİL) | HAYIR | Volman orijinal; ATR'ye geçirmek "stop tuning" cherry-pick'i olur |
| `tp_rule` | **2R fixed** | HAYIR | Volman target standart; trailing eklemek post-hoc tuning |
| `timeframe` | **1D** | HAYIR | RAG #2 'ii' equities/forex bağlamında, crypto 1D bar zaten yüksek-bilgi-bar; intraday'e indirmek farklı hipotez olur |
| `risk_per_trade` | **%1.0** | HAYIR | policy floor |
| `direction` | **long + short, ikisi de raporlanır** | — | Kabul kararı **kombine net P&L'e** bağlanır |
| `volume_filter` | **YOK** | HAYIR | volume filter eklemek aday'ı VSA-climax'a yaklaştırır → diversifier amacını delerdi |
| `regime_filter` | **YOK (in-sample)** | HAYIR | regime filter SOP-3 robustness'ta REPORT edilir, hipotez kabul/red kuralı DEĞİL; aksi halde post-hoc tuning |

**Curve-fit kırmızı bayrak savunmaları (Lopez de Prado RAG #1):**

- Tek parametre seti, n_trials=1 → Bonferroni/FDR gerekmez. EĞER backtest sonucu görüldükten sonra "depth=3 deneyim" diyorsam: o anda **bu hipotez RED arşivlenir**, yeni doc açılır, eski sonuç independent sample olamaz (frequentist disiplin).
- Hiçbir param crypto/post-2017 verisinden tüne edilmedi → in-sample bilgi sızıntısı yok.
- Volume filter eklemediğim için "veri görüldükten sonra volume filter ekleyip kurtarma" yolu kapalı — ya öyle çalışır ya çalışmaz.

## 5. Dependent Variables (Pre-Registered Ölçüm)

| Metric | Eşik | Yön | Notlar |
|---|---|---|---|
| `monthly_net_roi_avg` | ≥ %1.0 | ↑ | fixed-fraction $10k, taze ay başı reset |
| `sharpe_annualized` | ≥ 0.80 | ↑ | daily-bar return × √252 |
| `max_dd_account_equity` | ≤ %22 | ↓ | rolling peak account equity (CT-RSK-01) |
| `profit_factor` | ≥ 1.35 | ↑ | gross win / gross loss |
| `win_rate` | %38 — %52 | bant | bant dışı → leak/noise şüphesi |
| `n_trades_pool_total` | ≥ 120 | ↑ | aksi halde p anlamsız |
| `corr_monthly_with_vsa_climax_test` | abs ≤ 0.20 | ↓ | Pearson, aktif strateji aylık return series |
| `corr_monthly_with_iii_marubozu_1d` | abs ≤ 0.45 | ↓ | yakın akraba pattern — redundancy testi |
| `corr_monthly_with_turtle_donchian_20_1d` | abs ≤ 0.45 | ↓ | yakın akraba (compression→expansion) |
| `oos_sharpe / is_sharpe` | ≥ 0.55 | ↑ | Lopez IS≤3·OOS inversi |
| `shuffle_baseline_p_value` | < 0.05 | ↓ | 1000 returns bootstrap |
| `max_R_realized / mean_R_realized` | rapor | — | tek bar baskın katkı kontrolü; eşik DEĞİL |

## 6. Beklenen p-değeri ve Önsel Tahmin

- Shuffle baseline (n=1000) altında **beklediğim p ∈ [0.10, 0.30]** — yani null reddi **muhtemelen marjinal başarısız**. Bu samimi pre-mortem; başarı bekliyorsam neden test ediyorum sorusunu cevaplıyor: literatür güçlü iddia ama nicel destek zayıf, samimi belirsizlik yüksek.
- **%65 ihtimalle red** (gate gözden geçirildiğinde n_trades<120 veya Sharpe<0.8 veya |ρ_vsa|>0.20).
- **%25 ihtimalle iterate** (pozitif ay ama DD>22 veya korelasyon marjinal).
- **%10 ihtimalle terfi adayı** (tüm gate temiz).

## 7. Stop Criteria (Erken Vazgeçme — SOP-3 detayına geçmeden)

Aşağıdakilerden biri tetiklenirse araştırma DERHAL terkedilir:

1. **In-sample Sharpe < 0.40** → edge yok, devam etme.
2. **n_trades_pool < 80** → istatistik kuşkulu, evren küçük kalmış demek. Genişletme (66 → daha büyük pool) **bu hipotezin gate'i değil**, yeni hipotez gerekir.
3. **|corr_with_vsa_climax_test| > 0.35** → diversifier amacı çöktü, edge gerçek olsa bile portföye katmıyoruz.
4. **|corr_with_iii_marubozu_1d| > 0.60** → kardeş pattern redundant; iki ayrı slot harcamayız.
5. **MaxDD > %35** → kapasitemiz dışı, iterate bile kurtaramaz.
6. **OOS Sharpe / IS Sharpe < 0.25** → ağır overfit kanıtı; başkasını dene.
7. **2022-bear ve 2024-bull aynı işaretli değil** (ikisi de negatif veya birbirine zıt > 3x) → regime bağımlı şans, edge değil.

## 8. Curve-Fit / Lookahead / Bias Pre-Mortem (Adversary Engineer'a açıklama)

**Şüphelendiğim ve kırılgan noktalar (red team okuyacak):**

1. **"ii daha güçlü" iddiası nicelendirilmemiş** — Bulkowski/Volman literature kalitatif. Ölçtüğümde %54 (tek inside bar) civarında çıkarsa null reddedilemez. Bu hipotezin **en zayıf noktası**.
2. **Lookahead riski (klasik):** Inside-bar tespiti `df['high'].shift(2)`, `df['high'].shift(1)`, `df['high']` üzerinden mekaniğin causality test'ten geçmesi şart. Karar `t` bar kapanışında oluşur, giriş `t+1` open'da. `tests/test_lookahead.py` zorunlu.
3. **Stop entry slippage modeli:** Stop emir t+1 open'da fill olursa aslında t+1 open price ile gap olabilir (kripto 1D'de gap nadir ama bull/bear flip günlerinde olur). Konservatif: gap > %1 olduğu günlerde **fill = t+1 open** (slip = gap), pozisyon büyüklüğü hesabı **planlanan** stop'a göre değil **gerçek** stop'a göre yapılır → planned R vs realized R divergence raporlanır.
4. **Ambiguous breakout (her iki yönü tetikleyen bar) atlanır kuralı:** Eğer çok sık atlama olursa n_trades < 120 floor'una takılırız. Bu **özellik** değil, **risk**.
5. **2R fixed TP'nin trend günlerinde erken çıkması:** "Big bar follow-through"u kaçırırım → max_R_realized düşük olur. Bu ölçülecek ama **kabul gate'i değil** (post-hoc bias yaratmamak için).
6. **Crypto 1D bar morphology farkı:** Equities/forex'te ii sıkışması doğal cycle; crypto 7/24 pazarda inside bar mekaniği değişebilir (haftasonu likidite düşük, inside bar yapay görülebilir). **Symbol-out CV** ve **weekday-out** testi raporlanır.
7. **66-shelf efekti:** Eğer Lab tournament'a bu 67. olarak girerse, "66 strateji içinden 1 tane Sharpe>0.8 tutturanı seç" otomatik survivorship → DSR düzeltmesi shelf seviyesinde Lab tarafından uygulanmalı, **bu hipotezin sorumluluğu değil ama not edildi**.

## 9. Backtest Setup (SOP-2)

- **Universe:** `scripts/research/build_pool_19sym.py` (survivorship-free, delisting-aware) — 19 sym
- **Period IS:** 2022-01-01 → 2025-05-31 (3y4ay)
- **Period OOS:** 2025-06-01 → 2026-05-31 (12ay, **dokunulmaz hold-out** — bu pencereye hipotez kabul sonrasına kadar bakma)
- **Engine:** `backtest/engine.py` (vectorbt veya bespoke)
- **Fees:** taker 7.5 bps, maker -1 bps; entry stop-market → taker
- **Slippage:** 5 bps base + gap günleri için realized open price
- **Initial capital:** $10,000 USDT, fixed-fraction her ay reset (compounding inflation lessonu)
- **Sizing:** %1 risk / trade, account equity bazlı

## 10. Robustness Suite (SOP-3 — hipotez kabul için TÜMÜ ✓)

1. Walk-forward 12 dilim (3y train + 6m test, step 3m); Sharpe varyans / ortalama < 1.0
2. **Param perturbation YAPILMAYACAK** — kilitli set; sweep BIAS olur
3. Symbol-out CV (leave-one-out, 19 dilim); minimum sembol-out Sharpe ≥ %50 × ortalama
4. Regime split (bull / bear / range, en az 2'sinde pozitif net P&L)
5. Stress periods: 2022-05 (LUNA), 2022-11 (FTX), 2024-03 (BTC ATH), 2024-08 (Yen carry) — hiçbirinde toplam P&L > -%8
6. Shuffle baseline (returns bootstrap n=1000, p < 0.05)
7. Multiple testing correction: GEREKMEZ (n_trials=1, sweep yok)
8. **Lookahead causality test ZORUNLU** — fail ise tüm sonuçlar geçersiz
9. Weekday-out (Pzt-Paz, 7 dilim) — herhangi bir günde > %40 total P&L katkısı varsa kırılgan

## 11. Karar Çerçevesi (3 yol, SOP-4)

- **Tüm 7 eşik (madde 5) + tüm 9 robustness (madde 10) ✓** → **terfi adayı**, Lab tournament için aday config:
  `configs/strategies/volman_ii_double_inside_breakout_1d_diversifier.yaml` (taslak; insan onayı gerekir)
- **Aylık net ROI > 0 ama gate'i geçemez** (SOP-4b, max 5 versiyon iterate):
  - v2: risk %1 → %0.5 (DD reduction)
  - v3: 2R TP → trailing 5-bar opposite extreme (peak give-back azaltma; AMA bu kabul edilirse iterate olarak ayrı raporlanır)
  - v4: ADX>20 prefilter (Kaufman whipsaw uyarısına yanıt — sadece trending rejimde trade)
  - v5: weekday-out (zayıf gün dilim çıkar) — eğer madde 10.9 alarm verdiyse
- **Aylık net ROI ≤ 0 VEYA |ρ_vsa| > 0.35 VEYA OOS Sharpe / IS < 0.25** → **red**, gerekçeli arşiv, yeni hipotez bekle.

## 12. Reproducibility

- `git_hash`: (pre-registration commit hash — bu doc commit'lendiğinde)
- `config_hash`: backtest config dondurulduğunda
- `data_hash`: 19sym pool snapshot (build_pool_19sym output hash)

## 13. Yorumcu Notu (Researcher → Lab / Risk / Adversary)

Bu hipotez **muhtemelen reddedilecek** (önsel %65). Yazıyorum çünkü:
1. Literatür (RAG #2) niceleştirilmemiş bir iddia içeriyor — test edilmesi gereken samimi belirsizlik
2. VSA-climax ile yapısal ortogonalite teorik olarak yüksek (volume-bağımsız vs volume-driven; breakout vs fade)
3. Tek parametre seti, sweep yok → fail edersek "ii ≠ better than i in crypto 1D" temiz null bulgu

**Adversary Engineer kill-probe gating zorunlu** olur eğer terfi adayına dönerse — özellikle LUNA + FTX + 2024-08 yen carry pencereleri (compression patternlerinin volatilite expansion günlerinde nasıl yıkıldığı kritik).

**Lab tournament**: tek başına değil, vsa_climax_test ile birlikte ensemble Sharpe lift > %12 mi sorusunu Lab cevaplar; bu hipotezin gate'i değil.

**Sözüm:** OOS Sharpe / IS Sharpe < 0.55 ise araştırmayı bırakırım. Hikâye yazmam, "v2'de düzelir" demem; arşivler, bir sonraki hipoteze geçerim. Win rate > %55 çıkarsa lookahead/leak şüphesi otomatik açılır, çift causality testi koşulur.
