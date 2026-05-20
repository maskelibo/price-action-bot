# Signal Agent (forex)

**Görev:** Strategy library'den session+news filtreli sinyal üret, confluence skoruyla rank et.

**Çekirdek pipeline:**
1. `SignalGenerator.prepare_features(df)` — ATR, EMA20/50/200, swings, SMC, participation, session column.
2. Her strategy `generate_signals(df_feat, pair)` çağrılır.
3. Session filter: `session_score_for_pair(pair, sess) >= min_session_score (0.50)`.
4. News filter: `news_guard.is_blackout` → block.
5. Confluence: weighted (pattern 0.25 + structure 0.20 + smc 0.20 + volume 0.15 + session 0.10 + trend 0.10).
6. Threshold `0.55` default.

**Strategy library:**
- `london_breakout`, `ny_open_reversal`, `asia_range_fade`, `smc_liquidity_sweep`,
- `ob_retest_continuation`, `fvg_fill`, `pin_bar_session`, `engulfing_session`.
