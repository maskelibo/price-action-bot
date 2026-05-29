"""Merkezi konfigürasyon — pydantic-settings + .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Tüm ortam değişkenleri tek noktadan."""

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- LLM ---
    anthropic_api_key: str = ""
    claude_model_default: str = "claude-opus-4-7"
    claude_model_fast: str = "claude-sonnet-4-6"
    claude_model_light: str = "claude-haiku-4-5-20251001"

    # --- Borsalar ---
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet: bool = True
    bybit_api_key: str = ""
    bybit_api_secret: str = ""
    bybit_testnet: bool = True

    # --- Veritabanı ---
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "price_action"
    postgres_user: str = "pa"
    # FIX 2026-05-28 (audit-D1): default empty string (eski "changeme_in_real_env"
    # placeholder pratikte kullanılabilir bir default'tu → docker-compose ile
    # silent çalışıyordu, prod'a sızabilirdi). Şimdi boş; postgres bağlanmaya
    # çalışan kod `get_postgres_dsn()` üzerinden geçecek + boşsa ValueError.
    postgres_password: str = ""

    duckdb_path: Path = ROOT_DIR / "data" / "market.duckdb"
    # FIX 2026-05-28 (depo-ayirma): Ingest yazıcısı için ayrı DuckDB dosyası.
    # KÖK SORUN: CEO daemon market.duckdb'yi PA_DUCKDB_READ_ONLY=true açıyor
    # (silent-fail fix); ama saatlik OHLCV ingest AYNI process'te yazmak istiyor
    # → "Cannot DELETE on read-only" → market.duckdb donuyor. Çözüm: ingest
    # ayrı bir yazılabilir dosyaya (market_ingest.duckdb) yazar, sonra atomik
    # FILE-kopya snapshot ile market.duckdb tazeленir. Tüketiciler (regime/lab/
    # backtest/drift) hâlâ duckdb_path (market.duckdb) okur — single source of
    # truth korunur, paylaşılan değiştirilebilir dosya çakışması yok olur.
    ingest_duckdb_path: Path = ROOT_DIR / "data" / "market_ingest.duckdb"
    parquet_root: Path = ROOT_DIR / "data" / "parquet"
    chroma_path: Path = ROOT_DIR / "knowledge" / "index"

    # --- Telegram / RAG ---
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    youtube_api_key: str = ""

    # --- Çalışma modu ---
    pa_run_mode: Literal["backtest", "paper", "live"] = "backtest"
    pa_live_confirm: str = ""

    # --- Backtest / universe ---
    pa_backtest_years: int = 5
    pa_timeframes: str = "1d,1w,15m"
    pa_universe_mode: Literal["top_volume", "all_liquid", "manual"] = "all_liquid"
    pa_universe_min_vol_usdt: float = 1_000_000.0

    # --- Risk varsayılanları ---
    pa_risk_per_trade: float = 0.01
    pa_max_leverage: float = 3.0
    pa_daily_dd_breaker: float = 0.05
    pa_weekly_dd_breaker: float = 0.10

    # --- Logging ---
    log_level: str = "INFO"
    log_format: Literal["plain", "json"] = "json"

    # --- Yollar ---
    @property
    def configs_dir(self) -> Path:
        return ROOT_DIR / "configs"

    @property
    def memory_dir(self) -> Path:
        return ROOT_DIR / "memory"

    @property
    def knowledge_dir(self) -> Path:
        return ROOT_DIR / "knowledge"

    @property
    def reports_dir(self) -> Path:
        return ROOT_DIR / "reports"

    @property
    def logs_dir(self) -> Path:
        return ROOT_DIR / "logs"

    @property
    def agents_rules_dir(self) -> Path:
        return ROOT_DIR / "agents"

    @property
    def is_live(self) -> bool:
        return self.pa_run_mode == "live" and self.pa_live_confirm == "YES_I_KNOW"

    @property
    def timeframes_list(self) -> list[str]:
        return [t.strip() for t in self.pa_timeframes.split(",") if t.strip()]

    @property
    def postgres_dsn(self) -> str:
        # FIX 2026-05-28 (audit-D1): boş password ile DSN oluşturma → açık hata.
        # Eski default "changeme_in_real_env" ile DSN üretilince Postgres bağlantısı
        # "auth fail" hatası veriyordu (sebebi belirsiz). Şimdi explicit:
        # POSTGRES_PASSWORD set edilmemiş → ValueError, sebep net.
        if not self.postgres_password:
            raise ValueError(
                "POSTGRES_PASSWORD env değişkeni boş — .env veya shell environment'ta "
                "set edilmeli (settings.py default'u artık 'changeme_in_real_env' değil, "
                "boş string)."
            )
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def ensure_dirs() -> None:
    """Yokken klasörleri oluştur (idempotent)."""
    s = get_settings()
    for p in [
        s.duckdb_path.parent,
        s.parquet_root,
        s.chroma_path,
        s.reports_dir,
        s.logs_dir,
        s.memory_dir,
        s.knowledge_dir,
    ]:
        p.mkdir(parents=True, exist_ok=True)
