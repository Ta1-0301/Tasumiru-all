# backend/pipeline/tasks/skill_evaluation.py
"""
Task内容とrequired_skillsの整合性チェック（LLM不使用・キーワードベースの軽量な検査）。

目的は完全な意味判定ではなく、「明らかにTaskの作業と関係ないスキルが付いている」
ケースを検出することだけ。例:

  - 「テスト報告書を作成する」 → ["Figma", "Tailwind CSS", "React"]   … 検出する
  - 「要件定義書を作成する」   → ["Figma"]                          … 検出する
  - 「Reactコンポーネントを実装する」 → ["React"]                   … 問題なし
  - 「セッショントークンをハッシュ化して保存する」→ ["Python", "PostgreSQL"]
        … 付いているスキル自体は不自然ではないが、セキュリティ系の作業なのに
          セキュリティ系のスキルが1つも無い、として別種の指摘をする

判定は保守的にする（疑わしいだけのものは検出しない）。スキルがTaskの文面に
そのまま書かれている場合は、作業の種類に関係なく常に妥当とみなす。

**required_skillsは一切書き換えない。** 検出結果は`ValidationIssue`として返し、
呼び出し側(tasks/runner.py)が既存の`apply_review_flags`でneeds_reviewの印を
付けるだけにする（「黙って修復しない・印を付ける」という既存方針に合わせる）。
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Set

from pydantic import BaseModel, Field

from backend.pipeline.tasks.schema import Task, ValidationIssue
from backend.services.skill_normalization import normalize_skill_name

SKILL_TASK_MISMATCH = "SKILL_TASK_MISMATCH"
SECURITY_SKILL_MISSING = "SECURITY_SKILL_MISSING"

# ── Taskの作業の種類（タイトル・説明・完了条件の文面から判定） ──
_ACTIVITY_KEYWORDS: Dict[str, List[str]] = {
    "document": ["報告書", "ドキュメント", "文書", "要件定義", "議事録", "マニュアル", "readme",
                 "仕様書", "手順書", "レポート", "資料", "記載", "まとめる"],
    "planning": ["計画", "スケジュール", "調整", "レビュー", "承認", "提出", "報告", "共有",
                 "ヒアリング", "打ち合わせ", "調査", "選定", "検討"],
    "test": ["テスト", "検証", "動作確認", "品質", "qa"],
    "security": ["セキュリティ", "暗号", "ハッシュ", "脆弱性", "トークン", "認証", "認可",
                 "権限", "パスワード", "平文", "改ざん"],
    "ui": ["ui", "画面", "デザイン", "フロントエンド", "コンポーネント", "ワイヤー", "レイアウト",
           "スタイル", "css", "表示", "ux", "モック", "プロトタイプ"],
    "db": ["データベース", "db", "スキーマ", "テーブル", "sql", "クエリ", "マイグレーション", "保存"],
    "api": ["api", "エンドポイント", "バックエンド", "サーバ", "ロジック", "実装", "処理", "機能"],
    "infra": ["デプロイ", "環境", "インフラ", "コンテナ", "docker", "ci", "cd", "クラウド", "サーバー構築"],
    "ml": ["機械学習", "モデル学習", "推論", "学習データ", "ml"],
}

# ── スキルの分類（正規化後のスキル名 → 分類）。ここに無いスキルは判定しない ──
_SKILL_DOMAINS: Dict[str, str] = {
    **{k: "design" for k in ["figma", "tailwind css", "tailwind", "adobe xd", "sketch", "photoshop", "illustrator"]},
    **{k: "frontend" for k in ["react", "typescript", "javascript", "html", "css", "html css", "vue", "nextjs",
                               "angular", "svelte", "フロントエンド", "フロントエンド開発"]},
    **{k: "backend" for k in ["python", "fastapi", "django", "flask", "go", "java", "spring", "nodejs", "ruby",
                              "rails", "php", "c#", "kotlin", "rest api", "バックエンド", "バックエンド開発"]},
    **{k: "db" for k in ["postgresql", "mysql", "sqlite", "sql", "sqlalchemy", "mongodb", "redis", "oracle"]},
    **{k: "infra" for k in ["aws", "docker", "terraform", "kubernetes", "gcp", "azure", "devops", "devopsaws",
                            "linux", "nginx", "github actions"]},
    **{k: "ml" for k in ["pytorch", "scikit learn", "tensorflow", "pandas", "numpy", "機械学習"]},
}

# セキュリティ系の作業に付いていれば「セキュリティのスキルがある」とみなす語（スキル名の部分一致）
_SECURITY_SKILL_HINTS = [
    "セキュリティ", "security", "secure", "暗号", "crypto", "encrypt", "認証", "認可", "auth", "oauth", "jwt",
    "ハッシュ", "hash", "bcrypt", "argon", "脆弱性", "vulnerab", "owasp", "tls", "ssl", "pki", "鍵管理",
]

# 作業の目的がセキュリティであることを示す語。タイトルにあれば目的とみなす
_SECURITY_PURPOSE_STRONG = ["セキュリティ", "暗号", "ハッシュ", "脆弱性", "平文", "改ざん", "秘匿", "漏洩"]
# 単独ではセキュリティ目的と言えないが、説明文の強い語と組み合わさると目的とみなす語
# （例: タイトル「セッショントークンの保存方法を分析する」+ 説明「平文で保存しないよう…」）
_SECURITY_PURPOSE_WEAK = ["トークン", "パスワード", "認証", "認可", "権限", "セッション", "秘密鍵", "個人情報"]

# 文面にある技術が前提としている言語など（例: SQLAlchemyを使う作業にPythonが付くのは自然）。
# キーの技術のどれかがTaskの文面に書かれていれば、値のスキルは不整合としない。
# （required_skills側の技術は根拠にしない。無関係に付いた技術が、さらに別の無関係なスキルを
#   正当化してしまうため。例: 文書作成Taskに付いたFastAPIが、Pythonを正当化しない）
_IMPLIED_BY: Dict[str, List[str]] = {
    "python": ["fastapi", "django", "flask", "sqlalchemy", "pytorch", "scikit learn", "scikit-learn",
               "pandas", "numpy", "tensorflow", "pydantic", "pytest"],
    "typescript": ["react", "vue", "nextjs", "next.js", "angular", "svelte"],
    "javascript": ["react", "vue", "nextjs", "next.js", "angular", "svelte", "nodejs", "node.js"],
    "html css": ["react", "vue", "tailwind", "画面", "ui"],
    "sql": ["postgresql", "mysql", "sqlite", "sqlalchemy"],
}

# 作業の種類ごとに、文面に明記されていなくても不自然ではないスキル分類。
# ここに無い組み合わせ（例: document → design）は、文面に明記されていない限り不整合とする。
_COMPATIBLE: Dict[str, Set[str]] = {
    "ui": {"design", "frontend"},
    "api": {"backend", "db", "frontend", "infra"},
    "db": {"db", "backend"},
    "infra": {"infra", "backend", "db"},
    "security": {"backend", "db", "infra"},
    "test": {"backend", "frontend", "db", "infra"},
    "ml": {"ml", "backend"},
    "document": set(),
    "planning": set(),
}
_IMPLEMENTATION_ACTIVITIES = {"ui", "api", "db", "infra", "ml"}


class SkillMismatch(BaseModel):
    task_id: str
    skill: str
    activities: List[str] = Field(default_factory=list)


class SkillEvaluation(BaseModel):
    """1回のTask生成結果に対する集計（実測・レポート用）"""

    total_tasks: int
    tasks_with_skills: int
    mismatched_tasks: int
    mismatch_rate: float
    mismatches: List[SkillMismatch] = Field(default_factory=list)
    security_skill_missing_tasks: List[str] = Field(default_factory=list)


# 「フロントエンド担当者と結合テストを行う」のように、作業ではなく人・役割を指す表現。
# 作業の種類の判定からは除く（実測で、テスト計画のTaskがUI系の作業と誤判定されたため）。
_ROLE_PHRASE_RE = re.compile(r"(フロントエンド|バックエンド|インフラ|デザイン|ui|qa)\s*(担当者|担当|チーム|側)")


def _text_of(task: Task) -> str:
    text = " ".join([task.title, task.description, *task.acceptance_criteria]).lower()
    return _ROLE_PHRASE_RE.sub(" ", text)


def _has_keyword(text: str, keyword: str) -> bool:
    # 英字だけのキーワード（ui, api, db, ci ...）は、単語の一部（"guide"の"ui"等）に反応しないようにする
    if re.fullmatch(r"[a-z]+", keyword):
        return re.search(rf"(?<![a-z]){keyword}(?![a-z])", text) is not None
    return keyword in text


def classify_activities(task: Task) -> Set[str]:
    text = _text_of(task)
    return {name for name, words in _ACTIVITY_KEYWORDS.items() if any(_has_keyword(text, w) for w in words)}


def _skill_domain(skill: str) -> Optional[str]:
    key = normalize_skill_name(skill)
    return _SKILL_DOMAINS.get(key) or _SKILL_DOMAINS.get(key.replace("/", " "))


def _mentioned(skill: str, text: str) -> bool:
    """スキル名（またはその正規化形）がTaskの文面に書かれているか"""
    raw = skill.strip().lower()
    if raw and raw in text:
        return True
    key = normalize_skill_name(skill)
    return bool(key) and key in text.replace("-", " ").replace("_", " ")


def find_unrelated_skills(task: Task) -> List[str]:
    """Taskの作業の種類から見て、明らかに関係ないと判断できるスキルを返す。

    - スキルがTaskの文面に書かれていれば常に妥当
    - 分類できないスキル（抽象的な日本語スキル等）や'unknown'は判定しない
    - 作業の種類が判定できないTaskは判定しない
    - いずれかの作業の種類から見て不自然でなければ妥当（保守的に判定する）
    """
    activities = classify_activities(task)
    if not activities:
        return []
    # 文書作成が主で、実装系の作業（UI/API/DB/インフラ/ML）を含まないTask
    # （例: テスト報告書・要件定義書の作成）は、文面に明記されていない技術スキルを付けない
    if "document" in activities and not activities & _IMPLEMENTATION_ACTIVITIES:
        activities = {"document"}
    text = _text_of(task)
    # 文面に書かれているスキルの分類（例: "FastAPI"が書かれていれば、同じ分類の"Python"も自然とみなす）
    mentioned_domains = {
        _skill_domain(s) for s in task.required_skills if s and _mentioned(s, text) and _skill_domain(s)
    }
    unrelated: List[str] = []
    for skill in task.required_skills:
        if not skill or skill.strip().lower() == "unknown" or _mentioned(skill, text):
            continue
        domain = _skill_domain(skill)
        if domain is None or domain in mentioned_domains or _is_implied(skill, text):
            continue
        if not any(domain in _COMPATIBLE.get(a, set()) for a in activities):
            unrelated.append(skill)
    return unrelated


def _is_implied(skill: str, text: str) -> bool:
    """Taskの文面に書かれている技術が、このスキルを前提としているか"""
    key = normalize_skill_name(skill).replace("/", " ")
    return any(_has_keyword(text, t) for t in _IMPLIED_BY.get(key, []))


def is_security_purpose(task: Task) -> bool:
    """作業の目的がセキュリティか。

    単語が1つ出てくるだけでは判定しない:
      - タイトルにセキュリティ目的の強い語がある（例:「暗号化ロジックを実装する」）、または
      - タイトルに弱い語（トークン・パスワード等）があり、説明文・完了条件に強い語がある
    「PostgreSQLにユーザー情報を保存する」のように保存・DB操作だけの作業は対象にしない。
    """
    title = _ROLE_PHRASE_RE.sub(" ", task.title.lower())
    body = _text_of(task)
    if any(k in title for k in _SECURITY_PURPOSE_STRONG):
        return True
    return any(k in title for k in _SECURITY_PURPOSE_WEAK) and any(k in body for k in _SECURITY_PURPOSE_STRONG)


def has_security_skill(skills: Iterable[str]) -> bool:
    joined = " ".join(normalize_skill_name(s) for s in skills if s)
    return any(h in joined for h in _SECURITY_SKILL_HINTS)


def lacks_security_skill(task: Task) -> bool:
    """作業の目的がセキュリティなのに、セキュリティ系のスキルが1つも無い（Pythonのみ等）"""
    if not is_security_purpose(task):
        return False
    skills = [s for s in task.required_skills if s and s.strip().lower() != "unknown"]
    if not skills:
        return False  # スキル未特定は別の問題（既存のTask品質チェックの対象）
    return not has_security_skill(skills)


def check_task_skill_consistency(tasks: Iterable[Task]) -> List[ValidationIssue]:
    """Task生成結果の整合性を検査し、needs_review用の`ValidationIssue`を返す（書き換えはしない）"""
    issues: List[ValidationIssue] = []
    for t in tasks:
        unrelated = find_unrelated_skills(t)
        if unrelated:
            issues.append(ValidationIssue(
                code=SKILL_TASK_MISMATCH,
                message=f"作業内容と関係の薄い可能性があるスキル: {', '.join(unrelated)}",
                task_ids=[t.id],
            ))
        if lacks_security_skill(t):
            issues.append(ValidationIssue(
                code=SECURITY_SKILL_MISSING,
                message="セキュリティに関わる作業ですが、セキュリティ系のスキルが指定されていません",
                task_ids=[t.id],
            ))
    return issues


def evaluate_task_skills(tasks: Iterable[Task]) -> SkillEvaluation:
    """実測用の集計（Task数・スキル付きTask数・明らかな不整合の件数と率）"""
    tasks = list(tasks)
    mismatches: List[SkillMismatch] = []
    mismatched_ids: Set[str] = set()
    for t in tasks:
        activities = sorted(classify_activities(t))
        for s in find_unrelated_skills(t):
            mismatches.append(SkillMismatch(task_id=t.id, skill=s, activities=activities))
            mismatched_ids.add(t.id)
    with_skills = sum(1 for t in tasks if any(s and s.strip().lower() != "unknown" for s in t.required_skills))
    return SkillEvaluation(
        total_tasks=len(tasks),
        tasks_with_skills=with_skills,
        mismatched_tasks=len(mismatched_ids),
        mismatch_rate=round(len(mismatched_ids) / len(tasks) * 100, 2) if tasks else 0.0,
        mismatches=mismatches,
        security_skill_missing_tasks=[t.id for t in tasks if lacks_security_skill(t)],
    )
