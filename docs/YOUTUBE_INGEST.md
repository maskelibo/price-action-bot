# YouTube Transcript Ingest

## Why We Need This

The RAG corpus is the backbone of hypothesis generation in this system. Without rich,
domain-specific content, the Researcher agent produces generic hypotheses that lack
the precise vocabulary and conceptual depth of Brooks/Grimes price-action methodology.

YouTube transcripts from Al Brooks and Adam Grimes provide:

- **Brooks**: bar-by-bar reading, tight-channel breakouts, two-legged pullbacks, always-in
  concepts, and detailed pattern taxonomy — thousands of hours of highly specific PA content
  that is not easily replicated from blog posts.
- **Grimes**: disciplined statistical framing, regime awareness, behavioral-finance integration
  with PA, and rigorous trade management — a "scientific" counterbalance to Brooks' subjective
  feel.
- **Academic searches** (Jim Simons / RenTec talks, market microstructure lectures): calibrates
  the Lab Scientist's critique with real quantitative finance grounding.

Without these transcripts, the RAG store relies only on book summaries and RSS feeds, which
means hypothesis quality is significantly lower.

---

## Why Cookies Are Needed

YouTube's bot-detection blocks automated transcript fetching at scale. `youtube_transcript_api`
works without login for many public videos but fails silently when YouTube rate-limits the IP
or blocks the request. `yt-dlp --cookies-from-browser` was attempted but fails on this machine
because:

- **Chrome**: SQLite database is locked by a running Chrome instance (SQLITE_BUSY).
- **Edge**: DPAPI decryption fails outside of the user's Windows session context.

The robust workaround is a manually exported **Netscape-format cookies.txt** that yt-dlp
accepts directly.

---

## Manual Step: Export cookies.txt

1. Install the **"Get cookies.txt LOCALLY"** extension in Chrome:
   [Chrome Web Store link](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)

2. Open [https://www.youtube.com](https://www.youtube.com) in Chrome (you may be logged in
   or not — being logged in typically gets better rate limits).

3. Click the extension icon in the toolbar → click **"Export"**.

4. Save the downloaded file as:
   ```
   C:\Users\koray\projeler\Price Action\.cache\youtube_cookies.txt
   ```

> The `.cache/` directory is already in `.gitignore`. The cookies file will **never** be
> committed to the repository.

---

## Running the Ingest

### Prerequisites

```powershell
pip install yt-dlp youtube-transcript-api
```

Both packages should already be installed if you ran the project setup.

### Dry-run preview (no network calls)

```powershell
$env:PA_YT_DRY_RUN="true"; $env:PYTHONPATH="src"; python scripts/ingest_youtube.py
```

Or on bash/WSL:

```bash
PA_YT_DRY_RUN=true PYTHONPATH=src python scripts/ingest_youtube.py
```

Expected output (sample):

```
============================================================
YouTube Transcript Ingest
[DRY-RUN] Gercek network cagirisi YAPILMAYACAK.
============================================================

[dry-run] Planli kaynaklar:
  KANAL  [brooks_yt] Al Brooks Trading — ilk 30 video
  KANAL  [grimes_yt] Adam Grimes — ilk 20 video
  ARAMA  [jp_quant_research] 'Jim Simons Renaissance Technologies lecture' — ilk 10 video
  ARAMA  [trading_microstructure_lectures] 'market microstructure lecture algorithmic trading' — ilk 10 video

[dry-run] would fetch ~70 videos total (2 channel(s), 2 search(es))
[dry-run] Gercek ingest icin PA_YT_DRY_RUN cikarip PA_YT_COOKIES=.cache/youtube_cookies.txt ayarlayin.
```

### Real ingest (after cookies.txt is ready)

```powershell
$env:PA_YT_COOKIES=".cache/youtube_cookies.txt"
$env:PYTHONPATH="src"
python scripts/ingest_youtube.py
```

Or on bash/WSL:

```bash
PA_YT_COOKIES=.cache/youtube_cookies.txt PYTHONPATH=src python scripts/ingest_youtube.py
```

### Tuning video counts

| Env var             | Default | Effect                                   |
|---------------------|---------|------------------------------------------|
| `PA_YT_MAX_BROOKS`  | 30      | Max videos pulled from Al Brooks channel |
| `PA_YT_MAX_GRIMES`  | 20      | Max videos pulled from Adam Grimes channel |
| `PA_YT_MAX_SEARCH`  | 10      | Max videos per search query              |

---

## Transcript Fallback Strategy

For each video, the script tries two methods in order:

1. **`youtube_transcript_api`** — fast, no authentication required, uses YouTube's
   official transcript endpoint. Fails when YouTube blocks the IP or the video has
   no auto-generated captions.

2. **`yt-dlp --write-auto-sub --sub-format vtt`** — downloads the WebVTT subtitle file
   to a temp directory, strips timestamps and HTML tags, deduplicates repeated lines
   (common in YouTube auto-subs), and returns plain text. Requires cookies when
   youtube_transcript_api fails due to bot-detection.

Videos with fewer than 100 words of transcript are discarded. Items entering the RAG
pipeline still need to pass `ingest.quality_filter` (minimum 500 words, quality >= 3).

---

## Caveats / Known Issues

- **Rate limiting**: Pulling 70 videos in one run may trigger a temporary YouTube IP ban
  (usually 1–24 hours). If this happens, reduce `PA_YT_MAX_BROOKS` / `PA_YT_MAX_GRIMES`
  and run in batches across multiple days.

- **Cookie expiry**: YouTube cookies expire after 1–2 weeks (sometimes sooner after a
  password change). Re-export from the extension if you start seeing 403 errors.

- **Auto-caption quality**: YouTube's auto-generated captions for financial content
  frequently mishear trading terms ("pine bar" vs "pin bar", "Wyckoff" vs "why cough").
  The RAG chunker preserves the raw text; downstream LLM context handles most
  mis-transcriptions gracefully, but very garbled transcripts may slip through the
  500-word quality filter rather than being caught by semantic checks.

- **Search result non-determinism**: `ytsearch10:Jim Simons Renaissance Technologies lecture`
  returns YouTube's current ranking, which changes over time. The same run on two different
  days may return partially different video sets.

- **Concurrent autonomous_research.py**: Do not run this script at the same time as
  `autonomous_research.py` — both write to the same ChromaDB RAG store and the SQLite
  WAL may conflict. Run this ingest first, then let autonomous research pick up the
  richer corpus.
