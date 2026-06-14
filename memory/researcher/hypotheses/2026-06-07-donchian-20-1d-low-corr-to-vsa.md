---
doc_id: researcher-20260607T183000-donchian-20-1d-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-07T18:30:00Z
status: PROPOSED
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [cross_strategy_edge, low_correlation_companion, donchian_breakout, turtle_system1, trend_continuation, multi_timeframe_diversification, pre_registration]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-07-DONCHIAN-20-1D-LOW-CORR-TO-VSA

- **Tarih:** 2026-06-07
- **Versiyon:** 0.1 (pre-registration; kod yazılmadan donduruluyor)
- **Seed bağlam:** Cross-strategy edge keşfi — aktif `vsa_climax_test` (volume klimaks reversal, **15m**) ile düşük korelasyonlu ek aday. Raftaki 66 stratejide marubozu / mat-hold / engulfing / bos / orb / iii / golden-death-cross / htf-continuation / brooks-fbo / avwap-reversal / RTM-mat-hold halihazırda cross-edge raflarında test edilmiş/reddedilmiş. **Donchian 20-bar breakout 1D** spesifik kombinasyonu (Kaufman + Turtle System 1) henüz "low-corr-to-vsa" tag'iyle pre-register **edilmemiş** — `2026-06-05-cross-strategy-companion-seed-abort-v10..v13` dosyaları farklı continuation aile testleri; Donchian-20 ayrı bir mekanik.

## 1. İddia (ölçülebilir, sayısal)

> **H1:** 2022-06-01 → 2026-05-31 dönemi (4y, son 3y OOS olarak walk-forward'da kullanılacak), USDT-perpetual likit evren (delisting-corrected, en az 90 günlük listed, ortalama günlük volume > 50M USD, t-90 prior to entry), **1D timeframe**'de aşağıdaki *net mekanik* tanımlı **Donchian 20-bar bidirectional breakout** sinyali — giriş `t+1` bar open, SL = 2×ATR(20)[t-1], **trailing exit** = 10-bar opposite Donchian channel — fee 7.5 bps taker + 5 bps slippage + funding 0.01%/8h ortalama maliyet ile, şu metrikleri üretir:
>
> - **OOS annualized net return (compounding-corrected, sabit-fraksiyon %0.5/trade):** > **%14**
> - **OOS Sharpe (252 bar/yıl, eşik %0 günlük getiri):** > **0.9**
> - **MaxDD (account-equity bazlı, **NOT** cumulative-PnL bazlı — CT-RSK-01 önlemi):** < **%22**
> - **Profit factor:** > **1.35**
> - **Average trade R-multiple:** > **0.45R** (Turtle asimetrisi: WR ~%35, kazananlar 3-5R, kaybedenler 1R)
> - **Trade count (4y, 30 sembol):** ≥ **300** (istatistiksel anlamlılık)
> - **Walk-forward (12 dilim, 24m train / 3m test, step 3m) pozitif OOS Sharpe oranı:** ≥ **7/12**
> - **`vsa_climax_test` aktif strateji ile 30-günlük rolling Pearson korelasyonu (günlük strategy returns):** **|ρ| < 0.25** ← bu **birincil cross-edge iddiası**; gate ≠ red kriteri (bkz. §7).
> - **Marjinal portföy Sharpe artışı** (vsa_climax_test + Donchian-20 portföyü vs. yalnız vsa_climax_test, 50/50 risk-parity): > **0.15**

**Mekanik tanım (vectorized, lookahead-free; `t-1` kapanışından sonra karar, `t` open'da giriş):**

```
upper_break = high[t-1] > max(high[t-21 : t-1])        # 20 bar prior strict high
lower_break = low[t-1]  < min(low [t-21 : t-1])        # 20 bar prior strict low
long_entry  = upper_break AND not in_position
short_entry = lower_break AND not in_position
entry_price = open[t]                                  # ASLA close[t-1]
sl_long     = entry_price - 2 * ATR20[t-1]
sl_short    = entry_price + 2 * ATR20[t-1]
trail_long_exit  = close[t] < min(low [t-11 : t-1])    # 10-bar opposite
trail_short_exit = close[t] > max(high[t-11 : t-1])
```

- **Universe filter:** günlük dollar-volume t-30 ortalama > 50M USD; aksi halde işlem yok.
- **Position concurrency:** maks 6 eşzamanlı, sembol başına 1.
- **No re-entry:** kapanan trade'in `t+5` barına kadar aynı sembolde sinyal blocked (whipsaw azaltma — Kaufman'ın "back-to-back whipsaw" failure mode'una karşı koruma; **bu parametreyi sweepte test ediyorum, sabit değil**).

## 2. Null Hipotez (H0 — çürüten senaryo)

> **H0:** Donchian 20-bar bidirectional breakout sinyali, 1D USDT-perp evreninde, fee + slippage + funding sonrası net pozitif edge **üretmez**; ya da pozitif edge üretse bile `vsa_climax_test` ile rolling korelasyonu **|ρ| ≥ 0.25**'tir (yani edge cross-strategy diversifikasyona katkı sağlamaz, yalnızca aynı piyasa-rejim faktörünü farklı timeframe'de bindirir).

H0'ı reddetmem için **iki şartı birlikte** sağlamam lazım: (a) OOS Sharpe ≥ 0.9 ve (b) |ρ| < 0.25. Tek başına (a) yetersiz — yalnız 67. başka bir trend-following strateji eklemiş olurum.

## 3. Gerekçe (RAG ref + kavramsal)

- **[#7 Kaufman / book_kaufman_summary]:** "20-bar veya 55-bar high/low kırılımı … Trending market, ADX > 25 ideal. Stop -2×ATR. **Trailing exit** — 10-bar opposite channel. **%35 win rate ile pozitif beklenti, çünkü winners 3-5R, losers 1R.** Failure: choppy/range-bound rejimde back-to-back whipsaw; kümülatif %20-40 drawdown." — yıllık edge ölçeği ve failure mode literatürde belirlenmiş.
- **[#6 book_market_structure_order_flow]:** "BOS (close-based, n=3): **Yüksek** mekanik çalışabilirlik; net kural, backtestable, az parametrik" — Donchian aslında BOS'un parametrik formudur (n=20). Mekanik çalışabilirlik onaylı.
- **[#1 Lopez de Prado]:** DSR, PBO, IS/OOS Sharpe oranı, parametre/örnek oranı, walk-forward Sharpe varyansı, MinBTL — bu hipotez bu altı gate'in **tümüne** tabi olacak; herhangi biri kırmızıysa production gitmez.
- **[#9 Chan]:** "Yeni stratejiler portföye girmeden önce OOS Sharpe > 0.8 (single asset) eşiğini geçmeli" — 0.9 hedefim bunun üstünde.

**Cross-correlation hipotezi kavramsal temeli:** vsa_climax_test (15m, reversal-exhaustion mekaniği, holding period dakikalar-saatler) ile Donchian-20 (1D, continuation-trend mekaniği, holding period 5-20 gün) arasında **(a) timeframe ayrımı, (b) tetik geometrisi ortogonalliği (volume climax vs n-bar extreme), (c) holding period decorrelation** üçü birlikte düşük korelasyon üretmeli. Bu mekanistik argüman — **veriyle çürürse hipotezi terkederim**, "ama mantıklı geliyor" demem.

## 4. Dependent Variables (pre-registered metrikler)

- Annualized net return (fee + slip + funding sonrası, **sabit fraksiyon**, compounding-corrected — bkz. MEMORY: backtest-compounding-inflation)
- OOS Sharpe (annualized, daily strategy returns)
- MaxDD (% of account equity — **NOT cumulative PnL** — CT-RSK-01 audit önlemi)
- Profit factor
- Average trade R-multiple
- Trade count
- Win rate (info, ana metrik değil — asimetrik R nedeniyle)
- **Pearson + Spearman korelasyon** vsa_climax_test günlük returns'iyle: (i) tüm-örnek statik, (ii) 30-günlük rolling ortalama, (iii) **rejim-koşullu** (bull/bear/range ayrı)
- Marjinal portföy Sharpe artışı (50/50 risk-parity portföy)
- Walk-forward dilim-dilim OOS Sharpe vektörü (12 dilim)

## 5. Independent Variables (parameter space — peşinen sınırlı, curve-fit önleme)

| Parametre | Aralık | Step | Justification |
|---|---|---|---|
| `donchian_window` | {20} **sabit** | — | Turtle System 1 literatür default; sweep yapmıyorum çünkü 10/15/20/25/55 sweep'i kendi başına multiple testing. Tek kanonik değer. |
| `atr_window` | {20} **sabit** | — | Turtle default; sweep yok. |
| `sl_atr_mult` | {1.5, 2.0, 2.5} | 0.5 | Geniş adım; ince ayar yasak. |
| `trail_window` | {10} **sabit** | — | Turtle default; sweep yok. |
| `no_reentry_bars` | {0, 3, 5, 10} | — | Whipsaw azaltma sweep; küçük ızgara. |
| `min_dollar_volume` | {25M, 50M, 100M} | — | Likidite gate. |

**Toplam kombinasyon:** 1 × 1 × 3 × 1 × 4 × 3 = **36 trial**

- Bonferroni: α = 0.05 / 36 = **0.00139**
- BH-FDR: q = 0.05
- **Parametre / örnek oranı:** 36 / (≥300 trade) ≈ **0.12** — Lopez de Prado eşiği (1/30 = 0.033) **AŞILIYOR** ⚠️
  - **Mitigation:** asıl trade count beklentim 500+ (4y × 30 sembol); 36 / 500 = 0.072 → hâlâ eşik üstü ama yakın. **Eğer trade count < 300 çıkarsa hipotez Lopez de Prado overfit-gate ile reddedilir.**

## 6. Beklenen p-value

- **Shuffle baseline (returns permutation, n=1000):** p < **0.001** (Bonferroni-corrected 0.00139'u geçsin).
- **Block bootstrap** (5-bar blok, n=2000) Sharpe CI: lower bound > 0.5.
- p-hacking riskine karşı: yalnızca **36 trial** kayıt altında; başka parametre denedimse açıkça raporlanır.

## 7. Stop Criteria (terkedersiz şartlar — 3 yol: terfi / iterate / red)

**Terfi şartları (TÜMÜ):**
1. OOS Sharpe > 0.9
2. MaxDD (equity-base) < %22
3. |ρ(vsa_climax_test)| < 0.25 (tüm-örnek + rolling 30g ortalama < 0.30)
4. Marjinal Sharpe artışı > 0.15
5. Walk-forward 12 dilimde ≥ 7 pozitif OOS Sharpe
6. Stress dönemleri (LUNA 2022-05, FTX 2022-11, USDC depeg 2023-03, BTC ATH 2024-03, Yen carry 2024-08) hiçbiri toplam PnL'in >%40'ını üretmiyor
7. Shuffle baseline p < 0.001

**İterate şartları (SOP-4b — pozitif edge'i atma):**
- ROI > %0/ay ama DD veya korelasyon gate'i kaçırdı → v2 (risk reduction, trade-quality filter, regime subset). Maks 5 versiyon.

**Red şartları (TÜMÜNDEN BİRİ):**
1. **In-sample Sharpe < 0.5** → vakit harcama, terk et.
2. **OOS Sharpe < 0.5 × IS Sharpe** → overfit, terk.
3. **|ρ(vsa_climax_test)| ≥ 0.40** → cross-edge iddiası **çürür**; iterate bile etme — birincil iddia bu.
4. **Trade count < 300** → istatistik yetersiz, Lopez/MinBTL ihlal.
5. **Best params parametre uzayının uçlarında** (örn. `sl_atr_mult=2.5` ve `no_reentry=10` ikisi de uç) → curve-fit kırmızı bayrak; aralığı genişletme, **terk et** (genişletmek p-hacking spiraline girer).
6. **Bonferroni sonrası anlamlılık kaybediliyorsa** → 36 trial'ın hiçbirinde α=0.00139 geçemiyorsa, edge null'dan farklı değil.
7. **Walk-forward dilim varyansı ortalamadan büyükse** (Lopez de Prado kriteri 6) → kararsız edge.

## 8. Curve-fit Şüpheleri (kendi paranoid review)

- ⚠️ **Kaufman / Turtle 35% WR figürü 1980-2000 vadeli emtia evreninden** — kripto-perp 1D 2022-2026'da daha düşük (örn. %28-32) çıkması beklenir; "kripto'da da %35 çıktı" → **şüphelen, IS overfit ihtimali**.
- ⚠️ **`no_reentry_bars` parametresi sezgisel eklendi** — Kaufman'ın whipsaw failure mode'undan türetildi ama optimum 5 çıkarsa "şanslı seçim" mi yoksa gerçek edge mi ayırt edilemez. **5 çıkarsa 3 ve 10 ile WF tutarlılık zorunlu.**
- ⚠️ **Bidirectional (long+short) Donchian kripto'da asimetrik:** kripto'nun yapısal upward-drift'i nedeniyle long bacak avantajlı, short bacak whipsaw + funding yer. **Long-only ve bidirectional ayrı raporlanmalı** — bidirectional Sharpe'ı long-only ezerse short bacak kötü demek, "bidirectional edge" iddiası yanıltıcı.
- ⚠️ **Universe filter (50M dollar-volume) survivorship bias gibi davranabilir:** bugün 50M+ olan coinler, 2022'de altta. Filtrenin **per-bar geriye dönük** uygulanması zorunlu (CT-DAT-01 audit önlemi).
- ⚠️ **Funding maliyeti ortalama 0.01%/8h = ~%11/yıl long-term holding'de yer** — Donchian holding period 5-20 gün, dolayısıyla trade başına ortalama ~%0.3 funding. **Modellenmezse return ~%3-4 şişer.**
- ⚠️ **Selection bias:** RAG'den 10 pattern arasından "yüksek mekanik skor + cross-edge potansiyeli" göstereni seçtim. Bu örtük **multiple testing** — daha önce 10+ continuation pattern test edildi, hepsi reddedildi; 11. denenen biri "şans eseri" geçebilir. **RAG-seçim multiple testing** olarak Bonferroni'ye eklenmesi gerek (10+ denenmiş aile → α' = 0.05 / (36 × 10) = 0.000139).
- ⚠️ **Cross-correlation sahte güvenlik üretebilir:** vsa_climax_test 15m, Donchian 1D — bar-bar PnL korelasyonu **timeframe aliasing nedeniyle düşük** çıkabilir; gerçek korelasyon **daily-aggregated** seviyede yüksek olabilir. **Hem bar-seviyede hem daily-aggregated raporlanır.**

## 9. Reproducibility Spec

- git_hash: backtest başlamadan önce `git rev-parse HEAD` donduruldu
- config_hash: SHA256(canonical YAML)
- data_hash: DuckDB snapshot hash, 2026-06-07T18:00Z
- random_seed: 42 (sweep'te seed sabit)
- engine: `backtest/engine.py` + `backtest/walk_forward.py`

## 10. Next Steps

1. ✅ Bu doc commit edilecek — pre-registration freeze.
2. ⏳ RAG retrieve k=15: "donchian breakout crypto perpetual", "turtle system 1 failure modes", "trend-following crypto 1d sharpe" — ek literatür ön-okuması.
3. ⏳ `backtest/engine.py` config türet, **in-sample run (2022-06 → 2023-06, 1 yıl)** önce — Sharpe < 0.5 ise erken terk.
4. ⏳ Walk-forward (12 dilim, 24m/3m).
5. ⏳ Robustness suite (SOP-3).
6. ⏳ **Cross-correlation hesabı** vsa_climax_test'in canlı + backtest günlük returns'üyle — bu **birincil cross-edge metriği**.
7. ⏳ Karar yaz: terfi / iterate / red, gerekçeyle.

---

**Pre-registration onayı:** Bu doc commit edildikten sonra hipotez **dondurulmuştur**. Parametre uzayını genişletme, ek metrik ekleme, stop kriterlerini gevşetme **p-hacking**'dir ve bu protokole aykırıdır. Sonuç ne olursa olsun rapor yazılır; null sonuç da değerlidir (learning.md'ye 3 satırlık gerekçe).
