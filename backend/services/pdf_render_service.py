"""PDF page rendering service with bounded LRU in-memory PNG caching and VLM grid alignment."""

import ctypes
import io
import logging
import math
import threading
from collections import OrderedDict
from contextlib import closing
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
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


def normalize_bbox_to_1000(
    bbox_obj_or_seq: Any,
    page_width: float,
    page_height: float,
    coord_origin: str = "BOTTOMLEFT",
) -> list[int] | None:
    """Normalizes a bounding box into top-left ``[x1, y1, x2, y2]`` coordinates in ``0..1000``.

    Args:
        bbox_obj_or_seq: Docling ``BoundingBox`` object (with ``l, t, r, b`` and optional
            ``coord_origin``) or a 4-element sequence ``(x1, y1, x2, y2)``.
        page_width: Page width in PDF points or pixels (> 0).
        page_height: Page height in PDF points or pixels (> 0).
        coord_origin: Coordinate origin when ``bbox_obj_or_seq`` does not specify one
            (``"BOTTOMLEFT"`` or ``"TOPLEFT"``).

    Returns:
        Four-element integer list ``[x1, y1, x2, y2]`` clamped to ``0..1000`` in top-left
        coordinates, or ``None`` if the input or page dimensions are invalid.
    """
    if bbox_obj_or_seq is None or page_width <= 0 or page_height <= 0:
        return None

    origin = str(getattr(bbox_obj_or_seq, "coord_origin", coord_origin) or coord_origin).upper()
    if all(hasattr(bbox_obj_or_seq, attr) for attr in ("l", "t", "r", "b")):
        raw_x1 = float(bbox_obj_or_seq.l)
        raw_y1 = float(bbox_obj_or_seq.t)
        raw_x2 = float(bbox_obj_or_seq.r)
        raw_y2 = float(bbox_obj_or_seq.b)
    elif isinstance(bbox_obj_or_seq, (list, tuple)) and len(bbox_obj_or_seq) == 4:
        raw_x1, raw_y1, raw_x2, raw_y2 = (
            float(bbox_obj_or_seq[0]),
            float(bbox_obj_or_seq[1]),
            float(bbox_obj_or_seq[2]),
            float(bbox_obj_or_seq[3]),
        )
    else:
        return None

    x_min = min(raw_x1, raw_x2)
    x_max = max(raw_x1, raw_x2)
    y_min = min(raw_y1, raw_y2)
    y_max = max(raw_y1, raw_y2)

    if "BOTTOM" in origin:
        top_y = page_height - y_max
        bottom_y = page_height - y_min
    else:
        top_y = y_min
        bottom_y = y_max

    def _clamp1000(val: float, span: float) -> int:
        return max(0, min(1000, int(round((val / span) * 1000.0))))

    nx1 = _clamp1000(x_min, page_width)
    ny1 = _clamp1000(top_y, page_height)
    nx2 = _clamp1000(x_max, page_width)
    ny2 = _clamp1000(bottom_y, page_height)
    if nx2 <= nx1 or ny2 <= ny1:
        return None
    return [nx1, ny1, nx2, ny2]


def compute_gemma4_optimal_dimensions(
    width: float,
    height: float,
    max_soft_tokens: int = 1120,
    patch_size: int = 16,
    pooling_kernel_size: int = 3,
) -> tuple[int, int]:
    """Computes target ``(width, height)`` pixel dimensions that trigger zero resize in Gemma 4.

    Matches ``Gemma4ImageProcessor.aspect_ratio_preserving_resize`` /
    ``get_aspect_ratio_preserving_size`` and resolves to a guaranteed fixed point
    so that passing an image of the returned ``(opt_w, opt_h)`` into the Gemma 4
    processor satisfies ``target_height == height and target_width == width`` and
    bypasses bicubic resampling completely.

    Args:
        width: Source figure width in PDF points or pixels (> 0).
        height: Source figure height in PDF points or pixels (> 0).
        max_soft_tokens: Maximum Gemma 4 vision soft token budget (default ``1120``).
        patch_size: Vision patch size in pixels (default ``16``).
        pooling_kernel_size: Spatial pooling kernel size (default ``3``, giving ``48 px`` grid).

    Returns:
        Tuple ``(opt_width, opt_height)`` as positive multiples of ``pooling_kernel_size * patch_size``.
    """
    side_mult = pooling_kernel_size * patch_size
    w_in = max(1e-3, float(width))
    h_in = max(1e-3, float(height))
    max_patches = max_soft_tokens * (pooling_kernel_size**2)
    target_px = max_patches * (patch_size**2)
    max_side_length = max_soft_tokens * side_mult

    def _processor_step(w_val: float, h_val: float) -> tuple[int, int]:
        factor = math.sqrt(target_px / (h_val * w_val))
        th = int(math.floor(factor * h_val / side_mult)) * side_mult
        tw = int(math.floor(factor * w_val / side_mult)) * side_mult
        if th == 0 and tw == 0:
            return side_mult, side_mult
        if th == 0:
            th = side_mult
            tw = max(side_mult, min(int(math.floor(w_val / h_val)) * side_mult, max_side_length))
        elif tw == 0:
            tw = side_mult
            th = max(side_mult, min(int(math.floor(h_val / w_val)) * side_mult, max_side_length))
        return tw, th

    tw0, th0 = _processor_step(w_in, h_in)
    if _processor_step(tw0, th0) == (tw0, th0):
        return tw0, th0

    n0 = max(1, tw0 // side_mult)
    m0 = max(1, th0 // side_mult)
    target_ar = w_in / h_in
    candidates: list[tuple[float, int, int, int]] = []
    for n in range(max(1, n0 - 2), n0 + 6):
        for m in range(max(1, m0 - 2), m0 + 6):
            cw, ch = n * side_mult, m * side_mult
            if _processor_step(cw, ch) == (cw, ch):
                ar_err = abs((cw / ch) - target_ar) / target_ar
                candidates.append((ar_err, -(cw * ch), cw, ch))
    if candidates:
        candidates.sort()
        return candidates[0][2], candidates[0][3]

    cw, ch = tw0, th0
    for _ in range(10):
        nw, nh = _processor_step(cw, ch)
        if (nw, nh) == (cw, ch):
            break
        cw, ch = nw, nh
    return cw, ch


def extract_raw_pdf_image(
    page: Any,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> tuple[Image.Image | None, int | None]:
    """Inspects PDF page objects inside a figure bounding box for lossless raster extraction.

    Checks ``FPDF_PAGEOBJ_IMAGE``, ``FPDF_PAGEOBJ_PATH``, ``FPDF_PAGEOBJ_TEXT``,
    ``FPDF_PAGEOBJ_SHADING``, and ``FPDF_PAGEOBJ_FORM`` objects (up to depth 4) shifted
    into CropBox-relative coordinates. Returns the lossless ``PIL.Image.Image`` directly
    from the single ``FPDF_PAGEOBJ_IMAGE`` when and only when:
    1. Exactly one non-background image object intersects the figure region with IoU >= 0.85.
    2. Zero overlaid text, shading, or internal vector diagram paths intersect the interior.
    3. The image transformation matrix has no rotation, shear, reflection, or sub-region clipping.
    4. No custom polygon/sub-window ``FPDFClipPath`` clips the image interior.
    5. The rendered image bitmap is fully opaque (no transparent ``SMask`` alpha channel).

    When the figure is a single raster image without vector/text overlays (e.g. an image with
    an ``SMask``, rotation, or clipping path that requires ``page.render``), also returns a
    recommended soft-token budget cap based on the image's native pixel resolution so
    low-resolution embedded rasters are not needlessly upscaled by 4x.

    Args:
        page: Open ``pypdfium2.PdfPage`` instance.
        x0: Left figure coordinate in CropBox-relative bottom-left PDF points.
        y0: Bottom figure coordinate in CropBox-relative bottom-left PDF points.
        x1: Right figure coordinate in CropBox-relative bottom-left PDF points.
        y1: Top figure coordinate in CropBox-relative bottom-left PDF points.

    Returns:
        Tuple ``(direct_pil_image_or_none, native_soft_token_cap_or_none)``.
    """
    if not hasattr(page, "get_objects"):
        return None, None
    try:
        pw, ph = page.get_size()
        page_area = max(1.0, float(pw) * float(ph))
        cx0 = cy0 = 0.0
        if hasattr(page, "get_bbox"):
            try:
                pb = page.get_bbox()
                if isinstance(pb, (list, tuple)) and len(pb) == 4:
                    cx0, cy0 = float(pb[0]), float(pb[1])
            except Exception:
                cx0 = cy0 = 0.0

        objs = list(page.get_objects(max_depth=4))
        if not objs:
            return None, None
    except Exception:
        return None, None

    fig_box = (x0, y0, x1, y1)
    inner_box = (x0 + 1.5, y0 + 1.5, max(x0 + 1.6, x1 - 1.5), max(y0 + 1.6, y1 - 1.5))

    def _inter(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
        ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
        iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
        return ix * iy

    def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
        inter = _inter(a, b)
        if inter <= 0.0:
            return 0.0
        area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
        area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
        return inter / max(1e-6, area_a + area_b - inter)

    imgs: list[tuple[Any, tuple[float, float, float, float]]] = []
    has_vector_or_text_overlay = False

    for obj in objs:
        try:
            otype = obj.type
            rb = obj.get_bounds()
        except Exception:
            continue
        if rb[2] <= rb[0] or rb[3] <= rb[1]:
            continue
        b = (float(rb[0]) - cx0, float(rb[1]) - cy0, float(rb[2]) - cx0, float(rb[3]) - cy0)
        obj_area = (b[2] - b[0]) * (b[3] - b[1])

        if otype == pdfium_c.FPDF_PAGEOBJ_IMAGE:
            if _inter(b, fig_box) > 1.0:
                imgs.append((obj, b))
        elif otype in (pdfium_c.FPDF_PAGEOBJ_TEXT, pdfium_c.FPDF_PAGEOBJ_SHADING):
            if _inter(b, inner_box) > 1.0:
                has_vector_or_text_overlay = True
        elif otype == pdfium_c.FPDF_PAGEOBJ_PATH:
            if obj_area < 0.5 * page_area and _iou(b, fig_box) < 0.85 and _inter(b, inner_box) > 2.0:
                has_vector_or_text_overlay = True

    if has_vector_or_text_overlay or len(imgs) != 1:
        return None, None

    img_obj, img_b = imgs[0]
    img_w, img_h = img_b[2] - img_b[0], img_b[3] - img_b[1]
    if img_w * img_h >= 0.80 * page_area:
        return None, None

    try:
        px_w, px_h = img_obj.get_px_size()
        px_w, px_h = int(px_w), int(px_h)
    except Exception:
        return None, None
    if px_w < 8 or px_h < 8:
        return None, None

    # Compute native soft-token cap for single raster images so small JPEGs aren't upscaled 4x
    native_soft_tokens = max(
        280,
        min(1120, int(math.ceil((px_w * px_h * 1.5) / float(48 * 48)))),
    )

    if _iou(img_b, fig_box) < 0.85:
        return None, native_soft_tokens

    # Reject page-bleeding images or CTM rotation, reflection, shear, or sub-region clipping
    if img_b[0] < -1.0 or img_b[1] < -1.0 or img_b[2] > pw + 1.0 or img_b[3] > ph + 1.0:
        return None, native_soft_tokens

    try:
        mat = img_obj.get_matrix()
        if mat is None:
            return None, native_soft_tokens
        if abs(float(mat.b)) > 1e-2 or abs(float(mat.c)) > 1e-2 or float(mat.a) <= 0 or float(mat.d) <= 0:
            return None, native_soft_tokens
        if abs(abs(float(mat.a)) - img_w) > 2.0 or abs(abs(float(mat.d)) - img_h) > 2.0:
            return None, native_soft_tokens
    except Exception:
        return None, native_soft_tokens

    # Inspect FPDFPageObj_GetClipPath for non-trivial clipping masks
    try:
        cp = pdfium_c.FPDFPageObj_GetClipPath(img_obj)
        if cp:
            n_paths = pdfium_c.FPDFClipPath_CountPaths(cp)
            for p_i in range(n_paths):
                n_segs = pdfium_c.FPDFClipPath_CountPathSegments(cp, p_i)
                if n_segs <= 0:
                    continue
                xs: list[float] = []
                ys: list[float] = []
                for s_i in range(n_segs):
                    seg = pdfium_c.FPDFClipPath_GetPathSegment(cp, p_i, s_i)
                    if seg:
                        vx = ctypes.c_float()
                        vy = ctypes.c_float()
                        if pdfium_c.FPDFPathSegment_GetPoint(seg, ctypes.byref(vx), ctypes.byref(vy)):
                            xs.append(float(vx.value) - cx0)
                            ys.append(float(vy.value) - cy0)
                if xs and ys:
                    cp_b = (min(xs), min(ys), max(xs), max(ys))
                    cp_area = (cp_b[2] - cp_b[0]) * (cp_b[3] - cp_b[1])
                    if not (cp_area >= 0.85 * page_area and n_segs <= 5):
                        if n_segs > 5 or _iou(cp_b, img_b) < 0.90:
                            return None, native_soft_tokens
    except Exception:
        pass

    # Extract rendered bitmap and ensure no SMask transparency is present
    try:
        bm_ren = img_obj.get_bitmap(render=True).to_pil()
        if bm_ren.mode == "RGBA":
            extrema = bm_ren.getchannel("A").getextrema()
            if extrema and extrema[0] < 250:
                return None, native_soft_tokens
        rgb_img = bm_ren.convert("RGB")
        if rgb_img.width >= 8 and rgb_img.height >= 8:
            return rgb_img, native_soft_tokens
    except Exception:
        pass

    return None, native_soft_tokens


def render_pdf_figure_crop(
    page: Any,
    bbox: Any,
    target_longest_edge: int = 2048,
    coord_origin: str = "TOPLEFT",
    is_normalized_1000: bool = False,
    align_for_gemma4: bool = True,
    gemma_max_soft_tokens: int = 1120,
) -> Image.Image | None:
    """Renders a sub-rectangle figure from a PDF page using smart native/vector extraction.

    First inspects the PDF object tree inside ``bbox`` via :func:`extract_raw_pdf_image`:
    - If the figure is a pure unclipped, opaque single ``FPDF_PAGEOBJ_IMAGE`` with zero
      overlaid text or vector paths, extracts its native bitmap losslessly (and snaps to
      native-resolution-capped Gemma 4 fixed-point dimensions when ``align_for_gemma4=True``).
    - If the figure is a single raster image requiring ``page.render`` (e.g. ``SMask``
      transparency, CTM rotation/flip, or clipping path), caps the Gemma 4 soft-token
      target to the image's native pixel resolution to avoid upscaling low-DPI JPEGs.
    - If the figure contains vector diagrams, hybrid overlaid text/paths, tiled image
      strips, or ``FPDF_PAGEOBJ_FORM`` composites, rasterizes the PDF vector sub-rectangle
      directly at full resolution.

    Args:
        page: Open ``pypdfium2.PdfPage`` instance exposing ``get_size()`` and ``render()``.
        bbox: Bounding box as ``(x1, y1, x2, y2)`` sequence or object with ``(l, t, r, b)``.
        target_longest_edge: Target pixel dimension for the longer edge when ``align_for_gemma4=False``.
        coord_origin: Coordinate system origin (``"TOPLEFT"`` or ``"BOTTOMLEFT"``).
        is_normalized_1000: Whether ``bbox`` is expressed in ``0..1000`` normalized units.
        align_for_gemma4: Whether to snap output dimensions to Gemma 4 zero-resize fixed points.
        gemma_max_soft_tokens: Maximum soft tokens for Gemma 4 alignment (default ``1120``).

    Returns:
        Rendered ``PIL.Image.Image`` of the figure sub-rectangle, or ``None`` if invalid/too small.
    """
    if page is None or bbox is None:
        return None
    try:
        pw, ph = page.get_size()
        if pw <= 0 or ph <= 0:
            return None

        origin = str(getattr(bbox, "coord_origin", coord_origin) or coord_origin).upper()
        if all(hasattr(bbox, attr) for attr in ("l", "t", "r", "b")):
            bx1, by1, bx2, by2 = float(bbox.l), float(bbox.t), float(bbox.r), float(bbox.b)
        elif isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            bx1, by1, bx2, by2 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
        else:
            return None

        if is_normalized_1000:
            fx0 = max(0.0, min(1000.0, min(bx1, bx2))) / 1000.0
            fx1 = max(0.0, min(1000.0, max(bx1, bx2))) / 1000.0
            fy0 = max(0.0, min(1000.0, min(by1, by2))) / 1000.0
            fy1 = max(0.0, min(1000.0, max(by1, by2))) / 1000.0
            x0 = fx0 * pw
            x1 = fx1 * pw
            if "BOTTOM" in origin:
                y0 = fy0 * ph
                y1 = fy1 * ph
            else:
                y0 = (1.0 - fy1) * ph
                y1 = (1.0 - fy0) * ph
        else:
            x0 = max(0.0, min(pw, min(bx1, bx2)))
            x1 = max(0.0, min(pw, max(bx1, bx2)))
            y_min = max(0.0, min(ph, min(by1, by2)))
            y_max = max(0.0, min(ph, max(by1, by2)))
            if "BOTTOM" in origin:
                y0 = y_min
                y1 = y_max
            else:
                y0 = ph - y_max
                y1 = ph - y_min

        rw = x1 - x0
        rh = y1 - y0
        if rw < 4.0 or rh < 4.0:
            return None

        raw_img, native_token_cap = extract_raw_pdf_image(page, x0, y0, x1, y1)
        effective_soft_tokens = (
            min(gemma_max_soft_tokens, native_token_cap)
            if native_token_cap is not None
            else gemma_max_soft_tokens
        )

        if raw_img is not None:
            if not align_for_gemma4:
                return raw_img
            opt_w, opt_h = compute_gemma4_optimal_dimensions(
                raw_img.width, raw_img.height, max_soft_tokens=effective_soft_tokens
            )
            if raw_img.size == (opt_w, opt_h):
                return raw_img
            scale_fit = min(opt_w / max(1, raw_img.width), opt_h / max(1, raw_img.height))
            new_w = max(1, min(opt_w, int(round(raw_img.width * scale_fit))))
            new_h = max(1, min(opt_h, int(round(raw_img.height * scale_fit))))
            resized = raw_img.resize((new_w, new_h), Image.Resampling.BICUBIC)
            if resized.size == (opt_w, opt_h):
                return resized
            canvas = Image.new("RGB", (opt_w, opt_h), color=(255, 255, 255))
            canvas.paste(resized, ((opt_w - new_w) // 2, (opt_h - new_h) // 2))
            return canvas

        opt_w = opt_h = 0
        if align_for_gemma4:
            opt_w, opt_h = compute_gemma4_optimal_dimensions(
                rw, rh, max_soft_tokens=effective_soft_tokens
            )
            scale = min(32.0, max(0.2, min(opt_w / rw, opt_h / rh)))
        else:
            scale = min(8.0, max(0.2, float(target_longest_edge) / max(rw, rh, 1.0)))

        if round(rw * scale) < 8 or round(rh * scale) < 8:
            return None

        left_cut = max(0.0, x0)
        bottom_cut = max(0.0, y0)
        right_cut = max(0.0, pw - x1)
        top_cut = max(0.0, ph - y1)

        bitmap = page.render(
            scale=scale,
            crop=(left_cut, bottom_cut, right_cut, top_cut),
        )
        pil_img = bitmap.to_pil()
        if align_for_gemma4 and opt_w > 0 and opt_h > 0 and pil_img.size != (opt_w, opt_h):
            rgb_img = pil_img.convert("RGB")
            canvas = Image.new("RGB", (opt_w, opt_h), color=(255, 255, 255))
            offset_x = (opt_w - rgb_img.width) // 2
            offset_y = (opt_h - rgb_img.height) // 2
            canvas.paste(rgb_img, (offset_x, offset_y))
            return canvas
        return pil_img
    except Exception as exc:
        logger.debug("Vector figure crop render fallback: %s", exc)
        return None

