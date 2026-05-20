# forex_bot — Mimari

## Tek Cümle
Mevcut kripto bot (`src/price_action/`) iskeletinin forex'e uyarlanmış sibling paketidir; aynı agent/data/signal/risk/backtest sözleşmelerini korur, forex mikroyapısına özel modüller (session, news guard, cost model, smart money) ekler.

## Hizalama
- **Modül hiyerarşisi** kripto bot ile bire bir paralel: `data/`, `indicators/`, `signals/`, `strategies/`, `risk/`, `portfolio/`, `execution/`, `backtest/`, `reporting/`, `agents/`, `configs/`, `scripts/`, `tests/`.
- **Sözleşmeler:** `Signal`, `RiskedOrder`, `Fill`, `Position`, `TradeRecord`, `Reject`, `ReproducibilityManifest` (forex-flavored: pip, lot, base/quote currency).
- **Lookahead-free:** detector'lar yalnızca `t-1` kapanışını okur, karar `t` açılışında verilir, engine'de explicit shift testi.

## Forex'e Özel Eklemeler (delta)
1. **Instrument universe** — 10 majör+seçili minör pair (`configs/pairs/*.yaml`), pair başına ayrı strateji instance + parametre.
2. **Volume problemi** — gerçek volume yok → `indicators/volume_proxy.py`: (a) broker tick volume, (b) spread genişleme, (c) range expansion. CME futures volume (6E/6B/6J) opsiyonel confirm indicator.
3. **Session awareness** — `session/tagger.py`: Asia / London / NY tagging, London-NY overlap özel handling. Sinyaller session-tagged; rapor session bazlı break-down.
4. **Smart Money Concepts** — `indicators/smc.py`: order blocks (OB), fair value gaps (FVG), liquidity sweeps (equal highs/lows hunt), break of structure (BOS), change of character (CHoCH), premium/discount zones. Forex mikroyapısına kalibre (kripto'daki agresif wick'ler nadir).
5. **News & macro guard** — `news/guard.py`: NFP/FOMC/CPI/ECB/BoE penceresi ±30dk içinde yeni entry yasak, açık pozisyonlarda stop tightening.
6. **Cost model** — `backtest/costs.py`: pair+session bazlı dinamik spread, $7/lot commission, swap (long/short ayrı), 0.5–2 pip market slippage / 2–5 pip stop-out slippage, weekend gap.

## Veri Akışı

```
┌──────────────┐      ┌──────────────┐      ┌────────────┐     ┌──────────────┐
│  Dukascopy   │─────▶│ data/store   │─────▶│ indicators │────▶│ signals/gen  │
│  (15m+1m+    │      │  DuckDB +    │      │ + SMC +    │     │ confluence + │
│   tick)      │      │  Parquet     │      │ vol proxy  │     │ filters      │
└──────────────┘      └──────────────┘      └────────────┘     └──────┬───────┘
                              ▲                                       │
                              │                              ┌────────▼─────────┐
       ┌──────────────┐       │                              │ session/tagger + │
       │ ForexFactory │───────┘                              │ news/guard       │
       │  calendar    │ news events                          └────────┬─────────┘
       └──────────────┘                                                │
                                                                       ▼
        ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
        │ reporting    │◀───│ backtest/    │◀───│ risk/officer │◀───│ portfolio/   │
        │ HTML/JSON +  │    │ engine +     │    │ + breaker +  │    │ allocator    │
        │ comparison   │    │ costs        │    │ correlation  │    │ correlation  │
        └──────────────┘    └──────┬───────┘    └──────────────┘    └──────────────┘
                                   │                                        │
                                   ▼                                        ▼
                            ┌──────────────┐                       ┌──────────────┐
                            │ trade journal│◀──────────────────────│ execution/   │
                            │ DuckDB       │       fills           │ broker_base  │
                            └──────────────┘                       │ MT5/OANDA    │
                                                                   └──────────────┘
```

## Performance Hedefi & Gerçeklik Notu
- **Hedef:** Yıllık ROI ≥ kripto botu (≈%1800), Max DD ≤ kripto, WR ≥ kripto.
- **Realistic forex band:** Major pairs annualized vol ~%5–10 (BTC ~%60–80); aynı strateji edge'i forex'e taşındığında ROI yapısal olarak ~10–20× daha düşük. Hedef tutturulamıyorsa rapor `reports/forex_vs_crypto.md`'de kantitatif gerekçe verir (vol farkı, spread tax, swap cost, session sparsity).
- **Minimum kabul:** Yıllık ROI ≥ %500, Max DD ≤ %25, WR ≥ %55, PF ≥ 2.0, Sharpe ≥ 2.5 (HIGH leverage 1:200+ ve aggressive sizing %3 ile yaklaşılabilir; daha düşük leverage'de yapısal sınır var).

## Faz Gate'leri
| Faz | Gate | Eşik |
|---|---|---|
| 0 | Veri kalitesi | Eksik mum < %0.5, weekend filtering OK |
| 1 | Indicator/SMC unit test | ≥ %85 coverage |
| 2 | Backtest 4y | ROI ≥ %500 OR honest postmortem |
| 3 | Walk-forward | %70+ pencere pozitif |
| 4 | Monte Carlo | P5 ROI > 0, P95 DD < %35 |
| 5 | OOS son 12 ay | Sharpe drop ≤ %25 |
| 6 | Paper trading | 4 hafta P&L sapma < %30 |
| 7 | Live mode | İnsan onayı sonrası mikro sermaye |

## Reproducibility
Her backtest `(git_hash, config_hash, data_hash)` manifest yazar. Aynı manifest → bit-identical equity curve.
