"""LLM server lifecycle, page-chunked planning, and Gemma 4 standardisation service.

Orchestrates local Gemma 4 inference (via Apple Silicon ``rapid-mlx`` OpenAI
streaming or PyTorch CUDA/CPU fallback), page-wise chunk planning with read-only
neighbor page context, and interactive user-feedback optimization.

Prompt definitions live in ``backend.services.prompts``, static constants in
``backend.services.fibs_constants``, Pydantic models in ``backend.services.models``,
and deterministic FIBS post-processing in ``backend.services.fibs_postprocess``.
"""

from __future__ import annotations

import asyncio
import gc
import inspect
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx
from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAI

from backend.services import fibs_constants as fc
from backend.services.fibs_formatting import (
    bild_tag_from_vlm,
    format_bild_tag,
    has_caption_context,
)
from backend.services.fibs_postprocess import (
    optimize_markdown_fallback,
    post_process_structure,
    split_markdown_pages,
    standardise_markdown_fallback,
)
from backend.services.models import (
    StandardisationChunk,
    TableDescription,
    VlmDescriptionResult,
)
from backend.services.prompts import (
    CHUNK_MODE_INSTRUCTIONS,
    OPTIMIZE_SYSTEM_INSTRUCTION,
    SYSTEM_PROMPTS,
    VLM_IMAGE_PROMPT,
    build_chunk_section_message,
    build_custom_rules_block,
    build_optimize_user_prompt,
    build_vlm_prompt,
    table_resolution_rule,
)

logger = logging.getLogger(__name__)

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class StandardisationError(RuntimeError):
    """Raised when Gemma standardisation fails and silent fallback is disallowed."""


class StandardisationAborted(RuntimeError):
    """Raised from a token or progress callback to abort an active generation."""


def get_model_path() -> str:
    """Resolves the local Gemma model path from environment or workspace assets.

    Returns:
        Absolute filesystem path to the local Gemma model directory.
    """
    env_path = os.environ.get("GEMMA_MODEL_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    mlx_path = os.path.join(BASE_DIR, "assets", "models", "gemma", "mlx")
    if os.path.exists(mlx_path):
        return mlx_path
    gemma_root = os.path.join(BASE_DIR, "assets", "models", "gemma")
    if os.path.exists(gemma_root):
        return gemma_root
    return mlx_path


MODEL_PATH = get_model_path()

# ---------------------------------------------------------------------------
# Engine State & Idle Timer Management
# ---------------------------------------------------------------------------

_RAPID_MLX_PROCESS: subprocess.Popen[Any] | None = None
_RAPID_MLX_LOG_FILE: Any = None
_OPENAI_CLIENT: OpenAI | None = None
_ASYNC_OPENAI_CLIENT: AsyncOpenAI | None = None
_MLX_VLM_MODEL: Any = None
_MLX_VLM_PROCESSOR: Any = None
_TORCH_LLM_MODEL: Any = None
_TORCH_LLM_TOKENIZER: Any = None
_IDLE_TIMER: threading.Timer | None = None


def _cancel_idle_timer() -> None:
    """Cancels the active ``rapid-mlx`` idle shutdown timer if running."""
    global _IDLE_TIMER
    if _IDLE_TIMER is not None:
        try:
            _IDLE_TIMER.cancel()
        except Exception:
            pass
        _IDLE_TIMER = None


def _on_idle_timeout() -> None:
    """Callback invoked when the ``rapid-mlx`` server idle timeout expires."""
    logger.info(
        f"rapid-mlx idle timeout ({fc.IDLE_TIMEOUT_SECONDS}s) expired. "
        "Stopping background server to release VRAM..."
    )
    close_engine()
    release_gpu_memory()


def reset_idle_timer() -> None:
    """Resets the sliding idle timer so ``rapid-mlx`` stays warm during active use."""
    global _IDLE_TIMER
    _cancel_idle_timer()
    _IDLE_TIMER = threading.Timer(fc.IDLE_TIMEOUT_SECONDS, _on_idle_timeout)
    _IDLE_TIMER.daemon = True
    _IDLE_TIMER.start()


def _build_rapid_mlx_command(model_path: str) -> list[str]:
    """Constructs the CLI command for spawning the local ``rapid-mlx`` server.

    Args:
        model_path: Path to the local MLX model directory.

    Returns:
        List of command-line arguments for ``subprocess.Popen``.
    """
    venv_bin_dir = os.path.dirname(sys.executable)
    venv_rapid_mlx = os.path.join(venv_bin_dir, "rapid-mlx")
    if not os.path.exists(venv_rapid_mlx):
        venv_rapid_mlx = os.path.join(BASE_DIR, ".venv", "bin", "rapid-mlx")
    if not os.path.exists(venv_rapid_mlx):
        venv_rapid_mlx = shutil.which("rapid-mlx") or "rapid-mlx"

    return [
        venv_rapid_mlx,
        "serve",
        model_path,
        "--port",
        "8001",
        "--host",
        "127.0.0.1",
        "--max-tokens",
        "8192",
        "--no-thinking",
        "--no-tool-call-parser",
        "--no-reasoning-parser",
        "--max-num-seqs",
        "1",
        "--gpu-memory-utilization",
        "0.95",
        "--disable-prefix-cache",
        "--no-mllm",
        "--text-only",
        "--cache-memory-mb",
        "256",
        "--max-cache-blocks",
        "128",
    ]


def _open_rapid_mlx_log_file() -> Any:
    """Opens and rotates ``assets/logs/rapid_mlx.log`` for server stdout/stderr.

    Returns:
        Open writable file handle for ``rapid_mlx.log``.
    """
    log_dir = os.path.join(BASE_DIR, "assets", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file_path = os.path.join(log_dir, "rapid_mlx.log")
    max_log_bytes = 5 * 1024 * 1024
    keep_log_bytes = 2 * 1024 * 1024
    if os.path.exists(log_file_path) and os.path.getsize(log_file_path) > max_log_bytes:
        with open(log_file_path, "rb") as rf:
            rf.seek(-keep_log_bytes, os.SEEK_END)
            tail = rf.read()
        with open(log_file_path, "wb") as wf:
            wf.write(tail)
    handle = open(log_file_path, "a", encoding="utf-8")
    handle.write(f"\n--- rapid-mlx start {time.strftime('%Y-%m-%dT%H:%M:%S%z')} ---\n")
    handle.flush()
    return handle


def start_rapid_mlx() -> OpenAI | None:
    """Spawns the local ``rapid-mlx`` OpenAI-compatible server and waits until healthy.

    Returns:
        An ``OpenAI`` client connected to the local server, or ``None`` if unavailable.
    """
    global _RAPID_MLX_PROCESS, _RAPID_MLX_LOG_FILE, _OPENAI_CLIENT
    _cancel_idle_timer()

    if os.environ.get("E2E_MOCK") == "true":
        return None

    if _OPENAI_CLIENT is not None:
        try:
            response = httpx.get("http://127.0.0.1:8001/v1/models", timeout=0.5)
            if response.status_code == 200:
                return _OPENAI_CLIENT
        except Exception:
            _OPENAI_CLIENT = None

    base_url = os.environ.get("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8001/v1").rstrip("/")
    try:
        response = httpx.get(f"{base_url}/models", timeout=1.0)
        if response.status_code == 200:
            logger.info(f"Local OpenAI-compatible LLM server is running at {base_url}.")
            _OPENAI_CLIENT = OpenAI(
                base_url=base_url,
                api_key=os.environ.get("LOCAL_LLM_API_KEY", "local-key"),
            )
            return _OPENAI_CLIENT
    except Exception:
        pass

    model_path = get_model_path()
    if not os.path.exists(model_path):
        logger.warning(
            f"Local model path not found at {model_path}. Cannot start rapid-mlx server."
        )
        return None

    if sys.platform != "darwin":
        logger.info(
            "Non-macOS platform detected and no external server at LOCAL_LLM_BASE_URL; "
            "using PyTorch LLM backend."
        )
        return None

    cmd = _build_rapid_mlx_command(model_path)
    logger.info(f"Starting rapid-mlx server: {' '.join(cmd)}")

    try:
        _RAPID_MLX_LOG_FILE = _open_rapid_mlx_log_file()
        _RAPID_MLX_PROCESS = subprocess.Popen(
            cmd,
            stdout=_RAPID_MLX_LOG_FILE,
            stderr=subprocess.STDOUT,
        )

        start_time = time.time()
        timeout = 45.0
        while time.time() - start_time < timeout:
            if _RAPID_MLX_PROCESS.poll() is not None:
                logger.error("rapid-mlx subprocess exited prematurely.")
                break
            try:
                response = httpx.get("http://127.0.0.1:8001/v1/models", timeout=1.0)
                if response.status_code == 200:
                    logger.info("rapid-mlx server became responsive.")
                    _OPENAI_CLIENT = OpenAI(
                        base_url="http://127.0.0.1:8001/v1",
                        api_key="local-key",
                    )
                    return _OPENAI_CLIENT
            except Exception:
                pass
            time.sleep(0.5)

        logger.error(f"rapid-mlx server failed to respond within {timeout}s.")
    except Exception as e:
        logger.error(f"Failed to spawn rapid-mlx server: {e}")

    return None


_DEFAULT_START_RAPID_MLX = start_rapid_mlx


async def start_rapid_mlx_async() -> AsyncOpenAI | OpenAI | None:
    """Asynchronously starts or connects to ``rapid-mlx`` using ``httpx.AsyncClient``.

    Respects unit-test monkeypatches on ``start_rapid_mlx``.

    Returns:
        An ``AsyncOpenAI`` client (or monkeypatched test client), or ``None`` if unavailable.
    """
    global _RAPID_MLX_PROCESS, _RAPID_MLX_LOG_FILE, _OPENAI_CLIENT, _ASYNC_OPENAI_CLIENT
    if start_rapid_mlx is not _DEFAULT_START_RAPID_MLX:
        res = start_rapid_mlx()
        if inspect.isawaitable(res):
            res = await res
        return res

    _cancel_idle_timer()

    if os.environ.get("E2E_MOCK") == "true":
        return None

    base_url = os.environ.get("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8001/v1").rstrip("/")
    api_key = os.environ.get("LOCAL_LLM_API_KEY", "local-key")

    if _ASYNC_OPENAI_CLIENT is not None:
        try:
            async with httpx.AsyncClient(timeout=0.5) as hc:
                response = await hc.get(f"{base_url}/models")
                if response.status_code == 200:
                    return _ASYNC_OPENAI_CLIENT
        except Exception:
            _ASYNC_OPENAI_CLIENT = None

    try:
        async with httpx.AsyncClient(timeout=1.0) as hc:
            response = await hc.get(f"{base_url}/models")
            if response.status_code == 200:
                logger.info(f"Local OpenAI-compatible LLM server is running at {base_url}.")
                _OPENAI_CLIENT = OpenAI(base_url=base_url, api_key=api_key)
                _ASYNC_OPENAI_CLIENT = AsyncOpenAI(base_url=base_url, api_key=api_key)
                return _ASYNC_OPENAI_CLIENT
    except Exception:
        pass

    model_path = get_model_path()
    if not os.path.exists(model_path):
        logger.warning(
            f"Local model path not found at {model_path}. Cannot start rapid-mlx server."
        )
        return None

    if sys.platform != "darwin":
        logger.info(
            "Non-macOS platform detected and no external server at LOCAL_LLM_BASE_URL; "
            "using PyTorch LLM backend."
        )
        return None

    cmd = _build_rapid_mlx_command(model_path)
    logger.info(f"Starting rapid-mlx server (async): {' '.join(cmd)}")

    try:
        _RAPID_MLX_LOG_FILE = _open_rapid_mlx_log_file()
        _RAPID_MLX_PROCESS = subprocess.Popen(
            cmd,
            stdout=_RAPID_MLX_LOG_FILE,
            stderr=subprocess.STDOUT,
        )

        start_time = time.time()
        timeout = 45.0
        async with httpx.AsyncClient(timeout=1.0) as hc:
            while time.time() - start_time < timeout:
                if _RAPID_MLX_PROCESS.poll() is not None:
                    logger.error("rapid-mlx subprocess exited prematurely.")
                    break
                try:
                    response = await hc.get("http://127.0.0.1:8001/v1/models")
                    if response.status_code == 200:
                        logger.info("rapid-mlx server became responsive.")
                        _OPENAI_CLIENT = OpenAI(
                            base_url="http://127.0.0.1:8001/v1",
                            api_key="local-key",
                        )
                        _ASYNC_OPENAI_CLIENT = AsyncOpenAI(
                            base_url="http://127.0.0.1:8001/v1",
                            api_key="local-key",
                        )
                        return _ASYNC_OPENAI_CLIENT
                except Exception:
                    pass
                await asyncio.sleep(0.5)

        logger.error(f"rapid-mlx server failed to respond within {timeout}s.")
    except Exception as e:
        logger.error(f"Failed to spawn rapid-mlx server: {e}")

    return None


def close_engine() -> None:
    """Stops the background ``rapid-mlx`` server and closes its log file handle."""
    global _RAPID_MLX_PROCESS, _RAPID_MLX_LOG_FILE, _OPENAI_CLIENT, _ASYNC_OPENAI_CLIENT
    _cancel_idle_timer()
    _OPENAI_CLIENT = None
    _ASYNC_OPENAI_CLIENT = None
    if _RAPID_MLX_PROCESS is not None:
        logger.info("Stopping rapid-mlx background server...")
        try:
            _RAPID_MLX_PROCESS.terminate()
            _RAPID_MLX_PROCESS.wait(timeout=5.0)
            logger.info("rapid-mlx background server stopped successfully.")
        except Exception as e:
            logger.error(f"Error stopping rapid-mlx server: {e}")
            try:
                _RAPID_MLX_PROCESS.kill()
            except Exception:
                pass
        finally:
            _RAPID_MLX_PROCESS = None
    if _RAPID_MLX_LOG_FILE is not None:
        try:
            _RAPID_MLX_LOG_FILE.close()
        except Exception:
            pass
        _RAPID_MLX_LOG_FILE = None


def release_gpu_memory() -> None:
    """Releases GPU memory held by ``rapid-mlx``, ``mlx_vlm``, and PyTorch CUDA/MPS caches."""
    global _MLX_VLM_MODEL, _MLX_VLM_PROCESSOR, _TORCH_LLM_MODEL, _TORCH_LLM_TOKENIZER
    close_engine()
    if _MLX_VLM_MODEL is not None:
        logger.info("Releasing mlx_vlm model memory for GPU sequencing...")
        _MLX_VLM_MODEL = None
        _MLX_VLM_PROCESSOR = None
    if _TORCH_LLM_MODEL is not None:
        logger.info("Releasing PyTorch LLM model memory for GPU sequencing...")
        _TORCH_LLM_MODEL = None
        _TORCH_LLM_TOKENIZER = None
    try:
        import mlx.core as mx

        mx.synchronize()
        mx.clear_cache()
    except Exception:
        pass
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:
        pass
    gc.collect()
    logger.info("GPU sequencing cleanup complete.")


def _resolve_torch_llm_model_id() -> str:
    """Resolves the local model directory or HuggingFace ID for PyTorch inference.

    Returns:
        Local model directory path or HuggingFace model identifier.
    """
    env_id = os.environ.get("CUDA_LLM_MODEL_ID") or os.environ.get("GEMMA_MODEL_PATH")
    if env_id:
        return env_id
    for candidate in (
        os.path.join(BASE_DIR, "assets", "models", "gemma"),
        os.path.join(BASE_DIR, "assets", "models", "gemma", "mlx"),
    ):
        if os.path.exists(os.path.join(candidate, "config.json")):
            return candidate
    return "google/gemma-4-12b-it"


def _run_torch_cuda_llm(
    system_prompt: str,
    user_content: str,
    max_tokens: int = 4096,
    on_token: Callable[[str], None] | None = None,
) -> str | None:
    """Runs local PyTorch/CUDA (or CPU opt-in) LLM inference when ``rapid-mlx`` is unavailable.

    Args:
        system_prompt: System prompt instruction string.
        user_content: User message payload.
        max_tokens: Maximum number of tokens to generate.
        on_token: Optional streaming callback invoked for each generated token delta.

    Returns:
        Generated text response, or ``None`` if PyTorch inference is unavailable.

    Raises:
        StandardisationAborted: If ``on_token`` raises ``StandardisationAborted``.
    """
    global _TORCH_LLM_MODEL, _TORCH_LLM_TOKENIZER
    if os.environ.get("E2E_MOCK") == "true" or os.environ.get("DISABLE_TORCH_LLM") == "1":
        return None
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer

        has_cuda = torch.cuda.is_available()
        if not has_cuda and os.environ.get("ALLOW_CPU_LLM") != "1":
            return None

        model_id = _resolve_torch_llm_model_id()
        is_local = os.path.isdir(model_id)
        if _TORCH_LLM_MODEL is None:
            logger.info(f"Loading local PyTorch LLM from {model_id} (cuda={has_cuda})...")
            load_kwargs: dict[str, Any] = {
                "local_files_only": is_local or os.environ.get("HF_HUB_OFFLINE") == "1",
                "trust_remote_code": True,
            }
            if has_cuda:
                load_kwargs["device_map"] = "auto"
                try:
                    import bitsandbytes  # noqa: F401
                    from transformers import BitsAndBytesConfig

                    load_kwargs["quantization_config"] = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=torch.bfloat16,
                        bnb_4bit_quant_type="nf4",
                    )
                except ImportError:
                    load_kwargs["dtype"] = torch.bfloat16
            else:
                load_kwargs["dtype"] = torch.float32

            _TORCH_LLM_TOKENIZER = AutoTokenizer.from_pretrained(
                model_id,
                **{
                    k: v
                    for k, v in load_kwargs.items()
                    if k in ("local_files_only", "trust_remote_code")
                },
            )
            _TORCH_LLM_MODEL = AutoModelForCausalLM.from_pretrained(model_id, **load_kwargs)
            _TORCH_LLM_MODEL.eval()

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        text = _TORCH_LLM_TOKENIZER.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        target_device = next(_TORCH_LLM_MODEL.parameters()).device
        model_inputs = _TORCH_LLM_TOKENIZER([text], return_tensors="pt").to(target_device)

        if on_token is not None:
            streamer = TextIteratorStreamer(
                _TORCH_LLM_TOKENIZER, skip_prompt=True, skip_special_tokens=True
            )
            gen_kwargs = dict(
                **model_inputs,
                streamer=streamer,
                max_new_tokens=max_tokens,
                repetition_penalty=1.1,
                do_sample=False,
            )
            thread = threading.Thread(
                target=_TORCH_LLM_MODEL.generate, kwargs=gen_kwargs, daemon=True
            )
            thread.start()
            collected: list[str] = []
            for delta in streamer:
                if delta:
                    collected.append(delta)
                    try:
                        on_token(delta)
                    except StandardisationAborted:
                        raise
                    except Exception:
                        pass
            thread.join(timeout=5.0)
            return "".join(collected).strip()

        with torch.no_grad():
            generated_ids = _TORCH_LLM_MODEL.generate(
                **model_inputs,
                max_new_tokens=max_tokens,
                repetition_penalty=1.1,
                do_sample=False,
            )
        generated_ids = [
            output_ids[len(input_ids) :]
            for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
        ]
        response = _TORCH_LLM_TOKENIZER.batch_decode(generated_ids, skip_special_tokens=True)[0]
        return response.strip()
    except StandardisationAborted:
        raise
    except Exception as e:
        logger.warning(f"PyTorch LLM fallback failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Page-Chunked Gemma Planning & Context Helpers
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Computes a conservative token estimate for German Markdown (~3 chars/token).

    Args:
        text: Input Markdown string.

    Returns:
        Estimated token count.
    """
    return int(len(text or "") / fc.CHARS_PER_TOKEN) + 1


def output_token_allowance(text: str) -> int:
    """Computes the maximum output token budget for a section of ``text``.

    Args:
        text: Input Markdown section.

    Returns:
        Bounded ``max_tokens`` value for the LLM request.
    """
    return min(
        fc.GEMMA_MAX_OUTPUT_TOKENS,
        int(estimate_tokens(text) * fc.OUTPUT_TOKEN_FACTOR) + fc.OUTPUT_TOKEN_MARGIN,
    )


def _open_block_depth(text: str) -> int:
    """Counts unclosed FIBS/HTML block tags or display-math ``$$`` blocks in ``text``.

    Args:
        text: Partial Markdown string.

    Returns:
        Number of currently open structural blocks.
    """
    depth = sum(
        text.count(open_tag) - text.count(close_tag) for open_tag, close_tag in fc.BLOCK_TAGS
    )
    if text.count("$$") % 2:
        depth += 1
    return depth


def _split_page_into_paragraph_units(text: str) -> list[str]:
    """Splits a single oversized page at blank lines without tearing tags or ``$$`` blocks.

    Args:
        text: Markdown text of one page.

    Returns:
        List of lossless paragraph-group strings whose concatenation equals ``text``.
    """
    parts = re.split(r"(\n[ \t]*\n)", text)
    units: list[str] = []
    current = ""
    for i in range(0, len(parts), 2):
        piece = parts[i] + (parts[i + 1] if i + 1 < len(parts) else "")
        current += piece
        if _open_block_depth(current) <= 0 and current.strip():
            units.append(current)
            current = ""
    if current:
        if units and not current.strip():
            units[-1] += current
        else:
            units.append(current)
    return units


def _cost(text: str) -> int:
    """Computes the combined input + output token budget cost of ``text``."""
    return estimate_tokens(text) + output_token_allowance(text)


def _tail(text: str, max_chars: int) -> str:
    """Extracts the trailing ``max_chars`` of ``text``, preferring paragraph boundaries."""
    if len(text) <= max_chars:
        return text
    tail = text[-max_chars:]
    cut = tail.find("\n\n")
    return tail[cut + 2 :] if 0 <= cut < max_chars // 2 else tail


def _head(text: str, max_chars: int) -> str:
    """Extracts the leading ``max_chars`` of ``text``, preferring paragraph boundaries."""
    if len(text) <= max_chars:
        return text
    head = text[:max_chars]
    cut = head.rfind("\n\n")
    return head[:cut] if cut > max_chars // 2 else head


def build_standardisation_chunks(
    markdown: str,
    system_prompt: str,
    token_budget: int | None = None,
) -> list[StandardisationChunk]:
    """Plans page-wise Gemma standardisation chunks with neighbor-page context.

    Short documents that fit inside ``MAX_PAGES_PER_CHUNK`` and ``token_budget``
    become a single chunk without context banners. Longer documents are grouped
    into chunks of whole pages (or paragraph groups for oversized pages) with
    read-only previous and following page context.

    Args:
        markdown: Full extracted Markdown document.
        system_prompt: Active system prompt string (used to account for fixed tokens).
        token_budget: Optional override for ``GEMMA_REQUEST_TOKEN_BUDGET``.

    Returns:
        List of ``StandardisationChunk`` Pydantic models.
    """
    budget = token_budget or fc.GEMMA_REQUEST_TOKEN_BUDGET
    fixed = estimate_tokens(system_prompt) + fc.FRAME_TOKENS
    content_budget = max(budget - fixed, 600)

    segments = split_markdown_pages(markdown)
    all_pages = [s.page for s in segments if s.page is not None]
    if (
        len(all_pages) <= fc.MAX_PAGES_PER_CHUNK
        and _cost(markdown) <= content_budget
        and output_token_allowance(markdown) < fc.GEMMA_MAX_OUTPUT_TOKENS
    ):
        return [
            StandardisationChunk(
                index=1,
                text=markdown,
                pages=[s.page for s in segments],
                estimated_request_tokens=fixed + _cost(markdown),
            )
        ]

    context_reserve = min(2 * fc.CONTEXT_MAX_TOKENS, content_budget // 3)
    text_limit = max(content_budget - context_reserve, 300)
    context_chars = int(context_reserve / 2 * fc.CHARS_PER_TOKEN)

    units: list[dict[str, Any]] = []
    for seg in segments:
        if _cost(seg.text) <= text_limit:
            units.append(
                {"page": seg.page, "text": seg.text, "part": None, "starts_page": True}
            )
            continue
        paragraph_units = _split_page_into_paragraph_units(seg.text)
        groups: list[str] = []
        for para in paragraph_units:
            if groups and _cost(groups[-1] + para) <= text_limit:
                groups[-1] += para
            else:
                groups.append(para)
        for part, group in enumerate(groups, 1):
            if _cost(group) > text_limit:
                logger.warning(
                    f"Seite {seg.page}: Block mit ~{estimate_tokens(group)} Tokens überschreitet "
                    "das Abschnittsbudget und wird ungeteilt übertragen."
                )
            units.append(
                {
                    "page": seg.page,
                    "text": group,
                    "part": part if len(groups) > 1 else None,
                    "starts_page": part == 1,
                }
            )

    grouped: list[list[dict[str, Any]]] = []
    for unit in units:
        if grouped:
            current = grouped[-1]
            text = "".join(u["text"] for u in current) + unit["text"]
            pages = {u["page"] for u in current + [unit] if u["starts_page"]}
            mergeable = unit["part"] is None and all(u["part"] is None for u in current)
            if mergeable and _cost(text) <= text_limit and len(pages) <= fc.MAX_PAGES_PER_CHUNK:
                current.append(unit)
                continue
        grouped.append([unit])

    chunks: list[StandardisationChunk] = []
    flat_index = 0
    for i, group in enumerate(grouped):
        text = "".join(u["text"] for u in group)
        first_idx, last_idx = flat_index, flat_index + len(group) - 1
        flat_index += len(group)
        prev_unit = units[first_idx - 1] if first_idx > 0 else None
        next_unit = units[last_idx + 1] if last_idx + 1 < len(units) else None
        pages: list[str | None] = []
        for u in group:
            if u["page"] not in pages:
                pages.append(u["page"])
        prev_ctx = _tail(prev_unit["text"], context_chars) if prev_unit else ""
        next_ctx = _head(next_unit["text"], context_chars) if next_unit else ""
        chunk = StandardisationChunk(
            index=i + 1,
            text=text,
            pages=pages,
            part=group[0]["part"] if len(group) == 1 else None,
            prev_context=prev_ctx,
            next_context=next_ctx,
            prev_page=prev_unit["page"] if prev_unit else None,
            next_page=next_unit["page"] if next_unit else None,
            estimated_request_tokens=(
                fixed
                + _cost(text)
                + estimate_tokens(prev_ctx)
                + estimate_tokens(next_ctx)
            ),
        )
        chunks.append(chunk)
    return chunks


def describe_tables(markdown: str, max_cells: int) -> list[TableDescription]:
    """Finds tables in reading order and counts their cells for resolution hints.

    Args:
        markdown: Markdown string to inspect.
        max_cells: Maximum cell count up to which tables should be resolved.

    Returns:
        List of ``TableDescription`` models.
    """
    found: list[tuple[int, int, int]] = []
    for m in re.finditer(r"<Tabelle[^>]*>(.*?)</Tabelle>", markdown, flags=re.DOTALL):
        rows = [ln for ln in m.group(1).splitlines() if ln.strip()]
        found.append((m.start(), m.end(), sum(ln.count("\t") + 1 for ln in rows)))
    for m in re.finditer(r"<table\b.*?</table>", markdown, flags=re.DOTALL | re.IGNORECASE):
        found.append(
            (m.start(), m.end(), len(re.findall(r"<t[dh]\b", m.group(0), flags=re.IGNORECASE)))
        )
    fences: list[tuple[int, int]] = []
    fence_start: int | None = None
    offset = 0
    for line in markdown.splitlines(keepends=True):
        if line.lstrip().startswith("```"):
            if fence_start is None:
                fence_start = offset
            else:
                fences.append((fence_start, offset + len(line)))
                fence_start = None
        offset += len(line)
    if fence_start is not None:
        fences.append((fence_start, len(markdown)))
    for m in re.finditer(r"(?:^[ \t]*\|.*\|[ \t]*(?:\n|$))+", markdown, flags=re.MULTILINE):
        if any(s <= m.start() < e for s, e, _ in found) or any(
            s <= m.start() < e for s, e in fences
        ):
            continue
        cells = 0
        for row in m.group(0).splitlines():
            stripped = row.strip()
            if not stripped:
                continue
            row_cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in row_cells):
                continue
            cells += len(row_cells)
        found.append((m.start(), m.end(), cells))
    found.sort()
    return [
        TableDescription(cells=cells, resolve=bool(max_cells) and cells <= max_cells)
        for _, _, cells in found
    ]


def _table_hint(text: str, max_cells: int) -> str:
    """Builds the per-section ``[HINWEIS TABELLEN]`` block when ``max_cells > 0``."""
    if not max_cells:
        return ""
    tables = describe_tables(text, max_cells)
    if not tables:
        return ""
    lines = [
        f"Tabelle {i}: {t.cells} Zellen → "
        + ("auflösen" if t.resolve else "als <Tabelle> beibehalten")
        for i, t in enumerate(tables, 1)
    ]
    return "[HINWEIS TABELLEN – nicht ausgeben]\n" + "\n".join(lines) + "\n[ENDE HINWEIS]"


def build_chunk_user_message(
    chunk: StandardisationChunk,
    total: int,
    table_max_cells: int = 0,
) -> str:
    """Builds the user message for one chunk using Python 3.14 template strings.

    Args:
        chunk: Planned ``StandardisationChunk`` instance.
        total: Total number of chunks in the document plan.
        table_max_cells: Optional threshold for resolving small tables.

    Returns:
        Formatted user message string with read-only context and section markers.
    """
    return build_chunk_section_message(
        index=chunk.index,
        total=total,
        label=chunk.label,
        text=chunk.text,
        prev_context=chunk.prev_context,
        next_context=chunk.next_context,
        table_hint=_table_hint(chunk.text, table_max_cells),
    )


def _clean_chunk_output(text: str) -> str:
    """Strips echoed section/context banners and table hints from Gemma's response."""
    text = re.sub(r"^\[truncated[^\]]*\]\s*", "", text or "")
    text = re.sub(r"\[HINWEIS TABELLEN[^\]]*\].*?\[ENDE HINWEIS\]", "", text, flags=re.DOTALL)
    text = re.sub(r"(?m)^[ \t]*\[(?:ENDE )?(?:ABSCHNITT|KONTEXT)[^\]\n]*\][ \t]*$\n?", "", text)
    return text.strip()


def _trim_to_own_pages(text: str, chunk: StandardisationChunk) -> str:
    """Drops neighbor-page content if Gemma accidentally echoed context pages."""
    own = {p for p in chunk.pages if p}
    lines = text.split("\n")
    marker_re = re.compile(r"^\s*\(\((\d+)\)\)\s*$")
    if chunk.next_page and chunk.next_page not in own:
        for idx, line in enumerate(lines):
            m = marker_re.match(line)
            if m and m.group(1) == chunk.next_page:
                logger.warning(
                    f"Gemma hat Kontext der folgenden Seite (({chunk.next_page})) ausgegeben – entfernt."
                )
                lines = lines[:idx]
                break
    if chunk.prev_page and chunk.prev_page not in own:
        first_own: int | None = None
        prev_idx: int | None = None
        for i, ln in enumerate(lines):
            m = marker_re.match(ln)
            if not m:
                continue
            if first_own is None and m.group(1) in own:
                first_own = i
            if prev_idx is None and m.group(1) == chunk.prev_page:
                prev_idx = i
            if first_own is not None and prev_idx is not None:
                break
        if prev_idx is not None and first_own is not None and prev_idx < first_own:
            logger.warning(
                f"Gemma hat Kontext der vorherigen Seite (({chunk.prev_page})) ausgegeben – entfernt."
            )
            lines = lines[first_own:]
    return "\n".join(lines).strip()


def _load_custom_rules(task_id: str | None) -> str | None:
    """Loads book-specific custom rules from ``custom_ruleset.txt`` for a task.

    Args:
        task_id: Optional conversion task ID.

    Returns:
        Trimmed custom rules string if present and non-empty, otherwise ``None``.
    """
    if not task_id:
        return None
    custom_rules_path = os.path.join(BASE_DIR, "assets", "output", task_id, "custom_ruleset.txt")
    if not os.path.exists(custom_rules_path):
        return None
    try:
        with open(custom_rules_path, encoding="utf-8") as f:
            custom_rules = f.read().strip()
        return custom_rules or None
    except Exception as e:
        logger.error(f"Failed to read custom ruleset: {e}")
        return None


def _build_system_prompt(
    ruleset_key: str,
    task_id: str | None,
    table_max_cells: int,
    chunked: bool,
    directory_info: dict[str, Any] | None = None,
    custom_rules: str | None = None,
) -> str:
    """Constructs the complete Gemma system prompt including table, chunk, TOC, and custom rules.

    Args:
        ruleset_key: Identifier of the base FIBS ruleset.
        task_id: Optional task ID used to load ``custom_ruleset.txt`` or ``directory_info``.
        table_max_cells: Maximum cell count for small-table resolution.
        chunked: Whether multi-chunk mode instructions should be appended.
        directory_info: Optional detected TOC/directory metadata dictionary.
        custom_rules: Optional pre-loaded book-specific custom rules string.

    Returns:
        Assembled system prompt string.
    """
    system_prompt = SYSTEM_PROMPTS.get(ruleset_key, SYSTEM_PROMPTS["uebertragungsregeln_09_2025"])
    table_rule = table_resolution_rule(table_max_cells)
    if table_rule:
        system_prompt = f"{system_prompt}\n\n{table_rule}"
    if chunked:
        system_prompt = f"{system_prompt}\n\n{CHUNK_MODE_INSTRUCTIONS}"

    if directory_info is None and task_id:
        try:
            from backend.services.directory_service import load_directory_info

            task_out_dir = os.path.join(BASE_DIR, "assets", "output", task_id)
            directory_info = load_directory_info(task_out_dir)
        except Exception:
            pass

    if directory_info and directory_info.get("has_any_directory"):
        try:
            from backend.services.directory_service import format_directory_prompt_context

            dir_context = format_directory_prompt_context(directory_info)
            if dir_context:
                system_prompt = f"{system_prompt}\n\n{dir_context}"
        except Exception as e:
            logger.debug(f"Could not format directory prompt context: {e}")

    resolved_custom_rules = custom_rules if custom_rules is not None else _load_custom_rules(task_id)
    if resolved_custom_rules:
        system_prompt = f"{system_prompt}\n\n{build_custom_rules_block(resolved_custom_rules)}"
    return system_prompt


def _stream_chat_completion(
    client: Any,
    system_prompt: str,
    user_content: str,
    max_tokens: int,
    on_token: Callable[[str], None] | None,
) -> str:
    """Executes one synchronous streaming chat completion against ``rapid-mlx``.

    Args:
        client: OpenAI-compatible synchronous client.
        system_prompt: System prompt string.
        user_content: User message string.
        max_tokens: Maximum output tokens.
        on_token: Optional token delta callback.

    Returns:
        Full generated response text.

    Raises:
        StandardisationAborted: If ``on_token`` raises ``StandardisationAborted``.
    """
    response = client.chat.completions.create(
        model=MODEL_PATH,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.0,
        max_tokens=max_tokens,
        stream=True,
    )
    collected: list[str] = []
    try:
        for chunk in response:
            delta = (
                chunk.choices[0].delta.content if chunk.choices and chunk.choices[0].delta else ""
            )
            if not delta:
                continue
            collected.append(delta)
            if on_token:
                try:
                    on_token(delta)
                except StandardisationAborted:
                    raise
                except Exception as cb_err:
                    logger.debug(f"Token callback error ignored: {cb_err}")
    except StandardisationAborted:
        close = getattr(response, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
        raise
    return "".join(collected)


async def _stream_chat_completion_async(
    client: Any,
    system_prompt: str,
    user_content: str,
    max_tokens: int,
    on_token: Callable[[str], None] | None,
) -> str:
    """Executes one asynchronous streaming chat completion using ``AsyncOpenAI``.

    Also supports synchronous iterators returned by test mocks.

    Args:
        client: ``AsyncOpenAI`` (or mocked synchronous) client.
        system_prompt: System prompt string.
        user_content: User message string.
        max_tokens: Maximum output tokens.
        on_token: Optional token delta callback.

    Returns:
        Full generated response text.

    Raises:
        StandardisationAborted: If ``on_token`` raises ``StandardisationAborted``.
    """
    response = client.chat.completions.create(
        model=MODEL_PATH,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.0,
        max_tokens=max_tokens,
        stream=True,
    )
    if inspect.isawaitable(response):
        response = await response
    collected: list[str] = []
    try:
        if hasattr(response, "__aiter__"):
            async for chunk in response:
                delta = (
                    chunk.choices[0].delta.content
                    if chunk.choices and chunk.choices[0].delta
                    else ""
                )
                if not delta:
                    continue
                collected.append(delta)
                if on_token:
                    try:
                        on_token(delta)
                    except StandardisationAborted:
                        raise
                    except Exception as cb_err:
                        logger.debug(f"Token callback error ignored: {cb_err}")
        else:
            for chunk in response:
                delta = (
                    chunk.choices[0].delta.content
                    if chunk.choices and chunk.choices[0].delta
                    else ""
                )
                if not delta:
                    continue
                collected.append(delta)
                if on_token:
                    try:
                        on_token(delta)
                    except StandardisationAborted:
                        raise
                    except Exception as cb_err:
                        logger.debug(f"Token callback error ignored: {cb_err}")
    except StandardisationAborted:
        close = getattr(response, "close", None)
        if callable(close):
            try:
                res = close()
                if inspect.isawaitable(res):
                    await res
            except Exception:
                pass
        raise
    return "".join(collected)


def _rule_based_fallback_allowed(explicit: bool | None) -> bool:
    """Checks whether the deterministic fallback is explicitly permitted."""
    if explicit is not None:
        return explicit
    return (
        os.environ.get("E2E_MOCK") == "true"
        or os.environ.get("ALLOW_RULE_BASED_FALLBACK") == "1"
    )


def _emit_progress(on_progress: Callable[[dict[str, Any]], None] | None, **info: Any) -> None:
    """Safely invokes the caller's progress callback with ``info``."""
    if not on_progress:
        return
    try:
        on_progress(info)
    except StandardisationAborted:
        raise
    except Exception as err:
        logger.debug(f"Progress callback error ignored: {err}")


def _prepare_standardisation_plan(
    raw_markdown: str,
    ruleset_key: str,
    task_id: str | None,
    table_max_cells: int | None,
    directory_info: dict[str, Any] | None,
    on_progress: Callable[[dict[str, Any]], None] | None,
    custom_rules: str | None = None,
) -> tuple[int, dict[str, Any] | None, str | None, str, list[StandardisationChunk], bool]:
    """Resolves settings, directory metadata, system prompt, and chunks for standardisation.

    Shared between ``standardise_markdown`` and ``standardise_markdown_async``.

    Args:
        raw_markdown: Input Markdown string.
        ruleset_key: Active FIBS ruleset key.
        task_id: Optional conversion task ID.
        table_max_cells: Optional threshold for resolving small tables.
        directory_info: Optional detected TOC/directory metadata.
        on_progress: Optional progress callback.
        custom_rules: Optional book-specific custom rules string.

    Returns:
        Tuple of ``(resolved_table_max_cells, resolved_directory_info, resolved_custom_rules, system_prompt, chunks, is_single_chunk)``.
    """
    if table_max_cells is None:
        try:
            from backend.services.settings_service import get_setting

            table_max_cells = int(get_setting("table_resolve_max_cells"))
        except Exception as e:
            logger.warning(
                f"Einstellung table_resolve_max_cells nicht lesbar ({e}) – Tabellen werden nicht aufgelöst."
            )
            table_max_cells = 0

    if directory_info is None and task_id:
        try:
            from backend.services.directory_service import load_directory_info

            directory_info = load_directory_info(
                os.path.join(BASE_DIR, "assets", "output", task_id)
            )
        except Exception:
            pass

    resolved_custom_rules = (
        custom_rules if custom_rules is not None else _load_custom_rules(task_id)
    )
    chunk_prompt = _build_system_prompt(
        ruleset_key,
        task_id,
        table_max_cells,
        chunked=True,
        directory_info=directory_info,
        custom_rules=resolved_custom_rules,
    )
    chunks = build_standardisation_chunks(raw_markdown, chunk_prompt)
    total = len(chunks)
    single = total == 1
    system_prompt = (
        _build_system_prompt(
            ruleset_key,
            task_id,
            table_max_cells,
            chunked=False,
            directory_info=directory_info,
            custom_rules=resolved_custom_rules,
        )
        if single
        else chunk_prompt
    )
    if not single:
        msg = (
            f"Gemma-Standardisierung in {total} Abschnitten "
            "(ganze Seiten, mit vorheriger/folgender Seite als Kontext)."
        )
        logger.info(msg)
        _emit_progress(on_progress, event="plan", index=0, total=total, label="", message=msg)
    if table_max_cells:
        logger.info(f"Tabellen mit höchstens {table_max_cells} Zellen werden aufgelöst.")

    return table_max_cells, directory_info, resolved_custom_rules, system_prompt, chunks, single


def _strip_hallucinated_page_numbers(
    standardised_content: str | None,
    raw_markdown: str,
    directory_info: dict[str, Any] | None,
) -> str | None:
    """Removes any ``((n))`` page numbers invented by Gemma that do not exist in ``raw_markdown``.

    Args:
        standardised_content: Raw LLM or fallback standardised Markdown.
        raw_markdown: Stage 1 raw extracted Markdown.
        directory_info: Optional detected TOC/directory metadata.

    Returns:
        Cleaned Markdown string with hallucinated page markers removed.
    """
    if not standardised_content:
        return standardised_content

    raw_page_numbers: set[str] = set()
    for m in re.finditer(r"\(\((\d+)\)\)", raw_markdown):
        raw_page_numbers.add(m.group(1))
    if directory_info and directory_info.get("page_numbers"):
        for p_num in directory_info["page_numbers"]:
            raw_page_numbers.add(str(p_num))
    for line in raw_markdown.splitlines():
        line_clean = re.sub(
            r"</?(?:table|tr|td|tbody|p|div|span|b|i|strong|em)\b[^>]*>", "", line
        ).strip()
        page_match = re.match(
            r"^[\(\s\[\-\#]*(?:Seite|Se)?\s*(\d+)[\)\s\]\-\#]*$",
            line_clean,
            re.IGNORECASE,
        )
        if page_match:
            raw_page_numbers.add(page_match.group(1))

    if raw_page_numbers:
        cleaned_lines = []
        for line in standardised_content.splitlines():
            stripped = line.strip()
            m = re.match(r"^\(\((\d+)\)\)$", stripped)
            if m:
                page_num = m.group(1)
                if page_num not in raw_page_numbers:
                    logger.info(f"Removing hallucinated/added page index: (({page_num}))")
                    continue
            cleaned_lines.append(line)
        standardised_content = "\n".join(cleaned_lines)
        standardised_content = re.sub(r"\n{3,}", "\n\n", standardised_content)

    return standardised_content


def standardise_markdown(
    raw_markdown: str,
    ruleset_key: str = "uebertragungsregeln_09_2025",
    image_paths: list[str] | None = None,
    task_id: str | None = None,
    on_token_callback: Callable[[str], None] | None = None,
    physical_start_page: int = 1,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    table_max_cells: int | None = None,
    allow_fallback: bool | None = None,
    directory_info: dict[str, Any] | None = None,
    custom_rules: str | None = None,
) -> str:
    """Applies FIBS 09/2025 translation rules to extracted Markdown using Gemma 4.

    Standardises the document in page-bounded chunks with neighbor-page context,
    automatically retrying once on server failure and applying deterministic
    structural post-processing at the end.

    Args:
        raw_markdown: Stage 1 extracted Markdown string (with ``<Bild>`` tags).
        ruleset_key: Identifier of the FIBS ruleset to apply.
        image_paths: Optional list of extracted image paths (unused in text-only stage).
        task_id: Optional conversion task ID for custom rules and directory metadata.
        on_token_callback: Optional callback invoked for each streamed LLM token.
        physical_start_page: 1-based physical start page number.
        on_progress: Optional callback invoked on chunk ``plan``, ``start``, ``retry``, or ``fallback``.
        table_max_cells: Optional cell threshold for unrolling small tables.
        allow_fallback: Whether to permit the deterministic fallback if no LLM is available.
        directory_info: Optional pre-loaded directory/TOC metadata dictionary.
        custom_rules: Optional book-specific custom rules string.

    Returns:
        Standardised and post-processed E-Buch Markdown string.

    Raises:
        StandardisationError: If LLM inference fails and fallback is not permitted.
        StandardisationAborted: If aborted by a callback.
    """
    del image_paths, physical_start_page
    table_max_cells, directory_info, resolved_custom_rules, system_prompt, chunks, single = (
        _prepare_standardisation_plan(
            raw_markdown,
            ruleset_key,
            task_id,
            table_max_cells,
            directory_info,
            on_progress,
            custom_rules=custom_rules,
        )
    )
    total = len(chunks)

    standardised_content: str | None = None
    client = start_rapid_mlx()
    backend: str | None = "rapid-mlx" if client is not None else "cuda"
    outputs: list[str] = []

    for chunk in chunks:
        label = chunk.label
        _emit_progress(
            on_progress,
            event="start",
            index=chunk.index,
            total=total,
            label=label,
            message=f"Gemma: Abschnitt {chunk.index}/{total} ({label})",
        )
        if single:
            hint = _table_hint(chunk.text, table_max_cells)
            user_content = f"{hint}\n\n{raw_markdown}" if hint else raw_markdown
        else:
            user_content = build_chunk_user_message(chunk, total, table_max_cells)

        attempt = 0
        while True:
            attempt += 1
            try:
                if backend == "rapid-mlx":
                    logger.info(
                        f"=== CALLING GEMMA (LOCAL via rapid-mlx, TEXT-ONLY STREAMING) – "
                        f"Abschnitt {chunk.index}/{total} ({label}), ~{chunk.estimated_request_tokens} Tokens ==="
                    )
                    out = _stream_chat_completion(
                        client,
                        system_prompt,
                        user_content,
                        chunk.max_output_tokens,
                        on_token_callback,
                    )
                else:
                    out = _run_torch_cuda_llm(
                        system_prompt,
                        user_content,
                        max_tokens=chunk.max_output_tokens,
                        on_token=on_token_callback,
                    )
                    if out is None and not outputs and attempt == 1:
                        backend = None
                        break
                out = _clean_chunk_output(out or "")
                if not single:
                    out = _trim_to_own_pages(out, chunk)
                if not out.strip():
                    raise StandardisationError("leere Antwort von Gemma")
                outputs.append(out)
                break
            except StandardisationAborted:
                raise
            except Exception as e:
                err = (
                    f"{type(e).__name__}: {e}"
                    if not isinstance(e, StandardisationError)
                    else str(e)
                )
                if attempt >= 2:
                    raise StandardisationError(
                        f"Gemma-Standardisierung fehlgeschlagen in Abschnitt {chunk.index}/{total} ({label}): {err}"
                    ) from e
                logger.warning(
                    f"Gemma-Fehler in Abschnitt {chunk.index}/{total} ({label}): {err} – neuer Versuch."
                )
                _emit_progress(
                    on_progress,
                    event="retry",
                    index=chunk.index,
                    total=total,
                    label=label,
                    message=(
                        f"Gemma-Fehler in Abschnitt {chunk.index}/{total} ({label}): {err} – "
                        f"Modellserver wird neu gestartet, zweiter Versuch …"
                    ),
                )
                if backend == "rapid-mlx":
                    close_engine()
                    client = start_rapid_mlx()
                    if client is None:
                        raise StandardisationError(
                            f"Gemma-Standardisierung fehlgeschlagen in Abschnitt {chunk.index}/{total} ({label}): "
                            f"Modellserver konnte nicht neu gestartet werden ({err})"
                        ) from e

        if backend is None:
            break
        if on_token_callback and chunk.index < total:
            try:
                on_token_callback("\n\n")
            except StandardisationAborted:
                raise
            except Exception:
                pass

    if backend is not None:
        standardised_content = "\n\n".join(outputs)
        if backend == "rapid-mlx":
            reset_idle_timer()
    else:
        if not _rule_based_fallback_allowed(allow_fallback):
            raise StandardisationError(
                "Kein lokales Sprachmodell verfügbar (rapid-mlx/Gemma konnte nicht gestartet werden). "
                "Die regelbasierte Ersatzlösung wird nicht automatisch verwendet."
            )
        logger.info("=== RUNNING LOCAL RULE-BASED FALLBACK (NO GEMMA CALL) ===")
        _emit_progress(
            on_progress,
            event="fallback",
            index=0,
            total=total,
            label="",
            message="Kein Sprachmodell verfügbar – regelbasierte Ersatzlösung (explizit erlaubt).",
        )
        standardised_content = standardise_markdown_fallback(raw_markdown, ruleset_key)

    standardised_content = _strip_hallucinated_page_numbers(
        standardised_content, raw_markdown, directory_info
    )
    return post_process_structure(
        standardised_content or "",
        raw_markdown=raw_markdown,
        directory_info=directory_info,
        custom_rules=resolved_custom_rules,
    )


_DEFAULT_STANDARDISE_MARKDOWN = standardise_markdown


async def standardise_markdown_async(
    raw_markdown: str,
    ruleset_key: str = "uebertragungsregeln_09_2025",
    image_paths: list[str] | None = None,
    task_id: str | None = None,
    on_token_callback: Callable[[str], None] | None = None,
    physical_start_page: int = 1,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    table_max_cells: int | None = None,
    allow_fallback: bool | None = None,
    directory_info: dict[str, Any] | None = None,
    custom_rules: str | None = None,
) -> str:
    """Asynchronous counterpart to ``standardise_markdown`` using ``AsyncOpenAI``.

    Streams tokens natively on the asyncio event loop while offloading CPU-heavy
    fallback and post-processing steps via ``asyncio.to_thread``.

    Args:
        raw_markdown: Stage 1 extracted Markdown string.
        ruleset_key: Identifier of the FIBS ruleset to apply.
        image_paths: Optional list of extracted image paths.
        task_id: Optional conversion task ID.
        on_token_callback: Optional callback invoked for each streamed LLM token.
        physical_start_page: 1-based physical start page number.
        on_progress: Optional progress callback.
        table_max_cells: Optional cell threshold for unrolling small tables.
        allow_fallback: Whether to permit the deterministic fallback if no LLM is available.
        directory_info: Optional pre-loaded directory/TOC metadata dictionary.
        custom_rules: Optional book-specific custom rules string.

    Returns:
        Standardised and post-processed E-Buch Markdown string.
    """
    if standardise_markdown is not _DEFAULT_STANDARDISE_MARKDOWN:
        res = standardise_markdown(
            raw_markdown=raw_markdown,
            ruleset_key=ruleset_key,
            image_paths=image_paths,
            task_id=task_id,
            on_token_callback=on_token_callback,
            physical_start_page=physical_start_page,
            on_progress=on_progress,
            table_max_cells=table_max_cells,
            allow_fallback=allow_fallback,
            directory_info=directory_info,
        )
        if inspect.isawaitable(res):
            res = await res
        return res

    (
        table_max_cells,
        directory_info,
        resolved_custom_rules,
        system_prompt,
        chunks,
        single,
    ) = await asyncio.to_thread(
        _prepare_standardisation_plan,
        raw_markdown,
        ruleset_key,
        task_id,
        table_max_cells,
        directory_info,
        on_progress,
        custom_rules,
    )
    total = len(chunks)

    standardised_content: str | None = None
    client = await start_rapid_mlx_async()
    backend: str | None = "rapid-mlx" if client is not None else "cuda"
    outputs: list[str] = []

    for chunk in chunks:
        label = chunk.label
        _emit_progress(
            on_progress,
            event="start",
            index=chunk.index,
            total=total,
            label=label,
            message=f"Gemma: Abschnitt {chunk.index}/{total} ({label})",
        )
        if single:
            hint = _table_hint(chunk.text, table_max_cells)
            user_content = f"{hint}\n\n{raw_markdown}" if hint else raw_markdown
        else:
            user_content = build_chunk_user_message(chunk, total, table_max_cells)

        attempt = 0
        while True:
            attempt += 1
            try:
                if backend == "rapid-mlx":
                    logger.info(
                        f"=== CALLING GEMMA (LOCAL via rapid-mlx ASYNC STREAMING) – "
                        f"Abschnitt {chunk.index}/{total} ({label}), ~{chunk.estimated_request_tokens} Tokens ==="
                    )
                    out = await _stream_chat_completion_async(
                        client,
                        system_prompt,
                        user_content,
                        chunk.max_output_tokens,
                        on_token_callback,
                    )
                else:
                    out = await asyncio.to_thread(
                        _run_torch_cuda_llm,
                        system_prompt,
                        user_content,
                        chunk.max_output_tokens,
                        on_token_callback,
                    )
                    if out is None and not outputs and attempt == 1:
                        backend = None
                        break
                out = _clean_chunk_output(out or "")
                if not single:
                    out = _trim_to_own_pages(out, chunk)
                if not out.strip():
                    raise StandardisationError("leere Antwort von Gemma")
                outputs.append(out)
                break
            except StandardisationAborted:
                raise
            except Exception as e:
                err = (
                    f"{type(e).__name__}: {e}"
                    if not isinstance(e, StandardisationError)
                    else str(e)
                )
                if attempt >= 2:
                    raise StandardisationError(
                        f"Gemma-Standardisierung fehlgeschlagen in Abschnitt {chunk.index}/{total} ({label}): {err}"
                    ) from e
                logger.warning(
                    f"Gemma-Fehler in Abschnitt {chunk.index}/{total} ({label}): {err} – neuer Versuch."
                )
                _emit_progress(
                    on_progress,
                    event="retry",
                    index=chunk.index,
                    total=total,
                    label=label,
                    message=(
                        f"Gemma-Fehler in Abschnitt {chunk.index}/{total} ({label}): {err} – "
                        f"Modellserver wird neu gestartet, zweiter Versuch …"
                    ),
                )
                if backend == "rapid-mlx":
                    await asyncio.to_thread(close_engine)
                    client = await start_rapid_mlx_async()
                    if client is None:
                        raise StandardisationError(
                            f"Gemma-Standardisierung fehlgeschlagen in Abschnitt {chunk.index}/{total} ({label}): "
                            f"Modellserver konnte nicht neu gestartet werden ({err})"
                        ) from e

        if backend is None:
            break
        if on_token_callback and chunk.index < total:
            try:
                on_token_callback("\n\n")
            except StandardisationAborted:
                raise
            except Exception:
                pass

    if backend is not None:
        standardised_content = "\n\n".join(outputs)
        if backend == "rapid-mlx":
            reset_idle_timer()
    else:
        if not _rule_based_fallback_allowed(allow_fallback):
            raise StandardisationError(
                "Kein lokales Sprachmodell verfügbar (rapid-mlx/Gemma konnte nicht gestartet werden). "
                "Die regelbasierte Ersatzlösung wird nicht automatisch verwendet."
            )
        logger.info("=== RUNNING LOCAL RULE-BASED FALLBACK (NO GEMMA CALL) ===")
        _emit_progress(
            on_progress,
            event="fallback",
            index=0,
            total=total,
            label="",
            message="Kein Sprachmodell verfügbar – regelbasierte Ersatzlösung (explizit erlaubt).",
        )
        standardised_content = await asyncio.to_thread(
            standardise_markdown_fallback, raw_markdown, ruleset_key
        )

    standardised_content = _strip_hallucinated_page_numbers(
        standardised_content, raw_markdown, directory_info
    )
    return await asyncio.to_thread(
        post_process_structure,
        standardised_content or "",
        raw_markdown=raw_markdown,
        directory_info=directory_info,
        custom_rules=resolved_custom_rules,
    )


def _prepare_optimization_prompts(
    raw_markdown: str,
    current_markdown: str,
    feedback: str,
    ruleset_key: str,
    task_id: str | None,
) -> tuple[str, str]:
    """Builds the system and user prompts for interactive Markdown optimization.

    Args:
        raw_markdown: Original Stage 1 extracted Markdown.
        current_markdown: Current standardised Markdown being refined.
        feedback: User feedback instructions.
        ruleset_key: Active FIBS ruleset identifier.
        task_id: Optional conversion task ID.

    Returns:
        Tuple of ``(system_instruction, user_prompt)``.
    """
    rules_instruction = SYSTEM_PROMPTS.get(
        ruleset_key, SYSTEM_PROMPTS["uebertragungsregeln_09_2025"]
    )
    if task_id:
        custom_rules_path = os.path.join(BASE_DIR, "assets", "output", task_id, "custom_ruleset.txt")
        if os.path.exists(custom_rules_path):
            try:
                with open(custom_rules_path, encoding="utf-8") as f:
                    custom_rules = f.read().strip()
                if custom_rules:
                    rules_instruction = (
                        f"{rules_instruction}\n\n{build_custom_rules_block(custom_rules)}"
                    )
            except Exception as e:
                logger.error(f"Failed to read custom ruleset for optimize: {e}")

    user_prompt = build_optimize_user_prompt(
        rules_instruction=rules_instruction,
        raw_markdown=raw_markdown,
        current_markdown=current_markdown,
        feedback=feedback,
    )
    return OPTIMIZE_SYSTEM_INSTRUCTION, user_prompt


def optimize_markdown(
    raw_markdown: str,
    current_markdown: str,
    feedback: str,
    ruleset_key: str = "uebertragungsregeln_09_2025",
    image_paths: list[str] | None = None,
    task_id: str | None = None,
    on_token_callback: Callable[[str], None] | None = None,
) -> str:
    """Refines and optimizes standardised Markdown based on interactive user feedback.

    Args:
        raw_markdown: Original Stage 1 extracted Markdown.
        current_markdown: Current standardised Markdown document.
        feedback: User feedback prompt describing desired corrections.
        ruleset_key: Active FIBS ruleset identifier.
        image_paths: Optional list of image paths.
        task_id: Optional conversion task ID.
        on_token_callback: Optional callback invoked for each streamed LLM token.

    Returns:
        Optimized E-Buch Markdown string.
    """
    del image_paths
    if os.environ.get("E2E_MOCK") == "true":
        logger.info("E2E_MOCK active: bypassing Gemma optimize_markdown, calling fallback.")
        return optimize_markdown_fallback(current_markdown, feedback)

    system_instruction, user_prompt = _prepare_optimization_prompts(
        raw_markdown, current_markdown, feedback, ruleset_key, task_id
    )

    client = start_rapid_mlx()
    if client is not None:
        try:
            logger.info(
                "=== CALLING GEMMA FOR OPTIMIZATION (LOCAL via rapid-mlx, TEXT-ONLY STREAMING) ==="
            )
            raw_gen = _stream_chat_completion(
                client, system_instruction, user_prompt, 8192, on_token_callback
            )
            reset_idle_timer()
            if raw_gen:
                res_clean = re.sub(r"^\[truncated[^\]]*\]\s*", "", raw_gen)
                return res_clean.strip()
        except Exception as e:
            logger.error(f"rapid-mlx text-only optimization failed: {e}.")

    torch_opt = _run_torch_cuda_llm(
        system_instruction,
        user_prompt,
        max_tokens=8192,
        on_token=on_token_callback,
    )
    if torch_opt:
        res_clean = re.sub(r"^\[truncated[^\]]*\]\s*", "", torch_opt)
        return res_clean.strip()

    logger.info("=== RUNNING LOCAL FALLBACK FOR OPTIMIZATION (NO LLM AVAILABLE OR FAILED) ===")
    return optimize_markdown_fallback(current_markdown, feedback)


_DEFAULT_OPTIMIZE_MARKDOWN = optimize_markdown


async def optimize_markdown_async(
    raw_markdown: str,
    current_markdown: str,
    feedback: str,
    ruleset_key: str = "uebertragungsregeln_09_2025",
    image_paths: list[str] | None = None,
    task_id: str | None = None,
    on_token_callback: Callable[[str], None] | None = None,
) -> str:
    """Asynchronous counterpart to ``optimize_markdown`` using ``AsyncOpenAI`` streaming.

    Args:
        raw_markdown: Original Stage 1 extracted Markdown.
        current_markdown: Current standardised Markdown document.
        feedback: User feedback prompt describing desired corrections.
        ruleset_key: Active FIBS ruleset identifier.
        image_paths: Optional list of image paths.
        task_id: Optional conversion task ID.
        on_token_callback: Optional callback invoked for each streamed LLM token.

    Returns:
        Optimized E-Buch Markdown string.
    """
    if optimize_markdown is not _DEFAULT_OPTIMIZE_MARKDOWN:
        res = optimize_markdown(
            raw_markdown=raw_markdown,
            current_markdown=current_markdown,
            feedback=feedback,
            ruleset_key=ruleset_key,
            image_paths=image_paths,
            task_id=task_id,
            on_token_callback=on_token_callback,
        )
        if inspect.isawaitable(res):
            res = await res
        return res

    if os.environ.get("E2E_MOCK") == "true":
        logger.info("E2E_MOCK active: bypassing Gemma optimize_markdown, calling fallback.")
        return await asyncio.to_thread(optimize_markdown_fallback, current_markdown, feedback)

    system_instruction, user_prompt = await asyncio.to_thread(
        _prepare_optimization_prompts,
        raw_markdown,
        current_markdown,
        feedback,
        ruleset_key,
        task_id,
    )

    client = await start_rapid_mlx_async()
    if client is not None:
        try:
            logger.info(
                "=== CALLING GEMMA FOR OPTIMIZATION (LOCAL via rapid-mlx ASYNC STREAMING) ==="
            )
            raw_gen = await _stream_chat_completion_async(
                client,
                system_instruction,
                user_prompt,
                8192,
                on_token_callback,
            )
            reset_idle_timer()
            if raw_gen:
                res_clean = re.sub(r"^\[truncated[^\]]*\]\s*", "", raw_gen)
                return res_clean.strip()
        except Exception as e:
            logger.error(f"rapid-mlx async text-only optimization failed: {e}.")

    torch_opt = await asyncio.to_thread(
        _run_torch_cuda_llm,
        system_instruction,
        user_prompt,
        8192,
        on_token_callback,
    )
    if torch_opt:
        res_clean = re.sub(r"^\[truncated[^\]]*\]\s*", "", torch_opt)
        return res_clean.strip()

    logger.info("=== RUNNING LOCAL FALLBACK FOR OPTIMIZATION (NO LLM AVAILABLE OR FAILED) ===")
    return await asyncio.to_thread(optimize_markdown_fallback, current_markdown, feedback)


# ---------------------------------------------------------------------------
# Offline VLM Image Description Helpers
# ---------------------------------------------------------------------------


def describe_image(image_path: str, page_context: str = "") -> VlmDescriptionResult | None:
    """Generates a descriptive FIBS accessibility caption for a single image using ``mlx_vlm``.

    Note: The production extraction pipeline invokes ``vlm_describer.py`` in an
    isolated subprocess; this helper is retained for direct library callers and
    unit tests.

    Args:
        image_path: Filesystem path to the extracted image file.
        page_context: Optional read-only surrounding page text for orientation.

    Returns:
        Parsed ``VlmDescriptionResult`` model, or ``None`` on failure.
    """
    from backend.services.vlm_describer import parse_vlm_description

    if os.environ.get("E2E_MOCK") == "true":
        return parse_vlm_description(
            "Versuchsaufbau eines optischen Experiments mit Prismen zur Lichtbrechung."
        )

    global _MLX_VLM_MODEL, _MLX_VLM_PROCESSOR
    if not os.path.exists(image_path):
        logger.warning(f"Image not found for description: {image_path}")
        return None

    try:
        m_path = get_model_path()
        if _MLX_VLM_MODEL is None or _MLX_VLM_PROCESSOR is None:
            logger.info(f"Loading mlx_vlm model for offline VLM generation from {m_path}...")
            from mlx_vlm import load

            _MLX_VLM_MODEL, _MLX_VLM_PROCESSOR = load(m_path)

        from mlx_vlm import generate
        from mlx_vlm.prompt_utils import apply_chat_template
        from mlx_vlm.utils import load_config

        prompt = build_vlm_prompt(page_context) if page_context else VLM_IMAGE_PROMPT
        config = load_config(m_path)
        formatted_prompt = apply_chat_template(_MLX_VLM_PROCESSOR, config, prompt, num_images=1)

        desc = generate(
            _MLX_VLM_MODEL,
            _MLX_VLM_PROCESSOR,
            formatted_prompt,
            [image_path],
            max_tokens=2048,
            repetition_penalty=1.1,
            repetition_context_size=64,
            verbose=False,
        )
        desc_text = desc.text if hasattr(desc, "text") else str(desc)
        if desc_text and desc_text.strip():
            return parse_vlm_description(desc_text.strip())
    except Exception as e:
        logger.error(f"Failed to generate offline image description for {image_path}: {e}")
        _MLX_VLM_MODEL = None
        _MLX_VLM_PROCESSOR = None
    return None


def describe_markdown_images(
    markdown_content: str,
    image_dir: str,
    skip_descriptions: bool = False,
) -> str:
    """Replaces Markdown image references in ``markdown_content`` with FIBS ``<Bild>`` blocks.

    Args:
        markdown_content: Extracted Markdown containing ``![](images/...)`` links.
        image_dir: Directory containing the extracted image files.
        skip_descriptions: If True, formats ``<Bild>`` tags from alt text without running VLM.

    Returns:
        Markdown string with image links converted to multi-line ``<Bild>`` blocks.
    """
    if not image_dir or not os.path.exists(image_dir):
        logger.warning(f"Image directory not found: {image_dir}")
        return markdown_content

    markdown_content = re.sub(
        r"<details\b[^>]*>.*?</details>", "", markdown_content, flags=re.DOTALL
    )
    pattern = r"(?s)!\[(.*?)\]\((?:images/)?([^)]+)\)"
    wrapped_pattern = r"(?s)<Bild>\s*!\[(.*?)\]\((?:images/)?([^)]+)\)\s*</Bild>"

    def make_replacer(source: str) -> Callable[[re.Match[str]], str]:
        def replacer(match: re.Match[str]) -> str:
            alt_text = match.group(1)
            filename = os.path.basename(match.group(2))
            image_path = os.path.join(image_dir, filename)

            if skip_descriptions:
                return format_bild_tag("", alt_text, has_text=False)

            vlm_res = describe_image(image_path)
            if vlm_res:
                has_caption = has_caption_context(source, match.start(), match.end(), alt_text)
                return bild_tag_from_vlm(vlm_res, has_caption=has_caption, alt_text=alt_text)
            return format_bild_tag("", alt_text, has_text=False)

        return replacer

    output = re.sub(wrapped_pattern, make_replacer(markdown_content), markdown_content)
    output = re.sub(pattern, make_replacer(output), output)
    output = re.sub(r"\n{3,}", "\n\n", output)

    if not skip_descriptions:
        release_vlm_model()

    return output


def release_vlm_model() -> None:
    """Releases in-process ``mlx_vlm`` model references and runs garbage collection."""
    global _MLX_VLM_MODEL, _MLX_VLM_PROCESSOR
    if _MLX_VLM_MODEL is not None:
        logger.info("Releasing offline mlx_vlm model memory...")
        _MLX_VLM_MODEL = None
        _MLX_VLM_PROCESSOR = None
        gc.collect()
        logger.info("VLM model memory released.")
