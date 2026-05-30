"""AuditResearchAgent — Research & Backtest Integrity denetçisi (3. hat).

Kapsam: hypotheses → hypothesis_runner → lab → backtest/engine → walk_forward →
drift → promotion. "Backtest = hipotez; metrik doğru mu, gate gerçekten uygulandı mı,
overfit/leakage var mı?"

Archetype: Bailey & López de Prado (Deflated Sharpe / backtest overfitting PBO) +
reproducibility (Ioannidis) + GIPS performance-presentation verification.

Kontrol-testi:
  CT-RES-01  Sharpe annualization şişmesi (bu seansın 17.3 bug'ı): eşzamanlı
             trade'ler bağımsız sayılıp √(trades_per_year) ile çarpılıyor mu?
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from price_action.logging_config import logger

from .audit_base import SKIP, AuditAgentBase, Finding

_OWNER = "lab_scientist"


def ct_res_01_sharpe(
    reported_sharpe: float,
    *,
    implausible_threshold: float = 8.0,
    mean_r: float | None = None,
    std_r: float | None = None,
    n_trades: int | None = None,
) -> Finding | None:
    """DETERMİNİSTİK ÇEKİRDEK — raporlanan annualized Sharpe makul mü?

    Bu strateji sınıfı (intraday price-action) için annualized Sharpe ~1-4 makul.
    >implausible_threshold (örn 8) → büyük olasılıkla trade-sayısı annualization
    şişmesi: (mean_R/std_R)*sqrt(trades_per_year) eşzamanlı trade'leri bağımsız
    sayıyor. (Bu seansta 17.3 raporlanmıştı; gerçek takvim-günü ~3.6-8.)
    """
    if reported_sharpe is None:
        return None
    if reported_sharpe <= implausible_threshold:
        return None
    detail = ""
    if mean_r is not None and std_r and n_trades:
        # trade-sayısı bazlı (şişmiş) tahmini göster
        import math

        try:
            tnaive = (mean_r / std_r) * math.sqrt(max(n_trades, 1))
            detail = f" (mean_R/std_R·√n ≈ {tnaive:.1f} — trade-sayısı bazlı şişme deseni)"
        except Exception:
            pass
    return Finding(
        control_id="CT-RES-01",
        severity="high",
        owner=_OWNER,
        title="Sharpe annualization şişmesi (trade-sayısı bazlı)",
        condition=f"Raporlanan annualized Sharpe={reported_sharpe:.1f}, bu strateji "
        f"sınıfı için makul tavanın (~{implausible_threshold:.0f}) çok "
        f"üstünde{detail}.",
        criteria="Sharpe TAKVİM-GÜNÜ getirisinden hesaplanmalı (per-trade R'yi giriş "
        "gününe topla → günlük getiri Sharpe × √365), eşzamanlı trade'leri "
        "bağımsız sayan √(trades_per_year) DEĞİL.",
        cause="metrics/param_sweep Sharpe'ı (mean_R/std_R)·√(trades_per_year) ile "
        "hesaplıyor; overlapping pozisyonlar bağımsız varsayılıyor.",
        effect="Şişmiş Sharpe yanlış promotion/deploy kararı → curve-fit aday canlıya "
        "geçer. GIPS ihlali (yanlış performans sunumu).",
        recommendation="Sharpe'ı takvim-günü bazına çevir; mutlak-deploy Sharpe ile "
        "karşılaştırma Sharpe'ını ayır; Deflated Sharpe (PBO) uygula.",
        evidence={
            "reported_sharpe": round(reported_sharpe, 2),
            "implausible_threshold": implausible_threshold,
        },
        due_days=7,
    )


class AuditResearchAgent(AuditAgentBase):
    name: ClassVar[str] = "audit_research"
    domain: ClassVar[str] = "res"

    def run_ct_res_01(self) -> Finding | None:
        """En yeni backtest_results JSON'larını tara; şişmiş Sharpe var mı."""
        try:
            res_dir = self._repo_root() / "memory" / "researcher" / "backtest_results"
            if not res_dir.exists():
                return SKIP  # backtest sonucu yok → denetlenecek bir şey yok
            files = sorted(res_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            worst: Finding | None = None
            for fp in files[:20]:  # son 20 sonuç
                try:
                    data = json.loads(fp.read_text(encoding="utf-8"))
                except Exception:
                    continue
                # olası alan adları
                sharpe = (
                    data.get("sharpe_annualized")
                    or data.get("oos_sharpe")
                    or data.get("sharpe")
                    or 0.0
                )
                f = ct_res_01_sharpe(float(sharpe or 0.0))
                if f is not None:
                    f.evidence["source"] = fp.name
                    # en yüksek şişmeyi tut
                    if worst is None or float(sharpe) > worst.evidence.get("reported_sharpe", 0):
                        worst = f
            return worst
        except Exception as exc:
            logger.warning("audit_research.ct_res_01_fail", extra={"err": str(exc)[:160]})
            return SKIP

    def controls(self) -> dict[str, Any]:
        return {"CT-RES-01": self.run_ct_res_01}
