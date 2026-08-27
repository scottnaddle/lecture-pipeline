"""프로젝트 상태 모델.

project.json 구조:
{
  "version": 1,
  "project_id": "...",
  "name": "...",
  "chapters": {
    "01": {
      "title": "...",
      "section": "...",
      "duration_min": "40-50",
      "stages": {
        "script":  {"status": "completed" | "pending" | "in_progress" | "failed", "completed_at": "...", "details": {...}},
        "pngs":    {...},
        "tts":     {"status": "partial", "completed_slides": [1,2,3,...], "voice_id": "..."},
        "render":  {...},
        "srt":     {...},
        "scorm":   {...}
      }
    }
  },
  "elevenlabs": {"voice_id": "...", "model": "..."},
  "defaults": {"voice": "scott", "speed": 1.1, "backend": "elevenlabs"}
}
"""
from __future__ import annotations
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

PENDING = "pending"
IN_PROGRESS = "in_progress"
COMPLETED = "completed"
FAILED = "failed"
PARTIAL = "partial"

ALL_STAGES = ("script", "pngs", "voice_clone", "tts", "render", "srt", "scorm")

STAGE_LABELS = {
    "script": "슬라이드 스크립트",
    "pngs": "슬라이드 이미지",
    "voice_clone": "음성 클론",
    "tts": "음성 합성",
    "render": "영상 렌더링",
    "srt": "자막",
    "scorm": "SCORM 패키지",
}

# 단계 간 의존성 (앞 단계가 완료되어야 다음 단계 실행 가능)
STAGE_DEPS = {
    "script": [],
    "pngs": [],
    "voice_clone": [],
    "tts": ["script", "voice_clone"],
    "render": ["pngs", "tts"],
    "srt": ["tts"],
    "scorm": ["render", "srt"],
}


@dataclass
class StageState:
    status: str = PENDING
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None and v != {}}

    @classmethod
    def from_dict(cls, d: dict) -> "StageState":
        return cls(
            status=d.get("status", PENDING),
            started_at=d.get("started_at"),
            completed_at=d.get("completed_at"),
            details=d.get("details", {}),
        )


@dataclass
class ChapterState:
    title: str = ""
    section: str = ""
    duration_min: str = ""
    stages: dict[str, StageState] = field(default_factory=dict)

    def get_stage(self, stage: str) -> StageState:
        if stage not in self.stages:
            self.stages[stage] = StageState()
        return self.stages[stage]

    def to_dict(self) -> dict:
        out = {}
        for k in ("title", "section", "duration_min"):
            v = getattr(self, k)
            if v:
                out[k] = v
        out["stages"] = {s: self.get_stage(s).to_dict() for s in ALL_STAGES}
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "ChapterState":
        c = cls(
            title=d.get("title", ""),
            section=d.get("section", ""),
            duration_min=d.get("duration_min", ""),
        )
        for s, sd in d.get("stages", {}).items():
            c.stages[s] = StageState.from_dict(sd)
        return c

    def is_stage_done(self, stage: str) -> bool:
        s = self.get_stage(stage)
        return s.status in (COMPLETED,)

    def stage_progress_pct(self, stage: str) -> Optional[int]:
        s = self.get_stage(stage)
        d = s.details or {}
        if "total" in d and "completed" in d:
            return int(100 * d["completed"] / d["total"])
        return None


@dataclass
class ProjectState:
    project_id: str
    name: str
    version: int = 1
    chapters: dict[str, ChapterState] = field(default_factory=dict)
    elevenlabs: dict = field(default_factory=lambda: {"model": "eleven_multilingual_v2"})
    defaults: dict = field(default_factory=lambda: {"voice": "scott", "speed": 1.1, "backend": "elevenlabs"})

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "project_id": self.project_id,
            "name": self.name,
            "elevenlabs": self.elevenlabs,
            "defaults": self.defaults,
            "chapters": {k: v.to_dict() for k, v in self.chapters.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectState":
        p = cls(
            project_id=d.get("project_id", "default"),
            name=d.get("name", "Untitled"),
            version=d.get("version", 1),
            elevenlabs=d.get("elevenlabs", {}),
            defaults=d.get("defaults", {}),
        )
        for k, cd in d.get("chapters", {}).items():
            p.chapters[k] = ChapterState.from_dict(cd)
        return p

    def get_chapter(self, no: str) -> ChapterState:
        if no not in self.chapters:
            self.chapters[no] = ChapterState()
        return self.chapters[no]

    def add_chapter(self, no: str, title: str = "", section: str = "", duration_min: str = ""):
        self.chapters[no] = ChapterState(title=title, section=section, duration_min=duration_min)

    def remove_chapter(self, no: str):
        self.chapters.pop(no, None)

    def save(self, path: Path):
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "ProjectState":
        if not path.exists():
            raise FileNotFoundError(f"project.json 없음: {path}")
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
