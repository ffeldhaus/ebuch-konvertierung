"""Native Microsoft Word (DOCX) exporter and importer for E-Buch 2025 (FIBS 09/2025)."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from docx import Document

from backend.services import fibs_constants as fc

logger = logging.getLogger(__name__)


def sanitize_xml_string(text: str) -> str:
    """Remove non-XML-compatible control characters from a string.

    Args:
        text: Input string that may contain low-ASCII or invalid Unicode control codes.

    Returns:
        Sanitized string safe for OpenXML serialization.
    """
    if not isinstance(text, str):
        return text
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]", "", text)


_INLINE_FORMAT_TOKEN_RE = re.compile(
    r"(_\.\.\._)"
    r"|([A-Za-z0-9\)\]'\}]_(?:\{[^{}\n]*\}|[A-Za-z0-9~]+\b))"
    r"|((?<![A-Za-z0-9\\])\*(?=[A-Za-zÄÖÜäöüß])[^*\n]*?(?<![*\s])\*(?![A-Za-z0-9]))"
    r"|((?<![0-9\\])(?<!\d )%[^%\s][^%\n]*?(?<!\s)%(?![A-Za-zÄÖÜäöüß]))"
    r"|((?<![A-Za-z0-9\\'_])_(?!\s)(?:[^_\n]*?[^\s_]|[^\s_])_(?![A-Za-z0-9\{]))"
)


def _append_linked_bookmark_hyperlink(
    paragraph: Any,
    display_text: str,
    bm_name: str,
    target_anchor: str,
    bm_id: int,
    has_hyperlink_style: bool = False,
) -> None:
    """Append an OpenXML bookmark paired with an internal ``w:hyperlink`` anchor run.

    Args:
        paragraph: Target ``python-docx`` paragraph instance.
        display_text: Visible link text (e.g. ``"^1"``).
        bm_name: Bookmark name placed on this element (e.g. ``"S304_1"`` or ``"S304_1a"``).
        target_anchor: Target bookmark anchor for ``w:hyperlink`` (e.g. ``"S304_1a"``).
        bm_id: Unique integer ``w:id`` for ``w:bookmarkStart`` / ``w:bookmarkEnd``.
        has_hyperlink_style: Whether the document defines the ``Hyperlink`` character style.
    """
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    bm_id_str = str(bm_id)
    bm_start = OxmlElement("w:bookmarkStart")
    bm_start.set(qn("w:id"), bm_id_str)
    bm_start.set(qn("w:name"), bm_name)
    paragraph._p.append(bm_start)

    hl = OxmlElement("w:hyperlink")
    hl.set(qn("w:anchor"), target_anchor)
    hl.set(qn("w:history"), "1")

    r_el = OxmlElement("w:r")
    r_pr = OxmlElement("w:rPr")
    if has_hyperlink_style:
        r_style = OxmlElement("w:rStyle")
        r_style.set(qn("w:val"), "Hyperlink")
        r_pr.append(r_style)
    r_fonts = OxmlElement("w:rFonts")
    r_fonts.set(qn("w:ascii"), fc.FIBS_FONT_NAME)
    r_fonts.set(qn("w:hAnsi"), fc.FIBS_FONT_NAME)
    r_fonts.set(qn("w:cs"), fc.FIBS_FONT_NAME)
    r_pr.append(r_fonts)
    r_pr.append(OxmlElement("w:b"))
    u_el = OxmlElement("w:u")
    u_el.set(qn("w:val"), "single")
    r_pr.append(u_el)
    sz_val = str(int(fc.FIBS_BODY_FONT_SIZE_PT * 2))
    sz_el = OxmlElement("w:sz")
    sz_el.set(qn("w:val"), sz_val)
    r_pr.append(sz_el)
    sz_cs_el = OxmlElement("w:szCs")
    sz_cs_el.set(qn("w:val"), sz_val)
    r_pr.append(sz_cs_el)
    r_el.append(r_pr)

    t_el = OxmlElement("w:t")
    t_el.text = sanitize_xml_string(display_text)
    r_el.append(t_el)
    hl.append(r_el)
    paragraph._p.append(hl)

    bm_end = OxmlElement("w:bookmarkEnd")
    bm_end.set(qn("w:id"), bm_id_str)
    paragraph._p.append(bm_end)


def _add_formatted_segment(paragraph: Any, segment: str) -> None:
    """Write a text segment without footnote hyperlinks using FIBS inline formatting runs."""
    if not segment:
        return
    pos = 0
    for m in _INLINE_FORMAT_TOKEN_RE.finditer(segment):
        if m.start() > pos:
            paragraph.add_run(segment[pos : m.start()])
        tok = m.group(0)
        if m.group(1) or m.group(2):
            paragraph.add_run(tok)
        elif m.group(3):
            run = paragraph.add_run(tok)
            run.bold = True
        elif m.group(4):
            run = paragraph.add_run(tok)
            run.italic = True
        elif m.group(5):
            # Official FIBS _bl.docx convention: '_' (plain) + inner (bold, no underline) + '_' (plain)
            paragraph.add_run("_")
            r_inner = paragraph.add_run(tok[1:-1])
            r_inner.bold = True
            paragraph.add_run("_")
        pos = m.end()
    if pos < len(segment):
        paragraph.add_run(segment[pos:])


def add_formatted_text(
    paragraph: Any,
    text: str,
    *,
    is_heading: bool = False,
    link_specs: dict[str, tuple[str, str]] | None = None,
    bm_counter: list[int] | None = None,
    has_hyperlink_style: bool = False,
) -> None:
    """Parse E-Buch formatting markers and write them into a Word paragraph.

    Formats ``_Wort_`` as three runs (``"_"`` unbolded, inner text ``bold=True`` without
    Word underline, ``"_"`` unbolded), ``*bold*`` as bold, and ``%italic%`` as italic.
    Inside headings (``is_heading=True``), ``_..._`` emphasis underscores are stripped per
    FIBS §10 (p. 99). Optional ``link_specs`` turns matched ``^n`` glossary markers into
    bidirectional OpenXML bookmarks and hyperlinks.

    Args:
        paragraph: Target ``python-docx`` paragraph instance.
        text: Text string containing optional FIBS inline markers.
        is_heading: Whether the target paragraph is an ``Überschrift 1–5`` heading.
        link_specs: Optional mapping ``{num_str: (bm_name, target_anchor)}`` for inline ``^n`` links.
        bm_counter: Optional single-element mutable integer counter ``[next_id]`` for bookmarks.
        has_hyperlink_style: Whether the ``Hyperlink`` character style exists in ``doc.styles``.
    """
    text = sanitize_xml_string(text)
    if is_heading:
        text = re.sub(
            r"(?<![\w\\])_(?!\.\.\._)(?!\s)([^_\n]+?)(?<!\s)_(?![\w\{])",
            r"\1",
            text,
        )

    if not link_specs:
        _add_formatted_segment(paragraph, text)
        return

    ref_re = re.compile(r"(?<![0-9\\+\-=])\^(\d+)\b")
    last_idx = 0
    used_in_para: set[str] = set()
    for m_ref in ref_re.finditer(text):
        n_str = m_ref.group(1)
        if n_str not in link_specs or n_str in used_in_para:
            continue
        if m_ref.start() > last_idx:
            _add_formatted_segment(paragraph, text[last_idx : m_ref.start()])
        bm_name, target_anchor = link_specs[n_str]
        next_id = bm_counter[0] if bm_counter is not None else 1000
        if bm_counter is not None:
            bm_counter[0] += 1
        _append_linked_bookmark_hyperlink(
            paragraph,
            f"^{n_str}",
            bm_name,
            target_anchor,
            next_id,
            has_hyperlink_style=has_hyperlink_style,
        )
        used_in_para.add(n_str)
        last_idx = m_ref.end()

    if last_idx < len(text):
        _add_formatted_segment(paragraph, text[last_idx:])


def _parse_table_to_matrix(table_lines: list[str]) -> list[list[str]]:
    """Parse table lines (HTML, GFM Markdown pipe, or tab-separated) into a 2D cell matrix.

    Args:
        table_lines: Raw lines extracted from a ``<Tabelle>`` block or Markdown pipe block.

    Returns:
        2D list of rows and cells, or an empty list if no valid table structure is found.
    """
    joined = "\n".join(table_lines).strip()
    if not joined:
        return []

    # 1. HTML table
    if "<tr>" in joined.lower():
        rows = re.findall(r"<tr>(.*?)<\/tr>", joined, re.DOTALL | re.IGNORECASE)
        matrix = []
        for r in rows:
            cols = re.findall(r"<t[dh].*?>(.*?)<\/t[dh]>", r, re.DOTALL | re.IGNORECASE)
            clean_cols = [re.sub(r"<[^>]+>", "", c).strip() for c in cols]
            if clean_cols:
                matrix.append(clean_cols)
        if matrix:
            return matrix

    # 2. Markdown pipe table
    pipe_rows = [ln.strip() for ln in table_lines if ln.strip().startswith("|") and "|" in ln.strip()[1:]]
    if len(pipe_rows) >= 1:
        matrix = []
        for r in pipe_rows:
            inner = r.strip("|").strip()
            if re.match(r"^[\s\|:\-]+$", inner):
                continue
            cells = [c.strip() for c in r.strip("|").split("|")]
            if cells:
                matrix.append(cells)
        if matrix:
            return matrix

    # 3. Tab-separated rows
    tab_rows = [ln for ln in table_lines if "\t" in ln and ln.strip()]
    if tab_rows:
        matrix = []
        for r in tab_rows:
            cells = [c.strip() for c in r.split("\t")]
            if any(cells):
                matrix.append(cells)
        if matrix:
            return matrix

    return []


def _apply_fibs_paragraph_formatting(
    p: Any,
    font_size_pt: float = fc.FIBS_BODY_FONT_SIZE_PT,
    space_after_pt: float = 0.0,
    bold: bool = False,
) -> None:
    """Apply official FIBS-Dokumentvorlage paragraph and run formatting.

    Args:
        p: Target ``python-docx`` paragraph.
        font_size_pt: Font size in points (default 14 pt).
        space_after_pt: Space after paragraph in points (0 pt for body, 6 pt for headings).
        bold: Whether all runs in the paragraph should be bolded.
    """
    from docx.shared import Cm, Pt, RGBColor

    pf = p.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(space_after_pt)
    pf.line_spacing = fc.FIBS_LINE_SPACING
    pf.left_indent = Cm(0)
    pf.first_line_indent = Cm(0)
    for run in p.runs:
        run.font.name = fc.FIBS_FONT_NAME
        run.font.size = Pt(font_size_pt)
        run.font.color.rgb = RGBColor(0, 0, 0)
        if bold:
            run.bold = True


def _configure_fibs_document_defaults(doc: Any) -> None:
    """Configure page margins (2 cm) and base styles (Verdana 14pt, 1.5 line spacing) per FIBS 2.1.1.

    Args:
        doc: Target ``python-docx`` Document instance.
    """
    from docx.shared import Cm, Pt, RGBColor

    for section in doc.sections:
        section.top_margin = Cm(fc.FIBS_MARGIN_CM)
        section.bottom_margin = Cm(fc.FIBS_MARGIN_CM)
        section.left_margin = Cm(fc.FIBS_MARGIN_CM)
        section.right_margin = Cm(fc.FIBS_MARGIN_CM)

    for style in doc.styles:
        try:
            if hasattr(style, "font") and style.font is not None:
                style.font.name = fc.FIBS_FONT_NAME
                style.font.color.rgb = RGBColor(0, 0, 0)
                s_name = (style.name or "").lower()
                if s_name in ("normal", "standard"):
                    style.font.size = Pt(fc.FIBS_BODY_FONT_SIZE_PT)
                    style.paragraph_format.space_before = Pt(0)
                    style.paragraph_format.space_after = Pt(0)
                    style.paragraph_format.line_spacing = fc.FIBS_LINE_SPACING
                else:
                    for lvl, sz in fc.FIBS_HEADING_SIZES_PT.items():
                        if s_name in (f"heading {lvl}", f"überschrift {lvl}"):
                            style.font.size = Pt(sz)
                            style.font.bold = True
                            style.paragraph_format.space_before = Pt(0)
                            style.paragraph_format.space_after = Pt(fc.FIBS_HEADING_SPACE_AFTER_PT)
                            style.paragraph_format.line_spacing = fc.FIBS_LINE_SPACING
        except Exception:
            pass


def _write_table_to_docx(doc: Any, matrix: list[list[str]]) -> Any:
    """Render a 2D cell matrix as a FIBS-compliant Word table.

    Args:
        doc: Target ``python-docx`` Document instance.
        matrix: 2D list of cell strings.

    Returns:
        The created ``python-docx`` Table object, or ``None`` if ``matrix`` is empty.
    """
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    if not matrix:
        return None
    col_count = max(len(r) for r in matrix)
    row_count = len(matrix)
    if col_count == 0 or row_count == 0:
        return None

    word_table = doc.add_table(rows=row_count, cols=col_count)
    word_table.style = "Table Grid"
    for r_idx, row in enumerate(matrix):
        for c_idx in range(col_count):
            cell = word_table.cell(r_idx, c_idx)
            # FIBS 2.1.1.2 Tabellen: Standardzellenbegrenzung oben 0,25 cm (142 dxa)
            try:
                tc_pr = cell._tc.get_or_add_tcPr()
                tc_mar = OxmlElement("w:tcMar")
                top_mar = OxmlElement("w:top")
                top_mar.set(qn("w:w"), fc.FIBS_TABLE_TOP_MARGIN_DXA)
                top_mar.set(qn("w:type"), "dxa")
                tc_mar.append(top_mar)
                tc_pr.append(tc_mar)
            except Exception:
                pass

            val = row[c_idx] if c_idx < len(row) else ""
            # FIBS 7.5.1: Empty table cells where students enter answers get _..._
            if not val.strip():
                val = "_..._"
            # FIBS 10 (Page 99): Column headers in tables are not marked with underscores
            if r_idx == 0:
                val = re.sub(r"^_(.+)_$", r"\1", val.strip())
                val = re.sub(r"^\*\*(.+)\*\*$", r"\1", val.strip())

            p = cell.paragraphs[0]
            p.text = ""
            add_formatted_text(p, val)
            _apply_fibs_paragraph_formatting(
                p, font_size_pt=fc.FIBS_BODY_FONT_SIZE_PT, space_after_pt=0.0, bold=(r_idx == 0)
            )
    return word_table


_PAGE_MARKER_EXACT_RE = re.compile(
    r"^\(\(([\dIVXLCDMivxlcdm]+(?:\s*[-–]\s*[\dIVXLCDMivxlcdm]+)?)\)\)"
    r"(?:\s*/\s*\(\(([\dIVXLCDMivxlcdm]+)\)\))?$"
)


def _add_empty_fibs_paragraph(doc: Any) -> Any:
    """Insert one empty ``Standard`` paragraph (14 pt Verdana, 0 pt before/after, 1.5 spacing).

    Args:
        doc: Target ``python-docx`` Document instance.

    Returns:
        The newly created empty ``Paragraph`` object.
    """
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt

    p = doc.add_paragraph()
    try:
        p.style = "Standard"
    except KeyError:
        p.style = "Normal"
    pf = p.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing = fc.FIBS_LINE_SPACING
    pf.left_indent = Cm(0)
    pf.first_line_indent = Cm(0)
    try:
        p_pr = p._p.get_or_add_pPr()
        r_pr = OxmlElement("w:rPr")
        r_fonts = OxmlElement("w:rFonts")
        r_fonts.set(qn("w:ascii"), fc.FIBS_FONT_NAME)
        r_fonts.set(qn("w:hAnsi"), fc.FIBS_FONT_NAME)
        r_fonts.set(qn("w:cs"), fc.FIBS_FONT_NAME)
        r_pr.append(r_fonts)
        sz_val = str(int(fc.FIBS_BODY_FONT_SIZE_PT * 2))
        sz_el = OxmlElement("w:sz")
        sz_el.set(qn("w:val"), sz_val)
        r_pr.append(sz_el)
        sz_cs = OxmlElement("w:szCs")
        sz_cs.set(qn("w:val"), sz_val)
        r_pr.append(sz_cs)
        p_pr.append(r_pr)
    except Exception:
        pass
    return p


def _populate_fibs_header_and_clean_placeholders(
    doc: Any,
    markdown_content: str,
    doc_metadata: dict[str, str] | None,
) -> None:
    """Populate FIBS-Kopf fields in ``doc`` and strip the template's ``(())`` placeholder.

    Infers ``start_page`` and ``end_page`` from the first and last ``((num))`` markers
    in ``markdown_content`` when omitted from ``doc_metadata``.

    Args:
        doc: Loaded ``python-docx`` Document (from template or empty).
        markdown_content: Standardised Markdown string.
        doc_metadata: Optional metadata dict (``fach``, ``titel``, ``verlag``, ``isbn``,
            ``start_page``, ``end_page``).
    """
    meta = {k.lower(): str(v).strip() for k, v in (doc_metadata or {}).items() if v is not None}

    page_matches = re.findall(
        r"(?m)^\s*\(\(([\dIVXLCDMivxlcdm]+)\)\)(?:\s*/\s*\(\(([\dIVXLCDMivxlcdm]+)\)\))?\s*$",
        markdown_content or "",
    )
    inferred_start = page_matches[0][0] if page_matches else ""
    inferred_end = (page_matches[-1][1] or page_matches[-1][0]) if page_matches else ""
    start_page = meta.get("start_page") or inferred_start
    end_page = meta.get("end_page") or inferred_end

    isbn_val = meta.get("isbn", "")
    if isbn_val:
        isbn_clean = isbn_val.replace("_", "-").strip("- ")
        digits_only = re.sub(r"\D", "", isbn_clean)
        if len(digits_only) == 13:
            isbn_val = isbn_clean if "-" in isbn_clean else digits_only

    paras = list(doc.paragraphs)
    if not paras:
        return

    placeholder_indices: list[int] = []
    for idx, p in enumerate(paras[:30]):
        txt = p.text.strip()
        if txt.startswith("Fach:") and meta.get("fach"):
            p.text = ""
            p.add_run(f"Fach: {meta['fach']}")
            _apply_fibs_paragraph_formatting(p)
        elif txt.startswith("Titel:") and meta.get("titel"):
            p.text = ""
            p.add_run(f"Titel: {meta['titel']}")
            _apply_fibs_paragraph_formatting(p)
        elif txt.startswith("Verlag:") and meta.get("verlag"):
            p.text = ""
            p.add_run(f"Verlag: {meta['verlag']}")
            _apply_fibs_paragraph_formatting(p)
        elif txt.startswith("ISBN:") and isbn_val:
            p.text = ""
            p.add_run(f"ISBN: {isbn_val}")
            _apply_fibs_paragraph_formatting(p)
        elif re.match(r"^Seite:\s*bis\s*$", txt) and start_page and end_page:
            p.text = ""
            p.add_run(f"Seite: {start_page} bis {end_page}")
            _apply_fibs_paragraph_formatting(p)
        elif txt == "(())":
            placeholder_indices.append(idx)

    to_remove: list[Any] = []
    for p_idx in placeholder_indices:
        to_remove.append(paras[p_idx])
        nxt = p_idx + 1
        while nxt < len(paras) and not paras[nxt].text.strip():
            to_remove.append(paras[nxt])
            nxt += 1

    for p_rem in to_remove:
        parent = p_rem._element.getparent()
        if parent is not None:
            parent.remove(p_rem._element)


def _collect_glossary_link_anchors(
    lines: list[str],
) -> tuple[dict[int, dict[str, tuple[str, str]]], dict[int, tuple[str, str, str]]]:
    """Pair inline ``^n`` references with ``^n:`` glossary definitions per page ``((P))``.

    Args:
        lines: Split lines of the Markdown document.

    Returns:
        Tuple ``(body_links, glossary_links)`` where ``body_links[line_idx][num_str]``
        is ``(bm_name, target_anchor)`` (``S{P}_{n}`` -> ``S{P}_{n}a``) and
        ``glossary_links[line_idx]`` is ``(num_str, bm_name, target_anchor)``
        (``S{P}_{n}a`` -> ``S{P}_{n}``).
    """
    current_page = "1"
    in_glossary = False
    in_block_tag = False

    body_refs: list[tuple[int, str, str]] = []
    def_lines: list[tuple[int, str, str]] = []

    glossary_heading_re = re.compile(
        r"^(?:#{1,6}\s+|(?:\*\*|_))?(?:Worterklärung(?:en)?|Annotation(?:en)?)"
        r"(?:\s*\(Randspalte\))?:?(?:\*\*|_)?\s*$",
        re.IGNORECASE,
    )
    def_line_re = re.compile(r"^(?:\s*[-*+][\t ]+|\s*)\^(\d+)(?:[:.\t\s]+)(.+)$")
    strict_def_re = re.compile(r"^(?:\s*[-*+][\t ]+|\s*)\^(\d+):\s+(.+)$")
    inline_ref_re = re.compile(r"(?<![0-9\\+\-=])\^(\d+)\b")

    for idx, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        m_pg = _PAGE_MARKER_EXACT_RE.match(s)
        if m_pg:
            current_page = re.sub(r"[^0-9A-Za-z]+", "_", m_pg.group(1)).strip("_") or "1"
            in_glossary = False
            continue

        if re.match(r"^<(?:Bild|Tabelle|Rahmen|Anmerkung|Lückentext)\b", s, re.IGNORECASE):
            if not re.search(
                r"</(?:Bild|Tabelle|Rahmen|Anmerkung|Lückentext)>\s*$", s, re.IGNORECASE
            ):
                in_block_tag = True
            continue
        if in_block_tag:
            if re.search(
                r"</(?:Bild|Tabelle|Rahmen|Anmerkung|Lückentext)>\s*$", s, re.IGNORECASE
            ):
                in_block_tag = False
            continue

        if glossary_heading_re.match(s):
            in_glossary = True
            continue
        if in_glossary and s.startswith("#"):
            in_glossary = False

        if in_glossary:
            m_def = def_line_re.match(line)
            if m_def:
                def_lines.append((idx, current_page, m_def.group(1)))
                continue
        else:
            m_strict = strict_def_re.match(line)
            if m_strict and any(
                r_p == current_page and r_n == m_strict.group(1) for _, r_p, r_n in body_refs
            ):
                def_lines.append((idx, current_page, m_strict.group(1)))
                continue

        for m_r in inline_ref_re.finditer(line):
            body_refs.append((idx, current_page, m_r.group(1)))

    body_links: dict[int, dict[str, tuple[str, str]]] = {}
    glossary_links: dict[int, tuple[str, str, str]] = {}
    used_body_indices: set[tuple[int, str]] = set()

    for def_idx, def_page, num_str in def_lines:
        matched_ref: tuple[int, str, str] | None = None
        for r_idx, r_page, r_num in body_refs:
            if r_num == num_str and r_page == def_page and (r_idx, r_num) not in used_body_indices:
                matched_ref = (r_idx, r_page, r_num)
                break
        if matched_ref is None:
            for r_idx, r_page, r_num in reversed(body_refs):
                if (
                    r_idx < def_idx
                    and r_num == num_str
                    and (r_idx, r_num) not in used_body_indices
                ):
                    matched_ref = (r_idx, r_page, r_num)
                    break

        anchor_page = matched_ref[1] if matched_ref is not None else def_page
        base_bm = f"S{anchor_page}_{num_str}"
        glossary_links[def_idx] = (num_str, f"{base_bm}a", base_bm)
        if matched_ref is not None:
            used_body_indices.add((matched_ref[0], num_str))
            body_links.setdefault(matched_ref[0], {})[num_str] = (base_bm, f"{base_bm}a")

    return body_links, glossary_links


def convert_markdown_to_docx(
    markdown_content: str,
    output_docx_path: str,
    template_path: str | None = None,
    doc_metadata: dict[str, str] | None = None,
) -> str:
    r"""Convert E-Buch standardised Markdown to a native FIBS 09/2025 compliant DOCX file.

    Enforces official FIBS-Dokumentvorlage specifications (Übertragungsregeln Stand 09/2025, Section 2.1.1):
      - Margins: all 2 cm, zero hard page breaks before ``((n))``
      - Font: Verdana across entire document, line spacing 1.5
      - Standard: 14 pt, 0 Pt before, 0 Pt after
      - Überschrift 1–5: 20 pt, 18 pt, 16 pt, 14 pt, 14 pt (0 Pt before, 6 Pt after)
      - Liste: 14 pt, hanging indent 1 cm (left 1 cm, first line -1 cm), marker + Tab (``\\t``)
      - Listenfortsetzung: 14 pt, left indent 1 cm
      - Tags (``<Bild>``, ``<Rahmen>``, ``<Anmerkung>``, ``<Lückentext>``): single paragraphs with soft returns (``w:br``)
      - FIBS blank lines before ``((n))``, non-stacked headings, and after closed tags/tables

    Args:
        markdown_content: Standardised E-Buch Markdown text.
        output_docx_path: Destination path for the generated ``.docx`` file.
        template_path: Optional ``.docx`` or ``.dotx`` template path.
        doc_metadata: Optional metadata dict (``fach``, ``titel``, ``verlag``, ``isbn``,
            ``start_page``, ``end_page``) used to populate the FIBS-Kopf header.

    Returns:
        The ``output_docx_path`` where the document was saved.
    """
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm

    markdown_content = sanitize_xml_string(markdown_content or "")
    os.makedirs(os.path.dirname(output_docx_path) or ".", exist_ok=True)
    if template_path and os.path.exists(template_path):
        logger.info("Loading custom style template: %s", template_path)
        if template_path.lower().endswith(".dotx"):
            import io
            import zipfile

            with open(template_path, "rb") as f:
                dotx_bytes = f.read()
            in_zip = zipfile.ZipFile(io.BytesIO(dotx_bytes))
            out_zip_io = io.BytesIO()
            with zipfile.ZipFile(out_zip_io, "w", zipfile.ZIP_DEFLATED) as out_zip:
                for item in in_zip.infolist():
                    content = in_zip.read(item.filename)
                    if item.filename == "[Content_Types].xml":
                        content_str = content.decode("utf-8").replace(
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml",
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
                        )
                        content = content_str.encode("utf-8")
                    out_zip.writestr(item, content)
            doc = Document(io.BytesIO(out_zip_io.getvalue()))
        else:
            doc = Document(template_path)
        _populate_fibs_header_and_clean_placeholders(doc, markdown_content, doc_metadata)
    else:
        doc = Document()

    _configure_fibs_document_defaults(doc)

    has_hyperlink_style = any(
        (s.name or "").lower() == "hyperlink" for s in doc.styles
    )

    lines = markdown_content.splitlines()
    body_links, glossary_links = _collect_glossary_link_anchors(lines)
    bm_counter = [1]

    last_kind: str | None = None
    if doc.paragraphs:
        last_kind = "empty" if not doc.paragraphs[-1].text.strip() else "body"

    i = 0
    has_content_written = False
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # 1. Page Number: e.g. ((45)) or ((316)) / ((317)) — zero hard page breaks (6a)
        m_page = _PAGE_MARKER_EXACT_RE.match(stripped)
        if m_page or (stripped.startswith("((") and stripped.endswith("))")):
            if last_kind not in (None, "empty"):
                _add_empty_fibs_paragraph(doc)
                last_kind = "empty"

            p = doc.add_paragraph()
            try:
                p.style = "Standard"
            except KeyError:
                p.style = "Normal"

            bm_names: list[str] = []
            if m_page:
                p_first = re.sub(r"[^0-9A-Za-z]+", "_", m_page.group(1)).strip("_")
                p_second = (
                    re.sub(r"[^0-9A-Za-z]+", "_", m_page.group(2)).strip("_")
                    if m_page.group(2)
                    else ""
                )
                if p_first:
                    bm_names.append(f"page_{p_first}")
                if p_first and p_second:
                    bm_names.append(f"page_{p_first}_{p_second}")
            else:
                page_val = re.sub(r"[^0-9A-Za-z]+", "_", stripped.strip("()")).strip("_")
                if page_val:
                    bm_names.append(f"page_{page_val}")

            if bm_names:
                try:
                    assigned_ids: list[str] = []
                    for bm_name in bm_names:
                        bm_id = str(bm_counter[0])
                        bm_counter[0] += 1
                        assigned_ids.append(bm_id)
                        bm_start = OxmlElement("w:bookmarkStart")
                        bm_start.set(qn("w:id"), bm_id)
                        bm_start.set(qn("w:name"), bm_name)
                        p._p.append(bm_start)

                    add_formatted_text(p, stripped)

                    for bm_id in reversed(assigned_ids):
                        bm_end = OxmlElement("w:bookmarkEnd")
                        bm_end.set(qn("w:id"), bm_id)
                        p._p.append(bm_end)
                except Exception as ex:
                    logger.warning("Failed to add bookmark for page %s: %s", stripped, ex)
                    add_formatted_text(p, stripped)
            else:
                add_formatted_text(p, stripped)

            _apply_fibs_paragraph_formatting(
                p, font_size_pt=fc.FIBS_BODY_FONT_SIZE_PT, space_after_pt=0.0
            )
            has_content_written = True
            last_kind = "page"
            i += 1
            continue

        # 2. Headings (Überschrift 1–5: 20/18/16/14/14 pt, 0 Pt before, 6 Pt after)
        heading_match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading_match:
            if last_kind not in (None, "empty", "page", "heading"):
                _add_empty_fibs_paragraph(doc)
                last_kind = "empty"

            level = min(len(heading_match.group(1)), 5)
            title_text = heading_match.group(2)

            p = doc.add_paragraph()
            try:
                p.style = f"Überschrift {level}"
            except KeyError:
                p.style = f"Heading {level}"

            add_formatted_text(p, title_text, is_heading=True)
            _apply_fibs_paragraph_formatting(
                p,
                font_size_pt=fc.FIBS_HEADING_SIZES_PT.get(level, fc.FIBS_BODY_FONT_SIZE_PT),
                space_after_pt=fc.FIBS_HEADING_SPACE_AFTER_PT,
                bold=True,
            )
            has_content_written = True
            last_kind = "heading"
            i += 1
            continue

        # 2.5 Multi-line FIBS Tags (<Rahmen>, <Bild>, <Anmerkung>, <Lückentext>)
        tag_block_match = re.match(
            r"^<(rahmen|bild|anmerkung|lückentext)\b[^>]*>(.*)$", stripped, re.IGNORECASE
        )
        if tag_block_match:
            tag_name = tag_block_match.group(1).lower()
            closing_tag = f"</{tag_name}>"
            start_i = i
            block_lines = [stripped]
            if not stripped.lower().endswith(closing_tag):
                i += 1
                while i < len(lines):
                    b_line = lines[i].strip()
                    if b_line:
                        block_lines.append(b_line)
                    if b_line.lower().endswith(closing_tag):
                        break
                    i += 1

            # Frontmatter <Anmerkung> at document start containing bullet items (FIBS §5.2 p. 17)
            if (
                tag_name == "anmerkung"
                and not has_content_written
                and len(block_lines) >= 3
                and any(re.match(r"^[-*•](?:\t+|\s+)", bl) for bl in block_lines[1:-1])
            ):
                if last_kind in ("tag", "table"):
                    _add_empty_fibs_paragraph(doc)
                for b_text in block_lines:
                    m_bul = re.match(r"^([-*•])(?:\t+|\s+)(.+)$", b_text)
                    p_anm = doc.add_paragraph()
                    if m_bul:
                        try:
                            p_anm.style = "Liste"
                        except KeyError:
                            try:
                                p_anm.style = "List"
                            except KeyError:
                                p_anm.style = "Normal"
                        marker_ch = "-" if m_bul.group(1) == "•" else m_bul.group(1)
                        add_formatted_text(p_anm, f"{marker_ch}\t{m_bul.group(2).strip()}")
                        _apply_fibs_paragraph_formatting(
                            p_anm, font_size_pt=fc.FIBS_BODY_FONT_SIZE_PT, space_after_pt=0.0
                        )
                        p_anm.paragraph_format.left_indent = Cm(1.0)
                        p_anm.paragraph_format.first_line_indent = Cm(-1.0)
                    else:
                        try:
                            p_anm.style = "Standard"
                        except KeyError:
                            p_anm.style = "Normal"
                        add_formatted_text(p_anm, b_text)
                        _apply_fibs_paragraph_formatting(
                            p_anm, font_size_pt=fc.FIBS_BODY_FONT_SIZE_PT, space_after_pt=0.0
                        )
                has_content_written = True
                last_kind = "tag"
                i += 1
                continue

            # FIBS Section 5.3 & 7.1.1: Lift standalone Abb./Figure title line inside <Bild> above as Überschrift 4
            lifted_h4 = False
            if tag_name == "bild" and len(block_lines) >= 3 and block_lines[0].lower() == "<bild>":
                first_inner = block_lines[1]
                if re.match(
                    r"^(?:Abb(?:ildung)?\.?|Bild|Grafik|Figure|Fig\.|M\d*)\s*\d*",
                    first_inner,
                    re.IGNORECASE,
                ):
                    if last_kind not in (None, "empty", "page", "heading"):
                        _add_empty_fibs_paragraph(doc)
                    p_title = doc.add_paragraph()
                    try:
                        p_title.style = "Überschrift 4"
                    except KeyError:
                        p_title.style = "Heading 4"
                    add_formatted_text(p_title, first_inner, is_heading=True)
                    _apply_fibs_paragraph_formatting(
                        p_title,
                        font_size_pt=fc.FIBS_BODY_FONT_SIZE_PT,
                        space_after_pt=fc.FIBS_HEADING_SPACE_AFTER_PT,
                        bold=True,
                    )
                    desc_start = block_lines[2]
                    if ":" not in desc_start.split()[0] and not desc_start.lower().startswith(
                        "beschreibung"
                    ):
                        desc_start = f"Darstellung: {desc_start}"
                    block_lines = [f"<Bild> {desc_start}"] + block_lines[3:]
                    lifted_h4 = True
                    last_kind = "heading"

            if not lifted_h4 and last_kind in ("tag", "table"):
                _add_empty_fibs_paragraph(doc)

            p = doc.add_paragraph()
            try:
                p.style = "Standard"
            except KeyError:
                p.style = "Normal"

            combined_links: dict[str, tuple[str, str]] = {}
            for ln_no in range(start_i, min(i + 1, len(lines))):
                if ln_no in body_links:
                    combined_links.update(body_links[ln_no])

            for b_idx, b_text in enumerate(block_lines):
                if b_idx > 0:
                    p.add_run().add_break()
                add_formatted_text(
                    p,
                    b_text,
                    link_specs=combined_links or None,
                    bm_counter=bm_counter,
                    has_hyperlink_style=has_hyperlink_style,
                )
            _apply_fibs_paragraph_formatting(
                p, font_size_pt=fc.FIBS_BODY_FONT_SIZE_PT, space_after_pt=0.0
            )
            has_content_written = True
            last_kind = "tag"
            i += 1
            continue

        # 3. Tables wrapped in <Tabelle>
        if stripped.lower() == "<tabelle>":
            if last_kind in ("tag", "table"):
                _add_empty_fibs_paragraph(doc)

            table_lines = []
            i += 1
            while i < len(lines) and lines[i].strip().lower() != "</tabelle>":
                table_lines.append(lines[i])
                i += 1

            p_start = doc.add_paragraph()
            try:
                p_start.style = "Standard"
            except KeyError:
                p_start.style = "Normal"
            p_start.add_run("<Tabelle>")
            _apply_fibs_paragraph_formatting(
                p_start, font_size_pt=fc.FIBS_BODY_FONT_SIZE_PT, space_after_pt=0.0
            )

            matrix = _parse_table_to_matrix(table_lines)
            if matrix:
                _write_table_to_docx(doc, matrix)
            else:
                for t_line in table_lines:
                    if t_line.strip():
                        p_t = doc.add_paragraph(t_line)
                        _apply_fibs_paragraph_formatting(
                            p_t, font_size_pt=fc.FIBS_BODY_FONT_SIZE_PT, space_after_pt=0.0
                        )

            p_end = doc.add_paragraph()
            try:
                p_end.style = "Standard"
            except KeyError:
                p_end.style = "Normal"
            p_end.add_run("</Tabelle>")
            _apply_fibs_paragraph_formatting(
                p_end, font_size_pt=fc.FIBS_BODY_FONT_SIZE_PT, space_after_pt=0.0
            )
            has_content_written = True
            last_kind = "table"
            i += 1
            continue

        # 3b. Standalone Markdown pipe table outside <Tabelle>
        if stripped.startswith("|") and ("|" in stripped[1:]):
            if last_kind in ("tag", "table"):
                _add_empty_fibs_paragraph(doc)

            pipe_lines = []
            while (
                i < len(lines)
                and lines[i].strip().startswith("|")
                and ("|" in lines[i].strip()[1:])
            ):
                pipe_lines.append(lines[i].strip())
                i += 1
            matrix = _parse_table_to_matrix(pipe_lines)
            if matrix and len(matrix) >= 1:
                _write_table_to_docx(doc, matrix)
            else:
                for pl in pipe_lines:
                    p_t = doc.add_paragraph(pl)
                    _apply_fibs_paragraph_formatting(
                        p_t, font_size_pt=fc.FIBS_BODY_FONT_SIZE_PT, space_after_pt=0.0
                    )
            has_content_written = True
            last_kind = "table"
            continue

        # 4. List Items (FIBS 2.1.1.2: Verdana 14pt, hanging indent 1 cm, marker + Tab (\t))
        list_match = re.match(r"^(\s*)([\-\*\+]|\d+\.)(?:\t+|\s+)(.*)$", line)
        if list_match and (("\t" in line) or re.match(r"^(\s*)([\-\*\+]|\d+\.)\s+", line)):
            indent = list_match.group(1)
            marker = list_match.group(2)
            content = list_match.group(3).lstrip()

            p = doc.add_paragraph()
            try:
                p.style = "Liste"
            except KeyError:
                try:
                    p.style = "List"
                except KeyError:
                    try:
                        p.style = "Standard"
                    except KeyError:
                        p.style = "Normal"

            if i in glossary_links:
                g_num, g_bm, g_target = glossary_links[i]
                m_gl = re.match(rf"^\^{re.escape(g_num)}([:.\t\s]+.*)$", content)
                if m_gl:
                    p.add_run(f"{marker}\t")
                    next_id = bm_counter[0]
                    bm_counter[0] += 1
                    _append_linked_bookmark_hyperlink(
                        p,
                        f"^{g_num}",
                        g_bm,
                        g_target,
                        next_id,
                        has_hyperlink_style=has_hyperlink_style,
                    )
                    add_formatted_text(p, m_gl.group(1))
                else:
                    add_formatted_text(p, f"{marker}\t{content}")
            else:
                add_formatted_text(
                    p,
                    f"{marker}\t{content}",
                    link_specs=body_links.get(i),
                    bm_counter=bm_counter,
                    has_hyperlink_style=has_hyperlink_style,
                )

            _apply_fibs_paragraph_formatting(
                p, font_size_pt=fc.FIBS_BODY_FONT_SIZE_PT, space_after_pt=0.0
            )
            level_mult = (len(indent) // 2) + 1
            p.paragraph_format.left_indent = Cm(1.0 * level_mult)
            p.paragraph_format.first_line_indent = Cm(-1.0)
            has_content_written = True
            last_kind = "list"
            i += 1
            continue

        # 5. Indented Paragraph (FIBS 2.1.1.2 Listenfortsetzung: Verdana 14pt, left indent 1 cm)
        indent_match = re.match(r"^(\s{2,})(.*)$", line)
        if indent_match and not stripped.startswith("<"):
            indent = indent_match.group(1)
            content = indent_match.group(2)

            p = doc.add_paragraph()
            try:
                p.style = "Listenfortsetzung"
            except KeyError:
                p.style = "List Continue"

            add_formatted_text(
                p,
                content,
                link_specs=body_links.get(i),
                bm_counter=bm_counter,
                has_hyperlink_style=has_hyperlink_style,
            )
            _apply_fibs_paragraph_formatting(
                p, font_size_pt=fc.FIBS_BODY_FONT_SIZE_PT, space_after_pt=0.0
            )
            p.paragraph_format.left_indent = Cm(1.0 * max(1, len(indent) // 2))
            p.paragraph_format.first_line_indent = Cm(0)
            has_content_written = True
            last_kind = "list"
            i += 1
            continue

        # 6. Standard Paragraph (including standalone ^n: glossary lines without list bullets)
        if last_kind in ("tag", "table"):
            _add_empty_fibs_paragraph(doc)

        p = doc.add_paragraph()
        try:
            p.style = "Standard"
        except KeyError:
            p.style = "Normal"

        if i in glossary_links:
            g_num, g_bm, g_target = glossary_links[i]
            m_gl_plain = re.match(rf"^\s*\^{re.escape(g_num)}([:.\t\s]+.*)$", line)
            if m_gl_plain:
                next_id = bm_counter[0]
                bm_counter[0] += 1
                _append_linked_bookmark_hyperlink(
                    p,
                    f"^{g_num}",
                    g_bm,
                    g_target,
                    next_id,
                    has_hyperlink_style=has_hyperlink_style,
                )
                add_formatted_text(p, m_gl_plain.group(1))
            else:
                add_formatted_text(p, line)
        else:
            add_formatted_text(
                p,
                line,
                link_specs=body_links.get(i),
                bm_counter=bm_counter,
                has_hyperlink_style=has_hyperlink_style,
            )

        _apply_fibs_paragraph_formatting(
            p, font_size_pt=fc.FIBS_BODY_FONT_SIZE_PT, space_after_pt=0.0
        )
        has_content_written = True
        last_kind = "body"
        i += 1

    doc.save(output_docx_path)
    logger.info("DOCX document written successfully: %s", output_docx_path)
    return output_docx_path


def _docx_heading_level(style_name: str) -> int:
    """Return the heading level (1–6) for Word heading styles, else 0.

    Args:
        style_name: Lowercase Word paragraph style name.

    Returns:
        Heading level integer in ``1..6`` or ``0`` if not a heading style.
    """
    m = re.search(r"(?:heading|überschrift)\s*([1-6])\b", style_name)
    if m:
        return int(m.group(1))
    m = re.fullmatch(r"h([1-6])", style_name.strip())
    return int(m.group(1)) if m else 0


def _docx_list_level(paragraph: Any, style_name: str) -> int:
    """Determine the 1-based nesting level of a list paragraph in a DOCX document.

    Args:
        paragraph: ``python-docx`` Paragraph object.
        style_name: Lowercase paragraph style name.

    Returns:
        Nesting level (``>= 1``) for list paragraphs, or ``0`` for non-list paragraphs.
    """
    if "continue" in style_name or "fortsetzung" in style_name:
        return 0

    text = paragraph.text.strip()
    has_marker = bool(fc.DOCX_LIST_MARKER_RE.match(text))
    p_pr = getattr(paragraph._p, "pPr", None)
    has_numpr = bool(p_pr is not None and getattr(p_pr, "numPr", None) is not None)
    is_auto_bullet_style = bool(
        re.match(r"^(?:list\s+(?:bullet|number)|listenpunkt|aufzählungszeichen)\b", style_name)
    )
    is_generic_list_style = bool(re.match(r"^(?:list|liste)\b", style_name))

    if not (is_auto_bullet_style or has_marker or (is_generic_list_style and has_numpr)):
        return 0

    m = re.search(r"\b([2-9])\s*$", style_name)
    if (is_auto_bullet_style or is_generic_list_style) and m:
        return int(m.group(1))

    indent = paragraph.paragraph_format.left_indent
    if indent is not None and indent.cm >= 1.5:
        return max(1, int(round(indent.cm)))
    return 1


def _extract_ordered_paragraph_runs(paragraph: Any) -> list[tuple[str, bool, bool]]:
    """Extract ordered ``(text, is_bold, is_italic)`` segments including ``w:hyperlink`` text."""
    from docx.text.run import Run

    segments: list[tuple[str, bool, bool]] = []
    for child in paragraph._p:
        tag = child.tag
        if tag.endswith("}r") or tag == "r":
            r_obj = Run(child, paragraph)
            if r_obj.text:
                b = r_obj.bold is True
                it = r_obj.italic is True and not b
                segments.append((r_obj.text, b, it))
        elif tag.endswith("}hyperlink") or tag == "hyperlink":
            hl_txt_parts: list[str] = []
            for sub in child:
                if sub.tag.endswith("}r") or sub.tag == "r":
                    sub_r = Run(sub, paragraph)
                    if sub_r.text:
                        hl_txt_parts.append(sub_r.text)
            if hl_txt_parts:
                segments.append(("".join(hl_txt_parts), False, False))
    return segments


def _extract_paragraph_markdown(paragraph: Any, is_heading: bool) -> str:
    """Extract paragraph text while preserving run-level bold (``*...*``) and italic (``_..._``).

    Skips run-level wrapping inside headings, FIBS XML-like structural tags, or runs
    that already carry explicit FIBS emphasis delimiters (including ``'_' + [B]'Wort' + '_'``).

    Args:
        paragraph: ``python-docx`` Paragraph object.
        is_heading: Whether the paragraph uses a heading style.

    Returns:
        Extracted Markdown string for the paragraph.
    """
    raw_text = paragraph.text.strip()
    if not raw_text:
        return ""
    if is_heading or raw_text.startswith(
        (
            "<Bild",
            "</Bild",
            "<Rahmen",
            "</Rahmen",
            "<Anmerkung",
            "</Anmerkung",
            "<Lückentext",
            "</Lückentext",
            "<Tabelle",
            "</Tabelle",
        )
    ):
        return raw_text

    ordered = _extract_ordered_paragraph_runs(paragraph)
    if not ordered or not any(b or it for _, b, it in ordered):
        return raw_text
    if "".join(t for t, _, _ in ordered).strip() != raw_text:
        return raw_text

    merged: list[tuple[str, bool, bool]] = []
    for txt, b, it in ordered:
        if merged and merged[-1][1] == b and merged[-1][2] == it:
            merged[-1] = (merged[-1][0] + txt, b, it)
        else:
            merged.append((txt, b, it))

    out_parts: list[str] = []
    seen_non_ws = False
    for seg_idx, (seg_text, is_bold, is_italic) in enumerate(merged):
        if not (is_bold or is_italic) or not seg_text.strip():
            if seg_text.strip():
                seen_non_ws = True
            out_parts.append(seg_text)
            continue

        prev_txt = merged[seg_idx - 1][0] if seg_idx > 0 else ""
        next_txt = merged[seg_idx + 1][0] if seg_idx + 1 < len(merged) else ""
        delimited_by_neighbors = (
            (
                prev_txt.endswith("_")
                and not prev_txt.endswith("__")
                and next_txt.startswith("_")
                and not next_txt.startswith("__")
            )
            or (
                prev_txt.endswith("*")
                and not prev_txt.endswith("**")
                and next_txt.startswith("*")
                and not next_txt.startswith("**")
            )
            or (prev_txt.endswith("%") and next_txt.startswith("%"))
        )
        if delimited_by_neighbors:
            seen_non_ws = True
            out_parts.append(seg_text)
            continue

        formatted_lines: list[str] = []
        for ln_idx, ln in enumerate(seg_text.split("\n")):
            m_ws = re.match(r"^(\s*)(.*?)(\s*)$", ln, re.DOTALL)
            if not m_ws or not m_ws.group(2):
                formatted_lines.append(ln)
                continue
            lead, core, trail = m_ws.groups()
            list_prefix = ""
            if not seen_non_ws and ln_idx == 0:
                m_marker = re.match(
                    r"^(?:[-*+•]|\d+[.)]|[a-zA-Z][.)]|\[[ xX]?\])(?:\t+|\s+)",
                    core,
                )
                if m_marker:
                    list_prefix = m_marker.group(0)
                    core = core[len(list_prefix) :]
            seen_non_ws = True
            if core:
                already_wrapped = (
                    (core.startswith("*") and core.endswith("*"))
                    or (core.startswith("_") and core.endswith("_"))
                    or (core.startswith("%") and core.endswith("%"))
                )
                if not already_wrapped:
                    core = f"*{core}*" if is_bold else f"_{core}_"
            formatted_lines.append(f"{lead}{list_prefix}{core}{trail}")
        out_parts.append("\n".join(formatted_lines))

    return "".join(out_parts).strip()


def extract_markdown_from_docx(docx_source: str) -> str:
    r"""Parse a Microsoft Word DOCX file and extract standard E-Buch Markdown text.

    Preserves heading hierarchies (``#`` … ``######``), list tabulations (``-\\t...``)
    including nesting (two spaces per extra level), run-level bold/italic emphasis
    (round-tripping ``'_' + [B]'Wort' + '_'`` cleanly as ``_Wort_``), tables, and
    bookmark page boundaries.

    Args:
        docx_source: Filesystem path to the ``.docx`` file.

    Returns:
        Extracted E-Buch Markdown string.

    Raises:
        FileNotFoundError: If ``docx_source`` does not exist.
    """
    if not os.path.exists(docx_source):
        raise FileNotFoundError(f"DOCX file not found: {docx_source}")

    doc = Document(docx_source)
    extracted_elements: list[str] = []
    open_tag_name: str | None = None
    open_tag_lines: list[str] = []

    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for element in doc.element.body:
        if element.tag.endswith("p"):
            p = Paragraph(element, doc)
            raw_stripped = p.text.strip()
            if not raw_stripped:
                continue

            if open_tag_name:
                style_name_inner = (p.style.name if p.style else "").lower()
                inner_txt = _extract_paragraph_markdown(p, is_heading=False)
                if _docx_list_level(p, style_name_inner) and not fc.DOCX_LIST_MARKER_RE.match(
                    raw_stripped
                ):
                    inner_txt = f"-\t{inner_txt}"
                open_tag_lines.append(inner_txt)
                if re.search(rf"</{open_tag_name}>\s*$", raw_stripped, re.IGNORECASE):
                    extracted_elements.append("\n".join(open_tag_lines))
                    open_tag_name = None
                    open_tag_lines = []
                continue

            m_open_tag = re.match(r"^<(Bild|Anmerkung)\b", raw_stripped, re.IGNORECASE)
            if m_open_tag and not re.search(
                rf"</{m_open_tag.group(1)}>\s*$", raw_stripped, re.IGNORECASE
            ):
                open_tag_name = m_open_tag.group(1)
                open_tag_lines = [raw_stripped]
                continue

            style_name = (p.style.name if p.style else "").lower()
            heading_level = _docx_heading_level(style_name)
            text = _extract_paragraph_markdown(p, is_heading=bool(heading_level))

            if heading_level:
                text = f"{'#' * heading_level} {text}" if not text.startswith("#") else text
            elif "listenfortsetzung" in style_name or "list continue" in style_name:
                text = f"  {text}"
            else:
                level = _docx_list_level(p, style_name)
                if level:
                    if not fc.DOCX_LIST_MARKER_RE.match(
                        raw_stripped
                    ) and not raw_stripped.startswith("\\to"):
                        text = f"-\t{text}"
                    text = "  " * (level - 1) + text

            extracted_elements.append(text)

        elif element.tag.endswith("tbl"):
            if open_tag_lines:
                extracted_elements.append("\n".join(open_tag_lines))
                open_tag_name = None
                open_tag_lines = []
            table = Table(element, doc)
            table_rows = []
            for row in table.rows:
                row_cells = [re.sub(r"\s+", " ", cell.text.strip()) for cell in row.cells]
                table_rows.append("| " + " | ".join(row_cells) + " |")

            if table_rows:
                header_cols = len(table.rows[0].cells)
                sep_row = "| " + " | ".join(["---"] * header_cols) + " |"
                md_table = [table_rows[0], sep_row] + table_rows[1:]
                extracted_elements.append("\n".join(md_table))

    if open_tag_lines:
        extracted_elements.append("\n".join(open_tag_lines))

    result_md = "\n\n".join(extracted_elements)
    logger.info("Extracted %d blocks from DOCX: %s", len(extracted_elements), docx_source)
    return result_md
