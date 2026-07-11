"""Bot Monitor Agent — Faz 6 tests.

Coverage:
- DuckDB journal schema sanity (futures_trades_closed)
- _calc_drawdown determinism
- _calc_attribution per (strategy, sym)
- Kill criteria threshold breach → WARN doc
- No breach → no alert
- WARN → 24h hold → PAUSE flow

No live LLM call — `PA_LLM_DRY_RUN=true`.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from price_action.agents.bot_monitor import (
    BotMonitorAgent,
    _calc_attribution,
    _calc_drawdown,
    _count_consecutive_losses,
    _evaluate_threshold_breach,
)
from price_action.memory import MemoryStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bot_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """İzole ROOT_DIR; reports/ memory/ configs/ data/ alt dizinleri kurar.

    Canonical agent rules dir (agents/) tmp_path altında oluşturulur; minimal
    bir bot_monitor.md yazılır (system prompt'un load_rules için).
    """
    root = tmp_path
    (root / "reports" / "bot_monitor").mkdir(parents=True)
    (root / "memory" / "bot_monitor").mkdir(parents=True)
    (root / "memory" / "shared" / "facts").mkdir(parents=True)
    (root / "memory" / "shared" / "lessons").mkdir(parents=True)
    (root / "memory" / "protocol").mkdir(parents=True)
    (root / "configs").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    rules_dir = root / "agents"
    rules_dir.mkdir(parents=True)
    (rules_dir / "bot_monitor.md").write_text(
        "---\nname: bot_monitor\n---\n# Bot Monitor rules\n", encoding="utf-8"
    )
    (root / "memory" / "bot_monitor" / "identity.md").write_text("# id\n", encoding="utf-8")
    (root / "memory" / "bot_monitor" / "know_how.md").write_text("# kh\n", encoding="utf-8")
    (root / "memory" / "bot_monitor" / "learning.md").write_text("# l\n", encoding="utf-8")

    # Default kill criteria yaml — alt testlerde override edebiliriz
    yaml_text = """
bots:
  testbot_a:
    journal: data/testbot_a.duckdb
    kill_thresholds:
      cum_loss_7d_pct: 0.10
      cum_loss_14d_pct: 0.15
      max_drawdown_pct: 0.25
      consecutive_losses: 7
  testbot_b:
    journal: data/testbot_b.duckdb
    kill_thresholds:
      cum_loss_7d_pct: 0.08
      cum_loss_14d_pct: 0.12
      max_drawdown_pct: 0.20
      consecutive_losses: 5
defaults:
  warn_first: true
  warn_hold_hours: 24
  auto_pause: false
  alert_channel: telegram
"""
    (root / "configs" / "bot_kill_criteria.yaml").write_text(yaml_text, encoding="utf-8")

    monkeypatch.setenv("PA_LLM_DRY_RUN", "true")
    from price_action import settings as _settings_mod
    _settings_mod.get_settings.cache_clear()
    monkeypatch.setattr(_settings_mod, "ROOT_DIR", root)
    # Agent rules path = ROOT/agents (settings.agents_rules_dir property)
    return {"root": root, "rules_dir": rules_dir}


@pytest.fixture
def agent(bot_env: dict) -> BotMonitorAgent:
    store = MemoryStore(base_dir=bot_env["root"] / "memory")
    return BotMonitorAgent(memory_store=store)


def _seed_equity_snapshot(path: Path, *, ts: datetime, wallet: float, notes: str) -> None:
    duckdb = pytest.importorskip("duckdb")
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """CREATE TABLE futures_equity_snapshots (
                   snapshot_id VARCHAR PRIMARY KEY,
                   ts TIMESTAMP,
                   wallet_balance DOUBLE,
                   notes VARCHAR
               )"""
        )
        connection.execute(
            "INSERT INTO futures_equity_snapshots VALUES (?, ?, ?, ?)",
            ["snapshot-1", ts.replace(tzinfo=None), wallet, notes],
        )


def test_live_equity_uses_fresh_snapshot_without_exchange_constructor(
    agent: BotMonitorAgent,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import futures_trade_daily

    now = datetime(2026, 7, 11, 12, 30, tzinfo=UTC)
    journal = tmp_path / "journal.duckdb"
    _seed_equity_snapshot(
        journal,
        ts=now - timedelta(minutes=15),
        wallet=4924.07,
        notes="manual_exchange_truth",
    )
    agent._reset_live_equity_cache()
    monkeypatch.setenv("BINANCE_FUTURES_TESTNET_API_KEY", "test-key")
    monkeypatch.setattr(
        futures_trade_daily,
        "get_futures_exchange",
        lambda: (_ for _ in ()).throw(AssertionError("exchange constructor must not run")),
    )

    result = agent._fetch_live_equity(4963.0, journal_path=journal, now=now)

    assert result == pytest.approx(4924.07)


def test_live_equity_ttl_cache_allows_only_one_api_fetch_for_multiple_bots(
    agent: BotMonitorAgent,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import futures_trade_daily

    calls = {"constructor": 0, "fetch": 0}

    def fake_constructor():
        calls["constructor"] += 1
        return object()

    def fake_fetch(_exchange, **_kwargs):
        calls["fetch"] += 1
        return {"wallet_balance": 4875.5}

    agent._reset_live_equity_cache()
    monkeypatch.setenv("BINANCE_FUTURES_TESTNET_API_KEY", "test-key")
    monkeypatch.setattr(futures_trade_daily, "get_binance_ban_until", lambda: 0.0, raising=False)
    monkeypatch.setattr(futures_trade_daily, "get_futures_exchange", fake_constructor)
    monkeypatch.setattr(futures_trade_daily, "fetch_futures_state", fake_fetch)
    now = datetime(2026, 7, 11, 12, 30, tzinfo=UTC)

    first = agent._fetch_live_equity(
        4963.0,
        journal_path=tmp_path / "missing-a.duckdb",
        now=now,
    )
    second = agent._fetch_live_equity(
        10000.0,
        journal_path=tmp_path / "missing-b.duckdb",
        now=now + timedelta(minutes=1),
    )

    assert first == second == pytest.approx(4875.5)
    assert calls == {"constructor": 1, "fetch": 1}


def test_live_equity_shared_ban_skips_api_when_snapshot_missing(
    agent: BotMonitorAgent,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import futures_trade_daily

    now = datetime(2026, 7, 11, 12, 30, tzinfo=UTC)
    agent._reset_live_equity_cache()
    monkeypatch.setenv("BINANCE_FUTURES_TESTNET_API_KEY", "test-key")
    monkeypatch.setattr(
        futures_trade_daily,
        "get_binance_ban_until",
        lambda: now.timestamp() + 600,
        raising=False,
    )
    monkeypatch.setattr(
        futures_trade_daily,
        "get_futures_exchange",
        lambda: (_ for _ in ()).throw(AssertionError("API must be skipped during shared ban")),
    )

    result = agent._fetch_live_equity(
        4963.0,
        journal_path=tmp_path / "missing.duckdb",
        now=now,
    )

    assert result == 4963.0


def _seed_journal(path: Path, trades: list[dict[str, Any]]) -> None:
    """Test journal'a kapanmış trade ekle. duckdb yoksa skip."""
    duckdb = pytest.importorskip("duckdb")
    con = duckdb.connect(str(path))
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS futures_trades_closed (
                trade_id TEXT PRIMARY KEY,
                ts_open TIMESTAMP,
                ts_close TIMESTAMP,
                sym TEXT,
                side TEXT,
                strategy TEXT,
                entry_price DOUBLE,
                exit_price DOUBLE,
                qty DOUBLE,
                realized_pnl_usdt DOUBLE,
                realized_r DOUBLE,
                win BOOLEAN,
                close_reason TEXT
            )
            """
        )
        for t in trades:
            con.execute(
                """
                INSERT INTO futures_trades_closed VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    t["trade_id"], t["ts_open"], t["ts_close"], t["sym"], t["side"],
                    t["strategy"], t["entry_price"], t["exit_price"], t["qty"],
                    t["realized_pnl_usdt"], t["realized_r"], t["win"], t["close_reason"],
                ],
            )
        con.commit()
    finally:
        con.close()


def _mk_trade(
    *, trade_id: str, ts_close: datetime, pnl: float, sym: str = "BTCUSDT",
    strategy: str = "wide_stop", side: str = "long", r: float = 1.0,
) -> dict[str, Any]:
    return {
        "trade_id": trade_id,
        "ts_open": ts_close - timedelta(hours=1),
        "ts_close": ts_close,
        "sym": sym,
        "side": side,
        "strategy": strategy,
        "entry_price": 100.0,
        "exit_price": 100.0 + (pnl / 1.0),
        "qty": 1.0,
        "realized_pnl_usdt": pnl,
        "realized_r": r if pnl > 0 else -1.0,
        "win": pnl > 0,
        "close_reason": "tp" if pnl > 0 else "sl",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_journal_read_schema(bot_env: dict, agent: BotMonitorAgent) -> None:
    """DuckDB schema sağlam: tablo create + read trip."""
    pytest.importorskip("duckdb")
    journal = bot_env["root"] / "data" / "testbot_a.duckdb"
    now = datetime.now(UTC).replace(tzinfo=None)
    trades = [
        _mk_trade(trade_id="t1", ts_close=now - timedelta(days=1), pnl=10.0),
        _mk_trade(trade_id="t2", ts_close=now, pnl=-5.0),
    ]
    _seed_journal(journal, trades)

    assert agent._check_postgres_journal(journal) is True
    read = agent._read_trades(journal)
    assert len(read) == 2
    assert read[0]["trade_id"] == "t1"
    assert read[1]["realized_pnl_usdt"] == -5.0


def test_drawdown_calc_basic() -> None:
    """Bilinen equity serisi → bilinen DD."""
    # Peak 110, trough 80 → DD = 30/110 ≈ 0.2727
    eq = [100.0, 110.0, 100.0, 90.0, 80.0, 95.0]
    dd = _calc_drawdown(eq)
    assert dd == pytest.approx((110 - 80) / 110, rel=1e-6)

    # Monoton artan → DD = 0
    assert _calc_drawdown([10, 20, 30, 40]) == 0.0

    # Tek eleman / boş → 0
    assert _calc_drawdown([]) == 0.0
    assert _calc_drawdown([100.0]) == 0.0


def test_attribution_per_strategy() -> None:
    """Mock trades_df benzeri liste → (strategy, sym) bazında aggregation."""
    trades = [
        {"strategy": "A", "sym": "BTC", "realized_pnl_usdt": 10.0, "win": True},
        {"strategy": "A", "sym": "BTC", "realized_pnl_usdt": -5.0, "win": False},
        {"strategy": "B", "sym": "ETH", "realized_pnl_usdt": 7.0, "win": True},
        {"strategy": "A", "sym": "ETH", "realized_pnl_usdt": 3.0, "win": True},
    ]
    attr = _calc_attribution(trades)
    a_btc = attr[("A", "BTC")]
    assert a_btc["pnl"] == pytest.approx(5.0)
    assert a_btc["n"] == 2
    assert a_btc["wins"] == 1
    assert a_btc["win_rate"] == pytest.approx(0.5)
    assert attr[("B", "ETH")]["pnl"] == pytest.approx(7.0)
    assert attr[("A", "ETH")]["win_rate"] == pytest.approx(1.0)


def test_kill_criteria_threshold_breach(bot_env: dict, agent: BotMonitorAgent) -> None:
    """Eşik üstü cum_loss → WARN alert doc + state kaydı."""
    pytest.importorskip("duckdb")
    journal = bot_env["root"] / "data" / "testbot_a.duckdb"
    now = datetime.now(UTC).replace(tzinfo=None)
    # 7g cum_loss > %10: baseline=1.0 fallback → mutlak negatif PnL > 0.10
    # Yeterince büyük negatif PnL serisi
    trades = [
        _mk_trade(trade_id=f"t{i}", ts_close=now - timedelta(hours=12 * i), pnl=-50.0)
        for i in range(1, 8)
    ]
    _seed_journal(journal, trades)

    asyncio.run(agent.evaluate_kill_criteria())
    # State'te first_warn_at olmalı
    state = agent._load_warn_state()
    assert "testbot_a" in state
    assert state["testbot_a"]["first_warn_at"]
    # En az bir kill_criteria_alert doc yazılmış
    alerts = list((bot_env["root"] / "reports" / "bot_monitor").glob("*warn-testbot_a*.md"))
    assert len(alerts) >= 1
    content = alerts[0].read_text(encoding="utf-8")
    assert "WARN" in content
    assert "cum_loss_7d_pct" in content


def test_kill_criteria_no_breach(bot_env: dict, agent: BotMonitorAgent) -> None:
    """Eşik altı → ne WARN ne PAUSE doc."""
    pytest.importorskip("duckdb")
    journal_a = bot_env["root"] / "data" / "testbot_a.duckdb"
    journal_b = bot_env["root"] / "data" / "testbot_b.duckdb"
    now = datetime.now(UTC).replace(tzinfo=None)
    # Küçük pnl serisi — ne loss eşiği aşar ne ardışık 7 loss var
    trades_a = [
        _mk_trade(trade_id=f"a{i}", ts_close=now - timedelta(hours=6 * i), pnl=1.0)
        for i in range(1, 5)
    ]
    trades_b = [
        _mk_trade(trade_id=f"b{i}", ts_close=now - timedelta(hours=6 * i), pnl=0.5)
        for i in range(1, 5)
    ]
    _seed_journal(journal_a, trades_a)
    _seed_journal(journal_b, trades_b)

    asyncio.run(agent.evaluate_kill_criteria())
    state = agent._load_warn_state()
    assert state == {}
    # Sadece reports/bot_monitor/ altında WARN/PAUSE/CLEAR doc olmamalı
    warn_docs = list((bot_env["root"] / "reports" / "bot_monitor").glob("*warn-*.md"))
    pause_docs = list((bot_env["root"] / "reports" / "bot_monitor").glob("*pause-*.md"))
    assert len(warn_docs) == 0
    assert len(pause_docs) == 0


def test_warn_then_pause_flow(bot_env: dict, agent: BotMonitorAgent) -> None:
    """WARN doc → 24h sonra hala breach → PAUSE öneri doc."""
    pytest.importorskip("duckdb")
    journal = bot_env["root"] / "data" / "testbot_a.duckdb"
    now = datetime.now(UTC).replace(tzinfo=None)
    trades = [
        _mk_trade(trade_id=f"t{i}", ts_close=now - timedelta(hours=12 * i), pnl=-50.0)
        for i in range(1, 8)
    ]
    _seed_journal(journal, trades)

    # 1. Tur — WARN
    asyncio.run(agent.evaluate_kill_criteria())
    state = agent._load_warn_state()
    assert "testbot_a" in state

    # State'i 25 saat geriye al — sanki 25h önce WARN yazılmış
    state["testbot_a"]["first_warn_at"] = (
        datetime.now(UTC) - timedelta(hours=25)
    ).isoformat()
    agent._save_warn_state(state)

    # 2. Tur — PAUSE öneri çıkmalı
    asyncio.run(agent.evaluate_kill_criteria())
    pause_docs = list((bot_env["root"] / "reports" / "bot_monitor").glob("*pause-testbot_a*.md"))
    assert len(pause_docs) >= 1
    pause_content = pause_docs[0].read_text(encoding="utf-8")
    assert "PAUSE" in pause_content
    assert "Principal" in pause_content  # "Principal must manually stop" disclaimer
    # State'te last_pause_rec_at yazılmış olmalı
    state2 = agent._load_warn_state()
    assert state2["testbot_a"].get("last_pause_rec_at")


def test_consecutive_losses_counter() -> None:
    """En son trade'den geriye doğru ardışık loss sayısı."""
    base = datetime.now(UTC).replace(tzinfo=None)
    trades = [
        _mk_trade(trade_id="t1", ts_close=base, pnl=5.0),
        _mk_trade(trade_id="t2", ts_close=base + timedelta(minutes=1), pnl=-2.0),
        _mk_trade(trade_id="t3", ts_close=base + timedelta(minutes=2), pnl=-3.0),
        _mk_trade(trade_id="t4", ts_close=base + timedelta(minutes=3), pnl=-1.0),
    ]
    # Son 3 loss
    assert _count_consecutive_losses(trades) == 3
    # Tümü win
    trades_win = [
        _mk_trade(trade_id="w1", ts_close=base, pnl=1.0),
        _mk_trade(trade_id="w2", ts_close=base + timedelta(minutes=1), pnl=1.0),
    ]
    assert _count_consecutive_losses(trades_win) == 0
    # Boş liste
    assert _count_consecutive_losses([]) == 0


def test_evaluate_threshold_breach_helper() -> None:
    """Pure helper — cum_loss + DD + consec eşik aşımları."""
    out = _evaluate_threshold_breach(
        starting_equity=100.0,
        current_equity=85.0,
        equity_series=[100.0, 95.0, 85.0, 90.0],
        consecutive_losses=8,
        thresholds={
            "cum_loss_pct": 0.10,
            "max_drawdown_pct": 0.20,
            "consecutive_losses": 5,
        },
    )
    # cum_loss = 15/100 = 0.15 > 0.10 → breach
    # dd = (100-85)/100 = 0.15 < 0.20 → no breach
    # consec 8 >= 5 → breach
    assert any("cum_loss_pct" in b for b in out["breached"])
    assert any("consecutive_losses" in b for b in out["breached"])
    assert not any("max_drawdown_pct" in b for b in out["breached"])


def test_hourly_snapshot_writes_doc(bot_env: dict, agent: BotMonitorAgent) -> None:
    """Snapshot deterministik — LLM çağırmaz, dosya yazar."""
    pytest.importorskip("duckdb")
    journal = bot_env["root"] / "data" / "testbot_a.duckdb"
    now = datetime.now(UTC).replace(tzinfo=None)
    trades = [_mk_trade(trade_id="s1", ts_close=now, pnl=5.0)]
    _seed_journal(journal, trades)

    path = asyncio.run(agent.hourly_snapshot())
    assert path is not None
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "Bot Snapshot" in content
    assert "testbot_a" in content
    assert "testbot_b" in content  # config'te 2 bot var
    assert "Equity (cum realized)" in content
