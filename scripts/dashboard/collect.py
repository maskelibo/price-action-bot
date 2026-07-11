"""Komuta Merkezi Dashboard — veri toplayıcı.

Kalıcı yerel PnL/equity kanıtı + açık/kapanan pozisyonlar + daemon sağlığı +
iç denetim bulguları (SLA) + research pipeline + yapılan işler (git) + sistem.
Periyodik collector borsa istemcisi kurmaz ve private API fallback kullanmaz.

Her collector kendi try/except'inde — biri patlarsa diğerleri çalışır (partial).
Standalone: python scripts/dashboard/collect.py  → data/dashboard/snapshot.json
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

os.environ.setdefault("PA_LOG_QUIET", "1")
import warnings

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from dotenv import dotenv_values, load_dotenv

load_dotenv(ROOT / ".env", override=False)

# v15p2 borsa-truth anchor'ları (DASHBOARD-FIX 2026-07-08: v14-çağı → canlı v15p2).
# ANCHOR = v15p2 canlı deploy (2 Tem 16:07 TR); income-truth başlangıç cüzdanı 4963.
# CLEAN = F1 forming-bar fix sonrası GERÇEK temiz pencere (7 Tem 19:55 TR); öncesi
# kirli-veri dönemi (tarama oluşmakta-olan mumlarla karar veriyordu).
ANCHOR_MS = int(datetime(2026, 7, 2, 13, 7, 0, tzinfo=UTC).timestamp() * 1000)  # v15p2 canlı
CLEAN_MS = int(datetime(2026, 7, 7, 16, 55, 0, tzinfo=UTC).timestamp() * 1000)  # F1-fix sonrası
START_EQUITY = 4963.0

DAEMONS = [
    (
        "futures_v15p2",
        "com.priceaction.futures_v15p2",
        "Trading (15m v15p2)",
        "logs/futures_daemon_v15p2.log",
    ),
    ("ceo", "com.priceaction.ceo", "CEO / Scheduler", "logs/launchd/ceo.stdout.log"),
    ("ingest15m", "com.priceaction.ingest15m", "Veri Ingest", "logs/launchd/ingest15m.stdout.log"),
    ("dbbackup", "com.priceaction.dbbackup", "DB Yedek", "logs/launchd/dbbackup.stdout.log"),
    (
        "healthping",
        "com.priceaction.healthping",
        "Dış Dead-man",
        "logs/launchd/healthping.stdout.log",
    ),
]

# ──────────────────────────────────────────────────────────────────────────
# ORGANİZASYON — agent kimlikleri (3 savunma hattı) + görev akışları + hiyerarşi
# line: 1=İcra (operasyon), 2=Gözetim, 3=Bağımsız İç Denetim
ORG_AGENTS = [
    {
        "key": "ceo",
        "name": "CEO",
        "emoji": "🎩",
        "line": 0,
        "title": "İcra Kurulu Başkanı",
        "resp": "Tüm departmanların raporlarını tek bir stratejik görüşte birleştirir; günlük brief üretir, sermayeyi dağıtır ve kriz anında protokolü yönetir.",
        "tools": "Salt-okunur · web araştırma",
        "produces": "Günlük brief · stratejik yön",
    },
    {
        "key": "researcher",
        "name": "Araştırmacı",
        "emoji": "🔬",
        "line": 1,
        "title": "Strateji Araştırma",
        "resp": "Yeni alım-satım stratejileri geliştirir. Her hipotezi önce kaydeder, ardından geriye-test ve sağlamlık analizleriyle doğrular; aşırı-uyum ve geleceği-görme yanılgılarına karşı titizdir.",
        "tools": "Geriye-test motoru",
        "produces": "Doğrulanmış hipotez · aday strateji",
    },
    {
        "key": "signal_chief",
        "name": "Sinyal Şefi",
        "emoji": "📡",
        "line": 1,
        "title": "Formasyon Tanıma",
        "resp": "Fiyat formasyonlarını (pin bar, yutan mum, kırılım) tespit eden dedektörleri yazar ve denetler. Her dedektör hızlı, saf ve geleceği-görme testinden geçmiş olmalıdır.",
        "tools": "Dedektör kütüphanesi",
        "produces": "Sinyal dedektörleri",
    },
    {
        "key": "execution_chief",
        "name": "İcra Şefi",
        "emoji": "⚡",
        "line": 1,
        "title": "Emir Yürütme & Takas",
        "resp": "Borsayla konuşan tek katman. Emirleri yönlendirir, kayma (slippage) ve gerçekleşme kalitesini takip eder; çift-emir ve kopuk pozisyonlara karşı güvenlik kilitlerini işletir.",
        "tools": "Borsa API (canlı/kâğıt)",
        "produces": "Emirler · gerçekleşme raporu",
    },
    {
        "key": "portfolio_manager",
        "name": "Portföy Yöneticisi",
        "emoji": "🧩",
        "line": 1,
        "title": "Sermaye Tahsisi",
        "resp": "Sermayeyi sinyaller arasında dağıtır; korelasyonlu kümeleri ve tek-sembol yoğunlaşma limitlerini gözeterek hangi işlemin önceliklendirileceğine karar verir.",
        "tools": "Salt-okunur",
        "produces": "Tahsis kararı · sinyal önceliği",
    },
    {
        "key": "data_engineer",
        "name": "Veri Mühendisi",
        "emoji": "🗄️",
        "line": 1,
        "title": "Veri Altyapısı",
        "resp": "Fiyat verisini toplar ve temiz tutar. Eksik bar, tekrar ve anomali tespit eder; veriyi asla sessizce düzeltmez, sorunu yüzeye çıkarır.",
        "tools": "Veri boru hattı",
        "produces": "Temiz veri · kalite raporu",
    },
    {
        "key": "lab_scientist",
        "name": "Lab Bilimci",
        "emoji": "🧪",
        "line": 1,
        "title": "Şampiyon–Aday Turnuvası",
        "resp": "Haftalık turnuvalarla aktif stratejiyi adaylara karşı sınar; istatistiksel sapma testleriyle bozulmayı yakalar. Bir strateji ancak tüm kapıları geçerse terfi eder.",
        "tools": "Turnuva · istatistik testi",
        "produces": "Turnuva sonucu · terfi önerisi",
    },
    {
        "key": "analyst",
        "name": "Analist",
        "emoji": "📊",
        "line": 1,
        "title": "Performans Analitiği",
        "resp": "Günlük ve haftalık performans karnesi çıkarır, kayıp işlemlerin nedenini araştırır; sonuçlarda gizli yanlılık (yanlı örnekleme, geleceği-görme) izlerini avlar.",
        "tools": "Analitik raporlama",
        "produces": "Performans karnesi · post-mortem",
    },
    {
        "key": "strategy_curator",
        "name": "Strateji Küratörü",
        "emoji": "🎯",
        "line": 1,
        "title": "Strateji Portföyü Yaşam Döngüsü",
        "resp": "Aktif stratejilerin getirisini ve çeşitliliğini izler; getiri-aşınması yaşayanları emekliye ayırmayı, güçlü adayları sahaya almayı önerir.",
        "tools": "Salt-okunur",
        "produces": "Tut / Emekli / Ekle kararı",
    },
    {
        "key": "market_scout",
        "name": "Pazar Kâşifi",
        "emoji": "🧭",
        "line": 1,
        "title": "Yeni Pazar Fizibilitesi",
        "resp": "Aylık olarak yeni pazarları (Forex, BIST, farklı borsalar) araştırır ve GİT/GİTME kararı üretir. Yalnızca araştırır; asla işlem açmaz.",
        "tools": "Web araştırma",
        "produces": "Fizibilite raporu",
    },
    {
        "key": "risk_officer",
        "name": "Risk Sorumlusu",
        "emoji": "🛡️",
        "line": 2,
        "title": "Risk & Sermaye Kontrolü — VETO yetkili",
        "resp": "En muhafazakâr birim. Pozisyon büyüklüğü, kaldıraç ve korelasyonu denetler; devre kesicileri izler. Mutlak veto yetkisi vardır, asla yeni pozisyon önermez.",
        "tools": "Salt-okunur",
        "produces": "Veto · kapı kararı",
    },
    {
        "key": "adversary_engineer",
        "name": "Kırmızı Takım",
        "emoji": "⚔️",
        "line": 2,
        "title": "Düşman Mühendisi — İç Stres Testi",
        "resp": "Sistemin iç saldırganı. Backtest ve deploy adaylarının uç koşullarda çökeceğini kanıtlamaya çalışır; geçmiş krizleri (COVID, LUNA, FTX) yeniden oynatır.",
        "tools": "Salt-okunur",
        "produces": "Stres raporu · onay/ret",
    },
    {
        "key": "bot_monitor",
        "name": "Bot İzleyici",
        "emoji": "📟",
        "line": 2,
        "title": "Bot Sağlığı & Durdurma Kriterleri",
        "resp": "Her botun sermaye ve kâr-zararını saatlik izler, durdurma kriterlerini değerlendirir. Çalışan bir bota asla dokunmaz; yalnızca rapor ve alarm üretir.",
        "tools": "Salt-okunur",
        "produces": "Sağlık karnesi · durdurma alarmı",
    },
    {
        "key": "ops_engineer",
        "name": "Operasyon Mühendisi",
        "emoji": "🔧",
        "line": 2,
        "title": "Sistem Güvenilirliği (SRE)",
        "resp": "Zamanlayıcı ve servis sağlığını izler, alarm gürültüsünü dengeler, kill-switch ve ölü-adam anahtarını işletir. Asla işlem kararına karışmaz.",
        "tools": "Operasyon araçları",
        "produces": "Olay özeti · çalışma süresi",
    },
    {
        "key": "audit_chief",
        "name": "İç Denetim Başkanı",
        "emoji": "⚖️",
        "line": 3,
        "title": "Baş Denetçi — Bağımsız 3. Hat",
        "resp": "Denetim evrenini yönetir, kapsama boşluklarını haritalar ve bulgu kütüğünü tutar. Aylık güvence raporunu doğrudan Principal'a sunar; kendisi saha bulgusu üretmez.",
        "tools": "Salt-okunur · bağımsız",
        "produces": "Güvence raporu · kapsama haritası",
    },
    {
        "key": "audit_domain",
        "name": "Domain Denetçileri",
        "emoji": "🔎",
        "line": 3,
        "title": "Veri · İcra · Risk · Ops · Araştırma Denetimi",
        "resp": "Her alanın kontrollerini bağımsızca yeniden hesaplar ve doğrular. Her sabah 06:00'da daemon hata günlüklerini tarar, bulguyu ilgili sahibine 1-gün SLA ile atar.",
        "tools": "Salt-okunur · bağımsız",
        "produces": "Kontrol bulgusu · 1-gün SLA",
    },
]

ORG_FLOWS = [
    {
        "name": "Strateji Yaşam Döngüsü",
        "icon": "🔬",
        "color": "#5b8cff",
        "steps": [
            "Araştırmacı: hipotez",
            "Geriye-test",
            "Sağlamlık testleri",
            "Lab: turnuva",
            "CEO: onay",
            "İcra: sahaya al",
            "Bot İzleyici",
        ],
    },
    {
        "name": "Günlük İşlem Akışı",
        "icon": "⚡",
        "color": "#2dd4bf",
        "steps": [
            "Veri toplama",
            "Sinyal tarama",
            "Portföy önceliği",
            "Risk kapısı",
            "İcra: emir",
            "Kayıt defteri",
        ],
    },
    {
        "name": "İç Denetim Döngüsü",
        "icon": "⚖️",
        "color": "#34d399",
        "steps": [
            "Denetçi 06:00 tarar",
            "Bulgu açılır",
            "Sahibine atanır",
            "1-gün SLA",
            "Kapat / Principal'a yükselt",
        ],
    },
    {
        "name": "Risk & Savunma Hattı",
        "icon": "🛡️",
        "color": "#fbbf24",
        "steps": [
            "Kırmızı Takım: stres testi",
            "Risk Sorumlusu: veto",
            "Devre kesici",
            "Acil durdurma",
        ],
    },
]

# Şirket "departmanları" = agent'lar (scheduler cadence'inden)
AGENTS = [
    ("researcher", "Araştırma", "Hipotez üret + backtest", "günlük 05:00 TR"),
    ("lab_scientist", "Lab", "Turnuva + drift + RAG", "haftalık Paz"),
    ("analyst", "Analitik", "KPI + post-mortem", "günlük 02:00 TR"),
    ("risk_officer", "Risk", "Gate + breaker denetimi", "sürekli"),
    ("adversary_engineer", "Red Team", "Stres testi + kill-probe", "günlük 07:00 TR"),
    ("audit_chief", "İç Denetim", "3. savunma hattı", "günlük 06:00 TR"),
    ("ceo", "Yönetim (CEO)", "Brief + tahsis", "günlük + ay sonu"),
]


def _tr(ts_ms: int) -> str:
    return (datetime.fromtimestamp(ts_ms / 1000, UTC) + timedelta(hours=3)).strftime("%d %b %H:%M")


def _now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def _sym(s: str) -> str:
    return s.replace("/USDT:USDT", "").replace("/USDT", "").replace("USDT", "")


LOCAL_EVIDENCE_MAX_AGE = timedelta(minutes=30)


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _empty_closed_stats() -> dict:
    return {
        "n": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0.0,
        "best": 0.0,
        "worst": 0.0,
        "gross_win": 0.0,
        "gross_loss": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "profit_factor": None,
        "total_commission": 0.0,
    }


def _empty_pnl() -> dict:
    """Return the historical successful `/api/snapshot.pnl` shape.

    Failures used to collapse the object to only ``ok`` and ``error``.  Keeping
    every field present makes local-evidence degradation explicit without
    breaking dashboard/API consumers that expect the successful schema.
    """
    return {
        "ok": False,
        "error": None,
        "warnings": [],
        "net_realized": 0.0,
        "realized_pnl": 0.0,
        "commission": 0.0,
        "funding": 0.0,
        "n_closes": 0,
        "clean_net": 0.0,
        "clean_realized": 0.0,
        "clean_comm": 0.0,
        "clean_funding": 0.0,
        "clean_n": 0,
        "unrealized": 0.0,
        "wallet": 0.0,
        "margin": 0.0,
        "available": 0.0,
        "total_pnl": 0.0,
        "total_pnl_pct": 0.0,
        "start_equity": START_EQUITY,
        "anchor_tr": _tr(ANCHOR_MS),
        "clean_tr": _tr(CLEAN_MS),
        "positions": [],
        "pos_notional_total": 0.0,
        "pos_margin_total": None,
        # ``None`` means position evidence is unavailable/degraded.  It must
        # never be collapsed to a seemingly authoritative zero.
        "n_pos": None,
        "n_pos_green": None,
        "positions_ok": False,
        "sym_attribution": [],
        "all_attribution": [],
        "closed_stats": _empty_closed_stats(),
        "closed_trades": [],
        "daily_pnl": [],
        "recent_closes": [],
    }


def _utc_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _finite_float(value: object, *, field: str) -> float:
    """Parse a finite JSON-safe number or reject the whole evidence source."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} sonlu sayı değil")
    return number


def _nonnegative_count(value: object, *, field: str) -> int:
    """Parse a lossless, non-negative count (never truncate a float)."""
    number = _finite_float(value, field=field)
    if number < 0 or not number.is_integer():
        raise ValueError(f"{field} geçersiz sayaç")
    return int(number)


def _read_equity_snapshot(path: Path, *, now: datetime) -> tuple[dict | None, str | None]:
    """Read the newest durable exchange-truth snapshot, never the exchange."""
    if not path.is_file():
        return None, f"snapshot DB yok: {path.name}"
    try:
        import duckdb

        con = duckdb.connect(str(path), read_only=True)
        try:
            row = con.execute(
                """SELECT ts, wallet_balance, unrealized_pnl, margin_balance,
                          available_balance, n_positions, n_open_orders, notes
                     FROM futures_equity_snapshots
                 ORDER BY ts DESC
                    LIMIT 1"""
            ).fetchone()
        finally:
            con.close()
    except Exception as exc:
        return None, f"snapshot okunamadı: {type(exc).__name__}: {str(exc)[:100]}"
    if row is None:
        return None, "snapshot tablosu boş"
    try:
        ts = _utc_datetime(row[0])
        age = now - ts
        notes = str(row[7] or "")
        notes_lower = notes.lower()
        snapshot = {
            "ts": ts,
            "wallet": _finite_float(row[1], field="wallet_balance"),
            "unrealized": _finite_float(0.0 if row[2] is None else row[2], field="unrealized_pnl"),
            "margin": _finite_float(0.0 if row[3] is None else row[3], field="margin_balance"),
            "available": _finite_float(
                0.0 if row[4] is None else row[4], field="available_balance"
            ),
            "n_positions": _nonnegative_count(row[5] or 0, field="n_positions"),
            "n_open_orders": _nonnegative_count(row[6] or 0, field="n_open_orders"),
            "notes": notes,
            "positions_ok": not any(
                marker in notes_lower
                for marker in ("[api_stale]", "positions_ok=false", "positions_stale")
            ),
        }
    except (TypeError, ValueError, OverflowError) as exc:
        return None, f"snapshot bozuk: {type(exc).__name__}: {str(exc)[:100]}"
    if snapshot["wallet"] <= 0:
        return None, "snapshot wallet_balance geçersiz"
    if age < -timedelta(minutes=1):
        return None, f"snapshot gelecekte: {ts.isoformat()}"
    if age > LOCAL_EVIDENCE_MAX_AGE:
        return None, f"snapshot {age.total_seconds() / 60:.1f} dk eski"
    return snapshot, None


def _read_close_events(path: Path, *, anchor: datetime) -> tuple[list[dict], str | None]:
    """Read realized-PnL events from canonical persistent local journals."""
    if not path.is_file():
        return [], f"journal DB yok: {path.name}"
    try:
        import duckdb

        con = duckdb.connect(str(path), read_only=True)
        try:
            tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
            if "futures_trades_closed" not in tables:
                return [], "journal futures_trades_closed tablosu yok"
            rows = con.execute(
                """SELECT trade_id, ts_close, sym, realized_pnl_usdt
                     FROM futures_trades_closed
                    WHERE ts_close >= ? AND COALESCE(realized_pnl_usdt, 0) != 0""",
                [anchor.replace(tzinfo=None)],
            ).fetchall()
            if "futures_partial_closes" in tables:
                rows.extend(
                    con.execute(
                        """SELECT close_id, ts_close, sym, realized_pnl_usdt
                             FROM futures_partial_closes
                            WHERE ts_close >= ? AND COALESCE(realized_pnl_usdt, 0) != 0""",
                        [anchor.replace(tzinfo=None)],
                    ).fetchall()
                )
        finally:
            con.close()
        events = []
        for row in rows:
            events.append(
                {
                    "id": str(row[0]),
                    "ts": _utc_datetime(row[1]),
                    "symbol": str(row[2] or ""),
                    "pnl": _finite_float(row[3], field="realized_pnl_usdt"),
                }
            )
        events.sort(key=lambda event: event["ts"])
        return events, None
    except Exception as exc:
        return [], f"journal okunamadı: {type(exc).__name__}: {str(exc)[:100]}"


def _read_fee_events(path: Path, *, anchor: datetime) -> tuple[list[dict], str | None]:
    """Read persisted fill fees; positive stored fees become negative commission."""
    if not path.is_file():
        return [], f"fill DB yok: {path.name}"
    try:
        import duckdb

        con = duckdb.connect(str(path), read_only=True)
        try:
            tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
            if "fills" not in tables:
                return [], "fill DB fills tablosu yok"
            columns = {row[0] for row in con.execute("DESCRIBE fills").fetchall()}
            role_expr = "fill_role" if "fill_role" in columns else "'unknown'"
            rows = con.execute(
                f"""SELECT ts, symbol, COALESCE(fee_usdt, 0), {role_expr}
                       FROM fills
                      WHERE ts >= ?""",
                [anchor.replace(tzinfo=None)],
            ).fetchall()
        finally:
            con.close()
        events = []
        for row in rows:
            events.append(
                {
                    "ts": _utc_datetime(row[0]),
                    "symbol": str(row[1] or ""),
                    "commission": -abs(
                        _finite_float(0.0 if row[2] is None else row[2], field="fee_usdt")
                    ),
                    "role": str(row[3] or "unknown").lower(),
                }
            )
        return events, None
    except Exception as exc:
        return [], f"fill DB okunamadı: {type(exc).__name__}: {str(exc)[:100]}"


_POS_CHECK_ITEM = re.compile(
    r"(?P<symbol>[A-Z0-9]+)=(?P<side>[LS])(?P<qty>[0-9.]+)@\$"
    r"(?P<entry>[0-9.]+)->(?P<last>[0-9.]+)\((?P<upnl>[+-][0-9.]+)\)"
)
_POS_CHECK_TS = re.compile(r"^\[(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})Z\]")
_POS_CHECK_COUNT = re.compile(r"POS_CHECK:\s*(?P<count>-?\d+)\s+(?:pos|pozisyon)\b")
_BINANCE_RATE_EVENT = re.compile(r"(?:\b418\b|-1003\b)")
_BINANCE_BAN_DEADLINE = re.compile(
    r"banned until\s+(?P<until_ms>\d{10,16})",
    flags=re.IGNORECASE,
)


def _read_pos_check(path: Path, *, now: datetime) -> tuple[list[dict], str | None]:
    """Parse the last bounded POS_CHECK record as durable local position detail."""
    if not path.is_file():
        return [], f"POS_CHECK logu yok: {path.name}"
    try:
        stat = path.stat()
        file_mtime = datetime.fromtimestamp(stat.st_mtime, UTC)
        size = stat.st_size
        with path.open("rb") as handle:
            if size > 800_000:
                handle.seek(-800_000, 2)
                handle.readline()
            lines = handle.read().decode("utf-8", "replace").splitlines()
        line = next((item for item in reversed(lines) if "POS_CHECK:" in item), None)
        if line is None:
            return [], "POS_CHECK kaydı yok"
        ts_match = _POS_CHECK_TS.match(line)
        if ts_match is None:
            return [], "POS_CHECK zaman damgası yok"
        check_ts = file_mtime.replace(
            hour=int(ts_match.group("hour")),
            minute=int(ts_match.group("minute")),
            second=int(ts_match.group("second")),
            microsecond=0,
        )
        # Logs carry only UTC time-of-day.  File mtime provides the date; a
        # time later than mtime necessarily belongs to the previous UTC day.
        if check_ts > file_mtime + timedelta(minutes=5):
            check_ts -= timedelta(days=1)
        age = now - check_ts
        if age < -timedelta(minutes=1) or age > LOCAL_EVIDENCE_MAX_AGE:
            return [], f"POS_CHECK kaydı {age.total_seconds() / 60:.1f} dk eski"
        if "[API_STALE]" in line:
            return [], "POS_CHECK pozisyon kanıtı API_STALE"
        count_match = _POS_CHECK_COUNT.search(line)
        if count_match is None:
            return [], "POS_CHECK pozisyon sayacı ayrıştırılamadı"
        declared_count = _nonnegative_count(
            count_match.group("count"), field="POS_CHECK position count"
        )
        positions = []
        for match in _POS_CHECK_ITEM.finditer(line):
            qty = _finite_float(match.group("qty"), field="POS_CHECK qty")
            entry = _finite_float(match.group("entry"), field="POS_CHECK entry")
            last = _finite_float(match.group("last"), field="POS_CHECK last")
            upnl = _finite_float(match.group("upnl"), field="POS_CHECK upnl")
            if qty <= 0 or entry <= 0 or last <= 0:
                raise ValueError("POS_CHECK pozisyon fiyat/miktarı geçersiz")
            notional = abs(qty * entry)
            if not math.isfinite(notional) or notional <= 0:
                raise ValueError("POS_CHECK notional geçersiz")
            positions.append(
                {
                    "symbol": match.group("symbol"),
                    "side": "LONG" if match.group("side") == "L" else "SHORT",
                    "qty": round(qty, 4),
                    "entry": round(entry, 5),
                    "last": round(last, 5),
                    "upnl": round(upnl, 2),
                    "upnl_pct": round(upnl / notional * 100, 2) if notional else 0.0,
                    "notional": round(notional, 2),
                    # POS_CHECK has no leverage/margin field; do not invent one.
                    "margin": None,
                    "lev": None,
                }
            )
        # The daemon intentionally prints at most six position details.
        if len(positions) != min(declared_count, 6):
            return [], (
                f"POS_CHECK sayaç/ayrıntı uyuşmazlığı: "
                f"count={declared_count}, parsed={len(positions)}"
            )
        return positions, None
    except Exception as exc:
        return [], f"POS_CHECK okunamadı: {type(exc).__name__}: {str(exc)[:100]}"


def _rate_limit_status(path: Path, *, now: datetime | None = None) -> dict:
    """Summarize Binance private-REST bans from the local daemon log only."""
    checked_at = now or datetime.now(UTC)
    base = {
        "events": 0,
        "last_event_utc": None,
        "last_event_age_min": None,
        "ban_until_utc": None,
        "active": False,
        "recent_48h": False,
        "error": None,
    }
    if not path.is_file():
        base["error"] = f"rate-limit logu yok: {path.name}"
        return base
    try:
        stat = path.stat()
        file_mtime = datetime.fromtimestamp(stat.st_mtime, UTC)
        with path.open("rb") as handle:
            if stat.st_size > 2_000_000:
                handle.seek(-2_000_000, 2)
                handle.readline()
            lines = handle.read().decode("utf-8", "replace").splitlines()
        event_lines = [line for line in lines if _BINANCE_RATE_EVENT.search(line)]
        base["events"] = len(event_lines)
        if not event_lines:
            return base

        line = event_lines[-1]
        ts_match = _POS_CHECK_TS.match(line)
        if ts_match is None:
            raise ValueError("son rate-limit kaydında UTC saat yok")
        event_ts = file_mtime.replace(
            hour=int(ts_match.group("hour")),
            minute=int(ts_match.group("minute")),
            second=int(ts_match.group("second")),
            microsecond=0,
        )
        if event_ts > file_mtime + timedelta(minutes=5):
            event_ts -= timedelta(days=1)
        age = checked_at - event_ts
        deadline_match = next(
            (
                match
                for candidate in reversed(event_lines)
                if (match := _BINANCE_BAN_DEADLINE.search(candidate)) is not None
            ),
            None,
        )
        until = (
            datetime.fromtimestamp(int(deadline_match.group("until_ms")) / 1000.0, UTC)
            if deadline_match is not None
            else None
        )
        base.update(
            {
                "last_event_utc": event_ts.isoformat().replace("+00:00", "Z"),
                "last_event_age_min": round(age.total_seconds() / 60.0, 1),
                "ban_until_utc": (
                    until.isoformat().replace("+00:00", "Z") if until is not None else None
                ),
                "active": until is not None and until > checked_at,
                "recent_48h": -timedelta(minutes=5) <= age <= timedelta(hours=48),
            }
        )
    except Exception as exc:
        base["error"] = f"rate-limit kanıtı okunamadı: {type(exc).__name__}: {str(exc)[:100]}"
    return base


# ──────────────────────────────────────────────────────────────────────────
def collect_pnl() -> dict:
    """Collect PnL exclusively from durable local evidence.

    This periodic collector must never construct an exchange client or fall
    back to private Binance endpoints.  The trading daemon is the sole owner
    of exchange reads and persists the evidence consumed here.
    """
    out = _empty_pnl()
    now = _now_utc()
    anchor = datetime.fromtimestamp(ANCHOR_MS / 1000, UTC)
    clean_start = datetime.fromtimestamp(CLEAN_MS / 1000, UTC)
    journal = ROOT / "data" / "futures_journal_v15p2.duckdb"
    fills_db = ROOT / "data" / "execution_fills.duckdb"
    daemon_log = ROOT / "logs" / "futures_daemon_v15p2.log"

    snapshot, snapshot_error = _read_equity_snapshot(journal, now=now)
    closes, journal_error = _read_close_events(journal, anchor=anchor)
    fees, fee_error = _read_fee_events(fills_db, anchor=anchor)
    positions, pos_error = _read_pos_check(daemon_log, now=now)

    clean_closes = [event for event in closes if event["ts"] >= clean_start]
    clean_fees = [event for event in fees if event["ts"] >= clean_start]
    realized = sum(event["pnl"] for event in closes)
    commission = sum(event["commission"] for event in fees)
    clean_realized = sum(event["pnl"] for event in clean_closes)
    clean_commission = sum(event["commission"] for event in clean_fees)

    all_attr: dict[str, float] = defaultdict(float)
    all_n: dict[str, int] = defaultdict(int)
    clean_attr: dict[str, float] = defaultdict(float)
    clean_n: dict[str, int] = defaultdict(int)
    commission_by_symbol: dict[str, float] = defaultdict(float)
    for event in closes:
        all_attr[event["symbol"]] += event["pnl"]
        all_n[event["symbol"]] += 1
    for event in clean_closes:
        clean_attr[event["symbol"]] += event["pnl"]
        clean_n[event["symbol"]] += 1
    for event in fees:
        commission_by_symbol[event["symbol"]] += event["commission"]

    wins = [event["pnl"] for event in closes if event["pnl"] > 0]
    losses = [event["pnl"] for event in closes if event["pnl"] < 0]
    gross_win, gross_loss = sum(wins), sum(losses)
    closed_stats = {
        "n": len(closes),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closes) * 100, 1) if closes else 0.0,
        "best": round(max((event["pnl"] for event in closes), default=0.0), 2),
        "worst": round(min((event["pnl"] for event in closes), default=0.0), 2),
        "gross_win": round(gross_win, 2),
        "gross_loss": round(gross_loss, 2),
        "avg_win": round(gross_win / len(wins), 2) if wins else 0.0,
        "avg_loss": round(gross_loss / len(losses), 2) if losses else 0.0,
        "profit_factor": round(gross_win / abs(gross_loss), 2) if gross_loss else None,
        "total_commission": round(commission, 2),
    }

    # Associate persisted exit fees to close rows only when local timestamps
    # make the relationship unambiguous.  Entry fees remain in aggregate totals.
    unused_exit_fees = [event for event in fees if event["role"] == "exit"]
    closed_trades = []
    for event in reversed(closes[-90:]):
        candidates = [
            fee
            for fee in unused_exit_fees
            if _sym(fee["symbol"]) == _sym(event["symbol"])
            and abs((fee["ts"] - event["ts"]).total_seconds()) <= 15 * 60
        ]
        matched = (
            min(candidates, key=lambda fee: abs((fee["ts"] - event["ts"]).total_seconds()))
            if candidates
            else None
        )
        matched_commission = matched["commission"] if matched else 0.0
        if matched:
            unused_exit_fees.remove(matched)
        event_ms = int(event["ts"].timestamp() * 1000)
        closed_trades.append(
            {
                "tr": _tr(event_ms),
                "ts": event_ms,
                "symbol": _sym(event["symbol"]),
                "pnl": round(event["pnl"], 2),
                "comm": round(matched_commission, 4),
                # Journal PnL is the canonical breaker/accounting feed and may
                # already contain exchange commission/funding via
                # realized_pnl_override. Fee evidence is displayed but never
                # added a second time.
                "net": round(event["pnl"], 2),
                "clean": event["ts"] >= clean_start,
            }
        )

    daily_map: dict[str, dict] = {}
    for event in closes:
        tr_time = event["ts"] + timedelta(hours=3)
        day = daily_map.setdefault(
            tr_time.strftime("%Y-%m-%d"),
            {"date": tr_time.strftime("%d %b"), "net": 0.0, "n": 0},
        )
        day["net"] += event["pnl"]
        day["n"] += 1
    out.update(
        {
            "realized_pnl": round(realized, 2),
            "commission": round(commission, 2),
            # Account funding income has no canonical local journal yet.  Zero
            # is displayed only with an explicit warning below, never inferred.
            "funding": 0.0,
            "net_realized": round(realized, 2),
            "n_closes": len(closes),
            "clean_realized": round(clean_realized, 2),
            "clean_comm": round(clean_commission, 2),
            "clean_funding": 0.0,
            "clean_net": round(clean_realized, 2),
            "clean_n": len(clean_closes),
            "unrealized": round(sum(item["upnl"] for item in positions), 2),
            "positions": sorted(positions, key=lambda item: -item["upnl"]),
            "pos_notional_total": round(sum(item["notional"] for item in positions), 2),
            "pos_margin_total": None,
            "n_pos": len(positions) if pos_error is None else None,
            "n_pos_green": (
                sum(1 for item in positions if item["upnl"] > 0) if pos_error is None else None
            ),
            "positions_ok": pos_error is None,
            "sym_attribution": sorted(
                [
                    {"symbol": _sym(symbol), "net": round(value, 2), "n": clean_n[symbol]}
                    for symbol, value in clean_attr.items()
                ],
                key=lambda item: -item["net"],
            ),
            "all_attribution": sorted(
                [
                    {
                        "symbol": _sym(symbol),
                        "net": round(value, 2),
                        "n": all_n[symbol],
                        "comm": round(commission_by_symbol.get(symbol, 0.0), 2),
                    }
                    for symbol, value in all_attr.items()
                ],
                key=lambda item: -item["net"],
            ),
            "closed_stats": closed_stats,
            "closed_trades": closed_trades,
            "daily_pnl": [
                {"date": value["date"], "net": round(value["net"], 2), "n": value["n"]}
                for _, value in sorted(daily_map.items())
            ],
            "recent_closes": [
                {
                    "tr": _tr(int(event["ts"].timestamp() * 1000)),
                    "symbol": _sym(event["symbol"]),
                    "pnl": round(event["pnl"], 2),
                }
                for event in reversed(clean_closes[-14:])
            ],
        }
    )

    warnings_local = [
        "funding geliri için kalıcı yerel kanıt yok; 0 gösterildi",
        (
            "journal realized_pnl_usdt kanonik PnL kanıtıdır; komisyon/funding kapsamı "
            "kayıt bazında belirsiz olduğu için fill komisyonu eklenmedi"
        ),
    ]
    if pos_error:
        warnings_local.append(pos_error)
    if fee_error:
        warnings_local.append(fee_error)
    errors = []
    if snapshot_error:
        errors.append(f"STALE: {snapshot_error}")
    if journal_error:
        errors.append(f"EVIDENCE: {journal_error}")

    if snapshot:
        equity = snapshot["wallet"] + snapshot["unrealized"]
        out.update(
            {
                "wallet": round(snapshot["wallet"], 2),
                "unrealized": round(snapshot["unrealized"], 2),
                "margin": round(snapshot["margin"], 2),
                "available": round(snapshot["available"], 2),
                "total_pnl": round(equity - START_EQUITY, 2),
                "total_pnl_pct": round((equity - START_EQUITY) / START_EQUITY * 100, 2),
            }
        )
        if not snapshot["positions_ok"]:
            out["positions_ok"] = False
            out["n_pos"] = None
            out["n_pos_green"] = None
            warnings_local.append("equity snapshot pozisyon kalitesi stale/degraded")
        elif pos_error is None and len(positions) != snapshot["n_positions"]:
            out["positions_ok"] = False
            out["n_pos"] = None
            out["n_pos_green"] = None
            warnings_local.append(
                f"POS_CHECK {len(positions)} pozisyon, snapshot {snapshot['n_positions']} pozisyon"
            )

    out["ok"] = not errors
    out["error"] = " | ".join(errors) or None
    out["warnings"] = warnings_local
    return out


# ──────────────────────────────────────────────────────────────────────────
def _launchctl_job(label: str) -> dict:
    """Return launchd state without treating an idle periodic job as healthy.

    `launchctl list <label>` exposes a PID but not the run count or last exit
    reliably. `launchctl print` gives all of them, which is required for daily
    jobs such as dbbackup that are normally not running.
    """
    try:
        target = f"gui/{os.getuid()}/{label}"
        result = subprocess.run(
            ["launchctl", "print", target], capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return {
                "loaded": False,
                "pid": None,
                "state": "missing",
                "runs": 0,
                "last_exit": None,
            }
        output = result.stdout

        def _integer(pattern: str) -> int | None:
            match = re.search(pattern, output, flags=re.MULTILINE)
            return int(match.group(1)) if match else None

        state_match = re.search(r"^\s*state\s*=\s*([^\n]+)", output, flags=re.MULTILINE)
        return {
            "loaded": True,
            "pid": _integer(r"^\s*pid\s*=\s*(\d+)"),
            "state": state_match.group(1).strip() if state_match else "unknown",
            "runs": _integer(r"^\s*runs\s*=\s*(\d+)") or 0,
            "last_exit": _integer(r"^\s*last exit code\s*=\s*(-?\d+)"),
        }
    except Exception:
        return {
            "loaded": False,
            "pid": None,
            "state": "error",
            "runs": 0,
            "last_exit": None,
        }


def _launchctl_pid(label: str) -> int | None:
    """Compatibility wrapper for callers that only need the current PID."""
    return _launchctl_job(label)["pid"]


def _proc_etime(pid: int) -> str:
    try:
        r = subprocess.run(
            ["ps", "-p", str(pid), "-o", "etime="], capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip()
    except Exception:
        return ""


def _config_value(key: str) -> str:
    """Read a non-empty env/.env value without ever logging the secret value."""
    explicit = os.getenv(key, "").strip()
    if explicit:
        return explicit
    try:
        value = dotenv_values(ROOT / ".env").get(key)
    except (OSError, ValueError):
        return ""
    return str(value).strip() if value is not None else ""


def _healthchecks_drill_marker() -> str | None:
    """Return a validated external alarm-drill timestamp, never a secret URL."""
    raw = _config_value("HEALTHCHECKS_ALARM_DRILL_VERIFIED_AT")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    parsed = parsed.astimezone(UTC)
    if parsed > datetime.now(UTC) + timedelta(minutes=5):
        return None
    return parsed.isoformat().replace("+00:00", "Z")


def collect_daemons() -> list:
    out = []
    now = datetime.now(UTC).timestamp()
    for key, label, desc, logpath in DAEMONS:
        job = _launchctl_job(label)
        pid = job["pid"]
        log_age_min = None
        p = ROOT / logpath
        if p.exists():
            log_age_min = round((now - p.stat().st_mtime) / 60, 1)

        detail = ""
        if key == "dbbackup":
            # Daily job: PID absence is normal, but loaded+successful+fresh is
            # mandatory. The previous implementation returned OK unconditionally.
            if not job["loaded"]:
                status = "down"
                detail = "launchd job yüklü değil"
            elif pid:
                status = "warn"
                detail = f"backup şu anda çalışıyor · PID {pid}"
            elif job["last_exit"] not in (0, None):
                status = "down"
                detail = f"son exit={job['last_exit']}"
            elif job["last_exit"] is None:
                status = "warn"
                detail = "son exit durumu bilinmiyor"
            elif job["runs"] < 1:
                status = "warn"
                detail = "henüz hiç koşmadı"
            elif log_age_min is None:
                status = "warn"
                detail = "başarı logu yok"
            elif log_age_min > 26 * 60:
                status = "warn"
                detail = f"son backup logu {log_age_min / 60:.1f} saat eski"
            else:
                backup_root = ROOT / "data" / "backups"
                dated = sorted(
                    (
                        path
                        for path in backup_root.glob("[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]")
                        if path.is_dir()
                    ),
                    reverse=True,
                )
                if not dated:
                    status = "warn"
                    detail = "backup dizini yok"
                elif not (dated[0] / "backup_manifest.sha256").is_file():
                    status = "warn"
                    detail = f"{dated[0].name} checksum manifest yok — ilk yeni koşu bekleniyor"
                else:
                    status = "ok"
                    detail = f"son exit=0 · runs={job['runs']} · manifest var"
        elif key == "healthping":
            configured = bool(_config_value("HEALTHCHECKS_PING_URL"))
            drill_marker = _healthchecks_drill_marker()
            if not configured:
                status = "warn"
                detail = "INERT — HEALTHCHECKS_PING_URL yok"
            elif not job["loaded"]:
                status = "down"
                detail = "URL var ama launchd job yüklü değil"
            elif job["last_exit"] is None:
                status = "warn"
                detail = "health ping son exit durumu bilinmiyor"
            elif job["last_exit"] != 0:
                status = "down"
                detail = f"health ping son exit={job['last_exit']}"
            elif job["runs"] < 1:
                status = "warn"
                detail = "URL var ama health ping henüz hiç koşmadı"
            elif log_age_min is None:
                status = "warn"
                detail = "health ping stdout logu yok"
            elif log_age_min > 12:
                status = "warn"
                detail = f"health ping logu {log_age_min:.1f} dk eski"
            elif not drill_marker:
                status = "warn"
                detail = "ping exit=0 · dış alarm drill kanıtı PENDING"
            else:
                status = "ok"
                detail = f"configured · runs={job['runs']} · drill={drill_marker}"
        # Ingest is a periodic legacy row; preserve its pre-existing semantics.
        elif pid:
            if key == "ingest15m":
                status = "ok"
            elif log_age_min is not None and log_age_min > 25:
                status = "warn"
            else:
                status = "ok"
        else:
            status = "ok" if key == "ingest15m" else "down"
        out.append(
            {
                "key": key,
                "label": label,
                "desc": desc,
                "pid": pid,
                "uptime": _proc_etime(pid) if pid else "",
                "log_age_min": log_age_min,
                "status": status,
                "loaded": job["loaded"],
                "runs": job["runs"],
                "last_exit": job["last_exit"],
                "detail": detail,
            }
        )
    rate = _rate_limit_status(ROOT / "logs" / "futures_daemon_v15p2.log")
    if rate["error"]:
        rate_status = "warn"
        rate_detail = rate["error"]
    elif rate["active"]:
        rate_status = "warn"
        rate_detail = (
            f"ACTIVE ban until {rate['ban_until_utc']} · "
            f"retained-window events={rate['events']}"
        )
    elif rate["recent_48h"]:
        rate_status = "warn"
        rate_detail = (
            f"son olay {rate['last_event_age_min']} dk önce · 48s temiz kanıt PENDING · "
            f"events={rate['events']}"
        )
    else:
        rate_status = "ok"
        rate_detail = (
            "son 48s rate-ban yok"
            if rate["events"]
            else "retained logda 418/-1003 rate-ban yok"
        )
    out.append(
        {
            "key": "binance_private_rest",
            "label": None,
            "desc": "Binance Private REST",
            "pid": None,
            "uptime": "",
            "log_age_min": rate["last_event_age_min"],
            "status": rate_status,
            "loaded": False,
            "runs": rate["events"],
            "last_exit": None,
            "detail": rate_detail,
        }
    )
    # There is intentionally no fake credential or target. Keep DR visibly
    # degraded until an encrypted, tested off-site transport exists.
    out.append(
        {
            "key": "offsite_backup",
            "label": None,
            "desc": "Off-site Yedek",
            "pid": None,
            "uptime": "",
            "log_age_min": None,
            "status": "warn",
            "loaded": False,
            "runs": 0,
            "last_exit": None,
            "detail": "PENDING — repo kontrollü off-site hedef/restore kanıtı yok",
        }
    )
    return out


# ──────────────────────────────────────────────────────────────────────────
def collect_audit() -> dict:
    reg = ROOT / "memory" / "audit" / "findings_register.jsonl"
    latest: dict = {}
    if reg.exists():
        for line in reg.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                if r.get("finding_id"):
                    latest[r["finding_id"]] = r
            except json.JSONDecodeError:
                continue
    open_states = ("OPEN", "REOPENED", "REMEDIATION_FILED")
    now = datetime.now(UTC)
    findings = []
    for r in latest.values():
        if r.get("status") not in open_states:
            continue
        due = r.get("due_at")
        hrs_left = None
        overdue = False
        if due:
            try:
                due_dt = datetime.strptime(due, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
                hrs_left = round((due_dt - now).total_seconds() / 3600, 1)
                overdue = hrs_left < 0
            except ValueError:
                pass
        findings.append(
            {
                "id": r.get("finding_id"),
                "control": r.get("control_id"),
                "severity": r.get("severity"),
                "owner": r.get("owner"),
                "title": r.get("title"),
                "status": r.get("status"),
                "hrs_left": hrs_left,
                "overdue": overdue,
                "recurrence": r.get("recurrence_count", 0),
            }
        )
    sev_order = {"critical": 0, "high": 1, "med": 2, "low": 3}
    findings.sort(key=lambda f: (not f["overdue"], sev_order.get(f["severity"], 9)))
    closed = sum(1 for r in latest.values() if r.get("status") == "CLOSED")
    return {
        "open": len(findings),
        "overdue": sum(1 for f in findings if f["overdue"]),
        "closed": closed,
        "findings": findings,
    }


# ──────────────────────────────────────────────────────────────────────────
def collect_research() -> dict:
    hyp_dir = ROOT / "memory" / "researcher" / "hypotheses"
    bt_dir = ROOT / "memory" / "researcher" / "backtest_results"
    n_hyp = len(list(hyp_dir.glob("*.md"))) if hyp_dir.exists() else 0
    bts = list(bt_dir.glob("*.json")) if bt_dir.exists() else []
    n_bt = len(bts)
    n_seed_abort = sum(1 for f in bts if "seed-abort" in f.name)
    # son aktivite
    recent = sorted(bts, key=lambda f: f.stat().st_mtime, reverse=True)[:6]
    recent_list = [
        {
            "name": f.stem.replace("-seed-abort", "")[:48],
            "tr": (datetime.fromtimestamp(f.stat().st_mtime, UTC) + timedelta(hours=3)).strftime(
                "%d %b %H:%M"
            ),
        }
        for f in recent
    ]
    return {
        "n_hypotheses": n_hyp,
        "n_backtests": n_bt,
        "n_seed_abort": n_seed_abort,
        "n_promoted": 0,  # denetim: hiç GO yok
        "verdict": "48 iterasyon — hiç promote olmadı (self-throttle döngüsü)",
        "recent": recent_list,
    }


# ──────────────────────────────────────────────────────────────────────────
def collect_worklog() -> list:
    try:
        r = subprocess.run(
            ["git", "log", "-15", "--pretty=format:%h\x1f%cr\x1f%s"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=8,
        )
        out = []
        for line in r.stdout.splitlines():
            parts = line.split("\x1f")
            if len(parts) == 3:
                out.append({"hash": parts[0], "when": parts[1], "msg": parts[2]})
        return out
    except Exception:
        return []


# ──────────────────────────────────────────────────────────────────────────
def collect_botstats() -> dict:
    log = ROOT / "logs" / "futures_daemon_v15p2.log"
    out = {
        "scans": 0,
        "entries": 0,
        "widestop_rej": 0,
        "risk_rej": 0,
        "last_scan_tr": None,
        "pos_check": None,
        "rate_limit": _rate_limit_status(log),
    }
    if not log.exists():
        return out
    try:
        # tail ~4000 satır yeterli; tüm dosya büyük olabilir
        size = log.stat().st_size
        with log.open("rb") as fh:
            if size > 800_000:
                fh.seek(-800_000, 2)
                fh.readline()
            lines = fh.read().decode("utf-8", "replace").splitlines()
        out["scans"] = sum(1 for ln in lines if "15M_SCAN" in ln)
        out["entries"] = sum(
            1 for ln in lines if any(k in ln for k in ("15M_ENTRY", "POSITION_OPEN", "ACCEPT"))
        )
        out["widestop_rej"] = sum(1 for ln in lines if "15M_REJECT_WIDESTOP" in ln)
        out["risk_rej"] = sum(1 for ln in lines if "15M_REJECT_RISK" in ln)
        for ln in reversed(lines):
            if "15M_SCAN" in ln and ln.startswith("["):
                out["last_scan_tr"] = ln[1:9]  # HH:MM:SS UTC
                break
        for ln in reversed(lines):
            if "POS_CHECK:" in ln:
                out["pos_check"] = ln.split("POS_CHECK:")[1].strip()[:300]
                break
    except Exception:
        pass
    return out


# ──────────────────────────────────────────────────────────────────────────
def collect_system() -> dict:
    out = {"disk_free": None, "disk_pct": None}
    try:
        r = subprocess.run(["df", "-h", str(ROOT)], capture_output=True, text=True, timeout=5)
        parts = r.stdout.splitlines()[-1].split()
        out["disk_free"] = parts[3]
        out["disk_pct"] = parts[4]
    except Exception:
        pass
    return out


# ──────────────────────────────────────────────────────────────────────────
def collect_all() -> dict:
    now = datetime.now(UTC)
    daemons = collect_daemons()
    audit = collect_audit()
    pnl = collect_pnl()
    snap = {
        "generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_tr": (now + timedelta(hours=3)).strftime("%d %b %Y %H:%M:%S"),
        "pnl": pnl,
        "daemons": daemons,
        "audit": audit,
        "research": collect_research(),
        "worklog": collect_worklog(),
        "botstats": collect_botstats(),
        "system": collect_system(),
        "agents": [{"key": k, "label": lb, "desc": d, "cadence": c} for k, lb, d, c in AGENTS],
        "org": {"agents": ORG_AGENTS, "flows": ORG_FLOWS},
    }
    # genel sağlık skoru
    down = sum(1 for d in daemons if d["status"] == "down")
    snap["health"] = (
        "down"
        if down
        else (
            "warn"
            if (
                audit["overdue"] > 0
                or any(d["status"] == "warn" for d in daemons)
                or not pnl["ok"]
                or bool(pnl["warnings"])
                or not pnl["positions_ok"]
            )
            else "ok"
        )
    )
    return snap


if __name__ == "__main__":
    out_path = ROOT / "data" / "dashboard" / "snapshot.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    snap = collect_all()
    out_path.write_text(
        json.dumps(snap, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    pnl = snap["pnl"]
    print(f"[dashboard] snapshot yazıldı: {out_path}")
    if pnl.get("ok"):
        print(
            f"  equity total {pnl['total_pnl']:+.2f} | TEMİZ {pnl['clean_net']:+.2f} | "
            f"{pnl['n_pos']} poz | audit open {snap['audit']['open']} | health {snap['health']}"
        )
    else:
        print(f"  PnL HATA: {pnl.get('error')}")
