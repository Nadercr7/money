#!/usr/bin/env python3
"""Turn a YouTube / TikTok (or any yt-dlp supported) video into things Claude can read:
metadata, a timestamped transcript, and sampled frames + contact sheets.

Usage:
  watch_video.py URL [--out DIR] [--max-frames N] [--lang ar,en] [--model small]
                     [--force-whisper] [--no-frames] [--cookies FILE]
"""
import argparse
import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys


def log(msg):
    print(f"[watch-video] {msg}", file=sys.stderr, flush=True)


def run(cmd, check=True):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed:\n{p.stderr[-2000:]}")
    return p


def ensure_deps():
    missing = [t for t in ("yt-dlp", "ffmpeg", "ffprobe") if not shutil.which(t)]
    if "yt-dlp" in missing:
        log("installing yt-dlp ...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "yt-dlp"], check=False)
        missing = [t for t in ("yt-dlp", "ffmpeg", "ffprobe") if not shutil.which(t)]
    if missing:
        sys.exit(f"missing tools: {', '.join(missing)} (install ffmpeg / yt-dlp)")


def fmt_ts(sec):
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def ytdlp_base(args):
    base = ["yt-dlp", "--no-playlist", "--no-warnings", "--retries", "3"]
    if args.cookies:
        base += ["--cookies", args.cookies]
    return base


# ---------- metadata ----------

def fetch_info(args):
    p = run(ytdlp_base(args) + ["-J", args.url])
    return json.loads(p.stdout)


# ---------- subtitles ----------

def parse_vtt(path):
    """Return list of (start_seconds, text), de-duplicating YouTube's rolling auto-captions."""
    out, last = [], ""
    start = None
    ts_re = re.compile(r"(\d+):(\d+):(\d+)[.,](\d+)\s+-->")
    ts_re2 = re.compile(r"(\d+):(\d+)[.,](\d+)\s+-->")
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            m = ts_re.match(line) or ts_re2.match(line)
            if m:
                g = [int(x) for x in m.groups()]
                start = g[0] * 3600 + g[1] * 60 + g[2] if len(g) == 4 else g[0] * 60 + g[1]
                continue
            if not line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")) or line.isdigit():
                continue
            text = re.sub(r"<[^>]+>", "", line).strip()
            if not text or text == last:
                continue
            last = text
            out.append((start or 0, text))
    # second pass: drop lines fully contained in the previous one (rolling captions)
    cleaned = []
    for s, t in out:
        if cleaned and t in cleaned[-1][1]:
            continue
        cleaned.append((s, t))
    return cleaned


def get_subtitles(args, info, work):
    langs = args.lang
    has_manual = bool(info.get("subtitles"))
    has_auto = bool(info.get("automatic_captions"))
    if not (has_manual or has_auto):
        return None, None
    orig = info.get("language")
    lang_list = ([orig] if orig else []) + langs.split(",")
    sub_langs = ",".join(dict.fromkeys(l + suf for l in lang_list for suf in ("", ".*", "-orig")))
    cmd = ytdlp_base(args) + ["--skip-download", "--sub-format", "vtt/best", "--convert-subs", "vtt",
                              "--sub-langs", sub_langs, "-o", os.path.join(work, "subs.%(ext)s")]
    cmd += ["--write-subs"] if has_manual else []
    cmd += ["--write-auto-subs"] if has_auto else []
    run(cmd + [args.url], check=False)
    files = sorted(glob.glob(os.path.join(work, "subs*.vtt")))
    if not files:
        return None, None
    # prefer: original language, then manual over auto (manual files are written first), then requested order
    def rank(f):
        code = f.split("subs.")[-1].rsplit(".vtt", 1)[0]
        for i, l in enumerate(lang_list):
            if code == l or code.startswith(l + "-") or code == l + "-orig":
                return i
        return 99
    best = min(files, key=rank)
    segs = parse_vtt(best)
    code = best.split("subs.")[-1].rsplit(".vtt", 1)[0]
    return (segs or None), f"subtitles ({code})"


# ---------- download ----------

def download_video(args, work):
    out_tmpl = os.path.join(work, "video.%(ext)s")
    fmt = "bv*[height<=480]+ba/b[height<=480]/bv*[height<=720]+ba/b[height<=720]/b"
    run(ytdlp_base(args) + ["-f", fmt, "--merge-output-format", "mp4", "-o", out_tmpl, args.url])
    files = [f for f in glob.glob(os.path.join(work, "video.*")) if not f.endswith(".part")]
    if not files:
        raise RuntimeError("video download produced no file")
    return files[0]


def probe_duration(path):
    p = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path], check=False)
    try:
        return float(p.stdout.strip())
    except ValueError:
        return 0.0


# ---------- transcription ----------

def whisper_transcribe(video, work, model_name):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        log("installing faster-whisper ...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "faster-whisper"], check=False)
        from faster_whisper import WhisperModel
    import numpy as np
    # decode with ffmpeg ourselves: faster-whisper's PyAV decoder breaks on some av versions
    pcm = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", video, "-vn", "-f", "s16le",
                          "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000", "-"],
                         capture_output=True, check=True).stdout
    audio = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0
    log(f"transcribing with whisper '{model_name}' (CPU) ...")
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, info = model.transcribe(audio, vad_filter=True, beam_size=1)
    segs = [(s.start, s.text.strip()) for s in segments if s.text.strip()]
    return segs, f"whisper-{model_name} (detected language: {info.language}, p={info.language_probability:.2f})"


# ---------- frames ----------

def extract_frames(video, duration, frames_dir, max_frames):
    os.makedirs(frames_dir, exist_ok=True)
    if duration <= 0:
        duration = 60
    interval = max(1.0, duration / max_frames)
    # sample at even intervals, offset by half an interval to avoid black first frames
    times = [min(duration - 0.1, interval * (i + 0.5)) for i in range(max_frames)]
    times = [t for t in times if t >= 0]
    frames = []
    for i, t in enumerate(times):
        path = os.path.join(frames_dir, f"frame_{i + 1:03d}_{fmt_ts(t).replace(':', '-')}.jpg")
        p = run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1",
                 "-vf", "scale='min(768,iw)':-2", "-q:v", "4", path], check=False)
        if p.returncode == 0 and os.path.exists(path):
            frames.append((t, path))
    return frames, interval


def make_contact_sheets(frames, out_dir, per_sheet=9):
    """3x3 grids with timestamps burned in — cheap way to 'see' the whole video."""
    sheets = []
    font = next((f for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                             "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf") if os.path.exists(f)), None)
    for n in range(math.ceil(len(frames) / per_sheet)):
        chunk = frames[n * per_sheet:(n + 1) * per_sheet]
        inputs, filters = [], []
        for i, (t, path) in enumerate(chunk):
            inputs += ["-i", path]
            label = fmt_ts(t).replace(":", r"\:")
            draw = (f",drawtext=text='{label}':x=8:y=8:fontsize=28:fontcolor=white:box=1:boxcolor=black@0.6"
                    + (f":fontfile={font}" if font else ""))
            # fixed 400x300 tiles (letterboxed) so xstack gets uniform inputs; works for 9:16 TikToks too
            filters.append(f"[{i}:v]scale=400:300:force_original_aspect_ratio=decrease,"
                           f"pad=400:300:(ow-iw)/2:(oh-ih)/2{draw}[v{i}]")
        cols = min(3, len(chunk))
        layout = "|".join(f"{(i % cols) * 400}_{(i // cols) * 300}" for i in range(len(chunk)))
        stack = "".join(f"[v{i}]" for i in range(len(chunk)))
        fc = ";".join(filters) + (f";{stack}xstack=inputs={len(chunk)}:layout={layout}:fill=black[out]"
                                  if len(chunk) > 1 else ";[v0]null[out]")
        path = os.path.join(out_dir, f"contact_sheet_{n + 1:02d}.jpg")
        p = run(["ffmpeg", "-y", "-v", "error"] + inputs + ["-filter_complex", fc, "-map", "[out]",
                                                          "-q:v", "4", path], check=False)
        if p.returncode == 0:
            sheets.append((chunk[0][0], chunk[-1][0], path))
        else:
            log(f"contact sheet {n + 1} failed: {p.stderr[-300:]}")
    return sheets


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out", default=None, help="output directory (default: ./video_<id>)")
    ap.add_argument("--max-frames", type=int, default=27)
    ap.add_argument("--lang", default="ar,en", help="preferred subtitle languages, comma separated")
    ap.add_argument("--model", default="small", help="whisper model: tiny/base/small/medium/large-v3")
    ap.add_argument("--force-whisper", action="store_true", help="ignore platform subtitles")
    ap.add_argument("--no-frames", action="store_true", help="transcript only (no video download if subs exist)")
    ap.add_argument("--cookies", default=None, help="cookies.txt for age/bot-gated videos")
    args = ap.parse_args()

    ensure_deps()
    local = os.path.isfile(args.url)
    if local:
        args.url = os.path.abspath(args.url)
        name = os.path.splitext(os.path.basename(args.url))[0]
        info = {"id": name, "title": name, "webpage_url": args.url, "extractor_key": "local file",
                "duration": probe_duration(args.url)}
    else:
        log("fetching metadata ...")
        info = fetch_info(args)
    vid = re.sub(r"[^\w-]", "_", str(info.get("id", "video")))
    out = os.path.abspath(args.out or f"video_{vid}")
    work = os.path.join(out, "_work")
    os.makedirs(work, exist_ok=True)

    meta = {k: info.get(k) for k in ("id", "title", "uploader", "channel", "upload_date", "duration",
                                     "view_count", "like_count", "comment_count", "description",
                                     "tags", "webpage_url", "extractor_key", "language")}
    with open(os.path.join(out, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    segs, source = (None, None)
    if not args.force_whisper and not local:
        log("looking for subtitles ...")
        segs, source = get_subtitles(args, info, work)

    video = args.url if local else None
    need_video = (not args.no_frames) or segs is None
    if need_video and not local:
        log("downloading video ...")
        try:
            video = download_video(args, work)
        except RuntimeError as e:
            if segs is None:
                raise
            # YouTube often 403s / bot-checks cloud IPs for media but still serves subtitles
            log(f"video download failed, continuing transcript-only: {str(e).strip().splitlines()[-1]}")
    duration = info.get("duration") or (probe_duration(video) if video else 0)

    if segs is None:
        segs, source = whisper_transcribe(video, work, args.model)

    with open(os.path.join(out, "transcript.txt"), "w", encoding="utf-8") as f:
        for s, t in segs:
            f.write(f"[{fmt_ts(s)}] {t}\n")

    frames, sheets, interval = [], [], 0
    if video and not args.no_frames:
        log("extracting frames ...")
        frames, interval = extract_frames(video, duration, os.path.join(out, "frames"), args.max_frames)
        sheets = make_contact_sheets(frames, out)

    # README for whoever reads the output next
    lines = [f"# {meta.get('title')}", "",
             f"- URL: {meta.get('webpage_url')}",
             f"- Platform: {meta.get('extractor_key')} | Uploader: {meta.get('uploader') or meta.get('channel')}",
             f"- Duration: {fmt_ts(duration)} | Uploaded: {meta.get('upload_date')} | Views: {meta.get('view_count')}",
             f"- Transcript source: {source} — {len(segs)} lines → transcript.txt", ""]
    if sheets:
        lines.append(f"## Contact sheets (3x3 grids, one frame every ~{interval:.0f}s, timestamps top-left)")
        lines += [f"- {os.path.basename(p)}  ({fmt_ts(a)} → {fmt_ts(b)})" for a, b, p in sheets]
        lines += ["", f"Individual frames ({len(frames)}) are in frames/ — open one for detail.", ""]
    desc = (meta.get("description") or "").strip()
    if desc:
        lines += ["## Description", desc[:1500], ""]
    with open(os.path.join(out, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    shutil.rmtree(work, ignore_errors=True)
    print(json.dumps({"out_dir": out, "title": meta.get("title"), "duration": duration,
                      "transcript_source": source, "transcript_lines": len(segs),
                      "frames": len(frames), "contact_sheets": [p for _, _, p in sheets]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
