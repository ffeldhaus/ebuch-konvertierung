"""
Unit tests for the enhanced E-Buch Multi-Engine Benchmark Runner (`scripts/run_benchmark.py`)
and Diagnostics Analyzer (`scripts/analyze_benchmark_run.py`).

Tests:
1. Execution modes (`fast`, `smoke`, `full`) and default fast mode configuration.
2. Dataset suite resolution across open (`core`, `schoolbooks`, `open`) and proprietary
   (`proprietary`, `all` via `../ebuch-testdaten/catalog.json`) repositories.
3. Synthetic catalog title stripping (`strip_catalog_title_from_golden`) and page-range
   golden truth slicing (`slice_golden_markdown_to_pages`) for multi-page publisher PDFs.
4. Comprehensive FIBS 09/2025 & DOCX metrics:
   - `evaluate_boxes` (<Rahmen> callout boxes)
   - `evaluate_images` (<Bild> blocks) included in summary & composite score
   - `evaluate_page_monotonicity` (strictly increasing `((num))` markers)
   - `evaluate_docx_bookmarks` (native Word `w:bookmarkStart` `page_{num}` verification)
5. Checkpointing (`checkpoint_file`, `resume=True`) and batch execution (`batch_size`, `batch_index`),
   verifying that multi-batch runs accumulate into a single checkpoint and skip already-completed pairs.
"""

import json
import os
import pytest

from scripts.run_benchmark import (
    PROJECT_ROOT,
    build_judge_prompt,
    calibrate_judge_scores_with_programmatic_reference,
    evaluate_boxes,
    evaluate_docx_bookmarks,
    evaluate_formulas,
    evaluate_page_monotonicity,
    evaluate_tables,
    evaluate_text_and_continuity,
    evaluate_with_gemma_judge,
    load_external_catalog,
    resolve_suite_datasets,
    run_comprehensive_benchmark,
    slice_datasets_for_batch,
    slice_golden_markdown_to_pages,
    strip_catalog_title_from_golden,
)


def test_resolve_suite_datasets_open_and_external(tmp_path):
    # Create a mock proprietary testdata directory with catalog.json
    ext_dir = tmp_path / "ebuch-testdaten"
    (ext_dir / "testdata" / "golden").mkdir(parents=True)
    catalog_data = {
        "repository": "ebuch-testdaten",
        "total_documents": 2,
        "documents": [
            {
                "id": "nrw_01_test",
                "title": "Synthetic Catalog Title",
                "pdf_filename": "testdata/nrw_01_test.pdf",
                "raw_golden_filename": "testdata/golden/nrw_01_test.raw.golden.md",
                "fibs_golden_filename": "testdata/golden/nrw_01_test.uebertragungsregeln_09_2025.golden.md",
                "physical_pages": [10, 11, 12, 13, 14, 15],
                "benchmark_page_indices": [0, 1, 2, 3],
            },
            {
                "id": "nrw_02_test",
                "title": "Another Book Title",
                "pdf_filename": "testdata/nrw_02_test.pdf",
                "raw_golden_filename": "testdata/golden/nrw_02_test.raw.golden.md",
                "fibs_golden_filename": "testdata/golden/nrw_02_test.uebertragungsregeln_09_2025.golden.md",
                "physical_pages": [5, 6],
                "benchmark_page_indices": [0, 1],
            },
        ],
    }
    (ext_dir / "catalog.json").write_text(json.dumps(catalog_data), encoding="utf-8")
    for doc in catalog_data["documents"]:
        (ext_dir / doc["pdf_filename"]).write_bytes(b"%PDF-1.4 mock")

    cat_map = load_external_catalog(str(ext_dir))
    assert "nrw_01_test.pdf" in cat_map
    assert cat_map["nrw_01_test.pdf"]["title"] == "Synthetic Catalog Title"

    open_docs = resolve_suite_datasets("open_all", external_data_dir=str(ext_dir))
    assert len(open_docs) == 19
    assert "test_educational.pdf" in open_docs
    assert "sek2_mathematik_analysis.pdf" in open_docs

    prop_docs = resolve_suite_datasets("external", external_data_dir=str(ext_dir))
    assert prop_docs == ["nrw_01_test.pdf", "nrw_02_test.pdf"]

    all_docs = resolve_suite_datasets("full", external_data_dir=str(ext_dir))
    assert len(all_docs) == 19 + 2
    assert "test_educational.pdf" in all_docs
    assert "nrw_01_test.pdf" in all_docs


def test_strip_catalog_title_and_slice_golden_markdown_to_pages():
    raw_golden = (
        "((10))\n\n"
        "# Synthetic Catalog Title\n\n"
        "## 1 Echte Kapitelüberschrift\n\n"
        "Text auf Seite zehn.\n\n"
        "((11))\n\n"
        "Text auf Seite elf.\n\n"
        "((12))\n\n"
        "Text auf Seite zwölf.\n"
    )
    stripped = strip_catalog_title_from_golden(raw_golden, "Synthetic Catalog Title")
    assert "# Synthetic Catalog Title" not in stripped
    assert "## 1 Echte Kapitelüberschrift" in stripped

    sliced = slice_golden_markdown_to_pages(stripped, [10, 11])
    assert "((10))" in sliced
    assert "((11))" in sliced
    assert "Text auf Seite elf." in sliced
    assert "((12))" not in sliced
    assert "Text auf Seite zwölf." not in sliced


def test_evaluate_page_monotonicity_and_docx_bookmarks():
    gold_md = "((14))\n\n# Kapitel 1\n\nText A.\n\n((15))\n\nText B.\n\n((16))\n\nText C.\n"
    good_pred = "((14))\n\n# Kapitel 1\n\nText A.\n\n((15))\n\nText B.\n\n((16))\n\nText C.\n"
    bad_pred = "((14))\n\n# Kapitel 1\n\nText A.\n\n((99))\n\nText B.\n\n((12))\n\nText C.\n"

    mono_good = evaluate_page_monotonicity(good_pred, gold_md)
    assert mono_good["is_monotonic"] is True
    assert mono_good["score"] == 100.0
    assert mono_good["pred_pages"] == [14, 15, 16]

    mono_bad = evaluate_page_monotonicity(bad_pred, gold_md)
    assert mono_bad["is_monotonic"] is False
    assert mono_bad["score"] < 70.0

    docx_res = evaluate_docx_bookmarks(good_pred)
    assert docx_res["score"] == 100.0
    assert docx_res["expected_bookmarks"] == ["page_14", "page_15", "page_16"]
    assert docx_res["found_bookmarks"] == ["page_14", "page_15", "page_16"]


def test_slice_datasets_for_batch():
    docs = [f"doc_{i}.pdf" for i in range(10)]
    b0 = slice_datasets_for_batch(docs, batch_size=4, batch_index=0)
    b1 = slice_datasets_for_batch(docs, batch_size=4, batch_index=1)
    b2 = slice_datasets_for_batch(docs, batch_size=4, batch_index=2)

    assert b0 == ["doc_0.pdf", "doc_1.pdf", "doc_2.pdf", "doc_3.pdf"]
    assert b1 == ["doc_4.pdf", "doc_5.pdf", "doc_6.pdf", "doc_7.pdf"]
    assert b2 == ["doc_8.pdf", "doc_9.pdf"]


def test_checkpoint_and_batch_resume_skips_completed_docs_and_aggregates_metrics(tmp_path, monkeypatch):
    checkpoint_path = str(tmp_path / "bench_checkpoint.json")
    runs_dir = str(tmp_path / "runs")
    monkeypatch.setattr("scripts.run_benchmark.RUNS_DIR", runs_dir)
    monkeypatch.setattr("scripts.run_benchmark.LEADERBOARD_PATH", str(tmp_path / "LEADERBOARD.md"))

    call_log = []

    def fake_docling(pdf_path, output_dir, task=None, in_process=False):
        call_log.append(os.path.basename(pdf_path))
        return (
            "((1))\n\n# Titel\n\nEin kurzer Absatz mit $E = mc^2$.\n\n"
            "<Rahmen>\n*Merksatz:* Wichtig.\n</Rahmen>\n",
            0.25,
        )

    monkeypatch.setattr("scripts.run_benchmark.run_docling_extraction", fake_docling)

    all_two_docs = ["test_educational.pdf", "deutsch_textanalyse.pdf"]

    # Batch 0 (processes only test_educational.pdf and writes checkpoint)
    rec0 = run_comprehensive_benchmark(
        engines=["docling"],
        datasets=all_two_docs,
        skip_standardisation=True,
        checkpoint_file=checkpoint_path,
        resume=True,
        batch_size=1,
        batch_index=0,
    )
    assert os.path.exists(checkpoint_path)
    assert call_log == ["test_educational.pdf"]
    assert "test_educational.pdf" in rec0["details"]["docling"]["details_by_doc"]
    assert "deutsch_textanalyse.pdf" not in rec0["details"]["docling"]["details_by_doc"]

    # Batch 1 (resumes from checkpoint, skips test_educational.pdf if re-included, runs deutsch_textanalyse.pdf)
    rec1 = run_comprehensive_benchmark(
        engines=["docling"],
        datasets=all_two_docs,
        skip_standardisation=True,
        checkpoint_file=checkpoint_path,
        resume=True,
        batch_size=1,
        batch_index=1,
    )
    assert call_log == ["test_educational.pdf", "deutsch_textanalyse.pdf"]
    docs_in_ckpt = rec1["details"]["docling"]["details_by_doc"]
    assert "test_educational.pdf" in docs_in_ckpt
    assert "deutsch_textanalyse.pdf" in docs_in_ckpt

    # Verify new metrics are recorded per doc and in summary
    doc_detail = docs_in_ckpt["test_educational.pdf"]
    assert "boxes" in doc_detail["raw_metrics"]
    assert "page_monotonicity" in doc_detail["raw_metrics"]
    assert "docx_bookmarks" in doc_detail["uebertragung_metrics"]
    assert doc_detail["standardisation_backend"] == "fast_postprocess_only"
    assert doc_detail["peak_memory_mb"] >= 0

    summary_row = rec1["summary_digital"][0]
    assert "ueb_boxes" in summary_row
    assert "ueb_images" in summary_row
    assert "ueb_page_monotonicity" in summary_row
    assert "ueb_docx_bookmarks" in summary_row

    # Re-running full list with resume=True should make zero new extraction calls
    rec_cached = run_comprehensive_benchmark(
        engines=["docling"],
        datasets=all_two_docs,
        skip_standardisation=True,
        checkpoint_file=checkpoint_path,
        resume=True,
    )
    assert len(call_log) == 2
    assert len(rec_cached["details"]["docling"]["details_by_doc"]) == 2


def test_evaluate_with_gemma_judge_profile_and_calibration():
    gold_raw = "((1))\n\n# Kapitel 1\n\n![Abb. 1: Prisma](images/pic1.png)\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
    pred_raw = "((1))\n\n# Kapitel 1\n\n![Abb. 1: Prisma](images/pic1.png)\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"

    prog_metrics = {
        "headings": {"score": 100.0, "f1": 100.0, "pred_count": 1, "gold_count": 1},
        "formulas": {"score": 100.0, "f1": 100.0, "pred_count": 0, "gold_count": 0},
        "tables": {"score": 100.0, "cell_recall": 100.0, "pred_count": 1, "gold_count": 1},
        "continuity": {"score": 100.0, "word_recall": 100.0, "char_similarity": 100.0},
        "images": {"score": 100.0, "f1": 100.0, "pred_count": 1, "gold_count": 1},
        "boxes": {"score": 100.0, "pred_count": 0, "gold_count": 0},
        "a11y": {"score": 100.0},
    }

    prompt_raw = build_judge_prompt(pred_raw, gold_raw, profile="raw", programmatic_metrics=prog_metrics)
    assert "Raw Markdown" in prompt_raw or "ROH-EXTRAKTION" in prompt_raw
    assert "OBJEKTIVE PROGRAMMATISCHE REFERENZ-METRIKEN" in prompt_raw
    assert "Kein Abzug für fehlende <Bild>" in prompt_raw

    prompt_ueb = build_judge_prompt(
        pred_raw, gold_raw, profile="uebertragungsregeln_09_2025", programmatic_metrics=prog_metrics
    )
    assert "Übertragungsregeln Stand 09/2025" in prompt_ueb
    assert "OBJEKTIVE PROGRAMMATISCHE REFERENZ-METRIKEN" in prompt_ueb
    assert "Die folgende Tabelle wurde aufgelöst." in prompt_ueb

    # Verify calibration anchors hallucinated LLM sub-scores against objective programmatic reference
    raw_llm_hallucination = {
        "completeness_score": 95,
        "headings_score": 80,  # Suppose programmatic headings score is 0.0!
        "formulas_score": 90,
        "tables_score": 40,    # Suppose programmatic tables score is 100.0!
        "continuity_score": 95,
        "images_score": 60,    # Suppose programmatic images score is 100.0!
        "overall_judge_score": 76,
        "judge_feedback": "Test feedback",
    }
    strict_prog = {
        "headings": {"score": 0.0},
        "formulas": {"score": 90.0},
        "tables": {"score": 100.0},
        "continuity": {"score": 95.0, "word_recall": 98.0},
        "images": {"score": 100.0},
        "boxes": {"score": 100.0},
    }
    calibrated = calibrate_judge_scores_with_programmatic_reference(raw_llm_hallucination, strict_prog)
    assert calibrated["headings_score"] <= 15.0
    assert calibrated["tables_score"] >= 85.0
    assert calibrated["images_score"] >= 85.0


def test_evaluate_formulas_and_word_recall_with_latex_text_wrappers():
    gold_md = (
        "((310))\n\n"
        "Reaktion von Ethansäure ($\\text{CH}_3\\text{COOH}$) mit Ethanol ($\\text{C}_2\\text{H}_5\\text{OH}$) "
        "unter $\\text{H}_2\\text{SO}_4$-Katalyse.\n"
    )
    pred_md = (
        "((310))\n\n"
        "Reaktion von Ethansäure ($CH_3COOH$) mit Ethanol ($C_2H_5OH$) "
        "unter $H_2SO_4$-Katalyse.\n"
    )
    f_res = evaluate_formulas(pred_md, gold_md)
    assert f_res["score"] == 100.0

    c_res = evaluate_text_and_continuity(pred_md, gold_md)
    assert c_res["word_recall"] >= 98.0
    assert c_res["missing_chunks_count"] == 0


def test_compute_doc_composite_and_order_invariant_boxes():
    from scripts.run_benchmark import compute_doc_composite

    gold_md = (
        "((112))\n\n"
        "<Rahmen>\n_Worterklärungen_\n-\tHallig: kleine Marschinsel.\n</Rahmen>\n\n"
        "<Rahmen>\n_Hintergrund: Sturmflut_\n-\tWeststürme drücken Wasser in die Bucht.\n</Rahmen>\n\n"
        "<Rahmen>\n_Methode: Erzähltext untersuchen_\n-\tAtmosphäre und Schauplatz beachten.\n-\tFigurenrede untersuchen.\n</Rahmen>\n"
    )
    # Extracted with main-column box ('Methode') before margin boxes ('Worterklärungen', 'Hintergrund')
    pred_md = (
        "((112))\n\n"
        "<Rahmen>\n_Methode: Erzähltext untersuchen_\n-\tAtmosphäre und Schauplatz beachten.\n-\tFigurenrede untersuchen.\n</Rahmen>\n\n"
        "<Rahmen>\n_Worterklärungen_\n-\tHallig: kleine Marschinsel.\n</Rahmen>\n\n"
        "<Rahmen>\n_Hintergrund: Sturmflut_\n-\tWeststürme drücken Wasser in die Bucht.\n</Rahmen>\n"
    )
    b_res = evaluate_boxes(pred_md, gold_md)
    assert b_res["score"] >= 98.0

    # When a document has 0 tables and 0 formulas (gold_count=0, pred_count=0),
    # their 100% scores must not dilute a 0% boxes score or 50% headings score.
    metrics_no_tables_or_formulas = {
        "headings": {"score": 50.0, "gold_count": 4, "pred_count": 2},
        "formulas": {"score": 100.0, "gold_count": 0, "pred_count": 0},
        "tables": {"score": 100.0, "gold_count": 0, "pred_count": 0},
        "images": {"score": 100.0, "gold_count": 0, "pred_count": 0},
        "boxes": {"score": 0.0, "gold_count": 3, "pred_count": 0},
        "continuity": {"score": 90.0, "word_recall": 90.0},
        "a11y": {"score": 100.0},
        "judge": {"overall_judge_score": 80.0},
    }
    comp = compute_doc_composite(metrics_no_tables_or_formulas, include_boxes=True)
    # Without tables/formulas/images dilution, 0% on boxes and 50% on headings pulls composite well below 80
    assert comp < 78.0


def test_decoupled_ocr_and_gemma_benchmark_modes(tmp_path, monkeypatch):
    from scripts import run_benchmark as rb

    runs_dir = str(tmp_path / "runs")
    os.makedirs(runs_dir, exist_ok=True)
    monkeypatch.setattr(rb, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(rb, "LEADERBOARD_PATH", str(tmp_path / "LEADERBOARD.md"))

    extracted_calls = []
    judge_calls = []

    def fake_extract(pdf_path, output_dir, task=None, in_process=False):
        extracted_calls.append(os.path.basename(pdf_path))
        return "((45))\n\n# Kapitel 1\n\nEin kurzer Beispieltext.\n", 0.5

    monkeypatch.setattr(rb, "run_docling_extraction", fake_extract)
    monkeypatch.setattr(rb, "run_lightonocr_extraction", fake_extract)
    monkeypatch.setattr(rb, "run_infinity_extraction", fake_extract)
    monkeypatch.setattr(
        rb,
        "evaluate_with_gemma_judge",
        lambda pred, gold, profile="uebertragungsregeln_09_2025", programmatic_metrics=None: (
            judge_calls.append(profile)
            or {
                "completeness_score": 95.0,
                "headings_score": 95.0,
                "formulas_score": 100.0,
                "tables_score": 100.0,
                "continuity_score": 95.0,
                "images_score": 100.0,
                "overall_judge_score": 95.0,
                "judge_feedback": "OK",
                "comment": "OK",
            }
        ),
    )
    monkeypatch.setattr(
        "backend.services.llm_service.standardise_markdown",
        lambda md, **kwargs: md,
    )

    # Track A: --mode ocr runs all 3 engines with skip_standardisation=True and 0 LLM judge calls
    rec_ocr = rb.main(["--mode", "ocr", "--datasets", "test_educational.pdf"])
    assert rec_ocr["skip_standardisation"] is True
    assert set(rec_ocr["engines_requested"]) == {"docling", "lightonocr", "infinity"}
    assert len(extracted_calls) == 3
    assert len(judge_calls) == 0

    # Track B: --mode gemma defaults to single canonical engine ('docling'), reuses cached extraction,
    # and runs LLM judge only once (for post-Gemma 'uebertragungsregeln_09_2025', skipping redundant raw judge)
    rec_gemma = rb.main(["--mode", "gemma", "--datasets", "test_educational.pdf"])
    assert rec_gemma["skip_standardisation"] is False
    assert rec_gemma["engines_requested"] == ["docling"]
    assert len(extracted_calls) == 3  # Reused from Track A snapshot!
    assert judge_calls == ["uebertragungsregeln_09_2025"]




