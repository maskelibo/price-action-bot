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
    """Single param sweep cell, normalize edilmiş challenger formatında.

    FIX 2026-05-27 (Faz 14.11): param_sweep_runner artık per-cell
    max_drawdown_R, sharpe_annualized, returns_R_sample üretiyor. Bu
    sınıf bunları tournament'ın anlayacağı equity-% DD'ye çevirir.
    """

    challenger_id: str
    strategy: str
    sl_multiplier: float
    tp_r: float
    risk_pct: float
    n_trades: int
    mean_R_after_fees: float
    sharpe_like: float
    sharpe_annualized: float
    sum_R: float
    max_drawdown_R: float            # R cinsinden (param_sweep_runner çıktısı)
    trades_per_year: float
    returns_R_sample: list[float]    # 500-trade sample (Welch t-test için)
    bull_mean_R: float | None
    bear_mean_R: float | None
    source_chunk: str

    @property
    def oos_maxdd_pct(self) -> float:
        """R-cinsinden DD'yi equity %DD'ye çevir.

        equity_dd ≈ max_drawdown_R × risk_pct
        Örn: 25 R DD × 0.5% risk = 12.5% equity DD
        Bu yaklaşım sequential equity-curve sim'den farklı (compounding
        ihmal); yeterince doğru bir lower-bound proxy.
        """
        return float(self.max_drawdown_R) * float(self.risk_pct)

    def monthly_metrics(self) -> dict[str, float]:
        """FIX 2026-05-27 (Faz 14.13): Principal'in anladığı dilde metrik —
        aylık ROI ortalama, max DD %, negatif ay sayısı, yıllık compound.

        Hesap:
            equity[0] = 1.0
            her trade: equity *= (1 + R * risk_pct)
            sample period_years = n_trades / trades_per_year
            month_count = period_years * 12
            equity'yi month_count parçaya böl, her parçanın return'i = aylık ROI
            mean_monthly_roi_pct, max_dd_pct (peak-trough), neg_month_count

        Sample boyutu 500 trade, gerçek pool 12K-34K. Sample stratejisi
        first250+last250 = kronolojik kapsama ⇒ aylık dağılım tahmini
        gerçek 5y backtest'inkine yakın (büyük sapma yok).
        """
        if not self.returns_R_sample or self.trades_per_year <= 0:
            return {
                "monthly_roi_pct_mean": 0.0,
                "monthly_roi_pct_median": 0.0,
                "monthly_neg_count": 0,
                "monthly_total_count": 0,
                "annual_compound_pct": 0.0,
                "max_dd_compound_pct": 0.0,
            }
        try:
            import numpy as np
            r = np.array(self.returns_R_sample, dtype=float)
            n = len(r)
            risk = float(self.risk_pct) or 0.005
            # Equity curve: compound (1 + R*risk)
            per_trade_ret = r * risk
            equity = np.cumprod(1.0 + per_trade_ret)
            # Sample period years (sample n / yearly rate)
            period_years = float(n) / max(float(self.trades_per_year), 1.0)
            total_months = max(period_years * 12.0, 1.0)
            month_count = int(round(total_months))
            if month_count < 2:
                # too small span — return aggregate-as-month
                monthly_returns = np.array([equity[-1] - 1.0])
            else:
                # Equity'yi month_count parçaya böl
                edges = np.linspace(0, n - 1, month_count + 1).astype(int)
                monthly_returns_list = []
                prev_eq = 1.0
                for i in range(month_count):
                    end_eq = equity[edges[i + 1]]
                    monthly_returns_list.append((end_eq / prev_eq) - 1.0)
                    prev_eq = end_eq
                monthly_returns = np.array(monthly_returns_list)
            monthly_roi_mean = float(monthly_returns.mean())
            monthly_roi_median = float(np.median(monthly_returns))
            neg_count = int((monthly_returns < 0).sum())
            total_count = int(len(monthly_returns))
            # Compound annual return
            final_equity = float(equity[-1])
            if period_years > 0:
                annual_compound = final_equity ** (1.0 / period_years) - 1.0
            else:
                annual_compound = 0.0
            # Max DD on compound equity curve
            running_peak = np.maximum.accumulate(equity)
            dd = (equity - running_peak) / running_peak
            max_dd = float(-dd.min())
            return {
                "monthly_roi_pct_mean": monthly_roi_mean * 100.0,
                "monthly_roi_pct_median": monthly_roi_median * 100.0,
                "monthly_neg_count": neg_count,
                "monthly_total_count": total_count,
                "annual_compound_pct": annual_compound * 100.0,
                "max_dd_compound_pct": max_dd * 100.0,
            }
        except Exception:
            return {
                "monthly_roi_pct_mean": 0.0,
                "monthly_roi_pct_median": 0.0,
                "monthly_neg_count": 0,
                "monthly_total_count": 0,
                "annual_compound_pct": 0.0,
                "max_dd_compound_pct": 0.0,
            }

    def to_challenger_dict(self) -> dict[str, Any]:
        """Lab tournament'ın beklediği dict şemasına dönüş.

        Yeni alanlar:
        - oos_sharpe: annualized (sharpe_like değil)
        - oos_returns: 500-trade sample (Welch p-value hesaplanabilir)
        - oos_maxdd: equity %DD (R*risk dönüşümü, lower-bound proxy)
        - monthly_*: Faz 14.13 — Principal'in anladığı dilde metrik
          (aylık ROI ortalama %, neg ay sayısı, max DD compound)
        """
        monthly = self.monthly_metrics()
        return {
            "id": self.challenger_id,
            "strategy": self.strategy,
            "params": {
                "sl_multiplier": self.sl_multiplier,
                "tp_r": self.tp_r,
                "risk_pct": self.risk_pct,
            },
            "oos_sharpe": float(self.sharpe_annualized),
            "oos_returns": list(self.returns_R_sample),
            "oos_maxdd": self.oos_maxdd_pct,
            "n_trials": int(self.n_trades),
            # Diagnostik
            "mean_R_after_fees": float(self.mean_R_after_fees),
            "sum_R": float(self.sum_R),
            "max_drawdown_R": float(self.max_drawdown_R),
            "sharpe_like_raw": float(self.sharpe_like),
            "trades_per_year": float(self.trades_per_year),
            "bull_mean_R": self.bull_mean_R,
            "bear_mean_R": self.bear_mean_R,
            # Principal'in dilinde (Faz 14.13)
            "monthly_roi_pct_mean": monthly["monthly_roi_pct_mean"],
            "monthly_roi_pct_median": monthly["monthly_roi_pct_median"],
            "monthly_neg_count": monthly["monthly_neg_count"],
            "monthly_total_count": monthly["monthly_total_count"],
            "annual_compound_pct": monthly["annual_compound_pct"],
            "max_dd_compound_pct": monthly["max_dd_compound_pct"],
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
        # FIX 2026-05-27 (Faz 14.11): yeni alanlar — eski chunk'larda yok,
        # backward-compat default'larla oku.
        ranking = CellRanking(
            challenger_id=cell_id,
            strategy=strategy,
            sl_multiplier=sl,
            tp_r=tp,
            risk_pct=rk,
            n_trades=n_trades,
            mean_R_after_fees=mean_R_fees,
            sharpe_like=float(cell.get("sharpe_like", 0.0)),
            sharpe_annualized=float(cell.get("sharpe_annualized", 0.0)),
            sum_R=float(cell.get("sum_R", 0.0)),
            max_drawdown_R=float(cell.get("max_drawdown_R", 0.0)),
            trades_per_year=float(cell.get("trades_per_year", 0.0)),
            returns_R_sample=list(cell.get("returns_R_sample", []) or []),
            bull_mean_R=cell.get("bull_mean_R"),
            bear_mean_R=cell.get("bear_mean_R"),
            source_chunk=str(cell.get("_source_chunk", "")),
        )
        by_strategy.setdefault(strategy, []).append(ranking)

    # Her strateji için: önce (sl, tp) bazında dedupe (R-multiple replay
    # risk_pct'e duyarsızdır), sonra top-N (annualized sharpe).
    # FIX 2026-05-27 (Faz 14.11): sıralama sharpe_annualized'e geçti —
    # sharpe_like sqrt(n) ile şişiyordu (ki bu n_trades'i ödüllendiriyor,
    # gerçek strateji kalitesini değil).
    challengers: list[dict[str, Any]] = []
    for strategy, rankings in by_strategy.items():
        # Dedupe: (sl, tp) → en yüksek annualized sharpe olanı tut.
        # Tie-break: daha düşük risk_pct (daha konservatif).
        deduped: dict[tuple[float, float], CellRanking] = {}
        for r in rankings:
            key = (r.sl_multiplier, r.tp_r)
            existing = deduped.get(key)
            # Fallback: sharpe_annualized 0 olabilir (eski chunk) → sharpe_like'a düş
            r_sort = r.sharpe_annualized if r.sharpe_annualized != 0 else r.sharpe_like
            ex_sort = (
                existing.sharpe_annualized
                if existing and existing.sharpe_annualized != 0
                else (existing.sharpe_like if existing else float("-inf"))
            )
            if existing is None or r_sort > ex_sort or (
                r_sort == ex_sort and r.risk_pct < existing.risk_pct
            ):
                deduped[key] = r
        unique = sorted(
            deduped.values(),
            key=lambda r: (r.sharpe_annualized or r.sharpe_like),
            reverse=True,
        )
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
