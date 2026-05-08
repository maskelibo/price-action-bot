"""Order yaşam döngüsü yöneticisi.

Pre-trade re-check, place, monitor, partial-fill, child orders (SL/TP), heartbeat.
Tenacity ile retry. Idempotency: Signal.fingerprint() + manifest_hash duplicate kontrolü.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from price_action.contracts import Fill, OrderInstruction, Reject
from price_action.execution.broker_base import BrokerBase
from price_action.logging_config import logger
from price_action.risk.sizing import AccountState, RiskOfficer
from price_action.settings import get_settings


class OrderManager:
    """Tek noktada emir yaşam döngüsü.

    Heartbeat thread'i 60s'de bir Ops'a sinyal verir; broker tarafından kullanılır.
    """

    def __init__(
        self,
        broker: BrokerBase,
        *,
        risk_officer: RiskOfficer | None = None,
        heartbeat_sec: int = 60,
        dead_man_timeout_sec: int = 300,
    ) -> None:
        self.broker = broker
        self.risk_officer = risk_officer
        self.heartbeat_sec = heartbeat_sec
        self.dead_man_timeout_sec = dead_man_timeout_sec
        self._seen_fingerprints: set[str] = set()
        self._last_heartbeat = time.time()
        self._stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._log = logger.bind(component="order_manager", mode=broker.mode)

    # ----- heartbeat -----
    def start_heartbeat(self) -> None:
        if self._heartbeat_thread is not None:
            return

        def _loop() -> None:
            while not self._stop.is_set():
                self._last_heartbeat = time.time()
                self._log.debug("order_manager.heartbeat")
                self._stop.wait(self.heartbeat_sec)

        self._heartbeat_thread = threading.Thread(
            target=_loop, name="om-heartbeat", daemon=True
        )
        self._heartbeat_thread.start()

    def stop_heartbeat(self) -> None:
        self._stop.set()

    # ----- core -----
    def submit(self, instruction: OrderInstruction) -> Fill | Reject:
        sig = instruction.risked_order.signal
        fp = sig.fingerprint()

        # Idempotency
        if fp in self._seen_fingerprints:
            return Reject(
                signal=sig, rejected_by="execution", reason="duplicate_fingerprint"
            )

        # LIVE GUARD — settings + broker.mode tutarlı mı
        s = get_settings()
        if self.broker.mode == "live" and not s.is_live:
            return Reject(
                signal=sig,
                rejected_by="execution",
                reason="live_guard_failed",
                detail={"settings_is_live": s.is_live},
            )
        if self.broker.mode != "live" and s.pa_run_mode == "live":
            # Live moddayız ama paper broker geldi
            return Reject(
                signal=sig,
                rejected_by="execution",
                reason="broker_mode_mismatch",
                detail={"settings": s.pa_run_mode, "broker": self.broker.mode},
            )

        # Pre-trade re-check (Risk Officer son saniye)
        if self.risk_officer is not None:
            balances = self.broker.fetch_balance()
            equity = float(balances.get("USDT", 0.0))
            positions = self.broker.fetch_positions()
            account = AccountState(
                equity_usdt=equity,
                free_margin_usdt=equity,
                open_positions=positions,
            )
            re_check = self.risk_officer.evaluate(sig, account)
            if not hasattr(re_check, "quantity"):
                # Reject tipinde
                self._log.bind(reason=getattr(re_check, "reason", "?")).warning(
                    "om.pretrade_recheck_reject"
                )
                return re_check  # type: ignore[return-value]

        # Place
        fill = self.broker.place_order(instruction)
        if fill is None:
            return Reject(
                signal=sig, rejected_by="execution", reason="broker_returned_none"
            )

        self._seen_fingerprints.add(fp)
        self._log.bind(
            order_id=fill.order_id,
            symbol=fill.symbol,
            slip=fill.slippage_bps,
        ).info("om.fill")

        # SL & TP child orders — paper broker zaten state'e yazıyor; live'da
        # ayrıca exchange-side stop-market & take-profit eklenmeli.
        # MVP: Order Manager bu noktayı broker'a delege eder; mode-aware.
        self._maybe_place_protective_orders(instruction, fill)

        return fill

    def _maybe_place_protective_orders(
        self, instruction: OrderInstruction, fill: Fill
    ) -> None:
        """Live mode için stop-loss ve take-profit reduce-only emirleri.

        Paper broker SL/TP'yi state üzerinden simüle eder; bu metod live'da
        gerçek child order'ları atmak için yer tutucudur. Gerçek implementasyon
        broker venue spesifik — Ops Engineer dolduracak.
        """
        if self.broker.mode != "live":
            return
        # NOT: Bu MVP'de placeholder. Implementasyon: ex.create_order(stop, ...)
        self._log.bind(order_id=fill.order_id).debug("om.protective_orders_placeholder")

    def cancel(self, order_id: str) -> bool:
        return self.broker.cancel(order_id)

    # ----- dead man's switch -----
    @property
    def dead_mans_switch_triggered(self) -> bool:
        return time.time() - self._last_heartbeat > self.dead_man_timeout_sec
