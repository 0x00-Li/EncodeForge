"""Rebuild a season as short, consistently named episodes.

The source directory is never modified.  Its videos are concatenated in
natural filename order, re-encoded once, and segmented at exact keyframes into
a new sibling directory.
"""

from __future__ import annotations

import json
import logging
import math
import random
import re
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from core.rename_pattern import sanitize_path_segment
from utils.ffmpeg_manager import get_ffmpeg_manager

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm", ".ts", ".mts", ".m2ts"
}
STATE_FILENAME = ".encodeforge-resplit-state.json"
MERGED_FILENAME = ".encodeforge-merged.mp4"


@dataclass(frozen=True)
class SeasonResplitOptions:
    source_dir: Path
    show_title: str
    season: int = 1
    min_episode_seconds: int = 30
    max_episode_seconds: int = 50

    def validate(self) -> None:
        if not self.source_dir.is_dir():
            raise ValueError("The selected season directory does not exist.")
        if not self.show_title.strip():
            raise ValueError("A show title is required.")
        if self.season < 0:
            raise ValueError("Season must be zero or greater.")
        if self.min_episode_seconds < 1:
            raise ValueError("Episode duration must be at least one second.")
        if self.max_episode_seconds < self.min_episode_seconds:
            raise ValueError("Maximum duration cannot be less than minimum duration.")


def natural_sort_key(path: Path | str) -> List[Any]:
    name = path.name if isinstance(path, Path) else Path(path).name
    return [int(piece) if piece.isdigit() else piece.casefold()
            for piece in re.split(r"(\d+)", name)]


def find_season_videos(directory: Path) -> List[Path]:
    """Return only videos directly inside *directory*, in natural order."""
    return sorted(
        (p for p in directory.iterdir()
         if p.is_file() and p.suffix.casefold() in VIDEO_EXTENSIONS),
        key=natural_sort_key,
    )


def plan_episode_durations(
    total_seconds: float,
    minimum: int = 30,
    maximum: int = 50,
    *,
    rng: Optional[random.Random] = None,
) -> List[float]:
    """Plan chunks while avoiding a tiny final episode where possible.

    The requested range remains the first choice.  When the total duration
    cannot be divided inside that range, progressively allow 5% and then 10%
    variance before falling back to a short final remainder.
    """
    if total_seconds <= 0:
        raise ValueError("The source videos have no playable duration.")
    if minimum < 1 or maximum < minimum:
        raise ValueError("Invalid episode duration range.")
    picker = rng or random.SystemRandom()
    total = float(total_seconds)
    def plan_within(low_limit: float, high_limit: float) -> Optional[List[float]]:
        least_count = math.ceil(total / high_limit)
        greatest_count = math.floor(total / low_limit)
        if least_count > greatest_count:
            return None

        ideal = round(total / ((minimum + maximum) / 2.0))
        count = max(least_count, min(greatest_count, ideal))
        remaining = total
        result: List[float] = []
        for index in range(count):
            slots_after = count - index - 1
            if not slots_after:
                result.append(remaining)
                break
            low = max(low_limit, remaining - slots_after * high_limit)
            high = min(high_limit, remaining - slots_after * low_limit)
            integer_low, integer_high = math.ceil(low), math.floor(high)
            duration = (
                float(picker.randint(integer_low, integer_high))
                if integer_low <= integer_high else (low + high) / 2.0
            )
            result.append(duration)
            remaining -= duration
        return result

    # Prefer the exact requested range. If it leaves a tiny tail, accept the
    # user-facing 5–10% tolerance and distribute that tail across episodes.
    for tolerance in (0.0, 0.05, 0.10):
        result = plan_within(
            float(minimum) * (1.0 - tolerance),
            float(maximum) * (1.0 + tolerance),
        )
        if result is not None:
            return result

    # Very short input, or a total that cannot satisfy the range exactly.
    # Keep ordinary chunks valid and allow only the final remainder to be short
    # when even the 10% tolerance cannot absorb it.
    remaining = total
    result = []
    while remaining > maximum:
        duration = float(picker.randint(minimum, maximum))
        result.append(duration)
        remaining -= duration
    if remaining > 0.05:
        result.append(remaining)
    return result


def output_directory(options: SeasonResplitOptions) -> Path:
    """Return the deterministic output directory for a season task."""
    base = sanitize_path_segment(options.show_title.strip()) or "Resplit Season"
    return options.source_dir / base


def load_resplit_state(directory: Path) -> Optional[Dict[str, Any]]:
    state_file = directory / STATE_FILENAME
    if not state_file.is_file():
        return None
    try:
        value = json.loads(state_file.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read resplit state: {state_file}: {exc}") from exc


def _write_state(directory: Path, state: Dict[str, Any]) -> None:
    state_file = directory / STATE_FILENAME
    temporary = state_file.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(state_file)


def _concat_line(path: Path) -> str:
    # FFmpeg concat-demuxer quoting: a single quote is closed, escaped, reopened.
    escaped = str(path.resolve()).replace("'", "'\\''")
    return f"file '{escaped}'\n"


class SeasonResplitter:
    def __init__(self, ffmpeg_path: Optional[Path] = None, ffprobe_path: Optional[Path] = None):
        manager = get_ffmpeg_manager()
        self.ffmpeg_path = Path(ffmpeg_path or manager.get_ffmpeg_path() or "ffmpeg")
        self.ffprobe_path = Path(ffprobe_path or manager.get_ffprobe_path() or "ffprobe")

    def _duration(self, path: Path) -> float:
        result = subprocess.run(
            [str(self.ffprobe_path), "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Unable to read duration for {path.name}: {result.stderr.strip()}")
        try:
            return float(json.loads(result.stdout)["format"]["duration"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"No valid duration found for {path.name}.") from exc

    @staticmethod
    def inspect(options: SeasonResplitOptions) -> Dict[str, Any]:
        """Describe whether a task is new, resumable, or already complete."""
        direct_state = load_resplit_state(options.source_dir)
        if direct_state:
            return {
                "status": "complete" if direct_state.get("status") == "complete" else "resumable",
                "directory": str(options.source_dir),
                "state": direct_state,
            }
        directory = output_directory(options)
        state = load_resplit_state(directory)
        if state:
            return {
                "status": "complete" if state.get("status") == "complete" else "resumable",
                "directory": str(directory),
                "state": state,
            }
        return {"status": "existing" if directory.exists() else "new", "directory": str(directory)}

    def run(
        self,
        options: SeasonResplitOptions,
        *,
        metadata: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        options.validate()
        # Selecting the generated folder itself is supported for resume.  The
        # state keeps the original input folder, so a restart does not depend
        # on remembering which parent directory was selected initially.
        direct_state = load_resplit_state(options.source_dir)
        output_dir = options.source_dir if direct_state else output_directory(options)
        state = direct_state or load_resplit_state(output_dir)
        effective_source = options.source_dir
        if state and state.get("source_dir"):
            effective_source = Path(str(state["source_dir"])).expanduser()
        videos = find_season_videos(effective_source)
        if not videos:
            raise ValueError("No supported video files were found in the selected directory.")

        def progress(value: int, message: str) -> None:
            if progress_callback:
                progress_callback({"progress": value, "total": 100, "message": message})

        safe_title = sanitize_path_segment(options.show_title.strip()) or "Show"
        if state:
            saved_options = state.get("options") or {}
            expected = {
                "show_title": options.show_title,
                "season": options.season,
                "min_episode_seconds": options.min_episode_seconds,
                "max_episode_seconds": options.max_episode_seconds,
            }
            if any(saved_options.get(key) != value for key, value in expected.items()):
                raise RuntimeError("The existing resplit task uses different settings; start a new output folder.")
            durations = [float(value) for value in state.get("durations", [])]
            total = float(state.get("total_seconds", sum(durations)))
            metadata = metadata or state.get("metadata") or {}
        else:
            if output_dir.exists() and any(output_dir.iterdir()):
                raise RuntimeError(
                    f"Output folder already exists without a recoverable state file: {output_dir}"
                )
            progress(2, "Reading source durations…")
            total = sum(self._duration(video) for video in videos)
            durations = plan_episode_durations(
                total, options.min_episode_seconds, options.max_episode_seconds
            )
            output_dir.mkdir(parents=True, exist_ok=True)
            state = {
                "version": 1,
                "status": "merging",
                "source_dir": str(effective_source.resolve()),
                "show_title": options.show_title,
                "season": options.season,
                "options": {
                    "show_title": options.show_title,
                    "season": options.season,
                    "min_episode_seconds": options.min_episode_seconds,
                    "max_episode_seconds": options.max_episode_seconds,
                },
                "durations": durations,
                "total_seconds": total,
                "completed": [],
                "metadata": metadata or {},
            }
            _write_state(output_dir, state)

        merged = output_dir / MERGED_FILENAME
        if not merged.exists():
            concat_file = output_dir / ".encodeforge-sources.ffconcat"
            temporary_merged = output_dir / ".encodeforge-merged.building.mp4"
            concat_file.write_text(
                "ffconcat version 1.0\n" + "".join(_concat_line(p) for p in videos),
                encoding="utf-8",
            )
            command = [
                str(self.ffmpeg_path), "-hide_banner", "-y", "-f", "concat", "-safe", "0",
                "-i", str(concat_file), "-map", "0:v:0", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                str(temporary_merged),
            ]
            progress(8, "Merging source episodes…")
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                tail = "\n".join(result.stderr.splitlines()[-12:])
                raise RuntimeError(f"FFmpeg failed while merging the season:\n{tail}")
            temporary_merged.replace(merged)
            concat_file.unlink(missing_ok=True)
        state["status"] = "splitting"
        _write_state(output_dir, state)

        completed = set(state.get("completed") or [])
        elapsed = 0.0
        episodes: List[Path] = []
        progress(15, f"Splitting {len(durations)} episode(s)…")
        for index, duration in enumerate(durations, start=1):
            episode = output_dir / f"{safe_title} - S{options.season:02d}E{index:03d}.mp4"
            if episode.name not in completed or not episode.exists():
                command = [
                    str(self.ffmpeg_path), "-hide_banner", "-y", "-ss", f"{elapsed:.3f}",
                    "-i", str(merged), "-t", f"{duration:.3f}", "-map", "0:v:0", "-map", "0:a?",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                    str(episode),
                ]
                result = subprocess.run(command, capture_output=True, text=True, check=False)
                if result.returncode != 0:
                    tail = "\n".join(result.stderr.splitlines()[-12:])
                    raise RuntimeError(f"FFmpeg failed at episode {index}:\n{tail}")
                completed.add(episode.name)
                state["completed"] = sorted(completed, key=natural_sort_key)
                _write_state(output_dir, state)
            episodes.append(episode)
            elapsed += duration
            progress(15 + int(index * 80 / max(1, len(durations))), f"Episode {index}/{len(durations)} ready")

        self._write_introduction(output_dir, options, videos, episodes, durations, metadata or {})
        try:
            self._create_poster(output_dir, episodes[0], metadata or {})
        except Exception as exc:
            logger.warning("Poster generation failed after successful rebuild: %s", exc)
        state["status"] = "complete"
        state["completed"] = [episode.name for episode in episodes]
        _write_state(output_dir, state)
        merged.unlink(missing_ok=True)

        progress(100, "Season rebuild complete")
        return {
            "output_dir": str(output_dir),
            "episode_count": len(episodes),
            "source_count": len(videos),
            "total_seconds": total,
        }

    def _write_introduction(
        self, directory: Path, options: SeasonResplitOptions, sources: Iterable[Path],
        episodes: List[Path], durations: List[float], metadata: Dict[str, Any],
    ) -> None:
        overview = str(metadata.get("overview") or "暂无在线剧情简介。")
        year = metadata.get("show_year") or metadata.get("year") or ""
        source = metadata.get("source") or "local"
        lines = [
            f"# {options.show_title}", "", f"- 季：第 {options.season} 季",
            f"- 年份：{year or '未知'}", f"- 集数：{len(episodes)}",
            f"- 元数据来源：{source}", "", "## 剧情简介", "", overview, "",
            "## 重新分集信息", "",
            f"- 原始文件数：{len(list(sources))}",
            f"- 目标时长范围：{options.min_episode_seconds}–{options.max_episode_seconds} 秒",
            "- 时长容差：为避免过短尾集，必要时最多放宽 10%。",
            "- 处理方式：按文件名自然排序后连续合并，再按目标时长重新切分。", "",
            "## 剧集列表", "",
        ]
        lines.extend(
            f"- {episode.name}（约 {durations[index]:.1f} 秒）"
            for index, episode in enumerate(episodes)
        )
        (directory / "剧集介绍.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _create_poster(self, directory: Path, first_episode: Path, metadata: Dict[str, Any]) -> None:
        poster = directory / "poster.jpg"
        url = str(metadata.get("poster_url") or "").strip()
        if url:
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "EncodeForge/1.0"})
                with urllib.request.urlopen(request, timeout=20) as response, poster.open("wb") as target:
                    shutil.copyfileobj(response, target)
                if poster.stat().st_size > 0:
                    return
            except Exception as exc:
                logger.warning("Poster download failed, using a video frame: %s", exc)
                poster.unlink(missing_ok=True)
        result = subprocess.run(
            [str(self.ffmpeg_path), "-hide_banner", "-loglevel", "error", "-y",
             "-ss", "0", "-i", str(first_episode), "-frames:v", "1", "-q:v", "2", str(poster)],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Unable to generate poster: {result.stderr.strip()}")
