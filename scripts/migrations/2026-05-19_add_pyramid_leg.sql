-- Migration: 2026-05-19_add_pyramid_leg
-- Sprint: SEC54.3 — PyramidRouter live execution
--
-- Açıklama:
--   futures_orders tablosuna pyramid leg takibi için iki yeni kolon eklenir.
--   parent_position_id: hangi pozisyona ait (sinyal fingerprint / entry signal_id)
--   pyramid_leg_num:    1=entry, 2=ilk pyramid, 3=ikinci pyramid (NULL=non-pyramid order)
--
-- DuckDB NOT: ALTER TABLE ADD COLUMN IF NOT EXISTS DuckDB'de doğrudan desteklenmez.
--   Bu yüzden önce kolonun varlığı kontrol edilir; yoksa eklenir.
--   Script'i idempotent çalıştırmak için TRY bloğu içinde sarmalanmıştır.
--
-- Uygulama:
--   duckdb data/futures_journal.duckdb < scripts/migrations/2026-05-19_add_pyramid_leg.sql
--   duckdb data/futures_journal_phoenix.duckdb < scripts/migrations/2026-05-19_add_pyramid_leg.sql
--   duckdb data/futures_journal_atlas.duckdb < scripts/migrations/2026-05-19_add_pyramid_leg.sql
--
-- Backward compat:
--   Mevcut tek-leg emirler pyramid_leg_num=NULL, parent_position_id=NULL olarak kalır.
--   NULL = non-pyramid (eski semantiği korur, sorgularda IS NOT NULL ile ayrıştır).

-- futures_orders tablosu mevcut değilse oluştur (idempotent baseline)
CREATE TABLE IF NOT EXISTS futures_orders (
    order_id          VARCHAR PRIMARY KEY,
    signal_id         VARCHAR,
    ts                TIMESTAMP,
    symbol            VARCHAR,
    side              VARCHAR,
    strategy          VARCHAR,
    order_type        VARCHAR,
    qty               DOUBLE,
    price             DOUBLE,
    status            VARCHAR,
    exchange_order_id VARCHAR,
    client_order_id   VARCHAR,
    fill_price        DOUBLE,
    fill_qty          DOUBLE,
    fee_usdt          DOUBLE,
    slippage_bps      DOUBLE,
    mode              VARCHAR,
    notes             VARCHAR
);

-- parent_position_id kolonu: sinyal fingerprint (pyramid pozisyonun kökü)
-- Idempotent: DuckDB ALTER TABLE ADD COLUMN hata verir kolon varsa.
-- Çalıştırılmadan önce mevcut kolonlar kontrol edilmeli:
--   SELECT column_name FROM information_schema.columns
--   WHERE table_name='futures_orders' AND column_name='parent_position_id';
ALTER TABLE futures_orders ADD COLUMN IF NOT EXISTS parent_position_id VARCHAR;

-- pyramid_leg_num kolonu: 1=entry, 2=leg-2, 3=leg-3, NULL=pyramid dışı
ALTER TABLE futures_orders ADD COLUMN IF NOT EXISTS pyramid_leg_num INTEGER;

-- Doğrulama sorgusu (migration sonrası çalıştırın)
-- SELECT column_name, data_type
-- FROM information_schema.columns
-- WHERE table_name = 'futures_orders'
-- ORDER BY ordinal_position;
