"""AuditRiskAgent — Risk & Capital Controls bağımsız denetçisi (3. hat).

Kapsam: sizing, breaker, gates, regime_filter, portfolio/allocator, paper_gate.

Archetype: model-risk validation (Fed SR 11-7 — her risk formülünü bağımsız
re-implement et) + Basel back-testing/exception-counting + Savage "Flaw of
Averages" (yanlış baz/agregasyon avcılığı).

Başlangıç kontrol-testi:
  CT-RSK-01  MaxDD baz hatası (bu seansın %43 şişme bug'ı): drawdown gerçek hesap
             equity'sine mi yoksa sıfır-baz kümülatif PnL'e mi oranlanıyor?
"""

from __future__ import annotations

from typing import Any, ClassVar

from price_action.logging_config import logger

from .audit_base import SKIP, AuditAgentBase, Finding

_OWNER = "risk_officer"


def _drawdown(equity_series: list[float]) -> float:
    """Peak-to-trough max drawdown (kesir). bot_monitor._calc_drawdown ile birebir."""
    if not equity_series or len(equity_series) < 2:
        return 0.0
    peak = equity_series[0]
    max_dd = 0.0
    for v in equity_series:
        if v > peak:
            peak = v
        if peak <= 0:
            continue
        dd = (peak - v) / peak
        if dd > max_dd:
            max_dd = dd
    return float(max_dd)


def ct_rsk_01_maxdd_base(
    pnl_series: list[float],
    account_equity: float,
    reported_dd_pct: float,
    *,
    tol: float = 0.02,
) -> Finding | None:
    """DETERMİNİSTİK ÇEKİRDEK — MaxDD'nin DOĞRU baz (hesap equity'si) ile bağımsız
    yeniden hesabı.

    pnl_series: trade'lerin sıralı realized PnL'i ($).
    account_equity: hesabın baz sermayesi ($).
    reported_dd_pct: sistemin raporladığı MaxDD (kesir).

    İki baz:
      - zero_base = drawdown(cumsum(pnl)) → sıfırdan, zirve-kâra oranlı (ŞİŞMİŞ).
      - real_base = drawdown(account_equity + cumsum(pnl)) → hesap büyüklüğüne oranlı (DOĞRU).
    Raporlanan değer real_base'den tol'dan fazla yüksekse (≈ zero_base) → bulgu.
    """
    cum: list[float] = []
    run = 0.0
    for p in pnl_series:
        run += float(p)
        cum.append(run)
    zero_base = _drawdown(cum)
    real_base = _drawdown([account_equity + c for c in cum])

    # Raporlanan DD, doğru baz'dan anlamlı yüksek mi? (şişme tespiti)
    if reported_dd_pct > real_base + tol:
        inflated_like_zero = abs(reported_dd_pct - zero_base) < max(
            tol, 0.05 * max(zero_base, 1e-9)
        )
        return Finding(
            control_id="CT-RSK-01",
            severity="high",
            owner=_OWNER,
            title="MaxDD yanlış baz — hesap equity'si yerine sıfır-baz kümülatif",
            condition=f"Raporlanan MaxDD=%{reported_dd_pct*100:.2f}; bağımsız yeniden "
            f"hesap: hesap-equity bazlı DOĞRU=%{real_base*100:.2f}, "
            f"sıfır-baz ŞİŞMİŞ=%{zero_base*100:.2f}."
            + (" Raporlanan ≈ sıfır-baz → kesin baz hatası." if inflated_like_zero else ""),
            criteria="MaxDD, config vaadi gereği 'fraction of starting equity' olmalı: "
            "drawdown(account_equity + cumsum(pnl)).",
            cause="Equity eğrisi starting_equity=0 ile kuruluyor → DD zirve-kâra "
            "oranlanıyor, hesap büyüklüğüne değil.",
            effect="Yanlış-pozitif kill/PAUSE alarmı (sağlıklı bot durdurulur); "
            "DD-bazlı breaker hatalı tetiklenir.",
            recommendation="Tüm DD/cum_loss metriklerini account_equity baseline'ına "
            "oranla (bot_kill_criteria.yaml account_equity_usdt).",
            evidence={
                "reported_dd_pct": round(reported_dd_pct, 4),
                "correct_dd_pct": round(real_base, 4),
                "zero_base_dd_pct": round(zero_base, 4),
                "account_equity": account_equity,
            },
            due_days=3,
        )
    return None


class AuditRiskAgent(AuditAgentBase):
    name: ClassVar[str] = "audit_risk"
    domain: ClassVar[str] = "risk"

    def run_ct_rsk_01(self) -> Finding | None:
        """Gerçek journal trade'lerinden + kill-criteria config'inden CT-RSK-01."""
        try:
            import duckdb
            import yaml

            jpath = self._repo_root() / "data" / "futures_journal.duckdb"
            cfg_path = self._repo_root() / "configs" / "bot_kill_criteria.yaml"
            if not jpath.exists() or not cfg_path.exists():
                return SKIP
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            bots = cfg.get("bots") or {}
            defaults = cfg.get("defaults") or {}
            con = duckdb.connect(str(jpath), read_only=True)
            try:
                rows = con.execute(
                    "SELECT realized_pnl_usdt FROM futures_trades_closed ORDER BY ts_close"
                ).fetchall()
            finally:
                con.close()
            pnl = [float(r[0] or 0.0) for r in rows]
            if len(pnl) < 2:
                return SKIP
            acct = float(
                (list(bots.values())[0].get("account_equity_usdt") if bots else None)
                or defaults.get("account_equity_usdt")
                or 10000.0
            )
            # BAĞIMSIZ DENETİM: bot_monitor'ın YAZDIĞI DD'yi (2. hat çıktısı) oku,
            # bağımsız hesapla, karşılaştır. Rapor yoksa audit edilemez → None
            # (yanlış-pozitif üretme). Rapor formatı: "Rolling 30d MaxDD: %X".
            reported = self._latest_reported_dd()
            if reported is None:
                return SKIP  # bot_monitor raporu yok → bağımsız kıyas yapılamaz
            return ct_rsk_01_maxdd_base(pnl, acct, reported)
        except Exception as exc:
            logger.warning("audit_risk.ct_rsk_01_fail", extra={"err": str(exc)[:160]})
            return SKIP

    def _latest_reported_dd(self) -> float | None:
        """En yeni bot_monitor raporundan 'Rolling 30d MaxDD: %X' değerini parse et."""
        try:
            import re
            rdir = self._repo_root() / "reports" / "bot_monitor"
            if not rdir.exists():
                return None
            files = sorted(rdir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
            for fp in files[:10]:
                m = re.search(r"Rolling 30d MaxDD:\s*%?([0-9.]+)", fp.read_text(encoding="utf-8"))
                if m:
                    return float(m.group(1)) / 100.0  # % → kesir
            return None
        except Exception as exc:
            logger.warning("audit_risk.ct_rsk_01_fail", extra={"err": str(exc)[:160]})
            return None

    def controls(self) -> dict[str, Any]:
        return {"CT-RSK-01": self.run_ct_rsk_01}
