"""Standalone YouTube transcript ingest script.

Cookies stratejisi (sirayla denenir):
  1. PA_YT_COOKIES env var -> Netscape-format cookies.txt dosyasi
  2. --cookies-from-browser chrome
  3. --cookies-from-browser firefox
  4. Hicbiri yoksa hatali cikis

Kanallar ve aramalar seeds.yaml'dan okunur; yoksa hardcoded fallback kullanilir.

Calistirma:
    # Gercek ingest (cookies.txt hazir olduktan sonra):
    PA_YT_COOKIES=.cache/youtube_cookies.txt PYTHONPATH=src python scripts/ingest_youtube.py

    # Kuru calistirma (network cagirisi yok):
    PA_YT_DRY_RUN=true PYTHONPATH=src python scripts/ingest_youtube.py

Env degiskenleri:
    PA_YT_COOKIES      : Netscape cookies.txt yolu (opsiyonel)
    PA_YT_DRY_RUN      : "true" ise network cagirisi yapilmaz
    PA_YT_MAX_BROOKS   : Al Brooks icin max video sayisi  (default 30)
    PA_YT_MAX_GRIMES   : Adam Grimes icin max video sayisi (default 20)
    PA_YT_MAX_SEARCH   : Arama basina max video sayisi    (default 10)
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

# -----------------------------------------------------------------
# Path bootstrap — src/ modulleri import edebilmek icin
# -----------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# -----------------------------------------------------------------
# Sabitler / varsayilan seed listesi
# -----------------------------------------------------------------

HARDCODED_CHANNELS: list[dict[str, Any]] = [
    {
        "id": "brooks_yt",
        "name": "Al Brooks Trading",
        "type": "channel",
        "url": "https://www.youtube.com/@BrooksPriceAction",
        "categories": ["classic_pa"],
        "quality": 5,
        "max_videos_key": "PA_YT_MAX_BROOKS",
        "max_videos_default": 30,
    },
    {
        "id": "grimes_yt",
        "name": "Adam Grimes",
        "type": "channel",
        "url": "https://www.youtube.com/@AdamHGrimes",
        "categories": ["classic_pa", "trading_psychology"],
        "quality": 5,
        "max_videos_key": "PA_YT_MAX_GRIMES",
        "max_videos_default": 20,
    },
]

HARDCODED_SEARCHES: list[dict[str, Any]] = [
    {
        "id": "jp_quant_research",
        "name": "Jim Simons / RenTec talks",
        "type": "search",
        "query": "Jim Simons Renaissance Technologies lecture",
        "categories": ["quant_finance"],
        "quality": 5,
        "max_videos_key": "PA_YT_MAX_SEARCH",
        "max_videos_default": 10,
    },
    {
        "id": "trading_microstructure_lectures",
        "name": "Market Microstructure lectures",
        "type": "search",
        "query": "market microstructure lecture algorithmic trading",
        "categories": ["market_microstructure"],
        "quality": 4,
        "max_videos_key": "PA_YT_MAX_SEARCH",
        "max_videos_default": 10,
    },
]

# -----------------------------------------------------------------
# Cookies / auth yardimcilari
# -----------------------------------------------------------------


def _resolve_cookies() -> list[str]:
    """yt-dlp icin --cookies veya --cookies-from-browser arguman listesi dondurur.

    Oncelik:
      1. PA_YT_COOKIES env var -> Netscape cookies.txt
      2. --cookies-from-browser chrome
      3. --cookies-from-browser firefox
      4. Kookisiz devam et (public video'lar icin yeterli olabilir)
    """
    env_path = os.getenv("PA_YT_COOKIES", "").strip()
    if env_path:
        p = Path(env_path)
        if not p.is_absolute():
            p = ROOT / p
        if p.exists():
            print(f"[cookies] cookies.txt kullaniliyor: {p}", flush=True)
            return ["--cookies", str(p)]
        else:
            print(
                f"[cookies] UYARI: PA_YT_COOKIES={env_path} mevcut degil! "
                "Browser fallback'e geciliyor.",
                file=sys.stderr,
                flush=True,
            )

    for browser in ("chrome", "firefox"):
        probe = subprocess.run(
            [
                sys.executable, "-m", "yt_dlp",
                f"--cookies-from-browser", browser,
                "--flat-playlist",
                "--print", "%(id)s",
                "--playlist-end", "1",
                "--skip-download",
                "--no-warnings",
                "--quiet",
                "https://www.youtube.com/",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
        )
        if probe.returncode == 0:
            print(f"[cookies] --cookies-from-browser {browser} calisiyor.", flush=True)
            return ["--cookies-from-browser", browser]
        else:
            print(
                f"[cookies] --cookies-from-browser {browser} basarisiz: "
                f"{(probe.stderr or '').strip()[:120]}",
                file=sys.stderr,
                flush=True,
            )

    print(
        "[cookies] Kookie bulunamadi. Kimlik dogrulamasi olmadan devam edilecek.\n"
        "  Cozum: .cache/youtube_cookies.txt dosyasini olusturun ve\n"
        "  PA_YT_COOKIES=.cache/youtube_cookies.txt olarak ayarlayin.",
        file=sys.stderr,
        flush=True,
    )
    return []  # kooksiz dene — public videolar icin calisabilir


# -----------------------------------------------------------------
# yt-dlp sarmalayicilari
# -----------------------------------------------------------------


def _yt_dlp_list_channel(channel_url: str, max_videos: int, cookie_args: list[str]) -> list[dict]:
    """Kanal URL'inden video listesi dondurur [{id, title, url}]."""
    url_with_tab = (
        channel_url + "/videos"
        if "@" in channel_url and not channel_url.endswith("/videos")
        else channel_url
    )
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--flat-playlist",
        "--print", "%(id)s\t%(title)s\t%(webpage_url)s",
        "--playlist-end", str(max_videos),
        "--skip-download",
        "--no-warnings",
        "--quiet",
        *cookie_args,
        url_with_tab,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, encoding="utf-8"
        )
        rows: list[dict] = []
        for line in (proc.stdout or "").strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and parts[0]:
                rows.append({"id": parts[0], "title": parts[1], "url": parts[2]})
        if proc.returncode != 0 and not rows:
            print(
                f"  [yt] kanal liste hatasi ({channel_url}): "
                f"{(proc.stderr or '').strip()[:200]}",
                file=sys.stderr,
            )
        return rows
    except subprocess.TimeoutExpired:
        print(f"  [yt] timeout: {channel_url}", file=sys.stderr)
        return []
    except Exception as exc:
        print(f"  [yt] yt-dlp fail ({channel_url}): {exc}", file=sys.stderr)
        return []


def _yt_dlp_search(query: str, max_videos: int, cookie_args: list[str]) -> list[dict]:
    """YouTube aramasiyla video listesi dondurur [{id, title, url}]."""
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--flat-playlist",
        "--print", "%(id)s\t%(title)s\t%(webpage_url)s",
        "--no-warnings",
        "--quiet",
        *cookie_args,
        f"ytsearch{max_videos}:{query}",
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, encoding="utf-8"
        )
        rows: list[dict] = []
        for line in (proc.stdout or "").strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and parts[0]:
                rows.append({"id": parts[0], "title": parts[1], "url": parts[2]})
        if proc.returncode != 0 and not rows:
            print(
                f"  [yt] arama hatasi ('{query}'): "
                f"{(proc.stderr or '').strip()[:200]}",
                file=sys.stderr,
            )
        return rows
    except subprocess.TimeoutExpired:
        print(f"  [yt] timeout: {query}", file=sys.stderr)
        return []
    except Exception as exc:
        print(f"  [yt] search fail ('{query}'): {exc}", file=sys.stderr)
        return []


# -----------------------------------------------------------------
# VTT -> duz metin donusturucu
# -----------------------------------------------------------------

_VTT_TIMESTAMP = re.compile(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->")
_VTT_TAG = re.compile(r"<[^>]+>")
_VTT_ALIGN = re.compile(r"^(WEBVTT|Kind:|Language:|align:|position:|NOTE).*$", re.MULTILINE)


def _vtt_to_text(vtt_content: str) -> str:
    """WebVTT icerigini duz metne cevir (tekrar satirlari birlestir)."""
    lines: list[str] = []
    seen: set[str] = set()
    for raw_line in vtt_content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _VTT_TIMESTAMP.match(line):
            continue
        if _VTT_ALIGN.match(line):
            continue
        # HTML taglerini temizle
        line = _VTT_TAG.sub("", line).strip()
        if not line:
            continue
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return " ".join(lines)


# -----------------------------------------------------------------
# Transkript cekme — iki katmanli fallback
# -----------------------------------------------------------------


def _fetch_transcript_api(video_id: str, *, delay: float = 3.0) -> str:
    """youtube_transcript_api ile transkript cekmek icin birincil yontem.

    v1.2.4+ API degisikligi: get_transcript() kaldirildi, fetch() kullanilmali.
    `delay` saniye bekletme — ard arda cok istek yapilinca YouTube IP banlama
    uygular; her cagri arasinda kisa bir bekleme bunu onler.
    """
    import time
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore[import-not-found]
    except ImportError:
        return ""
    try:
        if delay > 0:
            time.sleep(delay)
        api = YouTubeTranscriptApi()
        transcript = api.fetch(video_id, languages=["en", "en-US", "en-GB"])
        return "\n".join(s.text for s in transcript)
    except Exception:
        return ""


def _fetch_transcript_ytdlp(video_id: str, cookie_args: list[str]) -> str:
    """yt-dlp --write-auto-sub ile VTT subtitle indirip metne cevir."""
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory(prefix="pa_yt_") as tmpdir:
        out_tmpl = str(Path(tmpdir) / "%(id)s")
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--write-auto-sub",
            "--skip-download",
            "--sub-format", "vtt",
            "--sub-langs", "en",
            "--output", out_tmpl,
            "--no-warnings",
            "--quiet",
            *cookie_args,
            video_url,
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=90, encoding="utf-8"
            )
        except (subprocess.TimeoutExpired, Exception) as exc:
            print(f"    [vtt] yt-dlp subtitle fail ({video_id}): {exc}", file=sys.stderr)
            return ""

        # Indirilen .vtt dosyasini bul
        vtt_files = list(Path(tmpdir).glob("*.vtt"))
        if not vtt_files:
            return ""
        try:
            content = vtt_files[0].read_text(encoding="utf-8", errors="ignore")
            return _vtt_to_text(content)
        except Exception as exc:
            print(f"    [vtt] parse fail ({video_id}): {exc}", file=sys.stderr)
            return ""


def fetch_transcript(video: dict, cookie_args: list[str]) -> str:
    """Birincil (youtube_transcript_api) ve yedek (yt-dlp VTT) ile transkript al."""
    vid_id = video["id"]

    # Oncelik 1: youtube_transcript_api (hizli, auth gerektirmez)
    text = _fetch_transcript_api(vid_id)
    if text and len(text.split()) >= 100:
        return text

    # Oncelik 2: yt-dlp subtitle fallback
    text = _fetch_transcript_ytdlp(vid_id, cookie_args)
    return text


# -----------------------------------------------------------------
# Seeds okuma
# -----------------------------------------------------------------


def _load_sources() -> tuple[list[dict], list[dict]]:
    """seeds.yaml'daki YouTube kaynaklarini oku; yoksa hardcoded fallback."""
    try:
        from price_action.rag.ingest import load_seeds  # type: ignore[import-not-found]

        seeds = load_seeds()
        yt_entries: list[dict] = seeds.get("youtube", []) or []
        if not yt_entries:
            raise ValueError("seeds.yaml icinde youtube kismi bos")

        channels: list[dict] = []
        searches: list[dict] = []
        for entry in yt_entries:
            entry = dict(entry)  # kopya
            if entry.get("type") == "channel":
                if "max_videos_default" not in entry:
                    entry["max_videos_default"] = int(
                        os.getenv("PA_YT_MAX_BROOKS", "30")
                        if "brooks" in entry.get("id", "").lower()
                        else os.getenv("PA_YT_MAX_GRIMES", "20")
                    )
                channels.append(entry)
            elif entry.get("type") == "search":
                if "max_videos_default" not in entry:
                    entry["max_videos_default"] = int(os.getenv("PA_YT_MAX_SEARCH", "10"))
                searches.append(entry)
        print(
            f"[seeds] seeds.yaml'dan {len(channels)} kanal, {len(searches)} arama yuklendi.",
            flush=True,
        )
        return channels, searches
    except Exception as exc:
        print(
            f"[seeds] seeds.yaml yuklenemedi ({exc}), hardcoded fallback kullaniliyor.",
            file=sys.stderr,
            flush=True,
        )
        # Hardcoded fallback — max_videos env'den oku
        channels = []
        for ch in HARDCODED_CHANNELS:
            ch = dict(ch)
            ch["max_videos_default"] = int(os.getenv(ch.get("max_videos_key", ""), str(ch["max_videos_default"])))
            channels.append(ch)
        searches = []
        for sr in HARDCODED_SEARCHES:
            sr = dict(sr)
            sr["max_videos_default"] = int(os.getenv(sr.get("max_videos_key", ""), str(sr["max_videos_default"])))
            searches.append(sr)
        return channels, searches


# -----------------------------------------------------------------
# Ana is akisi
# -----------------------------------------------------------------


def main() -> int:  # noqa: PLR0912, PLR0915
    dry_run = os.getenv("PA_YT_DRY_RUN", "").lower() in ("1", "true", "yes")

    print("=" * 60, flush=True)
    print("YouTube Transcript Ingest", flush=True)
    if dry_run:
        print("[DRY-RUN] Gercek network cagirisi YAPILMAYACAK.", flush=True)
    print("=" * 60, flush=True)

    # Kaynaklari yukle
    channels, searches = _load_sources()

    total_expected = sum(
        int(os.getenv(ch.get("max_videos_key", ""), str(ch["max_videos_default"])))
        for ch in channels
    ) + sum(
        int(os.getenv(sr.get("max_videos_key", ""), str(sr["max_videos_default"])))
        for sr in searches
    )

    if dry_run:
        print(f"\n[dry-run] Planli kaynaklar:", flush=True)
        for ch in channels:
            n = int(os.getenv(ch.get("max_videos_key", ""), str(ch["max_videos_default"])))
            print(f"  KANAL  [{ch['id']}] {ch['name']} — ilk {n} video", flush=True)
        for sr in searches:
            n = int(os.getenv(sr.get("max_videos_key", ""), str(sr["max_videos_default"])))
            print(f"  ARAMA  [{sr['id']}] {sr['name']!r} — ilk {n} video", flush=True)
        print(
            f"\n[dry-run] would fetch ~{total_expected} videos total "
            f"({len(channels)} channel(s), {len(searches)} search(es))",
            flush=True,
        )
        print(
            "[dry-run] Gercek ingest icin PA_YT_DRY_RUN cikarip "
            "PA_YT_COOKIES=.cache/youtube_cookies.txt ayarlayin.",
            flush=True,
        )
        return 0

    # --- Gercek ingest yolu ---
    cookie_args = _resolve_cookies()

    # seeds'e erisim
    try:
        from price_action.rag.ingest import load_seeds, ingest_items, IngestItem  # type: ignore[import-not-found]
        seeds = load_seeds()
    except Exception as exc:
        print(f"[HATA] seeds/ingest yuklenemedi: {exc}", file=sys.stderr)
        return 1

    all_items: list[Any] = []
    videos_found = 0
    transcripts_ok = 0

    # --- Kanal videolari ---
    for ch in channels:
        max_v = int(os.getenv(ch.get("max_videos_key", ""), str(ch["max_videos_default"])))
        print(f"\n[kanal] {ch['name']} — {ch['url']} (max {max_v})", flush=True)
        videos = _yt_dlp_list_channel(ch["url"], max_v, cookie_args)
        if not videos:
            print(f"  0 video bulundu — atlanıyor.", flush=True)
            continue
        videos_found += len(videos)
        print(f"  {len(videos)} video bulundu, transkriptler cekiliyor...", flush=True)
        ok = 0
        for v in videos:
            text = fetch_transcript(v, cookie_args)
            if not text or len(text.split()) < 100:
                continue
            try:
                item = IngestItem(
                    source_id=f"yt-{v['id']}",
                    source_type="youtube",
                    url=v["url"],
                    title=v["title"],
                    text=text,
                    author=ch.get("name", ""),
                    quality=int(ch.get("quality", 4)),
                    extra_tags=list(ch.get("categories", [])),
                )
                all_items.append(item)
                ok += 1
            except Exception as exc:
                print(f"    [item] olusturma hatasi ({v['id']}): {exc}", file=sys.stderr)
        transcripts_ok += ok
        print(f"  {ok}/{len(videos)} transkript alindi.", flush=True)

    # --- Arama sonuclari ---
    for sr in searches:
        max_v = int(os.getenv(sr.get("max_videos_key", ""), str(sr["max_videos_default"])))
        print(f"\n[arama] '{sr['query']}' — max {max_v}", flush=True)
        videos = _yt_dlp_search(sr["query"], max_v, cookie_args)
        if not videos:
            print(f"  0 video bulundu — atlanıyor.", flush=True)
            continue
        videos_found += len(videos)
        print(f"  {len(videos)} video bulundu, transkriptler cekiliyor...", flush=True)
        ok = 0
        for v in videos:
            text = fetch_transcript(v, cookie_args)
            if not text or len(text.split()) < 100:
                continue
            try:
                item = IngestItem(
                    source_id=f"yt-{v['id']}",
                    source_type="youtube",
                    url=v["url"],
                    title=v["title"],
                    text=text,
                    author=sr.get("name", ""),
                    quality=int(sr.get("quality", 4)),
                    extra_tags=list(sr.get("categories", [])),
                )
                all_items.append(item)
                ok += 1
            except Exception as exc:
                print(f"    [item] olusturma hatasi ({v['id']}): {exc}", file=sys.stderr)
        transcripts_ok += ok
        print(f"  {ok}/{len(videos)} transkript alindi.", flush=True)

    # --- Ingest ---
    print(f"\n[ingest] Toplam: {len(all_items)} item ingest pipeline'a giriyor...", flush=True)
    ingested_chunks = 0
    passed = 0
    if all_items:
        try:
            stats = ingest_items(all_items, seeds)
            ingested_chunks = stats.get("added_chunks", 0)
            passed = stats.get("passed", 0)
        except Exception as exc:
            print(f"[ingest] HATA: {exc}", file=sys.stderr)

    # --- Final rapor ---
    print("\n" + "=" * 60, flush=True)
    print("YOUTUBE INGEST TAMAMLANDI", flush=True)
    print(f"  Bulunan video    : {videos_found}", flush=True)
    print(f"  Transkript alindi: {transcripts_ok}", flush=True)
    print(f"  Kalite filtresinden gecen item : {passed}", flush=True)
    print(f"  RAG'a eklenen chunk : {ingested_chunks}", flush=True)
    print("=" * 60, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
