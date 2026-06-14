---
doc_id: researcher-20260612T100101-turtle-channel-20bar-d1-cross-edge
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-12T10:01:01Z
status: DRAFT
confidence: med
depends_on:
  - researcher-20260611-vsa-climax-volz-sweep
  - configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, cross-edge, low-corr-to-vsa, donchian, turtle-system1, trend-following, daily, pre-registered]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-12-turtle-channel-20bar-d1-cross-edge

## 0. Meta

- **Tarih:** 2026-06-12 (Asia/Istanbul)
- **Versiyon:** 0.1 (pre-registration, kod yazılmadan önce dondurulmuştur)
- **Tema:** Aktif `vsa_climax_test` (15m, exhaustion-fade) ile **düşük korelasyonlu ek bir trend-takip stratejisi**. Raftaki 66 adaydan, mekanik olarak farklı (continuation breakout) + zaman çerçevesi farklı (1D) + R-multiple profili zıt (asimetrik fat-tail vs. simetrik fade) seçildi.
- **Aday strateji:** Turtle System-1 Donchian Channel Breakout (20-bar high/low), 1D, trailing 10-bar opposite-channel exit.

## 1. İddia (Pre-Registered, Ölçülebilir)

> **"2022-01-01 ile 2025-05-31 tarihleri arasında (in-sample 3y4ay), 19-sembollik USDT-perpetual evreninde (survivorship-free build_pool_19sym), 1D timeframe'de:**
>
> Bir bar'ın kapanış değeri **önceki 20 bar'ın yüksek kapanışını** aşarsa bir sonraki bar'ın açılışında long pozisyon açılır (tersi short); stop **giriş ± 2·ATR(20)**; çıkış **10-bar karşı yön Donchian channel'a değme** (trailing). Risk **%1/trade fixed-fraction (account equity bazlı, NOT zero-base PnL)**, fee **7.5 bps taker** ve **5 bps slippage** dahil ise, in-sample backtest aşağıdaki TÜM hedefleri eşzamanlı tutturur:
>
> 1. **Aylık net ROI ≥ %1.5** (fixed-fraction, gerçek-canlı-ölçek; backtest_compounding_inflation lessonu uygulanır)
> 2. **Annualized Sharpe ≥ 1.0** (daily-bar return tabanlı, √252 ile annualize — CT-RES-01 katalog formülü)
> 3. **MaxDD ≤ %25** (rolling peak equity — account equity bazlı, sıfır-base PnL DEĞİL)
> 4. **Profit factor ≥ 1.4**
> 5. **Win rate ≥ %32 (≤ %42)** — bu bant dışına çıkış (özellikle %50+) overfit/lookahead şüphesi → otomatik red
> 6. **n_trades ≥ 100** (pool toplamı, 3y4ay) — küçükse istatistik zayıf
> 7. **Aylık return korelasyonu |ρ(turtle_1d, vsa_climax_test)| ≤ 0.20** — diversifier amacı; aksi halde edge gerçek olsa bile portföye taşınmaz
>
> Ek olarak **OOS pencerede (2025-06-01 → 2026-05-31, 12 ay)** yukarıdaki Sharpe metriği IS değerinin **en az %60'ını** korumalı (Lopez de Prado IS ≥ 3·OOS kırmızı bayrağının inversi)."**

## 2. Null Hipotez (H0)

Donchian-20 channel breakout'un 1D crypto'da pozitif edge'i **yoktur**; ölçülen P&L shuffle baseline'dan (returns bootstrap) **p ≥ 0.05** ile ayırt edilemez VEYA Kaufman'ın belirttiği "choppy/sideways regime cumulative %20-40 drawdown" (RAG #7) crypto bağlamında da realize olur → MaxDD > %30.

## 3. Gerekçe ve Literatür (RAG Referansları)

1. **[Kaufman summary — Channel Breakout (RAG #7, score=0.563):** "20-bar veya 55-bar high/low kırılımı. Turtle System 1 default. Asimetrik R-multiple; **~%35 win rate ile pozitif beklenti**, çünkü winners 3-5R, losers 1R. Failure: choppy/range-bound rejimde back-to-back whipsaw; **kümülatif %20-40 drawdown** mümkün." → Bu hem ümit hem **uyarı**; MaxDD %25 hedefimi sıkı tutuyorum.

2. **[Kaufman summary — Volatility Breakout (RAG #5):** Mekanik olarak FARKLI — open ± k·ATR intraday breakout. Donchian benim adayım N-bar high/low close-based. **Bu ayrımı pre-register ediyorum**: Kaufman vol-breakout'u (zaten 2026-06-11'de pre-register edildi) ile karıştırma riski. Param uzayı ortak DEĞİL.

3. **[Market structure / SMC (RAG #6, score=0.568):** BOS (close-based, n=3) crypto 1D'de "Yüksek" mekanik çalışabilirlik notu. BOS'un n=3 mini-versiyonu ile Donchian-20'nin **n=20 olması** — frekans/sinyal farkı: Donchian seyrek (ayda ~1-3 break per symbol) → trade ekonomisi daha az fee yükü. 2026-06-11'de pre-register edilen `bos-close-based-htf-1d` ile **mekanik benzerlik** var → **korelasyon ölçümü zorunlu** (target |ρ| ≤ 0.30 with BOS-1D backtest series; aksi halde aday redundant).

4. **[Lopez de Prado (RAG #1, score=0.582):** "DSR < 0.5, PBO > 0.5, T < MinBTL, IS Sharpe > 3·OOS Sharpe, params/sample > 1/30, walk-forward Sharpe varyans > ortalama → production'a gitmez." → **6 kriterin TAMAMINI** robustness suite'e geçtim (SOP-3 + bunlar). Tek bir kırmızı bayrak yeter.

## 4. Independent Variables (Pre-Registered, KİLİTLİ)

| Param | Değer | Sweep? | Gerekçe |
|---|---|---|---|
| `channel_length_N` | **20** | **HAYIR** | Turtle System-1 tarihsel default; sweep yapmıyorum → p-hacking riski yok |
| `atr_period` | **20** | HAYIR | Turtle default; ATR length sweep zaten in-sample fit baskı kaynağıdır |
| `stop_atr_mult` | **2.0** | HAYIR | Turtle default |
| `trailing_exit_N` | **10** | HAYIR | Turtle System-1 default ("10-bar opposite channel") |
| `timeframe` | **1D** | HAYIR | RAG #7 "Daily/weekly timeframe ideal; intraday'de gürültü baskın" |
| `risk_per_trade` | **%1.0** | HAYIR | mevcut policy floor |
| `direction` | **long + short ayrı ayrı raporlanır** | — | Long-only vs both ön-test sonrası karara bağlanır (post-test inceleme, hipotez kabul/red için **kombine net ROI** kullanılır) |

**Curve-fit kırmızı bayrak savunmaları (Lopez de Prado RAG #1 uyarınca):**

- Hiçbir parametre sweep edilmiyor → Bonferroni/FDR düzeltmesi gerekmez (n_trials=1).
- Tüm değerler 1970-1990 Turtle literatüründen — crypto öncesi → in-sample bilgi sızıntısı yok.
- Tek bir karar ucu var: long vs. short raporlama (bu **veri görüldükten sonra** alınırsa BIAS → bu yüzden hipotez kabul/red sadece **kombine net ROI'ye** bağlanır.)

## 5. Dependent Variables (Pre-Registered Ölçüm)

| Metric | Eşik | Yön | Notlar |
|---|---|---|---|
| `monthly_net_roi_avg` | ≥ %1.5 | ↑ | fixed-fraction $10k taze hesap; ay-bağımsız (NO compounding inflation) |
| `sharpe_annualized` | ≥ 1.0 | ↑ | daily-bar return × √252 |
| `max_dd_account_equity` | ≤ %25 | ↓ | **rolling peak account equity** (CT-RSK-01 katalog formülü, zero-base PnL DEĞİL) |
| `profit_factor` | ≥ 1.4 | ↑ | gross win / gross loss |
| `win_rate` | %32 — %42 | bant | bant dışı = overfit/leak şüphesi |
| `n_trades_pool_total` | ≥ 100 | ↑ | aksi halde p anlamsız |
| `corr_monthly_with_vsa_climax_test` | abs ≤ 0.20 | ↓ | aktif strateji aylık return series ile Pearson |
| `corr_monthly_with_bos_1d` | abs ≤ 0.30 | ↓ | 2026-06-11'de pre-register edilen BOS-1D ile redundancy testi |
| `oos_sharpe / is_sharpe` | ≥ 0.60 | ↑ | Lopez de Prado IS≤3·OOS kuralının inversi |
| `shuffle_baseline_p_value` | < 0.05 | ↓ | 1000 returns bootstrap |

## 6. Beklenen p-değeri

- Shuffle baseline (returns bootstrap, n=1000) altında **p < 0.01** beklenir (RAG #7 Turtle long-horizon edge'ine inanırsam).
- Bonferroni düzeltmesi GEREKMEZ — tek bir hipotez, sweep yok.
- Eğer p ∈ [0.05, 0.20] → "marginal", red **ama** literatür (RAG #7) güçlü olduğundan v2 (parametre sweep değil, evren genişletme) düşünülür.

## 7. Stop Criteria (Erken Vazgeçme)

Aşağıdakilerden biri tetiklenirse araştırma DERHAL terkedilir, başka SOP-3 testi koşulmaz:

1. **In-sample Sharpe < 0.5** → edge yok, devam etme.
2. **n_trades < 80** → istatistik anlamsız, evren küçük kal.
3. **|corr_with_vsa_climax_test| > 0.40** → diversifier amacı çöktü, taşınmaz (edge gerçek olsa bile).
4. **|corr_with_bos_1d| > 0.50** → redundant, 2026-06-11 BOS hipotezi varken bunu da ekleme.
5. **MaxDD > %40** → kapasitemizin dışı; "iterate-on-promising-edge" patikası bile kurtaramaz.
6. **OOS Sharpe / IS Sharpe < 0.30** → ağır overfit kanıtı; SOP-3 detay testi gereksiz.

## 8. Curve-Fit / Lookahead Pre-Mortem (Adversary Engineer'a Önceden Açıklama)

**Şüphelendiğim noktalar (red team okusun):**

1. **Turtle 20/10 sabitleri**: 1970'lerin commodity verisinden tüne edilmiş. "Out-of-sample testing on crypto" cila gibi görünebilir AMA o tüne **kendi yaptığım** değil → false-discovery-rate inflasyonu yok. Yine de **survivorship-free 19sym pool zorunlu** (bkz. CT-DAT-01 lesson).
2. **Daily bar crypto sample küçük**: 2022-01 → 2025-05 = ~1240 bar/sembol × 19 sym × ~%5 break-event rate ≈ ~1180 trade üst sınır. Gerçekte sinyal/sembol/ay seyrek → **n_trades ≥ 100 floor'unu sıkı tut**, altındaysa istatistik blöfü yok.
3. **Trailing 10-bar exit late-exit problemi**: Kaufman (RAG #7) "trend-day'de erken kâr alır, asimetri kaybolur" değil ama **çıkış geç olduğu için peak'ten geri verir**. Beklenen "max_R_realized / max_R_unrealized" oranı < %70 → bu metrik **rapor edilecek ama eşik DEĞİL** (post-hoc karar bias'ı yaratmamak için).
4. **Long-only mu both mu?** Crypto 2022-bear dahil ediliyor → **both directions zorunlu**; long-only sadece "sonuç görüldükten sonra" cherry-pick olur → yasak. Hipotez kabul kararı **kombine long+short net P&L'e** bağlanır.
5. **Lookahead riski (klasik):** Donchian channel hesaplama `df['high'].rolling(20).max().shift(1)` olmalı (önceki 20 bar, **bugünkü bar dahil değil**). Test: `tests/test_lookahead.py` zorunlu, causality test.
6. **Regime asimetrisi:** 2022-bear, 2023-range, 2024-bull, 2025-mixed. Trend-following yapısı **2024 single-regime bias'a açık**. **Regime split** (bull/bear/range) SOP-3'te zorunlu — en az 2 rejimde pozitif olmalı, aksi halde red.

## 9. Backtest Setup (SOP-2)

- **Universe:** `scripts/research/build_pool_19sym.py` (survivorship-free, delisting-aware)
- **Period IS:** 2022-01-01 → 2025-05-31 (3y4ay)
- **Period OOS:** 2025-06-01 → 2026-05-31 (12ay, **dokunulmaz hold-out**)
- **Engine:** `backtest/engine.py` (vectorbt veya küçük bespoke)
- **Fees:** taker 7.5 bps, maker -1 bps (varsayım: stop-limit veya market entry → taker)
- **Slippage:** 5 bps (kripto perp 1D timeframe için konservatif)
- **Initial capital:** $10,000 USDT (fixed-fraction reset her ay başı → backtest_compounding_inflation lessonu)
- **Position sizing:** %1 risk / trade, account equity bazlı

## 10. Robustness Suite (SOP-3 — zorunlu, hipotez kabul için TÜMÜ ✓)

1. Walk-forward 12 dilim (3y train + 6m test, step 3m)
2. **Param perturbation YAPILMAYACAK** — single locked param set, sweep yok (yapmak BIAS olur)
3. Symbol-out CV (leave-one-out, 19 dilim)
4. Regime split (bull/bear/range, en az 2'sinde pozitif)
5. Stress periods: 2022-05 (LUNA), 2022-11 (FTX), 2024-03 (BTC ATH), 2024-08 (Yen carry)
6. Shuffle baseline (returns bootstrap n=1000, p<0.05)
7. Multiple testing correction: **GEREKMEZ** (n_trials=1)

## 11. Karar Çerçevesi

- **Tüm 7 eşik (madde 5) + tüm 7 robustness (madde 10) ✓** → **terfi adayı**, Lab tournament'a aday config:
  `configs/strategies/turtle_donchian_20bar_1d_diversifier.yaml` (taslak; insan onayı gerekir)
- **Aylık net ROI > 0 ama gate'i geçemez (örn DD > %25 veya Sharpe < 1.0)** → **iterate** (SOP-4b, max 5 versiyon):
  - v2: risk %1 → %0.5 (DD reduction)
  - v3: trailing exit 10 → 15 bar (late exit cushion)
  - v4: regime filter (sadece ADX>25 → choppy whipsaw'dan kaçın, Kaufman uyarısı)
  - v5: symbol-out (bottom-quartile sembolleri at)
- **Aylık net ROI ≤ 0 veya |ρ(vsa)| > 0.40** → **red**, gerekçeli arşiv.

## 12. Reproducibility

- git_hash: (commit sonrası doldurulacak — pre-registration commit'i)
- config_hash: (backtest config dondurulduğunda)
- data_hash: 19sym pool snapshot hash (build_pool_19sym output)

## 13. Yorumcu Notu (Researcher → Lab/Risk/Adversary)

Lopez de Prado'nun (RAG #1) altı kırmızı bayrağından **PBO** ve **IS≤3·OOS** sweep yapmadığım için zayıf risk taşır AMA test edilecek; **DSR**, **MinBTL**, **walk-forward Sharpe variance** her aday için raporlanacak. Hipotez kabul yapsa bile, **Adversary Engineer kill-probe gating zorunlu** (LUNA + FTX + BTC ATH replay). Lab tournament'a tek başına değil **portföy katkı testi** ile değerlendirilmeli (vsa_climax_test ile birlikte koşan ensemble Sharpe lift > %15 mi? — bu Lab kararı, hipotezin gate'i değil).

**Sözüm:** OOS sonucu IS'ten 0.6× az ise araştırmayı bırakırım, hikâye yazmam.
