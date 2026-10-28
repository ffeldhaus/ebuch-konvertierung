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


def add_formatted_text(paragraph: Any, text: str) -> None:
    """Parse E-Buch formatting markers and write them into a Word paragraph.

    Parses ``*bold*``, ``%italic%``, and ``_highlight_`` in ``text`` and writes them
    using run-level formatting while keeping the markers literally in the text.
    Note: Highlighted text (``_text_``) must not use Word underline formatting.

    Args:
        paragraph: Target ``python-docx`` paragraph instance.
        text: Text string containing optional FIBS inline markers.
    """
    text = sanitize_xml_string(text)
    tokens = re.split(r"(\*[^*]+\*|%[^%]+%|_[^_]+_)", text)

    for token in tokens:
        if not token:
            continue
        if token.startswith("*") and token.endswith("*"):
            run = paragraph.add_run(token)
            run.bold = True
        elif token.startswith("%") and token.endswith("%"):
            run = paragraph.add_run(token)
            run.italic = True
        else:
            paragraph.add_run(token)


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


def convert_markdown_to_docx(
    markdown_content: str,
    output_docx_path: str,
    template_path: str | None = None,
) -> str:
    r"""Convert E-Buch standardised Markdown to a native FIBS 09/2025 compliant DOCX file.

    Enforces official FIBS-Dokumentvorlage specifications (Übertragungsregeln Stand 09/2025, Section 2.1.1):
      - Margins: all 2 cm
      - Font: Verdana across entire document, line spacing 1.5
      - Standard: 14 pt, 0 Pt before, 0 Pt after
      - Überschrift 1–5: 20 pt, 18 pt, 16 pt, 14 pt, 14 pt (0 Pt before, 6 Pt after)
      - Liste: 14 pt, hanging indent 1 cm (left 1 cm, first line -1 cm), marker + Tab (``\\t``)
      - Listenfortsetzung: 14 pt, left indent 1 cm
      - Tags (``<Bild>``, ``<Rahmen>``, ``<Anmerkung>``, ``<Lückentext>``): single paragraphs with soft returns (``w:br``)

    Args:
        markdown_content: Standardised E-Buch Markdown text.
        output_docx_path: Destination path for the generated ``.docx`` file.
        template_path: Optional ``.docx`` or ``.dotx`` template path.

    Returns:
        The ``output_docx_path`` where the document was saved.
    """
    from docx.shared import Cm

    markdown_content = sanitize_xml_string(markdown_content or "")
    os.makedirs(os.path.dirname(output_docx_path), exist_ok=True)
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
    else:
        doc = Document()

    _configure_fibs_document_defaults(doc)

    lines = markdown_content.splitlines()
    i = 0
    has_content_written = False
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # 1. Page Number: e.g. ((45))
        if stripped.startswith("((") and stripped.endswith("))"):
            if has_content_written:
                doc.add_page_break()
            p = doc.add_paragraph()
            try:
                p.style = "Standard"
            except KeyError:
                p.style = "Normal"

            page_val = re.sub(r"[^0-9A-Za-z]+", "_", stripped.strip("()")).strip("_")
            if page_val:
                try:
                    from docx.oxml import OxmlElement
                    from docx.oxml.ns import qn

                    bm_id = str(i + 1)
                    bm_name = f"page_{page_val}"
                    bm_start = OxmlElement("w:bookmarkStart")
                    bm_start.set(qn("w:id"), bm_id)
                    bm_start.set(qn("w:name"), bm_name)
                    p._p.append(bm_start)

                    add_formatted_text(p, line)

                    bm_end = OxmlElement("w:bookmarkEnd")
                    bm_end.set(qn("w:id"), bm_id)
                    p._p.append(bm_end)
                except Exception as ex:
                    logger.warning("Failed to add bookmark for page %s: %s", page_val, ex)
                    add_formatted_text(p, line)
            else:
                add_formatted_text(p, line)
            _apply_fibs_paragraph_formatting(p, font_size_pt=fc.FIBS_BODY_FONT_SIZE_PT, space_after_pt=0.0)
            has_content_written = True
            i += 1
            continue

        # 2. Headings (Überschrift 1–5: 20/18/16/14/14 pt, 0 Pt before, 6 Pt after)
        heading_match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading_match:
            level = min(len(heading_match.group(1)), 5)
            title_text = heading_match.group(2)

            p = doc.add_paragraph()
            try:
                p.style = f"Überschrift {level}"
            except KeyError:
                p.style = f"Heading {level}"

            add_formatted_text(p, title_text)
            _apply_fibs_paragraph_formatting(
                p,
                font_size_pt=fc.FIBS_HEADING_SIZES_PT.get(level, fc.FIBS_BODY_FONT_SIZE_PT),
                space_after_pt=fc.FIBS_HEADING_SPACE_AFTER_PT,
                bold=True,
            )
            has_content_written = True
            i += 1
            continue

        # 2.5 Multi-line FIBS Tags (<Rahmen>, <Bild>, <Anmerkung>, <Lückentext>) rendered with soft returns (w:br)
        tag_block_match = re.match(r"^<(rahmen|bild|anmerkung|lückentext)\b[^>]*>(.*)$", stripped, re.IGNORECASE)
        if tag_block_match:
            tag_name = tag_block_match.group(1).lower()
            closing_tag = f"</{tag_name}>"
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

            # FIBS Section 5.3 & 7.1.1: Lift standalone Abb./Figure title line inside <Bild> above as Überschrift 4
            if tag_name == "bild" and len(block_lines) >= 3 and block_lines[0].lower() == "<bild>":
                first_inner = block_lines[1]
                if re.match(r"^(?:Abb(?:ildung)?\.?|Bild|Grafik|Figure|Fig\.|M\d*)\s*\d*", first_inner, re.IGNORECASE):
                    p_title = doc.add_paragraph()
                    try:
                        p_title.style = "Überschrift 4"
                    except KeyError:
                        p_title.style = "Heading 4"
                    add_formatted_text(p_title, first_inner)
                    _apply_fibs_paragraph_formatting(
                        p_title,
                        font_size_pt=fc.FIBS_BODY_FONT_SIZE_PT,
                        space_after_pt=fc.FIBS_HEADING_SPACE_AFTER_PT,
                        bold=True,
                    )
                    desc_start = block_lines[2]
                    if ":" not in desc_start.split()[0] and not desc_start.lower().startswith("beschreibung"):
                        desc_start = f"Darstellung: {desc_start}"
                    block_lines = [f"<Bild> {desc_start}"] + block_lines[3:]

            p = doc.add_paragraph()
            try:
                p.style = "Standard"
            except KeyError:
                p.style = "Normal"

            for b_idx, b_text in enumerate(block_lines):
                if b_idx > 0:
                    p.add_run().add_break()
                add_formatted_text(p, b_text)
            _apply_fibs_paragraph_formatting(p, font_size_pt=fc.FIBS_BODY_FONT_SIZE_PT, space_after_pt=0.0)
            has_content_written = True
            i += 1
            continue

        # 3. Tables wrapped in <Tabelle>
        if stripped.lower() == "<tabelle>":
            table_lines = []
            i += 1
            while i < len(lines) and lines[i].strip().lower() != "</tabelle>":
                table_lines.append(lines[i])
                i += 1

            p_start = doc.add_paragraph()
            p_start.add_run("<Tabelle>")
            _apply_fibs_paragraph_formatting(p_start, font_size_pt=fc.FIBS_BODY_FONT_SIZE_PT, space_after_pt=0.0)

            matrix = _parse_table_to_matrix(table_lines)
            if matrix:
                _write_table_to_docx(doc, matrix)
            else:
                for t_line in table_lines:
                    if t_line.strip():
                        p_t = doc.add_paragraph(t_line)
                        _apply_fibs_paragraph_formatting(p_t, font_size_pt=fc.FIBS_BODY_FONT_SIZE_PT, space_after_pt=0.0)

            p_end = doc.add_paragraph()
            p_end.add_run("</Tabelle>")
            _apply_fibs_paragraph_formatting(p_end, font_size_pt=fc.FIBS_BODY_FONT_SIZE_PT, space_after_pt=0.0)
            has_content_written = True
            i += 1
            continue

        # 3b. Standalone Markdown pipe table outside <Tabelle>
        if stripped.startswith("|") and ("|" in stripped[1:]):
            pipe_lines = []
            while i < len(lines) and lines[i].strip().startswith("|") and ("|" in lines[i].strip()[1:]):
                pipe_lines.append(lines[i].strip())
                i += 1
            matrix = _parse_table_to_matrix(pipe_lines)
            if matrix and len(matrix) >= 1:
                _write_table_to_docx(doc, matrix)
            else:
                for pl in pipe_lines:
                    p_t = doc.add_paragraph(pl)
                    _apply_fibs_paragraph_formatting(p_t, font_size_pt=fc.FIBS_BODY_FONT_SIZE_PT, space_after_pt=0.0)
            has_content_written = True
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
                    p.style = "Standard"
                except KeyError:
                    p.style = "Normal"

            add_formatted_text(p, f"{marker}\t{content}")
            _apply_fibs_paragraph_formatting(p, font_size_pt=fc.FIBS_BODY_FONT_SIZE_PT, space_after_pt=0.0)
            level_mult = (len(indent) // 2) + 1
            p.paragraph_format.left_indent = Cm(1.0 * level_mult)
            p.paragraph_format.first_line_indent = Cm(-1.0)
            has_content_written = True
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

            add_formatted_text(p, content)
            _apply_fibs_paragraph_formatting(p, font_size_pt=fc.FIBS_BODY_FONT_SIZE_PT, space_after_pt=0.0)
            p.paragraph_format.left_indent = Cm(1.0 * max(1, len(indent) // 2))
            p.paragraph_format.first_line_indent = Cm(0)
            has_content_written = True
            i += 1
            continue

        # 6. Standard Paragraph
        p = doc.add_paragraph()
        try:
            p.style = "Standard"
        except KeyError:
            p.style = "Normal"

        add_formatted_text(p, line)
        _apply_fibs_paragraph_formatting(p, font_size_pt=fc.FIBS_BODY_FONT_SIZE_PT, space_after_pt=0.0)
        has_content_written = True
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
    is_list_style = (
        bool(re.match(r"^(?:list|liste|listenpunkt|aufzählungszeichen)\b", style_name))
        and "continue" not in style_name
        and "fortsetzung" not in style_name
    )
    m = re.search(r"\b([2-9])\s*$", style_name)
    if is_list_style and m:
        return int(m.group(1))

    text = paragraph.text.strip()
    if not (is_list_style or fc.DOCX_LIST_MARKER_RE.match(text)):
        return 0
    indent = paragraph.paragraph_format.left_indent
    if indent is not None and indent.cm >= 1.5:
        return max(1, int(round(indent.cm)))
    return 1


def extract_markdown_from_docx(docx_source: str) -> str:
    r"""Parse a Microsoft Word DOCX file and extract standard E-Buch Markdown text.

    Preserves heading hierarchies (``#`` … ``######``), list tabulations (``-\\t...``)
    including nesting (two spaces per extra level), tables, and bookmark page boundaries.

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
    extracted_elements = []

    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for element in doc.element.body:
        if element.tag.endswith("p"):
            p = Paragraph(element, doc)
            text = p.text.strip()
            if not text:
                continue

            style_name = (p.style.name if p.style else "").lower()
            heading_level = _docx_heading_level(style_name)

            if heading_level:
                text = f"{'#' * heading_level} {text}" if not text.startswith("#") else text
            elif "listenfortsetzung" in style_name or "list continue" in style_name:
                text = f"  {text}"
            else:
                level = _docx_list_level(p, style_name)
                if level:
                    if not fc.DOCX_LIST_MARKER_RE.match(text) and not text.startswith("\\to"):
                        text = f"-\t{text}"
                    text = "  " * (level - 1) + text

            extracted_elements.append(text)

        elif element.tag.endswith("tbl"):
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

    result_md = "\n\n".join(extracted_elements)
    logger.info("Extracted %d blocks from DOCX: %s", len(extracted_elements), docx_source)
    return result_md
