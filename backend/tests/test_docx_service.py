"""Synthetic unit tests for DOCX export and import (run-level emphasis and list continuation)."""

from __future__ import annotations

from docx import Document

from backend.services.docx_service import convert_markdown_to_docx, extract_markdown_from_docx


def test_docx_import_preserves_run_level_bold_and_italic(tmp_path) -> None:
    """Verify run-level bold (*...*) and italic (_..._) are extracted without double-wrapping."""
    docx_path = str(tmp_path / "emphasis.docx")
    doc = Document()

    doc.add_paragraph("Kapitel 1: Mechanik", style="Heading 1")

    p_body = doc.add_paragraph(style="Normal")
    p_body.add_run("Der Begriff ")
    r_b1 = p_body.add_run("Kraft")
    r_b1.bold = True
    r_b2 = p_body.add_run("stoß")
    r_b2.bold = True
    p_body.add_run(" sowie ")
    r_it = p_body.add_run("Impulserhaltung")
    r_it.italic = True
    p_body.add_run(" sind zentral.")

    p_bullet = doc.add_paragraph(style="Normal")
    r_m = p_bullet.add_run("• Phase A:")
    r_m.bold = True
    p_bullet.add_run(" Beschreibung der ersten Phase.")

    doc.save(docx_path)

    md = extract_markdown_from_docx(docx_path)
    blocks = md.split("\n\n")
    assert "# Kapitel 1: Mechanik" in blocks
    assert "Der Begriff *Kraftstoß* sowie _Impulserhaltung_ sind zentral." in blocks
    assert "• *Phase A:* Beschreibung der ersten Phase." in blocks


def test_docx_roundtrip_does_not_double_wrap_formatted_runs(tmp_path) -> None:
    """Verify convert_markdown_to_docx -> extract_markdown_from_docx does not double-wrap *bold* or %italic%."""
    docx_path = str(tmp_path / "roundtrip.docx")
    src = "# 1 Einführung\n\nEin *fett gedruckter* und %kursiver% sowie _hervorgehobener_ Begriff."
    convert_markdown_to_docx(src, docx_path)

    extracted = extract_markdown_from_docx(docx_path)
    assert "*fett gedruckter*" in extracted
    assert "**fett gedruckter**" not in extracted
    assert "%kursiver%" in extracted
    assert "_hervorgehobener_" in extracted


def test_docx_import_generic_list_style_continuation_has_no_false_bullet(tmp_path) -> None:
    r"""Verify paragraphs with style 'List' without numPr or list marker do not get a false '-\t' prefix."""
    docx_path = str(tmp_path / "list_cont.docx")
    doc = Document()
    doc.add_paragraph("1.\tErster Aufgabenpunkt.", style="List")
    doc.add_paragraph("Fortsetzungsabsatz ohne eigenes Aufzählungszeichen.", style="List")
    doc.add_paragraph("Zweiter Punkt mit Aufzählungsformatvorlage.", style="List Bullet")
    doc.save(docx_path)

    md = extract_markdown_from_docx(docx_path)
    blocks = md.split("\n\n")
    assert "1.\tErster Aufgabenpunkt." in blocks
    assert "Fortsetzungsabsatz ohne eigenes Aufzählungszeichen." in blocks
    assert "-\tFortsetzungsabsatz ohne eigenes Aufzählungszeichen." not in blocks
    assert "-\tZweiter Punkt mit Aufzählungsformatvorlage." in blocks


def test_docx_import_merges_multipara_bild_block(tmp_path) -> None:
    """Verify multi-paragraph <Bild>...</Bild> blocks in human DOCX files are joined with single newlines."""
    docx_path = str(tmp_path / "multipara_bild.docx")
    doc = Document()
    doc.add_paragraph("<Bild> Diagramm:", style="Normal")
    doc.add_paragraph("Beschreibung mit Bildtext:", style="Normal")
    doc.add_paragraph("1. Kurve A steigt linear an.", style="Normal")
    doc.add_paragraph("</Bild>", style="Normal")
    doc.save(docx_path)

    md = extract_markdown_from_docx(docx_path)
    assert "<Bild> Diagramm:\nBeschreibung mit Bildtext:\n1. Kurve A steigt linear an.\n</Bild>" in md
