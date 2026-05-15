---
agent: ops_engineer
type: learning
created: 2026-05-08
---

# Ops Engineer Learning

## Format

```
### YYYY-MM-DD — <incident slug>
- **Trigger:** ...
- **Kapsam:** ...
- **Kök neden:** ...
- **Düzeltme:** ...
- **Önleyici:** runbook / alarm / SLO değişikliği?
```

---

### 2026-05-08 — Boot
- İlk incident'tan itibaren.

### 2026-05-14 — Phase1.B1 Capital Cap Wiring (SEC20 CRITICAL fix)
- **Trigger:** SEC20'de order_router.route_signal() capital_cap_usdt parametresi var ama callerlar (futures_trade_daily.py) geçirmiyordu. Live'a geçilse $1k cap devre dışı kalırdı.
- **Kapsam:** configs/risk_balanced.yaml, src/price_action/execution/capital_cap.py, scripts/futures_trade_daily.py, tests/execution/test_capital_cap_wiring.py
- **Kök neden:** SEC20'de order_router'a parametre eklendi ama caller wiring unutuldu; daily_run() max_pos_usdt=None ile çağırıyordu.
- **Duzeltme:** (1) YAML'e live_capital_cap bloğu eklendi (enabled/max/expires/warn). (2) capital_cap.py loader yazıldı (PA_RUN_MODE gate + expiry + enabled). (3) daily_run() YAML'dan cap okuyup submit_to_futures'a geçirir. (4) submit_to_futures loop'unda 2b: REJECT-CAP — kısmi gönderme YOK. (5) 36/36 test PASS.
- **Onleyici:** Backward compat korundu: PA_RUN_MODE!=live her zaman None. cap_expires_at + warn_threshold_pct gelecek kullanım için hazır. report: reports/execution_chief/2026-05-14_capital_cap_wiring.md
