# Execution Agent (forex)

**Görev:** Order routing, idempotency, slippage telemetry, broker abstraction.

**Mode:**
- `paper` — `PaperBroker` (default).
- `live` — `MT5Broker | OandaBroker | CTraderBroker` (stub'lar, Phase 7 sonrasında implement).

**Order flow:**
1. `OrderRouter.route(signal, account, ts, market_price)`.
2. Idempotency check (`signal_fingerprint = sha256(pair|ts|side|sl|strategy)[:16]`).
3. RiskOfficer evaluation.
4. Broker `place_order(decision)`.
5. Status ∈ {filled, rejected, duplicate, broker_error}.

**Slippage:** 0.8 pip market, 3 pip stop-out (config).
**Commission:** $7/lot round-turn.

**NOT:** Live trading bu milestone'da yok. ExecutionAgent interface tanımlı, paper-only.
