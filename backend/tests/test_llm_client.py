# backend/tests/test_llm_client.py
"""backend/services/llm.py の OllamaClient の単体テスト。

STEP 2(num_ctx明示設定)の回帰テスト。実際のOllamaは呼ばず、
httpx.AsyncClient.postをモンキーパッチして送信payloadだけを検証する。
"""

import httpx
import pytest

import backend.services.llm as llm_module
from backend.services.llm import OllamaClient, _parse_positive_int


def _patch_post(monkeypatch, captured: dict, response_text: str = "ok"):
    async def fake_post(self, url, json=None, **kwargs):
        captured["url"] = url
        captured["json"] = json
        request = httpx.Request("POST", url)
        return httpx.Response(200, json={"response": response_text}, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)


@pytest.mark.asyncio
async def test_complete_sends_num_ctx_in_options(monkeypatch):
    """既定値(OLLAMA_NUM_CTX未設定時)がpayload.options.num_ctxに入ること"""
    monkeypatch.setattr(llm_module, "OLLAMA_BASE_URL", "http://localhost:11434")
    captured: dict = {}
    _patch_post(monkeypatch, captured)

    client = OllamaClient()
    result = await client.complete("テストプロンプト")

    assert result == "ok"
    assert captured["json"]["options"] == {"num_ctx": llm_module.OLLAMA_NUM_CTX}


@pytest.mark.asyncio
async def test_complete_num_ctx_reflects_env_override(monkeypatch):
    """OLLAMA_NUM_CTXを変更したら、新しく作ったOllamaClientのnum_ctxに反映されること
    （既存のGENERATE時のみ切り替わる。既に生成済みのインスタンスは変わらない）"""
    monkeypatch.setattr(llm_module, "OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setattr(llm_module, "OLLAMA_NUM_CTX", 2048)
    captured: dict = {}
    _patch_post(monkeypatch, captured)

    client = OllamaClient()
    assert client.num_ctx == 2048
    await client.complete("テストプロンプト")

    assert captured["json"]["options"] == {"num_ctx": 2048}


@pytest.mark.asyncio
async def test_complete_still_sets_format_json_alongside_num_ctx(monkeypatch):
    """json_mode=Trueのときも、既存のformat="json"指定とnum_ctxが両方payloadに入ること
    （num_ctx追加が既存のjson_mode挙動を壊していないことの回帰テスト）"""
    monkeypatch.setattr(llm_module, "OLLAMA_BASE_URL", "http://localhost:11434")
    captured: dict = {}
    _patch_post(monkeypatch, captured)

    client = OllamaClient()
    await client.complete("テストプロンプト", json_mode=True)

    assert captured["json"]["format"] == "json"
    assert captured["json"]["options"] == {"num_ctx": llm_module.OLLAMA_NUM_CTX}


def test_parse_positive_int_falls_back_on_missing_or_invalid(monkeypatch):
    monkeypatch.delenv("SOME_TEST_ENV_VAR", raising=False)
    assert _parse_positive_int("SOME_TEST_ENV_VAR", 8192) == 8192

    monkeypatch.setenv("SOME_TEST_ENV_VAR", "not-a-number")
    assert _parse_positive_int("SOME_TEST_ENV_VAR", 8192) == 8192

    monkeypatch.setenv("SOME_TEST_ENV_VAR", "0")
    assert _parse_positive_int("SOME_TEST_ENV_VAR", 8192) == 8192

    monkeypatch.setenv("SOME_TEST_ENV_VAR", "-5")
    assert _parse_positive_int("SOME_TEST_ENV_VAR", 8192) == 8192


def test_parse_positive_int_reads_valid_value(monkeypatch):
    monkeypatch.setenv("SOME_TEST_ENV_VAR", "4096")
    assert _parse_positive_int("SOME_TEST_ENV_VAR", 8192) == 4096
