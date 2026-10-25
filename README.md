# money

Claude skills and research notes.

## watch-video skill

Lets Claude "watch" YouTube / TikTok / Instagram / X videos or podcast episodes: it pulls metadata, a timestamped transcript (platform subtitles, or Whisper when there are none) and frame contact sheets, then summarizes or answers questions about them.

- Skill: [`.claude/skills/watch-video/SKILL.md`](.claude/skills/watch-video/SKILL.md)
- Script: [`.claude/skills/watch-video/scripts/watch_video.py`](.claude/skills/watch-video/scripts/watch_video.py)

### Use it

- **Claude Code (cloud or local):** open a session with this repo. The skill loads automatically from `.claude/skills/`. Run `./setup.sh` once to install dependencies (`ffmpeg`, `yt-dlp`, `faster-whisper`), then paste a video link: «شوف الفيديو ده ولخصهولي».
- **Use it everywhere on your own machine:** `cp -r .claude/skills/watch-video ~/.claude/skills/`

### Notes

- YouTube and TikTok often block cloud servers ("Sign in to confirm you're not a bot"). Workarounds:
  - Run Claude on your own computer (Claude Desktop or `claude remote-control`).
  - Pass `--cookies cookies.txt`, exported from a browser logged in to a secondary Google account.
  - Use the podcast fallback described in SKILL.md.
- Cloud sessions need network access set to **Full**, or the domains listed in SKILL.md allowed.
