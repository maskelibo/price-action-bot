"""Binance REST 418 cooldown guard ve aynı-bar state reuse regresyonları."""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path

import ccxt
import pytest

from scripts import futures_trade_daily as ftd


class _FakeExchange:
    def __init__(self, ban_until_ms: int) -> None:
        self.calls = 0
        self.ban_until_ms = ban_until_ms

    def request(
        self,
        path,
        api="public",
        method="GET",
        params=None,
        headers=None,
        body=None,
        config=None,
    ):
        del path, api, method, params, headers, body, config
        self.calls += 1
        raise RuntimeError(
            "binance 418 code=-1003 Way too many requests; "
            f"IP banned until {self.ban_until_ms}"
        )


class _PassiveExchange:
    def __init__(self) -> None:
        self.calls = 0

    def request(
        self,
        path,
        api="public",
        method="GET",
        params=None,
        headers=None,
        body=None,
        config=None,
    ):
        del path, api, method, params, headers, body, config
        self.calls += 1
        return {"ok": True}


def _request_from_fresh_process(state_path, lock_path, now_ms, result_queue) -> None:
    """Spawn target: emulate a new bot process with empty local cooldown state."""
    from scripts import futures_trade_daily as child_ftd

    child_ftd._BINANCE_BAN_STATE_PATH = Path(state_path)
    child_ftd._BINANCE_BAN_STATE_LOCK_PATH = Path(lock_path)
    child_ftd._BINANCE_BAN_UNTIL_MS = 0
    child_ftd.time.time = lambda: now_ms / 1000
    exchange = child_ftd._install_binance_cooldown_guard(_PassiveExchange())
    try:
        exchange.request("positions")
    except ccxt.RateLimitExceeded:
        result_queue.put(
            {
                "blocked": True,
                "calls": exchange.calls,
                "ban_until": child_ftd.get_binance_ban_until(),
            }
        )
    except Exception as exc:
        result_queue.put(
            {
                "blocked": False,
                "calls": exchange.calls,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    else:
        result_queue.put({"blocked": False, "calls": exchange.calls, "error": "not blocked"})


@pytest.fixture(autouse=True)
def _isolated_shared_ban_state(tmp_path, monkeypatch):
    state_dir = tmp_path / "runtime" / "data" / "state"
    monkeypatch.setattr(
        ftd,
        "_BINANCE_BAN_STATE_PATH",
        state_dir / "binance_rest_ban_until_ms",
    )
    monkeypatch.setattr(
        ftd,
        "_BINANCE_BAN_STATE_LOCK_PATH",
        state_dir / "binance_rest_ban_until_ms.lock",
    )
    monkeypatch.setattr(ftd, "_BINANCE_BAN_UNTIL_MS", 0)


def test_extract_binance_ban_until_ms() -> None:
    assert ftd._extract_binance_ban_until_ms("banned until 1783724879079") == 1783724879079
    assert ftd._extract_binance_ban_until_ms("ordinary timeout") is None


@pytest.mark.parametrize("value", ["1", "true", "YES", " on "])
def test_private_exchange_process_gate_blocks_before_credentials_or_client(
    monkeypatch, value
) -> None:
    monkeypatch.setenv("PA_DISABLE_PRIVATE_EXCHANGE_API", value)
    monkeypatch.delenv("BINANCE_FUTURES_TESTNET_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_FUTURES_TESTNET_API_SECRET", raising=False)

    def _client_must_not_be_constructed(*_args, **_kwargs):
        raise AssertionError("ccxt client construction crossed the process gate")

    monkeypatch.setattr(ftd.ccxt, "binance", _client_must_not_be_constructed)

    with pytest.raises(ftd.PrivateExchangeAccessDisabledError, match="disabled"):
        ftd.get_futures_exchange()


def test_ceo_launch_surface_enables_private_exchange_process_gate() -> None:
    root = Path(__file__).resolve().parents[2]
    wrapper = (root / "ops" / "launchd" / "run_ceo.sh").read_text(encoding="utf-8")
    plist = (root / "ops" / "launchd" / "com.priceaction.ceo.plist").read_text(
        encoding="utf-8"
    )

    assert 'export PA_DISABLE_PRIVATE_EXCHANGE_API="1"' in wrapper
    assert "<key>PA_DISABLE_PRIVATE_EXCHANGE_API</key>" in plist
    assert "<string>1</string>" in plist


def test_guard_blocks_followup_http_until_ban_expires(monkeypatch) -> None:
    now_ms = 2_000_000_000_000
    ban_until_ms = now_ms + 60_000
    monkeypatch.setattr(ftd.time, "time", lambda: now_ms / 1000)
    monkeypatch.setattr(ftd, "_BINANCE_BAN_UNTIL_MS", 0)
    exchange = ftd._install_binance_cooldown_guard(_FakeExchange(ban_until_ms))

    with pytest.raises(RuntimeError, match="banned until"):
        exchange.request("account")
    assert exchange.calls == 1

    with pytest.raises(ccxt.RateLimitExceeded, match="local cooldown"):
        exchange.request("positions")
    assert exchange.calls == 1  # ikinci istek ağa çıkmadı
    assert ftd._binance_cooldown_remaining_seconds(now_ms=now_ms) == 60.0


def test_shared_state_write_failure_still_blocks_followup_in_process(
    monkeypatch, caplog
) -> None:
    now_ms = 2_000_000_000_000
    ban_until_ms = now_ms + 60_000
    monkeypatch.setattr(ftd.time, "time", lambda: now_ms / 1000)
    monkeypatch.setattr(
        ftd,
        "_write_binance_ban_state_unlocked",
        lambda _until: (_ for _ in ()).throw(OSError("disk full")),
    )
    exchange = ftd._install_binance_cooldown_guard(_FakeExchange(ban_until_ms))

    with pytest.raises(RuntimeError, match="banned until"):
        exchange.request("account")
    assert ban_until_ms == ftd._BINANCE_BAN_UNTIL_MS
    with pytest.raises(ccxt.RateLimitExceeded, match="local cooldown"):
        exchange.request("positions")
    assert exchange.calls == 1
    assert "process-local ban remains active" in caplog.text


def test_shared_guard_blocks_second_process_instance(monkeypatch) -> None:
    """A'nın 418 state'i, ayrı bir B prosesinin HTTP request'ini de durdurur."""
    now_ms = 2_000_000_000_000
    ban_until_ms = now_ms + 90_000
    monkeypatch.setattr(ftd.time, "time", lambda: now_ms / 1000)

    exchange_a = ftd._install_binance_cooldown_guard(_FakeExchange(ban_until_ms))
    with pytest.raises(RuntimeError, match="banned until"):
        exchange_a.request("account")
    assert exchange_a.calls == 1
    assert ftd._BINANCE_BAN_STATE_PATH.read_text(encoding="ascii").strip() == str(
        ban_until_ms
    )

    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()
    process = ctx.Process(
        target=_request_from_fresh_process,
        args=(
            str(ftd._BINANCE_BAN_STATE_PATH),
            str(ftd._BINANCE_BAN_STATE_LOCK_PATH),
            now_ms,
            result_queue,
        ),
    )
    process.start()
    process.join(timeout=15)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        pytest.fail("fresh-process cooldown check timed out")
    assert process.exitcode == 0
    child_result = result_queue.get(timeout=5)
    assert child_result == {
        "blocked": True,
        "calls": 0,
        "ban_until": ban_until_ms / 1000.0,
    }
    assert ftd.get_binance_ban_until() == ban_until_ms / 1000.0


def test_shared_ban_deadline_is_monotonic_max(monkeypatch) -> None:
    now_ms = 2_000_000_000_000
    longer_ban_ms = now_ms + 120_000
    monkeypatch.setattr(ftd.time, "time", lambda: now_ms / 1000)

    assert ftd._record_binance_ban_until_ms(longer_ban_ms) == longer_ban_ms
    monkeypatch.setattr(ftd, "_BINANCE_BAN_UNTIL_MS", 0)
    assert ftd._record_binance_ban_until_ms(now_ms + 30_000) == longer_ban_ms
    assert ftd._BINANCE_BAN_STATE_PATH.read_text(encoding="ascii").strip() == str(
        longer_ban_ms
    )


def test_expired_shared_state_is_ignored_and_removed(monkeypatch) -> None:
    now_ms = 2_000_000_000_000
    monkeypatch.setattr(ftd.time, "time", lambda: now_ms / 1000)
    ftd._BINANCE_BAN_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ftd._BINANCE_BAN_STATE_PATH.write_text(str(now_ms - 1), encoding="ascii")

    exchange = ftd._install_binance_cooldown_guard(_PassiveExchange())
    assert exchange.request("time") == {"ok": True}
    assert exchange.calls == 1
    assert not ftd._BINANCE_BAN_STATE_PATH.exists()
    assert ftd._BINANCE_BAN_STATE_LOCK_PATH.exists()
    assert ftd.get_binance_ban_until() == 0.0


def test_invalid_shared_state_blocks_network_fail_closed(monkeypatch) -> None:
    now_ms = 2_000_000_000_000
    monkeypatch.setattr(ftd.time, "time", lambda: now_ms / 1000)
    ftd._BINANCE_BAN_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ftd._BINANCE_BAN_STATE_PATH.write_text("not-an-epoch\n", encoding="ascii")
    exchange = ftd._install_binance_cooldown_guard(_PassiveExchange())

    with pytest.raises(ValueError, match="invalid Binance ban state"):
        exchange.request("account")

    assert exchange.calls == 0
    assert ftd._BINANCE_BAN_STATE_PATH.read_text(encoding="ascii") == "not-an-epoch\n"


@pytest.mark.parametrize("alias", ["state", "lock"])
def test_symlinked_shared_ban_metadata_blocks_network(tmp_path, monkeypatch, alias) -> None:
    now_ms = 2_000_000_000_000
    monkeypatch.setattr(ftd.time, "time", lambda: now_ms / 1000)
    state_dir = ftd._BINANCE_BAN_STATE_PATH.parent
    state_dir.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / f"outside-{alias}"
    outside.write_text(str(now_ms + 60_000), encoding="ascii")
    target = (
        ftd._BINANCE_BAN_STATE_PATH
        if alias == "state"
        else ftd._BINANCE_BAN_STATE_LOCK_PATH
    )
    target.symlink_to(outside)
    exchange = ftd._install_binance_cooldown_guard(_PassiveExchange())

    with pytest.raises(ValueError, match="unsafe Binance ban"):
        exchange.request("positions")

    assert exchange.calls == 0
    assert outside.read_text(encoding="ascii") == str(now_ms + 60_000)


@pytest.mark.parametrize("alias", ["state", "lock"])
def test_hardlinked_shared_ban_metadata_blocks_network(tmp_path, monkeypatch, alias) -> None:
    now_ms = 2_000_000_000_000
    monkeypatch.setattr(ftd.time, "time", lambda: now_ms / 1000)
    state_dir = ftd._BINANCE_BAN_STATE_PATH.parent
    state_dir.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / f"outside-hardlink-{alias}"
    outside.write_text(str(now_ms + 60_000), encoding="ascii")
    target = (
        ftd._BINANCE_BAN_STATE_PATH
        if alias == "state"
        else ftd._BINANCE_BAN_STATE_LOCK_PATH
    )
    os.link(outside, target)
    exchange = ftd._install_binance_cooldown_guard(_PassiveExchange())

    with pytest.raises(ValueError, match="hard-linked Binance ban"):
        exchange.request("positions")

    assert exchange.calls == 0


def test_daemon_reuses_position_state_for_breaker_and_equity() -> None:
    source = (Path(__file__).resolve().parents[2] / "scripts" / "futures_daemon.py").read_text(
        encoding="utf-8"
    )
    assert "_pos_check_state = position_check()" in source
    assert "_g19_state = _pos_check_state" in source
