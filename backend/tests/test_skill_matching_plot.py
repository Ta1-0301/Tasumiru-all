# backend/tests/test_skill_matching_plot.py
"""backend/services/skill_matching_plot.py の単体テスト。

完全にローカル計算(TF-IDF Cosine Similarity)のみで、LLM/外部APIは
一切呼ばない。matplotlibの描画結果自体(ピクセル)は検証せず、
「既存のmatch_task_to_members()の結果通りにファイルが生成されること」
だけを確認する（描画内容の細部はこのテストの関心事ではない）。
"""

from backend.services.skill_matching_plot import _SAMPLE_MEMBERS, build_and_plot


def test_build_and_plot_creates_png_file(tmp_path):
    output_path = tmp_path / "skill_similarity.png"

    result_path = build_and_plot(["Python", "FastAPI"], _SAMPLE_MEMBERS, output_path=output_path)

    assert result_path == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0


def test_build_and_plot_with_no_required_skills_still_produces_a_file(tmp_path):
    """既存のmatch_task_to_members()は必要スキル無しなら全員1.0を返す
    （skill_matching.pyの既存仕様、ここでは変更しない）。その場合でも
    プロット自体は正常に生成されることを確認する。"""
    output_path = tmp_path / "skill_similarity_empty.png"

    result_path = build_and_plot([], _SAMPLE_MEMBERS, output_path=output_path)

    assert result_path.exists()
