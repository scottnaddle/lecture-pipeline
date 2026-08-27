#!/usr/bin/env python3
"""
ElevenLabs Instant Clone 샘플.

1) .env에서 ELEVENLABS_API_KEY 로드
2) ref_clip1~3 중 하나로 Instant Clone 목소리 생성 (또는 기존 voice_id 사용)
3) 한국어 강의 문장 2개 합성 → MP3 저장
4) 결과를 듣고 결정

최초 실행 시만 클론 생성. voice_id는 .env에 저장해 두면 재사용.
"""
from __future__ import annotations
import os
import time
from pathlib import Path
from dotenv import load_dotenv

BASE = Path(
    "/Users/scott/Library/CloudStorage/GoogleDrive-scott@naddle.net/내 드라이브/"
    "개인/개인 자료/[2024] 대구교대 강의/26년2학기/강의영상_제작"
)
ENV_FILE = BASE / ".env"
REF_DIR = BASE / "02_음성" / "voice_ref"
OUT_DIR = BASE / "02_음성" / "clone_sample_el"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SENTENCES = {
    "a_intro": "안녕하세요, 선생님들. 이번 장에서는 예측과 현실, "
               "무엇이 맞았고 무엇이 빗나갔는지 이야기 나눠 보겠습니다.",
    "b_tech": "생성형 AI가 교실에 들어온 뒤, 정의적 영역의 평가는 "
              "오히려 더 어려워졌습니다. 2019년의 예측은 방향은 맞았지만 "
              "생각보다 복잡해졌습니다.",
}

load_dotenv(ENV_FILE)
api_key = os.getenv("ELEVENLABS_API_KEY")
if not api_key:
    raise SystemExit("ELEVENLABS_API_KEY 없음")
print(f"키 로드 완료 (길이 {len(api_key)}자)")

from elevenlabs import ElevenLabs

client = ElevenLabs(api_key=api_key)

# 잔여 크레딧 확인 — user_read 권한이 있는 키일 때만 동작. 없으면 무시.
try:
    sub = client.user.subscription.get()
    print(f"사용량: {sub.character_count}/{sub.character_limit}자, "
          f"남은 {sub.character_limit - sub.character_count}자")
except Exception as e:
    print(f"(잔여 크레딧 확인 건너뜀 — user_read 권한 없음. 합성은 진행됩니다.)")

# === 목소리 클론 ===
# 1) 기존 voice_id 재사용 가능
voice_id = os.getenv("ELEVENLABS_VOICE_ID")

# 2) 없으면 ref_clip1로 Instant Clone 생성
if not voice_id:
    ref = REF_DIR / "ref_clip1.wav"
    print(f"\nInstant Clone 생성 중... (ref: {ref.name})")
    t0 = time.time()
    voice = client.voices.ivc.create(
        name="dnue-scott-1",
        files=[(ref.name, ref.read_bytes(), "audio/wav")],
        labels={},
    )
    voice_id = voice.voice_id
    print(f"  ✓ voice_id: {voice_id} ({time.time()-t0:.1f}초)")
    print(f"  → 이 voice_id를 .env에 ELEVENLABS_VOICE_ID로 저장하면 재사용됩니다.")
else:
    print(f"재사용 voice_id: {voice_id}")

# === 샘플 합성 ===
# multilingual_v2 모델 + 한국어, 출력은 mp3 44100Hz
print("\n샘플 합성 중...")
for key, text in SENTENCES.items():
    out = OUT_DIR / f"smoke_{key}.mp3"
    t0 = time.time()
    audio = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )
    # generate() returns iterator of bytes in newer SDK
    if isinstance(audio, (bytes, bytearray)):
        data = bytes(audio)
    else:
        data = b"".join(audio)
    out.write_bytes(data)
    print(f"  ✓ {out.name}: {len(out.read_bytes())//1024}KB, "
          f"{time.time()-t0:.1f}초, {len(text)}자")

print(f"\n결과: {OUT_DIR}")
print("들어보고 자연스러우면 batch_tts.py 백엔드 교체로 넘어갑니다.")
