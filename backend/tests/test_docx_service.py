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


def test_docx_underscore_bold_runs_and_clean_roundtrip(tmp_path) -> None:
    """Verifies 4a: _Wort_ exports as '_' + [B]'Wort' + '_' without Word underline,
    leaves v_1 / v_2 subscripts plain, strips _..._ inside headings, and round-trips as _Wort_.
    """
    docx_path = str(tmp_path / "fibs_bold.docx")
    src = (
        "## 1.2 _Wichtige_ Größen\n\n"
        "Die Geschwindigkeiten v_1 und v_2 zeigen ein _deutliches_ Maximum."
    )
    convert_markdown_to_docx(src, docx_path)

    doc = Document(docx_path)
    non_empty = [p for p in doc.paragraphs if p.text.strip()]
    assert non_empty[0].text == "1.2 Wichtige Größen"

    body_p = non_empty[1]
    runs_tuple = [(r.text, r.bold, r.underline) for r in body_p.runs]
    assert ("_", None, None) in runs_tuple
    assert ("deutliches", True, None) in runs_tuple
    assert not any(r.bold is True and "1 und v" in r.text for r in body_p.runs)

    roundtripped = extract_markdown_from_docx(docx_path)
    assert "_deutliches_" in roundtripped
    assert "_*deutliches*_" not in roundtripped
    assert "**_deutliches_**" not in roundtripped
    assert "v_1 und v_2" in roundtripped


def test_docx_bidirectional_worterklaerungen_bookmarks_and_frontmatter_anmerkung(tmp_path) -> None:
    """Verifies 5a: bidirectional OpenXML bookmarks/hyperlinks (S{P}_{n} <-> S{P}_{n}a)
    and frontmatter <Anmerkung> list preservation.
    """
    docx_path = str(tmp_path / "glossary_links.docx")
    src = (
        "<Anmerkung>\n"
        "Informationen zur Übertragung:\n"
        "-\tRandspalten wurden integriert.\n"
        "-\tWorterklärungen sind verlinkt.\n"
        "</Anmerkung>\n\n"
        "((304))\n\n"
        "### Stoffwechsel\n\n"
        "Die Homöostase^1 sichert konstante Bedingungen bei 10^3 Teilchen.\n\n"
        "#### Worterklärungen\n\n"
        "-\t^1: Aufrechterhaltung des inneren Milieus.\n"
    )
    convert_markdown_to_docx(src, docx_path)

    doc = Document(docx_path)
    full_xml = doc.element.xml
    assert 'w:name="S304_1"' in full_xml
    assert 'w:anchor="S304_1a"' in full_xml
    assert 'w:name="S304_1a"' in full_xml
    assert 'w:anchor="S304_1"' in full_xml
    # Math exponent 10^3 must NOT be turned into a glossary bookmark
    assert 'S304_3' not in full_xml

    # Frontmatter <Anmerkung> bullet items use Liste/List paragraph style with 1 cm hanging indent
    list_paras = [
        p for p in doc.paragraphs if "Randspalten wurden integriert." in p.text
    ]
    assert len(list_paras) == 1
    assert abs(list_paras[0].paragraph_format.left_indent.cm - 1.0) < 1e-3

    # Round-trip back to Markdown keeps ^1 clean (never *^1*) and reconstructs <Anmerkung>
    md_back = extract_markdown_from_docx(docx_path)
    assert "Homöostase^1 sichert" in md_back
    assert "*^1*" not in md_back
    assert "<Anmerkung>\nInformationen zur Übertragung:" in md_back


def test_docx_zero_page_breaks_fibs_blank_lines_and_fibs_kopf_metadata(tmp_path) -> None:
    """Verifies 6a (zero hard page breaks + spread bookmark), 6b (FIBS blank lines),
    and 6c (populated FIBS-Kopf without '(())' placeholder).
    """
    import os

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    dotx_path = os.path.join(
        base_dir, "assets", "templates", "Dokumentenvorlage FIBS 25.05.2025_NEU.dotx"
    )
    out_path = str(tmp_path / "fibs_export.docx")

    md = (
        "((297))\n\n"
        "### Material\n\n"
        "#### M1 Versuchsaufbau\n\n"
        "<Bild> Grafik:\nBeschreibung: Schematischer Aufbau.\n</Bild>\n\n"
        "Erklärender Absatz nach dem Bild.\n\n"
        "<Tabelle>\n\n| A | B |\n| :--- | :--- |\n| 1 | 2 |\n\n</Tabelle>\n\n"
        "<Tabelle>\n\n| C | D |\n| :--- | :--- |\n| 3 | 4 |\n\n</Tabelle>\n\n"
        "##### Aufgaben\n\n"
        "##### 1\n\n"
        "Beschreiben Sie den Versuch.\n\n"
        "##### 2\n\n"
        "Werten Sie die Daten aus.\n\n"
        "((316)) / ((317))\n\n"
        "## 4.2 Zusammenfassung\n\n"
        "Abschlusstext.\n"
    )
    meta = {
        "fach": "Naturwissenschaften",
        "titel": "Musterband Oberstufe",
        "verlag": "Beispielverlag",
        "isbn": "978-3-12-000000-0",
    }
    convert_markdown_to_docx(md, out_path, template_path=dotx_path, doc_metadata=meta)

    doc = Document(out_path)
    xml_str = doc.element.xml

    # 6a: Zero hard page breaks and spread bookmark page_316 present
    assert 'w:type="page"' not in xml_str
    assert 'w:name="page_297"' in xml_str
    assert 'w:name="page_316"' in xml_str

    texts = [p.text for p in doc.paragraphs]

    # 6c: Populated FIBS-Kopf and removed '(())' placeholder
    assert "Fach: Naturwissenschaften" in texts
    assert "Titel: Musterband Oberstufe" in texts
    assert "Verlag: Beispielverlag" in texts
    assert "ISBN: 978-3-12-000000-0" in texts
    assert "Seite: 297 bis 317" in texts
    assert "(())" not in texts

    # 6b: Exact FIBS blank-line placement
    idx_297 = texts.index("((297))")
    # No blank line between ((297)) and first heading 'Material', nor between stacked headings 'Material' -> 'M1 Versuchsaufbau'
    assert texts[idx_297 + 1] == "Material"
    assert texts[idx_297 + 2] == "M1 Versuchsaufbau"
    assert texts[idx_297 + 3].startswith("<Bild>")
    # 1 blank line after </Bild> before Standard body paragraph
    assert texts[idx_297 + 4] == ""
    assert texts[idx_297 + 5] == "Erklärender Absatz nach dem Bild."

    # 1 blank line between two <Tabelle> blocks
    idx_end_tab1 = texts.index("</Tabelle>")
    assert texts[idx_end_tab1 + 1] == ""
    assert texts[idx_end_tab1 + 2] == "<Tabelle>"

    # Stacked 'Aufgaben' -> '1' -> 'Beschreiben...' (no blank lines), then 1 blank line before '2'!
    idx_aufg = texts.index("Aufgaben")
    assert texts[idx_aufg + 1] == "1"
    assert texts[idx_aufg + 2] == "Beschreiben Sie den Versuch."
    assert texts[idx_aufg + 3] == ""
    assert texts[idx_aufg + 4] == "2"

    # 1 blank line before ((316)) / ((317)), and NO blank line between ((316)) / ((317)) and '4.2 Zusammenfassung'
    idx_spread = texts.index("((316)) / ((317))")
    assert texts[idx_spread - 1] == ""
    assert texts[idx_spread + 1] == "4.2 Zusammenfassung"
    assert texts[idx_spread + 2] == "Abschlusstext."

