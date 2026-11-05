"""Engine-neutral post-processing and hybrid Docling layout fusion for extracted Markdown."""

import hashlib
import json
import logging
import os
import re
import statistics
from typing import Any

from backend.services import fibs_constants as fc
from backend.services.pdf_render_service import (
    normalize_bbox_to_1000,
    render_pdf_figure_crop,
)

logger = logging.getLogger("extraction_postprocess")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DOCLING_MODELS_PATH = os.path.join(PROJECT_ROOT, "assets", "models", "docling")


def fix_escaped_dollars(text: str) -> str:
    r"""Unescapes \$...\$ inline math delimiters emitted by some VLM OCR models."""
    if not text or "\\$" not in text:
        return text
    return re.sub(r"\\\$([^\$\n]+?)\\\$", r"$\1$", text)


def clean_html_layout_tags(text: str) -> str:
    """Converts inline HTML layout wrappers (<div>, <p>, <br/>, <ul>, <li>, <strong>, <em>)
    sometimes emitted by VLM OCR models for multi-column / flexbox layouts into clean Markdown.
    """
    if not text or "<" not in text:
        return text
    # Convert <li>...</li> into Markdown list items
    text = re.sub(r"<li\b[^>]*>\s*(.*?)\s*</li>", r"- \1", text, flags=re.DOTALL | re.IGNORECASE)
    # Convert <br/> to newline
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    # Convert <strong> / <b> and <em> / <i>
    text = re.sub(r"<(?:strong|b)\b[^>]*>(.*?)</(?:strong|b)>", r"**\1**", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<(?:em|i)\b[^>]*>(.*?)</(?:em|i)>", r"*\1*", text, flags=re.DOTALL | re.IGNORECASE)
    # Strip layout container tags (<div>, <p>, <ul>, <ol>, <span>)
    text = re.sub(r"</?(?:div|p|ul|ol|span)\b[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Unwrap bold figure label prefix '**Abbildung 4.2a:** Rest' -> 'Abbildung 4.2a: Rest'
    text = re.sub(
        r"(?m)^[ \t]*\*\*((?:Abbildung|Abb\.|Bild|Grafik|Figure|Fig\.)\s+[^\*:\n]+:?)\*\*[ \t]*",
        r"\1 ",
        text,
        flags=re.IGNORECASE,
    )
    # Strip trailing 'Seite N' that was inside a right-aligned footer div
    text = re.sub(
        r"\n+\s*(?:Seite|Page)\s+(?:\d+|[IVXLCDMivxlcdm]+)\s*(?=\n+\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)|\Z)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_markdown_fences(text: str) -> str:
    """Strips wrapping or mid-page ```markdown ... ``` code fences, cleans HTML layout wrappers,
    sanitizes runaway repeating tokens, and ensures clean heading line breaks.
    """
    if not text:
        return text
    trimmed = sanitize_runaway_repetitions(clean_html_layout_tags(text.strip()))

    # Remove standalone code fence lines (```markdown, ```html, ```latex, ```) anywhere in the page
    lines = trimmed.splitlines()
    cleaned_lines = [
        line for line in lines
        if not re.match(r"^\s*```(?:markdown|md|html|latex|text)?\s*$", line, re.IGNORECASE)
    ]
    trimmed = "\n".join(cleaned_lines).strip()

    # Ensure headings start on fresh lines if generated inline
    trimmed = re.sub(r"(?<!\n)\s+(#{1,6}\s+)", r"\n\n\1", trimmed)
    return trimmed


def convert_html_tables_to_markdown(text: str) -> str:
    """Converts HTML <table>...</table> blocks (as emitted by LightOnOCR-3 or VLM OCR)
    into clean GFM pipe tables (| col1 | col2 |).
    """
    if not text or "<table" not in text.lower():
        return text

    def _table_repl(match: re.Match) -> str:
        html_block = match.group(0)
        row_matches = re.findall(r"<tr\b[^>]*>(.*?)</tr>", html_block, flags=re.DOTALL | re.IGNORECASE)
        if not row_matches:
            return html_block

        rows: list[list[str]] = []
        for tr_inner in row_matches:
            cells = re.findall(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", tr_inner, flags=re.DOTALL | re.IGNORECASE)
            if not cells:
                continue
            cleaned_cells = []
            for c in cells:
                c_text = re.sub(r"<br\s*/?>", " ", c, flags=re.IGNORECASE)
                c_text = re.sub(r"</?(?:p|div|span|b|i|strong|em|sub|sup)\b[^>]*>", "", c_text, flags=re.IGNORECASE)
                c_text = re.sub(r"\s+", " ", c_text).strip()
                cleaned_cells.append(c_text)
            rows.append(cleaned_cells)

        if not rows:
            return html_block

        max_cols = max(len(r) for r in rows)
        if max_cols == 0:
            return html_block

        md_lines = []
        for r_idx, r in enumerate(rows):
            padded = r + [""] * (max_cols - len(r))
            md_lines.append("| " + " | ".join(padded) + " |")
            if r_idx == 0:
                md_lines.append("| " + " | ".join(["---"] * max_cols) + " |")

        return "\n".join(md_lines)

    return re.sub(r"<table\b[^>]*>.*?</table>", _table_repl, text, flags=re.DOTALL | re.IGNORECASE)


def detect_pdf_callout_rects_by_page(pdf_path: str) -> dict[int, list[tuple[float, float, float, float]]]:
    """Detects drawn vector callout box rectangles per page via pypdfium2."""
    callout_rects_by_page: dict[int, list[tuple[float, float, float, float]]] = {}
    try:
        import pypdfium2 as pdfium
        pdf_doc = pdfium.PdfDocument(pdf_path)
        for p_i in range(len(pdf_doc)):
            page = pdf_doc[p_i]
            pw, ph = page.get_size()
            rects = []
            for obj in page.get_objects():
                if obj.type == 2:  # FPDF_PAGEOBJ_PATH
                    l_b, b_b, r_b, t_b = obj.get_bounds()
                    w_b = r_b - l_b
                    h_b = t_b - b_b
                    if w_b >= 95 and 32 <= h_b <= ph * 0.62 and b_b > 35 and t_b < ph - 35:
                        rects.append((l_b, b_b, r_b, t_b))
            callout_rects_by_page[p_i] = rects
        pdf_doc.close()
    except Exception:
        pass
    return callout_rects_by_page


def parse_furniture_opening_header(text: str, seen_opening_keys: set) -> str | None:
    """Checks if a running page_header furniture line is the first appearance of a numbered chapter/section title."""
    if re.fullmatch(r"\d{1,4}", text):
        return None
    clean_hdr = re.sub(r"^(?:\d{1,4}\s+)?(.*?)(?:\s+\d{1,4})?$", r"\1", text).strip()
    clean_hdr = re.sub(r"\b(?:ii|II|1I|I1)\b", "11", clean_hdr)
    clean_hdr = re.sub(
        r"\b(IN|AN|AUF|VON|MIT|FÜR|ZU|BEI)(UNTERSCHIEDLICHEN|VERSCHIEDENEN|GLEICHEN|ANDEREN)([A-ZÄÖÜ]{3,})\b",
        r"\1 \2 \3",
        clean_hdr,
    )
    norm_key = re.sub(r"\s+", " ", clean_hdr).lower()
    if norm_key in seen_opening_keys:
        return None
    if re.match(r"^kapitel\s+\d+\.?\s+\S", norm_key):
        seen_opening_keys.add(norm_key)
        title_cased = re.sub(
            r"^KAPITEL\s+(\d+\.?)\s+([A-ZÄÖÜ])([A-ZÄÖÜ]+)$",
            lambda m: f"Kapitel {m.group(1)} {m.group(2)}{m.group(3).lower()}",
            clean_hdr,
        )
        return f"# {title_cased}"
    if re.match(r"^\d+\.\d+\.?\s+[a-zäöü]", norm_key):
        seen_opening_keys.add(norm_key)
        return f"## {clean_hdr}"
    return None


def is_bbox_inside_callout_rect(
    bbox_obj: Any,
    text: str,
    page_rects: list[tuple[float, float, float, float]],
) -> bool:
    """Returns True if a heading bbox lies inside a drawn vector callout rectangle on that page."""
    if not bbox_obj or not page_rects:
        return False
    b_l = min(bbox_obj.l, bbox_obj.r)
    b_r = max(bbox_obj.l, bbox_obj.r)
    b_b = min(bbox_obj.b, bbox_obj.t)
    b_t = max(bbox_obj.b, bbox_obj.t)
    for rl, rb, rr, rt in page_rects:
        if b_l >= rl - 6 and b_r <= rr + 6 and b_b >= rb - 6 and b_t <= rt + 6:
            if not re.match(
                r"^(?:Kapitel|Chapter|\d+\.\d+|Aufgabe\s+\d+|Übung\s+\d+|Tab(?:elle)?\.?\s+\d+)",
                text,
                re.IGNORECASE,
            ):
                return True
    return False


_LAST_DOCLING_LAYOUT: dict[str, Any] = {}

_TABLE_PLACEHOLDER_CELLS: set[str] = {"", "...", "…", "_..._", "-", "–", "—"}

_MARGINALIA_GLOSSARY_RE = re.compile(
    r"^(?:"
    r"[¹²³⁴⁵⁶⁷⁸⁹]+\s*\S"
    r"|\^\d+\s+[A-ZÄÖÜa-zäöü]"
    r"|[Ww]orterklärung\b"
    r"|\d{1,2} [A-ZÄÖÜa-zäöü][a-zäöüß]+[^\n]*(?:[:.,;=–—]|\s+\S+\s+\S+)"
    r")"
)


def _is_marginalia_or_glossary_note(text: str) -> bool:
    """Checks whether a text item is a margin glossary definition or footnote explanation.

    Args:
        text: Candidate text block string.

    Returns:
        True if the text starts with a footnote/glossary marker or ``Worterklärung``
        rather than a running header/footer.
    """
    s = (text or "").strip()
    if not s or s.isupper():
        return False
    if re.match(r"^(?:\d+\s+)?(?:Kapitel|Chapter|Seite|Page|Teil|Abschnitt)\b", s, re.IGNORECASE):
        return False
    return bool(_MARGINALIA_GLOSSARY_RE.match(s))


def _parse_pipe_table_rows(table_md: str) -> list[list[str]]:
    """Parses a Markdown pipe table into a list of cell lists, excluding separator rows.

    Args:
        table_md: Markdown pipe table string.

    Returns:
        List of rows, where each row is a list of stripped cell strings.
    """
    rows: list[list[str]] = []
    for raw_line in (table_md or "").splitlines():
        stripped = raw_line.strip()
        if not stripped or "|" not in stripped:
            continue
        inner = stripped.strip("|").strip()
        if re.match(r"^[\s\|:\-]+$", inner):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        rows.append(cells)
    return rows


def _is_degenerate_diagram_table(table_md: str) -> bool:
    """Detects false-positive TableFormer pipe tables extracted from diagram/chart axes.

    Args:
        table_md: Candidate Markdown pipe table string.

    Returns:
        True if the table has fewer than 2 rows (no data rows), or if all data rows
        have at least 50% empty/placeholder cells, or if a short table (<= 3 rows)
        has only empty/placeholder data cells.
    """
    rows = _parse_pipe_table_rows(table_md)
    if len(rows) < 2:
        if (
            len(rows) == 1
            and len([c for c in rows[0] if c]) >= 2
            and all(re.match(r"^\*?\*?\d+\.\s+\S", c) for c in rows[0] if c)
        ):
            return False
        return True
    data_rows = rows[1:]
    if all(
        not row or sum(1 for c in row if c in _TABLE_PLACEHOLDER_CELLS) / len(row) >= 0.5
        for row in data_rows
    ):
        return True
    if len(rows) <= 3 and all(c in _TABLE_PLACEHOLDER_CELLS for row in data_rows for c in row):
        return True
    return False


def _extract_rect_coords(box: Any) -> tuple[float, float, float, float] | None:
    """Normalizes a bbox object or 4-tuple/list into ``(x0, y0, x1, y1)`` with ``x0 <= x1, y0 <= y1``.

    Args:
        box: A 4-element sequence ``[x0, y0, x1, y1]`` or object with ``l, b, r, t`` attributes.

    Returns:
        Normalized ``(x0, y0, x1, y1)`` tuple, or ``None`` if invalid.
    """
    if box is None:
        return None
    if isinstance(box, (list, tuple)) and len(box) >= 4:
        x0, y0, x1, y1 = float(box[0]), float(box[1]), float(box[2]), float(box[3])
    elif all(hasattr(box, attr) for attr in ("l", "b", "r", "t")):
        x0, y0, x1, y1 = float(box.l), float(box.b), float(box.r), float(box.t)
    else:
        return None
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _bbox_overlap_ratio(box_a: Any, box_b: Any) -> float:
    """Computes the fraction of ``box_a``'s area that intersects with ``box_b``.

    Args:
        box_a: First bounding box (sequence or bbox object).
        box_b: Second bounding box (sequence or bbox object).

    Returns:
        Intersection area divided by ``area(box_a)`` in ``[0.0, 1.0]``.
    """
    ra = _extract_rect_coords(box_a)
    rb = _extract_rect_coords(box_b)
    if ra is None or rb is None:
        return 0.0
    ax0, ay0, ax1, ay1 = ra
    bx0, by0, bx1, by1 = rb
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    if area_a <= 0.0:
        return 0.0
    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    return inter / area_a


def _filter_page_figure_bboxes(
    bboxes: list[Any],
    page_width: float = 1000.0,
    page_height: float = 1000.0,
) -> list[tuple[int, tuple[float, float, float, float]]]:
    """Filters nested sub-figure crops and merges tiny icon/label fragments on a page.

    1. Drops any box A contained inside a larger box B on the same page
       (``intersection_area / area(A) >= 0.65``).
    2. When a page has 3 or more figure boxes and one of them has a tiny area
       (``< 1.2%`` of page area) and is spatially close (``< 5%`` page width/height gap)
       or overlapping another figure box, merges its bounding box into the neighboring
       figure box rather than emitting a standalone crop.

    Args:
        bboxes: List of candidate figure bounding boxes on the page.
        page_width: Page width in the same coordinate system as ``bboxes``.
        page_height: Page height in the same coordinate system as ``bboxes``.

    Returns:
        List of ``(original_index, (x0, y0, x1, y1))`` for surviving figure boxes.
    """
    indexed_rects: list[tuple[int, tuple[float, float, float, float]]] = []
    for idx, b in enumerate(bboxes):
        rect = _extract_rect_coords(b)
        if rect is not None:
            indexed_rects.append((idx, rect))
    if len(indexed_rects) <= 1:
        return indexed_rects

    pw = page_width if page_width > 0 else 1000.0
    ph = page_height if page_height > 0 else 1000.0
    page_area = pw * ph
    initial_count = len(indexed_rects)

    def _rect_area(r: tuple[float, float, float, float]) -> float:
        return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])

    def _drop_contained(
        items: list[tuple[int, tuple[float, float, float, float]]],
    ) -> list[tuple[int, tuple[float, float, float, float]]]:
        kept: list[tuple[int, tuple[float, float, float, float]]] = []
        for i, (idx_a, rect_a) in enumerate(items):
            area_a = _rect_area(rect_a)
            contained = False
            for j, (idx_b, rect_b) in enumerate(items):
                if i == j:
                    continue
                area_b = _rect_area(rect_b)
                if area_b > area_a or (area_b == area_a and idx_b < idx_a):
                    if _bbox_overlap_ratio(rect_a, rect_b) >= 0.65:
                        contained = True
                        break
            if not contained:
                kept.append((idx_a, rect_a))
        return kept

    surviving = _drop_contained(indexed_rects)

    if initial_count >= 3 and len(surviving) >= 2:
        tiny_threshold = 0.012 * page_area
        max_gap_x = 0.05 * pw
        max_gap_y = 0.05 * ph
        rects_by_pos = [list(item) for item in surviving]
        dropped_positions: set[int] = set()

        for i, (_idx_a, rect_a) in enumerate(rects_by_pos):
            if i in dropped_positions:
                continue
            if _rect_area(rect_a) >= tiny_threshold:
                continue
            ax0, ay0, ax1, ay1 = rect_a
            best_j: int | None = None
            best_dist = float("inf")
            for j, (_idx_b, rect_b) in enumerate(rects_by_pos):
                if i == j or j in dropped_positions:
                    continue
                bx0, by0, bx1, by1 = rect_b
                gap_x = max(0.0, max(ax0, bx0) - min(ax1, bx1))
                gap_y = max(0.0, max(ay0, by0) - min(ay1, by1))
                if gap_x < max_gap_x and gap_y < max_gap_y:
                    dist = gap_x + gap_y
                    if dist < best_dist:
                        best_dist = dist
                        best_j = j
            if best_j is not None:
                bx0, by0, bx1, by1 = rects_by_pos[best_j][1]
                rects_by_pos[best_j][1] = (
                    min(bx0, ax0),
                    min(by0, ay0),
                    max(bx1, ax1),
                    max(by1, ay1),
                )
                dropped_positions.add(i)

        surviving = [
            (int(item[0]), item[1])
            for k, item in enumerate(rects_by_pos)
            if k not in dropped_positions
        ]
        surviving = _drop_contained(surviving)

    return surviving


def extract_docling_page_layout(pdf_path: str, images_dir: str) -> dict[str, Any]:
    """Run hybrid Docling CPU Layout & TableFormer extraction in a single pass.

    Extracts from any digital or scanned PDF:
      - pictures_by_page: {page_idx: [img_filename, ...]}
      - tables_by_page: {page_idx: [markdown_table, ...]}
      - furniture_by_page: {page_idx: [{"type": str, "text": str, "page_idx": int}, ...]}
      - heading_blocks: [{"type": "title", "text": str, "text_level": 1, "page_idx": int, "bbox": [0, 0, w, h], "is_body_sized": bool}, ...]
      - text_blocks: [{"type": str, "text": str, "page_idx": int}, ...]
      - text_blocks_by_page: {page_idx: [{"type": str, "text": str, "page_idx": int}, ...]}
      - opening_headers_by_page: {page_idx: [heading_str, ...]} for chapter/section titles placed in the PDF running header
      - body_line_height: float
    """
    global _LAST_DOCLING_LAYOUT
    os.makedirs(images_dir, exist_ok=True)
    result: dict[str, Any] = {
        "pictures_by_page": {},
        "tables_by_page": {},
        "furniture_by_page": {},
        "heading_blocks": [],
        "layout_blocks": [],
        "text_blocks": [],
        "text_blocks_by_page": {},
        "opening_headers_by_page": {},
        "body_line_height": 0.0,
    }
    if not pdf_path or not os.path.exists(pdf_path) or not pdf_path.lower().endswith(".pdf"):
        return result

    try:
        from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import AcceleratorDevice, PdfPipelineOptions, TableFormerMode
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling_core.types.doc import ContentLayer

        pipeline_options = PdfPipelineOptions()
        pipeline_options.accelerator_options.device = AcceleratorDevice.CPU
        if os.path.isdir(DEFAULT_DOCLING_MODELS_PATH):
            pipeline_options.artifacts_path = DEFAULT_DOCLING_MODELS_PATH
        pipeline_options.do_ocr = False
        pipeline_options.do_formula_enrichment = False
        pipeline_options.do_table_structure = True
        pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE
        pipeline_options.table_structure_options.do_cell_matching = True
        pipeline_options.generate_picture_images = True
        pipeline_options.generate_table_images = False

        format_options = {
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options,
                backend=PyPdfiumDocumentBackend,
            )
        }
        converter = DocumentConverter(format_options=format_options)
        conv_res = converter.convert(pdf_path)
        doc = conv_res.document

        pdf_doc_shared = None
        page_sizes_by_idx: dict[int, tuple[float, float]] = {}
        try:
            import pypdfium2 as pdfium

            pdf_doc_shared = pdfium.PdfDocument(pdf_path)
            for p_i in range(len(pdf_doc_shared)):
                page_sizes_by_idx[p_i] = pdf_doc_shared[p_i].get_size()
        except Exception:
            pdf_doc_shared = None

        if getattr(doc, "pages", None):
            page_entries = (
                doc.pages.items()
                if isinstance(doc.pages, dict)
                else [(idx + 1, pm) for idx, pm in enumerate(doc.pages)]
            )
            for p_no, page_meta in page_entries:
                p_idx = max(0, int(p_no) - 1)
                if p_idx not in page_sizes_by_idx and getattr(page_meta, "size", None):
                    sz = page_meta.size
                    if getattr(sz, "width", 0) and getattr(sz, "height", 0):
                        page_sizes_by_idx[p_idx] = (float(sz.width), float(sz.height))

        # 1. Pictures per page (filtered for nested sub-crops and tiny composite fragments)
        figure_bboxes_1000_by_page: dict[int, list[list[int]]] = {}
        figure_raw_rects_by_page: dict[int, list[tuple[float, float, float, float]]] = {}
        if getattr(doc, "pictures", None):
            pics_by_page_raw: dict[int, list[tuple[int, Any, Any]]] = {}
            for idx, pic in enumerate(doc.pictures):
                p_no = 1
                pic_bbox_obj = None
                if getattr(pic, "prov", None) and len(pic.prov) > 0:
                    p_no = pic.prov[0].page_no
                    pic_bbox_obj = pic.prov[0].bbox
                p_idx = max(0, p_no - 1)
                pics_by_page_raw.setdefault(p_idx, []).append((idx, pic, pic_bbox_obj))

            from types import SimpleNamespace

            for p_idx, page_pic_entries in pics_by_page_raw.items():
                pw_p, ph_p = page_sizes_by_idx.get(p_idx, (595.0, 842.0))
                if len(page_pic_entries) > 1 and all(entry[2] is not None for entry in page_pic_entries):
                    surviving_boxes = _filter_page_figure_bboxes(
                        [entry[2] for entry in page_pic_entries],
                        page_width=pw_p if pw_p > 0 else 595.0,
                        page_height=ph_p if ph_p > 0 else 842.0,
                    )
                    filtered_entries: list[tuple[int, Any, Any]] = []
                    for rel_idx, merged_rect in surviving_boxes:
                        orig_idx, orig_pic, orig_bbox = page_pic_entries[rel_idx]
                        orig_rect = _extract_rect_coords(orig_bbox)
                        if orig_rect is not None and merged_rect != orig_rect:
                            coord_origin = getattr(orig_bbox, "coord_origin", None)
                            merged_bbox = SimpleNamespace(
                                l=merged_rect[0],
                                b=merged_rect[1],
                                r=merged_rect[2],
                                t=merged_rect[3],
                                coord_origin=coord_origin,
                            )
                            filtered_entries.append((orig_idx, orig_pic, merged_bbox))
                        else:
                            filtered_entries.append((orig_idx, orig_pic, orig_bbox))
                else:
                    filtered_entries = page_pic_entries

                for idx, pic, pic_bbox_obj in filtered_entries:
                    try:
                        pil_img = pic.get_image(doc)
                        if pil_img is not None and pil_img.width >= 30 and pil_img.height >= 30:
                            if pic_bbox_obj is not None and pdf_doc_shared is not None and p_idx < len(pdf_doc_shared):
                                vec_img = render_pdf_figure_crop(
                                    pdf_doc_shared[p_idx],
                                    pic_bbox_obj,
                                    target_longest_edge=2048,
                                )
                                if vec_img is not None:
                                    pil_img = vec_img
                            img_bytes = pil_img.tobytes()
                            img_hash = hashlib.sha256(img_bytes).hexdigest()[:16]
                            img_filename = f"picture_{p_idx}_{idx}_{img_hash}.png"
                            img_path = os.path.join(images_dir, img_filename)
                            pil_img.save(img_path, format="PNG")
                            result["pictures_by_page"].setdefault(p_idx, []).append(img_filename)
                            raw_rect = _extract_rect_coords(pic_bbox_obj)
                            if raw_rect is not None:
                                figure_raw_rects_by_page.setdefault(p_idx, []).append(raw_rect)
                            pic_bbox_1000 = (
                                normalize_bbox_to_1000(pic_bbox_obj, pw_p, ph_p)
                                if pic_bbox_obj
                                else None
                            )
                            if pic_bbox_1000 is not None:
                                figure_bboxes_1000_by_page.setdefault(p_idx, []).append(pic_bbox_1000)
                                result["layout_blocks"].append({
                                    "type": "image",
                                    "text": f"![](images/{img_filename})",
                                    "page_idx": p_idx,
                                    "bbox_1000": pic_bbox_1000,
                                })
                    except Exception:
                        pass

        # 2. Tables per page (excluding degenerate diagram tables and tables overlapping figures >= 35%)
        if getattr(doc, "tables", None):
            for t_item in doc.tables:
                p_no = 1
                t_bbox_obj = None
                if getattr(t_item, "prov", None) and len(t_item.prov) > 0:
                    p_no = t_item.prov[0].page_no
                    t_bbox_obj = t_item.prov[0].bbox
                p_idx = max(0, p_no - 1)
                try:
                    t_md = t_item.export_to_markdown(doc=doc).strip()
                    if not t_md or "|" not in t_md or _is_degenerate_diagram_table(t_md):
                        continue
                    pw_t, ph_t = page_sizes_by_idx.get(p_idx, (0.0, 0.0))
                    t_bbox_1000 = normalize_bbox_to_1000(t_bbox_obj, pw_t, ph_t) if t_bbox_obj else None
                    overlaps_figure = False
                    if t_bbox_1000 is not None:
                        for fig_bbox in figure_bboxes_1000_by_page.get(p_idx, []):
                            if _bbox_overlap_ratio(t_bbox_1000, fig_bbox) >= 0.35:
                                overlaps_figure = True
                                break
                    if not overlaps_figure and t_bbox_obj is not None:
                        for fig_rect in figure_raw_rects_by_page.get(p_idx, []):
                            if _bbox_overlap_ratio(t_bbox_obj, fig_rect) >= 0.35:
                                overlaps_figure = True
                                break
                    if overlaps_figure:
                        continue
                    result["tables_by_page"].setdefault(p_idx, []).append(t_md)
                    if t_bbox_1000 is not None:
                        result["layout_blocks"].append({
                            "type": "table",
                            "text": t_md,
                            "page_idx": p_idx,
                            "bbox_1000": t_bbox_1000,
                        })
                except Exception:
                    pass

        if pdf_doc_shared is not None:
            try:
                pdf_doc_shared.close()
            except Exception:
                pass

        # 3. Collect single-line body heights, furniture, vector callout boxes, and heading bboxes
        callout_rects_by_page = detect_pdf_callout_rects_by_page(pdf_path)
        body_heights: list[float] = []
        raw_headings: list[dict[str, Any]] = []
        seen_opening_keys: set = set()

        for item, _level in doc.iterate_items(
            included_content_layers={ContentLayer.BODY, ContentLayer.FURNITURE}
        ):
            lbl = str(getattr(item, "label", "")).split(".")[-1].lower()
            layer = getattr(item, "content_layer", ContentLayer.BODY)
            p_no = 1
            bbox_obj = None
            if getattr(item, "prov", None) and len(item.prov) > 0:
                p_no = item.prov[0].page_no
                bbox_obj = item.prov[0].bbox
            p_idx = max(0, p_no - 1)
            txt = (getattr(item, "text", "") or "").strip()
            if not txt:
                continue

            h = round(abs(bbox_obj.t - bbox_obj.b), 2) if bbox_obj else 0.0
            w = round(abs(bbox_obj.r - bbox_obj.l), 2) if bbox_obj else 0.0
            pw_i, ph_i = page_sizes_by_idx.get(p_idx, (0.0, 0.0))
            bbox_1000 = normalize_bbox_to_1000(bbox_obj, pw_i, ph_i) if bbox_obj else None

            if (
                layer == ContentLayer.FURNITURE or lbl in ("page_header", "page_footer", "furniture")
            ) and not _is_marginalia_or_glossary_note(txt):
                f_type = "page_header" if "header" in lbl else "page_footer"
                furn_entry: dict[str, Any] = {
                    "type": f_type,
                    "text": txt,
                    "page_idx": p_idx,
                }
                if bbox_1000 is not None:
                    furn_entry["bbox_1000"] = bbox_1000
                result["furniture_by_page"].setdefault(p_idx, []).append(furn_entry)
                if f_type == "page_header":
                    open_hdr = parse_furniture_opening_header(txt, seen_opening_keys)
                    if open_hdr:
                        result["opening_headers_by_page"].setdefault(p_idx, []).append(open_hdr)
                continue

            effective_lbl = (
                "text" if lbl in ("page_header", "page_footer", "furniture") else lbl
            )
            tb_entry: dict[str, Any] = {
                "type": effective_lbl,
                "text": txt,
                "page_idx": p_idx,
            }
            if bbox_1000 is not None:
                tb_entry["bbox_1000"] = bbox_1000
            result["text_blocks"].append(tb_entry)
            result["text_blocks_by_page"].setdefault(p_idx, []).append(tb_entry)

            if lbl in ("text", "list_item") and 5.0 <= h <= 18.0 and 15 <= len(txt) <= 75 and w >= 80:
                body_heights.append(h)
            elif lbl in ("section_header", "title"):
                in_callout = is_bbox_inside_callout_rect(bbox_obj, txt, callout_rects_by_page.get(p_idx, []))
                raw_headings.append({
                    "text": txt,
                    "page_idx": p_idx,
                    "h": h,
                    "w": w,
                    "bbox_1000": bbox_1000,
                    "in_callout": in_callout,
                })

        body_line_h = statistics.median(body_heights) if body_heights else 0.0
        result["body_line_height"] = round(body_line_h, 2)

        # Estimate single-line font height for each heading
        single_line_candidates = [rh["h"] for rh in raw_headings if 0 < rh["h"] <= 24.0 and len(rh["text"]) <= 45]
        max_single_h = max(single_line_candidates) if single_line_candidates else 16.0

        for rh in raw_headings:
            h = rh["h"]
            w = rh["w"]
            txt = rh["text"]
            single_h = h
            # If a heading in a narrow column wrapped onto 2 lines, normalize to single-line height
            if w > 0 and w < 260 and len(txt) >= 35 and h > max_single_h * 1.35:
                single_h = round(h / 2.48, 2)
            is_body_sized = bool(body_line_h > 0 and single_h <= body_line_h * 1.04)
            hb_entry: dict[str, Any] = {
                "type": "title",
                "text": txt,
                "text_level": 1,
                "page_idx": rh["page_idx"],
                "bbox": [0, 0, w, single_h],
                "is_body_sized": is_body_sized,
                "is_callout_box": rh.get("in_callout", False),
            }
            if rh.get("bbox_1000") is not None:
                hb_entry["bbox_1000"] = rh["bbox_1000"]
            result["heading_blocks"].append(hb_entry)

    except Exception as e:
        logger.warning(f"Docling page layout extraction fallback: {e}")

    _LAST_DOCLING_LAYOUT = result
    return result


def _format_pipe_table_from_rows(rows: list[list[str]]) -> str:
    """Formats a 2D list of cell strings as a standard Markdown pipe table.

    Args:
        rows: Non-empty list of table rows (header row first, followed by data rows).

    Returns:
        Formatted Markdown pipe table string.
    """
    if not rows:
        return ""
    max_cols = max((len(r) for r in rows), default=0)
    if max_cols == 0:
        return ""
    out: list[str] = []
    for r_idx, row in enumerate(rows):
        padded = row + [""] * (max_cols - len(row))
        out.append("| " + " | ".join(padded) + " |")
        if r_idx == 0:
            out.append("| " + " | ".join(["---"] * max_cols) + " |")
    return "\n".join(out)


def _merge_or_select_better_pipe_table(vlm_table_md: str, docling_table_md: str) -> str:
    """Selects or merges a VLM pipe table and a Docling TableFormer pipe table without cell truncation.

    Compares the count of non-empty data cells and checks whether the Docling table
    has empty trailing cells in its last row where the VLM table has values. Backfills
    any empty cells in the selected table from the counterpart when dimensions match.

    Args:
        vlm_table_md: Markdown pipe table extracted by the VLM.
        docling_table_md: Markdown pipe table extracted by Docling TableFormer.

    Returns:
        The more complete pipe table with any missing cells backfilled.
    """
    vlm_rows = _parse_pipe_table_rows(vlm_table_md)
    doc_rows = _parse_pipe_table_rows(docling_table_md)
    if not doc_rows:
        return vlm_table_md
    if not vlm_rows:
        return docling_table_md

    vlm_non_empty = sum(
        1 for r in vlm_rows[1:] for c in r if c not in _TABLE_PLACEHOLDER_CELLS
    )
    doc_non_empty = sum(
        1 for r in doc_rows[1:] for c in r if c not in _TABLE_PLACEHOLDER_CELLS
    )

    doc_has_truncated_tail = False
    if len(vlm_rows) >= 2 and len(doc_rows) >= 2:
        vlm_last = vlm_rows[-1]
        doc_last = doc_rows[-1]
        for idx_c in range(min(len(vlm_last), len(doc_last))):
            if (
                doc_last[idx_c] in _TABLE_PLACEHOLDER_CELLS
                and vlm_last[idx_c] not in _TABLE_PLACEHOLDER_CELLS
            ):
                doc_has_truncated_tail = True
                break
        if len(vlm_last) > len(doc_last) and any(
            c not in _TABLE_PLACEHOLDER_CELLS for c in vlm_last[len(doc_last) :]
        ):
            doc_has_truncated_tail = True

    prefer_vlm = vlm_non_empty > doc_non_empty or doc_has_truncated_tail
    primary = [list(r) for r in (vlm_rows if prefer_vlm else doc_rows)]
    secondary = doc_rows if prefer_vlm else vlm_rows

    if len(primary) == len(secondary):
        for r_i in range(len(primary)):
            max_c = max(len(primary[r_i]), len(secondary[r_i]))
            while len(primary[r_i]) < max_c:
                primary[r_i].append("")
            for c_i in range(len(secondary[r_i])):
                if (
                    primary[r_i][c_i] in _TABLE_PLACEHOLDER_CELLS
                    and secondary[r_i][c_i] not in _TABLE_PLACEHOLDER_CELLS
                ):
                    primary[r_i][c_i] = secondary[r_i][c_i]

    return _format_pipe_table_from_rows(primary)


def _enrich_flattened_tables_with_docling(cleaned_text: str, page_tables: list[str]) -> str:
    """Replaces VLM-flattened borderless tables in ``cleaned_text`` with structured
    Markdown pipe tables from Docling's TableFormer, merges/preserves non-truncated VLM
    pipe tables, or appends missed non-degenerate tables.
    """
    valid_page_tables = [
        t_md for t_md in (page_tables or []) if t_md and not _is_degenerate_diagram_table(t_md)
    ]
    if not valid_page_tables:
        return cleaned_text

    if "|" not in cleaned_text:
        return cleaned_text.strip() + "\n\n" + "\n\n".join(valid_page_tables)

    pipe_block_re = re.compile(r"(?:^[ \t]*\|[^\n]+\|[ \t]*(?:\n|$)){2,}", re.MULTILINE)
    existing_matches = list(pipe_block_re.finditer(cleaned_text))
    matched_docling_indices: set[int] = set()

    if existing_matches:
        replacements: list[tuple[int, int, str]] = []
        for m in existing_matches:
            vlm_tbl = m.group(0).strip()
            vlm_tokens = {
                re.sub(r"\W+", "", c.lower())
                for r in _parse_pipe_table_rows(vlm_tbl)
                for c in r
                if len(re.sub(r"\W+", "", c)) >= 2
            }
            best_t_idx: int | None = None
            best_overlap = 0
            for t_idx, doc_tbl in enumerate(valid_page_tables):
                if t_idx in matched_docling_indices:
                    continue
                doc_tokens = {
                    re.sub(r"\W+", "", c.lower())
                    for r in _parse_pipe_table_rows(doc_tbl)
                    for c in r
                    if len(re.sub(r"\W+", "", c)) >= 2
                }
                overlap = len(vlm_tokens & doc_tokens)
                min_needed = max(1, min(len(vlm_tokens), len(doc_tokens)) // 3)
                if overlap >= min_needed and overlap > best_overlap:
                    best_overlap = overlap
                    best_t_idx = t_idx
            if best_t_idx is not None:
                matched_docling_indices.add(best_t_idx)
                merged_tbl = _merge_or_select_better_pipe_table(
                    vlm_tbl, valid_page_tables[best_t_idx]
                )
                trailing_nl = "\n" if m.group(0).endswith("\n") else ""
                replacements.append((m.start(), m.end(), merged_tbl + trailing_nl))

        for start_i, end_i, repl_str in reversed(replacements):
            cleaned_text = cleaned_text[:start_i] + repl_str + cleaned_text[end_i:]

    existing_pipe_lines = "\n".join(
        ln for ln in cleaned_text.splitlines() if ln.strip().startswith("|")
    ).lower()
    for t_idx, t_md in enumerate(valid_page_tables):
        if t_idx in matched_docling_indices:
            continue
        cells = [
            c.strip()
            for r in t_md.splitlines()
            if not re.match(r"^[\s\|:\-]+$", r)
            for c in r.strip("|").split("|")
            if len(c.strip()) >= 4
        ]
        if len(cells) < 2:
            continue
        matched_in_pipes = sum(1 for c in cells if c.lower() in existing_pipe_lines)
        if matched_in_pipes < max(1, len(cells) // 3):
            cleaned_text = cleaned_text.strip() + "\n\n" + t_md
    return cleaned_text


def clean_vlm_repetition_loops(vlm_md: str) -> tuple[str, bool]:
    r"""Detect and strip degenerate VLM-OCR token repetition loops and empty headings.

    Detects runs of 8 or more consecutive short headings (e.g. ``#### A``,
    ``#### B``, ... or single-token headings ``#{1,6}\s+\S{1,3}$``), identical or
    cycling short lines repeated 8 or more times in a row, and standalone empty
    headings (``#{1,6}\s*$``).

    Args:
        vlm_md: Raw or partially cleaned VLM page Markdown string.

    Returns:
        Tuple ``(cleaned_markdown, had_loop)`` where ``had_loop`` is True if a
        degenerate repetition run of 8 or more lines was detected and truncated.
    """
    if not vlm_md:
        return vlm_md, False

    lines = vlm_md.splitlines()
    non_empty: list[tuple[int, str]] = [
        (idx, lines[idx].strip()) for idx in range(len(lines)) if lines[idx].strip()
    ]
    if not non_empty:
        return "", False

    short_heading_re = re.compile(r"^#{1,6}(?:\s+\S{1,3})?\s*$")
    empty_heading_re = re.compile(r"^#{1,6}\s*$")
    short_token_line_re = re.compile(r"^(?:#{1,6}\s*)?[A-Za-z0-9äöüÄÖÜß]{1,3}[\.\)\:]?$")
    structural_prefix = ("((", "|", "![", "<", "```")

    drop_line_indices: set[int] = set()
    had_loop = False

    n_ne = len(non_empty)
    k = 0
    while k < n_ne:
        line_idx, s = non_empty[k]
        if short_heading_re.match(s):
            m = k + 1
            while m < n_ne and short_heading_re.match(non_empty[m][1]):
                m += 1
            if m - k >= 8:
                had_loop = True
                start_l = non_empty[k][0]
                end_l = non_empty[m - 1][0]
                for d_i in range(start_l, end_l + 1):
                    drop_line_indices.add(d_i)
                k = m
                continue

        if not s.startswith(structural_prefix) and short_token_line_re.match(s):
            m = k + 1
            while (
                m < n_ne
                and not non_empty[m][1].startswith(structural_prefix)
                and (short_token_line_re.match(non_empty[m][1]) or empty_heading_re.match(non_empty[m][1]))
            ):
                m += 1
            if m - k >= 8:
                had_loop = True
                start_l = non_empty[k][0]
                end_l = non_empty[m - 1][0]
                for d_i in range(start_l, end_l + 1):
                    drop_line_indices.add(d_i)
                k = m
                continue

        if not s.startswith(structural_prefix):
            matched_cycle = False
            for period in (1, 2, 3, 4):
                if k + 8 > n_ne:
                    break
                m = k + period
                while (
                    m < n_ne
                    and not non_empty[m][1].startswith(structural_prefix)
                    and non_empty[m][1] == non_empty[k + ((m - k) % period)][1]
                ):
                    m += 1
                if m - k >= 8:
                    had_loop = True
                    start_l = non_empty[k][0]
                    end_l = non_empty[m - 1][0]
                    for d_i in range(start_l, end_l + 1):
                        drop_line_indices.add(d_i)
                    k = m
                    matched_cycle = True
                    break
            if matched_cycle:
                continue

        k += 1

    surviving_lines: list[str] = []
    for idx, raw_line in enumerate(lines):
        if idx in drop_line_indices:
            continue
        if empty_heading_re.match(raw_line.strip()):
            continue
        surviving_lines.append(raw_line)

    cleaned = "\n".join(surviving_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, had_loop


def fuse_vlm_page_with_docling(
    raw_text: str,
    page_images: list[str],
    phys_num: int | str,
    page_tables: list[str] | None = None,
    opening_headers: list[str] | None = None,
    docling_layout: Any = None,
    page_idx: int | None = None,
) -> str:
    r"""Fuse a raw VLM OCR page with Docling layout crops, tables, and running header/footer stripping.

    1. Strips degenerate VLM repetition loops, code fences, and HTML layout wrappers; unescapes \$...\$; converts HTML <table> to pipe tables.
    2. Strips running footers / lone page numbers and all-caps running top headers (while rescuing opening chapter banners).
    3. Recovers missing non-furniture Docling text blocks when a VLM repetition loop truncated the page.
    4. Deduplicates repeated figure captions and unwraps heading/italic formatting on captions.
    5. Matches Docling-cropped layout figures (page_images) to inline placeholders and figure captions.
    6. Fuses borderless tables from Docling TableFormer (page_tables) when missed by the VLM.
    7. Repairs broken intra-line hyphenations and injects the physical page marker ((phys_num)).

    Args:
        raw_text: Raw VLM OCR Markdown text for a single page.
        page_images: Extracted Docling picture filenames on this page.
        phys_num: Physical printed page number or Roman label.
        page_tables: Optional Docling TableFormer pipe tables on this page.
        opening_headers: Optional chapter/section opening headers from FURNITURE.
        docling_layout: Optional Docling layout dict or object containing ``text_blocks`` for fallback recovery.
        page_idx: Optional 0-based page index when ``docling_layout`` is multi-page.

    Returns:
        Fused and post-processed page Markdown string.
    """
    from backend.services.fibs_postprocess import normalize_heading_page_markers

    loop_cleaned_text, had_loop = clean_vlm_repetition_loops(raw_text)
    cleaned_text = clean_markdown_fences(fix_escaped_dollars(loop_cleaned_text))
    cleaned_text = convert_html_tables_to_markdown(cleaned_text)
    cleaned_text = normalize_heading_page_markers(cleaned_text)

    # Strip degenerate diagram pipe tables already present in VLM output
    cleaned_text = re.sub(
        r"(?:^[ \t]*\|[^\n]+\|[ \t]*(?:\n|$))+",
        lambda m: "" if _is_degenerate_diagram_table(m.group(0)) else m.group(0),
        cleaned_text,
        flags=re.MULTILINE,
    )
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text).strip()

    # 1. Strip running footers / page numbers at start or end of page (preserving marginalia/glossary notes)
    phys_str = str(phys_num).strip()
    generic_footer_patterns = [
        r"^\s*\d{1,4}\s*\n+",
        r"\n+\s*\[?\s*(?:Seite|Page)\s+(?:\d+|[IVXLCDMivxlcdm]+)\s*\]?\s*$",
        r"\n+\s*\d{1,4}\s*$",
        r"\n+\s*(?:\d+\s+[-–—\s/|]\s+[A-ZÄÖÜa-zäöü0-9\s]{2,50}|[A-ZÄÖÜa-zäöü0-9\s]{2,50}\s+[-–—\s/|]\s+\d+)\s*$",
        r"\n+\s*\d+\s+[A-ZÄÖÜa-zäöü0-9\s]{2,50}\s*$",
        r"\n+\s*[A-ZÄÖÜa-zäöü0-9\s]{2,50}\s+\d+\s*$",
    ]
    if phys_str and not phys_str.isdigit():
        esc_phys = re.escape(phys_str)
        generic_footer_patterns.extend(
            [
                rf"^\s*{esc_phys}\s*\n+",
                rf"\n+\s*{esc_phys}\s*$",
            ]
        )
    for fp in generic_footer_patterns:
        m_fp = re.search(fp, cleaned_text, flags=re.IGNORECASE)
        if m_fp and not _is_marginalia_or_glossary_note(m_fp.group(0).strip()):
            cleaned_text = cleaned_text[: m_fp.start()] + cleaned_text[m_fp.end() :]

    # 2. Strip running top headers (preserving chapter/section opening headers on their first page)
    first_line = cleaned_text.strip().splitlines()[0].strip() if cleaned_text.strip() else ""
    is_opening_hdr = False
    if opening_headers and first_line:
        norm_first = re.sub(r"[^a-z0-9äöüß]", "", re.sub(r"\b(?:ii|II)\b", "11", first_line).lower())
        for oh in opening_headers:
            norm_oh = re.sub(r"[^a-z0-9äöüß]", "", oh.lower())
            if norm_first == norm_oh:
                is_opening_hdr = True
                cleaned_text = re.sub(r"^[^\n]+", oh, cleaned_text.strip(), count=1)
                break

    if not is_opening_hdr:
        cleaned_text = re.sub(
            r"(?:^(?:#{1,6}\s+)?[A-ZÄÖÜ0-9\s\-_–—:\.]{3,60}\s*\n+)+(?=[A-ZÄÖÜa-zäöü#!\*])",
            "",
            cleaned_text.strip(),
            flags=0,
        )
        if opening_headers:
            for oh in reversed(opening_headers):
                if oh.lstrip("#").strip().lower() not in cleaned_text.lower():
                    cleaned_text = f"{oh}\n\n{cleaned_text.strip()}"

    # 2b. Recover missing non-furniture Docling text blocks (when a VLM repetition loop truncated the page)
    #     and always preserve marginalia/glossary notes even if Docling labeled them as furniture.
    effective_layout = docling_layout if docling_layout is not None else _LAST_DOCLING_LAYOUT
    inferred_p_idx = page_idx
    if inferred_p_idx is None and page_images:
        for fn in page_images:
            m_p = re.match(r"^picture_(\d+)_", os.path.basename(fn))
            if m_p:
                inferred_p_idx = int(m_p.group(1))
                break

    if effective_layout:
        candidate_blocks: list[Any] = []
        furniture_norms: set[str] = set()
        if isinstance(effective_layout, dict):
            furn_by_page = effective_layout.get("furniture_by_page") or {}
            for f_p_idx, f_list in furn_by_page.items():
                for f_item in f_list or []:
                    f_txt = (f_item.get("text") if isinstance(f_item, dict) else str(f_item)) or ""
                    if not f_txt.strip():
                        continue
                    if _is_marginalia_or_glossary_note(f_txt):
                        if inferred_p_idx is None or f_p_idx == inferred_p_idx:
                            candidate_blocks.append(
                                {"type": "text", "text": f_txt.strip(), "page_idx": f_p_idx}
                            )
                    else:
                        furniture_norms.add(re.sub(r"\W+", " ", f_txt).strip().lower())

            tb_by_page = effective_layout.get("text_blocks_by_page") or {}
            if inferred_p_idx is not None and inferred_p_idx in tb_by_page:
                candidate_blocks.extend(tb_by_page[inferred_p_idx])
            elif tb_by_page and len(tb_by_page) == 1:
                candidate_blocks.extend(next(iter(tb_by_page.values())))
            elif tb_by_page and cleaned_text.strip():
                surv_words = set(re.findall(r"[a-zA-ZäöüÄÖÜß0-9]{4,}", cleaned_text.lower()))
                best_p = None
                best_overlap = 0
                for cand_p, p_blocks in tb_by_page.items():
                    p_txt = " ".join(
                        (b.get("text", "") if isinstance(b, dict) else str(b)) for b in p_blocks
                    ).lower()
                    p_words = set(re.findall(r"[a-zA-ZäöüÄÖÜß0-9]{4,}", p_txt))
                    ov = len(surv_words & p_words)
                    if ov > best_overlap:
                        best_overlap = ov
                        best_p = cand_p
                if best_p is not None:
                    candidate_blocks.extend(tb_by_page[best_p])
            if not candidate_blocks:
                candidate_blocks.extend(
                    effective_layout.get("text_blocks")
                    or effective_layout.get("blocks")
                    or effective_layout.get("layout_blocks")
                    or []
                )
        elif isinstance(effective_layout, (list, tuple)):
            candidate_blocks = list(effective_layout)
        else:
            candidate_blocks = list(
                getattr(effective_layout, "text_blocks", None)
                or getattr(effective_layout, "blocks", None)
                or []
            )

        norm_existing = re.sub(r"\W+", " ", cleaned_text).lower()
        existing_words = set(re.findall(r"[a-zA-ZäöüÄÖÜß0-9]{3,}", norm_existing))
        recovered_paras: list[str] = []

        for item in candidate_blocks:
            if isinstance(item, str):
                b_txt = item.strip()
                b_type = "text"
                b_layer = "body"
                b_p_idx = None
            elif isinstance(item, dict):
                b_txt = str(item.get("text") or "").strip()
                b_type = str(item.get("type") or item.get("label") or "text").split(".")[-1].lower()
                b_layer = str(item.get("content_layer") or item.get("layer") or "body").split(".")[-1].lower()
                b_p_idx = item.get("page_idx")
            else:
                b_txt = str(getattr(item, "text", "") or "").strip()
                b_type = str(getattr(item, "type", None) or getattr(item, "label", None) or "text").split(".")[-1].lower()
                b_layer = str(getattr(item, "content_layer", None) or getattr(item, "layer", None) or "body").split(".")[-1].lower()
                b_p_idx = getattr(item, "page_idx", None)

            if not b_txt or len(b_txt) < 4 or re.fullmatch(r"\d{1,4}", b_txt):
                continue
            if inferred_p_idx is not None and b_p_idx is not None and b_p_idx != inferred_p_idx:
                continue
            is_glossary = _is_marginalia_or_glossary_note(b_txt)
            if not had_loop and not is_glossary:
                continue
            if b_type in ("image", "picture", "table"):
                continue
            if (
                "furniture" in b_layer
                or b_type in ("header", "footer", "page_header", "page_footer", "furniture")
            ) and not is_glossary:
                continue
            norm_b = re.sub(r"\W+", " ", b_txt).strip().lower()
            if not norm_b or (not is_glossary and norm_b in furniture_norms):
                continue
            if norm_b in norm_existing or (len(norm_b) >= 30 and norm_b[:30] in norm_existing):
                continue
            b_words = re.findall(r"[a-zA-ZäöüÄÖÜß0-9]{3,}", norm_b)
            if not b_words:
                continue
            if (
                not is_glossary
                and len(b_words) >= 3
                and (sum(1 for w in b_words if w in existing_words) / len(b_words)) >= 0.75
            ):
                continue

            if b_type in ("title", "section_header", "heading") and not b_txt.startswith("#") and not is_glossary:
                formatted_b = f"## {b_txt}"
            elif b_type == "list_item" and not b_txt.startswith(("-", "*", "1.")) and not is_glossary:
                formatted_b = f"- {b_txt}"
            else:
                formatted_b = b_txt

            recovered_paras.append(formatted_b)
            norm_existing = f"{norm_existing} {norm_b}"
            existing_words.update(b_words)

        if recovered_paras:
            cleaned_text = (
                f"{cleaned_text.rstrip()}\n\n" + "\n\n".join(recovered_paras)
                if cleaned_text.strip()
                else "\n\n".join(recovered_paras)
            )

    # 3. Unwrap italic/bold around standalone figure captions (*Abbildung 4.1: ...* -> Abbildung 4.1: ...)
    cleaned_text = re.sub(
        r"(?m)^[ \t]*[\*_]{1,2}((?:Abbildung|Abb\.|Bild|Grafik|Figure|Fig\.)\s+[0-9IVXii]+[^\n\*_]+?)[\*_]{1,2}[ \t]*$",
        r"\1",
        cleaned_text,
        flags=re.IGNORECASE,
    )

    remaining_images = list(page_images or [])

    # 3a. Pre-deduplicate repeated figure captions and redundant in-figure label echoes right after captions
    caption_id_regex = re.compile(
        r"^(?:#{1,6}\s+)?(?:!\[[^\]]*\]\([^)]*\)\s*)?(?:<Bild>\s*|\*+|_*)?(?:Abbildung|Abb\.|Bild|Grafik|Figure|Fig\.)\s+([0-9IVXii]+(?:[\.\-]\d+)*[a-z]?)\b",
        re.IGNORECASE,
    )
    pre_lines = cleaned_text.splitlines()
    deduped_pre_lines: list[str] = []
    seen_fig_ids_pre = set()
    last_was_caption_with_paren = False
    for raw_l in pre_lines:
        s_l = raw_l.strip()
        if not s_l:
            deduped_pre_lines.append(raw_l)
            continue
        if last_was_caption_with_paren and re.match(r"^[A-ZÄÖÜa-zäöü\s]{3,30}\([A-ZÄÖÜa-zäöü]+\)$", s_l):
            last_was_caption_with_paren = False
            continue
        last_was_caption_with_paren = False

        m_img_cap = re.match(
            r"^!\[(?:Abbildung|Abb\.|Bild|Grafik|Figure|Fig\.)\s+([0-9IVXii]+(?:[\.\-]\d+)*[a-z]?)\b[^\]]*\]\([^)]*\)$",
            s_l,
            re.IGNORECASE,
        )
        if m_img_cap:
            fid = m_img_cap.group(1).lower().replace("ii", "11")
            if fid in seen_fig_ids_pre:
                continue
        m_cap = caption_id_regex.match(s_l)
        if m_cap and not s_l.startswith("!["):
            fid = m_cap.group(1).lower().replace("ii", "11")
            if fid in seen_fig_ids_pre:
                continue
            seen_fig_ids_pre.add(fid)
            if "(" in s_l and ")" in s_l:
                last_was_caption_with_paren = True
        deduped_pre_lines.append(raw_l)
    cleaned_text = "\n".join(deduped_pre_lines)

    # 3b. Replace inline image placeholders (<!-- image -->, ![image](image_1.png), ! [Label](#))
    img_pattern = r"<!--\s*image[^>]*-->|![ \t]*\[([^\]]*)\]\((?:https?://[^)\n]+|images/[^)\n]*|image_\d+\.[^)\n]*|[^)\n]*)\)"
    generic_label_re = re.compile(
        r"^(?:image|img|bild|figure|fig|picture|abbildung|grafik|foto)?[\s_\-]*\d*$",
        re.IGNORECASE,
    )

    def replace_ph(m: re.Match) -> str:
        if remaining_images:
            fn = remaining_images.pop(0)
            return f"![](images/{fn})"
        label = (m.group(1) or "").strip() if m.lastindex else ""
        if label and not generic_label_re.match(label) and not re.search(r"\.(?:png|jpe?g|gif|svg)$", label, re.I):
            return f"<Anmerkung> Abbildung nicht extrahiert: {label} </Anmerkung>"
        return ""

    if re.search(img_pattern, cleaned_text, flags=re.IGNORECASE):
        cleaned_text = re.sub(img_pattern, replace_ph, cleaned_text, flags=re.IGNORECASE)

    # 4. Scan lines to match captions and insert any remaining images above them
    lines = cleaned_text.splitlines()
    new_lines: list[str] = []
    caption_regex = re.compile(
        r"^(?:#{1,6}\s+)?(?:<Bild>\s*|\*+|_*)?(?:Abbildung|Abb\.|Bild|Grafik|Figure|Fig\.)\s+[0-9IVXii]+.*",
        re.IGNORECASE,
    )

    for line in lines:
        stripped = line.strip()
        if caption_regex.match(stripped):
            normalized_line = re.sub(r"^#{1,6}\s+", "", stripped)
            normalized_line = re.sub(r"^[\*_]+(.+?)[\*_]+$", r"\1", normalized_line)
            prev_is_img = False
            for prev in reversed(new_lines):
                if prev.strip():
                    if prev.strip().startswith("!["):
                        prev_is_img = True
                    break

            if not prev_is_img and remaining_images:
                fn = remaining_images.pop(0)
                new_lines.append(f"![](images/{fn})")
                new_lines.append("")

            new_lines.append(normalized_line)
        else:
            new_lines.append(line)

    cleaned_text = "\n".join(new_lines)

    # 4b. Enrich with Docling TableFormer tables when missed or flattened by VLM
    if page_tables:
        filtered_tables: list[str] = []
        fig_boxes_on_page: list[Any] = []
        table_boxes_by_md: dict[str, Any] = {}
        if isinstance(effective_layout, dict):
            for lb in effective_layout.get("layout_blocks") or []:
                if not isinstance(lb, dict):
                    continue
                if inferred_p_idx is not None and lb.get("page_idx") is not None and lb.get("page_idx") != inferred_p_idx:
                    continue
                lb_box = lb.get("bbox_1000") or lb.get("bbox")
                if not lb_box:
                    continue
                if lb.get("type") in ("image", "picture", "figure"):
                    fig_boxes_on_page.append(lb_box)
                elif lb.get("type") == "table" and lb.get("text"):
                    table_boxes_by_md[str(lb["text"]).strip()] = lb_box
            for fb in effective_layout.get("figure_bboxes") or []:
                fig_boxes_on_page.append(fb)
        elif effective_layout is not None:
            for fb in getattr(effective_layout, "figure_bboxes", None) or []:
                fig_boxes_on_page.append(fb)

        for t_entry in page_tables:
            if isinstance(t_entry, dict):
                t_md = str(t_entry.get("markdown") or t_entry.get("text") or "").strip()
                t_box = t_entry.get("bbox") or t_entry.get("bbox_1000")
            elif hasattr(t_entry, "markdown"):
                t_md = str(getattr(t_entry, "markdown", "") or "").strip()
                t_box = getattr(t_entry, "bbox", None)
            else:
                t_md = str(t_entry or "").strip()
                t_box = table_boxes_by_md.get(t_md)
            if not t_md or _is_degenerate_diagram_table(t_md):
                continue
            if t_box is not None and fig_boxes_on_page:
                if any(_bbox_overlap_ratio(t_box, fb) >= 0.35 for fb in fig_boxes_on_page):
                    continue
            filtered_tables.append(t_md)

        if filtered_tables:
            cleaned_text = _enrich_flattened_tables_with_docling(cleaned_text, filtered_tables)

    # 5. Place any remaining unmatched images after top page marker or at top
    if remaining_images:
        appended_imgs = "\n\n".join([f"![](images/{fn})" for fn in remaining_images])
        page_marker_match = re.search(r"^(\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)\s*\n+)", cleaned_text)
        if page_marker_match:
            idx = page_marker_match.end()
            cleaned_text = cleaned_text[:idx] + appended_imgs + "\n\n" + cleaned_text[idx:]
        else:
            cleaned_text = appended_imgs + "\n\n" + cleaned_text

    # 6. Clean stray space after hyphens in broken words (e.g. Zellkompartimen- ten -> Zellkompartimenten)
    cleaned_text = fc.INLINE_HYPHEN_SPACE_RE.sub(r"\1\2", cleaned_text)

    # 7. Prepend physical page boundary marker if not already present
    if f"(({phys_num}))" not in cleaned_text:
        cleaned_text = f"(({phys_num}))\n\n{cleaned_text}"

    return cleaned_text.strip()


def sanitize_runaway_repetitions(text: str) -> str:
    """Sanitizes autoregressive model runaway loops:
    1. Runaway image paths containing repetitive tokens (e.g. ![](images/00000000000...) or paths > 300 chars or unclosed trailing tags).
       Note: Normal image paths like ![](images/picture_0_0_119d3f49181bc92a.png) are strictly preserved.
    2. Single character repetitions (15+ identical non-table/non-blank characters).
       Preserves Markdown table separators (|---|---|), indentation spaces, and worksheet fill-in blanks (____).
    3. Repeated patterned headings/lines loops (e.g. '## B4 Nachweis...', '## B5 Nachweis...' repeating 3+ times).
    """
    if not text:
        return text

    text, _ = clean_vlm_repetition_loops(text)

    # 1. Runaway image paths (contain 10+ identical consecutive chars, excessively long > 300 chars, or unclosed trailing tags)
    text = re.sub(r"!\[.*?\]\([^\)\n]*?([a-zA-Z0-9_\-=*~`./\\ ])\1{10,}[^\)\n]*(?:\)|$)", "", text)
    text = re.sub(r"!\[.*?\]\([^\)\n]{300,}(?:\)|$)", "", text)
    text = re.sub(r"!\[.*?\]\([^\)\n]*?([a-zA-Z0-9_\-=*~`./\\ ])\1{10,}[^\)\n]*$", "", text)
    text = re.sub(r"!\[.*?\]\([^\)\n]*$", "", text)

    # 2. Single character repetitions (15+ identical chars, excluding '-', '_', and ' ' which occur in tables and fill-in blanks)
    text = re.sub(r"([a-zA-Z0-9=*~`./\\])\1{15,}", "", text)

    # 3. Repeated patterned headings/lines loop (3+ consecutive lines with identical body)
    lines = text.splitlines()
    cleaned_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # Never collapse structural tags like <Bild>, page markers ((num)), tables, or list items
        if stripped.startswith("<Bild") or stripped.startswith("((") or stripped.startswith("|") or stripped.startswith("-"):
            cleaned_lines.append(line)
            i += 1
            continue

        norm = re.sub(r"^(?:#{1,6}\s+)?(?:[A-Za-z]?\d+[\s\.\:\-]+|[A-Za-z]\d+\s+)", "", stripped)
        if len(norm) > 15:
            run_count = 1
            j = i + 1
            while j < len(lines):
                next_stripped = lines[j].strip()
                if not next_stripped:
                    j += 1
                    continue
                if next_stripped.startswith("<Bild") or next_stripped.startswith("((") or next_stripped.startswith("|") or next_stripped.startswith("-"):
                    break
                next_norm = re.sub(r"^(?:#{1,6}\s+)?(?:[A-Za-z]?\d+[\s\.\:\-]+|[A-Za-z]\d+\s+)", "", next_stripped)
                if next_norm == norm or (len(norm) > 25 and (next_norm.startswith(norm[:25]) or norm.startswith(next_norm[:25]))):
                    run_count += 1
                    j += 1
                else:
                    break
            if run_count >= 3:
                cleaned_lines.append(line)
                i = j
                continue
        cleaned_lines.append(line)
        i += 1

    return "\n".join(cleaned_lines)


def _is_preserved_lowercase_compound(part1: str, part2: str, full_text: str = "", match_start: int = 0, match_end: int = 0) -> bool:
    """Returns True if `part1-part2` is a legitimate hyphenated compound (German, English, French, URL, CSS, acronym) rather than a line-break artifact."""
    p1_low = part1.lower()
    p2_low = part2.lower()
    pair_low = f"{p1_low}-{p2_low}"

    # 1. Check surrounding context for multi-hyphen chains (e.g. Ende-zu-Ende, state-of-the-art) or URLs/paths/CSS
    if full_text and (match_start > 0 or match_end > 0):
        before = full_text[max(0, match_start - 3) : match_start]
        after = full_text[match_end : min(len(full_text), match_end + 15)]
        if before.endswith("-") or before.endswith("/") or before.endswith(".") or before.endswith("@") or before.endswith("_"):
            return True
        if after.startswith("-") or after.startswith("/") or after.startswith(".de") or after.startswith(".com") or after.startswith(".org") or after.startswith(".net") or after.startswith(".at") or after.startswith(".ch"):
            return True
        line_start = full_text.rfind("\n", 0, match_start) + 1
        line_end = full_text.find("\n", match_end)
        if line_end == -1:
            line_end = len(full_text)
        line_str = full_text[line_start:line_end]
        if "http://" in line_str or "https://" in line_str or "www." in line_str:
            return True

    # 2. Acronym / all-caps prefix (e.g. KI-generiert, IT-specialist, DNA-freie, US-amerikanisch, EU-kritisch, ARD-aktuell)
    if (len(part1) <= 4 and part1.isupper()) or p1_low in {
        "ki", "it", "dna", "rna", "us", "eu", "un", "co", "uv", "tv", "pc", "qr", "cd", "dvd", "ard", "zdf", "dpa", "akg", "lpb", "kn", "vw", "nr", "st", "ex", "non", "pre", "post", "co", "re", "pro", "anti", "sub", "super", "mini", "multi", "inter", "trans", "ultra", "neo", "pseudo", "semi", "self", "well", "low", "high", "top", "bottom", "full", "part", "long", "short", "real", "next", "check", "warm", "close", "pop", "stand", "test", "pat", "cut", "fact", "user", "world", "two", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
    }:
        return True

    # 3. Single-letter variable or math prefix (x-Achse, y-Achse, p-q-Formel)
    if len(part1) == 1 or len(part2) == 1:
        return True

    # 4. Exact whitelist of German, English, French, and technical lowercase compounds
    exact_whitelist = {
        "rot-weiß", "schwarz-weiß", "blau-weiß", "gelb-schwarz", "grün-weiß", "rot-grün", "schwarz-gelb", "schwarz-rot",
        "links-rechts", "oben-unten", "ost-west", "nord-süd", "mehr-weniger", "je-desto", "mathe-fit", "fix-weg",
        "dum-dum", "bestell-nr", "ende-zu", "punkt-zu", "punkt-vor", "schritt-für", "eins-zu", "power-to", "face-to",
        "fragen-und", "manfred-von", "leopold-von", "check-in", "check-up", "warm-up", "close-up", "pop-up", "pop-ups",
        "stand-by", "to-do", "test-run", "e-mail", "on-line", "up-to-date", "well-known", "self-confident",
        "simple-minded", "long-time", "full-time", "part-time", "real-time", "long-term", "short-term", "high-tech",
        "low-cost", "low-res", "next-gen", "mini-drones", "super-smart", "pat-down", "top-down", "bottom-up",
        "ground-breaking", "cutting-edge", "fact-checking", "user-generated", "validation-seeking", "world-wide",
        "two-thirds", "co-worker", "re-read", "pre-war", "post-war", "non-fiction", "extinction-level",
        "peut-être", "rendez-vous", "week-end", "grand-mère", "grand-père", "demi-heure", "aujourd'hui",
        "celui-ci", "celle-ci", "ceux-ci", "là-bas", "vis-à-vis", "tête-à-tête", "est-ce", "vas-tu", "as-tu",
        "background-color", "border-style", "border-color", "border-collapse", "border-width", "font-family",
        "font-size", "text-align", "line-height", "mildenberger-verlag", "das-uebungsheft", "blinde-kuh",
        "regenwald-schuetzen", "supra-lernplattform", "steckbrief-katta", "meine-startseite",
    }
    if pair_low in exact_whitelist:
        return True

    # 5. Co-equal adjective compounds (e.g. deutsch-französische, römisch-katholischen, wissenschaftlich-kritische, nicht-konstante)
    adj_prefixes = (
        "deutsch-", "englisch-", "französisch-", "polnisch-", "russisch-", "österreichisch-", "britisch-",
        "römisch-katholisch", "evangelisch-lutherisch", "sozial-ökologisch", "wissenschaftlich-technisch",
        "wissenschaftlich-kritisch", "geistig-seelisch", "körperlich-geistig", "politisch-gesellschaftlich",
        "wirtschaftlich-sozial", "historisch-politisch", "mathematisch-naturwissenschaftlich",
        "imperial-militärisch", "bürgerlich-konservativ", "marxistisch-sozialistisch",
        "demokratisch-parlamentarisch", "parlamentarisch-demokratisch", "kleinbürgerlich-engstirnig",
        "gebrochen-rational", "nicht-konstant", "nicht-codierend", "nicht-religiös", "nicht-wirklich",
        "wild-gefangen", "verantwortlich-sein",
    )
    if any(pair_low.startswith(pref) for pref in adj_prefixes):
        # Ensure part2 isn't truncated right in the middle of a stem like 'römisch-katho'
        if pair_low == "römisch-katho":
            return False
        return True

    return False


_PDF_DEHYPHEN_CACHE: dict[tuple[str, float], tuple[set[tuple[str, str]], set[str]]] = {}


def dehyphenate_inline_broken_words(text: str, pdf_path: str | None = None) -> str:
    r"""Joins broken mid-word German line-break hyphens (`part1-part2` where `part2` starts with lowercase).

    If `pdf_path` is provided, inspects the PDF text layer to find words split by `\u00ad`, `\ufffe`,
    or line-end `-\r?\n` and unconditionally joins those exact pairs, then joins remaining syllabic
    line-break artifacts while preserving legitimate lowercase hyphenated compounds.
    """
    if not text:
        return text

    pdf_split_pairs: set[tuple[str, str]] = set()
    pdf_unbroken_lower: set[str] = set()
    if pdf_path and os.path.exists(pdf_path) and pdf_path.lower().endswith(".pdf"):
        try:
            cache_key = (os.path.abspath(pdf_path), os.path.getmtime(pdf_path))
            cached = _PDF_DEHYPHEN_CACHE.get(cache_key)
            if cached is not None:
                pdf_split_pairs, pdf_unbroken_lower = cached
            else:
                import pypdfium2 as pdfium
                pdoc = pdfium.PdfDocument(pdf_path)
                for page in pdoc:
                    raw_pt = page.get_textpage().get_text_range() or ""
                    raw_pt = raw_pt.replace("\x13", "ff").replace("\x16", "ff").replace("\x14", "fi").replace("\x15", "fl")
                    for tok in re.findall(r"[a-zA-ZäöüÄÖÜß]+(?:[\u00ad\ufffe-][a-zA-ZäöüÄÖÜß]+)+", raw_pt):
                        if "\u00ad" in tok or "\ufffe" in tok:
                            subparts = re.split(r"[\u00ad\ufffe]+", tok)
                            for idx in range(len(subparts) - 1):
                                left = "".join(subparts[: idx + 1]).lstrip("-")
                                right = "".join(subparts[idx + 1 :]).rstrip("-")
                                if len(left) >= 2 and len(right) >= 2:
                                    pdf_split_pairs.add((left, right))
                                if len(subparts[idx]) >= 2 and len(subparts[idx + 1]) >= 2:
                                    pdf_split_pairs.add((subparts[idx], subparts[idx + 1]))
                    for m in re.finditer(
                        r"([a-zA-ZäöüÄÖÜß]{2,})(?:[\u00ad\ufffe]\s*|\-\s*\r?\n\s*)([a-zäöüß][a-zA-ZäöüÄÖÜß]{1,})",
                        raw_pt,
                    ):
                        pdf_split_pairs.add((m.group(1), m.group(2)))
                    cleaned_pt = re.sub(r"[\u00ad\ufffe]", "", raw_pt)
                    for w in re.findall(r"\b[a-zA-ZäöüÄÖÜß]{4,}\b", cleaned_pt):
                        pdf_unbroken_lower.add(w.lower())
                pdoc.close()
                _PDF_DEHYPHEN_CACHE[cache_key] = (pdf_split_pairs, pdf_unbroken_lower)
        except Exception:
            pass

    def _replace_match(m: re.Match) -> str:
        part1 = m.group(1)
        part2 = m.group(2)
        if (part1, part2) in pdf_split_pairs:
            return part1 + part2
        if _is_preserved_lowercase_compound(part1, part2, text, m.start(), m.end()):
            return m.group(0)
        if (part1 + part2).lower() in pdf_unbroken_lower:
            return part1 + part2
        return part1 + part2

    # Run two passes so words with two broken hyphens (e.g. 'Ko-ordina-tensystem') are fully joined
    out = text
    for _ in range(2):
        next_out = re.sub(r"\b([a-zA-ZäöüÄÖÜß]{2,})-([a-zäöüß][a-zA-ZäöüÄÖÜß]{1,})\b", _replace_match, out)
        if next_out == out:
            break
        out = next_out
    return out


def is_two_up_spread_page(page: Any) -> bool:
    """Returns True if the PDF page is a 2-up textbook double-page spread (``pw >= 900`` and ``pw > ph * 1.18``).

    Excludes single-page A5 landscape workbooks (``pw < 750``).
    """
    pw, ph = page.get_size()
    return bool(pw >= 900.0 and pw > ph * 1.18)


def extract_two_up_spread_page_text(page: Any) -> str:
    """Extracts text from a 2-up landscape textbook spread (``pw >= 900``, ``pw > ph * 1.18``)
    by splitting lines at the vertical gutter ``x = pw / 2`` so that:
      1. Full-spread top titles spanning across the gutter appear first,
      2. All left-page (``x_center < pw / 2``) lines/blocks appear next,
      3. All right-page (``x_center >= pw / 2``) lines/blocks appear after the left page,
      4. Standalone printed spread page numbers (``52 53``, ``16 17``, ``88 89``) in the top/bottom
         margins and ``.indd`` / ``.indb`` print-production slugs are stripped.
    """
    pw, ph = page.get_size()
    gutter_x = pw * 0.5
    tp = page.get_textpage()
    full_txt = tp.get_text_range() or ""

    span_header_items: list[tuple[str, float, float]] = []
    left_items: list[tuple[str, float, float]] = []
    right_items: list[tuple[str, float, float]] = []
    right_bottom_tasks: list[tuple[str, float, float]] = []

    pos = 0
    raw_lines = full_txt.split("\r\n")
    in_right_bottom_tasks = False

    for line in raw_lines:
        n = len(line)
        ls = line.strip()
        if not ls:
            pos += n + 2
            continue

        char_boxes: list[tuple[int, float, float, float, float]] = []
        for idx in range(pos, pos + n):
            box = tp.get_charbox(idx)
            if box:
                left_x, b, r, t = box
                if r > left_x and t > b:
                    char_boxes.append((idx - pos, left_x, b, r, t))
        pos += n + 2

        if not char_boxes:
            left_items.append((ls, 0.0, 0.0))
            continue

        segments: list[tuple[str, float, float, float]] = []
        seg_start_char = 0
        seg_xs: list[float] = []
        seg_ys: list[float] = []

        for k, (rel_i, left_x, b, r, t) in enumerate(char_boxes):
            xc = (left_x + r) * 0.5
            yc = (b + t) * 0.5
            if k > 0:
                _prev_rel_i, _prev_l, _prev_b, prev_r, _prev_t = char_boxes[k - 1]
                if prev_r < pw * 0.48 and left_x > pw * 0.52 and (left_x - prev_r) > 40.0:
                    seg_str = line[seg_start_char:rel_i].strip()
                    if seg_str and seg_xs:
                        segments.append((seg_str, min(seg_xs), max(seg_xs), sum(seg_ys) / len(seg_ys)))
                    seg_start_char = rel_i
                    seg_xs = []
                    seg_ys = []
            seg_xs.append(xc)
            seg_ys.append(yc)

        tail_str = line[seg_start_char:].strip()
        if tail_str and seg_xs:
            segments.append((tail_str, min(seg_xs), max(seg_xs), sum(seg_ys) / len(seg_ys)))

        for seg_str, x_min, x_max, y_avg in segments:
            if (y_avg < ph * 0.09 or y_avg > ph * 0.91) and re.fullmatch(
                r"(?:Seite\s*)?\d{1,4}(?:\s+(?:Seite\s*)?\d{1,4})?",
                seg_str,
                re.IGNORECASE,
            ):
                continue
            if re.search(r"\.ind[db]\s+\d{1,4}(?:[–-]\d{1,4})?\s+\d{2}\.\d{2}\.\d{4}", seg_str, re.IGNORECASE):
                continue

            x_mid = (x_min + x_max) * 0.5
            if x_min < pw * 0.42 and x_max > pw * 0.58 and y_avg > ph * 0.82:
                span_header_items.append((seg_str, x_min, y_avg))
            elif x_mid < gutter_x:
                in_right_bottom_tasks = False
                left_items.append((seg_str, x_min, y_avg))
            else:
                if re.match(r"^Aufgaben\b", seg_str) and y_avg < ph * 0.32:
                    in_right_bottom_tasks = True
                elif in_right_bottom_tasks and y_avg > ph * 0.40:
                    in_right_bottom_tasks = False

                if in_right_bottom_tasks:
                    right_bottom_tasks.append((seg_str, x_min, y_avg))
                else:
                    right_items.append((seg_str, x_min, y_avg))

    tp.close()

    def _join_column_items(items: list[tuple[str, float, float]]) -> str:
        if not items:
            return ""
        chunks: list[str] = [items[0][0]]
        for idx in range(1, len(items)):
            curr_txt, curr_x, curr_y = items[idx]
            _prev_txt, prev_x, prev_y = items[idx - 1]
            dy = prev_y - curr_y
            dx = abs(curr_x - prev_x)
            is_new_block = (
                dx > 40.0
                or dy < 4.0
                or dy > 24.0
                or bool(
                    re.match(
                        r"^(?:M\d+\b|Aufgaben\b|Extra\b|Kannst du schon\b|Zeig, was du kannst\b|[1-9]\d?\.\s|[1-9]\s+[A-ZÄÖÜ]|[a-z]\)\s|[–•-]\s)",
                        curr_txt,
                    )
                )
            )
            if is_new_block:
                chunks.append("\n\n" + curr_txt)
            else:
                chunks.append("\n" + curr_txt)
        return "".join(chunks)

    parts = [
        _join_column_items(span_header_items),
        _join_column_items(left_items),
        _join_column_items(right_items),
        _join_column_items(right_bottom_tasks),
    ]
    return "\n\n".join(p for p in parts if p.strip())


def clean_pdf_text_preserving_structure(text: str, pdf_path: str | None = None) -> str:
    """Cleans control-char ligatures, soft hyphens, PUA glyphs, small-caps encoding artefacts,
    and ``.indd``/``.indb`` print-production slugs while preserving paragraph newlines.
    """
    if not text:
        return text
    s = text.replace("\x13", "ff").replace("\x16", "ff").replace("\x14", "fi").replace("\x15", "fl")
    s = re.sub(r"\.2175\$+\s*\$*UJXPHQW", ".2175 UJXPHQW", s)
    s = re.sub(r"\$+UJXPHQW", "UJXPHQW", s)
    s = re.sub(r"\bLeRnBoX\b|\bLeRnBOX\b", "LERNBOX", s)
    s = re.sub(r"\bAuSBlICK\b", "AUSBLICK", s)
    s = re.sub(r"\bZu SeiTe\b", "Zu Seite", s)
    s = re.sub(
        r"\S+\.ind[db]\s+\d{1,4}(?:[–-]\d{1,4})?\s+\d{2}\.\d{2}\.\d{4}(?:\s+\d{2}:\d{2}(?::\d{2})?(?:\s*Uhr)?)?(?:\s*©[^\r\n]*)?",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"\S*_Inhalt_S\d+\s+\d+\s+\d{2}\.\d{2}\.\d{4}[^\r\n]*", "", s, flags=re.IGNORECASE)
    while re.search(r"([a-zA-ZäöüÄÖÜß])[\u00ad\ufffe]([a-zäöüß])", s):
        s = re.sub(r"([a-zA-ZäöüÄÖÜß])[\u00ad\ufffe]([a-zäöüß])", r"\1\2", s)
    s = s.replace("\u00ad", "").replace("\ufffe", "")
    s = re.sub(r"[\ue000-\uf8ff\ufff0-\uffff]", "", s)
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]+", " ", s)
    if pdf_path:
        s = dehyphenate_inline_broken_words(s, pdf_path=pdf_path)
    return s


def clean_pdf_text_for_eval(text: str, pdf_path: str | None = None) -> str:
    """Canonical PDF text layer cleaner for word-recall evaluation against Golden Ground Truths.

    Normalizes ligatures, strips ``.indd``/``.indb`` print slugs, joins soft and line-break
    hyphens across newlines, removes PUA/zero-width glyphs, and collapses horizontal whitespace.
    """
    if not text:
        return ""
    s = text.replace("\x13", "ff").replace("\x16", "ff").replace("\x14", "fi").replace("\x15", "fl")
    s = re.sub(
        r"\S+\.ind[db]\s+\d{1,4}(?:[–-]\d{1,4})?\s+\d{2}\.\d{2}\.\d{4}(?:\s+\d{2}:\d{2}(?::\d{2})?(?:\s*Uhr)?)?(?:\s*©[^\r\n]*)?",
        " ",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"\S*_Inhalt_S\d+\s+\d+\s+\d{2}\.\d{2}\.\d{4}[^\r\n]*",
        " ",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"([a-zA-ZäöüÄÖÜß]{2,})[\u00ad\ufffe-][ \t]*\r?\n+[ \t]*([a-zäöüß][a-zA-ZäöüÄÖÜß]*)",
        r"\1\2",
        s,
    )
    while re.search(r"([a-zA-ZäöüÄÖÜß])[\u00ad\ufffe]([a-zäöüß])", s):
        s = re.sub(r"([a-zA-ZäöüÄÖÜß])[\u00ad\ufffe]([a-zäöüß])", r"\1\2", s)
    s = s.replace("\u00ad", "").replace("\ufffe", "")
    s = re.sub(r"[\ue000-\uf8ff\ufff0-\uffff]", " ", s)
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]+", " ", s)
    s = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", s)
    if pdf_path:
        s = dehyphenate_inline_broken_words(s, pdf_path=pdf_path)
    return re.sub(r"[ \t]+", " ", s).strip()


clean_pdf_text = clean_pdf_text_for_eval


def recover_text_truncation(markdown_content: str, pdf_path: str | None = None) -> str:
    r"""Subtask 1: Text-Truncation & De-Hyphenation Recovery
    - Strips PDF print-production slugs (.indd/.indb timestamps), soft hyphens (\u00ad, \ufffe), and PUA glyphs.
    - Joins soft wraps and hyphenated words across line, column, and page boundaries.
    - Preserves Markdown structure, headings, lists, tables, and page boundaries.
    - Cleans runaway token repetition loops.
    """
    if not markdown_content:
        return markdown_content

    processed = fix_escaped_dollars(markdown_content)
    processed = processed.replace("\x13", "ff").replace("\x16", "ff").replace("\x14", "fi").replace("\x15", "fl")
    processed = re.sub(r"\.2175\$+\s*\$*UJXPHQW", ".2175 UJXPHQW", processed)
    processed = re.sub(r"\$+UJXPHQW", "UJXPHQW", processed)
    processed = re.sub(r"\bLeRnBoX\b|\bLeRnBOX\b", "LERNBOX", processed)
    processed = re.sub(r"\bAuSBlICK\b", "AUSBLICK", processed)
    processed = re.sub(r"\bZu SeiTe\b", "Zu Seite", processed)

    # 0a. If a digital PDF page was largely swallowed into a picture bbox (< 25 words extracted and PDF has > 2x tokens),
    #     recover the embedded PDF text layer lines via pypdfium2.
    if pdf_path and os.path.exists(pdf_path) and pdf_path.lower().endswith(".pdf"):
        clean_no_imgs = re.sub(r"!\[.*?\]\(.*?\)|\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)", "", processed)
        extracted_tokens = re.findall(r"\S{2,}", clean_no_imgs)
        if len(extracted_tokens) < 25:
            try:
                import pypdfium2 as pdfium
                pdoc = pdfium.PdfDocument(pdf_path)
                pdf_lines = []
                for page in pdoc:
                    raw_pt = (
                        extract_two_up_spread_page_text(page)
                        if is_two_up_spread_page(page)
                        else (page.get_textpage().get_text_range() or "")
                    )
                    for ln in raw_pt.splitlines():
                        ls = ln.strip()
                        if ls and not re.fullmatch(r"\d{1,4}", ls):
                            pdf_lines.append(ls)
                pdoc.close()
                pdf_tokens = re.findall(r"\S{2,}", " ".join(pdf_lines))
                if len(pdf_tokens) >= max(10, len(extracted_tokens) * 2):
                    existing_lower = clean_no_imgs.lower()
                    missing_lines = [ln for ln in pdf_lines if ln.lower() not in existing_lower]
                    if missing_lines:
                        processed = processed.rstrip() + "\n\n" + "\n\n".join(missing_lines) + "\n"
            except Exception:
                pass

    # 0b. Strip InDesign print-production slug lines and inline fragments
    # (e.g. 'DO01_...indd 18 11.11.2025 15:08:08', '110796_...indd 26-27 12.07.2021 15:46:49 Uhr © ...', '01_..._Inhalt_S001 1 20.06.2023 11:02:30')
    processed = re.sub(
        r"(?m)^[ \t]*\S+\.ind[db][ \t]+\d{1,4}(?:[–-]\d{1,4})?[ \t]+\d{2}\.\d{2}\.\d{4}(?:[ \t]+\d{2}:\d{2}(?::\d{2})?(?:[ \t]*Uhr)?)?(?:[ \t]*©[^\n]*)?[ \t]*\n?",
        "",
        processed,
        flags=re.IGNORECASE,
    )
    processed = re.sub(
        r"\S+\.ind[db]\s+\d{1,4}(?:[–-]\d{1,4})?\s+\d{2}\.\d{2}\.\d{4}(?:\s+\d{2}:\d{2}(?::\d{2})?(?:\s*Uhr)?)?(?:\s*©[^\n]*)?",
        "",
        processed,
        flags=re.IGNORECASE,
    )
    processed = re.sub(
        r"\S*_Inhalt_S\d+\s+\d+\s+\d{2}\.\d{2}\.\d{4}[^\n]*",
        "",
        processed,
        flags=re.IGNORECASE,
    )
    # 0b. Strip Private Use Area (PUA) icon glyphs (\ue000..\uf8ff)
    processed = re.sub(r"[\ue000-\uf8ff]", "", processed)
    # 0c. Normalize PDF soft hyphens (\u00ad) and \ufffe hyphenation markers
    processed = re.sub(r"([a-zA-ZäöüÄÖÜß])[\u00ad\ufffe][ \t]*(?=\n)", r"\1-", processed)
    while re.search(r"([a-zA-ZäöüÄÖÜß])[\u00ad\ufffe]([a-zäöüß])", processed):
        processed = re.sub(r"([a-zA-ZäöüÄÖÜß])[\u00ad\ufffe]([a-zäöüß])", r"\1\2", processed)
    processed = processed.replace("\u00ad", "").replace("\ufffe", "-")

    # 1. Join hyphenated words split across lines and page boundaries (including spread markers ((N)) / ((N+1)))
    hyphen_pattern = r"([a-zA-ZäöüÄÖÜß]{2,})-[ \t]*\n+(?:(\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)(?:\s*/\s*\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\))?)[ \t]*\n+)?[ \t]*([a-zA-ZäöüÄÖÜß]{2,})([.,;:!?])?[ \t]*"

    def replace_hyphen(match: re.Match) -> str:
        part1 = match.group(1)
        page_break = match.group(2)
        part2 = match.group(3)
        punct = match.group(4) or ""
        if part2.lower() in fc.SUSPENDED_HYPHEN_FOLLOWERS:
            joined = f"{part1}- {part2}{punct} "
        elif part1[0].isupper() and part2 in {
            "Hütte", "Tor", "Straße", "Weg", "Platz", "See", "Fluss", "Berg", "Gebirge",
            "Insel", "Halbinsel", "Kanal", "Meer", "Ozean", "Wüste", "Becken", "Tal",
            "Achse", "Formel", "Satz", "Regel", "Gesetz", "Effekt", "Modell", "System",
            "Test", "Check", "Rumpf", "Länge", "Editor", "Institut", "Krieg", "Chef",
        }:
            joined = f"{part1}-{part2}{punct}"
        else:
            if part2 and part2[0].isupper() and part1[-1].islower():
                part2 = part2[0].lower() + part2[1:]
            joined = part1 + part2 + punct
        if page_break:
            return f"{joined.rstrip()}\n\n{page_break}\n\n"
        return joined

    processed = re.sub(hyphen_pattern, replace_hyphen, processed)
    # Also repair pre-joined cross-page camelCase hyphenations (e.g. 'SelbstaufGabe ((86))\n. Dieser' -> 'Selbstaufgabe.\n\n((86))\n\nDieser')
    processed = re.sub(
        r"\b([A-ZÄÖÜa-zäöüß]{2,}[a-zäöüß])([A-ZÄÖÜ][a-zäöüß]{2,})[ \t]+(\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\))[ \t]*\n+[ \t]*([.,;:!?])[ \t]*",
        lambda m: f"{m.group(1)}{m.group(2).lower()}{m.group(4)}\n\n{m.group(3)}\n\n",
        processed,
    )
    # Join in-line hyphenated words with spaces where second part starts with lowercase (e.g. 'Brechungs- winkel' -> 'Brechungswinkel')
    processed = fc.INLINE_HYPHEN_SPACE_RE.sub(r"\1\2", processed)
    # Join broken mid-word inline hyphens (e.g. 'Aufga-ben' -> 'Aufgaben')
    processed = dehyphenate_inline_broken_words(processed, pdf_path=pdf_path)

    # 1b. Rejoin 2-column split paragraphs when a mid-page table/figure block displaced the column-2 continuation:
    # e.g. Paragraph 1 ends with 'Reaktionsgeschwindig-' followed by a table/figure block and then a paragraph starting with 'keit v von der...'
    displaced_col2_re = re.compile(
        r"([a-zA-ZäöüÄÖÜß]{3,})-[ \t]*\n\n((?:(?!(?:\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\))).)+?)\n\n([a-zäöüß]{2,}\b[^\n]+(?:\n(?![ \t]*(?:\n|#{1,6}\s|\(\(|\||!\[|<))[^\n]+)*)",
        re.DOTALL,
    )
    processed = displaced_col2_re.sub(r"\1\3\n\n\2", processed)

    # 2. Join soft wraps within paragraphs (strictly single newline, never across ((num)), headings, lists, or tables)
    lines = processed.splitlines()
    merged_lines: list[str] = []
    for line in lines:
        s = line.strip()
        if (
            merged_lines
            and s
            and merged_lines[-1].strip()
            and not re.match(
                r"^(?:#{1,6}\s|\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)|[-*•]\s|\d+\.\s|[a-z]\)\s|\||<|!\[|\[?\d+\]\s)",
                s,
            )
            and not re.match(
                r"^(?:#{1,6}\s|\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)|\||<|!\[|\*\*.*\*\*$)",
                merged_lines[-1].strip(),
            )
            and re.search(r"[a-zA-Z0-9äöüÄÖÜß,;:\)\]\"']$", merged_lines[-1].strip())
            and re.match(r"^[a-zäöüß\(\[\"'\$\<]", s)
        ):
            merged_lines[-1] = merged_lines[-1].rstrip() + " " + s
        else:
            merged_lines.append(line.rstrip())
    processed = "\n".join(merged_lines)

    # 3. Clean up any external URLs in image tags (preserve normal markdown links like [WebApp](https://...))
    processed = re.sub(r"!\[(.*?)\]\(https?://[^)]+\)", r"<Bild> Abbildung: \1 </Bild>", processed)
    processed = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", processed)

    # 4. Standardize German and typographic quotation marks to ASCII
    processed = re.sub(r"[„“”»«]", '"', processed)
    processed = re.sub(r"[‚‘’‹›]", "'", processed)

    # 5. Standardize ellipses (prepend space before three dots: aabb... -> aabb ...)
    processed = re.sub(r"…", " ...", processed)
    processed = re.sub(r"([a-zA-Z0-9äöüÄÖÜß_\*\%#])\.\.\.", r"\1 ...", processed)

    # 6. Strip runaway character and line repetitions
    processed = sanitize_runaway_repetitions(processed)

    return processed


def clean_duplicate_itemization(markdown_content: str) -> str:
    r"""Clean duplicate itemization and list markers in extracted Markdown.

    - Fixes duplicated bullets: '- - ' -> '- ', '- • ' -> '- ', '- · ' -> '- '
    - Fixes duplicated numbers: '3. 3. ' -> '3. ', '- 1. ' -> '1. '
    - Fixes bullet symbols combined with dashes: '- ■ ' -> '- '
    - Cleans Docling checkbox markers before lettered subtasks ('- [ ] a)' -> 'a)') and escaped underscores ('\_\_\_\_' -> '____').
    """
    if not markdown_content:
        return markdown_content

    # Unescape consecutive escaped underscores (\_\_\_\_ -> ____)
    markdown_content = re.sub(r"(?:\\_){2,}", lambda m: "_" * (len(m.group(0)) // 2), markdown_content)

    lines = markdown_content.split("\n")
    cleaned_lines = []

    for line in lines:
        cleaned = line
        # 0. Clean Docling checkbox/bullet prefix before lettered subtasks: '- [ ] a) ' or '- a) ' -> 'a) '
        cleaned = re.sub(r"^(\s*)-\s+\[\s*[xX]?\s*\]\s+([a-z]\)\s+)", r"\1\2", cleaned)
        cleaned = re.sub(r"^(\s*)[-*•]\s+([a-z]\)\s+)", r"\1\2", cleaned)

        # 1. Clean double dashes/bullets: - - -> - , - • -> - , - · -> - , - ◦ -> -
        cleaned = re.sub(r"^(\s*)-\s+[-\u2022\u00b7\u25e6]\s+", r"\1- ", cleaned)
        cleaned = re.sub(r"^(\s*)[-\u2022\u00b7\u25e6]\s+[-\u2022\u00b7\u25e6]\s+", r"\1- ", cleaned)
        cleaned = re.sub(r"^(\s*)\*\s+(?=[A-ZÄÖÜa-zäöü\$])", r"\1- ", cleaned)

        # 2. Clean bullet symbols after dash: - ■ -> - , - ● -> - , - ○ -> -
        cleaned = re.sub(r"^(\s*)-\s+[\u25a0\u25cf\u25cb\u25c6\u25b2]\s+", r"\1- ", cleaned)

        # 3. Clean dash before numbered list: - 1. -> 1.
        cleaned = re.sub(r"^(\s*)-\s+(\d+\.)\s+", r"\1\2 ", cleaned)

        # 4. Clean duplicated numbers: 3. 3. -> 3., 1. 1. -> 1.
        cleaned = re.sub(r"^(\s*(\d+)\.)\s+\2\.\s+", r"\1 ", cleaned)

        # 5. Clean tab or multiple spaces after bullet/numbered marker to single space in raw markdown
        cleaned = re.sub(r"^(\s*[-*])(?:\t+|\s{2,})", r"\1 ", cleaned)
        cleaned = re.sub(r"^(\s*\d+\.)(?:\t+|\s{2,})", r"\1 ", cleaned)

        # 5b. Restore circle difficulty symbols when PDF list parser turned '○/◐/● Aufgabe N (leicht/mittel/schwer):' into '- Aufgabe N (leicht):'
        m_diff_task = re.match(
            r"^\s*(?:[-*•]\s*)?(?:[○◐●]\s*)?(Aufgabe\s+\d+)\s*\((leicht|mittel|schwer)\)\s*:\s*(.+)$",
            cleaned,
            re.IGNORECASE,
        )
        if m_diff_task:
            t_label = m_diff_task.group(1)
            d_lvl = m_diff_task.group(2).lower()
            t_body = m_diff_task.group(3).strip()
            sym = {"leicht": "○", "mittel": "◐", "schwer": "●"}[d_lvl]
            cleaned = f"{sym} [{d_lvl}] {t_label}: {t_body}"

        cleaned_lines.append(cleaned)

    # 6. Reorder interleaved two-column lettered subtasks (e.g. a), f), b), g) -> a)..j))
    final_lines: list[str] = []
    i = 0
    while i < len(cleaned_lines):
        s = cleaned_lines[i].strip()
        if re.match(r"^[a-z]\)\s+", s):
            block_items: list[str] = []
            j = i
            while j < len(cleaned_lines):
                sj = cleaned_lines[j].strip()
                if not sj:
                    j += 1
                    continue
                if re.match(r"^[a-z]\)\s+", sj):
                    # Split multiple inline subtasks on the same line (e.g. 'a) ... b) ...') if separated by spaces
                    parts = re.split(r"(?<=[_0-9\?\.])\s+(?=[a-z]\)\s+)", sj)
                    for pt in parts:
                        # Unwrap trivial elementary arithmetic '$24 + 37 =$' before fill-in blanks
                        pt_clean = re.sub(r"\$(\d+\s*[\+\-\*:]\s*\d+\s*=)\$", r"\1", pt.strip())
                        block_items.append(pt_clean)
                    j += 1
                else:
                    break
            if len(block_items) >= 2:
                letters = [ it[0].lower() for it in block_items if re.match(r"^[a-z]\)", it) ]
                if letters != sorted(letters):
                    block_items.sort(key=lambda x: x[0].lower())
                final_lines.extend(block_items)
                final_lines.append("")
                i = j
                continue
        final_lines.append(cleaned_lines[i])
        i += 1

    return "\n".join(final_lines)


# Shared didactic callout box prefix pattern (used by Raw Markdown post-processing and FIBS 09/2025 <Rahmen> wrapping)
DIDACTIC_CALLOUT_PREFIXES = (
    r"Methode(?:n-Kasten)?\s*:|"
    r"Merksatz\s*:|"
    r"Sachwissen(?:\s+kompakt)?\s*:|"
    r"Forscher-Tipp\s*:|"
    r"Tipp(?:\s+[^\n:]+)?\s*:|"
    r"Worterklärungen\b|"
    r"Hintergrund\s*:|"
    r"Sprachwissen\s*:|"
    r"Sprachschatz\b|"
    r"Wortspeicher\b|"
    r"Spielidee\b|"
    r"Checkliste\b|"
    r"Bio-Kompakt\s*:|"
    r"Zusammenfassung\b|"
    r"Geo-Lexikon\s*:|"
    r"Lexikon\s*:|"
    r"Lernwegweiser\b|"
    r"Wortbausteine\s*:|"
    r"Mediencode\b|"
    r"Historisches\s+Grundwissen\s*:|"
    r"Versuchsprotokoll\b|"
    r"Merke\s*:|"
    r"Wichtig\s*:|"
    r"Info(?:-Kasten)?\s*:|"
    r"M[1-9]\s*:|"
    r"Useful\s+Phrases\s*:|"
    r"Grammar\s+Box\s*:|"
    r"Study\s+Skills\s*:|"
    r"Sicherheit\b[^\n:]*:|"
    r"Beispielrechnung\s*:|"
    r"CHAPTER OUTLINE\b|"
    r"LEARNING OBJECTIVES\b|"
    r"LINK TO LEARNING\b|"
    r"(?:CAREER|EVERYDAY|EVOLUTION)\s+CONNECTION\b|"
    r"THE PAST MEETS THE PRESENT\b|"
    r"Check Your Learning\b|"
    r"Solution\b|"
    r"EXAMPLE\s+\d+(?:\.\d+)?\b|"
    r"Lernbox\b|"
    r"Sprachbox\b|"
    r"Nach\s+Niveau\s+differenzieren\b|"
    r"Kreative\s+Zusatzaufgaben\b|"
    r"Gestärkt\s+in\s+die\s+Klassenarbeit\b|"
    r"(?:Fortgeschrittener\s+)?Arbeitsauftrag\s*:?$"
)

_DIDACTIC_CALLOUT_BOX_RE = re.compile(
    r"^(?:" + DIDACTIC_CALLOUT_PREFIXES + r")",
    re.IGNORECASE,
)


def _normalize_allcaps_german_heading(text: str) -> str:
    """Converts an ALL-CAPS German section/chapter heading (e.g. from a running header)
    into standard German capitalization (capitalizing first word and nouns, lowercasing prepositions/adjectives).
    """
    m = re.match(r"^(\d+(?:\.\d+)*\.?\s+)([A-ZÄÖÜ\s\-]{6,})$", text)
    if not m:
        m_k = re.match(r"^(KAPITEL\s+\d+\.?\s+)([A-ZÄÖÜ\s\-]{3,})$", text)
        if not m_k:
            return text
        prefix = m_k.group(1).title()
        words = m_k.group(2).split()
    else:
        prefix = m.group(1)
        words = m.group(2).split()

    lower_words = {
        "in", "im", "an", "am", "auf", "aus", "bei", "durch", "für", "gegen", "hinter",
        "mit", "nach", "neben", "über", "um", "unter", "von", "vor", "zu", "zum", "zur",
        "zwischen", "und", "oder", "aber", "den", "dem", "der", "die", "das", "des",
        "einer", "eines", "einem", "einen", "unterschiedlichen", "verschiedenen", "gleichen",
    }
    out_words = []
    for idx, w in enumerate(words):
        wl = w.lower()
        if idx > 0 and wl in lower_words:
            out_words.append(wl)
        else:
            out_words.append(w.capitalize())
    return f"{prefix}{' '.join(out_words)}"


def cluster_heading_heights(heights: list[float], tol: float = 6.0) -> list[float]:
    """Clusters heading bounding-box heights in descending order within ``tol`` and returns cluster means.

    Ported from ``lightonocr/lib.mjs`` (``clusterHeadingHeights``): the largest observed
    heading height defines level 1, and each subsequent height smaller by at least ``tol``
    starts a new lower heading level cluster.

    Args:
        heights: Sequence of positive heading heights (in ``0..1000`` grid units or PDF points).
        tol: Minimum height difference required to start a new cluster.

    Returns:
        List of cluster mean heights in descending order.
    """
    valid = sorted((float(h) for h in heights if h and float(h) > 0), reverse=True)
    if not valid:
        return []
    clusters: list[list[float]] = []
    anchors: list[float] = []
    for h in valid:
        if not anchors or h <= anchors[-1] - tol:
            anchors.append(h)
            clusters.append([h])
        else:
            clusters[-1].append(h)
    return [round(sum(c) / len(c), 2) for c in clusters]


def clamp_heading_outline_levels(markdown_text: str) -> str:
    """Clamps Markdown heading levels sequentially so no heading skips an outline level.

    Applies ``min(level, outline_top + 1, 6)`` across the document while preserving
    standard FIBS ``### Aufgabe N:`` headings when preceded by ``#`` or ``##``.

    Args:
        markdown_text: Input Markdown text containing ATX headings.

    Returns:
        Markdown text with sequential heading levels clamped to prevent level skips.
    """
    if not markdown_text:
        return markdown_text
    lines = markdown_text.split("\n")
    outline_top = 0
    for idx, line in enumerate(lines):
        m = re.match(r"^([ \t]*)(#{1,6})\s+(.+)$", line)
        if not m:
            continue
        indent, hashes, title = m.group(1), m.group(2), m.group(3).strip()
        lvl = len(hashes)
        is_fibs_task = bool(
            lvl == 3
            and outline_top in (1, 2)
            and re.match(r"^(?:Aufgabe|Übung|Versuch|Experiment)\b", title, re.IGNORECASE)
        )
        if not is_fibs_task:
            max_allowed = 1 if outline_top == 0 else min(outline_top + 1, 6)
            if lvl > max_allowed:
                lvl = max_allowed
                lines[idx] = f"{indent}{'#' * lvl} {title}"
        outline_top = lvl
    return "\n".join(lines)


def reconstruct_title_hierarchy(
    markdown_content: str,
    content_list_path: str | None = None,
    directory_info: dict[str, Any] | None = None,
) -> str:
    """Subtask 2: Title Hierarchy Reconstruction
    - Reconstructs semantic levels (# H1, ## H2, ### H3, #### H4) using bounding-box font heights
      from _content_list.json, Table of Contents (Inhaltsverzeichnis) entries, section numbering,
      chapter markers, and structural keywords.
    - Splits merged chapter + section headings ('# Kapitel 5: ... 5.1 ...').
    - Formats callout box titles as '**Title**' so they do not pollute section heading hierarchy.
    """
    if not markdown_content:
        return markdown_content

    from backend.services.fibs_postprocess import normalize_heading_page_markers

    markdown_content = normalize_heading_page_markers(markdown_content)

    # Step 0a: Join consecutive '# CHAPTER N' + '# <Title>' on adjacent lines into '# CHAPTER N: <Title>'
    markdown_content = re.sub(
        r"(?m)^#{1,3}\s+((?:CHAPTER|KAPITEL)\s+\d+)\s*\n+#{1,3}\s+([A-ZÄÖÜ][^\n]+)$",
        r"# \1: \2",
        markdown_content,
    )

    # Step 0b: Split merged chapter + section headings on the same line:
    # e.g. '# Kapitel 5: ... 5.1 ...' -> '# Kapitel 5: ...\n\n## 5.1 ...'
    markdown_content = re.sub(
        r"(?m)^(#{1,6})\s+((?:Kapitel|Chapter|Teil|Part)\s+\d+\s*[:\.]?\s+[^\n]+?)\s+(\d+\.\d+\.?\s+[A-ZÄÖÜa-zäöü][^\n]*)$",
        r"# \2\n\n## \3",
        markdown_content,
    )

    bbox_levels: dict[str, int] = {}
    body_sized_titles: set = set()
    callout_box_titles: set = set()
    if content_list_path and os.path.exists(content_list_path):
        try:
            with open(content_list_path, encoding="utf-8") as f:
                data = json.load(f)

            blocks = []
            if isinstance(data, dict):
                blocks = data.get("blocks", data.get("content", []))
            elif isinstance(data, list):
                if data and isinstance(data[0], list):
                    for page in data:
                        blocks.extend(page)
                else:
                    blocks = data

            title_blocks = []
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                b_type = str(b.get("type", "")).lower()
                if b_type in ("title", "section_header", "sectionheaderitem", "titleitem", "heading") or (
                    b_type == "text" and b.get("text_level", 0) > 0
                ):
                    txt = b.get("text", "").strip()
                    if b.get("is_callout_box"):
                        callout_box_titles.add(txt)
                        continue
                    if b.get("is_body_sized"):
                        body_sized_titles.add(txt)
                        continue
                    bbox = b.get("bbox", [])
                    if txt and len(bbox) == 4:
                        height = round(abs(bbox[3] - bbox[1]), 2)
                        if height > 0:
                            title_blocks.append((txt, height))

            if title_blocks:
                # Anchor H2 height if a 'Kapitel' heading is present alongside a larger H1 title
                max_h = max(h for _, h in title_blocks)
                kapitel_heights = [
                    h for t, h in title_blocks
                    if re.match(r"^(?:Kapitel|Chapter|Teil|Part)\s+\d+", t, re.IGNORECASE) and h < max_h * 0.9
                ]
                if kapitel_heights:
                    h2_ref = kapitel_heights[0]
                    for txt, h in title_blocks:
                        if h >= max_h * 0.88:
                            bbox_levels[txt] = 1
                        elif h >= h2_ref * 0.92:
                            bbox_levels[txt] = 2
                        else:
                            bbox_levels[txt] = 3
                else:
                    clusters = cluster_heading_heights([h for _, h in title_blocks], tol=0.6)
                    for txt, h in title_blocks:
                        rank = min(range(len(clusters)), key=lambda idx: abs(clusters[idx] - h))
                        target_level = min(rank + 1, 4)
                        bbox_levels[txt] = target_level
        except Exception as e:
            logger.warning(f"Could not parse bbox font heights for hierarchy: {e}")

    has_ch11 = bool(re.search(r"\b11\.\d+", markdown_content))
    if has_ch11:
        markdown_content = re.sub(
            r"\b(Abbildung|Abb\.|Bild)\s*(?:II|ii|1I|I1|ı1|I|ı|1)?\.(\d|s)(\d|o)\b",
            lambda m: f"{m.group(1)} 11.{m.group(2).replace('s', '5')}{m.group(3).replace('o', '0')}",
            markdown_content,
        )
        markdown_content = re.sub(
            r"\((?:i\s*\.\s*i|I\s*I\s*\.\s*1|II\.1|ii\.1)\)",
            "(11.1)",
            markdown_content,
        )
        markdown_content = re.sub(
            r"\((?:I\s*I\s*\.\s*2|II\.2|ii\.2)\)",
            "(11.2)",
            markdown_content,
        )
        # If OCR dropped the 3rd-level '.4' on a section heading situated between '11.6.3' and '11.6.5', restore '11.6.4'
        if "11.6.3" in markdown_content and "11.6.5" in markdown_content:
            markdown_content = re.sub(
                r"(?m)(11\.6\.3[\s\S]+?)^(#{1,6}\s+)11\.6\.?\s+(?!\d)([A-ZÄÖÜ][^\n]+)(?=[\s\S]+?11\.6\.5)",
                r"\1\g<2>11.6.4 \3",
                markdown_content,
            )

    lines = markdown_content.split("\n")
    # Identify callout box titles first so their bbox heights do not skew heading clusters
    excluded_from_bbox_clusters = set(callout_box_titles)
    in_openstax_example = False
    openstax_box_header_re = re.compile(
        r"\b(?:EXAMPLE\s+\d+\.\d+|(?:CAREER|EVERYDAY|EVOLUTION)\s+CONNECTION|THE\s+PAST\s+MEETS\s+THE\s+PRESENT)\b",
        re.IGNORECASE,
    )
    for idx_l, raw_l in enumerate(lines):
        s_l = raw_l.strip()
        if not s_l:
            continue
        if openstax_box_header_re.search(s_l):
            in_openstax_example = True
        m_ch = re.match(r"^(?:#{1,6}\s+|\*\*)(.+?)(?:\*\*)?$", s_l)
        if m_ch:
            ct = m_ch.group(1).strip()
            if _DIDACTIC_CALLOUT_BOX_RE.match(ct):
                excluded_from_bbox_clusters.add(ct)
                if "check your learning" in ct.lower():
                    in_openstax_example = False
                continue
            if in_openstax_example and not re.match(r"^\d+\.\d+\s+", ct):
                # Inside an OpenStax EXAMPLE or CONNECTION box, only mark the subtitle right after the box header or 'Solution' as callout
                prev_non_empty = ""
                for p_i in range(idx_l - 1, max(-1, idx_l - 4), -1):
                    if lines[p_i].strip():
                        prev_non_empty = lines[p_i].strip()
                        break
                if openstax_box_header_re.search(prev_non_empty) or ct.lower() == "solution":
                    excluded_from_bbox_clusters.add(ct)
                    continue
                else:
                    in_openstax_example = False
            if re.match(r"^(?:Merksatz|Bild\s+\d+\.\d+)\s*:\s*\S", ct, re.IGNORECASE):
                j = idx_l + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and re.match(r"^(?:[-*•]|\d+\.)\s+", lines[j].strip()):
                    excluded_from_bbox_clusters.add(ct)
                    continue
            if not re.match(
                r"^(?:Kapitel|Chapter|Teil|Abschnitt|\d+\.|[IVXLCDM]+\.|Versuch|Experiment|Aufgabe|Übung|Merksatz|Tab(?:elle)?\.?\s+\d+)",
                ct,
                re.IGNORECASE,
            ):
                j = idx_l + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines):
                    sub_l = lines[j].strip()
                    sub_clean = re.sub(r"^[\*_]+|[\*_]+$", "", sub_l).strip()
                    k = j + 1
                    while k < len(lines) and not lines[k].strip():
                        k += 1
                    if (
                        k < len(lines)
                        and 10 <= len(sub_clean) <= 65
                        and not re.match(r"^(?:#|-|\*\s|\||<|\(\()", sub_l)
                        and not sub_clean.endswith((".", "!", "?"))
                        and re.match(r"^[-*•]\s+", lines[k].strip())
                    ):
                        excluded_from_bbox_clusters.add(ct)

    # Rebuild bbox_levels excluding non-heading callout titles
    if content_list_path and os.path.exists(content_list_path) and excluded_from_bbox_clusters:
        try:
            with open(content_list_path, encoding="utf-8") as f:
                data = json.load(f)
            blocks = data.get("blocks", data.get("content", [])) if isinstance(data, dict) else data
            if isinstance(blocks, list) and blocks and isinstance(blocks[0], list):
                blocks = [b for page in blocks for b in page]
            filtered_tb = []
            for b in blocks:
                if not isinstance(b, dict) or b.get("is_body_sized") or b.get("is_callout_box"):
                    continue
                b_type = str(b.get("type", "")).lower()
                if b_type in ("title", "section_header", "sectionheaderitem", "titleitem", "heading") or (
                    b_type == "text" and b.get("text_level", 0) > 0
                ):
                    txt = b.get("text", "").strip()
                    bbox = b.get("bbox", [])
                    if txt and txt not in excluded_from_bbox_clusters and len(bbox) == 4:
                        h = round(abs(bbox[3] - bbox[1]), 2)
                        if h > 0:
                            filtered_tb.append((txt, h))
            if filtered_tb:
                bbox_levels.clear()
                max_h = max(h for _, h in filtered_tb)
                kapitel_heights = [
                    h for t, h in filtered_tb
                    if re.match(r"^(?:Kapitel|Chapter|Teil|Part)\s+\d+", t, re.IGNORECASE) and h < max_h * 0.9
                ]
                if kapitel_heights:
                    h2_ref = kapitel_heights[0]
                    for txt, h in filtered_tb:
                        if h >= max_h * 0.88:
                            bbox_levels[txt] = 1
                        elif h >= h2_ref * 0.92:
                            bbox_levels[txt] = 2
                        else:
                            bbox_levels[txt] = 3
                else:
                    clusters = cluster_heading_heights([h for _, h in filtered_tb], tol=0.6)
                    for txt, h in filtered_tb:
                        rank = min(range(len(clusters)), key=lambda idx: abs(clusters[idx] - h))
                        bbox_levels[txt] = min(rank + 1, 4)
        except Exception:
            pass

    processed_lines: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            processed_lines.append(line)
            i += 1
            continue

        clean_cand = re.sub(r"^(?:\*\*|__|\*|_)+(.+?)(?:\*\*|__|\*|_)+$", r"\1", stripped).strip()
        if has_ch11:
            clean_cand = re.sub(r"\b(?:II|ii)\.(\d+)", r"11.\1", clean_cand)
            clean_cand = _normalize_allcaps_german_heading(clean_cand)
            clean_cand = re.sub(r"\b([A-ZÄÖÜ][a-zäöü]+us)(ches|chen)\b", r"\1s\2", clean_cand)

        # Normalize OCR misread difficulty icons in 'Aufgabe N ...:' headings and format as '### Aufgabe N ...:'
        # (unless the text after ':' is a full sentence ending with '.', in which case it is a list item '- Aufgabe N: ...')
        m_sq_task = re.match(
            r"^(?:#{1,6}\s+)?(?:\*\*|__)?(Aufgabe\s+\d+[^\w:\n]*:\s*([^\n*]*?))(?:\*\*|__)?$",
            stripped,
            re.IGNORECASE,
        )
        if m_sq_task and not stripped.startswith(("○", "◐", "●", "-")):
            full_task = re.sub(r"[📐⚡☑]", "◩", m_sq_task.group(1).strip())
            after_colon = m_sq_task.group(2).strip()
            if after_colon.endswith(".") and len(after_colon) > 55:
                processed_lines.append(f"- {full_task}")
            else:
                processed_lines.append(f"### {full_task}")
            i += 1
            continue

        # Check if this heading/bold line is a titled callout box
        m_cand_h = re.match(r"^(?:#{1,6}\s+|\*\*)(.+?)(?:\*\*)?$", stripped)
        if m_cand_h:
            cand_title = m_cand_h.group(1).strip()
            if cand_title in excluded_from_bbox_clusters or _DIDACTIC_CALLOUT_BOX_RE.match(cand_title):
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines):
                    sub_l = lines[j].strip()
                    sub_clean = re.sub(r"^[\*_]+|[\*_]+$", "", sub_l).strip()
                    k = j + 1
                    while k < len(lines) and not lines[k].strip():
                        k += 1
                    if (
                        k < len(lines)
                        and 10 <= len(sub_clean) <= 65
                        and not re.match(r"^(?:#|-|\*\s|\||<|\(\()", sub_l)
                        and not sub_clean.endswith((".", "!", "?"))
                        and re.match(r"^[-*•]\s+", lines[k].strip())
                    ):
                        lines[j] = sub_clean if sub_clean.endswith(":") else f"{sub_clean}:"
                if re.match(r"^(?:Fortgeschrittener\s+)?Arbeitsauftrag:?$", cand_title, re.IGNORECASE) and not cand_title.endswith(":"):
                    cand_title = f"{cand_title}:"
                processed_lines.append(f"**{cand_title}**")
                i += 1
                continue

        is_bold_wrapped = (stripped.startswith("**") and stripped.endswith("**")) or (
            stripped.startswith("__") and stripped.endswith("__")
        )
        if (
            not stripped.startswith("#")
            and not stripped.startswith("<")
            and not stripped.startswith("((")
            and not stripped.startswith("-")
            and not stripped.startswith("|")
        ):
            if is_bold_wrapped and len(clean_cand.split()) == 1 and clean_cand.endswith(":"):
                processed_lines.append(clean_cand)
                i += 1
                continue
            if clean_cand in bbox_levels:
                lvl = bbox_levels[clean_cand]
                processed_lines.append(f"{'#' * lvl} {clean_cand}")
                i += 1
                continue
            if (
                is_bold_wrapped
                and clean_cand.endswith(":")
                and 2 <= len(clean_cand.split()) <= 5
                and len(clean_cand) <= 45
                and any(ln.startswith(("## ", "### ")) for ln in processed_lines)
            ):
                processed_lines.append(f"#### {clean_cand}")
                i += 1
                continue
            if (
                re.match(r"^(?:Kapitel|Chapter|Teil|Part|Abschnitt|Section|Module|Modul)\s+\d*[:\.\s]", clean_cand, re.IGNORECASE)
                and len(clean_cand) < 100
            ):
                if not any(ln.startswith("# ") for ln in processed_lines):
                    processed_lines.append(f"# {clean_cand}")
                else:
                    processed_lines.append(f"## {clean_cand}")
                i += 1
                continue
            if re.match(r"^[IVXLCDM]+\.\s+[A-ZÄÖÜ]", clean_cand) and len(clean_cand) < 100:
                processed_lines.append(f"### {clean_cand}")
                i += 1
                continue
            if (
                re.match(
                    r"^(?:Versuch|Experiment|Aufgabe|Übung|Merksatz|Definition|Beispiel|Exkurs)\s*(?:\d+|\:)",
                    clean_cand,
                    re.IGNORECASE,
                )
                and len(clean_cand) < 100
                and not any(c in stripped for c in ["○", "◐", "●", "[leicht]", "[mittel]", "[schwer]"])
                and not _DIDACTIC_CALLOUT_BOX_RE.match(clean_cand)
            ):
                processed_lines.append(f"### {clean_cand}")
                i += 1
                continue
            if (
                is_bold_wrapped
                and 4 <= len(clean_cand) <= 75
                and len(clean_cand.split()) >= 2
                and not clean_cand.endswith((".", ":"))
                and ":" not in clean_cand[:-1]
                and not _DIDACTIC_CALLOUT_BOX_RE.match(clean_cand)
            ):
                processed_lines.append(f"### {clean_cand}")
                i += 1
                continue

        match = re.match(r"^(#+)\s+(.*)$", stripped)
        if match:
            current_hashes = match.group(1)
            title_text = re.sub(r"^(?:\*\*|__|\*|_)+(.+?)(?:\*\*|__|\*|_)+$", r"\1", match.group(2).strip()).strip()
            if has_ch11:
                title_text = re.sub(r"\b(?:II|ii)\.(\d+)", r"11.\1", title_text)
                title_text = _normalize_allcaps_german_heading(title_text)
                title_text = re.sub(r"\b([A-ZÄÖÜ][a-zäöü]+us)(ches|chen)\b", r"\1s\2", title_text)

            # Convert short numbered definition headings (# 1. Term [desc]) into numbered list items
            m_short_num = re.match(r"^(\d+\.\s+[A-ZÄÖÜa-zäöü]+):?(?:\s+(.+))?$", title_text)
            if m_short_num and (
                title_text in body_sized_titles
                or m_short_num.group(2) is not None
                or any(ln.startswith("# ") for ln in processed_lines)
            ):
                term_part = m_short_num.group(1).strip()
                inline_desc = (m_short_num.group(2) or "").strip()
                if inline_desc:
                    processed_lines.append(f"{term_part}: {inline_desc}")
                    i += 1
                    continue
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and not lines[j].strip().startswith(("#", "![", "<", "((", "-", "|")):
                    desc_line = lines[j].strip()
                    processed_lines.append(f"{term_part}: {desc_line}")
                    i = j + 1
                    continue
                processed_lines.append(f"{term_part}:")
                i += 1
                continue

            # Generic H4 sub-label heading (short colon-ending sub-heading inside an active H2/H3 section)
            if (
                title_text.endswith(":")
                and 2 <= len(title_text.split()) <= 5
                and len(title_text) <= 45
                and title_text not in body_sized_titles
                and not re.match(r"^(?:Merksatz|Versuch|Experiment|Aufgabe|Übung|Kapitel)\b", title_text, re.IGNORECASE)
                and any(ln.startswith(("## ", "### ")) for ln in processed_lines)
            ):
                processed_lines.append(f"#### {title_text}")
                i += 1
                continue

            # Demote body-sized or single-word colon introductory labels (e.g. 'Links:', 'Aufgabenstellung...:')
            if (
                title_text.endswith(":")
                and not re.match(r"^(?:Merksatz|Versuch|Experiment|Aufgabe|Übung|Kapitel)\b", title_text, re.IGNORECASE)
                and (title_text in body_sized_titles or len(title_text) > 35 or len(title_text.split()) == 1)
            ):
                processed_lines.append(title_text)
                i += 1
                continue

            # 1. Decimal and hierarchical numbering patterns (ISO/DIN standard):
            # 11.6. -> H2, 1.1 -> H2, 11.6.2 -> H3, 1.1.1.1 -> H4
            num_match = re.match(r"^(\d+(?:\.\d+)+)\.?\s*([A-ZÄÖÜa-zäöü].*)$", title_text)
            if num_match:
                num_str = num_match.group(1).rstrip(".")
                rest_title = num_match.group(2).strip()
                dot_count = num_str.count(".")
                target_level = min(dot_count + 1, 4)
                prefix_num = f"{num_str}." if title_text.startswith(f"{num_str}.") else num_str
                processed_lines.append(f"{'#' * target_level} {prefix_num} {rest_title}")
                i += 1
                continue

            # Roman numerals (I. / II. / III. / IV. / V. -> H3)
            if re.match(r"^[IVXLCDM]+\.\s+", title_text):
                processed_lines.append(f"### {title_text}")
                i += 1
                continue

            # 2. Universal Chapter / Part / Section keywords across languages -> H1 if first heading in doc, else H2
            if re.match(r"^(?:Kapitel|Chapter|Teil|Part|Abschnitt|Section|Module|Modul)\s+\d*[:\.\s]", title_text, re.IGNORECASE):
                if not any(ln.startswith("# ") for ln in processed_lines):
                    processed_lines.append(f"# {title_text}")
                else:
                    processed_lines.append(f"## {title_text}")
                i += 1
                continue

            # 3. Standard didactic educational block keywords -> H3
            if re.match(
                r"^(?:Versuch|Experiment|Aufgabe|Übung|Merksatz|Definition|Beispiel|Exkurs|Tab(?:elle)?\.?\s+\d+)\b",
                title_text,
                re.IGNORECASE,
            ):
                processed_lines.append(f"### {title_text}")
                i += 1
                continue

            # 4. Check if we have bbox font height hierarchy for this exact title
            if title_text in bbox_levels:
                level = bbox_levels[title_text]
                if not any(ln.startswith("# ") for ln in processed_lines):
                    level = 1
                processed_lines.append(f"{'#' * level} {title_text}")
                i += 1
                continue

            # Lettered sections (A. / B. / C. -> H2, A.1 -> H3)
            letter_match = re.match(r"^([A-Z])(?:\.(\d+))?\.\s+", title_text)
            if letter_match:
                level = 3 if letter_match.group(2) else 2
                processed_lines.append(f"{'#' * level} {title_text}")
                i += 1
                continue

            # Top-level single digit decimal (e.g. 1. Einleitung -> H1)
            if re.match(r"^\d+\.\s+", title_text):
                processed_lines.append(f"# {title_text}")
                i += 1
                continue

            # First heading of the document if no H1 exists yet -> H1
            if not any(ln.startswith("# ") for ln in processed_lines):
                processed_lines.append(f"# {title_text}")
                i += 1
                continue

            processed_lines.append(f"{current_hashes} {title_text}")
            i += 1
            continue

        processed_lines.append(line)
        i += 1

    # Prevent noisy scan bbox H4 skips (e.g. H1 -> H4 or H2 -> H4) unless it is an explicit H4 heading
    prev_h_level = 0
    for idx_p, pl in enumerate(processed_lines):
        mh = re.match(r"^(#+)\s+(.*)$", pl)
        if mh:
            lvl = len(mh.group(1))
            htxt = mh.group(2)
            if (
                prev_h_level > 0
                and lvl == 4
                and prev_h_level < 3
                and not re.match(r"^(\d+(?:\.\d+){3})", htxt, re.IGNORECASE)
                and not htxt.endswith(":")
            ):
                lvl = prev_h_level + 1
                processed_lines[idx_p] = f"{'#' * lvl} {htxt}"
            prev_h_level = lvl

    reconstructed = "\n".join(processed_lines)
    try:
        from backend.services.directory_service import (
            apply_directory_heading_levels,
            load_directory_info,
        )

        if directory_info is None and content_list_path:
            cand_dir = os.path.dirname(content_list_path)
            for _ in range(3):
                if not cand_dir:
                    break
                loaded = load_directory_info(cand_dir)
                if loaded:
                    directory_info = loaded
                    break
                cand_dir = os.path.dirname(cand_dir)
        reconstructed, _ = apply_directory_heading_levels(reconstructed, directory_info=directory_info)
    except Exception as e:
        logger.debug(f"Could not apply directory heading levels in reconstruct_title_hierarchy: {e}")

    return reconstructed


def recover_table_truncation(markdown_content: str) -> str:
    """Subtask 3: Table Truncation & Cross-Page Continuity Recovery
    - Extracts table captions ('Tabelle N.M: ...' / 'Tab. N.M: ...') absorbed into row 0 of a pipe table.
    - Unrolls false-positive directory pipe tables (where cells end with leader dots + page numbers or contain directory headings).
    - Merges cross-page continuation tables ('Tabelle X (Teil 1)' + 'Tabelle X (Fortsetzung)').
    - Merges HTML tables split across page boundaries ((num)).
    - Unrolls multi-column numbered definition tables and lettered subtask tables.
    """
    if not markdown_content:
        return markdown_content

    # 0. Extract table captions ('Tabelle N.M: ...' / 'Tab. N.M: ...') absorbed into row 0 of a Markdown pipe table,
    #    or unroll pipe tables that are actually directory sections (Abbildungsverzeichnis / Tabellenverzeichnis / Bildverzeichnis).
    def _process_pipe_table_headers_and_directories(m: re.Match) -> str:
        block = m.group(0).strip()
        raw_rows = [r.strip() for r in block.splitlines() if r.strip()]
        data_rows = []
        for r in raw_rows:
            inner = r.strip("|").strip()
            if re.match(r"^[\s\|:\-]+$", inner):
                continue
            cells = [c.strip() for c in r.strip("|").split("|")]
            data_rows.append((r, cells))

        if not data_rows:
            return m.group(0)

        # Check if this table is a false-positive directory block (contains directory headers, dotted leader entries,
        # or TOC rows where the last column is a page number)
        dir_hdr_re = re.compile(
            r"^(?:Inhaltsverzeichnis|Abbildungsverzeichnis|Tabellenverzeichnis|Bildverzeichnis)$",
            re.IGNORECASE,
        )
        dotted_count = sum(
            1 for _r, cells in data_rows
            if re.search(r"[\.\·…]{3,}\s*\d{1,4}\s*$", " ".join(c for c in cells if c))
            or any(dir_hdr_re.match(c) for c in cells if c)
        )
        trailing_page_num_rows = sum(
            1 for _r, cells in data_rows
            if (
                len([c for c in cells if c]) >= 2
                and re.fullmatch(r"(?:S\.?\s*)?\d{1,3}", [c for c in cells if c][-1])
                and re.search(r"[A-Za-zäöüÄÖÜß]{3,}", " ".join([c for c in cells if c][:-1]))
            )
            or (
                len([c for c in cells if c]) == 1
                and re.search(r"^(?:Kapitel\s+\d+|Abb(?:ildung)?\.?\s*\d+|Tab(?:elle)?\.?\s*\d+|Bild\s*\d+|\d+\.\d+)\b.+\s+\d{1,3}$", [c for c in cells if c][0], re.IGNORECASE)
            )
        )
        max_non_empty_cols = max((len([c for c in cells if c]) for _r, cells in data_rows), default=0)
        if (
            (dotted_count >= 1 and (
                any(dir_hdr_re.match(c) for _r, cells in data_rows for c in cells if c)
                or sum(1 for _r, cells in data_rows if re.search(r"[\.\·…]{3,}\s*\d{1,4}\s*$", " ".join(c for c in cells if c))) >= 2
            ))
            or (trailing_page_num_rows >= 3 and trailing_page_num_rows >= len(data_rows) * 0.45)
            or (max_non_empty_cols == 1 and trailing_page_num_rows >= 2)
        ):
            out_lines = []
            for _r, cells in data_rows:
                non_empty = [c for c in cells if c]
                if not non_empty:
                    continue
                if len(non_empty) == 1 and dir_hdr_re.match(non_empty[0]):
                    out_lines.append(f"\n# {non_empty[0]}\n")
                elif dir_hdr_re.match(non_empty[0]) and len(non_empty) > 1:
                    out_lines.append(f"\n# {non_empty[0]}\n")
                    out_lines.append(f"- {' '.join(non_empty[1:])}")
                else:
                    joined_entry = re.sub(r"\s{2,}(\d{1,3})$", r" \1", " ".join(non_empty))
                    sub_entries = re.split(r"(?<=\.\.\.\s\d{2})\s+(?=(?:Abb\.|Tab\.|Bild|Kapitel|\d+\.\d+)\s)", joined_entry)
                    for se in sub_entries:
                        out_lines.append(f"- {se.strip()}")
            return "\n".join(out_lines).strip() + "\n"

        # Check if this pipe table is actually a multi-column textbook prose layout falsely classified as a table
        # (contains long multi-sentence prose cells >= 200 chars and no 'Tabelle'/'Tab.' header)
        all_non_empty_cells = [c for _r, cells in data_rows for c in cells if c]
        max_cell_len = max((len(c) for c in all_non_empty_cells), default=0)
        total_cell_len = sum(len(c) for c in all_non_empty_cells)
        if max_cell_len >= 200 and total_cell_len >= 450:
            prose_paras = []
            for _r, cells in data_rows:
                for c in cells:
                    if c and not re.fullmatch(r"[\-\s:|]+", c):
                        prose_paras.append(c.strip())
            return "\n\n".join(prose_paras) + "\n\n"

        # Check if row 0 is a table title ('Tabelle N.M: ...' or 'Tab. N.M: ...') absorbed into the pipe table header
        first_non_empty = [c for c in data_rows[0][1] if c]
        if (
            len(data_rows) >= 2
            and first_non_empty
            and re.match(r"^(?:Tabelle|Tab\.)\s+\d+(?:\.\d+)?(?:\s*\([^\)]+\))?\s*:", first_non_empty[0], re.IGNORECASE)
        ):
            caption_title = first_non_empty[0]
            # Check if remaining cells of row 0 were extra caption fragments or empty
            remaining_rows = data_rows[1:]
            max_cols = max(len(cells) for _r, cells in remaining_rows)
            rebuilt = [f"### {caption_title}", ""]
            for r_idx, (_r_orig, cells) in enumerate(remaining_rows):
                padded = cells + [""] * (max_cols - len(cells))
                rebuilt.append("| " + " | ".join(padded) + " |")
                if r_idx == 0:
                    rebuilt.append("| " + " | ".join(["---"] * max_cols) + " |")
            return "\n".join(rebuilt) + "\n"

        return m.group(0)

    markdown_content = re.sub(
        r"(?:^[ \t]*\|[^\n]+\|[ \t]*(?:\n|$)){2,}",
        _process_pipe_table_headers_and_directories,
        markdown_content,
        flags=re.MULTILINE,
    )

    # Ensure standalone plain/bold 'Tabelle N.M: ...' / 'Tab. N.M: ...' lines before a pipe table are formatted as '### ...'
    markdown_content = re.sub(
        r"(?m)^(?:\*\*|__)?((?:Tabelle|Tab\.)\s+\d+(?:\.\d+)?(?:\s*\([^\)]+\))?\s*:[^\n\*_]+)(?:\*\*|__)?[ \t]*$",
        r"### \1",
        markdown_content,
    )

    # 2. Merge cross-page continuation tables:
    # e.g. '### Tabelle 6.1 (Teil 1): Title\n\n| ... |\n...\n((413))\n...\n### Tabelle 6.1 (Fortsetzung): ...\n\n| ... |'
    cont_table_re = re.compile(
        r"(#{1,4}\s+(?:Tabelle|Tab\.)\s+\d+(?:\.\d+)?)\s*\(Teil\s*1\)\s*(:\s*[^\n]+)\n+"
        r"((?:\|[^\n]+\|\n)+)"
        r"([\s\S]*?)"
        r"\n*#{1,4}\s+(?:Tabelle|Tab\.)\s+\d+(?:\.\d+)?\s*\(Fortsetzung\)[^\n]*\n+"
        r"((?:\|[^\n]+\|\n?)+)",
        re.IGNORECASE,
    )

    def _merge_continuation_tables(m: re.Match) -> str:
        hdr_prefix = m.group(1).strip()
        hdr_rest = m.group(2).strip()
        table1_block = m.group(3).rstrip("\n")
        middle_content = m.group(4)
        table2_block = m.group(5).strip()

        t2_lines = [ln.strip() for ln in table2_block.splitlines() if ln.strip()]
        t2_data_rows = []
        for idx_r, r_line in enumerate(t2_lines):
            inner = r_line.strip("|").strip()
            if idx_r == 0 or re.match(r"^[\s\|:\-]+$", inner):
                continue
            t2_data_rows.append(r_line)

        merged_table = table1_block
        if t2_data_rows:
            merged_table += "\n" + "\n".join(t2_data_rows)
        return f"{hdr_prefix}{hdr_rest}\n\n{merged_table}\n{middle_content}"

    markdown_content = cont_table_re.sub(_merge_continuation_tables, markdown_content)

    # 2b. Clean trailing '(Teil 1)' on table headings, standalone '(Fortsetzung von Tabelle ... auf der Folgeseite)' notes,
    #     and duplicate '### Tabelle X.Y (Fortsetzung): ...' headings before split table continuations
    markdown_content = re.sub(
        r"(?m)^(#{1,4}\s+(?:Tabelle|Tab\.)\s+\d+(?:\.\d+)?\s*:[^\n]+?)\s*\(Teil\s*1\)[ \t]*$",
        r"\1",
        markdown_content,
        flags=re.IGNORECASE,
    )
    markdown_content = re.sub(
        r"(?m)^[ \t]*[\*_]*\(Fortsetzung\s+von\s+(?:Tabelle|Tab\.)[^\)\n]+\)[\*_]*[ \t]*\n*",
        "",
        markdown_content,
        flags=re.IGNORECASE,
    )
    markdown_content = re.sub(
        r"(?m)^#{1,4}\s+(?:Tabelle|Tab\.)\s+\d+(?:\.\d+)?\s*\(Fortsetzung\)[^\n]*\n+(?=\|)",
        "",
        markdown_content,
        flags=re.IGNORECASE,
    )

    # 3. Unroll 1-row multi-column numbered definition tables ('| 1. Term Desc | 2. Term Desc | 3. Term Desc |\n| --- | --- | --- |')
    def _unroll_numbered_def_table(m: re.Match) -> str:
        row_line = m.group(1).strip()
        cells = [c.strip() for c in row_line.strip("|").split("|") if c.strip()]
        if len(cells) >= 2 and all(re.match(r"^\*?\*?\d+\.\s+", c) for c in cells):
            out = []
            for c in cells:
                c_clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", c).strip()
                c_clean = re.sub(r"^(\d+\.\s+[A-ZÄÖÜa-zäöü\-]+):?\s+(.+)$", r"\1: \2", c_clean)
                out.append(c_clean)
            return "\n".join(out)
        return m.group(0)

    markdown_content = re.sub(
        r"(?m)^(\|[ \t]*\*?\*?1\.\s+[^\n]+\|)[ \t]*\n\|[ \t:\-\|]+\|[ \t]*$",
        _unroll_numbered_def_table,
        markdown_content,
    )

    # 4. Unroll multi-column lettered subtask pipe tables ('| a) ... | f) ... |\n| --- | --- |\n| b) ... | g) ... |')
    def _unroll_subtask_pipe_table(m: re.Match) -> str:
        block = m.group(0).strip()
        cells = []
        for r in block.splitlines():
            inner = r.strip("|").strip()
            if re.match(r"^[\s\|:\-]+$", inner):
                continue
            for c in r.strip("|").split("|"):
                cs = c.strip()
                if cs:
                    cells.append(cs)
        if len(cells) >= 2 and all(re.match(r"^[a-z]\)\s+", c) for c in cells):
            cells.sort(key=lambda x: x[0].lower())
            cleaned = [re.sub(r"\$(\d+\s*[\+\-\*:]\s*\d+\s*=)\$", r"\1", c) for c in cells]
            return "\n".join(cleaned) + "\n"
        return m.group(0)

    markdown_content = re.sub(
        r"(?:^[ \t]*\|[ \t]*[a-z]\)\s+[^\n]+\|[ \t]*\n)(?:^[ \t]*\|.+?\|[ \t]*(?:\n|$))+",
        _unroll_subtask_pipe_table,
        markdown_content,
        flags=re.MULTILINE,
    )

    # 5. Merge HTML tables split across page breaks: </table>\n\n((46))\n\n<table>
    html_split_pattern = r"</table>\s*\n+(?:(\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\))\s*\n+)?\s*<table\b[^>]*>"

    def merge_html_tables(match):
        page_marker = match.group(1)
        if page_marker:
            return f"<!-- {page_marker} -->"
        return ""

    processed = re.sub(html_split_pattern, merge_html_tables, markdown_content, flags=re.IGNORECASE)
    return processed


def associate_image_captions(markdown_content: str) -> str:
    """Subtask 4: Image-Text & Caption Association
    - Normalizes italicised figure captions (*Abbildung 4.1: ...* -> Abbildung 4.1: ...).
    - Associates standalone ![](images/...) with following OR preceding Abbildung / Figure / Bild captions,
      placing the image with its caption as alt-text directly above the caption line.
    """
    if not markdown_content:
        return markdown_content

    # 0. Unwrap italic/bold markers around standalone figure caption lines (*Abbildung 4.1: ...* -> Abbildung 4.1: ...)
    markdown_content = re.sub(
        r"(?m)^[ \t]*[\*_]{1,2}((?:Abbildung|Abb\.|Figure|Fig\.|Foto|Zeichnung|Diagramm)\s*[0-9IVXiiıIl\.]+[^\n\*_]+?)[\*_]{1,2}[ \t]*$",
        r"\1",
        markdown_content,
        flags=re.IGNORECASE,
    )
    # Ensure a space after figure prefix when OCR glued it to the number ('Abbildung4.1:' -> 'Abbildung 4.1:')
    markdown_content = re.sub(
        r"\b(Abbildung|Abb\.|Figure|Fig\.)(\d)",
        r"\1 \2",
        markdown_content,
        flags=re.IGNORECASE,
    )

    # 1. Handle Caption followed by an image with empty/generic alt-text (as emitted by Docling):
    #    'Abbildung 11.49: ...\n\n![](images/pic0.png)' -> '![Abbildung 11.49: ...](images/pic0.png)\n\nAbbildung 11.49: ...'
    cap_before_img_pattern = re.compile(
        r"(?m)^((?:Abbildung|Abb\.|Figure|Fig\.|Foto|Zeichnung|Diagramm)\s*[0-9IVXiiıIl\.][\d\.a-zA-Z]*[:\s][^\n]+)\s*\n+"
        r"!\[(|image|img|bild|abbildung)\]\((?:images/)?([^)\n]+)\)",
        re.IGNORECASE,
    )

    def _cap_first_repl(match: re.Match) -> str:
        caption_text = match.group(1).strip()
        filename = match.group(3).strip()
        return f"![{caption_text}](images/{filename})\n\n{caption_text}"

    markdown_content = cap_before_img_pattern.sub(_cap_first_repl, markdown_content)

    # 2. Handle Image followed directly by Abbildung / Figure caption:
    img_before_cap_pattern = re.compile(
        r"(!\[(.*?)\]\((?:images/)?([^)\n]+)\))\s*\n+(?:<p>)?\s*((?:Abbildung|Abb\.|Figure|Fig\.|Foto|Zeichnung|Diagramm)\s*[0-9IVXiiıIl\.][\d\.a-zA-Z]*[:\s][^\n]+)",
        re.IGNORECASE,
    )

    def _img_first_repl(match: re.Match) -> str:
        img_tag = match.group(1)
        alt_text = match.group(2).strip()
        filename = match.group(3).strip()
        caption_text = match.group(4).strip()
        if "</p>" in caption_text:
            caption_text = caption_text.replace("</p>", "").strip()

        if not alt_text or alt_text.lower() in ("image", "img", "bild", "figure"):
            return f"![{caption_text}](images/{filename})\n\n{caption_text}"
        return f"{img_tag}\n\n{caption_text}"

    return img_before_cap_pattern.sub(_img_first_repl, markdown_content)


def clean_running_headers_and_footers(markdown_content: str, content_list_path: str | None = None) -> str:
    """Subtask: Running Headers & Footers Cleanup (Kolumnentitel)
    - Strips recurring decorative running headers / footers at the top and bottom of pages.
    - Uses content_list metadata where blocks are classified as 'header' or 'footer' / 'page_header' / 'page_footer'.
    - Also filters repeating identical (or case-insensitive normalized) header lines and alternating
      numbered chapter/section headers right after ((num)) page boundary markers,
      preserving the first occurrence on the starting page if it is the chapter/section opening heading.
    """
    if not markdown_content:
        return markdown_content

    def _strip_page_number(s: str) -> tuple[str, bool]:
        m = re.match(r"^(?:\d{1,4}\s+)?(.*?)(?:\s+\d{1,4})?$", s)
        core = m.group(1) if m else s
        return core, core != s

    def _norm_header(s: str) -> str:
        s = re.sub(r"^#{1,6}\s*", "", s).strip()
        s = re.sub(r"[*_%#]+", " ", s).strip()
        s, _ = _strip_page_number(s)
        s = re.sub(r"\b(?:ii|II)\b", "11", s)
        s = re.sub(r"\s+", " ", s).strip().lower()
        return s

    def _norm_nospace(s: str) -> str:
        return re.sub(r"\s+", "", _norm_header(s))

    header_texts_norm = set()
    header_texts_nospace = set()
    if content_list_path and os.path.exists(content_list_path):
        try:
            with open(content_list_path, encoding="utf-8") as f:
                data = json.load(f)
            blocks = []
            if isinstance(data, dict):
                blocks = data.get("blocks", data.get("content", []))
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, list):
                        blocks.extend(item)
                    else:
                        blocks.append(item)

            for b in blocks:
                if isinstance(b, dict) and b.get("type") in ["header", "footer", "page_header", "page_footer"]:
                    txt = b.get("text", "").strip()
                    nh = _norm_header(txt)
                    if nh and len(nh) > 2:
                        header_texts_norm.add(nh)
                        header_texts_nospace.add(_norm_nospace(txt))
        except Exception:
            pass

    boundary_lines = 2
    image_line = re.compile(r"^(?:!\[|<Bild>|</Bild>|\[Image\]|\[Bild\]|<!--)")
    number_only = re.compile(r"^(?:#{1,6}\s*)?\d{1,4}$")
    numbered_sec_re = re.compile(
        r"^(?:(?:kapitel|chapter|abschnitt)\s+\d+|\d+\.\d+)\b",
        re.IGNORECASE,
    )

    def _candidate_key(line: str) -> tuple[str, bool, bool]:
        """(normalised title without page number, had page number, was heading)."""
        is_heading = bool(re.match(r"^#{1,6}\s", line))
        core = re.sub(r"[*_%#]+", " ", re.sub(r"^#{1,6}\s*", "", line)).strip()
        core, had_number = _strip_page_number(core)
        core = re.sub(r"\b(?:ii|II)\b", "11", core)
        core = re.sub(r"\s+", " ", core).strip().lower()
        return core, had_number, is_heading

    pages = re.split(r"(\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\))", markdown_content)
    segments = [
        i for i in range(len(pages)) if not re.match(r"^\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)$", pages[i])
    ]

    def _boundary_positions(seg: str) -> list[tuple[int, str]]:
        r"""Indices (within seg.split('\n')) of the first/last non-image lines plus their position tag."""
        lines = seg.split("\n")
        content = [i for i, ln in enumerate(lines) if ln.strip() and not image_line.match(ln.strip())]
        result = [(i, "start") for i in content[:boundary_lines]]
        result += [(i, "end") for i in content[-boundary_lines:] if (i, "start") not in result]
        return result

    stats: dict[str, dict[str, Any]] = {}
    for si in segments:
        for idx, pos in _boundary_positions(pages[si]):
            line = pages[si].split("\n")[idx].strip()
            key, had_number, is_heading = _candidate_key(line)
            if len(key) < 3 or len(key) > 80 or not re.search(r"[a-zäöüß]", key):
                continue
            st = stats.setdefault(
                key,
                {
                    "pages": set(),
                    "number": False,
                    "plain": False,
                    "end": False,
                    "numbered_sec": bool(numbered_sec_re.match(key)),
                },
            )
            st["pages"].add(si)
            st["number"] |= had_number
            st["plain"] |= not is_heading
            st["end"] |= pos == "end"

    min_pages = 2 if len(segments) < 6 else 3
    running_keys = {
        key
        for key, st in stats.items()
        # A generic unnumbered heading (e.g. "### Aufgaben") that only ever *starts* pages without a page
        # number is a real section heading. A numbered chapter/section title ("Kapitel 11...", "11.6. ...")
        # cannot genuinely open multiple pages with the exact same number, so its later repetitions are running headers.
        if (len(st["pages"]) >= min_pages and (st["number"] or st["plain"] or st["end"]))
        or (len(st["pages"]) >= 2 and st["numbered_sec"])
    }

    seen_chapter_headers = set()
    kept_chapter_openings: set = set()
    cleaned_pages = []
    current_page_num = None
    for part in pages:
        m_pg = re.match(r"^\(\((\d+|[IVXLCDMivxlcdm]+)\)\)$", part)
        if m_pg:
            current_page_num = m_pg.group(1)
            cleaned_pages.append(part)
            continue
        lines = part.split("\n")
        boundary = _boundary_positions(part)
        boundary_idx = {i for i, _ in boundary}
        content_idx = [i for i, _ in boundary]
        outermost = {min(content_idx), max(content_idx)} if content_idx else set()
        new_lines = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if current_page_num and stripped.lower() == current_page_num.lower():
                continue
            if i in boundary_idx:
                if i in outermost and number_only.match(stripped):
                    continue
                key = _candidate_key(stripped)[0]
                if key in running_keys:
                    if (
                        content_idx
                        and i == min(content_idx)
                        and (re.match(r"^#{1,6}\s", stripped) or numbered_sec_re.match(key))
                        and key not in kept_chapter_openings
                    ):
                        kept_chapter_openings.add(key)
                        if not re.match(r"^#{1,6}\s", stripped) and numbered_sec_re.match(key):
                            lvl = "#" if key.startswith("kapitel") else "##"
                            new_lines.append(f"{lvl} {stripped}")
                        else:
                            new_lines.append(line)
                    continue
            else:
                key, had_number, _ = _candidate_key(stripped)
                if had_number and key in running_keys:
                    continue
            norm_line = _norm_header(stripped)
            norm_ns = _norm_nospace(stripped)
            if norm_line in header_texts_norm or (norm_ns and norm_ns in header_texts_nospace):
                if (
                    content_idx
                    and i == min(content_idx)
                    and numbered_sec_re.match(norm_line)
                    and norm_ns not in seen_chapter_headers
                    and norm_line not in kept_chapter_openings
                ):
                    seen_chapter_headers.add(norm_ns)
                    kept_chapter_openings.add(norm_line)
                    new_lines.append(line)
                continue
            new_lines.append(line)
        cleaned_pages.append("\n".join(new_lines))
    markdown_content = "".join(cleaned_pages)
    markdown_content = re.sub(r"\n{3,}", "\n\n", markdown_content)

    return markdown_content


def apply_extraction_postprocess(
    markdown_content: str,
    content_list_path: str | None = None,
    page_range_str: str | None = None,
    pdf_path: str | None = None,
    directory_info: dict[str, Any] | None = None,
) -> str:
    """Run the complete engine-neutral post-processing pipeline on extracted Markdown.

    1. Text Truncation & De-hyphenation Recovery
    2. Duplicate Itemization & List Marker Cleanup
    3. Running Header & Footer Suppression (Kolumnentitel)
    4. Title Hierarchy Reconstruction (incl. BBox font heights & Table of Contents / Directory alignment)
    5. Table Truncation & Continuity Recovery
    6. Image-Text Caption Association
    7. STEM & Chemistry Formula Standardization ($...$ / $$...$$)
    8. Accurate Page Boundary Marker Injection
    """
    if not markdown_content:
        return markdown_content

    if directory_info is None and pdf_path and os.path.exists(pdf_path) and pdf_path.lower().endswith(".pdf"):
        should_check_dir = ("verzeichnis" in markdown_content.lower() or "table of contents" in markdown_content.lower())
        if not should_check_dir and content_list_path and os.path.exists(content_list_path):
            try:
                with open(content_list_path, encoding="utf-8") as cf:
                    cl_raw = cf.read().lower()
                if "verzeichnis" in cl_raw or "table of contents" in cl_raw:
                    should_check_dir = True
            except Exception:
                pass
        if should_check_dir:
            try:
                from backend.services.directory_service import check_document_directories

                directory_info = check_document_directories(pdf_path, max_pages=20)
            except Exception:
                pass

    result = markdown_content

    # Step 0: Inject page numbers from metadata JSON if not already present so page-boundary
    # running header cleanup and cross-page de-hyphenation operate on accurate ((num)) boundaries.
    if not re.search(r"\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)", result):
        if content_list_path and os.path.exists(content_list_path):
            try:
                from backend.services.extraction_service import insert_page_numbers_from_metadata

                result = insert_page_numbers_from_metadata(
                    result,
                    content_list_path,
                    page_range_str or "",
                    pdf_path=pdf_path,
                    directory_info=directory_info,
                )
            except Exception as e:
                logger.warning(f"Error injecting page numbers in postprocess pipeline: {e}")

    # Step 1: Running headers & footers cleanup BEFORE soft-wrap merging so mid-sentence page breaks
    # interrupted by a running header can be rejoined cleanly.
    result = clean_running_headers_and_footers(result, content_list_path=content_list_path)

    # Step 2: Text truncation & dehyphenation
    result = recover_text_truncation(result, pdf_path=pdf_path)

    # Step 3: Itemization cleanup (removes duplicate - -, - 1., 3. 3., reorders interleaved a)-j) subtasks)
    result = clean_duplicate_itemization(result)

    # Step 4: Table truncation & directory-table recovery (extracts absorbed table titles & directory headers first)
    result = recover_table_truncation(result)

    # Step 5: Heading hierarchy reconstruction
    result = reconstruct_title_hierarchy(
        result, content_list_path=content_list_path, directory_info=directory_info
    )

    # Step 5b: Second pass of table truncation recovery (merges cross-page continuation tables after ### Tabelle headings are normalized)
    result = recover_table_truncation(result)

    # Step 6: Image caption association
    result = associate_image_captions(result)

    # Step 7: Formula standardization
    try:
        from backend.services.formula_service import standardize_formulas

        result = standardize_formulas(result)
    except Exception as e:
        logger.warning(f"Formula standardization error in postprocess pipeline: {e}")

    # Step 8: Inject page numbers from metadata JSON if available
    if content_list_path and os.path.exists(content_list_path):
        try:
            from backend.services.extraction_service import insert_page_numbers_from_metadata

            result = insert_page_numbers_from_metadata(
                result,
                content_list_path,
                page_range_str or "",
                pdf_path=pdf_path,
                directory_info=directory_info,
            )
        except Exception as e:
            logger.warning(f"Error injecting page numbers in postprocess pipeline: {e}")
    elif directory_info and directory_info.get("has_any_directory"):
        try:
            from backend.services.directory_service import apply_directory_page_numbers

            result = apply_directory_page_numbers(result, directory_info=directory_info)
        except Exception as e:
            logger.warning(f"Error applying directory page numbers in postprocess pipeline: {e}")

    try:
        from backend.services.fibs_postprocess import deduplicate_page_numbers

        result = deduplicate_page_numbers(result)
    except Exception as e:
        logger.warning(f"Error deduplicating page numbers in postprocess pipeline: {e}")

    return result
