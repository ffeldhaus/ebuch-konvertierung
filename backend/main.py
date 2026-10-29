"""FastAPI backend application and HTTP endpoints for E-Buch conversion."""

import asyncio
import json
import logging
import os
import re
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

from backend.services.a11y_linter import autofix_markdown, lint_markdown
from backend.services.custom_benchmark_service import evaluate_custom_submission
from backend.services.diff_service import get_diff_highlighting
from backend.services.docx_service import convert_markdown_to_docx
from backend.services.extraction_service import (
    detect_physical_start_page,
    extract_pdf_pages,
    get_pdf_page_count,
    run_background_extraction,
    validate_pages_string,
)
from backend.services.fibs_constants import FEEDBACK_EXTENSIONS, TRANSFER_EXTENSIONS
from backend.services.llm_service import (
    close_engine,
    optimize_markdown_async,
    release_gpu_memory,
    standardise_markdown_async,
    suggest_char_replacements_async,
)
from backend.services.models import (
    CharSuggestRequest,
    CharSuggestResponse,
    DomainModel,
    LayoutBlock,
    TaskLayoutResponse,
)
from backend.services.pdf_render_service import normalize_bbox_to_1000
from backend.services.task_manager import TaskManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Keep strong references to background asyncio tasks to prevent them from being garbage-collected
_BACKGROUND_TASKS = set()
_BENCHMARK_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bench_worker")

# ---------------------------------------------------------------------------
# GPU / Environment Configuration
# ---------------------------------------------------------------------------
# Allow PyTorch to use unrestricted MPS (Apple Metal GPU) memory on macOS.
if sys.platform == "darwin":
    os.environ.setdefault("PYTORCH_MPS_HIGH_WATERMARK_RATIO", "0.0")

# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks."""
    # Log GPU availability on startup across CUDA, Apple Metal (MPS), and CPU
    try:
        import torch
        if torch.cuda.is_available():
            dev_name = torch.cuda.get_device_name(0)
            logger.info(f"✅ NVIDIA CUDA GPU detected ({dev_name}) — OCR/Layout/LLM engines will use CUDA acceleration")
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            logger.info("✅ Apple Metal (MPS) GPU detected — OCR/Layout/LLM engines will use GPU acceleration")
        else:
            logger.info("ℹ️  No CUDA/MPS GPU detected — OCR/Layout engines will run on CPU")
    except ImportError:
        logger.info("⚠️  PyTorch not installed — GPU detection skipped")

    # Resume any interrupted benchmark tasks from disk
    from backend.services.benchmark_task_manager import benchmark_task_manager
    resumed_ids = benchmark_task_manager.resume_unfinished_tasks()
    if resumed_ids:
        logger.info(f"🔄 Unterbrochene Benchmark-Tasks erfolgreich wiederaufgenommen: {resumed_ids}")

    # Heartbeat: wake-from-sleep logging, orphaned-task watchdog, caffeinate health.
    from backend.services.task_jobs import heartbeat_loop
    heartbeat = asyncio.create_task(heartbeat_loop(lambda: list(task_manager._tasks.values())))

    yield  # Application runs here

    heartbeat.cancel()
    # Shutdown: cancel running jobs (kills subprocesses, releases sleep assertions)
    from backend.services.task_jobs import cancel_task_job
    for t in list(task_manager._tasks.values()):
        if t.job_running():
            cancel_task_job(t)
    # Shutdown: stop rapid-mlx server
    close_engine()


app = FastAPI(
    title="E-Buch Standard Konverter Backend",
    version="0.2.0",
    lifespan=lifespan,
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Workspace directories
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "assets", "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "assets", "output")
# Feedback artifacts (revised transfer, PNG regions, Gemma reports) are kept
# outside the task output dir so they never interfere with markdown recovery.
FEEDBACK_DIR = os.path.join(BASE_DIR, "assets", "feedback")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(FEEDBACK_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Task management
# ---------------------------------------------------------------------------
task_manager = TaskManager(discover_disk=True)

# Legacy compatibility: expose active_tasks dict for tests that import it
# This is a reference to the internal dict — tests can use it directly.
active_tasks = task_manager._tasks

# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------

class StandardiseRequest(DomainModel):
    """Request payload for standardising extracted Markdown into FIBS format."""

    task_id: str
    """Unique identifier of the conversion task."""
    markdown: str
    """Raw extracted Markdown text to standardise."""
    ruleset: str
    """Custom FIBS ruleset instructions or empty string for defaults."""
    describe_images: bool | None = True
    """Whether to run VLM `<Bild>` image descriptions before Gemma standardisation."""


class OptimizeRequest(DomainModel):
    """Request payload for interactively optimizing a Markdown selection or document."""

    task_id: str
    """Unique identifier of the conversion task."""
    prompt: str
    """User instruction describing the desired optimization."""
    current_markdown: str
    """Current Markdown content to optimize."""
    ruleset: str
    """Custom FIBS ruleset instructions applied during optimization."""


class DiffRequest(DomainModel):
    """Request payload for computing inline diff highlighting between two Markdown texts."""

    raw: str
    """Original or raw Markdown baseline text."""
    std: str
    """Standardised or revised Markdown text to compare against raw."""


class LintRequest(DomainModel):
    """Request payload for running the FIBS 09/2025 accessibility linter."""

    markdown: str
    """Standardised Markdown text to inspect for FIBS compliance."""
    task_id: str | None = None
    """Optional conversion task ID used to resolve raw Markdown or expected page count."""
    raw_markdown: str | None = None
    """Optional raw OCR Markdown used for cross-checking content retention."""
    expected_pages: int | None = None
    """Optional expected number of `((num))` page markers."""
    table_max_cells: int | None = None
    """Optional cell threshold above which tables may remain unresolved."""


class ExportRequest(DomainModel):
    """Request payload for exporting standardised FIBS Markdown to a native `.docx` file."""

    task_id: str
    """Unique identifier of the conversion task."""
    markdown: str
    """Standardised FIBS Markdown content to convert into DOCX."""
    template_mode: str | None = "default"
    """DOCX styling template mode ('default' or 'accessible_large')."""

# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Step 1: Upload a PDF or DOCX file.
    Saves the file to local uploads directory and returns a task_id.
    """
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in [".pdf", ".docx"]:
        raise HTTPException(
            status_code=400, detail="Only PDF and DOCX files are supported."
        )

    task_id = str(uuid.uuid4())
    filename = f"{task_id}{file_ext}"
    input_path = os.path.join(UPLOAD_DIR, filename)

    try:
        content = await file.read()
        with open(input_path, "wb") as buffer:
            buffer.write(content)
    except Exception as e:
        logger.error(f"Failed to save uploaded file: {e}")
        raise HTTPException(status_code=500, detail="Failed to save uploaded file.")

    from backend.services.directory_service import (
        check_document_directories,
        save_directory_info,
    )

    page_count = 0
    physical_start_page = 1
    directory_info = await asyncio.to_thread(
        check_document_directories, input_path, max_pages=20
    )
    if file_ext == ".pdf":
        page_count = await asyncio.to_thread(get_pdf_page_count, input_path)
        physical_start_page = await asyncio.to_thread(
            detect_physical_start_page, input_path, directory_info=directory_info
        )

    task = await task_manager.create(
        task_id=task_id,
        original_name=file.filename,
        input_path=input_path,
        extension=file_ext,
        page_count=page_count,
    )
    task.physical_start_page = physical_start_page
    task.directory_info = directory_info
    await asyncio.to_thread(
        save_directory_info, os.path.join(OUTPUT_DIR, task_id), directory_info
    )

    if directory_info and directory_info.get("has_any_directory"):
        detected_str = ", ".join(directory_info.get("detected_types") or [])
        task.logs.append(
            f"[Verzeichnis-Check] Erkannt: {detected_str} "
            f"(geprüfte Seiten: {directory_info.get('checked_pages', 0)}, "
            f"Startseite: {physical_start_page})."
        )
    task.save_meta()

    logger.info(
        f"File uploaded successfully: {file.filename} -> task_id: {task_id}, "
        f"page_count: {page_count}, physical_start_page: {physical_start_page}, "
        f"directories: {directory_info.get('detected_types') if directory_info else []}"
    )
    return {
        "task_id": task_id,
        "filename": file.filename,
        "page_count": page_count,
        "physical_start_page": physical_start_page,
        "directories": directory_info,
    }


@app.post("/api/pdf/page-count")
async def get_pdf_page_count_endpoint(file: UploadFile = File(...)):
    """Extracts and returns the total page count, detected physical start page, and detected directories of an uploaded PDF."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
        content = await file.read()
        tmp.write(content)
        
    try:
        from backend.services.directory_service import check_document_directories
        page_count = await asyncio.to_thread(get_pdf_page_count, tmp_path)
        directory_info = await asyncio.to_thread(
            check_document_directories, tmp_path, max_pages=20
        )
        physical_start = await asyncio.to_thread(
            detect_physical_start_page, tmp_path, directory_info=directory_info
        )
        return {
            "filename": file.filename,
            "page_count": page_count,
            "physical_start_page": physical_start,
            "directories": directory_info,
        }
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


@app.post("/api/extract")
async def extract_markdown(
    task_id: str = Form(...),
    pages: str = Form(None),
    method: str = Form("auto"),
    lang: str = Form("en"),
    engine: str = Form("infinity"),
):
    """Step 2: Run extraction (LightOnOCR-3, Infinity-Parser2-Flash, or Docling) on the uploaded document.
    Streams progress logs, ending with the extracted Markdown payload.
    """
    task = await task_manager.get(task_id)
    if not task:
        raise HTTPException(
            status_code=404, detail="Task not found. Please upload the file again."
        )

    # If task is not actively running (e.g. pending, completed, failed, or aborted),
    # reset it so a new extraction with fresh parameters / engine / pages can run cleanly.
    if task.status != "processing":
        task.reset_for_new_extraction()

    # Create client queue for real-time logs
    client_queue = asyncio.Queue()
    task.listeners.append(client_queue)

    # Start task in background if it's currently pending
    if task.status == "pending":
        # Validate pages selection
        if pages and task.extension == ".pdf":
            page_count = task.page_count
            if page_count == 0:
                page_count = get_pdf_page_count(task.input_path)
                task.page_count = page_count

            if page_count > 0:
                is_valid, err_msg = validate_pages_string(
                    pages, page_count, physical_start=task.physical_start_page
                )
                if not is_valid:
                    raise HTTPException(status_code=400, detail=err_msg)

        task.pages = pages
        task.method = method
        task.lang = lang
        task.engine = engine
        task.status = "processing"
        if not task.started_at:
            task.started_at = time.time()
        task.save_meta()

        # Release GPU memory before extraction (GPU sequencing)
        release_gpu_memory()

        task_coro = run_background_extraction(
            task=task.__dict__,
            input_path=task.input_path,
            output_root=os.path.join(OUTPUT_DIR, task_id),
            upload_dir=UPLOAD_DIR,
            pages_str=pages,
            method=method,
            lang=lang,
            backend="vlm-engine",
            engine=engine,
        )
        from backend.services.task_jobs import start_task_job
        # Task-owned job: survives client disconnects; extraction closes its listeners itself.
        start_task_job(task, "extraction", task_coro, close_listeners_on_finish=False)
    else:
        # If already actively processing (concurrent client attaching to in-flight extraction), yield all historical logs first
        for past_log in task.logs:
            await client_queue.put(
                f'{{"status": "log", "message": {json.dumps(past_log)}}}\n'
            )

    async def log_stream_generator():
        try:
            while True:
                msg = await client_queue.get()
                if msg is None:  # End of stream
                    break
                yield msg
        except asyncio.CancelledError:
            pass
        finally:
            # Unregister queue when client disconnects
            if client_queue in task.listeners:
                task.listeners.remove(client_queue)

    return StreamingResponse(
        log_stream_generator(), media_type="application/x-ndjson"
    )


@app.get("/api/tasks")
async def get_tasks():
    """List all active document conversion tasks."""
    tasks = await task_manager.list_all()
    logger.debug(f"get_tasks called: found {len(tasks)} tasks")
    return [t.to_summary_dict() for t in tasks]


@app.get("/api/tasks/{task_id}/state")
async def get_task_state(task_id: str):
    """Retrieve full state of a task (markdown, etc.) for reattaching."""
    task = await task_manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task.to_state_dict()


def _load_task_layout_blocks(task_id: str) -> list[LayoutBlock]:
    """Loads layout blocks with ``bbox_1000`` from ``*_content_list.json`` in the task output directory.

    Args:
        task_id: Conversion task identifier.

    Returns:
        List of ``LayoutBlock`` domain models.
    """
    import glob

    task_dir = os.path.join(OUTPUT_DIR, task_id)
    if not os.path.isdir(task_dir):
        return []

    json_files = sorted(
        glob.glob(os.path.join(task_dir, "**", "*_content_list.json"), recursive=True)
    )
    if not json_files:
        json_files = sorted(
            glob.glob(os.path.join(task_dir, "**", "*content_list*.json"), recursive=True)
        )
    if not json_files:
        return []

    try:
        with open(json_files[0], encoding="utf-8") as f:
            raw_data = json.load(f)
    except Exception as exc:
        logger.warning(f"Could not read layout JSON for task {task_id}: {exc}")
        return []

    if isinstance(raw_data, dict):
        raw_blocks = raw_data.get("blocks", raw_data.get("content", []))
    elif isinstance(raw_data, list) and raw_data and isinstance(raw_data[0], list):
        raw_blocks = []
        for p_idx, page_list in enumerate(raw_data):
            for entry in page_list:
                if isinstance(entry, dict):
                    item_copy = dict(entry)
                    item_copy.setdefault("page_idx", p_idx)
                    raw_blocks.append(item_copy)
    elif isinstance(raw_data, list):
        raw_blocks = raw_data
    else:
        raw_blocks = []

    layout_blocks: list[LayoutBlock] = []
    for b in raw_blocks:
        if not isinstance(b, dict):
            continue
        b_type = str(b.get("type") or b.get("label") or "text").strip()
        text = str(b.get("text") or "").strip()
        page_idx = int(b.get("page_idx", 0) or 0)
        text_level_raw = b.get("text_level")
        text_level = int(text_level_raw) if isinstance(text_level_raw, (int, float)) else None
        is_callout = bool(b.get("is_callout_box", False))

        bbox_1000 = b.get("bbox_1000")
        if (
            isinstance(bbox_1000, list)
            and len(bbox_1000) == 4
            and all(isinstance(v, (int, float)) for v in bbox_1000)
        ):
            norm_bbox = [max(0, min(1000, int(round(v)))) for v in bbox_1000]
        else:
            norm_bbox = None
            raw_bbox = b.get("bbox")
            if (
                isinstance(raw_bbox, list)
                and len(raw_bbox) == 4
                and all(isinstance(v, (int, float)) for v in raw_bbox)
            ):
                x1, y1, x2, y2 = (
                    float(raw_bbox[0]),
                    float(raw_bbox[1]),
                    float(raw_bbox[2]),
                    float(raw_bbox[3]),
                )
                # Synthetic heading height bbox [0, 0, w, single_h] is not a spatial page box unless valid coordinates are given
                if not (x1 == 0.0 and y1 == 0.0 and y2 <= 30.0):
                    if max(x2, y2) <= 1000.0 and x2 > x1 and y2 > y1:
                        norm_bbox = [
                            max(0, min(1000, int(round(x1)))),
                            max(0, min(1000, int(round(y1)))),
                            max(0, min(1000, int(round(x2)))),
                            max(0, min(1000, int(round(y2)))),
                        ]
                    else:
                        norm_bbox = normalize_bbox_to_1000(
                            [x1, y1, x2, y2],
                            595.0,
                            842.0,
                            coord_origin="TOPLEFT",
                        )

        if norm_bbox is None:
            continue

        layout_blocks.append(
            LayoutBlock(
                type=b_type,
                text=text,
                page_idx=page_idx,
                bbox_1000=norm_bbox,
                text_level=text_level,
                is_callout_box=is_callout,
            )
        )
    return layout_blocks


@app.get("/api/tasks/{task_id}/layout", response_model=TaskLayoutResponse)
async def get_task_layout(task_id: str) -> TaskLayoutResponse:
    """Returns extracted layout blocks with ``bbox_1000`` coordinates for a conversion task."""
    task = await task_manager.get(task_id)
    task_dir = os.path.join(OUTPUT_DIR, task_id)
    if not task and not os.path.isdir(task_dir):
        raise HTTPException(status_code=404, detail="Task not found.")

    physical_start = int(getattr(task, "physical_start_page", 1) or 1) if task else 1
    blocks = await asyncio.to_thread(_load_task_layout_blocks, task_id)
    return TaskLayoutResponse(
        task_id=task_id,
        physical_start_page=physical_start,
        blocks=blocks,
    )


@app.post("/api/char-replacements/suggest", response_model=CharSuggestResponse)
async def suggest_char_replacements_endpoint(
    payload: CharSuggestRequest,
) -> CharSuggestResponse:
    """Generates Eurobraille/LaTeX replacement suggestions for non-Latin1 characters."""
    suggestions = await suggest_char_replacements_async(payload.chars)
    return CharSuggestResponse(suggestions=suggestions)


@app.get("/api/tasks/{task_id}/images/{image_name}")
async def get_task_image(task_id: str, image_name: str):
    """Serve an image extracted from a document conversion task."""
    task_dir = os.path.join(OUTPUT_DIR, task_id)
    if not os.path.exists(task_dir):
        raise HTTPException(status_code=404, detail="Task folder not found.")

    # Search recursively for the image name in the task folder
    for root, dirs, files in os.walk(task_dir):
        if image_name in files:
            img_path = os.path.join(root, image_name)
            return FileResponse(img_path)

    raise HTTPException(status_code=404, detail="Image not found in task directory.")


@app.post("/api/tasks/{task_id}/abort")
async def abort_task(task_id: str):
    """Abort an active document conversion task."""
    task = await task_manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    task.request_abort()
    logger.info(f"User requested abort for conversion task: {task_id}")

    # Cancel the task-owned job and kill its subprocess. The job's own finally block
    # releases its (named, idempotent) sleep assertion exactly once.
    from backend.services.task_jobs import cancel_task_job
    cancel_task_job(task)

    try:
        from backend.services.llm_service import release_gpu_memory
        release_gpu_memory()
    except Exception:
        pass

    # Notify listeners that task is aborted
    for queue in list(task.listeners):
        try:
            await queue.put(
                '{"status": "aborted", "message": "Konvertierung wurde auf Benutzerwunsch abgebrochen."}\n'
            )
            await queue.put(None)
        except Exception:
            pass

    return {"status": "aborted", "task_id": task_id}


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    """Cancel background extraction (if running), delete files, and remove task."""
    task = await task_manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    # 1. Cancel the task-owned job and kill its subprocess (if running)
    if task.job_running() or task.process is not None:
        from backend.services.task_jobs import cancel_task_job
        task.is_abort_requested = True
        cancel_task_job(task)
        logger.info(f"Terminated background job for task: {task_id}")

    # Notify listeners that task is deleted
    for queue in list(task.listeners):
        try:
            await queue.put(
                '{"status": "error", "message": "Prozess wurde abgebrochen."}\n'
            )
            await queue.put(None)
        except Exception:
            pass

    # 2. Delete folders from disk
    import shutil

    if os.path.exists(task.input_path):
        try:
            os.remove(task.input_path)
        except Exception as e:
            logger.warning(f"Failed to delete uploaded file: {task.input_path}: {str(e)}")

    output_root = os.path.join(OUTPUT_DIR, task_id)
    if os.path.exists(output_root):
        try:
            shutil.rmtree(output_root)
        except Exception as e:
            logger.warning(f"Failed to delete output dir {output_root}: {str(e)}")

    # Also delete selected temp pdf if exists
    selected_pdf_path = os.path.join(UPLOAD_DIR, "selected", f"{task_id}.pdf")
    if os.path.exists(selected_pdf_path):
        try:
            os.remove(selected_pdf_path)
        except Exception:
            pass

    # 3. Remove from task manager
    await task_manager.delete(task_id)

    return {"status": "deleted", "task_id": task_id}


def _standardise_events(task, request: StandardiseRequest):
    """Step 3 pipeline: VLM image descriptions + Gemma standardisation.

    Returns an async generator yielding NDJSON event lines. It is executed by the
    task-owned background job (:func:`_run_standardise_job`) and never directly by
    an HTTP response, so client disconnects cannot cancel it. Sleep prevention is
    handled by the job runner (``task_jobs.start_task_job``).
    """

    async def standardise_generator():
        try:
            # Helper to log and update progress
            def log_progress(percent: int, phase: str, log_msg: str = None):
                task.touch()
                task.progress = {
                    "percent": percent,
                    "phase": phase,
                    "current": 0,
                    "total": 0
                }
                if log_msg:
                    task.logs.append(log_msg)
                # Listeners are fed by the job runner (_run_standardise_job), which
                # publishes every yielded event line – no direct push here.

            # Determine if we have a PDF file and want multimodal input
            image_paths = None
            loop = asyncio.get_event_loop()
            
            should_describe = bool(getattr(request, "describe_images", True))

            # Pre-process raw markdown to describe images using the local VLM
            markdown_to_process = request.markdown
            if markdown_to_process:
                from backend.services.extraction_postprocess import sanitize_runaway_repetitions
                markdown_to_process = sanitize_runaway_repetitions(markdown_to_process)
            
            # Candidate directories where extractors place extracted images
            candidate_dirs = [
                task.image_dir,
                os.path.join(OUTPUT_DIR, request.task_id, "images"),
                os.path.join(OUTPUT_DIR, request.task_id, "auto", "images"),
                os.path.join(OUTPUT_DIR, request.task_id, request.task_id, "auto", "images"),
                os.path.join(OUTPUT_DIR, request.task_id, "docling", "images"),
                os.path.join(OUTPUT_DIR, request.task_id, "infinity", "images"),
                os.path.join(OUTPUT_DIR, request.task_id, "lightonocr", "images"),
            ]
            valid_image_dirs = [d for d in candidate_dirs if d and os.path.exists(d)]
            
            if valid_image_dirs:
                pattern = r"(?s)!\[(.*?)\]\((?:images/)?([^)]+)\)"
                wrapped_pattern = r"(?s)<Bild>\s*!\[(.*?)\]\((?:images/)?([^)]+)\)\s*</Bild>"
                
                # Find all images without duplicating nested matches
                wrapped_matches = list(re.finditer(wrapped_pattern, markdown_to_process))
                plain_matches = list(re.finditer(pattern, markdown_to_process))
                wrapped_spans = [m.span() for m in wrapped_matches]
                unique_matches = list(wrapped_matches)
                for pm in plain_matches:
                    p_start, p_end = pm.span()
                    if not any(w_start <= p_start and p_end <= w_end for w_start, w_end in wrapped_spans):
                        unique_matches.append(pm)
                
                total_images = len(unique_matches)
                if total_images > 0:
                    # Prepare image paths list (searching across valid candidate directories)
                    image_paths_list = []
                    matched_file_map = {}
                    for match in unique_matches:
                        img_filename = os.path.basename(match.group(2))
                        resolved_path = None
                        for img_dir in valid_image_dirs:
                            candidate_path = os.path.join(img_dir, img_filename)
                            if os.path.exists(candidate_path):
                                resolved_path = candidate_path
                                break
                        if not resolved_path:
                            resolved_path = os.path.join(valid_image_dirs[0], img_filename)
                        
                        matched_file_map[match.group(0)] = resolved_path
                        if resolved_path not in image_paths_list and os.path.exists(resolved_path):
                            image_paths_list.append(resolved_path)

                    if not should_describe:
                        log_progress(92, f"{total_images} Bilder ohne VLM übernommen", f"[Info] Gefunden: {total_images} Bilder. VLM-Bildbeschreibungen übersprungen.")
                        yield f'{{"status": "log", "message": "{total_images} Bilder ohne VLM übernommen."}}\n'
                        yield f'{{"status": "progress", "percent": 92, "phase": "{total_images} Bilder ohne VLM übernommen..."}}\n'
                        json_data = {}
                    else:
                        log_progress(92, f"Analysiere {total_images} Bilder...", f"[Info] Gefunden: {total_images} Bilder zur Barrierefreiheits-Beschreibung.")
                        yield f'{{"status": "log", "message": "Analysiere {total_images} Bilder..."}}\n'
                        yield f'{{"status": "progress", "percent": 92, "phase": "Analysiere {total_images} Bilder..."}}\n'
                        
                        import sys
                        json_data = {}
                        
                        if os.environ.get("E2E_MOCK") == "true":
                            logger.info("E2E_MOCK active: bypassing VLM describer subprocess.")
                            json_data = {
                                p: "Versuchsaufbau eines optischen Experiments mit Prismen zur Lichtbrechung."
                                for p in image_paths_list
                            }
                        elif image_paths_list:
                            # 1. Unload text model from GPU before starting VLM to prevent memory exhaustion
                            release_gpu_memory()

                            tmp_vlm_json_path = os.path.join(OUTPUT_DIR, request.task_id, "vlm_descriptions.json")
                            python_exe = sys.executable or "python"

                            cmd = [
                                python_exe,
                                "-m",
                                "backend.services.vlm_describer",
                                "--images",
                                ",".join(image_paths_list),
                                "--output-json",
                                tmp_vlm_json_path,
                            ]
                            
                            logger.info(f"Running VLM describer subprocess: {' '.join(cmd)}")
                            log_progress(92, "Lade Gemma VLM Modell...", f"[VLM] Lade Gemma VLM für {len(image_paths_list)} Bilder...")
                            yield f'{{"status": "log", "message": "[VLM] Lade Gemma VLM für {len(image_paths_list)} Bilder..."}}\n'
                            yield '{"status": "progress", "percent": 92, "phase": "Lade Gemma VLM Modell..."}\n'
                            
                            # Resume checkpoint: survives interruptions, removed after successful completion.
                            vlm_cache_path = os.path.join(OUTPUT_DIR, request.task_id, "vlm_cache.json")
                            cmd += ["--cache-json", vlm_cache_path]

                            # Page text context per image (current page, plus the end of the previous
                            # page from its last heading when the page does not start with a heading).
                            try:
                                from backend.services.fibs_formatting import image_contexts_for_markdown
                                vlm_contexts = image_contexts_for_markdown(markdown_to_process, matched_file_map)
                                vlm_contexts_path = os.path.join(OUTPUT_DIR, request.task_id, "vlm_contexts.json")
                                with open(vlm_contexts_path, "w", encoding="utf-8") as cf:
                                    json.dump(vlm_contexts, cf, ensure_ascii=False, indent=2)
                                cmd += ["--contexts-json", vlm_contexts_path]
                                log_progress(92, "Seitenkontext für Bilder vorbereitet",
                                             f"[VLM] Seitenkontext für {sum(1 for v in vlm_contexts.values() if v)}/{len(image_paths_list)} Bilder vorbereitet.")
                            except Exception as ctx_err:
                                logger.warning(f"Could not build page contexts for VLM: {ctx_err}")

                            # stdout -> DEVNULL: results come via --output-json. An unread PIPE would
                            # block the child as soon as its final JSON print exceeds the pipe buffer.
                            proc = await asyncio.create_subprocess_exec(
                                *cmd,
                                stdout=asyncio.subprocess.DEVNULL,
                                stderr=asyncio.subprocess.PIPE,
                                cwd=BASE_DIR,
                            )
                            task.process = proc  # explicit abort kills the subprocess

                            idx = 0
                            stderr_tail = []
                            try:
                                while True:
                                    line = await proc.stderr.readline()
                                    if not line:
                                        break
                                    line_str = line.decode("utf-8", errors="ignore").strip()
                                    if "[PROGRESS]" in line_str:
                                        m = re.search(r"\[PROGRESS\]\s+(\d+)/(\d+)", line_str)
                                        if m:
                                            idx = int(m.group(1))
                                            total_imgs_reported = int(m.group(2))
                                        else:
                                            idx += 1
                                            total_imgs_reported = len(image_paths_list)
                                        percent = 92 + int(((idx - 1) / max(1, total_imgs_reported)) * 5)
                                        phase = f"Analysiere Bild {idx}/{total_imgs_reported} (VLM)..."
                                        log_msg = f"[VLM] Analysiere Bild {idx}/{total_imgs_reported}..."
                                        log_progress(percent, phase, log_msg)
                                        yield f'{{"status": "log", "message": {json.dumps(log_msg)}}}\n'
                                        yield f'{{"status": "progress", "percent": {percent}, "phase": {json.dumps(phase)}}}\n'
                                    elif line_str:
                                        if "Resume checkpoint" in line_str:
                                            resume_msg = "[VLM] " + line_str.split(" - ")[-1]
                                            yield f'{{"status": "log", "message": {json.dumps(resume_msg)}}}\n'
                                        stderr_tail = (stderr_tail + [line_str])[-20:]

                                await proc.wait()
                            except BaseException:
                                # Job cancelled (explicit abort / shutdown): never leave the VLM running.
                                if proc.returncode is None:
                                    try:
                                        proc.kill()
                                    except ProcessLookupError:
                                        pass
                                raise
                            finally:
                                task.process = None

                            if proc.returncode not in (0, None):
                                warn = f"[VLM] Bildbeschreibung beendet mit Code {proc.returncode}."
                                logger.warning(warn + " stderr: " + " | ".join(stderr_tail[-5:]))
                                yield f'{{"status": "log", "message": {json.dumps(warn)}}}\n'

                            if os.path.exists(tmp_vlm_json_path):
                                from backend.services.vlm_describer import load_vlm_results

                                vlm_results = load_vlm_results(tmp_vlm_json_path)
                                try:
                                    os.remove(tmp_vlm_json_path)
                                except Exception:
                                    pass

                            # 2. Release VLM memory before loading text model for standardisation
                            release_gpu_memory()
                                
                    from backend.services.fibs_formatting import bild_tag_from_vlm, format_bild_tag, has_caption_context
                    from backend.services.vlm_describer import parse_vlm_description

                    descriptions = {}
                    decorative_removed = 0
                    for match in unique_matches:
                        alt_text = match.group(1)
                        resolved_img_path = matched_file_map.get(match.group(0), "")

                        vlm_res = vlm_results.get(resolved_img_path) if "vlm_results" in locals() else None
                        if vlm_res is None and resolved_img_path in json_data:
                            raw_val = json_data[resolved_img_path]
                            vlm_res = parse_vlm_description(raw_val) if isinstance(raw_val, str) and raw_val else None
                        if vlm_res:
                            # Structured VLM answer -> multi-line <Bild> block. Purely decorative images
                            # (VLM verdict) without caption / text context are not transferred (empty string).
                            has_caption = has_caption_context(markdown_to_process, match.start(), match.end(), alt_text)
                            tag = bild_tag_from_vlm(vlm_res, has_caption=has_caption, alt_text=alt_text)
                            if not tag:
                                decorative_removed += 1
                            descriptions[match.group(0)] = tag
                        else:
                            descriptions[match.group(0)] = format_bild_tag("", alt_text, has_text=False)

                    if decorative_removed:
                        log_msg = f"[VLM] {decorative_removed} dekorative(s) Bild(er) ohne Bildunterschrift nicht übertragen."
                        logger.info(log_msg)
                        yield f'{{"status": "log", "message": {json.dumps(log_msg)}}}\n'

                    # Apply replacements
                    for raw_match, replaced_tag in descriptions.items():
                        markdown_to_process = markdown_to_process.replace(raw_match, replaced_tag)
                    markdown_to_process = re.sub(r"\n{3,}", "\n\n", markdown_to_process)

                    # Strip details block
                    markdown_to_process = re.sub(r"<details\b[^>]*>.*?</details>", "", markdown_to_process, flags=re.DOTALL)

            # Now run text standardisation with real-time token streaming
            log_progress(98, "Formatiere Text...", "[Info] Wende E-Buch Formatierungsregeln (Gemma) an...")
            yield '{"status": "log", "message": "Wende E-Buch Formatierungsregeln (Gemma) an..."}\n'
            yield '{"status": "progress", "percent": 98, "phase": "Wende Übertragungsregeln an (Gemma)..."}\n'
            
            token_queue = asyncio.Queue()
            from backend.services.llm_service import StandardisationAborted

            def on_token_delta(delta: str):
                if task.is_abort_requested:
                    # Stops the streaming loop inside the worker thread on explicit abort.
                    raise StandardisationAborted("Standardisierung abgebrochen")
                loop.call_soon_threadsafe(token_queue.put_nowait, ("token", delta))

            def on_gemma_progress(info: dict):
                if task.is_abort_requested:
                    raise StandardisationAborted("Standardisierung abgebrochen")
                loop.call_soon_threadsafe(token_queue.put_nowait, ("progress", info))

            task.standardisation_backend = "gemma"
            exec_future = asyncio.create_task(
                standardise_markdown_async(
                    markdown_to_process,
                    request.ruleset,
                    image_paths,
                    request.task_id,
                    on_token_delta,
                    on_progress=on_gemma_progress,
                    directory_info=getattr(task, "directory_info", None),
                )
            )
            exec_future.add_done_callback(
                lambda _fut: loop.call_soon_threadsafe(token_queue.put_nowait, ("done", None))
            )

            # Stream tokens and section progress to the client as Gemma generates them (sentinel-driven, no busy polling)
            while True:
                kind, payload = await token_queue.get()
                if kind == "done":
                    break
                if kind == "token":
                    yield f'{{"status": "token", "delta": {json.dumps(payload)}}}\n'
                    continue
                if payload.get("event") == "fallback":
                    task.standardisation_backend = "rule_based_fallback"
                message = payload.get("message") or ""
                level = "[Warnung]" if payload.get("event") in ("retry", "fallback") else "[Gemma]"
                log_msg = f"{level} {message}"
                phase = message if payload.get("event") == "start" else None
                log_progress(98, phase or "Wende Übertragungsregeln an (Gemma)...", log_msg)
                yield f'{{"status": "log", "message": {json.dumps(log_msg)}}}\n'
                if phase:
                    yield f'{{"status": "progress", "percent": 98, "phase": {json.dumps(phase)}}}\n'

            standardised = await exec_future
            
            # Re-inject page boundary markers on the standardised markdown to guarantee they are present
            if task.extension == ".pdf":
                try:
                    # Resolve json_path and pages_str
                    pages_str = getattr(task, "pages", "") or ""
                    auto_dir = os.path.join(OUTPUT_DIR, request.task_id, request.task_id, "auto")
                    if not os.path.exists(auto_dir):
                        auto_dir = os.path.join(OUTPUT_DIR, request.task_id, "auto")
                    
                    base_name = os.path.splitext(task.original_name)[0]
                    json_path = os.path.join(auto_dir, f"{base_name}_content_list.json")
                    if not os.path.exists(json_path):
                        json_path = os.path.join(auto_dir, f"{base_name}_content_list_v2.json")
                    if not os.path.exists(json_path):
                        import glob
                        json_files = glob.glob(os.path.join(auto_dir, "*content_list*.json"))
                        if json_files:
                            json_path = json_files[0]
                        else:
                            json_path = None
                    
                    if json_path and os.path.exists(json_path):
                        logger.info(f"Re-injecting page numbers from metadata JSON: {json_path}")
                        from backend.services.extraction_service import insert_page_numbers_from_metadata
                        standardised = await asyncio.to_thread(
                            insert_page_numbers_from_metadata,
                            standardised,
                            json_path,
                            pages_str,
                            pdf_path=task.input_path,
                            directory_info=getattr(task, "directory_info", None),
                        )
                    elif getattr(task, "directory_info", None) and task.directory_info.get("has_any_directory") and not pages_str:
                        from backend.services.directory_service import apply_directory_page_numbers
                        standardised = await asyncio.to_thread(
                            apply_directory_page_numbers, standardised, task.directory_info
                        )
                except Exception as ex:
                    logger.error(f"Failed to re-inject page numbers on standardised markdown: {ex}")

            from backend.services.fibs_postprocess import deduplicate_page_numbers
            standardised = deduplicate_page_numbers(standardised)

            task.standardised_markdown = standardised
            task.status = "completed"
            task.finished_at = time.time()

            # Save standardised markdown to disk
            std_path = os.path.join(OUTPUT_DIR, request.task_id, f"{request.task_id}_standardised.md")
            try:
                with open(std_path, "w", encoding="utf-8") as sf:
                    sf.write(standardised)
            except Exception as ex:
                logger.error(f"Failed to write standardised markdown to disk: {ex}")

            # Generate/update DOCX if not present
            docx_path = os.path.join(OUTPUT_DIR, request.task_id, f"{request.task_id}.docx")
            try:
                from backend.services.docx_service import convert_markdown_to_docx
                await asyncio.to_thread(convert_markdown_to_docx, standardised, docx_path)
            except Exception as dex:
                logger.warning(f"Auto docx conversion skipped: {dex}")

            task.save_meta()

            # Note: vlm_cache.json is intentionally retained on disk (keyed by image path + prompt hash)
            # so re-standardising the same task reuses finished image descriptions without re-running VLM.

            success_msg = "[Success] Standardisierung erfolgreich abgeschlossen."
            log_progress(100, "Standardisierung beendet.", success_msg)
            yield f'{{"status": "log", "message": {json.dumps(success_msg)}}}\n'
            yield f'{{"status": "completed", "stage": "standardisation", "markdown": {json.dumps(standardised)}}}\n'
            
            import gc
            gc.collect()
            
        except Exception as e:
            logger.error(f"Standardisation failed for task {request.task_id}: {str(e)}")
            task.status = "failed"
            task.finished_at = time.time()
            task.save_meta()
            err_msg = f"[Error] Standardisierung fehlgeschlagen: {str(e)}"
            log_progress(100, "Fehler bei der Standardisierung.", err_msg)
            yield f'{{"status": "log", "message": {json.dumps(err_msg)}}}\n'
            yield f'{{"status": "error", "stage": "standardisation", "message": {json.dumps("Standardisation failed: " + str(e))}}}\n'

    return standardise_generator()


def _standardise_request_path(task_id: str) -> str:
    """Persisted /api/standardise input (exact markdown + options) used by resume."""
    return os.path.join(OUTPUT_DIR, task_id, "standardise_request.json")


def _prepare_standardise(task, request: StandardiseRequest) -> None:
    """Mark the task as processing and persist everything needed to resume it."""
    task.touch()
    task.status = "processing"
    task.is_abort_requested = False
    task.finished_at = None
    if not task.started_at:
        task.started_at = time.time()
    task.ruleset = request.ruleset
    task.describe_images = bool(request.describe_images)
    task.job_kind = "standardisation"
    if request.markdown:
        task.raw_markdown = request.markdown
    try:
        os.makedirs(os.path.join(OUTPUT_DIR, task.task_id), exist_ok=True)
        tmp = _standardise_request_path(task.task_id) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(request.model_dump(), f, ensure_ascii=False)
        os.replace(tmp, _standardise_request_path(task.task_id))
    except Exception as ex:
        logger.warning(f"Could not persist standardise request for resume: {ex}")
    task.save_meta()


async def _run_standardise_job(task, request: StandardiseRequest) -> None:
    """Job body: execute the standardisation pipeline and publish every event."""
    from contextlib import aclosing

    from backend.services.task_jobs import publish

    task.job_kind = "standardisation"
    task.stream_text = ""
    async with aclosing(_standardise_events(task, request)) as events:
        async for line in events:
            publish(task, line)
    # Persist the final progress / log tail (status was set by the pipeline).
    task.save_meta()


def _listener_response(task, replay: bool = True) -> StreamingResponse:
    """NDJSON stream attached to the task's listener queue (detaching never cancels work)."""
    from backend.services.task_jobs import attach_listener, listener_stream
    queue = attach_listener(task, replay=replay)
    return StreamingResponse(listener_stream(task, queue), media_type="application/x-ndjson")


@app.post("/api/standardise")
async def standardise_text(request: StandardiseRequest):
    """Step 3: Standardise Markdown (VLM image descriptions + Gemma).

    Starts a task-owned background job and streams its events. If the client
    disconnects (tab closed, AbortController, system sleep) the job continues;
    reattach via ``GET /api/tasks/{id}/stream``. If a standardisation job is
    already running for the task, this call simply attaches to it.
    """
    task = await task_manager.get(request.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    if task.job_running() and task.job_kind in ("standardisation", "pipeline"):
        return _listener_response(task, replay=True)

    from backend.services.task_jobs import attach_listener, listener_stream, start_task_job
    _prepare_standardise(task, request)
    task.stream_text = ""
    # Attach before starting the job so no event is lost.
    queue = attach_listener(task, replay=False)
    start_task_job(task, "standardisation", _run_standardise_job(task, request))
    return StreamingResponse(listener_stream(task, queue), media_type="application/x-ndjson")


@app.get("/api/tasks/{task_id}/stream")
async def stream_task(task_id: str):
    """(Re)attach to a task: replays logs/progress/streamed tokens, then live events."""
    task = await task_manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    return _listener_response(task, replay=True)


class SettingsUpdate(DomainModel):
    """Request payload for updating persisted application settings."""

    values: dict
    """Mapping of setting keys to updated values."""


@app.get("/api/settings")
async def get_settings():
    """Current application settings plus their schema (rendered generically by the ⚙️ Einstellungen view)."""
    from backend.services.settings_service import load_settings, settings_schema
    return {"values": load_settings(), "schema": settings_schema()}


@app.put("/api/settings")
async def put_settings(update: SettingsUpdate):
    """Validate and persist a partial settings update (422 on invalid values)."""
    from backend.services.settings_service import settings_schema, update_settings
    try:
        values = update_settings(update.values)
    except ValueError as ex:
        raise HTTPException(status_code=422, detail=str(ex))
    return {"values": values, "schema": settings_schema()}


def _resume_markdown(task) -> str | None:
    """Raw extraction markdown for resuming (page markers re-applied if missing)."""
    raw = task.raw_markdown
    if not raw:
        task.to_state_dict()  # loads raw markdown from disk
        raw = task.raw_markdown
    if not raw:
        return None
    if task.extension == ".pdf" and not re.search(r"^\(\(\d+\)\)", raw, flags=re.MULTILINE):
        try:
            import glob

            from backend.services.extraction_service import insert_page_numbers_from_metadata
            json_files = glob.glob(os.path.join(OUTPUT_DIR, task.task_id, "**", "*content_list*.json"),
                                   recursive=True)
            if json_files:
                selected = os.path.join(UPLOAD_DIR, "selected", f"{task.task_id}.pdf")
                pdf_path = selected if os.path.exists(selected) else task.input_path
                raw = insert_page_numbers_from_metadata(raw, json_files[0], task.pages or "", pdf_path=pdf_path)
        except Exception as ex:
            logger.warning(f"Resume: page markers could not be re-applied: {ex}")
    return raw


@app.post("/api/tasks/{task_id}/resume")
async def resume_task(task_id: str):
    """Resume an interrupted / failed / aborted task.

    * Raw extraction available -> restart the standardisation job (VLM descriptions
      reuse the per-image checkpoint) with the persisted request or saved options.
    * Otherwise -> rerun extraction with the saved parameters and chain the
      standardisation server-side ("pipeline" job).
    """
    from backend.services.task_jobs import publish, start_task_job
    from backend.services.task_manager import RESUMABLE_STATUSES

    task = await task_manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    if task.job_running():
        raise HTTPException(status_code=409, detail="Task läuft bereits.")
    if task.status not in RESUMABLE_STATUSES:
        raise HTTPException(status_code=409, detail=f"Task mit Status '{task.status}' kann nicht fortgesetzt werden.")

    request = None
    req_path = _standardise_request_path(task_id)
    if os.path.exists(req_path):
        try:
            with open(req_path, encoding="utf-8") as f:
                request = StandardiseRequest(**json.load(f))
        except Exception as ex:
            logger.warning(f"Resume: stored standardise request unreadable: {ex}")
    if request is None:
        raw = _resume_markdown(task)
        if raw:
            request = StandardiseRequest(
                task_id=task_id,
                markdown=raw,
                ruleset=task.ruleset or "uebertragungsregeln_09_2025",
                describe_images=task.describe_images,
            )

    task.is_abort_requested = False
    if request is not None:
        logger.info(f"▶️ Resume task {task_id}: standardisation")
        _prepare_standardise(task, request)
        task.stream_text = ""
        publish(task, {"status": "log", "message": "▶️ Verarbeitung wird fortgesetzt (Standardisierung mit Bildbeschreibungen)."})
        start_task_job(task, "standardisation", _run_standardise_job(task, request))
        return {"status": "resumed", "stage": "standardisation", "task_id": task_id}

    if not os.path.exists(task.input_path):
        raise HTTPException(status_code=409, detail="Keine Extraktion und keine Quelldatei zum Fortsetzen vorhanden.")

    logger.info(f"▶️ Resume task {task_id}: extraction + standardisation pipeline")
    ruleset = task.ruleset or "uebertragungsregeln_09_2025"
    describe_images = task.describe_images
    task.reset_for_new_extraction()
    task.status = "processing"
    task.started_at = time.time()
    task.save_meta()

    async def pipeline():
        release_gpu_memory()
        await run_background_extraction(
            task=task.__dict__,
            input_path=task.input_path,
            output_root=os.path.join(OUTPUT_DIR, task_id),
            upload_dir=UPLOAD_DIR,
            pages_str=task.pages,
            method=task.method or "auto",
            lang=task.lang or "en",
            backend="vlm-engine",
            engine=task.engine or "infinity",
        )
        if task.status == "completed" and not task.is_abort_requested and task.raw_markdown:
            req = StandardiseRequest(task_id=task_id, markdown=task.raw_markdown,
                                     ruleset=ruleset, describe_images=describe_images)
            _prepare_standardise(task, req)
            await _run_standardise_job(task, req)

    start_task_job(task, "pipeline", pipeline())
    return {"status": "resumed", "stage": "pipeline", "task_id": task_id}


@app.post("/api/optimize")
async def optimize_text(request: OptimizeRequest):
    """Iterative refinement step: Refines the standardised Markdown based on
    user feedback. For PDF tasks, includes rendered page images as
    multimodal input.
    """
    from backend.services.task_manager import acquire_sleep_assertion_sync, release_sleep_assertion_sync
    acquire_sleep_assertion_sync()
    task = await task_manager.get(request.task_id)
    if not task:
        release_sleep_assertion_sync()
        raise HTTPException(status_code=404, detail="Task not found.")

    raw_markdown = task.raw_markdown or request.current_markdown

    try:
        optimized = await optimize_markdown_async(
            raw_markdown=raw_markdown,
            current_markdown=request.current_markdown,
            feedback=request.prompt,
            ruleset_key=request.ruleset,
            task_id=request.task_id,
        )

        task.standardised_markdown = optimized

        import gc
        gc.collect()

        return {"task_id": request.task_id, "markdown": optimized}
    except Exception as e:
        logger.error(f"Optimization failed for task {request.task_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Optimization failed: {str(e)}"
        )
    finally:
        release_sleep_assertion_sync()


@app.post("/api/diff")
async def calculate_diff(payload: DiffRequest):
    """Computes categorised diff segments between raw and standardised markdown."""
    try:
        segments = await asyncio.to_thread(get_diff_highlighting, payload.raw, payload.std)
        return {"status": "success", "segments": segments}
    except Exception as e:
        logger.error(f"Error calculating diff: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/upload-template")
async def upload_template(task_id: str = Form(...), file: UploadFile = File(...)):
    """Saves a custom .docx style template file for the current task."""
    task = await task_manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in [".docx", ".dotx"]:
        raise HTTPException(
            status_code=400,
            detail="Only .docx and .dotx files are supported as custom style templates.",
        )

    task_dir = os.path.join(OUTPUT_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)

    # Clean up any conflicting template versions
    for old_ext in [".docx", ".dotx"]:
        old_path = os.path.join(task_dir, f"template{old_ext}")
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except Exception:
                pass

    template_path = os.path.join(task_dir, f"template{file_ext}")

    content = await file.read()
    with open(template_path, "wb") as buffer:
        buffer.write(content)

    logger.info(f"Custom style template uploaded for task {task_id}: {file.filename}")
    return {"task_id": task_id, "template_name": file.filename}


@app.post("/api/upload-ruleset")
async def upload_ruleset(task_id: str = Form(...), file: UploadFile = File(...)):
    """Saves a custom file-specific ruleset file for the current task."""
    if not task_manager.contains_sync(task_id):
        raise HTTPException(status_code=404, detail="Task not found.")

    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in [".txt", ".md", ".pdf", ".docx"]:
        raise HTTPException(
            status_code=400,
            detail="Only .txt, .md, .pdf, and .docx files are supported as custom rulesets.",
        )

    task_dir = os.path.join(OUTPUT_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)
    ruleset_path = os.path.join(task_dir, "custom_ruleset.txt")
    markdown_content = ""

    if file_ext == ".docx":
        temp_file_path = os.path.join(task_dir, f"ruleset_temp{file_ext}")
        content = await file.read()
        with open(temp_file_path, "wb") as buffer:
            buffer.write(content)
        try:
            from backend.services.docx_service import extract_markdown_from_docx
            markdown_content = await asyncio.to_thread(extract_markdown_from_docx, temp_file_path)
            with open(ruleset_path, "w", encoding="utf-8") as f:
                f.write(markdown_content)
        except Exception as e:
            logger.error(f"DOCX ruleset extraction failed: {e}")
            raise HTTPException(status_code=500, detail=f"Ruleset DOCX extraction failed: {str(e)}")
        finally:
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except Exception:
                    pass

    elif file_ext == ".pdf":
        import shutil
        temp_file_path = os.path.join(task_dir, f"ruleset_temp{file_ext}")
        content = await file.read()
        with open(temp_file_path, "wb") as buffer:
            buffer.write(content)

        try:
            from backend.services.task_manager import acquire_sleep_assertion_sync, release_sleep_assertion_sync
            acquire_sleep_assertion_sync()
            try:
                ruleset_output_dir = os.path.join(task_dir, "ruleset_extracted")
                if os.path.exists(ruleset_output_dir):
                    shutil.rmtree(ruleset_output_dir)
                os.makedirs(ruleset_output_dir, exist_ok=True)

                logger.info(
                    f"Running ruleset PDF extraction for task {task_id}"
                )
                from scripts.run_benchmark import run_docling_extraction
                markdown_content, _ = await asyncio.to_thread(
                    run_docling_extraction, temp_file_path, ruleset_output_dir
                )

                with open(ruleset_path, "w", encoding="utf-8") as f:
                    f.write(markdown_content)

                if os.path.exists(ruleset_output_dir):
                    shutil.rmtree(ruleset_output_dir)
            finally:
                release_sleep_assertion_sync()
        except Exception as e:
            logger.error(f"Ruleset PDF extraction failed: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Ruleset PDF extraction failed: {str(e)}",
            )
        finally:
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except Exception:
                    pass
    else:
        content = await file.read()
        markdown_content = content.decode("utf-8", errors="ignore")
        with open(ruleset_path, "w", encoding="utf-8") as buffer:
            buffer.write(markdown_content)

    logger.info(f"Custom ruleset uploaded for task {task_id}: {file.filename} ({len(markdown_content)} chars)")
    return {
        "task_id": task_id,
        "ruleset_name": file.filename,
        "content": markdown_content,
        "chars": len(markdown_content),
    }


@app.get("/api/ruleset/{task_id}")
async def get_ruleset(task_id: str):
    """Retrieves the parsed custom ruleset content for inspection."""
    if not task_manager.contains_sync(task_id):
        raise HTTPException(status_code=404, detail="Task not found.")
    ruleset_path = os.path.join(OUTPUT_DIR, task_id, "custom_ruleset.txt")
    if not os.path.exists(ruleset_path):
        return {"task_id": task_id, "has_ruleset": False, "content": "", "chars": 0}
    try:
        with open(ruleset_path, encoding="utf-8") as f:
            content = f.read()
        return {
            "task_id": task_id,
            "has_ruleset": True,
            "content": content,
            "chars": len(content),
        }
    except Exception as e:
        logger.error(f"Failed to read ruleset for task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read ruleset: {str(e)}")


@app.get("/api/pdf/{task_id}")
async def serve_pdf(task_id: str):
    """Serves the uploaded PDF file for inline viewing."""
    task = await task_manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    if task.extension.lower() == ".pdf":
        return FileResponse(task.input_path, media_type="application/pdf")
    else:
        return HTMLResponse(
            content=(
                "<html><body style='font-family:sans-serif; background:#0f172a; "
                "color:#f1f5f9; display:flex; align-items:center; justify-content:center; "
                "height:100vh; margin:0;'><h3>Vorschau für DOCX-Dateien ist nicht verfügbar. "
                "Bitte lade eine PDF-Datei hoch.</h3></body></html>"
            ),
            status_code=200,
        )


async def _resolve_lint_context(request: LintRequest):
    raw_markdown = request.raw_markdown
    expected_pages = request.expected_pages
    table_max_cells = request.table_max_cells
    if request.task_id:
        task = await task_manager.get(request.task_id)
        if task:
            if raw_markdown is None:
                raw_markdown = task.raw_markdown
            if expected_pages is None and task.page_count:
                expected_pages = task.page_count
    if table_max_cells is None:
        try:
            from backend.services.settings_service import get_setting
            table_max_cells = int(get_setting("table_resolve_max_cells"))
        except Exception:
            table_max_cells = 0
    return raw_markdown, expected_pages, table_max_cells


@app.post("/api/lint")
async def lint_document(request: LintRequest):
    """Validate markdown content against the E-Buch 2025 standard for accessibility.
    Returns compliance score, pass/fail status, and structured issue list.
    """
    try:
        raw_md, exp_pages, max_cells = await _resolve_lint_context(request)
        report = await asyncio.to_thread(
            lint_markdown,
            request.markdown,
            raw_markdown=raw_md,
            expected_pages=exp_pages,
            table_max_cells=max_cells,
        )
        return report
    except Exception as e:
        logger.error(f"Linting failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Linting failed: {str(e)}")


@app.post("/api/lint/autofix")
async def autofix_document(request: LintRequest):
    """Applies deterministic automatic fixes to resolve E-Buch 2025 accessibility issues.
    Returns fixed markdown, applied fixes list, and updated lint report.
    """
    try:
        raw_md, exp_pages, max_cells = await _resolve_lint_context(request)
        fixed_markdown, applied_fixes = await asyncio.to_thread(
            autofix_markdown, request.markdown
        )
        report = await asyncio.to_thread(
            lint_markdown,
            fixed_markdown,
            raw_markdown=raw_md,
            expected_pages=exp_pages,
            table_max_cells=max_cells,
        )
        return {
            "fixed_markdown": fixed_markdown,
            "applied_fixes": applied_fixes,
            "report": report
        }
    except Exception as e:
        logger.error(f"Autofix failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Autofix failed: {str(e)}")


@app.post("/api/export")
async def export_document(request: ExportRequest):
    """Step 4: Convert the standardised Markdown back to DOCX.
    Saves the file and returns download availability.
    """
    task = await task_manager.get(request.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    try:
        output_docx = os.path.join(OUTPUT_DIR, request.task_id, "ebuch_output.docx")
        template_docx = os.path.join(OUTPUT_DIR, request.task_id, "template.docx")
        template_dotx = os.path.join(OUTPUT_DIR, request.task_id, "template.dotx")

        template_mode = request.template_mode or "default"
        template_path = None

        if template_mode == "custom":
            if os.path.exists(template_docx):
                template_path = template_docx
            elif os.path.exists(template_dotx):
                template_path = template_dotx
        elif template_mode == "default":
            default_tpl = os.path.join(
                BASE_DIR,
                "assets",
                "templates",
                "Dokumentenvorlage FIBS 25.05.2025_NEU.dotx",
            )
            if os.path.exists(default_tpl):
                template_path = default_tpl

        await asyncio.to_thread(
            convert_markdown_to_docx, request.markdown, output_docx, template_path
        )

        task.output_path = output_docx

        return {
            "task_id": request.task_id,
            "download_url": f"/api/download/{request.task_id}",
        }
    except Exception as e:
        logger.error(f"Export failed for task {request.task_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Export failed: {str(e)}"
        )


@app.get("/api/download/{task_id}")
async def download_file(task_id: str):
    """Download endpoint for getting the final converted DOCX."""
    task = await task_manager.get(task_id)
    if not task or not task.output_path:
        raise HTTPException(status_code=404, detail="Converted file not found.")

    original_base = os.path.splitext(task.original_name)[0]
    download_filename = f"{original_base}_ebuch.docx"

    return FileResponse(
        task.output_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=download_filename,
    )


@app.post("/api/benchmark/custom-evaluate")
async def custom_benchmark_evaluate(
    source_file: UploadFile = File(...),
    ground_truth_file: UploadFile = File(...),
    custom_rules_file: UploadFile | None = File(None),
    custom_rules_text: str | None = Form(None),
    pages: str | None = Form(None),
    ruleset: str = Form("uebertragungsregeln_09_2025"),
    engines: str = Form("infinity,docling")
):
    """On-Demand Custom Benchmark Evaluation with Document-Specific Rules:
    Evaluates selected extraction engines on an uploaded source PDF against an uploaded manual ground truth Markdown file,
    incorporating optional document-specific conversion rules into the LLM standardisation pipeline.
    """
    task_id = str(uuid.uuid4())
    task_dir = os.path.join(OUTPUT_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)

    source_path = os.path.join(task_dir, source_file.filename)
    gt_path = os.path.join(task_dir, ground_truth_file.filename)

    selected_engines = [e.strip() for e in engines.split(",") if e.strip()]
    if not selected_engines:
        selected_engines = ["infinity", "docling"]

    from backend.services.benchmark_task_manager import benchmark_task_manager
    benchmark_task = benchmark_task_manager.create_task(
        task_id=task_id,
        source_filename=source_file.filename,
        ground_truth_filename=ground_truth_file.filename,
        ruleset=ruleset,
        engines=selected_engines,
        has_custom_rules=False
    )

    try:
        benchmark_task.add_log(f"Lade Quelldokument '{source_file.filename}'...")
        
        # Save source PDF (cropped if page range requested)
        if pages and pages.strip():
            raw_source_path = os.path.join(task_dir, f"full_{source_file.filename}")
            with open(raw_source_path, "wb") as f:
                content = await source_file.read()
                f.write(content)
            
            total_pages = await asyncio.to_thread(get_pdf_page_count, raw_source_path)
            is_valid, err_msg = validate_pages_string(pages.strip(), total_pages)
            if not is_valid:
                raise HTTPException(status_code=400, detail=err_msg)
            
            extracted = await asyncio.to_thread(extract_pdf_pages, raw_source_path, pages.strip(), source_path)
            cropped_count = await asyncio.to_thread(get_pdf_page_count, source_path) if os.path.exists(source_path) else 0
            if not extracted or not os.path.exists(source_path) or cropped_count == 0:
                raise HTTPException(status_code=400, detail=f"Ungültiger Seitenbereich '{pages.strip()}'. Keine Seiten konnten extrahiert werden.")
            
            benchmark_task.add_log(f"Seitenbereich [{pages.strip()}] ausgewählt. Quell-PDF gekürzt ({cropped_count} von {total_pages} Seiten).")
        else:
            with open(source_path, "wb") as f:
                content = await source_file.read()
                f.write(content)

        # Save and read Ground Truth (.md, .txt, or .docx)
        gt_filename_lower = ground_truth_file.filename.lower()
        if gt_filename_lower.endswith(".docx"):
            benchmark_task.add_log(f"Extrahiere E-Buch Markdown aus DOCX Referenzdatei '{ground_truth_file.filename}'...")
            with open(gt_path, "wb") as f:
                content = await ground_truth_file.read()
                f.write(content)
            from backend.services.docx_service import extract_markdown_from_docx
            gt_content = await asyncio.to_thread(extract_markdown_from_docx, gt_path)
            md_gt_path = os.path.join(task_dir, "ground_truth_extracted.md")
            with open(md_gt_path, "w", encoding="utf-8") as f:
                f.write(gt_content)
            benchmark_task.add_log(f"Ground-Truth DOCX erfolgreich analysiert ({len(gt_content)} Zeichen extrahiert).")
            logger.info(f"Extracted {len(gt_content)} chars of markdown from DOCX reference: {gt_path}")
        else:
            benchmark_task.add_log(f"Lade Markdown Ground-Truth Referenzdatei '{ground_truth_file.filename}'...")
            gt_content = (await ground_truth_file.read()).decode("utf-8")
            with open(gt_path, "w", encoding="utf-8") as f:
                f.write(gt_content)
            benchmark_task.add_log(f"Ground-Truth Markdown geladen ({len(gt_content)} Zeichen).")

        # Save optional document-specific custom ruleset (.txt, .md, .docx, .pdf)
        custom_rules = ""
        if custom_rules_file and custom_rules_file.filename:
            r_ext = os.path.splitext(custom_rules_file.filename)[1].lower()
            if r_ext == ".docx":
                benchmark_task.add_log(f"Extrahiere Regelsätze aus DOCX Datei '{custom_rules_file.filename}'...")
                temp_docx_rules = os.path.join(task_dir, f"rules_temp_{uuid.uuid4().hex[:6]}.docx")
                content = await custom_rules_file.read()
                with open(temp_docx_rules, "wb") as f:
                    f.write(content)
                from backend.services.docx_service import extract_markdown_from_docx
                custom_rules = (await asyncio.to_thread(extract_markdown_from_docx, temp_docx_rules)).strip()
                if os.path.exists(temp_docx_rules):
                    os.remove(temp_docx_rules)
                benchmark_task.add_log(f"Regel-DOCX verarbeitet ({len(custom_rules)} Zeichen extrahiert).")
                logger.info(f"Extracted {len(custom_rules)} chars of rules from DOCX: {custom_rules_file.filename}")
            elif r_ext == ".pdf":
                benchmark_task.add_log(f"Lade Regelsätze aus PDF Datei '{custom_rules_file.filename}'...")
                import pypdfium2
                content = await custom_rules_file.read()
                def _extract_pdf_rules(data: bytes) -> str:
                    pdf_doc = pypdfium2.PdfDocument(data)
                    return "\n\n".join([page.get_textpage().get_text_range() for page in pdf_doc]).strip()
                custom_rules = await asyncio.to_thread(_extract_pdf_rules, content)
                benchmark_task.add_log(f"Regel-PDF verarbeitet ({len(custom_rules)} Zeichen).")
                logger.info(f"Extracted {len(custom_rules)} chars of rules from PDF: {custom_rules_file.filename}")
            else:
                benchmark_task.add_log(f"Lade Dokumenten-Regeldatei '{custom_rules_file.filename}'...")
                file_bytes = await custom_rules_file.read()
                custom_rules = file_bytes.decode("utf-8").strip()

        if custom_rules_text and custom_rules_text.strip():
            if custom_rules:
                custom_rules += "\n\n" + custom_rules_text.strip()
            else:
                custom_rules = custom_rules_text.strip()

        if custom_rules:
            benchmark_task.has_custom_rules = True
            rules_path = os.path.join(task_dir, "custom_ruleset.txt")
            with open(rules_path, "w", encoding="utf-8") as f:
                f.write(custom_rules)
            benchmark_task.add_log(f"Dokumenten-spezifische Übertragungsregeln geladen ({len(custom_rules)} Zeichen).")
            logger.info(f"Custom rules saved for benchmark task {task_id} ({len(custom_rules)} chars)")

        async def _run_bg():
            loop = asyncio.get_event_loop()
            try:
                await loop.run_in_executor(
                    _BENCHMARK_EXECUTOR,
                    evaluate_custom_submission,
                    source_path,
                    gt_content,
                    ruleset,
                    selected_engines,
                    task_id,
                    pages
                )
            except Exception as ex:
                logger.error(f"Benchmark background execution failed: {ex}", exc_info=True)
                benchmark_task.status = "failed"
                benchmark_task.error_message = str(ex)
                benchmark_task.add_log(f"Schwerwiegender Fehler: {str(ex)}", level="error")

        bg_task = asyncio.create_task(_run_bg())
        _BACKGROUND_TASKS.add(bg_task)
        bg_task.add_done_callback(_BACKGROUND_TASKS.discard)

        return {
            "task_id": task_id,
            "status": "running",
            "source_filename": source_file.filename,
            "ground_truth_filename": ground_truth_file.filename,
            "is_docx_ground_truth": gt_filename_lower.endswith(".docx"),
            "has_custom_rules": bool(custom_rules),
            "total_engines": len(selected_engines)
        }
    except Exception as e:
        logger.error(f"Custom benchmark initialization failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Initialization failed: {str(e)}")


@app.get("/api/benchmark/tasks/{task_id}/status")
async def get_benchmark_task_status(task_id: str):
    """Returns current live progress, phase, logs, and results for a benchmark task."""
    from backend.services.benchmark_task_manager import benchmark_task_manager

    # 1. Check live status snapshot file on disk for instant GIL-lock-free response
    status_file = os.path.join(OUTPUT_DIR, task_id, "task_status.json")
    if os.path.exists(status_file):
        try:
            with open(status_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # 2. Check in-memory task
    task = benchmark_task_manager.get_task(task_id)
    if task:
        return task.to_dict()

    # 3. Check final benchmark_state.json fallback
    state_file = os.path.join(OUTPUT_DIR, task_id, "benchmark_state.json")
    if os.path.exists(state_file):
        try:
            with open(state_file, encoding="utf-8") as f:
                data = json.load(f)
            return {
                "task_id": task_id,
                "status": data.get("status", "completed"),
                "progress_percent": 100.0,
                "current_phase": "Abgeschlossen",
                "logs": [],
                "results": data.get("evaluation")
            }
        except Exception:
            pass

    return {
        "task_id": task_id,
        "status": "failed",
        "progress_percent": 0.0,
        "current_phase": "Server-Neustart unterbrach die Ausführung",
        "error_message": "Der Benchmark-Task wurde durch einen Server-Neustart unterbrochen.",
        "logs": [{"time": "", "level": "warning", "message": "Task durch Server-Neustart zurückgesetzt."}],
        "results": None
    }


@app.post("/api/benchmark/tasks/{task_id}/abort")
async def abort_benchmark_task(task_id: str):
    """Aborts an ongoing benchmark task and removes it from history."""
    from backend.services.benchmark_task_manager import benchmark_task_manager
    task = benchmark_task_manager.get_task(task_id)
    if task:
        task.request_abort()
    benchmark_task_manager.delete_run(task_id)
    return {"status": "aborted", "task_id": task_id}


@app.post("/api/benchmark/tasks/{task_id}/re-evaluate")
async def re_evaluate_benchmark_task(task_id: str):
    """Re-evaluates an existing finished benchmark run:
    recalculates all metric categories, triggers a fresh Gemma 4 LLM-as-a-Judge evaluation,
    re-computes visual diffs, and updates results in-place.
    """
    from backend.services.custom_benchmark_service import re_evaluate_submission
    try:
        updated = await asyncio.to_thread(re_evaluate_submission, task_id)
        return {
            "status": "success",
            "task_id": task_id,
            "results": updated.get("results"),
            "evaluation": updated.get("evaluation"),
            "logs": updated.get("logs", [])
        }
    except Exception as e:
        logger.error(f"Re-evaluation failed for task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/benchmark/history/{run_id}")
async def delete_benchmark_history_item(run_id: str):
    """Deletes a custom benchmark run completely from history and disk."""
    from backend.services.benchmark_task_manager import benchmark_task_manager
    success = benchmark_task_manager.delete_run(run_id)
    return {"status": "deleted", "run_id": run_id, "success": success}


@app.post("/api/benchmark/tasks/{task_id}/skip")
async def skip_benchmark_engine(task_id: str):
    """Skips the currently executing engine in a benchmark task."""
    from backend.services.benchmark_task_manager import benchmark_task_manager
    task = benchmark_task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Benchmark task not found.")
    
    task.request_skip_engine()
    return {"status": "skip_requested", "task_id": task_id, "skipped_engine": task.current_engine}


@app.get("/api/benchmark/active")
async def get_active_benchmark_task():
    """Returns the currently active benchmark task (if any) to resume UI on reload."""
    from backend.services.benchmark_task_manager import benchmark_task_manager
    active = benchmark_task_manager.get_active_task()
    if active:
        return {"has_active": True, "task": active.to_dict()}
    return {"has_active": False}


@app.get("/api/benchmark/history")
async def get_benchmark_history():
    """Returns a list of all past benchmark runs (custom and official leaderboard runs)."""
    from backend.services.benchmark_task_manager import benchmark_task_manager
    history = benchmark_task_manager.get_history()
    return {"history": history}


@app.get("/api/benchmark/history/{run_id}")
async def get_benchmark_run_details(run_id: str):
    """Returns detailed records and rankings for a past benchmark run."""
    from backend.services.benchmark_task_manager import benchmark_task_manager
    details = benchmark_task_manager.get_run_details(run_id)
    if not details:
        raise HTTPException(status_code=404, detail="Benchmark run record not found.")
    return details


@app.get("/api/benchmark/download-docx/{task_id}/{engine}")
async def download_benchmark_docx(task_id: str, engine: str):
    """Download the candidate Word DOCX generated during custom benchmark evaluation."""
    eng_clean = re.sub(r'[^a-zA-Z0-9_-]', '', engine)
    docx_path = os.path.join(OUTPUT_DIR, task_id, eng_clean, f"{eng_clean}_output.docx")
    
    if not os.path.exists(docx_path):
        alt_path = os.path.join(OUTPUT_DIR, task_id, f"{task_id}.docx")
        if os.path.exists(alt_path):
            docx_path = alt_path
        else:
            raise HTTPException(status_code=404, detail="Benchmark DOCX file not found.")

    return FileResponse(
        path=docx_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"benchmark_{engine}_{task_id[:8]}.docx"
    )


# ---------------------------------------------------------------------------
# Feedback mode: analyse manual corrections of a transfer with Gemma 4
# ---------------------------------------------------------------------------

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _feedback_artifacts(task) -> dict:
    """Resolve stored Markdown / DOCX / PDF artifacts of a conversion job."""
    task_dir = os.path.join(OUTPUT_DIR, task.task_id)
    md_path = os.path.join(task_dir, f"{task.task_id}_standardised.md")
    docx_path = None
    for cand in (os.path.join(task_dir, "ebuch_output.docx"), os.path.join(task_dir, f"{task.task_id}.docx")):
        if os.path.exists(cand):
            docx_path = cand
            break
    has_pdf = bool(task.input_path) and task.extension == ".pdf" and os.path.exists(task.input_path)
    return {
        "markdown_path": md_path if os.path.exists(md_path) else None,
        "has_markdown_in_memory": bool(task.standardised_markdown),
        "docx_path": docx_path,
        "has_pdf": has_pdf,
    }


def _feedback_job_dict(task) -> dict:
    art = _feedback_artifacts(task)
    reports_dir = os.path.join(FEEDBACK_DIR, task.task_id)
    report_count = len(os.listdir(reports_dir)) if os.path.isdir(reports_dir) else 0
    return {
        "task_id": task.task_id,
        "original_name": task.original_name,
        "status": task.status,
        "engine": task.engine,
        "pages": task.pages,
        "page_count": task.page_count,
        "physical_start_page": task.physical_start_page,
        "created_at": task.created_at,
        "finished_at": task.finished_at,
        "has_markdown": bool(art["markdown_path"] or art["has_markdown_in_memory"]),
        "has_docx": bool(art["docx_path"]),
        "has_pdf": art["has_pdf"],
        "report_count": report_count,
    }


def _load_original_transfer(task) -> str:
    """Return the stored automatic transfer (Markdown preferred, DOCX fallback)."""
    from backend.services.feedback_service import load_transfer_document
    art = _feedback_artifacts(task)
    if art["markdown_path"]:
        with open(art["markdown_path"], encoding="utf-8") as f:
            return f.read()
    if task.standardised_markdown:
        return task.standardised_markdown
    if art["docx_path"]:
        return load_transfer_document(art["docx_path"])
    return ""


@app.get("/api/feedback/jobs")
async def list_feedback_jobs():
    """Lists processed jobs from the history together with their stored artifacts."""
    tasks = await task_manager.list_all()
    jobs = [_feedback_job_dict(t) for t in tasks]
    jobs.sort(key=lambda j: j.get("finished_at") or j.get("created_at") or 0, reverse=True)
    return {"jobs": jobs}


@app.post("/api/feedback/jobs")
async def create_feedback_job(
    transfer_file: UploadFile = File(...),
    source_pdf: UploadFile | None = File(None),
):
    """Creates a new job for feedback when the original job is missing from the history.
    Requires the automatic transfer (Markdown or DOCX export); the source PDF is optional
    but needed to mark incorrectly transferred regions.
    """
    from backend.services.feedback_service import load_transfer_document

    t_ext = os.path.splitext(transfer_file.filename or "")[1].lower()
    if t_ext not in TRANSFER_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Übertragung muss als .md, .txt oder .docx vorliegen.")
    if source_pdf and source_pdf.filename and not source_pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Quelldokument muss eine PDF-Datei sein.")

    task_id = str(uuid.uuid4())
    task_dir = os.path.join(OUTPUT_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)

    input_path, extension, original_name, page_count, physical_start = "", t_ext, transfer_file.filename, 0, 1
    if source_pdf and source_pdf.filename:
        input_path = os.path.join(UPLOAD_DIR, f"{task_id}.pdf")
        with open(input_path, "wb") as f:
            f.write(await source_pdf.read())
        extension, original_name = ".pdf", source_pdf.filename
        page_count = await asyncio.to_thread(get_pdf_page_count, input_path)
        physical_start = await asyncio.to_thread(detect_physical_start_page, input_path)

    # Store the automatic transfer exactly where regular jobs keep their artifacts
    if t_ext == ".docx":
        docx_path = os.path.join(task_dir, f"{task_id}.docx")
        with open(docx_path, "wb") as f:
            f.write(await transfer_file.read())
        try:
            markdown = await asyncio.to_thread(load_transfer_document, docx_path)
        except Exception as e:
            import shutil
            shutil.rmtree(task_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=f"DOCX konnte nicht gelesen werden: {e}")
    else:
        markdown = (await transfer_file.read()).decode("utf-8", errors="ignore")
    with open(os.path.join(task_dir, f"{task_id}_standardised.md"), "w", encoding="utf-8") as f:
        f.write(markdown)

    task = await task_manager.create(
        task_id=task_id,
        original_name=original_name,
        input_path=input_path,
        extension=extension,
        page_count=page_count,
    )
    task.physical_start_page = physical_start
    task.standardised_markdown = markdown
    task.status = "completed"
    task.engine = "extern"
    task.finished_at = time.time()
    task.save_meta()
    logger.info(f"Feedback job created: {task_id} ({original_name}, transfer={transfer_file.filename})")
    return _feedback_job_dict(task)


@app.get("/api/feedback/jobs/{task_id}/files/{kind}")
async def download_feedback_job_file(task_id: str, kind: str):
    """Downloads the stored Markdown source or DOCX export of a job."""
    task = await task_manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Auftrag nicht gefunden.")
    base = os.path.splitext(task.original_name)[0]
    art = _feedback_artifacts(task)
    if kind == "markdown":
        if art["markdown_path"]:
            return FileResponse(art["markdown_path"], media_type="text/markdown", filename=f"{base}_ebuch.md")
        if task.standardised_markdown:
            return StreamingResponse(iter([task.standardised_markdown]), media_type="text/markdown")
    elif kind == "docx" and art["docx_path"]:
        return FileResponse(
            art["docx_path"],
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=f"{base}_ebuch.docx",
        )
    raise HTTPException(status_code=404, detail="Datei nicht vorhanden.")


@app.get("/api/feedback/jobs/{task_id}/pages/{page_idx}")
async def render_feedback_page(task_id: str, page_idx: int, scale: float = 2.0):
    """Renders a single source PDF page as PNG for marking incorrect regions."""
    from fastapi.responses import Response

    from backend.services.pdf_render_service import render_single_page_bytes

    task = await task_manager.get(task_id)
    if not task or task.extension != ".pdf" or not os.path.exists(task.input_path or ""):
        raise HTTPException(status_code=404, detail="Kein Quell-PDF für diesen Auftrag vorhanden.")
    scale = min(max(scale, 0.5), 3.0)
    loop = asyncio.get_event_loop()
    png = await loop.run_in_executor(None, render_single_page_bytes, task.input_path, page_idx, scale)
    if png is None:
        raise HTTPException(status_code=404, detail="Seite nicht gefunden.")
    # A job's source PDF never changes, so rendered pages can be cached (enables instant preloaded paging)
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@app.post("/api/feedback/analyze")
async def analyze_feedback(
    task_id: str = Form(...),
    revised_file: UploadFile = File(...),
    feedback_text: str | None = Form(None),
    feedback_file: UploadFile | None = File(None),
    regions: list[UploadFile] | None = File(None),
    regions_meta: str | None = Form(None),
):
    """Analyses a manually revised transfer against the stored automatic transfer.

    1. Converts the revised transfer to Markdown (DOCX supported).
    2. Computes a programmatic change summary + linter comparison.
    3. Runs Gemma 4 locally (isolated per-region image prompts, then text-only synthesis).
    4. Applies the copyright guard and streams the report as NDJSON.
    """
    from backend.services import feedback_service as fs

    if not _SAFE_ID.match(task_id):
        raise HTTPException(status_code=400, detail="Ungültige Auftrags-ID.")
    task = await task_manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Auftrag nicht gefunden.")

    original_md = _load_original_transfer(task)
    if not original_md.strip():
        raise HTTPException(status_code=400, detail="Für diesen Auftrag ist keine Übertragung (Markdown/DOCX) gespeichert.")

    r_ext = os.path.splitext(revised_file.filename or "")[1].lower()
    if r_ext not in TRANSFER_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Überarbeitete Übertragung muss als .md, .txt oder .docx vorliegen.")

    feedback_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    work_dir = os.path.join(FEEDBACK_DIR, task_id, feedback_id)
    regions_dir = os.path.join(work_dir, "regions")
    os.makedirs(regions_dir, exist_ok=True)

    # --- Persist inputs -----------------------------------------------------
    revised_upload = os.path.join(work_dir, f"revised_upload{r_ext}")
    with open(revised_upload, "wb") as f:
        f.write(await revised_file.read())
    try:
        revised_md = await asyncio.to_thread(fs.load_transfer_document, revised_upload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Überarbeitete Übertragung konnte nicht gelesen werden: {e}")
    with open(os.path.join(work_dir, "revised.md"), "w", encoding="utf-8") as f:
        f.write(revised_md)
    with open(os.path.join(work_dir, "original.md"), "w", encoding="utf-8") as f:
        f.write(original_md)

    feedback_parts = [feedback_text.strip()] if feedback_text and feedback_text.strip() else []
    if feedback_file and feedback_file.filename:
        fb_ext = os.path.splitext(feedback_file.filename)[1].lower()
        if fb_ext not in FEEDBACK_EXTENSIONS:
            raise HTTPException(status_code=400, detail="Feedback-Datei muss .txt, .md, .docx oder .pdf sein.")
        fb_path = os.path.join(work_dir, f"feedback_upload{fb_ext}")
        with open(fb_path, "wb") as f:
            f.write(await feedback_file.read())
        try:
            fb_doc = await asyncio.to_thread(fs.load_feedback_document, fb_path)
            feedback_parts.append(fb_doc.strip())
        except Exception as e:
            logger.warning(f"Feedback file could not be parsed: {e}")

    try:
        meta_list = json.loads(regions_meta) if regions_meta else []
    except json.JSONDecodeError:
        meta_list = []
    region_entries = []
    for idx, upload in enumerate(regions or [], 1):
        if not upload or not upload.filename:
            continue
        png_path = os.path.join(regions_dir, f"region_{idx}.png")
        with open(png_path, "wb") as f:
            f.write(await upload.read())
        meta = meta_list[idx - 1] if idx - 1 < len(meta_list) and isinstance(meta_list[idx - 1], dict) else {}
        from backend.services.prompts import build_region_prompt

        region_entries.append({
            "path": png_path,
            "page": meta.get("page"),
            "note": str(meta.get("note") or ""),
            "prompt": build_region_prompt(str(meta.get("note") or ""), meta.get("page")),
        })
    # Region notes are part of the user feedback as well
    for i, r in enumerate(region_entries, 1):
        if r["note"].strip():
            page_txt = f" (PDF-Seite {r['page']})" if r["page"] else ""
            feedback_parts.append(f"Markierte Stelle {i}{page_txt}: {r['note'].strip()}")
    combined_feedback = "\n\n".join(p for p in feedback_parts if p)
    with open(os.path.join(work_dir, "feedback.txt"), "w", encoding="utf-8") as f:
        f.write(combined_feedback)

    task_meta = {
        "Quelldokument": task.original_name,
        "Engine": task.engine,
        "Standardisierungs-Backend": getattr(task, "standardisation_backend", None) or "unbekannt",
        "Seitenauswahl": task.pages,
        "Regelsatz": "Übertragungsregeln FIBS (September 2025)",
    }

    async def analysis_stream():
        def ev(**payload) -> str:
            return json.dumps(payload, ensure_ascii=False) + "\n"

        try:
            yield ev(status="progress", percent=5, phase="Vergleiche Übertragungen…")
            change_summary = fs.compute_change_summary(original_md, revised_md)
            lint_cmp = fs.compare_lint_reports(original_md, revised_md)
            yield ev(status="log", message=f"{change_summary['hunk_count']} Änderungsblöcke erkannt "
                                           f"(Ähnlichkeit {change_summary['similarity']:.1%}).")
            from backend.services.prompts import build_analysis_prompt

            final_prompt = build_analysis_prompt(
                change_summary, lint_cmp, combined_feedback, task_meta, len(region_entries)
            )
            yield ev(status="progress", percent=15, phase="Lade Gemma 4 (lokal)…")

            if os.environ.get("E2E_MOCK") == "true":
                # Simulate the live event sequence of the real analyzer (logs, sections, tokens)
                yield ev(status="log", message="[Mock] Gemma-Modell geladen (simuliert).")
                region_findings = []
                for i in range(1, len(region_entries) + 1):
                    finding = f"Markierter Ausschnitt {i} (Mock-Strukturbeschreibung)."
                    region_findings.append(finding)
                    yield ev(status="progress", percent=20 + int((i - 1) / (len(region_entries) + 1) * 70),
                             phase=f"Analysiere markierte Stelle {i}/{len(region_entries)}")
                    yield ev(status="section", section="region", index=i)
                    for word in finding.split(" "):
                        yield ev(status="token", delta=word + " ")
                raw_report = fs.generate_mock_report(change_summary, combined_feedback, region_findings)
                yield ev(status="progress", percent=90, phase="Erstelle Fehleranalyse für Coding Assistant")
                yield ev(status="section", section="report", index=None)
                for start in range(0, len(raw_report), 80):
                    yield ev(status="token", delta=raw_report[start:start + 80])
            else:
                # GPU sequencing: stop rapid-mlx / clear caches before loading the VLM
                release_gpu_memory()
                event_q: asyncio.Queue = asyncio.Queue()

                def on_event(kind: str, data: dict):
                    event_q.put_nowait((kind, data))

                analysis_task = asyncio.create_task(fs.run_gemma_feedback_analysis(
                    final_prompt,
                    [{"path": r["path"], "prompt": r["prompt"]} for r in region_entries],
                    work_dir,
                    on_event,
                ))
                while not analysis_task.done() or not event_q.empty():
                    try:
                        kind, data = await asyncio.wait_for(event_q.get(), timeout=0.5)
                    except TimeoutError:
                        continue
                    if kind == "progress":
                        pct = 20 + int((data["step"] - 1) / max(1, data["total"]) * 70)
                        yield ev(status="progress", percent=pct, phase=data.get("label") or "Gemma analysiert…")
                    elif kind == "section":
                        yield ev(status="section", section=data["section"], index=data.get("index"))
                    elif kind == "token":
                        # Live tokens are unfiltered and never persisted (copyright guard applies to final report)
                        yield ev(status="token", delta=data["delta"])
                    else:
                        yield ev(status="log", message=data.get("message", ""))
                result = await analysis_task
                release_gpu_memory()
                region_findings = result.get("region_findings", [])
                raw_report = result.get("report", "")
                if not raw_report.strip():
                    yield ev(status="log", message="Gemma lieferte keine Antwort – heuristischer Fallback-Bericht wird erstellt.")
                    raw_report = fs.generate_mock_report(change_summary, combined_feedback, region_findings)

            yield ev(status="progress", percent=95, phase="Entferne längere Textpassagen (Urheberrecht)…")
            report = fs.redact_long_passages(fs.normalize_report_markdown(raw_report), [original_md, revised_md])
            report = report.rstrip() + "\n" + fs.build_statistics_appendix(change_summary, lint_cmp, task_meta)

            with open(os.path.join(work_dir, "report.md"), "w", encoding="utf-8") as f:
                f.write(report)
            with open(os.path.join(work_dir, "meta.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "feedback_id": feedback_id,
                    "task_id": task_id,
                    "created_at": time.time(),
                    "original_name": task.original_name,
                    "revised_filename": revised_file.filename,
                    "region_count": len(region_entries),
                    "regions": [{"page": r["page"], "note": r["note"]} for r in region_entries],
                    "region_findings": [fs.redact_long_passages(t, [original_md, revised_md]) for t in region_findings],
                    "change_summary": {k: v for k, v in change_summary.items() if k != "hunks"},
                    "lint_comparison": lint_cmp,
                }, f, ensure_ascii=False, indent=2)

            yield ev(status="completed", feedback_id=feedback_id, report=report,
                     open_questions=[q.model_dump() for q in fs.extract_open_questions(report)])
        except Exception as e:
            logger.error(f"Feedback analysis failed for task {task_id}: {e}", exc_info=True)
            yield ev(status="error", message=f"Analyse fehlgeschlagen: {e}")

    return StreamingResponse(analysis_stream(), media_type="application/x-ndjson")


@app.get("/api/feedback/reports")
async def list_feedback_reports(task_id: str | None = None):
    """Lists stored feedback reports (optionally filtered by job)."""
    reports = []
    if not os.path.isdir(FEEDBACK_DIR):
        return {"reports": reports}
    task_ids = [task_id] if task_id else os.listdir(FEEDBACK_DIR)
    for tid in task_ids:
        if not tid or not _SAFE_ID.match(tid):
            continue
        tdir = os.path.join(FEEDBACK_DIR, tid)
        if not os.path.isdir(tdir):
            continue
        for fid in os.listdir(tdir):
            meta_path = os.path.join(tdir, fid, "meta.json")
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, encoding="utf-8") as f:
                        meta = json.load(f)
                    reports.append({k: meta.get(k) for k in ("feedback_id", "task_id", "created_at", "original_name", "region_count")})
                except Exception:
                    pass
    reports.sort(key=lambda r: r.get("created_at") or 0, reverse=True)
    return {"reports": reports}


@app.get("/api/feedback/reports/{task_id}/{feedback_id}")
async def get_feedback_report(task_id: str, feedback_id: str):
    """Returns a stored feedback report."""
    if not _SAFE_ID.match(task_id) or not _SAFE_ID.match(feedback_id):
        raise HTTPException(status_code=400, detail="Ungültige ID.")
    report_path = os.path.join(FEEDBACK_DIR, task_id, feedback_id, "report.md")
    if not os.path.exists(report_path):
        raise HTTPException(status_code=404, detail="Bericht nicht gefunden.")
    with open(report_path, encoding="utf-8") as f:
        report = f.read()
    meta = {}
    meta_path = os.path.join(FEEDBACK_DIR, task_id, feedback_id, "meta.json")
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    return {"task_id": task_id, "feedback_id": feedback_id, "report": report, "meta": meta,
            "open_questions": fs_open_questions(report)}


def fs_open_questions(report: str) -> list[dict]:
    """Parsed "Offene Fragen" of a report (lazy import keeps startup light)."""
    from backend.services import feedback_service as fs
    return fs.extract_open_questions(report)


class FeedbackAnswersRequest(DomainModel):
    """Request payload for saving user answers to open questions in a feedback report."""

    answers: list[str | None]
    """Ordered list of user answer strings per open question, or None/empty when skipped."""


@app.post("/api/feedback/reports/{task_id}/{feedback_id}/answers")
async def answer_feedback_questions(task_id: str, feedback_id: str, body: FeedbackAnswersRequest):
    """Stores the user's short answers to Gemma's open questions: the
    "Offene Fragen" section of report.md is rewritten (answers as nested
    bullets, skipped questions marked as still open) and answers.json is saved.
    """
    from backend.services import feedback_service as fs

    if not _SAFE_ID.match(task_id) or not _SAFE_ID.match(feedback_id):
        raise HTTPException(status_code=400, detail="Ungültige ID.")
    work_dir = os.path.join(FEEDBACK_DIR, task_id, feedback_id)
    report_path = os.path.join(work_dir, "report.md")
    if not os.path.exists(report_path):
        raise HTTPException(status_code=404, detail="Bericht nicht gefunden.")
    with open(report_path, encoding="utf-8") as f:
        report = f.read()
    try:
        updated = fs.apply_question_answers(report, body.answers)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(updated)
    questions = [q.model_dump() for q in fs.extract_open_questions(updated)]
    with open(os.path.join(work_dir, "answers.json"), "w", encoding="utf-8") as f:
        json.dump({"answered_at": time.time(), "questions": questions}, f, ensure_ascii=False, indent=2)
    return {"report": updated, "open_questions": questions}

