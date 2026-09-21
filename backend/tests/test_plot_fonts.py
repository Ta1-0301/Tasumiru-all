# backend/tests/test_plot_fonts.py
"""backend/services/plot_fonts.py の単体テスト。"""

from backend.services.plot_fonts import configure_japanese_font


def test_configure_japanese_font_does_not_raise():
    """フォントが見つかる/見つからないいずれの環境でも例外を出さないこと。
    （CI環境等、日本語フォントが無い場合もグラフ生成自体は止めない方針）"""
    result = configure_japanese_font()
    assert result is None or isinstance(result, str)
