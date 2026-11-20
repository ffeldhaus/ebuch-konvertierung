"""Unit tests for FIBS PDF/DOCX -> Markdown rules synchronization (scripts/sync_rules_markdown.py)."""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from docx import Document
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from scripts.sync_rules_markdown import (
    MANIFEST_FILENAME,
    ascii_markdown_filename,
    main,
    normalize_pdf_artifacts,
    sync_rules_markdown,
)


def _create_sample_fibs_pdf(pdf_path: Path, body_page_1: str, body_page_2: str | None = None) -> None:
    """Builds a minimal PDF with FIBS running headers and page footers using ReportLab."""
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    pages = [body_page_1] + ([body_page_2] if body_page_2 else [])
    for idx, body in enumerate(pages, start=1):
        y = 800.0
        for hdr_line in (
            "Förderzentrum für die",
            "integrative",
            "Beschulung blinder und sehbehinderter",
            "SuS",
        ):
            c.drawString(50.0, y, hdr_line)
            y -= 14.0
        y -= 20.0
        for ln in body.splitlines():
            c.drawString(50.0, y, ln)
            y -= 16.0
        c.drawString(290.0, 40.0, str(idx))
        c.showPage()
    c.save()


def _create_sample_fibs_docx(docx_path: Path) -> None:
    """Builds a sample DOCX containing headings 1-4, bold runs, list items, and a table."""
    doc = Document()
    doc.add_heading("Bruchschreibweisen in Latex", level=1)
    doc.add_heading("Unterabschnitt Brüche", level=2)
    doc.add_heading("Detailregel", level=3)
    doc.add_heading("Feinregel", level=4)

    p = doc.add_paragraph()
    p.add_run("Hier muss es richtig heißen: ")
    bold_run = p.add_run(r"\f{1}{2}x ist korrekt")
    bold_run.bold = True

    doc.add_paragraph("Einfache Zahlenbrüche wie 1/1.000.000", style="List Bullet")

    tbl = doc.add_table(rows=2, cols=2)
    tbl.cell(0, 0).text = "Voll-LaTeX"
    tbl.cell(0, 1).text = "Minimiert"
    tbl.cell(1, 0).text = r"\frac{a}{b}"
    tbl.cell(1, 1).text = r"\f{a}{b}"
    doc.save(str(docx_path))


def test_ascii_markdown_filename_normalizes_nfc_nfd_and_umlauts():
    """Verifies NFC/NFD normalization and German umlaut transliteration for .md basenames."""
    nfd_name = unicodedata.normalize("NFD", "Übertragungsregeln_Stand_09_2025.pdf")
    assert ascii_markdown_filename(nfd_name) == "Uebertragungsregeln_Stand_09_2025.md"
    assert ascii_markdown_filename("Größen_Bücher_Ökologie_ß.docx") == "Groessen_Buecher_Oekologie_ss.md"
    assert (
        ascii_markdown_filename("Latex-Handreichung_FIBS_2012_Stand_2025.pdf")
        == "Latex-Handreichung_FIBS_2012_Stand_2025.md"
    )


def test_normalize_pdf_artifacts_cleans_decomposed_umlauts_and_math_symbols():
    """Verifies cleanup of LaTeX OT1 umlaut artifacts and math tilde/caret/degree symbols."""
    raw = "B¨ucher, a¨quivalent, Gr¨oßen, o¨ffnen, u¨ber, ¨Ubertragung, ¨Ose, ¨Ubung, ∼a, xˆ2, 90◦"
    cleaned = normalize_pdf_artifacts(raw)
    assert cleaned == "Bücher, äquivalent, Größen, öffnen, über, Übertragung, Öse, Übung, ~a, x^2, 90°"


def test_sync_rules_markdown_converts_pdf_and_docx_and_tracks_sha256(tmp_path: Path):
    """Verifies initial generation, idempotence, SHA-256 change detection, --check, and --force."""
    # Empty directory is a clean no-op
    assert sync_rules_markdown(tmp_path) == []
    assert main(["--rules-dir", str(tmp_path), "--check"]) == 0

    pdf_file = tmp_path / "Übertragungsregeln_Test.pdf"
    docx_file = tmp_path / "FIBS_Bruchschreibweisen_Test.docx"
    _create_sample_fibs_pdf(pdf_file, "Kapitel 1: Formeln mit xˆ2 und Gr¨oßen", "Kapitel 2: Br¨uche")
    _create_sample_fibs_docx(docx_file)

    # Before syncing, --check reports stale files (exit code 1)
    assert main(["--rules-dir", str(tmp_path), "--check"]) == 1

    synced = sync_rules_markdown(tmp_path)
    assert synced == [
        "FIBS_Bruchschreibweisen_Test.md",
        "Uebertragungsregeln_Test.md",
    ]
    assert main(["--rules-dir", str(tmp_path), "--check"]) == 0

    # Second run without changes is a no-op
    assert sync_rules_markdown(tmp_path) == []

    # Verify PDF Markdown content
    pdf_md = (tmp_path / "Uebertragungsregeln_Test.md").read_text(encoding="utf-8")
    assert "<!-- Seite 1 -->" in pdf_md
    assert "<!-- Seite 2 -->" in pdf_md
    assert "Förderzentrum für die" not in pdf_md
    assert "Kapitel 1: Formeln mit x^2 und Größen" in pdf_md
    assert "Kapitel 2: Brüche" in pdf_md

    # Verify DOCX Markdown content
    docx_md = (tmp_path / "FIBS_Bruchschreibweisen_Test.md").read_text(encoding="utf-8")
    assert "## Bruchschreibweisen in Latex" in docx_md
    assert "### Unterabschnitt Brüche" in docx_md
    assert "#### Detailregel" in docx_md
    assert "##### Feinregel" in docx_md
    assert r"**\f{1}{2}x ist korrekt**" in docx_md
    assert "-\tEinfache Zahlenbrüche wie 1/1.000.000" in docx_md
    assert "<Tabelle>\nVoll-LaTeX\tMinimiert\n\\frac{a}{b}\t\\f{a}{b}\n</Tabelle>" in docx_md

    # Manifest tracks both source and markdown SHA-256 digests
    manifest = json.loads((tmp_path / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert "Übertragungsregeln_Test.pdf" in manifest
    assert manifest["Übertragungsregeln_Test.pdf"]["markdown_file"] == "Uebertragungsregeln_Test.md"
    assert len(manifest["Übertragungsregeln_Test.pdf"]["sha256"]) == 64
    assert len(manifest["Übertragungsregeln_Test.pdf"]["markdown_sha256"]) == 64

    # Modifying source PDF triggers regeneration of only the modified file
    _create_sample_fibs_pdf(pdf_file, "Aktualisierter Regeltext auf Seite 1")
    assert main(["--rules-dir", str(tmp_path), "--check"]) == 1
    resynced = sync_rules_markdown(tmp_path)
    assert resynced == ["Uebertragungsregeln_Test.md"]
    assert "Aktualisierter Regeltext auf Seite 1" in (
        tmp_path / "Uebertragungsregeln_Test.md"
    ).read_text(encoding="utf-8")

    # --force regenerates both files even when hashes match
    forced = sync_rules_markdown(tmp_path, force=True)
    assert len(forced) == 2
