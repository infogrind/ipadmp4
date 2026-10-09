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

With `-r`, a directory is scanned recursively for videos, e.g. a whole
series with its season folders. An output folder is always flat: all MP4s
land directly in it, without recreating the source's subfolders. Should two
sources have the same file name, only the first is converted and the other is
reported as skipped.

At the end, a summary lists every file: what was converted and where the MP4
was written (with size and time taken), and what was skipped or failed and
why.

## Settings

Optional, in `~/.config/ipadmp4/config.toml` (or
`$XDG_CONFIG_HOME/ipadmp4/config.toml`):

```toml
# Where MP4s go; default: next to the originals.
output_dir = "~/Movies/iPad"
# Embed the file name as cover art (see below); default: true.
cover_art = true
```

`~` and `$VARIABLES` are expanded; the folder is created when needed.
`-o DIR` overrides the setting for one run, `--next-to-source` ignores it.
`--cover-art` / `--no-cover-art` override `cover_art`.
Unknown settings are reported as errors, so typos don't go unnoticed.

## Picking files with fzf

`ipadmp4` itself only takes paths. To pick movies, episodes or whole season
folders interactively from your library, put a small picker in front of it.
This [fish](https://fishshell.com) function lists folders and video files
under a root directory with [`fd`](https://github.com/sharkdp/fd), lets you
select several with [`fzf`](https://github.com/junegunn/fzf) (TAB), and passes
them to `ipadmp4 -r`:

```sh
ipadpick ~/Movies                          # pick under ~/Movies, convert
ipadpick ~/Movies -o ~/Desktop/trip -i     # extra arguments go to ipadmp4
```

Videos under 200 MB are not listed, which keeps samples out. Save this as
`~/.config/fish/functions/ipadpick.fish` (needs `brew install fd fzf`):

```fish
function ipadpick --description 'Pick videos/folders under ROOT with fzf and convert them with ipadmp4'
    if test (count $argv) -lt 1; or not test -d "$argv[1]"
        echo "usage: ipadpick ROOT [ipadmp4 options...]" >&2
        echo "  e.g. ipadpick ~/Movies -o ~/Desktop/trip -i" >&2
        return 2
    end
    set -l root (path resolve -- $argv[1])
    # Paths relative to ROOT, so fzf matches movie/series names, not the prefix.
    set -l picked (begin
            fd --type d --base-directory $root .     # folders: a movie, a season, a series
            fd --type f -e mkv -e avi -e mp4 -e mov --size +200m --base-directory $root .   # big videos only: no samples
        end | fzf --multi --prompt "ipadmp4 $root> " \
                --preview "ls -lh -- "(string escape -- $root)"/{}" \
                --header 'TAB: select several, ENTER: convert')
    test -n "$picked"; or return
    ipadmp4 -r $argv[2..] $root/$picked
end
```

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

Chapters and metadata are kept, except the title: the TV app displays the
MP4's title, so it is set to the file name without extension
(`Heat.1995.1080p.mkv` shows as "Heat.1995.1080p").

**Cover art:** the TV app on iPadOS shows only thumbnails, no names. So each
MP4 gets the file name, in bold white on black, as embedded cover art (an
iTunes `covr` tag), meant to become its thumbnail. The video itself is still
copied, not re-encoded. The image is drawn with macOS's AppKit via
`osascript`; if that fails, the file is converted without cover art and a
warning is shown. AC-3/E-AC-3 surround is used because
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
