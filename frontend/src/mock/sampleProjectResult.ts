// src/mock/sampleProjectResult.ts
//
// ============================================================================
// ⚠️ SAMPLE DATA — 実際のバックエンド出力ではありません (NOT REAL BACKEND OUTPUT)
// ============================================================================
//
// このファイルは実際に稼働しているバックエンドの出力ではない。
// 2026-08-24 時点でチームから共有された API_CONTRACT.md によれば、
// Requirements → Tasks → Dependencies → Members → Assignments →
// Validation → Final JSON のパイプライン（Phase 3〜9）は
// `backend/pipeline/*` に実装済みだが、HTTPエンドポイントとしては
// 一切公開されていない（CLIスクリプト経由でのみ実行可能）。
//
// このリポジトリ・このマシン上には実際のパイプライン出力JSONファイルが
// 存在しなかった（Desktop/Documents/Downloads/ホームディレクトリを
// 検索して確認済み）。そのため、バックエンド担当者との合意のもと、
// FinalProjectOutput スキーマ（API_CONTRACT.md §11.9、
// src/types/pipeline.ts で型定義したもの）に厳密に準拠した
// 「サンプルフィクスチャ」をここに手書きしている。
//
// 厳守した制約:
//   - スキーマに存在しないフィールドは一切追加していない
//   - スキーマに存在するフィールドの型・必須/任意は変更していない
//   - このデータを実在のAIの推論結果であるかのように偽装していない
//     （UI側は projectService.IS_SAMPLE_DATA を見て、必ず
//     「サンプルデータを表示中」のバナーを表示する）
//
// 実際の `GET /api/project/final`（仮称、未実装）が用意され次第、
// src/services/projectService.ts の実装だけを axios 呼び出しに差し替えれば
// よく、この型・各画面のコンポーネントは変更不要な設計にしている。
import type { FinalProjectOutput } from "../types/pipeline";

export const SAMPLE_PROJECT_RESULT: FinalProjectOutput = {
  project: {
    document_id: "DOC-SAMPLE-001",
    name: "サンプルプロジェクト（社内タスク管理システム）",
    exported_at: "2026-08-20",
  },

  requirements: [
    {
      id: "REQ-001",
      type: "functional",
      title: "ユーザーログイン機能",
      description:
        "利用者はメールアドレスとパスワードでシステムにログインできること。",
      priority: "high",
      origin: "explicit",
      source_reference: {
        document_id: "DOC-SAMPLE-001",
        page: 2,
        section: "2.1 認証",
        paragraph: "1",
        source_text: "利用者はメールアドレスとパスワードでログインできるものとする。",
      },
      confidence: 0.94,
    },
    {
      id: "REQ-002",
      type: "functional",
      title: "タスク一覧表示機能",
      description: "ログイン後、自分に割り当てられたタスクの一覧を表示すること。",
      priority: "medium",
      origin: "explicit",
      source_reference: {
        document_id: "DOC-SAMPLE-001",
        page: 3,
        section: "2.2 タスク管理",
        paragraph: "1",
        source_text: "ログイン後、自分のタスク一覧を表示する画面を用意すること。",
      },
      confidence: 0.9,
    },
    {
      id: "REQ-003",
      type: "non_functional",
      title: "レスポンス性能",
      description: "一覧表示は3秒以内に完了すること。",
      priority: "high",
      // origin: inferred の例 — 仕様書に明記はないがAIが文脈から推測した要件
      origin: "inferred",
      source_reference: null,
      confidence: 0.62,
    },
    {
      id: "REQ-004",
      type: "constraint",
      title: "利用ブラウザの制約",
      description: "モダンブラウザ（Chrome/Edge/Safari最新版）のみサポートすること。",
      priority: "low",
      origin: "explicit",
      source_reference: {
        document_id: "DOC-SAMPLE-001",
        page: 1,
        section: "1.3 動作環境",
        paragraph: null,
        source_text: "対応ブラウザはChrome, Edge, Safariの最新版とする。",
      },
      confidence: 0.88,
    },
  ],

  tasks: [
    {
      id: "TASK-001",
      requirement_ids: ["REQ-001"],
      title: "ログインAPIの実装",
      description: "メールアドレス/パスワードによる認証APIをFastAPIで実装する。",
      priority: "high",
      estimated_hours: 8,
      required_skills: ["Python", "FastAPI"],
      acceptance_criteria: [
        "正しい認証情報でログインできる",
        "誤った認証情報の場合は401を返す",
      ],
      source_reference: {
        document_id: "DOC-SAMPLE-001",
        page: 2,
        section: "2.1 認証",
        paragraph: "1",
        source_text: "利用者はメールアドレスとパスワードでログインできるものとする。",
      },
      confidence: 0.91,
      needs_review: false,
      review_reasons: [],
    },
    {
      id: "TASK-002",
      requirement_ids: ["REQ-001"],
      title: "ログイン画面のUI実装",
      description: "メールアドレス/パスワード入力フォームと送信処理を実装する。",
      priority: "medium",
      estimated_hours: 5,
      required_skills: ["TypeScript", "HTML", "CSS"],
      acceptance_criteria: ["入力エラー時にメッセージを表示する"],
      source_reference: {
        document_id: "DOC-SAMPLE-001",
        page: 2,
        section: "2.1 認証",
        paragraph: "2",
        source_text: "ログイン画面には入力エラー時のメッセージ表示を行うこと。",
      },
      confidence: 0.87,
      needs_review: false,
      review_reasons: [],
    },
    {
      id: "TASK-003",
      requirement_ids: ["REQ-002"],
      title: "タスク一覧APIの実装",
      description: "ログイン中ユーザーに割り当てられたタスクを返すAPIを実装する。",
      priority: "medium",
      estimated_hours: 6,
      required_skills: ["Python", "FastAPI"],
      acceptance_criteria: ["自分に割り当てられたタスクのみ返す"],
      source_reference: {
        document_id: "DOC-SAMPLE-001",
        page: 3,
        section: "2.2 タスク管理",
        paragraph: "1",
        source_text: "ログイン後、自分のタスク一覧を表示する画面を用意すること。",
      },
      confidence: 0.85,
      needs_review: false,
      review_reasons: [],
    },
    {
      id: "TASK-004",
      requirement_ids: ["REQ-002", "REQ-003"],
      title: "タスク一覧画面のパフォーマンス最適化",
      description: "一覧表示のレスポンスタイムを3秒以内に収めるためのキャッシュ導入を検討する。",
      priority: "high",
      estimated_hours: 10,
      required_skills: ["Python", "パフォーマンスチューニング"],
      acceptance_criteria: ["1000件のタスクでも3秒以内に表示完了する"],
      // REQ-003 が inferred（推測要件）由来のため、このタスク自体も
      // 人によるレビューが必要としてマークされている（実データをそのまま反映）
      source_reference: null,
      confidence: 0.55,
      needs_review: true,
      review_reasons: [
        "元要件(REQ-003)がAIによる推測要件であり、仕様書に明記がないため",
      ],
    },
    {
      id: "TASK-005",
      requirement_ids: ["REQ-004"],
      title: "対応ブラウザの動作確認",
      description: "Chrome/Edge/Safari最新版での表示崩れ・動作不良がないか確認する。",
      priority: "low",
      estimated_hours: 4,
      required_skills: ["QA", "手動テスト"],
      acceptance_criteria: ["3ブラウザ全てで主要画面が正しく表示される"],
      source_reference: {
        document_id: "DOC-SAMPLE-001",
        page: 1,
        section: "1.3 動作環境",
        paragraph: null,
        source_text: "対応ブラウザはChrome, Edge, Safariの最新版とする。",
      },
      confidence: 0.8,
      needs_review: false,
      review_reasons: [],
    },
  ],

  dependencies: [
    {
      from_task_id: "TASK-001",
      to_task_id: "TASK-002",
      type: "required",
      reason: "ログインAPIが未完成だとログイン画面の動作確認ができないため。",
      confidence: 0.93,
    },
    {
      from_task_id: "TASK-001",
      to_task_id: "TASK-003",
      type: "required",
      reason: "認証機構が無いとログイン中ユーザーを特定できないため。",
      confidence: 0.9,
    },
    {
      from_task_id: "TASK-003",
      to_task_id: "TASK-004",
      type: "recommended",
      reason: "一覧APIの実装が固まってからでないと最適化の効果測定ができないため。",
      confidence: 0.72,
    },
    {
      from_task_id: "TASK-002",
      to_task_id: "TASK-005",
      type: "optional",
      reason: "ログイン画面のUIが完成してからブラウザ確認を行うと手戻りが少ない。",
      confidence: 0.58,
    },
  ],

  members: [
    {
      id: "MEM-001",
      name: "田中 一郎",
      skills: [
        { skill: "Python", level: 4, experience_years: 5 },
        { skill: "FastAPI", level: 4, experience_years: 3 },
      ],
      experience_years: 5,
      availability: {
        available_hours_per_week: 30,
        working_days: ["月", "火", "水", "木", "金"],
        current_assigned_hours: 26,
      },
      constraints: [
        { type: "max_hours_per_week", value: null, max_hours: 30 },
      ],
    },
    {
      id: "MEM-002",
      name: "佐藤 花子",
      skills: [
        { skill: "TypeScript", level: 5, experience_years: 4 },
        { skill: "HTML", level: 5, experience_years: 6 },
        { skill: "CSS", level: 4, experience_years: 6 },
      ],
      experience_years: 6,
      availability: {
        available_hours_per_week: 25,
        working_days: ["月", "水", "木", "金"],
        current_assigned_hours: 10,
      },
      constraints: [
        { type: "day_unavailable", value: "火", max_hours: null },
      ],
    },
    {
      id: "MEM-003",
      name: "鈴木 次郎",
      // 経験値が未取得のメンバーの例 — 存在しない値を捏造せず null のまま表示する
      skills: [{ skill: "QA", level: 2, experience_years: null }],
      experience_years: null,
      availability: {
        available_hours_per_week: 20,
        working_days: ["月", "火", "水", "木", "金"],
        current_assigned_hours: 4,
      },
      constraints: [],
    },
  ],

  assignments: [
    {
      task_id: "TASK-001",
      assigned_member_id: "MEM-001",
      decided_by: "ai",
      overridden: false,
      override_reason: null,
      ai_recommendation: {
        task_id: "TASK-001",
        recommended_member_id: "MEM-001",
        score: 88,
        candidate_scores: [
          {
            member_id: "MEM-001",
            skill_match: 95,
            workload_score: 70,
            experience_score: 90,
            availability_score: 80,
            score: 88,
          },
          {
            member_id: "MEM-003",
            skill_match: 20,
            workload_score: 95,
            experience_score: 30,
            availability_score: 95,
            score: 42,
          },
        ],
        rejected_candidates: [
          { member_id: "MEM-002", reasons: ["Python/FastAPIスキルなし"] },
        ],
        reasons: [
          "Python/FastAPIの経験が最も豊富で、要求スキルと完全一致",
          "現在の稼働率は高いが、まだ許容範囲内",
        ],
        warnings: ["稼働時間が上限(30h)に近づいている"],
        status: "recommended",
      },
    },
    {
      task_id: "TASK-002",
      assigned_member_id: "MEM-002",
      decided_by: "human",
      overridden: true,
      override_reason: "AI推奨は佐藤さんだったが、繁忙期のため作業配分を人手で調整した。",
      ai_recommendation: {
        task_id: "TASK-002",
        recommended_member_id: "MEM-002",
        score: 91,
        candidate_scores: [
          {
            member_id: "MEM-002",
            skill_match: 98,
            workload_score: 85,
            experience_score: 88,
            availability_score: 90,
            score: 91,
          },
        ],
        rejected_candidates: [],
        reasons: ["TypeScript/HTML/CSSの全てで高いスキルレベルを保持"],
        warnings: [],
        status: "recommended",
      },
    },
    {
      task_id: "TASK-003",
      assigned_member_id: "MEM-001",
      decided_by: "ai",
      overridden: false,
      override_reason: null,
      ai_recommendation: {
        task_id: "TASK-003",
        recommended_member_id: "MEM-001",
        score: 80,
        candidate_scores: [
          {
            member_id: "MEM-001",
            skill_match: 90,
            workload_score: 55,
            experience_score: 90,
            availability_score: 60,
            score: 80,
          },
        ],
        rejected_candidates: [
          { member_id: "MEM-003", reasons: ["Pythonスキルなし"] },
          { member_id: "MEM-002", reasons: ["Pythonスキルなし"] },
        ],
        reasons: ["唯一Python/FastAPIの両方に高いスキルレベルを持つ"],
        warnings: ["稼働時間が上限(30h)を超過する可能性がある"],
        status: "recommended",
      },
    },
    {
      task_id: "TASK-004",
      // 適任者がいない例 — 存在しない担当を捏造せず null のまま表示する
      assigned_member_id: null,
      decided_by: "ai",
      overridden: false,
      override_reason: null,
      ai_recommendation: {
        task_id: "TASK-004",
        recommended_member_id: null,
        score: null,
        candidate_scores: [
          {
            member_id: "MEM-001",
            skill_match: 40,
            workload_score: 10,
            experience_score: 60,
            availability_score: 10,
            score: 31,
          },
        ],
        rejected_candidates: [
          {
            member_id: "MEM-001",
            reasons: ["稼働時間の上限(30h)を超過するため割り当て不可"],
          },
          {
            member_id: "MEM-002",
            reasons: ["「パフォーマンスチューニング」スキルなし"],
          },
          {
            member_id: "MEM-003",
            reasons: ["「パフォーマンスチューニング」スキルなし"],
          },
        ],
        reasons: [],
        warnings: ["要求スキルを満たす候補者が見つかりませんでした"],
        status: "no_suitable_member",
      },
    },
    {
      task_id: "TASK-005",
      assigned_member_id: "MEM-003",
      decided_by: "ai",
      overridden: false,
      override_reason: null,
      ai_recommendation: {
        task_id: "TASK-005",
        recommended_member_id: "MEM-003",
        score: 68,
        candidate_scores: [
          {
            member_id: "MEM-003",
            skill_match: 75,
            workload_score: 90,
            experience_score: 20,
            availability_score: 88,
            score: 68,
          },
        ],
        rejected_candidates: [],
        reasons: ["QAスキルを保持し、稼働に十分な空きがある唯一の候補"],
        warnings: [],
        status: "recommended",
      },
    },
  ],

  validation: {
    status: "error",
    critical_issue_count: 2,
    warning_issue_count: 3,
    traceability_errors: [
      {
        code: "TASK_WITHOUT_ASSIGNMENT",
        message: "TASK-004 は適任者が見つからず、担当者未確定のままです。",
        task_id: "TASK-004",
      },
      {
        code: "LOW_CONFIDENCE_REQUIREMENT",
        message: "REQ-003 は推測要件（origin=inferred）であり、人による確認が必要です。",
        task_id: null,
      },
    ],
    report: {
      valid: false,
      missing_requirements: [],
      duplicate_tasks: [
        {
          task_ids: ["TASK-001", "TASK-003"],
          similarity: 0.71,
          method: "hybrid",
          reason:
            "両タスクとも「ログイン中ユーザーの特定」に関する処理を含んでおり、内容が一部重複している可能性があります。",
        },
      ],
      dependency_errors: [
        {
          code: "MISSING_INTERMEDIATE_TASK",
          message:
            "TASK-004はTASK-003に依存していますが、TASK-002からTASK-004への直接的な要件的関連が確認できません。依存関係の見直しを推奨します。",
          task_ids: ["TASK-002", "TASK-004"],
        },
      ],
      workload_warnings: [
        {
          member_id: "MEM-001",
          assigned_hours: 8 + 6,
          available_hours: 30,
          remaining_capacity: 30 - 26,
          workload_percentage: 93,
          code: "NEAR_CAPACITY",
          message: "田中一郎さんの稼働率が93%に達しており、上限に近づいています。",
        },
      ],
      skill_mismatches: [
        {
          task_id: "TASK-005",
          member_id: "MEM-003",
          skill: "QA",
          required_level: 3,
          member_level: 2,
          message:
            "鈴木次郎さんのQAスキルレベル(2)が要求レベル(3)を下回っています。",
        },
      ],
      constraint_violations: [
        {
          task_id: "TASK-002",
          member_id: "MEM-002",
          code: "DAY_UNAVAILABLE_CONFLICT",
          message:
            "佐藤花子さんは火曜日が稼働不可ですが、タスクの想定スケジュールに火曜日が含まれています。",
        },
      ],
      workload_summaries: [
        {
          member_id: "MEM-001",
          assigned_hours: 14,
          available_hours: 30,
          remaining_capacity: 4,
          workload_percentage: 93,
        },
        {
          member_id: "MEM-002",
          assigned_hours: 5,
          available_hours: 25,
          remaining_capacity: 20,
          workload_percentage: 20,
        },
        {
          member_id: "MEM-003",
          assigned_hours: 4,
          available_hours: 20,
          remaining_capacity: 16,
          workload_percentage: 20,
        },
      ],
      generated_at: "2026-08-20T09:30:00+00:00",
    },
  },

  metadata: {
    generated_at: "2026-08-20T09:30:00+00:00",
    pipeline_version: "0.9.0-sample",
    model: "ollama/llama3.1",
    model_version: null,
    prompt_versions: {
      requirements_extraction: "v1",
      task_decomposition: "v1",
      dependency_proposal: "v1",
      assignment_reasoning: "v1",
    },
    document_id: "DOC-SAMPLE-001",
    models_by_phase: {},
  },
};
