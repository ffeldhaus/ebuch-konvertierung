"""LightOnOCR-3 VLM-OCR and hybrid Docling layout document extractor CLI."""

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
from typing import Any

from PIL import Image

from backend.services.extraction_postprocess import (
    apply_extraction_postprocess,
    extract_docling_page_layout,
    fuse_vlm_page_with_docling,
)
from backend.services.pdf_render_service import render_pdf_page_for_vlm

logger = logging.getLogger("lightonocr_extractor")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_MODEL_PATH = os.path.join(PROJECT_ROOT, "assets", "models", "lightonocr")

_GROUNDING_BLOCK_RE = re.compile(
    r"!\[([a-zA-Z0-9_\+]+)\]\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)[ \t]*(.*?)(?=(?:\n*!\[[a-zA-Z0-9_\+]+\]\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\))|\Z)",
    re.DOTALL,
)


def parse_args(cli_args: list[str] | None = None):
    """Parse CLI arguments for the LightOnOCR-3 extractor."""
    parser = argparse.ArgumentParser(description="LightOnOCR-3 MLX / Transformers Document Extractor")
    parser.add_argument("--input", required=True, help="Input PDF or image path")
    parser.add_argument("--output-dir", required=True, help="Output auto directory")
    parser.add_argument("--model-path", default=None, help="Local LightOnOCR-3 model path")
    parser.add_argument("--mode", choices=["plain", "grounding"], default="plain", help="LightOnOCR-3 prompt mode ('plain' or 'grounding')")
    parser.add_argument("--max-tokens", type=int, default=4096, help="Max generation tokens per page")
    return parser.parse_args(cli_args)


def ensure_lightonocr_cache_enabled(model_dir: str) -> None:
    """Ensures use_cache=True is set in config.json and generation_config.json for LightOnOCR-3-0.8B
    (whose upstream HF checkpoint ships with use_cache=false from training).
    """
    if not model_dir or not os.path.isdir(model_dir):
        return
    for fname in ("config.json", "generation_config.json"):
        fpath = os.path.join(model_dir, fname)
        if not os.path.exists(fpath):
            continue
        try:
            with open(fpath, encoding="utf-8") as f:
                data = json.load(f)
            changed = False
            if data.get("use_cache") is False:
                data["use_cache"] = True
                changed = True
            if isinstance(data.get("text_config"), dict) and data["text_config"].get("use_cache") is False:
                data["text_config"]["use_cache"] = True
                changed = True
            if changed:
                with open(fpath, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
        except Exception as e:
            logger.debug(f"Could not update {fname} in {model_dir}: {e}")


def build_lightonocr_messages(mode: str = "plain", pil_img: Image.Image | None = None) -> list[dict[str, Any]]:
    """Build the official LightOnOCR-3 chat message structure.

    Per LightOnOCR-3 specification, only two prompts are in-distribution:
      - 'plain': empty text prompt (image only)
      - 'grounding': exact single word 'grounding'
    """
    img_entry: dict[str, Any] = {"type": "image"}
    if pil_img is not None:
        img_entry["image"] = pil_img

    content: list[dict[str, Any]] = [img_entry]
    if mode == "grounding":
        content.append({"type": "text", "text": "grounding"})

    return [{"role": "user", "content": content}]


def parse_grounding_blocks(
    raw_text: str,
    page_pil_img: Image.Image | None = None,
    images_dir: str | None = None,
    page_idx: int = 0,
    has_existing_images: bool = False,
) -> tuple[str, list[str]]:
    """Parses LightOnOCR-3 grounding output (![label](x1,y1,x2,y2) content):
    - Drops 'header', 'footer', and 'page_number' blocks.
    - Preserves 'footnote' blocks (required by E-Buch standard).
    - Merges 'text+' continuation blocks onto the previous 'text' block even across intervening figures.
    - Crops 'image' / 'chart' bounding boxes (normalized 0..1000) as PNG fallback when Docling found no pictures.
    """
    if not raw_text or not _GROUNDING_BLOCK_RE.search(raw_text):
        return raw_text, []

    blocks: list[dict[str, Any]] = []
    cropped_files: list[str] = []
    crop_counter = 0

    for m in _GROUNDING_BLOCK_RE.finditer(raw_text):
        label = m.group(1).strip().lower()
        x1, y1, x2, y2 = int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
        body = m.group(6).strip()

        if label in ("header", "footer", "page_number"):
            continue

        if label in ("image", "chart"):
            if not has_existing_images and page_pil_img is not None and images_dir:
                try:
                    w, h = page_pil_img.size
                    px1 = max(0, min(w, int(round(x1 * w / 1000.0))))
                    py1 = max(0, min(h, int(round(y1 * h / 1000.0))))
                    px2 = max(0, min(w, int(round(x2 * w / 1000.0))))
                    py2 = max(0, min(h, int(round(y2 * h / 1000.0))))
                    if px2 - px1 >= 30 and py2 - py1 >= 30:
                        cropped = page_pil_img.crop((px1, py1, px2, py2))
                        img_hash = hashlib.sha256(cropped.tobytes()).hexdigest()[:16]
                        fname = f"picture_{page_idx}_{crop_counter}_{img_hash}.png"
                        cropped.save(os.path.join(images_dir, fname), format="PNG")
                        cropped_files.append(fname)
                        crop_counter += 1
                except Exception as e:
                    logger.debug(f"Could not crop grounding bbox on page {page_idx}: {e}")
            blocks.append({"label": "image", "text": "<!-- image -->"})
            continue

        if label == "text+":
            # Find last 'text' block and merge continuation
            merged = False
            for prev in reversed(blocks):
                if prev["label"] == "text":
                    prev_txt = prev["text"].rstrip()
                    if prev_txt.endswith("-") and body and body[0].islower():
                        prev["text"] = prev_txt[:-1] + body
                    else:
                        prev["text"] = prev_txt + " " + body
                    merged = True
                    break
            if not merged and body:
                blocks.append({"label": "text", "text": body})
            continue

        if label == "title" and body and not body.startswith("#"):
            body = f"## {body}"

        if body:
            blocks.append({"label": label, "text": body})

    assembled = "\n\n".join(b["text"] for b in blocks if b["text"])
    return assembled, cropped_files


def post_process_lightonocr_page(
    raw_text: str,
    page_images: list[str],
    phys_num: int,
    page_tables: list[str] | None = None,
    opening_headers: list[str] | None = None,
    page_pil_img: Image.Image | None = None,
    images_dir: str | None = None,
    page_idx: int = 0,
) -> str:
    """Clean raw OCR markdown from LightOnOCR-3 and fuse with Docling layout.

    - Parses grounding blocks if present
    - Delegates to shared fuse_vlm_page_with_docling() pipeline
    """
    text, bbox_cropped = parse_grounding_blocks(
        raw_text,
        page_pil_img=page_pil_img,
        images_dir=images_dir,
        page_idx=page_idx,
        has_existing_images=bool(page_images),
    )
    all_page_images = list(page_images) if page_images else list(bbox_cropped)
    return fuse_vlm_page_with_docling(
        text,
        page_images=all_page_images,
        phys_num=phys_num,
        page_tables=page_tables,
        opening_headers=opening_headers,
    )


def main(cli_args: list[str] | None = None):
    """Run the LightOnOCR-3 document extraction pipeline."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(line_buffering=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    args = parse_args(cli_args)
    os.makedirs(args.output_dir, exist_ok=True)
    images_dir = os.path.join(args.output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    model_path = args.model_path or os.environ.get("LIGHTONOCR_MODEL_PATH") or DEFAULT_MODEL_PATH
    use_mlx = importlib.util.find_spec("mlx_vlm") is not None

    if os.path.isdir(model_path):
        ensure_lightonocr_cache_enabled(model_path)
    else:
        logger.error(
            f"LightOnOCR-3 local model directory not found at {model_path}. "
            f"Please download 'lightonai/LightOnOCR-3-0.8B' to {DEFAULT_MODEL_PATH}."
        )
        sys.exit(1)

    input_path = args.input
    is_pdf = input_path.lower().endswith(".pdf")

    # Target longest edge: 1536px (48 * 32px native Qwen3_5 position grid) on GPU, 1120px (35 * 32px) on CPU
    has_gpu = use_mlx
    if not has_gpu:
        try:
            import torch
            has_gpu = torch.cuda.is_available()
        except ImportError:
            has_gpu = False
    target_longest_edge = 1536.0 if has_gpu else 1120.0

    pages_images: list[Image.Image] = []
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
                        min_scale=1.25,
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
    logger.info(
        f"Loaded {total_pages} page(s) from {input_path}. Loading LightOnOCR-3 from {model_path} (use_mlx={use_mlx}, mode={args.mode})..."
    )

    # Extract layout pictures, TableFormer tables, furniture headers/footers, and heading bboxes via Docling CPU
    layout_info = {"pictures_by_page": {}, "tables_by_page": {}, "furniture_by_page": {}, "heading_blocks": [], "opening_headers_by_page": {}}
    if is_pdf:
        try:
            layout_info = extract_docling_page_layout(input_path, images_dir)
        except Exception as ex:
            logger.warning(f"Docling layout helper encountered error: {ex}")

    # Load MLX (Apple Silicon Metal) or PyTorch model & processor
    if use_mlx:
        try:
            from mlx_vlm import generate, load
            model, processor = load(model_path)
        except Exception as e:
            logger.error(f"Failed to load LightOnOCR-3 MLX model: {e}")
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
            logger.error(f"Failed to load LightOnOCR-3 PyTorch model: {e}")
            sys.exit(1)

    all_markdown: list[str] = []
    blocks: list[dict[str, Any]] = []
    # Seed blocks with Docling heading bbox metadata and furniture metadata for downstream post-processing
    blocks.extend(layout_info.get("heading_blocks", []))
    for p_furn in layout_info.get("furniture_by_page", {}).values():
        blocks.extend(p_furn)

    physical_page_numbers: list[int] = []
    if is_pdf:
        try:
            from backend.services.extraction_service import get_physical_page_numbers_for_pdf
            physical_page_numbers = get_physical_page_numbers_for_pdf(input_path)
        except Exception as ex:
            logger.warning(f"Could not extract physical page numbers for LightOnOCR-3: {ex}")
    if not physical_page_numbers or len(physical_page_numbers) < total_pages:
        physical_page_numbers = [i + 1 for i in range(total_pages)]

    for p_idx, pil_img in enumerate(pages_images):
        current_page = p_idx + 1
        phys_num = physical_page_numbers[p_idx] if p_idx < len(physical_page_numbers) else current_page
        logger.info(f"Processing page {current_page}/{total_pages} (physical page {phys_num}) with LightOnOCR-3...")

        percent = int((p_idx / total_pages) * 100)
        sys.stdout.write(f"Processing pages: {percent}%| {current_page}/{total_pages}\n")
        sys.stdout.flush()

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
            tmp_img_path = tmp_file.name
            pil_img.save(tmp_img_path, format="PNG")

        page_text = ""
        try:
            if use_mlx:
                messages = build_lightonocr_messages(mode=args.mode)
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

                messages = build_lightonocr_messages(mode=args.mode, pil_img=pil_img)
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
                    generated_ids_trimmed,
                    skip_special_tokens=True,
                    clean_up_tokenization_spaces=False,
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

        page_images = list(layout_info.get("pictures_by_page", {}).get(p_idx, []))
        page_tables = list(layout_info.get("tables_by_page", {}).get(p_idx, []))
        opening_headers = list(layout_info.get("opening_headers_by_page", {}).get(p_idx, []))

        cleaned_text = post_process_lightonocr_page(
            page_text,
            page_images=page_images,
            phys_num=phys_num,
            page_tables=page_tables,
            opening_headers=opening_headers,
            page_pil_img=pil_img,
            images_dir=images_dir,
            page_idx=p_idx,
        )
        all_markdown.append(cleaned_text)

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
        logger.warning(f"Post-processing on LightOnOCR-3 markdown failed: {e}")

    md_path = os.path.join(args.output_dir, f"{base_name}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(combined_md)

    sys.stdout.write(f"Processing pages: 100%| {total_pages}/{total_pages}\n")
    sys.stdout.flush()

    # Cleanup GPU / Unified Memory (AGENTS.md §4)
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
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    gc.collect()

    logger.info(f"LightOnOCR-3 extraction completed successfully: {md_path}")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
