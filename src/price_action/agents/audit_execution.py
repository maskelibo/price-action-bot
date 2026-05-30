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


def ct_exe_02_pnl_recon(
    journal_pnl: dict[str, float],
    exchange_pnl: dict[str, float],
    *,
    tol_usd: float = 10.0,
    tol_pct: float = 0.25,
) -> Finding | None:
    """DETERMİNİSTİK ÇEKİRDEK — journal'ın KAPANAN-trade realized PnL'i ile borsanın
    gerçek REALIZED_PNL'ini (income) karşılaştır.

    2026-05-30 keşfi: CT-EXE-01 yalnız AÇIK pozisyon drift'ine bakıyordu; KAPANAN
    trade PnL şişmesini (journal +57.73 vs borsa −11.58, DOT +28.73 vs −3.52)
    GÖREMEDİ. Bu kör-noktayı kapatır: settlement bütünlüğü = pozisyon + PnL.

    journal_pnl / exchange_pnl: {symbol: realized_pnl_usd}. Bulgu koşulu:
      - toplam fark > tol_usd, VEYA
      - herhangi sembolde |fark| > tol_usd ve > tol_pct × max(|jp|,|ep|) (işaret-ters dahil).
    """
    jt = sum(journal_pnl.values())
    et = sum(exchange_pnl.values())
    total_diff = jt - et
    syms = set(journal_pnl) | set(exchange_pnl)
    offenders: list[str] = []
    for s in sorted(syms):
        jp = float(journal_pnl.get(s, 0.0))
        ep = float(exchange_pnl.get(s, 0.0))
        d = jp - ep
        if abs(d) > tol_usd and abs(d) > tol_pct * max(abs(jp), abs(ep), 1.0):
            flip = " (İŞARET TERS)" if jp * ep < 0 else ""
            offenders.append(f"{s}: journal={jp:+.2f} borsa={ep:+.2f} fark={d:+.2f}{flip}")
    if abs(total_diff) <= tol_usd and not offenders:
        return None
    sev = "critical" if (abs(total_diff) > 5 * tol_usd or jt * et < 0) else "high"
    return Finding(
        control_id="CT-EXE-02",
        severity=sev,
        owner=_OWNER,
        title="journal↔borsa realized PnL mutabakatsızlığı (kapanan-trade şişmesi)",
        condition=f"Journal net realized={jt:+.2f}$ ↔ borsa (income REALIZED_PNL)="
                  f"{et:+.2f}$ — fark {total_diff:+.2f}$." +
                  ("\n  - " + "\n  - ".join(offenders) if offenders else ""),
        criteria="Kapanan-trade realized PnL borsanın gerçek REALIZED_PNL income'ı ile "
                 "eşleşmeli; GERÇEK fill fiyatı × ACTUAL qty'den hesaplanmalı.",
        cause="Kapanış realized_pnl HEDEFLENEN TP/SL fiyatı × intended-qty'den yazılıyor "
              "(gerçek fill değil); reconcile_orphan tahmini fiyat. Bot performansı şişer.",
        effect="Şişmiş kâr → yanlış strateji/deploy/sizing kararı; gerçek edge gizlenir. "
               "(Bu seansta journal +57.73 vs gerçek −11.58.)",
        recommendation="Kapanış realized_pnl'i borsa income/fetch_order'dan yaz; eski "
                       "kayıtları borsa income'a reconcile et; günlük PnL mutabakatı (bu CT).",
        evidence={"journal_total": round(jt, 2), "exchange_total": round(et, 2),
                  "diff": round(total_diff, 2), "offenders": " | ".join(offenders[:6])},
        due_days=2,
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

    def _exchange_open_positions(self) -> dict[str, float] | None:
        """Borsadaki açık pozisyonlar. Sorgu BAŞARISIZ olursa None (boş {} DEĞİL) →
        denetçi 'borsa boş' ile 'borsaya ulaşamadım'ı karıştırıp yanlış-pozitif
        (phantom) üretmesin."""
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
            return None  # ulaşılamadı → audit edilemez (skip)

    # ------------------------------------------------------------------
    # Günlük kontrol-review
    # ------------------------------------------------------------------
    def run_ct_exe_01(self) -> Finding | None:
        """Gerçek journal + borsa verisini çekip CT-EXE-01 deterministik çekirdeğini koşar.

        Borsaya ulaşılamazsa (None) audit edilemez → None döner (yanlış-pozitif üretme).
        """
        exch = self._exchange_open_positions()
        if exch is None:
            logger.info("audit_execution.ct_exe_01_skip", extra={"reason": "exchange_unreachable"})
            return None
        return ct_exe_01_journal_drift(self._journal_open_positions(), exch)

    # ------------------------------------------------------------------
    # CT-EXE-02 — journal↔borsa realized PnL mutabakatı (2026-05-30)
    # ------------------------------------------------------------------
    def _journal_realized_by_symbol(self) -> dict[str, float]:
        """futures_trades_closed realized_pnl_usdt'yi sembol bazında topla."""
        try:
            import duckdb

            jpath = self._repo_root() / "data" / "futures_journal.duckdb"
            if not jpath.exists():
                return {}
            con = duckdb.connect(str(jpath), read_only=True)
            try:
                rows = con.execute(
                    "SELECT sym, COALESCE(SUM(realized_pnl_usdt),0) FROM futures_trades_closed "
                    "GROUP BY sym"
                ).fetchall()
            finally:
                con.close()
            return {str(s).split(":")[0]: float(v or 0.0) for s, v in rows}
        except Exception as exc:
            logger.warning("audit_execution.journal_pnl_fail", extra={"err": str(exc)[:160]})
            return {}

    def _exchange_realized_by_symbol(self) -> dict[str, float] | None:
        """Borsa REALIZED_PNL income'ını sembol bazında topla. Ulaşılamazsa None."""
        try:
            import sys

            sys.path.insert(0, str(self._repo_root() / "scripts"))
            from scripts.futures_trade_daily import get_futures_exchange  # type: ignore

            ex = get_futures_exchange()
            inc = ex.fapiPrivateGetIncome({"incomeType": "REALIZED_PNL", "limit": 200})
            out: dict[str, float] = {}
            for r in inc:
                v = float(r.get("income", 0) or 0.0)
                sym_raw = str(r.get("symbol", ""))
                # "NEARUSDT" → "NEAR/USDT" normalize (journal ile eşleşsin)
                sym = sym_raw.replace("USDT", "/USDT") if sym_raw.endswith("USDT") else sym_raw
                out[sym] = out.get(sym, 0.0) + v
            return out
        except Exception as exc:
            logger.warning("audit_execution.exchange_pnl_fail", extra={"err": str(exc)[:160]})
            return None

    def run_ct_exe_02(self) -> Finding | None:
        """journal realized PnL ↔ borsa REALIZED_PNL mutabakatı. Borsa yoksa skip."""
        exch = self._exchange_realized_by_symbol()
        if exch is None:
            logger.info("audit_execution.ct_exe_02_skip", extra={"reason": "exchange_unreachable"})
            return None
        return ct_exe_02_pnl_recon(self._journal_realized_by_symbol(), exch)

    async def daily_control_review(self) -> list[Any]:
        """Tüm execution kontrol-testlerini koş, bulguları emit et. Path listesi döner."""
        emitted = []
        for runner in (self.run_ct_exe_01, self.run_ct_exe_02):
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
