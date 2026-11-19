"""Unit and API stream tests for workload-aware realistic pipeline progress."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

import backend.main as main_module
from backend.services.models import DomainModel, StageProgressBudget
from backend.services.progress_service import (
    compute_extraction_budget,
    compute_gemma_stream_percent,
    compute_post_extraction_budget,
    compute_vlm_image_percent,
    count_pdf_embedded_images,
)


def test_stage_progress_budget_model_and_docstrings() -> None:
    """Verify StageProgressBudget inherits DomainModel, validates bounds, and exposes field docs."""
    assert issubclass(StageProgressBudget, DomainModel)
    assert StageProgressBudget.model_config.get("use_attribute_docstrings") is True
    assert StageProgressBudget.__doc__ and "Attributes:" not in StageProgressBudget.__doc__

    for field_name, field in StageProgressBudget.model_fields.items():
        assert isinstance(field.description, str) and field.description.strip(), (
            f"Missing attribute docstring on StageProgressBudget.{field_name}"
        )

    budget = StageProgressBudget(
        extraction_end_percent=8,
        vlm_start_percent=8,
        vlm_end_percent=65,
        gemma_start_percent=65,
    )
    assert budget.gemma_end_percent == 99

    with pytest.raises(ValidationError):
        StageProgressBudget(
            extraction_end_percent=105,
            vlm_start_percent=5,
            vlm_end_percent=50,
            gemma_start_percent=50,
        )


def test_count_pdf_embedded_images_filters_tiny_and_non_pdf(tmp_path: Path) -> None:
    """Verify count_pdf_embedded_images handles missing/non-PDF files and counts valid PDF images."""
    assert count_pdf_embedded_images("") == 0
    assert count_pdf_embedded_images(str(tmp_path / "missing.pdf")) == 0

    txt_file = tmp_path / "notes.txt"
    txt_file.write_text("Kein PDF", encoding="utf-8")
    assert count_pdf_embedded_images(str(txt_file)) == 0

    # Save a multi-page raster PDF via Pillow (each page >= 36x36 pt embeds 1 FPDF_PAGEOBJ_IMAGE)
    pdf_path = tmp_path / "sample_imgs.pdf"
    img1 = Image.new("RGB", (200, 200), color=(240, 240, 240))
    img2 = Image.new("RGB", (200, 200), color=(200, 220, 240))
    img1.save(str(pdf_path), "PDF", resolution=72.0, save_all=True, append_images=[img2])
    assert count_pdf_embedded_images(str(pdf_path)) == 2

    # Tiny PDF (< 36x36 pt) should be ignored as icon/bullet noise
    tiny_pdf = tmp_path / "tiny.pdf"
    tiny_img = Image.new("RGB", (20, 20), color=(0, 0, 0))
    tiny_img.save(str(tiny_pdf), "PDF", resolution=72.0)
    assert count_pdf_embedded_images(str(tiny_pdf)) == 0


def test_compute_extraction_budget_workload_proportionality() -> None:
    """Verify Stage 1 extraction ceiling scales realistically with engine speed and image count."""
    docling_heavy = compute_extraction_budget(
        "docling", page_count=25, estimated_images=47, describe_images=True
    )
    lighton_heavy = compute_extraction_budget(
        "lightonocr", page_count=25, estimated_images=47, describe_images=True
    )
    infinity_heavy = compute_extraction_budget(
        "infinity", page_count=25, estimated_images=47, describe_images=True
    )

    # Docling (~34s) vs ~61 min VLM+Gemma -> clamped to 5% (<= 10%)
    assert 5 <= docling_heavy.extraction_end_percent <= 10
    assert docling_heavy.vlm_end_percent > 60
    assert docling_heavy.gemma_start_percent == docling_heavy.vlm_end_percent
    assert docling_heavy.gemma_end_percent == 99

    # Infinity (~31 min) vs ~61 min VLM+Gemma -> ~34%
    assert 30 <= infinity_heavy.extraction_end_percent <= 40
    assert (
        docling_heavy.extraction_end_percent
        < lighton_heavy.extraction_end_percent
        < infinity_heavy.extraction_end_percent
    )

    # Disabling VLM or having 0 images collapses Stage 2 span to zero
    no_vlm = compute_extraction_budget(
        "docling", page_count=25, estimated_images=47, describe_images=False
    )
    assert no_vlm.vlm_start_percent == no_vlm.vlm_end_percent == no_vlm.gemma_start_percent

    zero_imgs = compute_extraction_budget(
        "lightonocr", page_count=10, estimated_images=0, describe_images=True
    )
    assert zero_imgs.vlm_start_percent == zero_imgs.vlm_end_percent == zero_imgs.gemma_start_percent

    non_pdf = compute_extraction_budget(
        "docling", page_count=5, estimated_images=0, describe_images=True, is_pdf=False
    )
    assert non_pdf.extraction_end_percent == 5


def test_compute_post_extraction_budget_splits_and_cache_awareness() -> None:
    """Verify post-extraction budget scales across 0, 5, 47, and cached VLM images."""
    b_zero = compute_post_extraction_budget(
        start_percent=5,
        uncached_images=0,
        cached_images=0,
        describe_images=True,
        total_chunks=14,
    )
    assert (b_zero.vlm_start_percent, b_zero.vlm_end_percent, b_zero.gemma_start_percent) == (
        5,
        5,
        5,
    )

    b_five = compute_post_extraction_budget(
        start_percent=5,
        uncached_images=5,
        cached_images=0,
        describe_images=True,
        total_chunks=14,
    )
    b_fortyseven = compute_post_extraction_budget(
        start_percent=5,
        uncached_images=47,
        cached_images=0,
        describe_images=True,
        total_chunks=14,
    )
    b_cached = compute_post_extraction_budget(
        start_percent=5,
        uncached_images=0,
        cached_images=47,
        describe_images=True,
        total_chunks=14,
    )

    assert 5 < b_cached.vlm_end_percent < b_five.vlm_end_percent < b_fortyseven.vlm_end_percent
    assert b_fortyseven.gemma_end_percent - b_fortyseven.gemma_start_percent >= 4


def test_vlm_and_gemma_percent_strict_monotonicity() -> None:
    """Verify VLM per-image and Gemma intra-chunk token percentages increase monotonically <= 99%."""
    budget = compute_post_extraction_budget(
        start_percent=5,
        uncached_images=47,
        cached_images=0,
        describe_images=True,
        total_chunks=14,
    )

    # Model load finishing at image 1 advances at least 1% past vlm_start_percent
    p_first = compute_vlm_image_percent(budget, 1, 47)
    assert p_first >= budget.vlm_start_percent + 1

    vlm_seq = [compute_vlm_image_percent(budget, i, 47) for i in range(1, 48)]
    vlm_seq.append(compute_vlm_image_percent(budget, 47, 47, finished=True))
    assert vlm_seq == sorted(vlm_seq)
    assert vlm_seq[-1] == budget.vlm_end_percent

    # Gemma streaming across all 14 chunks and intra-chunk char counts
    gemma_seq: list[int] = []
    for chunk_idx in range(1, 15):
        for chars in (0, 200, 800, 1600, 2500, 4500):
            pct = compute_gemma_stream_percent(
                budget,
                chunk_index=chunk_idx,
                total_chunks=14,
                streamed_chars_in_chunk=chars,
                expected_chars_in_chunk=2200,
            )
            assert budget.gemma_start_percent <= pct <= 99
            gemma_seq.append(pct)

    assert gemma_seq == sorted(gemma_seq)
    assert gemma_seq[-1] > gemma_seq[0]


def test_end_to_end_extract_and_standardise_monotonic_progress_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify /api/extract + /api/standardise emit monotonic 0->100% with unit transitions."""
    monkeypatch.setenv("E2E_MOCK", "true")
    upload_dir = tmp_path / "uploads"
    output_dir = tmp_path / "output"
    upload_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(main_module, "UPLOAD_DIR", str(upload_dir))
    monkeypatch.setattr(main_module, "OUTPUT_DIR", str(output_dir))

    pdf_file = tmp_path / "test_educational.pdf"
    Image.new("RGB", (200, 200), color=(255, 255, 255)).save(
        str(pdf_file), "PDF", resolution=72.0
    )

    client = TestClient(main_module.app)
    with open(pdf_file, "rb") as f:
        up_res = client.post(
            "/api/upload", files={"file": ("test_educational.pdf", f, "application/pdf")}
        )
    assert up_res.status_code == 200
    task_id = up_res.json()["task_id"]

    # Stage 1: /api/extract with docling + describe_images=true
    ext_res = client.post(
        "/api/extract",
        data={"task_id": task_id, "engine": "docling", "describe_images": "true"},
    )
    assert ext_res.status_code == 200
    ext_events = [json.loads(line) for line in ext_res.text.splitlines() if line.strip()]
    ext_progress = [e for e in ext_events if e.get("status") == "progress"]
    ext_completed = next(e for e in ext_events if e.get("status") == "completed")

    assert ext_progress, "Expected Stage 1 progress events"
    assert all(e.get("unit") == "Seiten" for e in ext_progress)
    ext_percents = [int(e["percent"]) for e in ext_progress]
    assert ext_percents == sorted(ext_percents)
    assert ext_percents[-1] <= 20  # Never jumps to legacy 90% or 100%!
    assert ext_completed["progress_percent"] == ext_percents[-1]

    # Create two dummy extracted images so Stage 2 (Bilder) and Stage 3 (Abschnitte) both run
    img_dir = output_dir / task_id / "auto" / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    for name in ("fig1.png", "fig2.png"):
        Image.new("RGB", (120, 80), color=(180, 200, 220)).save(str(img_dir / name))

    multi_page_md = (
        "((1))\n\n# Kapitel 1\n\nText A.\n\n![Abb. 1](images/fig1.png)\n\n"
        "((2))\n\n## Abschnitt 1.1\n\nText B.\n\n![Abb. 2](images/fig2.png)\n\n"
        "((3))\n\n## Abschnitt 1.2\n\nText C mit Formel $a + b = c$.\n"
    )

    # Stream synthetic multi-chunk Gemma progress + tokens to verify smooth intra-chunk progression
    async def fake_standardise_async(
        markdown: str,
        ruleset_key: str,
        image_paths,
        t_id: str,
        on_token,
        *,
        on_progress=None,
        directory_info=None,
        neighbor_context=None,
    ) -> str:
        for idx in (1, 2):
            if on_progress:
                on_progress(
                    {
                        "event": "start",
                        "index": idx,
                        "total": 2,
                        "label": f"Seite {idx}",
                        "message": f"Gemma: Abschnitt {idx}/2 (Seite {idx})",
                    }
                )
            for _ in range(5):
                on_token("Standardisierter Absatz mit Inhalt fuer Abschnitt.\n")
        return "((1))\n\n# Kapitel 1\n\nStandardisierter Text.\n"

    monkeypatch.setattr(main_module, "standardise_markdown_async", fake_standardise_async)

    std_res = client.post(
        "/api/standardise",
        json={
            "task_id": task_id,
            "markdown": multi_page_md,
            "ruleset": "uebertragungsregeln_09_2025",
            "describe_images": True,
        },
    )
    assert std_res.status_code == 200
    std_events = [json.loads(line) for line in std_res.text.splitlines() if line.strip()]
    std_progress = [e for e in std_events if e.get("status") == "progress"]
    std_percents = [int(e["percent"]) for e in std_progress]

    combined = ext_percents + std_percents
    assert combined == sorted(combined), f"Non-monotonic pipeline progress: {combined}"
    assert combined[-1] == 100
    assert 90 not in ext_percents

    units_seen = [e.get("unit") for e in ext_progress + std_progress if e.get("unit")]
    assert "Seiten" in units_seen
    assert "Bilder" in units_seen
    assert "Abschnitte" in units_seen
    assert units_seen.index("Seiten") < units_seen.index("Bilder") < units_seen.index("Abschnitte")

    # Verify Gemma emitted multiple distinct percentage values (no flat 98% plateau!)
    gemma_percents = {int(e["percent"]) for e in std_progress if e.get("unit") == "Abschnitte"}
    assert len(gemma_percents) >= 3, f"Expected smooth Gemma progression, got {gemma_percents}"

    # Re-running /api/standardise on an already completed (100%) task resets from < 100% cleanly
    std_rerun = client.post(
        "/api/standardise",
        json={
            "task_id": task_id,
            "markdown": multi_page_md,
            "ruleset": "uebertragungsregeln_09_2025",
            "describe_images": False,
        },
    )
    assert std_rerun.status_code == 200
    rerun_progress = [
        int(json.loads(line)["percent"])
        for line in std_rerun.text.splitlines()
        if line.strip() and json.loads(line).get("status") == "progress"
    ]
    assert rerun_progress[0] < 50
    assert rerun_progress == sorted(rerun_progress)
    assert rerun_progress[-1] == 100


def test_run_background_extraction_subprocess_stdout_progress_scaling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify real subprocess stdout parsing skips Loading weights and scales to extraction budget."""
    import asyncio
    from backend.services import extraction_service

    monkeypatch.delenv("E2E_MOCK", raising=False)

    pdf_file = tmp_path / "sample.pdf"
    imgs = [Image.new("RGB", (200, 200), color=(250, 250, 250)) for _ in range(4)]
    imgs[0].save(str(pdf_file), "PDF", resolution=72.0, save_all=True, append_images=imgs[1:])

    out_root = tmp_path / "out_task"
    auto_dir = out_root / "sample" / "auto"
    auto_dir.mkdir(parents=True, exist_ok=True)

    stdout_lines = (
        b"Loading weights: 100%| 770/770 [00:01<00:00]\n"
        b"INFO - Going to convert document sample.pdf...\n"
        b"Processing pages: 25%| 1/4 [00:01<00:03]\n"
        b"Processing pages: 50%| 2/4 [00:02<00:02]\n"
        b"Processing pages: 100%| 4/4 [00:04<00:00]\n"
    )

    class FakeStdout:
        def __init__(self, data: bytes) -> None:
            self._buf = data
            self._pos = 0

        async def read(self, n: int = 1024) -> bytes:
            if self._pos >= len(self._buf):
                return b""
            chunk = self._buf[self._pos : self._pos + 64]
            self._pos += 64
            return chunk

    class FakeProc:
        def __init__(self) -> None:
            self.stdout = FakeStdout(stdout_lines)
            self.returncode = 0

        async def wait(self) -> int:
            (auto_dir / "sample.md").write_text("((1))\n\n# Titel\n\nInhalt.\n", encoding="utf-8")
            (auto_dir / "sample_content_list.json").write_text("[]", encoding="utf-8")
            return 0

    async def fake_create_subprocess_exec(*_args, **_kwargs) -> FakeProc:
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    listener: asyncio.Queue = asyncio.Queue()
    task_dict = {
        "task_id": "unit-subproc-1",
        "original_name": "sample.pdf",
        "extension": ".pdf",
        "describe_images": True,
        "logs": [],
        "listeners": [listener],
        "progress": {},
    }

    asyncio.run(
        extraction_service.run_background_extraction(
            task=task_dict,
            input_path=str(pdf_file),
            output_root=str(out_root),
            upload_dir=str(tmp_path),
            engine="lightonocr",
        )
    )

    events: list[dict] = []
    while not listener.empty():
        item = listener.get_nowait()
        if isinstance(item, str) and item.strip():
            events.append(json.loads(item))

    prog_events = [e for e in events if e.get("status") == "progress"]
    completed_ev = next(e for e in events if e.get("status") == "completed")
    percents = [int(e["percent"]) for e in prog_events]

    assert percents == sorted(percents)
    # Must never jump to 100% from "Loading weights: 100%|" or legacy 90%
    assert max(percents) == completed_ev["progress_percent"]
    assert 5 <= completed_ev["progress_percent"] <= 25
    assert all(e.get("unit") == "Seiten" for e in prog_events)


def test_lightonocr_preselected_as_default_engine_across_stack() -> None:
    """Verifies item 15: LightOnOCR-3 is the default engine in frontend HTML and backend services."""
    import inspect

    from backend.services import custom_benchmark_service, extraction_service
    from backend.services.task_manager import Task

    html_path = Path(__file__).resolve().parents[2] / "frontend" / "index.html"
    html_txt = html_path.read_text(encoding="utf-8")
    select_match = html_txt.split('id="engine-select"', 1)[1].split("</select>", 1)[0]
    first_opt_pos = select_match.find('value="lightonocr"')
    inf_opt_pos = select_match.find('value="infinity"')
    assert 0 <= first_opt_pos < inf_opt_pos
    assert '<option value="lightonocr" selected>' in select_match

    sample_task = Task(task_id="t1", original_name="doc.pdf", input_path="doc.pdf", extension=".pdf")
    assert sample_task.engine == "lightonocr"

    sig_bg = inspect.signature(extraction_service.run_background_extraction)
    assert sig_bg.parameters["engine"].default == "lightonocr"

    sig_api = inspect.signature(main_module.extract_markdown)
    assert sig_api.parameters["engine"].default.default == "lightonocr"

    # Empty engine string falls back to lightonocr budget rather than infinity
    fallback_budget = compute_extraction_budget("", page_count=10, estimated_images=5)
    lighton_budget = compute_extraction_budget("lightonocr", page_count=10, estimated_images=5)
    assert fallback_budget == lighton_budget
    assert custom_benchmark_service is not None


