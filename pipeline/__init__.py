"""강의 영상 제작 파이프라인 서비스.

기존 스크립트(batch_tts.py, render_slides_ffmpeg.py 등)를 감싸는 얇은 레이어.
역할:
- 프로젝트 상태 추적 (project.json)
- 실패 시 재개 (resume)
- 차시 수 가변 (manifest 기반)
- CLI + 웹 UI 진입점
"""
__version__ = "0.1.0"
