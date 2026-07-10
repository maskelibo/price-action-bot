"""Pytest fixtures + global configuration.

Unit testler disposable bir runtime kullanır; dış ağ, canlı borsa ve işaretsiz
alt süreçler varsayılan olarak kapalıdır.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows runner
    fcntl = None  # type: ignore[assignment]

# Test modules import application code during collection. Establish the safety
# boundary before any of those imports can load the real .env or open runtime
# files under the repository. This is defense in depth for the test process,
# not an OS-level sandbox; marked child processes are still an explicit trust
# boundary and therefore receive the same sterile environment.
_ROOT = Path(__file__).resolve().parents[1]
_ORIGINAL_PROCESS_ENV = os.environ.copy()


def _truthy_at_start(name: str) -> bool:
    return _ORIGINAL_PROCESS_ENV.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


_RUN_INTEGRATION = _truthy_at_start("PA_RUN_INTEGRATION")
_RUN_NETWORK = _truthy_at_start("PA_RUN_NETWORK")
_RUN_OPS = _truthy_at_start("PA_RUN_OPS_TESTS")
_TEST_RUNTIME_ROOT = Path(tempfile.mkdtemp(prefix="price-action-pytest-")).resolve()

_SAFE_TEST_ENV = {
    "PA_TESTING": "1",
    "PYTHON_DOTENV_DISABLED": "1",
    "PA_RUNTIME_ROOT": str(_TEST_RUNTIME_ROOT),
    "DUCKDB_PATH": str(_TEST_RUNTIME_ROOT / "data" / "market.duckdb"),
    "INGEST_DUCKDB_PATH": str(_TEST_RUNTIME_ROOT / "data" / "market_ingest.duckdb"),
    "PARQUET_ROOT": str(_TEST_RUNTIME_ROOT / "data" / "parquet"),
    "CHROMA_PATH": str(_TEST_RUNTIME_ROOT / "knowledge" / "index"),
    "PA_RUN_MODE": "backtest",
    "PA_LIVE_CONFIRM": "",
    "PA_RUN_INTEGRATION": "1" if _RUN_INTEGRATION else "0",
    "PA_RUN_NETWORK": "1" if _RUN_NETWORK else "0",
    "PA_RUN_OPS_TESTS": "1" if _RUN_OPS else "0",
    "PA_RUN_LIVE": "0",
    "PA_LLM_DRY_RUN": "true",
    "PA_LLM_USE_CLI": "0",
    "PA_CEO_PUSH_TELEGRAM": "0",
    "PA_TELEGRAM_UNMUTE": "0",
    "PA_RESEARCH_AUTOPILOT": "0",
    "PA_YT_DRY_RUN": "1",
    "SWAP_EXECUTE": "0",
    "PA_DUCKDB_READ_ONLY": "false",
    "PA_LOG_QUIET": "1",
    "PA_DISABLE_FILE_LOG": "1",
    "LOG_LEVEL": "WARNING",
    "LOG_FORMAT": "plain",
    "BINANCE_TESTNET": "true",
    "BYBIT_TESTNET": "true",
}
_SECRET_ENV_KEYS = {
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BINANCE_TESTNET_API_KEY",
    "BINANCE_TESTNET_API_SECRET",
    "BINANCE_FUTURES_TESTNET_API_KEY",
    "BINANCE_FUTURES_TESTNET_API_SECRET",
    "BYBIT_API_KEY",
    "BYBIT_API_SECRET",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "YOUTUBE_API_KEY",
    "POSTGRES_PASSWORD",
    "DATABASE_URL",
    "POSTGRES_DSN",
    "PA_BINANCE_API_KEY",
    "PA_BINANCE_API_SECRET",
    "PA_BINANCE_SECRET",
    "PA_ADMIN_TOKEN",
    "PA_DASHBOARD_ADMIN_TOKEN",
}
_ENV_OVERRIDES = {**_SAFE_TEST_ENV, **{key: "" for key in _SECRET_ENV_KEYS}}
os.environ.update(_ENV_OVERRIDES)

# Repo içindeki operasyonel dizinler testler için salt-okunurdur. Normal test
# çıktıları (.pytest_cache, coverage, pycache) bu kümenin dışında kalır.
_REPO_PROTECTED_ROOTS = tuple(
    (_ROOT / name).resolve()
    for name in ("data", "logs", "reports", "memory", "knowledge", "configs")
)
_EXTERNAL_PROTECTED_ROOTS = tuple(
    Path(value).expanduser().resolve()
    for key in ("PA_RUNTIME_ROOT", "PARQUET_ROOT", "CHROMA_PATH")
    if (value := _ORIGINAL_PROCESS_ENV.get(key, "").strip())
)
_PROTECTED_ROOTS = _REPO_PROTECTED_ROOTS + _EXTERNAL_PROTECTED_ROOTS
_PROTECTED_FILES = {
    (_ROOT / ".env").resolve(),
    *(
        Path(value).expanduser().resolve()
        for key in ("DUCKDB_PATH", "INGEST_DUCKDB_PATH")
        if (value := _ORIGINAL_PROCESS_ENV.get(key, "").strip())
    ),
}
_NETWORK_ALLOWED = False
_OPS_READ_ALLOWED = False
_SUBPROCESS_ALLOWED = False
_SAFETY_ACTIVE = True
_SESSION_CLEANED = False

if any(
    root == _TEST_RUNTIME_ROOT or _TEST_RUNTIME_ROOT.is_relative_to(root)
    for root in _REPO_PROTECTED_ROOTS
):
    raise RuntimeError("Disposable pytest runtime must be outside repository operational paths")


def _resolved_path(
    value: object,
    dir_fd: object = None,
    *,
    follow_final: bool = True,
) -> Path | None:
    if not isinstance(value, str | bytes | os.PathLike):
        return None
    try:
        raw = os.fspath(value)
        path = Path(os.fsdecode(raw) if isinstance(raw, bytes) else raw)
        if not path.is_absolute():
            if isinstance(dir_fd, int) and dir_fd >= 0:
                base = _dir_fd_path(dir_fd)
                if base is None:
                    return None
                path = base / path
            else:
                path = Path.cwd() / path
        if follow_final:
            return path.resolve(strict=False)
        return path.parent.resolve(strict=False) / path.name
    except (OSError, TypeError, ValueError):
        return None


def _dir_fd_path(dir_fd: int) -> Path | None:
    for link in (f"/proc/self/fd/{dir_fd}", f"/dev/fd/{dir_fd}"):
        try:
            return Path(os.readlink(link))
        except OSError:
            pass
    if fcntl is not None and hasattr(fcntl, "F_GETPATH"):
        try:
            raw = fcntl.fcntl(dir_fd, fcntl.F_GETPATH, b"\0" * 1024)
            return Path(os.fsdecode(raw.split(b"\0", 1)[0]))
        except OSError:
            pass
    return None


def _is_protected_path(
    value: object,
    dir_fd: object = None,
    *,
    follow_final: bool = True,
) -> bool:
    path = _resolved_path(value, dir_fd, follow_final=follow_final)
    if path is None:
        return False
    if path == _TEST_RUNTIME_ROOT or path.is_relative_to(_TEST_RUNTIME_ROOT):
        return False
    if path in _PROTECTED_FILES:
        return True
    for protected_file in _PROTECTED_FILES:
        try:
            if path.exists() and protected_file.exists() and path.samefile(protected_file):
                return True
        except OSError:
            pass
    return any(_is_within_root(path, root) for root in _PROTECTED_ROOTS)


def _is_within_root(path: Path, root: Path) -> bool:
    if path == root or path.is_relative_to(root):
        return True
    if not root.exists():
        return False
    for ancestor in (path, *path.parents):
        try:
            if ancestor.exists() and ancestor.samefile(root):
                return True
        except OSError:
            pass
    return False


def _audit_test_safety(event: str, args: tuple[object, ...]) -> None:
    """Block real repo-state writes and external sockets inside pytest."""
    if not _SAFETY_ACTIVE:
        return

    network_events = {
        "socket.connect",
        "socket.getaddrinfo",
        "socket.gethostbyaddr",
        "socket.gethostbyname",
        "socket.gethostbyname_ex",
        "socket.getnameinfo",
        "socket.sendmsg",
        "socket.sendto",
    }
    if event in network_events and not _NETWORK_ALLOWED:
        raise RuntimeError(
            "Unit test network access blocked; mark integration/network and opt in explicitly"
        )

    if event == "open" and len(args) >= 3 and _is_protected_path(args[0]):
        mode, flags = args[1], args[2]
        by_mode = isinstance(mode, str) and any(char in mode for char in "wax+")
        write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        by_flags = isinstance(flags, int) and bool(flags & write_flags)
        if by_mode or by_flags:
            raise RuntimeError(f"Test attempted to write protected runtime path: {args[0]}")

    single_path_events = {
        "os.remove": (1, False),
        "os.rmdir": (1, False),
        "os.chmod": (2, True),
        "os.chown": (3, True),
        "os.truncate": (None, True),
        "os.utime": (3, True),
        "os.setxattr": (None, True),
        "os.removexattr": (None, True),
    }
    if event in single_path_events and args:
        dir_fd_index, follow_final = single_path_events[event]
        dir_fd = (
            args[dir_fd_index] if dir_fd_index is not None and len(args) > dir_fd_index else None
        )
        if _is_protected_path(args[0], dir_fd, follow_final=follow_final):
            raise RuntimeError(f"Test attempted to mutate protected runtime path: {args[0]}")

    mkdir_dir_fd = args[2] if len(args) > 2 else None
    if (
        event in {"os.mkdir", "os.mkfifo", "os.mknod"}
        and args
        and _is_protected_path(args[0], mkdir_dir_fd, follow_final=False)
    ):
        path = _resolved_path(args[0], mkdir_dir_fd, follow_final=False)
        if path is not None and not path.exists():
            raise RuntimeError(f"Test attempted to create protected runtime path: {args[0]}")

    if event in {"os.rename", "os.replace", "os.link"}:
        source_fd = args[2] if len(args) > 2 else None
        target_fd = args[3] if len(args) > 3 else None
        if args and _is_protected_path(args[0], source_fd, follow_final=False):
            raise RuntimeError(f"Test attempted to mutate protected runtime path: {args[0]}")
        if len(args) > 1 and _is_protected_path(args[1], target_fd, follow_final=False):
            raise RuntimeError(f"Test attempted to mutate protected runtime path: {args[1]}")

    if event == "os.symlink" and len(args) > 1:
        target_fd = args[2] if len(args) > 2 else None
        if _is_protected_path(args[1], target_fd, follow_final=False):
            raise RuntimeError(f"Test attempted to mutate protected runtime path: {args[1]}")


sys.addaudithook(_audit_test_safety)

_ORIGINAL_OS_OPEN = os.open
_ORIGINAL_OS_SYSTEM = os.system
_ORIGINAL_POSIX_SPAWN = getattr(os, "posix_spawn", None)
_ORIGINAL_POSIX_SPAWNP = getattr(os, "posix_spawnp", None)


def _guarded_os_open(
    path: object,
    flags: int,
    mode: int = 0o777,
    *,
    dir_fd: int | None = None,
) -> int:
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
    if _SAFETY_ACTIVE and flags & write_flags and _is_protected_path(path, dir_fd):
        raise RuntimeError(f"Test attempted to write protected runtime path: {path}")
    return _ORIGINAL_OS_OPEN(path, flags, mode, dir_fd=dir_fd)


os.open = _guarded_os_open  # type: ignore[assignment]


def _sterile_child_env(requested: object = None) -> dict[str, str]:
    child_env = dict(os.environ if requested is None else requested)
    child_env.update(_ENV_OVERRIDES)
    return child_env


def _guarded_os_system(command: object) -> int:
    if _SAFETY_ACTIVE and not _SUBPROCESS_ALLOWED:
        raise RuntimeError("Unit test subprocess blocked; add @pytest.mark.subprocess")
    return _ORIGINAL_OS_SYSTEM(command)


def _guarded_posix_spawn(path, argv, env, *args, **kwargs):
    if _SAFETY_ACTIVE and not _SUBPROCESS_ALLOWED:
        raise RuntimeError("Unit test subprocess blocked; add @pytest.mark.subprocess")
    assert _ORIGINAL_POSIX_SPAWN is not None
    return _ORIGINAL_POSIX_SPAWN(path, argv, _sterile_child_env(env), *args, **kwargs)


def _guarded_posix_spawnp(file, argv, env, *args, **kwargs):
    if _SAFETY_ACTIVE and not _SUBPROCESS_ALLOWED:
        raise RuntimeError("Unit test subprocess blocked; add @pytest.mark.subprocess")
    assert _ORIGINAL_POSIX_SPAWNP is not None
    return _ORIGINAL_POSIX_SPAWNP(file, argv, _sterile_child_env(env), *args, **kwargs)


os.system = _guarded_os_system  # type: ignore[assignment]
if _ORIGINAL_POSIX_SPAWN is not None:
    os.posix_spawn = _guarded_posix_spawn  # type: ignore[assignment]
if _ORIGINAL_POSIX_SPAWNP is not None:
    os.posix_spawnp = _guarded_posix_spawnp  # type: ignore[assignment]

import duckdb  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

_ORIGINAL_DUCKDB_CONNECT = duckdb.connect
_ORIGINAL_SQLITE_CONNECT = sqlite3.connect
_ORIGINAL_POPEN_INIT = subprocess.Popen.__init__


def _duckdb_target(args: tuple[object, ...], kwargs: dict[str, object]) -> tuple[object, bool]:
    database = args[0] if args else kwargs.get("database", ":memory:")
    read_only = bool(args[1]) if len(args) > 1 else bool(kwargs.get("read_only", False))
    return database, read_only


def _guarded_duckdb_connect(*args, **kwargs):
    database, read_only = _duckdb_target(args, kwargs)
    if database != ":memory:" and _is_protected_path(database):
        if not read_only:
            raise RuntimeError(f"Test attempted writable DuckDB connection: {database}")
        if not _OPS_READ_ALLOWED:
            raise RuntimeError(f"Unit test attempted protected DuckDB read: {database}")
    return _ORIGINAL_DUCKDB_CONNECT(*args, **kwargs)


def _sqlite_target(database: object, *, uri: bool) -> tuple[object, bool]:
    if not uri or not isinstance(database, str) or not database.startswith("file:"):
        return database, False
    parsed = urlparse(database)
    path = unquote(parsed.path)
    mode = parse_qs(parsed.query).get("mode", [""])[0]
    return path, mode == "ro"


def _guarded_sqlite_connect(database, *args, **kwargs):
    uri = bool(args[6]) if len(args) > 6 else bool(kwargs.get("uri", False))
    target, read_only = _sqlite_target(database, uri=uri)
    if target != ":memory:" and _is_protected_path(target):
        if not read_only:
            raise RuntimeError(f"Test attempted writable SQLite connection: {target}")
        if not _OPS_READ_ALLOWED:
            raise RuntimeError(f"Unit test attempted protected SQLite read: {target}")
    return _ORIGINAL_SQLITE_CONNECT(database, *args, **kwargs)


def _guarded_popen_init(self, *args, **kwargs):
    command = args[0] if args else kwargs.get("args")
    safe_metadata_probe = (
        isinstance(command, list | tuple)
        and len(command) > 1
        and Path(os.fsdecode(command[0])).name == "git"
        and command[1] in {"describe", "rev-list", "rev-parse", "show"}
    )
    if _SAFETY_ACTIVE and not (_SUBPROCESS_ALLOWED or safe_metadata_probe):
        raise RuntimeError("Unit test subprocess blocked; add @pytest.mark.subprocess")
    positional = list(args)
    positional_env = positional[10] if len(positional) > 10 else None
    requested_env = positional_env if len(positional) > 10 else kwargs.get("env")
    child_env = _sterile_child_env(requested_env)
    if len(positional) > 10:
        positional[10] = child_env
    else:
        kwargs["env"] = child_env
    return _ORIGINAL_POPEN_INIT(self, *positional, **kwargs)


duckdb.connect = _guarded_duckdb_connect
sqlite3.connect = _guarded_sqlite_connect
subprocess.Popen.__init__ = _guarded_popen_init

# `src/` layout için path ayarı (kurulu değilken testler çalışsın)
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "integration: dış servis gerektirir")
    config.addinivalue_line("markers", "slow: yavaş test")
    config.addinivalue_line("markers", "live: gerçek borsa")
    config.addinivalue_line("markers", "network: açık ağ erişimi gerektirir")
    config.addinivalue_line("markers", "ops: aktif runtime artefaktlarını doğrular")
    config.addinivalue_line("markers", "subprocess: steril ortamda alt süreç başlatır")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Default'ta integration ve live testleri atla."""
    skip_integration = pytest.mark.skip(reason="integration tests skipped by default")
    skip_live = pytest.mark.skip(reason="live exchange tests skipped by default")
    skip_network = pytest.mark.skip(reason="network tests skipped by default")
    skip_ops = pytest.mark.skip(reason="ops tests skipped by default")
    for item in items:
        if item.get_closest_marker("integration") is not None and not _RUN_INTEGRATION:
            item.add_marker(skip_integration)
        if item.get_closest_marker("live") is not None:
            item.add_marker(skip_live)
        if item.get_closest_marker("network") is not None and not (
            _RUN_NETWORK or _RUN_INTEGRATION
        ):
            item.add_marker(skip_network)
        if item.get_closest_marker("ops") is not None and not _RUN_OPS:
            item.add_marker(skip_ops)

    # Imported test modules and legacy script probes may mutate process-global
    # environment during collection. Reassert the sterile baseline before the
    # first fixture snapshots it.
    os.environ.update(_ENV_OVERRIDES)
    try:
        from price_action.settings import get_settings

        get_settings.cache_clear()  # type: ignore[attr-defined]
    except Exception:
        pass


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Apply per-test capabilities after collection-time safety defaults."""
    global _NETWORK_ALLOWED, _OPS_READ_ALLOWED, _SUBPROCESS_ALLOWED
    integration = item.get_closest_marker("integration") is not None
    network = item.get_closest_marker("network") is not None
    _NETWORK_ALLOWED = (integration and _RUN_INTEGRATION) or (
        network and (_RUN_NETWORK or _RUN_INTEGRATION)
    )
    _OPS_READ_ALLOWED = item.get_closest_marker("ops") is not None and _RUN_OPS
    _SUBPROCESS_ALLOWED = item.get_closest_marker("subprocess") is not None


def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> None:
    global _NETWORK_ALLOWED, _OPS_READ_ALLOWED, _SUBPROCESS_ALLOWED
    _NETWORK_ALLOWED = False
    _OPS_READ_ALLOWED = False
    _SUBPROCESS_ALLOWED = False


def _cleanup_test_session() -> None:
    global _SAFETY_ACTIVE, _SESSION_CLEANED
    if _SESSION_CLEANED:
        return
    _SESSION_CLEANED = True
    _SAFETY_ACTIVE = False
    try:
        from price_action.settings import get_settings

        get_settings.cache_clear()  # type: ignore[attr-defined]
    except Exception:
        pass
    shutil.rmtree(_TEST_RUNTIME_ROOT, ignore_errors=True)
    os.open = _ORIGINAL_OS_OPEN  # type: ignore[assignment]
    os.system = _ORIGINAL_OS_SYSTEM  # type: ignore[assignment]
    if _ORIGINAL_POSIX_SPAWN is not None:
        os.posix_spawn = _ORIGINAL_POSIX_SPAWN  # type: ignore[assignment]
    if _ORIGINAL_POSIX_SPAWNP is not None:
        os.posix_spawnp = _ORIGINAL_POSIX_SPAWNP  # type: ignore[assignment]
    duckdb.connect = _ORIGINAL_DUCKDB_CONNECT
    sqlite3.connect = _ORIGINAL_SQLITE_CONNECT
    subprocess.Popen.__init__ = _ORIGINAL_POPEN_INIT
    os.environ.clear()
    os.environ.update(_ORIGINAL_PROCESS_ENV)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Also clean up disposable state for collect-only sessions."""
    _cleanup_test_session()


# ---------------------------------------------------------------------------
# Synthetic OHLCV fixtures
# ---------------------------------------------------------------------------
def _make_bar(o: float, h: float, low: float, c: float, v: float = 1000.0) -> dict:
    return {"open": o, "high": h, "low": low, "close": c, "volume": v}


@pytest.fixture
def random_ohlcv() -> pd.DataFrame:
    """Sentetik OHLCV — 1d, 200 bar, deterministik seed."""
    rng = np.random.default_rng(42)
    n = 200
    start = datetime(2023, 1, 1, tzinfo=UTC)
    ts = pd.date_range(start, periods=n, freq="1D", tz="UTC")
    rets = rng.normal(0.0, 0.02, size=n)
    close = 100.0 * np.exp(np.cumsum(rets))
    high = close * (1 + rng.uniform(0.001, 0.02, size=n))
    low = close * (1 - rng.uniform(0.001, 0.02, size=n))
    open_ = np.empty(n)
    open_[0] = close[0] * (1 + rng.uniform(-0.005, 0.005))
    open_[1:] = close[:-1] * (1 + rng.uniform(-0.005, 0.005, size=n - 1))
    # OHLC sanity garantile: high = max(o,c,h), low = min(o,c,l)
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    volume = rng.uniform(500, 1500, size=n)
    df = pd.DataFrame(
        {
            "ts": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "venue": "binance",
            "symbol": "TEST/USDT",
            "timeframe": "1d",
        }
    )
    return df


@pytest.fixture
def backtest_ready_ohlcv(random_ohlcv) -> pd.DataFrame:
    """FIX 2026-05-28 (audit-Y8): backtest-ready fixture.

    Audit'in tespit ettiği "feature divergence backtest/live" sorununa karşı:
    strateji testlerinde prepare_features() inline çağırmak yerine, fixture'ı
    feature'larla zenginleştirilmiş olarak ver. Bu sayede:
      1) Strategy test'leri prepare_features path'i değil generate_signals
         logic'i ölçer (gerçek hedef).
      2) Backtest engine'in pre-compute path'ini simüle eder (production tutarlı).
      3) Feature column'lar eksikse strategy hangi default'a düşüyor görünür.

    Eklenen feature'lar: atr14, ema_fast (20), ema_slow (50), rsi14, hl_range.
    """
    df = random_ohlcv.copy()
    # ATR14 — basit gerçek formula (TR rolling mean)
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    close = df["close"].to_numpy()
    tr = np.maximum.reduce(
        [
            high - low,
            np.abs(high - np.roll(close, 1)),
            np.abs(low - np.roll(close, 1)),
        ]
    )
    tr[0] = high[0] - low[0]  # ilk bar boş wraparound — TR=range
    df["atr14"] = pd.Series(tr).rolling(14, min_periods=1).mean().values
    # EMA fast/slow
    df["ema_fast"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=50, adjust=False).mean()
    # RSI14 (Wilder)
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14, min_periods=1).mean()
    loss = (-delta.clip(upper=0)).rolling(14, min_periods=1).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi14"] = (100 - (100 / (1 + rs))).fillna(50.0)
    # Range
    df["hl_range"] = df["high"] - df["low"]
    return df


@pytest.fixture
def bullish_pin_bar_df() -> pd.DataFrame:
    """Tek bullish pin bar içeren manuel kurgu OHLCV (5 bar)."""
    bars = [
        _make_bar(100, 101, 99, 100),  # nötr
        _make_bar(100, 102, 98, 101),  # nötr
        # bullish pin: range=10, body=1, lower_wick=8, upper_wick=1
        _make_bar(o=99.5, h=100.5, low=90, c=100),
        _make_bar(101, 102, 100.5, 101.5),
        _make_bar(101.5, 102, 101, 101.8),
    ]
    ts = pd.date_range("2024-01-01", periods=len(bars), freq="1D", tz="UTC")
    df = pd.DataFrame(bars)
    df["ts"] = ts
    return df


@pytest.fixture
def bearish_pin_bar_df() -> pd.DataFrame:
    """Tek bearish pin bar (uzun üst fitil)."""
    bars = [
        _make_bar(100, 101, 99, 100),
        _make_bar(100, 102, 99, 101),
        _make_bar(o=100.5, h=110, low=99.5, c=100),  # bearish pin
        _make_bar(99, 100, 98, 98.5),
        _make_bar(98.5, 99, 97, 97.5),
    ]
    ts = pd.date_range("2024-01-01", periods=len(bars), freq="1D", tz="UTC")
    df = pd.DataFrame(bars)
    df["ts"] = ts
    return df


@pytest.fixture
def bullish_engulfing_df() -> pd.DataFrame:
    """Bullish engulfing örneği (3 bar)."""
    bars = [
        _make_bar(100, 101, 99, 100),  # nötr
        _make_bar(100, 100.5, 95, 96),  # bearish: open 100, close 96
        _make_bar(95, 102, 95, 101),  # bullish engulfing: open 95<=96, close 101>=100
    ]
    ts = pd.date_range("2024-01-01", periods=len(bars), freq="1D", tz="UTC")
    df = pd.DataFrame(bars)
    df["ts"] = ts
    return df


@pytest.fixture
def bearish_engulfing_df() -> pd.DataFrame:
    bars = [
        _make_bar(100, 101, 99, 100),
        _make_bar(100, 105, 99, 104),  # bullish: open 100, close 104
        _make_bar(105, 105.5, 95, 99),  # bearish engulfing: open 105>=104, close 99<=100
    ]
    ts = pd.date_range("2024-01-01", periods=len(bars), freq="1D", tz="UTC")
    df = pd.DataFrame(bars)
    df["ts"] = ts
    return df


@pytest.fixture
def inside_bar_df() -> pd.DataFrame:
    """3 bar: ilk normal, ikinci inside, üçüncü inside-bar long-breakout."""
    bars = [
        _make_bar(100, 110, 90, 105),  # geniş "mother" bar
        _make_bar(o=104, h=108, low=95, c=103),  # inside: 108<110 & 95>90
        _make_bar(
            o=104, h=115, low=104, c=112
        ),  # close > prev_high (108 değil—mother bar değil. Inside bar'ın high'ı 108 → close 112 > 108 long break)
    ]
    ts = pd.date_range("2024-01-01", periods=len(bars), freq="1D", tz="UTC")
    df = pd.DataFrame(bars)
    df["ts"] = ts
    return df


@pytest.fixture
def morning_star_df() -> pd.DataFrame:
    """Morning star üç-bar örneği."""
    bars = [
        # bar -2: belirgin bearish (range 10, body 8)
        _make_bar(o=110, h=110.5, low=100, c=101),
        # bar -1: küçük gövde
        _make_bar(o=100.5, h=101, low=99.5, c=100.0),
        # bar 0: bullish, midpoint(110+101)/2=105.5 üstü close
        _make_bar(o=100.5, h=108, low=100, c=107),
    ]
    ts = pd.date_range("2024-01-01", periods=len(bars), freq="1D", tz="UTC")
    df = pd.DataFrame(bars)
    df["ts"] = ts
    return df


@pytest.fixture
def evening_star_df() -> pd.DataFrame:
    bars = [
        _make_bar(o=100, h=110, low=99.5, c=109),  # belirgin bullish, midpoint 104.5
        _make_bar(o=109.5, h=110, low=109, c=109.6),  # küçük gövde
        _make_bar(o=109, h=109.5, low=100, c=101),  # bearish; close 101 < midpoint 104.5
    ]
    ts = pd.date_range("2024-01-01", periods=len(bars), freq="1D", tz="UTC")
    df = pd.DataFrame(bars)
    df["ts"] = ts
    return df


@pytest.fixture
def doji_df() -> pd.DataFrame:
    bars = [
        _make_bar(100, 101, 99, 100.05),  # doji: gövde 0.05, range 2 → ratio 0.025
        _make_bar(100, 105, 99, 104),  # değil
    ]
    ts = pd.date_range("2024-01-01", periods=len(bars), freq="1D", tz="UTC")
    df = pd.DataFrame(bars)
    df["ts"] = ts
    return df


@pytest.fixture
def gap_ohlcv() -> pd.DataFrame:
    """1d serisinde 2 bar eksik (gap)."""
    days = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-05", "2024-01-06"], utc=True)
    rng = np.random.default_rng(7)
    n = len(days)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    df = pd.DataFrame(
        {
            "ts": days,
            "open": close - 0.5,
            "high": close + 0.5,
            "low": close - 1.0,
            "close": close,
            "volume": rng.uniform(500, 1500, size=n),
            "venue": "binance",
            "symbol": "GAP/USDT",
            "timeframe": "1d",
        }
    )
    return df


@pytest.fixture
def duplicate_ohlcv() -> pd.DataFrame:
    days = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-02", "2024-01-03"], utc=True)
    return pd.DataFrame(
        {
            "ts": days,
            "open": [100, 101, 101, 102],
            "high": [102, 103, 103, 104],
            "low": [99, 100, 100, 101],
            "close": [101, 102, 102, 103],
            "volume": [1000, 1100, 1100, 1200],
            "venue": "binance",
            "symbol": "DUP/USDT",
            "timeframe": "1d",
        }
    )


# ---------------------------------------------------------------------------
# Analytics / ML / API fixtures (Analytics+ML+API+CLI alt sistemi)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _isolate_test_env():
    """Keep mutable state in one disposable session root."""
    # `scripts.seed_data` paketini import edebilmek için ROOT'u sys.path'e al
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    yield


@pytest.fixture(autouse=True)
def _restore_environment_after_each_test():
    """Undo direct os.environ mutations, not only monkeypatch-managed ones."""
    before = os.environ.copy()
    try:
        from price_action.settings import get_settings

        get_settings.cache_clear()  # type: ignore[attr-defined]
    except Exception:
        pass
    yield
    os.environ.clear()
    os.environ.update(before)
    try:
        from price_action.settings import get_settings

        get_settings.cache_clear()  # type: ignore[attr-defined]
    except Exception:
        pass


@pytest.fixture
def synthetic_trades_df() -> pd.DataFrame:
    """Sentetik trade DataFrame — analytics testleri için."""
    from scripts.seed_data import generate_trades

    return generate_trades(n=80, seed=7)


@pytest.fixture
def synthetic_ohlcv_df() -> pd.DataFrame:
    from scripts.seed_data import generate_ohlcv

    return generate_ohlcv(n=400, seed=11)


@pytest.fixture
def in_memory_journal(tmp_path):
    """Postgres yerine SQLite-file tabanlı Journal."""
    from price_action.analytics.journal import Journal

    db_url = f"sqlite:///{tmp_path / 'journal.sqlite'}"
    return Journal(db_url=db_url)
