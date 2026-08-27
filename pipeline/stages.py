"""각 파이프라인 단계의 실행/검증 래퍼.

기존 스크립트(batch_tts.py, render_slides_ffmpeg.py 등)를 subprocess로 호출하고,
산출물 검사로 단계 완료 여부를 판단합니다. 부분 진행(예: TTS 12/34)도 추적합니다.
"""
from __future__ import annotations
import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .state import (
    ProjectState, ChapterState, StageState,
    PENDING, IN_PROGRESS, COMPLETED, FAILED, PARTIAL,
    ALL_STAGES, STAGE_LABELS, STAGE_DEPS,
)


@dataclass
class StageResult:
    status: str  # "completed" | "partial" | "failed" | "skipped"
    message: str = ""
    details: dict = field(default_factory=dict)


class PipelineRunner:
    def __init__(self, proj_root: Path, project_state: ProjectState):
        self.root = proj_root
        self.proj = proj_root  # alias
        self.state = project_state
        self.venv_tts = proj_root / ".venv-tts"
        self.venv = proj_root / ".venv"
        self.scripts_dir = proj_root / "01_스크립트" / "scripts"
        # 템플릿은 str로 보관 (Path.format() 미지원 회피)
        self.audio_dir_template = str(proj_root / "02_음성") + "/{ch}"
        self.pngs_dir_template = str(proj_root / "03_영상") + "/ch{ch}_pngs"
        self.clips_dir_template = str(proj_root / "03_영상") + "/ch{ch}_clips"
        self.mp4_path_template = str(proj_root / "05_MP4") + "/ch{ch}_full_{voice}.mp4"
        self.srt_path_template = str(proj_root / "04_자막") + "/ch{ch}.srt"
        self.scorm_path_template = str(proj_root / "06_SCORM") + "/scorm_ch{ch}.zip"

    def _python(self, use_tts_venv: bool = True) -> str:
        venv = self.venv_tts if use_tts_venv else self.venv
        return str(venv / "bin" / "python")

    def _script_path(self, name: str) -> Path:
        return self.proj / {
            "batch_tts": "02_음성" / "batch_tts.py",
            "render": "03_영상" / "render_slides_ffmpeg.py",
            "pngs": "03_영상" / "generate_pngs.py",
            "srt": "04_자막" / "generate_srt.py",
            "scorm": "06_SCORM" / "build_scorm.py",
        }[name]

    def _run(self, args: list[str], timeout: int = 1800) -> tuple[int, str]:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout + "\n" + proc.stderr).strip()

    def _load_script(self, chapter_no: str) -> list[tuple[int, str]]:
        """ch01.txt 형식 → [(slide_no, text), ...]"""
        path = self.scripts_dir / f"ch{chapter_no}.txt"
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").split("\n"):
            line = line.strip()
            if not line or line.startswith("#") or "\t" not in line:
                continue
            no_str, text = line.split("\t", 1)
            out.append((int(no_str.strip()), text.strip()))
        out.sort(key=lambda x: x[0])
        return out

    def _check_deps(self, chapter_no: str, stage: str) -> Optional[str]:
        """의존성이 충족되지 않으면 메시지 반환."""
        ch = self.state.get_chapter(chapter_no)
        for dep in STAGE_DEPS.get(stage, []):
            if not ch.is_stage_done(dep):
                return f"'{stage}'은 '{dep}'이 완료되어야 실행 가능 (현재: {ch.get_stage(dep).status})"
        return None

    # ----------------------------------------------------------------
    # 산출물 검사 (verify)
    # ----------------------------------------------------------------
    def _verify_script(self, chapter_no: str) -> StageResult:
        path = self.scripts_dir / f"ch{chapter_no}.txt"
        if not path.exists():
            return StageResult("failed", f"스크립트 파일 없음: {path}")
        slides = self._load_script(chapter_no)
        if not slides:
            return StageResult("failed", "슬라이드 0개")
        return StageResult("completed", f"{len(slides)}장", {"slide_count": len(slides)})

    def _verify_pngs(self, chapter_no: str) -> StageResult:
        pngs_dir = Path(self.pngs_dir_template.format(ch=chapter_no))
        if not pngs_dir.exists():
            return StageResult("failed", f"디렉토리 없음: {pngs_dir}")
        pngs = sorted(pngs_dir.glob("slide-*.png"))
        script_slides = self._load_script(chapter_no)
        expected = len(script_slides) if script_slides else len(pngs)
        if not pngs:
            return StageResult("failed", "PNG 0개")
        if len(pngs) < expected:
            return StageResult("partial", f"{len(pngs)}/{expected}장", {"completed": len(pngs), "total": expected})
        return StageResult("completed", f"{len(pngs)}장", {"completed": len(pngs), "total": expected})

    def _verify_tts(self, chapter_no: str) -> StageResult:
        ch = self.state.get_chapter(chapter_no)
        defaults = self.state.defaults
        voice = defaults.get("voice", "scott")
        speed = defaults.get("speed", 1.1)
        audio_dir = Path(self.audio_dir_template.format(ch=chapter_no))
        if not audio_dir.exists():
            return StageResult("failed", f"디렉토리 없음: {audio_dir}")
        speed_str = f"x{speed:.1f}".replace(".", "_")
        mp3s = sorted(audio_dir.glob(f"s*_{voice}_{speed_str}.mp3"))
        script_slides = self._load_script(chapter_no)
        expected = len(script_slides) if script_slides else len(mp3s)
        if not mp3s:
            return StageResult("failed", "MP3 0개")
        if len(mp3s) < expected:
            completed = []
            for p in mp3s:
                m = re.match(r"s(\d+)_", p.stem)
                if m:
                    completed.append(int(m.group(1)))
            completed.sort()
            return StageResult("partial", f"{len(mp3s)}/{expected}장", {
                "completed_slides": completed,
                "completed": len(mp3s),
                "total": expected,
                "voice_id": ch.get_stage("tts").details.get("voice_id", ""),
            })
        return StageResult("completed", f"{len(mp3s)}장", {
            "completed_slides": list(range(1, len(mp3s) + 1)),
            "completed": len(mp3s),
            "total": expected,
            "voice_id": ch.get_stage("tts").details.get("voice_id", ""),
        })

    def _verify_render(self, chapter_no: str) -> StageResult:
        voice = self.state.defaults.get("voice", "scott")
        mp4 = Path(self.mp4_path_template.format(ch=chapter_no, voice=voice))
        if not mp4.exists() or mp4.stat().st_size == 0:
            return StageResult("failed", f"MP4 없음: {mp4}")
        return StageResult("completed", f"{mp4.stat().st_size//1024}KB")

    def _verify_srt(self, chapter_no: str) -> StageResult:
        srt = Path(self.srt_path_template.format(ch=chapter_no))
        if not srt.exists() or srt.stat().st_size == 0:
            return StageResult("failed", f"SRT 없음: {srt}")
        block_count = sum(1 for _ in srt.read_text(encoding="utf-8").split("\n") if _ and _[0].isdigit() and " " not in _)
        return StageResult("completed", f"{block_count}블록")

    def _verify_scorm(self, chapter_no: str) -> StageResult:
        zip_path = Path(self.scorm_path_template.format(ch=chapter_no))
        if not zip_path.exists() or zip_path.stat().st_size == 0:
            return StageResult("failed", f"SCORM zip 없음: {zip_path}")
        return StageResult("completed", f"{zip_path.stat().st_size//1024}KB")

    VERIFIERS = {
        "script": _verify_script,
        "pngs": _verify_pngs,
        "tts": _verify_tts,
        "render": _verify_render,
        "srt": _verify_srt,
        "scorm": _verify_scorm,
    }

    # ----------------------------------------------------------------
    # 단계 실행
    # ----------------------------------------------------------------
    def _execute(self, chapter_no: str, stage: str) -> StageResult:
        py = self._python(use_tts_venv=True)
        ch = self.state.get_chapter(chapter_no)
        defaults = self.state.defaults
        voice = defaults.get("voice", "scott")
        speed = defaults.get("speed", 1.1)

        if stage == "script":
            # 스크립트는 수동 작성 또는 AI 생성 — 자동 실행 없음
            return StageResult("skipped", "스크립트는 수동 또는 AI 별도 호출 필요")

        if stage == "pngs":
            rc, out = self._run([py, str(self._script_path("pngs")), "--chapter", chapter_no], timeout=1800)

        elif stage == "tts":
            rc, out = self._run([py, str(self._script_path("batch_tts")), "--chapter", chapter_no, "--speed", str(speed)], timeout=7200)

        elif stage == "render":
            rc, out = self._run([py, str(self._script_path("render")), "--chapter", chapter_no], timeout=3600)

        elif stage == "srt":
            rc, out = self._run([py, str(self._script_path("srt")), "--chapter", chapter_no], timeout=300)

        elif stage == "scorm":
            zip_name = f"scorm_ch{chapter_no}"
            rc, out = self._run([py, str(self._script_path("scorm")), "--chapter", chapter_no, "--voice", voice, "--zip-name", zip_name], timeout=300)

        else:
            return StageResult("failed", f"알 수 없는 stage: {stage}")

        return StageResult(
            "completed" if rc == 0 else "failed",
            out[-500:] if out else "",
        )

    # ----------------------------------------------------------------
    # 공개 API
    # ----------------------------------------------------------------
    def verify(self, chapter_no: str, stage: str) -> StageResult:
        return self.VERIFIERS[stage](self, chapter_no)

    def verify_all(self, chapter_no: str) -> dict[str, StageResult]:
        return {s: self.verify(chapter_no, s) for s in ALL_STAGES}

    def run(self, chapter_no: str, stage: str, force: bool = False) -> StageResult:
        # 의존성 체크
        dep_err = self._check_deps(chapter_no, stage)
        if dep_err:
            return StageResult("failed", dep_err)

        ch = self.state.get_chapter(chapter_no)
        st = ch.get_stage(stage)

        # force가 아니면 이미 완료된 단계는 스킵
        if not force and st.status == COMPLETED:
            return StageResult("skipped", "이미 완료됨")

        # 시작 표시
        st.status = IN_PROGRESS
        st.started_at = time.strftime("%Y-%m-%dT%H:%M:%S")

        # 실행
        result = self._execute(chapter_no, stage)

        # 검증
        verify_result = self.verify(chapter_no, stage)
        # 검증이 더 정확하므로 우선
        final_status = verify_result.status
        final_message = verify_result.message
        final_details = verify_result.details

        st.status = final_status
        st.details = final_details
        if final_status == COMPLETED:
            st.completed_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        else:
            st.completed_at = None

        return StageResult(final_status, final_message, final_details)

    def run_chapter(self, chapter_no: str, force: bool = False) -> dict[str, StageResult]:
        """챕터의 모든 단계를 의존성 순서대로 실행."""
        results = {}
        for stage in ALL_STAGES:
            err = self._check_deps(chapter_no, stage)
            if err and not force:
                results[stage] = StageResult("skipped", err)
                continue
            results[stage] = self.run(chapter_no, stage, force=force)
            if results[stage].status == "failed":
                break
        return results
