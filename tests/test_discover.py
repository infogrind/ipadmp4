from pathlib import Path

import pytest

from ipadmp4.discover import collect, normalize_extension


def _touch(root: Path, *names: str) -> None:
    for name in names:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()


def _srcs(jobs, root):
    return [str(j.src.relative_to(root)) for j in jobs]


@pytest.mark.parametrize(("raw", "norm"), [("avi", ".avi"), (".AVI", ".avi"), (" Wmv ", ".wmv")])
def test_normalize_extension(raw, norm):
    assert normalize_extension(raw) == norm


def test_directory_requires_recursive(tmp_path):
    _touch(tmp_path, "a.avi")
    jobs, errors = collect([tmp_path], recursive=False, extensions=None)
    assert jobs == []
    assert len(errors) == 1
    assert "use -r" in errors[0]


def test_directory_scan_picks_all_video_formats_case_insensitively(tmp_path):
    _touch(tmp_path, "a.avi", "B.AVI", "c.mkv", "d.wmv", "sub/e.Mov", "notes.txt", "done.mp4", "done.m4v", "x.mp4.part")
    jobs, errors = collect([tmp_path], recursive=True, extensions=None)
    assert errors == []
    assert _srcs(jobs, tmp_path) == ["B.AVI", "a.avi", "c.mkv", "d.wmv", "sub/e.Mov"]
    assert [str(j.rel) for j in jobs][-1] == "sub/e.Mov"


def test_hidden_files_and_folders_are_skipped(tmp_path):
    _touch(tmp_path, "a.avi", "._a.avi", ".hidden/b.avi", ".DS_Store")
    jobs, _ = collect([tmp_path], recursive=True, extensions=None)
    assert _srcs(jobs, tmp_path) == ["a.avi"]


def test_ext_restricts_directory_scan(tmp_path):
    _touch(tmp_path, "a.avi", "b.mkv", "c.WMV")
    jobs, _ = collect([tmp_path], recursive=True, extensions=frozenset({".avi", ".wmv"}))
    assert _srcs(jobs, tmp_path) == ["a.avi", "c.WMV"]


def test_explicit_files_are_taken_whatever_the_extension(tmp_path):
    _touch(tmp_path, "weird.xyz", "clip.mp4")
    files = [tmp_path / "weird.xyz", tmp_path / "clip.mp4"]
    jobs, errors = collect(files, recursive=False, extensions=None)
    assert errors == []
    assert [j.src for j in jobs] == files
    assert [str(j.rel) for j in jobs] == ["weird.xyz", "clip.mp4"]


def test_ext_also_filters_explicit_files(tmp_path):
    _touch(tmp_path, "a.avi", "b.mkv")
    jobs, _ = collect([tmp_path / "a.avi", tmp_path / "b.mkv"], recursive=False, extensions=frozenset({".avi"}))
    assert [j.src.name for j in jobs] == ["a.avi"]


def test_missing_file_is_reported_and_others_continue(tmp_path):
    _touch(tmp_path, "a.avi")
    jobs, errors = collect([tmp_path / "nope.avi", tmp_path / "a.avi"], recursive=False, extensions=None)
    assert [j.src.name for j in jobs] == ["a.avi"]
    assert errors == [f"{tmp_path / 'nope.avi'}: no such file or directory"]


def test_duplicates_are_removed(tmp_path):
    _touch(tmp_path, "a.avi")
    jobs, _ = collect([tmp_path / "a.avi", tmp_path, tmp_path / "a.avi"], recursive=True, extensions=None)
    assert len(jobs) == 1
