---
type: hypothesis
hypothesis_id: HYP-REGIME-001
status: pre-registered
date: 2026-05-12
researcher: researcher_agent
related_strategy: TOP_10_OVERLAY
parent_benchmark: v0.9.2 production (yearly +57%, DD -65%)
overlay_type: regime_filter
---

# HYP-REGIME-001 — Trend Quality Gate: ADX(14) + Bollinger Bandwidth Percentile (Chop Suppressor)

## Iddia (pre-registered)

> Mevcut Top 10 strateji aday-Trade'lerinin her birine, **trade tetiklenmeden 1 bar önce** ölçülen iki ortogonal trend-kalitesi metriği uygulanır:
>
> - **ADX(14, 1D)** — yön bağımsız trend gücü (Wilder).
> - **Bollinger Bandwidth Percentile (BBW pctile, 100-bar)** — volatilite genişlemesi/sıkışması.
>
> Üç rejim tanımlanır:
>
> 1. **TRENDING** (full-risk): `ADX >= 22 AND BBW_pctile >= 40`
> 2. **CHOP** (skip): `ADX < 18 AND BBW_pctile < 30`
> 3. **TRANSITION** (half-risk): diğer her şey (risk %3 → %1.5)
>
> Mevcut v0.9.2 production'a OVERLAY olarak uygulandığında, 3y rolling 13 pencere ortalamasında:
>
> - **Yıllık ROI:** mevcut ort. +%57.12 → hedef bandı +%50 ile +%60 arasında korunmalı (max −%10 ROI kaybı kabul edilebilir).
> - **Max DD:** mevcut ort. −%65.2 → hedef ort. **−%45 ile −%50** (en az **−15 pp DD reduction**).
> - **Min pencere DD:** mevcut −%71.5 → hedef ≥ −%55.
> - **Sub-Nisan 2026 DD penceresi**: özellikle bu pencere (chop ağırlıklı) için PnL −$4.2K → ≥ +$0 (zarar tamamen yutulmamalı, kayıp ≤ −$2K kabul).
>
> Bonferroni-corrected p < 0.05 (n_strategy_overlay_variants = 4).

## Mekanik Kurallar (kod-edilebilir)

Sinyal `signal_event(t)` üretildiğinde, **t-1 bar kapanışında**:

```python
def regime_state(df: pd.DataFrame, i: int) -> tuple[str, float]:
    """df: 1D OHLCV, i = signal bar index. Sadece [0..i-1] kullanilir (lookahead yok).
    Returns (state, risk_multiplier).
    """
    # ADX(14, Wilder)
    adx = wilder_adx(df.iloc[:i], period=14)  # son deger
    # Bollinger Bandwidth(20, 2)
    bb_upper, bb_mid, bb_lower = bbands(df['close'].iloc[:i], period=20, k=2)
    bbw = (bb_upper - bb_lower) / bb_mid
    # 100-bar percentile
    bbw_pct = (bbw.iloc[-100:].rank(pct=True).iloc[-1]) * 100

    if adx >= 22 and bbw_pct >= 40:
        return ("TRENDING", 1.0)      # full risk
    if adx < 18 and bbw_pct < 30:
        return ("CHOP", 0.0)          # SKIP - sinyali at
    return ("TRANSITION", 0.5)        # half risk
```

Backtest replay'inde her trade için:

```python
state, mult = regime_state(df, i)
if mult == 0.0: continue           # skip trade
risk_dollar_eff = base_risk_dollar * mult
notional_eff = notional * mult
```

## Bağlam Filtresi (Hangi Rejimlerde Tetiklenir)

| Rejim | ADX | BBW pctile | Aksiyon | Beklenen Trade Dağılımı |
|---|---|---|---|---|
| TRENDING | ≥ 22 | ≥ 40 | full risk %3 | ~%45-55 trade |
| TRANSITION | 18-22 veya 30-40 | mixed | half risk %1.5 | ~%30-40 trade |
| CHOP | < 18 | < 30 | SKIP | ~%15-25 trade kesilir |

## Literatür (RAG referansları)

- **Welles Wilder (1978, "New Concepts in Technical Trading Systems")**: ADX < 20 = trend yok / range; ADX > 25 = trend mevcut. Klasik benchmark.
- **John Bollinger (2001, "Bollinger on Bollinger Bands")**: BandWidth contraction → "The Squeeze" → eninde sonunda volatilite genişlemesi; squeeze sırasında breakout sinyalleri kümeleşir ama yanılma oranı yüksek (bias = noise).
- **Adam Grimes (2012, "Art and Science of Technical Analysis", ch.6)**: "Trending markets need trend tools, range markets need range tools" — strateji-rejim eşleştirmesi kritik.
- **Faith (2007, Turtle Trading)**: Trend-following sistemlerin yıllık DD'sinin %60+'ı, "tradable trend yok" döneminde toplanır. Filtreleme = DD küçültme.
- **Lo (2004), "The Adaptive Markets Hypothesis"**: Edge'ler rejim-koşullu; tek-rejim parametrelerle test edilen sistem misleading.

## Bağımlı Değişkenler (önceden tanımlı)

- annualized_net_return (3y rolling 13 pencere ortalaması)
- max_drawdown (her pencere, ortalama ve min)
- profit_factor
- win_rate
- pencere-bazli pozitiflik oranı (%50+ kazandiran pencere sayısı / 13)
- sub_nisan_2026_window_pnl ($)

## Bağımsız Değişkenler

- ADX threshold çiftleri: {(18,22), (20,25), (22,28)} — overfit riskine karşı kaba grid
- BBW pctile threshold çiftleri: {(30,40), (25,50)}
- Half-risk multiplier: {0.3, 0.5} — sabit; tek değer optimize edilmeyecek
- Lookback: ADX=14 (sabit, Wilder default), BBW=20/100 (sabit, Bollinger default)

**Toplam config kombinasyonu: 3 × 2 × 2 = 12. Bonferroni n=12.**

## Beklenen p-value

- Pencere-pair t-test (her pencere bağımsız): n=13, Bonferroni n=12 sonrası p < 0.05.
- Shuffle baseline (regime label random shuffle) vs gerçek: p < 0.01.

## Stop Criteria

- 3y rolling ortalamada **DD reduction < 10 pp** → red.
- ROI kaybı > %15 (mevcut +%57 → < +%48) → red.
- Sub-Nisan 2026 penceresinde iyileşme < +$2K → red (asıl hedef bu pencere).
- Walk-forward: 12 dilim, ≥ 8 dilim DD reduction göstermeli.
- IS/OOS Sharpe farkı > %40 → overfit, red.

## Hangi 3y Rolling Pencerelerinde Etki Beklenir

| Pencere (start) | Beklenen Rejim Yoğunluğu | Beklenen DD Etkisi |
|---|---|---|
| 2021-05 (LUNA + bear başlangıç) | Yüksek CHOP | Büyük iyileşme |
| 2021-07 (bear capitulation) | Karışık | Orta iyileşme |
| 2022-01-2022-05 (LUNA collapse) | Yüksek TRENDING (down) | Düşük etki |
| 2022-07 (FTX pre/post) | Yüksek CHOP | Büyük iyileşme |
| 2023-01 (bull recovery) | Yüksek TRENDING | Düşük etki / hafif ROI kaybı |
| 2023-05 (current best) | Karışık | Orta etki |
| **2025-08-2026-04 (Sub-Nis chop ⭐)** | **Yüksek CHOP** | **Maksimum etki — asıl hedef** |

## Walk-Forward Gate'leri

1. **3y/6m walk, step 3m, 12 dilim:** ≥ 8 dilimde DD daralması.
2. **Symbol-out CV:** 11 sembol → her birini sırayla dışarı bırak; ortalama DD reduction sapması ≤ %20.
3. **Regime-out CV:** TRENDING-only / CHOP-only / TRANSITION-only pencereler ayrı raporlanmalı.
4. **Stress check (mandatory):** LUNA (2022-05), FTX (2022-11), 2024-08 yen carry, **Sub-Nis 2026 chop** — bu 4 olayda mutlak DD ≤ −%30.
5. **Shuffle baseline:** Trade'lerin regime state'lerini bağımsız tekrar shuffle et (1000 simülasyon); gerçek DD reduction ≥ %95 percentile null.

## Apply-On-Top Mantığı

Bu hipotez tek başına bir strateji DEĞİL — Top 10 stratejinin **her birinin** trade çıktısı üzerinde post-filter olarak işler:

```
gather_top10_signals() -> trades
for trade in trades:
    state, mult = regime_state(df_for_symbol, trade.bar_idx)
    if mult == 0: SKIP
    else: scale trade.risk by mult
backtest_replay(scaled_trades, v092_config)
```

Hiçbir mevcut parametre değişmez. Sadece **trade-level approval + risk scaling** uygulanır.

## Reproducibility

- git_hash: `<filled-on-run>`
- config_hash: `stable_hash(v0.9.2_baseline + regime_overlay_v001.yaml)`
- data_hash: `stable_hash(11_symbols + 1d_ohlcv + 5y)`

## Sonuçlar (boş — backtest sonrası doldurulacak)

- [ ] In-sample (3y rolling 13 pencere)
- [ ] OOS (1y 2025-2026)
- [ ] Walk-forward dilim raporu
- [ ] Regime-out CV
- [ ] Symbol-out CV
- [ ] Shuffle baseline p-value
- [ ] Sub-Nis 2026 pencere PnL
- [ ] Karar: terfi / red

## Notlar

- ADX ve BBW deliberately **ORTOGONAL** seçildi: ADX yön gücü, BBW volatilite. İkisi birlikte CHOP = düşük momentum + düşük vol expansion. Tek başına ADX kullanılırsa "düşük ADX + genişleyen vol" (rejim değişim başlangıcı) yanlış skip'lenir.
- **HYP-001 ile fark:** HYP-001 1W EMA50 yön filtresi (long-only structural). Bu hipotez yön-agnostic trend KALİTESİ filtresi — long/short ikisini birden etkiler. İki hipotez ortogonal, kombo test edilmeli.
- 4h timeframe'inde ADX gürültülü; **sadece 1D Wilder ADX** kullanılacak.
- Half-risk yerine "trade'i al ama TP daha sıkı (1.0R yerine 0.7R)" varyantı düşünüldü — overfit riski yüksek olduğu için pre-registration'da yok; ilk sonuçlar pozitifse v2'de eklenebilir.
