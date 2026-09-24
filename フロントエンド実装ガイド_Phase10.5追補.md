# タスみる フロントエンド Phase 10.5 追補プロンプト

**新しいチャットを開いたら、このファイルの内容をそのまま貼り付けてください。**
既存のフロントエンド実装（`frontend/`）を前提にした**追補**です。まだ
`frontend/`が無い場合は、先に`フロントエンド実装ガイド.md`（リポジトリ直下）
を使ってセットアップしてから、このファイルを貼り付けてください。

---

## これはどういう位置づりのドキュメントか

このファイルはBackend側のセッション（Claude Code）が、**バックエンドの実際の
実装（`backend/`のソースコード・テスト・`docs/API_CONTRACT.md`・
`docs/openapi.json`）を直接読んで検証した内容**に基づいて書いている。
フロントエンド側のファイル（`frontend/`）は一切見ていない
——**別のMac上にあり、このセッションからはアクセスできないため**。

つまりこのドキュメントは:
- ✅ 「バックエンドは何を提供しているか」については断言できる（実装を読んで確認済み）
- ❌ 「今のフロントエンドがどう実装されているか」は断言できない（見ていない）

なので、**あなた（このプロンプトを渡された側）が最初にやるべきことは、
自分の`frontend/`を実際に読んで、demo/mock/fixtureがどこにあるかを
特定すること**。以下は「バックエンドの正確な事実」と「フロントエンドで
確認・実施すべきチェックリスト」の2部構成にしてある。

---

## Part A: バックエンドの現状（Phase 10で追加された事実）

`フロントエンド実装ガイド.md`が書かれた時点（Phase 9まで）から、バックエンドに
**Projects/Jobs API**が追加された。これにより、仕様書→タスク生成の「本流」の
実装が変わった。以下は2025-08-26時点の実装を直接確認した内容。

### A.1 認証（`/api/me`）は変更なし・引き続き使う

`フロントエンド実装ガイド.md` §4の認証フロー（チーム/メンバー/デバイスセッション、
`tasumiru_session`というHttpOnly Cookie、起動時の`GET /api/me`チェック）は
**Phase 10で一切変更されていない**（`backend/auth/*`は無変更）。

**結論: `main.ts`の起動時`GET /api/me`チェックはそのまま使い続けてよい。**
「/api/meが今のアーキテクチャに合わなくなった」という事実は無い。置き換える
必要は無く、削除してはいけない。

### A.2 新しいAPI: Projects & Jobs（`/api/projects/*`, `/api/jobs/*`）

すべて**チーム/デバイスセッションCookie必須**（`withCredentials: true`、
既存の`apiClient`をそのまま使う）。他チームのproject_id/job_idを指定すると
`404`（他チームの存在を教えないための設計、他のAPIと同じパターン）。

#### プロジェクト作成・取得

```
POST /api/projects
  body: { "name"?: string, "document_text"?: string }
  → 201 { "id": string, "team_id": string, "name": string|null,
          "has_document": boolean, "has_members": boolean,
          "created_at": string, "updated_at": string }

GET /api/projects/{project_id}
  → 200 同上の形
  → 404 { "detail": { "code": "PROJECT_NOT_FOUND", "message": "..." } }
```

⚠️ **重要な欠落: 「自チームのプロジェクト一覧を取得する」エンドポイントは
存在しない。** `GET /api/projects`（一覧）は無い。`project_id`を知らないと
何も取得できない。したがって:

- プロジェクト作成後、返ってきた`id`を**クライアント側（`localStorage`等）に
  保存する必要がある**（Phase 10の元の指示にある「必要最小限のクライアント状態」
  がこれに当たる。DBが真実の情報源であることに変わりはないが、「どのIDを見るか」
  だけはフロントが覚えておくしかない）。
- ブラウザをリロードした際は、保存しておいた`project_id`で
  `GET /api/projects/{project_id}`を呼んで存在確認する。`404`が返ってきたら
  （他チームでログインし直した等）保存値を破棄して「プロジェクト未作成」状態に戻す。
- これは今回のフロントエンド側の対応だけでは解決できない、**バックエンド側の
  既知の制限**。一覧エンドポイントが将来必要になったら、それは別フェーズで
  バックエンドに追加を依頼すること（今回のフロントエンド側の作業では
  新しいバックエンドエンドポイントを作らないこと）。

#### メンバー管理

```
PUT /api/projects/{project_id}/members
  body: { "members": [ {
    "id": string, "name": string,
    "skills"?: [{ "skill": string, "level": number(1-5), "experience_years"?: number|null }],
    "experience_years"?: number|null,
    "availability": { "available_hours_per_week": number,
                       "working_days"?: string[], "current_assigned_hours"?: number },
    "constraints"?: [{ "type": "scope_restriction"|"day_unavailable"|"max_hours_per_week"|"requires_review",
                        "value"?: string|null, "max_hours"?: number|null }]
  } ] }
  → 200 MemberDirectory（下記と同じ形。issuesにバリデーション結果が入る。
        リクエストは失敗させず、問題点だけ返す設計）

GET /api/projects/{project_id}/members
  → 200 { "team_id": string|null, "members": Member[],
           "issues": [{ "code": string, "message": string, "member_id": string|null }],
           "updated_at": string|null }
  → 404 { "detail": { "code": "MEMBERS_NOT_CONFIGURED", ... } }  ← まだ設定されていない
```

**`availability.available_hours_per_week`は必須。** それ以外は省略可。
スキルレベルや稼働状況をフロントエンドが**推測して埋めてはいけない**
——バックエンド側も同じ方針（Phase 6は「LLMがスキルレベルを自動生成しない」
ことを前提に設計されている）。入力フォームで未入力の項目はそのまま未送信にする。

#### 生成ジョブ（本体）

```
POST /api/projects/{project_id}/generate
  body: {
    "document_text"?: string,   // 渡すとプロジェクトの仕様書テキストを上書きしてから実行
    "use_assignment_llm_reasoning"?: boolean,   // 既定false。付けなくてよい
    "use_duplicate_llm_verification"?: boolean  // 既定false。付けなくてよい
  }
  → 202 { "job_id": string, "status": "queued" }
  → 400 { "detail": { "code": "DOCUMENT_NOT_SET", ... } }        // 仕様書テキストが無い
  → 400 { "detail": { "code": "MEMBERS_NOT_CONFIGURED", ... } }  // メンバー未設定
```

`document_text`はプレーンテキストのみ。**ファイルアップロード（PDF/Word）を
直接このエンドポイントに投げることはできない**——詳細はPart Bの
「仕様書アップロードについての重要な注意」を必ず読むこと。

呼び出す前に、フロントエンド側で「仕様書が入力されている」「メンバーが
1人以上登録されている」ことを確認し、事前にエラーメッセージを出す方が
UXとして親切（バックエンドも400を返すが、事前チェックの方が速い）。

#### ジョブのポーリング

```
GET /api/jobs/{job_id}
  → 200 {
    "job_id": string, "project_id": string, "team_id": string,
    "status": "queued"|"running"|"completed"|"failed"|"cancelled",
    "progress": number,          // 0-100
    "current_step": "requirements"|"tasks"|"dependencies"|"members"|"assignments"|"validation"|"finalize"|null,
    "message": string|null,      // 日本語、そのまま画面に表示してよい
    "created_at": string, "started_at": string|null, "completed_at": string|null,
    "error": { "code": string, "message": string } | null   // status=="failed"の時のみ非null
  }
```

- `status=="queued"`の間、`current_step`は`null`（まだどのステージも始まっていない）。
- 1〜2秒間隔でポーリングする。バックエンドの実測では、1回のLLM呼び出しに
  30秒〜3分程度かかる環境がある（`docs/PIPELINE_PERFORMANCE.md`参照）。
  **タイマーで進捗を偽装しないこと** — `progress`/`current_step`/`message`は
  必ずこのレスポンスの値をそのまま使う。
- `status=="completed"`になったら`GET /api/jobs/{job_id}/result`（下記）を呼ぶ。
- `status=="failed"`になったら`error.code`/`error.message`をそのまま表示する
  （スタックトレースは絶対に含まれない設計なので、そのまま出してよい）。
- `status=="cancelled"`は現在バックエンドが自発的に設定することは無い
  （ジョブをキャンセルするAPIも無い）が、型としては存在するので、
  UI側は分岐だけ用意しておく（未対応の状態として扱えば十分）。

#### 結果・各ステージのデータ取得

```
GET /api/jobs/{job_id}/result        → 200 FinalProjectOutput（下記）
                                       → 409 { "detail": { "code": "JOB_NOT_COMPLETED", ... } }  // 未完了
                                       → 409 { "detail": { "code": "<error_code>", ... } }        // 失敗時
GET /api/jobs/{job_id}/error         → 200 { "code": string, "message": string }
                                       → 404 { "detail": { "code": "NO_ERROR", ... } }  // 失敗していない
GET /api/jobs/{job_id}/requirements  → 200 RequirementDocument  / 409 STAGE_NOT_READY
GET /api/jobs/{job_id}/tasks         → 200 TaskDocument         / 409 STAGE_NOT_READY
GET /api/jobs/{job_id}/dependencies  → 200 DependencyDocument   / 409 STAGE_NOT_READY
GET /api/jobs/{job_id}/assignments   → 200 FinalAssignment[]    / 409 STAGE_NOT_READY
GET /api/jobs/{job_id}/validation    → 200 ValidationReport     / 409 STAGE_NOT_READY
```

`/result`（`FinalProjectOutput`）は全部入りで、個別のステージAPIは
「途中経過を先に見たい」「1画面だけ再取得したい」時に使う。どちらを使うかは
画面設計次第——両方とも実データを返す本物のAPI。

### A.3 実際のスキーマ（フィールド名を正確に）

**`RequirementDocument.requirements[]`（`Requirement`）**
```ts
{
  id: string;              // "REQ-001" 形式
  type: "system_purpose"|"target_user"|"functional"|"non_functional"|"constraint"|"assumption"|"deliverable"|"technical"|"business_rule";
  title: string; description: string;
  priority: "high"|"medium"|"low"|"unknown";
  origin: "explicit"|"inferred";
  source_reference: { document_id: string; page: number|null; section: string|null;
                       paragraph: string|null; source_text: string|null } | null;
  confidence: number;  // 0.0-1.0
}
```

**`TaskDocument.tasks[]`（`Task`）**——旧`/api/tasks`の`TaskSchema`とは**別物**、
フィールド名が違う点に注意（`task_id`ではなく`id`、`assignee`は無い等）:
```ts
{
  id: string;                    // "TASK-001" 形式（旧"T-001"とは別フォーマット）
  requirement_ids: string[];     // どの要求(REQ-xxx)から来たか
  title: string; description: string;
  priority: "high"|"medium"|"low"|"unknown";
  estimated_hours: number|null;
  required_skills: string[];     // レベル情報は無い（名前だけ）。デフォルト ["unknown"]
  acceptance_criteria: string[]; // 完了条件
  source_reference: { document_id, page, section, paragraph, source_text } | null;
  confidence: number;
  needs_review: boolean;         // レビュー推奨フラグ
  review_reasons: string[];      // 具体的な理由（無いなら空配列）
}
```
担当者(assignee)はTaskには**含まれない**——Assignments APIを別途参照する
（下記）。「必須スキル」はレベル無しの文字列一覧のみ。

**`DependencyDocument.dependencies[]`（`Dependency`）**——タスク自身には
依存関係が埋め込まれていない。フロント側で`to_task_id === task.id`の辺を
フィルタして「このタスクの前提」を組み立てる:
```ts
{
  from_task_id: string;  // 先に終わらせるべきタスク
  to_task_id: string;    // それに続くタスク
  type: "required"|"recommended"|"optional";
  reason: string; confidence: number;
}
```

**`FinalAssignment[]`（`GET .../assignments`の要素）**——担当者情報はここ:
```ts
{
  task_id: string;
  assigned_member_id: string | null;  // ← nullがあり得る（該当者無しの場合）
  decided_by: "ai" | "human";
  overridden: boolean;
  override_reason: string | null;
  ai_recommendation: {
    task_id: string; recommended_member_id: string|null; score: number|null; // 0-100
    candidate_scores: Array<{ member_id, skill_match, workload_score, experience_score, availability_score, score }>;
    rejected_candidates: Array<{ member_id: string; reasons: string[] }>;
    reasons: string[]; warnings: string[];
    status: "recommended" | "no_suitable_member";
  };
}
```
`assigned_member_id`が`null`のタスクは「担当者未定」として**「未設定」と
表示する**（STEP 12参照。架空の担当者名を作らない）。

**`ValidationReport`（`GET .../validation`、または`result.validation.report`）**
```ts
{
  valid: boolean;
  missing_requirements: Array<{ requirement_id: string; message: string }>;
  duplicate_tasks: Array<{ task_ids: string[]; similarity: number; method: "rule"|"llm"|"hybrid"; reason: string }>;
  dependency_errors: Array<{ code: string; message: string; task_ids: string[] }>;
  workload_warnings: Array<{ member_id, assigned_hours, available_hours, remaining_capacity, workload_percentage, code, message }>;
  skill_mismatches: Array<{ task_id, member_id, skill, required_level, member_level, message }>;
  constraint_violations: Array<{ task_id, member_id, code, message }>;
  workload_summaries: Array<{ member_id, assigned_hours, available_hours, remaining_capacity, workload_percentage }>;  // 問題無い人も含め全員分
  generated_at: string|null;
}
```

**`FinalProjectOutput`（`GET .../result`）**——上記すべてを1つにまとめたもの:
```ts
{
  project: { document_id: string; name: string|null; exported_at: string|null };
  requirements: Requirement[]; tasks: Task[]; dependencies: Dependency[];
  members: Member[]; assignments: FinalAssignment[];
  validation: {
    status: "valid" | "warning" | "error";   // ← 3段階。ValidationReport自体はvalid:booleanしか持たない
    critical_issue_count: number; warning_issue_count: number;
    traceability_errors: Array<{ code: string; message: string; task_id: string|null }>;
    report: ValidationReport;  // 上記そのまま
  };
  metadata: { generated_at: string; pipeline_version: string; model: string|null;
              model_version: string|null; prompt_versions: Record<string,string>;
              document_id: string|null; models_by_phase: Record<string,string> };
}
```
`validation.status`（3段階）を画面のバッジ等に使うとよい:
`"valid"`→問題なし、`"warning"`→要確認だが計画としては成立、`"error"`→
重大な問題あり（例: 要求に対応するタスクが無い、ハード制約違反等）。

### A.4 エラーコード一覧（Part Aで新規追加分）

`{"detail": {"code": "...", "message": "..."}}`という既存と同じ形（例外:
`/error`エンドポイントだけは`detail`で包まずトップレベルの`{code, message}`）。

| code | HTTPステータス | 意味 |
|---|---|---|
| `PROJECT_NOT_FOUND` | 404 | プロジェクトが無い、または他チームのもの |
| `JOB_NOT_FOUND` | 404 | ジョブが無い、または他チームのもの |
| `MEMBERS_NOT_CONFIGURED` | 400 (generate時) / 404 (GET members時) | メンバー未設定 |
| `DOCUMENT_NOT_SET` | 400 | 仕様書テキスト未設定 |
| `JOB_NOT_COMPLETED` | 409 | 完了前に`/result`を呼んだ |
| `STAGE_NOT_READY` | 409 | そのステージがまだ終わっていない |
| `NO_ERROR` | 404 | 失敗していないジョブに`/error`を呼んだ |
| その他（`OLLAMA_UNAVAILABLE`/`INTERNAL_ERROR`等） | job.errorの中 | ジョブ失敗理由。そのまま表示可 |

---

## Part B: フロントエンド側でやること（チェックリスト）

以下は元のPhase 10.5指示を、検証済みの事実に基づいて具体化したもの。
**あなた自身の`frontend/`を実際に読んでから**、該当箇所を特定して直すこと。
ファイル名は元の`フロントエンド実装ガイド.md`の構成（`src/api/`, `src/views/`,
`src/types/schemas.ts`）を前提にしているが、実際の構成が違えば実物を優先すること。

### B.1 まず調査: demo/mock/fixtureの洗い出し

`frontend/src/`全体を`demo`, `mock`, `fixture`, `sample`, `fake`, `dummy`で
grepし、見つかった箇所ごとに分類する:

- **A. 本番のデータソースとして使われている** → 置き換え対象
- **B. テスト専用（`*.test.ts`等）** → そのまま残してよい
- **C. コメント・ドキュメント内の言及のみ** → 何もしなくてよい
- **D. UIのプレースホルダーテキスト（`placeholder="例: ..."`等）** → そのまま残してよい

**A**に分類したものだけを、以下のPart B.2以降の内容で置き換える。

### B.2 APIクライアント構成

`src/api/client.ts`の`apiClient`（`withCredentials: true`）は既存のものを
**そのまま使う**——新しいAxiosインスタンスを作らない。新しいサービス関数を
追加する形にする（例: `src/api/projects.ts`, `src/api/jobs.ts`）。

`VITE_API_BASE_URL`（既存の環境変数名。指示書では`VITE_API_URL`という例が
出ているが、既存の`フロントエンド実装ガイド.md`は`VITE_API_BASE_URL`を
使っているので、フロントエンドに実際にどちらの変数名が使われているか確認し、
**既存の変数名に合わせる**——変数名を勝手に変えるとビルド時に壊れる）。

`frontend/.env.example`を作る/更新する:
```env
VITE_API_BASE_URL=http://localhost:8000
```
2台目のMacでは`frontend/.env.local`（gitignore対象にする）で実際のIPに
上書きする、という運用をコメントで明記する。

### B.3 型定義

`src/types/schemas.ts`に、Part A.3の型をそのまま追加する。既存の
`Task`/`Member`/`ProjectOutput`型（旧`/api/tasks`用）と**名前が衝突しない
ように**する（例: `PipelineTask`, `PipelineDocument`, `FinalProjectOutput`
のように別名にするか、旧タスク画面ごと新APIに置き換えるなら旧型を削除する
——後者の場合、旧`/api/tasks/*`系のservices/viewsも合わせて整理すること）。

### B.4 認証初期化（`main.ts`）

**変更不要。** `GET /api/me`による起動時チェックはそのまま。Part A.1参照。

### B.5 プロジェクト作成・再開

- 「プロジェクトを作成」操作 → `POST /api/projects` → 返ってきた`id`を
  `localStorage`（キー例: `tasumiru_active_project_id`）に保存し、以後の
  画面遷移でこの値を使う。
- アプリ起動時（`/api/me`成功後）、保存された`project_id`があれば
  `GET /api/projects/{id}`で存在確認。`404`なら保存値を消して
  「プロジェクト未作成」の状態に戻す。
- 偽の`project_id`を生成しない（Part A.2の一覧APIが無い制限を踏まえ、
  UUIDをでっち上げて動いたふりをしない）。

### B.6 メンバー管理画面

- 表示: `GET /api/projects/{id}/members`。**404 (`MEMBERS_NOT_CONFIGURED`)は
  エラーではなく「まだ未登録」という正常な空状態として扱う**
  （「メンバーがまだ登録されていません」＋登録フォームを表示）。
- 追加/編集: フォームの内容をまとめて`PUT /api/projects/{id}/members`
  （**全件送信・置き換え**——バックエンドはPUTなので、既存メンバーを
  維持したい場合は取得済みの一覧に追記してから送信すること）。
- 保存後は**レスポンスのMemberDirectoryをそのまま画面に反映**する
  （楽観的更新だけに頼らない。`issues`があれば警告として表示する）。

### B.7 仕様書アップロードについての重要な注意

⚠️ **新しいProjects APIは`document_text`（プレーンテキスト）しか受け付けない。
ファイル（PDF/Word）を直接送るエンドポイントは無い。**

既存のアップロードUI（ファイル選択 or テキスト直接入力）は変更しなくてよいが、
接続先を以下のように分ける必要がある:

- **テキスト直接入力 / `.txt`・`.md`ファイル**: ブラウザの`File.text()`で
  読み取ったプレーンテキストを、そのまま`POST /api/projects/{id}/generate`の
  `document_text`（または先に`PUT`相当が無いので`generate`呼び出し時に
  一緒に）渡せばよい。これは今すぐ実現できる。
- **`.pdf` / `.docx`ファイル**: 新しいProjects APIにはテキスト抽出手段が無い
  （抽出ロジックは旧`POST /api/tasks/generate`エンドポイント内部にしか無く、
  それは別のチーム非依存・非ジョブ方式のエンドポイントで、そのまま流用すると
  Projects/Jobsの仕組みと繋がらない）。**これは今回のフロントエンド作業だけでは
  解決できない、バックエンド側の制限として正直に扱うこと**:
  - 選択肢1: 今回はPDF/Wordのアップロードを一時的に無効化するか、
    「対応形式: .txt, .md のみ」と明示する。
  - 選択肢2: 対応が必要なら、バックエンド側に「テキスト抽出だけを行う
    エンドポイント」の追加を別途依頼する（**今回のフロントエンド作業の中で
    新しいバックエンドエンドポイントを作らないこと**——Phase 10.5の指示にも
    明記されている制約）。
  - どちらを選んだ場合も、ユーザーに何が起きているか誤解させない
    （PDFを選んだのに何も起きない、または旧エンドポイントに送られて
    Projects/Jobsと無関係な結果が出る、といった状態を避ける）。

### B.8 タスク生成ボタン

```ts
// src/api/jobs.ts（新規）
export async function startGeneration(projectId: string, documentText?: string) {
  const { data } = await apiClient.post(`/api/projects/${projectId}/generate`,
    documentText ? { document_text: documentText } : {});
  return data; // { job_id, status: "queued" }
}

export async function getJobStatus(jobId: string) {
  const { data } = await apiClient.get(`/api/jobs/${jobId}`);
  return data;
}
```

ボタン押下 → `startGeneration()` → 返ってきた`job_id`を画面の状態に保存 →
即座にポーリング画面へ遷移（**HTTPレスポンスを待つ間、画面をブロックしない**
——`startGeneration()`自体は数百ms程度で返る）。

### B.9 進捗表示

```ts
async function pollJob(jobId: string, onUpdate: (s: JobStatus) => void) {
  const status = await getJobStatus(jobId);
  onUpdate(status); // progress/current_step/messageをそのままUIへ
  if (status.status === "completed" || status.status === "failed") return status;
  await new Promise(r => setTimeout(r, 1500));
  return pollJob(jobId, onUpdate);
}
```

`current_step`の日本語ラベル対応表（表示用。バックエンドの`message`を
そのまま出してもよいが、ステップ名だけの見出しが欲しい場合用）:

| current_step | 表示例 |
|---|---|
| `null`（status=queued） | 準備中 |
| `requirements` | 要求を抽出中 |
| `tasks` | タスクに分解中 |
| `dependencies` | 依存関係を分析中 |
| `members` | メンバー情報を取得中 |
| `assignments` | 担当者を割り当て中 |
| `validation` | 検証中 |
| `finalize` | 最終結果を作成中 |

**タイマーでprogressを進めない。** 必ず`GET /api/jobs/{id}`から返ってきた
数値をそのまま使う。

### B.10 結果表示（タスク/依存関係/担当/検証）

各画面はPart A.3の型をそのまま使う。フィールドが無い/nullの場合は
「未設定」と表示する（架空の値を生成しない）。**担当割り当てロジックは
一切フロントに実装しない**——`FinalAssignment[]`をそのまま表示するだけ。

### B.11 Kanban

新しいパイプラインの`Task`型には`status`（TODO/DOING/DONE）フィールドが
**存在しない**。Projects/Jobs APIにタスクの状態を更新するエンドポイントも
**存在しない**。したがって:

- 新しいパイプラインのタスクをKanban的に動かしたい場合、**その状態は
  フロントエンドのメモリ内（またはlocalStorage）でしか保持できない**。
  リロードでリセットされる、または別ブラウザでは見えない、という制限を
  UI上に明記すること（例: 「この表示はこの端末でのみ保持されます」）。
- 既存のドラッグ&ドロップ実装（Sortable.js）自体は再利用してよいが、
  `updateTask(taskId, {status})`（旧`/api/tasks/{task_id}`）を呼ぶ実装は
  **新しいパイプラインのタスクIDには使わない**こと（別のデータ系統であり、
  `TASK-001`形式のIDを送っても旧システムには存在しないため`404`になる）。

### B.12 設定画面

変更不要。`/api/settings`は既存のまま（メモリ保持のみ、チーム非依存）。
これを「バックエンド設定として永続化されている」ように見せる文言があれば、
「この設定はサーバー再起動でリセットされます」等、正直な説明に直す。

### B.13 エラーハンドリング（日本語メッセージ対応表）

```ts
const ERROR_MESSAGES: Record<string, string> = {
  NETWORK_ERROR: "サーバーに接続できません。Backendが起動しているか確認してください。",
  UNAUTHENTICATED: "ログインが必要です。",
  SESSION_INVALID: "認証情報が無効です。再度ログインしてください。",
  PROJECT_NOT_FOUND: "プロジェクトが見つかりません。",
  JOB_NOT_FOUND: "ジョブが見つかりません。",
  MEMBERS_NOT_CONFIGURED: "メンバーが登録されていません。",
  DOCUMENT_NOT_SET: "仕様書が設定されていません。",
  JOB_NOT_COMPLETED: "タスク生成がまだ完了していません。",
};
function messageFor(code: string, fallback: string) {
  return ERROR_MESSAGES[code] ?? fallback ?? "タスク生成に失敗しました。";
}
```

`client.ts`のレスポンスインターセプタ（既存）は`{code, message}`を
そのままreject するので、`err.message`（バックエンドの日本語メッセージ）を
そのまま表示してもよいし、上記の対応表で画面ごとに定型文にしてもよい。
**スタックトレースを含む文字列を画面に出さない**（バックエンドはそもそも
返さない設計なので、フロント側で`JSON.stringify(err)`のような雑な表示を
しなければ問題ない）。

ネットワークエラー（バックエンド未起動等）は`client.ts`の
`err.response`が無いケースとして既に拾われている
（`{code: "NETWORK_ERROR", ...}`）。この場合は**デモデータに切り替えず**、
「サーバーに接続できません」+ 再試行ボタンを表示すること。

### B.14 ローディング/空状態

- ローディング中: 「メンバー情報を読み込んでいます...」等のテキストのみ。
  偽のカード/行を表示しない。
- 空状態（0件）: 「まだタスクが生成されていません」等、次のアクションへの
  導線（「タスクを生成する」ボタン等）と共に表示する。

---

## Part C: 動作確認（実バックエンドを使うこと）

`.env`の`VITE_API_BASE_URL`を実際に起動しているバックエンドに向けた上で:

1. バックエンド起動（`uvicorn backend.main:app --reload --port 8000`）、
   Ollama起動、`ALLOWED_ORIGINS`にフロントのオリジンが入っていることを確認。
2. フロントエンドを起動し、`/api/me`が401→ランディング画面になることを確認。
3. チーム作成 → ダッシュボードに遷移することを確認（Part A.1で無変更のはず）。
4. プロジェクト作成 → `project_id`が保存され、リロードしても同じプロジェクトが
   開くことを確認。
5. メンバー登録 → `GET`で登録した内容がそのまま返ってくることを確認。
6. 仕様書テキストを入力し「生成」→ `job_id`が即座に返り、画面がブロックしない
   ことを確認。
7. 進捗表示が`current_step`/`progress`/`message`の実際の値で変化することを
   （時間がかかる。1ステージ数十秒〜数分かかることがある）確認。
8. 完了後、タスク/依存関係/担当/検証の各画面が実データを表示することを確認。
9. わざとバックエンドを止めた状態でアプリを開き、「サーバーに接続できません」
   と表示され、デモデータにフォールバックしないことを確認。
10. わざと他チームのセッションで、保存済みの`project_id`/`job_id`にアクセスし、
    404になることを確認。

この確認は**実際のバックエンド**に対して行うこと。フィクスチャに対するテストは
「動作確認をした」ことにはならない。
