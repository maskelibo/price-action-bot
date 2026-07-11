"""Otonom Arastirma Loop — RAG ingest (YouTube + RSS) + hipotez tartismasi.

Bu script kullanici uyurken kendisini calistirir:
1. seeds.yaml'daki YouTube kanallarindan yt-dlp ile son N videoyu bul.
2. youtube_transcript_api ile transkriptleri cek, RAG'a ingest et.
3. Onceden tanimli 8 seed topic icin:
   - Researcher hipotez uretir (RAG'i kullanir).
   - Lab Scientist overfit/regime/gate riski analiz eder.
   - Analyst metrik onerisi yapar.
   - CEO conservative bias ile arbitraj yapar.
4. Sonuclari `reports/research/discussion-YYYYMMDD-HHMMSS.md`'ye yazar.

Calistirma:
    PYTHONPATH=src PA_LLM_USE_CLI=true python scripts/autonomous_research.py

Env:
    PA_RESEARCH_MODEL    : default `claude-haiku-4-5` (ucuz). Sonnet: `claude-sonnet-4-6`.
    PA_YOUTUBE_PER_CHANNEL : kanal basina cekilecek video sayisi (default 8).
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ----------------------------------------------------------------------
# YouTube ingest helper
# ----------------------------------------------------------------------

def _yt_dlp_list_videos(channel_url: str, max_videos: int) -> list[dict]:
    """yt-dlp ile kanal videolarini listele. Donus: [{id, title, url}]."""
    try:
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--flat-playlist",
            "--print", "%(id)s\t%(title)s\t%(webpage_url)s",
            "--playlist-end", str(max_videos),
            "--skip-download",
            "--no-warnings",
            channel_url + ("/videos" if "@" in channel_url and not channel_url.endswith("/videos") else ""),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, encoding="utf-8")
        out = (proc.stdout or "").strip()
        rows = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and parts[0]:
                rows.append({"id": parts[0], "title": parts[1], "url": parts[2]})
        return rows
    except Exception as exc:
        print(f"  [yt] yt-dlp fail for {channel_url}: {exc}", file=sys.stderr)
        return []


def _yt_search(query: str, max_videos: int) -> list[dict]:
    try:
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--flat-playlist",
            "--print", "%(id)s\t%(title)s\t%(webpage_url)s",
            "--no-warnings",
            f"ytsearch{max_videos}:{query}",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, encoding="utf-8")
        rows = []
        for line in (proc.stdout or "").strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and parts[0]:
                rows.append({"id": parts[0], "title": parts[1], "url": parts[2]})
        return rows
    except Exception as exc:
        print(f"  [yt] search fail '{query}': {exc}", file=sys.stderr)
        return []


def _fetch_youtube_items(seeds: dict, per_channel: int) -> list:
    """Seed'deki tum YouTube source'lari icin transkript IngestItem listesi uret."""
    from price_action.rag.ingest import IngestItem, fetch_youtube_transcript

    items: list[IngestItem] = []
    for entry in seeds.get("youtube", []) or []:
        sid = entry.get("id", "")
        stype = entry.get("type", "")
        quality = int(entry.get("quality", 4))
        cats = entry.get("categories", []) or []

        videos: list[dict] = []
        if stype == "channel":
            videos = _yt_dlp_list_videos(entry.get("url", ""), per_channel)
        elif stype == "search":
            videos = _yt_search(entry.get("query", ""), per_channel)
        if not videos:
            print(f"  [yt] {sid}: 0 video bulunamadi")
            continue
        print(f"  [yt] {sid}: {len(videos)} video bulundu, transkript cekiliyor...")
        ok = 0
        for v in videos:
            text = fetch_youtube_transcript(v["id"])
            if not text or len(text) < 800:
                continue
            items.append(
                IngestItem(
                    source_id=f"yt-{v['id']}",
                    source_type="youtube",
                    url=v["url"],
                    title=v["title"],
                    text=text,
                    author=entry.get("name", ""),
                    quality=quality,
                    extra_tags=cats,
                )
            )
            ok += 1
        print(f"  [yt] {sid}: {ok} transkript alindi")
    return items


# ----------------------------------------------------------------------
# Discussion loop
# ----------------------------------------------------------------------

SEED_TOPICS: list[tuple[str, str]] = [
    ("pin_bar_at_sr", "Pin bar at S/R + 1W trend filter (BTC/ETH 1D)"),
    ("engulfing_continuation", "Engulfing bar trend continuation (1D, post-pullback to 20EMA)"),
    ("inside_bar_breakout", "Inside bar breakout vs failure (Brooks 'fakey') on 1D crypto"),
    ("wyckoff_phase_d", "Wyckoff Phase D entry (spring + sign of strength)"),
    ("smc_orderblock", "SMC order block + liquidity grab on 1D crypto"),
    ("htf_filter", "Higher-timeframe (1W) trend filter as veto on 1D pin bar signals"),
    ("sr_retest_after_break", "Support-becomes-resistance retest after structural break"),
    ("range_failure_breakout", "Range failure breakout (false break + reversal)"),
]


async def _agent_call(agent, prompt: str, model: str, *, max_tokens: int = 800) -> dict:
    agent.model = model
    t0 = time.time()
    try:
        resp = await agent.run_full(prompt, max_tokens=max_tokens, temperature=0.3)
        return {
            "ok": True,
            "text": resp.text,
            "in_tok": resp.input_tokens,
            "out_tok": resp.output_tokens,
            "stop": resp.stop_reason,
            "dur_s": round(time.time() - t0, 1),
        }
    except Exception as exc:
        return {
            "ok": False,
            "text": "",
            "err": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc()[:500],
            "dur_s": round(time.time() - t0, 1),
        }


async def _discuss_one_topic(slug: str, topic: str, model: str) -> dict:
    """Tek bir topic icin Researcher + Lab + Analyst + CEO turunu calistir."""
    from price_action.agents.analyst import AnalystAgent
    from price_action.agents.ceo import CEOAgent
    from price_action.agents.lab_scientist import LabScientistAgent
    from price_action.agents.researcher import ResearcherAgent

    print(f"\n=== TOPIC: {slug} — {topic} ===", flush=True)
    out: dict = {"slug": slug, "topic": topic, "started": datetime.now(UTC).isoformat()}

    # 1) Researcher — RAG kullanir
    researcher = ResearcherAgent()
    print("  [1/4] Researcher: hipotez uretiyor (RAG ile)...", flush=True)
    try:
        # propose_hypothesis RAG'i kendisi cagirir
        researcher.model = model
        t0 = time.time()
        hypothesis = await researcher.propose_hypothesis(seed_topic=topic)
        out["researcher"] = {
            "ok": bool(hypothesis.strip()),
            "text": hypothesis,
            "dur_s": round(time.time() - t0, 1),
        }
        print(f"    ok dur={out['researcher']['dur_s']}s len={len(hypothesis)}")
    except Exception as exc:
        out["researcher"] = {"ok": False, "err": f"{type(exc).__name__}: {exc}"}
        print(f"    FAIL {exc}")
        return out

    hypothesis_text = out["researcher"]["text"][:6000]

    # 2) Lab Scientist — overfit / regime / gate
    print("  [2/4] Lab Scientist: overfit + regime + gate kritigi...", flush=True)
    lab = LabScientistAgent()
    lab_prompt = (
        "Asagidaki Researcher hipotezini overfit / regime sensitivity / istatistiksel gate "
        "perspektifinden ELESTIR. Onerilerini madde madde ver: \n"
        "- Hangi gate'ler test edilmeli (Sharpe, MaxDD, walk-forward, shuffle p-value)?\n"
        "- Hangi regime'larda kirilir? (bull/bear/range/high-vol)\n"
        "- Look-ahead/survivorship/data-snooping riski var mi?\n"
        "- Onerilen Bonferroni / multiple-comparison duzeltmesi.\n"
        "Sayisal tabloyla cevap ver. Curve-fit uretme; gozlenebilir curve-fit "
        "kirmizi bayragi varsa kanitla ve adayi reddet.\n\n"
        f"--- HIPOTEZ ---\n{hypothesis_text}"
    )
    out["lab"] = await _agent_call(lab, lab_prompt, model, max_tokens=1200)
    print(f"    {'OK' if out['lab']['ok'] else 'FAIL'} dur={out['lab'].get('dur_s')}s")

    # 3) Analyst — KPI / metrics
    print("  [3/4] Analyst: KPI ve metrik onerisi...", flush=True)
    analyst = AnalystAgent()
    analyst_prompt = (
        "Asagidaki Researcher hipotezi icin **olculebilir KPI seti** oner. "
        "Her KPI icin: tanim, formul, beklenen aralik, ne zaman alarm. "
        "Trade-level (R-multiple dist, MAE/MFE, hold time), "
        "strategy-level (Sharpe, Sortino, MaxDD, Calmar, profit factor), "
        "regime-level (Bull/Bear/Range conditional Sharpe), "
        "robustness (oos_sharpe / is_sharpe ratio, walk-forward dilim oranı).\n\n"
        f"--- HIPOTEZ ---\n{hypothesis_text}"
    )
    out["analyst"] = await _agent_call(analyst, analyst_prompt, model, max_tokens=1000)
    print(f"    {'OK' if out['analyst']['ok'] else 'FAIL'} dur={out['analyst'].get('dur_s')}s")

    # 4) CEO — conservative arbitraj
    print("  [4/4] CEO: conservative arbitraj...", flush=True)
    ceo = CEOAgent()
    ceo_prompt = (
        "Bir trading desk CEO'su olarak ASAGIDAKI hipotezi ve agent kritiklerini tarttip "
        "**3 secenekten birini sec**: PROMOTE_TO_BACKTEST / REVISE / REJECT. "
        "Conservative bias: supheliysen Risk/Lab tarafina yaslan. "
        "Cevabin format:\n"
        "DECISION: <one of three>\n"
        "REASON: <2-3 cumle, sayisal gerekce>\n"
        "CONDITIONS: <varsa Faz 1 backtest icin sart/uyari>\n\n"
        f"--- HIPOTEZ ---\n{hypothesis_text[:3000]}\n\n"
        f"--- LAB KRITIGI ---\n{(out['lab'].get('text') or '')[:2000]}\n\n"
        f"--- ANALYST METRIKLERI ---\n{(out['analyst'].get('text') or '')[:2000]}"
    )
    out["ceo"] = await _agent_call(ceo, ceo_prompt, model, max_tokens=600)
    print(f"    {'OK' if out['ceo']['ok'] else 'FAIL'} dur={out['ceo'].get('dur_s')}s")

    out["finished"] = datetime.now(UTC).isoformat()
    return out


def _write_report(rounds: list[dict], yt_stats: dict, rss_stats: dict | None) -> Path:
    s = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    reports_dir = ROOT / "reports" / "research"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"discussion-{s}.md"

    lines: list[str] = []
    lines.append(f"# Otonom Hipotez Tartismasi — {s}")
    lines.append("")
    lines.append("## Ingest Ozeti")
    lines.append(f"- RSS chunk eklendi   : {rss_stats.get('added_chunks', 'n/a') if rss_stats else 'n/a'}")
    lines.append(f"- YouTube videolari   : {yt_stats.get('videos', 0)}")
    lines.append(f"- YouTube chunk eklendi: {yt_stats.get('added_chunks', 0)}")
    lines.append("")
    # Karar ozeti
    lines.append("## Karar Ozeti")
    lines.append("")
    lines.append("| # | Topic | CEO Karari |")
    lines.append("|---|---|---|")
    import re as _re
    _decision_re = _re.compile(
        r"DECISION\s*[:\*]+\s*\*?\*?\s*(PROMOTE_TO_BACKTEST|REVISE|REJECT)",
        _re.IGNORECASE,
    )
    for i, r in enumerate(rounds, 1):
        ceo_text = (r.get("ceo", {}).get("text") or "")
        m = _decision_re.search(ceo_text)
        decision = m.group(1).upper() if m else "?"
        lines.append(f"| {i} | {r['slug']} — {r['topic']} | {decision} |")
    lines.append("")

    # Detay
    for i, r in enumerate(rounds, 1):
        lines.append(f"## {i}. {r['slug']} — {r['topic']}")
        lines.append("")

        for role in ("researcher", "lab", "analyst", "ceo"):
            section = r.get(role, {})
            label = role.upper()
            if not section.get("ok"):
                lines.append(f"### {label}\n*FAIL*: {section.get('err', 'no result')}")
                lines.append("")
                continue
            dur = section.get("dur_s", "?")
            in_tok = section.get("in_tok", "?")
            out_tok = section.get("out_tok", "?")
            lines.append(f"### {label} _(dur={dur}s, in={in_tok}, out={out_tok})_")
            lines.append("")
            lines.append(section.get("text", "").strip())
            lines.append("")
        lines.append("---")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


async def main() -> int:
    os.environ.setdefault("PA_LLM_USE_CLI", "true")
    os.environ.pop("PA_LLM_DRY_RUN", None)

    model = os.getenv("PA_RESEARCH_MODEL", "claude-haiku-4-5")
    yt_per_channel = int(os.getenv("PA_YOUTUBE_PER_CHANNEL", "8"))
    started = datetime.now(UTC).isoformat()
    print(f"[research] started={started} model={model} yt_per_channel={yt_per_channel}", flush=True)

    # === A) YouTube ingest ===
    print("\n[research] A) YouTube ingest", flush=True)
    yt_stats = {"videos": 0, "added_chunks": 0}
    try:
        from price_action.rag.ingest import ingest_items, load_seeds

        seeds = load_seeds()
        yt_items = _fetch_youtube_items(seeds, per_channel=yt_per_channel)
        yt_stats["videos"] = len(yt_items)
        if yt_items:
            stats = ingest_items(yt_items, seeds)
            yt_stats["added_chunks"] = stats.get("added_chunks", 0)
            yt_stats["passed"] = stats.get("passed", 0)
            print(f"[research] YouTube: {len(yt_items)} video, {yt_stats['added_chunks']} chunk", flush=True)
        else:
            print("[research] YouTube: 0 video (network/rate-limit?)", flush=True)
    except Exception as exc:
        print(f"[research] YouTube ingest FAIL: {exc}\n{traceback.format_exc()[:600]}", flush=True)

    # === B) Discussion loop ===
    print("\n[research] B) Discussion loop", flush=True)
    rounds: list[dict] = []
    for slug, topic in SEED_TOPICS:
        try:
            r = await _discuss_one_topic(slug, topic, model)
        except Exception as exc:
            r = {
                "slug": slug,
                "topic": topic,
                "error": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc()[:600],
            }
            print(f"  TOPIC FAIL: {exc}", flush=True)
        rounds.append(r)
        # Ara dump (script erken oldurulurse veri kaybetme)
        dump_path = ROOT / "reports" / "research" / f"_partial-{slug}.json"
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        dump_path.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")

    # === C) Report ===
    print("\n[research] C) Rapor yaziliyor", flush=True)
    rss_stats = None  # ilk ingest'i ana terminalden yapmistik; bu run'da skip
    report_path = _write_report(rounds, yt_stats, rss_stats)
    print(f"[research] OK rapor: {report_path}", flush=True)
    print(f"[research] finished={datetime.now(UTC).isoformat()}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
