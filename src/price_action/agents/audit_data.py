"""AuditDataAgent — Data & Storage Integrity bağımsız denetçisi (3. hat).

Kapsam: ingest_ccxt, ingest_15m_live, quality, snapshot, rag, alt-data,
+ DEPOLAMA (DuckDB) bütünlüğü.

Archetype: DAMA-DMBOK data-quality (completeness/consistency/timeliness) +
count-control reconciliation + data-lineage/provenance.

Kontrol-testleri:
  CT-DAT-01  ingest evreni ↔ trading evreni tutarlılığı (bu seansın 3538-vs-14 bug'ı;
             her iki yön: çok büyük=israf/gürültü, çok küçük=eksik veri).
  CT-DAT-04  DuckDB depolama-bütünlüğü (SINIF-bazlı): (a) lock-çakışması/açlığı →
             high; (b) handle-invalidation / allocator-bozulması ('Invalid bitmask',
             'has been invalidated', 'must be restarted') → critical. 2026-06-01
             saatlik invalidation'ı (eski lock-only dedektör kaçırmıştı) artık yakalanır.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from price_action.logging_config import logger

from .audit_base import SKIP, AuditAgentBase, Finding

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


# DuckDB arıza SINIFLARI — spesifik string değil, sınıf yakala (denetimin klasik
# zaafı: yalnız son ısıran varyantı aramak). İki tier:
#   LOCK     = çok-yazıcı çakışması/açlığı → ingest exit-1, taze veri kaçar (high).
#   FATAL    = handle invalidation / allocator-bozulması / corruption → process'in
#              DB handle'ı zehirlenir, restart gerekir, veri KAYBI riski (critical).
_LOCK_PATTERNS = (
    "Conflicting lock",
    "Could not set lock",
    "database is locked",
    "IOException",
)
_FATAL_PATTERNS = (
    "has been invalidated",
    "must be restarted",
    "Invalid bitmask",
    "FixedSizeAllocator",
    "FATAL Error",
    "Corruption",
    "Checksum",
    "database is invalid",
)


def _count_hits(log_text: str, patterns: tuple[str, ...]) -> int:
    return sum(len(re.findall(re.escape(p), log_text)) for p in patterns)


def ct_dat_04_duckdb_lock(log_text: str, *, max_allowed: int = 0) -> Finding | None:
    """DETERMİNİSTİK ÇEKİRDEK (ÖNGÖRÜ) — DuckDB SINIF-bazlı arıza izi.

    İki arıza sınıfını da sayar (lock + fatal/corruption); ``max_allowed``'ı aşarsa
    bulgu. FATAL sınıfı (handle invalidation / allocator-bozulması) lock'tan ağırdır:
    process handle'ı zehirler, restart ister, veri kaybı riski taşır → ``critical``.
    Lock yalnız taze-veri gecikmesi → ``high``.

    Eski isim/imza korunur (geriye uyumluluk); davranış genişledi: artık sadece
    kilit değil, bu gecenin "Invalid bitmask / has been invalidated" sınıfını da yakalar.
    """
    fatal_hits = _count_hits(log_text, _FATAL_PATTERNS)
    lock_hits = _count_hits(log_text, _LOCK_PATTERNS)
    if fatal_hits + lock_hits <= max_allowed:
        return None

    if fatal_hits > 0:
        return Finding(
            control_id="CT-DAT-04",
            severity="critical",
            owner=_OWNER,
            title="DuckDB handle invalidation / bozulma (FATAL — restart gerekir)",
            condition=f"Log'da {fatal_hits} kez DuckDB FATAL deseni "
            f"('has been invalidated' / 'Invalid bitmask for FixedSizeAllocator' / "
            f"'must be restarted'){f' + {lock_hits} kilit izi' if lock_hits else ''}.",
            criteria="DuckDB bağlantısı bir fatal hata sonrası zehirlenmişse process "
            "AYNI handle'ı yeniden kullanmamalı (reconnect); tek dosyaya eşzamanlı "
            "yazıcı (run_hourly + ingest15m + snapshot) çakışması olmamalı.",
            cause="Zehirlenmiş/yeniden-kullanılan global DuckDB handle veya eşzamanlı "
            "çok-process write → allocator/dosya bozulması; handle ömür boyu invalid kalıyor.",
            effect="ingest yolu KALICI ölü (her saat tekrar); kötü durumda WAL/dosya "
            "bozulması + VERİ KAYBI. Snapshot backstop arızayı maskeliyor.",
            recommendation="reconnect-on-invalidation (zehirli handle'ı kapat→yeniden aç) + "
            "run_hourly'de bağlantı izolasyonu (aç→kullan→kapat) + yazıcıları serialize et + "
            "yedek/disk-doluluk izle. En erken 'Invalid bitmask' zaman damgasını bul (ne zaman başladı).",
            evidence={"fatal_hits": fatal_hits, "lock_hits": lock_hits},
            due_days=1,
        )
    return Finding(
        control_id="CT-DAT-04",
        severity="high" if lock_hits > 5 else "med",
        owner=_OWNER,
        title="DuckDB kilit-çakışması / tek-yazıcı açlığı",
        condition=f"Log'da {lock_hits} kez DuckDB kilit-hatası deseni "
        f"({', '.join(_LOCK_PATTERNS[:3])}...).",
        criteria="Çok-yazıcılı DuckDB erişimi bounded-retry + lock-release ile "
        "çakışmasız olmalı; yazıcı process lock'u ömür boyu tutmamalı.",
        cause="CEO run_hourly + ingest15m + snapshot aynı DB'ye → single-writer "
        "starvation; lock-release/retry eksik veya regresyona uğramış.",
        effect="ingest exit-1 (taze veri kaçar), kötü durumda WAL/dosya bozulması, veri kaybı.",
        recommendation="write-mode bounded lock-retry + run_hourly sonrası "
        "close_pool_for_path(lock release); yedek bütünlüğü + disk doluluk izle.",
        evidence={"lock_error_hits": lock_hits},
        due_days=1,
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
            return SKIP

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
            return SKIP

    def controls(self) -> dict[str, Any]:
        return {"CT-DAT-01": self.run_ct_dat_01, "CT-DAT-04": self.run_ct_dat_04}
