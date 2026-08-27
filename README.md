# lecture-pipeline

원고 + PPTX → 음성 → 영상 → SCORM 패키지까지 자동화하는 한국어 강의 영상 제작 파이프라인.

교수 1명이 "원고 한 권 + PPTX 한 폴더"만 던지면 17챕터 분량의 강의 영상을 만들 수 있게 하는 것이 목표입니다.

## 특징

- **다중 AI 프로바이더**: OpenAI / Anthropic / z.ai (GLM) / Moonshot (Kimi) / MiniMax 자동 감지
- **즉시 재개**: 시스템 종료, 크레딧 소진 등 실패 시 완료된 슬라이드부터 이어서 실행
- **상태 추적**: `project.json`에 17챕터 × 7단계(script/pngs/voice_clone/tts/render/srt/scorm) 완료 여부 기록
- **가변 차시 수**: 차시는 매니페스트 기반, 추가/삭제 자유
- **음성 클론 통합**: `02_음성/voice_ref/`의 참조 음성만 넣으면 파이프라인 run 시 자동 클론
- **CLI + Web UI**: FastAPI 대시보드 또는 정적 HTML (서버 없이 가능)

## 디렉토리 구조

```
lecture-pipeline/
├── pipeline/                    # 서비스 레이어 (메인)
│   ├── __main__.py             # python -m pipeline 진입점
│   ├── cli.py                  # CLI 명령어
│   ├── server.py               # FastAPI 웹 서버
│   ├── state.py                # project.json 모델
│   ├── stages.py               # 7단계 실행/검증
│   ├── orchestrator.py         # 전체 파이프라인 한 번에 실행
│   ├── project_wizard.py       # 새 프로젝트 만들기
│   ├── script_generator.py     # AI 스크립트 자동 생성
│   ├── voice_clone.py          # ElevenLabs 음성 클론
│   ├── ai_providers.py         # 다중 AI 프로바이더 추상화
│   ├── manifest.py            # 00_매니페스트/manifest.json 래퍼
│   └── dashboard_gen.py        # 정적 HTML 대시보드
│
├── 01_스크립트/scripts/         # ch01.txt, ch02.txt, ... (per-chapter)
├── 02_음성/{NN}/              # MP3 per slide + concat
├── 02_음성/voice_ref/         # ElevenLabs Instant Voice Clone 참조
├── 03_영상/ch{NN}_pngs/       # PPTX → PDF → PNG (2000x1125)
├── 03_영상/ch{NN}_clips/      # per-slide video clips
├── 04_자막/ch{NN}.srt         # subtitles
├── 05_MP4/ch{NN}_full_*.mp4   # concatenated chapter video
├── 06_SCORM/scorm_ch{NN}.zip  # LMS upload
│
├── 00_매니페스트/manifest.json # 챕터 정의 (PPT 경로)
├── project.json                # 서비스 state
├── .env                        # API 키 (gitignored)
└── .env.example                # 템플릿 (커밋됨)
```

## 설치

```bash
# 1) Python 3.13+ 권장
python3 --version

# 2) 의존성 설치
python3 -m venv .venv-tts
source .venv-tts/bin/activate
pip install elevenlabs openai anthropic python-dotenv python-pptx fastapi uvicorn

# 3) 환경변수 설정
cp .env.example .env
# .env 편집: 필요한 API 키 채우기

# 4) 기존 파이프라인 스크립트 (lecture-pipeline과 같은 디렉토리에)
# batch_tts.py, render_slides_ffmpeg.py, generate_pngs.py,
# generate_srt.py, build_scorm.py, clone_sample_el.py, build_manifest.py
# → 이 리포에는 포함되어 있음. 이 경로가 lecture-pipeline/의 부모 디렉토리.
```

## 사용법

### A. 정적 대시보드 (서버 없이 즉시)

```bash
cd /path/to/your/project
python3 -m pipeline init    # project.json 생성 (최초 1회)
python3 -m pipeline dashboard
# 브라우저에서 pipeline/dashboard.html 열기
```

### B. CLI 명령어

```bash
# 상태 확인
python3 -m pipeline status               # 전체 프로젝트
python3 -m pipeline status ch04          # 특정 챕터
python3 -m pipeline status --verify      # 실제 파일로 검증 후 state 동기화

# 새 프로젝트 (다른 학기, 다른 교재)
python3 -m pipeline new-project --name "AI 시대 교육" \
  --pptx-dir /path/to/pptx \
  --manuscript /path/to/text.md

# 음성 클론 (선택: 즉시 실행, 또는 02_음성/voice_ref/*.wav 두고 pipeline run 시 자동)
python3 -m pipeline clone-voice --project-dir . --ref-audio ref1.wav

# AI 스크립트 자동 생성 (PPTX + 원고 → 35장 분량 나레이션)
python3 -m pipeline generate-scripts --project-dir . --all

# 음성 클론만 단독 실행 (파이프라인 단계)
python3 -m pipeline run ch01 voice_clone

# 전체 파이프라인 실행 (PNG → 음성 클론 → TTS → 렌더 → SRT → SCORM)
python3 -m pipeline run --project-dir . --all

# 챕터 추가/제거
python3 -m pipeline add 18 --pptx ... --section "5부"
python3 -m pipeline remove 18

# AI 프로바이더 상태
python3 -m pipeline ai
```

### C. 웹 UI (FastAPI)

```bash
# uvicorn 0.52.4 hang 버그 우회: uvicorn.Server(config).run() 사용
# → server.py의 run_server()는 이미 이 방식으로 구현됨

python3 -m pipeline serve --host 127.0.0.1 --port 8765
# 브라우저에서 http://127.0.0.1:8765 접속

# 포트 충돌 시 다른 포트
python3 -m pipeline serve --port 9200
```

## 환경변수 (.env)

```bash
# AI 프로바이더 (필요한 것만 채우기)
OPENAI_API_KEY=sk-...           # gpt-4o 등
ANTHROPIC_API_KEY=sk-ant-...    # claude-sonnet-4-5 등
ZAI_API_KEY=...                 # z.ai GLM-4.6
MOONSHOT_API_KEY=...            # Kimi
MINIMAX_API_KEY=...             # MiniMax

# 기본 프로바이더 (openai | anthropic | zhipu | moonshot | minimax)
DEFAULT_AI_PROVIDER=openai

# ElevenLabs
ELEVENLABS_API_KEY=sk_...       # 음성 클론 + TTS
ELEVENLABS_VOICE_ID=...         # 클론 후 자동 저장
ELEVENLABS_MODEL=eleven_multilingual_v2

# 파이프라인 경로 (기본: 현재 디렉토리)
PIPELINE_PROJ_DIR=/path/to/your/project

# 음성 설정
DEFAULT_VOICE=main               # 파일명에 들어가는 라벨
DEFAULT_SPEED=1.1                # TTS 속도
```

## 7단계 파이프라인

| # | 단계 | 입력 | 출력 | 비고 |
|---|---|---|---|---|
| 1 | script | PPTX 텍스트 + 원고 | `01_스크립트/scripts/ch{NN}.txt` | AI 또는 수동 |
| 2 | pngs | PPTX | `03_영상/ch{NN}_pngs/slide-*.png` | soffice + pdftoppm |
| 3 | voice_clone | `02_음성/voice_ref/*.wav` | `project.json` (voice_id) | ElevenLabs Instant Voice Clone. `02_음성/voice_ref/`에 .wav만 두면 `pipeline run` 시 자동 실행. 이미 voice_id 있으면 스킵 |
| 4 | tts | 스크립트 + voice_id | `02_음성/{NN}/s{NN}_*.mp3` | ElevenLabs TTS. voice_clone 완료된 voice_id 사용 |
| 5 | render | PNG + MP3 | `05_MP4/ch{NN}_full_*.mp4` | ffmpeg, bilinear, 정적 (떨림 없음) |
| 6 | srt | MP3 길이 + 스크립트 | `04_자막/ch{NN}.srt` | 자막 자동 분할 |
| 7 | scorm | MP4 + SRT | `06_SCORM/scorm_ch{NN}.zip` | SCORM 1.2 패키지 |

**의존성** (`STAGE_DEPS`): `script/pngs/voice_clone`은 독립, `tts`는 `script + voice_clone`, `render`는 `pngs + tts`, `srt`는 `tts`, `scorm`은 `render + srt` 후 실행 가능.

## 차시 수 가변

`pipeline add N` / `pipeline remove N`으로 차시 추가/제거 자유. 매니페스트(`00_매니페스트/manifest.json`)에서 PPTX 파일을 스캔하므로 PPTX가 N개면 자동으로 N챕터로 구성.

## 알려진 이슈

- **uvicorn 0.52.4 + Python 3.13**: `uvicorn.run()`이 hang. server.py는 이미 `uvicorn.Server(config).run()`으로 우회.
- **ElevenLabs 월간 크레딧**: 90,000자/월 기본. 17챕터 약 90,000자. 한 학기당 한 번 충전 필요.
- **PPTX → PNG는 한 번에 하나씩**: soffice 동시 실행 시 lock 파일 충돌. 순차 처리됨.

## 라이선스

MIT
