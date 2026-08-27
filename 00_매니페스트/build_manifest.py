#!/usr/bin/env python3
"""
Phase 0: 슬라이드(.pptx) + 원고(.md) 매니페스트 빌더.
- 슬라이드 17챕터 ↔ 원고 17챕터 1:1 매칭
- 디자인 토큰(컬러, 폰트, 슬라이드 비율) 추출
- 결과: manifest.json + chapter_index.json
"""
from __future__ import annotations
import json
import os
import re
import unicodedata
import zipfile
from pathlib import Path

# --- 경로 ---
BASE = Path("/Users/scott/Library/CloudStorage/GoogleDrive-scott@naddle.net/내 드라이브/개인/개인 자료/[2024] 대구교대 강의/26년2학기")
SLIDES_DIR = BASE / "슬라이드" / "최종"
MANUSCRIPT_DIR = BASE / "교재_일반판"
OUT_DIR = BASE / "강의영상_제작" / "00_매니페스트"

# --- 챕터 메타 (강의 시간, 대상 등 강제 고정값) ---
CHAPTER_META = {
    "01": {"duration_min": "40-50", "section": "1부 · 2026년의 교실"},
    "02": {"duration_min": "40-50", "section": "1부 · 2026년의 교실"},
    "03": {"duration_min": "40-50", "section": "1부 · 2026년의 교실"},
    "04": {"duration_min": "40-50", "section": "1부 · 2026년의 교실"},
    "05": {"duration_min": "40-50", "section": "1부 · 2026년의 교실"},
    "06": {"duration_min": "40-50", "section": "2부 · AI와 함께 쓰는 수업"},
    "07": {"duration_min": "40-50", "section": "2부 · AI와 함께 쓰는 수업"},
    "08": {"duration_min": "40-50", "section": "2부 · AI와 함께 쓰는 수업"},
    "09": {"duration_min": "40-50", "section": "2부 · AI와 함께 쓰는 수업"},
    "10": {"duration_min": "40-50", "section": "2부 · AI와 함께 쓰는 수업"},
    "11": {"duration_min": "40-50", "section": "2부 · AI와 함께 쓰는 수업"},
    "12": {"duration_min": "40-50", "section": "3부 · 다시 그리는 수업"},
    "13": {"duration_min": "40-50", "section": "3부 · 다시 그리는 수업"},
    "14": {"duration_min": "40-50", "section": "3부 · 다시 그리는 수업"},
    "15": {"duration_min": "40-50", "section": "4부 · 거시 시선"},
    "16": {"duration_min": "40-50", "section": "4부 · 거시 시선"},
    "17": {"duration_min": "40-50", "section": "5부 · 2030년으로"},
}

# --- 디자인 토큰 (슬라이드 XML에서 직접 확인) ---
# 1장 슬라이드 1에서 확인된 색상:
#   - 배경: #0E1520 (다크)
#   - 강조: #B8954A (골드)
#   - 보조 텍스트: #A39E94 (베이지-그레이)
#   - 메인 텍스트: #F7F3EB (크림)
#   - 카드 배경: #161E2C (딥 네이비)
DESIGN_TOKENS = {
    "palette": {
        "bg_dark":        "#0E1520",
        "bg_card":        "#161E2C",
        "accent_gold":    "#B8954A",
        "text_main":      "#F7F3EB",
        "text_muted":     "#A39E94",
        "border_subtle":  "#D9D1C3",
    },
    "fonts": {
        "heading":  "Noto Serif CJK KR",
        "body":     "Noto Sans CJK KR",
    },
    "slide_aspect": "16:9",
    "slide_size_emu": {"cx": 12192000, "cy": 6858000},
    "tone_guide": {
        "voice": "대화형·친근한",
        "address": "선생님",  # 청자를 부를 때
        "register": "구어체, 단문 위주, 한 호흡당 15–20어절",
        "pacing": "슬라이드당 60–80초, 핵심 문장 후 0.5–1.0초 pause",
    },
}


def extract_chapter_no_from_slide(path: Path) -> str | None:
    """'1장_...' 또는 '10장_...' 패턴에서 챕터 번호 추출. NFC 정규화 후 매칭."""
    stem = unicodedata.normalize("NFC", path.stem)
    m = re.match(r"^(\d{1,2})장_", stem)
    return m.group(1).zfill(2) if m else None


def extract_chapter_no_from_md(path: Path) -> str | None:
    """'g01_...' 또는 'g17_...' 패턴에서 챕터 번호 추출. NFC 정규화 후 매칭."""
    stem = unicodedata.normalize("NFC", path.stem)
    m = re.match(r"^g(\d{1,2})_", stem)
    return m.group(1).zfill(2) if m else None


def build():
    # 1) 슬라이드 매핑 — macOS NFD 정규화 회피: listdir + 정규식 사용
    slide_files = [
        SLIDES_DIR / f
        for f in sorted(os.listdir(SLIDES_DIR))
        if f.endswith(".pptx") and not f.startswith("~$")
    ]

    # 2) 원고 매핑
    md_files = [
        MANUSCRIPT_DIR / f
        for f in sorted(os.listdir(MANUSCRIPT_DIR))
        if re.match(r"^g\d{2}_.*\.md$", unicodedata.normalize("NFC", f))
    ]

    slide_map = {}
    for sf in slide_files:
        no = extract_chapter_no_from_slide(sf)
        if no:
            slide_map[no] = sf

    md_map = {}
    for mf in md_files:
        no = extract_chapter_no_from_md(mf)
        if no:
            md_map[no] = mf

    # 3) 매니페스트 조립
    chapters = []
    for no in sorted(set(slide_map) | set(md_map)):
        entry = {
            "chapter_no": no,
            "slide_path": str(slide_map[no]) if no in slide_map else None,
            "manuscript_path": str(md_map[no]) if no in md_map else None,
            "matched": no in slide_map and no in md_map,
            **CHAPTER_META.get(no, {"duration_min": "?", "section": "?"}),
        }
        if not entry["matched"]:
            entry["warning"] = "missing"
        chapters.append(entry)

    missing = [c for c in chapters if not c["matched"]]
    if missing:
        print(f"⚠ 매칭 실패 챕터: {[c['chapter_no'] for c in missing]}")

    manifest = {
        "version": "1.0",
        "created_at": "2026-08-24",
        "base_dir": str(BASE),
        "design_tokens": DESIGN_TOKENS,
        "chapters": chapters,
        "summary": {
            "total_slide_chapters": len([c for c in chapters if c["slide_path"]]),
            "total_manuscript_chapters": len([c for c in chapters if c["manuscript_path"]]),
            "matched_chapters": len([c for c in chapters if c["matched"]]),
            "missing": [c["chapter_no"] for c in missing],
        },
        "output_spec": {
            "video":  {"codec": "h264", "resolution": "1920x1080", "fps": 30, "bitrate": "5Mbps"},
            "audio":  {"codec": "aac", "sample_rate": 48000, "bitrate": "192kbps"},
            "subtitle": {"format": "srt", "encoding": "utf-8"},
            "scorm":  {"version": "1.2"},
        },
    }

    out_manifest = OUT_DIR / "manifest.json"
    out_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ {out_manifest}")
    print(f"  슬라이드 챕터: {manifest['summary']['total_slide_chapters']}")
    print(f"  원고 챕터:    {manifest['summary']['total_manuscript_chapters']}")
    print(f"  매칭 성공:    {manifest['summary']['matched_chapters']}")
    if missing:
        print(f"  ⚠ 매칭 실패: {manifest['summary']['missing']}")


if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    build()