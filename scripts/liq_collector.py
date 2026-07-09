"""Likidasyon collector (Bybit linear allLiquidation) — YOL_HARITASI §3d.

NEDEN: Dalga-5 A4-eksen1 — likidasyon feed'i $0 maliyetli, vsa_climax'in doğal
doğrulayıcısı (climax barları likidasyon kaskadlarıyla örtüşür). Stream geriye
dönük VERİLMEZ → başlamadığımız her gün kalıcı backtest tarihi kaybı. Araştırma
değeri: liq-yoğunluğu feature'ları (meta-labeling hammaddesi), kaskad-rejim
tespiti, stop-avı bölge haritası.

KAYNAK NEDEN BYBIT (2026-07-10 kanıtı): Binance fstream.binance.com websocket'i
bu ağdan HİÇ veri akıtmıyor (handshake OK, 0 mesaj — aggTrade kontrol grubu
dahil; browser-header'lar da çare değil; REST fapi 200 dönüyor). Muhtemel
TR-bölge websocket engeli. Spot WS + binance.vision akıyor ama forceOrder
futures-only. Bybit v5 public linear: ack success + ticker 58 msg/15s kanıtlı.
Likidasyon kaskadları borsalar-arası yüksek korele → feature değeri korunur.
VPS'e taşınınca (A4 operasyon planı) Binance backend'i yeniden değerlendirilir.

TASARIM:
- wss://stream.bybit.com/v5/public/linear, topic: allLiquidation.{SYMBOL}
- Evren: canlı botun 18 sembolü + BTC/ETH (piyasa-geneli kaskad bağlamı).
- DuckDB tek-yazar: data/liquidations.duckdb (T3 eşzamanlılık dersleri).
- Periyodik flusher (mesaj-gelişinden bağımsız — sakin piyasada da heartbeat).
- Üstel backoff'lu sonsuz reconnect; kopuşta buffer önce yazılır.
- Heartbeat: logs/state/liq_collector_heartbeat.txt (promises.yaml'a bağlanabilir).

Çalıştır: .venv/bin/python scripts/liq_collector.py [--probe N]
launchd: ops/launchd/com.priceaction.liqcollector.plist (KeepAlive)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("PA_LOG_QUIET", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import duckdb  # noqa: E402
import websockets  # noqa: E402

WS_URL = "wss://stream.bybit.com/v5/public/linear"
DB_PATH = ROOT / "data" / "liquidations.duckdb"
HEARTBEAT = ROOT / "logs" / "state" / "liq_collector_heartbeat.txt"
FLUSH_SEC = 30
RECONNECT_BASE_SEC = 2
RECONNECT_MAX_SEC = 300

# Canlı bot evreni (scripts/futures_trade_15m.py SYMBOLS, 18) + BTC/ETH bağlam.
# Bybit linear format: suffix'siz birleşik (AAVEUSDT).
UNIVERSE = [
    "BTCUSDT",
    "ETHUSDT",  # piyasa-geneli kaskad bağlamı
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "AVAXUSDT",
    "DOTUSDT",
    "LINKUSDT",
    "NEARUSDT",
    "XLMUSDT",
    "FILUSDT",
    "ZECUSDT",
    "TRXUSDT",
    "ATOMUSDT",
    "AAVEUSDT",
    "ALGOUSDT",
]


def _log(msg: str) -> None:
    ts = datetime.now(UTC).strftime("%H:%M:%SZ")
    print(f"[{ts}] {msg}", flush=True)


def _init_db() -> None:
    con = duckdb.connect(str(DB_PATH))
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS liquidations (
                event_ts TIMESTAMP,      -- naive-UTC (TradeJournal._strip_tz konvansiyonu)
                symbol VARCHAR,          -- BTCUSDT formatı
                side VARCHAR,            -- Bybit S: 'Buy' = short-liq, 'Sell' = long-liq
                price DOUBLE,
                qty DOUBLE,
                notional_usdt DOUBLE,    -- price × qty
                source VARCHAR           -- 'bybit_linear'
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_liq_sym_ts ON liquidations(symbol, event_ts)")
        con.commit()
    finally:
        con.close()


def _flush(rows: list[tuple]) -> int:
    """Batch'i DB'ye yaz. Kısa bağlantı, try/finally (T3 dersi)."""
    if not rows:
        return 0
    con = duckdb.connect(str(DB_PATH))
    try:
        con.executemany("INSERT INTO liquidations VALUES (?,?,?,?,?,?,?)", rows)
        con.commit()
        return len(rows)
    finally:
        con.close()


def _parse_message(raw: str) -> list[tuple]:
    """Bybit allLiquidation mesajını satırlara çevir. Bozuk → [] (akış durmaz).

    Format: {"topic":"allLiquidation.BTCUSDT","ts":...,"data":[
        {"T": ms, "s": "BTCUSDT", "S": "Buy"|"Sell", "v": "qty", "p": "price"}]}
    """
    try:
        msg = json.loads(raw)
        if not str(msg.get("topic", "")).startswith("allLiquidation"):
            return []
        out = []
        for d in msg.get("data", []) or []:
            # naive-UTC yazım (aware bind DuckDB'de LOKAL'e çevrilir — T1 dersi)
            ts = datetime.fromtimestamp(int(d.get("T", 0)) / 1000, UTC).replace(tzinfo=None)
            price = float(d.get("p") or 0)
            qty = float(d.get("v") or 0)
            out.append(
                (
                    ts,
                    str(d.get("s", "")),
                    str(d.get("S", "")),
                    price,
                    qty,
                    price * qty,
                    "bybit_linear",
                )
            )
        return out
    except Exception:
        return []


async def _flusher(buffer: list[tuple], stats: dict) -> None:
    """Periyodik flush — mesaj-gelişinden BAĞIMSIZ."""
    while True:
        await asyncio.sleep(FLUSH_SEC)
        rows, buffer[:] = list(buffer), []
        n = _flush(rows)
        stats["total"] += n
        HEARTBEAT.touch()
        if n:
            _log(f"flush: +{n} likidasyon (toplam {stats['total']})")


async def run(max_seconds: float | None = None) -> int:
    """max_seconds: probe modu — N saniye sonra flush edip çıkar."""
    _init_db()
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    buffer: list[tuple] = []
    stats = {"total": 0}
    backoff = RECONNECT_BASE_SEC
    sub = json.dumps({"op": "subscribe", "args": [f"allLiquidation.{s}" for s in UNIVERSE]})
    _log(f"liq_collector başladı → {DB_PATH.name} | {len(UNIVERSE)} sembol (bybit linear)")
    flusher = asyncio.create_task(_flusher(buffer, stats))
    deadline = (asyncio.get_event_loop().time() + max_seconds) if max_seconds else None

    try:
        while True:
            try:
                async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=20) as ws:
                    await ws.send(sub)
                    _log("WS bağlı + abone (bybit allLiquidation)")
                    backoff = RECONNECT_BASE_SEC
                    while True:
                        timeout = 5.0
                        if deadline is not None:
                            remain = deadline - asyncio.get_event_loop().time()
                            if remain <= 0:
                                return stats["total"] + _flush(list(buffer))
                            timeout = min(timeout, remain)
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                        except TimeoutError:
                            continue  # sessiz pencere
                        buffer.extend(_parse_message(raw))
            except Exception as exc:
                # Kopuşta buffer'ı KAYBETME — önce yaz, sonra reconnect
                stats["total"] += _flush(list(buffer))
                buffer.clear()
                _log(
                    f"WS koptu ({type(exc).__name__}: {str(exc)[:80]}) — "
                    f"{backoff}s sonra reconnect"
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, RECONNECT_MAX_SEC)
    finally:
        flusher.cancel()
        stats["total"] += _flush(list(buffer))


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", type=float, default=None, help="N saniye topla, flush et, çık")
    args = ap.parse_args()
    try:
        n = asyncio.run(run(max_seconds=args.probe))
        if args.probe:
            _log(f"probe bitti: {n} satır yazıldı")
    except KeyboardInterrupt:
        _log("durduruldu (SIGINT)")
