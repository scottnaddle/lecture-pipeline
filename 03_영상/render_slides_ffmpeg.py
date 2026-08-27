#!/usr/bin/env python3
"""
Phase 4: 슬라이드 PNG + 음성 → 챕터 전체 MP4 영상 렌더링.

방식: FFmpeg로 각 슬라이드마다
  - PNG를 정적으로 영상화 (bilinear, 줌 없음)
  - 해당 음성 길이만큼 mux
  - 모든 클립을 concat

사용법:
    # 전체 챕터
    python render_slides_ffmpeg.py --chapter 01

    # 일부 슬라이드만 (테스트)
    python render_slides_ffmpeg.py --chapter 04 --limit 5
    python render_slides_ffmpeg.py --chapter 04 --slides 1,2,3
"""
from __future__ import annotations
import argparse
import json
import subprocess
import shutil
from pathlib import Path

BASE = Path("/Users/scott/Library/CloudStorage/GoogleDrive-scott@naddle.net/내 드라이브/개인/개인 자료/[2024] 대구교대 강의/26년2학기")
PROJ = BASE / "강의영상_제작"
MANIFEST = PROJ / "00_매니페스트" / "manifest.json"
OUT_DIR = PROJ / "05_MP4"

WIDTH, HEIGHT, FPS = 1920, 1080, 30
VOICE = "scott"
SPEED = 1.1


def chapter_paths(chapter_no: str) -> dict[Path, str]:
    """챕터 번호로 PNG/오디오/클립 디렉토리 경로 반환."""
    return {
        "png": PROJ / "03_영상" / f"ch{chapter_no}_pngs",
        "audio": PROJ / "02_음성" / chapter_no,
        "clips": PROJ / "03_영상" / f"ch{chapter_no}_clips",
    }


def speed_str(s: float) -> str:
    """1.1 → 'x1_1', 1.2 → 'x1_2' 등."""
    return f"x{s:.1f}".replace(".", "_")


def get_audio_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def render_slide_clip(slide_no: int, png: Path, audio: Path, out: Path, duration: float):
    """단일 슬라이드 영상 클립 생성 (정적 + bilinear)."""
    if out.exists() and out.stat().st_size > 0:
        return out

    # 정적 슬라이드: 2000x1125 PNG를 1920x1080으로 bilinear 다운스케일.
    # zoom 없음 → 떨림 없음. bilinear → 텍스트 ringing 없음.
    vf = (
        f"scale={WIDTH}:{HEIGHT}:flags=bilinear,"
        f"format=yuv420p"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(png),
        "-i", str(audio),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-t", str(duration),
        "-r", str(FPS),
        "-pix_fmt", "yuv420p",
        "-shortest",
        str(out),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chapter", required=True, help="챕터 번호 (예: 01)")
    parser.add_argument("--limit", type=int, default=0,
                        help="처리할 슬라이드 수 제한 (0=전체)")
    parser.add_argument("--slides", type=str, default="",
                        help="콤마 구분 슬라이드 번호 (예: 1,2,3)")
    parser.add_argument("--suffix", type=str, default="",
                        help="출력 파일명 접미사 (예: 'test' → ch01_full_scott_test.mp4)")
    args = parser.parse_args()

    paths = chapter_paths(args.chapter)
    PNG_DIR = paths["png"]
    AUDIO_DIR = paths["audio"]
    CLIPS_DIR = paths["clips"]

    if not PNG_DIR.exists():
        print(f"⚠ PNG 디렉토리 없음: {PNG_DIR}")
        print(f"  → 먼저 PNG 생성이 필요합니다 (03_영상/ch{args.chapter}_pngs/).")
        sys.exit(1)

    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    pngs = sorted(PNG_DIR.glob("slide-*.png"))
    if args.slides:
        wanted = {int(s) for s in args.slides.split(",")}
        pngs = [p for p in pngs if int(p.stem.split("-")[-1]) in wanted]
    elif args.limit > 0:
        pngs = pngs[: args.limit]
    print(f"✓ ch{args.chapter}: {len(pngs)} 슬라이드 PNG 사용 (voice={VOICE}, speed={SPEED})")

    # 슬라이드별 클립 생성
    clip_list = []
    for png in pngs:
        slide_no = int(png.stem.split("-")[-1])
        audio = AUDIO_DIR / f"s{slide_no:02d}_{VOICE}_{speed_str(SPEED)}.mp3"
        if not audio.exists():
            print(f"  ⚠ 슬라이드 {slide_no}: 음성 없음 ({audio.name}), 스킵")
            continue
        clip_out = CLIPS_DIR / f"clip_{slide_no:02d}_{VOICE}{args.suffix}.mp4"
        duration = get_audio_duration(audio)
        print(f"  • 슬라이드 {slide_no}: {duration:.1f}초 → {clip_out.name}")
        render_slide_clip(slide_no, png, audio, clip_out, duration)
        clip_list.append(clip_out)

    # concat list 파일 생성
    list_file = CLIPS_DIR / f"_concat_{VOICE}{args.suffix}.txt"
    list_file.write_text(
        "\n".join([f"file '{f.name}'" for f in clip_list]),
        encoding="utf-8",
    )

    # 전체 영상 concat
    final_name = f"ch{args.chapter}_full_{VOICE}{args.suffix}.mp4" if args.suffix else f"ch{args.chapter}_full_{VOICE}.mp4"
    final_out = OUT_DIR / final_name
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        str(final_out),
    ]
    subprocess.run(cmd, capture_output=True, check=True)

    # 길이 확인
    duration = get_audio_duration(final_out)
    print(f"\n✓ 최종 영상: {final_out}")
    print(f"  크기: {final_out.stat().st_size // 1024}KB")
    print(f"  길이: {duration:.1f}초 = {duration / 60:.1f}분")

    # 정리
    list_file.unlink(missing_ok=True)


if __name__ == "__main__":
    main()