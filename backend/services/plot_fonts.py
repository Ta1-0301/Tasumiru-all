# backend/services/plot_fonts.py
"""
matplotlibで日本語ラベル(メンバー名・見出し等)が文字化け(tofu)しないよう、
実行環境にインストール済みの日本語フォントを探して設定する共通ヘルパー。

M1 iMac / Windows(RTX 3060 Ti)の両方で動かす想定のため、フォント名を
1つに決め打ちせず、両OSでよくある候補を順に探し、最初に見つかったものだけを
使う。どれも見つからない場合は何もしない（文字化けはするが描画自体は失敗しない
——グラフ生成自体をフォントの有無で止めたくないため）。
"""

from __future__ import annotations

import matplotlib.font_manager as fm

_JAPANESE_FONT_CANDIDATES = [
    # Windows
    "Yu Gothic", "Meiryo", "MS Gothic",
    # macOS
    "Hiragino Sans", "Hiragino Kaku Gothic Pro", "AppleGothic",
    # Linux（Ollama評価環境等）
    "Noto Sans CJK JP", "Noto Sans JP", "IPAexGothic", "TakaoGothic",
]


def configure_japanese_font() -> str | None:
    """利用可能な日本語フォントをmatplotlibのデフォルトフォントに設定する。

    見つかったフォント名を返す（見つからなければNone）。
    """
    import matplotlib.pyplot as plt  # 遅延import（pyplot未使用の呼び出し元に負荷をかけない）

    available = {f.name for f in fm.fontManager.ttflist}
    for candidate in _JAPANESE_FONT_CANDIDATES:
        if candidate in available:
            plt.rcParams["font.family"] = candidate
            plt.rcParams["axes.unicode_minus"] = False  # 一部の日本語フォントはマイナス記号が無いため
            return candidate
    return None
