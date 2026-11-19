"""Workload-aware stage progress budget and monotonic percentage calculation helpers."""

from __future__ import annotations

import math
import os

from backend.services import fibs_constants as fc
from backend.services.models import StageProgressBudget


def count_pdf_embedded_images(pdf_path: str) -> int:
    """Counts non-trivial embedded raster images in a PDF via fast PDFium object inspection.

    Scans ``FPDF_PAGEOBJ_IMAGE`` page objects with dimensions of at least ``36 x 36`` pt,
    deduplicating heavily overlapping tile bounding boxes per page and capping per-page
    counts so mosaic strips do not inflate estimates.

    Args:
        pdf_path: Path to the input file on disk.

    Returns:
        Estimated count of meaningful embedded PDF images, or ``0`` on non-PDF or error.
    """
    if not pdf_path or not pdf_path.lower().endswith(".pdf") or not os.path.exists(pdf_path):
        return 0
    try:
        import pypdfium2 as pdfium
        import pypdfium2.raw as pdfium_c
    except ImportError:
        return 0

    total_images = 0
    pdf = None
    try:
        pdf = pdfium.PdfDocument(pdf_path)
        for page_idx in range(len(pdf)):
            page = pdf[page_idx]
            accepted_boxes: list[tuple[float, float, float, float]] = []
            try:
                objs = page.get_objects(
                    filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE],
                    max_depth=2,
                )
                for obj in objs:
                    try:
                        x0, y0, x1, y1 = (float(v) for v in obj.get_bounds())
                    except Exception:
                        continue
                    width = x1 - x0
                    height = y1 - y0
                    if width < 36.0 or height < 36.0:
                        continue
                    area = width * height
                    is_duplicate = False
                    for ex0, ey0, ex1, ey1 in accepted_boxes:
                        inter_w = max(0.0, min(x1, ex1) - max(x0, ex0))
                        inter_h = max(0.0, min(y1, ey1) - max(y0, ey0))
                        inter = inter_w * inter_h
                        if inter > 0.0:
                            ex_area = max(1e-6, (ex1 - ex0) * (ey1 - ey0))
                            if inter / max(1e-6, min(area, ex_area)) >= 0.75:
                                is_duplicate = True
                                break
                    if not is_duplicate:
                        accepted_boxes.append((x0, y0, x1, y1))
                        if len(accepted_boxes) >= 15:
                            break
            except Exception:
                pass
            finally:
                try:
                    page.close()
                except Exception:
                    pass
            total_images += len(accepted_boxes)
    except Exception:
        return 0
    finally:
        if pdf is not None:
            try:
                pdf.close()
            except Exception:
                pass
    return total_images


def compute_post_extraction_budget(
    start_percent: int,
    uncached_images: int,
    cached_images: int,
    describe_images: bool,
    total_chunks: int,
) -> StageProgressBudget:
    """Computes exact Stage 2 (VLM) and Stage 3 (Gemma) bounds from ``start_percent`` to 99%.

    Args:
        start_percent: Percentage reached at the end of Stage 1 extraction (clamped to 0..95).
        uncached_images: Number of extracted images requiring fresh VLM inference.
        cached_images: Number of extracted images already present in ``vlm_cache.json``.
        describe_images: Whether VLM image description is enabled for this run.
        total_chunks: Planned number of Gemma 4 12B page chunks.

    Returns:
        Validated ``StageProgressBudget`` covering ``[base .. 99]``.
    """
    base = max(0, min(95, int(start_percent)))
    end = fc.PROGRESS_FINALIZE_PERCENT
    uncached = max(0, int(uncached_images))
    cached = max(0, int(cached_images))
    chunks = max(1, int(total_chunks))

    if not describe_images or (uncached + cached) <= 0:
        return StageProgressBudget(
            extraction_end_percent=base,
            vlm_start_percent=base,
            vlm_end_percent=base,
            gemma_start_percent=base,
            gemma_end_percent=end,
        )

    vlm_init = fc.PROGRESS_VLM_INIT_SECONDS if uncached > 0 else 0.5
    t_vlm = (
        vlm_init
        + uncached * fc.PROGRESS_VLM_SECONDS_PER_IMAGE
        + cached * fc.PROGRESS_VLM_CACHED_SECONDS_PER_IMAGE
    )
    t_gemma = fc.PROGRESS_GEMMA_INIT_SECONDS + chunks * fc.PROGRESS_GEMMA_SECONDS_PER_CHUNK

    remaining = max(1, end - base)
    if remaining >= 2:
        min_gemma = min(4, remaining - 1)
        max_vlm = max(1, remaining - min_gemma)
        raw_vlm = int(round(remaining * (t_vlm / max(1e-6, t_vlm + t_gemma))))
        vlm_points = max(1, min(max_vlm, raw_vlm))
    else:
        vlm_points = 0

    vlm_end = base + vlm_points
    return StageProgressBudget(
        extraction_end_percent=base,
        vlm_start_percent=base,
        vlm_end_percent=vlm_end,
        gemma_start_percent=vlm_end,
        gemma_end_percent=end,
    )


def compute_extraction_budget(
    engine: str,
    page_count: int,
    estimated_images: int,
    describe_images: bool = True,
    is_pdf: bool = True,
) -> StageProgressBudget:
    """Computes expected Stage 1 extraction ceiling and tentative VLM/Gemma splits.

    Args:
        engine: Selected extraction engine identifier (e.g. ``"docling"``, ``"lightonocr"``, ``"infinity"``).
        page_count: Number of pages to extract.
        estimated_images: Estimated number of embedded images in the selected pages.
        describe_images: Whether Stage 2 VLM image description is enabled.
        is_pdf: Whether the uploaded file is a PDF document.

    Returns:
        Validated ``StageProgressBudget`` with ``extraction_end_percent`` clamped to ``[5, 70]``.
    """
    eng_key = "non_pdf" if not is_pdf else (engine or "lightonocr").strip().lower()
    init_s = fc.PROGRESS_EXTRACTION_INIT_SECONDS.get(
        eng_key, fc.PROGRESS_EXTRACTION_INIT_SECONDS["lightonocr"]
    )
    per_page_s = fc.PROGRESS_EXTRACTION_SECONDS_PER_PAGE.get(
        eng_key, fc.PROGRESS_EXTRACTION_SECONDS_PER_PAGE["lightonocr"]
    )

    pages = max(1, int(page_count))
    imgs = max(0, int(estimated_images))
    est_chunks = max(1, math.ceil(pages / fc.PROGRESS_GEMMA_ESTIMATED_PAGES_PER_CHUNK))

    t_extract = init_s + pages * per_page_s
    t_vlm = (
        fc.PROGRESS_VLM_INIT_SECONDS + imgs * fc.PROGRESS_VLM_SECONDS_PER_IMAGE
        if (describe_images and imgs > 0)
        else 0.0
    )
    t_gemma = fc.PROGRESS_GEMMA_INIT_SECONDS + est_chunks * fc.PROGRESS_GEMMA_SECONDS_PER_CHUNK

    total_seconds = max(1e-6, t_extract + t_vlm + t_gemma)
    raw_extract_pct = int(round((t_extract / total_seconds) * fc.PROGRESS_FINALIZE_PERCENT))
    extraction_end = max(
        fc.PROGRESS_MIN_EXTRACTION_PERCENT,
        min(fc.PROGRESS_MAX_EXTRACTION_PERCENT, raw_extract_pct),
    )

    return compute_post_extraction_budget(
        start_percent=extraction_end,
        uncached_images=imgs if describe_images else 0,
        cached_images=0,
        describe_images=describe_images,
        total_chunks=est_chunks,
    )


def compute_vlm_image_percent(
    budget: StageProgressBudget,
    current_index: int,
    total_images: int,
    *,
    finished: bool = False,
) -> int:
    """Maps 1-based VLM image index cleanly across ``[budget.vlm_start_percent .. budget.vlm_end_percent]``.

    Args:
        budget: Active stage progress budget.
        current_index: 1-based index of the image starting or completing VLM description.
        total_images: Total number of images scheduled for VLM description.
        finished: Whether all VLM image descriptions have completed.

    Returns:
        Monotonic integer percentage within ``[budget.vlm_start_percent, budget.vlm_end_percent]``.
    """
    start = budget.vlm_start_percent
    end = budget.vlm_end_percent
    span = max(0, end - start)
    if finished or span == 0:
        return end

    total = max(1, int(total_images))
    idx = max(0, min(total, int(current_index)))
    if idx <= 0:
        return start

    init_offset = 1 if span >= 3 else 0
    work_span = max(0, span - init_offset)
    pct = start + init_offset + int(((idx - 1) / total) * work_span)
    return max(start, min(end, pct))


def compute_gemma_stream_percent(
    budget: StageProgressBudget,
    chunk_index: int,
    total_chunks: int,
    streamed_chars_in_chunk: int = 0,
    expected_chars_in_chunk: int = 2500,
) -> int:
    """Maps chunk index and streamed characters monotonically inside ``[gemma_start .. gemma_end]``.

    Args:
        budget: Active stage progress budget.
        chunk_index: 1-based index of the currently active Gemma standardisation chunk.
        total_chunks: Total number of planned Gemma standardisation chunks.
        streamed_chars_in_chunk: Characters streamed so far within the active chunk.
        expected_chars_in_chunk: Expected output character count for one chunk.

    Returns:
        Monotonic integer percentage within ``[budget.gemma_start_percent, budget.gemma_end_percent]``.
    """
    start = budget.gemma_start_percent
    end = budget.gemma_end_percent
    span = max(0, end - start)
    if span == 0:
        return end

    total = max(1, int(total_chunks))
    idx = max(1, min(total, int(chunk_index)))
    chars = max(0, int(streamed_chars_in_chunk))
    denom = max(200.0, float(expected_chars_in_chunk) * 1.15)
    intra = min(0.92, chars / denom)
    fraction = ((idx - 1) + intra) / total
    pct = start + int(fraction * span)
    return max(start, min(end, pct))
