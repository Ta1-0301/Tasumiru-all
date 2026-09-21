# legacy results

This directory holds the raw evaluation output from Phase 1 of the evaluation
work, produced by the (now removed) flat `backend/evaluation/*.py` modules
before the Phase 2 restructure.

- Scores in these files use the **old 0-2 scale**, not the current 0-5 rubric
  defined in `backend/evaluation/schemas/rubric.py`.
- Field names (`traceability_score`, `coverage_score`, ...) do not match the
  current `ScoreDetail`/`TaskEvaluation`/`DocumentEvaluation` schemas.
- They are kept only as historical evidence of real measured runs (never
  fabricated) referenced by `TASK_EXTRACTION_EVALUATION.md`. They are not
  read by any current code.
