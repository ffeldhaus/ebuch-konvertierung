"""Fast post-upload directory check service using Docling.

Inspects at most the first 20 pages of an uploaded document without extracting
formulas, table structures, or images. Detects:
  - Inhaltsverzeichnis (Table of Contents)
  - Abbildungsverzeichnis (List of Figures)
  - Tabellenverzeichnis (List of Tables)
  - Bildverzeichnis (List of Pictures / Illustrations)

Uses the extracted directory entries to:
  1. Accurately determine physical/printed page numbers and page offsets,
     preventing false-positive page number detections on directory pages and
     recovering missing or misdetected page numbers on content pages.
  2. Reconstruct accurate heading levels (# H1, ## H2, ### H3, #### H4) by
     combining numbering schemes, visual indentation (bounding box x-offset),
     font height, and hierarchical parent-child context from the TOC.
"""

import json
import logging
import os
import re
from typing import Any

import pypdfium2 as pdfium

logger = logging.getLogger(__name__)

# Maximum number of pages inspected during the fast post-upload directory check
MAX_DIRECTORY_CHECK_PAGES = 20

# In-memory cache keyed by (abs_path, mtime_ns, size, max_pages)
_DIRECTORY_CACHE: dict[tuple[str, int, int, int], dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Fast Docling Pipeline Configuration (no formulas, no tables, no images)
# ---------------------------------------------------------------------------

try:
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    _HAS_DOCLING = True
except Exception as e:  # pragma: no cover
    logger.warning(f"Docling not available for fast directory check: {e}")
    _HAS_DOCLING = False
    PdfPipelineOptions = None  # type: ignore

try:
    from docling.pipeline.native_pdf_pipeline import NativePdfPipeline, NativePdfPipelineOptions
except Exception:  # pragma: no cover
    NativePdfPipeline = None  # type: ignore
    NativePdfPipelineOptions = PdfPipelineOptions  # type: ignore

if PdfPipelineOptions is not None:
    class FastDirectoryPipelineOptions(NativePdfPipelineOptions):  # type: ignore[misc,valid-type]
        """Ultra-fast native PDF pipeline options for directory checking.
        Explicitly disables formula enrichment, table structure, code enrichment,
        and image generation so that checking up to 20 pages completes in < 0.5s.
        """
        do_ocr: bool = False
        do_table_structure: bool = False
        do_code_enrichment: bool = False
        do_formula_enrichment: bool = False
        do_picture_classification: bool = False
        do_picture_description: bool = False
        generate_page_images: bool = False
        generate_picture_images: bool = False
        generate_table_images: bool = False
        generate_parsed_pages: bool = False
else:  # pragma: no cover
    FastDirectoryPipelineOptions = None  # type: ignore



def build_fast_docling_pipeline_options(do_ocr: bool = False):
    """Returns a Docling PdfPipelineOptions instance configured for fast directory
    inspection (no formula enrichment, no table structure, no picture/page images).
    """
    if PdfPipelineOptions is None:
        return None
    opts = PdfPipelineOptions()
    opts.do_ocr = do_ocr
    opts.do_table_structure = False
    opts.do_code_enrichment = False
    opts.do_formula_enrichment = False
    opts.do_picture_classification = False
    opts.do_picture_description = False
    opts.generate_page_images = False
    opts.generate_picture_images = False
    opts.generate_table_images = False
    opts.generate_parsed_pages = True
    return opts


# ---------------------------------------------------------------------------
# Heading & Entry Regex Patterns
# ---------------------------------------------------------------------------

DIRECTORY_HEADER_PATTERNS: dict[str, re.Pattern] = {
    "toc": re.compile(
        r"^(?:#{1,6}\s*)?(?:\*\*|__|_|\*)?\s*"
        r"(?:Inhaltsverzeichnis|Inhaltsübersicht|Inhalt|Table\s+of\s+Contents|Contents)"
        r"\s*(?:\*\*|__|_|\*)?\s*:?\s*$",
        re.IGNORECASE,
    ),
    "figures": re.compile(
        r"^(?:#{1,6}\s*)?(?:\*\*|__|_|\*)?\s*"
        r"(?:Abbildungsverzeichnis|Verzeichnis\s+der\s+Abbildungen|List\s+of\s+Figures)"
        r"\s*(?:\*\*|__|_|\*)?\s*:?\s*$",
        re.IGNORECASE,
    ),
    "tables": re.compile(
        r"^(?:#{1,6}\s*)?(?:\*\*|__|_|\*)?\s*"
        r"(?:Tabellenverzeichnis|Verzeichnis\s+der\s+Tabellen|List\s+of\s+Tables)"
        r"\s*(?:\*\*|__|_|\*)?\s*:?\s*$",
        re.IGNORECASE,
    ),
    "pictures": re.compile(
        r"^(?:#{1,6}\s*)?(?:\*\*|__|_|\*)?\s*"
        r"(?:Bildverzeichnis|Bilderverzeichnis|Bildquellenverzeichnis|"
        r"Quellen-\s*und\s*Bildverzeichnis|Verzeichnis\s+der\s+Bilder|List\s+of\s+Illustrations)"
        r"\s*(?:\*\*|__|_|\*)?\s*:?\s*$",
        re.IGNORECASE,
    ),
}

DIRECTORY_TYPE_LABELS: dict[str, str] = {
    "toc": "Inhaltsverzeichnis",
    "figures": "Abbildungsverzeichnis",
    "tables": "Tabellenverzeichnis",
    "pictures": "Bildverzeichnis",
}

# Matches a directory line ending with leader dots/spaces and a page number:
# e.g. "5.1 Interferenz und Beugung am Doppelspalt ............ 45"
# or   "Abb. 5.1: Interferenzmuster am Doppelspalt   S. 45"
_ENTRY_WITH_PAGE_RE = re.compile(
    r"^(?P<title>.+?)"
    r"(?:\s*(?:[\.\·\•…_]{2,}|\t+|\s{2,})\s*|\s+)"
    r"(?:(?:Seite|S\.|p\.|pp\.)\s*)?"
    r"(?P<page>\d{1,4})\s*$",
    re.IGNORECASE,
)

# Prefixes identifying figure, table, or picture entries
_FIGURE_PREFIX_RE = re.compile(
    r"^(?:Abb(?:ildung)?\.?|Fig(?:ure)?\.?|Diagramm|Grafik|Karte|Schema)\s*"
    r"(?P<num>\d+(?:[\.\-]\d+)*[a-z]?)\s*[:\.\-–]?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
_TABLE_PREFIX_RE = re.compile(
    r"^(?:Tab(?:elle)?\.?|Table)\s*"
    r"(?P<num>\d+(?:[\.\-]\d+)*[a-z]?)\s*[:\.\-–]?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
_PICTURE_PREFIX_RE = re.compile(
    r"^(?:Bild|Foto|Zeichnung|Illustration|Tafel)\s*"
    r"(?P<num>\d+(?:[\.\-]\d+)*[a-z]?)\s*[:\.\-–]?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

# Structural numbering prefixes for TOC entries
_CHAPTER_PREFIX_RE = re.compile(
    r"^(?P<kw>Kapitel|Chapter|Teil|Part|Modul|Module|Lektion|Unit)\s+"
    r"(?P<num>[0-9IVXLCDM]+)\s*[:\.\-–]?\s*(?P<rest>.+)$",
    re.IGNORECASE,
)
_DECIMAL_PREFIX_RE = re.compile(
    r"^(?P<num>\d+(?:\.\d+)*)\.?\s+(?P<rest>.+)$"
)
_ROMAN_PREFIX_RE = re.compile(
    r"^(?P<num>[IVXLCDM]+)\.\s+(?P<rest>[A-ZÄÖÜ].+)$"
)
_LETTER_PREFIX_RE = re.compile(
    r"^(?P<num>[A-Z](?:\.\d+)?)\.\s+(?P<rest>.+)$"
)


def _normalize_text_for_match(text: str) -> str:
    """Normalizes a heading or caption string for robust fuzzy/exact comparison."""
    if not text:
        return ""
    s = re.sub(r"^#{1,6}\s*", "", text.strip())
    s = re.sub(r"[\*_`~]+", "", s)
    # Remove trailing page numbers / leader dots if present
    s = re.sub(r"(?:\s*[\.\·\•…]{2,}\s*|\s{2,})(?:S\.?\s*|Seite\s*)?\d{1,4}\s*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip(" :.-–\t")
    return s.lower()


def _strip_section_number(text: str) -> str:
    """Strips leading chapter/section numbering (e.g. 'Kapitel 5:', '5.1', 'Abb. 5.1:') from a title."""
    s = re.sub(r"^#{1,6}\s*", "", text.strip())
    s = re.sub(r"[\*_`~]+", "", s).strip()
    m_ch = _CHAPTER_PREFIX_RE.match(s)
    if m_ch:
        return m_ch.group("rest").strip()
    for rx in (_FIGURE_PREFIX_RE, _TABLE_PREFIX_RE, _PICTURE_PREFIX_RE):
        m_p = rx.match(s)
        if m_p and m_p.group("rest").strip():
            return m_p.group("rest").strip()
    m_dec = _DECIMAL_PREFIX_RE.match(s)
    if m_dec:
        return m_dec.group("rest").strip()
    m_rom = _ROMAN_PREFIX_RE.match(s)
    if m_rom:
        return m_rom.group("rest").strip()
    return s


# ---------------------------------------------------------------------------
# Fast Docling Page Line Extraction
# ---------------------------------------------------------------------------

def _cluster_docling_items_into_lines(items_on_page: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Groups Docling text items that share the same visual horizontal line
    (e.g. left-aligned TOC title and right-aligned page number) into unified lines,
    preserving the leftmost x-coordinate (`indent`) and font height (`height`).
    """
    if not items_on_page:
        return []

    # Sort top-to-bottom (in bottom-left PDF coordinates, higher y_mid is higher on page;
    # in top-left coordinates, smaller y_mid is higher on page).
    # Docling bbox has coord_origin (usually BOTTOMLEFT in native_pdf_pipeline).
    first_origin = items_on_page[0].get("origin", "BOTTOMLEFT")
    reverse_y = "BOTTOM" in str(first_origin).upper()

    sorted_items = sorted(
        items_on_page,
        key=lambda it: (-it["y_mid"] if reverse_y else it["y_mid"], it["l"]),
    )

    clusters: list[dict[str, Any]] = []
    for it in sorted_items:
        placed = False
        for cl in clusters:
            tol = max(5.5, min(cl["height"], it["height"]) * 0.65)
            if abs(it["y_mid"] - cl["y_mid"]) <= tol:
                cl["items"].append(it)
                cl["l"] = min(cl["l"], it["l"])
                cl["r"] = max(cl["r"], it["r"])
                cl["height"] = max(cl["height"], it["height"])
                # Update running average y_mid
                cl["y_mid"] = sum(x["y_mid"] for x in cl["items"]) / len(cl["items"])
                placed = True
                break
        if not placed:
            clusters.append({
                "y_mid": it["y_mid"],
                "l": it["l"],
                "r": it["r"],
                "height": it["height"],
                "items": [it],
            })

    lines_out: list[dict[str, Any]] = []
    for cl in clusters:
        cl_items = sorted(cl["items"], key=lambda x: x["l"])
        parts = []
        prev_r = None
        for x in cl_items:
            txt = x["text"].strip()
            if not txt:
                continue
            if prev_r is not None and (x["l"] - prev_r) > 25.0:
                parts.append("   " + txt)
            else:
                parts.append(txt)
            prev_r = x["r"]
        full_text = " ".join(parts).strip()
        if full_text:
            lines_out.append({
                "text": full_text,
                "indent": round(float(cl["l"]), 2),
                "right": round(float(cl["r"]), 2),
                "height": round(float(cl["height"]), 2),
                "y_mid": round(float(cl["y_mid"]), 2),
            })

    return lines_out


def _extract_lines_with_pypdfium(pdf_path: str, max_pages: int) -> tuple[int, list[list[dict[str, Any]]], list[str]]:
    """Extracts structured lines (with bounding-box x-indentation) and full page text
    from the PDF using pypdfium2.
    """
    try:
        doc = pdfium.PdfDocument(pdf_path)
    except Exception as e:
        logger.debug(f"Could not open PDF with pypdfium2 for directory check ({pdf_path}): {e}")
        return 0, [], []
    total_pages = len(doc)
    check_count = min(total_pages, max_pages)
    pages_lines: list[list[dict[str, Any]]] = []
    all_page_texts: list[str] = []

    try:
        for idx in range(total_pages):
            page = doc[idx]
            textpage = page.get_textpage()
            raw_text = textpage.get_text_range() or ""
            all_page_texts.append(raw_text)

            if idx < check_count:
                lines_list: list[dict[str, Any]] = []
                for raw_line in raw_text.splitlines():
                    stripped = raw_line.strip()
                    if not stripped:
                        continue
                    lines_list.append({
                        "text": stripped,
                        "indent": 48.0,
                        "right": 500.0,
                        "height": 10.0,
                        "y_mid": 0.0,
                    })
                pages_lines.append(lines_list)
            textpage.close()
    finally:
        doc.close()

    return total_pages, pages_lines, all_page_texts


def _extract_pages_with_docling_fast(
    file_path: str, max_pages: int = MAX_DIRECTORY_CHECK_PAGES
) -> tuple[int, list[list[dict[str, Any]]], list[str]]:
    """Uses Docling (capped to `max_pages`, with formula/table/image extraction disabled)
    to extract positioned text lines from the first `max_pages` pages.
    Returns (total_pages, pages_lines_for_checked_pages, all_page_texts).
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".docx":
        if _HAS_DOCLING:
            try:
                from docling.datamodel.base_models import InputFormat
                from docling.document_converter import DocumentConverter

                converter = DocumentConverter(allowed_formats=[InputFormat.DOCX])
                res = converter.convert(file_path)
                lines_list: list[dict[str, Any]] = []
                full_texts: list[str] = []
                for item, level in res.document.iterate_items():
                    txt = getattr(item, "text", "").strip()
                    if txt:
                        lines_list.append({
                            "text": txt,
                            "indent": float(level * 18),
                            "right": 500.0,
                            "height": 12.0,
                            "y_mid": 0.0,
                        })
                        full_texts.append(txt)
                return 1, [lines_list], ["\n".join(full_texts)]
            except Exception as e:
                logger.warning(f"Docling DOCX directory check fallback: {e}")
        return 1, [[]], [""]

    # PDF handling: first read total_pages and raw page texts via pypdfium2
    total_pages, fallback_lines, all_page_texts = _extract_lines_with_pypdfium(file_path, max_pages)
    if total_pages == 0 or not _HAS_DOCLING:
        return total_pages, fallback_lines, all_page_texts

    check_count = min(total_pages, max_pages)

    # Check if the first checked pages have embedded digital text
    checked_char_count = sum(len(t.strip()) for t in all_page_texts[:check_count])
    has_digital_text = checked_char_count >= 40

    if has_digital_text and NativePdfPipeline is None:
        return total_pages, fallback_lines, all_page_texts

    try:
        from docling.datamodel.base_models import InputFormat
        from docling.document_converter import DocumentConverter, PdfFormatOption

        if has_digital_text and NativePdfPipeline is not None and FastDirectoryPipelineOptions is not None:
            fast_opts = FastDirectoryPipelineOptions()
            converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(
                        pipeline_cls=NativePdfPipeline,
                        pipeline_options=fast_opts,
                    )
                }
            )
        else:
            # Scanned PDF without text layer: use fast PdfPipelineOptions (no tables/formulas/images)
            pdf_opts = build_fast_docling_pipeline_options(do_ocr=not has_digital_text)
            converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_opts)
                }
            )

        conv_res = converter.convert(file_path, page_range=(1, check_count))
        doc = conv_res.document

        per_page_raw_items: dict[int, list[dict[str, Any]]] = {p: [] for p in range(1, check_count + 1)}
        for item, _level in doc.iterate_items():
            txt = getattr(item, "text", None)
            if not txt or not txt.strip():
                continue
            prov_list = getattr(item, "prov", None)
            if prov_list and len(prov_list) > 0:
                prov = prov_list[0]
                page_no = int(getattr(prov, "page_no", 1))
                bbox = getattr(prov, "bbox", None)
                if bbox is not None and 1 <= page_no <= check_count:
                    l_val = float(getattr(bbox, "l", 48.0))
                    r_val = float(getattr(bbox, "r", 500.0))
                    t_val = float(getattr(bbox, "t", 0.0))
                    b_val = float(getattr(bbox, "b", 0.0))
                    origin = str(getattr(bbox, "coord_origin", "BOTTOMLEFT"))
                    height = abs(t_val - b_val) or 10.0
                    y_mid = (t_val + b_val) / 2.0
                    per_page_raw_items[page_no].append({
                        "text": txt.strip(),
                        "l": l_val,
                        "r": r_val,
                        "height": height,
                        "y_mid": y_mid,
                        "origin": origin,
                    })

        pages_lines: list[list[dict[str, Any]]] = []
        for p_no in range(1, check_count + 1):
            clustered = _cluster_docling_items_into_lines(per_page_raw_items.get(p_no, []))
            if clustered:
                pages_lines.append(clustered)
            elif p_no - 1 < len(fallback_lines):
                pages_lines.append(fallback_lines[p_no - 1])
            else:
                pages_lines.append([])

        return total_pages, pages_lines, all_page_texts
    except Exception as e:
        logger.warning(f"Fast Docling directory check fell back to pypdfium2 on {file_path}: {e}")
        return total_pages, fallback_lines, all_page_texts


# ---------------------------------------------------------------------------
# Directory Line Parsing & Heading Level Inference
# ---------------------------------------------------------------------------

def _match_directory_header(line_text: str) -> str | None:
    """Returns the directory type key ('toc', 'figures', 'tables', 'pictures')
    if `line_text` is a directory heading, otherwise None.
    """
    cleaned = line_text.strip()
    if not cleaned or len(cleaned) > 90:
        return None
    # Strip trailing page number if a running header or TOC lists the directory itself without dots
    if re.search(r"[\.\·…]{2,}\s*\d+\s*$", cleaned):
        return None
    for dir_key, pattern in DIRECTORY_HEADER_PATTERNS.items():
        if pattern.match(cleaned):
            return dir_key
    return None


def _parse_directory_entry_line(
    line_info: dict[str, Any], active_dir_type: str, page_idx: int
) -> dict[str, Any] | None:
    """Attempt to parse a single line inside an active directory section into a structured entry."""
    raw_text = line_info.get("text", "").strip()
    if not raw_text or len(raw_text) < 3:
        return None

    # Ignore running headers / footers like "Seite 44" or standalone numbers
    if re.match(r"^(?:Seite|Page|S\.)?\s*\d{1,4}$", raw_text, re.IGNORECASE):
        return None

    m = _ENTRY_WITH_PAGE_RE.match(raw_text)
    if not m:
        return None

    title_part = m.group("title").strip()
    # Clean trailing leader dots, dashes, or tabs from title_part
    title_part = re.sub(r"[\s\.\·\•…_]+$", "", title_part).strip()
    # Strip markdown heading hashes or bold markers if present
    title_part = re.sub(r"^#{1,6}\s*", "", title_part).strip()
    title_part = re.sub(r"^(?:\*\*|__)+(.+?)(?:\*\*|__)+$", r"\1", title_part).strip()

    if not title_part or len(title_part) < 2:
        return None
    # Must contain at least one letter
    if not re.search(r"[a-zA-ZäöüÄÖÜß]", title_part):
        return None

    target_page = int(m.group("page"))
    if target_page <= 0 or target_page > 5000:
        return None

    # Determine specific entry subtype from prefix if unambiguous
    entry_type = active_dir_type
    label = None
    number = None
    clean_title = title_part

    m_fig = _FIGURE_PREFIX_RE.match(title_part)
    m_tab = _TABLE_PREFIX_RE.match(title_part)
    m_pic = _PICTURE_PREFIX_RE.match(title_part)

    if m_fig:
        entry_type = "figures"
        number = m_fig.group("num")
        label = f"Abb. {number}"
        clean_title = m_fig.group("rest").strip() or title_part
    elif m_tab:
        entry_type = "tables"
        number = m_tab.group("num")
        label = f"Tab. {number}"
        clean_title = m_tab.group("rest").strip() or title_part
    elif m_pic:
        entry_type = "pictures"
        number = m_pic.group("num")
        label = f"Bild {number}"
        clean_title = m_pic.group("rest").strip() or title_part
    else:
        # Check TOC numbering patterns
        m_ch = _CHAPTER_PREFIX_RE.match(title_part)
        m_dec = _DECIMAL_PREFIX_RE.match(title_part)
        m_rom = _ROMAN_PREFIX_RE.match(title_part)
        m_let = _LETTER_PREFIX_RE.match(title_part)
        if m_ch:
            number = f"{m_ch.group('kw')} {m_ch.group('num')}"
            clean_title = m_ch.group("rest").strip()
        elif m_dec:
            number = m_dec.group("num")
            clean_title = m_dec.group("rest").strip()
        elif m_rom:
            number = m_rom.group("num")
            clean_title = m_rom.group("rest").strip()
        elif m_let:
            number = m_let.group("num")
            clean_title = m_let.group("rest").strip()

    return {
        "type": entry_type,
        "title": title_part,
        "clean_title": clean_title,
        "number": number,
        "label": label,
        "page": target_page,
        "indent": float(line_info.get("indent", 48.0)),
        "height": float(line_info.get("height", 10.0)),
        "directory_page_idx": page_idx,
    }


def _infer_toc_heading_levels(toc_entries: list[dict[str, Any]]) -> None:
    """Infers the semantic heading level (1..4, corresponding to # .. ####) for each
    entry in `toc_entries` in-place, combining:
      1. Explicit numbering (Kapitel X -> 1, 5.1 -> 2, 5.1.1 -> 3, 5.1.1.1 -> 4)
      2. Visual x-indentation clusters (`indent` from Docling bbox)
      3. Hierarchical parent-child context for unnumbered subsections.
    """
    if not toc_entries:
        return

    # Cluster distinct left-indentation tiers (separated by >= 7 pt)
    indents = sorted(set(round(e.get("indent", 48.0), 1) for e in toc_entries))
    indent_tiers: list[float] = []
    for val in indents:
        if not indent_tiers or (val - indent_tiers[-1]) >= 7.0:
            indent_tiers.append(val)

    def _get_indent_rank(indent_val: float) -> int:
        if not indent_tiers:
            return 0
        best_idx = 0
        best_dist = abs(indent_val - indent_tiers[0])
        for idx, t_val in enumerate(indent_tiers):
            d = abs(indent_val - t_val)
            if d < best_dist:
                best_dist = d
                best_idx = idx
        return best_idx

    current_level = 1
    last_numbered_level = 1
    last_indent_rank = 0

    for entry in toc_entries:
        title = entry["title"]
        indent_rank = _get_indent_rank(entry.get("indent", 48.0))

        # 1. Explicit Chapter / Part / Module prefix -> H1
        if _CHAPTER_PREFIX_RE.match(title):
            lvl = 1
            last_numbered_level = 1
        # 2. Decimal numbering: '5' -> H1, '5.1' -> H2, '5.1.1' -> H3, '5.1.1.1' -> H4
        elif (m_dec := _DECIMAL_PREFIX_RE.match(title)):
            num_str = m_dec.group("num")
            dots = num_str.count(".")
            lvl = min(dots + 1, 4)
            last_numbered_level = lvl
        # 3. Roman numerals: I., II., III. -> H3 (or H2 if at top level)
        elif _ROMAN_PREFIX_RE.match(title):
            lvl = 3 if last_numbered_level >= 2 else 2
            last_numbered_level = lvl
        # 4. Lettered sections: A. -> H2, A.1 -> H3
        elif (m_let := _LETTER_PREFIX_RE.match(title)):
            lvl = 3 if "." in m_let.group("num") else 2
            last_numbered_level = lvl
        else:
            # Unnumbered TOC entry: combine visual indentation rank with parent heading context
            if len(indent_tiers) >= 2 and indent_rank > 0:
                # Map visual indent tier relative to parent structure, capped at 4
                lvl = min(max(indent_rank + 1, last_numbered_level + 1), 4)
                if indent_rank > last_indent_rank and current_level >= 3:
                    lvl = min(current_level + 1, 4)
            else:
                # Fallback when all TOC lines share the same left margin (e.g. plain text TOC):
                # An unnumbered entry inside an H2 section becomes H3; sub-keywords or deeper items become H4
                if re.match(
                    r"^(?:Herleitung|Exkurs|Vertiefung|Detail|Anwendung|Beweis|Spezialfall)\b",
                    title,
                    re.IGNORECASE,
                ) and current_level >= 3:
                    lvl = 4
                else:
                    lvl = min(last_numbered_level + 1, 4)

        entry["level"] = int(max(1, min(lvl, 4)))
        current_level = entry["level"]
        last_indent_rank = indent_rank


# ---------------------------------------------------------------------------
# Page Number Resolution via Directory Cross-Referencing
# ---------------------------------------------------------------------------

def _entry_matches_page_text(entry: dict[str, Any], norm_page_text: str) -> int:
    """Checks whether a directory entry (`toc`, `figures`, `tables`, `pictures`)
    appears on a given PDF page's normalized text.
    Returns a confidence weight (0 = no match, 2 = strong token match, 3 = exact substring match).
    """
    if not norm_page_text:
        return 0

    candidates = []
    if entry.get("title"):
        candidates.append(_normalize_text_for_match(entry["title"]))
    if entry.get("clean_title"):
        candidates.append(_normalize_text_for_match(entry["clean_title"]))
    if entry.get("label"):
        candidates.append(_normalize_text_for_match(entry["label"]))

    for cand in candidates:
        if len(cand) >= 5 and cand in norm_page_text:
            return 3

    # Token overlap check for longer titles (handles soft wraps or hyphenation on the target page)
    clean_norm = _normalize_text_for_match(entry.get("clean_title") or entry.get("title") or "")
    tokens = [t for t in re.findall(r"[a-zA-ZäöüÄÖÜß0-9]{4,}", clean_norm)]
    if len(tokens) >= 2:
        matched = sum(1 for t in tokens if t in norm_page_text)
        if matched == len(tokens) or ( len(tokens) >= 3 and matched >= len(tokens) - 1 ):
            return 2

    return 0


def _detect_printed_number_ignoring_directory_lines(
    page_text: str, is_directory_page: bool
) -> int | None:
    """Extracts a printed header/footer page number from `page_text`.
    On directory pages (`is_directory_page=True`), only explicit 'Seite X' / 'S. X'
    or standalone numbers are accepted so that the target page number at the end
    of a directory entry line ('Bild 5.2: ... 47') is never mistaken for the
    directory page's own page number.
    """
    lines = [ln.strip() for ln in (page_text or "").splitlines() if ln.strip()]
    if not lines:
        return None

    # 1. Explicit "Seite X" / "Page X" in first 2 or last 2 lines
    boundary_lines = lines[:2] + list(reversed(lines[-2:]))
    for line in boundary_lines:
        # Skip lines with leader dots (e.g. "... S. 45" in a directory entry)
        if re.search(r"[\.\·…]{2,}", line):
            continue
        m = re.search(r"\b(?:[sS]eite|[pP]age)\s*(\d{1,4})\b", line)
        if m:
            return int(m.group(1))

    # 2. Standalone page number in footer (last 2 lines) or header (first 2 lines)
    for line in reversed(lines[-2:]):
        m = re.match(r"^(\d{1,4})$", line)
        if m:
            return int(m.group(1))
    for line in lines[:2]:
        m = re.match(r"^(\d{1,4})$", line)
        if m:
            return int(m.group(1))

    # 3. Alternating running header/footer ('44 Kapitel 5' or 'Kapitel 5 | 44')
    # NEVER apply the trailing-number heuristic on a directory page because directory
    # lines naturally end with target page numbers!
    if not is_directory_page:
        for line in reversed(lines[-2:]):
            m = re.match(r"^(\d{1,4})\s+[a-zA-ZäöüÄÖÜß]", line)
            if m:
                return int(m.group(1))
            m = re.search(r"[a-zA-ZäöüÄÖÜß]\s+(\d{1,4})$", line)
            if m:
                return int(m.group(1))
        for line in lines[:2]:
            m = re.match(r"^(\d{1,4})\s+[a-zA-ZäöüÄÖÜß]", line)
            if m:
                return int(m.group(1))
            m = re.search(r"[a-zA-ZäöüÄÖÜß]\s+(\d{1,4})$", line)
            if m:
                return int(m.group(1))
    else:
        # On a directory page, allow leading number in running header/footer if not a numbered section
        for line in (lines[0], lines[-1]):
            if re.search(r"[\.\·…]{2,}", line):
                continue
            m = re.match(r"^(\d{1,4})\s+(?:\|\s*)?[A-ZÄÖÜ][a-zA-ZäöüÄÖÜß\s\-–]+$", line)
            if m:
                return int(m.group(1))

    return None


def _resolve_page_numbers_from_directories(
    total_pages: int,
    all_page_texts: list[str],
    directory_page_indices: set[int],
    all_entries: list[dict[str, Any]],
) -> list[int]:
    """Combines directory entry page targets with actual PDF page contents and
    printed header/footer page numbers to determine the exact physical page number
    for every page in the PDF (0-based index -> printed page number).
    """
    if total_pages <= 0:
        return [1]

    norm_page_texts = [
        _normalize_text_for_match(re.sub(r"-\s*\n\s*", "", txt or ""))
        for txt in all_page_texts
    ]

    # Votes per PDF page index: {page_idx: {printed_page: score}}
    page_votes: dict[int, dict[int, int]] = {i: {} for i in range(total_pages)}
    # Votes for constant offset (printed_page - page_idx): {offset: score}
    offset_votes: dict[int, int] = {}

    # 1. Match directory entries against non-directory pages
    for entry in all_entries:
        target_page = entry.get("page")
        if not isinstance(target_page, int) or target_page <= 0:
            continue

        best_idx = None
        best_weight = 0
        for idx in range(total_pages):
            if idx in directory_page_indices:
                continue
            w = _entry_matches_page_text(entry, norm_page_texts[idx])
            if w > best_weight:
                best_weight = w
                best_idx = idx

        if best_idx is not None and best_weight > 0:
            entry["matched_pdf_page_idx"] = best_idx
            page_votes[best_idx][target_page] = page_votes[best_idx].get(target_page, 0) + best_weight
            offset = target_page - best_idx
            offset_votes[offset] = offset_votes.get(offset, 0) + best_weight

    # 2. Check printed page numbers on each PDF page (directory-safe)
    for idx in range(total_pages):
        is_dir = idx in directory_page_indices
        printed = _detect_printed_number_ignoring_directory_lines(
            all_page_texts[idx] if idx < len(all_page_texts) else "",
            is_directory_page=is_dir,
        )
        if printed is not None:
            w = 2 if not is_dir else 1
            page_votes[idx][printed] = page_votes[idx].get(printed, 0) + w
            offset = printed - idx
            offset_votes[offset] = offset_votes.get(offset, 0) + w

    # 3. Determine dominant offset if available
    dominant_offset: int | None = None
    if offset_votes:
        dominant_offset = max(offset_votes.items(), key=lambda kv: (kv[1], -abs(kv[0])))[0]

    # 4. Enforce a strictly sequential (+1) page sequence across the PDF pages
    if dominant_offset is not None:
        return [max(1, dominant_offset + i) for i in range(total_pages)]

    return [i + 1 for i in range(total_pages)]



# ---------------------------------------------------------------------------
# Main Public API: Fast Directory Check
# ---------------------------------------------------------------------------

def check_document_directories(
    file_path: str, max_pages: int = MAX_DIRECTORY_CHECK_PAGES
) -> dict[str, Any]:
    """Perform a fast check on at most the first `max_pages` pages using Docling.

    Detects whether the document contains:
      - Inhaltsverzeichnis (Table of Contents)
      - Abbildungsverzeichnis (List of Figures)
      - Tabellenverzeichnis (List of Tables)
      - Bildverzeichnis (List of Pictures)

    Returns a dictionary containing detection flags, structured entries with
    target page numbers and heading levels, and resolved physical page numbers.
    """
    empty_result: dict[str, Any] = {
        "checked_pages": 0,
        "max_pages": max_pages,
        "has_any_directory": False,
        "has_toc": False,
        "has_list_of_figures": False,
        "has_list_of_tables": False,
        "has_list_of_pictures": False,
        "detected_types": [],
        "directory_pages": [],
        "toc_entries": [],
        "figure_entries": [],
        "table_entries": [],
        "picture_entries": [],
        "heading_levels": {},
        "page_numbers": [],
        "physical_start_page": 1,
    }

    if not file_path or not os.path.exists(file_path):
        return empty_result

    abs_path = os.path.abspath(file_path)
    try:
        st = os.stat(abs_path)
        cache_key = (abs_path, st.st_mtime_ns, st.st_size, int(max_pages))
        if cache_key in _DIRECTORY_CACHE:
            return _DIRECTORY_CACHE[cache_key]
    except OSError:
        cache_key = None

    total_pages, pages_lines, all_page_texts = _extract_pages_with_docling_fast(
        abs_path, max_pages=max_pages
    )
    checked_pages = min(total_pages, max_pages)

    entries_by_type: dict[str, list[dict[str, Any]]] = {
        "toc": [],
        "figures": [],
        "tables": [],
        "pictures": [],
    }
    explicit_headers_seen: set[str] = set()
    directory_page_indices: set[int] = set()

    active_dir_type: str | None = None
    non_entry_streak = 0

    for page_idx, lines_on_page in enumerate(pages_lines):
        page_entries_count = 0
        page_candidate_entries: list[dict[str, Any]] = []

        for line_info in lines_on_page:
            text = line_info.get("text", "").strip()
            if not text:
                continue

            header_type = _match_directory_header(text)
            if header_type is not None:
                active_dir_type = header_type
                explicit_headers_seen.add(header_type)
                directory_page_indices.add(page_idx)
                non_entry_streak = 0
                continue

            if active_dir_type is not None:
                parsed = _parse_directory_entry_line(line_info, active_dir_type, page_idx)
                if parsed is not None:
                    entries_by_type[parsed["type"]].append(parsed)
                    page_entries_count += 1
                    directory_page_indices.add(page_idx)
                    non_entry_streak = 0
                else:
                    # Allow short subheaders inside a directory, but end directory mode
                    # if body paragraphs appear
                    if len(text) > 110:
                        non_entry_streak += 1
                        if non_entry_streak >= 2:
                            active_dir_type = None
            else:
                # Implicit directory detection on early pages when leader dots + page numbers appear
                if re.search(r"[\.\·…]{3,}\s*\d{1,4}\s*$", text):
                    parsed = _parse_directory_entry_line(line_info, "toc", page_idx)
                    if parsed is not None:
                        page_candidate_entries.append(parsed)

        # If a page without an explicit heading had >= 3 dotted leader entries, accept them
        if len(page_candidate_entries) >= 3:
            directory_page_indices.add(page_idx)
            for pe in page_candidate_entries:
                entries_by_type[pe["type"]].append(pe)

        # Reset active_dir_type at page break if the current page had no directory entries or headers
        if page_entries_count == 0 and page_idx not in directory_page_indices:
            active_dir_type = None

    # Infer semantic heading levels (1..4) for TOC entries
    _infer_toc_heading_levels(entries_by_type["toc"])

    # Build lookup map of normalized title -> heading level (1..4)
    heading_levels: dict[str, int] = {}
    for entry in entries_by_type["toc"]:
        lvl = entry.get("level", 2)
        norm_full = _normalize_text_for_match(entry["title"])
        norm_clean = _normalize_text_for_match(entry.get("clean_title") or "")
        if norm_full:
            heading_levels[norm_full] = lvl
        if norm_clean and norm_clean not in heading_levels:
            heading_levels[norm_clean] = lvl

    all_entries = (
        entries_by_type["toc"]
        + entries_by_type["figures"]
        + entries_by_type["tables"]
        + entries_by_type["pictures"]
    )

    page_numbers = _resolve_page_numbers_from_directories(
        total_pages=total_pages,
        all_page_texts=all_page_texts,
        directory_page_indices=directory_page_indices,
        all_entries=all_entries,
    )

    has_toc = bool(entries_by_type["toc"] or "toc" in explicit_headers_seen)
    has_figures = bool(entries_by_type["figures"] or "figures" in explicit_headers_seen)
    has_tables = bool(entries_by_type["tables"] or "tables" in explicit_headers_seen)
    has_pictures = bool(entries_by_type["pictures"] or "pictures" in explicit_headers_seen)

    detected_types: list[str] = []
    if has_toc:
        detected_types.append(DIRECTORY_TYPE_LABELS["toc"])
    if has_figures:
        detected_types.append(DIRECTORY_TYPE_LABELS["figures"])
    if has_tables:
        detected_types.append(DIRECTORY_TYPE_LABELS["tables"])
    if has_pictures:
        detected_types.append(DIRECTORY_TYPE_LABELS["pictures"])

    result: dict[str, Any] = {
        "checked_pages": checked_pages,
        "max_pages": max_pages,
        "has_any_directory": bool(detected_types),
        "has_toc": has_toc,
        "has_list_of_figures": has_figures,
        "has_list_of_tables": has_tables,
        "has_list_of_pictures": has_pictures,
        "detected_types": detected_types,
        "directory_pages": sorted(idx + 1 for idx in directory_page_indices),
        "toc_entries": entries_by_type["toc"],
        "figure_entries": entries_by_type["figures"],
        "table_entries": entries_by_type["tables"],
        "picture_entries": entries_by_type["pictures"],
        "heading_levels": heading_levels,
        "page_numbers": page_numbers,
        "physical_start_page": page_numbers[0] if page_numbers else 1,
    }

    if cache_key is not None:
        _DIRECTORY_CACHE[cache_key] = result

    return result


# ---------------------------------------------------------------------------
# Markdown-Based Directory Extraction & Application Helpers
# ---------------------------------------------------------------------------

def extract_directories_from_markdown(markdown_content: str) -> dict[str, Any]:
    """Parses directory sections directly from extracted or raw Markdown text when
    no pre-computed `directory_info` dict was passed in.
    """
    entries_by_type: dict[str, list[dict[str, Any]]] = {
        "toc": [],
        "figures": [],
        "tables": [],
        "pictures": [],
    }
    if not markdown_content:
        return {
            "has_any_directory": False,
            "has_toc": False,
            "has_list_of_figures": False,
            "has_list_of_tables": False,
            "has_list_of_pictures": False,
            "detected_types": [],
            "toc_entries": [],
            "figure_entries": [],
            "table_entries": [],
            "picture_entries": [],
            "heading_levels": {},
        }

    active_dir: str | None = None
    for raw_line in markdown_content.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if re.match(r"^\(\(\d+\)\)$", stripped):
            continue

        header_type = _match_directory_header(stripped)
        if header_type is not None:
            active_dir = header_type
            continue

        # Stop active directory when hitting a real content heading that has no trailing page number
        if stripped.startswith("#") and not _ENTRY_WITH_PAGE_RE.match(stripped):
            active_dir = None
            continue

        if active_dir is not None:
            leading_spaces = len(raw_line) - len(raw_line.lstrip(" \t"))
            line_info = {
                "text": re.sub(r"^[-*]\s+", "", stripped),
                "indent": 48.0 + leading_spaces * 8.0,
                "height": 10.0,
            }
            parsed = _parse_directory_entry_line(line_info, active_dir, 0)
            if parsed is not None:
                entries_by_type[parsed["type"]].append(parsed)

    _infer_toc_heading_levels(entries_by_type["toc"])
    heading_levels: dict[str, int] = {}
    for entry in entries_by_type["toc"]:
        lvl = entry.get("level", 2)
        norm_full = _normalize_text_for_match(entry["title"])
        norm_clean = _normalize_text_for_match(entry.get("clean_title") or "")
        if norm_full:
            heading_levels[norm_full] = lvl
        if norm_clean and norm_clean not in heading_levels:
            heading_levels[norm_clean] = lvl

    detected_types = []
    if entries_by_type["toc"]:
        detected_types.append("Inhaltsverzeichnis")
    if entries_by_type["figures"]:
        detected_types.append("Abbildungsverzeichnis")
    if entries_by_type["tables"]:
        detected_types.append("Tabellenverzeichnis")
    if entries_by_type["pictures"]:
        detected_types.append("Bildverzeichnis")

    return {
        "has_any_directory": bool(detected_types),
        "has_toc": bool(entries_by_type["toc"]),
        "has_list_of_figures": bool(entries_by_type["figures"]),
        "has_list_of_tables": bool(entries_by_type["tables"]),
        "has_list_of_pictures": bool(entries_by_type["pictures"]),
        "detected_types": detected_types,
        "toc_entries": entries_by_type["toc"],
        "figure_entries": entries_by_type["figures"],
        "table_entries": entries_by_type["tables"],
        "picture_entries": entries_by_type["pictures"],
        "heading_levels": heading_levels,
    }


def resolve_toc_heading_level(
    candidate_title: str, directory_info: dict[str, Any] | None
) -> int | None:
    """Looks up `candidate_title` in `directory_info`'s TOC entries and returns the
    authoritative heading level (1..4) if found, or None.
    """
    if not directory_info or not candidate_title:
        return None

    toc_entries = directory_info.get("toc_entries") or []
    if not toc_entries:
        return None

    # Do not match lines that are themselves directory lines with leader dots + page numbers
    if re.search(r"[\.\·…]{2,}\s*\d{1,4}\s*$", candidate_title.strip()):
        return None

    norm_cand = _normalize_text_for_match(candidate_title)
    norm_cand_stripped = _normalize_text_for_match(_strip_section_number(candidate_title))
    if not norm_cand or len(norm_cand) < 3:
        return None

    heading_levels = directory_info.get("heading_levels") or {}
    if norm_cand in heading_levels:
        return int(heading_levels[norm_cand])
    if norm_cand_stripped and norm_cand_stripped in heading_levels:
        return int(heading_levels[norm_cand_stripped])

    for entry in toc_entries:
        lvl = int(entry.get("level", 2))
        e_full = _normalize_text_for_match(entry.get("title", ""))
        e_clean = _normalize_text_for_match(entry.get("clean_title", ""))
        if norm_cand == e_full or (e_clean and norm_cand == e_clean):
            return lvl
        if norm_cand_stripped and (norm_cand_stripped == e_full or norm_cand_stripped == e_clean):
            return lvl

    return None


def is_caption_in_figure_or_picture_directory(
    candidate_title: str, directory_info: dict[str, Any] | None
) -> bool:
    """Returns True if `candidate_title` matches an entry from the Abbildungsverzeichnis
    or Bildverzeichnis (so it should be treated as a figure/picture caption rather
    than a chapter H1/H2 heading).
    """
    if not directory_info or not candidate_title:
        return False

    norm_cand = _normalize_text_for_match(candidate_title)
    if not norm_cand:
        return False

    for key in ("figure_entries", "picture_entries"):
        for entry in directory_info.get(key) or []:
            e_full = _normalize_text_for_match(entry.get("title", ""))
            e_label = _normalize_text_for_match(entry.get("label") or "")
            if e_full and (norm_cand == e_full or norm_cand.startswith(e_full)):
                return True
            if e_label and len(e_label) >= 5 and norm_cand.startswith(e_label):
                return True
    return False


def is_caption_in_table_directory(
    candidate_title: str, directory_info: dict[str, Any] | None
) -> bool:
    """Returns True if `candidate_title` matches an entry from the Tabellenverzeichnis
    (so it should be formatted as a ### H3 table heading rather than an H1/H2 chapter heading).
    """
    if not directory_info or not candidate_title:
        return False

    norm_cand = _normalize_text_for_match(candidate_title)
    if not norm_cand:
        return False

    for entry in directory_info.get("table_entries") or []:
        e_full = _normalize_text_for_match(entry.get("title", ""))
        e_label = _normalize_text_for_match(entry.get("label") or "")
        if e_full and (norm_cand == e_full or norm_cand.startswith(e_full)):
            return True
        if e_label and len(e_label) >= 5 and norm_cand.startswith(e_label):
            return True
    return False


def apply_directory_heading_levels(
    markdown_content: str,
    directory_info: dict[str, Any] | None = None,
    raw_markdown: str | None = None,
) -> tuple[str, set[int]]:
    """Enforces heading levels (# .. ####) derived from the document's Table of Contents
    on `markdown_content` and demotes figure/picture/table captions listed in the
    Abbildungsverzeichnis / Bildverzeichnis / Tabellenverzeichnis if they were wrongly
    tagged as # or ##.

    Returns (updated_markdown, locked_line_indices).
    """
    if not markdown_content:
        return markdown_content, set()

    if not directory_info or not directory_info.get("has_any_directory"):
        directory_info = extract_directories_from_markdown(raw_markdown or markdown_content)

    if not directory_info or not directory_info.get("has_any_directory"):
        return markdown_content, set()

    lines = markdown_content.split("\n")
    locked_indices: set[int] = set()
    in_directory_section = False

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        # Track whether we are inside a directory section in the markdown itself
        header_type = _match_directory_header(stripped)
        if header_type is not None:
            in_directory_section = True
            has_prior_h1_dir = any(ln.strip().startswith("# ") for ln in lines[:idx])
            if header_type in ("figures", "tables", "pictures") and has_prior_h1_dir:
                hdr_hashes = "##"
            else:
                m_existing_h = re.match(r"^(#{1,2})\s+", stripped)
                hdr_hashes = m_existing_h.group(1) if m_existing_h else "#"
            clean_hdr = re.sub(r"^#{1,6}\s*", "", stripped)
            clean_hdr = re.sub(r"^(?:\*\*|__|_|\*)+(.+?)(?:\*\*|__|_|\*)+$", r"\1", clean_hdr).strip()
            lines[idx] = f"{hdr_hashes} {clean_hdr}"
            locked_indices.add(idx)
            continue

        if in_directory_section:
            if _ENTRY_WITH_PAGE_RE.match(stripped) or re.match(r"^[-*]\s+", stripped):
                continue
            if stripped.startswith("(("):
                in_directory_section = False
                continue
            in_directory_section = False

        # Skip special FIBS tags, table rows, list items, and page markers
        if stripped.startswith(("<", "((", "|", "-\t", "- ", "* ")):
            continue
        if re.match(r"^\d+\.\t", stripped):
            continue

        m_heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if m_heading:
            hashes = m_heading.group(1)
            raw_title = m_heading.group(2).strip()
            clean_title = re.sub(r"^(?:\*\*|__|_|\*)+(.+?)(?:\*\*|__|_|\*)+$", r"\1", raw_title).strip()

            # Check if it's a figure/picture caption from Abbildungsverzeichnis / Bildverzeichnis
            if is_caption_in_figure_or_picture_directory(clean_title, directory_info):
                if len(hashes) <= 3:
                    lines[idx] = f"#### {clean_title}"
                    locked_indices.add(idx)
                continue

            # Check if it's a table heading from Tabellenverzeichnis
            if is_caption_in_table_directory(clean_title, directory_info):
                if len(hashes) <= 2:
                    lines[idx] = f"### {clean_title}"
                    locked_indices.add(idx)
                continue

            toc_lvl = resolve_toc_heading_level(clean_title, directory_info)
            if toc_lvl is not None:
                lines[idx] = f"{'#' * toc_lvl} {clean_title}"
                locked_indices.add(idx)
                continue
        else:
            # Check standalone line (plain or bold/italic wrapped) that matches a TOC or Figure/Picture directory entry
            if len(stripped) <= 110 and not stripped.endswith("."):
                unwrapped = re.sub(r"^(?:\*\*|__|_|\*)+(.+?)(?:\*\*|__|_|\*)+$", r"\1", stripped).strip()
                toc_lvl = resolve_toc_heading_level(unwrapped, directory_info)
                if toc_lvl is not None:
                    lines[idx] = f"{'#' * toc_lvl} {unwrapped}"
                    locked_indices.add(idx)
                elif is_caption_in_figure_or_picture_directory(unwrapped, directory_info):
                    next_non_empty = ""
                    for n_i in range(idx + 1, len(lines)):
                        if lines[n_i].strip():
                            next_non_empty = lines[n_i].strip()
                            break
                    if not next_non_empty.startswith(("-", "*", "<Bild", "![")):
                        lines[idx] = f"#### {unwrapped}"
                        locked_indices.add(idx)

    return "\n".join(lines), locked_indices


def apply_directory_page_numbers(
    markdown_content: str,
    directory_info: dict[str, Any] | None = None,
) -> str:
    """Uses the detected directories (`toc_entries`, `figure_entries`, `table_entries`,
    `picture_entries`, and `page_numbers`) to verify and repair `((num))` page markers
    in `markdown_content`.
    """
    if not markdown_content:
        return markdown_content

    if not directory_info or not directory_info.get("has_any_directory"):
        directory_info = extract_directories_from_markdown(markdown_content)

    if not directory_info or not directory_info.get("has_any_directory"):
        return markdown_content

    all_entries = (
        (directory_info.get("toc_entries") or [])
        + (directory_info.get("figure_entries") or [])
        + (directory_info.get("table_entries") or [])
        + (directory_info.get("picture_entries") or [])
    )
    known_pages = directory_info.get("page_numbers") or []

    # Split markdown by ((num)) page markers
    parts = re.split(r"(\(\(\d+\)\))", markdown_content)
    if len(parts) < 2:
        # If no page markers exist at all and we know physical_start_page, prepend it
        start_pg = directory_info.get("physical_start_page")
        if start_pg and start_pg > 1:
            return f"(({start_pg}))\n\n{markdown_content}"
        return markdown_content

    marker_indices = [i for i, p in enumerate(parts) if re.match(r"^\(\(\d+\)\)$", p)]
    if not marker_indices:
        return markdown_content

    # Cross-check each segment's content against directory entries and accumulate offset votes
    offset_votes: dict[int, int] = {}
    if len(marker_indices) == len(known_pages) and known_pages:
        offset_votes[int(known_pages[0])] = offset_votes.get(int(known_pages[0]), 0) + 3

    for seg_pos, m_idx in enumerate(marker_indices):
        seg_text = parts[m_idx + 1] if (m_idx + 1) < len(parts) else ""
        norm_seg = _normalize_text_for_match(seg_text)

        # Check if this segment is a directory page itself
        has_dir_header = any(
            _match_directory_header(line.strip()) is not None
            for line in seg_text.splitlines()
            if line.strip()
        )
        if not has_dir_header and norm_seg:
            for entry in all_entries:
                target_pg = entry.get("page")
                if not isinstance(target_pg, int):
                    continue
                w = _entry_matches_page_text(entry, norm_seg)
                if w > 0 and (target_pg - seg_pos) >= 1:
                    offset = target_pg - seg_pos
                    offset_votes[offset] = offset_votes.get(offset, 0) + w

    if offset_votes:
        best_offset = max(offset_votes.items(), key=lambda kv: (kv[1], -abs(kv[0])))[0]
        inferred_marker_pages = [max(1, best_offset + i) for i in range(len(marker_indices))]
    elif known_pages:
        start_pg = int(known_pages[0])
        inferred_marker_pages = [max(1, start_pg + i) for i in range(len(marker_indices))]
    else:
        start_pg = int(directory_info.get("physical_start_page") or 1)
        inferred_marker_pages = [max(1, start_pg + i) for i in range(len(marker_indices))]

    for seg_pos, m_idx in enumerate(marker_indices):
        new_pg = inferred_marker_pages[seg_pos]
        if new_pg is not None:
            parts[m_idx] = f"(({new_pg}))"

    return "".join(parts)



def format_directory_prompt_context(directory_info: dict[str, Any] | None) -> str:
    """Formats detected directory information into a concise instruction block for the
    LLM system prompt so Gemma preserves the exact heading hierarchy and page numbers.
    """
    if not directory_info or not directory_info.get("has_any_directory"):
        return ""

    lines = [
        "ERKANNTE VERZEICHNISSE (aus den ersten Seiten des Dokuments):",
        f"Erkannte Verzeichnisarten: {', '.join(directory_info.get('detected_types') or [])}.",
    ]
    toc_entries = directory_info.get("toc_entries") or []
    if toc_entries:
        lines.append(
            "Nutze die folgende Gliederung aus dem Inhaltsverzeichnis verbindlich für die "
            "Überschriftsebenen (# = Ebene 1, ## = Ebene 2, ### = Ebene 3, #### = Ebene 4) "
            "und die zugehörigen Seitenzahlen ((Seite)):"
        )
        for e in toc_entries[:40]:
            hashes = "#" * int(e.get("level", 2))
            lines.append(f"  - {hashes} {e['title']} -> ((Seite {e['page']}))")

    for key, label in (
        ("figure_entries", "Abbildungsverzeichnis"),
        ("table_entries", "Tabellenverzeichnis"),
        ("picture_entries", "Bildverzeichnis"),
    ):
        entries = directory_info.get(key) or []
        if entries:
            lines.append(f"Einträge im {label} (zur Seiten- und Titelorientierung):")
            for e in entries[:20]:
                lines.append(f"  - {e['title']} -> ((Seite {e['page']}))")

    return "\n".join(lines)


def save_directory_info(output_dir: str, directory_info: dict[str, Any]) -> str | None:
    """Saves `directory_info.json` inside the task's output directory."""
    if not output_dir or not directory_info:
        return None
    try:
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, "directory_info.json")
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(directory_info, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
        return path
    except Exception as e:
        logger.warning(f"Could not save directory_info.json to {output_dir}: {e}")
        return None


def load_directory_info(path_or_dir: str) -> dict[str, Any] | None:
    """Loads `directory_info.json` from a task directory or file path if present."""
    if not path_or_dir:
        return None
    cand = (
        path_or_dir
        if path_or_dir.endswith(".json")
        else os.path.join(path_or_dir, "directory_info.json")
    )
    if os.path.exists(cand):
        try:
            with open(cand, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load directory_info.json from {cand}: {e}")
    return None
