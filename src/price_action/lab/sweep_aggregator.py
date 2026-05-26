"""Sweep chunk aggregator — top cells'i Lab tournament challenger formatında döndürür.

Faz 14.10 (2026-05-27): Lab tournament boş `rows: []` üretiyordu çünkü
`_collect_active_challengers` yalnız Researcher hipotez dosyalarını okuyordu
(hepsi `oos_sharpe=0, oos_returns=[]` placeholder). Param sweep zaten
`reports/param_sweep/chunks/*.jsonl` altında gerçek 12000+ trade'lik
backtest cell sonuçları üretiyor (sharpe_like + mean_R_after_fees +
regime breakdown). Bu modül o veriyi tournament'a köprüler.

Tek public fonksiyon: `top_cells_as_challengers()`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from price_action.logging_config import logger

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CHUNKS_DIR = REPO_ROOT / "reports" / "param_sweep" / "chunks"


@dataclass(frozen=True)
class CellRanking:
    """Single param sweep cell, normalize edilmiş challenger formatında."""

    challenger_id: str
    strategy: str
    sl_multiplier: float
    tp_r: float
    risk_pct: float
    n_trades: int
    mean_R_after_fees: float
    sharpe_like: float  # = mean_R / std_R * sqrt(n)
    sum_R: float
    bull_mean_R: float | None
    bear_mean_R: float | None
    source_chunk: str

    def to_challenger_dict(self) -> dict[str, Any]:
        """Lab tournament'ın beklediği dict şemasına dönüş.

        Önemli: `oos_returns` boş bırakılıyor (per-trade R serisi sweep
        çıktısında yok). `oos_sharpe` olarak `sharpe_like` kullanılıyor —
        annualized değil ama relatif sıralama doğru. `oos_maxdd`
        sweep'te yok → 0 (tournament gate maxdd_excess karşılaştırması
        kullanır, 0 vs 0 nötr).
        """
        return {
            "id": self.challenger_id,
            "strategy": self.strategy,
            "params": {
                "sl_multiplier": self.sl_multiplier,
                "tp_r": self.tp_r,
                "risk_pct": self.risk_pct,
            },
            "oos_sharpe": float(self.sharpe_like),
            "oos_returns": [],  # serie yok — DSR varsayılan n=30'a düşer
            "oos_maxdd": 0.0,   # sweep cell-level DD hesaplamıyor
            "n_trials": int(self.n_trades),
            "mean_R_after_fees": float(self.mean_R_after_fees),
            "sum_R": float(self.sum_R),
            "bull_mean_R": self.bull_mean_R,
            "bear_mean_R": self.bear_mean_R,
            "source_doc": self.source_chunk,
            "status": "FROM_SWEEP_CHUNK",
        }


def _load_chunks(
    chunks_dir: Path,
    since_days: int = 7,
) -> list[dict[str, Any]]:
    """Tüm jsonl chunk dosyalarını oku, since_days'dan eski olanları at."""
    if not chunks_dir.exists():
        logger.info(
            "sweep_aggregator.chunks_dir_missing",
            extra={"path": str(chunks_dir)},
        )
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    rows: list[dict[str, Any]] = []
    for chunk_path in sorted(chunks_dir.glob("*.jsonl")):
        try:
            mtime = datetime.fromtimestamp(chunk_path.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                continue
            with chunk_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        cell = json.loads(line)
                        cell["_source_chunk"] = str(chunk_path)
                        rows.append(cell)
                    except json.JSONDecodeError:
                        continue
        except Exception as exc:
            logger.warning(
                "sweep_aggregator.chunk_read_fail",
                extra={"path": str(chunk_path), "err": str(exc)[:200]},
            )
    return rows


def top_cells_as_challengers(
    *,
    chunks_dir: Path | None = None,
    since_days: int = 7,
    top_n_per_strategy: int = 3,
    min_trades: int = 500,
    min_mean_R_after_fees: float = 0.0,
) -> list[dict[str, Any]]:
    """Sweep chunk'larından strateji başına top-N cell → challenger.

    Args:
        chunks_dir: override (default: repo/reports/param_sweep/chunks/)
        since_days: bu kadar gün içinde yazılmış chunk'lar
        top_n_per_strategy: strateji başına en iyi N cell
        min_trades: bu kadar az trade'li cell'leri at (gürültü)
        min_mean_R_after_fees: bu kadar düşük R'li cell'leri at (fee
            sonrası kayıp eden setleri tournament'a almıyoruz)

    Returns:
        Lab.weekly_tournament(challengers=...) için liste.
        Her item to_challenger_dict() formatında.
    """
    cdir = chunks_dir or DEFAULT_CHUNKS_DIR
    cells = _load_chunks(cdir, since_days=since_days)

    # Strateji bazında topla
    by_strategy: dict[str, list[CellRanking]] = {}
    for cell in cells:
        strategy = cell.get("strategy", "unknown")
        n_trades = int(cell.get("n_trades", 0))
        mean_R_fees = float(cell.get("mean_R_after_fees", 0.0))
        if n_trades < min_trades:
            continue
        if mean_R_fees < min_mean_R_after_fees:
            continue
        sl = float(cell.get("sl_multiplier", 0))
        tp = float(cell.get("tp_r", 0))
        rk = float(cell.get("risk_pct", 0))
        cell_id = f"{strategy}-sl{sl:.2f}-tp{tp:.2f}-risk{rk:.4f}"
        ranking = CellRanking(
            challenger_id=cell_id,
            strategy=strategy,
            sl_multiplier=sl,
            tp_r=tp,
            risk_pct=rk,
            n_trades=n_trades,
            mean_R_after_fees=mean_R_fees,
            sharpe_like=float(cell.get("sharpe_like", 0.0)),
            sum_R=float(cell.get("sum_R", 0.0)),
            bull_mean_R=cell.get("bull_mean_R"),
            bear_mean_R=cell.get("bear_mean_R"),
            source_chunk=str(cell.get("_source_chunk", "")),
        )
        by_strategy.setdefault(strategy, []).append(ranking)

    # Her strateji için: önce (sl, tp) bazında dedupe (R-multiple replay
    # risk_pct'e duyarsızdır; aynı sl/tp'nin farklı risk variant'ları
    # tournament slot'unu boşa harcar), sonra top-N (sharpe_like).
    challengers: list[dict[str, Any]] = []
    for strategy, rankings in by_strategy.items():
        # Dedupe: (sl, tp) → en yüksek sharpe_like olanı tut (risk_pct
        # tie-break: en küçük risk_pct = en konservatif)
        deduped: dict[tuple[float, float], CellRanking] = {}
        for r in rankings:
            key = (r.sl_multiplier, r.tp_r)
            existing = deduped.get(key)
            if existing is None or (
                r.sharpe_like > existing.sharpe_like
                or (r.sharpe_like == existing.sharpe_like and r.risk_pct < existing.risk_pct)
            ):
                deduped[key] = r
        unique = sorted(deduped.values(), key=lambda r: r.sharpe_like, reverse=True)
        top = unique[:top_n_per_strategy]
        for r in top:
            challengers.append(r.to_challenger_dict())

    logger.info(
        "sweep_aggregator.top_cells_collected",
        extra={
            "n_chunks_dirs": str(cdir),
            "n_strategies": len(by_strategy),
            "n_challengers": len(challengers),
            "strategies": list(by_strategy.keys()),
        },
    )
    return challengers


if __name__ == "__main__":
    # Manuel debug — top cells'i yazdır
    import sys
    challengers = top_cells_as_challengers()
    if not challengers:
        print("HİÇ challenger toplanamadı — chunk dosyaları boş veya filtre sıkı.")
        sys.exit(0)
    print(f"Top {len(challengers)} challenger:")
    for ch in challengers:
        print(
            f"  {ch['id']:>55}  "
            f"sharpe={ch['oos_sharpe']:+.3f}  "
            f"meanR_fees={ch['mean_R_after_fees']:+.4f}  "
            f"n={ch['n_trials']}"
        )
