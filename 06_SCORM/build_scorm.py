#!/usr/bin/env python3
"""
Phase 6: SCORM 1.2 패키지 빌더.

사용법:
    # 기본 (ch01, voice=scott, suffix 없음)
    python build_scorm.py --chapter 01

    # suffix 있는 변형 (테스트/실험)
    python build_scorm.py --chapter 01 --suffix _test

    # 전체 챕터 일괄 (모두 빌드)
    for c in 01 02 03 ... 17; do python build_scorm.py --chapter $c; done

생성물:
- 06_SCORM/ 디렉토리
  ├── imsmanifest.xml  (동적 생성)
  ├── index.html       (타이틀 동적 교체)
  ├── scorm12.js
  ├── ch{NN}_full.mp4  (SCORM 표준 이름)
  └── ch{NN}.srt
- 06_SCORM/{zip_name}.zip  (LMS 업로드용)
"""
from __future__ import annotations
import argparse
import json
import re
import shutil
import zipfile
from pathlib import Path

BASE = Path("/Users/scott/Library/CloudStorage/GoogleDrive-scott@naddle.net/내 드라이브/개인/개인 자료/[2024] 대구교대 강의/26년2학기")
PROJ = BASE / "강의영상_제작"

SCORM_DIR = PROJ / "06_SCORM"
MP4_DIR = PROJ / "05_MP4"
SRT_DIR = PROJ / "04_자막"
MANIFEST = PROJ / "00_매니페스트" / "manifest.json"

BOOK_TITLE = "AI 시대 교육"


def pptx_to_chapter_title(pptx_path: str) -> str:
    """PPTX 파일명에서 챕터 표시 제목 생성.
    예: '1장_2026년의교실_세개의국면.pptx' → '1장 · 2026년의교실 세개의국면'
    """
    stem = Path(pptx_path).stem
    parts = stem.split("_", 1)
    chapter = parts[0]
    rest = parts[1].replace("_", " ") if len(parts) > 1 else ""
    return f"{chapter} · {rest}" if rest else chapter


def chapter_info(chapter_no: str) -> dict:
    """매니페스트에서 챕터 정보 조회."""
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for c in m["chapters"]:
        if c["chapter_no"] == chapter_no:
            return c
    raise KeyError(f"매니페스트에 ch{chapter_no} 없음")


def generate_manifest_xml(chapter_no: str, item_title: str, section: str) -> str:
    """imsmanifest.xml 동적 생성."""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="AI_SIDAE_CH{chapter_no}" version="1.2"
  xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
  xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.imsproject.org/xsd/imscp_rootv1p1p2 imscp_rootv1p1p2.xsd
                      http://www.imsglobal.org/xsd/imsmd_rootv1p2p1 imsmd_rootv1p2p1.xsd
                      http://www.adlnet.org/xsd/adlcp_rootv1p2 adlcp_rootv1p2.xsd">

  <metadata>
    <schema>ADL SCORM</schema>
    <schemaversion>1.2</schemaversion>
  </metadata>

  <organizations default="ORG-AI_SIDAE">
    <organization identifier="ORG-AI_SIDAE">
      <title>{BOOK_TITLE} — {section}</title>
      <item identifier="ITEM-CH{chapter_no}" identifierref="RES-CH{chapter_no}">
        <title>{item_title}</title>
        <adlcp:masteryscore>95</adlcp:masteryscore>
      </item>
    </organization>
  </organizations>

  <resources>
    <resource identifier="RES-CH{chapter_no}" type="webcontent"
      adlcp:scormtype="sco" href="index.html">
      <file href="index.html"/>
      <file href="scorm12.js"/>
      <file href="ch{chapter_no}_full.mp4"/>
      <file href="ch{chapter_no}.srt"/>
    </resource>
  </resources>
</manifest>
'''


def update_index_title(index_path: Path, item_title: str) -> None:
    """기존 index.html의 <title> 태그만 교체."""
    html = index_path.read_text(encoding="utf-8")
    new_html = re.sub(
        r"<title>.*?</title>",
        f"<title>{item_title}</title>",
        html,
        count=1,
    )
    index_path.write_text(new_html, encoding="utf-8")


def build(chapter_no: str, voice: str, suffix: str, zip_name: str):
    SCORM_DIR.mkdir(parents=True, exist_ok=True)

    # 소스 파일 확인
    mp4_name = f"ch{chapter_no}_full_{voice}{suffix}.mp4"
    srt_name = f"ch{chapter_no}{suffix}.srt"
    mp4_src = MP4_DIR / mp4_name
    srt_src = SRT_DIR / srt_name

    if not mp4_src.exists():
        raise FileNotFoundError(f"MP4 없음: {mp4_src}")
    if not srt_src.exists():
        raise FileNotFoundError(f"SRT 없음: {srt_src}")

    # 매니페스트 정보
    info = chapter_info(chapter_no)
    item_title = pptx_to_chapter_title(info["slide_path"])
    section = info["section"]
    print(f"✓ 챕터 제목: {item_title}")
    print(f"✓ 섹션: {section}")

    # 1) MP4 / SRT 복사
    target_mp4 = SCORM_DIR / f"ch{chapter_no}_full.mp4"
    target_srt = SCORM_DIR / f"ch{chapter_no}.srt"
    shutil.copy2(mp4_src, target_mp4)
    shutil.copy2(srt_src, target_srt)
    print(f"✓ {mp4_src.name} → {target_mp4.name} ({target_mp4.stat().st_size // 1024}KB)")
    print(f"✓ {srt_src.name} → {target_srt.name} ({target_srt.stat().st_size} bytes)")

    # 2) imsmanifest.xml 동적 생성
    target_manifest = SCORM_DIR / "imsmanifest.xml"
    target_manifest.write_text(generate_manifest_xml(chapter_no, item_title, section), encoding="utf-8")
    print(f"✓ imsmanifest.xml (동적 생성)")

    # 3) index.html 타이틀 교체
    target_index = SCORM_DIR / "index.html"
    # 소스가 없으면 기존 파일 사용, 있으면 복사 후 타이틀 교체
    src_index = SCORM_DIR / "index.html"
    if not src_index.exists():
        # 첫 빌드라면 템플릿이 필요 — 기존 06_SCORM/index.html을 템플릿으로 사용
        # 이미 위 복사 단계에서 만들어졌을 것. 없으면 에러.
        raise FileNotFoundError("index.html 템플릿 없음")
    update_index_title(target_index, item_title)
    print(f"✓ index.html (title: {item_title})")

    # 4) ZIP 패키징
    files = [
        "imsmanifest.xml",
        "index.html",
        "scorm12.js",
        f"ch{chapter_no}_full.mp4",
        f"ch{chapter_no}.srt",
    ]
    out_zip = SCORM_DIR / f"{zip_name}.zip"
    if out_zip.exists():
        out_zip.unlink()

    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in files:
            src = SCORM_DIR / f
            zf.write(src, arcname=f)
            print(f"  + {f}")

    print(f"\n✓ SCORM 패키지: {out_zip}")
    print(f"  크기: {out_zip.stat().st_size // 1024}KB")
    print(f"\nLMS 업로드:")
    print(f"  1. {out_zip.name} 파일을 LMS에 업로드")
    print(f"  2. SCORM 1.2 호환 LMS에서 자동 인식 (Moodle, Canvas, K-에듀파인 등)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chapter", default="01", help="챕터 번호 (예: 01)")
    parser.add_argument("--voice", default="scott", help="음성 라벨 (파일명에 사용)")
    parser.add_argument("--suffix", default="", help="음성/자막 파일 suffix (예: _test, _static)")
    parser.add_argument("--zip-name", default="", help="출력 zip 이름 (기본: scorm_ch{NN}{suffix})")
    args = parser.parse_args()

    if not args.zip_name:
        args.zip_name = f"scorm_ch{args.chapter}{args.suffix}"

    build(args.chapter, args.voice, args.suffix, args.zip_name)


if __name__ == "__main__":
    main()