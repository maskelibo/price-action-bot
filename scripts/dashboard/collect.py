"""Komuta Merkezi Dashboard — veri toplayıcı.

Borsa-truth PnL (income API) + açık/kapanan pozisyonlar + daemon sağlığı +
iç denetim bulguları (SLA) + research pipeline + yapılan işler (git) + sistem.

Her collector kendi try/except'inde — biri patlarsa diğerleri çalışır (partial).
Standalone: python scripts/dashboard/collect.py  → data/dashboard/snapshot.json
"""

from __future__ import annotations

import json
import os
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
from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)

# v14 borsa-truth anchor'ları (status-report memory'sinden)
ANCHOR_MS = int(datetime(2026, 6, 10, 22, 4, 44, tzinfo=UTC).timestamp() * 1000)  # v14 $5000 start
CLEAN_MS = int(datetime(2026, 6, 14, 21, 53, 0, tzinfo=UTC).timestamp() * 1000)  # champion emekli
START_EQUITY = 5000.0

DAEMONS = [
    (
        "futures_v14",
        "com.priceaction.futures_v14",
        "Trading (15m v14)",
        "logs/futures_daemon_v14.log",
    ),
    ("ceo", "com.priceaction.ceo", "CEO / Scheduler", "logs/launchd/ceo.stdout.log"),
    ("ingest15m", "com.priceaction.ingest15m", "Veri Ingest", "logs/launchd/ingest15m.stdout.log"),
    ("futures5m", "com.priceaction.futures5m", "Trading (5m, idle)", "logs/futures_daemon_5m.log"),
    ("dbbackup", "com.priceaction.dbbackup", "DB Yedek", "logs/launchd/dbbackup.stdout.log"),
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


# ──────────────────────────────────────────────────────────────────────────
def collect_pnl() -> dict:
    out: dict = {"ok": False, "error": None}
    try:
        from scripts.futures_trade_daily import get_futures_exchange

        ex = get_futures_exchange()
        now_ms = _now_ms()

        def fetch_income(start_ms: int) -> list:
            res: list = []
            cur = start_ms
            while cur < now_ms:
                batch = ex.fapiPrivateGetIncome(
                    {"startTime": cur, "endTime": now_ms, "limit": 1000}
                )
                if not batch:
                    break
                res.extend(batch)
                if len(batch) < 1000:
                    break
                cur = int(batch[-1]["time"]) + 1
            seen = set()
            uniq = []
            for r in res:
                k = (r.get("tranId"), r.get("time"), r.get("incomeType"), r.get("income"))
                if k in seen:
                    continue
                seen.add(k)
                uniq.append(r)
            return uniq

        def summ(rows: list):
            rp = sum(float(r["income"]) for r in rows if r["incomeType"] == "REALIZED_PNL")
            cm = sum(float(r["income"]) for r in rows if r["incomeType"] == "COMMISSION")
            fn = sum(float(r["income"]) for r in rows if r["incomeType"] == "FUNDING_FEE")
            return rp, cm, fn

        inc = fetch_income(ANCHOR_MS)
        rp, cm, fn = summ(inc)
        clean = [r for r in inc if int(r["time"]) >= CLEAN_MS]
        crp, ccm, cfn = summ(clean)
        closes = [r for r in inc if r["incomeType"] == "REALIZED_PNL" and float(r["income"]) != 0.0]
        clean_closes = [r for r in closes if int(r["time"]) >= CLEAN_MS]

        sym_net: dict = defaultdict(float)
        sym_n: dict = defaultdict(int)
        for r in clean_closes:
            sym_net[r["symbol"]] += float(r["income"])
            sym_n[r["symbol"]] += 1

        poss = [p for p in ex.fetch_positions() if abs(float(p["info"].get("positionAmt", 0))) > 0]
        rows_pos = []
        for p in poss:
            info = p["info"]
            s = p["symbol"]
            amt = float(info["positionAmt"])
            entry = float(info["entryPrice"])
            try:
                last = float(ex.fetch_ticker(s)["last"])
            except Exception:
                last = float(info.get("markPrice", entry))
            upnl = (last - entry) * amt
            notional = abs(float(info.get("notional") or 0)) or abs(amt) * entry
            margin = float(
                info.get("initialMargin")
                or info.get("positionInitialMargin")
                or info.get("isolatedWallet")
                or 0
            )
            lev = round(notional / margin, 1) if margin else None
            rows_pos.append(
                {
                    "symbol": _sym(s),
                    "side": "LONG" if amt > 0 else "SHORT",
                    "qty": abs(amt),
                    "entry": entry,
                    "last": last,
                    "upnl": upnl,
                    "upnl_pct": (upnl / notional * 100) if notional else 0.0,
                    "notional": notional,
                    "margin": margin,
                    "lev": lev,
                }
            )
        rows_pos.sort(key=lambda x: -x["upnl"])

        # Komisyon eşleme: COMMISSION income'ı (sembol, zaman) ile REALIZED_PNL'e bağla
        comm_at: dict = defaultdict(float)
        all_comm_sym: dict = defaultdict(float)
        for r in inc:
            if r["incomeType"] == "COMMISSION":
                comm_at[(r["symbol"], int(r["time"]))] += float(r["income"])
                all_comm_sym[r["symbol"]] += float(r["income"])

        # Tüm kapanış geçmişi (geçmiş pozisyonlar sekmesi) + istatistik
        all_attr: dict = defaultdict(float)
        all_n: dict = defaultdict(int)
        for r in closes:
            all_attr[r["symbol"]] += float(r["income"])
            all_n[r["symbol"]] += 1
        wins = [float(r["income"]) for r in closes if float(r["income"]) > 0]
        losses = [float(r["income"]) for r in closes if float(r["income"]) < 0]
        gw, gl = sum(wins), sum(losses)
        closed_stats = {
            "n": len(closes),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(closes) * 100, 1) if closes else 0.0,
            "best": round(max([float(r["income"]) for r in closes], default=0.0), 2),
            "worst": round(min([float(r["income"]) for r in closes], default=0.0), 2),
            "gross_win": round(gw, 2),
            "gross_loss": round(gl, 2),
            "avg_win": round(gw / len(wins), 2) if wins else 0.0,
            "avg_loss": round(gl / len(losses), 2) if losses else 0.0,
            "profit_factor": round(gw / abs(gl), 2) if gl else None,
            "total_commission": round(cm, 2),  # tüm v14 ödenen komisyon (fee)
        }
        closed_trades = []
        for r in sorted(closes, key=lambda r: int(r["time"]), reverse=True)[:90]:
            c = comm_at.get((r["symbol"], int(r["time"])), 0.0)
            closed_trades.append(
                {
                    "tr": _tr(int(r["time"])),
                    "ts": int(r["time"]),
                    "symbol": _sym(r["symbol"]),
                    "pnl": round(float(r["income"]), 2),
                    "comm": round(c, 4),
                    "net": round(float(r["income"]) + c, 2),
                    "clean": int(r["time"]) >= CLEAN_MS,
                }
            )

        # Günlük performans (income'ı TR gününe göre grupla — equity ilerlemesi)
        daily_map: dict = {}
        for r in inc:
            dt = datetime.fromtimestamp(int(r["time"]) / 1000, UTC) + timedelta(hours=3)
            k = dt.strftime("%Y-%m-%d")
            d = daily_map.setdefault(k, {"date": dt.strftime("%d %b"), "net": 0.0, "n": 0})
            d["net"] += float(r["income"])
            if r["incomeType"] == "REALIZED_PNL" and float(r["income"]) != 0.0:
                d["n"] += 1
        daily_pnl = [
            {"date": v["date"], "net": round(v["net"], 2), "n": v["n"]}
            for _, v in sorted(daily_map.items())
        ]

        bal = ex.fetch_balance()
        wallet = float(bal["info"]["totalWalletBalance"])
        margin = float(bal["info"]["totalMarginBalance"])
        avail = float(bal["info"].get("availableBalance", 0) or 0)
        upnl_total = sum(x["upnl"] for x in rows_pos)

        out.update(
            {
                "ok": True,
                "net_realized": round(rp + cm + fn, 2),
                "realized_pnl": round(rp, 2),
                "commission": round(cm, 2),
                "funding": round(fn, 2),
                "n_closes": len(closes),
                "clean_net": round(crp + ccm + cfn, 2),
                "clean_realized": round(crp, 2),
                "clean_comm": round(ccm, 2),
                "clean_funding": round(cfn, 2),
                "clean_n": len(clean_closes),
                "unrealized": round(upnl_total, 2),
                "wallet": round(wallet, 2),
                "margin": round(margin, 2),
                "available": round(avail, 2),
                "total_pnl": round((wallet + upnl_total) - START_EQUITY, 2),
                "total_pnl_pct": round(
                    ((wallet + upnl_total) - START_EQUITY) / START_EQUITY * 100, 2
                ),
                "start_equity": START_EQUITY,
                "anchor_tr": _tr(ANCHOR_MS),
                "clean_tr": _tr(CLEAN_MS),
                "positions": [
                    {
                        **p,
                        "qty": round(p["qty"], 4),
                        "entry": round(p["entry"], 5),
                        "last": round(p["last"], 5),
                        "upnl": round(p["upnl"], 2),
                        "upnl_pct": round(p["upnl_pct"], 2),
                        "notional": round(p["notional"], 2),
                        "margin": round(p["margin"], 2),
                    }
                    for p in rows_pos
                ],
                "pos_notional_total": round(sum(p["notional"] for p in rows_pos), 2),
                "pos_margin_total": round(sum(p["margin"] for p in rows_pos), 2),
                "n_pos": len(rows_pos),
                "n_pos_green": sum(1 for p in rows_pos if p["upnl"] > 0),
                "sym_attribution": sorted(
                    [
                        {"symbol": _sym(k), "net": round(v, 2), "n": sym_n[k]}
                        for k, v in sym_net.items()
                    ],
                    key=lambda x: -x["net"],
                ),
                "all_attribution": sorted(
                    [
                        {
                            "symbol": _sym(k),
                            "net": round(v, 2),
                            "n": all_n[k],
                            "comm": round(all_comm_sym.get(k, 0.0), 2),
                        }
                        for k, v in all_attr.items()
                    ],
                    key=lambda x: -x["net"],
                ),
                "closed_stats": closed_stats,
                "closed_trades": closed_trades,
                "daily_pnl": daily_pnl,
                "recent_closes": [
                    {
                        "tr": _tr(int(r["time"])),
                        "symbol": _sym(r["symbol"]),
                        "pnl": round(float(r["income"]), 2),
                    }
                    for r in sorted(clean_closes, key=lambda r: int(r["time"]))[-14:]
                ][::-1],
            }
        )
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:160]}"
    return out


# ──────────────────────────────────────────────────────────────────────────
def _launchctl_pid(label: str) -> int | None:
    try:
        r = subprocess.run(["launchctl", "list", label], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if '"PID"' in line:
                return int(line.split("=")[1].strip().rstrip(";").strip())
    except Exception:
        pass
    return None


def _proc_etime(pid: int) -> str:
    try:
        r = subprocess.run(
            ["ps", "-p", str(pid), "-o", "etime="], capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip()
    except Exception:
        return ""


def collect_daemons() -> list:
    out = []
    now = datetime.now(UTC).timestamp()
    for key, label, desc, logpath in DAEMONS:
        pid = _launchctl_pid(label)
        log_age_min = None
        p = ROOT / logpath
        if p.exists():
            log_age_min = round((now - p.stat().st_mtime) / 60, 1)
        # sağlık: PID var + log <20dk taze (periodik job'lar hariç)
        if pid:
            if key in ("ingest15m", "dbbackup"):
                status = "ok"  # periodik
            elif log_age_min is not None and log_age_min > 25:
                status = "warn"
            else:
                status = "ok"
        else:
            status = "ok" if key in ("ingest15m", "dbbackup") else "down"
        out.append(
            {
                "key": key,
                "label": label,
                "desc": desc,
                "pid": pid,
                "uptime": _proc_etime(pid) if pid else "",
                "log_age_min": log_age_min,
                "status": status,
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
    log = ROOT / "logs" / "futures_daemon_v14.log"
    out = {
        "scans": 0,
        "entries": 0,
        "widestop_rej": 0,
        "risk_rej": 0,
        "last_scan_tr": None,
        "pos_check": None,
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
    snap = {
        "generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_tr": (now + timedelta(hours=3)).strftime("%d %b %Y %H:%M:%S"),
        "pnl": collect_pnl(),
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
            if (audit["overdue"] > 0 or any(d["status"] == "warn" for d in daemons))
            else "ok"
        )
    )
    return snap


if __name__ == "__main__":
    out_path = ROOT / "data" / "dashboard" / "snapshot.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    snap = collect_all()
    out_path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    pnl = snap["pnl"]
    print(f"[dashboard] snapshot yazıldı: {out_path}")
    if pnl.get("ok"):
        print(
            f"  equity total {pnl['total_pnl']:+.2f} | TEMİZ {pnl['clean_net']:+.2f} | "
            f"{pnl['n_pos']} poz | audit open {snap['audit']['open']} | health {snap['health']}"
        )
    else:
        print(f"  PnL HATA: {pnl.get('error')}")
