# backend/tests/conftest.py
import os

# backend.main のインポート時に環境変数チェックが走るため、テスト実行前に最低限の値を設定する
os.environ.setdefault("LLM_PROVIDER", "ollama")
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
os.environ.setdefault("MAX_TASKS_FREE", "50")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:5173")

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.auth import models as _auth_models  # noqa: F401  Base.metadata登録のため
from backend.db.base import Base
from backend.db.session import get_db
from backend.main import app as fastapi_app
from backend.models import member as _member_models  # noqa: F401
from backend.models import task as _task_models  # noqa: F401


@pytest_asyncio.fixture
async def db_engine():
    """テストごとに独立したインメモリSQLiteエンジンを作成する"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """テストコードから直接DBを操作するためのセッション（期限切れ・無効化状態の再現用）"""
    session_maker = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_engine):
    """アプリの get_db をテスト用DBに差し替えたHTTPクライアント"""
    session_maker = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    fastapi_app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    fastapi_app.dependency_overrides.clear()


def new_client(db_engine):
    """同じテストDBに対して独立したCookieジャール（＝別デバイス）を持つクライアントを作る"""
    session_maker = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    fastapi_app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=fastapi_app)
    return AsyncClient(transport=transport, base_url="http://testserver")
