"""AuditExecutionAgent — Execution & Settlement bağımsız denetçisi (3. hat).

Kapsam: order_manager, post_only/pyramid router, ccxt_live/paper, idempotency,
slippage_tracker, dead_mans_switch, reconcile_journal, futures_daemon.

Archetype: forensic transaction-cycle reconciliation + Barings/Leeson post-mortem
+ dead-man-switch reliability. "Her emrin borsada bir karşılığı olmalı; olmayan = bulgu."

Başlangıç kontrol-testleri (deterministik çekirdek — LLM'siz, test edilebilir):
  CT-EXE-01  journal↔borsa pozisyon drift'i (bu seansın XLM/NEAR bug'ı)
"""

from __future__ import annotations

from typing import Any, ClassVar

from price_action.logging_config import logger

from .audit_base import AuditAgentBase, Finding

_OWNER = "execution_chief"


def ct_exe_01_journal_drift(
    journal_open: dict[str, float],
    exchange_open: dict[str, float],
    *,
    tol_pct: float = 0.05,
) -> Finding | None:
    """DETERMİNİSTİK ÇEKİRDEK — journal'ın "açık" sandığı pozisyonlar ile borsadaki
    gerçek pozisyonları karşılaştır.

    journal_open / exchange_open: {symbol: signed_qty}. Drift türleri:
      - PHANTOM: journal'da açık (qty!=0) ama borsada yok/sıfır → reconcile_orphan
        hayalet kapanış riski (bu seansta XLM: journal -$35.69, borsa -$23.24).
      - QTY_DRIFT: ikisinde de açık ama miktar %tol'dan fazla farklı (NEAR 291 vs 219).
      - UNTRACKED: borsada açık ama journal'da yok → korumasız/izlenmeyen pozisyon.

    Bulgu varsa Finding, yoksa None döner.
    """
    syms = set(journal_open) | set(exchange_open)
    drifts: list[str] = []
    severity = "med"
    for s in sorted(syms):
        jq = float(journal_open.get(s, 0.0) or 0.0)
        eq = float(exchange_open.get(s, 0.0) or 0.0)
        if abs(jq) < 1e-9 and abs(eq) < 1e-9:
            continue
        denom = max(abs(jq), abs(eq), 1e-9)
        diff_pct = abs(jq - eq) / denom
        if abs(eq) < 1e-9 and abs(jq) > 1e-9:
            drifts.append(f"{s}: PHANTOM (journal açık {jq:g}, borsa kapalı)")
            severity = "high"
        elif abs(jq) < 1e-9 and abs(eq) > 1e-9:
            drifts.append(f"{s}: UNTRACKED (borsa açık {eq:g}, journal yok → korumasız)")
            severity = "high"
        elif diff_pct > tol_pct:
            drifts.append(f"{s}: QTY_DRIFT journal={jq:g} borsa={eq:g} (%{diff_pct*100:.1f})")
            severity = "high" if severity != "high" else severity
    if not drifts:
        return None
    return Finding(
        control_id="CT-EXE-01",
        severity=severity,
        owner=_OWNER,
        title="journal↔borsa pozisyon drift'i (settlement bütünlüğü)",
        condition="Journal'ın açık-pozisyon görüşü borsa gerçeğiyle uyuşmuyor:\n  - "
        + "\n  - ".join(drifts),
        criteria="Her journal pozisyonu borsada birebir karşılanmalı; reconcile "
        "orphan kapanışı GERÇEK borsa fill fiyatını kullanmalı; market "
        "fallback ACTUAL filled qty kaydetmeli.",
        cause="reconcile_orphan yanlış-pozitif (fetch_positions geçici boş) + "
        "kısmi-fill/market-fallback intended qty kaydı + tahmini exit fiyatı.",
        effect="Yanlış P&L (DD/kill-criteria bozulur), korumasız pozisyon, "
        "operatör güven kaybı. Canlıda gerçek para riski.",
        recommendation="reconcile orphan-guard (journal cross-check) + gerçek fill "
        "fiyatı (fetch_order) + actual-qty kaydı; günlük journal↔borsa "
        "mutabakatının SIFIR drift ile kapandığını doğrula.",
        evidence={
            "drift_count": len(drifts),
            "symbols": ", ".join(d.split(":")[0] for d in drifts),
        },
        due_days=3,
    )


class AuditExecutionAgent(AuditAgentBase):
    name: ClassVar[str] = "audit_execution"
    domain: ClassVar[str] = "execution"

    # ------------------------------------------------------------------
    # Gerçek-veri toplayıcılar (best-effort; DRY_RUN/keysiz ortamda boş döner)
    # ------------------------------------------------------------------
    def _journal_open_positions(self) -> dict[str, float]:
        """futures_journal: filled ama kapanmamış sinyallerden açık-pozisyon türet."""
        try:
            import duckdb

            jpath = self._repo_root() / "data" / "futures_journal.duckdb"
            if not jpath.exists():
                return {}
            con = duckdb.connect(str(jpath), read_only=True)
            try:
                rows = con.execute(
                    "SELECT symbol, side, fill_qty FROM futures_signals "
                    "WHERE status='filled' AND signal_id NOT IN "
                    "(SELECT trade_id FROM futures_trades_closed)"
                ).fetchall()
            finally:
                con.close()
            out: dict[str, float] = {}
            for sym, side, qty in rows:
                q = float(qty or 0.0)
                out[sym] = out.get(sym, 0.0) + (q if str(side).lower() == "long" else -q)
            return out
        except Exception as exc:
            logger.warning("audit_execution.journal_read_fail", extra={"err": str(exc)[:160]})
            return {}

    def _exchange_open_positions(self) -> dict[str, float]:
        try:
            import sys

            sys.path.insert(0, str(self._repo_root() / "scripts"))
            from scripts.futures_trade_daily import get_futures_exchange  # type: ignore

            ex = get_futures_exchange()
            out: dict[str, float] = {}
            for p in ex.fetch_positions():
                c = float(p.get("contracts") or 0.0)
                if abs(c) < 1e-9:
                    continue
                sym = str(p.get("symbol", "")).split(":")[0]
                out[sym] = c if str(p.get("side")) == "long" else -c
            return out
        except Exception as exc:
            logger.warning("audit_execution.exchange_read_fail", extra={"err": str(exc)[:160]})
            return {}

    # ------------------------------------------------------------------
    # Günlük kontrol-review
    # ------------------------------------------------------------------
    def run_ct_exe_01(self) -> Finding | None:
        """Gerçek journal + borsa verisini çekip CT-EXE-01 deterministik çekirdeğini koşar."""
        return ct_exe_01_journal_drift(
            self._journal_open_positions(),
            self._exchange_open_positions(),
        )

    async def daily_control_review(self) -> list[Any]:
        """Tüm execution kontrol-testlerini koş, bulguları emit et. Path listesi döner."""
        emitted = []
        for runner in (self.run_ct_exe_01,):
            try:
                f = runner()
                if f is not None:
                    emitted.append(self.emit_finding(f))
            except Exception as exc:
                logger.warning(
                    "audit_execution.ct_fail",
                    extra={"runner": runner.__name__, "err": str(exc)[:160]},
                )
        return emitted
