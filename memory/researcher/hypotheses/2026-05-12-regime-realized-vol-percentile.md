---
type: hypothesis
hypothesis_id: HYP-REGIME-002
status: pre-registered
date: 2026-05-12
researcher: researcher_agent
related_strategy: TOP_10_OVERLAY
parent_benchmark: v0.9.2 production (yearly +57%, DD -65%)
overlay_type: vol_regime_filter
---

# HYP-REGIME-002 — Realized Volatility Percentile Gate (Vol-Adjusted Risk Sizing)

## Iddia (pre-registered)

> Her sinyalden 1 bar önce, **BTC/USDT'nin 30-günlük annualized realized volatility (RV30)** hesaplanır ve son 2 yıllık dağılımdaki **percentile**'ı bulunur. Bu, **piyasa-genelinde vol rejimi** proxy'sidir (BTC vol kripto vol için referans).
>
> Üç rejim:
>
> 1. **HIGH-VOL** (`pctile >= 80`): Piyasa stress'te. Tradable trend OLABİLİR ama whipsaw riski yüksek. **DD breakers daha sıkı + risk %50'ye düşür.**
> 2. **NORMAL-VOL** (`20 <= pctile < 80`): Default behavior — v0.9.2 production aynen.
> 3. **LOW-VOL** (`pctile < 20`): Vol contraction → ya squeeze öncesi yaklaşıyor ya da kalıcı range. **SADECE breakout-tipi stratejileri al (brooks_failed_breakout, equal_highs_sweep'i SKIP); mean-reversion'ı normal risk'te al.**
>
> Mevcut v0.9.2 production'a OVERLAY:
>
> - **Yıllık ROI:** mevcut ort. +%57 → hedef ≥ +%48 (en fazla %15 ROI kaybı kabul).
> - **Max DD:** mevcut ort. −%65 → hedef ort. **−%48 ile −%52** (en az **−12 pp DD reduction**).
> - **2022-05 LUNA pencereleri** (HIGH-VOL stress): DD −%47.5 → ≤ −%35.
> - **2026-04 BTC reversal** (HIGH-VOL): 2026-04-21'de 4 simultan short kayıp önlenmeli (kayıp ≤ 2 trade).

## Mekanik Kurallar (kod-edilebilir)

```python
def vol_regime(df_btc: pd.DataFrame, i: int) -> tuple[str, float, set[str]]:
    """df_btc: BTC/USDT 1D OHLCV. i = signal bar index. Sadece [0..i-1] kullanilir.
    Returns (state, risk_multiplier, blocked_strategies).
    """
    close = df_btc['close'].iloc[:i]
    log_ret = np.log(close / close.shift(1)).dropna()
    rv30 = log_ret.tail(30).std() * np.sqrt(365)
    # 2y rolling percentile
    rv30_series = (
        np.log(close / close.shift(1)).rolling(30).std() * np.sqrt(365)
    ).dropna()
    lookback = rv30_series.tail(730)  # ~2y
    pct = (lookback <= rv30).mean() * 100  # percentile of current

    if pct >= 80:
        return ("HIGH_VOL", 0.5, set())                       # half risk, all strategies
    if pct < 20:
        # Low vol: block mean-reversion type, keep breakout-fade
        return ("LOW_VOL", 1.0, {"brooks_failed_breakout", "equal_highs_sweep"})
    return ("NORMAL", 1.0, set())                             # default
```

DD breaker'lar HIGH_VOL state'inde ek olarak sıkılaşır:

```python
if state == "HIGH_VOL":
    daily_dd_breaker = 0.035     # 0.05 -> 0.035
    weekly_dd_breaker = 0.075    # 0.10 -> 0.075
    consecutive_loss_pause_days = 8  # 5 -> 8
```

## Bağlam Filtresi (Hangi Rejimlerde Tetiklenir)

| Rejim | RV30 Pctile | Aksiyon | Beklenen Mantık |
|---|---|---|---|
| HIGH_VOL | ≥ 80 | half risk + sıkı breakers | Whipsaw + reversal yoğunluğu; size küçült, hızlı çık |
| NORMAL | 20-80 | default | Sistem normal davranış |
| LOW_VOL | < 20 | breakout-tipi blok | Range içinde "false break" sinyalleri yanılma oranı yüksek |

**Önemli:** HIGH_VOL'ü tamamen blok ETMİYORUZ — çünkü 2025-09-2025-12 gibi HIGH_VOL + güçlü trend pencerelerinde sistemin en büyük kazançları olabilir. Sadece **size küçültüp DD breaker sıkıyoruz**.

## Literatür (RAG referansları)

- **Ang & Bekaert (2002, "Regime Switches in Interest Rates")**: Vol rejimi yön rejiminden ortogonal; ikisi birlikte modellenmeli.
- **Mandelbrot (1963)** + **Engle (1982, ARCH)**: Vol clustering — yüksek vol bugün → yüksek vol yarın (persistence). Bu, "vol rejimi" kavramının istatistiksel temeli.
- **Moreira & Muir (2017, "Volatility-Managed Portfolios", J. Finance)**: Vol-target portfolios → realized Sharpe artar, DD belirgin azalır (özellikle 2008, 2020 stress periodları).
- **Harvey et al. (2018, "The Best Strategies for the Worst Crises", Man AHL)**: "Risk parity" + vol-targeting → crisis DD %30-50 azaltıyor.
- **Hurst, Ooi, Pedersen (2017, "A Century of Evidence on Trend-Following")**: Trend-following stratejileri yüksek vol döneminde "agile" davranır — pozisyon küçültür, geçici drawdown kabul eder. Bu, HIGH_VOL'de risk %50'ye düşürme tezimizin temel desteği.
- **Internal ADR-007** (`memory/shared/decisions/ADR-007-vol-target-sizing.md`): Defensive preset zaten vol-target enable; bu hipotez ondan farklı olarak **rejim-temelli ON/OFF** mantığı getiriyor.

## Bağımlı Değişkenler

- annualized_net_return (3y rolling 13 pencere ortalaması)
- max_drawdown (ortalama, min, max)
- profit_factor
- Sharpe (eklendi — vol-targeting Sharpe'a doğrudan etki eder)
- Calmar ratio (ROI/|DD|) — KRİTİK metric burada
- 2022-05 LUNA pencere DD
- 2024-08 yen carry trade pencere DD
- 2026-04 reversal pencere PnL

## Bağımsız Değişkenler

- HIGH_VOL pctile threshold: {75, 80, 85} — 3 değer
- LOW_VOL pctile threshold: {15, 20, 25} — 3 değer
- HIGH_VOL risk multiplier: {0.4, 0.5, 0.6} — 3 değer
- LOW_VOL blocked strategies: sabit (kod yorumda; overfit'i önlemek için sweep edilmiyor)
- DD breaker sıkılaştırma faktörü: {0.7x, 0.75x} — 2 değer (uses scaling, not absolute)

**Toplam config kombinasyonu: 3 × 3 × 3 × 2 = 54. Bonferroni n=54 → çok agresif. Bu hipotezi 2-stage test ediyoruz:**

1. **Stage 1 (default):** {80, 20, 0.5, 0.75x} — tek konfigürasyon — Bonferroni gereksiz, p < 0.05 yeter.
2. **Stage 2 (robustness):** Yukarıdaki sweep yalnızca parametre perturbation testinde kullanılır (±%10 sapma → Sharpe kaybı < %25).

## Beklenen p-value

- Stage 1 pre-registered: p < 0.05.
- Shuffle baseline: BTC vol percentile değerlerini bağımsız shuffle → null dağılım. Gerçek DD reduction ≥ %95 percentile.

## Stop Criteria

- 3y rolling ortalamada **DD reduction < 8 pp** → red.
- Calmar improvement < %15 → red.
- 2022-05 LUNA stress'te iyileşme < 5 pp → red (asıl HIGH_VOL test).
- Walk-forward 12 dilim → en az 7 dilimde DD daralması.

## Hangi 3y Rolling Pencerelerinde Etki Beklenir

| Pencere | Vol Rejimi Profili | Beklenen Etki |
|---|---|---|
| 2021-05 (BTC ATH chop) | Karışık → HIGH | Orta DD reduction |
| 2022-01 (LUNA → bear) | Yoğun HIGH_VOL | Maksimum etki ⭐ |
| 2022-07 (FTX) | Yüksek HIGH_VOL | Büyük etki |
| 2023-01 (recovery, vol cooling) | NORMAL → LOW | Hafif ROI kaybı bekleniyor |
| 2023-05 (steady bull) | Çoğunlukla NORMAL | Düşük etki |
| **2025-08-2026-04 (mixed)** | **Karışık + 2026-04 HIGH_VOL spike** | **Hedef pencere** |

## Walk-Forward Gate'leri

1. **3y/6m walk, 12 dilim:** ≥ 7 dilimde DD ve/veya Calmar iyileşmesi.
2. **Stress events:**
   - LUNA 2022-05 (HIGH_VOL): DD reduction ≥ 10 pp.
   - FTX 2022-11 (HIGH_VOL): DD reduction ≥ 8 pp.
   - 2024-08 yen carry: DD reduction ≥ 5 pp.
   - 2026-04 BTC reversal: simultan short kayıp ≤ 2.
3. **Param perturbation (±%10):** Sharpe kaybı < %25, DD geri büyüme < %20.
4. **Vol rejim isabet kontrolü:** HIGH_VOL etiketli barların gerçekten yüksek-vol olduğu (eski VIX gibi crypto vol indikatorleri ile cross-check; örn. Deribit DVOL).
5. **Cross-symbol:** BTC vol rejimi olmasına rağmen, ETH/SOL/altcoin filtresi tutarlı çalışmalı (ETH-only vol percentile alternative test edilmeli, ama PRE-REG: BTC baz alınır).

## Apply-On-Top Mantığı

```
btc_df = load_ohlcv("BTC/USDT", "1d", lookback=5y)  # once
gather_top10_signals() -> trades
for trade in trades:
    state, mult, blocked = vol_regime(btc_df, trade.bar_idx)
    if trade.strategy in blocked: SKIP
    trade.risk_pct *= mult
    if state == "HIGH_VOL":
        trade.dd_breakers = tighter_breakers()
backtest_replay(modified_trades, v092_config)
```

## Reproducibility

- git_hash: `<filled-on-run>`
- config_hash: `stable_hash(v0.9.2_baseline + vol_regime_overlay_v001.yaml)`
- data_hash: `stable_hash(BTC/USDT 5y + 11_symbol_5y)`

## Sonuçlar (boş — backtest sonrası doldurulacak)

- [ ] In-sample 3y rolling 13 pencere
- [ ] LUNA / FTX / yen carry / 2026-04 stress DD reduction
- [ ] Calmar improvement
- [ ] Shuffle baseline p-value
- [ ] Param perturbation (±%10) sonuçlar
- [ ] Karar: terfi / red

## Notlar

- **HYP-REGIME-001 ile farkı:** ADX/BBW lokal/sembol-bazinda. RV percentile **piyasa-geneli** (BTC vol). İki sinyal yarı-ortogonal; kombinasyon test edilmeli (HYP-COMBO-001).
- **ADR-007 vol-target ile farkı:** ADR-007 her trade'in size'ını sürekli ATR'ye göre ayarlıyor (volatilite-bazlı size). Bu hipotez **rejim-discrete** (HIGH/NORMAL/LOW olarak üçe ayırıyor) ve DD breaker'ları da etkiliyor — daha kaba ama yorumlanabilir, daha düşük overfit riski.
- LOW_VOL'de "breakout-tipi" stratejileri blok kararı: backtest CSV analizinden çıktı. 2026 Sub-Nis penceresinde `brooks_failed_breakout` ve `equal_highs_sweep` kayıpların %60'ı; bu dönemde BTC RV30 < %20 idi (LOW_VOL).
