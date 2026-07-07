---
doc_id: researcher-20260623T220000-golden-death-cross-50-200-ema-cross-strategy-companion-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-23T22:00:00Z
status: DRAFT
confidence: low
depends_on:
  - researcher-20260623T180300-order-block-mitigation-cross-strategy-companion-vsa
  - researcher-20260623T140300-eqh-eql-liquidity-sweep-reversal-cross-strategy-vsa-companion
  - researcher-20260623T100300-donchian20-vsa-companion
  - researcher-20260623T060800-bearish-marubozu-continuation-d1-cross-edge-vsa
  - researcher-20260623T020400-chan-halflife-rank-bollinger-fade-basket-1d
blocks: []
requested_review_from:
  - lab_scientist
  - risk_officer
tags:
  - cross_strategy_companion
  - vsa_climax_diversifier
  - kaufman_ma_crossover
  - golden_cross
  - death_cross
  - trend_following
  - long_horizon
  - low_corr_target
  - pre_registration
  - curve_fit_watch
  - lopez_prado_familywise_inflation_acknowledged
  - daily_cadence_6th_hypothesis
  - multiple_testing_alpha_inflated
supersedes: null
hash: null
hypothesis_id: 2026-06-23-golden-death-cross-50-200-ema-cross-strategy-companion-vsa
version: 0.1
---

# Hipotez: Golden / Death Cross (50/200 EMA) — vsa_climax_test düşük-korelasyonlu refakatçi

## 0. Curve-Fit & Multiple-Testing Açıklama (peşin uyarı)

Bu hipotez bugünkü (2026-06-23) auto-cadence içinde **6. companion seed**'dir. Aynı bağımlı evren (vsa_climax_test ile düşük-korelasyon arayışı) üzerinde 3 günlük pencerede **12+ ön-kayıtlı hipotez** var. Family-wise α inflation açıkça mevcut. Aşağıdaki sertleştirmeler uygulanmıştır:

- Pre-registered α (raw): 0.01
- **Family-wise düzeltilmiş α (Holm, N=121, 121 = bugüne kadarki cross-family pre-registration N + 1):** α_holm ≈ 4.20e-4 — kabul için **OOS p < 4.20e-4** zorunlu.
- Bonferroni-eşdeğer (N=121): α_bonf ≈ 4.13e-4.
- López-Prado free-params/N tabanı: aşağıdaki bölüm 7.

Curve-fit kırmızı bayrak threshold'ları **şimdi sabitlendi**, optimizasyon sonrası gevşetilemez.

---

## 1. Iddia (pre-registered, ölçülebilir)

> 1D timeframe'de, USDT-perpetual evreninde (3 yıl, survivorship-dahil, ~50 sembol), aşağıdaki mekanik kurallarla tanımlanan **50/200 EMA crossover (Golden Cross long, Death Cross short)** sinyali — crossover bar'ının kapanışında karar, **t+1** bar açılışında market emir, ATR-trailing exit ile — son 3 yılda aşağıdaki metrikleri birlikte sağlar:
>
> - **Net annualized return ≥ %18** (fees 7.5bps taker + 5bps slip dahil)
> - **OOS Sharpe ≥ 0.70** (walk-forward, 3y/6m, 12 dilim; sembol başına bağımsız)
> - **OOS Sharpe stability:** 12 dilimin **en az 8'inde** pozitif Sharpe (whipsaw rejim toleransı)
> - **MaxDD ≤ %22** (account equity bazında, López-Prado convention — kümülatif PnL DEĞİL)
> - **Profit factor ≥ 1.25** (asimetrik R-multiple ile düşük WR doğal)
> - **Expected Win Rate band:** %30-45 (Kaufman: trend-following karakteristik); %50+ raporlanırsa lookahead şüphesi → otomatik red
> - **N_trades ≥ 80** (universe genelinde 3y; long-horizon doğası gereği düşük frekans, düşük-N reddi için sert eşik)
> - **Spearman korelasyonu (gün-bazlı equity-curve returns, vsa_climax_test ile) |ρ| ≤ 0.20** — bu **BİRİNCİL gate**; düşük korelasyon yoksa edge yeterli olsa bile companion olarak deploy ETMEM.
> - **Rolling 90-day Spearman max(|ρ|) ≤ 0.35** — global korelasyon düşük olsa bile lokal yüksek-korelasyon yasak.

Notlar:
- Korelasyon hedefi yapısal beklenti: VSA climax = high-volume exhaustion mean-reversion (intraday-to-swing); Golden/Death Cross = long-horizon trend-following (haftalar-aylar). Mekaniğin **zaman ölçeği** ve **yön mantığı** ortogonal. Ama "mantıklı geliyor" hipotezi geçirmez — sayı kazanır.
- Kaufman'ın notu: "Sideways market'te 4-6 ardışık whipsaw, kümülatif drawdown sorunu." Bu özellik MaxDD ≤ %22 gate'inde test edilir; whipsaw rejim filtresi (ADX) sonradan eklenirse o ayrı bir hipotez olur (bu hipotezin gate'ini değiştirme yasak).

---

## 2. Mekanik Tanım (curve-fit'e karşı sabitlenmiş, daha-sonra-değişmez)

**Indicator'lar:**
- `EMA_fast = EMA(close, 50)`
- `EMA_slow = EMA(close, 200)`
- `ATR_20 = ATR(20)` (Wilder)

**Sinyal:**
- **Golden Cross (Long entry trigger):** bar `t`'de `EMA_fast[t] > EMA_slow[t]` AND `EMA_fast[t-1] ≤ EMA_slow[t-1]`. Karar `t` close'da; giriş `t+1` open'da market.
- **Death Cross (Short entry trigger):** bar `t`'de `EMA_fast[t] < EMA_slow[t]` AND `EMA_fast[t-1] ≥ EMA_slow[t-1]`. Karar `t` close'da; giriş `t+1` open'da market.

**Initial Stop:**
- Long: entry − `2.0 × ATR_20[t]`
- Short: entry + `2.0 × ATR_20[t]`

**Exit (kombine, ilki tetikler):**
1. **Opposite crossover** → pozisyon close.
2. **ATR trailing stop:** Wilder Chandelier stil — long için `max(high[entry:t]) − 3.0 × ATR_20[t]`; short için simetrik.
3. **Hard time stop:** 60 bar (≈ 2 ay) sonra hâlâ açıksa close (alpha-decay disiplin).

**Position sizing:** Risk = %1 / trade üzerinden ATR-based; max leverage 3x (configs/risk.yaml ile uyumlu); single-symbol cap %20.

**Filters (sabitlenmiş — ekleme/çıkarma yasak):**
- Liquidity: günlük notional volume > 5M USDT (rolling 30d median).
- Funding rate: |funding| < 0.05% / 8h (extreme-funding krizi exit-only).
- Listing seasoning: ≥ 250 bar history (200 EMA stable olsun).
- **YOK:** sentiment, news, on-chain, social — bu hipotez sadece PA.

---

## 3. Gerekçe (RAG referansları + literatür)

1. **[Kaufman summary ch.MA-crossover, #4]** — "Golden/Death cross long-horizon trend captures; daily/weekly ideal; intraday gürültü baskın. Edge: düşük frekans, düşük commission, major trend yakalar. Failure: sideways whipsaw."
   - Bizim 1D crypto evrenimizde tam Kaufman'ın belirttiği rejim — günlük bar, multi-week trend yapısı.
2. **[Kaufman summary ch.7 Donchian, #7]** — analog asimetrik R-multiple yapısı: "%35 WR ile pozitif beklenti, çünkü winners 3-5R, losers 1R." Aynı asimetri MA-crossover'da bekleniyor.
3. **[López-Prado #1]** — Free-param/N kuralı: bu hipotezde free-params sayısı **6** (50/200 fast/slow periods, 2.0 ATR initial SL mult, 3.0 ATR trail mult, 60 bar time-stop, 5M USDT liquidity floor). Sample size: 3y × 50 sembol × 1D ≈ 54,750 bar. Free-params/N = 6/54750 ≈ **1.1e-4 ≪ 1/30**. **López-Prado floor PASS**. (Sample = sinyal sayısı değil, bar sayısı; sinyal-bazlı: N ≈ 80 trade minimum → 6/80 = 0.075 < 1/30=0.033 → **FAIL sinyal-bazlı**. Çift floor ihlali → trade-level overfitting riski yüksek; aşağıda Bölüm 7'de ele alınıyor.)
4. **[Bulkowski candlestick stats — kıyas]** — bireysel mum kalıpları %54-74 continuation; MA-crossover sıkı bir kalıp değil, **portfolio-of-trades** doğası gereği WR daha düşük (%30-45) bekleniyor. Bulkowski tek-bar stats ile karşılaştırma yanıltıcı.
5. **vsa_climax_test ile yapısal ortogonalite:** VSA = climactic exhaustion (high-vol bar, mean-revert); MA-crossover = trend-confirm (multi-bar momentum). Aynı bar üzerinde her ikisi de tetiklenirse karşıt yön → korelasyon negatife yakın bekleniyor. Ama: trending bull rejim her ikisini de long-bias yapabilir → Spearman ölçüm zorunlu, "ortogonal görünüyor" gerekçesi YETERSİZ.

**RAG corpus gap kabulü:** Cross-asset companion-pair selection metodolojisi (Engle-Granger / cointegration / marginal-Sharpe-given-portfolio / half-life pair-gating) corpus'ta hâlâ ABSENT (v71 abort dossier'inde dokümante). Bu hipotez companion seçim metodolojisinin **kanıt-üretme** adımı; pair-gating teorik framework hâlâ açık.

---

## 4. Independent Variables (donduruldu — optimizasyon kapsamında değil)

- **Fast EMA period:** 50 (Kaufman canonical; deneme aralığı YOK — sweep yapma)
- **Slow EMA period:** 200 (Kaufman canonical)
- **ATR period:** 20
- **Initial SL mult:** 2.0
- **Trail SL mult:** 3.0
- **Time stop:** 60 bar
- **Liquidity floor:** 5M USDT
- **Funding extreme:** 0.05%

**Sweep yapılacak parametreler:** YOK. Bu pre-registration "canonical Kaufman setup" testidir. Parametre optimizasyonu (örn. 20/100, 30/150 varyantı) ayrı hipotez olarak yazılır, family-wise N artırır.

**Optuna yasak:** bu hipotezde Optuna kullanılmaz. Tek nokta kanonik konfigürasyon → Bonferroni N=1 (kendi içinde), ama family-wise inflate edilmiş α (bkz Bölüm 0) yine de geçerli.

---

## 5. Dependent Variables (raporlanacak — sabit liste)

Birincil:
1. Net annualized return (fee+slip dahil) [%]
2. OOS Sharpe (12-dilim ortalaması) [scalar]
3. OOS Sharpe pozitif-dilim sayısı [/12]
4. MaxDD (equity-based, López-Prado) [%]
5. Profit factor
6. N_trades (universe 3y total)
7. Win rate [%]
8. Spearman ρ (gün-bazlı returns, vsa_climax_test ile) — **birincil gate**
9. Rolling 90-day max |Spearman ρ|

İkincil (red sebebi değil, raporlama için):
- Sembol-bazlı Sharpe dağılımı (symbol-out CV için)
- Rejim-bazlı PnL (bull/bear/range — HMM veya BTC trend filter ile)
- Average winner / average loser R-multiple
- Time-in-trade dağılımı (60-bar tavanın ne sıklıkla bind olduğu)
- Whipsaw cluster sayısı (Kaufman'ın 4-6 ardışık whipsaw uyarısı için)

---

## 6. Beklenen p-value & Stop Criteria

**Beklenen OOS Sharpe p-value (shuffle baseline'a karşı):**
- Hipotez geçerli ise: p < 4.20e-4 (Holm-düzeltilmiş α_family)
- Raw p < 0.01 ama düzeltilmiş p > 4.20e-4 → **MARGINAL** etiketi, deploy YOK, Lab tournament'a önerilmez.

**Stop criteria (research terkedilir):**
- IS Sharpe < 0.5 → hemen terk (Kaufman'ın "düşük commission edge" iddiası geçersiz).
- N_trades < 50 → istatistik anlamsız, terk.
- Spearman |ρ| (vsa_climax_test ile) > 0.40 → companion amacı çürür, terk (edge varsa bile DEPLOY OLMAZ — başka bir hipotez olarak arşivle).
- 12-dilim WF'de pozitif dilim < 6 → instabilite, terk.
- IS Sharpe > 3 × OOS Sharpe → López-Prado overfitting bayrağı, terk.
- Best parameters parametre sınırında olması: **uygulanmaz** (bu hipotezde sweep yok).
- Backtest çalıştırma sırasında lookahead testi (`detector(df[:t+1])[t] == detector(df)[t]`) başarısız → CRİTİK fail, hipotez ölü, signal_chief escalate.

---

## 7. Curve-Fit & Overfit Şüphe Öz-Eleştirisi (proaktif)

Aşağıdaki kırmızı bayraklar **hipotez henüz çalıştırılmadan** açıkça bildirilir:

1. **Sinyal-bazlı López-Prado floor FAIL.** Free-params/N ≈ 0.075 > 1/30 = 0.033. Trade-level overfitting riski yapısal. Bar-level pass olsa da, kararın trade'ler üzerinde verildiği gerçeği bu floor'u öncelikli yapar.
   → **Karşı önlem:** parametreler **donduruldu** (Kaufman canonical), sweep yok. Bu floor ihlalini en aza indirir ama elimine etmez.

2. **Family-wise α inflate.** Bugün 6., 3 günde 12+ ön-kayıtlı companion hipotezi. Holm N=121.
   → **Karşı önlem:** raw α gevşek (0.01) ama gate sıkı (α_holm 4.20e-4).

3. **"Kanonik" iddiası kendi başına bir form of selection bias.** "50/200 EMA seçildi çünkü Kaufman/finans literatürü öyle diyor" → ama literatürde 50/200 **rapor edilmiş** olması publication bias'lı (başarısız varyantlar rapor edilmedi).
   → **Karşı önlem:** sonuç pozitif olursa, post-hoc duyarlılık testi (20/100, 30/150 varyantları sweep) — ama bu **ayrı bir hipotez** olarak yazılır, bu hipotezin gate'ini etkilemez.

4. **Crypto 1D'de 200-EMA 200-bar history gerektirir → genç sembolleri dışlar → tekrar survivorship-adjacent bias.** Listing seasoning ≥ 250 bar filter survivorship-koruma değildir; aksine kısıtlama getirir.
   → **Karşı önlem:** rapor universe-of-test'i (kaç sembol filtrelendi); 200-bar history koşulu sembol başına listing-aware uygulanır (delisted semboller dahil edilir, sadece listing tarihine kadar olan ilk 250 bar dışlanır).

5. **Rejim coupling riski.** 2023-2024 BTC bull trend'inde 50/200 crossover otomatik long-bias; aynı dönemde VSA climax SHORT-bias (overhead exhaustion). Korelasyon negatife yakın **trivial** çıkabilir — ama bu trend-rejim'e koşullu, bear/range rejimlerde tersine dönebilir.
   → **Karşı önlem:** **rolling 90-day max |ρ| ≤ 0.35** gate'i bu rejim-koşullu sızıntıyı yakalar.

6. **Whipsaw cluster underweight.** Kaufman'ın 4-6 ardışık whipsaw uyarısı, MaxDD üzerinde sert etkili. 3y backtest'te yeterince sideways rejim yoksa (2022 H2 sınırlı), Maximum-DD optimist tahmin olur.
   → **Karşı önlem:** stress periodları (LUNA 2022-05, FTX 2022-11, USDC depeg 2023-03, Yen carry 2024-08) ayrı raporlanır; whipsaw cluster sayısı dependent var olarak listelendi.

7. **Survivorship'in long-tail etkisi.** Delisted sembollerin çoğu small-cap → 200-bar EMA istikrarsız → MA-crossover bunlarda zaten gürültü. Filtrelenince edge calculation büyük-cap'lere ağırlık verir → live'da küçük-cap'lerde davranış belirsiz.
   → **Karşı önlem:** symbol-out CV: top-10 sembolü çıkar, edge ortalama ne kadar düşüyor — bu raporlanır.

---

## 8. Robustness Suite (SOP-3 zorunlu — değiştirilemez)

Aday için aşağıdakilerin **tamamı** çalıştırılır:

| # | Test | Gate |
|---|---|---|
| 1 | Walk-forward 3y/6m, 12 dilim | OOS Sharpe ≥ 0.70 ortalama, ≥ 8/12 pozitif |
| 2 | IS / OOS Sharpe farkı | ≤ %50 |
| 3 | Random parameter perturb ±%10, 50 seed | Sharpe kayıp ≤ %25 |
| 4 | Symbol-out CV (top-10 sembol tek tek dışarıda) | min OOS Sharpe ≥ 0.40 |
| 5 | Regime split (bull/bear/range) | En az 2 rejimde pozitif Sharpe |
| 6 | Stress periodları (LUNA / FTX / USDC depeg / Yen carry) | Hiçbirinde MaxDD > %15 |
| 7 | Shuffle baseline (returns shuffle, 1000 seed) | p < 0.05 raw, p < 4.20e-4 Holm |
| 8 | Multiple testing correction (Holm N=121) | α_holm'da survive |
| 9 | Lookahead test (`detector(df[:t+1])[t] == detector(df)[t]`) | %100 pass |
| 10 | **Spearman ρ vsa_climax_test, gün-bazlı** | **|ρ| ≤ 0.20 (birincil gate)** |
| 11 | Rolling 90d max |ρ| | ≤ 0.35 |
| 12 | López-Prado floor (sinyal-bazlı) | rapor (FAIL bilinen, mitigation: param freeze) |
| 13 | López-Prado floor (bar-bazlı) | rapor, PASS |

Tablodaki herhangi bir gate FAIL ise: **REJECTED, deploy YOK, arşivlenir**.

---

## 9. Beklenen Sonuç (öngörü — pre-registered tahmin)

**Best-case (subjective prior, %30 olasılık):**
- Net annual %22-30, OOS Sharpe 0.85-1.10, MaxDD %18-22, |ρ_vsa| 0.05-0.15 → companion adayı, Lab tournament'a önerilir.

**Modal-case (%50 olasılık):**
- Net annual %5-15, OOS Sharpe 0.30-0.65, MaxDD %25-35, |ρ_vsa| 0.15-0.30 → MARGINAL veya REJECTED. Sideways periodlar (2022 H2) whipsaw cluster yaratır, MaxDD gate'i geçirmez.

**Worst-case (%20 olasılık):**
- Net annual negatif, OOS Sharpe < 0, |ρ_vsa| ≥ 0.40 → REJECTED. Crypto 1D'de 50/200 EMA fazla yavaş; entry-exit gecikmesi commission'a yenilir.

**Prior tahmini hedef-üstü:** Bayesyen anlamda bu hipoteze düşük güven (confidence: low). Pre-registration disiplini bu güven seviyesini sonuca etki ettirmez — sayı kazanır.

---

## 10. Reproducibility

- git HEAD (snapshot): `bb3eda1` (commit "fix(daemon): TRADE_CLOSED_LOOKUP_FAIL")
- config hash: TBD (backtest engine config yazıldıktan sonra eklenecek)
- data hash: TBD (universe + bar data snapshot SHA-256)
- backtest seed: 42 (deterministic shuffle/perturb için)
- Python env: `pyproject.toml` lock (uv.lock SHA)

---

## 11. Karar Akışı

1. Bu doc PROPOSED → lab_scientist, risk_officer review (24h SLA).
2. Endorse / critique alındıktan sonra REVIEWED.
3. ACK ≥ 2 → backtest tetiklenir (`backtest/engine.py` + `walk_forward.py`).
4. Robustness suite (Bölüm 8) tamamı PASS → APPROVED candidate, Lab tournament'a sunulur.
5. Herhangi bir gate FAIL → REJECTED, gerekçeli arşiv, learning.md'ye 3-satır lesson.
6. **Spearman |ρ| > 0.40 ama edge yeterli senaryosu:** "stand-alone strateji olabilir ama companion DEĞİL" notu + arşiv. Ayrı bir hipotez doc'u olarak yeniden ele alınabilir.

---

## 12. Aktif Sistem Bağlamı (audit-trail)

- **0/6 reset gate kapalı** (v71 abort dossier ile aynı): RAG corpus 30d+ frozen, shelf YAML 30d+ unchanged (52nd "raftaki 66" falsifier), ops G2 cron-sanitizer SLA 18d+ breach, vsa_climax per-trade returns deterministic extractor absent (Spearman ρ ölçüm infra eksik → bu hipotezin Bölüm 8 #10 gate'i şu an mekanik olarak hesaplanamaz; **bu yapısal blocker bilinçli olarak kabul edilir, hipotez yine pre-register edilir** — extractor ship olduğunda bu hipotez "ready-to-run" listesinde olur), Principal explicit override yok, CEO seed rotation directive ARMED ama issued değil (175h+).
- v15-v17 brooks-fbo seed_abort cascade aktif (sub-5-min cadence band, ops G2 SLA breach).
- v18+ JSONL-only stub policy SADECE brooks-fbo ailesi için ARMED; cross-strategy-companion ailesi 2026-06-21'den itibaren body-mode'a döndü (bu hipotez body-mode'da).

Bu doc'un **deploy-readiness'i strüktürel blocker'a bağlı** (vsa_climax extractor). Pre-registration disiplini açısından tam, ama runtime için yarı-blocked.

---

## 13. Notlar (audit için)

- **Bu auto-cadence günün 6. companion seed'i.** Family-wise inflation kabul edildi, α sıkılaştırıldı (4.20e-4).
- **Çalıştırılma önceliği DÜŞÜK** — extractor blocker'ı kalktığında, bugünkü 6 companion adayı + dünkü 3 + önceki günkü 3 = 12 aday için aynı anda paralel backtest + cross-correlation matrix lazım. Tek tek değil, **portföy-bazlı** companion seçimi yapılır (marginal Sharpe / portfolio Sharpe artış).
- **Anti-doc-inflation disiplin:** v71 abort 8.8kb; bu hipotez ~16kb — gerekçesi: ilk-defa kullanılan kanonik strateji (RAG #4 daha önce kullanılmadı), tam pre-registration template uygulandı. Tekrar eden aboutlarda azaltma.
