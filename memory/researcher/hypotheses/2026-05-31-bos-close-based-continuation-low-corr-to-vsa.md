---
doc_id: researcher-20260531T180000-bos-close-based-continuation-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-31T18:00:00Z
status: PROPOSED
confidence: med
depends_on:
  - shared-fact-vsa-climax-test-active
blocks: []
requested_review_from:
  - lab_scientist
  - risk_officer
  - adversary_engineer
tags:
  - hypothesis
  - cross_strategy
  - continuation
  - market_structure
  - bos
  - low_correlation
  - vsa_diversifier
  - pre_registration
supersedes: null
hash: null
---

# HYP-2026-05-31 — BOS Close-Based Continuation (Low-Corr Diversifier to `vsa_climax_test`)

> **Seed:** "Cross-strategy edge keşfi: aktif `vsa_climax_test` ile düşük korelasyonlu ek strateji (raftaki 66 adaydan)."
> **Cevap:** **Break of Structure (BOS, close-based, n=3 pivot)** — trend-state continuation profili; VSA climax'in exhaustion-reversal imzasına yapısal olarak ortogonal. Bugünkü kuyrukta mat_hold / bearish_marubozu / engulfing-continuation seed-abort'a girdi; BOS aile içinde **standalone hipotez tabanı henüz boş** (incidental mention dışında).

---

## 1. İddia (pre-registered, ölçülebilir)

Crypto perpetual USDT evreninde (≥40 likit sembol, **delisting'ler dahil — survivorship-clean**), **1D timeframe**'de, **1W EMA50 üzerinde** (long sinyalleri) / altında (short sinyalleri) HTF trend filtresi varken, aşağıdaki **close-based BOS** kuralı:

**Long BOS tetik:**
- **Pivot yapısı:** Son **n=3** barlık swing high tanımı — `bar[t-3:t]` aralığında local high pivot; `high[t-2] > high[t-3] AND high[t-2] > high[t-1]` (klasik 3-bar fractal).
- **Break şartı:** `close[t] > high[t-2]` (kapanış bazlı, intra-bar wick'ler sayılmaz — lookahead-safe; karar t kapanışı, giriş t+1 open).
- **Confirmation:** `close[t] > close[t-1]` (yön onayı tek bar).
- **Volume guard:** `vol[t] ≥ 0.8 × SMA(vol, 20)[t-1]` (climax dışlama — bu kuralın amacı VSA climax ile profili maksimum farklılaştırmak; **yüksek hacimde tetik istemiyoruz**).

**Short BOS tetik:** simetrik (swing low close-break).

**Entry:** `bar[t+1].open` (lookahead-safe; karar `t` close'a göre, giriş bir sonraki bar open'da)
**SL:** `1.5 × ATR(14)` (giriş ± yön)
**Exit (sweep edilecek — küçük grid):** {fixed `2.0R`, `10-bar opposite-channel trail`, `BE-protect @ 0.7R + 2.0R hard TP`} — **3 varyant, başka switch yok**.
**Window:** 2021-01-01 → 2025-12-31 (5y); **son 6 ay (2025-07-01 → 2025-12-31) strict OOS hold-out** (tek dokunuş).
**Maliyet:** taker fee 7.5 bps + slippage 5 bps (her giriş/çıkış).

### Hard gate'ler (hepsi sağlanmalı, AND koşulu)

| Metric | Hard Gate | Gerekçe |
|---|---|---|
| OOS Annualized net return (fee+slip sonrası) | **≥ %18** | Çağrı: marginal Sharpe pozitif kalsın diye Curator eşiği |
| OOS Sharpe (annualized, daily PnL, √365) | **≥ 0.8** | Chan retail-realistic single-asset eşiği [#9] |
| OOS MaxDD (**account equity** bazında, ADR-RSK-01 uyumlu) | **≤ %22** | Active live MaxDD %-15'in üstüne taşmamalı |
| Trade count N (5y × evren) | **≥ 100** | İstatistiksel taban; Volman ii/iii güç eşiğinin altı geçersiz |
| Profit factor | **≥ 1.30** | konservatif fee modeline emniyet payı |
| **Pearson corr(daily PnL, `vsa_climax_test` daily PnL)** | **≤ 0.20** | **BU İDDİANIN ÇEKİRDEĞİ** — diversification edge; sağlanmazsa 5 metrik geçilse bile **TERFİ EDİLMEZ** |
| Walk-forward dilim başarı (3y/6m, step 3m → 12 dilim) | **≥ 9/12 pozitif** | Robustness; varyans-ort. dengesi |
| Shuffle baseline empirical p (1000 perm) | **< 0.000231** | Bonferroni N=216 grid (3 exit × 4 ATR_SL × 6 n_pivot × 3 vol_guard) |
| **DSR (Deflated Sharpe, Bailey-Lopez)** | **> 0.5** | Lopez de Prado 6-kriterinden birincisi [#1] |
| In-sample / OOS Sharpe oranı | **IS/OOS ≤ 2.0** | overfit kırmızı bayrağı; Lopez kriter #4 (3·OOS) yarısı |

---

## 2. Null hipotez (H0)

H0: BOS close-based continuation post-tetik `t+1` open giriş, **shuffle baseline** (returns rastgele karıştırılmış null) ile karşılaştırıldığında bootstrap Sharpe dağılımının %95 CI'sının dışına Bonferroni-sonrası anlamlılıkla çıkmaz (`p ≥ 0.000231` corrected). Brooks'un "n-bar high/low aşımı + geri dönüş" notunun [#3] **continuation** versiyonu olan close-break, kripto perpetual fee/slip modelinde anlamlı pozitif beklenti üretmez.

H0 reddedilirse → H1 geçici kabul → Lab tournament adayı.

---

## 3. Gerekçe (RAG referansları + ex-ante korelasyon argümanı)

1. **[book_market_structure_order_flow §BOS (#6 score=0.568)]** — "BOS (close-based, n=3) → **Mekanik Çalışabilirlik: Yüksek**; net kural, backtestable, az parametrik." RAG'in 1D crypto için doğrudan onay verdiği tek market-structure adayı.
2. **[book_brooks_deep_catalog §reversal/continuation (#3 score=0.579)]** — n-bar high/low aşımı + reversal/continuation rejimi "test edilebilir mi: 5/5" notuyla en güçlü adaylar arasında.
3. **[book_candlestick_statistics §Inside Bar (#2 score=0.581)]** — Tekli inside bar zayıf (%54), ama **breakout** versiyonu (iii) daha güçlü. BOS = inside-cluster sonrası swing break ile yapısal akrabalık.
4. **[book_chan_summary §Sharpe gating (#9 score=0.558)]** — single-asset Sharpe > 0.8 OOS eşiği; bu hipotezin hard gate'inde **direkt** kullanılıyor.

### Düşük korelasyon ex-ante argümanı (sayısal mantık)

`vsa_climax_test` ana tetik koşulları (kanıtlanmış): **(a) yüksek hacim z-score (vol_z ≥ ~2.0)** + **(b) wide-range bar** + **(c) trend uçundan reversal candle**. BOS'un tetikleri ise: **(a') vol ≤ 0.8 × SMA(20)** (climax exclusion — explicit!) + **(b') trend yönünde close-break** + **(c') HTF EMA50 ile aynı yönde**. (a) ve (a') zaten karşılıklı dışlayıcı koşullar; (b)/(b') ve (c)/(c') ortogonal. Bu yüzden hard gate **ρ ≤ 0.20**'nin sağlanmaması yapısal bir hipotez ihlali — eğer sağlanmazsa **ya implementasyonda bug var ya da BOS aslında VSA climax'in zayıf bir mirror'ı**, iki durum da **terfi edilmemeyi** zorunlu kılar.

---

## 4. Dependent variables (ölçülen — log'lanacak)

- `annualized_net_return_oos` (%)
- `sharpe_oos`, `sharpe_is`, `sharpe_ratio_is_over_oos`
- `maxdd_equity_oos` (%, account equity bazında)
- `profit_factor_oos`
- `n_trades_total`, `n_trades_per_symbol_min`
- `win_rate_oos`
- `avg_R_winner`, `avg_R_loser`
- `pearson_corr_daily_pnl_vs_vsa_climax_test` (OOS dilim)
- `wf_slice_positive_count` (12 dilimden kaçı pozitif)
- `shuffle_p_empirical` (1000 perm)
- `dsr_bailey_lopez`
- `bonferroni_alpha_threshold` (grid boyu × 0.05)
- `regime_split_sharpe`: {bull, bear, range} ayrı ayrı
- `stress_period_pnl`: {2022-05 LUNA, 2022-11 FTX, 2024-03 BTC ATH, 2024-08 Yen carry}

## 5. Independent variables (parametre uzayı — sweep edilen, GRID SAYILACAK)

Dürüst grid: **3 × 4 × 6 × 3 = 216** kombinasyon (multiple testing düzeltmesi buna göre).

| Param | Aralık | Adım | Mantık |
|---|---|---|---|
| `exit_variant` | {`2R_fixed`, `10bar_trail`, `BE_07R_then_2R`} | — | exit aile |
| `atr_sl_mult` | [1.0, 1.5, 2.0, 2.5] | 0.5 | grid kabası — **ince adım YASAK** (curve-fit kırmızı bayrak) |
| `n_pivot` | [3, 4, 5, 6, 7, 8] | 1 | pivot pencere |
| `vol_guard_threshold` | [0.6, 0.8, 1.0] × SMA(vol,20) | — | climax dışlama eşiği (1.0 = guard yok kontrol) |

**SABİT (sweep edilmiyor — overfit yüzeyini kısıtla):**
- HTF filter: `close > EMA50(1W)` (sabit, değiştirilmiyor)
- ATR window: 14 (sabit)
- Vol SMA window: 20 (sabit)
- Confirmation: `close[t] > close[t-1]` (sabit)

---

## 6. Beklenen p-value

- **Naïve eşik:** p < 0.05
- **Bonferroni düzeltilmiş (N=216):** **p < 0.000231**
- **Benjamini-Hochberg FDR (alternatif, daha hafif):** q < 0.05 — terfi için en az **Bonferroni** istiyorum (paranoid mod).
- **Shuffle baseline metodu:** OOS PnL serisinin sembol-içi günlük getirilerini 1000 kez random permute, her permutation'da Sharpe hesapla, gerçek OOS Sharpe'ın yüzdelik dilimi → empirical p.

---

## 7. Stop criteria (araştırmayı terk koşulları — ÖNCEDEN bağlanmış)

Aşağıdakilerden **HER HANGİ BİRİ** gerçekleşirse hipotez **derhal reddedilir**, gerekçeli arşive yazılır, iterate açılmaz:

1. **In-sample Sharpe < 0.5** → temel beklentinin altı; iterate'in başlangıç noktası yok.
2. **N_trades_total < 100** → istatistiksel taban yetersiz.
3. **ρ(BOS, vsa_climax_test) > 0.40 in-sample bile** → diversification temel argümanı çürür (yapısal); ince ayar bunu kurtaramaz.
4. **Best params parametre uzayının kenarında** (`atr_sl_mult=2.5` veya `n_pivot=8` çıkarsa) → aralık yetersiz, ya genişlet ya bırak; ben **bırakacağım** (curve-fit kırmızı bayrak #2).
5. **IS/OOS Sharpe oranı > 3.0** → Lopez kriter #4 ihlali, deploy yasak.
6. **2022-05 LUNA veya 2024-08 Yen-carry stress dilimlerinden HERHANGİ BİRİNDE %-15+ rolling DD** → tail-risk profili kötü, iterate eşiği bile aşıldı.

**Iterate hakkı (SOP-4b):** Yukarıdaki 6 stop criteria'nın HİÇBİRİ ihlal edilmediyse AMA DD sadece marjinal aştıysa (örn. `MaxDD = %25` vs hedef `%22`), iterate açılır — risk_pct azaltma, trade-quality filtresi, BE-protect varyantı. **Aksi halde temiz red.**

---

## 8. Curve-fit şüphe günlüğü (zorunlu — pre-registration parçası)

Bu hipotez aşağıdaki noktalardan **şüpheli**:

1. **Brooks/Bulkowski/Wyckoff literatür havuzu kripto-specific değil.** Equity / FX'ten gelen continuation rate'leri (%64-74) kripto perpetual fee modelinde aynı kalmayabilir. **Korunma:** OOS hold-out 6 ay tek dokunuş + Bonferroni.
2. **BOS tanımı "swing pivot" alt-parametrelerine duyarlı.** n=3 vs n=5 vs fractal-Williams varyantları → 6 farklı tetik üretebilir. **Korunma:** parametre uzayını grid'de açıkça sayıyorum, FDR çoklu test düzeltmesi var.
3. **`vol_guard ≤ 0.8 × SMA(20)` koşulu literatürde standart değil — `vsa_climax_test` ile korelasyonu azaltmak için tasarlandı.** Bu **purpose-built** olduğu için **circular reasoning** riski var (low-corr istiyorum → low-corr için filtre koyuyorum → low-corr ölçüyorum). **Korunma:** `vol_guard=1.0` (yani guard yok) kontrol grubu **mutlaka** grid'de var; eğer guard ÇIKARILDIĞINDA da ρ ≤ 0.30 kalıyorsa argüman dayanaklı, aksi halde **structurally artificial**.
4. **5 yıllık kripto datası 1-2 büyük rejim içerir (2021 bull, 2022 bear, 2023 chop, 2024 bull) → effective independent regime count düşük.** Walk-forward dilim sayısı 12'ye çıkarmak istatistik gücü artırmıyor, sadece görüntü veriyor. **Korunma:** regime split metriği zorunlu.
5. **`enabled.*true` filtresinde sadece `classic_pa.yaml` aktif görünüyor — vsa_climax_test'in canlı PnL serisinin doğru kaynaktan çekildiğini lab_scientist'in çapraz doğrulaması ile teyit etmek gerekiyor**, aksi halde ρ hesabı yanlış serinin üstüne kurulur.

---

## 9. Reproducibility

- `git_hash`: doldur (run anında)
- `config_hash`: doldur
- `data_hash`: DuckDB snapshot hash'i (5y, delisted dahil)
- `seed`: 42 (Optuna sampler için)
- Backtest komutu: `python -m price_action.backtest.engine --hyp HYP-2026-05-31-bos-close-based-continuation-low-corr-to-vsa --grid configs/research/bos-close-grid.yaml --oos-holdout 2025-07-01:2025-12-31`

---

## 10. Karar matrisi (post-test)

| Sonuç | Aksiyon |
|---|---|
| Tüm hard gate'ler ✓ + Bonferroni p < 0.000231 + DSR > 0.5 + ρ ≤ 0.20 + vol_guard=1.0 kontrolünde de ρ ≤ 0.30 | **Lab tournament adayı (PROPOSED → REVIEWED → Lab queue)** |
| 5/6 gate ✓ AMA MaxDD marjinal aşıyor (≤ %30) + edge ρ ≤ 0.20 | **Iterate v2: risk reduction (SOP-4b)** |
| ρ > 0.40 (in-sample) | **Stop criteria #3 → red, arşiv** |
| Best params kenarda | **Stop criteria #4 → red, arşiv** |
| Bonferroni sonrası p ≥ 0.000231 | **Red — şans, arşiv** |
| `vol_guard` kaldırıldığında ρ patlıyor | **Structurally artificial → red + learning.md'ye not** |

---

**Pre-registration commit hash:** (commit anında doldur)
**Hash dondurulduktan sonra hipotez body değiştirilemez; revizyon = yeni doc + `supersedes`.**
