"""00_매니페스트/manifest.json 로드 + 차시 추가/삭제 헬퍼.

manifest.json 구조:
{
  "chapters": [
    {"chapter_no": "01", "slide_path": "...", "manuscript_path": "...", "section": "...", "duration_min": "..."},
    ...
  ]
}
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ChapterInfo:
    chapter_no: str
    slide_path: str = ""
    manuscript_path: str = ""
    section: str = ""
    duration_min: str = ""

    def to_dict(self) -> dict:
        out = {"chapter_no": self.chapter_no}
        for k in ("slide_path", "manuscript_path", "section", "duration_min"):
            v = getattr(self, k)
            if v:
                out[k] = v
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "ChapterInfo":
        return cls(
            chapter_no=d["chapter_no"],
            slide_path=d.get("slide_path", ""),
            manuscript_path=d.get("manuscript_path", ""),
            section=d.get("section", ""),
            duration_min=d.get("duration_min", ""),
        )


class Manifest:
    def __init__(self, path: Path):
        self.path = path
        self.chapters: list[ChapterInfo] = []
        if path.exists():
            self.load()

    def load(self):
        d = json.loads(self.path.read_text(encoding="utf-8"))
        self.chapters = [ChapterInfo.from_dict(c) for c in d.get("chapters", [])]

    def save(self):
        d = {
            "chapters": [c.to_dict() for c in self.chapters],
        }
        self.path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, chapter_no: str, slide_path: str = "", manuscript_path: str = "",
            section: str = "", duration_min: str = "40-50") -> ChapterInfo:
        # 중복 방지
        for c in self.chapters:
            if c.chapter_no == chapter_no:
                return c
        c = ChapterInfo(
            chapter_no=chapter_no,
            slide_path=slide_path,
            manuscript_path=manuscript_path,
            section=section,
            duration_min=duration_min,
        )
        self.chapters.append(c)
        self.chapters.sort(key=lambda c: c.chapter_no)
        return c

    def remove(self, chapter_no: str) -> bool:
        before = len(self.chapters)
        self.chapters = [c for c in self.chapters if c.chapter_no != chapter_no]
        return len(self.chapters) < before

    def get(self, chapter_no: str) -> Optional[ChapterInfo]:
        for c in self.chapters:
            if c.chapter_no == chapter_no:
                return c
        return None

    def list_nos(self) -> list[str]:
        return [c.chapter_no for c in self.chapters]
