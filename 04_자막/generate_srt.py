#!/usr/bin/env python3
"""
Phase 5: 스크립트 + 음성 길이 → SRT 자막 생성.
- 각 슬라이드의 스크립트 텍스트를 음성 시작/종료 시간에 맞춰 자막 블록으로
- 너무 긴 텍스트는 30-40자 단위로 줄바꿈

사용법:
    python generate_srt.py --chapter 01
    python generate_srt.py --chapter 04 --limit 5     # 테스트
"""
from __future__ import annotations
import argparse
import re
import subprocess
from pathlib import Path

BASE = Path("/Users/scott/Library/CloudStorage/GoogleDrive-scott@naddle.net/내 드라이브/개인/개인 자료/[2024] 대구교대 강의/26년2학기")
PROJ = BASE / "강의영상_제작"
SCRIPT_DIR = PROJ / "01_스크립트" / "scripts"
OUT_DIR = PROJ / "04_자막"
OUT_DIR.mkdir(parents=True, exist_ok=True)

VOICE = "scott"
SPEED = 1.1


def speed_str(s: float) -> str:
    return f"x{s:.1f}".replace(".", "_")


def get_audio_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def load_scripts(script_file: Path) -> dict[int, str]:
    if not script_file.exists():
        raise FileNotFoundError(f"스크립트 파일 없음: {script_file}")
    out = {}
    for line in script_file.read_text(encoding="utf-8").split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or "\t" not in line:
            continue
        no_str, text = line.split("\t", 1)
        out[int(no_str)] = text.strip()
    return out


def fmt_ts(t: float) -> str:
    """초 → SRT 타임스탬프 'HH:MM:SS,mmm'."""
    if t < 0:
        t = 0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def split_for_subtitle(text: str, max_chars: int = 38, max_lines: int = 2) -> list[str]:
    """긴 자막을 max_chars 기준으로 줄바꿈 (문장 부호 우선)."""
    text = re.sub(r"\s+", " ", text).strip()
    # 문장 단위로 우선 분리
    sentences = re.split(r"(?<=[.!?。?!])\s+|(?<=[.!?。?!])$", text)
    sentences = [s for s in sentences if s]

    lines = []
    current = ""
    for s in sentences:
        if len(current) + len(s) + 1 <= max_chars:
            current = (current + " " + s).strip()
        else:
            if current:
                lines.append(current)
            current = s
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)

    if not lines:
        lines = [text[:max_chars]]

    # 너무 긴 단일 문장은 강제 분할
    final = []
    for ln in lines:
        while len(ln) > max_chars:
            final.append(ln[:max_chars])
            ln = ln[max_chars:]
        final.append(ln)
    return final[:max_lines]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chapter", required=True, help="챕터 번호 (예: 01)")
    parser.add_argument("--limit", type=int, default=0,
                        help="처리할 슬라이드 수 제한 (0=전체)")
    parser.add_argument("--suffix", type=str, default="",
                        help="출력 파일명 접미사 (예: 'test' → ch01_test.srt)")
    args = parser.parse_args()

    script_file = SCRIPT_DIR / f"ch{args.chapter}.txt"
    audio_dir = PROJ / "02_음성" / args.chapter

    try:
        scripts = load_scripts(script_file)
    except FileNotFoundError as e:
        print(f"⚠ {e}")
        return

    if args.limit > 0:
        keys = sorted(scripts.keys())[: args.limit]
        scripts = {k: scripts[k] for k in keys}
    print(f"✓ ch{args.chapter}: {len(scripts)} 슬라이드 스크립트 사용 (voice={VOICE})")

    # 슬라이드별 시작/종료 시간 누적
    entries = []  # (start, end, text)
    cursor = 0.0
    for slide_no in sorted(scripts.keys()):
        audio = audio_dir / f"s{slide_no:02d}_{VOICE}_{speed_str(SPEED)}.mp3"
        if not audio.exists():
            print(f"  ⚠ 슬라이드 {slide_no}: 음성 없음, 스킵")
            continue
        dur = get_audio_duration(audio)
        text = scripts[slide_no]
        if len(text) <= 38:
            chunks = [text]
        else:
            chunks = split_for_subtitle(text, max_chars=38, max_lines=2)
        n = len(chunks)
        per_chunk = dur / n
        for i, chunk in enumerate(chunks):
            start = cursor + i * per_chunk
            end = cursor + (i + 1) * per_chunk
            entries.append((start, end, chunk))
        cursor += dur

    srt_name = f"ch{args.chapter}{args.suffix}.srt" if args.suffix else f"ch{args.chapter}.srt"
    srt_path = OUT_DIR / srt_name
    lines = []
    for i, (start, end, text) in enumerate(entries, 1):
        lines.append(str(i))
        lines.append(f"{fmt_ts(start)} --> {fmt_ts(end)}")
        lines.append(text)
        lines.append("")
    srt_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ {srt_path}")
    print(f"  자막 블록: {len(entries)}개")
    print(f"  총 길이: {cursor:.1f}초 = {cursor / 60:.1f}분")

    print("\n--- 첫 10블록 ---")
    for i, (start, end, text) in enumerate(entries[:10], 1):
        print(f"{i}. {fmt_ts(start)} → {fmt_ts(end)}")
        print(f"   {text}")


if __name__ == "__main__":
    main()