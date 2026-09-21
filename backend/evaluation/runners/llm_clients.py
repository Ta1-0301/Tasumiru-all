# backend/evaluation/runners/llm_clients.py
"""
評価専用のLLMクライアント実装。

`backend/services/llm.py` の本番クライアント(`OllamaClient`/`AnthropicClient`)は
モデル名・温度(temperature)がハードコードまたは非対応で、複数モデルの比較用途
には使えない（例: `OllamaClient.model`は常に"llama3.1:8b"に固定されている）。

複数モデル(Model A / Model B / Model C)を同じ評価フレームワークで比較する
ためには、モデル名・temperatureを差し替えられるクライアントが必要になる。
そのため、ここでだけ`backend.services.llm.BaseLLMClient`の評価専用の実装を
追加する。**本番コード(backend/services/llm.py)は一切変更しない。**

evaluators/metrics側は`BaseLLMClient.complete()`だけを呼ぶため、ここで
どのクライアント実装を使ってもモデル固有の分岐は一切発生しない。
"""

from __future__ import annotations

import asyncio
import os
from typing import Optional

import httpx

from backend.services.llm import BaseLLMClient


class EvaluationOllamaClient(BaseLLMClient):
    """評価用: モデル名・temperatureを明示的に指定できるOllamaクライアント。"""

    def __init__(
        self,
        model: str,
        base_url: Optional[str] = None,
        temperature: Optional[float] = None,
    ):
        self.model = model
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL")
        self.temperature = temperature
        if not self.base_url:
            raise RuntimeError("環境変数 'OLLAMA_BASE_URL' が設定されていません。")

    async def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        payload = {"model": self.model, "prompt": prompt, "stream": False}
        if json_mode:
            payload["format"] = "json"
        if self.temperature is not None:
            payload["options"] = {"temperature": self.temperature}

        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(f"{self.base_url}/api/generate", json=payload)
            response.raise_for_status()
            return response.json()["response"]


class EvaluationAnthropicClient(BaseLLMClient):
    """評価用: モデル名・temperatureを明示的に指定できるAnthropicクライアント。"""

    def __init__(
        self,
        model: str,
        temperature: Optional[float] = None,
        api_key: Optional[str] = None,
    ):
        import anthropic  # 使用時のみインポート（未使用時は未インストールでもよい）

        self.model = model
        self.temperature = temperature
        key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("環境変数 'ANTHROPIC_API_KEY' が設定されていません。")
        self.client = anthropic.Anthropic(api_key=key)

    async def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        kwargs = dict(
            model=self.model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature

        response = await asyncio.to_thread(self.client.messages.create, **kwargs)
        raw_text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()

        if raw_text.startswith("```"):
            raw_text = raw_text.strip("`")
            if raw_text.lower().startswith("json"):
                raw_text = raw_text[4:].strip()

        return raw_text
