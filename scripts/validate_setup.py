"""Ortam doğrulama scripti — env, klasör, bağımlılık kontrolü.

Renk-kodlu çıktı (yeşil/kırmızı/sarı) ile her kalemin durumunu raporlar.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def _ok(msg: str) -> None:
    print(f"{GREEN}[OK]{RESET} {msg}")


def _err(msg: str) -> None:
    print(f"{RED}[ERR]{RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"{YELLOW}[WARN]{RESET} {msg}")


def check_python() -> bool:
    if sys.version_info >= (3, 11):
        _ok(f"python {sys.version.split()[0]}")
        return True
    _err(f"python >=3.11 gerekli, mevcut {sys.version.split()[0]}")
    return False


def check_imports() -> bool:
    required = [
        "pandas",
        "numpy",
        "pydantic",
        "pydantic_settings",
        "loguru",
        "fastapi",
        "uvicorn",
        "sqlalchemy",
        "duckdb",
        "scipy",
        "sklearn",
        "joblib",
        "prometheus_client",
        "typer",
        "jinja2",
    ]
    failed = []
    for mod in required:
        try:
            importlib.import_module(mod)
        except ImportError:
            failed.append(mod)
    if failed:
        _err(f"eksik paketler: {', '.join(failed)}")
        return False
    _ok(f"core paketler ({len(required)}) yüklü")
    return True


def check_optional() -> None:
    optional = ["xgboost", "ccxt", "vectorbt", "chromadb", "sentence_transformers"]
    for mod in optional:
        try:
            importlib.import_module(mod)
            _ok(f"opt: {mod}")
        except ImportError:
            _warn(f"opt: {mod} yüklü değil")


def check_dirs(root: Path) -> bool:
    needed = ["src/price_action", "configs", "agents", "tests", "scripts"]
    bad = [p for p in needed if not (root / p).is_dir()]
    if bad:
        _err(f"eksik dizinler: {bad}")
        return False
    _ok("temel dizinler mevcut")
    return True


def check_files(root: Path) -> bool:
    files = [
        "pyproject.toml",
        "docker-compose.yml",
        "configs/risk.yaml",
        "configs/strategies/classic_pa.yaml",
        "src/price_action/contracts.py",
        "src/price_action/settings.py",
        "scripts/db/init.sql",
    ]
    bad = [f for f in files if not (root / f).is_file()]
    if bad:
        _err(f"eksik dosyalar: {bad}")
        return False
    _ok("anahtar dosyalar mevcut")
    return True


def check_env() -> None:
    if Path(".env").exists():
        _ok(".env mevcut")
    else:
        _warn(".env yok — defaults çalışır")
    if os.getenv("PA_ADMIN_TOKEN"):
        _ok("PA_ADMIN_TOKEN set")
    else:
        _warn("PA_ADMIN_TOKEN tanımsız — admin endpoint'leri 503 verir")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    print(f"--- price-action setup validation @ {root} ---")
    fails = 0
    fails += 0 if check_python() else 1
    fails += 0 if check_dirs(root) else 1
    fails += 0 if check_files(root) else 1
    fails += 0 if check_imports() else 1
    check_optional()
    check_env()
    if fails:
        _err(f"{fails} kritik kontrol başarısız")
        return 1
    _ok("tüm kritik kontroller geçti")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
