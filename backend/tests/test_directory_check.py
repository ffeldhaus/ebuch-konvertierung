"""
Tests for fast post-upload directory detection (Inhaltsverzeichnis, Abbildungsverzeichnis,
Tabellenverzeichnis, Bildverzeichnis) and directory-assisted page number & heading level
reconstruction.
"""

import json
import os
import time
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.directory_service import (
    MAX_DIRECTORY_CHECK_PAGES,
    build_fast_docling_pipeline_options,
    check_document_directories,
    apply_directory_heading_levels,
    apply_directory_page_numbers,
)
from backend.services.extraction_service import (
    detect_physical_start_page,
    get_physical_page_numbers_for_pdf,
    insert_page_numbers_from_metadata,
)
from backend.services.fibs_postprocess import (
    infer_heading_hierarchy,
    post_process_structure,
)
from backend.services.llm_service import _build_system_prompt
from backend.services.extraction_postprocess import reconstruct_title_hierarchy
from backend.services.a11y_linter import lint_markdown

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEST_DATA_DIR = os.path.join(PROJECT_ROOT, "testdata")
PHYSIK_VERZEICHNISSE_PDF = os.path.join(TEST_DATA_DIR, "sek2_physik_verzeichnisse.pdf")


def test_fast_docling_pipeline_disables_formulas_tables_and_images():
    """
    Verifies that the fast Docling directory-check configuration caps pages at 20
    and disables formula enrichment, table structure, and image extraction.
    """
    assert MAX_DIRECTORY_CHECK_PAGES == 20
    opts = build_fast_docling_pipeline_options(do_ocr=False)
    assert opts.do_formula_enrichment is False
    assert opts.do_table_structure is False
    assert opts.do_code_enrichment is False
    assert opts.do_picture_classification is False
    assert opts.do_picture_description is False
    assert opts.generate_picture_images is False
    assert opts.generate_table_images is False
    assert opts.generate_page_images is False


def test_test_document_with_directories_exists_and_is_checked_quickly():
    """
    Verifies that test_data/sek2_physik_verzeichnisse.pdf exists and that
    check_document_directories detects all four directory types quickly via Docling.
    """
    assert os.path.exists(PHYSIK_VERZEICHNISSE_PDF), (
        f"Expected test document {PHYSIK_VERZEICHNISSE_PDF} to exist."
    )

    t0 = time.perf_counter()
    info = check_document_directories(PHYSIK_VERZEICHNISSE_PDF, max_pages=20)
    elapsed = time.perf_counter() - t0

    # Fast check must complete quickly
    assert elapsed < 10.0, f"Directory check took too long: {elapsed:.2f}s"
    assert info["checked_pages"] <= 20
    assert info["has_any_directory"] is True
    assert info["has_toc"] is True
    assert info["has_list_of_figures"] is True
    assert info["has_list_of_tables"] is True
    assert info["has_list_of_pictures"] is True

    detected_types = set(info["detected_types"])
    assert {
        "Inhaltsverzeichnis",
        "Abbildungsverzeichnis",
        "Tabellenverzeichnis",
        "Bildverzeichnis",
    }.issubset(detected_types)

    # Check extracted TOC entries and inferred heading levels (1..4)
    toc_by_title = {e["title"]: e for e in info["toc_entries"]}
    assert any("Kapitel 5" in t and e["level"] == 1 and e["page"] == 45 for t, e in toc_by_title.items())
    assert any("5.1" in t and e["level"] == 2 and e["page"] == 45 for t, e in toc_by_title.items())
    assert any(
        "Versuchsaufbau mit dem Doppelspalt" in t and e["level"] == 3 and e["page"] == 45
        for t, e in toc_by_title.items()
    )
    assert any(
        "Herleitung der Gangunterschiedsformel" in t and e["level"] == 4 and e["page"] == 46
        for t, e in toc_by_title.items()
    )
    assert any("5.2" in t and e["level"] == 2 and e["page"] == 46 for t, e in toc_by_title.items())
    assert any(
        "Photoelektrischer Effekt und Lichtquantenhypothese" in t and e["level"] == 3 and e["page"] == 47
        for t, e in toc_by_title.items()
    )

    # Check figure, table, and picture directory entries
    assert len(info["figure_entries"]) >= 2
    assert any(e["page"] == 45 and "5.1" in (e.get("label") or e["title"]) for e in info["figure_entries"])
    assert any(e["page"] == 46 and "5.2" in (e.get("label") or e["title"]) for e in info["figure_entries"])

    assert len(info["table_entries"]) >= 2
    assert any(e["page"] == 46 and "5.1" in (e.get("label") or e["title"]) for e in info["table_entries"])
    assert any(e["page"] == 47 and "5.2" in (e.get("label") or e["title"]) for e in info["table_entries"])

    assert len(info["picture_entries"]) >= 2
    assert any(e["page"] == 45 and "5.1" in (e.get("label") or e["title"]) for e in info["picture_entries"])
    assert any(e["page"] == 47 and "5.2" in (e.get("label") or e["title"]) for e in info["picture_entries"])


def test_directory_used_for_accurate_page_number_detection():
    """
    Verifies that directory entries (TOC, figures, tables, pictures) are matched against
    actual PDF page contents to accurately infer physical page numbers even when pages
    lack printed footer/header page numbers or when a directory page ends with a target page number.
    """
    page_numbers = get_physical_page_numbers_for_pdf(PHYSIK_VERZEICHNISSE_PDF)
    assert page_numbers == [44, 45, 46, 47]
    assert detect_physical_start_page(PHYSIK_VERZEICHNISSE_PDF) == 44


def test_directory_page_numbers_correct_metadata_and_markdown_markers(tmp_path):
    """
    Verifies that insert_page_numbers_from_metadata and apply_directory_page_numbers
    use directory entries to inject and repair ((page)) markers.
    """
    info = check_document_directories(PHYSIK_VERZEICHNISSE_PDF, max_pages=20)

    # 1. Test apply_directory_page_numbers when a page marker was misdetected (e.g. ((2)) instead of ((45)))
    wrong_md = (
        "((1))\n\n"
        "# Inhaltsverzeichnis\n\n"
        "((2))\n\n"
        "# Kapitel 5: Wellenoptik und Quantenphysik\n\n"
        "## 5.1 Interferenz und Beugung am Doppelspalt\n\n"
        "### Versuchsaufbau mit dem Doppelspalt\n\n"
        "((3))\n\n"
        "#### Herleitung der Gangunterschiedsformel\n\n"
        "### Tabelle 5.1: Wellenlängen und Beugungswinkel ausgewählter Spektrallinien\n\n"
        "((4))\n\n"
        "### Photoelektrischer Effekt und Lichtquantenhypothese\n\n"
        "### Tabelle 5.2: Austrittsarbeit ausgewählter Metalle beim Photoeffekt\n"
    )
    corrected_md = apply_directory_page_numbers(wrong_md, info)
    assert "((44))" in corrected_md
    assert "((45))" in corrected_md
    assert "((46))" in corrected_md
    assert "((47))" in corrected_md
    assert "((1))" not in corrected_md
    assert "((2))" not in corrected_md

    # 2. Test insert_page_numbers_from_metadata with content_list.json and directory_info
    blocks = [
        {"type": "title", "text": "Inhaltsverzeichnis", "page_idx": 0},
        {"type": "title", "text": "Kapitel 5: Wellenoptik und Quantenphysik", "page_idx": 1},
        {"type": "title", "text": "Herleitung der Gangunterschiedsformel", "page_idx": 2},
        {"type": "title", "text": "Photoelektrischer Effekt und Lichtquantenhypothese", "page_idx": 3},
    ]
    json_path = tmp_path / "content_list.json"
    json_path.write_text(json.dumps(blocks), encoding="utf-8")

    raw_without_markers = (
        "# Inhaltsverzeichnis\n\n"
        "# Kapitel 5: Wellenoptik und Quantenphysik\n\n"
        "#### Herleitung der Gangunterschiedsformel\n\n"
        "### Photoelektrischer Effekt und Lichtquantenhypothese\n"
    )
    with_markers = insert_page_numbers_from_metadata(
        raw_without_markers,
        str(json_path),
        "",
        pdf_path=PHYSIK_VERZEICHNISSE_PDF,
        directory_info=info,
    )
    assert "((44))" in with_markers
    assert "((45))" in with_markers
    assert "((46))" in with_markers
    assert "((47))" in with_markers


def test_directory_used_for_heading_level_detection():
    """
    Verifies that TOC entries and their inferred levels (H1..H4) improve heading hierarchy
    detection in reconstruct_title_hierarchy, infer_heading_hierarchy, and post_process_structure,
    even when headings are unnumbered or flattened to '#' / plain lines by OCR.
    """
    info = check_document_directories(PHYSIK_VERZEICHNISSE_PDF, max_pages=20)

    flattened_md = (
        "((45))\n\n"
        "# Kapitel 5: Wellenoptik und Quantenphysik\n\n"
        "# 5.1 Interferenz und Beugung am Doppelspalt\n\n"
        "Im Jahr 1802 wies Thomas Young die Wellennatur des Lichts nach.\n\n"
        "# Versuchsaufbau mit dem Doppelspalt\n\n"
        " kohärentes Laserlicht trifft auf zwei parallele Spalte.\n\n"
        "((46))\n\n"
        "Herleitung der Gangunterschiedsformel\n\n"
        "Für den Gangunterschied gilt eine einfache geometrische Beziehung.\n\n"
        "# 5.2 Optisches Gitter und hochauflösende Spektroskopie\n\n"
        "Ein optisches Gitter besteht aus vielen Spalten.\n\n"
        "((47))\n\n"
        "## Photoelektrischer Effekt und Lichtquantenhypothese\n\n"
        "Albert Einstein deutete den Photoeffekt 1905 über Lichtquanten.\n\n"
        "# Bild 5.1: Historisches Doppelspalt-Interferenzmuster nach Thomas Young\n"
    )

    reconstructed = reconstruct_title_hierarchy(flattened_md, directory_info=info)
    assert "# Kapitel 5: Wellenoptik und Quantenphysik" in reconstructed
    assert "## 5.1 Interferenz und Beugung am Doppelspalt" in reconstructed
    assert "### Versuchsaufbau mit dem Doppelspalt" in reconstructed
    assert "#### Herleitung der Gangunterschiedsformel" in reconstructed
    assert "## 5.2 Optisches Gitter und hochauflösende Spektroskopie" in reconstructed
    assert "### Photoelektrischer Effekt und Lichtquantenhypothese" in reconstructed
    # Picture/figure captions from Bildverzeichnis/Abbildungsverzeichnis must not remain H1/H2 chapter headings
    assert "\n# Bild 5.1:" not in reconstructed
    assert "\n## Bild 5.1:" not in reconstructed

    inferred = infer_heading_hierarchy(flattened_md, directory_info=info)
    assert "# Kapitel 5: Wellenoptik und Quantenphysik" in inferred
    assert "## 5.1 Interferenz und Beugung am Doppelspalt" in inferred
    assert "### Versuchsaufbau mit dem Doppelspalt" in inferred
    assert "#### Herleitung der Gangunterschiedsformel" in inferred
    assert "## 5.2 Optisches Gitter und hochauflösende Spektroskopie" in inferred
    assert "### Photoelektrischer Effekt und Lichtquantenhypothese" in inferred

    post_processed = post_process_structure(flattened_md, directory_info=info)
    assert "# Kapitel 5: Wellenoptik und Quantenphysik" in post_processed
    assert "## 5.1 Interferenz und Beugung am Doppelspalt" in post_processed
    assert "### Versuchsaufbau mit dem Doppelspalt" in post_processed
    assert "#### Herleitung der Gangunterschiedsformel" in post_processed
    assert "## 5.2 Optisches Gitter und hochauflösende Spektroskopie" in post_processed
    assert "### Photoelektrischer Effekt und Lichtquantenhypothese" in post_processed


def test_upload_and_page_count_endpoints_return_directory_check_info():
    """
    Verifies that POST /api/upload and POST /api/pdf/page-count run the fast directory check
    and return both the detected directories and the directory-resolved physical_start_page.
    """
    client = TestClient(app)

    with open(PHYSIK_VERZEICHNISSE_PDF, "rb") as f:
        pdf_bytes = f.read()

    # 1. Test POST /api/pdf/page-count
    res_pc = client.post(
        "/api/pdf/page-count",
        files={"file": ("sek2_physik_verzeichnisse.pdf", pdf_bytes, "application/pdf")},
    )
    assert res_pc.status_code == 200
    pc_data = res_pc.json()
    assert pc_data["page_count"] == 4
    assert pc_data["physical_start_page"] == 44
    assert "directories" in pc_data
    assert pc_data["directories"]["has_toc"] is True
    assert pc_data["directories"]["has_list_of_figures"] is True
    assert pc_data["directories"]["has_list_of_tables"] is True
    assert pc_data["directories"]["has_list_of_pictures"] is True

    # 2. Test POST /api/upload
    res_up = client.post(
        "/api/upload",
        files={"file": ("sek2_physik_verzeichnisse.pdf", pdf_bytes, "application/pdf")},
    )
    assert res_up.status_code == 200
    up_data = res_up.json()
    task_id = up_data["task_id"]
    try:
        assert up_data["page_count"] == 4
        assert up_data["physical_start_page"] == 44
        assert "directories" in up_data
        assert up_data["directories"]["has_any_directory"] is True
        assert set(up_data["directories"]["detected_types"]) == {
            "Inhaltsverzeichnis",
            "Abbildungsverzeichnis",
            "Tabellenverzeichnis",
            "Bildverzeichnis",
        }

        # Check task state endpoint includes directory_info
        state_res = client.get(f"/api/tasks/{task_id}/state")
        assert state_res.status_code == 200
        state_data = state_res.json()
        assert state_data["physical_start_page"] == 44
        assert state_data["directories"]["has_toc"] is True

        # Check system prompt includes directory hierarchy context for the task
        sys_prompt = _build_system_prompt("uebertragungsregeln_09_2025", task_id, 0, chunked=False)
        assert "ERKANNTE VERZEICHNISSE" in sys_prompt
        assert "Versuchsaufbau mit dem Doppelspalt" in sys_prompt
        assert "### " in sys_prompt
        assert "#### " in sys_prompt
    finally:
        client.delete(f"/api/tasks/{task_id}")


def test_sek2_physik_verzeichnisse_golden_files_pass_a11y_linter():
    """
    Verifies that the golden ground truth files for sek2_physik_verzeichnisse exist
    and pass the FIBS 09/2025 accessibility linter with 100/100.
    """
    golden_dir = os.path.join(PROJECT_ROOT, "testdata", "golden")
    raw_path = os.path.join(golden_dir, "sek2_physik_verzeichnisse.raw.golden.md")
    ueb_path = os.path.join(golden_dir, "sek2_physik_verzeichnisse.uebertragungsregeln_09_2025.golden.md")

    assert os.path.exists(raw_path)
    assert os.path.exists(ueb_path)

    with open(ueb_path, "r", encoding="utf-8") as f:
        ueb_md = f.read()

    for p in (44, 45, 46, 47):
        assert f"(({p}))" in ueb_md

    report = lint_markdown(ueb_md)
    assert report.score == 100, f"Linter issues: {report.issues}"
    assert report.passed is True


def test_directory_edge_cases_table_captions_leader_dots_and_partial_pages():
    """
    Verifies edge cases:
    - Table captions from Tabellenverzeichnis demoted from H1/H2 to H3 (###).
    - Directory leader dots ('........ 45') stripped cleanly in post_process_structure
      without turning into fill-in-the-blank '_..._' placeholders.
    - Partial page range markdown markers repaired accurately via directory votes + propagation.
    - max_pages parameter strictly caps inspected pages.
    """
    info_1 = check_document_directories(PHYSIK_VERZEICHNISSE_PDF, max_pages=1)
    assert info_1["checked_pages"] == 1
    assert info_1["has_toc"] is True

    info = check_document_directories(PHYSIK_VERZEICHNISSE_PDF, max_pages=20)

    # 1. Table caption demotion + leader dots cleanup + wrong page markers on a 2-page slice
    slice_md = (
        "((1))\n\n"
        "# Inhaltsverzeichnis\n\n"
        "- Kapitel 5: Wellenoptik und Quantenphysik ................ 45\n"
        "- 5.2 Optisches Gitter und hochauflösende Spektroskopie ... 46\n\n"
        "((2))\n\n"
        "# 5.2 Optisches Gitter und hochauflösende Spektroskopie\n\n"
        "# Tab. 5.1: Wellenlängen und Beugungswinkel ausgewählter Spektrallinien\n\n"
        "| Spektrallinie | Wellenlänge |\n"
        "| :--- | :--- |\n"
        "| Quecksilber | 404,7 nm |\n"
    )
    processed = post_process_structure(slice_md, directory_info=info)
    # Leader dots must not become _..._
    assert "_..._ 45" not in processed
    assert "-\tKapitel 5: Wellenoptik und Quantenphysik 45" in processed
    # Section 5.2 must be H2 (##) and Tab. 5.1 must be H3 (###), not H1 (#)
    assert "## 5.2 Optisches Gitter und hochauflösende Spektroskopie" in processed
    assert "### Tab. 5.1: Wellenlängen und Beugungswinkel ausgewählter Spektrallinien" in processed
    # Page 2 of slice has 5.2 & Tab. 5.1 (page 46), so markers become ((45)) and ((46))
    assert "((46))" in processed


def test_monotonic_page_sequence_rejects_outliers_and_replaces_wrong_markers(tmp_path):
    """
    Regression test for TODO 'Nicht-monotone Seitenzahlen nach Infinity-Extraktion':
    1. _resolve_page_sequence must strictly return a monotonic sequence even when OCR detects
       noisy non-monotonic outliers (e.g. [24, None, None, 23, 28, None, 90, None, 18]).
    2. apply_directory_page_numbers must never produce non-monotonic markers when spurious
       directory entry matches vote for out-of-order page numbers.
    3. insert_page_numbers_from_metadata must replace pre-existing wrong/non-monotonic ((num))
       markers emitted by an extractor instead of inserting new markers alongside them.
    """
    import re
    from backend.services.extraction_service import _resolve_page_sequence

    # 1. _resolve_page_sequence with scattered non-monotonic outliers and no duplicate offset
    noisy_detected = [28, None, None, 23, None, 90, None, 18]
    seq = _resolve_page_sequence(noisy_detected, fallback_start_page=1)
    assert seq == [seq[0] + i for i in range(len(noisy_detected))], f"Non-monotonic sequence: {seq}"

    # 2. apply_directory_page_numbers with conflicting out-of-order votes across segments
    fake_dir_info = {
        "has_any_directory": True,
        "physical_start_page": 28,
        "page_numbers": [28, 29, 30, 31, 32],
        "toc_entries": [
            {"title": "Kapitel Alpha Grundlagen", "clean_title": "Kapitel Alpha Grundlagen", "page": 28, "level": 1},
            {"title": "Übung 90 Wiederholung", "clean_title": "Übung 90 Wiederholung", "page": 90, "level": 3},
            {"title": "Rückblick Seite 18", "clean_title": "Rückblick Seite 18", "page": 18, "level": 3},
        ],
        "figure_entries": [],
        "table_entries": [],
        "picture_entries": [],
    }
    noisy_md = (
        "((24))\n\n# Kapitel Alpha Grundlagen\n\nErster Abschnitt.\n\n"
        "((23))\n\nZweiter Abschnitt mit Text.\n\n"
        "((90))\n\n### Übung 90 Wiederholung\n\nAufgabentext.\n\n"
        "((18))\n\n### Rückblick Seite 18\n\nWeiterer Text.\n\n"
        "((22))\n\nFünfter Abschnitt.\n"
    )
    repaired_md = apply_directory_page_numbers(noisy_md, fake_dir_info)
    markers = [int(m) for m in re.findall(r"\(\((\d+)\)\)", repaired_md)]
    assert markers == [28, 29, 30, 31, 32], f"Expected monotonic [28..32], got {markers}"

    # 3. insert_page_numbers_from_metadata when extractor already injected wrong ((24)), ((23)), ((90)), ((18))
    blocks = [
        {"type": "heading", "text": "# Kapitel Alpha Grundlagen", "page_idx": 0},
        {"type": "text", "text": "Zweiter Abschnitt mit Text.", "page_idx": 1},
        {"type": "heading", "text": "### Übung 90 Wiederholung", "page_idx": 2},
        {"type": "heading", "text": "### Rückblick Seite 18", "page_idx": 3},
        {"type": "text", "text": "Fünfter Abschnitt.", "page_idx": 4},
    ]
    json_path = tmp_path / "doc_content_list.json"
    json_path.write_text(json.dumps(blocks), encoding="utf-8")

    fixed_md = insert_page_numbers_from_metadata(
        noisy_md,
        str(json_path),
        "28-32",
        directory_info=None,
    )
    fixed_markers = [int(m) for m in re.findall(r"\(\((\d+)\)\)", fixed_md)]
    assert fixed_markers == [28, 29, 30, 31, 32], f"Expected [28, 29, 30, 31, 32], got {fixed_markers}"


