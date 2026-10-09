# ipadmp4

Convert movies (usually MKV) to MP4 for the iPad's TV app: surround sound
for Spatial Audio on AirPods, and subtitles you can switch on and off.
Replaces the Handbrake preset. Sibling of `tomp4`.

Requires `ffmpeg` (`brew install ffmpeg`).

## Usage

```sh
ipadmp4 movie.mkv              # English 5.1 audio, English subtitles
ipadmp4 *.mkv                  # several files: all questions first, then encoding
ipadmp4 -i movie.mkv           # choose the audio and subtitle tracks yourself
ipadmp4 -r ~/Movies/trip       # all videos in a folder tree
ipadmp4 -n movie.mkv           # show the ffmpeg command, convert nothing
```

`movie.mkv` becomes `movie.mp4` next to it, or in the configured output
folder (see below), or under `-o DIR`. Existing MP4s are skipped unless
`--force` is given.

At the end, a summary lists every file: what was converted and where the MP4
was written (with size and time taken), and what was skipped or failed and
why.

## Settings

Optional, in `~/.config/ipadmp4/config.toml` (or
`$XDG_CONFIG_HOME/ipadmp4/config.toml`):

```toml
# Where MP4s go; default: next to the originals.
output_dir = "~/Movies/iPad"
```

`~` and `$VARIABLES` are expanded; the folder is created when needed.
`-o DIR` overrides the setting for one run, `--next-to-source` ignores it.
Unknown settings are reported as errors, so typos don't go unnoticed.

## Questions come first

All files are inspected and every question is answered before the first
encode starts, so a batch never stops halfway to wait for you.

Questions are asked when:

- `-i` is given: pick audio and subtitles for every file (the automatic
  choice is the default, so Enter accepts it);
- a file has no English audio track or no English subtitles;
- the subtitles are only images (see below).

After a question, `ipadmp4` offers to use the same languages for all
remaining files. Say yes to keep e.g. Japanese audio with English subtitles
for a whole season without being asked again. At any track question, `s`
skips the file.

## Track selection

**Audio:** one track, in English by default. Most channels win (7.1 and 5.1
count the same), then AC-3/E-AC-3 (copied as-is), then the file's default
track. Commentary and audio-description tracks are never picked
automatically. A file whose only audio track has no language tag gets that
track.

**Subtitles:** one track, English, full subtitles (forced-only tracks are
ignored): regular English before English SDH, text before image, tracks inside
the movie before separate files. The subtitle track is **on by default** and
can be switched off in the TV app.

Separate subtitle files next to the movie are found too: `Movie.srt`,
`Movie.en.srt`, `Movie.English.SDH.srt`, `Movie.de.srt`, ... A file without a
language in its name counts as English. Non-UTF-8 files are read as Windows
Latin-1 (CP1252).

**Image subtitles** (PGS from Blu-rays, VobSub from DVDs) can't be a
switchable track in an MP4. When those are the only ones, you choose: burn
them in (always visible; the video gets re-encoded), no subtitles, another
track, or skip the file.

## How it converts

| Input | Result |
| --- | --- |
| H.264 (8-bit, 4:2:0), HEVC | copied (instant, lossless); HEVC tagged `hvc1` |
| other video (10-bit H.264, MPEG-2, VC-1, ...) | HEVC, hardware encoder (`hevc_videotoolbox -q:v 70`), 10-bit kept |
| AC-3 / E-AC-3 surround (incl. Atmos) | copied |
| other surround (DTS, TrueHD, AAC 5.1, ...) | AC-3 5.1 640k (7.1 is downmixed) |
| stereo / mono AAC, AC-3, MP3 | copied |
| other stereo / mono | AAC 192k |
| subtitles (SRT, ASS, ...) | `mov_text` text track, default on, language-tagged |
| everything else | dropped |

Chapters and metadata (title) are kept. AC-3/E-AC-3 surround is used because
Apple's player reliably plays it with Spatial Audio; reports for
multichannel AAC are mixed.

Options: `--reencode` (re-encode video even if it could be copied), `-v`
(full ffmpeg output).

## Safety

- ffmpeg writes to `name.mp4.part`, renamed to `name.mp4` only after a
  successful conversion. A failed or interrupted (Ctrl-C) conversion leaves
  nothing behind.
- The exit code is non-zero if any file failed; the run ends with a summary.

## Development

```sh
uv run pytest
uv run ruff check . && uv run ruff format --check .
```
