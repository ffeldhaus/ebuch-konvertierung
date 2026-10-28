---
name: ebuch-benchmark
description: >-
  Run, analyze, and maintain multi-engine E-Buch benchmarks (scripts/run_benchmark.py,
  scripts/analyze_benchmark_run.py, backend/services/custom_benchmark_service.py)
  and the Multi-Tier Leaderboard (benchmarks/LEADERBOARD.md). Activate this skill
  whenever the user asks to run benchmarks, compare OCR/LLM engines, inspect
  benchmark runs, or update benchmark scoring and leaderboards.
---

# E-Buch Multi-Engine Benchmark & Leaderboard Workflow

The benchmarking suite provides programmatic validation, LLM-as-a-Judge scoring, and regression tracking against verified **Golden Ground Truth** references across both open repository textbooks (`testdata/`, 19 docs) and external publisher samples (`--external-data-dir ../ebuch-testdaten`, 50 docs).

## 1. Execution Profiles (`--mode`) & Suites (`--suite`)

- **`--mode fast`**: Runs `docling` + deterministic FIBS post-processing (`post_process_structure`, no LLM/VLM) across `--suite open_all` (all 19 open documents) in ~30s for fast CI/regression checks.
- **`--mode ocr` (Track A — OCR Engine Comparison)**: Evaluates all 3 OCR engines (**Docling**, **Infinity-Parser2-Flash**, **LightOnOCR-3-0.8B**) using deterministic FIBS post-processing (`post_process_structure`, no Gemma LLM overhead) so OCR/layout accuracy can be compared rapidly and cached.
- **`--mode gemma` (Track B — Gemma Standardisation Only)**: Runs **Gemma 4 12B** standardisation + **Gemma LLM-as-a-Judge** on top of cached raw extractions from a previous run (`--from-ocr-run <run_json>`), avoiding redundant OCR re-extraction when iterating on prompts or FIBS post-processing.
- **`--mode smoke`**: Runs all 3 engines + **Gemma 4 12B** standardisation + **Gemma LLM-as-a-Judge** end-to-end on a 3-document smoke slice (`1 core` + `1 generated schoolbook` + `1 external publisher PDF` cropped to its 4 benchmark pages).
- **`--mode full`**: Runs all 3 engines + Gemma 4 12B standardisation + VLM image descriptions + Gemma LLM-as-a-Judge across `--suite full` (19 open + 50 external publisher documents = 69 documents).
- **Suites (`--suite`)**: `smoke` (3 docs), `core` (4 baseline docs), `schoolbooks` (12 generated multi-format schoolbooks), `open_all` (all 19 open repository docs), `external` (50 publisher PDFs in `../ebuch-testdaten`), and `full` (all 69 docs).
- **Checkpointing & Batching**: Supports incremental persistence after every `(document, engine)` pair via `--checkpoint-file <path>` and `--resume`, deterministic batch slicing via `--batch-size N --batch-index I` and `--max-docs N`, and leaderboard-only regeneration via `--update-leaderboard-only`.

## 2. Composite Scoring & Leaderboard Policy

- **De-Saturated Composite Score (`compute_doc_composite`, 100%)**:
  - **Stage 1 (Raw Layout & OCR)**: `Word Recall 15% + Flow 10% + Judge 20% + Tables 15% + Formulas 15% + Headings 10% + <Bild> 10% + A11y 5% = 100%`
  - **Stage 2 (Übertragungsregeln 09/2025)**: `Word Recall 15% + Flow 10% + Judge 18% + Tables 12% + Formulas 12% + Headings 10% + <Bild> 10% + <Rahmen> 8% + A11y 5% = 100%`
  - Weights dynamically re-normalize when a document has no ground-truth tables, formulas, images, or `<Rahmen>` boxes.
  - `evaluate_a11y(pred_md, raw_markdown=..., expected_pages=...)` runs the full FIBS `lint_markdown()` checker including source-aware completeness checks (missing page markers and omitted captioned images).
- **Multi-Tier Leaderboard Policy (`benchmarks/LEADERBOARD.md`)**:
  - Tracks `⚡ Fast Regression`, `🔍 Track A — OCR Engine Comparison`, `🧠 Track B / 🔥 Smoke Multi-Engine + Gemma`, and `🏛️ Full Benchmark` side-by-side without fast/smoke runs overwriting full multi-engine standings.
  - **Strict Repository Separation**: When external data is evaluated, external publisher rows and filenames are written **exclusively** to `../ebuch-testdaten/benchmarks/LEADERBOARD.md` while keeping the open repo's `benchmarks/LEADERBOARD.md` 100% free of proprietary references.

## 3. CLI Commands Reference

- **Fast Regression Benchmark (~30s, Docling + deterministic FIBS rules on all 19 open docs):**
  ```bash
  .venv/bin/python scripts/run_benchmark.py --mode fast
  ```
- **Decoupled Track A (All 3 OCR Engines) & Track B (Gemma on Cached Extractions):**
  ```bash
  .venv/bin/python scripts/run_benchmark.py --mode ocr --suite smoke
  .venv/bin/python scripts/run_benchmark.py --mode gemma --suite smoke --from-ocr-run benchmarks/runs/run_<id>.json
  ```
- **Multi-Engine + Gemma 4 12B Smoke Benchmark:**
  ```bash
  .venv/bin/python scripts/run_benchmark.py --mode smoke --checkpoint-file benchmarks/runs/checkpoint_smoke.json --resume
  ```
- **Official Full Multi-Engine Benchmark in Resumable Batches:**
  ```bash
  .venv/bin/python scripts/run_benchmark.py --mode full --external-data-dir ../ebuch-testdaten --batch-size 5 --batch-index 0 --checkpoint-file ../ebuch-testdaten/benchmarks/runs/checkpoint_full.json --resume
  ```
- **Run Diagnostics & Bottleneck Analysis (`scripts/analyze_benchmark_run.py`):**
  ```bash
  .venv/bin/python scripts/analyze_benchmark_run.py --details
  .venv/bin/python scripts/analyze_benchmark_run.py --external-data-dir ../ebuch-testdaten --details
  ```
