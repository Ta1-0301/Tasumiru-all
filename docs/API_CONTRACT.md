# タスみる API Contract (as-implemented)

**This document describes the CURRENT implementation only.** It does not propose
new endpoints, new fields, or a redesigned pipeline. Every field, status code,
and behavior below was verified directly against the source code and the live
FastAPI OpenAPI schema. Sections up through §13 were originally verified on
2026-08-24 (Phase 9); §3.9, §12A, §14, and the Phase 10 rows in §11 were added
and verified on 2026-08-26 (Phase 10) after implementing the job-based
pipeline API described there. Where the code and a plausible expectation
diverge, that divergence is called out explicitly rather than smoothed over.

The generated OpenAPI document is saved at [`docs/openapi.json`](openapi.json)
(produced by `app.openapi()`, not hand-written — see §13).

## 0. The single most important fact for the frontend team

**Four routers are mounted on the FastAPI app**, confirmed by reading
`backend/main.py` and by grepping the whole `backend/` tree for
`include_router`/`APIRouter(`:

```python
app.include_router(tasks.router)      # backend/routers/tasks.py     — prefix /api
app.include_router(auth_router)       # backend/auth/router.py       — prefix /api
app.include_router(projects.router)   # backend/routers/projects.py  — prefix /api  (Phase 10, NEW)
app.include_router(jobs.router)       # backend/routers/jobs.py      — prefix /api  (Phase 10, NEW)
```

As of Phase 9, the **Requirements → Tasks → Dependencies → Members →
Assignments → Validation → Final JSON pipeline** existed only as plain Python
modules under `backend/pipeline/*`, with no HTTP surface at all. **Phase 10
changes this**: `backend/routers/projects.py` and `backend/routers/jobs.py`
now expose that entire pipeline through a job-based, asynchronous HTTP API
(§3.9) — the frontend starts a job, polls its status, and reads the result
and every intermediate stage's data once ready. **No existing Phase 3-9
business logic was rewritten to make this possible** — the new routers and
`backend/jobs/*` only orchestrate and instrument the existing
`backend.pipeline.*.runner` functions; see §3.9 for exactly how.

The **CLI entry points** (`python -m backend.pipeline.<name>.runner`)
described in §4/§6/§7/§8/§9 below **still work unchanged** and remain a
second, independent way to invoke the same underlying functions (useful for
local development/debugging without going through HTTP) — see §12A.

What *is* live today, and what the frontend can integrate against right now:

- **Team / Member (auth) / Session** — `backend/auth/router.py` (§3, §10)
- **Projects & the full pipeline as an async job** — `backend/routers/projects.py`,
  `backend/routers/jobs.py` (§3.9) — **NEW in Phase 10**
- **Specification upload → task generation (legacy, single global project)** —
  `backend/routers/tasks.py` (§3.5 / "Tasks" §5) — unchanged, still separate
  from the Phase 10 job API (see §3.9's note on why these are not merged)
- **Settings** — `backend/routers/tasks.py`
- **Health check** — `backend/main.py`

---

## 1. Frontend integration information

| Item | Value |
|---|---|
| Backend base URL | Not hardcoded anywhere in the backend; it's whatever host/port the frontend's Vite dev server is configured to call (e.g. `http://localhost:8000`). Nothing in `backend/` sets a fixed port; that's an ASGI-server launch concern (e.g. `uvicorn backend.main:app --port 8000`), not part of the app. |
| CORS | `CORSMiddleware` in `backend/main.py`, `allow_origins` = `ALLOWED_ORIGINS` env var (comma-separated), default `http://localhost:5173`. `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`. **The frontend's exact dev-server origin must be listed in `ALLOWED_ORIGINS` — because `allow_credentials=True`, FastAPI/Starlette will not accept a wildcard `*` origin, so the origin must be enumerated exactly (scheme+host+port).** |
| Authentication mechanism | HttpOnly session cookie (`tasumiru_session`), *not* a bearer token / `Authorization` header. See §10. As of Phase 10, this mechanism protects the auth-router endpoints (§3) **and every Projects/Jobs endpoint (§3.9)** — a job/project created by one team is invisible (404) to every other team, same as `require_same_team` elsewhere. **It is still not applied to the legacy task-generation/upload/settings endpoints in `backend/routers/tasks.py`** (§5.A), which remain completely unauthenticated and unscoped — unchanged in Phase 10, see the final report. |
| Required headers | For JSON endpoints: `Content-Type: application/json`. For the upload endpoint: `Content-Type: multipart/form-data` (set automatically by the browser/Axios when sending a `FormData` body — do not set it manually with `axios`, or the multipart boundary will be wrong). |
| Cookie requirements | Axios must be configured with `withCredentials: true` (equivalent to fetch's `credentials: 'include'`) on every request, or the session cookie will not be sent/stored. The cookie's `Secure` flag is controlled by `COOKIE_SECURE` (env var, default `false`) and `SameSite` by `COOKIE_SAMESITE` (default `lax`). In local dev over plain HTTP, keep `COOKIE_SECURE=false`; if the frontend and backend are ever on different top-level sites, `SameSite=lax` cookies will not be sent cross-site on top-level navigations and `SameSite=none`+`Secure=true`+HTTPS would be required — this is not currently configured for that case. |
| Content-Type (responses) | `application/json` for every endpoint except `POST /api/sessions/revoke` (204, no body) and `DELETE /api/members/{member_id}` (204, no body). |
| File upload format | `multipart/form-data` to `POST /api/tasks/generate`, fields: `file` (binary, optional), `text_content` (string, optional), `members_json` (string, **required** — a JSON-encoded array, see §5). Accepted file extensions, from `backend/services/parser.py`: `.pdf`, `.docx`, `.txt`, `.md`. Anything else raises `400 FILE_PARSE_ERROR`. |
| Maximum upload size | `MAX_UPLOAD_SIZE` env var, default `20 * 1024 * 1024` = **20 MB** (`backend/services/parser.py`). Enforced *after* the full file has already been read into memory (`await file.read()`), not by a streaming limit — a large-but-under-some-ASGI-default upload will still be fully buffered before the 20 MB check runs. There is no FastAPI/Starlette-level request size limit configured on top of this. |
| Extracted-text cap | `MAX_EXTRACT_CHARS` env var, default `5000`. Text beyond this is silently truncated with an appended Japanese notice string before being sent to the LLM — this is a real behavior, not a bug, but the frontend should know a very long spec will be cut. |

---

## 2. Error response shape (applies to every endpoint below)

Every `HTTPException` raised anywhere in the backend (`backend/routers/tasks.py`,
`backend/auth/router.py`, `backend/auth/dependencies.py`,
`backend/auth/middleware.py`, `backend/services/llm.py`) uses the same
`detail` shape:

```json
{
  "detail": {
    "code": "SOME_MACHINE_READABLE_CODE",
    "message": "人が読める日本語のメッセージ"
  }
}
```

FastAPI's own automatic request-validation errors (HTTP 422, e.g. a required
form field missing or a body failing Pydantic validation) use FastAPI's
standard shape instead, **not** the `{code, message}` shape above:

```json
{
  "detail": [
    { "loc": ["body", "field_name"], "msg": "Field required", "type": "missing" }
  ]
}
```

The frontend must handle **both** shapes when parsing error responses.

---

## 3. Endpoints — Team, Member, Authentication/Session

Source: `backend/auth/router.py`, `backend/auth/schemas.py`,
`backend/auth/dependencies.py`, `backend/auth/middleware.py`.

Architecture: **Team → Member → Device Session.** No email/password, no
global user account, no OAuth. A member belongs to a team purely through a
possession-based session cookie. `SESSION_COOKIE_NAME = "tasumiru_session"`.

### 3.1 `POST /api/teams` — create a team

- **Auth required:** No (this is how a team first comes into existence).
- **Path params:** none. **Query params:** none.
- **Request headers:** `Content-Type: application/json`.
- **Request body** (`TeamCreateRequest`):
  ```json
  { "name": "string, 1-255 chars", "admin_display_name": "string, 1-100 chars" }
  ```
- **Response:** `201 Created`, body `MeResponse`:
  ```json
  { "team": { "id": "string", "name": "string" },
    "member": { "id": "string", "display_name": "string", "is_admin": true } }
  ```
- **Side effect:** sets the `tasumiru_session` HttpOnly cookie for the newly
  created admin member (30-day expiry, `path=/`).
- **Errors:** `422` (validation, e.g. empty name).
- **Example request:**
  ```bash
  curl -i -c cookies.txt -X POST http://localhost:8000/api/teams \
    -H "Content-Type: application/json" \
    -d '{"name":"開発チームA","admin_display_name":"山田太郎"}'
  ```
- **Example response:**
  ```json
  {"team":{"id":"b2f...","name":"開発チームA"},
   "member":{"id":"a91...","display_name":"山田太郎","is_admin":true}}
  ```

### 3.2 `POST /api/teams/{team_id}/invitations` — create an invitation

- **Auth required:** Yes — admin member of that team (`get_current_admin` +
  `require_same_team`).
- **Path params:** `team_id` (string).
- **Request body** (`InvitationCreateRequest`, all optional):
  ```json
  { "expires_in_hours": 24 }
  ```
  (`1`–`720`, default `24`.)
- **Response:** `201 Created`, body `InvitationCreateResponse`:
  ```json
  { "token": "raw token string — shown only in this response", "expires_at": "2026-08-25T12:00:00+00:00" }
  ```
- **Errors:**
  - `401 UNAUTHENTICATED` — no session cookie.
  - `401 SESSION_INVALID` — cookie present but session invalid/expired/revoked.
  - `403 FORBIDDEN` — authenticated but not an admin.
  - `404 NOT_FOUND` — authenticated admin belongs to a *different* team than
    `{team_id}` (deliberately returned as 404, not 403, to avoid confirming
    the other team's existence — see `require_same_team`).
  - `422` — invalid `expires_in_hours`.

### 3.3 `POST /api/invitations/{token}/join` — join a team via invitation

- **Auth required:** No (this is how a new member joins).
- **Path params:** `token` (string, the raw invitation token from §3.2).
- **Request body** (`JoinTeamRequest`): `{ "display_name": "string, 1-100 chars" }`
- **Response:** `201 Created`, body `MeResponse` (same shape as §3.1).
- **Side effect:** sets the `tasumiru_session` cookie for the new member.
- **Rate limiting:** `rate_limit_invitation_join` — **10 attempts per IP per
  60-second sliding window**, in-memory only (not shared across multiple
  backend processes/instances). Exceeding it returns `429`.
- **Errors:**
  - `404 INVITATION_NOT_FOUND`
  - `410 INVITATION_REVOKED`
  - `410 INVITATION_EXPIRED`
  - `404 TEAM_NOT_FOUND` (invitation's team was deleted)
  - `429 RATE_LIMITED`
  - `422` — invalid `display_name`.

### 3.4 `POST /api/sessions/refresh` — rotate the current session

- **Auth required:** Yes (`get_current_member`).
- **Response:** `200 OK`, body `SessionRefreshResponse`: `{ "expires_at": "..." }`.
- **Side effect:** the old session is revoked and a new cookie is set
  (rotation, not just extension).
- **Errors:** `401 UNAUTHENTICATED` / `401 SESSION_INVALID`.

### 3.5 `POST /api/sessions/revoke` — log out

- **Auth required:** No dependency is declared on this route — it reads
  whatever cookie is present (if any) and revokes that session; it is a
  no-op if there is no cookie. Effectively idempotent logout.
- **Response:** `204 No Content`, empty body.
- **Side effect:** deletes the `tasumiru_session` cookie
  (`response.delete_cookie`) and marks the underlying session row revoked in
  the DB if one existed.

### 3.6 `GET /api/me` — current member + team

- **Auth required:** Yes (`get_current_member`).
- **Response:** `200 OK`, body `MeResponse` (same shape as §3.1).
- **Errors:** `401 UNAUTHENTICATED` / `401 SESSION_INVALID` /
  `404 TEAM_NOT_FOUND` (orphaned member — team deleted after member created).

### 3.7 `GET /api/teams/{team_id}/members` — list team members

- **Auth required:** Yes, any authenticated member of that team.
- **Path params:** `team_id`.
- **Response:** `200 OK`, body `List[TeamMemberResponse]`:
  ```json
  [{ "id": "string", "display_name": "string", "is_admin": false }]
  ```
- **Errors:** `401`/`404 NOT_FOUND` (cross-team access, same 404-not-403
  pattern as §3.2) / `422` (malformed path — unlikely for a plain string).

### 3.8 `DELETE /api/members/{member_id}` — remove a team member

- **Auth required:** Yes, admin of that member's team.
- **Path params:** `member_id`.
- **Response:** `204 No Content`.
- **Errors:**
  - `400 CANNOT_REMOVE_SELF` — an admin cannot delete themself this way
    (must use session revoke instead).
  - `404 MEMBER_NOT_FOUND` — either genuinely missing, or belongs to another
    team (same information-hiding pattern).
  - `400 LAST_ADMIN` — refuses to delete a team's only remaining admin.

---

## 3.9 Endpoints — Projects & Jobs (Phase 10, job-based pipeline execution)

Source: `backend/routers/projects.py`, `backend/routers/jobs.py`,
`backend/jobs/manager.py`, `backend/models/project.py`, `backend/models/job.py`,
`backend/models/job_schemas.py`.

**Why this exists:** a real integration test showed the legacy
`POST /api/tasks/generate` (§5.A) running for 5+ minutes with the frontend's
HTTP connection blocked the whole time, waiting on one synchronous request.
The Phase 3-9 pipeline (§4-§9) makes multiple sequential LLM calls per stage
and has no HTTP surface at all before Phase 10. This section replaces
"one blocking request" with **start a job → poll its status → fetch the
result once done**, and is now the way to run the *actual* Requirements →
Tasks → Dependencies → Members → Assignments → Validation → Final JSON
pipeline over HTTP (§4-§9's schemas are what these endpoints return — see
the cross-references there).

**How it reuses existing code, concretely:** every stage in
`backend/jobs/manager.py` calls the exact same function the CLI calls —
`run_requirements_pipeline`, `run_task_decomposition_pipeline`,
`run_dependency_pipeline`, `load_member_directory`/`build_member_directory`,
`run_assignment` (once per task, then `accept_recommendation`),
`validate_project_plan`, `assemble_final_output` — then calls that
function's own `save_*` function to persist the result to that phase's own
`output/` directory (the same one the CLI writes to). No prompt, model call,
scoring function, or validation rule was reimplemented for the API layer;
`backend/jobs/adapters.py`'s `task_to_assignment_task()` is the only new
"logic," and it's a pure data-shape adapter (Phase 4's `Task.required_skills`
has no skill levels; it reuses Phase 8's existing
`skill_mismatch.default_required_skills()` rather than inventing a new rule
— see that file's docstring).

**Auth on every endpoint below:** `get_current_member` (§3's session
cookie). A project/job belongs to the team that created it
(`ProjectModel.team_id` / `JobModel.team_id`); any request for a
project/job belonging to a *different* team gets `404` (`PROJECT_NOT_FOUND`
/ `JOB_NOT_FOUND`) — same information-hiding pattern as `require_same_team`
elsewhere in this codebase, never a `403` that would confirm the resource
exists.

### 3.9.1 `POST /api/projects` — create a project

- **Request body** (`ProjectCreateRequest`, both optional):
  ```json
  { "name": "string, optional", "document_text": "string, optional — can be set later via /generate" }
  ```
- **Response:** `201 Created`, body `ProjectResponse`:
  ```json
  { "id": "uuid", "team_id": "uuid", "name": "string | null",
    "has_document": false, "has_members": false,
    "created_at": "2026-08-26T...", "updated_at": "2026-08-26T..." }
  ```
- **Errors:** `401 UNAUTHENTICATED` / `401 SESSION_INVALID`, `422`.

### 3.9.2 `GET /api/projects/{project_id}` — get project info

- **Response:** `200 OK`, `ProjectResponse` (same shape as above).
- **Errors:** `401`/`404 PROJECT_NOT_FOUND` (missing or wrong team).

### 3.9.3 `PUT /api/projects/{project_id}/members` — set the project's structured member directory

This is Phase 6 (§7), finally reachable over HTTP. It calls
`build_member_directory(team_id, records)` — the exact existing function —
**unchanged**. Skill levels/availability/constraints are never invented:
whatever is missing from the request is simply absent from the result, and
`build_member_directory`'s own validation issues (invalid skill level,
negative hours, etc. — §7/§11.6) are returned as part of the response.

- **Request body** (`SetMembersRequest`):
  ```json
  { "members": [ { "id": "M-001", "name": "山田太郎",
      "skills": [{"skill": "Python", "level": 5, "experience_years": 3}],
      "availability": {"available_hours_per_week": 40, "working_days": ["Monday"], "current_assigned_hours": 0},
      "constraints": [] } ] }
  ```
  (Each element is passed through verbatim to Phase 6 — see §11.6 for the
  full `Member` shape and what's optional.)
- **Response:** `200 OK`, body is the resulting `MemberDirectory` (§11.6) —
  including any `issues` Phase 6's validator found (the request still
  succeeds; problems are reported, not silently dropped or blocked).
- **Errors:** `401`/`404 PROJECT_NOT_FOUND`, `422`.

### 3.9.4 `GET /api/projects/{project_id}/members` — get the project's member directory

- **Response:** `200 OK`, `MemberDirectory` (§11.6), re-validated on read
  (calls `load_member_directory`, not a raw file passthrough).
- **Errors:** `401`/`404 PROJECT_NOT_FOUND` / `404 MEMBERS_NOT_CONFIGURED`
  (members were never set for this project).

### 3.9.5 `POST /api/projects/{project_id}/generate` — start a generation job

This is the endpoint from the desired flow at the top of this project's
Phase 10 brief:

```
POST /api/projects/{project_id}/generate
        ↓
{ "job_id": "...", "status": "queued" }
```

- **Request body** (`GenerateRequest`, all optional):
  ```json
  {
    "document_text": "string, optional — if given, overwrites the project's stored spec text before running",
    "use_assignment_llm_reasoning": false,
    "use_duplicate_llm_verification": false
  }
  ```
  The two `use_*` flags correspond to genuinely-optional existing features:
  Phase 7 Step 3 ("Optionally provide the top candidates to the LLM" — see
  `backend.pipeline.assignment.reasoning`) and Phase 8 CHECK 2's optional
  LLM duplicate-verification pass (`validate_project_plan_with_llm_verification`).
  **Both default to `false`** — i.e. the job runs the fully-deterministic
  path unless explicitly asked otherwise, which is also the fastest path
  (see `docs/PIPELINE_PERFORMANCE.md` for why every extra LLM call matters
  at ~30-180s each on this model).
- **Preconditions (checked synchronously, before any job is created):**
  the project must have non-empty `document_text` (either already stored,
  or provided in this request) and a member directory already set via
  §3.9.3. Missing either returns `400` **without** creating a job:
  - `400 DOCUMENT_NOT_SET`
  - `400 MEMBERS_NOT_CONFIGURED`
- **Response:** `202 Accepted` (chosen over `200` because this is
  specifically "accepted for asynchronous processing"), body
  `GenerateResponse`:
  ```json
  { "job_id": "uuid", "status": "queued" }
  ```
- **What happens next:** the handler creates a `JobModel` row
  (`status="queued"`) and calls `asyncio.create_task(...)` to run the
  pipeline in the background, then returns immediately — **the HTTP
  connection is never held open for pipeline execution.**
- **Errors:** `401`/`404 PROJECT_NOT_FOUND`, `400 DOCUMENT_NOT_SET`,
  `400 MEMBERS_NOT_CONFIGURED`, `422`.

### 3.9.6 `GET /api/jobs/{job_id}` — poll job status

```
GET /api/jobs/{job_id}
        ↓
{ "job_id": "...", "status": "running", "progress": 55,
  "current_step": "dependencies", "message": "依存関係を分析しています..." }
```

- **Response:** `200 OK`, body `JobStatusResponse`:
  ```json
  {
    "job_id": "uuid", "project_id": "uuid", "team_id": "uuid",
    "status": "queued|running|completed|failed|cancelled",
    "progress": 0,
    "current_step": "requirements|tasks|dependencies|members|assignments|validation|finalize|null",
    "message": "string | null",
    "created_at": "...", "started_at": "... | null", "completed_at": "... | null",
    "error": { "code": "string", "message": "string" } | null
  }
  ```
  `error` is populated **only** when `status == "failed"`; it is the same
  `{code, message}` shape as every other error in this API (§2).
  `current_step`/`message`/`progress` are the exact fields the brief's
  desired-flow example asks for — see §14 for how the frontend should
  consume them, and `docs/PIPELINE_PERFORMANCE.md` §"progress" for how the
  percentages are derived (structural stage weighting, not a fake timer —
  see Phase 10's STEP 5 requirement).
- **Errors:** `401`/`404 JOB_NOT_FOUND`.

### 3.9.7 `GET /api/jobs/{job_id}/result` — get the completed Phase 9 result

- **Response if `status == "completed"`:** `200 OK`, body `FinalProjectOutput`
  (§11.9) — the actual Phase 9 object, loaded via
  `backend.pipeline.final_output.runner.load_final_output()` (re-validated
  against its schema on every read, not a raw file passthrough).
- **Response if not yet completed:** `409 Conflict`,
  `{"detail": {"code": "JOB_NOT_COMPLETED", "message": "..."}}`.
- **Response if the job failed:** `409 Conflict`,
  `{"detail": {"code": "<job.error_code>", "message": "<job.error_message>"}}`
  (the job's own recorded error, not a generic message).
- **Errors:** `401`/`404 JOB_NOT_FOUND`, `500 RESULT_MISSING` (should not
  happen in practice — a completed job always has a `result_path`).

### 3.9.8 `GET /api/jobs/{job_id}/error` — get failure detail

- **Response if `status == "failed"`:** `200 OK`, `{"code": "...", "message": "..."}`
  (same info as `JobStatusResponse.error`, as a standalone endpoint per the
  brief's STEP 6, which lists this as optional if the status response
  already includes it — it does, but this endpoint is implemented too for
  a stable, dedicated URL to poll/link to).
- **Response otherwise:** `404`, `{"detail": {"code": "NO_ERROR", ...}}`.
- **Errors:** `401`/`404 JOB_NOT_FOUND`.

### 3.9.9-3.9.13 Stage data endpoints (STEP 7: expose every intermediate result)

Each of these reads the JSON file that stage's own `save_*` function
already wrote (via `backend.jobs.manager`), re-validates it against that
phase's real schema (§11.3-§11.8), and returns it as-is:

| Endpoint | Returns | Schema |
|---|---|---|
| `GET /api/jobs/{job_id}/requirements` | `RequirementDocument` | §11.3 |
| `GET /api/jobs/{job_id}/tasks` | `TaskDocument` | §11.4 |
| `GET /api/jobs/{job_id}/dependencies` | `DependencyDocument` | §11.5 |
| `GET /api/jobs/{job_id}/assignments` | `List[FinalAssignment]` | §11.7 |
| `GET /api/jobs/{job_id}/validation` | `ValidationReport` | §11.8 |

(There is no separate `GET /api/jobs/{job_id}/members` — the member
directory used by a job is available via §3.9.4 on the *project*, since
members are project-level input data set once, not a per-job output.)

- **Response if that stage has completed:** `200 OK`, the schema above.
- **Response if that stage hasn't completed yet:** `409 Conflict`,
  `{"detail": {"code": "STAGE_NOT_READY", "message": "'<stage>'ステージはまだ完了していません。"}}`.
- **Errors:** `401`/`404 JOB_NOT_FOUND`, `500 RESULT_READ_ERROR` (a saved
  file exists but failed to parse/validate — should not happen in practice).

### Error codes introduced in this section

| Code | HTTP status | Meaning |
|---|---|---|
| `PROJECT_NOT_FOUND` | 404 | Project doesn't exist, or belongs to another team. |
| `JOB_NOT_FOUND` | 404 | Job doesn't exist, or belongs to another team. |
| `MEMBERS_NOT_CONFIGURED` | 400 (at `/generate`) or 404 (at `GET .../members`) | No member directory set for this project yet. |
| `DOCUMENT_NOT_SET` | 400 | No specification text on the project. |
| `JOB_NOT_COMPLETED` | 409 | `/result` requested before `status == "completed"`. |
| `STAGE_NOT_READY` | 409 | A stage endpoint requested before that stage finished. |
| `NO_ERROR` | 404 | `/error` requested on a job that hasn't failed. |
| `RESULT_MISSING` / `RESULT_READ_ERROR` | 500 | Internal inconsistency (saved file missing/corrupt) — should not occur in normal operation. |
| `OLLAMA_UNAVAILABLE` | (job `error.code`, not an HTTP status — the job itself is marked `failed`) | The LLM client could not be constructed/reached (`ConnectionError`/`OSError`) when the job tried to start. |
| `INTERNAL_ERROR` / `VALIDATION_ERROR` | (job `error.code`) | Fallback classification for any other exception a stage raised — see `backend/jobs/errors.py`. Never includes a stack trace. |

**Important distinction, confirmed by test** (`test_llm_http_errors_are_absorbed_as_issues_not_a_job_crash`
in `backend/tests/test_jobs_api.py`): if the *configured* LLM provider
itself times out or errors on individual calls (e.g. real Ollama returning
504s), that is **already handled by the unmodified existing pipeline code**
(`backend/services/pipeline/llm_json.py`'s `call_llm_json` retries and then
records an `EXTRACTION_ERROR`/`DECOMPOSITION_ERROR` issue in the resulting
document) — the job still reaches `status: "completed"`, just with fewer
requirements/tasks and visible `issues`. A job only becomes `status: "failed"`
when something outside that existing retry logic goes wrong (e.g. the LLM
client can't be constructed at all, or an unrelated exception occurs).

---

## 3.10 `POST /api/documents/parse` — convert a spec file (PDF/Word) to body text

Added per `Backend依頼_仕様書ファイル変換API.md`. `backend/routers/documents.py`.
File → text conversion only — **no DB write, no job started.** Reuses the
existing `backend/services/parser.py` extraction logic unchanged (PyMuPDF for
`.pdf`, python-docx for `.docx`, plain UTF-8 decode for `.txt`/`.md`).
Auth: same team session cookie as every `/api/projects*` endpoint
(`get_current_member`).

Request: `multipart/form-data`, field name `file` (exactly one file).

Response `200`:
```json
{
  "filename": "EC_要件定義書.pdf",
  "text": "1. 概要\n本書は…",
  "char_count": 18420,
  "page_count": 24,
  "truncated": false
}
```
`page_count` is `null` for `.docx`/`.txt`/`.md` (page count only makes sense
for PDF). **`truncated` is always `false`** — unlike the legacy
`parse_document()` used by `/api/tasks/generate` (§5.A), this endpoint calls
a new `parse_document_full()` (same module) that does **not** apply
`MAX_EXTRACT_CHARS` truncation, since the Phase 3-9 pipeline already
processes the document in per-chunk pieces at the Requirements stage — there
is no need to pre-truncate here, and doing so would silently drop content
from long specs before requirement extraction ever sees it. This was 案A
(recommended) from the request document; `parse_document()` itself is
unchanged and the legacy endpoint's truncation behavior is untouched.

Errors (same `{"detail": {"code", "message"}}` shape as every other endpoint):

| status | code | condition |
|---|---|---|
| 400 | `UNSUPPORTED_FILE_TYPE` | Extension isn't `.pdf`/`.docx`/`.txt`/`.md` |
| 400 | `EMPTY_DOCUMENT` | No extractable text (e.g. a scanned image-only PDF) |
| 413 | `FILE_TOO_LARGE` | File exceeds `MAX_UPLOAD_SIZE` (default 20 MB) |
| 401 | `UNAUTHENTICATED` | No/invalid session cookie |

---

## 4. Endpoints — Requirements (Phase 3)

**As of Phase 10, reachable indirectly via `GET /api/jobs/{job_id}/requirements`
(§3.9.9)** — once a job created through §3.9.5 finishes this stage. There is
still no standalone `POST /api/requirements` — you cannot run *only* this
stage over HTTP in isolation; it's always part of a full job. The
functionality itself lives entirely in `backend/pipeline/requirements/`
(`extractor.py`, `validator.py`, `runner.py`) and remains **also** reachable
via `python -m backend.pipeline.requirements.runner <spec.txt> <document_id>`
(unchanged CLI, §12A), which writes a `requirements.json` file to
`backend/pipeline/requirements/output/` — the same function and the same
kind of output file the job API now also produces (to a job-specific path).

The `Requirement` / `RequirementDocument` schema is documented in §11.

---

## 5. Endpoints — Tasks

Two, **unrelated and non-interoperable**, things are called "tasks" in this
codebase. The frontend team must not conflate them.

### 5.A The live, HTTP-exposed task system (`backend/routers/tasks.py`)

This is a **single global project** (no team scoping — see the final
report). Every call to `generate` **replaces** all existing tasks and
members in the database (`DELETE FROM tasks; DELETE FROM members;` before
inserting the new set).

#### `POST /api/tasks/generate` — upload a spec, generate tasks

- **Auth required:** No.
- **Request:** `multipart/form-data`.
  - `file` (binary, optional) — one of `.pdf` / `.docx` / `.txt` / `.md`.
  - `text_content` (string, optional) — plain spec text, used only if `file`
    is not provided.
  - `members_json` (string, **required**) — a JSON-encoded array whose
    elements match `MemberSchema` (`backend/models/schemas.py`), even though
    FastAPI/OpenAPI only types this field as an opaque `string`:
    ```json
    [{ "name": "山田太郎", "skills": ["Python", "FastAPI"], "load_pct": 0 }]
    ```
    (`skills` may also be given as a comma-separated string; a `field_validator`
    splits it. `load_pct` defaults to `0` if omitted.)
  - At least one of `file` / `text_content` must resolve to non-empty text.
- **Processing:** **synchronous** — the HTTP request blocks until the whole
  multi-stage extraction pipeline (`backend/services/pipeline/runner.py`)
  finishes calling the configured LLM one or more times. There is no job ID,
  no polling endpoint, no background task. For a real spec document against
  a local Ollama model this can take well over a minute; the frontend must
  set a generous request timeout.
- **Response:** `200 OK`, body `ProjectOutputSchema` (see §11 for full
  field list) — includes `generation_notes` (counts of failed/dropped items,
  non-null only on this endpoint's response).
- **Errors:**
  - `500 CONFIG_ERROR` — `MAX_TASKS_FREE` env var not set on the server.
  - `400 INVALID_MEMBERS_JSON` — `members_json` didn't parse.
  - `400 FILE_PARSE_ERROR` — unsupported extension, empty/unreadable content,
    or file exceeds `MAX_UPLOAD_SIZE`.
  - `500 FILE_PARSE_ERROR` — unexpected parser exception.
  - `400 EMPTY_INPUT` — neither `file` nor `text_content` yielded text.
  - `403 PLAN_LIMIT_EXCEEDED` — generated task count exceeds `MAX_TASKS_FREE`.
  - `504 LLM_TIMEOUT` / `500 LLM_PARSE_ERROR` / `502 LLM_API_ERROR` — from
    the configured LLM provider (`backend/services/llm.py`), surfaced as-is.
  - `422` — missing `members_json`.
- **Example request:**
  ```bash
  curl -X POST http://localhost:8000/api/tasks/generate \
    -F "file=@spec.pdf" \
    -F 'members_json=[{"name":"山田太郎","skills":["Python"],"load_pct":0}]'
  ```

#### `GET /api/tasks` — list current (global) tasks

- **Auth required:** No.
- **Response:** `200 OK`, `ProjectOutputSchema` with `generation_notes: null`.

#### `GET /api/tasks/export` — same data, "export" framing

- **Auth required:** No.
- **Response:** `200 OK`, `ProjectOutputSchema`.
- **Note:** this endpoint's handler (`export_tasks`) calls the exact same
  `_build_project_output(db)` helper as `GET /api/tasks` — **the two
  endpoints currently return byte-identical JSON.** Flagged in the final
  report; not changed here per the no-redesign instruction.

#### `PUT /api/tasks/{task_id}` — update one task (Kanban drag/inline edit)

- **Auth required:** No.
- **Path params:** `task_id` (string, e.g. `T-001` — see the ID-format note
  in the final report).
- **Request body** (`TaskUpdateRequest`, all fields optional):
  ```json
  { "title": null, "assignee": null, "priority": null, "source_section": null, "status": null }
  ```
- **Response:** `200 OK`. **No `response_model` is declared on this route**,
  so OpenAPI documents the response schema as `{}` (unknown). The actual
  runtime shape, read from source, is:
  ```json
  { "status": "success", "task": { /* TaskSchema, see §11 */ } }
  ```
- **Errors:** `404 TASK_NOT_FOUND`, `422`.

### 5.B The pipeline task-decomposition system (Phase 4)

**As of Phase 10, reachable indirectly via `GET /api/jobs/{job_id}/tasks`
(§3.9.9).** Lives in `backend/pipeline/tasks/` (`decomposer.py`,
`validator.py`, `runner.py`), consumes a `RequirementDocument` (§4), and is
**also** reachable via
`python -m backend.pipeline.tasks.runner <requirements.json> [spec.txt]`
(unchanged CLI). Its `Task` schema is richer than and incompatible with
§5.A's `TaskSchema` (IDs are `TASK-001`-style, not `T-001`; carries
`requirement_ids`, `needs_review`, `review_reasons`, structured
`source_reference`, etc. — see §11). It is still not linked to the
database or to §5.A's tasks — the job API stores its output as a JSON file
(§3.9), same as the CLI does, not as `TaskModel` rows.

---

## 6. Endpoints — Dependencies (Phase 5)

**As of Phase 10, reachable indirectly via `GET /api/jobs/{job_id}/dependencies`
(§3.9.9).** Lives in `backend/pipeline/dependencies/` (`proposer.py`,
`validator.py`, `graph.py`, `runner.py`), consumes a `TaskDocument` (§5.B),
**also** reachable via `python -m backend.pipeline.dependencies.runner <tasks.json>`
(unchanged CLI). `Dependency` / `DependencyDocument` schema in §11.

---

## 7. Endpoints — Members (Phase 6, structured skill/availability model)

**As of Phase 10, reachable via `PUT`/`GET /api/projects/{project_id}/members`
(§3.9.3-3.9.4)** — the first of the Phase 3-9 pipeline's own concepts to get
a *dedicated* (not job-scoped) endpoint, since member data is project-level
input set once and reused across job runs, not a per-run output. This is
still a *third* concept called "member" in the codebase, separate from both
§3's auth `TeamMember` and §5.A's simple `MemberModel`
(name/skills-string/load_pct used only for the legacy matcher). It lives in
`backend/pipeline/members/` (`validator.py`, `runner.py`) and is populated
only from user/manager input or imported data — **never from an LLM** —
`PUT /api/projects/{project_id}/members` calls the exact same
`build_member_directory()` function unchanged. `Member` / `MemberDirectory`
schema in §11.

---

## 8. Endpoints — Assignments (Phase 7)

**As of Phase 10, reachable indirectly via `GET /api/jobs/{job_id}/assignments`
(§3.9.9)**, returning `List[FinalAssignment]` (not `AssignmentResult`
directly — each task's AI recommendation is wrapped via
`accept_recommendation()`, unchanged, and embedded inside `FinalAssignment.ai_recommendation`;
see §11.7). Lives in `backend/pipeline/assignment/` (`filters.py`,
`scoring.py`, `reasoning.py`, `override.py`, `runner.py`). Combines
deterministic hard-constraint filtering + configurable scoring + optional
LLM reasoning (off by default via the job API — see §3.9.5's
`use_assignment_llm_reasoning`) to produce an `AssignmentResult`
recommendation per task. Still **also** reachable via
`python -m backend.pipeline.assignment.runner <task.json> <members.json> [--llm]`
(unchanged CLI, operates on one task at a time, unlike the job API which
loops over every task in the `TaskDocument` — see §3.9's "how it reuses
existing code"). Schemas in §11.

---

## 9. Endpoints — Validation (Phase 8) & Final project result (Phase 9)

**As of Phase 10, both reachable via the job API**:
`GET /api/jobs/{job_id}/validation` (§3.9.9, returns `ValidationReport`) and
`GET /api/jobs/{job_id}/result` (§3.9.7, returns the full `FinalProjectOutput`,
which embeds the `ValidationReport` inside `validation.report` — see §11.9).

- Validation lives in `backend/pipeline/validation/` (`missing_requirements.py`,
  `duplicates.py`, `dependencies.py`, `workload.py`, `skill_mismatch.py`,
  `constraints.py`, `runner.py`), **also** reachable via
  `python -m backend.pipeline.validation.runner <req.json> <tasks.json> <deps.json> <members.json> <assignments.json> [--llm]`
  (unchanged CLI). `ValidationReport` schema in §11.
- Final assembly lives in `backend/pipeline/final_output/`
  (`assembler.py`, `metadata.py`, `validation_summary.py`, `json_schema.py`,
  `runner.py`), **also** reachable via
  `python -m backend.pipeline.final_output.runner <req.json> <tasks.json> <deps.json> <members.json> <assignments.json> <validation.json> [project_name]`
  (unchanged CLI). `FinalProjectOutput` schema in §11. Its own JSON Schema
  can still be obtained by calling
  `backend.pipeline.final_output.json_schema.get_json_schema()` (not the
  same document as `docs/openapi.json` — that's the FastAPI app's schema,
  this is just `FinalProjectOutput`'s own schema, useful for validating a
  `/result` response body against in isolation).

---

## 10. Settings & health (not in the original 10-category list, included for completeness)

### `POST /api/settings`

- **Auth required:** No. Storage is a single in-memory `dict`
  (`SETTINGS_STORE` in `backend/routers/tasks.py`) — not per-team, not
  persisted to the database, reset on server restart.
- **Request body** (`SettingsSchema`):
  ```json
  { "provider": "openai|anthropic|ollama", "api_key": "string", "base_url": null, "slack_webhook_url": null, "teams_webhook_url": null }
  ```
- **Response:** `200 OK`. No `response_model` declared; actual runtime shape:
  ```json
  { "status": "success", "message": "設定を保存しました", "current_settings": { /* SettingsSchema fields */ } }
  ```

### `GET /api/settings`

- **Auth required:** No. No `response_model` declared (OpenAPI shows `{}`).
  Actual runtime shape is the raw `SETTINGS_STORE` dict (same fields as
  `SettingsSchema`, defaults: `provider: "openai"`, `api_key: ""`).

### `GET /healthz`

- **Auth required:** No. Response: `200 OK`, `{"status": "ok", "version": "1.0.0"}`.

---

## 11. JSON Schemas (as actually implemented)

All of these are the literal Pydantic models in the codebase — no field was
added, renamed, or invented for this document.

### 11.1 `TaskSchema` — the live/HTTP-exposed task (`backend/models/schemas.py`)

```jsonc
{
  "task_id": "string",            // e.g. "T-001" — required
  "title": "string",              // required
  "assignee": "string",           // required
  "skill_required": "string",     // required — display string, see required_skills for detail
  "priority": "high|medium|low|unknown", // required
  "deadline": "date | null",
  "source_section": "string",     // required — display string
  "load_pct": "integer 0-100",    // required
  "status": "string",             // default "TODO"
  "description": "string | null",
  "estimated_hours": "number | null",
  "required_skills": "string[] | null",
  "acceptance_criteria": "string[] | null",
  "source_chunk_id": "string | null",
  "source_excerpt": "string | null",
  "needs_review": "boolean",      // default false
  "review_reason": "string | null"
}
```

### 11.2 `ProjectOutputSchema` (wraps 11.1; response of §5.A endpoints)

```jsonc
{
  "project": "string",            // default "名称未設定プロジェクト"
  "exported_at": "date",          // required
  "tasks": [ /* TaskSchema, §11.1 */ ],   // required
  "generation_notes": {            // null except right after /api/tasks/generate
    "failed_item_count": "integer",
    "dropped_duplicate_titles": "string[]"
  } | null
}
```

### 11.3 `Requirement` / `RequirementDocument` (Phase 3, `backend/pipeline/requirements/schema.py`) — **not exposed via HTTP**

```jsonc
// Requirement
{
  "id": "string",  // pattern ^REQ-\d{3,}$
  "type": "system_purpose|target_user|functional|non_functional|constraint|assumption|deliverable|technical|business_rule",
  "title": "string", "description": "string",
  "priority": "high|medium|low|unknown",       // default "unknown"
  "origin": "explicit|inferred",                // default "explicit"
  "source_reference": {                          // nullable
    "document_id": "string", "page": "integer | null",
    "section": "string | null", "paragraph": "string | null", "source_text": "string | null"
  } | null,
  "confidence": "number 0.0-1.0"   // required
}
// RequirementDocument
{
  "document_id": "string", "requirements": [ /* Requirement[] */ ],
  "issues": [ { "code": "string", "message": "string", "requirement_ids": "string[]" } ],
  "model": "string | null", "model_version": "string | null", "generated_at": "string | null"
}
```

### 11.4 `Task` / `TaskDocument` (Phase 4, `backend/pipeline/tasks/schema.py`) — **not exposed via HTTP**

```jsonc
// Task
{
  "id": "string",  // pattern ^TASK-\d{3,}$  (NOT the same format as 11.1's task_id)
  "requirement_ids": "string[]",           // default []
  "title": "string", "description": "string",
  "priority": "high|medium|low|unknown",   // default "unknown"
  "estimated_hours": "number | null",
  "required_skills": "string[]",           // default ["unknown"]
  "acceptance_criteria": "string[]",        // default []
  "source_reference": { /* same shape as 11.3 */ } | null,
  "confidence": "number 0.0-1.0",           // required
  "needs_review": "boolean",                // default false
  "review_reasons": "string[]"              // default []
}
// TaskDocument
{
  "document_id": "string", "tasks": [ /* Task[] */ ],
  "issues": [ { "code": "string", "message": "string", "task_ids": "string[]" } ],
  "model": "string | null", "generated_at": "string | null"
}
```

### 11.5 `Dependency` / `DependencyDocument` (Phase 5, `backend/pipeline/dependencies/schema.py`) — **not exposed via HTTP**

```jsonc
// Dependency — edge meaning: from_task_id must finish before to_task_id can start
{
  "from_task_id": "string", "to_task_id": "string",
  "type": "required|recommended|optional",  // default "optional"
  "reason": "string",                        // default ""
  "confidence": "number 0.0-1.0"              // required
}
// DependencyDocument
{
  "document_id": "string", "dependencies": [ /* Dependency[] */ ],
  "issues": [ { "code": "string", "message": "string", "edges": [{"from_task_id":"string","to_task_id":"string"}] } ],
  "graph": { "nodes": "string[]", "edges": "object[]", "levels": "object", "required_cycle": "string[] | null" },
  "model": "string | null", "generated_at": "string | null"
}
```

### 11.6 `Member` / `MemberDirectory` (Phase 6, `backend/pipeline/members/schema.py`) — **not exposed via HTTP**

```jsonc
// Member
{
  "id": "string", "name": "string",
  "skills": [ { "skill": "string", "level": "integer 1-5", "experience_years": "number | null" } ],
  "experience_years": "number | null",
  "availability": {
    "available_hours_per_week": "number", "working_days": "string[]",
    "current_assigned_hours": "number"        // default 0.0
    // remaining_capacity = available_hours_per_week - current_assigned_hours (computed property, NOT a stored/serialized field)
  },
  "constraints": [ { "type": "scope_restriction|day_unavailable|max_hours_per_week|requires_review", "value": "string | null", "max_hours": "number | null" } ]
}
// MemberDirectory
{
  "team_id": "string | null", "members": [ /* Member[] */ ],
  "issues": [ { "code": "string", "message": "string", "member_id": "string | null" } ],
  "updated_at": "string | null"
}
```

**Important:** `remaining_capacity` is a Python `@property`, not a Pydantic
field — it is **not present** in `Member.model_dump()` / the serialized JSON.
Any consumer (frontend included) that needs it must compute
`available_hours_per_week - current_assigned_hours` itself.

### 11.7 `AssignmentResult` / `FinalAssignment` (Phase 7, `backend/pipeline/assignment/schema.py`) — **not exposed via HTTP**

```jsonc
// AssignmentResult — the AI's recommendation for one task
{
  "task_id": "string",
  "recommended_member_id": "string | null",
  "score": "number | null",   // 0-100
  "candidate_scores": [ { "member_id":"string","skill_match":"number","workload_score":"number","experience_score":"number","availability_score":"number","skill_similarity":"number","score":"number" } ],
  "rejected_candidates": [ { "member_id": "string", "reasons": "string[]" } ],
  "reasons": "string[]", "warnings": "string[]",
  "status": "recommended|no_suitable_member"
}
// FinalAssignment — the human's actual decision (this is what "assignments" means in §9's Final JSON)
{
  "task_id": "string", "assigned_member_id": "string | null",
  "decided_by": "ai|human", "overridden": "boolean",
  "override_reason": "string | null",
  "ai_recommendation": { /* AssignmentResult, embedded in full */ }
}
```

### 11.8 `ValidationReport` ("ValidationResult", Phase 8, `backend/pipeline/validation/schema.py`) — **not exposed via HTTP**

```jsonc
{
  "valid": "boolean",
  "missing_requirements": [ { "requirement_id": "string", "message": "string" } ],
  "duplicate_tasks": [ { "task_ids": "string[]", "similarity": "number", "method": "rule|llm|hybrid", "reason": "string" } ],
  "dependency_errors": [ { "code": "string", "message": "string", "task_ids": "string[]" } ],
  "workload_warnings": [ { "member_id":"string","assigned_hours":"number","available_hours":"number","remaining_capacity":"number","workload_percentage":"number","code":"string","message":"string" } ],
  "skill_mismatches": [ { "task_id":"string","member_id":"string","skill":"string","required_level":"integer","member_level":"integer","message":"string" } ],
  "constraint_violations": [ { "task_id":"string","member_id":"string","code":"string","message":"string" } ],
  "task_quality_issues": [ { "task_id":"string","code":"string","message":"string" } ],
  "assignment_score_anomalies": [ { "task_id":"string","member_id":"string","score":"number","threshold":"number","message":"string" } ],
  "workload_summaries": [ { "member_id":"string","assigned_hours":"number","available_hours":"number","remaining_capacity":"number","workload_percentage":"number" } ],
  "generated_at": "string | null"
}
```

`task_quality_issues` and `assignment_score_anomalies` are new in Phase 11
(CHECK 7/8, Part 14) — purely additive fields, default to `[]`, existing
consumers unaffected (Part 20: backward compatibility). `task_quality_issues`
does **not** affect `valid` (it mirrors Phase 4's per-task `needs_review`
flags, which are already surfaced on each `Task` — see §11.4 — so this would
double-block generation if treated as a hard error); both new lists are
folded into `warning_issue_count` one layer up in Phase 9's
`ValidationSummary` (§11.9), never silently dropped.

Note: `valid` is the *only* status field here — the tri-state
`valid`/`warning`/`error` distinction only exists one layer up, in Phase 9's
`ValidationSummary` (§11.9), not in this object itself.

### 11.9 `FinalProjectOutput` ("FinalProjectResult", Phase 9, `backend/pipeline/final_output/schema.py`) — **not exposed via HTTP**

```jsonc
{
  "project": { "document_id": "string", "name": "string | null", "exported_at": "string | null" },
  "requirements": [ /* Requirement[], §11.3 */ ],
  "tasks": [ /* Task[], §11.4 */ ],
  "dependencies": [ /* Dependency[], §11.5 */ ],
  "members": [ /* Member[], §11.6 */ ],
  "assignments": [ /* FinalAssignment[], §11.7 */ ],
  "validation": {
    "status": "valid|warning|error",   // computed by validation_summary.py, not stored on ValidationReport itself
    "critical_issue_count": "integer", "warning_issue_count": "integer",
    "traceability_errors": [ { "code": "string", "message": "string", "task_id": "string | null" } ],
    "report": { /* ValidationReport, §11.8, embedded in full — never dropped or summarized away */ }
  },
  "metadata": {
    "generated_at": "string", "pipeline_version": "string",
    "model": "string | null", "model_version": "string | null",
    "prompt_versions": { "requirements_extraction":"string","task_decomposition":"string","dependency_proposal":"string","assignment_reasoning":"string" },
    "document_id": "string | null",
    "models_by_phase": "object"   // only populated when phases disagree on which model was used
  }
}
```

Its own machine-readable JSON Schema can be produced at any time by calling
`backend.pipeline.final_output.json_schema.get_json_schema()` — that is the
canonical schema for this object, not anything transcribed by hand above.

### 11.10 `ProjectResponse` / `JobStatusResponse` (Phase 10, `backend/models/job_schemas.py`) — **exposed via HTTP, §3.9**

These are new in Phase 10 — thin, purpose-built response shapes for the
job/project API, not reused from Phase 3-9 (unlike everything else in §11,
which reuses the pipeline's own types).

```jsonc
// ProjectResponse
{
  "id": "string", "team_id": "string", "name": "string | null",
  "has_document": "boolean", "has_members": "boolean",
  "created_at": "datetime", "updated_at": "datetime"
}
// JobStatusResponse
{
  "job_id": "string", "project_id": "string", "team_id": "string",
  "status": "queued|running|completed|failed|cancelled",
  "progress": "integer 0-100",
  "current_step": "requirements|tasks|dependencies|members|assignments|validation|finalize|null",
  "message": "string | null",
  "created_at": "datetime", "started_at": "datetime | null", "completed_at": "datetime | null",
  "error": { "code": "string", "message": "string" } | null
}
```

### 11.11 `ParsedDocument` (`backend/services/parser.py`) — **exposed via HTTP, §3.10**

```jsonc
{
  "filename": "string",
  "text": "string",
  "char_count": "integer",
  "page_count": "integer | null",   // null for .docx/.txt/.md
  "truncated": "boolean"            // always false for this endpoint (§3.10)
}
```

---

## 12. Pipeline flow — documented against the actual code

### Legacy path (§5.A, unchanged by Phase 10)

```
Specification                → §5.A  POST /api/tasks/generate  (LIVE, synchronous, no job ID)
    ↓ (inside that one request, backend/services/pipeline/runner.py does its own
       internal decompose→identify→extract→normalize→dedup→validate steps —
       none of these sub-steps are individually exposed either)
Tasks (legacy TaskSchema)     ← returned directly in the same response
```

This request still blocks the whole time (this is the "5+ minutes, no
response" path described in the Phase 10 brief) — **unchanged in this
phase**, per the instruction not to alter existing behavior. It remains a
separate, simpler code path from the Phase 3-9 pipeline below (see §5's
"two unrelated things called 'tasks'").

### Phase 3-9 pipeline, now job-based (§3.9, NEW in Phase 10)

```
Specification                 → POST /api/projects (§3.9.1) + PUT .../members (§3.9.3)
    ↓                            then POST /api/projects/{id}/generate (§3.9.5)
    ↓                            → { "job_id": "...", "status": "queued" }  (returns immediately)
    ↓                            (backend/jobs/manager.py runs the rest in an asyncio background task)
Requirements (Phase 3)        → run_requirements_pipeline()          → GET /api/jobs/{id}/requirements
    ↓
Tasks (Phase 4)                → run_task_decomposition_pipeline()    → GET /api/jobs/{id}/tasks
    ↓
Dependencies (Phase 5)         → run_dependency_pipeline()            → GET /api/jobs/{id}/dependencies
    ↓
Members (Phase 6)              → load_member_directory()  (no LLM)    → GET /api/projects/{id}/members
    ↓
Assignments (Phase 7)          → run_assignment() × 1 per task        → GET /api/jobs/{id}/assignments
    ↓
Validation (Phase 8)           → validate_project_plan()              → GET /api/jobs/{id}/validation
    ↓
Final JSON (Phase 9)           → assemble_final_output()              → GET /api/jobs/{id}/result
```

Poll `GET /api/jobs/{id}` (§3.9.6) at any point during this to read
`status`/`progress`/`current_step`/`message`. See §14 for the exact
frontend polling pattern.

**Synchronicity, precisely:** every individual stage function above is
still called and awaited exactly as it always was (nothing inside Phase 3-9
was made concurrent or non-blocking that wasn't already `async`/`await`).
What changed is *where* that blocking happens: it's inside a background
`asyncio.create_task()` owned by the job manager, not inside the HTTP
request/response cycle. The HTTP layer only ever blocks for the handful of
milliseconds it takes to create a `JobModel` row and schedule the task.

---

## 12A. CLI vs. API — one pipeline, two entry points

Per Phase 10 STEP 18 (backward compatibility), every CLI entry point listed
in §4-§9 **still works exactly as before** — none of `backend/pipeline/*`
was modified. `backend/jobs/manager.py` calls the identical
`backend.pipeline.*.runner` functions the CLI scripts call; it does not
duplicate, wrap-and-diverge, or reimplement any of them:

```
CLI (python -m backend.pipeline.*.runner) ──┐
                                              ↓
                                    backend.pipeline.* (Phase 3-9, unchanged)
                                              ↑
                                              │
FastAPI (backend/jobs/manager.py) ───────────┘
```

The only things `backend/jobs/manager.py` adds *around* those calls are:
timing/logging instrumentation (`backend/jobs/timing.py`, wraps
`BaseLLMClient` from the outside — `backend/services/llm.py` itself is
unmodified), progress bookkeeping (`JobModel` updates between stages), and
persisting each stage's already-existing `save_*()` output to a
`JobModel`-tracked path. There is exactly one pipeline implementation.

---

## 13. OpenAPI

FastAPI generates the OpenAPI document automatically; nothing in
`backend/main.py` overrides `openapi_url`, `docs_url`, or `redoc_url`, so the
defaults are live at runtime:

- Raw schema: `GET /openapi.json`
- Swagger UI: `GET /docs`
- ReDoc: `GET /redoc`

`docs/openapi.json` in this repo was produced by literally calling
`app.openapi()` on the real app object (see command below) — it was not
hand-written, per this task's instructions.

```bash
python3 -c "
from backend.main import app
import json
json.dump(app.openapi(), open('docs/openapi.json','w'), ensure_ascii=False, indent=2)
"
```

As of Phase 10 the app had **26 paths** (verified by re-running the command
above and counting `schema['paths']`), 12 of which are the new
Projects/Jobs endpoints from §3.9. As of the `/api/documents/parse` addition
(§3.10) the count is **27 paths**.

Cross-checking it against the implementation surfaced these gaps (also in
the final report):

1. **No security scheme is declared anywhere in the OpenAPI document**
   (`components.securitySchemes` is absent, and no operation carries a
   `security` requirement) — even though `/api/me`,
   `/api/sessions/refresh`, `/api/teams/{team_id}/invitations`,
   `/api/teams/{team_id}/members`, `/api/members/{member_id}`, and **every
   one of the new §3.9 Projects/Jobs endpoints** genuinely require the
   session cookie. This is because auth is implemented via a manual
   `request.cookies.get(...)` read (`backend/auth/dependencies.py`) rather
   than FastAPI's `Security()`/`Cookie()` dependency machinery — and
   `backend/routers/projects.py`/`backend/routers/jobs.py` reuse that exact
   same `get_current_member` dependency unchanged, so this gap now applies
   to twice as many endpoints as before. **Swagger UI's "Authorize" button
   will not appear**, and generated API clients will not know a cookie is
   needed — the frontend must rely on this document (§3/§3.9/§10), not the
   OpenAPI file, for auth requirements.
2. Several response schemas are empty objects (`{}`) because no
   `response_model` was declared on those routes: `PUT /api/tasks/{task_id}`,
   `GET /api/settings`, `POST /api/settings` (root shape). The real response
   shapes are documented from source in §5.A/§10 above. Every Phase 10
   route *does* declare a `response_model` (see §3.9), so this specific gap
   was not reintroduced.
3. The `members_json` field of `POST /api/tasks/generate` is typed as an
   opaque `string` in OpenAPI (it's a JSON-encoded string passed through a
   plain `Form(...)` parameter) — the actual expected inner structure
   (`MemberSchema[]`) is invisible to OpenAPI and only documented here (§5.A).
   `PUT /api/projects/{project_id}/members` (§3.9.3) does not have this
   problem — it takes a real JSON body (`SetMembersRequest`), fully typed.

---

## 14. Frontend integration example (Phase 10 job API)

`axios` configured with `withCredentials: true` (§1) is assumed
(`const api = axios.create({ baseURL: ..., withCredentials: true })`).

```ts
// 1. Create a project (once), set its spec text and member list.
const { data: project } = await api.post("/api/projects", {
  name: "タスみる導入プロジェクト",
  document_text: specText,
});
const projectId = project.id;

await api.put(`/api/projects/${projectId}/members`, {
  members: [
    {
      id: "M-001",
      name: "山田太郎",
      skills: [{ skill: "Python", level: 5, experience_years: 3 }],
      availability: { available_hours_per_week: 40, working_days: ["Monday"], current_assigned_hours: 0 },
    },
  ],
});

// 2. Start the job. Returns immediately — job_id, status "queued".
const { data: gen } = await api.post(`/api/projects/${projectId}/generate`);
const jobId = gen.job_id;

// 3. Poll status until it reaches a terminal state.
async function pollJob(jobId: string): Promise<JobStatusResponse> {
  while (true) {
    const { data: status } = await api.get(`/api/jobs/${jobId}`);
    // status: { job_id, status, progress, current_step, message, error, ... }
    // → feed status directly into a progress component:
    //   <ProgressBar percent={status.progress} label={status.message} step={status.current_step} />
    if (status.status === "completed" || status.status === "failed") {
      return status;
    }
    await new Promise((r) => setTimeout(r, 2000)); // poll every 2s
  }
}

const finalStatus = await pollJob(jobId);

// 4. Fetch the result (or handle the error).
if (finalStatus.status === "completed") {
  const { data: result } = await api.get(`/api/jobs/${jobId}/result`);
  // result: FinalProjectOutput (§11.9) — project, requirements, tasks,
  // dependencies, members, assignments, validation, metadata
} else {
  // finalStatus.error: { code, message } — display directly, never a stack trace
  console.error(finalStatus.error.code, finalStatus.error.message);
}
```

**Progress component contract** (matches the brief's example exactly):

```ts
interface JobStatus {
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  progress: number;       // 0-100
  current_step: string | null;  // "requirements" | "tasks" | "dependencies" | "members" | "assignments" | "validation" | "finalize"
  message: string | null; // Japanese, human-readable — safe to display directly
}
```

**Recommended polling interval:** every 1-2 seconds is reasonable. Given the
measured per-LLM-call latency (`docs/PIPELINE_PERFORMANCE.md` — tens of
seconds to a few minutes per call on this environment's Ollama setup),
polling more aggressively than every ~1s gains nothing and just adds load;
polling less often than every ~5s makes the progress bar feel unresponsive
during the (currently long) `requirements`/`tasks` stages.

**Inspecting an in-progress or completed job's individual stages** (useful
for a "show me what was extracted so far" panel, not required for the
basic flow above):

```ts
const requirements = await api.get(`/api/jobs/${jobId}/requirements`); // 409 if not ready yet
const tasks = await api.get(`/api/jobs/${jobId}/tasks`);
const dependencies = await api.get(`/api/jobs/${jobId}/dependencies`);
const assignments = await api.get(`/api/jobs/${jobId}/assignments`);
const validation = await api.get(`/api/jobs/${jobId}/validation`);
```

**Replacing fixture data:** per the brief, do this only after the API
implementation above is exercised against a real backend. Every response
shape here matches an actual Pydantic model (§11) with no invented fields —
swapping a fixture-JSON service call for one of the `api.get(...)` calls
above should not require changing how a component consumes the data, only
how it's fetched.
