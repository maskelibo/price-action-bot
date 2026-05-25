# Reporting Agent (forex)

**Görev:** Per-pair, per-session, per-month break-down + equity/DD/R distribution + crypto comparison.

**Çıktılar (`reports/forex/`):**
- `forex_backtest_<ts>.html` — KPI tablosu + per-* breakdown'lar.
- `forex_kpis_<ts>.json` — programmatic okuma için.
- `forex_vs_crypto.html` — crypto bot KPI'leri ile yan yana.

**KPI seti:** ROI total, CAGR, Sharpe, Sortino, Calmar, Max DD, WR, Profit Factor, Expectancy (R), n_trades.

**Karşılaştırma raporu:** Eğer forex ROI < crypto ROI hedefi, neden farkı `rationale` bloğunda kantitatif gerekçe (vol farkı, spread tax, swap drag, session sparsity).
