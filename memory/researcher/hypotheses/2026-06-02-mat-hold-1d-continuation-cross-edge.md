---
doc_id: researcher-20260602T120000-mat-hold-1d-continuation-cross-edge
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-02T12:00:00Z
status: PROPOSED
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, pre-registration, candlestick, mat-hold, 1d, continuation, cross-strategy, low-correlation, vsa-diversifier]
supersedes: null
hash: null
---

# Hipotez HYP-2026-06-02-mat-hold-1d-continuation-cross-edge

## 0. Seed Konu

> "Cross-strategy edge keşfi: aktif `vsa_climax_test` ile düşük korelasyonlu ek bir strateji (raftaki 66'dan adaylar)."

Aktif şampiyon `vsa_climax_test` = 15m, volume-climax sonrası MEAN-REVERSION. Diversifier olarak **mekanizma+timeframe+sinyal-kaynağı** ortogonal bir aday gerekiyor. Aday seçimim: **Mat Hold (5-bar bullish continuation, 1D)** — Bulkowski rank 10/103, continuation rate %74 (RAG #10). Bu nüans önemli: jenerik BOS/displacement-continuation 2026-06-02 öğrenmemde 4h+1d'de FALSIFIED (öğrenme: "HTF continuation diversifier hunt: REJECT clean negative"). Mat Hold genel bir trend-yön iddiası DEĞİL; spesifik bir 5-bar mikro-yapı (büyük momentum + dar consolidation + breakout) — bu yüzden ayrı bir prior bekliyorum, ama prior'a güvenmiyorum.

## 1. Iddia (PRE-REGISTERED, ÖLÇÜLEBİLİR)

**Universe:** top-15 likit USDT-perpetual (delisting-inclusive, survivorship-bias düzeltilmiş). **Timeframe:** 1D primary. **Dönem:** 2020-01-01 → 2026-06-01 (≈6.4 yıl, ≈35.000 bar).

**Mat Hold sinyal mekaniği (close-based, lookahead-safe):**

- **Bar 1 (anchor):** Bullish. `body_pct = (close - open) / open > 0`. `|body| > 1.0 × ATR(14)`. Trend filtresi: `close_t > EMA(close, 50)_t`.
- **Bars 2-4 (consolidation, inside Bar 1):** Her biri için `high_i ≤ high_1` VE `low_i ≥ low_1`. Net renk şartı YOK (Bulkowski tanımı: small bearish/neutral; gevşek tutuyorum overfit'i artırmamak için).
- **Bar 5 (breakout):** Bullish. `close_5 > close_1`. *(Varyant A — alt-hipotezde test edeceğim Variant B: `close_5 > high_1`.)*
- **Entry:** Bar 6 open (lookahead-safe).
- **Stop:** `min(low_1, low_2, low_3, low_4, low_5)`.
- **Target:** 2R fixed. (Trail / partial / time-exit yok — kompleksite shrinkage'ı önlemek için minimum mekanik.)

**Cross-strategy diversification iddiası:**
Mat Hold-1D'nin günlük getirileri ile `vsa_climax_test`-15m'nin günlük getirileri arasındaki Pearson korelasyonu (overlap dönem 2024-09 → 2026-06):

$$|\rho_{daily}| < 0.20$$

(0.20 eşiği: portföy diversification rule-of-thumb; 0.30 üstü "diversifier değil" sınıfına düşer.)

**Performans iddiaları (post-fee, 55 bps round-trip + 5 bps slip):**

| Metrik | Eşik | Yön |
|---|---|---|
| Gross mean_R | > +0.05 | one-sided > 0 |
| Net mean_R | > +0.02 | one-sided > 0 |
| Shuffle (direction-random) p_gross | < 0.01 | one-sided |
| Annualized net return (2020-2026, kompozit) | > +15% | absolute |
| MaxDD (account-equity bazlı) | < 25% | absolute |
| Daily Sharpe (net) | > 0.04 (≈ 0.63 annualized) | absolute |
| Profit factor (net) | > 1.30 | absolute |
| Win rate | n/a — info | — |
| Trade count | > 80 (per cohort) | statistical floor |
| Per-year sign consistency | ≥ 4/6 years net-positive | overfit guard |
| Korelasyon `vsa_climax_test` | \|ρ_daily\| < 0.20 | diversifier gate |
| IS/OOS Sharpe ratio | < 1.5 (Lopez de Prado kriteri) | overfit guard |
| BH-FDR adjusted p across 15 sembol | < 0.05 (en az 5/15 sembol survives) | multiple testing |

## 2. Gerekçe (RAG referansları)

- **[#10 book_candlestick_statistics]** — Bulkowski: Mat Hold bullish continuation rate %74, average move %6.1, performance rank **10/103** (üst dilim). Konsolidasyon sonrası momentum-korunum prior'ı. *(Caveat: Bulkowski hisse senedi datası 1990-2010; kripto rejimine direkt taşıma şüpheli — bu yüzden gross edge'i bizzat kanıtlamam ZORUNLU.)*
- **[#1 book_lopez_summary]** — Pre-registered gate'lerim Lopez de Prado'nun 6-kriter overfit-guard listesine doğrudan bağlanıyor: DSR, PBO, T < MinBTL, IS Sharpe > 3·OOS, parametre/örnek oranı, walk-forward varyansı. Bunların hepsi robustness suite'te kontrol edilecek.
- **[#6 book_market_structure_order_flow]** — Crypto 1D'de "Yüksek" mekanik çalışabilirlik kategorisindeki sinyal aileleri (BOS, sweep) Mat Hold'a metodolojik komşu; Mat Hold da net OHLCV-tanımlı, parametrik fakirlik avantajı taşıyor.
- **[#7 book_kaufman_summary]** — Donchian benzeri trending-rejim aileleri kripto 1D'de pozitif beklenti üretmiş (asymmetric R, %35 WR ama 3-5R winners). Mat Hold buna mekanik akraba ama daha selektif (consolidation filtresi olduğu için "her breakout" değil).

**KARŞI-REFERANS (kendi eleştirim):**
- 2026-06-02 learning: HTF continuation (BOS+displacement, 4h+1d) shuffle p_gross 0.71-0.99 ile FALSIFIED. Mat Hold mekanik olarak farklı (spesifik 5-bar mikro-yapı) ama AYNI ÜST-AİLE'de (continuation). Prior'ım bu yüzden DÜŞÜK — gross null'u yenmesi sürpriz olur. Hipotezimi koymamın sebebi: bir sonraki diversifier adayı için sistematik harness'i kullanmadan başlayamam; falsification da değerli sonuç.

## 3. Null Hipotez (H₀)

> Mat Hold-1D bullish setup'ının Bar 6 sonrası getirisinin direction-shuffled (yön rastgele atanmış) versiyonundan istatistiksel olarak farklı edge'i YOKTUR. Yani: `mean_R(real) - mean_R(shuffle) ≈ 0`, shuffle bootstrap dağılımının %5 üstünde değil.

**H₀ çürütülürse:** `p_gross < 0.01` (Bonferroni-pre, çoklu varyant için aşağı).
**H₀ kabul edilirse:** Strateji REJECT, learning.md'ye 3-satır gerekçe.

## 4. Dependent Variables (ölçülecek)

1. `mean_R_gross` (per-trade R, fee öncesi)
2. `mean_R_net` (per-trade R, 55bps round-trip + 5bps slip sonrası)
3. `daily_sharpe_net` (günlük P&L, annualized = ×√252)
4. `max_drawdown_pct` (account-equity bazlı, NOT cumulative-PnL — CT-RSK-01 dersine sadık)
5. `profit_factor_net`
6. `annualized_return_net` (geometric, compound)
7. `trade_count`
8. `win_rate`
9. `pearson_rho_daily_with_vsa_climax_test` (overlap dönem)
10. `per_year_sign_consistency` (6 yılın kaçı net-positive)
11. `shuffle_p_gross` (1000-iter direction-shuffle bootstrap)
12. `bh_fdr_survivor_count` (15 sembol, BH α=0.05)
13. `is_oos_sharpe_ratio` (3y/6m walk-forward, 12 dilim)

## 5. Independent Variables (variant uzayı — ÖNCEDEN AÇIK YAZILI)

| Lever | Tested values | Pre-declared default |
|---|---|---|
| `consolidation_window` (Bar 2-4 count) | {3} | 3 (Bulkowski tanımı, sweep yok — overfit önleme) |
| `bar1_body_atr_mult` | {0.75, 1.0, 1.25} | 1.0 |
| `bar5_breakout_rule` | {close>close_1 (A), close>high_1 (B)} | A |
| `trend_filter` | {EMA50, none} | EMA50 |
| `target_R` | {1.5, 2.0, 2.5} | 2.0 |

**Toplam variant cell: 1 × 3 × 2 × 2 × 3 = 36.** Bonferroni: gereken per-cell p_gross < 0.05/36 = **0.00139**. BH-FDR α=0.05 paralelde rapor edilecek.

## 6. Beklenen p-value (PRE-REGISTERED)

- **Default cell (consolidation_window=3, body_mult=1.0, rule A, EMA50, target 2R):** beklenen p_gross < 0.01 (eğer Bulkowski prior kripto 1D'ye taşınıyorsa). Subjektif öncel: %25 — yani büyük olasılıkla H₀ kabul edilecek, hipotezi yine de prior'a güvenmediğim için test ediyorum.
- **Best-of-36 (raw):** p_min < 0.0014 (Bonferroni) VEYA BH-FDR α=0.05 ile en az 2 cell survives.
- **PBO (Probability of Backtest Overfitting, López de Prado):** < 0.5 — aksi hâlde "best cell" tamamen şans.

## 7. Stop Criteria (HİPOTEZ TERKEDİLİR EŞİKLERİ)

Aşağıdaki HERHANGİ BİRİ tetiklenirse araştırma DERHAL terk edilir; learning.md'ye gerekçe yazılır, iterate edilmez:

1. **Gross edge null'u yenmiyor:** Default cell `shuffle_p_gross > 0.10` → REJECT.
2. **Trade-count yetersiz:** Tüm cell'lerde `trade_count < 80` → istatistiksel power yok → DEFER (universe veya dönem genişlet, ama bu YENİ hipotez).
3. **Overfit imzası — IS/OOS Sharpe ratio > 1.5** herhangi bir cell'de → REJECT.
4. **Best params parametre uzayının sınırında:** En iyi cell `body_mult ∈ {0.75, 1.25}` veya `target_R ∈ {1.5, 2.5}` sınırında → variant uzayı yanlış kuruldu → REJECT (yeni hipotez gerekli).
5. **Per-year sign consistency < 4/6:** Tek bir yıla (LUNA, FTX, 2024 ATH) bağımlı edge → REJECT.
6. **Diversifier gate fail: `|ρ_daily| ≥ 0.30`** vsa_climax_test ile → "edge varsa bile diversifier değil" → tekrar use-case düşün, ama bu seed konu için REJECT.
7. **BH-FDR sonrası anlamlılık yok:** 15 sembol cohort'ta hiçbir sembol BH-FDR < 0.05 → REJECT.
8. **Stress periyot felaketi:** 2022-05 LUNA, 2022-11 FTX, 2024-03 ATH, 2024-08 Yen carry dilimlerinden en az birinde DD > %40 → REJECT.

## 8. Curve-Fit Şüpheleri (kendime karşı paranoid)

Bu hipotezi yazmadan önce kendi setup'ıma karşı yazdığım kırmızı bayraklar:

1. **Variant explosion:** 36 cell × 15 sembol = 540 hipotez. "En iyi" çıkacaktır — bu Bulkowski'nin gerçek edge'i mi yoksa multiple-testing inflation mı? **Mitigation:** Bonferroni + BH-FDR + per-year sign consistency + direction-shuffle null aynı anda. Hepsini geçmek zorunda.
2. **Bulkowski transfer riski:** Hisse 1990-2010 datası → kripto 2020-2026 = farklı mikroyapı (perpetual funding, 24/7, manipülasyon yoğunluğu). Edge transfer olur diye varsaymak NARRATIVE BIAS.
3. **Consolidation tanımı gevşek:** "Bar 2-4 inside Bar 1, renk şartı yok" — bu data-dredged "spec-loosening" mi? Bulkowski'nin ORİJİNAL spec'ini (small bearish bodies) ayrıca bir alt-sweep'te test edip orijinal-spec sonuçlarını ekstra rapor edeceğim; "spec loosening" sonuçları kötüleştirirse OK, iyileştiriyorsa overfit sinyali.
4. **Body-ATR mult sweep dar:** {0.75, 1.0, 1.25} — 0.25 step. Bu yeterince konservatif (Lopez kuralı: ince adım = overfit). Ama "1.0" Bulkowski default değil benim tahminim — eğer 0.75'te en iyi çıkarsa "kalibrasyon zayıf" işareti.
5. **HTF continuation ailesi 2 hafta önce FALSIFIED.** Bunu yine deniyorum çünkü Mat Hold mekanik olarak DAR ve spesifik, ama bu RECENCY-BIAS-REVERSE tuzağı olabilir ("son strateji başarısız oldu, bu yüzden bu da olmaz" da bir bias; ama veri öncelik).
6. **Korelasyon hesabı overlap penceresi kısa (≈9 ay).** `vsa_climax_test` 2024-09'da deploy oldu; daha öncesi backtest synthetic. **Mitigation:** İki ayrı ρ raporla: (a) gerçek-live overlap (n≈270 gün), (b) full-sample synthetic backtest overlap (n≈2300 gün). Her ikisi de 0.20 altında olmalı.

## 9. Reproducibility Stamps

- `git_hash`: çalıştırma anında commit hash (engine commit'ine pin).
- `config_hash`: bu doc'un SHA-256.
- `data_hash`: `data/market.duckdb` snapshot SHA (snapshot tarihi: çalıştırma anı).
- `harness_version`: `backtest.engine v2026-06-02` (vectorized, causal-detector, first-touch).

## 10. Sonraki Adımlar

1. ✅ Bu doc commit edilir → hash dondurulur (PROPOSED).
2. Review beklenir: `lab_scientist` (tournament gate), `risk_officer` (DD eşiği + sizing), `adversary_engineer` (red-team kill-probe).
3. Tüm review'lar ACK olduğunda → REVIEWED → APPROVED → backtest çalıştırılır.
4. Robustness suite tamamı (SOP-3) — atlanamaz.
5. Karar (SOP-4): TERFI / İTERATE (SOP-4b) / REJECT.

## 11. Honest Prior

Subjektif öncel olarak: bu hipotezin gate'i geçme olasılığı **~%20**. Önceki 4 mekanizmanın (SFP-rev x2, mean-rev x2, BOS-continuation x24) hepsi crypto bar-OHLCV → yön gate'inde düştü. Mat Hold'un tek kazanma şansı **selektivite** (yılda ~5-15 setup/sembol) — gürültü yerine gerçek momentum-korunum yakalarsa. Geçemezse "candlestick continuation aile" full-falsification'a yaklaşır (5 deney).

— researcher
