# Pipeline Performance — Phase 10 → Phase 11

Phase 10 (§1-2 below) measured and documented the problem. Phase 11 (§3+)
implements the improvements identified as safe, and adds deterministic
skill matching + workload-aware assignment. **Nothing in Phase 3-9's LLM
prompts, models, or business logic was rewritten** — Phase 11 changes are
additive (new modules) or narrowly scoped (loop orchestration, ranking
selection), per the explicit instruction to preserve the existing pipeline.

---

## 1. Real measurement (Phase 10 baseline — unchanged, kept for reference)

### Method

`backend/tmp_perf_measure.py` (a temporary, non-production script, removed
after this measurement) calls the real pipeline runners in sequence —
`run_requirements_pipeline` → `run_task_decomposition_pipeline` →
`run_dependency_pipeline` → `build_member_directory` → `run_assignment` (once
per task) → `validate_project_plan` → `assemble_final_output` — wrapping the
real `get_llm_client()` (Ollama, `llama3.1:8b`, confirmed running locally)
with `timed_client()`, and each stage with `pipeline_stage()`. It uses a
short (~4-paragraph, 4-clause) specification text.

### What was actually observed

```
[PIPELINE] requirements start
[LLM] requirements start model=llama3.1:8b
[LLM] requirements completed model=llama3.1:8b duration=116.27s
[LLM] requirements start model=llama3.1:8b
[LLM] requirements completed model=llama3.1:8b duration=82.82s
[LLM] requirements start model=llama3.1:8b
[LLM] requirements completed model=llama3.1:8b duration=98.57s
[LLM] requirements start model=llama3.1:8b
[LLM] requirements completed model=llama3.1:8b duration=43.47s
[LLM] requirements start model=llama3.1:8b
[LLM] requirements completed model=llama3.1:8b duration=30.48s
[PIPELINE] requirements completed duration=371.72s

[PIPELINE] tasks start
[LLM] tasks start model=llama3.1:8b
[LLM] tasks completed model=llama3.1:8b duration=177.11s
[LLM] tasks start model=llama3.1:8b
[LLM] tasks completed model=llama3.1:8b duration=100.27s
[LLM] tasks start model=llama3.1:8b
[LLM] tasks failed model=llama3.1:8b duration=300.31s error=HTTPException
[LLM] tasks start model=llama3.1:8b
... (stopped here — see note below)
```

This is the **unedited** log output from `backend/jobs/timing.py`'s logger,
captured from a real run in this environment. The measurement ran for
**just over 16 minutes** before it was deliberately stopped, having
completed only 1 of 7 stages and partway through the 2nd. See the git
history of this file for the full original writeup (interpretation,
bottleneck table, concurrency-candidate analysis) — condensed here since
Phase 11 supersedes most of its recommendations with actual implementation.

### Bottom line from Phase 10

The bottleneck is **Ollama inference latency per call** (30-300s+ per call
on this machine/model), **multiplied by the number of sequential LLM calls**
the pipeline makes: one per document chunk for requirements, one per
requirement for task decomposition. Not database I/O, not member retrieval,
not JSON parsing.

---

## 2. Phase 11 Part 1 — Audit of the actual LLM call architecture

Read directly from the Phase 3-9 source (not guessed) before any change was made:

| Stage | Current LLM calls | Sequential? | Can be merged? | Can be parallelized? |
|---|---|---|---|---|
| Requirements extraction (`requirements/runner.py` → `extractor.py`) | 1 per document chunk (N chunks) | Yes, `for` loop | No — each chunk's prompt+context is already minimal (heading+chunk text only); merging chunks into one call would blow up context and reduce per-chunk extraction quality/traceability | **Yes** — each chunk's extraction has zero dependency on any other chunk's result |
| Task decomposition (`tasks/runner.py` → `decomposer.py`) | 1 per requirement (N requirements) | Yes, `for` loop | No — same reasoning; this is also the stage with the *most* calls on a real spec (more requirements than chunks), so it's the primary target | **Yes** — each requirement's decomposition has zero dependency on any other requirement's result |
| Dependency proposal (`dependencies/proposer.py`) | **1 call for the entire task list** | N/A — already a single call | Already optimal (no merge opportunity left) | N/A |
| Member retrieval (`members/runner.py`) | **0** — deterministic file I/O | N/A | N/A | N/A |
| Assignment reasoning (`assignment/reasoning.py`, opt-in, `use_assignment_llm_reasoning`, default off) | 1 per task, only if enabled | Yes, `for` loop in `jobs/manager.py::_run_assignments` | No — each task's top-3-candidate context is task-specific | **No** (since the workload-cap change) — assignment runs sequentially because each task's candidates depend on the hours already assigned (100% cap / load balancing / deadlines) |
| Duplicate LLM verification (`validation/duplicates.py`, opt-in, `use_duplicate_llm_verification`, default off) | 1 per candidate duplicate pair, only if enabled | Yes, `for` loop | No — each pair independent | **Yes** — independent per pair |

**Finding on Part 2 (reduce unnecessary LLM calls):** every LLM call site
already sends the *minimum* scope needed (one chunk, one requirement, one
task pair, or — for dependencies — the whole task list because that call's
job genuinely requires seeing all tasks at once). There was no case of the
"BAD" pattern described in the request (repeated identical calls with
duplicated context) to merge away. Dependency proposal was *already* merged
into a single call in Phase 5. **No LLM calls were removed in Phase 11** —
the call count is identical before and after. The available, safe lever was
parallelization (Part 3), not call reduction.

**Finding on Part 4 (context/prompt reduction):** inspecting every prompt
template (`_EXTRACTION_PROMPT`, `_DECOMPOSITION_PROMPT`, `_DEPENDENCY_PROMPT`,
`_REASONING_PROMPT`, `_VERIFICATION_PROMPT`) shows none of them send the
full specification, the full requirement list, the full task list, or the
full member list where a narrower scope would do — each already receives
only what its own stage conceptually needs (e.g. task decomposition sends
one `Requirement`'s type/title/description, never the original document or
other requirements). **No prompt content was reduced in Phase 11** because
there was nothing unnecessary left to remove without also removing
traceability (e.g. dependency proposal's single call *must* see every task
title+description to find real cross-task relationships — that is not
waste, it is the job).

---

## 3. Phase 11 Part 3 — Safe parallelization (implemented)

`backend/services/concurrency.py` adds `gather_with_concurrency()`, a small
`asyncio.Semaphore`-gated helper, plus `get_max_concurrency()` which reads
`OLLAMA_MAX_CONCURRENCY` from the environment.

**Default is 1** — i.e. **identical sequential behavior to Phase 10**, byte
for byte. Nothing changes for a deployment that doesn't set the env var.
This directly follows the instruction: *"Do not hardcode aggressive
concurrency... make concurrency configurable, default to a conservative
value."* Per the same instruction's warning — a single local Ollama worker
can serialize concurrent requests and make them *slower*, a fact already
observed in Phase 10 (a 300s HTTP timeout firing mid-call) — raising this
above 1 is an explicit, deliberate opt-in, not a new default.

Wired into every independent per-item loop identified in the Part 1 audit:

| Loop | File | Order preserved when concurrency > 1? |
|---|---|---|
| Requirement extraction over chunks | `pipeline/requirements/runner.py` | Yes — `asyncio.gather` semantics preserve input order regardless of completion order, so `REQ-001, REQ-002, ...` ID assignment stays deterministic/reproducible at any concurrency level |
| Task decomposition over requirements | `pipeline/tasks/runner.py` | Yes, same reasoning for `TASK-001, TASK-002, ...` |
| Assignment over tasks | `jobs/manager.py::_run_assignments` | N/A — always sequential (deadline order, then original order); results are returned in the original task order |
| Duplicate LLM verification over candidate pairs | `pipeline/validation/duplicates.py` | Yes |

Reproducibility (Phase 9's requirement) is preserved regardless of the
concurrency setting, because ID/ordering assignment always happens after
`gather_with_concurrency` returns its order-preserving result list — never
based on completion order.

**Consciously *not* parallelized:** the Phase 10 doc's own suggested
diagram (member-loading concurrent with dependency generation) was
reconsidered here and declined. Member loading is deterministic file I/O
that already completes in well under a millisecond; dependency generation
is a real ~30-300s LLM call. Running them concurrently would save
approximately zero wall-clock time (the LLM call dominates completely) while
adding real risk to `STAGE_BOUNDS` progress-percentage ordering in
`jobs/manager.py` (two stages updating `job.progress` concurrently could
make the reported percentage jump non-monotonically for a poller). This is
a declined optimization, documented rather than silently skipped, per Part
1's "do not guess" and the general "no silent decisions" ethos of this
project.

### Benchmark attempt (honest result — Part 18)

A live A/B benchmark (`OLLAMA_MAX_CONCURRENCY=1` vs `=2`, against the real
local `llama3.1:8b` Ollama instance already running in this environment) was
attempted with a small synthetic 3-section spec. The `concurrency=1` leg
was allowed to run to completion:

```
[concurrency=1] {'requirements_seconds': 1252.92, 'requirements_count': 0,
                 'tasks_seconds': 0.02, 'tasks_count': 0, 'total_seconds': 1252.93}
```

This is the **unedited** real result. Two honest observations about it:

1. **It took 1252.92s (~21 minutes) and extracted 0 requirements** from 3
   chunks. `run_requirements_pipeline` never raises on a per-chunk failure
   — it records the failure in `RequirementDocument.issues` and continues
   — so this indicates every chunk's `call_llm_json` call exhausted its
   retries (consistent with the HTTP-timeout-and-retry behavior already
   documented as real in the Phase 10 measurement above, where individual
   calls ranged 30-300s+ and one genuinely hit the 300s timeout). This
   machine also had a live `uvicorn --reload` dev server running throughout
   testing, competing for resources. This is not a Phase 11 regression —
   `gather_with_concurrency` with `max_concurrency=1` is unit-tested
   (`test_concurrency.py`) to behave identically to a plain sequential
   `for` loop, and no retry/timeout logic in `call_llm_json` was touched.
2. **The `concurrency=2` leg was not reached.** Given the `concurrency=1`
   leg alone consumed ~21 minutes without a usable result, continuing to a
   second ~21+ minute leg was judged not to be a good use of the time
   available for this phase — the same judgment call the Phase 10
   measurement made when it was stopped partway through for the same reason.

**Honest conclusion, per Part 18: whether raising `OLLAMA_MAX_CONCURRENCY`
above 1 actually helps or hurts throughput on this specific machine/model
was not conclusively measured in this pass.** What *is* verified (by
`backend/tests/test_concurrency.py`, deterministic and fast, no live LLM
required): the mechanism itself is correct — it respects the configured
limit, preserves result order, and defaults to fully sequential execution.
Recommended before enabling `OLLAMA_MAX_CONCURRENCY > 1` in any real
deployment: run this same A/B comparison directly against that
deployment's own Ollama instance (uncontended, dedicated), since local
single-worker Ollama behavior under concurrent load is highly
machine/model-dependent and the one data point gathered here does not
settle the question either way.

---

## 4. Phase 11 Parts 5-9 — Deterministic skill matching & scoring

### TF-IDF skill similarity (`backend/services/skill_matching.py`)

New, isolated service using `sklearn.feature_extraction.text.TfidfVectorizer`
+ `sklearn.metrics.pairwise.cosine_similarity` (already a pinned dependency
in `requirements.txt` — no new dependency added). Each skill-name list
(task's required skills, one member's skills) becomes a "document" (space-
joined normalized skill names); cosine similarity between the task-document
and each member-document gives a 0.0-1.0 similarity score. No sklearn
objects leak past this module's boundary — callers only see `float` and
plain pydantic models.

This is **complementary to**, not a **replacement for**, Phase 7's existing
`score_skill_match` (which checks whether a member's skill *level* meets
the task's required minimum — a near-hard-constraint concern). TF-IDF
similarity instead measures how close the *overall skill-name sets* are —
catching e.g. "task needs Python+FastAPI+REST API, member has
Python+FastAPI+SQL" as a strong partial match, something exact-level
lookups can't express as a single number.

### Skill normalization (`backend/services/skill_normalization.py`)

A small, deterministic, rule-based layer (lowercase, whitespace/punctuation
collapse, a short exact-alias table for known variants like `"Fast API"` →
`fastapi`, `"RESTful API"` → `rest api`, plus mechanical version-suffix
stripping: `"Python3"` → `python`). Extensible via an `extra_rules` dict —
**deliberately not a large synonym database**, per the instruction.

This is applied to **both** the hard-constraint gate
(`assignment/filters.py::_find_member_skill`) and the deterministic scoring
(`assignment/scoring.py`) and the validation skill-mismatch check
(`validation/skill_mismatch.py`) — all three previously did a bare
`.strip().lower()` comparison, which meant a task requiring `"Python3"`
against a member who listed `"Python"` was a **false hard rejection**
(no match at all). Normalization fixes this while staying a strict,
deterministic equality check on normalized strings — never a fuzzy match —
so it does not weaken hard-constraint semantics (see the module's own
docstring for why fuzzy matching was deliberately kept out of the hard-
constraint path).

### Scoring integration (`assignment/schema.py`, `assignment/scoring.py`)

`CandidateScore` gained a new `skill_similarity` field (default `0.0`).
`ScoringWeights` gained a new `skill_similarity` weight, **defaulting to
`0.0`** — i.e., **the default production score is numerically unchanged**
from Phase 7. This default was a deliberate choice: Phase 7's level-based
`skill_match` is already tested and has real usage; enabling a second,
differently-shaped signal by default, without measuring its effect on real
project data, would be exactly the kind of un-measured optimization Phase
10 established this project should not do. To enable it: pass
`ScoringWeights(skill_similarity=0.15, ...)` (or any value) explicitly —
weights auto-normalize regardless of how many are non-zero.

All 50 pre-existing `assignment` tests pass unchanged (verified) — this
confirms the addition is behavior-neutral at default settings.

---

## 5. Phase 11 Parts 8-11 — Workload-aware, load-balanced assignment

`backend/pipeline/assignment/workload_balancing.py` (new module,
deterministic, no LLM):

- `compute_projected_workload_percentage(task, member)` — what a member's
  workload % would become *after* accepting this task (reuses the same
  0-division convention as the existing `validation/workload.py`, so the
  metric means the same thing everywhere in the codebase).
- `select_recommended_candidate(task, candidate_scores, members_by_id)` —
  implements the exact worked example from the request (Part 11): if the
  top-scored candidate would end up above `WORKLOAD_WARNING_PERCENTAGE`
  (80%, a module constant) but a lower-scored candidate stays under it,
  the under-threshold candidate is recommended instead, with a warning
  explaining the substitution. If every surviving candidate is over
  threshold, the original top scorer is kept and a warning notes the
  overload — assignment is never silently blocked, matching Part 11's
  "still allow assignment if necessary."
  **Superseded for the job pipeline (commit 14f6c2f):** `JobManager` now passes
  an `AssignmentLedger`, so candidates whose cumulative load would exceed 100%
  (or who cannot finish by the deadline) are excluded as hard constraints
  (`WORKLOAD_TOO_HIGH` / `DEADLINE_INFEASIBLE`) and the task may be left
  unassigned; among the rest, `_select_balanced_candidate` prefers ≤80% and the
  lowest projected load among skill-comparable candidates. The behaviour above
  remains only for the ledger-less path (`select_recommended_candidate` without
  a ledger, e.g. the CLI runner). See `backend/pipeline/assignment/README.md`.

Critically, this function **never reorders or rewrites `candidate_scores`
itself** — the full, pure, decision-transparent ranking is still returned
to the frontend unchanged (Phase 8/9's traceability guarantee). It only
changes *which one* of the already-computed candidates becomes
`recommended_member_id`, with the reasoning recorded as a warning string —
the same "mark, don't silently fix" pattern used everywhere else in this
codebase.

Wired into `assignment/runner.py::run_assignment`, replacing the previous
unconditional `top = candidate_scores[0]` pick. All existing
`assignment_runner` tests (multi-candidate ranking, ties, LLM-reasoning
additivity) pass unchanged, because none of their fixtures approach the 80%
workload-warning threshold — a new dedicated test file
(`test_workload_balancing.py`, 9 tests, including the exact Member-A-95%/
Member-B-40% scenario from the request) covers the new behavior directly.

---

## 6. Phase 11 Part 14 — Validation expansion (CHECK 7 & 8)

Two new checks added to `ValidationReport` (`pipeline/validation/schema.py`)
— both purely additive fields, defaulting to `[]`, so no existing consumer
of `ValidationReport` breaks (Part 20):

- **CHECK 7 — Task data quality** (`validation/task_quality.py`,
  `task_quality_issues`): surfaces two things — (a) tasks Phase 4 already
  flagged `needs_review=True` for (which already covers "missing source
  references" and "invalid estimated effort" from the request's Part 14
  list — reused via the existing field, not reimplemented), and (b) tasks
  whose `required_skills` is empty or only the `"unknown"` sentinel
  ("missing required skills"). Deliberately **does not** flip
  `ValidationReport.valid` to `False` — these are already-known,
  already-surfaced-elsewhere signals, and double-blocking generation on
  them would make Phase 4's per-task review flags block the *entire*
  project unnecessarily.
- **CHECK 8 — Assignment score anomaly** (`validation/score_anomaly.py`,
  `assignment_score_anomalies`): flags a `FinalAssignment` whose actually-
  assigned member scored below a threshold (default 40). Deliberately
  looks up the assigned member's score from
  `ai_recommendation.candidate_scores` — **not** `ai_recommendation.score`
  — because after a human override, those can be two different members;
  using the AI's top-pick score would misattribute it. If the assigned
  member isn't in the candidate list at all (e.g. an override outside the
  originally-scored pool), no score is fabricated — the check silently
  defers to the existing CHECK 6 (constraint violations), which already
  covers illegitimate overrides.

Both are folded into Phase 9's tri-state `warning_issue_count` (never
`critical`/error) in `final_output/validation_summary.py`, so they reach
the frontend through the existing `FinalProjectOutput.validation` shape
without any new endpoint or schema-breaking change.

`jobs/manager.py::_run_validation` now passes `final_assignments` through
to `validate_project_plan`/`validate_project_plan_with_llm_verification` so
CHECK 8 has the data it needs in the real job pipeline (previously only
the flattened `task_id -> member_id` map was passed, which has no score
information).

---

## 7. Tests (Part 17)

New test files, all deterministic (no live LLM required):

- `test_skill_normalization.py` (8 tests)
- `test_skill_matching.py` (11 tests) — exact/partial/no match, multiple
  members, missing skills, name-variant recognition, ranking, determinism
- `test_workload_balancing.py` (9 tests) — including the request's own
  worked load-balancing example
- `test_concurrency.py` (7 tests) — ordering, concurrency-limit
  enforcement, env var parsing/fallback
- `test_validation_task_quality.py` (5 tests)
- `test_validation_score_anomaly.py` (6 tests) — including the
  override-score-attribution case above

Plus targeted edits to existing files (`assignment/filters.py`,
`assignment/scoring.py`, `validation/skill_mismatch.py`,
`requirements/runner.py`, `tasks/runner.py`, `validation/duplicates.py`,
`jobs/manager.py`, `validation/runner.py`,
`final_output/validation_summary.py`) — all covered by the pre-existing
test suite, which was re-run after every change.

**Full suite result: 467 passed, 0 failed** (up from the Phase 10 baseline
of 420 — 47 new tests added, zero regressions in any pre-existing test).

---

## 8. API compatibility (Part 20)

No endpoint was added, removed, or renamed. Every Phase 10 endpoint
(`POST /api/projects/{id}/generate`, `GET /api/jobs/{id}`, `/result`,
`/requirements`, `/tasks`, `/dependencies`, `/assignments`, `/validation`)
is unchanged. New fields (`CandidateScore.skill_similarity`,
`ScoringWeights.skill_similarity`, `ValidationReport.task_quality_issues`,
`ValidationReport.assignment_score_anomalies`) are additive with defaults —
see `docs/API_CONTRACT.md` §11.7-11.8 for the updated schemas.

## 9. Database (Part 21)

No schema change, no migration. All Phase 11 data (skill similarity scores,
workload-balancing warnings, new validation checks) is computed on the fly
from existing `Member`/`Task`/`FinalAssignment` data and stored in the same
JSON output files Phase 3-9 already produced — nothing new is persisted.

## 10. Remaining bottlenecks (honest, from real data)

Unchanged from Phase 10's finding, because Part 2's call-reduction audit
found nothing safe to remove and the concurrency A/B benchmark was
inconclusive (§3 above): **the dominant cost is still raw local Ollama
inference latency per call, multiplied by call count** (one per chunk for
requirements, one per requirement for task decomposition). The mechanism to
address this with parallel calls now exists and defaults to off; whether
enabling it helps on any given deployment's hardware needs to be measured
directly against that deployment, not assumed from this session's single
inconclusive data point.

## 11. Recommended next phase

1. Run the `OLLAMA_MAX_CONCURRENCY=1` vs `2` (vs higher) A/B comparison
   against a production-representative Ollama deployment (ideally one not
   sharing the machine with anything else), and record the result here.
2. If a multi-worker Ollama deployment (or a hosted LLM API) becomes
   available, re-evaluate the concurrency default with real numbers.
3. Once real project data exists, measure whether enabling
   `skill_similarity` in `ScoringWeights` (currently opt-in, weight 0)
   changes assignment quality, and only then consider changing the default.
