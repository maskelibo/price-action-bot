"""Data Engineer — hybrid agent.

Audit Faz 14.27'de bulundu: data_engineer/ memory klasörü vardı ama Python
agent class HİÇ TANIMSIZDI → 6+ gün sessizlik (cron tetikleyemez).

Sorumluluklar:
  - Market data ingestion sağlık (saatlik ingest_data cron sonrası kontrol)
  - Reconciliation analiz (phantom + orphan trend)
  - Regime features cache tazeligi (daily refresh kontrolü)
  - Schema parity audit (backtest vs LIVE config field mismatch)

LLM görevleri minimal: anomali tespiti + kısa summary (Haiku model).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from .base import LLMAgentBase


class DataEngineerAgent(LLMAgentBase):
    name: ClassVar[str] = "data_engineer"
    default_model: ClassVar[str] = ""  # settings.claude_model_light (Haiku)
    allowed_tools: ClassVar[tuple[str, ...]] = (
        "read_parquet",
        "read_duckdb",
        "write_report",
    )

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        if not self.model:
            self.model = self.settings.claude_model_light

    async def ingest_health_check(self) -> dict[str, Any]:
        """Saatlik ingest sonrası: market.duckdb tazeligi + row counts.

        Returns:
            {"market_db_age_hours": float, "last_ingest_ts": str|None,
             "anomalies": list[str]}
        """
        from pathlib import Path
        ROOT = Path(__file__).resolve().parents[3]
        market_db = ROOT / "data" / "market.duckdb"
        anomalies: list[str] = []
        if not market_db.exists():
            anomalies.append("market.duckdb dosyası YOK")
            age_h = float("inf")
        else:
            age_s = datetime.now(timezone.utc).timestamp() - market_db.stat().st_mtime
            age_h = age_s / 3600
            if age_h > 2.0:
                anomalies.append(f"market.duckdb yaşı {age_h:.1f}h (>2h, ingest geç kalmış)")
            if age_h > 24.0:
                anomalies.append(f"market.duckdb yaşı {age_h:.0f}h (>24h, KRİTİK)")
        return {
            "market_db_age_hours": round(age_h, 2),
            "last_ingest_ts": (
                datetime.fromtimestamp(market_db.stat().st_mtime, tz=timezone.utc).isoformat()
                if market_db.exists() else None
            ),
            "anomalies": anomalies,
        }

    async def regime_cache_health(self) -> dict[str, Any]:
        """regime_features_latest.parquet tazeligi + format doğruluğu.

        Faz 14.27 bug: fetched_at string olarak yazılıyordu, bot fallback'e
        düşüyordu (silent FRESH). Bu check sürekli izler.
        """
        from pathlib import Path
        import pandas as pd
        ROOT = Path(__file__).resolve().parents[3]
        p = ROOT / "data" / "regime_features_latest.parquet"
        anomalies: list[str] = []
        if not p.exists():
            return {"exists": False, "anomalies": ["regime_features_latest.parquet YOK"]}
        df = pd.read_parquet(p)
        if df.empty:
            anomalies.append("parquet boş")
            return {"exists": True, "rows": 0, "anomalies": anomalies}
        row = df.iloc[-1]
        fa = row.get("fetched_at")
        fa_type = type(fa).__name__
        if not isinstance(fa, (str,)) and not hasattr(fa, "to_pydatetime"):
            anomalies.append(f"fetched_at tipi beklenmiyor: {fa_type}")
        # Age
        if isinstance(fa, str):
            try:
                fa_dt = datetime.fromisoformat(fa)
            except Exception:
                anomalies.append(f"fetched_at parse fail: {fa}")
                fa_dt = None
        elif hasattr(fa, "to_pydatetime"):
            fa_dt = fa.to_pydatetime()
        else:
            fa_dt = None
        age_h = None
        if fa_dt is not None:
            if fa_dt.tzinfo is None:
                fa_dt = fa_dt.replace(tzinfo=timezone.utc)
            age_h = (datetime.now(timezone.utc) - fa_dt).total_seconds() / 3600
            if age_h > 12:
                anomalies.append(f"regime cache yaşı {age_h:.1f}h (>12h)")
        return {
            "exists": True,
            "rows": len(df),
            "fetched_at_type": fa_type,
            "age_hours": round(age_h, 2) if age_h is not None else None,
            "anomalies": anomalies,
        }

    async def reconcile_trend(self, hours_back: int = 24) -> dict[str, Any]:
        """Son N saatlik reconcile raporlarını topla — phantom/orphan trend.

        Returns:
            {"reports_n": int, "total_phantoms": int, "total_orphans": int,
             "phantom_symbols": list[str], "alerts": list[str]}
        """
        import json
        from pathlib import Path
        from datetime import timedelta
        ROOT = Path(__file__).resolve().parents[3]
        reports_dir = ROOT / "reports" / "reconcile"
        if not reports_dir.exists():
            return {"reports_n": 0, "alerts": ["reconcile reports dir yok"]}
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        total_phantoms = 0
        total_orphans = 0
        phantom_syms: set[str] = set()
        n = 0
        for f in sorted(reports_dir.glob("reconcile-*.json"), reverse=True):
            try:
                if f.stat().st_mtime < cutoff.timestamp():
                    break
                data = json.loads(f.read_text())
                stats = data.get("stats", {})
                total_phantoms += stats.get("phantoms", 0)
                total_orphans += stats.get("orphans_closed", 0)
                for s in stats.get("phantom_symbols", []) or []:
                    phantom_syms.add(s)
                n += 1
            except Exception:
                continue
        alerts: list[str] = []
        if total_phantoms > 3:
            alerts.append(f"Son {hours_back}h'de {total_phantoms} phantom — investigate")
        if total_orphans > 10:
            alerts.append(f"Son {hours_back}h'de {total_orphans} orphan close — bot/exchange drift")
        return {
            "reports_n": n,
            "total_phantoms": total_phantoms,
            "total_orphans": total_orphans,
            "phantom_symbols": sorted(phantom_syms),
            "alerts": alerts,
        }

    async def daily_health_summary(self) -> Path:
        """Günlük (06:30 UTC) data health raporu — markdown + inbox post.

        Cron tarafından tetiklenir. Üç sağlık check'i birleştirir + raporlar.
        """
        ingest = await self.ingest_health_check()
        regime = await self.regime_cache_health()
        trend = await self.reconcile_trend(hours_back=24)
        all_anomalies = ingest["anomalies"] + regime.get("anomalies", []) + trend.get("alerts", [])
        body = "\n".join([
            f"# Data Health Daily — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
            "",
            "## Ingest (market.duckdb)",
            f"- Age: {ingest['market_db_age_hours']}h",
            f"- Last ingest: {ingest.get('last_ingest_ts', 'n/a')}",
            "",
            "## Regime Features Cache",
            f"- Rows: {regime.get('rows', 0)}, age: {regime.get('age_hours', 'n/a')}h",
            f"- fetched_at type: {regime.get('fetched_at_type', 'n/a')}",
            "",
            "## Reconciliation Trend (24h)",
            f"- Reports: {trend['reports_n']}, phantoms: {trend['total_phantoms']}, orphans: {trend['total_orphans']}",
            f"- Phantom symbols: {trend['phantom_symbols']}",
            "",
            "## Anomalies",
            ("\n".join(f"- ⚠️ {a}" for a in all_anomalies)) if all_anomalies else "- (none ✅)",
        ])
        return self.write_protocol_doc(
            doc_type="data_health_daily",
            body=body,
            slug=f"data-health-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
            target_dir=self.settings.reports_dir / "data_engineer",
            status="ACTIVE",
            confidence="high",
            tags=["data_health", "daily"],
            requested_review_from=["ops_engineer"] if all_anomalies else [],
        )
