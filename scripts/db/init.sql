-- Price Action — Postgres schema (idempotent).
-- Container ilk açılışta bunu çalıştırır (`docker-entrypoint-initdb.d/init.sql`).
-- SQLAlchemy ORM da aynı tabloları create_all ile garanti eder; bu dosya
-- ham SQL ihtiyaç duyan alet (psql, dbt vb.) için hazır şema.

CREATE TABLE IF NOT EXISTS trades (
    trade_id            VARCHAR(64) PRIMARY KEY,
    venue               VARCHAR(32) NOT NULL,
    symbol              VARCHAR(64) NOT NULL,
    side                VARCHAR(8)  NOT NULL,
    entry_ts            TIMESTAMP    NOT NULL,
    exit_ts             TIMESTAMP    NOT NULL,
    entry_price         DOUBLE PRECISION NOT NULL,
    exit_price          DOUBLE PRECISION NOT NULL,
    quantity            DOUBLE PRECISION NOT NULL,
    realized_pnl_usdt   DOUBLE PRECISION NOT NULL,
    realized_r_multiple DOUBLE PRECISION NOT NULL,
    fees_usdt           DOUBLE PRECISION NOT NULL,
    slippage_bps        DOUBLE PRECISION NOT NULL,
    strategy_id         VARCHAR(64) NOT NULL,
    pattern_id          VARCHAR(64) NOT NULL,
    confluence_score    DOUBLE PRECISION NOT NULL,
    initial_sl          DOUBLE PRECISION NOT NULL,
    initial_tp          DOUBLE PRECISION NOT NULL,
    mae_pct             DOUBLE PRECISION NOT NULL,
    mfe_pct             DOUBLE PRECISION NOT NULL,
    classification      VARCHAR(32),
    notes               TEXT,
    manifest_hash       VARCHAR(64) NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_trades_symbol      ON trades (symbol);
CREATE INDEX IF NOT EXISTS idx_trades_strategy    ON trades (strategy_id);
CREATE INDEX IF NOT EXISTS idx_trades_pattern     ON trades (pattern_id);
CREATE INDEX IF NOT EXISTS idx_trades_exit_ts     ON trades (exit_ts);
CREATE INDEX IF NOT EXISTS idx_trades_entry_ts    ON trades (entry_ts);


CREATE TABLE IF NOT EXISTS fills (
    id              BIGSERIAL PRIMARY KEY,
    order_id        VARCHAR(64) NOT NULL,
    venue           VARCHAR(32) NOT NULL,
    symbol          VARCHAR(64) NOT NULL,
    side            VARCHAR(8)  NOT NULL,
    price           DOUBLE PRECISION NOT NULL,
    quantity        DOUBLE PRECISION NOT NULL,
    fee_usdt        DOUBLE PRECISION NOT NULL,
    fee_currency    VARCHAR(16) NOT NULL DEFAULT 'USDT',
    timestamp       TIMESTAMP    NOT NULL,
    is_maker        BOOLEAN     NOT NULL,
    expected_price  DOUBLE PRECISION NOT NULL,
    slippage_bps    DOUBLE PRECISION NOT NULL,
    mode            VARCHAR(16) NOT NULL,
    manifest_hash   VARCHAR(64) NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_fills_order   ON fills (order_id);
CREATE INDEX IF NOT EXISTS idx_fills_symbol  ON fills (symbol);
CREATE INDEX IF NOT EXISTS idx_fills_ts      ON fills (timestamp);


CREATE TABLE IF NOT EXISTS positions (
    id                  BIGSERIAL PRIMARY KEY,
    venue               VARCHAR(32) NOT NULL,
    symbol              VARCHAR(64) NOT NULL,
    side                VARCHAR(8)  NOT NULL,
    quantity            DOUBLE PRECISION NOT NULL,
    entry_price         DOUBLE PRECISION NOT NULL,
    current_price       DOUBLE PRECISION NOT NULL,
    unrealized_pnl_usdt DOUBLE PRECISION NOT NULL,
    realized_pnl_usdt   DOUBLE PRECISION NOT NULL,
    sl_price            DOUBLE PRECISION,
    tp_price            DOUBLE PRECISION,
    opened_at           TIMESTAMP    NOT NULL,
    strategy_id         VARCHAR(64) NOT NULL,
    last_updated        TIMESTAMP    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_positions_symbol   ON positions (symbol);
CREATE INDEX IF NOT EXISTS idx_positions_strategy ON positions (strategy_id);


CREATE TABLE IF NOT EXISTS signals (
    id                 BIGSERIAL PRIMARY KEY,
    fingerprint        VARCHAR(32) NOT NULL UNIQUE,
    ts                 TIMESTAMP    NOT NULL,
    venue              VARCHAR(32) NOT NULL,
    symbol             VARCHAR(64) NOT NULL,
    timeframe          VARCHAR(8)  NOT NULL,
    direction          VARCHAR(8)  NOT NULL,
    pattern_id         VARCHAR(64) NOT NULL,
    confluence_score   DOUBLE PRECISION NOT NULL,
    sl_price           DOUBLE PRECISION NOT NULL,
    tp_price           DOUBLE PRECISION NOT NULL,
    suggested_size_atr DOUBLE PRECISION NOT NULL,
    metadata_json      JSONB,
    manifest_hash      VARCHAR(64) NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_signals_fp     ON signals (fingerprint);
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals (symbol);
CREATE INDEX IF NOT EXISTS idx_signals_ts     ON signals (ts);


-- Paper trading state (Execution Chief tarafından yazılır).
CREATE TABLE IF NOT EXISTS paper_state (
    id              BIGSERIAL PRIMARY KEY,
    snapshot_ts     TIMESTAMP    NOT NULL,
    equity_usdt     DOUBLE PRECISION NOT NULL,
    cash_usdt       DOUBLE PRECISION NOT NULL,
    open_positions  INT          NOT NULL,
    breaker_active  BOOLEAN     NOT NULL DEFAULT FALSE,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_paper_state_ts ON paper_state (snapshot_ts);
