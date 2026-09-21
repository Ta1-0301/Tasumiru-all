# backend/pipeline/assignment/__init__.py
"""
Phase 7: タスクへのメンバーアサインを推薦するエンジン。

**LLMだけで最終的な割り当てを決定させない。** 以下の3つを組み合わせる:

  1. 決定的スコアリング（deterministic scoring） -> scoring.py
  2. 有用な場合のLLMによる補足説明（LLM reasoning where useful） -> reasoning.py
  3. 明示的な制約（explicit constraints） -> filters.py

パイプライン:
  Step 1 候補者フィルタリング（ハード制約による除外）      -> filters.py
  Step 2 決定的スコアリング（設定可能な重み付け）          -> scoring.py
  Step 3 （任意）LLMによる上位候補の補足説明・曖昧性の指摘  -> reasoning.py
  出力   AssignmentResult（推薦） / FinalAssignment（人間の最終決定） -> schema.py

Step 3のLLMは`reasons`/`warnings`という説明文字列しか返せない構造になっており、
`recommended_member_id`やハード制約の判定結果を書き換える経路は存在しない。

AIの推薦(`AssignmentResult`)と人間の最終決定(`FinalAssignment`)は別のデータ
構造として保持し、マネージャーが推薦を上書きできる（override.py）。
"""
