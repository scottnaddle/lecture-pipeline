"""전체 파이프라인 오케스트레이터.

한 챕터에 대해 [pngs → tts → render → srt → scorm] 전체 실행.
또는 한 프로젝트의 모든 챕터에 대해 일괄 실행.

사용법:
  python -m pipeline.orchestrator --project-dir <path> --chapter 04
  python -m pipeline.orchestrator --project-dir <path> --all
  python -m pipeline.orchestrator --project-dir <path> --chapter 04 --from pngs
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from .stages import PipelineRunner, StageResult


# 파이프라인 순서 + 각 단계의 스크립트
STAGE_SCRIPTS = {
    "pngs":   ("03_영상/generate_pngs.py",   ["--chapter"]),
    "tts":    ("02_음성/batch_tts.py",        ["--chapter", "--speed"]),
    "render": ("03_영상/render_slides_ffmpeg.py", ["--chapter"]),
    "srt":    ("04_자막/generate_srt.py",     ["--chapter"]),
    "scorm":  ("06_SCORM/build_scorm.py",     ["--chapter", "--voice", "--zip-name"]),
}


def run_stage(stage: str, chapter: str, project_dir: Path,
              voice: str, speed: float, log_path: Path) -> tuple[int, float]:
    """단일 단계 실행. (returncode, 소요시간) 반환."""
    rel, base_args = STAGE_SCRIPTS[stage]
    script = project_dir / rel
    if not script.exists():
        return (127, 0.0)

    args = [sys.executable, str(script)] + base_args
    if stage == "tts":
        args += [chapter, str(speed)]
    elif stage == "scorm":
        zip_name = f"scorm_ch{chapter}"
        args += [chapter, "--voice", voice, "--zip-name", zip_name]
    else:
        args += [chapter]

    t0 = time.time()
    with open(log_path, "a", encoding="utf-8") as logf:
        logf.write(f"\n[{time.strftime('%H:%M:%S')}] {' '.join(args)}\n")
        logf.flush()
        p = subprocess.run(args, cwd=str(project_dir), stdout=logf, stderr=subprocess.STDOUT, timeout=3600)
    return (p.returncode, time.time() - t0)


def run_chapter(project_dir: Path, chapter: str,
                stages: list[str] | None = None,
                voice: str = "scott", speed: float = 1.1,
                log_dir: Path | None = None) -> dict[str, StageResult]:
    """한 챕터의 여러 단계를 순서대로 실행. 실패 시 중단."""
    runner = PipelineRunner(project_dir, _load_state(project_dir))
    state = _load_state(project_dir)
    stages = stages or ["pngs", "tts", "render", "srt", "scorm"]
    log_dir = log_dir or project_dir / "pipeline" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"ch{chapter}.log"

    results = {}
    print(f"\n=== ch{chapter} 파이프라인 시작 ({len(stages)}단계) ===", flush=True)
    for stage in stages:
        print(f"  [{stage}] 실행 중...", end=" ", flush=True)
        # 의존성 체크
        ch = state.get_chapter(chapter)
        from .state import STAGE_DEPS
        for dep in STAGE_DEPS.get(stage, []):
            if not ch.is_stage_done(dep):
                print(f"스킵 (의존성 {dep} 미완료)", flush=True)
                results[stage] = StageResult("skipped", f"{dep} 미완료")
                continue

        rc, dur = run_stage(stage, chapter, project_dir, voice, speed, log_path)
        # 검증
        result = runner.verify(chapter, stage)
        # state 업데이트
        st = ch.get_stage(stage)
        st.status = result.status
        st.details = result.details
        from .state import COMPLETED
        if result.status == COMPLETED:
            from datetime import datetime
            st.completed_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        results[stage] = result

        icon = {"completed": "✓", "partial": "◐", "failed": "✗", "skipped": "○"}.get(result.status, "?")
        print(f"{icon} {result.status} ({dur:.0f}초) — {result.message[:80]}", flush=True)

        if result.status == "failed":
            print(f"  → 중단: {stage} 실패", flush=True)
            break

    # state 저장
    state.save(project_dir / "project.json")
    return results


def _load_state(project_dir: Path):
    from .state import ProjectState
    return ProjectState.load(project_dir / "project.json")


def run_all(project_dir: Path, voice: str = "scott", speed: float = 1.1) -> dict:
    """프로젝트의 모든 챕터를 순차 실행."""
    state = _load_state(project_dir)
    summary = {}
    for ch_no in sorted(state.chapters.keys()):
        results = run_chapter(project_dir, ch_no, voice=voice, speed=speed)
        summary[ch_no] = {s: r.status for s, r in results.items()}
    return summary


def main():
    p = argparse.ArgumentParser(description="파이프라인 오케스트레이터")
    p.add_argument("--project-dir", required=True, help="프로젝트 디렉토리")
    p.add_argument("--chapter", help="특정 챕터만 (예: 04)")
    p.add_argument("--all", action="store_true", help="모든 챕터")
    p.add_argument("--from", dest="from_stage", help="이 단계부터 시작 (pngs|tts|render|srt|scorm)")
    p.add_argument("--stages", help="콤마 구분 단계 목록 (예: pngs,tts)")
    p.add_argument("--voice", default=None, help="음성 라벨 (기본: project.json의 defaults.voice)")
    p.add_argument("--speed", type=float, default=None, help="TTS 속도")
    args = p.parse_args()

    pd = Path(args.project_dir).resolve()
    if not (pd / "project.json").exists():
        print(f"project.json 없음: {pd}")
        sys.exit(1)
    state = _load_state(pd)
    voice = args.voice or state.defaults.get("voice", "scott")
    speed = args.speed or state.defaults.get("speed", 1.1)

    if args.chapter:
        stages = args.stages.split(",") if args.stages else None
        if args.from_stage and stages is None:
            all_stages = ["pngs", "tts", "render", "srt", "scorm"]
            idx = all_stages.index(args.from_stage)
            stages = all_stages[idx:]
        run_chapter(pd, args.chapter, stages=stages, voice=voice, speed=speed)
    elif args.all:
        run_all(pd, voice=voice, speed=speed)
    else:
        print("--chapter NN 또는 --all 필요")
        sys.exit(1)


if __name__ == "__main__":
    main()
