#!/usr/bin/env python3
"""
Phase 2 자동화: 슬라이드 본문 + 원고 → 슬라이드별 나레이션 스크립트 자동 생성.

- 입력: slide_texts.json (Phase 1 산출물) + manuscript_texts.json
- LLM: OpenAI gpt-4-turbo
- 프롬프트: 1장 스크립트(32슬라이드)를 few-shot 예시로 제공 → 톤 일관성 확보
- 출력: scripts/ch{NN}.txt
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

BASE = Path("/Users/scott/Library/CloudStorage/GoogleDrive-scott@naddle.net/내 드라이브/개인/개인 자료/[2024] 대구교대 강의/26년2학기")
SCRIPT_DIR = BASE / "강의영상_제작" / "01_스크립트"
SLIDES_JSON = SCRIPT_DIR / "slide_texts.json"
MANUS_JSON = SCRIPT_DIR / "manuscript_texts.json"
OUT_DIR = SCRIPT_DIR / "scripts"
ENV_FILE = BASE / "강의영상_제작" / ".env"

# === 1장 스크립트 few-shot 예시 (자동 생성에서 제외) ===
# 이미 01_스크립트/scripts/ch01.txt에 있으므로, 다른 챕터 생성 시 참고용으로만 사용

SYSTEM_PROMPT = """당신은 한국 초·중등교사 대상 연수 강의를 위한 '나레이션 스크립트' 작가입니다.

[톤 가이드]
- 호칭: '선생님' 일관
- 어조: 대화형·친근한 구어체
- 한 호흡: 15~20어절
- 슬라이드당 분량: 60~80초 (한국어 220~320자)
- 슬라이드 본문 핵심 문장은 반드시 포함
- 슬라이드 마지막에 다음 슬라이드로 자연스럽게 연결되는 멘트 1문장
- 한자/외래어는 한국어로 풀어서 (예: '에이전트' → '에이전트', 'high-impact AI' → '고영향 AI')
- 강조할 단어만 「 」로 감싸기 (선택 사항, 안 써도 OK)

[출력 형식]
- 한 줄 = 한 슬라이드
- 형식: '<slide_no>\\t<text>'
- 빈 줄, 마크다운, 번호 매기기, 따옴표 래핑 없이 순수 텍스트만

[절대 하지 말 것]
- 마크다운 (**, ##, 번호 등) 출력에 넣지 않기
- 챕터 번호/제목 등 메타 정보 출력에 넣지 않기
- 한 슬라이드에 여러 줄 출력하지 않기
- 슬라이드 번호 순서 건너뛰지 않기
"""

# Few-shot: 1장 슬라이드 3~4개를 예시로 보여줌
FEW_SHOT_HEADER = """아래는 1장의 실제 스크립트 예시입니다. 같은 톤·분량·형식으로 작성하세요.

[예시 — 1장 슬라이드 1]
본문: 2026년의 교실 — 세 개의 국면 / 기술·제도·경험이 한 해에 동시에 만난다 / 한 줄 요약: 2026년은 기술(에이전트), 제도(AI 기본법), 경험(첫 성적표)의 세 국면이 동시에 움직이는 해다.

스크립트:
1\\t여러분, 안녕하세요. 1장 「2026년의 교실 — 세 개의 국면」 시작합니다. 올해는 좀 특별합니다. 기술이 한 번에 움직이고, 제도도 한 번에 움직이고, 학생들의 경험도 한 번에 움직이는 해거든요. 그래서 이 책은 딱 세 가지 국면으로 이야기를 엮어 봤습니다. 기술은 에이전트, 제도는 AI 기본법, 경험은 첫 성적표까지 — 이 세 가지가 동시에 만나는 해가 2026년입니다. 그게 오늘 우리가 함께 들여다볼 질문이에요.

[예시 — 1장 슬라이드 4]
본문: 5년 전과 비교하다 / 학생의 손 — 교과서 대신 태블릿, 숙제를 할 때 챗GPT를 켭니다 / 교사의 손 — 학급 알림장을 AI로 쓴 뒤에 카카오톡으로 보냅니다 / 가속도의 세 이유 / 질문의 이동

스크립트:
4\\t먼저 5년 전으로 가볼게요. 2021년과 지금을 나란히 놓는 겁니다. 학생의 손이 달라졌습니다. 교과서 대신 태블릿을 들고, 숙제할 때 챗GPT를 켭니다. 교사의 손도 달라졌어요. 학급 알림장을 AI로 먼저 쓰고, 그다음 카카오톡으로 발송합니다. 그런데 이 변화는 우연이 아닙니다. 가속도의 이유가 세 가지 있어요. 도구가 좋아지면서 저렴해졌고, 일과의 한가운데로 들어왔고 — 알림장이나 학습지처럼 매주 반복되는 일부터 대신하기 시작했죠. 셋째, 학생들이 먼저 쓰기 시작했습니다. 선생님이 「써도 되나」를 고민하실 때쯤, 학생들은 이미 숙제에 챗GPT를 켜두었다는 뜻이에요. 그래서 질문이 이동했습니다. 「쓸 것인가」에서 「어떻게 쓸 것인가」로요. 그런데 「어떻게」는 무게가 다릅니다. 결정을 한 번 하면 끝나는 게 아니라, 매주 반복되는 수업·평가·학부모 소통의 설계를 통째로 다시 그리는 문제이기 때문입니다.

[예시 — 1장 슬라이드 13]
본문: 비교 / 챗봇과 에이전트, 무엇이 다른가 / 표의 핵심 — 에이전트로 갈수록 '누가 무엇을 확인하는가'가 설계의 중심이 된다

스크립트:
13\\t챗봇과 에이전트의 차이를 표로 보실게요. 핵심은 이겁니다. 에이전트로 갈수록 「누가 무엇을 확인하는가」가 설계의 중심이 된다는 거예요. 도구가 아무리 똑똑해져도, 확인과 판단의 책임은 그대로 선생님께 남아 있습니다.

[예시 — 1장 슬라이드 32]
본문: 참고자료 / Walcutt, J.J. & Schatz, S. (2019) Modernizing Learning / UNESCO (2023) Guidance for generative AI in education and research

스크립트:
32\\t마지막으로 참고자료 두 가지입니다. 첫째, 2019년 미국 ADL의 「Modernizing Learning」입니다. 5년 전 청사진의 원문이에요. 둘째, 2023년 UNESCO의 「Guidance for generative AI in education and research」입니다. 두 권 모두 무료로 공개돼 있습니다. 슬라이드 안의 링크에서 바로 받아 보실 수 있어요. 1장 여기까지입니다. 고생하셨습니다.

---

이제 아래 챕터의 슬라이드별로 스크립트를 작성하세요.
"""


def build_user_prompt(chapter_no: str, slides: list[dict], manuscript_excerpt: str) -> str:
    """챕터 정보 + 슬라이드 본문 + 원고 발췌를 user 메시지로."""
    parts = [FEW_SHOT_HEADER, f"\n[이제 작성할 챕터: {chapter_no}장]", "\n[원고 발췌 (참고용)]", manuscript_excerpt[:3000], "\n[슬라이드 본문]"]
    for s in slides:
        text = s["content_text"].strip()
        text = re.sub(r"^\d+장.*\n", "", text, flags=re.MULTILINE)  # 헤더 제거
        parts.append(f"\n[슬라이드 {s['slide_no']}]\n{text}")
    parts.append("\n\n위 슬라이드 순서대로 스크립트를 작성하세요. 형식: '<slide_no>\\t<text>'")
    return "\n".join(parts)


def parse_llm_output(raw: str, expected_slide_count: int, start_slide_no: int = 1) -> list[dict]:
    """LLM 출력을 파싱해서 [{slide_no, text}, ...] 리스트로.

    - 구분자: \t, \\t (백슬래시-t 2글자), |, : 모두 시도
    - 슬라이드 번호가 1부터 시작하면 start_slide_no부터 재매김
    """
    out = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        # 마크다운 코드블록/리스트마커 제거
        line = re.sub(r"^```[a-z]*$|^```$", "", line).strip()
        line = re.sub(r"^[\-\*\d]\.\s+", "", line)

        # 구분자 시도 순서: \t, \\t (백슬래시+t), |, :
        sep = None
        for candidate in ["\t", "\\t", "|", ": "]:
            if candidate in line:
                sep = candidate
                break
        if sep is None:
            continue

        try:
            no_str, text = line.split(sep, 1)
            no_str_clean = re.sub(r"[^0-9]", "", no_str)
            if not no_str_clean:
                continue
            raw_no = int(no_str_clean)
            text = text.strip().strip('"').strip("'").strip()
            text = text.replace('\\"', '"').replace("\\'", "'")
            if text and len(text) > 30:  # 너무 짧은 매칭은 무시
                out.append({"raw_no": raw_no, "text": text})
        except (ValueError, IndexError):
            continue

    # 슬라이드 번호 재매김: chunk 시작 번호부터
    remapped = []
    for i, d in enumerate(out):
        remapped.append({"slide_no": start_slide_no + i, "text": d["text"]})
    return remapped


def generate_chapter(client: OpenAI, chapter_no: str, slides: list[dict], manuscript: str) -> list[dict]:
    """챕터 1개의 스크립트 생성."""
    user_prompt = build_user_prompt(chapter_no, slides, manuscript)

    print(f"  → 챕터 {chapter_no}: {len(slides)}슬라이드, 원고 {len(manuscript)}자")
    print(f"    LLM 호출 중...", end=" ", flush=True)
    t0 = time.time()

    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        max_tokens=16384,
    )

    dt = time.time() - t0
    raw = resp.choices[0].message.content
    tokens = resp.usage.total_tokens if resp.usage else 0
    print(f"완료 ({dt:.1f}s, {tokens} tokens)")

    parsed = parse_llm_output(raw, len(slides), start_slide_no=slides[0]["slide_no"])
    if len(parsed) < len(slides):
        missing = [s["slide_no"] for s in slides if s["slide_no"] not in (p["slide_no"] for p in parsed)]
        print(f"    ⚠ 누락된 슬라이드: {missing}")
    return parsed


def save_chapter(chapter_no: str, scripts: list[dict]) -> Path:
    """ch{NN}.txt 형식으로 저장."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"ch{chapter_no}.txt"
    lines = [f"# 챕터 {chapter_no} 자동 생성 스크립트"]
    for s in scripts:
        lines.append(f"{s['slide_no']}\t{s['text']}")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def generate_chapter_chunked(client: OpenAI, chapter_no: str, slides: list[dict], manuscript: str, chunk_size: int = 12) -> list[dict]:
    """긴 챕터는 슬라이드를 chunk로 나눠서 여러 번 호출."""
    if len(slides) <= chunk_size:
        return generate_chapter(client, chapter_no, slides, manuscript)

    all_scripts = []
    chunks = [slides[i:i + chunk_size] for i in range(0, len(slides), chunk_size)]
    for idx, chunk in enumerate(chunks, 1):
        print(f"    [chunk {idx}/{len(chunks)}: 슬라이드 {chunk[0]['slide_no']}~{chunk[-1]['slide_no']}]")
        scripts = generate_chapter(client, chapter_no, chunk, manuscript)
        # chunk 내에서 슬라이드 번호 재매김
        for i, s in enumerate(scripts):
            s["slide_no"] = chunk[i]["slide_no"]
        all_scripts.extend(scripts)
        time.sleep(0.3)
    return all_scripts


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--chapter", help="챕터 번호 (예: 02)")
    p.add_argument("--from-chapter", default="02", help="시작 챕터")
    p.add_argument("--to-chapter", default="17", help="끝 챕터")
    p.add_argument("--chunk-size", type=int, default=12)
    args = p.parse_args()

    if not ENV_FILE.exists():
        print(f"⚠ {ENV_FILE} 없음")
        sys.exit(1)
    load_dotenv(ENV_FILE)
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or api_key.startswith("sk-proj-여기에"):
        print("⚠ OPENAI_API_KEY 미설정")
        sys.exit(1)
    client = OpenAI(api_key=api_key)

    slides_all = json.loads(SLIDES_JSON.read_text(encoding="utf-8"))
    manus_all = json.loads(MANUS_JSON.read_text(encoding="utf-8"))

    if args.chapter:
        targets = [args.chapter]
    else:
        targets = [f"{i:02d}" for i in range(int(args.from_chapter), int(args.to_chapter) + 1)]

    total = 0
    total_chars = 0
    for ch_no in targets:
        slides = slides_all[ch_no]["slides"]
        manuscript_text = manus_all[ch_no]["full_text"]
        try:
            scripts = generate_chapter_chunked(client, ch_no, slides, manuscript_text, chunk_size=args.chunk_size)
            path = save_chapter(ch_no, scripts)
            total += len(scripts)
            total_chars += sum(len(s["text"]) for s in scripts)
            print(f"    ✓ {path} ({len(scripts)}/{len(slides)}개 슬라이드)")
        except Exception as e:
            print(f"    ✗ 실패: {e}")
            continue

    print(f"\n총 {total}개 슬라이드 생성, {total_chars}자")


if __name__ == "__main__":
    main()