"""새 프로젝트 wizard.

사용법:
  python -m pipeline.new_project --name "강의명" [--pptx-dir ...] [--manuscript ...]

또는 대화형:
  python -m pipeline.new_project
"""
from __future__ import annotations
import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def slugify(name: str) -> str:
    """폴더명으로 쓸 안전한 ID 생성."""
    s = re.sub(r"[^a-zA-Z0-9가-힣]+", "_", name).strip("_")
    return s[:40] if s else "project"


def prompt(question: str, default: str = "") -> str:
    if default:
        ans = input(f"{question} [{default}]: ").strip()
    else:
        ans = input(f"{question}: ").strip()
    return ans or default


def detect_ai_providers() -> dict:
    import os
    provs = {}
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ZAI_API_KEY", "MOONSHOT_API_KEY", "MINIMAX_API_KEY"):
        if os.getenv(k):
            provs[k.replace("_API_KEY", "").lower()] = True
    return provs


def find_pptx_files(directory: Path) -> list[Path]:
    if not directory or not directory.exists():
        return []
    files = sorted(directory.glob("*.pptx"))
    # 임시 파일 제외
    return [f for f in files if not f.name.startswith("~$")]


def chapter_from_pptx(pptx: Path, fallback_no: int) -> str:
    """PPTX 파일명에서 챕터 번호 추출. '1장_제목.pptx' → '01'."""
    m = re.match(r"^(\d+)장", pptx.stem)
    if m:
        return f"{int(m.group(1)):02d}"
    return f"{fallback_no:02d}"


def section_from_filename(pptx: Path) -> str:
    """PPTX 파일명에서 섹션 추출. '1장_2026년의교실_세개의국면' → '2026년의교실 세개의국면'."""
    stem = pptx.stem
    parts = stem.split("_", 2)
    if len(parts) >= 3:
        title = parts[2]
    elif len(parts) >= 2:
        title = parts[1]
    else:
        title = stem
    return title.replace("_", " ")


def new_project(
    name: str,
    *,
    base_dir: Path,
    pptx_dir: Optional[Path] = None,
    manuscript: Optional[Path] = None,
    voice_id: Optional[str] = None,
    voice_name: str = "main",
    speed: float = 1.1,
    default_provider: str = "openai",
) -> Path:
    """새 프로젝트 디렉토리 생성 + project.json + manifest.json."""
    base_dir.mkdir(parents=True, exist_ok=True)

    # 1) 슬러그 결정 (충돌 시 _2, _3 ...)
    slug = slugify(name)
    proj_dir = base_dir / slug
    n = 2
    while proj_dir.exists():
        proj_dir = base_dir / f"{slug}_{n}"
        n += 1
    proj_dir.mkdir(parents=True)
    print(f"✓ 프로젝트 디렉토리: {proj_dir}")

    # 2) 표준 폴더 구조
    for sub in ("00_매니페스트", "01_스크립트/scripts", "02_음성/voice_ref",
                "03_영상", "04_자막", "05_MP4", "06_SCORM",
                "pipeline/projects"):
        (proj_dir / sub).mkdir(parents=True, exist_ok=True)

    # 3) .env 템플릿
    env_path = proj_dir / ".env"
    env_path.write_text(
        f"""# AI 프로바이더 (필요한 것만 채우기)
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
ZAI_API_KEY=
MOONSHOT_API_KEY=
MINIMAX_API_KEY=

# 기본 프로바이더 (openai|anthropic|zhipu|moonshot|MiniMax)
DEFAULT_AI_PROVIDER={default_provider}

# ElevenLabs (음성 클론용)
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID={voice_id or ''}
ELEVENLABS_MODEL=eleven_multilingual_v2
""", encoding="utf-8")
    print(f"✓ .env 템플릿: {env_path}")

    # 4) PPTX 스캔 → manifest.json
    manifest_path = proj_dir / "00_매니페스트" / "manifest.json"
    chapters = []
    if pptx_dir and pptx_dir.exists():
        pptx_files = find_pptx_files(pptx_dir)
        for i, p in enumerate(pptx_files, 1):
            ch_no = chapter_from_pptx(p, i)
            chapters.append({
                "chapter_no": ch_no,
                "slide_path": str(p.resolve()),
                "manuscript_path": str(manuscript.resolve()) if manuscript else "",
                "section": section_from_filename(p),
                "duration_min": "40-50",
            })
        print(f"✓ {len(pptx_files)}개 PPTX 감지 → manifest.json")
    manifest_path.write_text(
        json.dumps({"chapters": chapters}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 5) project.json
    project_state = {
        "version": 1,
        "project_id": proj_dir.name,
        "name": name,
        "pptx_dir": str(pptx_dir.resolve()) if pptx_dir else "",
        "manuscript_path": str(manuscript.resolve()) if manuscript else "",
        "elevenlabs": {
            "voice_id": voice_id or "",
            "voice_name": voice_name,
            "model": "eleven_multilingual_v2",
        },
        "defaults": {
            "voice": voice_name,
            "speed": speed,
            "backend": "elevenlabs",
            "ai_provider": default_provider,
        },
        "chapters": {
            ch["chapter_no"]: {
                "title": Path(ch["slide_path"]).stem.split("_", 1)[-1] if ch.get("slide_path") else "",
                "section": ch.get("section", ""),
                "duration_min": ch.get("duration_min", ""),
                "stages": {
                    s: {"status": "pending", "completed_at": None, "details": {}}
                    for s in ("script", "pngs", "tts", "render", "srt", "scorm")
                },
            }
            for ch in chapters
        },
    }
    (proj_dir / "project.json").write_text(
        json.dumps(project_state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"✓ project.json: {proj_dir / 'project.json'}")
    return proj_dir


def main():
    p = argparse.ArgumentParser(description="새 프로젝트 만들기")
    p.add_argument("--name", help="강의명 (예: 'AI 시대 교육')")
    p.add_argument("--base-dir", default=".", help="프로젝트 루트 디렉토리")
    p.add_argument("--pptx-dir", help="PPTX 파일들이 있는 디렉토리")
    p.add_argument("--manuscript", help="원고 파일 경로 (.md 권장)")
    p.add_argument("--voice-id", help="ElevenLabs voice_id (없으면 나중에 clone-voice)")
    p.add_argument("--voice-name", default="main", help="음성 라벨 (파일명에 들어감)")
    p.add_argument("--speed", type=float, default=1.1, help="TTS 속도")
    p.add_argument("--provider", default="openai", help="기본 AI 프로바이더")
    args = p.parse_args()

    if not args.name:
        print("=== 새 프로젝트 만들기 (대화형) ===\n")
        args.name = prompt("강의명 (예: 'AI 시대 교육')")
        if not args.name:
            print("강의명은 필수입니다.")
            sys.exit(1)
        args.pptx_dir = prompt("PPTX 디렉토리 (Enter로 건너뛰기)", args.pptx_dir or "")
        args.manuscript = prompt("원고 파일 (.md)", args.manuscript or "")
        args.voice_id = prompt("ElevenLabs voice_id (없으면 나중에 clone-voice)", args.voice_id or "")

    new_project(
        name=args.name,
        base_dir=Path(args.base_dir).resolve(),
        pptx_dir=Path(args.pptx_dir).resolve() if args.pptx_dir else None,
        manuscript=Path(args.manuscript).resolve() if args.manuscript else None,
        voice_id=args.voice_id,
        voice_name=args.voice_name,
        speed=args.speed,
        default_provider=args.provider,
    )


if __name__ == "__main__":
    main()
