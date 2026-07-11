"""Active v15p2 wrapper must expose the canonical replay-safe protection path."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.subprocess
def test_v15p2_restores_canonical_protection_and_pins_each_entry(tmp_path: Path) -> None:
    code = r'''
import json
import os
from pathlib import Path

import ccxt

log_path = Path(os.environ["PA_RUNTIME_ROOT"]) / "logs/futures_daemon_v15p2.log"
log_size_before = log_path.stat().st_size if log_path.exists() else 0
import scripts.futures_daemon_v14 as v14
import scripts.futures_trade_daily as ftd
log_size_after_import = log_path.stat().st_size if log_path.exists() else 0


class Exchange:
    def __init__(self):
        self.orders = {}
        self.create_attempts = []
        self.next_id = 1

    def amount_to_precision(self, _symbol, value):
        return str(value)

    def price_to_precision(self, _symbol, value):
        return str(value)

    def fetch_order(self, _order_id, _symbol, params=None):
        client_id = (params or {}).get("clientAlgoId")
        if client_id not in self.orders:
            raise ccxt.OrderNotFound("OrderNotFound")
        return dict(self.orders[client_id])

    def create_order(self, symbol, type, side, amount, params):
        client_id = params["newClientOrderId"]
        self.create_attempts.append(client_id)
        order = {
            "id": f"order-{self.next_id}",
            "clientOrderId": client_id,
            "type": type,
            "side": side,
            "amount": amount,
            "triggerPrice": params["stopPrice"],
            "reduceOnly": params["reduceOnly"],
            "symbol": symbol,
        }
        self.next_id += 1
        self.orders[client_id] = order
        return dict(order)


exchange = Exchange()
active = ftd.place_protection_orders
kwargs = {
    "exchange": exchange,
    "symbol": "BTC/USDT:USDT",
    "side": "long",
    "qty": 1.0,
    "tp_price": 112.5,
    "sl_price": 95.0,
    "entry_price": 100.0,
    "protection_key": "PA_entry-one",
}
first = active(**kwargs)
first_attempts = len(exchange.create_attempts)
second = active(**kwargs)
second_attempts = len(exchange.create_attempts)
kwargs["protection_key"] = "PA_entry-two"
third = active(**kwargs)

print(json.dumps({
    "canonical_identity": active is v14._v13mod._original_place_protection_orders,
    "active_name": active.__name__,
    "legacy_wrapper_active": active is v14._v13mod._v13_place_protection_orders,
    "first_status": first["status"],
    "first_prices": [first["tp_price"], first["tp2_price"], first["sl_price"]],
    "first_ids": sorted(first["client_order_ids"].values()),
    "second_sources": sorted(leg["source"] for leg in second["legs"].values()),
    "first_attempts": first_attempts,
    "second_attempts": second_attempts,
    "third_status": third["status"],
    "third_ids": sorted(third["client_order_ids"].values()),
    "final_attempts": len(exchange.create_attempts),
    "import_log_size_before": log_size_before,
    "import_log_size_after": log_size_after_import,
}, sort_keys=True))
'''
    env = os.environ.copy()
    env.update(
        {
            "PA_TESTING": "1",
            "PYTHON_DOTENV_DISABLED": "1",
            "PA_RUNTIME_ROOT": str(tmp_path / "runtime"),
            "PA_V14_PHASE": "v15p2",
            "PA_LIVE_CONFIRM": "",
            "PA_LOG_QUIET": "1",
        }
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["canonical_identity"] is True
    assert result["active_name"] == "place_protection_orders"
    assert result["legacy_wrapper_active"] is False
    assert result["first_status"] == "placed"
    assert result["first_prices"] == [105.0, 107.5, 95.0]
    assert len(set(result["first_ids"])) == 3
    assert result["first_attempts"] == 3
    assert result["second_attempts"] == 3
    assert result["second_sources"] == ["reconciled", "reconciled", "reconciled"]
    assert result["third_status"] == "placed"
    assert set(result["first_ids"]).isdisjoint(result["third_ids"])
    assert result["final_attempts"] == 6
    assert result["import_log_size_after"] == result["import_log_size_before"]
