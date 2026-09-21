# backend/pipeline/requirements/

Phase 3: 仕様書を構造化要求（`requirements.json`）に変換するパイプライン。

```
Specification Document
    ↓  (backend.services.parser.parse_document() — 既存。ここでは呼ばない/変更しない)
Document Parser
    ↓
LLM Requirement Extraction   (extractor.py)
    ↓
Requirement Validation       (validator.py)
    ↓
requirements.json            (runner.py が output/ に保存)
```

**このフェーズではタスクへの分解は行わない。** `backend/services/pipeline/`
（Specification → Task、既存のタスク分解パイプライン）とは完全に独立していて、
一切呼び出さない・変更しない。

## モジュール構成

| ファイル | 役割 |
|---|---|
| `schema.py` | `Requirement`/`RequirementDocument`等のデータ構造。9種類の`type`、`origin`(explicit/inferred)、`confidence`(0-1)、`source_reference`(document_id/page/section/paragraph/source_text) |
| `extractor.py` | LLM Requirement Extraction。チャンクごとに逐次実行。`BaseLLMClient`のみに依存し、プロバイダー固有のロジックを含まない |
| `validator.py` | Requirement Validation。重複・出典欠落・矛盾（簡易ヒューリスティック）・空記述・不正ID を検出する決定的な処理 |
| `runner.py` | 全体のオーケストレーターとCLIエントリポイント |

## 実行方法

```bash
source .venv/bin/activate
export LLM_PROVIDER=ollama OLLAMA_BASE_URL=http://localhost:11434   # 既存のプロバイダー抽象化
python -m backend.pipeline.requirements.runner path/to/spec.txt spec_a_simple
```

モデルは`LLM_PROVIDER`(`ollama`/`anthropic`/`openai`)で切り替えられる
（`backend.services.llm.get_llm_client()`、既存の抽象化をそのまま使用）。
このパッケージのコード（`extractor.py`/`validator.py`/`runner.py`）は
Ollama固有の処理を一切含まない。

## 出典トレーサビリティ

`source_reference.source_text`は常に
`backend.services.pipeline.structure.decompose_document()`
（既存の文書構造抽出、読み取り専用で再利用）が切り出した実在のチャンクの
全文であり、LLMが自由記述したものではない。これにより出典を
LLMが捏造することを構造的に防いでいる。`page`は仕様書がプレーンテキストで
ページの概念を持たないため常に`None`（無い情報を捏造しない）。

## 既知の限界

- `validator.check_contradictions`は字面ベースの簡易ヒューリスティック
  （対になる語のペアが同じ話題に出現するかを見るだけ）であり、
  言い回しが異なる論理的矛盾は検出できない。
- チャンクごとに逐次抽出するため、`system_purpose`/`target_user`のような
  文書全体にまたがる情報が、それが最も明確に述べられているチャンク以外では
  拾えない場合がある。
