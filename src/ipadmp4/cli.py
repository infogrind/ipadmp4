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
import time
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

from .command import Options, build_command, describe
from .config import config_path, load_config
from .discover import collect, normalize_extension
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

Settings: {config}
  output_dir = "~/Movies/iPad"   default for -o
"""

CONVERTED = "converted"
WOULD_CONVERT = "would convert"
SKIPPED = "skipped"
FAILED = "FAILED"


@dataclass(frozen=True)
class Task:
    src: Path
    dst: Path
    info: MediaInfo
    plan: Plan


@dataclass(frozen=True)
class Result:
    """What happened to one input, for the summary at the end."""

    src: Path
    status: str
    dst: Path | None = None
    detail: str = ""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ipadmp4",
        description="Convert movies (MKV) to MP4 for the iPad TV app: surround audio, toggleable subtitles.",
        epilog=EPILOG.format(config=config_path()),
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
    where = parser.add_mutually_exclusive_group()
    where.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        help="write MP4s here (default: output_dir setting, else next to the originals)",
    )
    where.add_argument(
        "--next-to-source", action="store_true", help="write MP4s next to the originals, ignoring output_dir"
    )
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
        output_dir = args.output_dir
        if output_dir is None and not args.next_to_source:
            output_dir = load_config(config_path()).output_dir
        return _run(
            args.paths,
            recursive=args.recursive,
            extensions=extensions,
            output_dir=output_dir,
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

    tasks, results = _plan_all(jobs, output_dir, force, session, asker)

    if tasks and len(jobs) > 1 and not dry_run:
        print(f"\nAll set. Converting {len(tasks)} file(s), no more questions.\n")
    for n, task in enumerate(tasks, 1):
        print(f"[{n}/{len(tasks)}] {task.src} -> {task.dst} ({describe(task.info, task.plan, opts)})")
        if dry_run:
            print(shlex.join(build_command(task.src, task.dst, task.info, task.plan, opts, overwrite=force)))
            results.append(Result(task.src, WOULD_CONVERT, task.dst))
            continue
        started = time.monotonic()
        if _convert(task, opts):
            took = _duration(time.monotonic() - started)
            results.append(Result(task.src, CONVERTED, task.dst, f"{_size(task.dst.stat().st_size)}, {took}"))
        else:
            print(f"[{n}/{len(tasks)}] FAILED {task.src}: ffmpeg reported an error", file=sys.stderr)
            results.append(Result(task.src, FAILED, task.dst, "ffmpeg reported an error"))

    order = {CONVERTED: 0, WOULD_CONVERT: 0, SKIPPED: 1, FAILED: 2}
    _print_summary(sorted(results, key=lambda r: order[r.status]), errors, output_dir)
    failed = len(errors) + sum(r.status == FAILED for r in results)
    return 1 if failed else 0


def _plan_all(
    jobs: list[Path], output_dir: Path | None, force: bool, session: Session, asker: Asker
) -> tuple[list[Task], list[Result]]:
    """Inspect every file and settle every question up front.

    Returns the conversions to run, plus a Result for every file that won't be.
    """
    tasks: list[Task] = []
    results: list[Result] = []
    planned: dict[Path, Path] = {}  # output -> the source that claimed it

    for n, src in enumerate(jobs, 1):
        prefix = f"[{n}/{len(jobs)}]"
        outcome = _plan_one(src, prefix, output_dir, force, planned, session, asker, remaining=len(jobs) - n)
        if isinstance(outcome, Task):
            tasks.append(outcome)
        else:
            failed = outcome.status == FAILED
            print(
                f"{prefix} {outcome.status} {outcome.src}: {outcome.detail}", file=sys.stderr if failed else sys.stdout
            )
            results.append(outcome)
    return tasks, results


def _plan_one(
    src: Path,
    prefix: str,
    output_dir: Path | None,
    force: bool,
    planned: dict[Path, Path],
    session: Session,
    asker: Asker,
    *,
    remaining: int,
) -> Task | Result:
    dst = _output_path(src, output_dir)

    key = dst.resolve()
    if key == src.resolve():
        return Result(src, SKIPPED, dst, "already an MP4")
    if key in planned:
        return Result(src, SKIPPED, dst, f"{dst} is already produced from {planned[key]}")
    planned[key] = src
    if dst.exists() and not force:
        return Result(src, SKIPPED, dst, f"{dst} already exists (use --force to overwrite)")

    try:
        info = probe(src)
    except Ipadmp4Error as e:
        return Result(src, FAILED, dst, str(e))
    if info.video is None:
        return Result(src, FAILED, dst, "no video stream")

    print(f"{prefix} {src}")
    plan = plan_file(src.name, info, session, asker, remaining=remaining)
    if plan is None:
        return Result(src, SKIPPED, dst, "skipped by choice")
    print(f"  -> {plan.summary()}")
    return Task(src=src, dst=dst, info=info, plan=plan)


def _print_summary(results: list[Result], errors: list[str], output_dir: Path | None) -> None:
    """One line per input: what happened, and where the MP4 is."""
    print("\nSummary:")
    for r in results:
        if r.status in (CONVERTED, WOULD_CONVERT):
            extra = f" ({r.detail})" if r.detail else ""
            print(f"  {r.status:<13} {r.src}\n  {'':<13} -> {r.dst}{extra}")
        else:
            print(f"  {r.status:<13} {r.src}: {r.detail}")
    for msg in errors:
        print(f"  {FAILED:<13} {msg}")

    counts = {s: sum(r.status == s for r in results) for s in (CONVERTED, WOULD_CONVERT, SKIPPED, FAILED)}
    counts[FAILED] += len(errors)
    done = counts[WOULD_CONVERT] if counts[WOULD_CONVERT] else counts[CONVERTED]
    verb = WOULD_CONVERT if counts[WOULD_CONVERT] else CONVERTED
    print(f"Done: {done} {verb}, {counts[SKIPPED]} skipped, {counts[FAILED]} failed.")
    if output_dir is not None and done:
        print(f"Output folder: {output_dir}")


def _size(n: float) -> str:
    for unit in ("bytes", "KB", "MB"):
        if n < 1000:
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.2f} GB"


def _duration(seconds: float) -> str:
    seconds = round(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m{seconds:02d}s"


def _output_path(src: Path, output_dir: Path | None) -> Path:
    """Next to the source, or flat in `output_dir` (no subfolders, even with -r)."""
    if output_dir is None:
        return src.with_suffix(".mp4")
    return output_dir / f"{src.stem}.mp4"


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
