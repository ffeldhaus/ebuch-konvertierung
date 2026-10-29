"""Infinity-Parser2-Flash VLM-OCR and hybrid Docling layout document extractor CLI."""

import argparse
import gc
import hashlib
import importlib.util
import json
import logging
import os
import re
import sys
import tempfile

from PIL import Image

from backend.services.extraction_postprocess import (
    apply_extraction_postprocess,
    extract_docling_page_layout,
    fuse_vlm_page_with_docling,
)
from backend.services.pdf_render_service import render_pdf_page_for_vlm

# Official Infinity-Parser2 training prompt (infinity_parser2/prompts.py)
PROMPT_DOC2MD = "Please transform the document's contents into Markdown format."

logger = logging.getLogger("infinity_parser_extractor")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_MODEL_PATH = os.path.join(PROJECT_ROOT, "assets", "models", "infinity_parser2_flash")

LAST_EXTRACTED_TABLES_BY_PAGE: dict[int, list[str]] = {}


def extract_pdf_pictures_layout_aware(pdf_path: str, images_dir: str) -> dict[int, list[str]]:
    """Extracts page pictures using Docling's layout model and returns {page_idx: [filenames]}."""
    if pdf_path and not os.path.isabs(pdf_path) and not os.path.exists(pdf_path):
        cand_path = os.path.join(PROJECT_ROOT, pdf_path)
        if os.path.exists(cand_path):
            pdf_path = cand_path
    layout = extract_docling_page_layout(pdf_path, images_dir)
    global LAST_EXTRACTED_TABLES_BY_PAGE
    LAST_EXTRACTED_TABLES_BY_PAGE = layout.get("tables_by_page", {})
    return layout.get("pictures_by_page", {})


def parse_args(cli_args: list[str] | None = None):
    """Parse CLI arguments for the Infinity-Parser2-Flash extractor."""
    parser = argparse.ArgumentParser(description="Infinity-Parser2-Flash MLX Document Extractor")
    parser.add_argument("--input", required=True, help="Input PDF or image path")
    parser.add_argument("--output-dir", required=True, help="Output auto directory")
    parser.add_argument("--model-path", default=None, help="Local MLX model path")
    parser.add_argument("--max-tokens", type=int, default=4096, help="Max generation tokens per page")
    return parser.parse_args(cli_args)


def main(cli_args: list[str] | None = None):
    """Run the Infinity-Parser2-Flash document extraction pipeline."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(line_buffering=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    args = parse_args(cli_args)
    os.makedirs(args.output_dir, exist_ok=True)
    images_dir = os.path.join(args.output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    model_path = args.model_path or os.environ.get("INFINITY_MODEL_PATH") or DEFAULT_MODEL_PATH
    use_mlx = importlib.util.find_spec("mlx_vlm") is not None

    if not os.path.exists(model_path):
        logger.error(
            f"Infinity-Parser2-Flash local model directory not found at {model_path}. "
            f"Please download 'infly/Infinity-Parser2-Flash' to {DEFAULT_MODEL_PATH}."
        )
        sys.exit(1)

    input_path = args.input
    is_pdf = input_path.lower().endswith(".pdf")

    has_gpu = use_mlx
    if not has_gpu:
        try:
            import torch
            has_gpu = torch.cuda.is_available()
        except ImportError:
            has_gpu = False
    # 1792px (56 * 32px) on GPU keeps an A4 page (~40x56 = 2240 visual tokens) within Qwen3_5's native
    # 2304-token position embedding grid while cutting prefill compute by ~22% vs 2048px; 1536px (48 * 32px) on CPU.
    target_longest_edge = 1792.0 if has_gpu else 1536.0

    # 1. Render all pages of PDF or load single image
    pages_images = []
    pdf = None
    if is_pdf:
        try:
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(input_path)
            for page_idx in range(len(pdf)):
                pages_images.append(
                    render_pdf_page_for_vlm(
                        pdf[page_idx],
                        target_longest_edge=target_longest_edge,
                        grid_factor=32,
                        min_scale=1.5,
                        max_scale=2.8,
                    )
                )
        except Exception as e:
            logger.error(f"Failed to render PDF {input_path}: {e}")
            sys.exit(1)
    else:
        try:
            with Image.open(input_path) as raw_img:
                pages_images.append(raw_img.convert("RGB"))
        except Exception as e:
            logger.error(f"Failed to load image {input_path}: {e}")
            sys.exit(1)

    total_pages = len(pages_images)
    logger.info(f"Loaded {total_pages} page(s) from {input_path}. Loading model from {model_path} (use_mlx={use_mlx})...")

    # Extract pictures, TableFormer tables, furniture headers/footers, and heading bboxes via Docling CPU
    layout_info = {"pictures_by_page": {}, "tables_by_page": {}, "furniture_by_page": {}, "heading_blocks": [], "opening_headers_by_page": {}}
    if is_pdf:
        try:
            layout_info = extract_docling_page_layout(input_path, images_dir)
            global LAST_EXTRACTED_TABLES_BY_PAGE
            LAST_EXTRACTED_TABLES_BY_PAGE = layout_info.get("tables_by_page", {})
        except Exception as ex:
            logger.warning(f"Layout picture extraction encountered error: {ex}")
    layout_pictures_by_page = layout_info.get("pictures_by_page", {})

    # 2. Load MLX or PyTorch model & processor
    if use_mlx:
        try:
            from mlx_vlm import generate, load
            model, processor = load(model_path)
        except Exception as e:
            logger.error(f"Failed to load Infinity-Parser2-Flash MLX model: {e}")
            sys.exit(1)
    else:
        try:
            import torch
            from transformers import AutoModelForImageTextToText, AutoProcessor

            processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
            model = AutoModelForImageTextToText.from_pretrained(
                model_path,
                dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
                device_map="auto" if torch.cuda.is_available() else None,
                trust_remote_code=True,
            )
            model.generation_config.use_cache = True
            model.config.use_cache = True
            if hasattr(model.config, "text_config"):
                model.config.text_config.use_cache = True
            model.eval()
        except Exception as e:
            logger.error(f"Failed to load Infinity-Parser2-Flash PyTorch model: {e}")
            sys.exit(1)

    all_markdown = []
    blocks = []
    blocks.extend(layout_info.get("heading_blocks", []))
    blocks.extend(layout_info.get("layout_blocks", []))
    for p_furn in layout_info.get("furniture_by_page", {}).values():
        blocks.extend(p_furn)

    physical_page_numbers = []
    if is_pdf:
        try:
            from backend.services.extraction_service import get_physical_page_numbers_for_pdf
            physical_page_numbers = get_physical_page_numbers_for_pdf(input_path)
        except Exception as ex:
            logger.warning(f"Could not extract physical page numbers for Infinity: {ex}")
    if not physical_page_numbers or len(physical_page_numbers) < total_pages:
        physical_page_numbers = [i + 1 for i in range(total_pages)]

    # 3. Process page-by-page
    for p_idx, pil_img in enumerate(pages_images):
        current_page = p_idx + 1
        phys_num = physical_page_numbers[p_idx] if p_idx < len(physical_page_numbers) else current_page
        logger.info(f"Processing page {current_page}/{total_pages} (physical page {phys_num}) with Infinity-Parser2-Flash...")

        percent = int((p_idx / total_pages) * 100)
        sys.stdout.write(f"Processing pages: {percent}%| {current_page}/{total_pages}\n")
        sys.stdout.flush()

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
            tmp_img_path = tmp_file.name
            pil_img.save(tmp_img_path, format="PNG")

        page_text = ""
        try:
            if use_mlx:
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image"},
                            {"type": "text", "text": PROMPT_DOC2MD},
                        ],
                    }
                ]
                try:
                    prompt = processor.apply_chat_template(
                        messages,
                        tokenize=False,
                        add_generation_prompt=True,
                        enable_thinking=False,
                    )
                except TypeError:
                    prompt = processor.apply_chat_template(
                        messages,
                        tokenize=False,
                        add_generation_prompt=True,
                    )

                res = generate(
                    model,
                    processor,
                    prompt,
                    tmp_img_path,
                    max_tokens=args.max_tokens,
                    temp=0.0,
                    verbose=False,
                )
                page_text = res.text if hasattr(res, "text") else str(res)
            else:
                import torch

                messages = [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image", "image": pil_img},
                            {"type": "text", "text": PROMPT_DOC2MD},
                        ],
                    }
                ]
                try:
                    prompt_text = processor.apply_chat_template(
                        messages,
                        tokenize=False,
                        add_generation_prompt=True,
                        enable_thinking=False,
                    )
                except TypeError:
                    prompt_text = processor.apply_chat_template(
                        messages,
                        tokenize=False,
                        add_generation_prompt=True,
                    )
                inputs = processor(
                    text=[prompt_text],
                    images=[pil_img],
                    padding=True,
                    return_tensors="pt",
                )
                if torch.cuda.is_available():
                    inputs = inputs.to("cuda")
                with torch.no_grad():
                    generated_ids = model.generate(
                        **inputs,
                        max_new_tokens=args.max_tokens,
                        do_sample=False,
                        use_cache=True,
                        logits_to_keep=1,
                        eos_token_id=[248044, 248046],
                    )
                generated_ids_trimmed = [
                    out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
                ]
                page_text = processor.batch_decode(
                    generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
                )[0]
        except Exception as e:
            logger.error(f"Error generating markdown for page {current_page}: {e}")
            page_text = ""
        finally:
            if os.path.exists(tmp_img_path):
                try:
                    os.remove(tmp_img_path)
                except Exception:
                    pass

        # 3b. Retrieve extracted layout pictures for this page (or fallback to PDF object stream)
        page_images = list(layout_pictures_by_page.get(p_idx, []))
        if not page_images and is_pdf and pdf is not None:
            try:
                import pypdfium2 as pdfium
                raw_page = pdf[p_idx]
                page_w, page_h = raw_page.get_size()
                for obj_idx, obj in enumerate(raw_page.get_objects()):
                    if obj.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE:
                        try:
                            bitmap = obj.get_bitmap()
                            img_pil = bitmap.to_pil()
                            is_full_page_scan = img_pil.width >= 0.95 * page_w and img_pil.height >= 0.95 * page_h
                            if not is_full_page_scan and img_pil.width >= 30 and img_pil.height >= 30:
                                img_bytes = img_pil.tobytes()
                                img_hash = hashlib.sha256(img_bytes).hexdigest()[:16]
                                img_filename = f"picture_{p_idx}_{obj_idx}_{img_hash}.png"
                                img_target_path = os.path.join(images_dir, img_filename)
                                img_pil.save(img_target_path, format="PNG")
                                page_images.append(img_filename)
                        except Exception as ex:
                            logger.warning(f"Could not extract image obj {obj_idx} on page {p_idx}: {ex}")
            except Exception as ex:
                logger.warning(f"Could not inspect objects on page {p_idx}: {ex}")

        page_tables = layout_info.get("tables_by_page", {}).get(p_idx, [])
        opening_headers = layout_info.get("opening_headers_by_page", {}).get(p_idx, [])
        cleaned_text = fuse_vlm_page_with_docling(
            page_text,
            page_images,
            phys_num,
            page_tables=page_tables,
            opening_headers=opening_headers,
        )
        all_markdown.append(cleaned_text)

        # Emit real-time page streaming chunk
        try:
            page_payload = {
                "status": "raw_chunk",
                "page": p_idx + 1,
                "total": total_pages,
                "delta": cleaned_text,
            }
            sys.stdout.write(f"\n---STREAM_PAGE_START---\n{json.dumps(page_payload)}\n---STREAM_PAGE_END---\n")
            sys.stdout.flush()
        except Exception:
            pass

        for line in cleaned_text.splitlines():
            line_str = line.strip()
            if not line_str or re.fullmatch(r"\(\(\d+\)\)", line_str):
                continue
            b_type = "text"
            if line_str.startswith("#"):
                b_type = "heading"
            elif line_str.startswith("|") and line_str.endswith("|"):
                b_type = "table"
            elif line_str.startswith("$$") or line_str.startswith("\\["):
                b_type = "formula"
            elif line_str.startswith("!["):
                b_type = "image"
            blocks.append({
                "type": b_type,
                "text": line_str,
                "page_idx": p_idx,
                "page_no": phys_num,
            })

    if pdf is not None:
        try:
            pdf.close()
        except Exception:
            pass

    combined_md = "\n\n".join(all_markdown)

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    os.makedirs(args.output_dir, exist_ok=True)
    json_path = os.path.join(args.output_dir, f"{base_name}_content_list.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(blocks, f, indent=2)

    try:
        combined_md = apply_extraction_postprocess(
            combined_md,
            content_list_path=json_path,
            pdf_path=input_path if is_pdf else None,
        )
    except Exception as e:
        logger.warning(f"Post-processing on Infinity-Parser markdown failed: {e}")

    md_path = os.path.join(args.output_dir, f"{base_name}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(combined_md)

    sys.stdout.write(f"Processing pages: 100%| {total_pages}/{total_pages}\n")
    sys.stdout.flush()

    try:
        del model
        del processor
    except Exception:
        pass
    try:
        import mlx.core as mx
        mx.synchronize()
        mx.clear_cache()
    except Exception:
        pass
    gc.collect()

    logger.info(f"Infinity-Parser2-Flash extraction completed successfully: {md_path}")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
