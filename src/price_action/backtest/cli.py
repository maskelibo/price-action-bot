"""Backtest CLI — `pa-backtest run --strategy classic_pa --years 3 --universe all_liquid`.

Walk-forward `--wf` flag.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import typer

from price_action.logging_config import logger
from price_action.settings import get_settings

app = typer.Typer(help="Price Action — Backtest CLI")


@app.command()
def run(
    strategy: str = typer.Option("classic_pa", help="Strateji adı (configs/strategies/<name>.yaml)"),
    years: int = typer.Option(3, help="Geriye dönük backtest yılı"),
    universe: str = typer.Option("all_liquid", help="Universe modu (config'den okunur)"),
    timeframe: str = typer.Option("1d", help="Karar timeframe'i"),
    fees_taker: float = typer.Option(0.00075),
    fees_maker: float = typer.Option(-0.0001),
    slippage_bps: float = typer.Option(5.0),
    initial_capital: float = typer.Option(10_000.0),
    wf: bool = typer.Option(False, "--wf", help="Walk-forward modu"),
    out_dir: Optional[Path] = typer.Option(None, help="Rapor çıktı dizini (opsiyonel)"),
) -> None:
    """Backtest çalıştır."""
    settings = get_settings()
    cfg_path = settings.configs_dir / "strategies" / f"{strategy}.yaml"
    if not cfg_path.exists():
        typer.echo(f"Strateji manifesti bulunamadı: {cfg_path}", err=True)
        raise typer.Exit(code=2)

    from price_action.strategies.classic_pa import ClassicPriceActionStrategy
    from price_action.strategies.base import Strategy

    strat = Strategy.load_from_yaml(cfg_path)
    if not isinstance(strat, ClassicPriceActionStrategy):
        typer.echo(f"Beklenen strateji türü: ClassicPriceActionStrategy, alındı {type(strat)}")
        raise typer.Exit(code=2)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365 * years)
    universe_list = _resolve_universe(universe)

    out_dir = out_dir or settings.reports_dir / "backtest" / strategy
    out_dir.mkdir(parents=True, exist_ok=True)

    if wf:
        from price_action.backtest.walk_forward import WalkForward

        wf_runner = WalkForward()
        result = wf_runner.run(
            cfg_path,
            universe=universe_list,
            start=start,
            end=end,
        )
        outp = out_dir / "wf_result.json"
        outp.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        typer.echo(f"Walk-forward done. Folds={result.n_folds}, output={outp}")
        return

    # Standart backtest
    from price_action.backtest.engine import BacktestEngine
    from price_action.backtest.report import render_report
    from price_action.risk.sizing import RiskOfficer

    risk_yaml = settings.configs_dir / "risk.yaml"
    risk_officer = RiskOfficer.from_yaml(risk_yaml) if risk_yaml.exists() else None
    engine = BacktestEngine(risk_officer=risk_officer)

    result = engine.run(
        strat,
        universe_list,
        start=start,
        end=end,
        fees={"taker": fees_taker, "maker": fees_maker},
        slippage_bps=slippage_bps,
        initial_capital=initial_capital,
        timeframe=timeframe,
    )
    outp = out_dir / f"report_{result.manifest.composite}.html"
    render_report(result, outp)
    typer.echo(f"Backtest done. Trades={result.n_trades}. Report={outp}")


def _resolve_universe(mode: str) -> list[str]:
    """Universe.yaml'dan sembol listesi çek (manuel modda fallback)."""
    settings = get_settings()
    sym_yaml = settings.configs_dir / "symbols.yaml"
    if not sym_yaml.exists():
        return ["BTC/USDT", "ETH/USDT"]
    import yaml

    raw = yaml.safe_load(sym_yaml.read_text(encoding="utf-8")) or {}
    universe = raw.get("universe", {})
    manual_list = universe.get("manual_list", []) or []
    # Data layer build_universe'dan çekmek ideal; CLI fallback için manual_list iyidir.
    return list(manual_list) if manual_list else ["BTC/USDT", "ETH/USDT"]


def main() -> None:
    app()


if __name__ == "__main__":
    main()
