import os
import io
import shutil
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.custom_benchmark_service import evaluate_custom_submission

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

SAMPLE_GROUND_TRUTH = """# Kapitel 1: Biologie der Zelle

((1))

Die Zellmembran schützt das Zellinnere.

$E = m \\cdot c^2$

| Organell | Funktion |
| :--- | :--- |
| Zellkern | Erbgutspeicher |
"""

SAMPLE_PRED_MD = """# Kapitel 1: Biologie der Zelle

((1))

Die Zellmembran schützt das Zellinnere.

$E = m \\cdot c^2$

| Organell | Funktion |
| :--- | :--- |
| Zellkern | Erbgutspeicher |
"""


def test_evaluate_custom_submission_mocked():
    """Tests evaluate_custom_submission pipeline logic with mocked extraction and Gemma calls."""
    with patch("backend.services.custom_benchmark_service.run_single_engine_extraction") as mock_extract, \
         patch("backend.services.custom_benchmark_service.standardise_markdown") as mock_std, \
         patch("backend.services.custom_benchmark_service.evaluate_with_gemma_judge") as mock_judge:
         
        mock_extract.return_value = (SAMPLE_PRED_MD, 1.25)
        mock_std.return_value = SAMPLE_PRED_MD
        mock_judge.return_value = {
            "overall_judge_score": 95.0,
            "judge_feedback": "Excellente Übereinstimmung mit der Ground Truth."
        }

        # Create dummy PDF path
        dummy_pdf_path = os.path.join(os.path.dirname(__file__), "dummy.pdf")
        with open(dummy_pdf_path, "wb") as f:
            f.write(b"%PDF-1.4 dummy content")

        test_task_id = "test_mocked_custom_bench"
        try:
            results = evaluate_custom_submission(
                source_pdf_path=dummy_pdf_path,
                ground_truth_md=SAMPLE_GROUND_TRUTH,
                ruleset_key="uebertragungsregeln_09_2025",
                engines=["docling", "infinity"],
                task_id=test_task_id
            )

            assert "rankings" in results
            assert len(results["rankings"]) == 2
            assert results["rankings"][0]["composite_score"] > 80.0
            assert "diff_html" in results["rankings"][0]
            assert results["rankings"][0]["speed_sec_per_page"] > 0
        finally:
            if os.path.exists(dummy_pdf_path):
                os.remove(dummy_pdf_path)
            from backend.services.benchmark_task_manager import OUTPUT_DIR
            out_dir = os.path.join(OUTPUT_DIR, test_task_id)
            if os.path.exists(out_dir):
                shutil.rmtree(out_dir, ignore_errors=True)


def test_api_custom_benchmark_evaluate_endpoint(client):
    """Tests POST /api/benchmark/custom-evaluate endpoint returning task status running."""
    with patch("backend.services.custom_benchmark_service.evaluate_custom_submission") as mock_custom_eval, \
         patch("backend.main.evaluate_custom_submission") as mock_main_eval:
        mock_custom_eval.return_value = {}
        mock_main_eval.return_value = {}

        files = {
            "source_file": ("test.pdf", io.BytesIO(b"%PDF-1.4 dummy pdf"), "application/pdf"),
            "ground_truth_file": ("ground_truth.md", io.BytesIO(SAMPLE_GROUND_TRUTH.encode("utf-8")), "text/markdown")
        }
        data = {
            "ruleset": "uebertragungsregeln_09_2025",
            "engines": "docling,infinity"
        }

        response = client.post("/api/benchmark/custom-evaluate", files=files, data=data)
        assert response.status_code == 200
        res_json = response.json()
        assert res_json["status"] == "running"
        assert res_json["source_filename"] == "test.pdf"
        assert res_json["ground_truth_filename"] == "ground_truth.md"
        assert "task_id" in res_json


def test_api_custom_benchmark_with_custom_rules_endpoint(client):
    """Tests POST /api/benchmark/custom-evaluate endpoint with document-specific custom rules."""
    with patch("backend.services.custom_benchmark_service.evaluate_custom_submission") as mock_custom_eval, \
         patch("backend.main.evaluate_custom_submission") as mock_main_eval:
        mock_custom_eval.return_value = {}
        mock_main_eval.return_value = {}

        files = {
            "source_file": ("test.pdf", io.BytesIO(b"%PDF-1.4 dummy pdf"), "application/pdf"),
            "ground_truth_file": ("ground_truth.md", io.BytesIO(SAMPLE_GROUND_TRUTH.encode("utf-8")), "text/markdown"),
            "custom_rules_file": ("custom_rules.md", io.BytesIO(b"Custom Rule: Do not translate X"), "text/markdown")
        }
        data = {
            "ruleset": "uebertragungsregeln_09_2025",
            "engines": "docling,infinity",
            "custom_rules_text": "Always put task numbers in bold."
        }

        response = client.post("/api/benchmark/custom-evaluate", files=files, data=data)
        assert response.status_code == 200
        res_json = response.json()
        assert res_json["status"] == "running"
        assert res_json["has_custom_rules"] is True


def test_extract_markdown_from_docx_helper(tmp_path):
    """Tests extract_markdown_from_docx parsing headings, lists, tables from a DOCX file."""
    from backend.services.docx_service import convert_markdown_to_docx, extract_markdown_from_docx
    
    test_md = "# Hauptkapitel\n\n## Unterkapitel\n\n-	Listenpunkt 1\n\n((10))\n\n| A | B |\n| 1 | 2 |"
    docx_file = str(tmp_path / "test_ref.docx")
    convert_markdown_to_docx(test_md, docx_file)
    
    extracted_md = extract_markdown_from_docx(docx_file)
    assert "# Hauptkapitel" in extracted_md
    assert "## Unterkapitel" in extracted_md
    assert "Listenpunkt 1" in extracted_md
    assert "((10))" in extracted_md
    assert "| A | B |" in extracted_md


def test_api_custom_benchmark_with_docx_ground_truth(tmp_path, client):
    """Tests POST /api/benchmark/custom-evaluate with a .docx ground truth file."""
    from backend.services.docx_service import convert_markdown_to_docx

    docx_path = str(tmp_path / "final_reference.docx")
    convert_markdown_to_docx(SAMPLE_GROUND_TRUTH, docx_path)

    with open(docx_path, "rb") as f:
        docx_bytes = f.read()

    with patch("backend.services.custom_benchmark_service.evaluate_custom_submission") as mock_custom_eval, \
         patch("backend.main.evaluate_custom_submission") as mock_main_eval:
        mock_custom_eval.return_value = {}
        mock_main_eval.return_value = {}

        files = {
            "source_file": ("test.pdf", io.BytesIO(b"%PDF-1.4 dummy pdf"), "application/pdf"),
            "ground_truth_file": ("final_reference.docx", io.BytesIO(docx_bytes), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        }
        data = {
            "ruleset": "uebertragungsregeln_09_2025",
            "engines": "infinity"
        }

        response = client.post("/api/benchmark/custom-evaluate", files=files, data=data)
        assert response.status_code == 200
        res_json = response.json()
        assert res_json["status"] == "running"
        assert res_json["is_docx_ground_truth"] is True
        assert res_json["ground_truth_filename"] == "final_reference.docx"


def test_api_custom_benchmark_task_controls_and_history(client):
    """Tests status polling, abort, skip, active task, and history endpoints."""
    from backend.services.benchmark_task_manager import benchmark_task_manager

    t_id = "test_task_controls_999"
    task = benchmark_task_manager.create_task(
        task_id=t_id,
        source_filename="sample.pdf",
        ground_truth_filename="gt.md",
        ruleset="uebertragungsregeln_09_2025",
        engines=["docling", "infinity"]
    )
    task.update_progress("Extrahiere Docling...", 0, "docling", 0.5)

    # Status
    res_status = client.get(f"/api/benchmark/tasks/{t_id}/status")
    assert res_status.status_code == 200
    st_json = res_status.json()
    assert st_json["current_engine"] == "docling"
    assert len(st_json["logs"]) > 0

    # Skip engine
    res_skip = client.post(f"/api/benchmark/tasks/{t_id}/skip")
    assert res_skip.status_code == 200
    assert task.should_skip_engine() is True

    # Abort task
    res_abort = client.post(f"/api/benchmark/tasks/{t_id}/abort")
    assert res_abort.status_code == 200
    assert task.is_abort_requested() is True

    # Active task
    res_active = client.get("/api/benchmark/active")
    assert res_active.status_code == 200

    # History
    res_hist = client.get("/api/benchmark/history")
    assert res_hist.status_code == 200
    assert "history" in res_hist.json()


def test_api_custom_benchmark_re_evaluate(client):
    """Tests POST /api/benchmark/tasks/{task_id}/re-evaluate endpoint."""
    import json
    from backend.main import OUTPUT_DIR

    t_id = "test_reevaluate_123"
    task_dir = os.path.join(OUTPUT_DIR, t_id)
    os.makedirs(task_dir, exist_ok=True)

    try:
        # 1. Write dummy ground truth
        gt_path = os.path.join(task_dir, "ground_truth_extracted.md")
        with open(gt_path, "w", encoding="utf-8") as f:
            f.write(SAMPLE_GROUND_TRUTH)

        # 2. Write dummy initial task status with previous ranking
        status_path = os.path.join(task_dir, "task_status.json")
        initial_status = {
            "task_id": t_id,
            "source_filename": "biology_test.pdf",
            "ground_truth_filename": "gt.md",
            "ruleset": "uebertragungsregeln_09_2025",
            "status": "completed",
            "results": {
                "timestamp": "2026-08-20 12:00:00",
                "ruleset": "uebertragungsregeln_09_2025",
                "page_count": 1,
                "rankings": [
                    {
                        "engine": "docling",
                        "composite_score": 50.0,
                        "raw_markdown": SAMPLE_PRED_MD,
                        "extracted_markdown": SAMPLE_PRED_MD
                    }
                ]
            }
        }
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump(initial_status, f)

        # 3. Call re-evaluate endpoint
        res = client.post(f"/api/benchmark/tasks/{t_id}/re-evaluate")
        assert res.status_code == 200
        res_json = res.json()
        assert res_json["status"] == "success"
        assert "results" in res_json
        rankings = res_json["results"]["rankings"]
        assert len(rankings) == 1
        assert rankings[0]["engine"] == "docling"
        assert rankings[0]["composite_score"] > 80.0  # Perfect match against SAMPLE_GROUND_TRUTH
        assert "diff_html" in rankings[0]
        assert "judge_score" in rankings[0]

        # Verify disk persistence
        with open(status_path, "r", encoding="utf-8") as f:
            updated_on_disk = json.load(f)
        assert updated_on_disk["results"]["rankings"][0]["composite_score"] == rankings[0]["composite_score"]

    finally:
        if os.path.exists(task_dir):
            shutil.rmtree(task_dir, ignore_errors=True)


def test_benchmark_evaluators_monotonicity_bookmarks_and_slicing():
    """Tests evaluate_page_monotonicity, evaluate_docx_bookmarks, strip_catalog_title_from_golden, and slice_golden_markdown_to_pages."""
    from scripts.run_benchmark import (
        evaluate_page_monotonicity,
        evaluate_docx_bookmarks,
        strip_catalog_title_from_golden,
        slice_golden_markdown_to_pages,
    )

    gold_md = "((32))\n\n# Musterbuch Deutsch – Schulbuch 5. Schuljahr\n\n## Kapitel 1\n\nText A.\n\n((33))\n\nText B.\n\n((34))\n\nText C.\n"
    pred_good = "((32))\n\n## Kapitel 1\n\nText A.\n\n((33))\n\nText B.\n\n((34))\n\nText C.\n"
    pred_bad = "((32))\n\nText A.\n\n((30))\n\nText B.\n\n((90))\n\nText C.\n"

    mono_good = evaluate_page_monotonicity(pred_good, gold_md)
    assert mono_good["is_monotonic"] is True
    assert mono_good["score"] == 100.0

    mono_bad = evaluate_page_monotonicity(pred_bad, gold_md)
    assert mono_bad["is_monotonic"] is False
    assert mono_bad["score"] < 50.0

    docx_res = evaluate_docx_bookmarks(pred_good)
    assert docx_res["score"] == 100.0
    assert docx_res["expected_bookmarks"] == ["page_32", "page_33", "page_34"]

    stripped = strip_catalog_title_from_golden(gold_md, "Musterbuch Deutsch – Schulbuch 5. Schuljahr")
    assert "# Musterbuch Deutsch" not in stripped
    assert "## Kapitel 1" in stripped

    sliced = slice_golden_markdown_to_pages(stripped, [32, 33])
    assert "((32))" in sliced
    assert "((33))" in sliced
    assert "((34))" not in sliced
    assert "Text C." not in sliced


def test_resolve_page_sequence_rejects_non_monotonic_outliers():
    """Tests _resolve_page_sequence rejecting duplicate, backward-jumping, and misread OCR page numbers."""
    from backend.services.extraction_service import _resolve_page_sequence

    # Simulated noisy OCR detections for physical pages 28..35 (including jumps to 23, 30, 90)
    noisy_detected = [28, 29, 30, 23, 32, 33, 30, 90]
    resolved = _resolve_page_sequence(noisy_detected, fallback_start_page=28)
    assert resolved == [28, 29, 30, 31, 32, 33, 34, 35]


def test_benchmark_batching_checkpoint_resume_and_modes(tmp_path, monkeypatch):
    """Tests slice_datasets_for_batch, resolve_suite_datasets, multi-tier LEADERBOARD.md, and checkpoint resume."""
    import json
    from scripts import run_benchmark as rb

    all_docs = ["doc1.pdf", "doc2.pdf", "doc3.pdf", "doc4.pdf", "doc5.pdf"]
    assert rb.slice_datasets_for_batch(all_docs, batch_size=2, batch_index=0) == ["doc1.pdf", "doc2.pdf"]
    assert rb.slice_datasets_for_batch(all_docs, batch_size=2, batch_index=1) == ["doc3.pdf", "doc4.pdf"]
    assert rb.slice_datasets_for_batch(all_docs, batch_size=2, batch_index=2) == ["doc5.pdf"]

    # Create a synthetic external catalog directory to test suite resolution deterministically
    fake_ext_dir = tmp_path / "fake_ext"
    fake_ext_dir.mkdir(parents=True, exist_ok=True)
    (fake_ext_dir / "catalog.json").write_text(
        json.dumps(
            {
                "documents": [
                    {"id": "ext_sample_01", "pdf_filename": "ext_sample_01.pdf", "physical_pages": [10, 11]},
                    {"id": "ext_sample_02", "pdf_filename": "ext_sample_02.pdf", "physical_pages": [20, 21]},
                ]
            }
        ),
        encoding="utf-8",
    )

    open_suite = rb.resolve_suite_datasets("open_all", external_data_dir=str(tmp_path / "nonexistent"))
    assert len(open_suite) == 19
    assert "test_educational.pdf" in open_suite
    assert "sek1_informatik.pdf" in open_suite

    ext_suite = rb.resolve_suite_datasets("external", external_data_dir=str(fake_ext_dir))
    full_suite = rb.resolve_suite_datasets("full", external_data_dir=str(fake_ext_dir))
    assert ext_suite == ["ext_sample_01.pdf", "ext_sample_02.pdf"]
    assert len(full_suite) == 21

    # Test checkpoint & batch resume without re-running completed (engine, doc) pairs
    ckpt_file = str(tmp_path / "checkpoint.json")
    runs_dir = str(tmp_path / "runs")
    lb_file = str(tmp_path / "LEADERBOARD.md")
    monkeypatch.setattr(rb, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(rb, "LEADERBOARD_PATH", lb_file)

    extraction_calls = []

    def fake_docling(pdf_path, out_dir, task=None, in_process=False):
        extraction_calls.append(os.path.basename(pdf_path))
        os.makedirs(out_dir, exist_ok=True)
        return "((45))\n\n# Kapitel 1\n\nText.", 0.25

    monkeypatch.setattr(rb, "run_docling_extraction", fake_docling)

    # Batch 0 (1st document)
    rec0 = rb.run_comprehensive_benchmark(
        engines=["docling"],
        datasets=["test_educational.pdf", "mathe_grade3.pdf"],
        checkpoint_file=ckpt_file,
        batch_size=1,
        batch_index=0,
        skip_standardisation=True,
    )
    assert list(rec0["details"]["docling"]["details_by_doc"].keys()) == ["test_educational.pdf"]
    assert len(extraction_calls) == 1

    # Batch 1 (2nd document, resuming from checkpoint) + re-running across both with resume=True
    rec1 = rb.run_comprehensive_benchmark(
        engines=["docling"],
        datasets=["test_educational.pdf", "mathe_grade3.pdf"],
        checkpoint_file=ckpt_file,
        resume=True,
        skip_standardisation=True,
    )
    assert set(rec1["details"]["docling"]["details_by_doc"].keys()) == {"test_educational.pdf", "mathe_grade3.pdf"}
    # test_educational.pdf was loaded from checkpoint and NOT extracted a second time
    assert extraction_calls == ["test_educational.pdf", "mathe_grade3.pdf"]
    assert os.path.exists(ckpt_file)
    with open(ckpt_file, "r", encoding="utf-8") as cf:
        saved_ckpt = json.load(cf)
    assert saved_ckpt["summary_digital"][0]["docs_evaluated"] == 2
    assert os.path.exists(lb_file)
    lb_content = open(lb_file, "r", encoding="utf-8").read()
    assert "Executive Quality Overview" in lb_content
    assert "Tier 1: Fast Regression" in lb_content
    assert "Textbook Category & Format Breakdown" in lb_content



