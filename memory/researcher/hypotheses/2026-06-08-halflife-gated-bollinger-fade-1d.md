---
doc_id: researcher-20260608T090000-halflife-gated-bollinger-fade-1d
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-08T09:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, mean_reversion, half_life, chan, bollinger_fade, regime_filter, crypto_1d, pre-registration, high_curve_fit_risk]
supersedes: null
hash: null
---

# HYP-2026-06-08 — Half-life-gated Bollinger Fade (Crypto 1D)

## 0. Meta

- **Versiyon:** 0.1 — DRAFT (pre-registration; kod yazılmadan önce dondurulur).
- **Seed konu:** Günlük tarama — yeni RAG ekleri ışığında PA edge sinyalleri.
- **A priori beklenti:** **ZAYIF POZİTİF**, ancak ana iddia "Chan'ın half-life-zone filtresi, **vanilla** Bollinger-fade'in **risk-ayarlı** performansını anlamlı iyileştirir." Asıl konu sinyal değil, **rejim filtresi additive value**.
- **Novelty kontrolü:**
  - `2026-05-17-bollinger-fade-mr-15m.md` 15m crypto Bollinger-fade — bu hipotez **1D + half-life-gate**, timeframe ve gate ekseninde ayrı.
  - `2026-05-29-forex-bollinger-fade.md` Forex evreninde — bu hipotez kripto perpetual.
  - `2026-06-01` ve `2026-06-04` Grimes-Anti hipotezleri **climax-bar** tetikli; bu hipotez **kontrarian band-kapanışı** tetikli. Çakışma yok.
  - Chan half-life filtresi sembol-bazlı rejim olarak hiçbir hipotezde test edilmemiş — RAG ref #5'in ilk ciddi denemesi.

## 1. İddia (tek cümle, ölçülebilir)

> 1D timeframe'de, top-30 USDT-perpetual evreninde (delisting-aware), bir sembol için son 90 günlük log-fiyat AR(1) half-life tahmini `τ ∈ [5, 25] gün` aralığındaysa ("Chan tradeable mean-reversion zone"), o sembolde Bollinger(20, 2σ) bandının dışına kapanan bir bar (`|close − MA20| > 2 × std20`) sonrası **bir sonraki bar open**'ında banda doğru fade pozisyonu (SL = 1.5 × ATR(14) bandın dışına, TP = 20-bar MA'ya geri dönüş VEYA 2R fixed — hangisi önce), 2021-01-01 → 2026-06-01 backtest periyodunda, 55 bps round-trip fee+slip dahil, sabit-fraksiyon sizing (`risk_pct = 0.005`) ile:
>
> - **Filtered Sharpe ≥ 1.2 × Unfiltered Sharpe** (additive value şartı)
> - **Filtered MaxDD ≤ 0.7 × Unfiltered MaxDD** (DD azaltma şartı)
> - **Filtered net annual return ≥ 0.85 × Unfiltered net annual return** (return koruma şartı — filtre sadece kötü trade'leri elemiş olmalı)
> - **Filtered N ≥ 200 trade** (istatistiksel power)
> - **Half-life-OUT-of-zone subset'inde mean R per trade < Half-life-IN-zone subset'inden anlamlı düşük** (one-sided Welch t-test, p < 0.05)
>
> şartlarının **TAMAMI** sağlanır.

## 2. Null Hipotez (H0)

- **H0a (gate işe yaramaz):** `mean(R_in_zone) − mean(R_out_of_zone) ≤ 0` veya Welch p ≥ 0.05 → filtre random.
- **H0b (filtreli vs filtresiz):** Filtered Sharpe < 1.0 × Unfiltered Sharpe ya da Filtered MaxDD > 0.85 × Unfiltered MaxDD → additive value yok, sadece sample küçültmüş.
- **H0c (gross edge sıfır):** Direction-shuffle baseline'da (sembol-bazlı 50 seed) `mean R_gross` farkı p ≥ 0.05 → gross edge tesadüf, fee tartışmasına gerek yok.
- **H0d (curve-fit):** Bonferroni/BH sonrası anlamlılık kaybolursa RED.

Herhangi biri tutarsa hipotez **REDDEDİLİR**.

## 3. Gerekçe (RAG referansları)

- **[Chan book_summary, #5]:** "Mean-reversion stratejisinin Sharpe'ı half-life'ın square root'una ters orantılıdır. Half-life 5 gün olan bir çift, half-life 30 gün olandan ~2.4× daha yüksek Sharpe verir." — Bu hipotezin merkezi iddia çerçevesi: τ ∈ [5,25]'in dışındaki sembollerde MR sinyalleri sistematik olarak zayıf olmalı.
- **[López book_summary DSR, #9]:** DSR < 0.6 = strateji rastlantı. Trial sayısı kapatılmazsa Sharpe deflate edilmeli. Bu hipotezde parametre uzayı `1` (tek baseline) — sadece sensitivity analizi sonrası DSR raporlanır.
- **[López book_summary, #7]:** N eşzamanlı trade'de 1/N volatilite-normalize sizing. Bu hipotezin sizing'i sabit-fraksiyon; allocation hipotezi DEĞİL — başka hipotez konusudur. Burada referans, multi-symbol concurrent kapasitenin abartılmaması için.
- **[Grimes book_summary, #4]:** Over-leverage ve transaction-cost ihmali backtest illüzyonunun #1 kaynağı → 55 bps konservatif round-trip, leverage tavanı 3× (`risk.yaml` zaten kilitli).
- **[Volman book_summary, #2]:** Banda baskı yapan exhausted moves — destekleyici PA çerçevesi, ancak Volman 5m anlatır; 1D'ye taşıma özgün iddia.
- **[Kaufman book_summary, #6]:** "RSI can stay overbought longer than you can stay solvent" — saf overextension'ın yetmediği konusunda uyarı; rejim filtresinin gerekçesi de bu zaten.

## 4. Dependent Variables (önceden taahhüt, kilitli)

| Metrik | Tanım | Hesap noktası |
|---|---|---|
| `mean_R_gross_in` | Half-life-IN zone trade'lerinde mean R, fee/slip hariç | Trade close |
| `mean_R_gross_out` | Half-life-OUT zone trade'lerinde mean R, fee/slip hariç | Trade close |
| `welch_p_in_vs_out` | One-sided Welch t-test p-value (in > out) | Yıllık dilim toplama |
| `mean_R_net_filtered` | Filtreli stratejide mean R, 55 bps dahil | Trade close |
| `annual_return_net_filtered` | Compounded annual net return, filtreli | Equity curve sonu |
| `annual_return_net_unfiltered` | Compounded annual net return, filtresiz baseline | Equity curve sonu |
| `sharpe_filtered` | Sharpe (252 bar annualized), filtreli | Equity curve |
| `sharpe_unfiltered` | Sharpe (252 bar annualized), filtresiz | Equity curve |
| `maxdd_filtered` | Account-equity bazlı max DD, filtreli | Equity curve |
| `maxdd_unfiltered` | Account-equity bazlı max DD, filtresiz | Equity curve |
| `n_trades_filtered` | Filtreli toplam trade | Backtest sonu |
| `n_trades_unfiltered` | Filtresiz toplam trade | Backtest sonu |
| `p_shuffle` | 50 seed direction-shuffle null p-value (filtreli) | Bootstrap |
| `dsr` | Deflated Sharpe Ratio (López, trial=1 baseline + sens=24) | Walk-forward sonrası |
| `is_oos_sharpe_ratio` | IS Sharpe / OOS Sharpe (12-fold walk-forward) | Walk-forward |
| `regime_attribution_pct` | Filtreli ve filtresiz pozitif aylık dilim sayısı | Aylık dilim |

## 5. Independent Variables (parametre uzayı — DONDURULDU)

**KİLİTLİ baseline (curve-fit önleme):**
| Param | Değer | Gerekçe |
|---|---|---|
| `halflife_window_days` | **90** | Chan'ın metinde tekrar ettiği rolling pencere |
| `halflife_low_days` | **5** | Chan "1 günden az noise" iddiasının üst güvenli payı |
| `halflife_high_days` | **25** | Chan "30 günden fazla kapital cost yüksek" alt güvenli payı (interior, kenardan kaçınıyoruz) |
| `bb_window` | **20** | Standart |
| `bb_sigma` | **2.0** | Standart |
| `sl_atr_mult` | **1.5** | ATR bandın dışı |
| `tp_mode` | **`min(MA20_return, 2R)`** | Mean-reversion native + R-cap |
| `risk_pct` | **0.005** | risk_phoenix_scalp varsayılanı |
| `fee_round_trip_bps` | **55** | Konservatif (taker+slip) |
| `universe` | **top-30 USDT-perp by 90d ADV** | Delisting-aware (lessons/lesson_survivorship_bias.md) |
| `entry_timing` | **next bar open** | Lookahead-clean (decision t close, entry t+1 open) |

**Sensitivity (RED kararından SONRA, robustness için):**
| Param | Range | Adım | Cardinality |
|---|---|---|---|
| `halflife_low_days` | {3, 5, 7} | — | 3 |
| `halflife_high_days` | {20, 25, 30} | — | 3 |
| `bb_sigma` | {1.5, 2.0, 2.5} | 0.5 | 3 |
| `halflife_window_days` | {60, 90, 120} | — | 3 |
| `sl_atr_mult` | {1.0, 1.5, 2.0} | 0.5 | 3 |
| `tp_mode` | {`MA20`, `2R`, `min(MA20,2R)`, `1.5R`} | — | 4 |
| `risk_pct` | {0.003, 0.005, 0.008} | — | 3 |

**Toplam sensitivity grid:** 3×3×3×3×3×4×3 = **972 kombinasyon**.
**Bonferroni eşiği:** α = 0.05 / 972 ≈ **5.14e-5** → tek başına anlamlılık zor.
**Resmi kullanılacak:** **Benjamini-Hochberg FDR, q = 0.05** (sensitivity'de).
**Baseline trial = 1** olduğu için ana karar (Sharpe/MaxDD/return karşılaştırması) Bonferroni gerektirmez; ancak DSR raporlanırken trial = 972 verilir (López disiplini — gerçek trial-equivalent uzayını saklamak yasak).

## 6. Curve-fit Şüpheleri (zorunlu öz-eleştiri)

A priori şüpheler:
1. **Half-life zone sınırları seçimi.** [5, 25] aralığı Chan'ın metinde verdiği geniş [1, 60] aralığının iç-kesimi. "Kenarları kestik" suçlamasına karşı, sensitivity 3×3 zone sweep zorunlu — Bonferroni'siz iyileşme anlamsız.
2. **AR(1) half-life tahmini gürültülü.** 90 gün ~ 64-90 trading bar (1D); küçük örneklem. Half-life'ın 95% CI'si rapor edilecek; CI > tahminin 50%'sinden büyükse filtre güvenilmez sayılır.
3. **Survivorship-clean evren zorunlu.** "Top-30 today" değil "top-30 at the time" — delisting'ler dahil.
4. **Multiple regime simultane.** Half-life zaman içinde değişir. Filtre 1D bar-by-bar uygulanır — sembol bir gün IN, ertesi gün OUT olabilir. Trade orijinleme anındaki τ'ya bağlı sabitlenir, trade ortasında τ kayarsa exit edilmez (lookahead'i önlemek için).
5. **TP'nin "MA20'ye dönüş" tanımı.** "Dönüş" = entry sonrası ilk MA20 cross — close bazlı, intra-bar değil (lookahead şüphesini kesmek için).
6. **Filtre sadece N azaltıyor olabilir.** Şart §1: filtered N ≥ 200 + Sharpe ≥ 1.2× unfiltered. Sample küçültüp Sharpe yükseltmek "free lunch değil" — return koruma şartı bu sebeple var.

## 7. Beklenen p-value & Sample Size

- **Ana karşılaştırma (in-zone vs out-of-zone gross R):** raw p ön-taahhüdü **< 0.01** (Welch one-sided).
- **Shuffle baseline:** raw p < 0.01.
- **Sensitivity BH-FDR (q=0.05) sonrası:** baseline'ın hâlâ q-adjusted < 0.05 olması ZORUNLU.
- **Sample size hedefi:** N_filtered ≥ 200 trade (Sharpe SE için kabaca ~%14 — bu hipotezin %20 Sharpe geliştirme iddiasına yeter).

## 8. Stop Criteria (hipotezi terk koşulları)

| Koşul | Aksiyon |
|---|---|
| IS Sharpe (filtreli) < 0.5 | Hipotez terkedilir, learning.md'ye ekleme |
| Filtered MaxDD > 0.7 × Unfiltered MaxDD | RED |
| Filtered annual return < 0.85 × Unfiltered annual return | RED (filtre return'ü yiyor) |
| `welch_p_in_vs_out` ≥ 0.05 | RED (rejim filtresi anlamsız) |
| `is_oos_sharpe_ratio` > 1.5 ya da OOS Sharpe < 0.5 | Overfit → RED |
| `dsr` < 0.5 | López disiplini → RED |
| Walk-forward 12 dilimden 5'inden azı pozitif | İstikrarsız → RED |

## 9. Robustness Suite (SOP-3 — yürütme öncesi commit edildi)

Zorunlu testler (yürütme sırasında değiştirilemez):
1. **Walk-forward** 3y train + 6m test, step 3m, 12 dilim.
2. **IS/OOS Sharpe farkı** < %30.
3. **Random parameter perturbation** ±%10, 50 seed (her sensitivity ekseninde).
4. **Symbol-out CV** — her sembolü tek tek çıkar, ortalama OOS değişmemeli.
5. **Regime split** — bull (2021, 2024H1), bear (2022, 2024H2-2025H1), range (2023) → en az 2'de pozitif.
6. **Stress periyotları** — 2022-05 (LUNA), 2022-11 (FTX), 2024-03 (ATH), 2024-08 (Yen carry). Her birinde yıkıcı kayıp yok (-%10 max equity hit).
7. **Shuffle baseline** — sembol-bazlı 50 seed direction shuffle, p < 0.05.
8. **DSR** — trial = 972 ile López deflation.
9. **Lookahead test** — `detector(df.iloc[:t+1])[t] == detector(df)[t]` her t için.

## 10. Reproducibility

- `git_hash`: backtest çalıştırılınca doldurulur
- `config_hash`: bu dosyanın SHA256'sı backtest config'ine yapışıyor
- `data_hash`: `data/duckdb_snapshot.sha256` build-time
- Bu dosya kod yazılmadan **commit edilir**; sonradan değişirse `supersedes` ile yeni doc.

## 11. Karar Çerçevesi (yürütmenin nihai çıktısı)

```
SONUÇ TABLOSU
| Metric                   | Filtered | Unfiltered | Hedef           | Pass |
| net annual return        | ?        | ?          | F ≥ 0.85×U      | ?    |
| Sharpe                   | ?        | ?          | F ≥ 1.2×U       | ?    |
| MaxDD                    | ?        | ?          | F ≤ 0.7×U       | ?    |
| N trades                 | ?        | ?          | F ≥ 200         | ?    |
| Welch p (in > out)       | ?        | —          | < 0.05          | ?    |
| Shuffle p                | ?        | ?          | < 0.05          | ?    |
| DSR                      | ?        | ?          | > 0.6           | ?    |
| IS/OOS ratio             | ?        | ?          | < 1.5           | ?    |
| Walk-forward + dilim     | ?/12     | ?/12       | F ≥ 6/12        | ?    |
| Stress periyot hayatta   | ?/4      | ?/4        | F = 4/4         | ?    |

KARAR:
  □ Terfi adayı (TÜM gate ✓) → Lab tournament
  □ İterate (positive edge, DD yüksek) → SOP-4b v2 hipotezi aç
  □ RED — gerekçe: ...
```

## 12. Lab/Risk/Adversary Review Notları

`requested_review_from`:
- **lab_scientist** — tournament gates uyumluluğu (DSR p < 0.05, effect ≥ 15%, MaxDD ≤ champion+5%) ön onayı.
- **risk_officer** — `risk_pct=0.005`, 3× leverage tavanı, concurrent kapasite (top-30 evrende olası 30 paralel pozisyon → portföy notional/equity ≤ 4 şart) sağlaması.
- **adversary_engineer** — climax-fade'in 2022-05 LUNA dilim hayatta-kalma probu + flash-crash sentetik scenario. Bu hipotezin "Banda-fade in-zone'da iyi olur" iddiasının tersi: aşırı düşüşler tam half-life-IN sembollerde olmalı (BTC/ETH gibi yüksek likidite, ortalama-dönüş eğiliminde). LUNA τ büyüktür → IN değildir → filtre çoktan eler; yine de adversary test eder.
