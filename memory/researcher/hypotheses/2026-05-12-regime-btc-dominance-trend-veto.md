---
type: hypothesis
hypothesis_id: HYP-REGIME-003
status: pre-registered
date: 2026-05-12
researcher: researcher_agent
related_strategy: TOP_10_OVERLAY
parent_benchmark: v0.9.2 production (yearly +57%, DD -65%)
overlay_type: cross_asset_regime_filter
parent_hypothesis: HYP-22 (2026-05-09 BTC dominance altrotation — focused on engulfing long only)
---

# HYP-REGIME-003 — BTC Dominance Regime + BTC vs Alt Side Asymmetric Veto

## Iddia (pre-registered)

> **BTC.D (BTC market cap / total crypto market cap)** trendi, altcoin pozisyonlarının başarı oranını yön-asimetrik şekilde değiştirir:
>
> 1. **BTC.D YÜKSELEN trend (slope > 0)**: Sermaye BTC'ye akıyor.
>    - **Alt LONG sinyalleri:** blok (alts underperform).
>    - **Alt SHORT sinyalleri:** PASS (alts zayıf, short profit ihtimali yüksek).
>    - **BTC kendisi:** her zaman PASS (asla bloklanmaz).
>
> 2. **BTC.D DÜŞEN trend (slope < 0)**: "Alt rotation". Sermaye alts'a akıyor.
>    - **Alt LONG:** PASS.
>    - **Alt SHORT:** half-risk (alts güçlü, short zor; risk yarıya).
>    - **BTC kendisi:** her zaman PASS.
>
> 3. **BTC.D YATAY (|slope| < threshold)**: Net rejim yok → default behavior (v0.9.2 aynen).
>
> Mevcut v0.9.2 production'a OVERLAY uygulandığında:
>
> - **Yıllık ROI:** mevcut +%57 → hedef ≥ +%50 (max %12 ROI kaybı).
> - **Max DD:** mevcut ort. −%65 → hedef ort. **−%52 ile −%55** (en az **−10 pp DD reduction**).
> - **Asıl hedef:** **2026-02-16 ve 2026-04-21 simultan multi-symbol short kayıp günleri** önlenmeli — bu günler BTC.D'nin düşüş ortasında yapılan alt-short'ları içeriyor. Beklenti: bu günlerde toplam kayıp $-5.2K → ≤ $-1.5K.

## Mekanik Kurallar (kod-edilebilir)

```python
def btcd_regime(btcd_df: pd.DataFrame, i: int) -> tuple[str, float]:
    """btcd_df: BTC.D daily snapshot. i = signal bar index.
    Returns (state, slope_value).
    """
    series = btcd_df['btc_dom'].iloc[max(0, i-31):i]  # son 30 bar [t-30..t-1]
    if len(series) < 25:
        return ("UNKNOWN", 0.0)
    x = np.arange(len(series))
    slope, _ = np.polyfit(x, series.values, 1)
    # 30-gun mutlak hareket olarak normalize
    slope_pct_per_day = slope / series.mean() * 100  # % per day

    if slope_pct_per_day > 0.03:    # >0.03% per day rising (~+1% in 30d)
        return ("BTC_DOMINANT", slope_pct_per_day)
    if slope_pct_per_day < -0.03:   # alt rotation
        return ("ALT_ROTATION", slope_pct_per_day)
    return ("NEUTRAL", slope_pct_per_day)


def apply_btcd_overlay(trade, state):
    is_btc = trade.symbol == "BTC/USDT"
    if is_btc:
        return ("PASS", 1.0)
    if state == "BTC_DOMINANT":
        if trade.side == "long":  return ("SKIP", 0.0)
        else:                     return ("PASS", 1.0)
    if state == "ALT_ROTATION":
        if trade.side == "long":  return ("PASS", 1.0)
        else:                     return ("PASS", 0.5)  # short half-risk
    return ("PASS", 1.0)  # NEUTRAL = default
```

## Bağlam Filtresi

| BTC.D Rejim | slope (%/gün) | Alt LONG | Alt SHORT | BTC | Beklenen Etki |
|---|---|---|---|---|---|
| BTC_DOMINANT | > +0.03 | SKIP | PASS | PASS | Alt long kayıplarını keser |
| ALT_ROTATION | < −0.03 | PASS | half-risk | PASS | Alt short overconfidence'i frenler |
| NEUTRAL | ±0.03 içi | default | default | default | v0.9.2 aynen |

## Literatür / Referanslar

- **CoinMetrics SOTN ("State of the Network")**: BTC dominance ile altcoin relative performansı arasında istatistiksel anlamlı negatif korelasyon (yıllık ~-0.4 ile -0.6).
- **Glassnode (2023, "BTC Dominance and Capital Rotation")**: Dominance düşüşü → sermaye alts'a; bu rotation 4-12 hafta sürebilir. Klasik "alt season" yapısı.
- **Internal H22** (`2026-05-09-btc-dominance-altrotation.md`): Engulfing LONG only filter; sadece long-side test edilmiş. Bu hipotez **iki yönlü (asimetrik)** + **tüm Top 10 stratejilere** uygulanıyor — bu nedenle H22'nin tamamlayıcısı, tekrarı değil.
- **Lo, Mamaysky, Wang (2000)**: Cross-asset rejim sinyalleri, tek-asset teknik sinyallerinin önüne geçer (orthogonal information).

## Bağımlı Değişkenler

- annualized_net_return (3y rolling)
- max_drawdown
- 2026-02 ve 2026-04 multi-short loss günlerinin toplam PnL'i (özel metrik)
- alt-short win rate by regime (ayrılmış)
- profit factor
- skip_rate (LONG-only ve SHORT-only)

## Bağımsız Değişkenler

- BTC.D slope threshold: {0.02, 0.03, 0.05} (% per day) — 3 değer
- Lookback: {21, 30, 45} bar — 3 değer
- Alt-short half-risk multiplier (ALT_ROTATION): {0.4, 0.5, 0.6} — 3 değer
- BTC her zaman PASS (sabit)

**Toplam: 27 kombinasyon. Bonferroni n=27.**

**Stage-gated test:**
1. **Stage 1 (pre-registered default):** {0.03, 30, 0.5} — tek konfig.
2. **Stage 2:** Sweep sadece robustness (perturbation) için.

## Beklenen p-value

- Stage 1: p < 0.05.
- Shuffle (BTC.D series random shuffle relative to signal dates): p < 0.01.

## Stop Criteria

- 3y rolling DD reduction < 8 pp → red.
- ROI kaybı > %15 → red.
- Sub-Nis 2026 2 kritik gün (02-16, 04-21) toplamı iyileşme < $3K → red.
- BTC.D rejim isabeti: BTC_DOMINANT etiketli pencerelerin gerçekten BTC out-performed ettiği doğrulanmalı (sanity check); değilse red.

## Veri & Implementation Risks

**KRİTİK:** BTC.D verisi backtest döneminde (2021-2026) açık API'lardan tutarlı çekilebilmeli.

- **Kaynak 1:** CoinGecko `/global` daily snapshots → 3y geriye ulaşmak için **history pulling** (rate-limit dikkat).
- **Kaynak 2:** TradingView CRYPTOCAP:BTC.D series — webscrape veya manuel CSV export.
- **Kaynak 3 (fallback):** Synthetic BTC.D = `BTC_mcap / sum(top_30_coin_mcaps)` — internal pipeline'da hesaplanabilir.

**ÖNEMLİ:** Eğer veri kalitesi 2021-2022 dönemi için zayıfsa (eski coinlerin mcap'i eksik), bu hipotez **2022-07 sonrası** pencerelerle sınırlı test edilmeli. Pre-registration'a not düşülüyor.

## Hangi 3y Rolling Pencerelerinde Etki Beklenir

| Pencere | BTC.D Profili (tahmin) | Beklenen Etki |
|---|---|---|
| 2021-05 (alt season top) | BTC.D düşük, sonra yükselen | Karışık |
| 2022-01 (LUNA → bear) | BTC.D dalgalı | Düşük etki |
| 2023-05 (bull recovery) | BTC.D yükselen (BTC dominant) | Alt-long bloklamasıyla ROI küçük kayıp + DD reduction |
| 2024 (BTC halving + ETF) | BTC.D yüksek | Maksimum alt-long bloklaması |
| **2025-08 (alt season başlangıcı)** | **BTC.D düşmeye başlayan** | **Alt-short half-risk + alt-long agresif** |
| **2026-02-04 (chop + BTC reversal)** | **BTC.D belirsiz** | **NEUTRAL daha çok bekleniyor; bu hipotez tek başına yeterli değil — REGIME-001 veya 002 ile kombo gerekli** |

## Walk-Forward Gate'leri

1. **3y/6m walk, 12 dilim:** ≥ 7 dilimde DD daralması.
2. **2026-02-16 ve 2026-04-21 yakın incelemeleri:** Bu günlerde gerçek BTC.D slope, hipoteze göre hangi rejimde idi → bu günlerde sistemi DOĞRU yönlendirdi mi (kayıp ≤ 2 short)?
3. **Symbol-out:** 11 sembol — her birini sırayla dışarı bırak; alt-short etkisi stabil mi?
4. **BTC-only invariance:** BTC trade'leri overlay öncesi ve sonrası AYNI olmalı (bug yakalayıcı sanity check).
5. **Shuffle:** BTC.D rejim etiketlerini bağımsız shuffle → null dağılım; gerçek delta ≥ %95.

## Apply-On-Top Mantığı

```
btcd_df = load_btc_dominance_daily(5y)
gather_top10_signals() -> trades
for trade in trades:
    state, _ = btcd_regime(btcd_df, trade.bar_idx)
    action, mult = apply_btcd_overlay(trade, state)
    if action == "SKIP": continue
    trade.risk_pct *= mult
backtest_replay(modified_trades, v092_config)
```

## Reproducibility

- git_hash: `<filled-on-run>`
- config_hash: `stable_hash(v0.9.2 + btcd_overlay_v001.yaml)`
- data_hash: `stable_hash(BTC.D_5y + 11_symbol_5y)`
- data_source: CoinGecko `/global` daily, fallback synthetic

## Sonuçlar (boş — backtest sonrası doldurulacak)

- [ ] In-sample 3y rolling 13 pencere
- [ ] 2026-02-16 ve 2026-04-21 gün-bazlı PnL impact
- [ ] Alt-long skip rate by regime
- [ ] Alt-short half-risk pencere by pencere
- [ ] BTC invariance check (zorunlu pass)
- [ ] Shuffle baseline p-value
- [ ] Karar: terfi / red

## Notlar

- **H22'den fark:** H22 sadece engulfing LONG sinyalini etkiliyor; bu hipotez Top 10'un tamamı + iki yönlü asimetri (long blok + short half-risk).
- **HYP-REGIME-001 (chop) ile fark:** Chop filter sembol-bazlı, lokal. BTC.D filter cross-asset. Ortogonal — kombine kullanılabilir (HYP-COMBO-002).
- BTC her zaman PASS = sistemin "anchor" sembolüne dokunma; aksi takdirde BTC trade'leri ortadan kalkar, win-rate distortion.
- "Alt-short half-risk" yerine "Alt-short SKIP" varyantı reddedildi — alt-short kazançları (2025-05 DOGE/SOL/ETH short'ları gibi) sistemin önemli alpha kaynağı; tamamen bloklamak ROI'yi yıkar.
- Bu hipotez tek başına DD'yi büyük düşürmeyebilir; **HYP-REGIME-001 veya 002 ile kombo** halinde maksimum DD reduction beklenir.
