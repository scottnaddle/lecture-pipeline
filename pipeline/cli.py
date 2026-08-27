"""CLI 진입점.

사용법:
  python -m pipeline status                  # 전체 프로젝트 상태
  python -m pipeline status ch01             # 특정 챕터
  python -m pipeline verify ch03            # 실제 파일로 검증만 (실행 X)
  python -m pipeline run ch03 tts           # 특정 단계 실행
  python -m pipeline run ch03               # 챕터 전체 실행
  python -m pipeline add ch18 ...           # 새 챕터 추가
  python -m pipeline remove ch15            # 챕터 제거 (산출물은 보존)
  python -m pipeline init                   # 현재 manifest에서 project.json 초기화
  python -m pipeline sync                   # 실제 파일 기준으로 state 재동기화
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from .state import (
    ProjectState, StageState,
    PENDING, IN_PROGRESS, COMPLETED, FAILED, PARTIAL,
    ALL_STAGES, STAGE_LABELS, STAGE_DEPS,
)
from .manifest import Manifest, ChapterInfo
from .stages import PipelineRunner, StageResult

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


def _load_or_init_state() -> ProjectState:
    if STATE.exists():
        return ProjectState.load(STATE)
    print(f"project.json 없음 → {STATE} 에서 생성")
    manifest = Manifest(MANIFEST)
    state = ProjectState(
        project_id="dnue_2026_2",
        name="AI 시대 교육",
        elevenlabs={"voice_id": "sIqpog1pVqIIn2ivuloD", "model": "eleven_multilingual_v2"},
    )
    for c in manifest.chapters:
        state.add_chapter(
            no=c.chapter_no,
            title=Path(c.slide_path).stem.split("_", 1)[-1] if c.slide_path else "",
            section=c.section,
            duration_min=c.duration_min,
        )
    state.save(STATE)
    return state


def _color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def _status_icon(status: str) -> str:
    return {
        PENDING: _color("○", "90"),
        IN_PROGRESS: _color("◐", "33"),
        COMPLETED: _color("●", "32"),
        FAILED: _color("✗", "31"),
        PARTIAL: _color("◐", "33"),
    }.get(status, "?")


def _status_label(status: str) -> str:
    return {
        PENDING: _color("대기", "90"),
        IN_PROGRESS: _color("진행", "33"),
        COMPLETED: _color("완료", "32"),
        FAILED: _color("실패", "31"),
        PARTIAL: _color("부분", "33"),
    }.get(status, status)


def cmd_status(args):
    state = _load_or_init_state()
    runner = PipelineRunner(PROJ_DEFAULT, state)

    if args.chapter:
        chapters = [args.chapter]
    else:
        chapters = sorted(state.chapters.keys())

    if args.verify:
        # 실제 파일로 재동기화
        for ch_no in chapters:
            for stage in ALL_STAGES:
                result = runner.verify(ch_no, stage)
                st = state.get_chapter(ch_no).get_stage(stage)
                st.status = result.status
                st.details = result.details
                if result.status == COMPLETED:
                    st.completed_at = st.completed_at or __import__("time").strftime("%Y-%m-%dT%H:%M:%S")
                else:
                    st.completed_at = None
        state.save(STATE)
        print(f"✓ {len(chapters)}개 챕터 동기화 완료\n")

    print(f"{'='*72}")
    print(f"  프로젝트: {state.name}  ({state.project_id})")
    print(f"  챕터 수: {len(state.chapters)}")
    print(f"  음성: voice_id={state.elevenlabs.get('voice_id', '?')[:12]}...  model={state.elevenlabs.get('model', '?')}")
    print(f"  기본: voice={state.defaults.get('voice')}  speed={state.defaults.get('speed')}  backend={state.defaults.get('backend')}")
    print(f"{'='*72}\n")

    for ch_no in chapters:
        ch = state.get_chapter(ch_no)
        title_part = f" — {ch.title}" if ch.title else ""
        sec_part = f"  ({ch.section})" if ch.section else ""
        print(f"ch{ch_no}{title_part}{sec_part}")
        for stage in ALL_STAGES:
            st = ch.get_stage(stage)
            label = STAGE_LABELS[stage]
            icon = _status_icon(st.status)
            stat = _status_label(st.status)
            detail = ""
            if st.status == PARTIAL and st.details:
                c, t = st.details.get("completed"), st.details.get("total")
                if c is not None and t is not None:
                    detail = f" ({c}/{t})"
            print(f"  {icon} {label:<14} {stat}{detail}")
        print()


def cmd_run(args):
    state = _load_or_init_state()
    runner = PipelineRunner(PROJ_DEFAULT, state)

    if not args.chapter:
        print("오류: 챕터 번호 필요 (--chapter)")
        sys.exit(1)
    ch_no = args.chapter

    if ch_no not in state.chapters:
        print(f"오류: ch{ch_no}이(가) project.json에 없음. `add` 먼저 실행")
        sys.exit(1)

    if args.stage:
        result = runner.run(ch_no, args.stage, force=args.force)
        icon = _status_icon(result.status)
        print(f"  {icon} {STAGE_LABELS[args.stage]}: {_status_label(result.status)} — {result.message[:200]}")
    else:
        # 챕터 전체 실행
        print(f"ch{ch_no} 전체 실행:")
        results = runner.run_chapter(ch_no, force=args.force)
        for stage, r in results.items():
            icon = _status_icon(r.status)
            print(f"  {icon} {STAGE_LABELS[stage]}: {_status_label(r.status)} — {r.message[:200]}")

    state.save(STATE)


def cmd_add(args):
    state = _load_or_init_state()
    manifest = Manifest(MANIFEST)

    info = ChapterInfo(
        chapter_no=args.chapter,
        slide_path=args.pptx or "",
        manuscript_path=args.manuscript or "",
        section=args.section or "",
        duration_min=args.duration or "40-50",
    )

    # manifest에도 추가
    manifest.add(
        args.chapter,
        slide_path=info.slide_path,
        manuscript_path=info.manuscript_path,
        section=info.section,
        duration_min=info.duration_min,
    )
    manifest.save()

    # state에도 추가
    state.add_chapter(
        no=info.chapter_no,
        title=Path(info.slide_path).stem.split("_", 1)[-1] if info.slide_path else args.title or "",
        section=info.section,
        duration_min=info.duration_min,
    )
    state.save(STATE)

    print(f"✓ ch{args.chapter} 추가 (manifest + state)")


def cmd_remove(args):
    state = _load_or_init_state()
    manifest = Manifest(MANIFEST)
    if not args.force:
        ans = input(f"정말 ch{args.chapter}을(를) 제거할까요? 산출물 파일은 그대로 남습니다 [y/N]: ")
        if ans.lower() != "y":
            print("취소")
            return
    manifest.remove(args.chapter)
    manifest.save()
    state.remove_chapter(args.chapter)
    state.save(STATE)
    print(f"✓ ch{args.chapter} 제거 (manifest + state)")


def cmd_sync(args):
    cmd_status(argparse.Namespace(chapter=None, verify=True))


def cmd_init(args):
    if STATE.exists() and not args.force:
        ans = input(f"{STATE} 이미 존재. 덮어쓸까요? [y/N]: ")
        if ans.lower() != "y":
            print("취소")
            return
    # state = _load_or_init_state()가 init도 처리하므로 단순히 호출
    state = _load_or_init_state()
    print(f"✓ {STATE} 초기화/갱신 완료")


def cmd_serve(args):
    """FastAPI 웹 서버 실행."""
    from .server import run_server
    run_server(host=args.host, port=args.port)



def cmd_new_project(args):
    from .project_wizard import new_project as wizard
    proj_dir = wizard(
        name=args.name,
        base_dir=Path(args.base_dir).resolve(),
        pptx_dir=Path(args.pptx_dir).resolve() if args.pptx_dir else None,
        manuscript=Path(args.manuscript).resolve() if args.manuscript else None,
        voice_id=args.voice_id,
        voice_name=args.voice_name,
        speed=args.speed,
        default_provider=args.provider,
    )
    print(f"\n다음 단계:")
    print(f"  1. .env 편집: open '{proj_dir}/.env'")
    print(f"  2. 음성 클론: cd '{proj_dir}' && python -m pipeline clone-voice --project-dir . --ref-audio <wav>")
    print(f"  3. 스크립트 생성: python -m pipeline generate-scripts --project-dir . --all")
    print(f"  4. 전체 실행: python -m pipeline run --project-dir . --all")


def cmd_orchestrate(args):
    from .orchestrator import run_chapter, run_all
    pd = Path(args.project_dir).resolve()
    if not (pd / "project.json").exists():
        print(f"project.json 없음: {pd}"); sys.exit(1)
    from .state import ProjectState
    state = ProjectState.load(pd / "project.json")
    voice = args.voice or state.defaults.get("voice", "scott")
    speed = args.speed or state.defaults.get("speed", 1.1)
    if args.chapter:
        stages = args.stages.split(",") if args.stages else None
        if args.from_stage and stages is None:
            from .stages import STAGE_DEPS  # noqa
            all_stages = ["pngs", "tts", "render", "srt", "scorm"]
            stages = all_stages[all_stages.index(args.from_stage):]
        run_chapter(pd, args.chapter, stages=stages, voice=voice, speed=speed)
    elif args.all:
        run_all(pd, voice=voice, speed=speed)
    else:
        print("--chapter NN 또는 --all 필요"); sys.exit(1)


def cmd_clone_voice(args):
    from .voice_clone import clone_voice
    refs = [Path(r).expanduser().resolve() for r in args.ref_audio]
    clone_voice(Path(args.project_dir).resolve(), refs, name=args.name, model=args.model)


def cmd_generate_scripts(args):
    from .script_generator import generate_chapter_script
    pd = Path(args.project_dir).resolve()
    if not (pd / "project.json").exists():
        print(f"project.json 없음: {pd}"); sys.exit(1)
    import json
    state = json.loads((pd / "project.json").read_text(encoding="utf-8"))
    if args.chapter:
        generate_chapter_script(pd, args.chapter, provider_name=args.provider, temperature=args.temperature)
    elif args.all:
        for ch_no in sorted(state["chapters"].keys()):
            generate_chapter_script(pd, ch_no, provider_name=args.provider, temperature=args.temperature)
    else:
        print("--chapter NN 또는 --all 필요"); sys.exit(1)


def cmd_dashboard(args):
    """정적 HTML 대시보드 생성 (uvicorn 없이 즉시 사용)."""
    import json, datetime
    from pathlib import Path
    pd = Path(args.project_dir).resolve() if args.project_dir else Path.cwd()
    proj_json = pd / "project.json"
    if not proj_json.exists():
        print(f"project.json 없음: {proj_json}"); sys.exit(1)
    state = json.loads(proj_json.read_text(encoding="utf-8"))
    def s_check(ch, st):
        defaults = state["defaults"]
        voice, speed = defaults["voice"], defaults["speed"]
        speed_str = f"x{speed:.1f}".replace(".", "_")
        paths = {
            "script": pd / "01_스크립트" / "scripts" / f"ch{ch}.txt",
            "pngs": pd / "03_영상" / f"ch{ch}_pngs",
            "voice_clone": pd / "02_음성" / "voice_ref",
            "tts": pd / "02_음성" / ch,
            "render": pd / "05_MP4" / f"ch{ch}_full_{voice}.mp4",
            "srt": pd / "04_자막" / f"ch{ch}.srt",
            "scorm": pd / "06_SCORM" / f"scorm_ch{ch}.zip",
        }
        p = paths[st]
        return "완료" if p.exists() and (p.is_file() or p.is_dir()) else "대기"
    rows = ""
    for ch in sorted(state["chapters"].keys()):
        c = state["chapters"][ch]
        cells = "".join(f"<td>{s_check(ch, st)}</td>" for st in ALL_STAGES)
        rows += f'<tr><td><b>ch{ch}</b></td><td>{c.get("title","")}<br><span style="color:#666;font-size:0.85em">{c.get("section","")}</span></td>{cells}</tr>'
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html = f"""<!doctype html><html lang=ko><head><meta charset=utf-8><title>{state['name']} 대시보드</title>
<style>body{{font-family:-apple-system,sans-serif;max-width:1200px;margin:24px auto;padding:0 16px}}
h1{{font-size:1.5em;border-bottom:2px solid #333;padding-bottom:8px}}
table{{width:100%;border-collapse:collapse;margin-top:16px;font-size:0.9em}}
th,td{{padding:8px 10px;border-bottom:1px solid #eee}}
th{{background:#f4f4f4}}td{{text-align:center}}td:first-child{{text-align:left;font-weight:600}}
.meta{{color:#666;font-size:0.85em}}code{{background:#e0e0e0;padding:2px 5px;border-radius:2px}}
</style></head><body>
<h1>{state['name']}</h1>
<div class=meta>프로젝트: {state['project_id']} · 챕터 {len(state['chapters'])}개 · 음성: <code>{state['elevenlabs'].get('voice_id','?')}</code></div>
<table><thead><tr><th>챕터</th><th>제목·섹션</th>{"".join(f"<th>{STAGE_LABELS[s]}</th>" for s in ALL_STAGES)}</tr></thead>
<tbody>{rows}</tbody></table>
<p class=meta>생성: {now} · <code>python -m pipeline dashboard --project-dir {pd}</code></p>
</body></html>"""
    out = pd / "pipeline" / "dashboard.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"✓ {out}")


def cmd_ai_status(args):
    from .ai_providers import detect_providers
    p = detect_providers()
    if not p:
        print("설정된 AI 프로바이더 없음. .env에 키 추가 필요")
        return
    print("사용 가능한 AI 프로바이더:")
    for name, prov in p.items():
        print(f"  {name:12s}  {prov.model:30s}  {prov.base_url}")




def main():
    p = argparse.ArgumentParser(prog="pipeline", description="강의 영상 제작 파이프라인 서비스")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="프로젝트/챕터 상태 표시")
    p_status.add_argument("chapter", nargs="?", help="특정 챕터 (예: 01)")
    p_status.add_argument("--verify", action="store_true", help="실제 파일로 검증 후 동기화")
    p_status.set_defaults(func=cmd_status)

    p_run = sub.add_parser("run", help="단계 실행")
    p_run.add_argument("chapter", help="챕터 번호 (예: 01)")
    p_run.add_argument("stage", nargs="?", help="단계 (script/pngs/tts/render/srt/scorm). 생략 시 전체")
    p_run.add_argument("--force", action="store_true", help="완료된 단계도 다시 실행")
    p_run.set_defaults(func=cmd_run)

    p_add = sub.add_parser("add", help="챕터 추가")
    p_add.add_argument("chapter", help="챕터 번호 (예: 18)")
    p_add.add_argument("--pptx", help="PPTX 파일 경로")
    p_add.add_argument("--manuscript", help="원고 파일 경로")
    p_add.add_argument("--section", help="섹션명 (예: 5부 · 결론)")
    p_add.add_argument("--duration", help="차시 길이 (예: 40-50)")
    p_add.add_argument("--title", help="챕터 제목 (state용)")
    p_add.set_defaults(func=cmd_add)

    p_remove = sub.add_parser("remove", help="챕터 제거 (state/manifest에서만)")
    p_remove.add_argument("chapter", help="챕터 번호")
    p_remove.add_argument("--force", action="store_true", help="확인 생략")
    p_remove.set_defaults(func=cmd_remove)

    p_sync = sub.add_parser("sync", help="실제 파일 기준으로 state 재동기화")
    p_sync.set_defaults(func=cmd_sync)

    p_init = sub.add_parser("init", help="project.json 초기화 (manifest 기반)")
    p_init.add_argument("--force", action="store_true", help="덮어쓰기 확인 생략")
    p_init.set_defaults(func=cmd_init)

    p_serve = sub.add_parser("serve", help="웹 UI 서버 시작")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", default=8765, type=int)
    p_serve.set_defaults(func=cmd_serve)

    p_new = sub.add_parser("new-project", help="새 프로젝트 만들기 (wizard)")
    p_new.add_argument("--name", help="강의명")
    p_new.add_argument("--base-dir", default=".", help="프로젝트 루트")
    p_new.add_argument("--pptx-dir", help="PPTX 디렉토리")
    p_new.add_argument("--manuscript", help="원고 파일")
    p_new.add_argument("--voice-id", help="ElevenLabs voice_id")
    p_new.add_argument("--voice-name", default="main")
    p_new.add_argument("--speed", type=float, default=1.1)
    p_new.add_argument("--provider", default="openai")
    p_new.set_defaults(func=cmd_new_project)

    p_clone = sub.add_parser("clone-voice", help="ElevenLabs 음성 클론")
    p_clone.add_argument("--project-dir", required=True)
    p_clone.add_argument("--ref-audio", action="append", required=True)
    p_clone.add_argument("--name", default="main")
    p_clone.add_argument("--model", default="eleven_multilingual_v2")
    p_clone.set_defaults(func=cmd_clone_voice)

    p_genscript = sub.add_parser("generate-scripts", help="AI 스크립트 생성")
    p_genscript.add_argument("--project-dir", required=True)
    p_genscript.add_argument("--chapter")
    p_genscript.add_argument("--all", action="store_true")
    p_genscript.add_argument("--provider")
    p_genscript.add_argument("--temperature", type=float, default=0.7)
    p_genscript.set_defaults(func=cmd_generate_scripts)

    p_dash = sub.add_parser("dashboard", help="정적 HTML 대시보드 생성")
    p_dash.add_argument("--project-dir", help="프로젝트 디렉토리 (생략 시 . 현재 디렉토리)")
    p_dash.set_defaults(func=cmd_dashboard)

    p_ai = sub.add_parser("ai", help="AI 프로바이더 상태")
    p_ai.set_defaults(func=cmd_ai_status)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
