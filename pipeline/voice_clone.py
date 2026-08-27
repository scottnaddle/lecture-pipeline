"""ElevenLabs 음성 클론 + 프로젝트 연결.

사용법:
  python -m pipeline.voice_clone --project-dir <path> --ref-audio ref1.wav [--ref-audio ref2.wav] [--name "scott"]
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def clone_voice(
    project_dir: Path,
    ref_audios: list[Path],
    *,
    name: str = "main",
    model: str = "eleven_multilingual_v2",
) -> str:
    """ElevenLabs Instant Voice Clone 생성 후 project.json 업데이트."""
    # 클라이언트 lazy import
    try:
        from elevenlabs import ElevenLabs
    except ImportError:
        print("elevenlabs 미설치. .venv-tts/bin/pip install elevenlabs")
        sys.exit(1)

    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        print("ELEVENLABS_API_KEY 미설정 (.env 확인)")
        sys.exit(1)

    proj = project_dir / "project.json"
    state = json.loads(proj.read_text(encoding="utf-8"))

    # 음성 참조 파일 검증
    valid_refs = [r for r in ref_audios if r.exists()]
    if not valid_refs:
        print(f"유효한 음성 파일 없음: {ref_audios}")
        sys.exit(1)

    # voice_ref 디렉토리에 복사
    ref_dir = project_dir / "02_음성" / "voice_ref"
    ref_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, r in enumerate(valid_refs, 1):
        dest = ref_dir / f"ref_{i}.wav"
        if dest.resolve() != r.resolve():
            import shutil
            shutil.copy2(r, dest)
        saved.append(dest)
    print(f"✓ {len(saved)}개 음성 참조 저장: {ref_dir}")

    # ElevenLabs 클론 생성
    print("ElevenLabs 클론 생성 중...")
    client = ElevenLabs(api_key=api_key)
    try:
        voice = client.voices.ivc.create(
            name=f"{state['project_id']}_{name}",
            files=[(None, open(r, "rb"), "audio/wav") for r in saved],
            labels={},
        )
    except Exception as e:
        print(f"✗ 클론 실패: {e}")
        sys.exit(1)

    voice_id = voice.voice_id
    print(f"✓ voice_id: {voice_id}")

    # project.json 업데이트
    state["elevenlabs"]["voice_id"] = voice_id
    state["elevenlabs"]["voice_name"] = name
    state["elevenlabs"]["model"] = model
    state["elevenlabs"]["ref_audios"] = [str(r.relative_to(project_dir)) for r in saved]
    state["elevenlabs"]["cloned_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    state["defaults"]["voice"] = name
    proj.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ project.json 갱신: voice_id={voice_id}, name={name}")

    # .env에 ELEVENLABS_VOICE_ID 동기화 (선택)
    env_path = project_dir / ".env"
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
        new_lines = []
        replaced = False
        for line in lines:
            if line.startswith("ELEVENLABS_VOICE_ID="):
                new_lines.append(f"ELEVENLABS_VOICE_ID={voice_id}")
                replaced = True
            else:
                new_lines.append(line)
        if not replaced:
            new_lines.append(f"ELEVENLABS_VOICE_ID={voice_id}")
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print(f"✓ .env 갱신: {env_path}")

    return voice_id


def main():
    p = argparse.ArgumentParser(description="ElevenLabs 음성 클론")
    p.add_argument("--project-dir", required=True)
    p.add_argument("--ref-audio", action="append", required=True,
                   help="음성 참조 파일 (1~3개, 10초 이상 권장)")
    p.add_argument("--name", default="main", help="음성 라벨 (project.json의 defaults.voice로 들어감)")
    p.add_argument("--model", default="eleven_multilingual_v2")
    args = p.parse_args()

    refs = [Path(r).expanduser().resolve() for r in args.ref_audio]
    proj_dir = Path(args.project_dir).resolve()
    clone_voice(proj_dir, refs, name=args.name, model=args.model)


if __name__ == "__main__":
    main()
