---
type: hypothesis
hypothesis_id: H-001
status: pre-registered
date: 2026-05-08
researcher: researcher_agent
related_strategy: classic_pa
---

# Hipotez H-001: Pin Bar @ S/R + Trend Filter Edge

## Iddia (pre-registered)

> 1D timeframe'de, 1W EMA50'nin üstünde fiyat olan sembollerde, son 200 barlık yatay direnç çizgisinin 0.5 ATR yakınında oluşan **bullish pin bar** (alt gölge ≥ %60, gövde ≤ %33, üst gölge ≤ %15), 1D bar açılışında long alım, 2 ATR SL ve 2R TP ile, son 3 yıl USDT-perpetual evreninde (likidite filtreli):
> - Annualized net return > %50 (fee+slip dahil)
> - Sharpe > 1.0
> - MaxDD < %25
> - Profit factor > 1.4

(Bearish simetri: 1W EMA50 altı + S/R yakını bearish pin bar — short.)

## Gerekçe (literatür)

- **Brooks (Reading Price Charts Bar by Bar):** "Pin bar requires context. S/R adds context."
- **Volman (Forex PA Scalping):** Pin bar = "PBF" (Pattern Break Fakey) varyantı; S/R kümeleme yüksek olasılık.
- **Wyckoff:** S/R dış dünyaya "spring" / "upthrust" tepki — pin bar bunu somut bir mum kalıbı olarak yakalar.
- **Grimes (Art and Science):** Multi-timeframe confluence (1W trend + 1D pattern) edge'i belirler.

## Bağımlı Değişkenler (önceden tanımlı)

- annualized_net_return
- sharpe_ratio
- max_drawdown
- profit_factor
- win_rate
- expectancy_R
- avg_holding_bars

## Bağımsız Değişkenler

- pin bar parametreleri (gölge oranı, gövde oranı)
- S/R kümeleme: lookback (200), atr_multiplier (0.5), min_touches (2)
- ATR SL çarpanı (2.0)
- R-multiple TP (2.0)
- trend filter periyodu (1W EMA50)

## Beklenen p-value

- Çoklu hipotez testi sonrası (Bonferroni n=10) anlamlı (p < 0.005).
- Shuffle baseline'a karşı anlamlı (p < 0.01).

## Stop Criteria

- In-sample Sharpe < 0.5 → araştırma terkedilir.
- OOS Sharpe < 0.7 → red ve gerekçeli arşiv.
- IS/OOS Sharpe farkı > %50 → overfit, red.
- Walk-forward dilimleri %50'den azı pozitif → red.

## Veri

- Universe: `configs/symbols.yaml::universe.mode = all_liquid`, son 3 yıl.
- Survivorship: delisted semboller dahil (delisting'e kadar).
- Fees: 7.5 bps taker, -1 bp maker.
- Slippage: 5 bps base.

## Reproducibility

- git_hash: <to-be-filled-on-run>
- config_hash: stable_hash(classic_pa.yaml + risk.yaml)
- data_hash: stable_hash(universe + date_range + dataset_version)

## Sonuçlar (boş — backtest sonrası doldurulacak)

- [ ] In-sample
- [ ] Out-of-sample
- [ ] Walk-forward (dilim sayısı)
- [ ] Robustness suite
- [ ] Karar: terfi adayı / red

## Notlar

İlk pre-registered hipotez. `classic_pa` stratejisinin çekirdek hipotezi.
