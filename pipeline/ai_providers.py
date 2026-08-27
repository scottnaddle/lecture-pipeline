"""AI 프로바이더 추상화.

지원 프로바이더 (모두 OpenAI 호환 /chat/completions):
- openai    (gpt-4o 등)        — OPENAI_API_KEY
- anthropic (claude 등)         — ANTHROPIC_API_KEY
- zhipu     (z.ai GLM-4.6)      — ZAI_API_KEY
- moonshot  (Kimi k2)          — MOONSHOT_API_KEY
- MiniMax   (MiniMax-Text-01)   — MINIMAX_API_KEY
"""
from __future__ import annotations
import json, os, urllib.request, urllib.error
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AIProvider:
    name: str
    base_url: str
    api_key: Optional[str] = None
    model: str = ""
    extra_headers: dict = field(default_factory=dict)

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def chat(self, system: str, user: str, *, temperature: float = 0.7,
             max_tokens: int = 4096, timeout: int = 120) -> str:
        if not self.is_configured():
            raise RuntimeError(f"{self.name}: API 키 미설정")
        url = self.base_url.rstrip("/") + "/chat/completions"
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                **self.extra_headers,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"{self.name} HTTP {e.code}: {body}")
        return data["choices"][0]["message"]["content"]


def detect_providers() -> dict:
    providers = {}
    if os.getenv("OPENAI_API_KEY"):
        providers["openai"] = AIProvider(
            name="openai",
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            api_key=os.getenv("OPENAI_API_KEY"),
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        )
    if os.getenv("ANTHROPIC_API_KEY"):
        providers["anthropic"] = AIProvider(
            name="anthropic",
            base_url=os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"),
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
            extra_headers={"anthropic-version": "2023-06-01"},
        )
    if os.getenv("ZAI_API_KEY"):
        providers["zhipu"] = AIProvider(
            name="zhipu",
            base_url=os.getenv("ZAI_BASE_URL", "https://api.z.ai/v1"),
            api_key=os.getenv("ZAI_API_KEY"),
            model=os.getenv("ZAI_MODEL", "glm-4.6"),
        )
    if os.getenv("MOONSHOT_API_KEY"):
        providers["moonshot"] = AIProvider(
            name="moonshot",
            base_url=os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1"),
            api_key=os.getenv("MOONSHOT_API_KEY"),
            model=os.getenv("MOONSHOT_MODEL", "kimi-k2-0905-preview"),
        )
    if os.getenv("MINIMAX_API_KEY"):
        providers["MiniMax"] = AIProvider(
            name="MiniMax",
            base_url=os.getenv("MINIMAX_BASE_URL", "https://api.MiniMax.chat/v1"),
            api_key=os.getenv("MINIMAX_API_KEY"),
            model=os.getenv("MINIMAX_MODEL", "MiniMax-Text-01"),
        )
    return providers


def get_provider(name=None) -> AIProvider:
    available = detect_providers()
    if not available:
        raise RuntimeError("AI 프로바이더 없음. .env에 키 추가")
    if name is None:
        name = os.getenv("DEFAULT_AI_PROVIDER") or next(iter(available))
    if name not in available:
        raise RuntimeError(f"'{name}' 미설정. 사용 가능: {list(available.keys())}")
    return available[name]
