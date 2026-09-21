# backend/services/skill_matching_plot.py
"""
既存のTF-IDF + Cosine Similarityスキルマッチング(backend/services/skill_matching.py、
無変更)の結果を可視化する（バックエンドのみ、matplotlib）。

LLM/外部APIは一切呼ばない。TfidfVectorizerもCosine Similarity計算も完全に
ローカルな決定的計算のみで、Ollama等のネットワーク呼び出しは発生しない。

使い方（CLIから直接実行する場合）:
    python -m backend.services.skill_matching_plot "Python,FastAPI,REST API" \\
        --members-json backend/pipeline/members/output/team_xxx.members.json \\
        [--output out.png]

    --members-jsonを省略した場合は、動作確認用の組み込みサンプルメンバーを使う。
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

import matplotlib

matplotlib.use("Agg")  # ヘッドレス環境向け。plt.show()は使わずファイル保存のみ行う
import matplotlib.pyplot as plt

from backend.pipeline.members.runner import load_member_directory
from backend.pipeline.members.schema import Availability, Member, Skill
from backend.services.plot_fonts import configure_japanese_font
from backend.services.skill_matching import MemberSkillSimilarity, match_task_to_members

configure_japanese_font()

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output" / "skill_cosine_similarity.png"

_SAMPLE_MEMBERS = [
    Member(id="M-001", name="山田太郎",
           skills=[Skill(skill="Python", level=5), Skill(skill="FastAPI", level=4), Skill(skill="SQL", level=3)],
           availability=Availability(available_hours_per_week=40)),
    Member(id="M-002", name="佐藤花子",
           skills=[Skill(skill="React", level=5), Skill(skill="TypeScript", level=4)],
           availability=Availability(available_hours_per_week=40)),
    Member(id="M-003", name="鈴木一郎",
           skills=[Skill(skill="Python", level=3), Skill(skill="REST API", level=4), Skill(skill="Docker", level=3)],
           availability=Availability(available_hours_per_week=30)),
]


def plot_skill_similarity(
    required_skills: List[str],
    results: List[MemberSkillSimilarity],
    members_by_id: dict,
    *,
    output_path: Path = DEFAULT_OUTPUT,
) -> Path:
    """1件のタスクの必要スキルと各メンバーのTF-IDF Cosine Similarityを棒グラフにして保存する。"""
    labels = [f"{members_by_id[r.member_id].name}\n({r.member_id})" for r in results]
    values = [r.skill_similarity for r in results]

    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 1.2), 4.5))
    ax.bar(range(len(labels)), values, color="#2f855a")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels)
    ax.set_ylim(0.0, 1.0)
    ax.set_ylabel("TF-IDF Cosine Similarity")
    ax.set_title(f"Task-Member Skill Similarity\nrequired_skills: {', '.join(required_skills)}")
    fig.tight_layout()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def build_and_plot(
    required_skills: List[str],
    members: List[Member],
    *,
    output_path: Path = DEFAULT_OUTPUT,
) -> Path:
    """既存のmatch_task_to_members()（無変更）を呼び、結果をプロットする。"""
    results = match_task_to_members(required_skills, members)
    members_by_id = {m.id: m for m in members}
    return plot_skill_similarity(required_skills, results, members_by_id, output_path=output_path)


def _main() -> None:
    parser = argparse.ArgumentParser(description="タスクの必要スキルとメンバーのTF-IDF Cosine Similarityをプロットする")
    parser.add_argument("required_skills", help="カンマ区切りの必要スキル一覧（例: 'Python,FastAPI'）")
    parser.add_argument("--members-json", type=Path, default=None, help="members.jsonのパス（省略時は組み込みサンプル）")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    required_skills = [s.strip() for s in args.required_skills.split(",") if s.strip()]
    members = (
        load_member_directory(args.members_json).members if args.members_json else _SAMPLE_MEMBERS
    )

    output_path = build_and_plot(required_skills, members, output_path=args.output)
    print(f"保存先: {output_path}")


if __name__ == "__main__":
    _main()
