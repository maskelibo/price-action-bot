"""AuditDataAgent — Data & Storage Integrity bağımsız denetçisi (3. hat).

Kapsam: ingest_ccxt, ingest_15m_live, quality, snapshot, rag, alt-data,
+ DEPOLAMA (DuckDB) bütünlüğü.

Archetype: DAMA-DMBOK data-quality (completeness/consistency/timeliness) +
count-control reconciliation + data-lineage/provenance.

Kontrol-testleri:
  CT-DAT-01  ingest evreni ↔ trading evreni tutarlılığı (bu seansın 3538-vs-14 bug'ı;
             her iki yön: çok büyük=israf/gürültü, çok küçük=eksik veri).
  CT-DAT-04  DuckDB kilit-bütünlüğü (ÖNGÖRÜ — bugün ingest15m exit-1; gelecekte
             tek-yazıcı açlığı / dosya bozulması). Log'da kilit-çakışması izi.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from price_action.logging_config import logger

from .audit_base import AuditAgentBase, Finding

_OWNER = "data_engineer"


def ct_dat_01_universe(
    ingest_count: int,
    trading_count: int,
    *,
    ratio_thresh: float = 3.0,
) -> Finding | None:
    """DETERMİNİSTİK ÇEKİRDEK — saatlik ingest evreni ile trading evreninin tutarlılığı.

    - ingest >> trading (oran > ratio_thresh): israf + confluence gürültü riski
      (bu seansta 3538 ingest vs 14 trading).
    - ingest < trading: trading edilen sembolün ingest kapsamında OLMAMASI =
      bayat/eksik veri (kararlar stale veriyle alınır).
    """
    if trading_count <= 0:
        return None
    if ingest_count > trading_count * ratio_thresh:
        return Finding(
            control_id="CT-DAT-01",
            severity="med",
            owner=_OWNER,
            title="ingest evreni trading evreninden aşırı büyük (israf + gürültü)",
            condition=f"Saatlik ingest {ingest_count} sembol çekiyor; bot yalnız "
            f"{trading_count} sembol trade ediyor (oran {ingest_count/trading_count:.0f}x).",
            criteria="Saatlik delta ingest CANLI-ilgili evrenle (trading + regime) "
            "sınırlı olmalı; geniş backfill ayrı/manuel iş.",
            cause="run_hourly build_universe (all_liquid) kullanıyor, trading listesini değil.",
            effect="Binlerce illiquid/delisted sembol → API/maliyet israfı, "
            "per-symbol fail gürültüsü, iş yarıda kalıp cancel.",
            recommendation="Saatlik ingest'i trading evrenine kısıtla (env override'lı).",
            evidence={"ingest_count": ingest_count, "trading_count": trading_count},
            due_days=7,
        )
    missing = trading_count - ingest_count
    if missing > 0:
        return Finding(
            control_id="CT-DAT-01",
            severity="high",
            owner=_OWNER,
            title="trading sembolleri ingest kapsamı dışında (eksik/bayat veri)",
            condition=f"Trading evreni {trading_count} sembol, saatlik ingest yalnız "
            f"{ingest_count} — {missing} sembol ingest edilmiyor.",
            criteria="Trade edilen HER sembol ingest kapsamında olmalı (taze veri).",
            cause="Trading evreni genişletildi ama ingest listesi paralel güncellenmedi.",
            effect="Eksik sembollerde bot bayat/eksik veriyle karar verir; "
            "regime/backtest/correlation hatalı.",
            recommendation="ingest listesini trading evreniyle senkronla (tek kaynak).",
            evidence={
                "ingest_count": ingest_count,
                "trading_count": trading_count,
                "missing": missing,
            },
            due_days=3,
        )
    return None


_LOCK_PATTERNS = (
    "Conflicting lock",
    "Could not set lock",
    "database is locked",
    "IOException",
)


def ct_dat_04_duckdb_lock(log_text: str, *, max_allowed: int = 0) -> Finding | None:
    """DETERMİNİSTİK ÇEKİRDEK (ÖNGÖRÜ) — DuckDB kilit-çakışması izi.

    Log metninde kilit-hata desenlerini sayar; max_allowed'ı aşarsa bulgu.
    (Bugün ingest15m exit-1; gelecekte tek-yazıcı açlığı / bozulma sınıfı.)
    """
    hits = sum(len(re.findall(re.escape(p), log_text)) for p in _LOCK_PATTERNS)
    if hits <= max_allowed:
        return None
    return Finding(
        control_id="CT-DAT-04",
        severity="high" if hits > 5 else "med",
        owner=_OWNER,
        title="DuckDB kilit-çakışması / tek-yazıcı açlığı",
        condition=f"Log'da {hits} kez DuckDB kilit-hatası deseni ({', '.join(_LOCK_PATTERNS[:3])}...).",
        criteria="Çok-yazıcılı DuckDB erişimi bounded-retry + lock-release ile "
        "çakışmasız olmalı; yazıcı process lock'u ömür boyu tutmamalı.",
        cause="CEO run_hourly + ingest15m + snapshot aynı DB'ye → single-writer "
        "starvation; lock-release/retry eksik veya regresyona uğramış.",
        effect="ingest exit-1 (taze veri kaçar), kötü durumda WAL/dosya bozulması, " "veri kaybı.",
        recommendation="write-mode bounded lock-retry + run_hourly sonrası "
        "close_pool_for_path(lock release); yedek bütünlüğü + disk doluluk izle.",
        evidence={"lock_error_hits": hits},
        due_days=5,
    )


class AuditDataAgent(AuditAgentBase):
    name: ClassVar[str] = "audit_data"
    domain: ClassVar[str] = "data"

    def run_ct_dat_01(self) -> Finding | None:
        """Saatlik ingest evreni (ingest_ccxt._HOURLY_TRADING_SYMBOLS) vs trading
        evreni (15m config strategy_portfolio.symbols)."""
        try:
            import yaml

            from price_action.data.ingest_ccxt import _HOURLY_TRADING_SYMBOLS

            cfg_path = self._repo_root() / "configs" / "risk_phoenix_scalp_15m_widestop_vsa2.yaml"
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            trading = (cfg.get("strategy_portfolio", {}) or {}).get("symbols", []) or []
            return ct_dat_01_universe(len(_HOURLY_TRADING_SYMBOLS), len(trading))
        except Exception as exc:
            logger.warning("audit_data.ct_dat_01_fail", extra={"err": str(exc)[:160]})
            return None

    def run_ct_dat_04(self) -> Finding | None:
        """Son ingest15m launchd stderr + app.log'da kilit-çakışması izi."""
        try:
            texts = []
            for rel in ("logs/launchd/ingest15m.stderr.log", "logs/app.log"):
                p = self._repo_root() / rel
                if p.exists():
                    # son ~200KB yeterli (taze pencere)
                    data = p.read_text(encoding="utf-8", errors="ignore")
                    texts.append(data[-200_000:])
            return ct_dat_04_duckdb_lock("\n".join(texts), max_allowed=0)
        except Exception as exc:
            logger.warning("audit_data.ct_dat_04_fail", extra={"err": str(exc)[:160]})
            return None

    async def daily_control_review(self) -> list[Any]:
        emitted = []
        for runner in (self.run_ct_dat_01, self.run_ct_dat_04):
            try:
                f = runner()
                if f is not None:
                    emitted.append(self.emit_finding(f))
            except Exception as exc:
                logger.warning(
                    "audit_data.ct_fail", extra={"runner": runner.__name__, "err": str(exc)[:160]}
                )
        return emitted
