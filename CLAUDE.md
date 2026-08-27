# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

`lecture-pipeline` is a Korean-language lecture video production pipeline. Given one manuscript + a folder of PPTX files, it produces per-chapter narration (TTS), per-slide PNGs (PPTX→PDF→PNG), concatenated MP4s, SRT subtitles, and SCORM 1.2 zips — fully resumable across crashes and credit exhaustion.

Two-layer design: a `pipeline/` Python package (CLI + FastAPI server + state) wraps **standalone legacy scripts** under the Korean-named stage directories (`02_음성/batch_tts.py`, `03_영상/render_slides_ffmpeg.py`, `04_자막/generate_srt.py`, `06_SCORM/build_scorm.py`). `pipeline.stages.PipelineRunner` invokes those scripts via subprocess and verifies outputs against `STAGE_DEPS` + filesystem.

## Repo layout

```
lecture-pipeline/
├── pipeline/                        # Service layer (CLI + server + state)
│   ├── cli.py                       # python -m pipeline 진입점
│   ├── server.py                    # FastAPI 웹 UI (create_app(), run_server)
│   ├── orchestrator.py              # 외부 스크립트 직접 호출 (run_stage subprocess)
│   ├── stages.py                    # PipelineRunner + VERIFIERS dict + STAGE_DEPS
│   ├── state.py                     # ProjectState / ChapterState / StageState (dataclass)
│   ├── manifest.py                  # 00_매니페스트/manifest.json 래퍼
│   ├── project_wizard.py            # 새 프로젝트 디렉토리 + 폴더 스캐폴딩
│   ├── ai_providers.py              # 5개 AI 프로바이더 자동 감지 + OpenAI 호환 chat()
│   ├── voice_clone.py               # ElevenLabs Instant Voice Clone
│   ├── script_generator.py          # PPTX 텍스트 + 원고 → AI 스크립트
│   └── dashboard_gen.py             # 정적 HTML 대시보드
│
├── 02_음성/batch_tts.py             # 외부 스크립트 (ElevenLabs TTS)
├── 03_영상/generate_pngs.py         # soffice + pdftoppm
├── 03_영상/render_slides_ffmpeg.py  # ffmpeg 슬라이드 합성
├── 04_자막/generate_srt.py
├── 06_SCORM/build_scorm.py
├── 00_매니페스트/build_manifest.py  # PPTX 디렉토리 → manifest.json
├── 01_스크립트/extract_texts.py     # PPTX에서 텍스트 추출
├── 01_스크립트/generate_scripts.py  # (deprecated, use pipeline.script_generator)
│
└── <project_name>/                  # 각 강의 프로젝트 = 폴더 1개
    ├── project.json                 # ★ 진실의 원천: 챕터×스테이지 상태
    ├── 00_매니페스트/manifest.json  # PPTX 경로만 (state와 별도)
    ├── 01_스크립트/scripts/ch{NN}.txt
    ├── 02_음성/{NN}/s{NN}_*_voice_speed.mp3
    ├── 03_영상/ch{NN}_pngs/         # 2000x1125
    ├── 04_자막/ch{NN}.srt
    ├── 05_MP4/ch{NN}_full_{voice}.mp4
    ├── 06_SCORM/scorm_ch{NN}.zip
    └── .env                         # gitignore 대상
```

## Setup

```bash
# Python 3.13 권장. 외부 스크립트는 .venv-tts 사용 (elevenlabs + 모든 의존성)
python3 -m venv .venv-tts
source .venv-tts/bin/activate
pip install elevenlabs openai anthropic python-dotenv python-pptx fastapi uvicorn

cp .env.example .env  # API 키 채우기
```

`PipelineRunner._python()`은 항상 `.venv-tts/bin/python`을 호출한다. `.venv`는 일부 도우미용이지만 외부 스크립트는 `.venv-tts`에서 실행됨.

## Common commands

모든 명령은 **프로젝트 루트** (`project.json`이 있는 디렉토리)에서 실행. CLI는 `python -m pipeline ...`.

```bash
# 0. 새 프로젝트 (대화형 또는 비대화형)
python -m pipeline new-project --name "강의명" --pptx-dir /path/to/pptx --manuscript /path/to/manuscript.md

# 1. 상태 확인 (실제 파일로 재동기화하려면 --verify)
python -m pipeline status
python -m pipeline status ch04
python -m pipeline status --verify       # ★ 산출물 누락 시 state 교정

# 2. AI 스크립트 생성 (PPTX + 원고 → ch{NN}.txt)
python -m pipeline generate-scripts --project-dir . --all
python -m pipeline generate-scripts --project-dir . --chapter 04 --provider anthropic

# 3. 음성 클론 (ElevenLabs IVC, 1~3개 참조 음성)
python -m pipeline clone-voice --project-dir . --ref-audio ref1.wav --name scott

# 4. 파이프라인 실행 (--force로 완료된 단계도 재실행)
python -m pipeline run ch04 tts --force
python -m pipeline run ch04             # 챕터 전체 (의존성 순서)

# 5. 웹 UI (FastAPI)
python -m pipeline serve --port 8765

# 6. 정적 대시보드 (서버 없이 즉시)
python -m pipeline dashboard
# → pipeline/dashboard.html 열기

# 7. 챕터 가변 추가/삭제
python -m pipeline add 18 --pptx path.pptx --section "5부"
python -m pipeline remove 18 --force

# 8. AI 프로바이더 점검
python -m pipeline ai
```

## 아키텍처 핵심

### 상태 (state.py)
- `ProjectState.chapters: dict[str, ChapterState]` — 챕터 번호 `"01".."17"`이 키
- `ChapterState.stages: dict[str, StageState]` — 7단계 키: `script | pngs | voice_clone | tts | render | srt | scorm`
- `StageState.status`: `pending | in_progress | completed | failed | partial` (모두 상수 `PENDING` 등)
- `STAGE_DEPS`가 단계 간 의존성을 정의. `script`/`pngs`는 독립, `tts`는 script 후, `render`는 pngs+tts 후, `scorm`은 render+srt 후.
- `ProjectState.save(path)` / `ProjectState.load(path)` — JSON 직렬화 (UTF-8, ensure_ascii=False)

### 단계 실행 (stages.py)
- `PipelineRunner.run(ch, stage, force=False)` — 의존성 체크 → 실행 → verify → state 업데이트 → 저장
- `PipelineRunner.run_chapter(ch, force=False)` — 의존성 순서대로 전체 7단계
- `_execute()`는 `script` 단계는 자동 실행 안 함 ("수동 또는 AI 별도 호출 필요" 반환). 나머지는 외부 스크립트 subprocess 호출.
- `VERIFIERS` dict는 각 단계의 산출물 검사. `tts`는 glob `s*_{voice}_x{1_1}.mp3` 패턴으로 부분 진행까지 카운트 (e.g., `partial` → `12/34장`).

### 오케스트레이터 (orchestrator.py) — 직접 호출 경로
- `STAGE_SCRIPTS` dict에 외부 스크립트 경로 hard-coded: `02_음성/batch_tts.py`, `03_영상/render_slides_ffmpeg.py`, `04_자막/generate_srt.py`, `06_SCORM/build_scorm.py`.
- `run_chapter()`는 이 경로를 직접 subprocess 실행 (PipelineRunner 우회). 로그를 `pipeline/logs/ch{NN}.log`에 누적.
- **`pipeline run`은 `PipelineRunner` 경로, `python -m pipeline.orchestrator`는 직접 subprocess 경로.** 두 경로가 동시에 산출물을 만든다 — state 동기화는 항상 `status --verify`로.

### AI 프로바이더 (ai_providers.py)
- 5개 모두 OpenAI 호환 `/chat/completions`: `openai`, `anthropic`, `zhipu` (z.ai GLM-4.6), `moonshot` (Kimi k2), `MiniMax`
- `detect_providers()`는 환경변수 키 존재만으로 자동 등록. `urllib.request`만 사용 (외부 SDK 없음).
- 선택 우선순위: 인자 → `DEFAULT_AI_PROVIDER` env → 첫 번째 등록된 프로바이더.
- Anthropic은 `extra_headers={"anthropic-version": "2023-06-01"}`만 다름.

### 음성 클론 (voice_clone.py)
- ElevenLabs Instant Voice Clone만 사용. `02_음성/voice_ref/`에 참조 음성 복사 후 `client.voices.ivc.create()` 호출.
- 성공 시 `project.json`의 `elevenlabs.voice_id` 갱신 + `.env`의 `ELEVENLABS_VOICE_ID` 동기화.
- 클론 ID는 `defaults.voice` (라벨, e.g. "scott")와 함께 TTS 파일명 `{voice}_x{1_1}.mp3`에 들어감.

### 스크립트 생성 (script_generator.py)
- `read_slide_texts()`: python-pptx로 슬라이드 텍스트 추출
- `read_manuscript_excerpt()`: 마크다운 원고에서 `## Chapter N` / `# N장` 마커로 챕터 경계 찾기 → window 2만큼 발췌
- `parse_script_output()`: AI 응답에서 `<번호>\t<텍스트>` 파싱 (80% 미만이면 부분만 저장, 누락 슬라이드는 placeholder)
- 시스템 프롬프트: 슬라이드당 60~80초 구어체, "선생님" 호칭, 15~20어절 호흡

### 서버 (server.py)
- FastAPI, `uvicorn.Server(config).run()` 직접 호출 (uvicorn 0.52.4 hang 우회).
- 엔드포인트: `/`, `/chapter/{ch}`, `/api/status`, `POST /api/run/{ch}/{stage}`, `POST /api/sync`, `/projects`, `POST /api/projects/create`, `POST /api/projects/{name}/clone-voice`, `POST /api/projects/{name}/generate-scripts/{chapter|all}`, `POST /api/projects/{name}/run/{chapter}`
- 다중 프로젝트 모드: `PROJ_DEFAULT.parent`를 스캔해 `project.json` 가진 디렉토리 모두 노출.
- 백그라운드 작업 결과는 메모리 `_run_log: dict[tuple[str, str], list[str]]`에 누적 (재시작 시 휘발).

## 환경변수 (.env)

`.env.example` 참고. 주요 키:
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `ZAI_API_KEY`, `MOONSHOT_API_KEY`, `MINIMAX_API_KEY` — 필요한 것만
- `DEFAULT_AI_PROVIDER` — `openai|anthropic|zhipu|moonshot|MiniMax`
- `ELEVENLABS_API_KEY` — 음성 클론 + TTS (월 90,000자 / 17�터 ≈ 한 학기 1회)
- `PIPELINE_PROJ_DIR` — 기본 프로젝트 경로 (CLI/서버가 자동 인식)
- `DEFAULT_VOICE`, `DEFAULT_SPEED` — TTS 파일명 라벨 / 속도

`.env`는 gitignore. `.env.example`만 커밋.

## 알려진 이슈 / 함정

- **uvicorn 0.52.4 + Python 3.13**: `uvicorn.run()`이 hang. `server.py`는 이미 `uvicorn.Server(config).run()` 우회. 다른 곳에서 uvicorn 호출하지 말 것.
- **PPTX → PNG는 순차 처리**: soffice 동시 실행 시 lock 충돌. `generate_pngs.py` 내부에서 이미 직렬화.
- **state와 실제 파일 불일치**: TTS가 외부에서 돌다가 죽으면 `project.json`은 `completed`인데 파일 일부 누락일 수 있음. `status --verify` 또는 `python -m pipeline sync`로 재동기화.
- **`pipeline run` vs `pipeline.orchestrator`**: 둘 다 실행 가능하지만 state 업데이트 경로가 다름. 일반적으로 `pipeline run` 권장.
- **ElevenLabs 월간 크레딧**: 90,000자. 한 학기 분량 1회 충전 필요.
- **PPTX 파일명 규약**: `chapter_from_pptx()`가 `^(\d+)장` 정규식만 인식. `1장_제목.pptx` → `01`. 다른 명명 규칙은 `add`로 수동 매핑.
- **마크다운 원고 마커**: `script_generator.read_manuscript_excerpt()`가 `## Chapter N` / `# N장` / `## N장` 형식만 탐지. 마커 없으면 앞 3000자만 발췌.
- **AI 응답 파싱**: 80% 미만 파싱 시 부분 저장 + 누락 슬라이드는 `(슬라이드 N 자동 생성 실패 - 직접 작성 필요)` placeholder. TTS 단계는 그 placeholder를 그대로 읽음.

## 작업 시 체크리스트

- 새 기능 추가 시: `pipeline/` (service layer)에 둘지, `02_음성/` 등 외부 스크립트에 둘지 결정. UI/CLI/state는 service layer, 실제 변환 로직은 외부 스크립트가 기본 분리.
- 상태 추가 시: `state.py`의 `StageState`/`ChapterState`/`ProjectState` dataclass와 `to_dict`/`from_dict` 동기화 필수 (JSON 호환성).
- 새 검증 추가 시: `stages.py`의 `VERIFIERS` dict에 등록.
- 새 CLI 명령 추가 시: `cli.py`의 `cmd_xxx` 함수 + `main()`의 sub-parser에 등록.
- 새 AI 프로바이더 추가 시: `ai_providers.py`의 `detect_providers()`에 한 블록 추가.
- 산출물 파일 패턴 변경 시 (e.g., MP3 파일명 규칙): `stages.py`의 `_verify_*`도 함께 수정.
