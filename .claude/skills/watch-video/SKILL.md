---
name: watch-video
description: "Watch" a YouTube, YouTube Shorts, TikTok, Instagram Reel, X or any yt-dlp-supported video from a URL — pulls metadata, a timestamped transcript (platform subtitles, or Whisper speech-to-text when none exist) and sampled frames as 3x3 contact sheets, then summarizes, answers questions, or analyzes it. Use whenever the user shares a video link or asks to watch / summarize / analyze / transcribe a video, in any language (e.g. "شوف الفيديو ده", "لخصلي الفيديو").
---

# watch-video

Claude cannot stream video, so this skill converts a video into text + images Claude can read:

- `README.md` — title, uploader, duration, views, description, file index
- `metadata.json` — full metadata
- `transcript.txt` — `[mm:ss] text` lines (subtitles if the platform has them, otherwise Whisper)
- `contact_sheet_NN.jpg` — 3x3 grids of frames with timestamps burned in (the cheap way to "see" the video)
- `frames/frame_NNN_mm-ss.jpg` — individual frames for close-ups

## Run it

The script sits next to this file in `scripts/watch_video.py` (in a repo: `.claude/skills/watch-video/scripts/`, user-level: `~/.claude/skills/watch-video/scripts/`). Use its absolute path:

```bash
python3 <skill-dir>/scripts/watch_video.py "<URL>" --out <dir>
```

First run in a fresh environment: run `setup.sh` from the repo root if it exists (installs ffmpeg, yt-dlp with TikTok impersonation, faster-whisper).

Options:
- `--max-frames N` (default 27 = 3 contact sheets). Shorts/TikToks: 9–18 is enough. Long videos (>20 min): 36–45.
- `--no-frames` — transcript only; skips the video download when subtitles exist (fastest, for "what does he say" questions).
- `--lang ar,en` — preferred subtitle languages (the video's original language is always tried first).
- `--model small` — Whisper size. `base` is faster. For Egyptian/Arabic dialect `small` garbles names and numbers; use `medium` (or `large-v3`) when accuracy matters and you can wait (~1x–2x real-time on 4 CPU cores). Always tell the user which numbers came from a shaky transcript.
- `--force-whisper` — ignore platform subtitles (use when auto-captions are garbage).
- `--cookies cookies.txt` — for age-restricted videos or "Sign in to confirm you're not a bot".

The script installs `yt-dlp` / `faster-whisper` with pip if they are missing; `ffmpeg` must already exist.
Print the JSON it outputs at the end — it lists the out dir and contact sheet paths.

## Then actually watch it

1. Read `README.md` and `transcript.txt`.
2. Read **every** `contact_sheet_*.jpg` with the Read tool (images). Match timestamps on the sheets to transcript lines so visuals and speech line up.
3. Open individual `frames/` only when you need detail (on-screen text, code, a product, a face).
4. Answer in the user's language. Cite timestamps (`[03:12]`) so they can jump there.

Never pretend to have seen something that isn't in the frames or transcript; say what you could not tell (e.g. music, tone of voice, motion between sampled frames).

## Saving tokens with subagents

Video work is mostly mechanical, so hand it to cheaper models when the Agent tool is available:

- **One video:** run the script yourself (one Bash call), then if the transcript is long (>~400 lines) spawn a `haiku` agent to summarize `transcript.txt` into timestamped sections while you read the contact sheets.
- **Several videos / a channel / a TikTok list:** spawn one `haiku` agent per video, in parallel, each told: run the script on URL X with `--out <dir>`, read README + transcript + all contact sheets, return a ≤300-word summary with timestamps and anything visually notable. Use `sonnet` instead when the analysis needs judgment (comparing arguments, critiquing a video, extracting code or steps accurately). Then merge their summaries yourself.
- Give each agent the absolute script path and absolute out dir; agents do not share your context.

## Troubleshooting

- `CONNECT tunnel failed, response 403` / connection refused → the environment's network policy blocks the host. Needed domains: `youtube.com`, `*.youtube.com`, `youtu.be`, `*.googlevideo.com`, `*.ytimg.com`, `*.tiktok.com`, `*.tiktokcdn.com`, `*.tiktokcdn-us.com`, `*.tiktokv.com`, `*.ibyteimg.com`, `*.byteoversea.com`, `huggingface.co`, `*.huggingface.co`, `*.hf.co` (Whisper models) plus package managers (pip).
- `Sign in to confirm you're not a bot`, media `HTTP Error 403`, or a redirect to `google.com/sorry` → YouTube is blocking the server's (cloud) IP; this also breaks `youtube-transcript-api`. `pip install -U yt-dlp` first; if it persists, ask the user for a `cookies.txt` exported from a logged-in browser (extension "Get cookies.txt LOCALLY") and pass `--cookies`. When subtitles download but the media 403s, the script continues transcript-only. **Podcast fallback (works well):** many creators (e.g. الدحيح) publish the same episode as a podcast. Find the show's Apple id via web search, then `curl "https://itunes.apple.com/lookup?id=<id>"` → `feedUrl` → RSS `<enclosure url>` mp3 → `curl -L -o ep.mp3 URL` → run the script on the local file (`--no-frames`) to Whisper it. Last resort: find a transcript/summary on the web, and tell the user that's what you used.
- TikTok: install `pip install "yt-dlp[default,curl-cffi]"` for impersonation. yt-dlp often can't list a profile page (`@user`) — find individual `/video/<id>` URLs instead (web search, or `curl -sL -A "Mozilla/5.0" https://www.tiktok.com/@user | grep -o 'video/[0-9]*'`). TikToks rarely have subtitles, so expect Whisper.
- Video too long / slow Whisper → use `--no-frames` when subs exist, or `--model base`.
- If the URL fails entirely, ask the user to upload the video file; run the same steps (ffmpeg frames + whisper) on the local file — the script also accepts a local file path as the URL.
