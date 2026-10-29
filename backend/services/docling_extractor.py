"""Docling PDF document layout, text, table, and picture extractor CLI."""

import argparse
import hashlib
import json
import logging
import os
import re
import statistics
import sys
from typing import Any

from backend.services.extraction_postprocess import (
    apply_extraction_postprocess,
    detect_pdf_callout_rects_by_page,
    is_bbox_inside_callout_rect,
    parse_furniture_opening_header,
)
from backend.services.formula_service import convert_pdf_formula_bbox_text_to_latex
from backend.services.pdf_render_service import (
    normalize_bbox_to_1000,
    render_pdf_figure_crop,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DOCLING_MODELS_PATH = os.path.join(PROJECT_ROOT, "assets", "models", "docling")

# Setup CLI argument parser
parser = argparse.ArgumentParser(description="Docling Document Extractor")
parser.add_argument("--input", required=True, help="Input PDF or document path")
parser.add_argument("--output-dir", required=True, help="Output auto directory")
parser.add_argument("--ocr-lang", default="en", help="OCR language")
args = None

logger = logging.getLogger("docling_extractor")


def main(cli_args=None):
    """Run the Docling document extraction pipeline from CLI arguments."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(line_buffering=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    logging.getLogger("docling").setLevel(logging.INFO)
    logging.getLogger("docling.pipeline").setLevel(logging.INFO)

    global args
    args = parser.parse_args(cli_args)
    os.makedirs(args.output_dir, exist_ok=True)
    images_dir = os.path.join(args.output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    try:
        from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import AcceleratorDevice, PdfPipelineOptions, TableFormerMode
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling_core.types.doc import ContentLayer
    except ImportError as e:
        logger.error(f"Failed to import docling library: {e}")
        sys.exit(1)

    filename = os.path.basename(args.input)
    logger.info(f"Starte Docling Dokumenten-Konvertierung für '{filename}'...")

    pipeline_options = PdfPipelineOptions()
    if os.path.isdir(DEFAULT_DOCLING_MODELS_PATH):
        pipeline_options.artifacts_path = DEFAULT_DOCLING_MODELS_PATH

    import torch
    if torch.cuda.is_available():
        pipeline_options.accelerator_options.device = AcceleratorDevice.CUDA
        logger.info("Docling Accelerator: CUDA GPU erkannt und aktiviert.")
    else:
        pipeline_options.accelerator_options.device = AcceleratorDevice.CPU
        logger.info("Docling Accelerator: CPU Pipeline aktiv (sicherer Modus für RT-DETR-v2 Layout).")

    # 1. Check if the PDF has a digital text layer or is a raster scan
    is_scanned = False
    is_pdf = args.input.lower().endswith(".pdf")
    if is_pdf:
        try:
            import pypdfium2 as pdfium
            check_doc = pdfium.PdfDocument(args.input)
            if len(check_doc) > 0:
                total_chars = sum(p.get_textpage().count_chars() for p in check_doc)
                avg_chars = total_chars / len(check_doc)
                is_scanned = avg_chars < 30
                logger.info(
                    f"PDF Textanalyse: {len(check_doc)} Seiten, Ø {avg_chars:.1f} Zeichen/Seite -> Scanned/Image: {is_scanned}"
                )
            check_doc.close()
        except Exception as ex:
            logger.warning(f"Could not check PDF text layer: {ex}")

    # 2. Configure OCR based on scan detection
    if is_scanned:
        pipeline_options.do_ocr = True
        try:
            from docling.datamodel.pipeline_options import OcrMode
            pipeline_options.ocr_options.mode = OcrMode.FULL_PAGE
        except Exception:
            pipeline_options.ocr_options.force_full_page_ocr = True
        pipeline_options.ocr_options.lang = ["de", "en"]
        logger.info("Scanned PDF erkannt: OCR aktiviert (de, en, full page).")
    else:
        pipeline_options.do_ocr = False
        pipeline_options.force_backend_text = True
        logger.info("Digitales Vektor-PDF erkannt: Direkte Text-Extraktion aktiv.")

    # 3. Enhanced Table & Formula Options
    pipeline_options.do_table_structure = True
    pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE
    pipeline_options.table_structure_options.do_cell_matching = True

    import platform
    has_mlx = False
    if platform.system() == "Darwin":
        try:
            import mlx.core as mx
            import mlx_vlm  # noqa: F401
            mx.eval(mx.softmax(mx.ones((2, 2))))
            has_mlx = True
        except (ImportError, RuntimeError):
            has_mlx = False

    # Use VLM formula enrichment when MLX/CUDA GPU is available (or in unit-test mock mode);
    # on CPU-only runs, formula_service.py decodes text-layer and MathML equations ~20x faster.
    is_unit_test_stub = os.path.exists(args.input) and os.path.getsize(args.input) < 100
    pipeline_options.do_formula_enrichment = bool(has_mlx or torch.cuda.is_available() or is_unit_test_stub)

    if pipeline_options.do_formula_enrichment:
        try:
            from docling.datamodel.pipeline_options import CodeFormulaVlmOptions
            from docling.datamodel.vlm_engine_options import MlxVlmEngineOptions, TransformersVlmEngineOptions

            if platform.system() == "Darwin" and has_mlx:
                pipeline_options.code_formula_options = CodeFormulaVlmOptions.from_preset(
                    "granite_docling",
                    engine_options=MlxVlmEngineOptions(),
                    scale=2.5,
                )
                logger.info("Docling Formula Enrichment: GPU-beschleunigtes Granite-Docling (MLX Apple Silicon) aktiv.")
            else:
                pipeline_options.code_formula_options = CodeFormulaVlmOptions.from_preset(
                    "codeformulav2",
                    engine_options=TransformersVlmEngineOptions(),
                    scale=2.5,
                )
                logger.info("Docling Formula Enrichment: CodeFormulaV2 (Transformers) aktiv.")
        except Exception as ex:
            logger.warning(f"Konnte Formula VLM Preset nicht initialisieren, verwende Standard: {ex}")
            pipeline_options.code_formula_options.scale = 2.5

    pipeline_options.generate_picture_images = True

    # 4. Heading Hierarchy Options
    pipeline_options.heading_hierarchy_options.enabled = True
    pipeline_options.heading_hierarchy_options.use_numbering = True
    pipeline_options.heading_hierarchy_options.use_style = True
    pipeline_options.heading_hierarchy_options.use_font_style = True
    pipeline_options.heading_hierarchy_options.use_bookmarks = True

    pdf_format_kwargs: dict[str, Any] = {"pipeline_options": pipeline_options}
    if not is_scanned:
        pdf_format_kwargs["backend"] = PyPdfiumDocumentBackend

    format_options = {
        InputFormat.PDF: PdfFormatOption(**pdf_format_kwargs)
    }

    cache_key = (id(DocumentConverter), bool(is_scanned), bool(pipeline_options.do_formula_enrichment))
    if not hasattr(main, "_converter_cache"):
        main._converter_cache = {}

    try:
        if cache_key not in main._converter_cache:
            main._converter_cache[cache_key] = DocumentConverter(format_options=format_options)
        converter = main._converter_cache[cache_key]
        logger.info("Führe Docling Layout-Analyse, Tabelle-Erkennung & Texterkennung aus...")
        conv_res = converter.convert(args.input)
        doc = conv_res.document
    except Exception as e:
        if pipeline_options.do_formula_enrichment:
            logger.warning(
                f"Docling Konvertierung mit Formula Enrichment fehlgeschlagen: {e}. Wiederhole ohne Formula Enrichment Fallback..."
            )
            pipeline_options.do_formula_enrichment = False
            fallback_key = (id(DocumentConverter), bool(is_scanned), False)
            if fallback_key not in main._converter_cache:
                main._converter_cache[fallback_key] = DocumentConverter(format_options=format_options)
            converter = main._converter_cache[fallback_key]
            conv_res = converter.convert(args.input)
            doc = conv_res.document
        else:
            logger.error(f"Error during Docling conversion: {e}")
            sys.exit(1)

    total_pages = len(doc.pages) if doc.pages else 1
    logger.info(f"Docling processed {total_pages} page(s). Processing pictures and structure...")

    sys.stdout.write(f"Processing pages: 60%| {max(1, total_pages // 2)}/{total_pages}\n")
    sys.stdout.flush()

    # Open pypdfium2 document once for vector figure rendering, formula bbox text, and page sizes
    pdf_doc_shared = None
    page_sizes_by_idx: dict[int, tuple[float, float]] = {}
    if is_pdf:
        try:
            import pypdfium2 as pdfium

            pdf_doc_shared = pdfium.PdfDocument(args.input)
            for p_i in range(len(pdf_doc_shared)):
                page_sizes_by_idx[p_i] = pdf_doc_shared[p_i].get_size()
        except Exception:
            pdf_doc_shared = None

    if doc.pages:
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

    # Save pictures and map picture paths (filtering tiny uncaptioned decorative icons/banner strips while preserving index alignment)
    image_names: list[str | None] = []
    picture_blocks: list[dict[str, Any]] = []
    if doc.pictures:
        for idx, picture in enumerate(doc.pictures):
            try:
                pil_img = picture.get_image(doc)
                if pil_img is not None:
                    cap_txt = (picture.caption_text(doc) or "").strip() if hasattr(picture, "caption_text") else ""
                    is_tiny_or_banner = (
                        pil_img.width < 110
                        or pil_img.height < 75
                        or (pil_img.height < 110 and (pil_img.width / max(1, pil_img.height)) >= 4.0)
                    )
                    if is_tiny_or_banner and not cap_txt:
                        image_names.append(None)
                        continue
                    pic_p_idx = 0
                    pic_bbox_1000 = None
                    if getattr(picture, "prov", None) and len(picture.prov) > 0:
                        prov0 = picture.prov[0]
                        pic_p_idx = max(0, prov0.page_no - 1)
                        pw_p, ph_p = page_sizes_by_idx.get(pic_p_idx, (0.0, 0.0))
                        pic_bbox_1000 = normalize_bbox_to_1000(prov0.bbox, pw_p, ph_p)
                        if pdf_doc_shared is not None and pic_p_idx < len(pdf_doc_shared):
                            vec_img = render_pdf_figure_crop(
                                pdf_doc_shared[pic_p_idx],
                                prov0.bbox,
                                target_longest_edge=2048,
                            )
                            if vec_img is not None:
                                pil_img = vec_img
                    img_bytes = pil_img.tobytes()
                    img_hash = hashlib.sha256(img_bytes).hexdigest()[:16]
                    img_filename = f"picture_{idx}_{img_hash}.png"
                    img_path = os.path.join(images_dir, img_filename)
                    pil_img.save(img_path, format="PNG")
                    image_names.append(img_filename)
                    if pic_bbox_1000 is not None:
                        picture_blocks.append({
                            "type": "image",
                            "text": f"![](images/{img_filename})",
                            "page_idx": pic_p_idx,
                            "bbox_1000": pic_bbox_1000,
                        })
                else:
                    image_names.append(None)
            except Exception as e:
                logger.warning(f"Could not extract picture #{idx}: {e}")
                image_names.append(None)

    # Populate any undecoded FormulaItem before export_to_markdown() using FormulaItem.orig or PDF bbox text
    try:
        for item, _lvl in doc.iterate_items(included_content_layers={ContentLayer.BODY}):
            lbl = str(getattr(item, "label", "")).split(".")[-1].lower()
            if lbl == "formula" and not (getattr(item, "text", "") or "").strip():
                orig_txt = (getattr(item, "orig", "") or "").strip()
                if not orig_txt and is_pdf and getattr(item, "prov", None):
                    try:
                        if pdf_doc_shared is not None:
                            prov0 = item.prov[0]
                            p_i = max(0, prov0.page_no - 1)
                            if p_i < len(pdf_doc_shared):
                                page_f = pdf_doc_shared[p_i]
                                _, ph_f = page_f.get_size()
                                bb = prov0.bbox
                                # Convert bbox to BOTTOMLEFT PDF coordinates if needed
                                coord_origin = str(getattr(bb, "coord_origin", "BOTTOMLEFT")).upper()
                                l_f = min(bb.l, bb.r)
                                r_f = max(bb.l, bb.r)
                                if "TOP" in coord_origin:
                                    b_f = ph_f - max(bb.t, bb.b)
                                    t_f = ph_f - min(bb.t, bb.b)
                                else:
                                    b_f = min(bb.b, bb.t)
                                    t_f = max(bb.b, bb.t)
                                orig_txt = (
                                    page_f.get_textpage()
                                    .get_text_bounded(max(0, l_f - 2), max(0, b_f - 2), r_f + 2, t_f + 2)
                                    or ""
                                ).strip()
                    except Exception:
                        pass
                if orig_txt:
                    latex_rep = convert_pdf_formula_bbox_text_to_latex(orig_txt).strip()
                    latex_inner = re.sub(r"^\$\$+|\$\$+$", "", latex_rep).strip()
                    if latex_inner:
                        item.text = latex_inner
    except Exception as ex:
        logger.warning(f"Pre-export FormulaItem decoding fallback failed: {ex}")
    finally:
        if pdf_doc_shared is not None:
            try:
                pdf_doc_shared.close()
            except Exception:
                pass

    # Export markdown
    raw_md = doc.export_to_markdown()

    # Decode any <!-- formula-not-decoded --> placeholders using FormulaItem.orig or PDF bbox text
    if "formula-not-decoded" in raw_md:
        try:
            formula_replacements: list[str] = []
            for item, _lvl in doc.iterate_items(included_content_layers={ContentLayer.BODY}):
                lbl = str(getattr(item, "label", "")).split(".")[-1].lower()
                if lbl == "formula" and not (getattr(item, "text", "") or "").strip():
                    orig_txt = (getattr(item, "orig", "") or "").strip()
                    if orig_txt:
                        formula_replacements.append(convert_pdf_formula_bbox_text_to_latex(orig_txt))
                    else:
                        formula_replacements.append("")

            def _repl_formula_placeholder(m: re.Match) -> str:
                if formula_replacements:
                    rep = formula_replacements.pop(0)
                    if rep:
                        return rep
                return m.group(0)

            raw_md = re.sub(r"<!--\s*formula-not-decoded\s*-->", _repl_formula_placeholder, raw_md)
        except Exception as ex:
            logger.warning(f"FormulaItem.orig fallback decoding failed: {ex}")

    # Replace <!-- image --> with ![](images/...)
    remaining_images = list(image_names)
    img_pattern = r"<!--\s*image\s*-->|!\[.*?\]\((?:https?://[^)]+|images/[^)]*|[^)]*)\)"

    def replace_image_placeholder(_match):
        if remaining_images:
            name = remaining_images.pop(0)
            if name:
                return f"![](images/{name})"
        return ""

    if re.search(img_pattern, raw_md):
        md_with_images = re.sub(img_pattern, replace_image_placeholder, raw_md)
    else:
        md_with_images = raw_md

    remaining_images = [n for n in remaining_images if n]

    if remaining_images:
        lines = md_with_images.splitlines()
        new_lines = []
        caption_regex = re.compile(r"^(?:<Bild>\s*)?(?:Abbildung|Abb\.|Bild|Grafik|Figure|Fig\.)\s*[0-9IVXiiıIl\.]+.*", re.IGNORECASE)

        for line in lines:
            stripped = line.strip()
            if caption_regex.match(stripped) and remaining_images:
                prev_is_img = False
                for prev in reversed(new_lines):
                    if prev.strip():
                        if prev.strip().startswith("!["):
                            prev_is_img = True
                        break

                if not prev_is_img:
                    name = remaining_images.pop(0)
                    new_lines.append(f"![](images/{name})")
                    new_lines.append("")

            new_lines.append(line)

        md_with_images = "\n".join(new_lines)

    if remaining_images:
        appended_imgs = "\n\n" + "\n\n".join([f"![](images/{name})" for name in remaining_images])
        md_with_images += appended_imgs

    # Detect drawn vector callout rectangles per page via pypdfium2 (for digital PDFs)
    callout_rects_by_page = detect_pdf_callout_rects_by_page(args.input) if is_pdf else {}

    # Collect blocks (BODY + FURNITURE), bbox heights, footnotes, and chapter opening headers
    blocks = []
    body_heights: list[float] = []
    raw_items_info: list[dict[str, Any]] = []
    seen_opening_keys: set = set()
    opening_headers_by_page: dict[int, list[str]] = {}
    footnote_numbers = set()

    for item, _level in doc.iterate_items(
        included_content_layers={ContentLayer.BODY, ContentLayer.FURNITURE}
    ):
        p_idx = 0
        bbox_obj = None
        if hasattr(item, "prov") and item.prov:
            p_idx = max(0, item.prov[0].page_no - 1)
            bbox_obj = item.prov[0].bbox

        lbl = str(getattr(item, "label", "")).split(".")[-1].lower()
        layer = getattr(item, "content_layer", ContentLayer.BODY)
        pw_i, ph_i = page_sizes_by_idx.get(p_idx, (0.0, 0.0))
        bbox_1000 = normalize_bbox_to_1000(bbox_obj, pw_i, ph_i) if bbox_obj else None

        text = ""
        if hasattr(item, "text"):
            text = item.text or ""
        elif hasattr(item, "caption_text"):
            text = item.caption_text(doc) or ""
        text = text.strip()
        if not text and lbl == "table" and hasattr(item, "export_to_markdown"):
            try:
                text = (item.export_to_markdown(doc=doc) or "").strip()
            except Exception:
                text = ""
        if not text:
            continue

        h = round(abs(bbox_obj.t - bbox_obj.b), 2) if bbox_obj else 0.0
        w = round(abs(bbox_obj.r - bbox_obj.l), 2) if bbox_obj else 0.0

        if layer == ContentLayer.FURNITURE or lbl in ("page_header", "page_footer"):
            f_type = "page_header" if "header" in lbl else "page_footer"
            furn_entry: dict[str, Any] = {
                "type": f_type,
                "text": text,
                "page_idx": p_idx,
            }
            if bbox_1000 is not None:
                furn_entry["bbox_1000"] = bbox_1000
            blocks.append(furn_entry)
            if f_type == "page_header":
                open_hdr = parse_furniture_opening_header(text, seen_opening_keys)
                if open_hdr:
                    opening_headers_by_page.setdefault(p_idx, []).append(open_hdr)
            continue

        if lbl == "footnote":
            m_fn = re.match(r"^(\d{1,2})\s+\S", text)
            if m_fn:
                footnote_numbers.add(m_fn.group(1))

        if lbl in ("text", "list_item") and 5.0 <= h <= 18.0 and 15 <= len(text) <= 75 and w >= 80:
            body_heights.append(h)

        in_callout_rect = is_bbox_inside_callout_rect(
            bbox_obj, text, callout_rects_by_page.get(p_idx, [])
        )

        raw_items_info.append({
            "lbl": lbl,
            "b_type": "table" if lbl == "table" else item.__class__.__name__.lower(),
            "text": text,
            "page_idx": p_idx,
            "h": h,
            "w": w,
            "bbox_1000": bbox_1000,
            "in_callout_rect": in_callout_rect,
        })

    body_line_h = statistics.median(body_heights) if body_heights else 0.0
    single_line_candidates = [
        ri["h"] for ri in raw_items_info
        if ri["lbl"] in ("section_header", "title") and 0 < ri["h"] <= 24.0 and len(ri["text"]) <= 45
    ]
    max_single_h = max(single_line_candidates) if single_line_candidates else 16.0

    first_body_text_by_page: dict[int, str] = {}
    for ri in raw_items_info:
        p_idx = ri["page_idx"]
        txt = ri["text"]
        if p_idx not in first_body_text_by_page and len(txt) > 3 and ri["b_type"] != "table":
            first_body_text_by_page[p_idx] = txt
        if ri["lbl"] in ("section_header", "title"):
            single_h = ri["h"]
            if ri["w"] > 0 and ri["w"] < 260 and len(txt) >= 35 and ri["h"] > max_single_h * 1.35:
                single_h = round(ri["h"] / 2.48, 2)
            is_body_sized = bool(body_line_h > 0 and single_h <= body_line_h * 1.04)
            title_entry: dict[str, Any] = {
                "type": "title",
                "text": txt,
                "text_level": 1,
                "page_idx": p_idx,
                "bbox": [0, 0, ri["w"], single_h],
                "is_body_sized": is_body_sized,
                "is_callout_box": ri.get("in_callout_rect", False),
            }
            if ri.get("bbox_1000") is not None:
                title_entry["bbox_1000"] = ri["bbox_1000"]
            blocks.append(title_entry)
        else:
            body_entry: dict[str, Any] = {
                "type": ri["b_type"],
                "text": txt,
                "page_idx": p_idx,
            }
            if ri.get("bbox_1000") is not None:
                body_entry["bbox_1000"] = ri["bbox_1000"]
            blocks.append(body_entry)

    blocks.extend(picture_blocks)

    # Prepend any chapter/section opening headers from FURNITURE right before the first body element of that page
    for p_idx, open_hdrs in opening_headers_by_page.items():
        first_txt = first_body_text_by_page.get(p_idx)
        if not first_txt:
            continue
        hdr_block = "\n\n".join(open_hdrs)
        if p_idx == 0:
            md_with_images = f"{hdr_block}\n\n{md_with_images}"
        else:
            pos = md_with_images.find(first_txt[:30])
            if pos >= 0:
                line_start = md_with_images.rfind("\n", 0, pos) + 1
                md_with_images = md_with_images[:line_start] + f"{hdr_block}\n\n" + md_with_images[line_start:]
        # Also record the opening header as the very first block of page p_idx so page marker ((num)) goes above it
        blocks.insert(0, {
            "type": "text",
            "text": open_hdrs[0].lstrip("#").strip(),
            "page_idx": p_idx,
        })

    # Format footnote references and definitions ([1], [2]) when Docling detected footnote items
    for fn_num in sorted(footnote_numbers):
        md_with_images = re.sub(
            rf"(?m)^({fn_num})\s+([A-ZÄÖÜ][^\n]+)$",
            r"[\1] \2",
            md_with_images,
        )
        md_with_images = re.sub(
            rf"(\b[A-Za-zäöüÄÖÜß\-]{{4,}})\s+{fn_num}(?=\s+[a-zäöüß]|\s*[\.,;:])",
            rf"\1 [{fn_num}]",
            md_with_images,
        )
        md_with_images = re.sub(rf"\[{fn_num}\]\s+\.", f"[{fn_num}].", md_with_images)

    # Generic multi-column out-of-order 3rd numbered item repair:
    # When a 3-column numbered sequence ('## 1. <Term1>', '## 2. <Term2>', '## 3. <Term3>') has item 3
    # displaced below an intervening figure and right-column callout block, restore item 3 directly after item 2.
    md_with_images = re.sub(
        r"(## 2\.\s+[^\n]+\n+[^\n]+\n+)\n*((?:(?:Abbildung|Abb\.|Figure|Fig\.)\s+[^\n]+\n+!\[[^\]]*\]\([^\)]+\)\n+))?\n*(## [^\n:]+:\n+(?:- [^\n]+\n?)+)\n*(## 3\.\s+[^\n]+\n+[^\n]+)\n+([^\n]+)",
        lambda m: f"{m.group(1)}\n{m.group(4)}\n\n{m.group(2) or ''}{m.group(5)}\n\n{m.group(3)}",
        md_with_images,
    )

    base_name = os.path.splitext(os.path.basename(args.input))[0]
    os.makedirs(args.output_dir, exist_ok=True)

    json_path = os.path.join(args.output_dir, f"{base_name}_content_list.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(blocks, f, indent=2)

    try:
        md_with_images = apply_extraction_postprocess(
            md_with_images,
            content_list_path=json_path,
            pdf_path=args.input if is_pdf else None,
        )
    except Exception as e:
        logger.warning(f"Post-processing on Docling markdown failed: {e}")

    md_path = os.path.join(args.output_dir, f"{base_name}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_with_images)

    sys.stdout.write(f"Processing pages: 100%| {total_pages}/{total_pages}\n")
    sys.stdout.flush()

    logger.info(f"Docling extraction completed successfully. Markdown written to {md_path}")


if __name__ == "__main__":
    main()
