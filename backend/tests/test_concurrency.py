# backend/tests/test_concurrency.py
"""backend/services/concurrency.py の単体テスト（Part 3）。"""

import asyncio

import pytest

from backend.services.concurrency import gather_with_concurrency, get_max_concurrency


@pytest.mark.asyncio
async def test_results_preserve_input_order_regardless_of_completion_order():
    async def delayed(value, delay):
        await asyncio.sleep(delay)
        return value

    factories = [
        (lambda: delayed("a", 0.03)),
        (lambda: delayed("b", 0.01)),
        (lambda: delayed("c", 0.02)),
    ]
    results = await gather_with_concurrency(factories, max_concurrency=3)
    assert results == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_concurrency_of_one_runs_fully_sequentially():
    active = 0
    max_active = 0

    async def track():
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return "done"

    factories = [track for _ in range(5)]
    await gather_with_concurrency(factories, max_concurrency=1)
    assert max_active == 1


@pytest.mark.asyncio
async def test_concurrency_limit_is_respected():
    active = 0
    max_active = 0

    async def track():
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return "done"

    factories = [track for _ in range(10)]
    await gather_with_concurrency(factories, max_concurrency=3)
    assert max_active <= 3
    assert max_active > 1  # 実際に並列化されていることも確認する


@pytest.mark.asyncio
async def test_empty_list_returns_empty_list():
    assert await gather_with_concurrency([], max_concurrency=2) == []


def test_get_max_concurrency_defaults_to_one_when_unset(monkeypatch):
    monkeypatch.delenv("OLLAMA_MAX_CONCURRENCY", raising=False)
    assert get_max_concurrency() == 1


def test_get_max_concurrency_reads_env_var(monkeypatch):
    monkeypatch.setenv("OLLAMA_MAX_CONCURRENCY", "4")
    assert get_max_concurrency() == 4


def test_get_max_concurrency_falls_back_on_invalid_value(monkeypatch):
    monkeypatch.setenv("OLLAMA_MAX_CONCURRENCY", "not-a-number")
    assert get_max_concurrency() == 1


def test_get_max_concurrency_falls_back_on_non_positive_value(monkeypatch):
    monkeypatch.setenv("OLLAMA_MAX_CONCURRENCY", "0")
    assert get_max_concurrency() == 1
