from pathlib import Path
from random import Random
from subprocess import CompletedProcess

import pytest

from core.season_resplit import (
    SeasonResplitOptions,
    SeasonResplitter,
    find_season_videos,
    natural_sort_key,
    plan_episode_durations,
)


def test_video_files_are_naturally_sorted_and_non_video_files_are_ignored(tmp_path):
    for name in ("Episode 10.mp4", "Episode 2.mkv", "Episode 1.mp4", "notes.txt"):
        (tmp_path / name).touch()
    assert [p.name for p in find_season_videos(tmp_path)] == [
        "Episode 1.mp4", "Episode 2.mkv", "Episode 10.mp4"
    ]


def test_random_duration_plan_preserves_total_and_range():
    durations = plan_episode_durations(400, 30, 50, rng=Random(7))
    assert sum(durations) == pytest.approx(400)
    assert all(30 <= duration <= 50 for duration in durations)
    assert len(set(durations)) > 1


def test_fixed_duration_allows_only_short_final_remainder():
    assert plan_episode_durations(70, 30, 30, rng=Random(1)) == [30, 30, 10]


def test_short_source_becomes_one_short_episode():
    assert plan_episode_durations(12.5, 30, 50, rng=Random(1)) == [12.5]


@pytest.mark.parametrize(
    "minimum,maximum",
    [(0, 50), (51, 50)],
)
def test_invalid_duration_ranges_are_rejected(minimum, maximum):
    with pytest.raises(ValueError):
        plan_episode_durations(100, minimum, maximum)


def test_options_require_an_existing_directory_and_title(tmp_path):
    SeasonResplitOptions(tmp_path, "A Show").validate()
    with pytest.raises(ValueError):
        SeasonResplitOptions(Path("missing"), "A Show").validate()
    with pytest.raises(ValueError):
        SeasonResplitOptions(tmp_path, "  ").validate()


def test_natural_sort_key_handles_numbers():
    names = [Path("e100.mp4"), Path("e12.mp4"), Path("e2.mp4")]
    assert [p.name for p in sorted(names, key=natural_sort_key)] == [
        "e2.mp4", "e12.mp4", "e100.mp4"
    ]


def test_rebuild_creates_named_episodes_document_and_fallback_poster(tmp_path, monkeypatch):
    source_a = tmp_path / "source 1.mp4"
    source_b = tmp_path / "source 2.mp4"
    source_a.write_bytes(b"source-a")
    source_b.write_bytes(b"source-b")

    splitter = SeasonResplitter(Path("ffmpeg"), Path("ffprobe"))
    monkeypatch.setattr(splitter, "_duration", lambda _path: 32.5)

    def fake_run(command, **_kwargs):
        output = Path(command[-1])
        if "-t" in command:
            output.write_bytes(b"episode")
        elif output.name.endswith(".mp4"):
            output.write_bytes(b"merged")
        else:
            output.write_bytes(b"poster")
        return CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("core.season_resplit.subprocess.run", fake_run)
    result = splitter.run(
        SeasonResplitOptions(tmp_path, "测试/剧集", season=2, min_episode_seconds=30,
                             max_episode_seconds=30),
        metadata={"overview": "剧情介绍", "show_year": "2026"},
    )

    output_dir = Path(result["output_dir"])
    assert result["episode_count"] == 3
    assert [p.name for p in sorted(output_dir.glob("*.mp4"))] == [
        "测试剧集 - S02E001.mp4", "测试剧集 - S02E002.mp4", "测试剧集 - S02E003.mp4"
    ]
    assert "剧情介绍" in (output_dir / "剧集介绍.md").read_text(encoding="utf-8")
    assert (output_dir / "poster.jpg").read_bytes() == b"poster"
    assert source_a.read_bytes() == b"source-a"
    assert source_b.read_bytes() == b"source-b"


def test_rebuild_resumes_from_state_and_skips_completed_episodes(tmp_path, monkeypatch):
    (tmp_path / "source.mp4").write_bytes(b"source")
    splitter = SeasonResplitter(Path("ffmpeg"), Path("ffprobe"))
    monkeypatch.setattr(splitter, "_duration", lambda _path: 65.0)
    split_calls = []
    fail_once = {"value": True}

    def fake_run(command, **_kwargs):
        output = Path(command[-1])
        if "-t" in command:
            split_calls.append(output.name)
            if fail_once["value"] and len(split_calls) == 2:
                fail_once["value"] = False
                return CompletedProcess(command, 1, "", "interrupted")
            output.write_bytes(b"episode")
        else:
            output.write_bytes(b"merged")
        return CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("core.season_resplit.subprocess.run", fake_run)
    options = SeasonResplitOptions(tmp_path, "Resume Show", min_episode_seconds=30, max_episode_seconds=30)
    with pytest.raises(RuntimeError):
        splitter.run(options)
    assert (tmp_path / "Resume Show" / ".encodeforge-resplit-state.json").is_file()

    result = splitter.run(options)
    assert result["episode_count"] == 3
    assert split_calls.count("Resume Show - S01E001.mp4") == 1
    assert (tmp_path / "Resume Show" / ".encodeforge-resplit-state.json").read_text(encoding="utf-8").find('"complete"') >= 0
