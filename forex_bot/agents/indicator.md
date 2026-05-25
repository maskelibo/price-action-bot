# Indicator Agent (forex)

**Görev:** Price action + Smart Money + volume proxy detector kütüphanesi. Vektörize, lookahead-free, pure function.

**Sözleşme:**
- `def detector(df: pd.DataFrame, **params) -> pd.Series[bool]` (or pd.DataFrame for multi-output)
- Yalnızca `df.iloc[:t]` okur; karar t mumu açılışında verilir.
- `t-1` shift testi: `out.shift(1)` ile aynı sinyali tekrar üretmemeli.

**Aileler:**
1. `indicators/price_action.py` — pin bar, engulfing, inside bar, fakey
2. `indicators/smc.py` — order block, FVG, liquidity sweep, BOS, CHoCH, premium/discount
3. `indicators/volume_proxy.py` — tick volume z-score, range expansion, spread widening, participation score
4. `indicators/confluence.py` — weighted aggregation (0..1)

**Test gate:** Coverage ≥ %85, vectorization (no .apply on rows).
