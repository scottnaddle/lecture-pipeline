"""FastAPI 웹 서버.

`python -m pipeline serve` 로 실행. 브라우저에서 http://127.0.0.1:8765 접속.

기능:
- /                    : 프로젝트 대시보드 (전체 챕터 상태)
- /chapter/{no}        : 챕터 상세
- /api/status          : JSON 상태
- /api/run/{ch}/{stage} : 단계 실행 (백그라운드)
- /api/sync            : state 재동기화
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Optional

try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks
    from fastapi.responses import HTMLResponse
except ImportError:
    raise SystemExit("FastAPI 필요: pip install fastapi uvicorn jinja2")

from .state import (
    ProjectState, ChapterState, StageState,
    PENDING, IN_PROGRESS, COMPLETED, FAILED, PARTIAL,
    ALL_STAGES, STAGE_LABELS, STAGE_DEPS,
)
from .stages import PipelineRunner, StageResult
from .manifest import Manifest

import os

def _resolve_proj() -> Path:
    """프로젝트 경로 결정. 우선순위: 환경변수 > 현재 디렉토리의 project.json."""
    env = os.getenv("PIPELINE_PROJ_DIR")
    if env:
        return Path(env).expanduser().resolve()
    cwd_proj = Path.cwd() / "project.json"
    if cwd_proj.exists():
        return Path.cwd().resolve()
    # 기본값: 현재 디렉토리 (이때 새 프로젝트가 됨)
    return Path.cwd().resolve()


PROJ_DEFAULT = _resolve_proj()
MANIFEST = PROJ_DEFAULT / "00_매니페스트" / "manifest.json"
STATE = PROJ_DEFAULT / "project.json"

# 간단한 진행 상태 (메모리) — 실서비스에선 Redis/DB 권장
_run_log: dict[tuple[str, str], list[str]] = {}


def _load_state() -> ProjectState:
    if not STATE.exists():
        raise HTTPException(503, f"project.json 없음. `python -m pipeline init` 먼저 실행")
    return ProjectState.load(STATE)


def _runner() -> PipelineRunner:
    return PipelineRunner(PROJ_DEFAULT, _load_state())


def _status_badge(status: str) -> str:
    colors = {
        PENDING: "#999",
        IN_PROGRESS: "#e0a800",
        COMPLETED: "#28a745",
        FAILED: "#dc3545",
        PARTIAL: "#fd7e14",
    }
    labels = {
        PENDING: "대기",
        IN_PROGRESS: "진행",
        COMPLETED: "완료",
        FAILED: "실패",
        PARTIAL: "부분",
    }
    color = colors.get(status, "#666")
    label = labels.get(status, status)
    return f'<span class="badge" style="background:{color}">{label}</span>'


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 1100px; margin: 24px auto; padding: 0 16px; color: #222; }}
h1 {{ font-size: 1.4em; border-bottom: 2px solid #333; padding-bottom: 6px; }}
h2 {{ font-size: 1.1em; margin-top: 24px; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 3px; color: white; font-size: 0.78em; font-weight: 600; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
th, td {{ padding: 6px 10px; text-align: left; border-bottom: 1px solid #eee; font-size: 0.92em; }}
th {{ background: #f4f4f4; }}
.stage-cell {{ display: flex; justify-content: space-between; align-items: center; }}
a {{ color: #06c; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
button {{ background: #06c; color: white; border: none; padding: 4px 10px; border-radius: 3px; cursor: pointer; font-size: 0.8em; }}
button:hover {{ background: #0050a0; }}
button:disabled {{ background: #ccc; cursor: not-allowed; }}
pre.log {{ background: #1e1e1e; color: #ddd; padding: 8px; border-radius: 3px; font-size: 0.78em; max-height: 240px; overflow-y: auto; }}
.meta {{ color: #666; font-size: 0.85em; }}
.nav {{ background: #f4f4f4; padding: 8px 12px; border-radius: 3px; margin-bottom: 16px; }}
.nav a {{ margin-right: 12px; }}
</style>
</head>
<body>
<div class="nav">
<a href="/">대시보드</a>
<a href="/api/status">JSON</a>
<form method="post" action="/api/sync" style="display:inline"><button type="submit">동기화</button></form>
</div>
{body}
</body>
</html>"""


def _chapter_row_html(state: ProjectState, ch_no: str) -> str:
    ch = state.get_chapter(ch_no)
    title = ch.title or "(제목 없음)"
    section = ch.section or ""
    cells = []
    for s in ALL_STAGES:
        st = ch.get_stage(s)
        cells.append(f'<td>{_status_badge(st.status)}</td>')
    return f"""<tr>
<td><a href="/chapter/{ch_no}">ch{ch_no}</a></td>
<td>{title}<div class="meta">{section}</div></td>
{''.join(cells)}
</tr>"""


def _index(state: ProjectState) -> str:
    body = f"""
<h1>{state.name}</h1>
<p class="meta">프로젝트: {state.project_id} · 챕터 수: {len(state.chapters)} · 음성: <code>{state.elevenlabs.get('voice_id', '?')}</code></p>
<table>
<tr><th>챕터</th><th>제목</th>
{''.join(f'<th>{STAGE_LABELS[s]}</th>' for s in ALL_STAGES)}
</tr>
{''.join(_chapter_row_html(state, ch) for ch in sorted(state.chapters.keys()))}
</table>
"""
    return _page("대시보드", body)


def _chapter_detail(state: ProjectState, ch_no: str) -> str:
    if ch_no not in state.chapters:
        raise HTTPException(404, f"ch{ch_no} 없음")
    ch = state.get_chapter(ch_no)
    title = ch.title or "(제목 없음)"
    body = f"""
<h1>ch{ch_no} — {title}</h1>
<p class="meta">섹션: {ch.section} · 길이: {ch.duration_min}분</p>
<table>
<tr><th>단계</th><th>상태</th><th>진행</th><th>완료시각</th><th>액션</th></tr>
"""
    for stage in ALL_STAGES:
        st = ch.get_stage(stage)
        progress = ""
        if st.status == PARTIAL and st.details:
            c, t = st.details.get("completed"), st.details.get("total")
            if c is not None and t is not None:
                progress = f"{c}/{t} ({int(100*c/t)}%)"
        completed_at = st.completed_at or "-"
        body += f"""<tr>
<td>{STAGE_LABELS[stage]}</td>
<td>{_status_badge(st.status)}</td>
<td>{progress}</td>
<td class="meta">{completed_at}</td>
<td>
<form method="post" action="/api/run/{ch_no}/{stage}" style="display:inline">
<button type="submit" {'disabled' if st.status == IN_PROGRESS else ''}>
{'진행 중' if st.status == IN_PROGRESS else '실행'}
</button>
</form>
</td>
</tr>
"""
    body += "</table>"

    # 실행 로그 표시
    for stage in ALL_STAGES:
        log = _run_log.get((ch_no, stage), [])
        if log:
            body += f"<h2>{STAGE_LABELS[stage]} 실행 로그</h2><pre class='log'>{'<br>'.join(log[-50:])}</pre>"

    return _page(f"ch{ch_no}", body)


def _run_stage_task(ch_no: str, stage: str):
    """백그라운드 태스크."""
    log_key = (ch_no, stage)
    _run_log.setdefault(log_key, [])
    try:
        state = _load_state()
        runner = PipelineRunner(PROJ_DEFAULT, state)
        _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] 시작: {STAGE_LABELS[stage]}")
        result = runner.run(ch_no, stage, force=False)
        _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] {result.status}: {result.message[:200]}")
        state.save(STATE)
    except Exception as e:
        _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] 오류: {e}")



    @app.get("/", response_class=HTMLResponse)
    def index():
        return _index(_load_state())

    @app.get("/chapter/{ch_no}", response_class=HTMLResponse)
    def chapter(ch_no: str):
        return _chapter_detail(_load_state(), ch_no)

    @app.get("/api/status")
    def api_status():
        return _load_state().to_dict()

    @app.post("/api/run/{ch_no}/{stage}")
    def api_run(ch_no: str, stage: str, background_tasks: BackgroundTasks):
        if stage not in ALL_STAGES:
            raise HTTPException(400, f"알 수 없는 단계: {stage}")
        if ch_no not in _load_state().chapters:
            raise HTTPException(404, f"ch{ch_no} 없음")
        background_tasks.add_task(_run_stage_task, ch_no, stage)
        return {"status": "queued", "chapter": ch_no, "stage": stage}

    @app.post("/api/sync")
    def api_sync():
        state = _load_state()
        runner = PipelineRunner(PROJ_DEFAULT, state)
        for ch_no in state.chapters:
            for stage in ALL_STAGES:
                result = runner.verify(ch_no, stage)
                st = state.get_chapter(ch_no).get_stage(stage)
                st.status = result.status
                st.details = result.details
                if result.status == COMPLETED and not st.completed_at:
                    st.completed_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        state.save(STATE)
        return {"status": "synced", "chapters": len(state.chapters)}

    @app.get("/api/projects")
    def api_projects():
        """PROJ_ROOT 안의 모든 하위 프로젝트 디렉토리 스캔."""
        from .project_wizard import slugify
        proj_root = PROJ_DEFAULT.parent  # 26년2학기/
        projects = []
        for d in sorted(proj_root.iterdir()):
            if d.is_dir() and (d / "project.json").exists():
                try:
                    state = ProjectState.load(d / "project.json")
                    projects.append({
                        "path": str(d),
                        "name": state.name,
                        "project_id": state.project_id,
                        "chapters": len(state.chapters),
                        "voice_id": state.elevenlabs.get("voice_id", ""),
                    })
                except Exception:
                    pass
        return projects

    @app.post("/api/projects/{name}/clone-voice")
    def api_clone_voice(name: str, background_tasks: BackgroundTasks):
        """지정한 프로젝트 디렉토리에서 음성 클론 (백그라운드)."""
        proj_root = PROJ_DEFAULT.parent
        target = proj_root / name
        if not (target / "project.json").exists():
            raise HTTPException(404, f"project.json 없음: {target}")
        state = ProjectState.load(target / "project.json")
        ref_dir = target / "02_음성" / "voice_ref"
        refs = sorted(ref_dir.glob("*.wav")) if ref_dir.exists() else []
        if not refs:
            raise HTTPException(400, f"voice_ref에 .wav 파일 없음: {ref_dir}")
        log_key = (name, "voice-clone")
        _run_log.setdefault(log_key, [])
        def task():
            try:
                from .voice_clone import clone_voice
                _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] 시작")
                voice_id = clone_voice(target, refs, name=state.elevenlabs.get("voice_name", "main"))
                _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] 완료: voice_id={voice_id}")
            except Exception as e:
                _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] 오류: {e}")
        background_tasks.add_task(task)
        return {"status": "queued", "project": name, "refs": [r.name for r in refs]}

    @app.post("/api/projects/{name}/generate-scripts/{chapter}")
    def api_generate_script(name: str, chapter: str, background_tasks: BackgroundTasks):
        proj_root = PROJ_DEFAULT.parent
        target = proj_root / name
        if not (target / "project.json").exists():
            raise HTTPException(404, f"project 없음: {target}")
        log_key = (name, f"script-gen-{chapter}")
        _run_log.setdefault(log_key, [])
        def task():
            try:
                from .script_generator import generate_chapter_script
                _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] 시작: ch{chapter}")
                n = generate_chapter_script(target, chapter)
                _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] 완료: {n}장")
            except Exception as e:
                _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] 오류: {e}")
        background_tasks.add_task(task)
        return {"status": "queued", "project": name, "chapter": chapter}

    @app.post("/api/projects/{name}/run/{chapter}")
    def api_run_chapter(name: str, chapter: str, background_tasks: BackgroundTasks):
        proj_root = PROJ_DEFAULT.parent
        target = proj_root / name
        if not (target / "project.json").exists():
            raise HTTPException(404, f"project 없음: {target}")
        log_key = (name, f"run-{chapter}")
        _run_log.setdefault(log_key, [])
        def task():
            try:
                from .orchestrator import run_chapter
                _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] 시작: ch{chapter}")
                results = run_chapter(target, chapter)
                _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] 완료: {[(s, r.status) for s, r in results.items()]}")
            except Exception as e:
                _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] 오류: {e}")
        background_tasks.add_task(task)
        return {"status": "queued", "project": name, "chapter": chapter}

    @app.get("/projects")
    def projects_page():
        """프로젝트 목록 + 만들기 페이지."""
        from .project_wizard import slugify
        proj_root = PROJ_DEFAULT.parent
        projects = []
        for d in sorted(proj_root.iterdir()):
            if d.is_dir() and (d / "project.json").exists():
                try:
                    state = ProjectState.load(d / "project.json")
                    projects.append({
                        "path": str(d),
                        "name": state.name,
                        "project_id": state.project_id,
                        "chapters": len(state.chapters),
                        "voice_id": state.elevenlabs.get("voice_id", "")[:16] + "...",
                    })
                except Exception:
                    pass
        items = "".join(
            f'<div class="proj"><h3>{p["name"]}</h3>'
            f'<p class="meta">경로: <code>{p["path"]}</code></p>'
            f'<p>챕터: {p["chapters"]}개 · 음성: <code>{p["voice_id"]}</code></p>'
            f'<a href="/project/{p["project_id"]}">열기 →</a></div>'
            for p in projects
        )
        if not items:
            items = '<p class="meta">아직 프로젝트가 없습니다. <code>python -m pipeline new-project</code> 로 만드세요.</p>'
        body = f"""
<h1>프로젝트 목록</h1>
<p class="meta">루트: <code>{proj_root}</code></p>
<form method="post" action="/api/projects/create" style="margin: 16px 0; padding: 12px; background: #f0f7ff; border-radius: 4px;">
<strong>새 프로젝트 만들기:</strong>
<input name="name" placeholder="강의명 (예: AI 시대 교육)" style="margin-left: 8px; padding: 4px 8px; width: 240px;">
<button type="submit" style="margin-left: 8px;">만들기</button>
</form>
{items}
"""
        return HTMLResponse(_page("프로젝트", body))

    @app.post("/api/projects/create")
    async def api_create_project(request):
        form = await request.form()
        name = form.get("name", "").strip()
        if not name:
            raise HTTPException(400, "name 필요")
        from .project_wizard import new_project as wizard, slugify
        proj_root = PROJ_DEFAULT.parent
        # 충돌 시 _2, _3
        base = slugify(name)
        target = proj_root / base
        n = 2
        while target.exists():
            target = proj_root / f"{base}_{n}"; n += 1
        wizard(name=name, base_dir=proj_root)
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/projects", status_code=303)

    @app.get("/project/{project_id}")
    def project_detail(project_id: str):
        proj_root = PROJ_DEFAULT.parent
        target = None
        for d in proj_root.iterdir():
            if d.is_dir() and (d / "project.json").exists():
                try:
                    st = ProjectState.load(d / "project.json")
                    if st.project_id == project_id:
                        target = d; break
                except Exception: pass
        if not target:
            raise HTTPException(404, f"project {project_id} 없음")
        state = ProjectState.load(target / "project.json")
        voice = state.defaults.get("voice", "scott")
        rows = ""
        for ch_no in sorted(state.chapters.keys()):
            ch = state.chapters[ch_no]
            cells = "".join(
                f'<td>{_run_log.get((project_id, f"run-{ch_no}"), ["대기"])[-1] if (project_id, f"run-{ch_no}") in _run_log else "대기"}</td>'
                if False else f'<td>대기</td>'
                for _ in [1]
            )
            for s in ALL_STAGES:
                st = ch.get_stage(s)
                color = {"completed": "#28a745", "pending": "#999", "in_progress": "#e0a800",
                          "failed": "#dc3545", "partial": "#fd7e14"}.get(st.status, "#666")
                cells += f'<td><span class="badge" style="background:{color}">{st.status}</span></td>'
            rows += f'<tr><td><b>ch{ch_no}</b></td><td>{ch.get("title","")}</td>{cells}'
            rows += f'<td><form method="post" action="/api/projects/{project_id}/run/{ch_no}" style="display:inline"><button>실행</button></form></td></tr>'
        body = f"""
<h1>{state.name}</h1>
<p class="meta">경로: <code>{target}</code> · 음성: <code>{state.elevenlabs.get('voice_id','?')}</code></p>
<div style="margin: 12px 0; padding: 10px; background: #fff8c5; border-radius: 4px;">
  <form method="post" action="/api/projects/{project_id}/clone-voice" style="display:inline">
    <button type="submit">음성 클론 ({voice} 만들기)</button>
  </form>
  &nbsp;
  <form method="post" action="/api/projects/{project_id}/generate-scripts/all" style="display:inline">
    <button type="submit">전체 AI 스크립트 생성</button>
  </form>
</div>
<table>
<thead><tr><th>챕터</th><th>제목</th>
{"".join(f"<th>{STAGE_LABELS[s]}</th>" for s in ALL_STAGES)}
<th>액션</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<p><a href="/projects">← 프로젝트 목록</a></p>
"""
        return HTMLResponse(_page(f"{state.name}", body))

    @app.post("/api/projects/{name}/generate-scripts/all")
    def api_generate_all(name: str, background_tasks: BackgroundTasks):
        proj_root = PROJ_DEFAULT.parent
        target = proj_root / name
        if not (target / "project.json").exists():
            raise HTTPException(404, f"project 없음: {target}")
        log_key = (name, "script-gen-all")
        _run_log.setdefault(log_key, [])
        def task():
            try:
                import json
                state = json.loads((target / "project.json").read_text(encoding="utf-8"))
                from .script_generator import generate_chapter_script
                for ch_no in sorted(state["chapters"].keys()):
                    _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] ch{ch_no} 시작")
                    n = generate_chapter_script(target, ch_no)
                    _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] ch{ch_no} 완료 ({n}장)")
            except Exception as e:
                _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] 오류: {e}")
        background_tasks.add_task(task)
        return {"status": "queued", "project": name}


        state = _load_state()
        runner = PipelineRunner(PROJ_DEFAULT, state)
        for ch_no in state.chapters:
            for stage in ALL_STAGES:
                result = runner.verify(ch_no, stage)
                st = state.get_chapter(ch_no).get_stage(stage)
                st.status = result.status
                st.details = result.details
                if result.status == COMPLETED and not st.completed_at:
                    st.completed_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        state.save(STATE)
        return {"status": "synced", "chapters": len(state.chapters)}

    import uvicorn
    print(f"🚀 파이프라인 서비스 시작: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")

def create_app() -> "FastAPI":
    app = FastAPI(title="강의 영상 파이프라인")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return _index(_load_state())

    @app.get("/chapter/{ch_no}", response_class=HTMLResponse)
    def chapter(ch_no: str):
        return _chapter_detail(_load_state(), ch_no)

    @app.get("/api/status")
    def api_status():
        return _load_state().to_dict()

    @app.post("/api/run/{ch_no}/{stage}")
    def api_run(ch_no: str, stage: str, background_tasks: BackgroundTasks):
        if stage not in ALL_STAGES:
            raise HTTPException(400, f"알 수 없는 단계: {stage}")
        if ch_no not in _load_state().chapters:
            raise HTTPException(404, f"ch{ch_no} 없음")
        background_tasks.add_task(_run_stage_task, ch_no, stage)
        return {"status": "queued", "chapter": ch_no, "stage": stage}

    @app.post("/api/sync")
    def api_sync():
        state = _load_state()
        runner = PipelineRunner(PROJ_DEFAULT, state)
        for ch_no in state.chapters:
            for stage in ALL_STAGES:
                result = runner.verify(ch_no, stage)
                st = state.get_chapter(ch_no).get_stage(stage)
                st.status = result.status
                st.details = result.details
                if result.status == COMPLETED and not st.completed_at:
                    st.completed_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        state.save(STATE)
        return {"status": "synced", "chapters": len(state.chapters)}

    @app.get("/api/projects")
    def api_projects():
        """PROJ_ROOT 안의 모든 하위 프로젝트 디렉토리 스캔."""
        from .project_wizard import slugify
        proj_root = PROJ_DEFAULT.parent  # 26년2학기/
        projects = []
        for d in sorted(proj_root.iterdir()):
            if d.is_dir() and (d / "project.json").exists():
                try:
                    state = ProjectState.load(d / "project.json")
                    projects.append({
                        "path": str(d),
                        "name": state.name,
                        "project_id": state.project_id,
                        "chapters": len(state.chapters),
                        "voice_id": state.elevenlabs.get("voice_id", ""),
                    })
                except Exception:
                    pass
        return projects

    @app.post("/api/projects/{name}/clone-voice")
    def api_clone_voice(name: str, background_tasks: BackgroundTasks):
        """지정한 프로젝트 디렉토리에서 음성 클론 (백그라운드)."""
        proj_root = PROJ_DEFAULT.parent
        target = proj_root / name
        if not (target / "project.json").exists():
            raise HTTPException(404, f"project.json 없음: {target}")
        state = ProjectState.load(target / "project.json")
        ref_dir = target / "02_음성" / "voice_ref"
        refs = sorted(ref_dir.glob("*.wav")) if ref_dir.exists() else []
        if not refs:
            raise HTTPException(400, f"voice_ref에 .wav 파일 없음: {ref_dir}")
        log_key = (name, "voice-clone")
        _run_log.setdefault(log_key, [])
        def task():
            try:
                from .voice_clone import clone_voice
                _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] 시작")
                voice_id = clone_voice(target, refs, name=state.elevenlabs.get("voice_name", "main"))
                _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] 완료: voice_id={voice_id}")
            except Exception as e:
                _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] 오류: {e}")
        background_tasks.add_task(task)
        return {"status": "queued", "project": name, "refs": [r.name for r in refs]}

    @app.post("/api/projects/{name}/generate-scripts/{chapter}")
    def api_generate_script(name: str, chapter: str, background_tasks: BackgroundTasks):
        proj_root = PROJ_DEFAULT.parent
        target = proj_root / name
        if not (target / "project.json").exists():
            raise HTTPException(404, f"project 없음: {target}")
        log_key = (name, f"script-gen-{chapter}")
        _run_log.setdefault(log_key, [])
        def task():
            try:
                from .script_generator import generate_chapter_script
                _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] 시작: ch{chapter}")
                n = generate_chapter_script(target, chapter)
                _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] 완료: {n}장")
            except Exception as e:
                _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] 오류: {e}")
        background_tasks.add_task(task)
        return {"status": "queued", "project": name, "chapter": chapter}

    @app.post("/api/projects/{name}/run/{chapter}")
    def api_run_chapter(name: str, chapter: str, background_tasks: BackgroundTasks):
        proj_root = PROJ_DEFAULT.parent
        target = proj_root / name
        if not (target / "project.json").exists():
            raise HTTPException(404, f"project 없음: {target}")
        log_key = (name, f"run-{chapter}")
        _run_log.setdefault(log_key, [])
        def task():
            try:
                from .orchestrator import run_chapter
                _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] 시작: ch{chapter}")
                results = run_chapter(target, chapter)
                _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] 완료: {[(s, r.status) for s, r in results.items()]}")
            except Exception as e:
                _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] 오류: {e}")
        background_tasks.add_task(task)
        return {"status": "queued", "project": name, "chapter": chapter}

    @app.get("/projects")
    def projects_page():
        """프로젝트 목록 + 만들기 페이지."""
        from .project_wizard import slugify
        proj_root = PROJ_DEFAULT.parent
        projects = []
        for d in sorted(proj_root.iterdir()):
            if d.is_dir() and (d / "project.json").exists():
                try:
                    state = ProjectState.load(d / "project.json")
                    projects.append({
                        "path": str(d),
                        "name": state.name,
                        "project_id": state.project_id,
                        "chapters": len(state.chapters),
                        "voice_id": state.elevenlabs.get("voice_id", "")[:16] + "...",
                    })
                except Exception:
                    pass
        items = "".join(
            f'<div class="proj"><h3>{p["name"]}</h3>'
            f'<p class="meta">경로: <code>{p["path"]}</code></p>'
            f'<p>챕터: {p["chapters"]}개 · 음성: <code>{p["voice_id"]}</code></p>'
            f'<a href="/project/{p["project_id"]}">열기 →</a></div>'
            for p in projects
        )
        if not items:
            items = '<p class="meta">아직 프로젝트가 없습니다. <code>python -m pipeline new-project</code> 로 만드세요.</p>'
        body = f"""
<h1>프로젝트 목록</h1>
<p class="meta">루트: <code>{proj_root}</code></p>
<form method="post" action="/api/projects/create" style="margin: 16px 0; padding: 12px; background: #f0f7ff; border-radius: 4px;">
<strong>새 프로젝트 만들기:</strong>
<input name="name" placeholder="강의명 (예: AI 시대 교육)" style="margin-left: 8px; padding: 4px 8px; width: 240px;">
<button type="submit" style="margin-left: 8px;">만들기</button>
</form>
{items}
"""
        return HTMLResponse(_page("프로젝트", body))

    @app.post("/api/projects/create")
    async def api_create_project(request):
        form = await request.form()
        name = form.get("name", "").strip()
        if not name:
            raise HTTPException(400, "name 필요")
        from .project_wizard import new_project as wizard, slugify
        proj_root = PROJ_DEFAULT.parent
        # 충돌 시 _2, _3
        base = slugify(name)
        target = proj_root / base
        n = 2
        while target.exists():
            target = proj_root / f"{base}_{n}"; n += 1
        wizard(name=name, base_dir=proj_root)
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/projects", status_code=303)

    @app.get("/project/{project_id}")
    def project_detail(project_id: str):
        proj_root = PROJ_DEFAULT.parent
        target = None
        for d in proj_root.iterdir():
            if d.is_dir() and (d / "project.json").exists():
                try:
                    st = ProjectState.load(d / "project.json")
                    if st.project_id == project_id:
                        target = d; break
                except Exception: pass
        if not target:
            raise HTTPException(404, f"project {project_id} 없음")
        state = ProjectState.load(target / "project.json")
        voice = state.defaults.get("voice", "scott")
        rows = ""
        for ch_no in sorted(state.chapters.keys()):
            ch = state.chapters[ch_no]
            cells = "".join(
                f'<td>{_run_log.get((project_id, f"run-{ch_no}"), ["대기"])[-1] if (project_id, f"run-{ch_no}") in _run_log else "대기"}</td>'
                if False else f'<td>대기</td>'
                for _ in [1]
            )
            for s in ALL_STAGES:
                st = ch.get_stage(s)
                color = {"completed": "#28a745", "pending": "#999", "in_progress": "#e0a800",
                          "failed": "#dc3545", "partial": "#fd7e14"}.get(st.status, "#666")
                cells += f'<td><span class="badge" style="background:{color}">{st.status}</span></td>'
            rows += f'<tr><td><b>ch{ch_no}</b></td><td>{ch.get("title","")}</td>{cells}'
            rows += f'<td><form method="post" action="/api/projects/{project_id}/run/{ch_no}" style="display:inline"><button>실행</button></form></td></tr>'
        body = f"""
<h1>{state.name}</h1>
<p class="meta">경로: <code>{target}</code> · 음성: <code>{state.elevenlabs.get('voice_id','?')}</code></p>
<div style="margin: 12px 0; padding: 10px; background: #fff8c5; border-radius: 4px;">
  <form method="post" action="/api/projects/{project_id}/clone-voice" style="display:inline">
    <button type="submit">음성 클론 ({voice} 만들기)</button>
  </form>
  &nbsp;
  <form method="post" action="/api/projects/{project_id}/generate-scripts/all" style="display:inline">
    <button type="submit">전체 AI 스크립트 생성</button>
  </form>
</div>
<table>
<thead><tr><th>챕터</th><th>제목</th>
{"".join(f"<th>{STAGE_LABELS[s]}</th>" for s in ALL_STAGES)}
<th>액션</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<p><a href="/projects">← 프로젝트 목록</a></p>
"""
        return HTMLResponse(_page(f"{state.name}", body))

    @app.post("/api/projects/{name}/generate-scripts/all")
    def api_generate_all(name: str, background_tasks: BackgroundTasks):
        proj_root = PROJ_DEFAULT.parent
        target = proj_root / name
        if not (target / "project.json").exists():
            raise HTTPException(404, f"project 없음: {target}")
        log_key = (name, "script-gen-all")
        _run_log.setdefault(log_key, [])
        def task():
            try:
                import json
                state = json.loads((target / "project.json").read_text(encoding="utf-8"))
                from .script_generator import generate_chapter_script
                for ch_no in sorted(state["chapters"].keys()):
                    _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] ch{ch_no} 시작")
                    n = generate_chapter_script(target, ch_no)
                    _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] ch{ch_no} 완료 ({n}장)")
            except Exception as e:
                _run_log[log_key].append(f"[{time.strftime('%H:%M:%S')}] 오류: {e}")
        background_tasks.add_task(task)
        return {"status": "queued", "project": name}


        state = _load_state()
        runner = PipelineRunner(PROJ_DEFAULT, state)
        for ch_no in state.chapters:
            for stage in ALL_STAGES:
                result = runner.verify(ch_no, stage)
                st = state.get_chapter(ch_no).get_stage(stage)
                st.status = result.status
                st.details = result.details
                if result.status == COMPLETED and not st.completed_at:
                    st.completed_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        state.save(STATE)
        return {"status": "synced", "chapters": len(state.chapters)}

    return app


app = create_app()


def run_server(host: str = "127.0.0.1", port: int = 8765):
    import uvicorn
    config = uvicorn.Config(app, host=host, port=port, log_level="info", access_log=False, loop="asyncio")
    server = uvicorn.Server(config)
    print(f"🚀 파이프라인 서비스 시작: http://{host}:{port}")
    server.run()
