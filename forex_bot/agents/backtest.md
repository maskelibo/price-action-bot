# Backtest Agent (forex)

**Görev:** Walk-forward + Monte Carlo + OOS hold-out ile gerçekçi cost modelli backtest.

**Engine (`backtest/engine.py`):**
- Bar-by-bar 15m, entry next-bar-open, SL/TP intra-bar (h/l).
- Lifecycle: TP1 30% / TP2 30% / runner 40% with ATR trail.
- Force exit: 32 bars (8 hours) default.
- News close: blackout başında stage 0 trade'leri flat.
- Move SL → BE after TP1.

**Cost model (`backtest/costs.py`):**
- Spread (pair × session, sözlüklü).
- Commission $7/lot.
- Swap (long/short ayrı, overnight hold).
- Slippage 0.8 pip market / 3.0 pip stop.
- Weekend gap p50=4 / p95=12 pip.

**Walk-forward:** 6 ay train / 3 ay test, kayan pencere.
**Monte Carlo:** 1000 iter trade shuffle → P5/P50/P95 ROI & DD.
**OOS:** Son 12 ay tamamen ayrı, parametre dokunmaz.

**Faz gate:** 3y backtest pozitif PnL, WF ≥ %70 pencere pozitif, MC P5 > 0.
