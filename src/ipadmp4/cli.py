"""Command-line entry point.

`main(argv)` parses arguments and wraps `_run(...)` in the single
Ipadmp4Error boundary; `_run` takes plain values and returns an exit code, so
tests can call it without subprocesses or sys.exit.

A run has two phases: first every file is inspected and every question is
asked, then all encodes run unattended.
"""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

from .command import Options, build_command, describe
from .discover import Job, collect, normalize_extension
from .errors import Ipadmp4Error
from .plan import Asker, Plan, Session, plan_file
from .probe import probe
from .tracks import MediaInfo

EPILOG = """\
examples:
  ipadmp4 movie.mkv              English 5.1 audio, English subtitles
  ipadmp4 *.mkv                  several files: questions first, then encoding
  ipadmp4 -i movie.mkv           choose audio and subtitle tracks yourself
  ipadmp4 -r ~/Movies/trip       all videos in a folder tree
  ipadmp4 -n movie.mkv           show the ffmpeg command, convert nothing

Surround audio is kept for Spatial Audio: AC-3/E-AC-3 is copied, anything
else becomes AC-3 5.1. Subtitles become a text track that is on by default
and can be switched off in the TV app. H.264/HEVC video is copied; other
video is encoded to HEVC with the hardware encoder.
"""


@dataclass(frozen=True)
class Task:
    src: Path
    dst: Path
    info: MediaInfo
    plan: Plan


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ipadmp4",
        description="Convert movies (MKV) to MP4 for the iPad TV app: surround audio, toggleable subtitles.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("paths", nargs="+", type=Path, metavar="PATH", help="movie files or directories")
    parser.add_argument(
        "-i", "--interactive", action="store_true", help="choose the audio and subtitle tracks for each file"
    )
    parser.add_argument("-r", "--recursive", action="store_true", help="convert videos in directories, recursively")
    parser.add_argument(
        "-e",
        "--ext",
        action="append",
        metavar="EXT",
        help="only convert files with this extension (repeatable; default for directories: all video formats)",
    )
    parser.add_argument("-o", "--output-dir", type=Path, help="write MP4s here instead of next to the originals")
    parser.add_argument("-n", "--dry-run", action="store_true", help="print the ffmpeg commands without running them")
    parser.add_argument("-f", "--force", action="store_true", help="overwrite existing MP4 files")
    parser.add_argument("--reencode", action="store_true", help="re-encode video even if it could be copied")
    parser.add_argument("-v", "--verbose", action="store_true", help="show full ffmpeg output")
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('ipadmp4')}")
    return parser


def main(argv: list[str] | None = None, asker: Asker | None = None) -> int:
    # Flush each status line, so it isn't printed after ffmpeg's own output.
    sys.stdout.reconfigure(line_buffering=True)
    args = _build_parser().parse_args(argv)
    extensions = frozenset(normalize_extension(e) for e in args.ext) if args.ext else None
    try:
        return _run(
            args.paths,
            recursive=args.recursive,
            extensions=extensions,
            output_dir=args.output_dir,
            dry_run=args.dry_run,
            force=args.force,
            session=Session(interactive=args.interactive),
            asker=asker or Asker(),
            opts=Options(reencode=args.reencode, verbose=args.verbose),
        )
    except Ipadmp4Error as e:
        print(f"ipadmp4: error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


def _run(
    paths: list[Path],
    *,
    recursive: bool,
    extensions: frozenset[str] | None,
    output_dir: Path | None,
    dry_run: bool,
    force: bool,
    session: Session,
    asker: Asker,
    opts: Options,
) -> int:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise Ipadmp4Error(f"{tool} not found (install it with: brew install ffmpeg)")

    jobs, errors = collect(paths, recursive=recursive, extensions=extensions)
    for msg in errors:
        print(f"ipadmp4: {msg}", file=sys.stderr)
    if not jobs:
        if not errors:
            print("ipadmp4: no video files found", file=sys.stderr)
        return 1

    tasks, skipped, failed = _plan_all(jobs, output_dir, force, session, asker)
    failed += len(errors)

    if tasks and len(jobs) > 1 and not dry_run:
        print(f"\nAll set. Converting {len(tasks)} file(s), no more questions.\n")
    converted = 0
    for n, task in enumerate(tasks, 1):
        print(f"[{n}/{len(tasks)}] {task.src} -> {task.dst} ({describe(task.info, task.plan, opts)})")
        if dry_run:
            print(shlex.join(build_command(task.src, task.dst, task.info, task.plan, opts, overwrite=force)))
            converted += 1
        elif _convert(task, opts):
            converted += 1
        else:
            print(f"[{n}/{len(tasks)}] FAILED {task.src}: ffmpeg reported an error", file=sys.stderr)
            failed += 1

    verb = "would convert" if dry_run else "converted"
    print(f"Done: {converted} {verb}, {skipped} skipped, {failed} failed.")
    return 1 if failed else 0


def _plan_all(
    jobs: list[Job], output_dir: Path | None, force: bool, session: Session, asker: Asker
) -> tuple[list[Task], int, int]:
    """Inspect every file and settle every question up front."""
    tasks: list[Task] = []
    skipped = failed = 0
    planned: dict[Path, Path] = {}  # output -> the source that claimed it

    for n, job in enumerate(jobs, 1):
        src = job.src
        dst = _output_path(job, output_dir)
        prefix = f"[{n}/{len(jobs)}]"

        key = dst.resolve()
        if key == src.resolve():
            print(f"{prefix} skip {src}: already an MP4")
            skipped += 1
            continue
        if key in planned:
            print(f"{prefix} skip {src}: {dst} is already produced from {planned[key]}", file=sys.stderr)
            skipped += 1
            continue
        planned[key] = src
        if dst.exists() and not force:
            print(f"{prefix} skip {src}: {dst} already exists")
            skipped += 1
            continue

        try:
            info = probe(src)
        except Ipadmp4Error as e:
            print(f"{prefix} FAILED {src}: {e}", file=sys.stderr)
            failed += 1
            continue
        if info.video is None:
            print(f"{prefix} FAILED {src}: no video stream", file=sys.stderr)
            failed += 1
            continue

        print(f"{prefix} {src}")
        plan = plan_file(src.name, info, session, asker, remaining=len(jobs) - n)
        if plan is None:
            print(f"{prefix} skip {src}")
            skipped += 1
            continue
        print(f"  -> {plan.summary()}")
        tasks.append(Task(src=src, dst=dst, info=info, plan=plan))
    return tasks, skipped, failed


def _output_path(job: Job, output_dir: Path | None) -> Path:
    if output_dir is None:
        return job.src.with_suffix(".mp4")
    return (output_dir / job.rel).with_suffix(".mp4")


def _convert(task: Task, opts: Options) -> bool:
    """Run ffmpeg into `dst.part` and rename it to `dst` only on success.

    A finished `dst` therefore always is a complete file: an interrupted or
    failed run leaves at most a `.part` file, which is removed.
    """
    dst = task.dst
    part = dst.with_name(dst.name + ".part")
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_command(task.src, part, task.info, task.plan, opts, overwrite=True)
    try:
        result = subprocess.run(cmd, stdin=subprocess.DEVNULL)
    except KeyboardInterrupt:
        part.unlink(missing_ok=True)
        print(f"\nInterrupted; removed incomplete {part}", file=sys.stderr)
        raise SystemExit(130) from None
    if result.returncode != 0:
        part.unlink(missing_ok=True)
        return False
    part.replace(dst)
    return True


if __name__ == "__main__":
    sys.exit(main())
