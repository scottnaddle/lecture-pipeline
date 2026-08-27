#!/usr/bin/env python3
"""
Phase 3 batch: 슬라이드별 스크립트 일괄 TTS 합성.

백엔드: openai (tts-1-hd, 프리셋 음성) | elevenlabs (Instant Voice Clone, voice_id)

사용법:
    # ElevenLabs (기본) — .env의 ELEVENLABS_VOICE_ID 사용, 1.1x
    python batch_tts.py --chapter 01
    python batch_tts.py --all

    # OpenAI
    python batch_tts.py --backend openai --chapter 01 --voice onyx --speed 1.2

    # 특정 슬라이드만
    python batch_tts.py --chapter 01 --slides 1,2,3

스크립트 파일 형식:
    01_스크립트/scripts/ch{NN}.txt
    각 줄: <slide_no>\t<text>
    빈 줄은 무시, '#' 시작 줄은 주석

출력:
    02_음성/{chapter_no}/s{NN}_{voice}_x{speed}.mp3
    02_음성/{chapter_no}/concat.mp3  (전체 슬라이드 순서대로 합친 버전)
"""
from __future__ import annotations
import argparse
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
import subprocess

BASE = Path("/Users/scott/Library/CloudStorage/GoogleDrive-scott@naddle.net/내 드라이브/개인/개인 자료/[2024] 대구교대 강의/26년2학기")
SCRIPT_DIR = BASE / "강의영상_제작" / "01_스크립트" / "scripts"
VOICE_DIR = BASE / "강의영상_제작" / "02_음성"
ENV_FILE = BASE / "강의영상_제작" / ".env"
MANIFEST = BASE / "강의영상_제작" / "00_매니페스트" / "manifest.json"

import json


def load_scripts(chapter_no: str) -> list[dict]:
    """ch01.txt 형식: 한 줄 = 'slide_no<TAB>text'."""
    path = SCRIPT_DIR / f"ch{chapter_no}.txt"
    if not path.exists():
        raise FileNotFoundError(f"스크립트 파일 없음: {path}")
    out = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" not in line:
            continue
        no_str, text = line.split("\t", 1)
        no = int(no_str.strip())
        text = text.strip()
        if text:
            out.append({"slide_no": no, "text": text})
    out.sort(key=lambda d: d["slide_no"])
    return out


def synthesize(client: OpenAI, text: str, out_path: Path, voice: str, speed: float, model: str = "tts-1-hd",
                backend: str = "openai", voice_id: str | None = None) -> tuple[float, int]:
    """한 슬라이드 MP3 합성. (소요초, 바이트) 반환."""
    if out_path.exists() and out_path.stat().st_size > 0:
        return 0.0, out_path.stat().st_size
    t0 = time.time()
    if backend == "elevenlabs":
        # 지연 import: 백엔드별로 필요 패키지만 로드
        from elevenlabs import ElevenLabs
        from elevenlabs.types.voice_settings import VoiceSettings
        el_client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
        audio = el_client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
            voice_settings=VoiceSettings(speed=speed),
        )
        data = audio if isinstance(audio, (bytes, bytearray)) else b"".join(audio)
        out_path.write_bytes(data)
    else:
        from openai import OpenAI
        if client is None:
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        resp = client.audio.speech.create(
            model=model,
            voice=voice,  # type: ignore
            input=text,
            speed=speed,
            response_format="mp3",
        )
        out_path.write_bytes(resp.content)
    return time.time() - t0, out_path.stat().st_size


def concat_chapter(chapter_no: str, voice: str, speed: float) -> Path | None:
    """챕터 디렉토리의 모든 MP3를 concat해서 concat.mp3 생성 (ffmpeg 사용)."""
    ch_dir = VOICE_DIR / chapter_no
    files = sorted(ch_dir.glob(f"s*_{voice}_x{speed}.mp3"))
    if not files:
        return None
    # ffmpeg concat list
    list_file = ch_dir / "_concat_list.txt"
    list_file.write_text(
        "\n".join([f"file '{f.name}'" for f in files]),
        encoding="utf-8",
    )
    concat_path = ch_dir / f"concat_{voice}_x{speed}.mp3"
    # ffmpeg 호출
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            str(concat_path),
        ],
        capture_output=True,
        text=True,
    )
    list_file.unlink(missing_ok=True)
    if result.returncode != 0:
        print(f"  ⚠ concat 실패: {result.stderr[-200:]}")
        return None
    return concat_path


def run(args):
    if not ENV_FILE.exists():
        print(f"⚠ {ENV_FILE} 없음")
        sys.exit(1)
    load_dotenv(ENV_FILE)

    backend = args.backend
    client = None
    voice_id = None
    if backend == "elevenlabs":
        if not os.getenv("ELEVENLABS_API_KEY"):
            print("⚠ ELEVENLABS_API_KEY 미설정")
            sys.exit(1)
        voice_id = os.getenv("ELEVENLABS_VOICE_ID")
        if not voice_id:
            print("⚠ ELEVENLABS_VOICE_ID 미설정 — 먼저 clone_sample_el.py로 클론 생성")
            sys.exit(1)
        print(f"백엔드: ElevenLabs, voice_id={voice_id}, speed={args.speed}")
    else:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("⚠ OPENAI_API_KEY 미설정")
            sys.exit(1)
        client = OpenAI(api_key=api_key)
        print(f"백엔드: OpenAI, voice={args.voice}, speed={args.speed}")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    chapters = [c["chapter_no"] for c in manifest["chapters"]]

    speed_str = f"x{args.speed}".replace(".", "_")
    voice_name = args.voice  # ElevenLabs도 파일명에 이 이름 사용
    targets = []
    if args.all:
        targets = [(c, voice_name, args.speed) for c in chapters]
    elif args.chapter:
        targets = [(args.chapter, voice_name, args.speed)]
    else:
        print("--chapter 또는 --all 필요")
        sys.exit(1)

    total_files = 0
    total_bytes = 0
    for ch_no, voice, speed in targets:
        try:
            scripts = load_scripts(ch_no)
        except FileNotFoundError as e:
            print(f"  ⚠ {e}")
            continue

        if args.slides:
            wanted = {int(s) for s in args.slides.split(",")}
            scripts = [s for s in scripts if s["slide_no"] in wanted]
        if args.limit:
            scripts = scripts[: args.limit]

        ch_dir = VOICE_DIR / ch_no
        ch_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== 챕터 {ch_no}: {len(scripts)}개 슬라이드 (voice={voice}, speed={speed}) ===")

        for s in scripts:
            out_path = ch_dir / f"s{s['slide_no']:02d}_{voice}_{speed_str}.mp3"
            try:
                dt, size = synthesize(client, s["text"], out_path, voice, speed,
                                      backend=backend, voice_id=voice_id)
                total_files += 1
                total_bytes += size
                status = f"{dt:.1f}s, {size//1024}KB" if dt > 0 else "cached"
                print(f"  • 슬라이드 {s['slide_no']:>2} → {status}")
            except Exception as e:
                print(f"  • 슬라이드 {s['slide_no']:>2} → FAIL: {e}")
            time.sleep(0.15)

        # 챕터 단위 concat
        if not args.slides:
            concat_path = concat_chapter(ch_no, voice, speed)
            if concat_path:
                print(f"  ✓ concat: {concat_path.name} ({concat_path.stat().st_size//1024}KB)")

    print(f"\n총 {total_files}개 파일, {total_bytes//1024}KB 생성")
    print(f"저장 위치: {VOICE_DIR}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--chapter", help="챕터 번호 (예: 01)")
    p.add_argument("--all", action="store_true", help="17챕터 전체")
    p.add_argument("--slides", help="콤마 구분 슬라이드 번호 (예: 1,2,3)")
    p.add_argument("--limit", type=int, help="처음 N개만")
    p.add_argument("--backend", choices=["openai", "elevenlabs"], default="elevenlabs",
                   help="TTS 백엔드 (기본: elevenlabs)")
    p.add_argument("--voice", default="scott",
                   help="OpenAI 프리셋 이름 또는 ElevenLabs 출력 파일명용 라벨 (기본: scott)")
    p.add_argument("--speed", type=float, default=1.1)
    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()