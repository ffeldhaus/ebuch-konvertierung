"""PDF page rendering service with bounded LRU in-memory PNG caching and VLM grid alignment."""

import io
import logging
import threading
from collections import OrderedDict
from contextlib import closing
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
from PIL import Image

logger = logging.getLogger(__name__)

# Bounded in-memory LRU cache for rendered page bytes (max 30 pages to prevent memory pressure on 100+ page PDFs)
_PAGE_BYTES_CACHE_MAX_SIZE = 30
_PAGE_BYTES_CACHE: OrderedDict[str, bytes] = OrderedDict()
_CACHE_LOCK = threading.Lock()


def get_cached_page_bytes(cache_key: str) -> bytes | None:
    """Retrieves rendered page bytes from the thread-safe LRU in-memory cache.

    Args:
        cache_key: Composite cache key identifying the PDF path, page index, scale, and mtime.

    Returns:
        Cached PNG bytes if present, otherwise ``None``.
    """
    with _CACHE_LOCK:
        if cache_key in _PAGE_BYTES_CACHE:
            _PAGE_BYTES_CACHE.move_to_end(cache_key)
            return _PAGE_BYTES_CACHE[cache_key]
        return None


def store_cached_page_bytes(cache_key: str, data: bytes) -> None:
    """Stores rendered page bytes into the bounded thread-safe LRU in-memory cache.

    Args:
        cache_key: Composite cache key identifying the PDF path, page index, scale, and mtime.
        data: Encoded PNG bytes to cache.
    """
    with _CACHE_LOCK:
        _PAGE_BYTES_CACHE[cache_key] = data
        _PAGE_BYTES_CACHE.move_to_end(cache_key)
        if len(_PAGE_BYTES_CACHE) > _PAGE_BYTES_CACHE_MAX_SIZE:
            _PAGE_BYTES_CACHE.popitem(last=False)


def render_single_page_bytes(
    pdf_path: str | Path,
    page_idx: int,
    scale: float = 2.0,
) -> bytes | None:
    """Renders a single PDF page directly to PNG bytes using in-memory LRU caching.

    Safely handles documents of arbitrary length (100+ pages) without excessive
    memory usage or native PDFium handle leaks.

    Args:
        pdf_path: Filesystem path to the source PDF document.
        page_idx: Zero-based page index to render.
        scale: Rendering scale factor relative to 72 DPI (default ``2.0`` = 144 DPI).

    Returns:
        Encoded PNG image bytes, or ``None`` if the file/page does not exist or rendering fails.
    """
    path = Path(pdf_path)
    if not path.is_file():
        return None

    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0

    cache_key = f"{path}:{page_idx}:{scale}:{mtime}"
    cached = get_cached_page_bytes(cache_key)
    if cached is not None:
        return cached

    try:
        with closing(pdfium.PdfDocument(str(path))) as doc:
            if page_idx < 0 or page_idx >= len(doc):
                return None

            with closing(doc[page_idx]) as page:
                bitmap = page.render(scale=scale)
                pil_img = bitmap.to_pil()

                buffer = io.BytesIO()
                pil_img.save(buffer, format="PNG")
                png_bytes = buffer.getvalue()

        store_cached_page_bytes(cache_key, png_bytes)
        return png_bytes
    except Exception as exc:
        logger.error("Error rendering single PDF page %d to bytes: %s", page_idx, exc)
        return None


def render_pdf_page_for_vlm(
    page: Any,
    target_longest_edge: float = 1536.0,
    grid_factor: int = 32,
    min_scale: float = 1.25,
    max_scale: float = 2.8,
) -> Image.Image:
    """Renders a ``pypdfium2`` page to a PIL Image aligned to the VLM patch-merge grid.

    Aligning dimensions to exact multiples of ``grid_factor`` (32 px = 16 px patch_size *
    2 spatial_merge_size for Qwen3-VL / LightOnOCR-3 / Infinity-Parser2-Flash) prevents
    the HuggingFace image processor from performing a second lossy bicubic resize on
    rendered glyph edges.

    Args:
        page: Open ``pypdfium2.PdfPage`` instance exposing ``get_size()`` and ``render()``.
        target_longest_edge: Target pixel length for the longer page dimension.
        grid_factor: Spatial patch-grid multiple to snap width and height to.
        min_scale: Minimum allowed PDF rendering scale factor.
        max_scale: Maximum allowed PDF rendering scale factor.

    Returns:
        Grid-aligned RGB ``PIL.Image.Image`` ready for VLM-OCR inference.
    """
    w, h = page.get_size()
    scale = max(min_scale, min(max_scale, target_longest_edge / max(w, h, 1.0)))
    pil_img = page.render(scale=scale).to_pil()
    if grid_factor > 1:
        gw = max(grid_factor, int(round(pil_img.width / grid_factor)) * grid_factor)
        gh = max(grid_factor, int(round(pil_img.height / grid_factor)) * grid_factor)
        if (gw, gh) != pil_img.size:
            pil_img = pil_img.resize((gw, gh), Image.Resampling.BICUBIC)
    return pil_img
