# E-Buch Standard Converter

A strictly offline, local web application that converts educational textbooks (PDF, DOCX, PPTX) into accessible **German E-Buch** format (**Übertragungsregeln FIBS, Stand September 2025**) for blind and visually impaired students.

All document parsing, layout analysis, formula recognition, image description, and FIBS standardisation run **100% locally** using open-source models cleared for commercial and institutional deployment (**Apache 2.0 / MIT / Gemma Terms of Use**).

---

## 🎬 Video Walkthrough & Demo

https://github.com/user-attachments/assets/0e7cdab0-bf90-410b-bbdf-65b978494f86

---

## 1. Supported Hardware & Operating Systems

The converter runs across **macOS**, **Linux**, and **Windows (WSL2 or Native)** and automatically selects the best local inference backend (`cuda` → `mps` → `cpu`):

| Platform / Hardware Profile | Recommended RAM / VRAM | OCR & Layout Engines (`Docling`, `LightOnOCR-3`, `Infinity-Parser2`) | Gemma 4 12B-it (VLM Image Descriptions & FIBS Standardisation) |
| :--- | :--- | :--- | :--- |
| **macOS (Apple Silicon M1–M4)** | **24 GB+ Unified Memory** (16 GB minimum for Docling/LightOnOCR) | Native Metal acceleration via `mlx-vlm` & `torch` (`mps`) | Native 8-bit MLX (`mlx-vlm` + background `rapid-mlx` server on port `8001`) |
| **Linux / Windows with NVIDIA GPU** | **16–24 GB+ VRAM** + 32 GB System RAM | Native **PyTorch CUDA** (`bfloat16`) | **PyTorch CUDA** (`transformers` + optional 4-bit/8-bit `bitsandbytes`) or local OpenAI-compatible server (`vLLM`, `llama.cpp`, `Ollama`) via `LOCAL_LLM_BASE_URL` |
| **CPU-Only Server (Linux / Windows / macOS)** | **16–32 GB System RAM** | **Docling** (~1–3 s/page on digital PDFs) & **LightOnOCR-3-0.8B** (`float32` CPU) | Deterministic FIBS rule engine (`ALLOW_RULE_BASED_FALLBACK=1`) or external local OpenAI server (`LOCAL_LLM_BASE_URL`) |

---

## 2. Step-by-Step Installation

### Step 1: System Prerequisites
Install **Python 3.12+**, **Node.js 20+**, and **LibreOffice** (optional, used for live `.docx` preview rendering in the web UI):

- **macOS (Homebrew):**
  ```bash
  brew install python@3.12 node
  brew install --cask libreoffice
  ```
- **Ubuntu / Debian Linux:**
  ```bash
  sudo apt update && sudo apt install -y python3.12 python3.12-venv python3-pip nodejs npm libreoffice
  ```
- **Windows (WSL2 Ubuntu recommended, or Native PowerShell via `winget`):**
  ```powershell
  winget install Python.Python.3.12 OpenJS.NodeJS.LTS TheDocumentFoundation.LibreOffice
  ```

### Step 2: Create Python Virtual Environment & Install Dependencies
```bash
# Clone the main repository
git clone https://github.com/ffeldhaus/ebuch-konvertierung.git
cd ebuch-konvertierung

# Create and activate virtual environment
python3.12 -m venv .venv
source .venv/bin/activate   # On Windows PowerShell: .\.venv\Scripts\Activate.ps1

# Install Python dependencies (automatically installs MLX on macOS arm64, or PyTorch/bitsandbytes on Linux/Windows)
pip install --upgrade pip
pip install -e ".[dev]"

# Install Frontend dependencies
npm install
```
> **Note for Linux/Windows NVIDIA CUDA users:** Ensure your PyTorch installation matches your system CUDA driver (e.g. `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124`).

### Step 3: Pre-Download Local AI Models (`assets/models/`)
Because the application operates **strictly offline at runtime**, pre-download the model weights once into `assets/models/`:

```bash
# 1. Docling Layout (RT-DETR-v2), TableFormer, CodeFormulaV2 & RapidOCR (~1.2 GB)
.venv/bin/docling-tools models download -o assets/models/docling layout tableformer code_formula rapidocr

# 2. LightOnOCR-3-0.8B (~1.7 GB, Apache 2.0)
.venv/bin/hf download lightonai/LightOnOCR-3-0.8B --local-dir assets/models/lightonocr

# 3. Infinity-Parser2-Flash (~4.5 GB, Apache 2.0)
.venv/bin/hf download infly/Infinity-Parser2-Flash --local-dir assets/models/infinity_parser2_flash
```

#### Gemma 4 12B-it Weights (for VLM `<Bild>` Descriptions & FIBS Text Standardisation):
- **On macOS (Apple Silicon MLX):**
  ```bash
  .venv/bin/hf download mlx-community/gemma-3-12b-it-8bit --local-dir assets/models/gemma/mlx
  ```
- **On Linux / Windows (PyTorch CUDA or CPU via HuggingFace `transformers`):**
  Place the HuggingFace Gemma 12B-it checkpoint in `assets/models/gemma/` (or `assets/models/gemma/hf/`, or point `GEMMA_MODEL_PATH=/path/to/model`).
  - To enable 4-bit or 8-bit quantization on 12–16 GB CUDA GPUs, set `GEMMA_LOAD_IN_4BIT=1` or `GEMMA_LOAD_IN_8BIT=1`.
  - Alternatively, if you serve Gemma via a local **vLLM**, **llama.cpp**, or **Ollama** instance, set `LOCAL_LLM_BASE_URL=http://127.0.0.1:8001/v1` (and optionally `LOCAL_LLM_MODEL_NAME`).

---

## 3. Starting the Application

Start both the FastAPI backend (`http://localhost:8000`) and Vite frontend (`http://localhost:3000`) with a single command:

```bash
npm start
```

Or run them in two separate terminals:
```bash
# Terminal 1 – FastAPI Backend (port 8000)
.venv/bin/uvicorn backend.main:app --reload --port 8000

# Terminal 2 – Vite Frontend (port 3000)
npm run dev
```
Open **[http://localhost:3000](http://localhost:3000)** in your browser.

---

## 4. Extraction Engines & Application Modes

### Extraction Engine Overview

| Dimension | **Docling** (IBM Research) | **LightOnOCR-3-0.8B** + Docling Layout | **Infinity-Parser2-Flash** + Docling Layout |
| :--- | :--- | :--- | :--- |
| **Best Used For** | Digital (vector-native) PDFs, `.docx`, `.pptx` at high speed (~0.5–2 s/page) | Scans, complex STEM LaTeX formulas & tables with low VRAM (~1.7 GB) | Dense multi-column STEM textbooks & complex scans (~4.5 GB VRAM) |
| **Architecture** | `docling-layout-heron` + `TableFormer` + `CodeFormulaV2` | End-to-end VLM (`0.8B`) + CPU Docling layout & `TableFormer` | End-to-end VLM (`2B`) + CPU Docling layout & `TableFormer` |
| **Supported Formats** | PDF, DOCX, PPTX, XLSX, HTML, Images | PDF, Images | PDF, Images |
| **License** | **MIT / Apache 2.0** | **Apache 2.0** | **Apache 2.0** |

### Workspace Modes (Top Navigation Dropdown)
1. **📄 Übertragung (Conversion Workspace):** Upload a textbook PDF/DOCX, select physical page ranges (e.g. `45-48`) or chapters, run layout extraction and FIBS 09/2025 standardisation (`((num))` page markers, `<Rahmen>`, `<Bild>`, `<Tabelle>`, `<Anmerkung>`, difficulty symbols `○ [leicht]` / `◐ [mittel]` / `● [schwer]`), inspect live diffs and accessibility linter checks (`a11y_linter.py`), and export screen-reader-ready Word `.docx` files with native OpenXML page bookmarks (`w:bookmarkStart` / `w:bookmarkEnd`).
2. **⚖️ Benchmark & Evaluierung:** Upload any PDF and a manual ground-truth reference (`.md` or `.docx`) to compare extraction engines side-by-side across all FIBS quality dimensions.
3. **💬 Feedback:** Upload a manually revised transfer alongside the original conversion and optional marked PDF regions. Gemma analyzes systematic differences, applies a 12-word verbatim copyright redaction guard, and generates a structured developer report (`assets/feedback/<task_id>/<feedback_id>/report.md`).
4. **⚙️ Einstellungen:** Configure persistent FIBS formatting rules (`assets/settings.json`), such as the maximum cell count for automatic table resolution (`table_resolve_max_cells`, default `6`).

### Task Lifecycle, Sleep Prevention & Resume
- Conversion jobs run as server-owned background tasks (`backend/services/task_jobs.py`); closing the browser tab never aborts active conversions.
- While a job is active, the backend prevents system idle sleep via `caffeinate` (macOS) or `systemd-inhibit` (Linux).
- Sequential GPU memory management (`release_gpu_memory()`) automatically unloads OCR weights and clears Metal/CUDA caches (`mx.clear_cache()` / `torch.cuda.empty_cache()`) before starting VLM image descriptions or text standardisation.
- Interrupted tasks can be resumed via **Fortsetzen** (`POST /api/tasks/{id}/resume`), reusing cached image descriptions from `vlm_cache.json`.

---

## 5. Connecting the Companion Test Suite (`../ebuch-testdaten`) & Running Benchmarks

### Repository Split (Open vs. Private Publisher Corpus)
- **`./ebuch-konvertierung` (this repository — Open Source):** Contains the full application code and **19 open/synthetic benchmark textbooks** in `testdata/` (12 deterministic single-subject schoolbooks across 4 page geometries generated by `scripts/generate_schoolbook_suite.py`, plus 7 OER textbook excerpts under CC0 / CC BY 4.0 / CC BY-SA 4.0; see [`testdata/ATTRIBUTIONS.md`](testdata/ATTRIBUTIONS.md)).
- **`../ebuch-testdaten` (private companion repository):** Contains **50 real publisher sample/test PDFs** (706 pages across 5 major German schoolbook publishers with NRW focus) and **100 verified Golden Ground Truths** (`100/100` in `a11y_linter`). Clone it as a sibling directory next to `ebuch-konvertierung`:
  ```bash
  cd ..
  git clone https://github.com/ffeldhaus/ebuch-testdaten.git
  cd ebuch-konvertierung
  ```
  When `--external-data-dir ../ebuch-testdaten` is passed, all benchmark outputs and leaderboards containing publisher filenames are written exclusively inside `../ebuch-testdaten/benchmarks/` so zero proprietary data ever enters `ebuch-konvertierung`.

### Decoupled & End-to-End Benchmark Modes (`scripts/run_benchmark.py`)
`scripts/run_benchmark.py` supports 5 execution modes (`--mode {fast,ocr,gemma,smoke,full}`), suites (`--suite {smoke,core,schoolbooks,open_all,external,full}`), and incremental checkpointing (`--checkpoint-file`, `--resume`):

```bash
# 1. Fast Regression (~30s): Docling + deterministic FIBS rules across all 19 open textbooks
.venv/bin/python scripts/run_benchmark.py --mode fast

# 2. Track A – OCR Engine Comparison (deterministic FIBS post-processing, no LLM overhead):
#    Evaluates Docling, LightOnOCR-3-0.8B, and Infinity-Parser2-Flash side-by-side
.venv/bin/python scripts/run_benchmark.py --mode ocr --suite smoke

# 3. Track B – Gemma 4 12B Standardisation Only (reuses cached raw extractions from Track A):
.venv/bin/python scripts/run_benchmark.py --mode gemma --suite smoke \
  --from-ocr-run benchmarks/runs/run_<YYYYMMDD_HHMMSS>.json

# 4. End-to-End Smoke Test (3 representative docs across all 3 engines + Gemma 4 12B + LLM Judge):
.venv/bin/python scripts/run_benchmark.py --mode smoke \
  --checkpoint-file benchmarks/runs/checkpoint_smoke.json --resume

# 5. Full Benchmark across Open + External Publisher Corpus (resumable batches):
.venv/bin/python scripts/run_benchmark.py --mode full --external-data-dir ../ebuch-testdaten \
  --batch-size 5 --batch-index 0 --checkpoint-file ../ebuch-testdaten/benchmarks/runs/checkpoint_full.json --resume

# Refresh benchmarks/LEADERBOARD.md from existing run JSONs without re-running models:
.venv/bin/python scripts/run_benchmark.py --update-leaderboard-only

# Diagnose specific engine bottlenecks on the latest benchmark run:
.venv/bin/python scripts/analyze_benchmark_run.py --details
```

See [`benchmarks/LEADERBOARD.md`](benchmarks/LEADERBOARD.md) for current multi-tier standings and metric definitions.

---

## 6. Testing & Static Verification

```bash
# Backend unit & anti-overfitting test suite (pytest)
.venv/bin/pytest backend/tests

# Frontend TypeScript type-check & ESLint
npx tsc --noEmit
npm run lint

# Python dead-code check (vulture)
npm run dead-code

# End-to-End Playwright browser tests
npx playwright test

# Verify the private companion repository (if cloned at ../ebuch-testdaten)
.venv/bin/python ../ebuch-testdaten/scripts/verify_testdaten.py
```

---

## 7. Licensing Summary

This project is released under the **MIT License (see [`LICENSE`](LICENSE))**.

All integrated models and libraries are cleared for free commercial and institutional deployment across schools, *Blindenstudienanstalten*, and *Landesmedienzentren*:

| Component | License | Commercial & Institutional Status |
| :--- | :--- | :--- |
| **Docling & TableFormer** (IBM Research) | **MIT / Apache 2.0** | ✅ Unrestricted commercial & institutional use |
| **LightOnOCR-3-0.8B** (LightOn AI) | **Apache 2.0** | ✅ Unrestricted commercial & institutional use |
| **Infinity-Parser2-Flash** (INF Tech) | **Apache 2.0** | ✅ Unrestricted commercial & institutional use |
| **Gemma 4 12B-it** (Google) | **Gemma Terms of Use** | ✅ Royalty-free commercial & institutional deployment |
| **Backend & Frontend Stack** (`FastAPI`, `python-docx`, `pypdfium2`, `ReportLab`, `Vite`) | **MIT / Apache 2.0 / BSD-3-Clause** | ✅ Unrestricted (avoids AGPL dependencies like PyMuPDF/fitz) |
| **Open Benchmark Corpus** (`testdata/`) | **CC0 1.0 / CC BY 4.0 / CC BY-SA 4.0 / ODbL 1.0** | ✅ Full attribution in [`testdata/ATTRIBUTIONS.md`](testdata/ATTRIBUTIONS.md) |
