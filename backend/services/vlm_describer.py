"""Sequential offline VLM image description generator for FIBS <Bild> blocks."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import logging
import os
import sys

from backend.services import fibs_constants as fc
from backend.services.fibs_formatting import clean_bildart
from backend.services.models import VlmDescriptionResult
from backend.services.prompts import VLM_IMAGE_PROMPT, build_vlm_prompt

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger("vlm_describer")


def parse_vlm_description(raw: str) -> VlmDescriptionResult:
    """Parses a structured VLM response into a validated ``VlmDescriptionResult`` model.

    Falls back gracefully when given an unstructured description string so older
    models and test mocks remain supported.

    Args:
        raw: Raw text returned by the VLM image describer.

    Returns:
        A ``VlmDescriptionResult`` instance.
    """
    text = (raw or "").strip()
    result = VlmDescriptionResult(
        image_type="",
        has_text=None,
        decorative=False,
        description=text,
    )
    clean = text.replace("**", "")
    m_desc = fc.VLM_DESC_HEADER_RE.search(clean)
    if not m_desc and not fc.VLM_BILDART_HEADER_RE.search(clean):
        return result

    header = clean[: m_desc.start()] if m_desc else clean
    description = clean[m_desc.end() :].strip() if m_desc else ""

    def field(name: str) -> str | None:
        fm = fc.VLM_FIELD_RE_MAP[name].search(header)
        return fm.group(1).strip() if fm else None

    has_text = field("TEXT_IM_BILD")
    decorative = field("DEKORATIV")
    result.image_type = clean_bildart(field("BILDART") or "")
    result.has_text = None if has_text is None else has_text.lower().startswith(("j", "y"))
    result.decorative = bool(decorative and decorative.lower().startswith(("j", "y")))
    result.description = description
    return result


def load_vlm_results(path: str | None) -> dict[str, VlmDescriptionResult]:
    """Loads VLM subprocess JSON output into typed ``VlmDescriptionResult`` models.

    Args:
        path: Path to the JSON file written by ``vlm_describer.py --output-json``.

    Returns:
        Dictionary mapping image file paths to ``VlmDescriptionResult`` instances.
    """
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as ex:
        logger.error(f"Failed to read VLM output json {path}: {ex}")
        return {}
    if not isinstance(data, dict):
        return {}
    parsed_map: dict[str, VlmDescriptionResult] = {}
    for img_path, val in data.items():
        if isinstance(val, dict):
            parsed_map[img_path] = VlmDescriptionResult.model_validate(val)
        elif isinstance(val, str) and val.strip():
            parsed_map[img_path] = parse_vlm_description(val)
    return parsed_map


def load_cache(path: str | None, prompt: str) -> dict[str, str]:
    """Loads per-image descriptions from a resume checkpoint when the base prompt matches.

    Args:
        path: Path to the checkpoint JSON file, or ``None``.
        prompt: Base VLM prompt string used to verify checkpoint compatibility.

    Returns:
        Dictionary mapping ``"<image_path>#<prompt_sha256_prefix>"`` keys to non-empty description strings.
    """
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    fp = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    if not isinstance(data, dict) or data.get("prompt") != fp:
        return {}
    return {
        k: v
        for k, v in (data.get("descriptions") or {}).items()
        if isinstance(v, str) and v.strip()
    }


def save_cache(path: str | None, prompt: str, results: dict[str, str]) -> None:
    """Atomically writes the resume checkpoint after each described image.

    Args:
        path: Path to the checkpoint JSON file, or ``None``.
        prompt: Base VLM prompt string whose fingerprint is stored in the checkpoint.
        results: Mapping from ``cache_key`` to raw VLM description text.
    """
    if not path:
        return
    fp = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"prompt": fp, "descriptions": results}, f, ensure_ascii=False)
    os.replace(tmp, path)


def main() -> None:
    """Runs the sequential offline VLM image description CLI."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(line_buffering=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Describe images for E-Buch accessibility standard offline."
    )
    parser.add_argument(
        "--images", required=True, help="Comma-separated paths to images to describe."
    )
    parser.add_argument(
        "--model-path", default=None, help="Path to local MLX VLM model directory."
    )
    parser.add_argument(
        "--output-json", default=None, help="Path to write output JSON descriptions to."
    )
    parser.add_argument(
        "--cache-json",
        default=None,
        help="Resume checkpoint: finished descriptions are reused and saved after each image.",
    )
    parser.add_argument(
        "--contexts-json",
        default=None,
        help="JSON map {image_path: page text context} used as read-only orientation.",
    )
    args = parser.parse_args()

    mlx_dir = os.path.join(PROJECT_ROOT, "assets", "models", "gemma", "mlx")
    default_model_path = (
        os.environ.get("GEMMA_MODEL_PATH")
        or (mlx_dir if os.path.exists(mlx_dir) else os.path.join(PROJECT_ROOT, "assets", "models", "gemma"))
    )
    model_path = args.model_path or default_model_path

    image_paths = [p.strip() for p in args.images.split(",") if p.strip()]
    if not image_paths:
        if args.output_json:
            with open(args.output_json, "w", encoding="utf-8") as f:
                json.dump({}, f)
        print("---JSON_START---")
        print(json.dumps({}))
        print("---JSON_END---")
        return

    if sys.platform == "darwin":
        os.environ["PYTORCH_MPS_HIGH_WATERMARK_RATIO"] = "0.0"

    use_mlx = False
    try:
        from mlx_vlm import generate, load
        from mlx_vlm.prompt_utils import apply_chat_template
        from mlx_vlm.utils import load_config

        use_mlx = True
    except ImportError:
        use_mlx = False

    contexts: dict[str, str] = {}
    if args.contexts_json and os.path.exists(args.contexts_json):
        try:
            with open(args.contexts_json, encoding="utf-8") as f:
                ctx_data = json.load(f)
            if isinstance(ctx_data, dict):
                contexts = {k: v for k, v in ctx_data.items() if isinstance(v, str)}
        except Exception as ex:
            logger.warning(f"Could not read page contexts {args.contexts_json}: {ex}")

    prompts = {p: build_vlm_prompt(contexts.get(p, "")) for p in image_paths}
    keys = {
        p: f"{p}#{hashlib.sha256(prompts[p].encode('utf-8')).hexdigest()[:16]}"
        for p in image_paths
    }

    results: dict[str, str] = {}
    checkpoint: dict[str, str] = {}
    cached = load_cache(args.cache_json, VLM_IMAGE_PROMPT)
    for p in image_paths:
        if keys[p] in cached:
            results[p] = cached[keys[p]]
            checkpoint[keys[p]] = cached[keys[p]]
    todo = [p for p in image_paths if p not in results]
    if cached:
        logger.info(
            f"Resume checkpoint: {len(image_paths) - len(todo)}/{len(image_paths)} images already described."
        )
    if contexts:
        logger.info(
            f"Page context available for {sum(1 for p in image_paths if contexts.get(p))}/{len(image_paths)} images."
        )
    model = processor = None
    try:
        total_imgs = len(image_paths)
        if not todo:
            sys.stderr.write(f"[PROGRESS] {total_imgs}/{total_imgs}\n")
            sys.stderr.flush()
        else:
            if use_mlx:
                logger.info(f"Loading mlx_vlm model from {model_path}...")
                model, processor = load(model_path)
                config = load_config(model_path)
            else:
                import torch
                from PIL import Image
                from transformers import AutoModelForImageTextToText, AutoProcessor

                if not os.path.exists(model_path):
                    alt_path = os.path.join(PROJECT_ROOT, "assets", "models", "gemma")
                    if os.path.exists(alt_path):
                        model_path = alt_path
                logger.info(f"Loading PyTorch/Transformers VLM model from {model_path}...")
                processor = AutoProcessor.from_pretrained(
                    model_path, local_files_only=True, trust_remote_code=True
                )
                model = AutoModelForImageTextToText.from_pretrained(
                    model_path,
                    dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
                    device_map="auto" if torch.cuda.is_available() else None,
                    local_files_only=True,
                    trust_remote_code=True,
                )
                model.eval()

            if hasattr(processor, "image_processor") and hasattr(
                processor.image_processor, "max_soft_tokens"
            ):
                processor.image_processor.max_soft_tokens = 1120
            if hasattr(processor, "image_seq_length"):
                processor.image_seq_length = 1120

            for idx, img_path in enumerate(image_paths, 1):
                if img_path in results:
                    continue
                if not os.path.exists(img_path):
                    logger.warning(f"Image not found: {img_path}")
                    results[img_path] = ""
                    continue

                logger.info(f"Describing image {idx}/{total_imgs}: {img_path}")
                sys.stderr.write(f"[PROGRESS] {idx}/{total_imgs}\n")
                sys.stderr.flush()
                try:
                    if use_mlx:
                        formatted_prompt = apply_chat_template(
                            processor, config, prompts[img_path], num_images=1
                        )
                        desc = generate(
                            model,
                            processor,
                            formatted_prompt,
                            [img_path],
                            max_tokens=2048,
                            repetition_penalty=1.1,
                            repetition_context_size=64,
                            verbose=False,
                        )
                        desc_text = desc.text if hasattr(desc, "text") else str(desc)
                    else:
                        import torch
                        from PIL import Image

                        with Image.open(img_path) as raw_img:
                            pil_img = raw_img.convert("RGB")
                        messages = [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "image"},
                                    {"type": "text", "text": prompts[img_path]},
                                ],
                            }
                        ]
                        text_prompt = processor.apply_chat_template(
                            messages, tokenize=False, add_generation_prompt=True
                        )
                        inputs = processor(
                            text=[text_prompt], images=[pil_img], return_tensors="pt"
                        )
                        target_device = next(model.parameters()).device
                        inputs = {
                            k: v.to(target_device) if hasattr(v, "to") else v
                            for k, v in inputs.items()
                        }
                        with torch.no_grad():
                            out_ids = model.generate(
                                **inputs,
                                max_new_tokens=2048,
                                do_sample=False,
                                repetition_penalty=1.1,
                            )
                        in_len = inputs["input_ids"].shape[1]
                        desc_text = processor.batch_decode(
                            out_ids[:, in_len:], skip_special_tokens=True
                        )[0]
                    results[img_path] = desc_text.strip()
                except Exception as ex:
                    logger.error(f"Error describing {img_path}: {ex}")
                    results[img_path] = ""
                checkpoint[keys[img_path]] = results[img_path]
                try:
                    save_cache(args.cache_json, VLM_IMAGE_PROMPT, checkpoint)
                except Exception as ex:
                    logger.warning(f"Could not write resume checkpoint: {ex}")
    except Exception as ex:
        logger.error(f"Global VLM describer error: {ex}")
    finally:
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

    if args.output_json:
        try:
            with open(args.output_json, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to write output JSON to {args.output_json}: {e}")

    print("---JSON_START---")
    print(json.dumps(results, ensure_ascii=False))
    print("---JSON_END---")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
