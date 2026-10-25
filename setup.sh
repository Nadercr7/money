#!/usr/bin/env bash
# Installs what the watch-video skill needs. Safe to re-run.
set -e
if ! command -v ffmpeg >/dev/null; then
  (sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg) || apt-get install -y -qq ffmpeg || brew install ffmpeg
fi
python3 -m pip install -q -U "yt-dlp[default,curl-cffi]" faster-whisper youtube-transcript-api
echo "watch-video deps ready"
