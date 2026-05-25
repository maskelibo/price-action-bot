# forex_bot — Live Deployment Guide (Phase 6 → 7)

## Phase 6: Paper trading on OANDA practice account (4 hafta)

### 1. Setup
```bash
# Install OANDA SDK
pip install oandapyV20

# Create OANDA practice account at https://www.oanda.com/account/
# Get API token from "Manage API Access" → generate token
# Get account ID from account dashboard

# Set env vars (do NOT commit to git)
export FX_OANDA_API_TOKEN="your-token-here"
export FX_OANDA_ACCOUNT_ID="101-001-xxxxxxxx-001"
export FX_LIVE_CONFIRM="YES_I_KNOW"     # DOUBLE-LOCK; required to construct OandaBroker
export FX_CAPITAL_CAP_USD="1000"
```

### 2. Smoke test (1 saat)
```bash
# Verify connection
python -c "
from forex_bot.execution.oanda_iface import OandaBroker
b = OandaBroker(environment='practice')
b.connect()
print('balance:', b.balance_usd())
print('equity:', b.equity_usd({}))
"
```

### 3. Paper daemon (USDJPY-only, en güçlü edge)
```bash
python -m forex_bot.scripts.paper_daemon --pairs USDJPY --interval 900
# 15min interval, sadece USDJPY (gerçek Dukascopy 4y'de tek positive edge pair)
```

### 4. Monitoring
- `logs/forex/forex_bot.log` — rotating (200MB/14d, secret-redacted)
- `logs/forex/forex_heartbeat` — DMS heartbeat file
- `logs/forex/forex_kill_switch.json` — DMS triggered flag
- `logs/forex/forex_journal.duckdb` — closed trades
- `logs/forex/forex_slippage.duckdb` — slippage records

```bash
# Monitor
tail -f logs/forex/forex_bot.log

# Daily PnL check
python -c "
from forex_bot.execution.trade_journal import TradeJournal
j = TradeJournal('logs/forex/forex_journal.duckdb')
print('Today realized:', j.get_realized_pnl_today())
"
```

### 5. Phase 6 Gate
4 hafta paper trading sonunda:
- [ ] Realized PnL sapma backtest beklentisinden < %30
- [ ] DMS triggered count = 0 (heartbeat sağlam)
- [ ] Slippage P95 ≤ 1.5 pip
- [ ] No critical alerts (Telegram throttle)
- [ ] WR ≥ %50, PF ≥ 1.3

## Phase 7: Mikro live ($1k cap)

### 1. Activate live account
```bash
export FX_OANDA_API_TOKEN="LIVE-token"
export FX_OANDA_ACCOUNT_ID="001-001-xxxxxxxx-001"
# environment='live' instead of 'practice'
```

### 2. Switch daemon to live OANDA broker
- Replace `PaperBroker` with `OandaBroker(environment='live')` in `paper_daemon.py`
- Or use a new `live_daemon.py` (recommended for clean separation)

### 3. Capital cap protocol
- `FX_CAPITAL_CAP_USD=1000` enforced via `RiskOfficer` gate 9
- Once equity > $1000, all new orders rejected
- Manual approval required to lift cap to next tier ($5k, $10k)

### 4. Gate to scale up
| Tier | Equity Cap | Approval | Min Track Record |
|---|---|---|---|
| 1 | $1,000 | Initial | 4 weeks paper PASS |
| 2 | $5,000 | Human | 4 weeks live PASS |
| 3 | $25,000 | Human | 12 weeks live, Sharpe ≥ 1.0 |
| 4 | Open | Human | 6 months live, no DMS triggers |

## Critical Operational Rules

1. **Never bypass FX_LIVE_CONFIRM**. It's the only thing preventing accidental live trades.
2. **Always test connection in practice first**. Live mode is 1 env var swap.
3. **DMS heartbeat MUST run**. If daemon hangs, DMS auto-flattens after 300s.
4. **Kill switch active = system halted**. Don't manually re-enable without root cause analysis.
5. **Slippage CRITICAL alerts → human review**. If P95 > 5 pip, halt and investigate broker.
6. **News guard mandatory**. Never disable. Even if a strategy says "trade through NFP", DON'T.

## Reconnect / outage handling

OANDA disconnect → daemon catches exception → logs CRITICAL → if 3 consecutive failures:
- Telegram CRITICAL alert
- Pause new entries
- DMS will eventually trigger if heartbeat fails (300s)

To reconnect: restart daemon. Idempotency store ensures no duplicate orders.

## Backup & disaster recovery

Daily backup:
- `data/forex/forex.duckdb` (Dukascopy ohlcv store)
- `logs/forex/forex_journal.duckdb` (closed trades)
- `logs/forex/forex_breaker_state.json` (DD breaker state)
- `logs/forex/forex_idempotency.duckdb` (order fingerprints)

Restore: copy files, daemon picks up from latest state automatically.

## Final Pre-Live Checklist

- [ ] OANDA practice account 4 weeks tested, all gates passed
- [ ] All 45 unit tests PASS
- [ ] DMS heartbeat verified (intentional crash → auto-flatten test)
- [ ] Slippage tracker telemetry validated
- [ ] Telegram throttle confirmed (test alarm rate)
- [ ] Capital cap test: simulate equity > $1k → orders rejected
- [ ] News guard test: simulate NFP event → entries blocked ±30min
- [ ] Idempotency test: kill daemon mid-fill, restart, verify no duplicate
- [ ] Human signoff on live activation
- [ ] FX_LIVE_CONFIRM env set deliberately, not in .bashrc
