"""Engine-neutral post-processing and hybrid Docling layout fusion for extracted Markdown."""

import ctypes
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
    trimmed = re.sub(
        r"(?im)^[ \t]*```[ \t]*mermaid\b[\s\S]*?```[ \t]*$",
        "",
        trimmed,
    )
    trimmed = re.sub(
        r"(?im)^[ \t]*mermaid[ \t]+(?:graph|flowchart)[ \t]+(?:TD|TB|BT|RL|LR)\b[\s\S]*?(?=\n[ \t]*\n|\n[ \t]*(?:!\[|#|\(\(|<)|\Z)",
        "",
        trimmed,
    )
    lines = trimmed.splitlines()
    cleaned_lines = [
        line for line in lines
        if not re.match(r"^\s*```(?:markdown|md|html|latex|text|mermaid)?\s*$", line, re.IGNORECASE)
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


def detect_pdf_callout_rects_by_page(
    pdf_path: str,
    pdf_doc: Any = None,
) -> dict[int, list[tuple[float, float, float, float]]]:
    """Detects drawn vector callout box rectangles per page via pypdfium2.

    Args:
        pdf_path: Path to the source PDF file (used when ``pdf_doc`` is None).
        pdf_doc: Optional already-open ``pypdfium2.PdfDocument`` handle to reuse.

    Returns:
        Mapping of 0-based page index to list of ``(left, bottom, right, top)`` rects.
    """
    callout_rects_by_page: dict[int, list[tuple[float, float, float, float]]] = {}
    owns_doc = False
    try:
        import pypdfium2 as pdfium

        if pdf_doc is None:
            pdf_doc = pdfium.PdfDocument(pdf_path)
            owns_doc = True
        for p_i in range(len(pdf_doc)):
            page = pdf_doc[p_i]
            _pw, ph = page.get_size()
            rects = []
            for obj in page.get_objects():
                if obj.type == 2:  # FPDF_PAGEOBJ_PATH
                    l_b, b_b, r_b, t_b = obj.get_bounds()
                    w_b = r_b - l_b
                    h_b = t_b - b_b
                    min_h = 36 if b_b <= 35 else 32
                    if w_b >= 95 and min_h <= h_b <= ph * 0.62 and b_b > 14 and t_b < ph - 35:
                        rects.append((l_b, b_b, r_b, t_b))
            callout_rects_by_page[p_i] = rects
    except Exception:
        pass
    finally:
        if owns_doc and pdf_doc is not None:
            try:
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
    r"|(?:[*_]*)(?:lat\.|griech\.|gr\.|engl\.|frz\.|ital\.)(?:[*_]*)\s+[A-Za-zÄÖÜäöüß\-*_]+"
    r"|(?:[*_]*)[A-Za-zÄÖÜäöüß\-]{3,35}(?:[*_]*)\s*=\s*(?:[*_]*)[A-Za-zÄÖÜäöüß]"
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


_EXPLICIT_CAPTION_PREFIX_RE = re.compile(
    r"^(?:#{1,6}\s+)?(?:!\[[^\]]*\]\([^)]*\)\s*)?(?:<Bild>\s*|\*+|_*)?"
    r"(?:Abbildung|Abb\.|Bild|Grafik|Figure|Fig\.|Foto|Zeichnung|Diagramm|Schema)\s*[0-9IVXiiıIl]+",
    re.IGNORECASE,
)

_TASK_SECTION_HEADING_RE = re.compile(
    r"^#{1,6}\s+.*\b(?:Aufgaben?|Übungen?|Arbeitsaufträge?|Arbeitsauftrag|Kontrollfragen?|Überprüfen|Training)\b",
    re.IGNORECASE,
)

_TASK_IMPERATIVE_SIE_RE = re.compile(
    r"\b(?:Nennen|Erläutern|Beschreiben|Erklären|Begründen|Vergleichen|Stellen|Planen|"
    r"Recherchieren|Werten|Deuten|Ordnen|Berechnen|Bestimmen|Skizzieren|Diskutieren|"
    r"Leiten|Formulieren|Zeichnen|Untersuchen|Überprüfen|Entwickeln|Analysieren|"
    r"Beurteilen|Bewerten|Benennen|Charakterisieren|Fassen|Geben|Nehmen|Prüfen|"
    r"Ermitteln|Lösen|Ergänzen|Markieren|Lesen|Arbeiten|Gestalten|Entscheiden|Ordnen)\s+Sie\b",
    re.IGNORECASE,
)

_TASK_IMPERATIVE_DU_START_RE = re.compile(
    r"^(?:Nenne|Nennt|Erläutere|Erläutert|Beschreibe|Beschreibt|Erkläre|Erklärt|"
    r"Begründe|Begründet|Vergleiche|Vergleicht|Stelle|Stellt|Plane|Plant|"
    r"Recherchiere|Recherchiert|Werte|Wertet|Deute|Deutet|Ordne|Ordnet|"
    r"Berechne|Berechnet|Bestimme|Bestimmt|Skizziere|Skizziert|Diskutiere|Diskutiert|"
    r"Leite|Leitet|Formuliere|Formuliert|Zeichne|Zeichnet|Untersuche|Untersucht|"
    r"Überprüfe|Überprüft|Entwickle|Entwickelt|Analysiere|Analysiert|"
    r"Beurteile|Beurteilt|Bewerte|Bewertet|Benenne|Benennt|Fasse|Fasst|"
    r"Gib|Gebt|Prüfe|Prüft|Ermittle|Ermittelt|Löse|Löst|Ergänze|Ergänzt|"
    r"Markiere|Markiert|Lies|Lest|Bearbeite|Bearbeitet)\b",
)

_FOOTNOTE_OR_TASK_NOUN_RE = re.compile(
    r"(?:^(?:Vgl\.|Siehe\b|Zitiert\s+nach\b|Nach\s+[A-ZÄÖÜ])|"
    r"\b(?:Übungsaufgabe|Kontrollfrage|Teilaufgabe|bezeichnet\s+den|bezeichnet\s+die|bezeichnet\s+das|versteht\s+man)\b)",
    re.IGNORECASE,
)

_PROTECTED_INLINE_SPAN_RE = re.compile(
    r"(\$\$[^$\n]+\$\$|\$[^$\n]+\$|\*\*[^*\n]+\*\*|\*[^*\n]+\*|__[^_\n]+__|_[^_\n]+_|`[^`\n]+`|!?\[[^\]]*\]\([^)\n]*\))"
)


def _is_bare_numbered_caption(
    line: str,
    *,
    has_page_images: bool = True,
    in_task_section: bool = False,
    major_heading_norms: set[str] | None = None,
    has_layout_headings: bool = False,
) -> bool:
    """Checks whether a line is a standalone bare-numbered figure caption (without ``Abb.`` prefix).

    Matches lines such as ``1 Historisches Fernrohr mit Stativ`` or ``### 1 Dosierpumpe``
    when the page contains images, while rejecting H1/H2 section titles, numbered list
    steps (``1. ...``, ``1) ...``), task instructions (imperative operators, ``?``, or
    lines inside ``Aufgaben``/``Übungen`` sections), footnotes, and long prose (> 160 chars).

    Args:
        line: Stripped candidate Markdown line.
        has_page_images: Whether the page has at least one extracted or inline image.
        in_task_section: Whether the line sits inside an ``Aufgaben``/``Übungen`` section.
        major_heading_norms: Optional normalized non-body-sized section headings on the page.
        has_layout_headings: Whether PDF/Docling layout headings were inspected for the page.

    Returns:
        True if the line represents a bare-numbered figure caption.
    """
    if not has_page_images or in_task_section:
        return False
    s = (line or "").strip()
    if not s or len(s) > 160 or s.endswith("?") or s.endswith("!"):
        return False
    # H1 / H2 headings ('# 1 ...', '## 1 ...') are chapter/section headings unless PDF layout proves otherwise
    if re.match(r"^#{1,2}\s+", s) and not has_layout_headings:
        return False
    unwrapped = re.sub(r"^#{1,6}\s+", "", s).strip()
    unwrapped = re.sub(r"^(?:\*\*|__|\*|_)(.+?)(?:\*\*|__|\*|_)$", r"\1", unwrapped).strip()
    if len(unwrapped) > 160 or unwrapped.endswith("?") or unwrapped.endswith("!"):
        return False

    # Require bare integer 1..39 (optional letter a-d), NOT followed by '.', ')', ':', '-', or decimal '.1'
    m = re.match(r"^([1-9]|[1-3]\d)([a-d])?\s+([A-ZÄÖÜ][^\n]+)$", unwrapped)
    if not m:
        return False
    rest = m.group(3).strip()
    if len(rest) < 3:
        return False
    if re.match(r"^(?:Kapitel|Chapter|Abschnitt|Teil|Band|Seite|Page|Aufgabe|Übung|Material|Tab(?:elle)?\.?)\b", rest, re.IGNORECASE):
        return False
    if _TASK_IMPERATIVE_SIE_RE.search(rest) or _TASK_IMPERATIVE_DU_START_RE.match(rest):
        return False
    if _FOOTNOTE_OR_TASK_NOUN_RE.search(rest):
        return False
    if major_heading_norms:
        norm_u = re.sub(r"\W+", " ", unwrapped).strip().lower()
        norm_rest = re.sub(r"\W+", " ", rest).strip().lower()
        if norm_u in major_heading_norms or norm_rest in major_heading_norms:
            return False
    return True


def _is_figure_caption_line(
    line: str,
    *,
    has_page_images: bool = True,
    in_task_section: bool = False,
    major_heading_norms: set[str] | None = None,
    has_layout_headings: bool = False,
) -> bool:
    """Checks whether a line is an explicit or bare-numbered figure caption.

    Args:
        line: Candidate line string.
        has_page_images: Whether the page contains images.
        in_task_section: Whether the line is under a task heading.
        major_heading_norms: Optional normalized major section headings on the page.
        has_layout_headings: Whether PDF/Docling layout headings were inspected for the page.

    Returns:
        True if the line is an explicit ``Abb.``/``Abbildung`` caption or a valid bare-numbered caption.
    """
    s = (line or "").strip()
    if not s:
        return False
    if _EXPLICIT_CAPTION_PREFIX_RE.match(s):
        return True
    return _is_bare_numbered_caption(
        s,
        has_page_images=has_page_images,
        in_task_section=in_task_section,
        major_heading_norms=major_heading_norms,
        has_layout_headings=has_layout_headings,
    )


def _sort_blocks_in_reading_order(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sorts page text blocks in column-aware reading order using ``bbox_1000``.

    Full-width spanning headings/banners divide the page into vertical bands; within each
    band, horizontally disjoint columns are ordered left-to-right and top-to-bottom.
    Blocks lacking ``bbox_1000`` preserve their relative order (with marginalia/glossary
    notes without coordinates placed at the end).

    Args:
        blocks: List of block dictionaries on a single page.

    Returns:
        New list of block dictionaries ordered in natural reading order.
    """
    if len(blocks) <= 1:
        return list(blocks)

    with_coords: list[tuple[int, dict[str, Any], tuple[float, float, float, float]]] = []
    without_coords_top: list[tuple[int, dict[str, Any]]] = []
    without_coords_tail: list[tuple[int, dict[str, Any]]] = []

    for idx, b in enumerate(blocks):
        box = b.get("bbox_1000") or b.get("bbox")
        # Ignore synthetic [0, 0, w, single_h] heading boxes that carry only width/height
        rect = _extract_rect_coords(box) if box is not None else None
        if rect is not None and not (rect[0] == 0.0 and rect[1] == 0.0 and b.get("bbox_1000") is None):
            with_coords.append((idx, b, rect))
        else:
            txt = str(b.get("text") or "")
            if _is_marginalia_or_glossary_note(txt):
                without_coords_tail.append((idx, b))
            else:
                without_coords_top.append((idx, b))

    if len(with_coords) <= 1:
        return [b for _, b in without_coords_top] + [b for _, b, _ in with_coords] + [b for _, b in without_coords_tail]

    def _is_spanning(r: tuple[float, float, float, float]) -> bool:
        return (r[2] - r[0]) >= 520.0 or (r[0] < 360.0 and r[2] > 640.0)

    def _sort_band(band_items: list[tuple[int, dict[str, Any], tuple[float, float, float, float]]]) -> list[dict[str, Any]]:
        if len(band_items) <= 1:
            return [item[1] for item in band_items]
        # Connected-components clustering by horizontal interval overlap
        n = len(band_items)
        parent = list(range(n))

        def _find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for i in range(n):
            ix0, _iy0, ix1, _iy1 = band_items[i][2]
            iw = max(1.0, ix1 - ix0)
            for j in range(i + 1, n):
                jx0, _jy0, jx1, _jy1 = band_items[j][2]
                jw = max(1.0, jx1 - jx0)
                overlap_x = min(ix1, jx1) - max(ix0, jx0)
                if overlap_x > 0.25 * min(iw, jw):
                    ri, rj = _find(i), _find(j)
                    if ri != rj:
                        parent[rj] = ri

        clusters: dict[int, list[tuple[int, dict[str, Any], tuple[float, float, float, float]]]] = {}
        for i in range(n):
            clusters.setdefault(_find(i), []).append(band_items[i])

        ordered_clusters = sorted(
            clusters.values(),
            key=lambda cl: (min(it[2][0] for it in cl), min(it[2][1] for it in cl)),
        )
        out: list[dict[str, Any]] = []
        for cl in ordered_clusters:
            cl_sorted = sorted(cl, key=lambda it: (it[2][1], it[2][0], it[0]))
            out.extend(it[1] for it in cl_sorted)
        return out

    spanning = sorted([it for it in with_coords if _is_spanning(it[2])], key=lambda it: (it[2][1], it[2][0], it[0]))
    non_spanning = [it for it in with_coords if not _is_spanning(it[2])]

    if not spanning:
        ordered_coords = _sort_band(non_spanning)
    else:
        ordered_coords = []
        remaining = list(non_spanning)
        for sp in spanning:
            sp_y_mid = (sp[2][1] + sp[2][3]) / 2.0
            above = [it for it in remaining if (it[2][1] + it[2][3]) / 2.0 < sp_y_mid - 8.0]
            remaining = [it for it in remaining if (it[2][1] + it[2][3]) / 2.0 >= sp_y_mid - 8.0]
            if above:
                ordered_coords.extend(_sort_band(above))
            ordered_coords.append(sp[1])
        if remaining:
            ordered_coords.extend(_sort_band(remaining))

    return [b for _, b in without_coords_top] + ordered_coords + [b for _, b in without_coords_tail]


def normalize_split_decimal_headings(markdown_text: str) -> str:
    """Normalizes 2-line PDF section headings where a decimal number sits mid-title.

    Rewrites headings such as ``## Grundlagen 2.1 im Überblick`` into
    ``## 2.1 Grundlagen im Überblick`` while preserving label prefixes (e.g. ``Abbildung 4.1``),
    and drops an immediately preceding unnumbered duplicate heading on the same page.

    Args:
        markdown_text: Input Markdown text.

    Returns:
        Markdown text with split decimal section headings normalized and deduplicated.
    """
    if not markdown_text:
        return markdown_text

    lines = markdown_text.split("\n")
    norm_lines: list[str] = []
    for raw_ln in lines:
        s_ln = raw_ln.strip()
        m_sp = fc.SPLIT_DECIMAL_HEADING_RE.match(s_ln)
        if m_sp:
            hashes_sp = m_sp.group(1)
            prefix_sp = m_sp.group(2).strip()
            num_sp = re.sub(r"\s*\.\s*", ".", m_sp.group(3).strip())
            suffix_sp = m_sp.group(4).strip()
            maj_s, sub_s = num_sp.rstrip(".").split(".", 1)
            if (
                not fc.SPLIT_HEADING_EXCLUDED_PREFIX_RE.match(prefix_sp)
                and int(maj_s) <= 40
                and int(sub_s) <= 40
                and not re.match(r"^(?:°|%|cm\b|mm\b|km\b|kg\b|ms\b|mol\b|Hz\b)", suffix_sp)
            ):
                raw_ln = f"{hashes_sp}{num_sp} {prefix_sp} {suffix_sp}"
                s_ln = raw_ln.strip()

        m_dec = re.match(r"^(#{1,4})\s+([1-9]\d?\.[1-9]\d?\.?)\s+([A-ZÄÖÜa-zäöüß].+)$", s_ln)
        if m_dec and norm_lines:
            cur_hashes, cur_num, cur_title = m_dec.group(1), m_dec.group(2), m_dec.group(3)
            cur_title_norm = re.sub(r"\W+", " ", cur_title).strip().lower()
            if len(cur_title_norm) >= 5:
                prev_idx = len(norm_lines) - 1
                while prev_idx >= 0 and not norm_lines[prev_idx].strip():
                    prev_idx -= 1
                if prev_idx >= 0:
                    prev_s = norm_lines[prev_idx].strip()
                    m_prev_h = re.match(r"^#{1,4}\s+([^\d#\n][^\n]*)$", prev_s)
                    if m_prev_h:
                        prev_title_norm = re.sub(r"\W+", " ", m_prev_h.group(1)).strip().lower()
                        if prev_title_norm == cur_title_norm:
                            del norm_lines[prev_idx:]
                    else:
                        m_prev_dec = re.match(
                            r"^(#{1,4})\s+([1-9]\d?\.[1-9]\d?\.?)\s+([A-ZÄÖÜa-zäöüß].+)$",
                            prev_s,
                        )
                        if m_prev_dec and m_prev_dec.group(2).rstrip(".") == cur_num.rstrip("."):
                            prev_dec_norm = re.sub(r"\W+", " ", m_prev_dec.group(3)).strip().lower()
                            if prev_dec_norm == cur_title_norm:
                                best_h = (
                                    m_prev_dec.group(1)
                                    if len(m_prev_dec.group(1)) <= len(cur_hashes)
                                    else cur_hashes
                                )
                                del norm_lines[prev_idx:]
                                raw_ln = f"{best_h} {cur_num} {cur_title}"

        norm_lines.append(raw_ln)

    return "\n".join(norm_lines)


def _detect_page_3dot_task_difficulties(
    page: Any,
    textpage: Any,
    pw: float,
    ph: float,
    bx0: float,
    by0: float,
    rotation: int,
    pdfium_c: Any,
) -> list[dict[str, Any]]:
    """Detects horizontal 3-dot vector task difficulty indicators on a single PDF page.

    Applies a strict zero-overhead guard: ``page.render(scale=2.0)`` is invoked only
    when at least one collinear triplet of 3 equal-sized small square/circle paths
    exists above ``y = 20 pt``. Filters out diagram-interior particle circles without
    adjacent task prose/bullets and sorts indicators in 2-column reading order.

    Args:
        page: Open ``pypdfium2.PdfPage`` handle.
        textpage: Open ``pypdfium2.PdfTextPage`` handle.
        pw: Page width in PDF points.
        ph: Page height in PDF points.
        bx0: Page bounding box left origin in PDF points.
        by0: Page bounding box bottom origin in PDF points.
        rotation: Page rotation in degrees.
        pdfium_c: ``pypdfium2.raw`` C bindings module.

    Returns:
        Reading-order list of ``{"points": 1|2|3, "anchor": str, "y_1000": float}`` dicts.
    """
    raw_dots: list[tuple[float, float, float, float, float, float, float, float]] = []
    try:
        path_objs = page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_PATH], max_depth=3)
        for obj in path_objs:
            try:
                l_b, b_b, r_b, t_b = (float(v) for v in obj.get_bounds())
            except Exception:
                continue
            w_b = r_b - l_b
            h_b = t_b - b_b
            if (
                2.5 <= w_b <= 6.8
                and 2.5 <= h_b <= 6.8
                and abs(w_b - h_b) <= 1.8
                and (b_b - by0) > 20.0
            ):
                raw_dots.append(
                    (l_b, b_b, r_b, t_b, (l_b + r_b) / 2.0, (b_b + t_b) / 2.0, w_b, h_b)
                )
    except Exception:
        return []

    if len(raw_dots) < 3:
        return []

    # Deduplicate concentric / fill+stroke path pairs belonging to the same dot
    raw_dots.sort(key=lambda d: (round(d[5], 1), d[4]))
    dedup_dots: list[tuple[float, float, float, float, float, float, float, float]] = []
    for d in raw_dots:
        merged = False
        for idx_d in range(len(dedup_dots) - 1, -1, -1):
            ed = dedup_dots[idx_d]
            if abs(d[5] - ed[5]) > 1.8:
                break
            if abs(d[4] - ed[4]) < 2.0 and abs(d[5] - ed[5]) <= 1.2:
                nl, nb = min(d[0], ed[0]), min(d[1], ed[1])
                nr, nt = max(d[2], ed[2]), max(d[3], ed[3])
                nw, nh = nr - nl, nt - nb
                if nw <= 6.8 and nh <= 6.8:
                    dedup_dots[idx_d] = (
                        nl,
                        nb,
                        nr,
                        nt,
                        (nl + nr) / 2.0,
                        (nb + nt) / 2.0,
                        nw,
                        nh,
                    )
                merged = True
                break
        if not merged:
            dedup_dots.append(d)

    if len(dedup_dots) < 3:
        return []

    # Cluster horizontal rows (|dy| <= 1.2 pt) and extract exact-length-3 equidistant runs
    used = [False] * len(dedup_dots)
    candidate_triplets: list[
        tuple[
            tuple[float, float, float, float, float, float, float, float],
            tuple[float, float, float, float, float, float, float, float],
            tuple[float, float, float, float, float, float, float, float],
        ]
    ] = []
    for i_d, seed in enumerate(dedup_dots):
        if used[i_d]:
            continue
        row = [seed]
        used[i_d] = True
        for j_d in range(i_d + 1, len(dedup_dots)):
            if not used[j_d] and abs(dedup_dots[j_d][5] - seed[5]) <= 1.2:
                row.append(dedup_dots[j_d])
                used[j_d] = True
        if len(row) < 3:
            continue
        row.sort(key=lambda item: item[4])
        runs: list[list[tuple[float, float, float, float, float, float, float, float]]] = [[row[0]]]
        for nxt_d in row[1:]:
            prev_d = runs[-1][-1]
            dx_center = nxt_d[4] - prev_d[4]
            dx_gap = nxt_d[0] - prev_d[2]
            size_ok = abs(nxt_d[6] - prev_d[6]) <= 1.5 and abs(nxt_d[7] - prev_d[7]) <= 1.5
            step_ok = dx_gap >= 0.4 and (
                2.8 <= dx_center <= 8.5 or (2.8 <= dx_gap <= 8.5 and dx_center <= 13.5)
            )
            if size_ok and step_ok:
                runs[-1].append(nxt_d)
            else:
                runs.append([nxt_d])
        for run in runs:
            if len(run) == 3:
                step1 = run[1][4] - run[0][4]
                step2 = run[2][4] - run[1][4]
                if abs(step2 - step1) <= 2.2:
                    candidate_triplets.append((run[0], run[1], run[2]))

    if not candidate_triplets:
        return []

    try:
        pil_img = page.render(scale=2.0).to_pil().convert("RGB")
    except Exception:
        return []

    img_w, img_h = pil_img.size
    if img_w <= 0 or img_h <= 0:
        return []

    found_difficulties: list[tuple[int, float, float, dict[str, Any]]] = []
    for trip in candidate_triplets:
        states: list[bool] = []
        ambiguous = False
        for d in trip:
            cx_pt = d[4] - bx0
            cy_pt = d[5] - by0
            if rotation == 90:
                cx_r, cy_r = cy_pt, ph - cx_pt
            elif rotation == 180:
                cx_r, cy_r = pw - cx_pt, ph - cy_pt
            elif rotation == 270:
                cx_r, cy_r = pw - cy_pt, cx_pt
            else:
                cx_r, cy_r = cx_pt, cy_pt
            px_x = max(0, min(img_w - 1, int(round((cx_r / pw) * img_w))))
            px_y = max(0, min(img_h - 1, int(round(((ph - cy_r) / ph) * img_h))))
            r_v, g_v, b_v = pil_img.getpixel((px_x, px_y))
            lum = 0.299 * r_v + 0.587 * g_v + 0.114 * b_v
            if lum < 195.0:
                states.append(True)
            elif lum >= 205.0:
                states.append(False)
            else:
                ambiguous = True
                break
        if ambiguous or states not in (
            [True, False, False],
            [True, True, False],
            [True, True, True],
        ):
            continue

        n_filled = sum(1 for st in states if st)
        x0 = trip[0][0]
        x2 = trip[2][2]
        y0 = min(d[1] for d in trip)
        y1 = max(d[3] for d in trip)

        # Detect 2-column right-column placement via empty center gutter + right-side text
        col_idx = 0
        col_left_clamp = 0.0
        if x0 > bx0 + pw * 0.48:
            gutter_w = max(8.0, pw * 0.02)
            for frac in (0.44, 0.46, 0.48, 0.50, 0.52, 0.54):
                gx0 = bx0 + pw * frac
                gx1 = gx0 + gutter_w
                if gx1 >= x0 - 12.0:
                    break
                try:
                    g_txt = textpage.get_text_bounded(
                        gx0, max(0.0, y0 - 3.0), gx1, y1 + 3.0
                    ).strip()
                    r_txt = textpage.get_text_bounded(
                        gx1, max(0.0, y0 - 4.0), max(gx1, x0 - 1.5), y1 + 4.0
                    ).strip()
                except Exception:
                    g_txt, r_txt = "x", ""
                if not g_txt and r_txt:
                    col_idx = 1
                    col_left_clamp = gx1
                    break

        snippet = ""
        try:
            snippet = " ".join(
                textpage.get_text_bounded(
                    max(col_left_clamp, x0 - 45.0), max(0.0, y0 - 5.0), x2 + 10.0, y1 + 5.0
                ).split()
            )
            if len(re.sub(r"[•●○◦∙⋅\s]+", "", snippet)) < 2:
                snippet = " ".join(
                    textpage.get_text_bounded(
                        max(col_left_clamp, x0 - 160.0),
                        max(0.0, y0 - 5.0),
                        x2 + 10.0,
                        y1 + 5.0,
                    ).split()
                )
        except Exception:
            snippet = ""

        has_bullets = bool(fc.DOT_BULLET_RUN_RE.search(snippet))
        clean_snip = re.sub(r"[•●○◦∙⋅\s]+", " ", snippet).strip()
        alpha_words_3 = re.findall(r"[A-Za-zÄÖÜäöüß]{3,}", clean_snip)
        ends_punct = clean_snip.endswith((".", "?", "!", ":"))
        has_prose_anchor = len(alpha_words_3) >= 2 or (
            ends_punct
            and len(re.findall(r"[A-Za-zÄÖÜäöüß]{2,}", clean_snip)) >= 1
            and not re.fullmatch(r"(?:ca|vgl|bzw|Abb|Fig|Tab)\.", clean_snip, re.IGNORECASE)
        )
        if not has_bullets and not has_prose_anchor:
            continue

        y_1000 = round(((ph - (((y0 + y1) / 2.0) - by0)) / ph) * 1000.0, 1)
        x_1000 = round(((x0 - bx0) / pw) * 1000.0, 1)
        found_difficulties.append(
            (
                col_idx,
                y_1000,
                x_1000,
                {"points": n_filled, "anchor": snippet, "y_1000": y_1000},
            )
        )

    found_difficulties.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in found_difficulties]


def extract_pdf_page_details(
    pdf_path_or_doc: Any,
    figure_bboxes_by_page: dict[int, list[list[int]]] | None = None,
    table_bboxes_by_page: dict[int, list[list[int]]] | None = None,
    callout_rects_by_page: dict[int, list[tuple[float, float, float, float]]] | None = None,
) -> dict[str, dict[int, list[Any]]]:
    """Extracts born-digital PDF text blocks, inline font spans, furniture, in-figure labels, and 3-dot task difficulties.

    Uses a single ``pypdfium2.PdfDocument`` handle and ``FPDFText_GetFontInfo`` /
    ``FPDFText_GetFontWeight`` to capture ``Bold``/``SemiBold`` and ``Italic``/``Oblique``
    spans (excluding headings and whole-paragraph italic intro blocks of >= 15 words
    immediately under a heading or >= 25 words elsewhere), separate in-figure text inside
    ``figure_bboxes_by_page``, detect 3-dot vector task difficulty indicators, and build
    clean reading-order PDF text blocks with ``bbox_1000``.

    Args:
        pdf_path_or_doc: Path to a PDF file or an already-open ``pypdfium2.PdfDocument``.
        figure_bboxes_by_page: Optional per-page list of normalized ``0..1000`` figure bboxes.
        table_bboxes_by_page: Optional per-page list of normalized ``0..1000`` table bboxes.
        callout_rects_by_page: Optional per-page list of raw PDF vector callout rects.

    Returns:
        Dictionary with keys ``font_spans_by_page``, ``figure_texts_by_page``,
        ``pdf_blocks_by_page``, ``furniture_by_page``, and ``task_difficulties_by_page``.
    """
    details: dict[str, dict[int, list[Any]]] = {
        "font_spans_by_page": {},
        "figure_texts_by_page": {},
        "pdf_blocks_by_page": {},
        "furniture_by_page": {},
        "task_difficulties_by_page": {},
    }
    if pdf_path_or_doc is None:
        return details

    owns_doc = False
    pdf_doc = None
    try:
        import pypdfium2 as pdfium
        import pypdfium2.raw as pdfium_c

        if isinstance(pdf_path_or_doc, (str, os.PathLike)):
            path_str = str(pdf_path_or_doc)
            if not os.path.exists(path_str) or not path_str.lower().endswith(".pdf"):
                return details
            pdf_doc = pdfium.PdfDocument(path_str)
            owns_doc = True
        else:
            pdf_doc = pdf_path_or_doc

        buf = ctypes.create_string_buffer(256)
        buf_ptr = ctypes.cast(buf, ctypes.c_void_p)
        flags_c = ctypes.c_int(0)
        l_c = ctypes.c_double()
        r_c = ctypes.c_double()
        b_c = ctypes.c_double()
        t_c = ctypes.c_double()
        ox_c = ctypes.c_double()
        oy_c = ctypes.c_double()
        font_style_cache: dict[tuple[bytes, int, int], tuple[bool, bool]] = {}

        bold_name_re = re.compile(
            r"(?:semi|demi|extra|ultra)?bold|demi(?![a-z])|heavy|black|(?:[-,_])(?:bd|sb|bf)(?:it|ita|ital|ob|obl)?$"
        )
        italic_name_re = re.compile(
            r"italic|oblique|kursiv|slanted|(?:[-,_]|bold|semibold|demibold|medium|regular|light|roman)(?:it|ita|ital|ob|obl)$"
        )

        fig_map = figure_bboxes_by_page or {}
        tbl_map = table_bboxes_by_page or {}
        callout_map = (
            callout_rects_by_page
            if callout_rects_by_page is not None
            else detect_pdf_callout_rects_by_page("", pdf_doc=pdf_doc)
        )

        for p_idx in range(len(pdf_doc)):
            page = pdf_doc[p_idx]
            pw, ph = page.get_size()
            if pw <= 0 or ph <= 0:
                continue
            rotation = page.get_rotation()
            bx0, by0 = page.get_bbox()[:2]
            textpage = page.get_textpage()
            try:
                page_diffs = _detect_page_3dot_task_difficulties(
                    page, textpage, pw, ph, bx0, by0, rotation, pdfium_c
                )
                if page_diffs:
                    details["task_difficulties_by_page"][p_idx] = page_diffs

                n_chars = textpage.count_chars()
                if n_chars <= 0:
                    continue

                raw_lines: list[dict[str, Any]] = []
                cur_chars: list[tuple[str, tuple[float, float, float, float] | None, float, bool, bool]] = []
                prev_baseline_1000: float | None = None
                prev_nx1: float | None = None

                def _flush_line() -> None:
                    nonlocal cur_chars, prev_baseline_1000, prev_nx1
                    if not cur_chars:
                        return
                    raw_str = "".join(c[0] for c in cur_chars)
                    clean_str = (
                        raw_str.encode("utf-16-le", "surrogatepass")
                        .decode("utf-16-le", "ignore")
                        .strip()
                    )
                    boxes = [c[1] for c in cur_chars if c[1] is not None]
                    fsizes = [c[2] for c in cur_chars if c[2] > 0 and not c[0].isspace()]
                    if clean_str and boxes:
                        lx0 = min(b[0] for b in boxes)
                        ly0 = min(b[1] for b in boxes)
                        lx1 = max(b[2] for b in boxes)
                        ly1 = max(b[3] for b in boxes)
                        raw_lines.append({
                            "text": clean_str,
                            "chars": list(cur_chars),
                            "bbox_1000": [
                                max(0, min(1000, int(round(lx0)))),
                                max(0, min(1000, int(round(ly0)))),
                                max(0, min(1000, int(round(lx1)))),
                                max(0, min(1000, int(round(ly1)))),
                            ],
                            "fsize": statistics.median(fsizes) if fsizes else 0.0,
                        })
                    cur_chars = []
                    prev_baseline_1000 = None
                    prev_nx1 = None

                for ci in range(n_chars):
                    unit = pdfium_c.FPDFText_GetUnicode(textpage.raw, ci)
                    if unit == 0:
                        continue
                    if unit in (0x0D, 0x0A):
                        _flush_line()
                        continue
                    if unit in (0x02, 0xFFFE):
                        ch = "-"
                    elif unit == 0x00AD:
                        ch = "\u00ad"
                    elif unit in (0x13, 0x16):
                        ch = "ff"
                    elif unit == 0x14:
                        ch = "fi"
                    elif unit == 0x15:
                        ch = "fl"
                    else:
                        ch = chr(unit)

                    ok_box = pdfium_c.FPDFText_GetCharBox(textpage.raw, ci, l_c, r_c, b_c, t_c)
                    ok_orig = pdfium_c.FPDFText_GetCharOrigin(textpage.raw, ci, ox_c, oy_c)
                    c_box: tuple[float, float, float, float] | None = None
                    if ok_box and r_c.value > l_c.value and t_c.value > b_c.value:
                        x0 = min(l_c.value, r_c.value) - bx0
                        y0 = min(b_c.value, t_c.value) - by0
                        x1 = max(l_c.value, r_c.value) - bx0
                        y1 = max(b_c.value, t_c.value) - by0
                        orig_x = ox_c.value - bx0 if ok_orig else x0
                        orig_y = oy_c.value - by0 if ok_orig else y0
                        if rotation == 90:
                            x0, y0, x1, y1 = y0, ph - x1, y1, ph - x0
                            orig_x, orig_y = orig_y, ph - orig_x
                        elif rotation == 180:
                            x0, y0, x1, y1 = pw - x1, ph - y1, pw - x0, ph - y0
                            orig_x, orig_y = pw - orig_x, ph - orig_y
                        elif rotation == 270:
                            x0, y0, x1, y1 = pw - y1, x0, pw - y0, x1
                            orig_x, orig_y = pw - orig_y, orig_x
                        nx0 = (x0 / pw) * 1000.0
                        nx1 = (x1 / pw) * 1000.0
                        ny0 = ((ph - y1) / ph) * 1000.0
                        ny1 = ((ph - y0) / ph) * 1000.0
                        if nx1 <= 1.0 or nx0 >= 999.0 or ny1 <= 1.0 or ny0 >= 999.0:
                            _flush_line()
                            continue
                        baseline_1000 = ((ph - orig_y) / ph) * 1000.0
                        c_box = (nx0, ny0, nx1, ny1)

                        ch_h = max(6.0, ny1 - ny0)
                        if prev_baseline_1000 is not None and abs(baseline_1000 - prev_baseline_1000) > max(4.5, ch_h * 0.65):
                            _flush_line()
                        elif prev_nx1 is not None and nx0 < prev_nx1 - 80.0:
                            _flush_line()
                        prev_baseline_1000 = baseline_1000
                        prev_nx1 = nx1

                    if ch.isspace():
                        cur_chars.append((" ", c_box, 0.0, False, False))
                        continue

                    flags_c.value = 0
                    nb = pdfium_c.FPDFText_GetFontInfo(textpage.raw, ci, buf_ptr, 256, ctypes.byref(flags_c))
                    raw_fn = buf.value if nb > 0 else b""
                    weight = pdfium_c.FPDFText_GetFontWeight(textpage.raw, ci)
                    fsize = float(pdfium_c.FPDFText_GetFontSize(textpage.raw, ci))
                    cache_k = (raw_fn, flags_c.value, weight)
                    style_pair = font_style_cache.get(cache_k)
                    if style_pair is None:
                        fn_clean = re.sub(r"^[A-Z]{6}\+", "", raw_fn.decode("utf-8", errors="ignore")).lower()
                        is_b = bool(
                            weight >= 600
                            or (flags_c.value & 0x40000)
                            or bold_name_re.search(fn_clean)
                        )
                        is_i = bool(
                            (flags_c.value & 0x40)
                            or italic_name_re.search(fn_clean)
                        )
                        style_pair = (is_b, is_i)
                        font_style_cache[cache_k] = style_pair

                    cur_chars.append((ch, c_box, fsize, style_pair[0], style_pair[1]))

                _flush_line()
            finally:
                textpage.close()

            if not raw_lines:
                continue

            page_figs = fig_map.get(p_idx, [])
            page_tbls = tbl_map.get(p_idx, [])
            page_callouts_1000: list[list[int]] = [
                [
                    max(0, min(1000, int(round(((rl - bx0) / pw) * 1000.0)))),
                    max(0, min(1000, int(round(((ph - (rt - by0)) / ph) * 1000.0)))),
                    max(0, min(1000, int(round(((rr - bx0) / pw) * 1000.0)))),
                    max(0, min(1000, int(round(((ph - (rb - by0)) / ph) * 1000.0)))),
                ]
                for rl, rb, rr, rt in callout_map.get(p_idx, [])
                if rr > rl and rt > rb
            ]

            # Rescue figure_bboxes that actually crop a colored didactic/Steckbrief callout box
            callout_fig_rects: list[tuple[float, float, float, float]] = []
            for fb in page_figs:
                fb_rect = _extract_rect_coords(fb)
                if fb_rect is None:
                    continue
                fig_lns = [
                    ln_e["text"]
                    for ln_e in raw_lines
                    if _bbox_overlap_ratio(ln_e["bbox_1000"], fb_rect) >= 0.55
                    or (
                        fb_rect[0] <= (ln_e["bbox_1000"][0] + ln_e["bbox_1000"][2]) / 2.0 <= fb_rect[2]
                        and fb_rect[1] <= (ln_e["bbox_1000"][1] + ln_e["bbox_1000"][3]) / 2.0 <= fb_rect[3]
                    )
                ]
                has_didactic_hdr = any(fc.DIDACTIC_BOX_HEADER_RE.match(t) for t in fig_lns)
                fig_word_cnt = sum(len(t.split()) for t in fig_lns)
                if has_didactic_hdr and fig_word_cnt >= 25:
                    callout_fig_rects.append(fb_rect)

            body_lines: list[dict[str, Any]] = []
            page_has_top_rubric_badge = any(
                ln_e["bbox_1000"][1] <= 120
                and not fc.FOLIO_EDGE_NUMBER_RE.search(ln_e["text"].strip())
                and bool(fc.STANDALONE_RUBRIC_LABEL_RE.match(ln_e["text"].strip()))
                for ln_e in raw_lines
            )

            for ln_entry in raw_lines:
                lb = ln_entry["bbox_1000"]
                ltxt = ln_entry["text"]
                s_ltxt = ltxt.strip()
                cx = (lb[0] + lb[2]) / 2.0
                cy = (lb[1] + lb[3]) / 2.0
                is_top_rubric_banner = (
                    lb[1] <= 120
                    and not fc.FOLIO_EDGE_NUMBER_RE.search(s_ltxt)
                    and (
                        bool(fc.DIDACTIC_RUBRIC_BANNER_RE.match(s_ltxt))
                        or (
                            page_has_top_rubric_badge
                            and 2 <= len(s_ltxt.split()) <= 14
                            and not s_ltxt.endswith(".")
                            and (
                                len(re.findall(r"\b[A-ZÄÖÜ][A-Za-zÄÖÜäöüß\-]+", s_ltxt)) >= 2
                                or (len(s_ltxt.split()) <= 4 and bool(re.match(r"^[A-ZÄÖÜ]", s_ltxt)))
                            )
                        )
                    )
                )

                in_fig = False
                in_rescued_callout = False
                for fb in page_figs:
                    fb_rect = _extract_rect_coords(fb)
                    if fb_rect is None:
                        continue
                    if (
                        _bbox_overlap_ratio(lb, fb_rect) >= 0.55
                        or (fb_rect[0] <= cx <= fb_rect[2] and fb_rect[1] <= cy <= fb_rect[3])
                    ):
                        if fb_rect in callout_fig_rects:
                            in_rescued_callout = True
                            break
                        # Keep real captions positioned at the bottom edge of a figure box or top rubric banners out of figure_texts
                        if is_top_rubric_banner or (
                            lb[1] >= fb_rect[3] - 32
                            and _is_figure_caption_line(ltxt, has_page_images=True)
                        ):
                            in_fig = False
                        else:
                            in_fig = True
                        break
                if in_fig:
                    details["figure_texts_by_page"].setdefault(p_idx, []).append(ltxt)
                    continue
                if in_rescued_callout:
                    ln_entry["in_callout_box"] = True

                if (
                    (lb[3] <= 65 or lb[1] >= 945)
                    and not is_top_rubric_banner
                    and not _is_marginalia_or_glossary_note(ltxt)
                ):
                    f_type = "page_header" if lb[3] <= 65 else "page_footer"
                    details["furniture_by_page"].setdefault(p_idx, []).append({
                        "type": f_type,
                        "text": ltxt,
                        "page_idx": p_idx,
                        "bbox_1000": lb,
                    })
                    continue

                if any(_bbox_overlap_ratio(lb, tb) >= 0.55 for tb in page_tbls):
                    continue

                body_lines.append(ln_entry)

            if not body_lines:
                continue

            body_fsizes = [
                ln_e["fsize"]
                for ln_e in body_lines
                if ln_e["fsize"] > 0 and len(ln_e["text"]) >= 20
            ]
            if not body_fsizes:
                body_fsizes = [ln_e["fsize"] for ln_e in body_lines if ln_e["fsize"] > 0]
            median_fsize = statistics.median(body_fsizes) if body_fsizes else 0.0

            # Group body lines into paragraphs while preserving character styles
            paragraphs: list[list[dict[str, Any]]] = []
            for ln_e in body_lines:
                if not paragraphs:
                    paragraphs.append([ln_e])
                    continue
                prev_ln = paragraphs[-1][-1]
                pb = prev_ln["bbox_1000"]
                cb = ln_e["bbox_1000"]
                lh = max(8, pb[3] - pb[1])
                same_col = abs(cb[0] - pb[0]) <= 90 and (min(pb[2], cb[2]) - max(pb[0], cb[0])) > 15
                vert_gap = cb[1] - pb[3]
                same_size = abs(ln_e["fsize"] - prev_ln["fsize"]) <= max(1.2, 0.12 * max(ln_e["fsize"], prev_ln["fsize"], 1.0))
                prev_is_callout_sub = (
                    len(paragraphs) >= 2
                    and len(paragraphs[-1]) == 1
                    and bool(fc.DIDACTIC_BOX_HEADER_RE.match(paragraphs[-2][0]["text"]))
                    and len(prev_ln["text"].split()) <= 10
                    and not prev_ln["text"].endswith((".", "!", "?"))
                )
                starts_new_item = bool(
                    re.match(
                        r"^(?:[-*•]\s+|\d{1,2}[\.\)]\s+|[A-Z]\d+\s+|(?:Abb(?:ildung)?\.?|Tab(?:elle)?\.?|Aufgabe|Übung|Material)\s+\S)",
                        ln_e["text"],
                    )
                    or fc.DIDACTIC_BOX_HEADER_RE.match(ln_e["text"])
                    or fc.DIDACTIC_BOX_HEADER_RE.match(prev_ln["text"])
                    or prev_is_callout_sub
                )
                if same_col and -5 <= vert_gap <= max(18, int(lh * 1.15)) and same_size and not starts_new_item:
                    paragraphs[-1].append(ln_e)
                else:
                    paragraphs.append([ln_e])

            unstyled_words_on_page: set[str] = set()
            raw_styled_candidates: list[dict[str, Any]] = []
            page_pdf_blocks: list[dict[str, Any]] = []

            for para_lines in paragraphs:
                merged_chars: list[tuple[str, bool, bool]] = []
                for li, pl in enumerate(para_lines):
                    lchars = [(c[0], c[3], c[4]) for c in pl["chars"]]
                    while lchars and lchars[0][0].isspace():
                        lchars.pop(0)
                    while lchars and lchars[-1][0].isspace():
                        lchars.pop()
                    if not lchars:
                        continue
                    if li > 0 and merged_chars:
                        last_ch = merged_chars[-1][0]
                        next_ch = lchars[0][0]
                        if last_ch == "\u00ad":
                            merged_chars.pop()
                            merged_chars.extend(lchars)
                            continue
                        if last_ch == "-" and next_ch.islower():
                            # Check trailing word stem before '-'
                            stem_chars: list[str] = []
                            for back_ch, _, _ in reversed(merged_chars[:-1]):
                                if back_ch.isalpha():
                                    stem_chars.append(back_ch)
                                else:
                                    break
                            stem = "".join(reversed(stem_chars))
                            rem_chars: list[str] = []
                            for fwd_ch, _, _ in lchars:
                                if fwd_ch.isalpha():
                                    rem_chars.append(fwd_ch)
                                else:
                                    break
                            rem = "".join(rem_chars)
                            if stem and rem and not _is_preserved_lowercase_compound(stem, rem):
                                merged_chars.pop()
                                merged_chars.extend(lchars)
                                continue
                            merged_chars.extend(lchars)
                            continue
                        merged_chars.append((" ", False, False))
                    merged_chars.extend(lchars)

                para_str = (
                    "".join(c[0] for c in merged_chars)
                    .replace("\u00ad", "")
                    .encode("utf-16-le", "surrogatepass")
                    .decode("utf-16-le", "ignore")
                )
                para_str = re.sub(r"\s+", " ", para_str).strip()
                if not para_str:
                    continue

                para_bbox = [
                    min(pl["bbox_1000"][0] for pl in para_lines),
                    min(pl["bbox_1000"][1] for pl in para_lines),
                    max(pl["bbox_1000"][2] for pl in para_lines),
                    max(pl["bbox_1000"][3] for pl in para_lines),
                ]
                para_fsize = statistics.median([pl["fsize"] for pl in para_lines if pl["fsize"] > 0] or [0.0])
                para_words = para_str.split()
                is_heading_para = bool(
                    median_fsize > 0
                    and para_fsize > median_fsize * 1.14
                    and len(para_words) <= 22
                )
                is_callout_para = (
                    not _is_marginalia_or_glossary_note(para_str)
                    and (
                        any(pl.get("in_callout_box") for pl in para_lines)
                        or any(
                            _bbox_overlap_ratio(para_bbox, cr_b) >= 0.55
                            or (
                                para_bbox[0] >= cr_b[0] - 12
                                and para_bbox[2] <= cr_b[2] + 12
                                and para_bbox[1] >= cr_b[1] - 12
                                and para_bbox[3] <= cr_b[3] + 12
                            )
                            for cr_b in page_callouts_1000
                        )
                    )
                )
                blk_entry: dict[str, Any] = {
                    "type": "section_header" if is_heading_para else "text",
                    "text": para_str,
                    "page_idx": p_idx,
                    "bbox_1000": para_bbox,
                }
                if is_callout_para:
                    blk_entry["is_callout_box"] = True
                page_pdf_blocks.append(blk_entry)

                if is_heading_para:
                    continue

                prev_was_heading = len(page_pdf_blocks) >= 2 and (
                    page_pdf_blocks[-2].get("type") == "section_header"
                    or bool(
                        re.match(
                            r"^(?:#{1,6}\s+|\d+\.\d+\b|(?:Methode|Basiskonzept|Exkurs)\b)",
                            str(page_pdf_blocks[-2].get("text") or "").strip(),
                            re.IGNORECASE,
                        )
                    )
                )
                min_italic_words = 15 if prev_was_heading else 25
                alpha_total = sum(1 for ch, _, _ in merged_chars if ch.isalpha())
                italic_alpha = sum(1 for ch, _b, it in merged_chars if ch.isalpha() and it)
                bold_alpha = sum(1 for ch, bd, _i in merged_chars if ch.isalpha() and bd)
                suppress_italic = bool(
                    len(para_words) >= min_italic_words
                    and alpha_total > 0
                    and (italic_alpha / alpha_total) >= 0.80
                )
                suppress_all_caption = bool(
                    _is_figure_caption_line(para_str, has_page_images=True)
                    and alpha_total > 0
                    and ((italic_alpha + bold_alpha) / alpha_total) >= 0.80
                )
                if suppress_all_caption:
                    continue

                # Tokenize merged_chars into word tokens + separator strings
                word_tokens: list[dict[str, Any]] = []
                idx_c = 0
                nc = len(merged_chars)
                while idx_c < nc:
                    ch_i, bd_i, it_i = merged_chars[idx_c]
                    if ch_i.isalnum() or ch_i in "äöüÄÖÜß":
                        w_chars: list[tuple[str, bool, bool]] = []
                        while idx_c < nc and (
                            merged_chars[idx_c][0].isalnum()
                            or merged_chars[idx_c][0] in "äöüÄÖÜß-"
                        ):
                            w_chars.append(merged_chars[idx_c])
                            idx_c += 1
                        sep_chars: list[str] = []
                        while idx_c < nc and not (
                            merged_chars[idx_c][0].isalnum()
                            or merged_chars[idx_c][0] in "äöüÄÖÜß"
                        ):
                            sep_chars.append(merged_chars[idx_c][0])
                            idx_c += 1
                        w_txt = (
                            "".join(x[0] for x in w_chars)
                            .encode("utf-16-le", "surrogatepass")
                            .decode("utf-16-le", "ignore")
                            .strip("-")
                        )
                        if not w_txt:
                            continue
                        n_let = max(1, sum(1 for x in w_chars if x[0].isalpha()))
                        b_cnt = sum(1 for x in w_chars if x[0].isalpha() and x[1])
                        i_cnt = sum(1 for x in w_chars if x[0].isalpha() and x[2])
                        w_style: str | None = None
                        if b_cnt / n_let >= 0.75:
                            w_style = "bold"
                        elif not suppress_italic and (i_cnt / n_let) >= 0.75:
                            w_style = "italic"
                        word_tokens.append({
                            "word": w_txt,
                            "style": w_style,
                            "sep": "".join(sep_chars),
                        })
                    else:
                        idx_c += 1

                for wt in word_tokens:
                    if wt["style"] is None:
                        unstyled_words_on_page.add(wt["word"].lower())

                wi = 0
                nw = len(word_tokens)
                while wi < nw:
                    st = word_tokens[wi]["style"]
                    if st is None:
                        wi += 1
                        continue
                    wj = wi + 1
                    while (
                        wj < nw
                        and word_tokens[wj]["style"] == st
                        and re.fullmatch(r"\s+", word_tokens[wj - 1]["sep"] or "")
                    ):
                        wj += 1
                    phrase = " ".join(word_tokens[k]["word"] for k in range(wi, wj))
                    if (
                        len(phrase) >= 3
                        and len(re.findall(r"[A-Za-zÄÖÜäöüß]", phrase)) >= 2
                        and len(phrase.split()) < 25
                    ):
                        left_w = word_tokens[wi - 1]["word"] if (wi > 0 and re.fullmatch(r"\s+", word_tokens[wi - 1]["sep"] or "")) else ""
                        right_w = word_tokens[wj]["word"] if (wj < nw and re.fullmatch(r"[\s,;:]+", word_tokens[wj - 1]["sep"] or "")) else ""
                        raw_styled_candidates.append({
                            "text": phrase,
                            "style": st,
                            "left": left_w,
                            "right": right_w,
                        })
                    wi = wj

            if page_pdf_blocks:
                details["pdf_blocks_by_page"][p_idx] = _sort_blocks_in_reading_order(page_pdf_blocks)

            if raw_styled_candidates:
                seen_spans: set[tuple[str, str, str, str]] = set()
                final_spans: list[dict[str, Any]] = []
                for sc in raw_styled_candidates:
                    words_in_sc = sc["text"].lower().split()
                    always_styled = (
                        True
                        if len(words_in_sc) >= 2
                        else (words_in_sc[0] not in unstyled_words_on_page)
                    )
                    dedup_key = (
                        sc["text"],
                        sc["style"],
                        "" if always_styled else sc["left"].lower(),
                        "" if always_styled else sc["right"].lower(),
                    )
                    if dedup_key in seen_spans:
                        continue
                    seen_spans.add(dedup_key)
                    final_spans.append({
                        "text": sc["text"],
                        "style": sc["style"],
                        "left": sc["left"],
                        "right": sc["right"],
                        "always_styled": always_styled,
                    })
                details["font_spans_by_page"][p_idx] = final_spans
    except Exception as ex:
        logger.debug(f"Could not extract PDF page font/block details: {ex}")
    finally:
        if owns_doc and pdf_doc is not None:
            try:
                pdf_doc.close()
            except Exception:
                pass
    return details


def _apply_pdf_font_spans_to_markdown(markdown_text: str, font_spans: list[dict[str, Any]]) -> str:
    """Applies extracted PDF ``Bold``/``SemiBold`` (``**...**``) and ``Italic`` (``*...*``) spans to body prose.

    Skips headings, pipe tables, image tags, math formulas, already-formatted emphasis spans,
    and standalone whole-line captions or callout headers.

    Args:
        markdown_text: Page Markdown text to enrich.
        font_spans: List of ``{"text": str, "style": "bold"|"italic", ...}`` span dictionaries.

    Returns:
        Markdown text with inline ``**...**`` and ``*...*`` emphasis markers applied.
    """
    if not markdown_text or not font_spans:
        return markdown_text

    ordered_spans = sorted(
        font_spans,
        key=lambda s: (len(str(s.get("text") or "")), 1 if s.get("always_styled", True) else 0),
        reverse=True,
    )

    out_lines: list[str] = []
    for raw_line in markdown_text.splitlines():
        s = raw_line.strip()
        if (
            not s
            or re.match(r"^#{1,6}\s", s)
            or s.startswith(("|", "![", "((" , "```", "<Bild", "</Bild", "<Anmerkung", "</Anmerkung", "<Rahmen", "</Rahmen", "<Tabelle", "</Tabelle"))
            or re.match(r"^(?:\*\*|__).+(?:\*\*|__)$", s)
        ):
            out_lines.append(raw_line)
            continue

        is_cap_line = _is_figure_caption_line(s, has_page_images=True)
        updated_line = raw_line

        for sp in ordered_spans:
            phrase = str(sp.get("text") or "").strip(" \t\r\n,.;:!?()[]{}\"'„“‚‘»«")
            if len(phrase) < 3 or len(phrase.split()) >= 25:
                continue
            if len(re.findall(r"[A-Za-zÄÖÜäöüß]", phrase)) < 2:
                continue
            if re.match(r"^(?:Aufgabe|Übung|Material|Abb(?:ildung)?\.?|Tab(?:elle)?\.?)\s*\S*$", phrase, re.IGNORECASE):
                continue
            if is_cap_line and len(phrase) >= 0.75 * len(s):
                continue

            style = str(sp.get("style") or "italic").lower()
            marker = "**" if "bold" in style else "*"
            always_styled = bool(sp.get("always_styled", True))
            left_w = str(sp.get("left") or "").strip()
            right_w = str(sp.get("right") or "").strip()

            phrase_regex_body = r"\s+".join(re.escape(tok) for tok in phrase.split())
            if always_styled or (not left_w and not right_w):
                pat = re.compile(rf"(?<![\wÄÖÜäöüß*_$])({phrase_regex_body})(?![\wÄÖÜäöüß*_$])")
            elif left_w:
                pat = re.compile(
                    rf"(?<![\wÄÖÜäöüß*_$])({re.escape(left_w)}\s+)({phrase_regex_body})(?![\wÄÖÜäöüß*_$])",
                    re.IGNORECASE,
                )
            else:
                pat = re.compile(
                    rf"(?<![\wÄÖÜäöüß*_$])({phrase_regex_body})(\s+{re.escape(right_w)})(?![\wÄÖÜäöüß*_$])",
                    re.IGNORECASE,
                )

            parts = _PROTECTED_INLINE_SPAN_RE.split(updated_line)
            rebuilt_parts: list[str] = []
            for idx_p, part in enumerate(parts):
                if idx_p % 2 == 1 or not part:
                    rebuilt_parts.append(part)
                    continue
                if always_styled or (not left_w and not right_w):
                    rebuilt_parts.append(pat.sub(rf"{marker}\1{marker}", part))
                elif left_w:
                    rebuilt_parts.append(pat.sub(lambda m: f"{m.group(1)}{marker}{phrase}{marker}", part))
                else:
                    rebuilt_parts.append(pat.sub(lambda m: f"{marker}{phrase}{marker}{m.group(2)}", part))
            updated_line = "".join(rebuilt_parts)

        out_lines.append(updated_line)

    return "\n".join(out_lines)


def extract_docling_page_layout(pdf_path: str, images_dir: str) -> dict[str, Any]:
    """Run hybrid Docling CPU Layout, TableFormer & single-handle PDF font/text extraction.

    Extracts from any digital or scanned PDF:
      - pictures_by_page: {page_idx: [img_filename, ...]}
      - tables_by_page: {page_idx: [markdown_table, ...]}
      - furniture_by_page: {page_idx: [{"type": str, "text": str, "page_idx": int}, ...]}
      - heading_blocks: [{"type": "title", "text": str, "text_level": 1, "page_idx": int, "bbox": [0, 0, w, h], "is_body_sized": bool}, ...]
      - text_blocks: [{"type": str, "text": str, "page_idx": int}, ...]
      - text_blocks_by_page: {page_idx: [{"type": str, "text": str, "page_idx": int, "bbox_1000": [...]}, ...]}
      - font_spans_by_page: {page_idx: [{"text": str, "style": str, ...}, ...]}
      - figure_texts_by_page: {page_idx: [str, ...]}
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
        "font_spans_by_page": {},
        "figure_texts_by_page": {},
        "task_difficulties_by_page": {},
        "opening_headers_by_page": {},
        "body_line_height": 0.0,
    }
    if not pdf_path or not os.path.exists(pdf_path) or not pdf_path.lower().endswith(".pdf"):
        return result

    pdf_doc_shared = None
    page_sizes_by_idx: dict[int, tuple[float, float]] = {}
    figure_bboxes_1000_by_page: dict[int, list[list[int]]] = {}
    table_bboxes_1000_by_page: dict[int, list[list[int]]] = {}
    seen_opening_keys: set[str] = set()

    try:
        import pypdfium2 as pdfium

        pdf_doc_shared = pdfium.PdfDocument(pdf_path)
        for p_i in range(len(pdf_doc_shared)):
            page_sizes_by_idx[p_i] = pdf_doc_shared[p_i].get_size()
    except Exception:
        pdf_doc_shared = None

    try:
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
                            table_bboxes_1000_by_page.setdefault(p_idx, []).append(t_bbox_1000)
                            result["layout_blocks"].append({
                                "type": "table",
                                "text": t_md,
                                "page_idx": p_idx,
                                "bbox_1000": t_bbox_1000,
                            })
                    except Exception:
                        pass

            # 3. Collect single-line body heights, furniture, vector callout boxes, and heading bboxes
            callout_rects_by_page = detect_pdf_callout_rects_by_page(pdf_path, pdf_doc=pdf_doc_shared)
            body_heights: list[float] = []
            raw_headings: list[dict[str, Any]] = []
            pages_with_top_rubric_badge: set[int] = set()
            for pre_item, _pre_lvl in doc.iterate_items(
                included_content_layers={ContentLayer.BODY, ContentLayer.FURNITURE}
            ):
                pre_txt = (getattr(pre_item, "text", "") or "").strip()
                if (
                    not pre_txt
                    or fc.FOLIO_EDGE_NUMBER_RE.search(pre_txt)
                    or not fc.STANDALONE_RUBRIC_LABEL_RE.match(pre_txt)
                ):
                    continue
                pre_p_no = 1
                pre_bbox = None
                if getattr(pre_item, "prov", None) and len(pre_item.prov) > 0:
                    pre_p_no = pre_item.prov[0].page_no
                    pre_bbox = pre_item.prov[0].bbox
                pre_p_idx = max(0, pre_p_no - 1)
                pw_pre, ph_pre = page_sizes_by_idx.get(pre_p_idx, (0.0, 0.0))
                pre_b1000 = normalize_bbox_to_1000(pre_bbox, pw_pre, ph_pre) if pre_bbox else None
                if pre_b1000 is None or pre_b1000[1] <= 120:
                    pages_with_top_rubric_badge.add(pre_p_idx)

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
                if bbox_obj is not None and pw_i > 0 and ph_i > 0:
                    b_min_x = min(float(bbox_obj.l), float(bbox_obj.r))
                    b_max_x = max(float(bbox_obj.l), float(bbox_obj.r))
                    if b_max_x <= 1.0 or b_min_x >= pw_i - 1.0:
                        continue
                bbox_1000 = normalize_bbox_to_1000(bbox_obj, pw_i, ph_i) if bbox_obj else None

                is_top_rubric_banner = (
                    lbl != "page_footer"
                    and (bbox_1000 is None or bbox_1000[1] <= 120)
                    and not fc.FOLIO_EDGE_NUMBER_RE.search(txt)
                    and (
                        bool(fc.DIDACTIC_RUBRIC_BANNER_RE.match(txt))
                        or (
                            p_idx in pages_with_top_rubric_badge
                            and bbox_1000 is not None
                            and 2 <= len(txt.split()) <= 14
                            and not txt.endswith(".")
                            and (
                                len(re.findall(r"\b[A-ZÄÖÜ][A-Za-zÄÖÜäöüß\-]+", txt)) >= 2
                                or (len(txt.split()) <= 4 and bool(re.match(r"^[A-ZÄÖÜ]", txt)))
                            )
                        )
                    )
                )

                is_top_or_bottom_furniture = bool(
                    bbox_1000 is not None
                    and (bbox_1000[3] <= 65 or (bbox_1000[1] >= 945 and len(txt) <= 85))
                    and lbl not in ("title",)
                )
                if (
                    layer == ContentLayer.FURNITURE
                    or lbl in ("page_header", "page_footer", "furniture")
                    or is_top_or_bottom_furniture
                ) and not is_top_rubric_banner and not _is_marginalia_or_glossary_note(txt):
                    f_type = (
                        "page_header"
                        if ("header" in lbl or (bbox_1000 is not None and bbox_1000[3] <= 65))
                        else "page_footer"
                    )
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

                # Exclude diagram-internal labels located inside figure_bboxes_1000_by_page
                in_callout_doc = is_bbox_inside_callout_rect(bbox_obj, txt, callout_rects_by_page.get(p_idx, []))
                if bbox_1000 is not None and lbl != "caption":
                    in_fig_box = False
                    for fig_bbox in figure_bboxes_1000_by_page.get(p_idx, []):
                        if _bbox_overlap_ratio(bbox_1000, fig_bbox) >= 0.55:
                            if (
                                is_top_rubric_banner
                                or fc.DIDACTIC_BOX_HEADER_RE.match(txt)
                                or (in_callout_doc and len(txt.split()) >= 4)
                                or (
                                    bbox_1000[1] >= fig_bbox[3] - 32
                                    and _is_figure_caption_line(txt, has_page_images=True)
                                )
                            ):
                                in_fig_box = False
                            else:
                                in_fig_box = True
                                break
                    if in_fig_box:
                        result["figure_texts_by_page"].setdefault(p_idx, []).append(txt)
                        continue

                effective_lbl = (
                    "section_header"
                    if is_top_rubric_banner
                    else ("text" if lbl in ("page_header", "page_footer", "furniture") else lbl)
                )
                tb_entry: dict[str, Any] = {
                    "type": effective_lbl,
                    "text": txt,
                    "page_idx": p_idx,
                }
                if in_callout_doc and not _is_marginalia_or_glossary_note(txt):
                    tb_entry["is_callout_box"] = True
                if bbox_1000 is not None:
                    tb_entry["bbox_1000"] = bbox_1000
                result["text_blocks"].append(tb_entry)
                result["text_blocks_by_page"].setdefault(p_idx, []).append(tb_entry)

                if lbl in ("text", "list_item") and not is_top_rubric_banner and 5.0 <= h <= 18.0 and 15 <= len(txt) <= 75 and w >= 80:
                    body_heights.append(h)
                elif lbl in ("section_header", "title") or (is_top_rubric_banner and h > 0):
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

        # 4. Single-handle pypdfium2 pass for inline Bold/SemiBold/Italic font spans,
        #    in-figure PDF text labels, and born-digital text block recall
        if pdf_doc_shared is not None:
            pdf_details = extract_pdf_page_details(
                pdf_doc_shared,
                figure_bboxes_by_page=figure_bboxes_1000_by_page,
                table_bboxes_by_page=table_bboxes_1000_by_page,
                callout_rects_by_page=callout_rects_by_page,
            )
            for p_idx, spans in pdf_details.get("font_spans_by_page", {}).items():
                if spans:
                    result["font_spans_by_page"][p_idx] = spans
            for p_idx, fig_txts in pdf_details.get("figure_texts_by_page", {}).items():
                if fig_txts:
                    result["figure_texts_by_page"].setdefault(p_idx, []).extend(fig_txts)
            for p_idx, t_diffs in pdf_details.get("task_difficulties_by_page", {}).items():
                if t_diffs:
                    result["task_difficulties_by_page"][p_idx] = t_diffs
            for p_idx, furn_items in pdf_details.get("furniture_by_page", {}).items():
                existing_f_norms = {
                    re.sub(r"\W+", " ", str(fi.get("text") or "")).strip().lower()
                    for fi in result["furniture_by_page"].get(p_idx, [])
                }
                for fi in furn_items:
                    fnorm = re.sub(r"\W+", " ", str(fi.get("text") or "")).strip().lower()
                    if fnorm and fnorm not in existing_f_norms:
                        existing_f_norms.add(fnorm)
                        result["furniture_by_page"].setdefault(p_idx, []).append(fi)
                        if fi.get("type") == "page_header":
                            open_hdr = parse_furniture_opening_header(str(fi.get("text") or ""), seen_opening_keys)
                            if open_hdr:
                                result["opening_headers_by_page"].setdefault(p_idx, []).append(open_hdr)

            all_page_indices = set(result["text_blocks_by_page"].keys()) | set(
                pdf_details.get("pdf_blocks_by_page", {}).keys()
            )
            for p_idx in sorted(all_page_indices):
                doc_blocks = list(result["text_blocks_by_page"].get(p_idx, []))
                pdf_blocks = pdf_details.get("pdf_blocks_by_page", {}).get(p_idx, [])
                doc_words = {
                    w
                    for db in doc_blocks
                    for w in re.findall(r"[a-zA-ZäöüÄÖÜß0-9]{4,}", str(db.get("text") or "").lower())
                }
                furn_norms_p = {
                    re.sub(r"\W+", " ", str(fi.get("text") or "")).strip().lower()
                    for fi in result["furniture_by_page"].get(p_idx, [])
                }
                doc_norms_p = {
                    re.sub(r"\W+", " ", str(db.get("text") or "")).strip().lower()
                    for db in doc_blocks
                }
                for pb in pdf_blocks:
                    pb_txt = str(pb.get("text") or "").strip()
                    pb_norm = re.sub(r"\W+", " ", pb_txt).strip().lower()
                    if not pb_norm or pb_norm in furn_norms_p or pb_norm in doc_norms_p:
                        continue
                    if pb.get("is_callout_box") and fc.DIDACTIC_BOX_HEADER_RE.match(pb_txt):
                        doc_blocks.append(pb)
                        doc_norms_p.add(pb_norm)
                        continue
                    pb_words = re.findall(r"[a-zA-ZäöüÄÖÜß0-9]{4,}", pb_norm)
                    if not pb_words:
                        continue
                    ov = sum(1 for w in pb_words if w in doc_words) / len(pb_words)
                    if ov < 0.45:
                        doc_blocks.append(pb)
                        doc_words.update(pb_words)
                        doc_norms_p.add(pb_norm)

                ordered_p_blocks = _sort_blocks_in_reading_order(doc_blocks)
                p_spans = result["font_spans_by_page"].get(p_idx, [])
                if p_spans:
                    for blk in ordered_p_blocks:
                        blk["font_spans"] = p_spans
                result["text_blocks_by_page"][p_idx] = ordered_p_blocks

            result["text_blocks"] = [
                blk
                for p_i in sorted(result["text_blocks_by_page"].keys())
                for blk in result["text_blocks_by_page"][p_i]
            ]
    finally:
        if pdf_doc_shared is not None:
            try:
                pdf_doc_shared.close()
            except Exception:
                pass

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
    r"""Detect and strip degenerate VLM-OCR token repetition loops, cycling blocks, and empty headings.

    Detects:
      1. Intra-line token/substring repetition loops (> 250 chars where a 2..20 char n-gram
         repeats >= 12 times consecutively).
      2. Runs of 8 or more consecutive short headings (``#{1,6}\s+\S{1,3}$``) or short tokens.
      3. Multi-line cycles (``period`` 1..8, >= 2 full repeats of >= 4 lines, including cycles
         containing ``#`` headings), preserving the first occurrence and dropping duplicate copies.
      4. Standalone empty headings (``#{1,6}\s*$``).

    Args:
        vlm_md: Raw or partially cleaned VLM page Markdown string.

    Returns:
        Tuple ``(cleaned_markdown, had_loop)`` where ``had_loop`` is True if a
        degenerate repetition loop was detected and stripped.
    """
    if not vlm_md:
        return vlm_md, False

    lines = list(vlm_md.splitlines())
    drop_line_indices: set[int] = set()
    had_loop = False

    intra_ngram_loop_re = re.compile(r"(.{2,20}?)\1{11,}")
    table_sep_re = re.compile(r"^\|[\s:\-\|]+\|$")

    for idx, raw_line in enumerate(lines):
        s_raw = raw_line.strip()
        if len(s_raw) > 250 and not table_sep_re.match(s_raw):
            m_intra = intra_ngram_loop_re.search(s_raw)
            if m_intra:
                had_loop = True
                prefix_str = s_raw[: m_intra.start()].strip()
                if (
                    s_raw.lstrip().startswith(("![", "! ["))
                    or "http://" in s_raw
                    or "https://" in s_raw
                    or "www." in s_raw
                    or "![" in prefix_str
                    or len(re.findall(r"[A-Za-zÄÖÜäöüß]", prefix_str)) < 40
                ):
                    drop_line_indices.add(idx)
                else:
                    cut_pos = raw_line.find(m_intra.group(0))
                    if cut_pos > 0:
                        lines[idx] = raw_line[:cut_pos].rstrip()
                    else:
                        drop_line_indices.add(idx)

    non_empty: list[tuple[int, str]] = [
        (idx, lines[idx].strip())
        for idx in range(len(lines))
        if idx not in drop_line_indices and lines[idx].strip()
    ]
    if not non_empty:
        return "", had_loop

    short_heading_re = re.compile(r"^#{1,6}(?:\s+\S{1,3})?\s*$")
    empty_heading_re = re.compile(r"^#{1,6}\s*$")
    short_token_line_re = re.compile(r"^(?:#{1,6}\s*)?[A-Za-z0-9äöüÄÖÜß]{1,3}[\.\)\:]?$")
    structural_prefix = ("((", "|", "![", "<", "```")
    non_cycle_prefix = ("((", "|", "<", "```")
    blank_rule_re = re.compile(r"^[_\.\-\s]{3,}$")
    roman_tok_re = re.compile(
        r"\b(?=[IVXLCDM]+\b)M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})\b"
    )
    page_marker_re = re.compile(r"^\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)")

    def _norm_cycle_line(txt: str) -> str:
        return re.sub(r"\s+", " ", txt.strip())

    def _enum_skeleton(txt: str) -> str:
        s_t = txt.strip()
        if not s_t or s_t.startswith(("((", "|", "![", "<", "```", "- ", "* ", "• ", "-\t")):
            return ""
        if re.match(r"^\d+\.\t", s_t) or blank_rule_re.match(s_t):
            return ""
        is_h = bool(re.match(r"^#{1,6}\s+\S", s_t))
        if not is_h and len(s_t) > 60:
            return ""
        body = re.sub(r"^#{1,6}\s+", "", s_t).strip()
        body = re.sub(r"[*_`]+", "", body)
        body = roman_tok_re.sub("#", body)
        body = re.sub(r"\b[A-ZÄÖÜ]\b", "#", body)
        body = re.sub(r"\b[A-Za-z]?\d+(?:[.,]\d+)*[a-z]?\b", "#", body)
        body = re.sub(r"\s+", " ", body).strip().lower()
        if not re.search(r"[a-zäöüß]{2,}", body):
            return ""
        return f"{'h:' if is_h else 's:'}{body}"

    titled_heading_words_on_page: set[str] = set()
    n_ne = len(non_empty)
    k = 0
    while k < n_ne:
        _line_idx, s = non_empty[k]
        if page_marker_re.match(s):
            titled_heading_words_on_page.clear()
            k += 1
            continue

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

        skel_k = _enum_skeleton(s)
        if skel_k:
            matched_ne_positions: list[int] = [k]
            m_sk = k + 1
            while m_sk < n_ne:
                cand_sk_line = non_empty[m_sk][1]
                if page_marker_re.match(cand_sk_line):
                    break
                if cand_sk_line.startswith("!["):
                    m_sk += 1
                    continue
                if _enum_skeleton(cand_sk_line) == skel_k:
                    matched_ne_positions.append(m_sk)
                    m_sk += 1
                else:
                    break
            if len(matched_ne_positions) >= 6:
                had_loop = True
                base_words = re.findall(r"[a-zäöüß]{2,}", skel_k[2:])
                base_w = base_words[0] if base_words else ""
                drop_positions = (
                    matched_ne_positions
                    if (base_w and base_w in titled_heading_words_on_page)
                    else matched_ne_positions[1:]
                )
                for pos_i in drop_positions:
                    drop_line_indices.add(non_empty[pos_i][0])
                k = matched_ne_positions[-1] + 1
                continue

        if re.match(r"^#{1,6}\s+\S", s):
            h_words = re.findall(r"[A-Za-zÄÖÜäöüß]{3,}", re.sub(r"^#{1,6}\s+", "", s))
            if len(h_words) >= 3:
                titled_heading_words_on_page.add(h_words[0].lower())

        if not s.startswith(non_cycle_prefix) and not blank_rule_re.match(s):
            matched_cycle = False
            for period in range(1, 9):
                min_needed = 4 if period == 1 else max(4, 2 * period)
                if k + min_needed > n_ne:
                    continue
                if period == 1 and s.startswith("!["):
                    continue
                if any(
                    non_empty[k + off][1].startswith(non_cycle_prefix)
                    or blank_rule_re.match(non_empty[k + off][1])
                    for off in range(period)
                ):
                    continue
                m = k + period
                while (
                    m < n_ne
                    and not non_empty[m][1].startswith(non_cycle_prefix)
                    and not blank_rule_re.match(non_empty[m][1])
                    and _norm_cycle_line(non_empty[m][1]) == _norm_cycle_line(non_empty[k + ((m - k) % period)][1])
                ):
                    m += 1
                total_span = m - k
                full_repeats = total_span // period
                is_valid_cycle = False
                if period == 1:
                    is_valid_cycle = total_span >= 4
                elif full_repeats >= 2 and total_span >= 4:
                    if total_span >= 6 or any(
                        non_empty[k + off][1].startswith("#") or len(non_empty[k + off][1]) >= 10
                        for off in range(period)
                    ):
                        is_valid_cycle = True

                if is_valid_cycle:
                    had_loop = True
                    # Keep the FIRST occurrence (k .. k + period - 1) and drop 2nd+ copies
                    start_drop = non_empty[k + period][0]
                    end_drop = non_empty[m - 1][0]
                    for d_i in range(start_drop, end_drop + 1):
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


def _norm_furniture_key(text: str) -> str:
    """Normalizes a running header/footer string for layout furniture matching.

    Args:
        text: Candidate header, footer, or line string.

    Returns:
        Lowercased alphanumeric phrase with leading/trailing page numbers stripped.
    """
    s = re.sub(r"^#{1,6}\s*", "", (text or "").strip())
    s = re.sub(r"[*_`]+", " ", s).strip()
    s = re.sub(
        r"^(?:\d{1,4}(?:\s*[-–—|/]\s*|\s+))?(.*?)(?:(?:\s*[-–—|/]\s*|\s+)\d{1,4})?$",
        r"\1",
        s,
    )
    s = re.sub(r"\b(?:ii|II)\b", "11", s)
    return re.sub(r"\W+", " ", s).strip().lower()


def fuse_vlm_page_with_docling(
    raw_text: str,
    page_images: list[str],
    phys_num: int | str,
    page_tables: list[str] | None = None,
    opening_headers: list[str] | None = None,
    docling_layout: Any = None,
    page_idx: int | None = None,
) -> str:
    r"""Fuse a raw VLM OCR page with Docling layout crops, tables, PDF text/fonts, and furniture stripping.

    1. Strips degenerate VLM repetition loops (intra-line and multi-line cycles), code fences, and HTML wrappers.
    2. Strips running footers, lone page numbers, and Docling/top-margin running headers (including combined headers).
    3. Replaces foreign-language VLM hallucinations or recovers missing PDF/Docling columns/blocks in reading order.
    4. Strips orphan in-figure diagram label echoes while preserving real captions, headings, and tasks.
    5. Matches layout figures (page_images) to inline placeholders, explicit/bare-numbered captions, or below headings.
    6. Fuses borderless tables from Docling TableFormer and applies PDF Bold/SemiBold/Italic font emphasis.
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

    loop_cleaned_text, _had_loop = clean_vlm_repetition_loops(raw_text)
    cleaned_text = clean_markdown_fences(fix_escaped_dollars(loop_cleaned_text))
    cleaned_text = convert_html_tables_to_markdown(cleaned_text)
    cleaned_text = normalize_heading_page_markers(cleaned_text)
    cleaned_text = fc.INDESIGN_FOOTER_BLOCK_RE.sub("", cleaned_text)
    cleaned_text = "\n".join(
        ln for ln in cleaned_text.splitlines() if not fc.PREPRESS_MARK_LINE_RE.match(ln)
    )

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
        r"\n+\s*(?:\d+\s+[-–—\s/|]\s+[A-ZÄÖÜa-zäöüß0-9\s\-–—,:;.()/&]{2,65}|[A-ZÄÖÜa-zäöüß0-9\s\-–—,:;.()/&]{2,65}\s+[-–—\s/|]\s+\d+)\s*$",
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

    if phys_str.isdigit() and cleaned_text:
        esc_phys = re.escape(phys_str)
        bar_re = re.compile(
            rf"^[ \t]*(?:{esc_phys}[ \t]*[-–—|][ \t]*[A-ZÄÖÜa-zäöüß0-9\s\-–—,:;.()/&]{{2,65}}|"
            rf"[A-ZÄÖÜa-zäöüß0-9\s\-–—,:;.()/&]{{2,65}}[ \t]*[-–—|][ \t]*{esc_phys})[ \t]*$"
        )
        page_lines = cleaned_text.splitlines()
        non_empty_indices = [idx for idx, ln in enumerate(page_lines) if ln.strip()]
        boundary_set = set(non_empty_indices[:2] + non_empty_indices[-5:])
        kept_lines = [
            ln
            for idx, ln in enumerate(page_lines)
            if not (
                idx in boundary_set
                and not ln.lstrip().startswith(("#", "|", "- ", "* "))
                and bar_re.match(ln)
                and not _is_marginalia_or_glossary_note(ln.strip())
            )
        ]
        cleaned_text = re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines)).strip()

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

    # Resolve Docling layout (avoiding stale global cache unless page_images/page_tables match it)
    effective_layout = docling_layout
    if effective_layout is None and _LAST_DOCLING_LAYOUT:
        cached_pics = {
            os.path.basename(p)
            for plist in (_LAST_DOCLING_LAYOUT.get("pictures_by_page") or {}).values()
            for p in (plist or [])
        }
        cached_tbls = {
            t.strip()
            for tlist in (_LAST_DOCLING_LAYOUT.get("tables_by_page") or {}).values()
            for t in (tlist or [])
            if isinstance(t, str)
        }
        if (
            any(os.path.basename(fn) in cached_pics for fn in (page_images or []))
            or any(isinstance(t, str) and t.strip() in cached_tbls for t in (page_tables or []))
        ):
            effective_layout = _LAST_DOCLING_LAYOUT

    inferred_p_idx = page_idx
    if inferred_p_idx is None and page_images:
        for fn in page_images:
            m_p = re.match(r"^picture_(\d+)_", os.path.basename(fn))
            if m_p:
                inferred_p_idx = int(m_p.group(1))
                break

    fig_boxes_on_page: list[Any] = []
    table_boxes_on_page: list[Any] = []
    table_boxes_by_md: dict[str, Any] = {}
    image_bboxes_by_basename: dict[str, tuple[float, float, float, float]] = {}
    heading_bboxes_on_page: list[tuple[str, tuple[float, float, float, float]]] = []
    major_heading_norms_on_page: set[str] = set()
    body_heading_norms_on_page: set[str] = set()
    font_spans_on_page: list[dict[str, Any]] = []
    figure_texts_on_page: list[str] = []

    if effective_layout:
        candidate_blocks: list[Any] = []
        furniture_norms: set[str] = set()
        furniture_nospace: set[str] = set()
        page_known = True

        def _register_furn(raw_f: str) -> None:
            nf = _norm_furniture_key(raw_f)
            if len(nf) >= 3:
                furniture_norms.add(nf)
                nf_ns = re.sub(r"\s+", "", nf)
                if len(nf_ns) >= 5:
                    furniture_nospace.add(nf_ns)

        if isinstance(effective_layout, dict):
            for lb in effective_layout.get("layout_blocks") or []:
                if not isinstance(lb, dict):
                    continue
                if inferred_p_idx is not None and lb.get("page_idx") is not None and lb.get("page_idx") != inferred_p_idx:
                    continue
                lb_box = lb.get("bbox_1000") or lb.get("bbox")
                lb_type = str(lb.get("type") or "").lower()
                lb_txt = str(lb.get("text") or "").strip()
                if lb_type in ("image", "picture", "figure") and lb_box:
                    fig_boxes_on_page.append(lb_box)
                    rect_img = _extract_rect_coords(lb_box)
                    m_img_fn = re.search(r"images/([^)\n]+)", lb_txt)
                    if rect_img is not None and m_img_fn:
                        image_bboxes_by_basename[os.path.basename(m_img_fn.group(1).strip())] = rect_img
                elif lb_type == "table" and lb_box:
                    table_boxes_on_page.append(lb_box)
                    if lb_txt:
                        table_boxes_by_md[lb_txt] = lb_box

            for fb in effective_layout.get("figure_bboxes") or []:
                fig_boxes_on_page.append(fb)
            if inferred_p_idx is not None and isinstance(effective_layout.get("figure_bboxes_by_page"), dict):
                fig_boxes_on_page.extend(effective_layout["figure_bboxes_by_page"].get(inferred_p_idx) or [])

            for hb in effective_layout.get("heading_blocks") or []:
                if not isinstance(hb, dict):
                    continue
                if inferred_p_idx is not None and hb.get("page_idx") is not None and hb.get("page_idx") != inferred_p_idx:
                    continue
                hb_txt = str(hb.get("text") or "").strip()
                hb_box = hb.get("bbox_1000")
                hb_rect = _extract_rect_coords(hb_box) if hb_box is not None else None
                if hb_txt and (hb_rect is None or hb_rect[3] > 65.0):
                    hn = _norm_furniture_key(hb_txt)
                    if hn:
                        body_heading_norms_on_page.add(hn)
                    if not hb.get("is_body_sized") and not hb.get("is_callout_box"):
                        major_heading_norms_on_page.add(re.sub(r"\W+", " ", hb_txt).strip().lower())
                    if hb_rect is not None:
                        heading_bboxes_on_page.append((hb_txt, hb_rect))

            furn_by_page = effective_layout.get("furniture_by_page") or {}
            for f_p_idx, f_list in furn_by_page.items():
                hdr_items_on_p: list[tuple[float, str]] = []
                ftr_items_on_p: list[tuple[float, str]] = []
                for f_item in f_list or []:
                    f_txt = (f_item.get("text") if isinstance(f_item, dict) else str(f_item)) or ""
                    if not f_txt.strip():
                        continue
                    if _is_marginalia_or_glossary_note(f_txt):
                        if inferred_p_idx is None or f_p_idx == inferred_p_idx:
                            f_box = f_item.get("bbox_1000") if isinstance(f_item, dict) else None
                            gl_entry: dict[str, Any] = {"type": "text", "text": f_txt.strip(), "page_idx": f_p_idx}
                            if f_box is not None:
                                gl_entry["bbox_1000"] = f_box
                            candidate_blocks.append(gl_entry)
                    else:
                        _register_furn(f_txt)
                        f_type = str(f_item.get("type") or "page_header").lower() if isinstance(f_item, dict) else "page_header"
                        f_box = f_item.get("bbox_1000") if isinstance(f_item, dict) else None
                        f_rect = _extract_rect_coords(f_box) if f_box is not None else None
                        fx0 = f_rect[0] if f_rect is not None else 0.0
                        if "footer" in f_type:
                            ftr_items_on_p.append((fx0, f_txt.strip()))
                        else:
                            hdr_items_on_p.append((fx0, f_txt.strip()))

                for grp in (hdr_items_on_p, ftr_items_on_p):
                    if 2 <= len(grp) <= 6:
                        ordered_txts = [t for _, t in sorted(grp, key=lambda x: x[0])]
                        raw_txts = [t for _, t in grp]
                        _register_furn(" ".join(ordered_txts))
                        _register_furn(" ".join(raw_txts))
                        for i_f in range(len(ordered_txts)):
                            for j_f in range(len(ordered_txts)):
                                if i_f != j_f:
                                    _register_furn(f"{ordered_txts[i_f]} {ordered_txts[j_f]}")

            ft_by_page = effective_layout.get("figure_texts_by_page") or {}
            if inferred_p_idx is not None and inferred_p_idx in ft_by_page:
                figure_texts_on_page.extend(ft_by_page[inferred_p_idx] or [])
            elif ft_by_page and len(ft_by_page) == 1 and inferred_p_idx is None:
                figure_texts_on_page.extend(next(iter(ft_by_page.values())) or [])
            if effective_layout.get("figure_texts"):
                figure_texts_on_page.extend(effective_layout.get("figure_texts") or [])

            fs_by_page = effective_layout.get("font_spans_by_page") or {}
            if inferred_p_idx is not None and inferred_p_idx in fs_by_page:
                font_spans_on_page.extend(fs_by_page[inferred_p_idx] or [])
            elif fs_by_page and len(fs_by_page) == 1 and inferred_p_idx is None:
                font_spans_on_page.extend(next(iter(fs_by_page.values())) or [])
            if effective_layout.get("font_spans"):
                font_spans_on_page.extend(effective_layout.get("font_spans") or [])

            tb_by_page = effective_layout.get("text_blocks_by_page") or {}
            if inferred_p_idx is not None:
                if inferred_p_idx in tb_by_page:
                    candidate_blocks.extend(tb_by_page[inferred_p_idx])
                elif not tb_by_page:
                    candidate_blocks.extend(
                        effective_layout.get("text_blocks")
                        or effective_layout.get("blocks")
                        or effective_layout.get("layout_blocks")
                        or []
                    )
            elif tb_by_page and len(tb_by_page) == 1:
                only_p, only_blocks = next(iter(tb_by_page.items()))
                inferred_p_idx = only_p
                candidate_blocks.extend(only_blocks)
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
                if best_p is not None and best_overlap >= 3:
                    inferred_p_idx = best_p
                    candidate_blocks.extend(tb_by_page[best_p])
                else:
                    page_known = False
            elif not tb_by_page:
                candidate_blocks.extend(
                    effective_layout.get("text_blocks")
                    or effective_layout.get("blocks")
                    or effective_layout.get("layout_blocks")
                    or []
                )
            else:
                page_known = False
        elif isinstance(effective_layout, (list, tuple)):
            candidate_blocks = list(effective_layout)
        else:
            for fb in getattr(effective_layout, "figure_bboxes", None) or []:
                fig_boxes_on_page.append(fb)
            figure_texts_on_page.extend(getattr(effective_layout, "figure_texts", None) or [])
            font_spans_on_page.extend(getattr(effective_layout, "font_spans", None) or [])
            candidate_blocks = list(
                getattr(effective_layout, "text_blocks", None)
                or getattr(effective_layout, "blocks", None)
                or []
            )

        # Normalize candidate_blocks and separate furniture / figure-internal labels / body blocks
        raw_page_hdr_texts: list[str] = []
        clean_page_blocks: list[dict[str, Any]] = []
        for item in candidate_blocks:
            if isinstance(item, str):
                b_txt = item.strip()
                b_type = "text"
                b_layer = "body"
                b_p_idx = None
                b_box = None
                b_spans = None
            elif isinstance(item, dict):
                b_txt = str(item.get("text") or "").strip()
                b_type = str(item.get("type") or item.get("label") or "text").split(".")[-1].lower()
                b_layer = str(item.get("content_layer") or item.get("layer") or "body").split(".")[-1].lower()
                b_p_idx = item.get("page_idx")
                b_box = item.get("bbox_1000") or item.get("bbox")
                b_spans = item.get("font_spans")
            else:
                b_txt = str(getattr(item, "text", "") or "").strip()
                b_type = str(getattr(item, "type", None) or getattr(item, "label", None) or "text").split(".")[-1].lower()
                b_layer = str(getattr(item, "content_layer", None) or getattr(item, "layer", None) or "body").split(".")[-1].lower()
                b_p_idx = getattr(item, "page_idx", None)
                b_box = getattr(item, "bbox_1000", None) or getattr(item, "bbox", None)
                b_spans = getattr(item, "font_spans", None)

            if not b_txt:
                continue
            if inferred_p_idx is not None and b_p_idx is not None and b_p_idx != inferred_p_idx:
                continue
            is_gl = _is_marginalia_or_glossary_note(b_txt)
            b_rect = _extract_rect_coords(b_box) if b_box is not None else None
            is_top_margin = bool(b_rect is not None and b_rect[3] <= 65.0 and b_type != "title")

            if (
                "furniture" in b_layer
                or b_type in ("header", "footer", "page_header", "page_footer", "furniture")
                or is_top_margin
            ) and not is_gl:
                _register_furn(b_txt)
                if "footer" not in b_type:
                    raw_page_hdr_texts.append(b_txt)
                continue

            if b_type in ("image", "picture", "figure", "table"):
                continue

            is_cb_callout = bool(
                item.get("is_callout_box") if isinstance(item, dict) else getattr(item, "is_callout_box", False)
            )
            if b_rect is not None and fig_boxes_on_page and b_type != "caption" and not is_cb_callout:
                if any(_bbox_overlap_ratio(b_rect, fb) >= 0.50 for fb in fig_boxes_on_page):
                    if not _is_figure_caption_line(b_txt, has_page_images=True):
                        figure_texts_on_page.append(b_txt)
                        continue

            if b_rect is not None and table_boxes_on_page:
                if any(_bbox_overlap_ratio(b_rect, tb) >= 0.50 for tb in table_boxes_on_page):
                    continue

            if len(b_txt) < 3 or re.fullmatch(r"\d{1,4}", b_txt):
                continue
            if not is_gl and _norm_furniture_key(b_txt) in furniture_norms:
                continue

            if b_spans and not font_spans_on_page:
                font_spans_on_page.extend(b_spans)
            if b_type in ("title", "section_header", "heading") and not is_gl:
                hn = _norm_furniture_key(b_txt)
                if hn:
                    body_heading_norms_on_page.add(hn)
                if b_rect is not None:
                    heading_bboxes_on_page.append((b_txt, b_rect))

            norm_entry: dict[str, Any] = {
                "type": b_type,
                "text": b_txt,
                "page_idx": b_p_idx,
                "is_glossary": is_gl,
                "is_callout_box": is_cb_callout,
            }
            if b_box is not None:
                norm_entry["bbox_1000"] = b_box
            clean_page_blocks.append(norm_entry)

        if 2 <= len(raw_page_hdr_texts) <= 6:
            _register_furn(" ".join(raw_page_hdr_texts))
            for i_h in range(len(raw_page_hdr_texts)):
                for j_h in range(len(raw_page_hdr_texts)):
                    if i_h != j_h:
                        _register_furn(f"{raw_page_hdr_texts[i_h]} {raw_page_hdr_texts[j_h]}")

        # 2a-ii. Strip lines matching furniture_norms (including joined page_header items) anywhere on page
        if furniture_norms and cleaned_text:
            opening_norms = {
                _norm_furniture_key(oh) for oh in (opening_headers or []) if _norm_furniture_key(oh)
            }
            seen_real_body_hdrs: set[str] = set()
            furn_filtered_lines: list[str] = []
            for ln in cleaned_text.splitlines():
                s_ln = ln.strip()
                if (
                    s_ln
                    and not s_ln.startswith(("![", "|", "<", "((" , "```"))
                    and not _is_marginalia_or_glossary_note(s_ln)
                ):
                    nf = _norm_furniture_key(s_ln)
                    nf_ns = re.sub(r"\s+", "", nf)
                    if (len(nf) >= 3 and nf in furniture_norms) or (len(nf_ns) >= 5 and nf_ns in furniture_nospace):
                        if nf in opening_norms:
                            furn_filtered_lines.append(ln)
                            continue
                        if nf in body_heading_norms_on_page and nf not in seen_real_body_hdrs and s_ln.startswith("#"):
                            seen_real_body_hdrs.add(nf)
                            furn_filtered_lines.append(ln)
                            continue
                        continue
                furn_filtered_lines.append(ln)
            cleaned_text = re.sub(r"\n{3,}", "\n\n", "\n".join(furn_filtered_lines)).strip()
            if opening_headers:
                for oh in reversed(opening_headers):
                    if oh.lstrip("#").strip().lower() not in cleaned_text.lower():
                        cleaned_text = f"{oh}\n\n{cleaned_text.strip()}"

        # 2b. Foreign-Language Hallucination Guard & Missing Column / Truncated Page Recovery
        clean_page_blocks = _sort_blocks_in_reading_order(clean_page_blocks)

        def _format_doc_block(blk: dict[str, Any]) -> str:
            bt = blk["text"]
            bty = blk["type"]
            igl = blk["is_glossary"]
            if (
                bty in ("title", "section_header", "heading")
                and not bt.startswith("#")
                and not igl
                and not _is_figure_caption_line(bt, has_page_images=bool(page_images))
            ):
                return f"## {bt}"
            if bty == "list_item" and not re.match(r"^(?:[-*•]|\d+[\.\)])\s+", bt) and not igl:
                return f"- {bt}"
            return bt

        rebuilt_from_pdf = False
        if page_known and clean_page_blocks:
            pdf_corpus = " ".join(b["text"] for b in clean_page_blocks) + " " + " ".join(opening_headers or [])
            pdf_word_tokens = re.findall(r"[a-zA-ZäöüÄÖÜß]{4,}", pdf_corpus.lower())
            pdf_word_set = set(pdf_word_tokens)

            if len(pdf_word_tokens) >= 25 or len(pdf_word_set) >= 20:
                vlm_prose = re.sub(r"!\[[^\]]*\]\([^)\n]*\)|<!--[^>]*-->", " ", cleaned_text)
                vlm_word_set = set(re.findall(r"[a-zA-ZäöüÄÖÜß]{4,}", vlm_prose.lower()))
                tbl_corpus = " ".join(str(t) for t in (page_tables or []))
                tbl_word_set = set(re.findall(r"[a-zA-ZäöüÄÖÜß]{4,}", tbl_corpus.lower()))
                recall = len(vlm_word_set & pdf_word_set) / max(1, len(pdf_word_set))
                non_matching_vlm = vlm_word_set - pdf_word_set - tbl_word_set

                is_hallucination = (
                    recall < 0.45
                    and len(non_matching_vlm) >= 6
                    and (len(non_matching_vlm) / max(1, len(vlm_word_set))) >= 0.45
                )
                is_severe_truncation = (
                    len(pdf_word_set) >= 50
                    and recall < 0.25
                    and len(vlm_word_set) < len(pdf_word_set) * 0.30
                )
                if is_hallucination or is_severe_truncation:
                    known_page_img_names = {os.path.basename(fn) for fn in (page_images or [])}
                    kept_local_imgs = [
                        m_img.group(0)
                        for m_img in re.finditer(r"!\[[^\]]*\]\(images/([^)\n]+)\)", cleaned_text)
                        if os.path.basename(m_img.group(1).strip()) not in known_page_img_names
                    ]
                    rebuilt_blocks: list[str] = []
                    seen_rebuilt_norms: set[str] = set()
                    for oh in opening_headers or []:
                        oh_n = _norm_furniture_key(oh)
                        if oh_n:
                            seen_rebuilt_norms.add(oh_n)
                        rebuilt_blocks.append(oh)
                    for cb in clean_page_blocks:
                        cb_n = _norm_furniture_key(cb["text"])
                        if cb["type"] in ("title", "section_header", "heading") and cb_n in seen_rebuilt_norms:
                            continue
                        if cb_n:
                            seen_rebuilt_norms.add(cb_n)
                        rebuilt_blocks.append(_format_doc_block(cb))

                    if kept_local_imgs:
                        ins_pos = 0
                        while ins_pos < len(rebuilt_blocks) and rebuilt_blocks[ins_pos].lstrip().startswith("#"):
                            ins_pos += 1
                        rebuilt_blocks = rebuilt_blocks[:ins_pos] + kept_local_imgs + rebuilt_blocks[ins_pos:]

                    cleaned_text = "\n\n".join(rebuilt_blocks)
                    rebuilt_from_pdf = True

        if not rebuilt_from_pdf and page_known and clean_page_blocks:
            stop_words_4 = {
                "aber", "alle", "allen", "aller", "also", "auch", "beim", "dann", "dass",
                "denn", "diese", "diesem", "diesen", "dieser", "dieses", "doch", "dort",
                "durch", "eine", "einem", "einen", "einer", "eines", "erst", "etwa",
                "ihre", "ihrem", "ihren", "ihrer", "immer", "jede", "jedem", "jeden",
                "jeder", "kann", "keine", "können", "mehr", "nach", "nicht", "noch",
                "oder", "ohne", "sein", "seine", "seinem", "seinen", "seiner", "sich",
                "sind", "sowie", "über", "unter", "viele", "vom", "während", "weil",
                "wenn", "werden", "wird", "wurde", "wurden", "zum", "zur",
            }
            norm_existing = re.sub(r"\W+", " ", cleaned_text).lower()
            orig_words_4 = {
                w for w in re.findall(r"[a-zA-ZäöüÄÖÜß0-9]{4,}", norm_existing) if w not in stop_words_4
            }
            orig_words_3 = set(re.findall(r"[a-zA-ZäöüÄÖÜß0-9]{3,}", norm_existing))
            recovered_word_sets: list[set[str]] = []

            cb_word_sets: list[set[str]] = [
                set(re.findall(r"[a-zA-ZäöüÄÖÜß0-9]{4,}", b["text"].lower()))
                for b in clean_page_blocks
            ]

            vlm_paras = [p.strip() for p in re.split(r"\n{2,}", cleaned_text.strip()) if p.strip()]
            vlm_para_ranks: list[int | None] = []
            opening_norm_set = {_norm_furniture_key(oh) for oh in (opening_headers or []) if _norm_furniture_key(oh)}
            for vp in vlm_paras:
                if _norm_furniture_key(vp) in opening_norm_set:
                    vlm_para_ranks.append(-1)
                    continue
                vp_words = set(re.findall(r"[a-zA-ZäöüÄÖÜß0-9]{4,}", vp.lower()))
                vp_norm = re.sub(r"\W+", " ", vp).strip().lower()
                best_cb_i: int | None = None
                best_sc = 0.0
                for cb_i, cb_ws in enumerate(cb_word_sets):
                    cb_norm = re.sub(r"\W+", " ", clean_page_blocks[cb_i]["text"]).strip().lower()
                    if cb_norm and (cb_norm in vp_norm or vp_norm in cb_norm):
                        best_cb_i = cb_i
                        best_sc = 1.0
                        break
                    if cb_ws and vp_words:
                        sc = len(vp_words & cb_ws) / min(len(vp_words), len(cb_ws))
                        if sc >= 0.45 and sc > best_sc:
                            best_sc = sc
                            best_cb_i = cb_i
                vlm_para_ranks.append(best_cb_i)

            recovered_with_rank: list[tuple[int, bool, dict[str, Any], str]] = []
            for cb_i, cb in enumerate(clean_page_blocks):
                b_txt = cb["text"]
                b_type = cb["type"]
                is_gl = cb["is_glossary"]
                is_hdr = b_type in ("title", "section_header", "heading")
                is_task_blk = bool(re.match(r"^(?:[A-Z]\d+|\d{1,2}[\.\)]?|[a-z]\))\s+[A-ZÄÖÜa-zäöü]{3,}", b_txt))
                if not (is_gl or len(b_txt) >= 25 or is_hdr or is_task_blk):
                    continue

                norm_b = re.sub(r"\W+", " ", b_txt).strip().lower()
                if not norm_b:
                    continue
                if norm_b in norm_existing or (len(norm_b) >= 30 and norm_b[:30] in norm_existing):
                    continue

                b_words_4 = [
                    w for w in re.findall(r"[a-zA-ZäöüÄÖÜß0-9]{4,}", norm_b) if w not in stop_words_4
                ]
                b_set_4 = set(b_words_4)
                if b_set_4 and any(
                    len(b_set_4 & r_ws) / len(b_set_4) >= 0.80 for r_ws in recovered_word_sets
                ):
                    continue

                if not is_hdr:
                    threshold = 0.75 if is_gl else 0.55
                    if b_words_4:
                        ov = sum(1 for w in b_words_4 if w in orig_words_4) / len(b_words_4)
                        if ov >= threshold:
                            continue
                    else:
                        b_words_3 = re.findall(r"[a-zA-ZäöüÄÖÜß0-9]{3,}", norm_b)
                        if not b_words_3:
                            continue
                        ov = sum(1 for w in b_words_3 if w in orig_words_3) / len(b_words_3)
                        if ov >= threshold:
                            continue

                formatted_b = _format_doc_block(cb)
                recovered_with_rank.append((cb_i, is_gl, cb, formatted_b))
                norm_existing = f"{norm_existing} {norm_b}"
                if b_set_4:
                    recovered_word_sets.append(b_set_4)

            if recovered_with_rank:
                if not vlm_paras:
                    cleaned_text = "\n\n".join(fb for _, _, _, fb in recovered_with_rank)
                else:
                    before_slot: dict[int, list[str]] = {}
                    tail_items: list[str] = []
                    tail_glossary: list[str] = []
                    for rec_rank, is_gl, cb, formatted_b in recovered_with_rank:
                        if is_gl and cb.get("bbox_1000") is None:
                            tail_glossary.append(formatted_b)
                            continue
                        target_vp: int | None = None
                        for vp_i, v_rank in enumerate(vlm_para_ranks):
                            if v_rank is not None and v_rank > rec_rank:
                                target_vp = vp_i
                                break
                        if target_vp is not None:
                            before_slot.setdefault(target_vp, []).append(formatted_b)
                        else:
                            tail_items.append(formatted_b)

                    merged_paras: list[str] = []
                    for vp_i, vp in enumerate(vlm_paras):
                        if vp_i in before_slot:
                            merged_paras.extend(before_slot[vp_i])
                        merged_paras.append(vp)
                    merged_paras.extend(tail_items)
                    merged_paras.extend(tail_glossary)
                    cleaned_text = "\n\n".join(merged_paras)

        # 2b-ii. Format or recover colored didactic / Steckbrief callout boxes (<Rahmen>)
        if clean_page_blocks and cleaned_text:
            cb_idx = 0
            while cb_idx < len(clean_page_blocks):
                cb_cur = clean_page_blocks[cb_idx]
                if cb_cur.get("is_callout_box") and fc.DIDACTIC_BOX_HEADER_RE.match(cb_cur["text"]):
                    grp_blocks = [cb_cur]
                    nxt_cb = cb_idx + 1
                    while nxt_cb < len(clean_page_blocks) and clean_page_blocks[nxt_cb].get("is_callout_box"):
                        if fc.DIDACTIC_BOX_HEADER_RE.match(clean_page_blocks[nxt_cb]["text"]):
                            break
                        grp_blocks.append(clean_page_blocks[nxt_cb])
                        nxt_cb += 1
                    hdr_clean = re.sub(r"^[#*_:\s]+|[#*_:\s]+$", "", grp_blocks[0]["text"]).strip()
                    if hdr_clean.isupper() and len(hdr_clean) >= 4:
                        hdr_clean = hdr_clean.capitalize()
                    sub_line = ""
                    prose_blks = grp_blocks[1:]
                    if len(prose_blks) >= 2 and len(prose_blks[0]["text"].split()) <= 10:
                        sub_line = re.sub(r"^[#*_]+|[#*_]+$", "", prose_blks[0]["text"]).strip()
                        prose_blks = prose_blks[1:]
                    prose_joined = " ".join(b["text"].strip() for b in prose_blks if b["text"].strip()).strip()
                    prose_words = {
                        w for w in re.findall(r"[a-zA-ZäöüÄÖÜß0-9]{4,}", prose_joined.lower()) if len(w) >= 4
                    }
                    if prose_words and f"#### {hdr_clean}".lower() not in cleaned_text.lower():
                        paras_cur = [p for p in re.split(r"\n{2,}", cleaned_text) if p.strip()]
                        wrapped_existing = False
                        for p_i_c, p_val in enumerate(paras_cur):
                            if "<Rahmen" in p_val or p_val.lstrip().startswith(("#", "![", "|")):
                                continue
                            pw_set = set(re.findall(r"[a-zA-ZäöüÄÖÜß0-9]{4,}", p_val.lower()))
                            if pw_set and len(pw_set & prose_words) / max(1, min(len(pw_set), len(prose_words))) >= 0.55:
                                body_inner = p_val.strip().strip("-").strip()
                                rahmen_inner = f"_{sub_line}_\n{body_inner}" if sub_line else body_inner
                                paras_cur[p_i_c] = f"#### {hdr_clean}\n\n<Rahmen>\n{rahmen_inner}\n</Rahmen>"
                                wrapped_existing = True
                                break
                        if wrapped_existing:
                            cleaned_text = re.sub(r"(?m)^[ \t]*---[ \t]*\n+", "", "\n\n".join(paras_cur)).strip()
                        elif prose_joined:
                            rahmen_inner = f"_{sub_line}_\n{prose_joined}" if sub_line else prose_joined
                            cleaned_text = f"{cleaned_text.rstrip()}\n\n#### {hdr_clean}\n\n<Rahmen>\n{rahmen_inner}\n</Rahmen>"
                    cb_idx = nxt_cb
                    continue
                cb_idx += 1

        # 2c. In-Figure Text Label Deduplication (strip orphan diagram labels outside figures)
        if figure_texts_on_page and cleaned_text:
            greek_tex_map = {
                r"\alpha": "α",
                r"\beta": "β",
                r"\gamma": "γ",
                r"\delta": "δ",
                r"\mu": "µ",
            }

            def _norm_fig_cmp(raw_s: str) -> str:
                tmp_s = raw_s.replace("\x04", "fi").replace("\x07", "fb")
                for k_g, v_g in greek_tex_map.items():
                    tmp_s = tmp_s.replace(k_g, v_g)
                tmp_s = tmp_s.replace("μ", "µ")
                return re.sub(r"\W+", " ", tmp_s).strip().lower()

            body_full_norm = " ".join(_norm_fig_cmp(b["text"]) for b in clean_page_blocks)
            body_line_norms = {
                _norm_fig_cmp(ln)
                for b in clean_page_blocks
                for ln in b["text"].splitlines()
                if ln.strip()
            }
            body_tokens = set(re.findall(r"[a-zA-ZäöüÄÖÜßαβγδµ0-9]{2,}", body_full_norm))
            fig_line_norms: set[str] = set()
            fig_tokens: set[str] = set()
            ft_joined = re.sub(
                r"([A-Za-zÄÖÜäöüß])-\s*\n\s*([a-zäöüß])",
                r"\1\2",
                "\n".join(str(ft) for ft in figure_texts_on_page),
            )
            for sub_l in [*[ln_f for ft in figure_texts_on_page for ln_f in str(ft).splitlines()], *ft_joined.splitlines()]:
                fn_n = _norm_fig_cmp(sub_l)
                if fn_n:
                    fig_line_norms.add(fn_n)
                    fig_tokens.update(re.findall(r"[a-zA-ZäöüÄÖÜßαβγδµ0-9]{2,}", fn_n))

            if fig_line_norms:
                has_any_img = bool(page_images) or ("![" in cleaned_text)
                has_layout_hdrs = bool(effective_layout)
                dedup_fig_lines: list[str] = []
                in_task_sec_fig = False
                for raw_ln in cleaned_text.splitlines():
                    s_ln = raw_ln.strip()
                    if not s_ln:
                        dedup_fig_lines.append(raw_ln)
                        continue
                    if re.match(r"^#{1,6}\s+", s_ln):
                        in_task_sec_fig = bool(_TASK_SECTION_HEADING_RE.match(s_ln))
                        if has_any_img and re.match(r"^#{1,6}\s+[A-F]\s*$", s_ln):
                            continue

                    if s_ln.startswith(("![", "|", "<", "((" , "```", "$$", "\\[")):
                        dedup_fig_lines.append(raw_ln)
                        continue
                    if _is_figure_caption_line(
                        s_ln,
                        has_page_images=has_any_img,
                        in_task_section=in_task_sec_fig,
                        major_heading_norms=major_heading_norms_on_page,
                        has_layout_headings=has_layout_hdrs,
                    ):
                        dedup_fig_lines.append(raw_ln)
                        continue
                    if (
                        in_task_sec_fig
                        or re.match(
                            r"^(?:#{1,6}\s+)?(?:[A-Z]\d+|\d{1,2}[\.\)]|Aufgabe\s+\d+|Übung\s+\d+|[a-z]\))\s+\S",
                            s_ln,
                            re.IGNORECASE,
                        )
                        or _TASK_IMPERATIVE_SIE_RE.search(s_ln)
                        or _TASK_IMPERATIVE_DU_START_RE.match(re.sub(r"^\d+\s+", "", s_ln))
                    ):
                        dedup_fig_lines.append(raw_ln)
                        continue

                    clean_cand = re.sub(r"^(?:#{1,6}\s+|[-*•]\s+)", "", s_ln).strip()
                    norm_cand = _norm_fig_cmp(clean_cand)
                    if s_ln.startswith("#"):
                        if (
                            norm_cand in body_heading_norms_on_page
                            or norm_cand in body_line_norms
                            or re.match(
                                r"^(?:\d|Aufgaben?|Übungen?|Material\b|Quellen?|[MBQ]\s*\d|Abb(?:ildung)?\b|"
                                r"Bild\b|Grafik\b|Tab(?:elle)?\b|Kapitel\b|im\s+blickpunkt\b|überblick\b|worterklärung)",
                                clean_cand,
                                re.IGNORECASE,
                            )
                            or fc.DIDACTIC_BOX_HEADER_RE.match(clean_cand)
                        ):
                            dedup_fig_lines.append(raw_ln)
                            continue
                    if (
                        not norm_cand
                        or len(clean_cand) > 85
                        or len(clean_cand.split()) > 10
                        or (len(clean_cand.split()) >= 6 and clean_cand.endswith((".", "!", "?")))
                    ):
                        dedup_fig_lines.append(raw_ln)
                        continue

                    cand_toks = re.findall(r"[a-zA-ZäöüÄÖÜßαβγδµ0-9]{2,}", norm_cand)
                    in_body_phrase = bool(re.search(rf"\b{re.escape(norm_cand)}\b", body_full_norm))
                    is_orphan_fig_label = False
                    if s_ln.startswith("#"):
                        if (
                            1 <= len(cand_toks) <= 4
                            and all(t in fig_tokens for t in cand_toks)
                            and not in_body_phrase
                        ):
                            is_orphan_fig_label = True
                    elif norm_cand in fig_line_norms and norm_cand not in body_line_norms and not in_body_phrase:
                        is_orphan_fig_label = True
                    elif (
                        cand_toks
                        and len(cand_toks) <= 8
                        and all(t in fig_tokens for t in cand_toks)
                        and not in_body_phrase
                        and any(t not in body_tokens for t in cand_toks)
                    ):
                        is_orphan_fig_label = True

                    if not is_orphan_fig_label:
                        dedup_fig_lines.append(raw_ln)

                cleaned_text = re.sub(r"\n{3,}", "\n\n", "\n".join(dedup_fig_lines)).strip()

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
        full_tag = m.group(0)
        if re.match(r"^!\[[^\]]*\]\(images/[A-Za-z0-9_\-./]+\.(?:png|jpe?g|webp|gif|svg)\)$", full_tag.strip(), re.I):
            return full_tag
        label = (m.group(1) or "").strip() if m.lastindex else ""
        if label and not generic_label_re.match(label) and not re.search(r"\.(?:png|jpe?g|gif|svg)$", label, re.I):
            return f"<Anmerkung> Abbildung nicht extrahiert: {label} </Anmerkung>"
        return ""

    if re.search(img_pattern, cleaned_text, flags=re.IGNORECASE):
        cleaned_text = re.sub(img_pattern, replace_ph, cleaned_text, flags=re.IGNORECASE)

    # 4. Scan lines to match explicit and bare-numbered captions and insert remaining images above them
    lines = cleaned_text.splitlines()
    new_lines: list[str] = []
    explicit_caption_re = re.compile(
        r"^(?:#{1,6}\s+)?(?:<Bild>\s*|\*+|_*)?(?:Abbildung|Abb\.|Bild|Grafik|Figure|Fig\.|Foto|Zeichnung|Diagramm|Schema)\s+[0-9IVXii]+.*",
        re.IGNORECASE,
    )
    in_task_section = False
    has_layout_hdrs_step4 = bool(effective_layout)

    for line in lines:
        stripped = line.strip()
        if re.match(r"^#{1,6}\s+", stripped):
            if _TASK_SECTION_HEADING_RE.match(stripped):
                in_task_section = True
            elif not _is_bare_numbered_caption(
                stripped,
                has_page_images=bool(remaining_images),
                in_task_section=False,
                major_heading_norms=major_heading_norms_on_page,
                has_layout_headings=has_layout_hdrs_step4,
            ):
                in_task_section = False

        prev_is_img = False
        for prev in reversed(new_lines):
            if prev.strip():
                if prev.strip().startswith("!["):
                    prev_is_img = True
                break

        is_explicit_cap = bool(explicit_caption_re.match(stripped))
        is_bare_cap = (
            False
            if is_explicit_cap
            else _is_bare_numbered_caption(
                stripped,
                has_page_images=bool(prev_is_img or remaining_images),
                in_task_section=in_task_section,
                major_heading_norms=major_heading_norms_on_page,
                has_layout_headings=has_layout_hdrs_step4,
            )
        )

        if is_explicit_cap or is_bare_cap:
            normalized_line = re.sub(r"^#{1,6}\s+", "", stripped)
            normalized_line = re.sub(r"^[\*_]+(.+?)[\*_]+$", r"\1", normalized_line)

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

    # 4c. Apply PDF Bold/SemiBold (**...**) and Italic (*...*) emphasis spans to body paragraphs
    if font_spans_on_page and cleaned_text:
        cleaned_text = _apply_pdf_font_spans_to_markdown(cleaned_text, font_spans_on_page)

    # 5. Place remaining unmatched images immediately after the opening heading block
    #    (or matched vertically by bbox_1000 y0 to the nearest preceding Material/section heading)
    if remaining_images:
        cur_lines = cleaned_text.splitlines()
        material_hdr_re = re.compile(
            r"^(?:#{1,6}\s+|\*\*|__)?(?:Material\s+[A-Z0-9]+|M\s*\d+)\b",
            re.IGNORECASE,
        )
        heading_line_indices: list[int] = [
            idx_l
            for idx_l, raw_l in enumerate(cur_lines)
            if re.match(r"^#{1,6}\s+\S", raw_l.strip())
            or (
                material_hdr_re.match(raw_l.strip())
                and (raw_l.strip().startswith("#") or re.match(r"^(?:\*\*|__).+(?:\*\*|__)$", raw_l.strip()))
            )
        ]

        insert_after_line: dict[int, list[str]] = {}
        placed_by_heading = False

        if heading_line_indices:
            # Resolve bbox_1000 (x0, y0) for each heading line if available
            hdr_coords_by_line: dict[int, tuple[float, float]] = {}
            for hl_idx in heading_line_indices:
                hl_clean = re.sub(r"^(?:#{1,6}\s+|\*\*|__)|(?:\*\*|__)$", "", cur_lines[hl_idx].strip()).strip()
                hl_norm = re.sub(r"\W+", " ", hl_clean).strip().lower()
                for hb_txt, hb_rect in heading_bboxes_on_page:
                    hb_norm = re.sub(r"\W+", " ", hb_txt).strip().lower()
                    if hb_norm and (hb_norm == hl_norm or hb_norm in hl_norm or hl_norm in hb_norm):
                        hdr_coords_by_line[hl_idx] = (hb_rect[0], hb_rect[1])
                        break

            # Determine end of the contiguous opening heading stack (e.g. '# Chapter' + '## 1.1 Section')
            first_non_marker_idx = 0
            while first_non_marker_idx < len(cur_lines):
                st_l = cur_lines[first_non_marker_idx].strip()
                if not st_l or re.fullmatch(r"\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)", st_l):
                    first_non_marker_idx += 1
                else:
                    break

            opens_with_heading = first_non_marker_idx in heading_line_indices
            opening_stack_end = heading_line_indices[0]
            if opens_with_heading:
                scan_i = first_non_marker_idx
                last_h = first_non_marker_idx
                while scan_i + 1 < len(cur_lines):
                    nxt_i = scan_i + 1
                    nxt_s = cur_lines[nxt_i].strip()
                    if not nxt_s:
                        scan_i = nxt_i
                        continue
                    if nxt_i in heading_line_indices and not (
                        material_hdr_re.match(cur_lines[last_h].strip())
                        and material_hdr_re.match(nxt_s)
                    ):
                        last_h = nxt_i
                        scan_i = nxt_i
                        continue
                    break
                opening_stack_end = last_h

            material_indices = [hi for hi in heading_line_indices if material_hdr_re.match(cur_lines[hi].strip())]

            if (
                len(heading_line_indices) >= 2
                and hdr_coords_by_line
                and any(os.path.basename(fn) in image_bboxes_by_basename for fn in remaining_images)
            ):
                for fn in remaining_images:
                    img_rect = image_bboxes_by_basename.get(os.path.basename(fn))
                    if img_rect is not None:
                        img_x0, img_y0 = img_rect[0], img_rect[1]
                        preceding = [
                            (hl_i, coords)
                            for hl_i, coords in hdr_coords_by_line.items()
                            if coords[1] <= img_y0 + 30.0
                        ]
                        if preceding:
                            best_hl = max(
                                preceding,
                                key=lambda item: (
                                    1 if abs(item[1][0] - img_x0) < 260.0 else 0,
                                    item[1][1],
                                    item[0],
                                ),
                            )[0]
                        else:
                            best_hl = opening_stack_end
                        if best_hl < opening_stack_end and opens_with_heading and not material_hdr_re.match(cur_lines[best_hl].strip()):
                            best_hl = opening_stack_end
                        insert_after_line.setdefault(best_hl, []).append(f"![](images/{fn})")
                    else:
                        insert_after_line.setdefault(opening_stack_end, []).append(f"![](images/{fn})")
                placed_by_heading = True
            elif len(material_indices) >= 2 and len(remaining_images) >= 2:
                for idx_img, fn in enumerate(remaining_images):
                    target_hl = material_indices[min(idx_img, len(material_indices) - 1)]
                    insert_after_line.setdefault(target_hl, []).append(f"![](images/{fn})")
                placed_by_heading = True
            elif opens_with_heading or len(heading_line_indices) == 1:
                target_hl = opening_stack_end if opens_with_heading else heading_line_indices[0]
                for fn in remaining_images:
                    insert_after_line.setdefault(target_hl, []).append(f"![](images/{fn})")
                placed_by_heading = True

        if placed_by_heading and insert_after_line:
            rebuilt_step5: list[str] = []
            for idx_l, raw_l in enumerate(cur_lines):
                rebuilt_step5.append(raw_l)
                if idx_l in insert_after_line:
                    rebuilt_step5.append("")
                    for img_md in insert_after_line[idx_l]:
                        rebuilt_step5.append(img_md)
                        rebuilt_step5.append("")
            cleaned_text = re.sub(r"\n{3,}", "\n\n", "\n".join(rebuilt_step5)).strip()
        else:
            appended_imgs = "\n\n".join([f"![](images/{fn})" for fn in remaining_images])
            page_marker_match = re.search(r"^(\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)\s*\n+)", cleaned_text)
            if page_marker_match:
                idx = page_marker_match.end()
                cleaned_text = cleaned_text[:idx] + appended_imgs + "\n\n" + cleaned_text[idx:]
            else:
                cleaned_text = appended_imgs + "\n\n" + cleaned_text

    # 6. Clean stray space after hyphens in broken words, normalize split decimal headings,
    #    and attach PDF 3-dot task difficulty tags ([1 Punkt]..[3 Punkte])
    cleaned_text = fc.INLINE_HYPHEN_SPACE_RE.sub(r"\1\2", cleaned_text)
    cleaned_text = normalize_split_decimal_headings(cleaned_text)

    task_diffs_on_page: list[dict[str, Any]] = []
    if isinstance(effective_layout, dict):
        td_by_page = effective_layout.get("task_difficulties_by_page") or {}
        if inferred_p_idx is not None and inferred_p_idx in td_by_page:
            task_diffs_on_page.extend(td_by_page[inferred_p_idx] or [])
        elif td_by_page and len(td_by_page) == 1 and inferred_p_idx is None:
            task_diffs_on_page.extend(next(iter(td_by_page.values())) or [])
        if effective_layout.get("task_difficulties"):
            task_diffs_on_page.extend(effective_layout.get("task_difficulties") or [])

    if task_diffs_on_page and cleaned_text:
        raw_dots_re = re.compile(
            r"[ \t]*(?:[•●○◦∙⋅]{3}|(?:[•●○◦∙⋅][ \t]+){2}[•●○◦∙⋅])[ \t]*"
        )
        td_lines = cleaned_text.splitlines()
        matched_line_to_pts: dict[int, int] = {}
        unmatched_entries: list[dict[str, Any]] = []

        for td_entry in task_diffs_on_page:
            pts_val = int(td_entry.get("points") or 0)
            if pts_val not in (1, 2, 3):
                continue
            anchor_raw = re.sub(r"[•●○◦∙⋅]+", "", str(td_entry.get("anchor") or "")).strip()
            anchor_cmp = re.sub(r"[\*_]+", "", anchor_raw).strip()
            hit_idx: int | None = None
            if anchor_cmp:
                for li_td, raw_td_ln in enumerate(td_lines):
                    if li_td in matched_line_to_pts:
                        continue
                    s_td = raw_td_ln.strip()
                    if not s_td or s_td.startswith(("![", "<Bild", "|", "((")):
                        continue
                    s_no_dots = raw_dots_re.sub("", s_td).strip()
                    s_plain = re.sub(r"[\*_]+", "", s_no_dots).strip()
                    if len(anchor_cmp) >= 3 and s_plain.endswith(anchor_cmp):
                        hit_idx = li_td
                        break
                    if (
                        len(anchor_cmp) >= 4
                        and anchor_cmp in s_plain[-max(70, len(anchor_cmp) + 20) :]
                    ):
                        hit_idx = li_td
                        break
                    if re.fullmatch(r"[A-LN-Z]?\d+[a-z]?[.:)]?", anchor_cmp) and re.match(
                        rf"^(?:#{{1,6}}\s+)?(?:[-*•]\s+)?(?:\*\*|_)?(?:Aufgabe\s+)?{re.escape(anchor_cmp.rstrip('.:)'))}(?:\*\*|_)?[.:)]?\s+\S",
                        s_no_dots,
                        re.IGNORECASE,
                    ):
                        hit_idx = li_td
                        break
            if hit_idx is not None:
                matched_line_to_pts[hit_idx] = pts_val
            else:
                unmatched_entries.append({"points": pts_val, "anchor": anchor_cmp})

        if unmatched_entries:
            seq_task_indices: list[int] = []
            in_aufg_td = False
            for li_td, raw_td_ln in enumerate(td_lines):
                s_td = raw_dots_re.sub("", raw_td_ln.strip()).strip()
                if not s_td:
                    continue
                if re.match(
                    r"^(?:#{1,6}\s+)?(?:\*\*|_)?Aufgaben?:?(?:\*\*|_)?\s*$",
                    s_td,
                    re.IGNORECASE,
                ):
                    in_aufg_td = True
                    continue
                if li_td in matched_line_to_pts:
                    continue
                m_t_cand = re.match(
                    r"^(?:#{1,6}\s+)?(?:[-*•]\s+)?(?:\*\*|_)?(?:Aufgabe\s+|Übung\s+)?([A-LN-Z]\d+|\d{1,2})(?:\*\*|_)?[.:)]?\s+([A-ZÄÖÜ].+)$",
                    s_td,
                )
                if m_t_cand:
                    body_cand = m_t_cand.group(2).strip()
                    if (
                        in_aufg_td
                        or _TASK_IMPERATIVE_SIE_RE.search(body_cand)
                        or _TASK_IMPERATIVE_DU_START_RE.match(body_cand)
                        or body_cand.endswith("?")
                    ):
                        seq_task_indices.append(li_td)
            for td_rem, li_seq in zip(unmatched_entries, seq_task_indices):
                matched_line_to_pts[li_seq] = int(td_rem["points"])

        for li_td, raw_td_ln in enumerate(td_lines):
            if li_td in matched_line_to_pts:
                pts_v = matched_line_to_pts[li_td]
                unit_lbl = "Punkt" if pts_v == 1 else "Punkte"
                base_ln = raw_dots_re.sub("", raw_td_ln).rstrip()
                if not fc.POINT_DIFFICULTY_TAG_RE.search(base_ln):
                    td_lines[li_td] = f"{base_ln} [{pts_v} {unit_lbl}]"
                else:
                    td_lines[li_td] = base_ln
            elif re.search(r"[•●○◦∙⋅]{3}\s*$", raw_td_ln):
                td_lines[li_td] = raw_dots_re.sub("", raw_td_ln).rstrip()

        cleaned_text = "\n".join(td_lines)

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

    # 0b. Strip PDF prepress bleed marks and InDesign print-production footer/slug blocks
    processed = fc.INDESIGN_FOOTER_BLOCK_RE.sub("", processed)
    processed = "\n".join(
        ln for ln in processed.splitlines() if not fc.PREPRESS_MARK_LINE_RE.match(ln)
    )
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

    # 7. Reorder column-swapped numbered task runs within the same section/page
    #    (e.g. right column tasks 4..10 followed by intro prose and left column tasks 1..3 -> intro, 1..10)
    boundary_re = re.compile(
        r"^(?:#{1,6}\s|\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)|\|"
        r"|</?(?:Tabelle|Rahmen|Anmerkung|Lückentext)\b)"
    )
    numbered_task_start_re = re.compile(
        r"^(?:\*\*|__)?([1-9]\d?)(?:\*\*|__)?(?:[\.\)](?!\d)|\s+(?=[A-ZÄÖÜ\[\(○◐●★◇◈◆]))\s*\S"
    )
    subtask_cont_re = re.compile(r"^[a-z]\)\s+")
    bild_start_re = re.compile(r"^<Bild\b", re.IGNORECASE)
    bild_end_re = re.compile(r"^</Bild>", re.IGNORECASE)

    def _is_bullet_block(block_lines: list[str]) -> bool:
        if block_lines and bild_start_re.match(block_lines[0].strip()):
            return False
        return any(ln.lstrip().startswith(("- ", "* ")) for ln in block_lines)

    def _reorder_plain_section(section_lines: list[str]) -> list[str]:
        items: list[tuple[int | None, list[str]]] = []
        cur_num: int | None = None
        cur_lines: list[str] = []
        idx = 0
        n_lines = len(section_lines)
        while idx < n_lines:
            ln = section_lines[idx]
            stripped = ln.strip()
            if not stripped:
                if cur_lines:
                    items.append((cur_num, cur_lines))
                    cur_num = None
                    cur_lines = []
                idx += 1
                continue
            if bild_start_re.match(stripped):
                if cur_lines:
                    items.append((cur_num, cur_lines))
                    cur_num = None
                    cur_lines = []
                bild_lines = [ln]
                idx += 1
                if not bild_end_re.match(stripped) and "</Bild>" not in stripped:
                    while idx < n_lines:
                        b_ln = section_lines[idx]
                        bild_lines.append(b_ln)
                        idx += 1
                        if bild_end_re.match(b_ln.strip()) or "</Bild>" in b_ln:
                            break
                items.append((None, bild_lines))
                continue
            in_bullet = bool(cur_lines and cur_num is None and cur_lines[0].lstrip().startswith(("- ", "* ")))
            m_task = None if in_bullet else numbered_task_start_re.match(stripped)
            if m_task:
                if cur_lines:
                    items.append((cur_num, cur_lines))
                cur_num = int(m_task.group(1))
                cur_lines = [ln]
                idx += 1
                continue
            if not cur_lines and items and items[-1][0] is not None and subtask_cont_re.match(stripped):
                items[-1][1].extend(["", ln])
                idx += 1
                continue
            cur_lines.append(ln)
            idx += 1
        if cur_lines:
            items.append((cur_num, cur_lines))

        if len(items) < 3:
            return section_lines

        new_items: list[tuple[int | None, list[str]]] = []
        changed = False
        pos = 0
        m_items = len(items)
        while pos < m_items:
            k = items[pos][0]
            if k is None:
                new_items.append(items[pos])
                pos += 1
                continue

            end1 = pos + 1
            while end1 < m_items and items[end1][0] == (items[end1 - 1][0] or 0) + 1:
                end1 += 1
            last_n = items[end1 - 1][0] or 0

            matched_swap = False
            if k >= 2 and last_n >= 3:
                for mid_len in (0, 1, 2):
                    mid_end = end1 + mid_len
                    if mid_end >= m_items:
                        break
                    if any(items[j][0] is not None or _is_bullet_block(items[j][1]) for j in range(end1, mid_end)):
                        break
                    if items[mid_end][0] != 1:
                        continue
                    end2 = mid_end + 1
                    while end2 < m_items and items[end2][0] == (items[end2 - 1][0] or 0) + 1:
                        end2 += 1
                    prefix_nums = [items[j][0] for j in range(mid_end, end2)]
                    if prefix_nums == list(range(1, k)):
                        new_items.extend(items[end1:mid_end])
                        new_items.extend(items[mid_end:end2])
                        new_items.extend(items[pos:end1])
                        pos = end2
                        changed = True
                        matched_swap = True
                        break

            if not matched_swap:
                new_items.extend(items[pos:end1])
                pos = end1

        if not changed:
            return section_lines

        rebuilt: list[str] = []
        if section_lines and not section_lines[0].strip():
            rebuilt.append("")
        for b_idx, (_, block_lines) in enumerate(new_items):
            if b_idx > 0:
                rebuilt.append("")
            rebuilt.extend(block_lines)
        if section_lines and not section_lines[-1].strip():
            rebuilt.append("")
        return rebuilt

    reordered_lines: list[str] = []
    sec_buf: list[str] = []
    for ln in final_lines:
        if boundary_re.match(ln.strip()):
            if sec_buf:
                reordered_lines.extend(_reorder_plain_section(sec_buf))
                sec_buf = []
            reordered_lines.append(ln)
        else:
            sec_buf.append(ln)
    if sec_buf:
        reordered_lines.extend(_reorder_plain_section(sec_buf))

    return "\n".join(reordered_lines)


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
    markdown_content = normalize_split_decimal_headings(markdown_content)

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

    markdown_content = img_before_cap_pattern.sub(_img_first_repl, markdown_content)

    # 3. Also associate standalone ![](images/...) immediately followed by a bare-numbered figure caption
    bare_img_cap_re = re.compile(
        r"(!\[(|image|img|bild|figure)\]\((?:images/)?([^)\n]+)\))\s*\n+([1-9][0-9]?[a-d]?\s+[A-ZÄÖÜ][^\n]{2,155})"
    )

    def _bare_img_cap_repl(match: re.Match) -> str:
        filename = match.group(3).strip()
        cand_cap = match.group(4).strip()
        if _is_bare_numbered_caption(cand_cap, has_page_images=True):
            return f"![{cand_cap}](images/{filename})\n\n{cand_cap}"
        return match.group(0)

    return bare_img_cap_re.sub(_bare_img_cap_repl, markdown_content)


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

    from backend.services.fibs_postprocess import strip_prepress_and_indesign_artifacts

    markdown_content = strip_prepress_and_indesign_artifacts(markdown_content)

    def _strip_page_number(s: str) -> tuple[str, bool]:
        m = re.match(
            r"^(?:\d{1,4}(?:\s*[-–—|/]\s*|\s+))?(.*?)(?:(?:\s*[-–—|/]\s*|\s+)\d{1,4})?$",
            s,
        )
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

            hdrs_by_page_idx: dict[Any, list[str]] = {}
            ftrs_by_page_idx: dict[Any, list[str]] = {}
            for b in blocks:
                if isinstance(b, dict) and b.get("type") in ["header", "footer", "page_header", "page_footer"]:
                    txt = b.get("text", "").strip()
                    nh = _norm_header(txt)
                    if nh and len(nh) > 2:
                        header_texts_norm.add(nh)
                        header_texts_nospace.add(_norm_nospace(txt))
                    p_key = b.get("page_idx", b.get("page_no"))
                    if p_key is not None and txt:
                        if "footer" in str(b.get("type", "")):
                            ftrs_by_page_idx.setdefault(p_key, []).append(txt)
                        else:
                            hdrs_by_page_idx.setdefault(p_key, []).append(txt)
            for grp_map in (hdrs_by_page_idx, ftrs_by_page_idx):
                for items in grp_map.values():
                    if 2 <= len(items) <= 6:
                        joined = " ".join(items)
                        nh_j = _norm_header(joined)
                        if nh_j and len(nh_j) > 2:
                            header_texts_norm.add(nh_j)
                            header_texts_nospace.add(_norm_nospace(joined))
                        for i_a in range(len(items)):
                            for i_b in range(len(items)):
                                if i_a != i_b:
                                    pair_str = f"{items[i_a]} {items[i_b]}"
                                    nh_p = _norm_header(pair_str)
                                    if nh_p and len(nh_p) > 2:
                                        header_texts_norm.add(nh_p)
                                        header_texts_nospace.add(_norm_nospace(pair_str))
        except Exception:
            pass

    start_boundary_lines = 2
    end_boundary_lines = 3
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
        result = [(i, "start") for i in content[:start_boundary_lines]]
        result += [(i, "end") for i in content[-end_boundary_lines:] if (i, "start") not in result]
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
