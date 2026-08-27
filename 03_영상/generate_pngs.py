#!/usr/bin/env python3
"""
Phase 1: PPTX → PDF (LibreOffice) → PNG (pdftoppm) 일괄 변환.

ch01_pngs는 이미 존재(2000x1125). 02~17은 이 스크립트로 생성.
해상도 2000x1125 = 150 DPI (16:9 슬라이드 13.333인치 기준).

사용법:
    # 전체 챕터 (ch02~17)
    python generate_pngs.py

    # 특정 챕터
    python generate_pngs.py --chapter 04

    # 모든 챕터 (ch01 포함, 덮어쓰기)
    python generate_pngs.py --all
"""
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path("/Users/scott/Library/CloudStorage/GoogleDrive-scott@naddle.net/내 드라이브/개인/개인 자료/[2024] 대구교대 강의/26년2학기")
PROJ = BASE / "강의영상_제작"
MANIFEST = PROJ / "00_매니페스트" / "manifest.json"
PNG_DIR_TEMPLATE = str(PROJ / "03_영상" / "ch{NN}_pngs")

SOFFICE = "/opt/homebrew/bin/soffice"
DPI = 150  # 2000x1125 @ 16:9


def pptx_to_pngs(pptx_path: Path, out_dir: Path) -> int:
    """단일 PPTX → PNG 변환. 반환: 생성된 PNG 수."""
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # 1) PPTX → PDF
        result = subprocess.run(
            [SOFFICE, "--headless", "--convert-to", "pdf",
             "--outdir", str(tmp), str(pptx_path)],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            print(f"  ✗ soffice 실패:\n{result.stderr[-300:]}")
            return 0
        pdf_path = tmp / (pptx_path.stem + ".pdf")
        if not pdf_path.exists():
            print(f"  ✗ PDF 생성 안 됨: {pdf_path}")
            return 0

        # 2) PDF → PNG (150dpi)
        prefix = tmp / "slide"
        subprocess.run(
            ["pdftoppm", "-r", str(DPI), "-png", str(pdf_path), str(prefix)],
            capture_output=True, check=True,
        )
        pngs = sorted(tmp.glob("slide-*.png"))
        if not pngs:
            print(f"  ✗ PNG 생성 안 됨")
            return 0

        # 3) out_dir로 이동 (slide-01.png 형식, 0-pad)
        for i, p in enumerate(pngs, 1):
            target = out_dir / f"slide-{i:02d}.png"
            shutil.move(str(p), str(target))
        return len(pngs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chapter", help="특정 챕터만 (예: 04). 미지정 시 ch02~17 일괄")
    parser.add_argument("--all", action="store_true", help="ch01 포함 17개 전부")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    if args.chapter:
        targets = [c for c in manifest["chapters"] if c["chapter_no"] == args.chapter]
        if not targets:
            print(f"⚠ ch{args.chapter} 매니페스트에 없음")
            sys.exit(1)
    else:
        if args.all:
            targets = manifest["chapters"]
        else:
            # 기본: ch01은 이미 있으므로 ch02~17만
            targets = [c for c in manifest["chapters"] if c["chapter_no"] != "01"]

    print(f"=== PNG 생성 대상: {len(targets)}개 챕터 ===\n")
    total = 0
    for c in targets:
        ch_no = c["chapter_no"]
        pptx = Path(c["slide_path"])
        if not pptx.exists():
            print(f"  ✗ ch{ch_no}: PPTX 없음 ({pptx})")
            continue
        out_dir = Path(PNG_DIR_TEMPLATE.format(NN=ch_no))
        print(f"[ch{ch_no}] {pptx.name} → {out_dir.name}/")
        n = pptx_to_pngs(pptx, out_dir)
        total += n
        if n > 0:
            # 첫 PNG 크기 확인 (해상도 검증)
            first = out_dir / "slide-01.png"
            size = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
                 "-of", "default=nw=1:nk=1", str(first)],
                capture_output=True, text=True,
            ).stdout.strip()
            print(f"  ✓ {n}장 생성, 첫 슬라이드 {size}")
        print()

    print(f"=== 완료: 총 {total}장 PNG 생성 ===")


if __name__ == "__main__":
    main()
