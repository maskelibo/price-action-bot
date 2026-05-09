"""Curated YouTube transcript ingest — no yt-dlp needed.

Uses youtube-transcript-api v1.2.4+ directly with hardcoded, verified video IDs.
Adds a configurable delay between requests to avoid IP bans.

Curated video list covers:
  - Al Brooks (classic price action)
  - Adam Grimes (art & science of technical analysis)
  - Wyckoff method educators

Usage:
    PYTHONPATH=src python scripts/ingest_youtube_curated.py

Env vars:
    PA_YT_DELAY_SEC   : seconds between API calls (default 5)
    PA_YT_DRY_RUN     : "true" -> no network calls, just list videos
    PA_YT_MIN_WORDS   : minimum word count to pass filter (default 500)
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# ---------------------------------------------------------------------------
# Curated video list — verified via direct API test on 2025-05-09
# Each entry: (video_id, author_key, author_name, title, quality, categories)
# ---------------------------------------------------------------------------
CURATED_VIDEOS: list[tuple[str, str, str, str, int, list[str]]] = [
    # Al Brooks — classic price action
    (
        "sO5NZ9L3n14",
        "al_brooks", "Al Brooks",
        "Al Brooks Trading Room Open House November 2024",
        5, ["classic_pa", "price_action"],
    ),
    (
        "Zw2_bc69euU",
        "al_brooks", "Al Brooks",
        "Master Price Action From The Best - Al Brooks Interview",
        5, ["classic_pa", "price_action"],
    ),
    (
        "GwEtBdh9sEY",
        "al_brooks", "Al Brooks",
        "Price Action Trading Expert - Al Brooks Interview",
        5, ["classic_pa", "price_action"],
    ),
    (
        "xhAle897TXo",
        "al_brooks", "Al Brooks",
        "Mastering Price Action Trading Will Make You Profitable - Al Brooks",
        5, ["classic_pa", "price_action"],
    ),
    (
        "DEm9TTKxNH8",
        "al_brooks", "Al Brooks",
        "Al Brooks: The Legend of Price Action - Bible of Day Trading",
        5, ["classic_pa", "price_action"],
    ),
    (
        "N-kr7PTO_wU",
        "al_brooks", "Al Brooks",
        "The GOAT Teaches Price Action - Al Brooks Episode 5",
        5, ["classic_pa", "price_action"],
    ),
    (
        "KBXnfay-BQE",
        "al_brooks", "Al Brooks",
        "The Best Price Action Trader In The World - Al Brooks Interview",
        5, ["classic_pa", "price_action"],
    ),
    (
        "RsQ2WBZVjUQ",
        "al_brooks", "Al Brooks",
        "The Godfather of Price Action Trading - Speculators Podcast",
        5, ["classic_pa", "price_action"],
    ),
    # Adam Grimes — art & science of technical analysis
    (
        "ZHoPjGvQk4Y",
        "adam_grimes", "Adam Grimes",
        "Consistently Profitable Mindset and Trading Techniques - Adam Grimes",
        5, ["classic_pa", "trading_psychology"],
    ),
    (
        "Wuzh5_pWK78",
        "adam_grimes", "Adam Grimes",
        "The Secret Art and Science of Technical Trading - Adam Grimes",
        5, ["classic_pa", "trading_psychology"],
    ),
    (
        "EnA6RlKMRnI",
        "adam_grimes", "Adam Grimes",
        "FP Markets Webinar: How to Trade US Markets with Discretionary Systems",
        5, ["classic_pa", "trading_psychology"],
    ),
    (
        "Tz_l1OBJRK4",
        "adam_grimes", "Adam Grimes",
        "How to Identify a Trading Edge and the Realistic Path of a Trader",
        5, ["classic_pa", "trading_psychology"],
    ),
    (
        "_5Q1x5Ejcy8",
        "adam_grimes", "Adam Grimes",
        "The Art and Science of Technical Analysis - Adam Grimes",
        5, ["classic_pa", "trading_psychology"],
    ),
    (
        "dfRPZfkrDKk",
        "adam_grimes", "Adam Grimes",
        "Hand Traders vs System Traders - Adam Grimes Interview",
        5, ["classic_pa", "trading_psychology"],
    ),
    (
        "WP5eCBFZo3o",
        "adam_grimes", "Adam Grimes",
        "Building Your Trading Edge in Any Financial Market - Adam Grimes",
        5, ["classic_pa", "trading_psychology"],
    ),
    (
        "-RzXLy2SPC4",
        "adam_grimes", "Adam Grimes",
        "Why Trading Can Be So Challenging and What to Do - Adam Grimes",
        5, ["classic_pa", "trading_psychology"],
    ),
    # Wyckoff method
    (
        "8sbfrusR5Eo",
        "wyckoff", "Wyckoff Method",
        "The Ultimate Wyckoff Trading Course",
        4, ["structure", "classic_pa"],
    ),
    (
        "bUk2essMH2A",
        "wyckoff", "Wyckoff Method",
        "All Wyckoff Trading Secrets in 73 Minutes - Complete Method",
        4, ["structure", "classic_pa"],
    ),
    (
        "NfiQ-0aooB0",
        "wyckoff", "Wyckoff Method",
        "Analyzing and Trading Markets Using the Wyckoff Trading Method",
        4, ["structure", "classic_pa"],
    ),
    (
        "6vcpxOKdJaE",
        "wyckoff", "Wyckoff Method",
        "The Wyckoff Method - A Beginners Guide",
        4, ["structure", "classic_pa"],
    ),
    (
        "ergVw_5MkmM",
        "wyckoff", "Wyckoff Method",
        "How SMC and ICT Secretly Copied the Wyckoff Trading Method",
        4, ["structure", "classic_pa"],
    ),
    (
        "_WmJooGKDuw",
        "wyckoff", "Wyckoff Method",
        "Wyckoff Method Explained in 10 Minutes - Simplified",
        4, ["structure", "classic_pa"],
    ),
    (
        "jqvTQ6-D0Dw",
        "wyckoff", "Wyckoff Method",
        "Wyckoff Trading Method Point and Figure Tutorial Part 1",
        4, ["structure", "classic_pa"],
    ),
    (
        "aHO5R0q-5FY",
        "wyckoff", "Wyckoff Method",
        "The Wyckoff Method Explained: Path to Trading Mastery (Power Charting)",
        4, ["structure", "classic_pa"],
    ),
]


def _fetch_transcript(video_id: str, delay: float = 5.0) -> str | None:
    """Fetch transcript for one video. Returns text or None on failure."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
    except ImportError:
        print("[ERROR] youtube-transcript-api not installed. Run: pip install youtube-transcript-api", file=sys.stderr)
        sys.exit(1)

    if delay > 0:
        time.sleep(delay)

    try:
        api = YouTubeTranscriptApi()
        transcript = api.fetch(video_id, languages=["en", "en-US", "en-GB"])
        return "\n".join(s.text for s in transcript)
    except Exception as exc:
        err_type = type(exc).__name__
        err_msg = str(exc)
        if "blocked" in err_msg.lower() or "429" in err_msg or "IpBlocked" in err_type or "RequestBlocked" in err_type:
            print(f"  [BLOCKED] {video_id}: YouTube IP ban active — {err_type}", file=sys.stderr)
        else:
            print(f"  [ERR] {video_id}: {err_type}: {err_msg[:100]}", file=sys.stderr)
        return None


def main() -> int:
    dry_run = os.getenv("PA_YT_DRY_RUN", "").lower() in ("1", "true", "yes")
    delay = float(os.getenv("PA_YT_DELAY_SEC", "5"))
    min_words = int(os.getenv("PA_YT_MIN_WORDS", "500"))

    # Windows: force utf-8 stdout
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
        except Exception:
            pass

    print("=" * 60)
    print("YouTube Curated Transcript Ingest")
    print(f"  Videos: {len(CURATED_VIDEOS)} curated entries")
    print(f"  Delay between requests: {delay}s")
    print(f"  Min word count: {min_words}")
    if dry_run:
        print("  [DRY-RUN] No network calls will be made.")
    print("=" * 60)

    if dry_run:
        for vid_id, author_key, author_name, title, quality, cats in CURATED_VIDEOS:
            print(f"  [{author_key}] {vid_id} — {title}")
        print(f"\n[dry-run] Would attempt {len(CURATED_VIDEOS)} videos.")
        return 0

    # Real fetch
    from price_action.rag.ingest import IngestItem, ingest_items, load_seeds

    try:
        seeds = load_seeds()
    except Exception as exc:
        print(f"[ERROR] Cannot load seeds.yaml: {exc}", file=sys.stderr)
        return 1

    items: list[Any] = []
    ok_count = 0
    err_count = 0
    skip_count = 0
    blocked = False

    for i, (vid_id, author_key, author_name, title, quality, cats) in enumerate(CURATED_VIDEOS, 1):
        print(f"[{i:2d}/{len(CURATED_VIDEOS)}] {vid_id} - {title[:60]}", flush=True)

        text = _fetch_transcript(vid_id, delay=delay)

        if text is None:
            err_count += 1
            # Check if we hit a block — if so, stop to avoid wasting time
            # (error already printed by _fetch_transcript)
            blocked = True
            print(f"         -> FAILED", flush=True)
            continue

        words = len(text.split())
        if words < min_words:
            print(f"         -> SKIP ({words} words < {min_words} min)", flush=True)
            skip_count += 1
            continue

        print(f"         -> OK ({words:,} words)", flush=True)
        ok_count += 1
        items.append(
            IngestItem(
                source_id=f"yt-{vid_id}",
                source_type="youtube",
                url=f"https://www.youtube.com/watch?v={vid_id}",
                title=title,
                text=text,
                author=author_name,
                quality=quality,
                extra_tags=cats,
            )
        )

    print(f"\n--- Fetch phase complete ---")
    print(f"  OK: {ok_count}  SKIP (too short): {skip_count}  FAILED: {err_count}")

    if blocked and ok_count == 0:
        print(
            "\n[BLOCKED] All requests were blocked by YouTube."
            "\nThe IP is temporarily banned. Options:"
            "\n  1. Wait 10-30 minutes and re-run."
            "\n  2. Use a VPN or proxy: set PA_YT_PROXY=http://host:port"
            "\n  3. Install cookies via browser extension and set PA_YT_COOKIES",
            file=sys.stderr,
        )
        return 1

    if not items:
        print("[WARN] No items to ingest.")
        return 0

    # Ingest into RAG
    print(f"\n[ingest] Sending {len(items)} items to RAG pipeline...", flush=True)
    try:
        stats = ingest_items(items, seeds)
    except Exception as exc:
        print(f"[ERROR] ingest_items failed: {exc}", file=sys.stderr)
        return 1

    print("\n" + "=" * 60)
    print("INGEST COMPLETE")
    print(f"  Transcripts fetched    : {ok_count}")
    print(f"  Too short (skipped)    : {skip_count}")
    print(f"  Fetch errors           : {err_count}")
    print(f"  Items into RAG pipe    : {stats['received']}")
    print(f"  Passed quality filter  : {stats['passed']}")
    print(f"  Rejected               : {stats['rejected']}")
    print(f"  RAG chunks added       : {stats['added_chunks']}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
