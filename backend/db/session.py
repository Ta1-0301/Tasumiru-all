# backend/db/session.py
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.config import settings
from backend.db.base import Base

# SQLiteの場合のみ、特殊な接続引数が必要
connect_args = {"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}

engine = create_async_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=True,  # 開発時はSQLログを出力（本番は環境変数でFalseに制御できるようにすると良い）
)

# 各リクエストで使うSessionのファクトリ
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """テーブルが存在しなければ作成する（開発用。本番はAlembicマイグレーションに移行予定）"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    """
    FastAPIの Depends() から使うDBセッションのジェネレータ。

    NOTE: yield以降の後始末コードはFastAPIにより「レスポンス送信後」に実行されるため、
          ここで自動コミットすると「クライアントが201を受け取った直後に次のリクエストを送る」
          という現実的な流れでコミット前の状態を読んでしまうレースコンディションが発生する
          （実機・実HTTPでの統合テストで実際に再現した: 招待作成→即join で稀に404になる）。
          そのため各エンドポイント側で明示的に await db.commit() を呼ぶ設計とし、
          ここでは異常系のロールバックのみを担当する。
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
