"""Yardımcı script — classic_pa stratejisini çalıştır + HTML raporu üret.

`backtest.cli.main` modülü hazır olmadığında anlamlı bir mesaj gösterir.
HTML raporu olarak basit bir KPI snapshot dökümü üretir (örnek/synthetic data
ile çalışacak şekilde defansif).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run classic_pa backtest")
    parser.add_argument("--strategy", default="classic_pa")
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument(
        "--out",
        default="reports/backtests/classic_pa_latest.html",
        help="HTML raporu çıktı yolu",
    )
    args = parser.parse_args()

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Backtest engine henüz bu agent'ın işi değilse external'i çağır.
    try:
        from price_action.backtest.cli import main as bt_main  # type: ignore[import-not-found]

        bt_main(strategy=args.strategy, years=args.years, out=str(out_path))
        print(f"backtest tamamlandı → {out_path}")
        return 0
    except ImportError:
        # Engine hazır değil — synthetic placeholder rapor üret.
        from price_action.analytics.kpi import compute_kpis
        from scripts.seed_data import generate_trades

        trades = generate_trades(n=120)
        kpi = compute_kpis(trades)
        out_path.write_text(_render_placeholder(args.strategy, kpi), encoding="utf-8")
        print(f"engine yok — placeholder rapor üretildi: {out_path}", file=sys.stderr)
        return 0


def _render_placeholder(strategy: str, kpi: dict) -> str:
    rows = "".join(f"<tr><td>{k}</td><td>{v:.4f}</td></tr>" for k, v in kpi.items())
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Backtest — {strategy}</title>
<style>body{{font-family:sans-serif;margin:30px;}}
table{{border-collapse:collapse}} td,th{{padding:4px 10px;border-bottom:1px solid #eee}}
</style></head>
<body>
<h1>Backtest — {strategy} (placeholder)</h1>
<p>Engine henüz hazır değil; synthetic trade'lerle KPI snapshot.</p>
<table><tr><th>KPI</th><th>Değer</th></tr>{rows}</table>
</body></html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
