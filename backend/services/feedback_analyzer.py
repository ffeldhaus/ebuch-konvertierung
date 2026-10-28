"""Offline Gemma 4 feedback analyzer (subprocess entry point).

Executed by ``feedback_service.run_gemma_feedback_analysis`` in a separate
process so that all MLX/Metal memory is released when it exits.

Steps (strictly sequential, one model load):
  1. For every marked PDF region (PNG) run an *isolated* single-image prompt
     (no multi-image batching – see AGENTS.md) describing its structure.
  2. Insert the region findings into the final prompt and run a text-only
     generation that produces the coding-assistant report.
  3. Clear the Metal cache and exit.

Input JSON:  {"final_prompt": str, "placeholder": str, "regions": [{"path": str, "prompt": str}]}
Output JSON: {"region_findings": [str], "report": str}

Live stderr line protocol (parsed by ``feedback_service.parse_analyzer_line``):
  ``[PROGRESS] i/n label``   – pipeline step
  ``[SECTION] region N``     – token stream for marked region N begins
  ``[SECTION] report``       – token stream for the final report begins
  ``[TOKEN] "<json str>"``   – one generated text delta (JSON-encoded, may contain newlines)
  anything else              – plain log line
"""
import argparse
import json
import logging
import os
import sys

logger = logging.getLogger("feedback_analyzer")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL_PATH = os.environ.get("GEMMA_MODEL_PATH") or os.path.join(PROJECT_ROOT, "assets", "models", "gemma", "mlx")

REGION_MAX_TOKENS = 1024
REPORT_MAX_TOKENS = 6144  # overview + test-data tables need extra headroom


def _emit(line: str) -> None:
    """Write one protocol line to stderr and flush immediately (live forwarding)."""
    sys.stderr.write(line + "\n")
    sys.stderr.flush()


def _progress(step: int, total: int, label: str) -> None:
    _emit(f"[PROGRESS] {step}/{total} {label}")


def _stream(stream_generate, model, processor, prompt, image, section: str, **kwargs) -> str:
    """Run one isolated generation with token streaming.

    Every text delta is forwarded as ``[TOKEN]`` line; the full text is
    accumulated and returned. Throughput/memory stats are logged at the end.
    """
    import time
    _emit(f"[SECTION] {section}")
    parts = []
    last = None
    started = time.time()
    for chunk in stream_generate(model, processor, prompt, image, **kwargs):
        delta = getattr(chunk, "text", "") or ""
        if delta:
            parts.append(delta)
            _emit("[TOKEN] " + json.dumps(delta, ensure_ascii=False))
        last = chunk
    elapsed = time.time() - started
    if last is not None:
        gen_tps = getattr(last, "generation_tps", 0.0) or 0.0
        prompt_tps = getattr(last, "prompt_tps", 0.0) or 0.0
        peak = getattr(last, "peak_memory", 0.0) or 0.0
        logger.info(
            f"{section}: fertig in {elapsed:.1f}s – Prompt {prompt_tps:.1f} tok/s, "
            f"Generierung {gen_tps:.1f} tok/s, Peak-Speicher {peak:.2f} GB"
        )
    return "".join(parts).strip()


def main() -> None:
    """Run offline Gemma 4 transfer feedback analysis from CLI JSON input."""
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(line_buffering=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    parser = argparse.ArgumentParser(description="Analyse transfer feedback offline with Gemma 4.")
    parser.add_argument("--input-json", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--model-path", default=None)
    args = parser.parse_args()

    with open(args.input_json, encoding="utf-8") as f:
        payload = json.load(f)
    regions = payload.get("regions", [])
    final_prompt = payload["final_prompt"]
    placeholder = payload.get("placeholder", "{{REGION_FINDINGS}}")
    total = len(regions) + 1

    result = {"region_findings": [], "report": ""}
    model = processor = None
    if sys.platform == "darwin":
        os.environ["PYTORCH_MPS_HIGH_WATERMARK_RATIO"] = "0.0"
    try:
        import time
        model_path = args.model_path or MODEL_PATH
        if not os.path.exists(model_path):
            alt_path = os.path.join(PROJECT_ROOT, "assets", "models", "gemma")
            if os.path.exists(alt_path):
                model_path = alt_path

        use_mlx = False
        try:
            from mlx_vlm import load, stream_generate
            from mlx_vlm.prompt_utils import apply_chat_template
            from mlx_vlm.utils import load_config
            use_mlx = True
        except ImportError:
            use_mlx = False

        if use_mlx:
            logger.info(f"Lade Gemma-Modell (MLX) aus {os.path.relpath(model_path, PROJECT_ROOT)} ...")
            t0 = time.time()
            model, processor = load(model_path)
            config = load_config(model_path)
            logger.info(f"Modell geladen in {time.time() - t0:.1f}s ({len(regions)} markierte Stelle(n))")

            # 1. Isolated per-region structure descriptions
            for idx, region in enumerate(regions, 1):
                _progress(idx, total, f"Analysiere markierte Stelle {idx}/{len(regions)}")
                path = region.get("path", "")
                if not os.path.exists(path):
                    result["region_findings"].append("")
                    continue
                try:
                    prompt = apply_chat_template(processor, config, region.get("prompt", ""), num_images=1)
                    text = _stream(stream_generate, model, processor, prompt, [path], f"region {idx}",
                                   max_tokens=REGION_MAX_TOKENS, repetition_penalty=1.1,
                                   repetition_context_size=64)
                    result["region_findings"].append(text)
                except Exception as ex:
                    logger.error(f"Region analysis failed for {path}: {ex}")
                    result["region_findings"].append("")
                try:
                    import mlx.core as mx
                    mx.clear_cache()
                except Exception:
                    pass

            # 2. Text-only synthesis of the coding-assistant report
            findings_block = "\n".join(
                f"- Stelle {i}: {txt if txt else '(keine Beschreibung verfügbar)'}"
                for i, txt in enumerate(result["region_findings"], 1)
            )
            final_prompt = final_prompt.replace(placeholder, findings_block)
            _progress(total, total, "Erstelle Fehleranalyse für Coding Assistant")
            prompt = apply_chat_template(processor, config, final_prompt, num_images=0)
            result["report"] = _stream(stream_generate, model, processor, prompt, None, "report",
                                       max_tokens=REPORT_MAX_TOKENS, repetition_penalty=1.05,
                                       repetition_context_size=128)
        else:
            import torch
            from PIL import Image
            from transformers import AutoModelForImageTextToText, AutoProcessor

            logger.info(f"Lade Gemma-Modell (PyTorch) aus {os.path.relpath(model_path, PROJECT_ROOT)} ...")
            processor = AutoProcessor.from_pretrained(model_path, local_files_only=True, trust_remote_code=True)
            model = AutoModelForImageTextToText.from_pretrained(
                model_path,
                dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
                device_map="auto" if torch.cuda.is_available() else None,
                local_files_only=True,
                trust_remote_code=True,
            )
            model.eval()
            target_device = next(model.parameters()).device

            for idx, region in enumerate(regions, 1):
                _progress(idx, total, f"Analysiere markierte Stelle {idx}/{len(regions)}")
                path = region.get("path", "")
                if not os.path.exists(path):
                    result["region_findings"].append("")
                    continue
                try:
                    _emit(f"[SECTION] region {idx}")
                    with Image.open(path) as raw_img:
                        pil_img = raw_img.convert("RGB")
                    messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": region.get("prompt", "")}]}]
                    text_prompt = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                    inputs = processor(text=[text_prompt], images=[pil_img], return_tensors="pt")
                    inputs = {k: v.to(target_device) if hasattr(v, "to") else v for k, v in inputs.items()}
                    with torch.no_grad():
                        out_ids = model.generate(**inputs, max_new_tokens=REGION_MAX_TOKENS, do_sample=False, repetition_penalty=1.1)
                    in_len = inputs["input_ids"].shape[1]
                    text = processor.batch_decode(out_ids[:, in_len:], skip_special_tokens=True)[0].strip()
                    if text:
                        _emit("[TOKEN] " + json.dumps(text, ensure_ascii=False))
                    result["region_findings"].append(text)
                except Exception as ex:
                    logger.error(f"Region analysis failed for {path}: {ex}")
                    result["region_findings"].append("")

            findings_block = "\n".join(
                f"- Stelle {i}: {txt if txt else '(keine Beschreibung verfügbar)'}"
                for i, txt in enumerate(result["region_findings"], 1)
            )
            final_prompt = final_prompt.replace(placeholder, findings_block)
            _progress(total, total, "Erstelle Fehleranalyse für Coding Assistant")
            _emit("[SECTION] report")
            messages = [{"role": "user", "content": [{"type": "text", "text": final_prompt}]}]
            text_prompt = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = processor(text=[text_prompt], return_tensors="pt")
            inputs = {k: v.to(target_device) if hasattr(v, "to") else v for k, v in inputs.items()}
            with torch.no_grad():
                out_ids = model.generate(**inputs, max_new_tokens=REPORT_MAX_TOKENS, do_sample=False, repetition_penalty=1.05)
            in_len = inputs["input_ids"].shape[1]
            report_text = processor.batch_decode(out_ids[:, in_len:], skip_special_tokens=True)[0].strip()
            if report_text:
                _emit("[TOKEN] " + json.dumps(report_text, ensure_ascii=False))
            result["report"] = report_text
    except Exception as ex:
        logger.error(f"Feedback analyzer failed: {ex}")
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
        import gc
        gc.collect()

    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
