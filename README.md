# タスみる (Tasumiru)

仕様書から要件を抽出してタスクに分解し、メンバーのスキルと負荷をもとに担当者を提案する、AIプロジェクトマネジメント支援システムです。

高専プロコン2026 課題部門 出場作品

- バックエンド: FastAPI + LLMパイプライン（要件抽出 → タスク分解 → 依存関係 → 割当 → 検証）
- フロントエンド: Vite + TypeScript（Spec to Tasks の11ステップ画面）
- LLM: ローカルの Ollama（既定 `gemma3:4b`）。Anthropic API にも切り替え可能

---

## 必要なもの

| ツール | バージョン | 用途 |
|---|---|---|
| Python | 3.12 以上 | バックエンド |
| [uv](https://docs.astral.sh/uv/) | 最新 | Python の依存関係管理（`pyproject.toml` / `uv.lock`） |
| Node.js | 20.19 以上（22 以上推奨） | フロントエンド（Vite 8） |
| [Ollama](https://ollama.com/) | 最新 | ローカル LLM（Anthropic API を使う場合は不要） |
| Git | — | — |

---

## セットアップ

### 1. リポジトリを取得する

```bash
git clone https://github.com/Ta1-0301/Tasumiru-all.git
cd Tasumiru-all
```

### 2. バックエンド

プロジェクトのルートで実行します。

```bash
uv sync
```

`.venv/` が作られ、テスト用のパッケージ（pytest など）も含めて依存関係がインストールされます。

環境変数ファイルを作ります。

```bash
# Mac / Linux
cp .env.example .env
```

```powershell
# Windows (PowerShell)
Copy-Item .env.example .env
```

既定の設定（`LLM_PROVIDER=ollama`, `OLLAMA_MODEL=gemma3:4b`）のままでローカルの Ollama を使います。主な設定は次のとおりです。

| 変数 | 既定値 | 説明 |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` または `anthropic` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama のアドレス |
| `OLLAMA_MODEL` | `gemma3:4b` | 使用するモデル |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | — | `LLM_PROVIDER=anthropic` の場合に設定 |
| `ALLOWED_ORIGINS` | `http://localhost:5173` | CORS を許可するフロントエンドのオリジン（カンマ区切り） |
| `ENABLE_RAG` | `false` | 実験的な RAG 機能（通常は `false` のまま） |
| `OLLAMA_MAX_CONCURRENCY` | `1` | LLM 呼び出しの最大同時実行数（未設定なら逐次実行） |

### 3. Ollama のモデル

```bash
ollama pull gemma3:4b
```

Ollama が起動していない場合は `ollama serve` で起動します。Anthropic API を使う場合、この手順は不要です。

### 4. フロントエンド

```bash
cd frontend
npm install
cp .env.example .env.local      # Windows: Copy-Item .env.example .env.local
cd ..
```

バックエンドとフロントエンドを同じ PC で動かす場合、`.env.local` は変更不要です。別の PC でバックエンドを動かす場合は、`VITE_API_BASE_URL` と `BACKEND_PROXY_TARGET` をバックエンドのアドレスに書き換えてください（ログインなどの Cookie を使う API は、Vite の開発サーバーのプロキシ経由でバックエンドに中継されます）。

---

## 起動

### Windows: まとめて起動する

プロジェクトのルートで実行します。Ollama の起動確認、モデルの取得、フロントエンド（別ウィンドウ）、バックエンドの起動をまとめて行います。

```powershell
.\start-dev.ps1
```

オプション: `-Model gemma3:4b`（使用モデル）、`-Port 8000`（バックエンドのポート）、`-NoFrontend`（フロントエンドを起動しない）

### 個別に起動する（Mac / Linux / Windows）

ターミナルを2つ開きます。

```bash
# ターミナル1: バックエンド（プロジェクトのルートで）
uv run uvicorn backend.main:app --reload --port 8000
```

```bash
# ターミナル2: フロントエンド
cd frontend
npm run dev
```

### 動作確認

- バックエンド: http://localhost:8000/healthz にアクセスして `{"status": "ok", "version": "1.0.0"}` が返れば起動しています。API の一覧は http://localhost:8000/docs で確認できます。
- フロントエンド: http://localhost:5173/ を開きます。

初回はチーム作成画面が表示されます。チームを作成すると、次の流れで使えます。

1. 仕様書の本文を貼り付ける（テキスト / Markdown ファイルの読み込み、または「サンプル仕様書で試す」も可）
2. プロジェクト名とメンバー（氏名・`Python:4, React:3` 形式のスキル・稼働時間）を登録して「AI分析を開始」
3. 分析完了後、要件・タスク・依存関係・割当・警告・出典・Kanban を順に確認する

分析時間は仕様書の長さと PC の性能によって変わります（短い仕様書・`gemma3:4b` で数十秒〜数分）。

### その他の画面

| URL | 内容 |
|---|---|
| http://localhost:5173/ | Spec to Tasks 画面（メイン、バックエンド接続） |
| http://localhost:5173/legacy.html | 以前の画面 |
| http://localhost:5173/spec-to-tasks.html | Spec to Tasks のサンプルデータ版デモ（バックエンド不要） |

---

## テスト

```bash
uv run pytest backend/tests -q
```

実際の LLM は呼び出さず、テスト用の偽のクライアントで実行します（Ollama の起動は不要です）。

フロントエンドの型チェックとビルドは次のとおりです。

```bash
cd frontend
npm run build
```

---

## ディレクトリ構成

```text
.
├── backend/
│   ├── main.py              # FastAPI アプリ（/healthz, /docs）
│   ├── auth/                # チーム作成・招待・セッション
│   ├── routers/             # API（projects, jobs, tasks）
│   ├── jobs/                # 生成ジョブの実行・進捗・計測ログ
│   ├── pipeline/            # LLMパイプライン
│   │   ├── requirements/    #   要件抽出
│   │   ├── tasks/           #   タスク分解・スキル語彙・スキル整合性チェック
│   │   ├── dependencies/    #   依存関係
│   │   ├── members/         #   メンバー情報
│   │   ├── assignment/      #   担当者の割当
│   │   ├── validation/      #   検証
│   │   └── final_output/    #   最終JSONの組み立て
│   ├── services/            # LLMクライアント・スキル正規化/類似度・並列実行 など
│   └── tests/               # pytest
├── frontend/
│   ├── index.html           # Spec to Tasks 画面
│   ├── legacy.html          # 以前の画面
│   ├── spec-to-tasks.html   # サンプルデータ版デモ
│   └── src/
│       ├── specToTasks/     # Spec to Tasks 画面の実装
│       ├── api/ services/   # バックエンドとの通信
│       └── views/           # 認証・チーム管理などの画面
├── docs/                    # API仕様（openapi.json など）・性能計測の記録
├── .env.example             # バックエンドの環境変数のひな形
├── pyproject.toml / uv.lock # Python の依存関係
└── start-dev.ps1            # Windows 用の一括起動スクリプト
```

---

## よくあるトラブル

| 症状 | 原因 | 対処 |
|---|---|---|
| 画面に「バックエンドに接続できませんでした」と出る | バックエンドが起動していない、またはアドレスの設定違い | バックエンドを起動する。別の PC で動かしている場合は `frontend/.env.local` の `BACKEND_PROXY_TARGET` を確認する |
| 分析が「AIサーバーとの通信に失敗しました」で止まる | Ollama が起動していない、またはモデル未取得 | `ollama serve` と `ollama pull gemma3:4b` を実行する |
| 分析に非常に時間がかかる | PC の性能・モデルの大きさ | 小さいモデル（`gemma3:4b`）を使う。長い仕様書は分割する |
| ブラウザで CORS エラーが出る | フロントエンドのアドレスが許可されていない | `.env` の `ALLOWED_ORIGINS` にフロントエンドの URL を追加する |
| `uv: command not found` / `npm: command not found` | ツール未インストール、または PATH が古い | インストール後、ターミナルを開き直す |
| PDF / Word が読み込めない | 分析 API はテキスト本文のみ対応 | ファイルを開いて本文をコピーし、画面の入力欄に貼り付ける |

---

## License

This project is developed for the National Institute of Technology Programming Contest 2026 (KOSEN Procon 2026 - Problem Division).
