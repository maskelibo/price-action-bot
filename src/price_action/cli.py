"""`pa` CLI — typer tabanlı.

Komutlar mümkün olduğunca diğer paketlerin `main` fonksiyonlarını çağırır;
saf orchestration. Diğer paketler henüz yoksa anlamlı hata mesajı verir.
"""
from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from price_action import __version__
from price_action.logging_config import logger
from price_action.settings import ensure_dirs, get_settings

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Price Action — otonom trading şirketi CLI.",
)
console = Console()

# Sub-apps
universe_app = typer.Typer(help="Sembol evreni komutları.")
backtest_app = typer.Typer(help="Backtest komutları.")
rag_app = typer.Typer(help="RAG ingest / refresh.")
ceo_app = typer.Typer(help="CEO orchestrator komutları.")
ops_app = typer.Typer(help="Operasyonel komutlar.")
app.add_typer(universe_app, name="universe")
app.add_typer(backtest_app, name="backtest")
app.add_typer(rag_app, name="rag")
app.add_typer(ceo_app, name="ceo")
app.add_typer(ops_app, name="ops")


# =====================================================================
# Init / status
# =====================================================================

@app.command()
def init() -> None:
    """Klasörleri oluştur, init.sql ve default config kontrolü yap."""
    s = get_settings()
    ensure_dirs()
    needed = [
        s.duckdb_path.parent,
        s.parquet_root,
        s.chroma_path,
        s.reports_dir,
        s.logs_dir,
        s.memory_dir,
        s.knowledge_dir,
        s.reports_dir / "ceo",
        s.reports_dir / "analytics",
        s.reports_dir / "postmortems",
        s.reports_dir / "ops",
    ]
    for p in needed:
        p.mkdir(parents=True, exist_ok=True)
    init_sql = Path(__file__).resolve().parents[2] / "scripts" / "db" / "init.sql"
    risk_yaml = s.configs_dir / "risk.yaml"
    classic = s.configs_dir / "strategies" / "classic_pa.yaml"

    table = Table(title="pa init")
    table.add_column("kontrol")
    table.add_column("durum")
    table.add_row("klasörler", "ok")
    table.add_row("init.sql", "ok" if init_sql.exists() else "EKSİK")
    table.add_row("risk.yaml", "ok" if risk_yaml.exists() else "EKSİK")
    table.add_row("classic_pa.yaml", "ok" if classic.exists() else "EKSİK")
    console.print(table)


@app.command()
def status() -> None:
    """Açık pozisyon, son brief, breaker durumu özet."""
    s = get_settings()
    table = Table(title="pa status")
    table.add_column("alan")
    table.add_column("değer")
    table.add_row("version", __version__)
    table.add_row("mode", s.pa_run_mode)

    # Halt state
    try:
        from price_action.api.server import is_halted

        table.add_row("halted", "EVET" if is_halted() else "hayır")
    except Exception:
        table.add_row("halted", "?")

    # Açık pozisyonlar
    n_open = "?"
    try:
        from price_action.analytics.journal import Journal

        df = Journal().query_open_positions()
        n_open = str(len(df))
    except Exception as exc:
        logger.debug("status.no_journal", extra={"err": str(exc)[:120]})
    table.add_row("open positions", n_open)

    # Son CEO brief
    last_ceo = "yok"
    ceo_dir = s.reports_dir / "ceo"
    if ceo_dir.exists():
        files = sorted(ceo_dir.glob("*.md"), reverse=True)
        if files:
            last_ceo = files[0].name
    table.add_row("last ceo brief", last_ceo)

    console.print(table)


@app.command()
def version() -> None:
    """Versiyon bilgisi."""
    console.print(f"price-action {__version__}")


# =====================================================================
# Ingest
# =====================================================================

@app.command()
def ingest(
    venue: str = typer.Option("binance", "--venue", help="Borsa: binance | bybit"),
    tf: str = typer.Option("1d", "--tf", help="Timeframe (örn 1d, 1w)"),
    years: int = typer.Option(3, "--years", help="Geriye kaç yıl çekilecek"),
) -> None:
    """`data.ingest_ccxt.main` çağrı sarıcısı."""
    _call_external(
        "price_action.data.ingest_ccxt",
        "main",
        venue=venue,
        tf=tf,
        years=years,
        op="ingest",
    )


# =====================================================================
# Universe
# =====================================================================

@universe_app.command("build")
def universe_build() -> None:
    """Sembol evreni kur (data.universe.main)."""
    _call_external("price_action.data.universe", "main", op="universe build")


# =====================================================================
# Backtest
# =====================================================================

@backtest_app.command("run")
def backtest_run(
    strategy: str = typer.Option("classic_pa", "--strategy"),
    years: int = typer.Option(3, "--years"),
) -> None:
    """`backtest.cli.main` çağır."""
    _call_external(
        "price_action.backtest.cli",
        "main",
        strategy=strategy,
        years=years,
        op="backtest",
    )


# =====================================================================
# RAG
# =====================================================================

@rag_app.command("ingest")
def rag_ingest() -> None:
    _call_external("price_action.rag.ingest", "main", op="rag ingest")


@rag_app.command("stats")
def rag_stats() -> None:
    """RAG corpus istatistiklerini göster."""
    from price_action.rag.ingest import stats as _stats
    _stats()


@rag_app.command("query")
def rag_query(
    text: str = typer.Argument(..., help="Sorgu metni"),
    k: int = typer.Option(8, "--k", help="Döndürülecek hit sayısı"),
    source_type: str = typer.Option(None, "--source-type", help="Filtre: book | rss | web | youtube"),
    topic: str = typer.Option(None, "--topic", help="topic_tag filtresi"),
    full: bool = typer.Option(False, "--full/--no-full", help="Tam chunk metnini bas"),
) -> None:
    """RAG corpus'unu interaktif olarak sorgula."""
    from price_action.rag.ingest import format_query_output, run_query
    hits = run_query(text, k=k, source_type=source_type, topic=topic)
    output = format_query_output(
        text, hits, k=k, source_type=source_type, topic=topic, full=full
    )
    console.print(output)


# =====================================================================
# CEO
# =====================================================================

@ceo_app.command("daily")
def ceo_daily() -> None:
    """CEO daily brief tetikle."""
    _call_external("price_action.orchestrator.ceo_loop", "run_daily", op="ceo daily")


# =====================================================================
# Ops
# =====================================================================

@ops_app.command("halt")
def ops_halt(reason: str = typer.Option("manual", "--reason")) -> None:
    """Kill-switch — yeni emirleri durdur."""
    from price_action.api.server import _write_halt_state

    _write_halt_state(
        {
            "halted": True,
            "reason": reason,
            "ts": datetime.now(timezone.utc).isoformat(),
            "by": "cli",
        }
    )
    console.print(f"[bold red]HALTED[/bold red] — reason={reason}")


@ops_app.command("resume")
def ops_resume() -> None:
    """Kill-switch'i geri al."""
    from price_action.api.server import _write_halt_state

    _write_halt_state(
        {
            "halted": False,
            "reason": None,
            "ts": datetime.now(timezone.utc).isoformat(),
            "by": "cli",
        }
    )
    console.print("[bold green]RESUMED[/bold green]")


# =====================================================================
# Yardımcılar
# =====================================================================

def _call_external(module_name: str, func_name: str, *, op: str, **kwargs) -> None:
    """Dış paket modülünü dinamik import et + main çağır.

    Eksikse renkli açıklama bas, exit-1.
    """
    try:
        mod = importlib.import_module(module_name)
    except ImportError as exc:
        console.print(
            f"[yellow]'{module_name}' modülü henüz hazır değil[/yellow] "
            f"(op={op}). Detay: {exc}"
        )
        raise typer.Exit(code=2) from exc
    fn = getattr(mod, func_name, None)
    if fn is None:
        console.print(f"[yellow]{module_name}.{func_name} bulunamadı[/yellow]")
        raise typer.Exit(code=2)
    try:
        fn(**kwargs) if kwargs else fn()
    except TypeError:
        # Aldığı parametre seti farklıysa kwargs'i sil
        fn()


def main(argv: Optional[list[str]] = None) -> None:
    """`[project.scripts]` için entry point."""
    app(args=argv)


if __name__ == "__main__":  # pragma: no cover
    main()
