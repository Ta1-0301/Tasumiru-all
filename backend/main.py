# backend/main.py
from dotenv import load_dotenv

# ⚠️ 他の自作ルーターを読み込む前に、最優先で .env をロードする
load_dotenv()

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# backend/jobs/timing.py が既に "tasumiru.pipeline" ロガーへステージ/LLM呼び出し
# ごとの構造化タイミングを記録している(STEP 9)が、ハンドラが未設定のため
# これまで実際には出力されていなかった。性能計測(10月2日提出前のボトルネック
# 特定)のため、ここでファイル出力を有効化する。既存のパイプライン処理・
# 出力内容には一切影響しない（ロギングを追加するだけ）。
_LOG_DIR = Path(__file__).resolve().parent / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_pipeline_logger = logging.getLogger("tasumiru.pipeline")
_pipeline_logger.setLevel(logging.INFO)
if not _pipeline_logger.handlers:
    _file_handler = logging.FileHandler(_LOG_DIR / "pipeline_perf.log", encoding="utf-8")
    _file_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    _pipeline_logger.addHandler(_file_handler)
    _pipeline_logger.propagate = False

from backend.db.session import init_db
# Base.metadata にテーブル定義を登録するため、モデルを import しておく
from backend.auth import models as _auth_models  # noqa: F401
from backend.models import member as _member_model  # noqa: F401
from backend.models import task as _task_model  # noqa: F401
from backend.models import project as _project_model  # noqa: F401  (Phase 10)
from backend.models import job as _job_model  # noqa: F401  (Phase 10)
from backend.auth.router import router as auth_router
from backend.routers import tasks  # .env ロード後にインポート
from backend.routers import projects, jobs  # Phase 10: パイプラインのジョブAPI
from backend.routers import documents  # 仕様書ファイル→本文テキスト変換API


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="タスみる API",
    description="仕様書からタスクを自動生成し、担当候補を提案するAPI",
    version="1.0.0",
    lifespan=lifespan,
)

# 指針1: ALLOWED_ORIGINS も .env から読み込む形へアップデート
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,  # 環境変数から取得したオリジンを許可
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ルーターの有効化
app.include_router(tasks.router)
app.include_router(auth_router)
app.include_router(projects.router)  # Phase 10
app.include_router(jobs.router)      # Phase 10
app.include_router(documents.router)  # 仕様書ファイル→本文テキスト変換API


@app.get("/healthz", tags=["health"])
def health_check():
    return {"status": "ok", "version": "1.0.0"}
