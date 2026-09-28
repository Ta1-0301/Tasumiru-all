import os
import asyncio
from abc import ABC, abstractmethod

import httpx
from fastapi import HTTPException

# 指針1: デフォルト値を持たせず、.env からダイレクトに取得（なければNone）
LLM_PROVIDER = os.getenv("LLM_PROVIDER")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")


def _parse_positive_int(env_var: str, default: int) -> int:
    """backend/services/concurrency.pyのget_max_concurrencyと同じ方針:
    未設定/不正な値は保守的にデフォルトへフォールバックする（起動時に例外で
    落ちたりしない）。"""
    raw = os.getenv(env_var)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


# Ollamaのcontext window(トークン数)。未指定だとOllama側の実効デフォルト
# (実測で約4096)に切り捨てられ、長い仕様書/大量Taskのプロンプトが欠落した
# まま推論される→JSON parse失敗→call_llm_jsonのリトライ、という無駄な遅延が
# 発生することを実測で確認した(2026-09-25の性能調査)。速度目的ではなく、
# この切り捨てを防ぐための設定。既定値8192はApple M1/8GBでのメモリ使用量・
# 生成品質を確認した上で採用（詳細はSTEP8のA/B計測記録を参照）。
OLLAMA_NUM_CTX = _parse_positive_int("OLLAMA_NUM_CTX", 8192)


class BaseLLMClient(ABC):
    """
    全プロバイダー共通のインターフェース。

    NOTE: 以前は generate_tasks(document_text) という「仕様書→タスク配列」専用の
          メソッドを持っていたが、単一のプロンプトに固定された処理だとタスク抽出
          パイプライン（backend/services/pipeline/）が必要とする複数ステップの
          プロンプト（文書構造把握・要求抽出・候補タスク化・JSON修復など）に
          対応できない。そのため、プロンプト構築や出力形式の意味づけを一切知らない
          汎用的な complete() だけを提供し、プロンプト設計は呼び出し側
          （パイプラインの各ステージ）に委ねる設計に変更した。
          これにより「タスク生成ロジックにOllama固有の挙動をハードコードしない」
          という要件も自然に満たせる。
    """

    @abstractmethod
    async def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        """プロンプトに対する生のテキスト補完を返す（JSONパースは呼び出し側の責務）"""


class OllamaClient(BaseLLMClient):
    """コンペ本番用：ローカル Ollama 実装（モデル名は環境変数 OLLAMA_MODEL で切り替え可能、既定は llama3.1:8b）"""

    def __init__(self):
        if not OLLAMA_BASE_URL:
            raise RuntimeError("環境変数 'OLLAMA_BASE_URL' が設定されていません。")
        self.base_url = OLLAMA_BASE_URL
        self.model = OLLAMA_MODEL
        self.num_ctx = OLLAMA_NUM_CTX

    async def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_ctx": self.num_ctx},
        }
        if json_mode:
            payload["format"] = "json"

        async with httpx.AsyncClient(timeout=300) as client:
            try:
                response = await client.post(f"{self.base_url}/api/generate", json=payload)
                response.raise_for_status()
                return response.json()["response"]
            except httpx.HTTPError:
                raise HTTPException(
                    status_code=504,
                    detail={"code": "LLM_TIMEOUT", "message": "AIサーバーとの通信に失敗しました。"},
                )
            except KeyError:
                raise HTTPException(
                    status_code=500,
                    detail={"code": "LLM_PARSE_ERROR", "message": "AIの応答フォーマットが不正です。"},
                )


class AnthropicClient(BaseLLMClient):
    """本番/マネタイズ用：Anthropic Claude の実装"""

    def __init__(self):
        import anthropic  # 使用時のみインポート（Ollama運用時は未インストールでも起動可能にする）

        if not ANTHROPIC_API_KEY:
            raise RuntimeError("環境変数 'ANTHROPIC_API_KEY' が設定されていません。")
        # Anthropic SDKは同期クライアントのみなので、asyncio.to_thread で非同期化する
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = ANTHROPIC_MODEL

    async def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        import anthropic  # __init__ と同様、使用時のみインポート

        # NOTE: Claude はJSONモード専用のAPIフラグを持たないため、json_modeは
        #       呼び出し側のプロンプト文面での指示に委ねる（ここでは無視する）。
        try:
            response = await asyncio.to_thread(
                self.client.messages.create,
                model=self.model,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APITimeoutError:
            raise HTTPException(
                status_code=504,
                detail={"code": "LLM_TIMEOUT", "message": "Anthropic APIとの通信がタイムアウトしました。"},
            )
        except anthropic.APIError as e:
            raise HTTPException(
                status_code=502,
                detail={"code": "LLM_API_ERROR", "message": f"Anthropic APIエラー: {str(e)}"},
            )

        raw_text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()

        # モデルが ```json ... ``` で囲んで返してきた場合のガードレール
        if raw_text.startswith("```"):
            raw_text = raw_text.strip("`")
            if raw_text.lower().startswith("json"):
                raw_text = raw_text[4:].strip()

        return raw_text


class OpenAIClient(BaseLLMClient):
    """将来のマネタイズ用：OpenAI 実装（未実装のモック）"""

    async def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        return "{}"


def get_llm_client() -> BaseLLMClient:
    """環境変数の値に応じてクライアントを動的に返す（設定なしはエラー）"""
    if not LLM_PROVIDER:
        raise RuntimeError("環境変数 'LLM_PROVIDER' が設定されていません。")

    if LLM_PROVIDER == "openai":
        return OpenAIClient()
    elif LLM_PROVIDER == "anthropic":
        return AnthropicClient()
    elif LLM_PROVIDER == "ollama":
        return OllamaClient()
    else:
        raise RuntimeError(f"未対応のLLMプロバイダーが指定されています: {LLM_PROVIDER}")
