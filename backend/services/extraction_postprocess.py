"""Engine-neutral post-processing and hybrid Docling layout fusion for extracted Markdown."""

import hashlib
import json
import logging
import os
import re
import statistics
from typing import Any

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
    text = re.sub(r"\n+\s*(?:Seite|Page)\s+\d+\s*(?=\n+\(\(\d+\)\)|\Z)", "", text, flags=re.IGNORECASE)
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


def extract_docling_page_layout(pdf_path: str, images_dir: str) -> dict[str, Any]:
    """Run hybrid Docling CPU Layout & TableFormer extraction in a single pass.

    Extracts from any digital or scanned PDF:
      - pictures_by_page: {page_idx: [img_filename, ...]}
      - tables_by_page: {page_idx: [markdown_table, ...]}
      - furniture_by_page: {page_idx: [{"type": str, "text": str, "page_idx": int}, ...]}
      - heading_blocks: [{"type": "title", "text": str, "text_level": 1, "page_idx": int, "bbox": [0, 0, w, h], "is_body_sized": bool}, ...]
      - opening_headers_by_page: {page_idx: [heading_str, ...]} for chapter/section titles placed in the PDF running header
      - body_line_height: float
    """
    os.makedirs(images_dir, exist_ok=True)
    result: dict[str, Any] = {
        "pictures_by_page": {},
        "tables_by_page": {},
        "furniture_by_page": {},
        "heading_blocks": [],
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

        # 1. Tables per page
        if getattr(doc, "tables", None):
            for t_item in doc.tables:
                p_no = 1
                if getattr(t_item, "prov", None) and len(t_item.prov) > 0:
                    p_no = t_item.prov[0].page_no
                p_idx = max(0, p_no - 1)
                try:
                    t_md = t_item.export_to_markdown(doc=doc).strip()
                    if t_md and "|" in t_md:
                        result["tables_by_page"].setdefault(p_idx, []).append(t_md)
                except Exception:
                    pass

        # 2. Pictures per page
        if getattr(doc, "pictures", None):
            for idx, pic in enumerate(doc.pictures):
                p_no = 1
                if getattr(pic, "prov", None) and len(pic.prov) > 0:
                    p_no = pic.prov[0].page_no
                p_idx = max(0, p_no - 1)
                try:
                    pil_img = pic.get_image(doc)
                    if pil_img is not None and pil_img.width >= 30 and pil_img.height >= 30:
                        img_bytes = pil_img.tobytes()
                        img_hash = hashlib.sha256(img_bytes).hexdigest()[:16]
                        img_filename = f"picture_{p_idx}_{idx}_{img_hash}.png"
                        img_path = os.path.join(images_dir, img_filename)
                        pil_img.save(img_path, format="PNG")
                        result["pictures_by_page"].setdefault(p_idx, []).append(img_filename)
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

            if layer == ContentLayer.FURNITURE or lbl in ("page_header", "page_footer"):
                f_type = "page_header" if "header" in lbl else "page_footer"
                result["furniture_by_page"].setdefault(p_idx, []).append({
                    "type": f_type,
                    "text": txt,
                    "page_idx": p_idx,
                })
                if f_type == "page_header":
                    open_hdr = parse_furniture_opening_header(txt, seen_opening_keys)
                    if open_hdr:
                        result["opening_headers_by_page"].setdefault(p_idx, []).append(open_hdr)
                continue

            if lbl in ("text", "list_item") and 5.0 <= h <= 18.0 and 15 <= len(txt) <= 75 and w >= 80:
                body_heights.append(h)
            elif lbl in ("section_header", "title"):
                in_callout = is_bbox_inside_callout_rect(bbox_obj, txt, callout_rects_by_page.get(p_idx, []))
                raw_headings.append({
                    "text": txt,
                    "page_idx": p_idx,
                    "h": h,
                    "w": w,
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
            result["heading_blocks"].append({
                "type": "title",
                "text": txt,
                "text_level": 1,
                "page_idx": rh["page_idx"],
                "bbox": [0, 0, w, single_h],
                "is_body_sized": is_body_sized,
                "is_callout_box": rh.get("in_callout", False),
            })

    except Exception as e:
        logger.warning(f"Docling page layout extraction fallback: {e}")

    return result


def _enrich_flattened_tables_with_docling(cleaned_text: str, page_tables: list[str]) -> str:
    """Replaces VLM-flattened borderless tables in ``cleaned_text`` with structured
    Markdown pipe tables from Docling's TableFormer, or appends missed tables.
    """
    if not page_tables:
        return cleaned_text

    if "|" not in cleaned_text:
        return cleaned_text.strip() + "\n\n" + "\n\n".join(page_tables)

    # Check each Docling table: if its distinct cell tokens are absent from existing pipe tables
    # but appear as plain text lines, append or splice the table.
    existing_pipe_lines = "\n".join(
        ln for ln in cleaned_text.splitlines() if ln.strip().startswith("|")
    ).lower()
    for t_md in page_tables:
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


def fuse_vlm_page_with_docling(
    raw_text: str,
    page_images: list[str],
    phys_num: int,
    page_tables: list[str] | None = None,
    opening_headers: list[str] | None = None,
) -> str:
    r"""Fuse a raw VLM OCR page with Docling layout crops, tables, and running header/footer stripping.

    1. Strips code fences, cleans HTML layout wrappers, unescapes \$...\$, and converts HTML <table> to pipe tables.
    2. Strips running footers / lone page numbers and all-caps running top headers (while rescuing opening chapter banners).
    3. Deduplicates repeated figure captions and unwraps heading/italic formatting on captions.
    4. Matches Docling-cropped layout figures (page_images) to inline placeholders and figure captions.
    5. Fuses borderless tables from Docling TableFormer (page_tables) when missed by the VLM.
    6. Repairs broken intra-line hyphenations and injects the physical page marker ((phys_num)).
    """
    cleaned_text = clean_markdown_fences(fix_escaped_dollars(raw_text))
    cleaned_text = convert_html_tables_to_markdown(cleaned_text)

    # 1. Strip running footers / page numbers at start or end of page
    generic_footer_patterns = [
        r"^\s*\d{1,4}\s*\n+",
        r"\n+\s*\[?\s*(?:Seite|Page)\s+\d+\s*\]?\s*$",
        r"\n+\s*\d{1,4}\s*$",
        r"\n+\s*(?:\d+\s+[-–—\s/|]\s+[A-ZÄÖÜa-zäöü0-9\s]{2,50}|[A-ZÄÖÜa-zäöü0-9\s]{2,50}\s+[-–—\s/|]\s+\d+)\s*$",
        r"\n+\s*\d+\s+[A-ZÄÖÜa-zäöü0-9\s]{2,50}\s*$",
        r"\n+\s*[A-ZÄÖÜa-zäöü0-9\s]{2,50}\s+\d+\s*$",
    ]
    for fp in generic_footer_patterns:
        cleaned_text = re.sub(fp, "", cleaned_text, flags=re.IGNORECASE)

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
        cleaned_text = _enrich_flattened_tables_with_docling(cleaned_text, page_tables)

    # 5. Place any remaining unmatched images after top page marker or at top
    if remaining_images:
        appended_imgs = "\n\n".join([f"![](images/{fn})" for fn in remaining_images])
        page_marker_match = re.search(r"^(\(\(\d+\)\)\s*\n+)", cleaned_text)
        if page_marker_match:
            idx = page_marker_match.end()
            cleaned_text = cleaned_text[:idx] + appended_imgs + "\n\n" + cleaned_text[idx:]
        else:
            cleaned_text = appended_imgs + "\n\n" + cleaned_text

    # 6. Clean stray space after hyphens in broken words (e.g. Zellkompartimen- ten -> Zellkompartimenten)
    cleaned_text = re.sub(r"([a-zA-ZäöüÄÖÜß]{2,})-\s+([a-zäöüß][a-zA-ZäöüÄÖÜß]{2,})", r"\1\2", cleaned_text)

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


def recover_text_truncation(markdown_content: str, pdf_path: str | None = None) -> str:
    """Subtask 1: Text-Truncation & De-Hyphenation Recovery
    - Strips PDF print-production slugs (.indd timestamps), soft hyphens (\u00ad, \ufffe), and PUA glyphs.
    - Joins soft wraps and hyphenated words across line, column, and page boundaries.
    - Preserves Markdown structure, headings, lists, tables, and page boundaries.
    - Cleans runaway token repetition loops.
    """
    if not markdown_content:
        return markdown_content

    processed = fix_escaped_dollars(markdown_content)

    # 0a. If a digital PDF page was largely swallowed into a picture bbox (< 25 words extracted and PDF has > 2x tokens),
    #     recover the embedded PDF text layer lines via pypdfium2.
    if pdf_path and os.path.exists(pdf_path) and pdf_path.lower().endswith(".pdf"):
        clean_no_imgs = re.sub(r"!\[.*?\]\(.*?\)|\(\(\d+\)\)", "", processed)
        extracted_tokens = re.findall(r"\S{2,}", clean_no_imgs)
        if len(extracted_tokens) < 25:
            try:
                import pypdfium2 as pdfium
                pdoc = pdfium.PdfDocument(pdf_path)
                pdf_lines = []
                for page in pdoc:
                    raw_pt = page.get_textpage().get_text_range() or ""
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

    # 0b. Strip InDesign print-production slug lines (e.g. 'DO01_...indd 18 11.11.2025 15:08:08')
    processed = re.sub(
        r"(?m)^[ \t]*\S+\.indd[ \t]+\d{1,4}[ \t]+\d{2}\.\d{2}\.\d{4}(?:[ \t]+\d{2}:\d{2}(?::\d{2})?)?[ \t]*\n?",
        "",
        processed,
        flags=re.IGNORECASE,
    )
    # 0b. Strip Private Use Area (PUA) icon glyphs (\ue000..\uf8ff)
    processed = re.sub(r"[\ue000-\uf8ff]", "", processed)
    # 0c. Normalize PDF soft hyphens (\u00ad) and \ufffe hyphenation markers
    processed = re.sub(r"([a-zA-ZäöüÄÖÜß])[\u00ad\ufffe][ \t]*(?=\n)", r"\1-", processed)
    processed = re.sub(r"([a-zA-ZäöüÄÖÜß])[\u00ad\ufffe]([a-zäöüß])", r"\1\2", processed)
    processed = processed.replace("\u00ad", "").replace("\ufffe", "-")

    # 1. Join hyphenated words split across lines and page boundaries (including spread markers ((N)) / ((N+1)))
    hyphen_pattern = r"([a-zA-ZäöüÄÖÜß]{2,})-[ \t]*\n+(?:(\(\(\d+\)\)(?:\s*/\s*\(\(\d+\)\))?)[ \t]*\n+)?[ \t]*([a-zA-ZäöüÄÖÜß]{2,})([.,;:!?])?[ \t]*"

    def replace_hyphen(match: re.Match) -> str:
        part1 = match.group(1)
        page_break = match.group(2)
        part2 = match.group(3)
        punct = match.group(4) or ""
        if part2 and part2[0].isupper() and part1[-1].islower():
            part2 = part2[0].lower() + part2[1:]
        joined = part1 + part2 + punct
        if page_break:
            return f"{joined}\n\n{page_break}\n\n"
        return joined

    processed = re.sub(hyphen_pattern, replace_hyphen, processed)
    # Also repair pre-joined cross-page camelCase hyphenations (e.g. 'SelbstaufGabe ((86))\n. Dieser' -> 'Selbstaufgabe.\n\n((86))\n\nDieser')
    processed = re.sub(
        r"\b([A-ZÄÖÜa-zäöüß]{2,}[a-zäöüß])([A-ZÄÖÜ][a-zäöüß]{2,})[ \t]+(\(\(\d+\)\))[ \t]*\n+[ \t]*([.,;:!?])[ \t]*",
        lambda m: f"{m.group(1)}{m.group(2).lower()}{m.group(4)}\n\n{m.group(3)}\n\n",
        processed,
    )
    # Join in-line hyphenated words with spaces where second part starts with lowercase (e.g. 'Brechungs- winkel' -> 'Brechungswinkel')
    processed = re.sub(
        r"\b([a-zA-ZäöüÄÖÜß]{3,})-\s+([a-zäöüß][a-zA-ZäöüÄÖÜß]{2,})\b",
        r"\1\2",
        processed,
    )

    # 1b. Rejoin 2-column split paragraphs when a mid-page table/figure block displaced the column-2 continuation:
    # e.g. Paragraph 1 ends with 'Reaktionsgeschwindig-' followed by a table/figure block and then a paragraph starting with 'keit v von der...'
    displaced_col2_re = re.compile(
        r"([a-zA-ZäöüÄÖÜß]{3,})-[ \t]*\n\n((?:(?!(?:\(\(\d+\)\))).)+?)\n\n([a-zäöüß]{2,}\b[^\n]+(?:\n(?![ \t]*(?:\n|#{1,6}\s|\(\(|\||!\[|<))[^\n]+)*)",
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
            and not re.match(r"^(?:#{1,6}\s|\(\(\d+\)\)|[-*•]\s|\d+\.\s|[a-z]\)\s|\||<|!\[|\[?\d+\]\s)", s)
            and not re.match(r"^(?:#{1,6}\s|\(\(\d+\)\)|\||<|!\[|\*\*.*\*\*$)", merged_lines[-1].strip())
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
                    raw_heights = sorted(list(set(h for _, h in title_blocks)), reverse=True)
                    clusters: list[float] = []
                    for h in raw_heights:
                        if not clusters or abs(clusters[-1] - h) > 0.6:
                            clusters.append(h)

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
                    raw_heights = sorted(list(set(h for _, h in filtered_tb)), reverse=True)
                    clusters = []
                    for h in raw_heights:
                        if not clusters or abs(clusters[-1] - h) > 0.6:
                            clusters.append(h)
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
    html_split_pattern = r"</table>\s*\n+(?:(\(\(\d+\)\))\s*\n+)?\s*<table\b[^>]*>"

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

    pages = re.split(r"(\(\(\d+\)\))", markdown_content)
    segments = [i for i in range(len(pages)) if not re.match(r"^\(\(\d+\)\)$", pages[i])]

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
        m_pg = re.match(r"^\(\((\d+)\)\)$", part)
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
            if current_page_num and stripped == current_page_num:
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
    if not re.search(r"\(\(\d+\)\)", result):
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
