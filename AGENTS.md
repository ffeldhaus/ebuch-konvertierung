# AGENTS.md – Project Rules & Architectural Invariants

Core invariants for `ebuch-konvertierung`. Task-specific runbooks are stored as on-demand workspace skills in `.agents/skills/`:
- **Benchmarks & Leaderboards**: [`.agents/skills/ebuch-benchmark/SKILL.md`](.agents/skills/ebuch-benchmark/SKILL.md)
- **Gemma Feedback Reports (`💬 Feedback` mode)**: [`.agents/skills/ebuch-feedback-analysis/SKILL.md`](.agents/skills/ebuch-feedback-analysis/SKILL.md)

## 1. Code Structure, Python 3.14 Templates, Pydantic & Google Style Guide
- **Dedicated Constants & Prompts Modules (`fibs_constants.py`, `prompts.py`)**:
  - Extract static definitions (system prompts, regex tables, symbol lookup maps, token budgets, FIBS DOCX style constants) into `backend/services/fibs_constants.py` and `backend/services/prompts.py` so functional service modules remain focused on business logic.
- **Python 3.14 Template Strings (`string.templatelib` / PEP 750 `t"..."`)**:
  - Construct dynamic LLM/VLM prompts in `backend/services/prompts.py` using Python 3.14 `Template` literals (`t"..."`) and `render_prompt(template: Template) -> str` (supports `:strip_markers` to sanitize untrusted OCR inputs against `[ABSCHNITT]`/`[KONTEXT]` marker injection and `:max_chars=N` for bounded context interpolation).
- **Pydantic Domain Models (`backend/services/models.py`)**:
  - Use Pydantic `DomainModel` (`use_attribute_docstrings=True`) for structured domain payloads (`VlmDescriptionResult`, `PageSegment`, `TableDescription`, `StandardisationChunk`, `LintIssue`, `LintReport`, `DiffHunk`, `OpenQuestion`) and FastAPI request/response schemas. Use English attribute names and document every field via a single-line docstring immediately beneath the attribute definition (never duplicate descriptions in class `Attributes:` blocks or `Field(description=...)`).
  - **Typed Service Boundaries**: LLM/VLM/analyzer services and internal service boundaries must parse structured outputs into `DomainModel` instances at the boundary rather than passing around raw protocol strings or untyped `dict[str, Any]` payloads. Downstream formatting and export modules accept those typed `DomainModel` objects directly.
- **Google Style Guide & Linting Enforcement**:
  - Write Python docstrings in **Google Style Guide** format (`Args:`, `Returns:`, `Raises:`) enforced via `ruff` (`[tool.ruff.lint.pydocstyle] convention = "google"`).
  - Follow the **Google TypeScript Style Guide** in `frontend/src/`, enforced via `eslint.config.js` (`npx eslint frontend/src --max-warnings 0`) and `npx tsc --noEmit`.
- **Imports, Canonical Modules & No `__all__` Re-Exports**:
  - Never define `__all__` or re-export symbols across `backend/services/` modules; import every function, class, and constant directly from its canonical module.
  - When a module uses more than a few constants/regexes from `fibs_constants.py` or `prompts.py`, import the module with a short alias (`from backend.services import fibs_constants as fc`) instead of bloating the file header with a long multi-line symbol import list.
- **Function Extraction vs. Inline Code Discipline**:
  - **Single-use logic**: If a helper is only called once (and is not a required callback/closure like `re.sub(repl, ...)` or an externally tested public API entry point), inline the code directly at the call site.
  - **Small multi-use helpers**: If a helper is called only a few times and contains only a few lines of code, only extract it as a function if the function definition + Google docstring + call sites are shorter than inlining the expression at each call site.
  - **Zero Trivial Passthrough Wrappers**: Never create trivial 1-statement passthrough wrapper functions across modules (`test_no_trivial_passthrough_wrapper_functions_in_backend_services`).

## 2. Testing, Quality Gates & Backlog
- **TDD & Verification**: Every backend change requires unit tests in `backend/tests/` (`.venv/bin/pytest backend/tests`). UI workflows are tested via Playwright (`npx playwright test`, target < 10 min total). Do not use the browser tool for manual visual inspection unless explicitly requested.
- **Pre-Commit Hook (`.husky/pre-commit`)**: Enforces dependency/model freshness (`scripts/check_dependencies_and_models.py`), `ruff check` (including Google docstrings), `npx eslint frontend/src --max-warnings 0`, `npx tsc --noEmit`, `vulture backend --min-confidence 90`, and `pytest --cov=backend --cov-fail-under=60`.
- **Backlog (`TODO.md`)**: Do not silently fix out-of-scope issues discovered during a task; log verified findings in `TODO.md` (checkbox, priority, affected files, evidence, proposed fix) and mention new entries briefly in your response.

## 3. Offline Runtime, Paths & Repository Separation
- **100% Offline Inference**: Never call external APIs, online tools, or CDNs at runtime, and never trigger dynamic model downloads during document processing. Pre-downloaded models live in `assets/models/{lightonocr,infinity_parser2_flash,docling,gemma}` (or `GEMMA_MODEL_PATH` / `LOCAL_LLM_BASE_URL`).
- **Workspace-Relative Paths Only**: Never hardcode absolute paths (`/Users/...`, `C:\...`); resolve all paths dynamically from `PROJECT_ROOT` / `BASE_DIR` or environment variables.
- **Zero Overfitting (No Test-Data Leakage)**: Extractors, post-processors (`extraction_postprocess.py`, `formula_service.py`, `fibs_postprocess.py`, `docling_extractor.py`), and prompts (`prompts.py`, `llm_service.py`) must remain 100% generic. Never hardcode textbook titles, authors, phrases, or document-specific regexes (enforced by `test_no_test_data_leakage_across_backend_services` and `test_no_hardcoded_test_document_phrases_in_formula_service`).
- **Open License & Companion Repo Separation**:
  - `ebuch-konvertierung` only permits commercially usable open licenses (`CC0`, `CC BY 4.0`, `CC BY-SA 4.0`, `Apache 2.0`, `ODbL 1.0` documented in `testdata/ATTRIBUTIONS.md`). `CC BY-NC*` and AGPL are forbidden (`test_all_repo_test_data_free_of_noncommercial_restrictions_and_publisher_ngrams`).
  - Deterministic synthetic multi-format textbooks (`scripts/generate_schoolbook_suite.py`) provide 100% verified Golden Ground Truths in `testdata/golden/` (must score `100/100` in `lint_markdown`).
  - Proprietary publisher PDFs and their ground truths/leaderboards reside strictly in `../ebuch-testdaten` — zero proprietary filenames or 7-word n-grams may ever enter `ebuch-konvertierung`.

## 4. Pipeline & FIBS 09/2025 Domain Invariants
- **Hybrid VLM-OCR + Docling Fusion (`extraction_postprocess.py`)**:
  - `LightOnOCR-3` (`1536 px` longest edge) and `Infinity-Parser2-Flash` (`1792 px` on GPU / `1536 px` on CPU) render PDF pages via `render_pdf_page_for_vlm(..., grid_factor=32)` so dimensions align with the Qwen3-VL `32×32` patch grid without secondary bicubic resizing.
  - Both engines fuse with `extract_docling_page_layout()` via `fuse_vlm_page_with_docling()` for figure cropping, `TableFormer` flattened-table recovery, `FURNITURE` running header/footer stripping, and BBox heading hierarchy inference.
- **VLM `<Bild>` Descriptions (`vlm_describer.py`, `fibs_formatting.py`, `prompts.py`)**:
  - Execute sequentially with isolated 1-image prompts (never batch multiple images).
  - Pass read-only page context (`image_contexts_for_markdown()`, `[HIER STEHT DAS BILD]`, capped at `VLM_CONTEXT_MAX_CHARS`; prepend the previous page from its last heading when a page does not start with a heading). Resume cache (`vlm_cache.json`) is keyed by `cache_key(path, prompt)`.
  - Output format: multi-line `<Bild> {Bildart}:` / `Beschreibung mit Bildtext: …` (or `Beschreibung: …`) / `</Bild>`. Keep descriptions compact (1–3 sentences, strictly visual facts, zero interpretation; transcribe diagrams structurally using ` \to ` per branch). Drop decorative images only when VLM marks `DEKORATIV: ja` **and** `has_caption_context()` is false.
- **Chunked Gemma Standardisation (`llm_service.py`, `fibs_postprocess.py`)**:
  - Never send a full book in one LLM request. Plan whole-page chunks via `build_standardisation_chunks()` within `GEMMA_REQUEST_TOKEN_BUDGET` (`MAX_PAGES_PER_CHUNK=2`), passing previous/next pages as read-only `[KONTEXT …]` (trimmed via `_clean_chunk_output` and `_trim_to_own_pages`).
  - Words hyphenated across a page break are completed in full on the preceding page before `((num))`.
  - **No Silent Fallback**: Retry a failing Gemma chunk once (restarting `rapid-mlx`); if it fails again, raise `StandardisationError`. `standardise_markdown_fallback()` is only permitted when explicitly enabled (`allow_fallback=True`, `E2E_MOCK=true`, or `ALLOW_RULE_BASED_FALLBACK=1`). Never swallow `StandardisationAborted`.
- **FIBS Structural Rules & Native DOCX Export (`docx_service.py`, `a11y_linter.py`)**:
  - **Table Resolution**: Tables with $\le$ `table_resolve_max_cells` cells (default `6`, persisted in `assets/settings.json` via `settings_service.py`) resolve into linear paragraphs after `<Anmerkung>\nDie folgende Tabelle wurde aufgelöst.\n</Anmerkung>`.
  - **`<Rahmen>`**: Use only for semantic callout/info/method boxes and sidebars (detected via PDF vector geometry `FPDF_PAGEOBJ_PATH` and didactic prefixes), never for visual borders around sequential standard exercises (`### Aufgabe N:`).
  - **Page Mapping & Export**: Map physical page selections (e.g. `45-48`) to relative PDF indices during extraction while preserving physical `((num))` markers. Construct `.docx` files natively via `python-docx` (never Pandoc) with OpenXML `w:bookmarkStart`/`w:bookmarkEnd` (`page_{num}`) for screen readers.

## 5. Async Execution, GPU Sequencing & Task Lifecycle
- **Task-Owned Background Jobs (`task_jobs.py`)**: Long-running work (`extraction`, `standardisation`, `pipeline`) runs inside `start_task_job()` as a task-owned `asyncio.Task` (`task.job`), never inside an HTTP response generator. Client disconnects only detach listener queues; only `POST /api/tasks/{id}/abort` or `DELETE` cancels `task.job` and kills `task.process`.
- **Non-Blocking Event Loop**: In FastAPI routes (`backend/main.py`), use `standardise_markdown_async()` / `optimize_markdown_async()` (`AsyncOpenAI`) and offload synchronous CPU/disk/PDF/DOCX calls via `await asyncio.to_thread(...)`.
- **GPU Serialization & Memory Hygiene**: Concurrent conversion jobs serialize on the per-loop GPU semaphore (`status="queued"`), and every stage boundary calls `release_gpu_memory()` (`close_engine()`, `mx.clear_cache()`, `torch.cuda.empty_cache()`) so OCR, VLM, and Gemma never compete for VRAM / Unified Memory. `rapid-mlx` stays warm for 60s via a sliding idle timer for `/api/optimize`.
- **Sleep Assertions & Watchdog**: Active jobs hold named idempotent sleep assertions (`caffeinate` on macOS / `systemd-inhibit` on Linux) monitored by `heartbeat_loop()`, which detects system sleep/wake, marks orphaned tasks as `interrupted` after 30s, and supports resuming via `POST /api/tasks/{id}/resume`.
