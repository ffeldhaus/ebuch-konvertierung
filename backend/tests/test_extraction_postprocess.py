"""Unit tests for engine-neutral extraction post-processing and hybrid Docling fusion."""

import json
import os
import tempfile

from backend.services.extraction_postprocess import (
    apply_extraction_postprocess,
    associate_image_captions,
    clean_markdown_fences,
    clean_running_headers_and_footers,
    convert_html_tables_to_markdown,
    fix_escaped_dollars,
    fuse_vlm_page_with_docling,
    reconstruct_title_hierarchy,
    recover_table_truncation,
    recover_text_truncation,
    sanitize_runaway_repetitions,
)


def test_recover_text_truncation_dehyphenates():
    """Verifies de-hyphenation across line and page boundaries."""
    # Split across line
    raw = "Das ist ein Brechungs-\ngesetz der Optik."
    res = recover_text_truncation(raw)
    assert "Brechungsgesetz" in res

    # Split across page boundary
    raw_page = "Ein schönes Schmet-\n((12))\nterlingsexemplar."
    res_page = recover_text_truncation(raw_page)
    assert "((12))" in res_page
    assert "Schmetterlingsexemplar" in res_page

    # Capitalized German noun split across page boundary with trailing period
    # (must lowercase part2 when part1 ends with lowercase, keep period before ((86)), and not glue ((86)) inline)
    raw_cap_noun = "treibt ihn dies an den Rand der totalen Selbstauf-\n\n((86))\n\nGabe. Dieser existentielle Tiefpunkt markiert den Wendepunkt."
    res_cap_noun = recover_text_truncation(raw_cap_noun)
    assert "Selbstaufgabe." in res_cap_noun
    assert "SelbstaufGabe" not in res_cap_noun
    assert "Selbstaufgabe.\n\n((86))\n\nDieser" in res_cap_noun


def test_recover_text_truncation_joins_soft_wraps():
    """Verifies soft line-wrap joining within paragraphs."""
    raw = "Hier ist ein langer Satz,\nder auf der nächsten Zeile weitergeht."
    res = recover_text_truncation(raw)
    assert "Hier ist ein langer Satz, der auf der nächsten Zeile weitergeht." in res


def test_sanitize_runaway_repetitions_preserves_tables_and_blanks():
    """Verifies runaway repetition stripping while preserving table separators and blanks."""
    # Padded markdown table separator and worksheet blanks must NEVER be deleted
    table_and_blanks = (
        "| Material            | Brechungsindex n   |\n"
        "|---------------------|--------------------|\n"
        "| Vakuum              | 1                  |\n\n"
        "Rechnung: ________________________ Antwort: ________________________"
    )
    cleaned = sanitize_runaway_repetitions(table_and_blanks)
    assert "|---------------------|--------------------|" in cleaned
    assert "________________________" in cleaned

    # Runaway alphanumeric loop must still be stripped
    runaway = "Normaler Text " + ("0" * 50) + " Ende."
    cleaned_runaway = sanitize_runaway_repetitions(runaway)
    assert "0" * 20 not in cleaned_runaway
    assert "Normaler Text" in cleaned_runaway


def test_reconstruct_title_hierarchy_numbering():
    """Verifies ISO/DIN decimal heading hierarchy reconstruction."""
    raw = (
        "# 1. Einleitung\n\n"
        "Text.\n\n"
        "# 1.1 Optische Phänomene\n\n"
        "Text.\n\n"
        "# 1.1.1 Die Lichtbrechung\n\n"
        "Text.\n\n"
        "# 1.1.1.1 Mathematische Herleitung\n\n"
        "Text.\n"
    )
    res = reconstruct_title_hierarchy(raw)
    assert "# 1. Einleitung" in res
    assert "## 1.1 Optische Phänomene" in res
    assert "### 1.1.1 Die Lichtbrechung" in res
    assert "#### 1.1.1.1 Mathematische Herleitung" in res


def test_reconstruct_title_hierarchy_keywords():
    """Verifies keyword-based heading hierarchy reconstruction."""
    raw = (
        "# Kapitel 3: Mechanik\n\n"
        "# Versuch: Pendelbewegung\n\n"
        "# Aufgabe 4: Berechnen Sie die Frequenz\n\n"
        "# Merksatz: Die Schwingungsdauer ist konstant\n"
    )
    res = reconstruct_title_hierarchy(raw)
    assert "# Kapitel 3: Mechanik" in res
    assert "### Versuch: Pendelbewegung" in res
    assert "### Aufgabe 4: Berechnen Sie die Frequenz" in res
    assert "**Merksatz: Die Schwingungsdauer ist konstant**" in res


def test_reconstruct_title_hierarchy_bbox_clustering():
    """Verifies bounding-box font-height clustering for heading levels."""
    raw = (
        "# Hauptkapitel\n\n"
        "Text.\n\n"
        "# Unterabschnitt\n\n"
        "Text.\n"
    )
    content_list = [
        {"type": "title", "text": "Hauptkapitel", "text_level": 1, "bbox": [10, 10, 200, 40]},  # height 30 -> H1
        {"type": "title", "text": "Unterabschnitt", "text_level": 1, "bbox": [10, 60, 200, 80]},  # height 20 -> H2
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(content_list, f)
        temp_json = f.name

    try:
        res = reconstruct_title_hierarchy(raw, content_list_path=temp_json)
        assert "# Hauptkapitel" in res
        assert "## Unterabschnitt" in res
    finally:
        if os.path.exists(temp_json):
            os.remove(temp_json)


def test_recover_table_truncation_html():
    """Verifies merging of HTML tables split across page boundaries."""
    raw = (
        "<table><tr><td>Zeile 1</td></tr></table>\n\n"
        "((45))\n\n"
        "<table><tr><td>Zeile 2</td></tr></table>"
    )
    res = recover_table_truncation(raw)
    assert "</table>\n\n((45))\n\n<table>" not in res
    assert "Zeile 1" in res
    assert "Zeile 2" in res


def test_convert_html_tables_to_markdown():
    """Verifies conversion of HTML tables to GFM pipe tables."""
    html_md = (
        "Text davor.\n\n"
        "<table>\n"
        "  <thead>\n"
        "    <tr><th>Material</th><th>Brechungsindex $n$</th></tr>\n"
        "  </thead>\n"
        "  <tbody>\n"
        "    <tr><td>Vakuum</td><td>1</td></tr>\n"
        "    <tr><td>Wasser</td><td>1,33</td></tr>\n"
        "  </tbody>\n"
        "</table>\n\n"
        "Text danach."
    )
    res = convert_html_tables_to_markdown(html_md)
    assert "<table>" not in res
    assert "| Material | Brechungsindex $n$ |" in res
    assert "| Vakuum | 1 |" in res
    assert "| Wasser | 1,33 |" in res


def test_associate_image_captions_both_orders():
    """Verifies association of image links with captions before and after the image."""
    # Order 1: Image followed by caption
    raw1 = (
        "![](images/prism.png)\n\n"
        "Abbildung 4.1: Versuchsaufbau mit Prisma."
    )
    res1 = associate_image_captions(raw1)
    assert "![Abbildung 4.1: Versuchsaufbau mit Prisma.](images/prism.png)" in res1
    assert "Abbildung 4.1: Versuchsaufbau mit Prisma." in res1

    # Order 2: Caption followed by image (as emitted by Docling) for consecutive figures
    raw2 = (
        "Abbildung 11.49: Lichtweg mit Knick\n\n"
        "![](images/pic0.png)\n\n"
        "Abbildung 11.50: Lichtbrechung am Übergang Luft-Glas\n\n"
        "![](images/pic1.png)"
    )
    res2 = associate_image_captions(raw2)
    assert "![Abbildung 11.49: Lichtweg mit Knick](images/pic0.png)\n\nAbbildung 11.49: Lichtweg mit Knick" in res2
    assert "![Abbildung 11.50: Lichtbrechung am Übergang Luft-Glas](images/pic1.png)\n\nAbbildung 11.50: Lichtbrechung am Übergang Luft-Glas" in res2


def test_apply_extraction_postprocess_full_pipeline():
    """Verifies the end-to-end extraction post-processing pipeline."""
    raw = (
        "# Kapitel 4: Optik\n\n"
        "Das Brechungs-\ngesetz erklärt Lichtbrechung.\n\n"
        "# 4.1 Brechungsindex\n\n"
        "Formel: $$n = \\frac{c_0}{c}$$\n\n"
        "![](images/lens.jpg)\n\n"
        "Abbildung 4.2: Konvexe Linse.\n"
    )
    res = apply_extraction_postprocess(raw)
    assert "# Kapitel 4: Optik" in res
    assert "Brechungsgesetz" in res
    assert "n = \\frac{c_0}{c}" in res
    assert "<L>" not in res
    assert "![Abbildung 4.2: Konvexe Linse.](images/lens.jpg)" in res


def test_clean_running_headers_and_footers():
    """Verifies removal of recurring running headers across pages."""
    raw = (
        "((1))\n\n"
        "FAUST I - TEXTANALYSE\n\n"
        "# 1. Einleitung\n\n"
        "Text auf Seite 1.\n\n"
        "((2))\n\n"
        "FAUST I - TEXTANALYSE\n\n"
        "# 2. Hauptteil\n\n"
        "Text auf Seite 2."
    )
    cleaned = clean_running_headers_and_footers(raw)
    assert "FAUST I - TEXTANALYSE" not in cleaned
    assert "# 1. Einleitung" in cleaned
    assert "# 2. Hauptteil" in cleaned


def test_clean_running_headers_alternating_numbered_section_headers():
    """Verifies removal of alternating even/odd running chapter and section headers."""
    # Alternating even/odd numbered running headers (e.g. Kapitel 11 on even pages, 11.6. on odd pages)
    raw = (
        "((500))\n\n"
        "# Kapitel 11. Optik\n\n"
        "Text auf Seite 500.\n\n"
        "((501))\n\n"
        "## 11.6. Licht in unterschiedlichen Medien\n\n"
        "Text auf Seite 501.\n\n"
        "((502))\n\n"
        "## Kapitel 11. Optik\n\n"
        "Der Begriff der Dichte ist unabhängig von dem der\n\n"
        "((503))\n\n"
        "## 11.6. Licht in unterschiedlichen Medien\n\n"
        "optischen Dichte eines Materials."
    )
    cleaned = clean_running_headers_and_footers(raw)
    assert cleaned.count("Kapitel 11. Optik") == 1
    assert cleaned.count("11.6. Licht in unterschiedlichen Medien") == 1
    assert "# Kapitel 11. Optik" in cleaned
    assert "## 11.6. Licht in unterschiedlichen Medien" in cleaned
    assert "unabhängig von dem der\n\n((503))\n\noptischen Dichte" in cleaned


def test_fix_escaped_dollars_and_midpage_fences():
    """Verifies unescaping of inline dollar math and removal of code fences."""
    raw = "Die Geschwindigkeit beträgt \\$c_0 = 3 \\cdot 10^8\\$ m/s.\n\n```markdown\n| A | B |\n| --- | --- |\n| 1 | 2 |\n```"
    cleaned = clean_markdown_fences(fix_escaped_dollars(raw))
    assert "$c_0 = 3 \\cdot 10^8$" in cleaned
    assert "```" not in cleaned
    assert "| A | B |" in cleaned


def test_insert_page_numbers_skips_furniture_anchors_and_detects_scanned_page_numbers(tmp_path):
    """Verifies page number insertion from metadata while skipping furniture anchors."""
    from backend.services.extraction_service import insert_page_numbers_from_metadata

    blocks = [
        {"type": "page_header", "text": "500 KAPITEL 11. OPTIK", "page_idx": 0},
        {"type": "page_header", "text": "11.6. LICHT IN UNTERSCHIEDLICHEN MEDIEN 501", "page_idx": 1},
        {"type": "text", "text": "Erster Absatz auf Seite 500 über Lichtbrechung.", "page_idx": 0},
        {"type": "text", "text": "Zweiter Absatz auf Seite 501 über das Fermatsche Prinzip.", "page_idx": 1},
    ]
    cl_file = tmp_path / "scanned_content_list.json"
    cl_file.write_text(json.dumps(blocks), encoding="utf-8")

    md = (
        "Erster Absatz auf Seite 500 über Lichtbrechung.\n\n"
        "Zweiter Absatz auf Seite 501 über das Fermatsche Prinzip."
    )
    res = insert_page_numbers_from_metadata(md, str(cl_file), pages_str="")
    assert "((500))" in res
    assert "((501))" in res


def test_standardize_formulas_ocr_scanned_variables():
    """Verifies STEM formula standardization on OCR-scanned variables."""
    from backend.services.formula_service import standardize_formulas

    scanned_md = (
        "Vakuum-Lichtgeschwindigkeit von c0 = 3 · 108 m/s und Verhältnis c0 zur Ausbreitungsgeschwindigkeit cM:\n\n"
        "<!-- formula-not-decoded -->\n\n"
        "Diese Größe (Zahl) n wird Brechungsindex genannt.\n\n"
        "- α1, den Einfallswinkel im Medium 1\n"
        "- α2, den Brechungswinkel im Medium 2\n"
        "- c1, die Lichtgeschwindigkeit im Medium 1\n"
        "- n1, den Brechungsindex von Medium 1"
    )
    res = standardize_formulas(scanned_md)
    assert "$c_0 = 3 \\cdot 10^8 \\, \\text{m/s}$" in res
    assert "$$n = \\frac{c_0}{c_M}$$" in res
    assert "Größe (Zahl) $n$" in res
    assert "- $\\alpha_1$, den" in res
    assert "- $\\alpha_2$, den" in res
    assert "- $c_1$, die" in res
    assert "- $n_1$, den" in res


def test_reconstruct_title_hierarchy_splits_merged_chapter_and_section_headings():
    """Verifies splitting of merged chapter and section headings on the same line."""
    raw = (
        "((112))\n\n"
        "# Kapitel 4: Erzähltexte untersuchen 4.1 Spannung aufbauen\n\n"
        "Einleitender Absatz.\n\n"
        "# Aufgabe 1: Leseverständnis sichern\n\n"
        "# Aufgabe 2: Sprachliche Mittel untersuchen\n\n"
        "# Aufgabe 3: Perspektivwechsel schreiben\n"
    )
    res = reconstruct_title_hierarchy(raw)
    assert "# Kapitel 4: Erzähltexte untersuchen\n\n## 4.1 Spannung aufbauen" in res
    assert "### Aufgabe 1: Leseverständnis sichern" in res
    assert "### Aufgabe 2: Sprachliche Mittel untersuchen" in res
    assert "### Aufgabe 3: Perspektivwechsel schreiben" in res


def test_reconstruct_title_hierarchy_formats_callout_boxes_as_bold_not_headings():
    """Verifies callout box headers are formatted as bold text rather than headings."""
    raw = (
        "# Kapitel 2: Oberrheingraben\n\n"
        "## 2.1 Tektonik und Klima\n\n"
        "### Methode: Ein Walter-Lieth-Klimadiagramm auswerten\n\n"
        "1. Lies Ort, Höhe und Jahresmitteltemperatur ab.\n\n"
        "### Merksatz: Entstehung eines Grabenbruchs\n\n"
        "- Dehnung der Erdkruste führt zum Absinken der Grabenscholle.\n"
    )
    res = reconstruct_title_hierarchy(raw)
    assert "**Methode: Ein Walter-Lieth-Klimadiagramm auswerten**" in res
    assert "**Merksatz: Entstehung eines Grabenbruchs**" in res
    assert "### Methode:" not in res


def test_unroll_false_positive_directory_pipe_table():
    """Verifies unrolling of TOC/directory blocks falsely extracted as pipe tables."""
    raw = (
        "((44))\n\n"
        "# Inhaltsverzeichnis\n\n"
        "| Kapitel 5: Wellenoptik und Quantenphysik ................................ 45 |\n"
        "| --- |\n"
        "| 5.1 Interferenz und Beugung am Doppelspalt .............................. 45 |\n"
        "| 5.2 Optisches Gitter und hochauflösende Spektroskopie ................... 46 |\n"
    )
    res = recover_table_truncation(raw)
    assert "| --- |" not in res
    assert "- Kapitel 5: Wellenoptik und Quantenphysik" in res
    assert "- 5.1 Interferenz und Beugung am Doppelspalt" in res


def test_insert_page_numbers_does_not_match_inside_directory_page(tmp_path):
    """Verifies page-number matching does not anchor inside TOC directory lines."""
    from backend.services.extraction_service import insert_page_numbers_from_metadata

    blocks = [
        {"type": "title", "text": "Inhaltsverzeichnis", "page_idx": 0},
        {"type": "text", "text": "Kapitel 5: Wellenoptik und Quantenphysik .... 45", "page_idx": 0},
        {"type": "title", "text": "Kapitel 5: Wellenoptik und Quantenphysik", "page_idx": 1},
        {"type": "text", "text": "Im Jahr 1802 gelang Thomas Young der Nachweis.", "page_idx": 1},
    ]
    cl_file = tmp_path / "dir_content_list.json"
    cl_file.write_text(json.dumps(blocks), encoding="utf-8")

    md = (
        "# Inhaltsverzeichnis\n\n"
        "- Kapitel 5: Wellenoptik und Quantenphysik ................................ 45\n\n"
        "# Kapitel 5: Wellenoptik und Quantenphysik\n\n"
        "Im Jahr 1802 gelang Thomas Young der Nachweis."
    )
    res = insert_page_numbers_from_metadata(md, str(cl_file), pages_str="44-45")
    assert res.index("((44))") < res.index("# Inhaltsverzeichnis")
    assert res.index("- Kapitel 5: Wellenoptik") < res.index("((45))") < res.index("Im Jahr 1802")


def test_strip_indesign_slug_and_soft_hyphens():
    """Verifies removal of InDesign production slugs and soft hyphens."""
    raw = (
        "((18))\n\n"
        "Ein Mikro\u00adcontroller verarbeitet Sensor\ufffedaten in Echtzeit.\n\n"
        "DO01_0-00-123456_K02_010_029.indd   18   11.11.2025   15:08:08\n\n"
        "((19))\n\n"
        "Nächste Seite."
    )
    res = apply_extraction_postprocess(raw)
    assert "Mikrocontroller" in res
    assert "Sensordaten" in res
    assert ".indd" not in res
    assert "15:08:08" not in res


def test_rejoin_two_column_displaced_continuation_and_merge_continuation_tables():
    """Verifies rejoining of displaced two-column continuations and cross-page tables."""
    raw = (
        "((412))\n\n"
        "## 6.1 Abhängigkeit der Reaktionsgeschwindigkeit\n\n"
        "Die Abhängigkeit der enzymatischen Reaktionsgeschwindig-\n\n"
        "### Tabelle 6.1 (Teil 1): Messreihe zur Urease-Aktivität\n\n"
        "| Substrat [S] | v_0 |\n"
        "| --- | --- |\n"
        "| 0,5 | 18,2 |\n\n"
        "keit v von der Substratkonzentration [S] wurde 1913 beschrieben.\n\n"
        "((413))\n\n"
        "### Tabelle 6.1 (Fortsetzung): Messreihe bei hohen Konzentrationen\n\n"
        "| Substrat [S] | v_0 |\n"
        "| --- | --- |\n"
        "| 8,0 | 69,0 |\n"
    )
    res = apply_extraction_postprocess(raw)
    assert "Reaktionsgeschwindigkeit v von der Substratkonzentration $[S]$ wurde 1913 beschrieben." in res
    assert res.index("Reaktionsgeschwindigkeit v von der") < res.index("### Tabelle 6.1: Messreihe zur Urease-Aktivität")
    assert "Tabelle 6.1 (Fortsetzung)" not in res
    assert "| 0,5 | 18,2 |\n| 8,0 | 69,0 |" in res


def test_no_test_data_leakage_across_backend_services():
    """Verifies zero hardcoded test-document phrases across backend service modules."""
    import inspect

    from backend.services import (
        docling_extractor,
        extraction_postprocess,
        formula_service,
        llm_service,
    )

    forbidden_leaks = [
        "INUNTERSCHIEDLICHENMEDIEN",
        "Snelliussches Brechungsgesetz",
        "Die Bedeutung des Knittelverses",
        "Vers-für-Vers Metrische Analyse",
        "Leitfragen zur Erarbeitung",
        "Brechungsindex von Kronglas",
        "Lichtgeschwindigkeit im Vakuum",
        "MathML-Render-Beispiel",
        "Fortgeschrittener Arbeitsauftrag:\\n+(?:-",
        "Cytotechnologist",
        "\\pi + x^2 - 1",
    ]
    for mod in (docling_extractor, extraction_postprocess, formula_service, llm_service):
        src = inspect.getsource(mod)
        for leak in forbidden_leaks:
            assert leak not in src, f"Forbidden test-data leak '{leak}' found in {mod.__name__}"


def test_docx_spread_page_bookmark(tmp_path):
    """Verifies OpenXML bookmark generation for double-page spread markers."""
    from docx import Document

    from backend.services.docx_service import convert_markdown_to_docx

    md = "((18)) / ((19))\n\n# Kapitel 3: Der geheime Kompass\n\nText auf der Doppelseite."
    out_docx = str(tmp_path / "spread_test.docx")
    convert_markdown_to_docx(md, out_docx)
    doc = Document(out_docx)
    xml_str = doc.element.xml
    assert 'w:name="page_18_19"' in xml_str


def test_one_col_toc_unroll_and_post_process_boxes_and_split_tables():
    """Verifies 1-column TOC unrolling, didactic box wrapping, and split table merging."""
    from backend.services.fibs_postprocess import post_process_structure

    raw_toc = (
        "# Inhaltsverzeichnis\n\n"
        "| 5.1 Interferenz am Doppelspalt  45 |\n"
        "| --- |\n"
        "| 5.2 Beugung am Gitter  46 |\n"
    )
    cleaned_toc = apply_extraction_postprocess(raw_toc)
    assert "| 5.1" not in cleaned_toc
    assert "- 5.1 Interferenz am Doppelspalt 45" in cleaned_toc

    raw_bio = (
        "((412))\n\n"
        "**Bio-Kompakt: Wichtige Begriffe**\n\n"
        "- Substrat: Ausgangsstoff.\n\n"
        "### Tabelle 6.1: Messreihe (Teil 1)\n\n"
        "| [S] | v |\n"
        "| --- | --- |\n"
        "| 0,5 | 18,2 |\n\n"
        "*(Fortsetzung von Tabelle 6.1 auf der Folgeseite)*\n\n"
        "((413))\n\n"
        "### Tabelle 6.1 (Fortsetzung): Messreihe\n\n"
        "| [S] | v |\n"
        "| --- | --- |\n"
        "| 4,0 | 61,5 |\n"
    )
    stage1 = apply_extraction_postprocess(raw_bio)
    assert "(Teil 1)" not in stage1
    assert "Fortsetzung von Tabelle" not in stage1
    assert "Tabelle 6.1 (Fortsetzung)" not in stage1

    stage2 = post_process_structure(stage1, raw_markdown=stage1)
    assert "<Rahmen>\n_Bio-Kompakt: Wichtige Begriffe_" in stage2
    assert stage2.count("<Tabelle>") == 1


def test_suspended_hyphen_ergaenzungsstrich_preserved_before_prepositions_and_conjunctions():
    """Verifies preservation of German suspended hyphens (Ergänzungsstriche)."""
    from backend.services.fibs_postprocess import post_process_structure

    page_md = (
        "## Vom Ruhe- zum Aktionspotenzial\n\n"
        "Beim Übergang vom Eingangs- zur Ausgangsspannung sowie bei Auf-\n"
        "gegen Abbauprozessen treten Vor- wie Nachteile auf.\n"
        "Die Zellkompartimen- ten bleiben intakt."
    )
    fused = fuse_vlm_page_with_docling(page_md, [], 12)
    assert "Vom Ruhe- zum Aktionspotenzial" in fused
    assert "Eingangs- zur Ausgangsspannung" in fused
    assert "Vor- wie Nachteile" in fused
    assert "Zellkompartimenten" in fused

    stage1 = apply_extraction_postprocess(fused)
    assert "Vom Ruhe- zum Aktionspotenzial" in stage1
    assert "Eingangs- zur Ausgangsspannung" in stage1
    assert "Auf- gegen Abbauprozessen" in stage1
    assert "Vor- wie Nachteile" in stage1
    assert "Zellkompartimenten" in stage1

    stage2 = post_process_structure(stage1, raw_markdown=stage1)
    assert "Vom Ruhe- zum Aktionspotenzial" in stage2
    assert "Eingangs- zur Ausgangsspannung" in stage2
    assert "Auf- gegen Abbauprozessen" in stage2
    assert "Vor- wie Nachteile" in stage2
    assert "Zellkompartimenten" in stage2


def test_clean_vlm_repetition_loops_and_docling_fallback():
    """Verifies VLM repetition loop stripping and Docling non-furniture text recovery."""
    from types import SimpleNamespace

    from backend.services.extraction_postprocess import clean_vlm_repetition_loops

    loop_headings = "\n\n".join(f"#### {chr(65 + (i % 26))}" for i in range(40))
    raw_vlm = (
        "## 8.3 Kristallgitter und Festkörperphysik\n\n"
        "Festkörper besitzen eine regelmäßige Anordnung von Atomen im Raumgitter.\n\n"
        f"{loop_headings}\n\n"
        "####"
    )
    cleaned, had_loop = clean_vlm_repetition_loops(raw_vlm)
    assert had_loop is True
    assert "#### A" not in cleaned
    assert "#### Z" not in cleaned
    assert not cleaned.endswith("####")
    assert "Festkörper besitzen eine regelmäßige Anordnung" in cleaned

    docling_layout = SimpleNamespace(
        text_blocks=[
            {"type": "page_header", "text": "KAPITEL 8 FESTKÖRPERPHYSIK 293", "layer": "furniture"},
            {"type": "section_header", "text": "8.3 Kristallgitter und Festkörperphysik", "layer": "body"},
            {
                "type": "text",
                "text": "Festkörper besitzen eine regelmäßige Anordnung von Atomen im Raumgitter.",
                "layer": "body",
            },
            {
                "type": "text",
                "text": "Durch Röntgenbeugung lassen sich die Netzebenenabstände präzise bestimmen.",
                "layer": "body",
            },
            {
                "type": "text",
                "text": "Die Bragg-Gleichung beschreibt die Bedingung für konstruktive Interferenz.",
                "layer": "body",
            },
        ]
    )
    fused = fuse_vlm_page_with_docling(
        raw_vlm,
        page_images=[],
        phys_num=293,
        docling_layout=docling_layout,
    )
    assert "((293))" in fused
    assert "#### A" not in fused
    assert "KAPITEL 8 FESTKÖRPERPHYSIK 293" not in fused
    assert "Durch Röntgenbeugung lassen sich die Netzebenenabstände präzise bestimmen." in fused
    assert "Die Bragg-Gleichung beschreibt die Bedingung für konstruktive Interferenz." in fused


def test_filter_degenerate_diagram_tables_and_figure_bbox_overlap():
    """Verifies 2a: rejection of degenerate diagram pipe tables and figure-overlapping TableFormer tables."""
    from backend.services.extraction_postprocess import _is_degenerate_diagram_table

    # < 2 rows (header only) -> degenerate
    assert _is_degenerate_diagram_table("| x (ms) | y (mV) |\n| --- | --- |") is True
    # All data rows have >= 50% empty/placeholder cells -> degenerate
    assert _is_degenerate_diagram_table(
        "| Zeit t | Spannung U |\n| --- | --- |\n| 0 | |\n| 5 | - |"
    ) is True
    # <= 3 rows with only empty/placeholder data cells -> degenerate
    assert _is_degenerate_diagram_table(
        "| Kanal A | Kanal B |\n| --- | --- |\n| ... | _..._ |\n| | – |"
    ) is True
    # Valid data table -> not degenerate
    valid_tbl = "| Medium | Geschwindigkeit (km/s) |\n| --- | --- |\n| Luft | 300000 |\n| Wasser | 225000 |"
    assert _is_degenerate_diagram_table(valid_tbl) is False

    # Degenerate pipe table in VLM output is stripped, and Docling table overlapping figure bbox >= 35% is skipped
    raw_vlm = (
        "## 4.2 Messkurve im Koordinatensystem\n\n"
        "| Achse X | Achse Y |\n"
        "| --- | --- |\n"
        "| | |\n\n"
        "![](images/picture_0_0_abc.png)\n\n"
        "Abbildung 4.2: Verlauf der Messgröße."
    )
    overlapping_chart_table = (
        "| t in ms | U in mV |\n"
        "| --- | --- |\n"
        "| 1,0 | -70 |\n"
        "| 2,0 | +30 |"
    )
    docling_layout = {
        "layout_blocks": [
            {
                "type": "image",
                "text": "![](images/picture_0_0_abc.png)",
                "page_idx": 0,
                "bbox_1000": [100, 200, 600, 700],
            },
            {
                "type": "table",
                "text": overlapping_chart_table,
                "page_idx": 0,
                "bbox_1000": [150, 250, 550, 650],
            },
        ]
    }
    fused = fuse_vlm_page_with_docling(
        raw_vlm,
        page_images=["picture_0_0_abc.png"],
        phys_num=42,
        page_tables=[overlapping_chart_table],
        docling_layout=docling_layout,
        page_idx=0,
    )
    assert "Achse X" not in fused
    assert "t in ms" not in fused
    assert "Abbildung 4.2: Verlauf der Messgröße." in fused


def test_prevent_truncated_table_cells_during_vlm_docling_fusion():
    """Verifies 2b: VLM table with complete cells is not overwritten by a truncated Docling table."""
    vlm_md = (
        "## 5.1 Messwerte im Überblick\n\n"
        "| Probe | Temperatur (°C) | Leitfähigkeit (mS/cm) |\n"
        "| --- | --- | --- |\n"
        "| A | 20 | 1,45 |\n"
        "| B | 40 | 2,10 |\n"
        "| C | 60 | 2,85 |"
    )
    truncated_docling_table = (
        "| Probe | Temperatur (°C) | Leitfähigkeit (mS/cm) |\n"
        "| --- | --- | --- |\n"
        "| A | 20 | 1,45 |\n"
        "| B | 40 | 2,10 |\n"
        "| C | 60 | |"
    )
    fused = fuse_vlm_page_with_docling(
        vlm_md,
        page_images=[],
        phys_num=51,
        page_tables=[truncated_docling_table],
    )
    assert "| C | 60 | 2,85 |" in fused
    assert fused.count("| Probe |") == 1


def test_suppress_nested_and_tiny_subfigure_crops():
    """Verifies 3a: nested sub-crops (>= 65% overlap) are dropped and tiny fragments (< 1.2% page area) are merged."""
    from backend.services.extraction_postprocess import _filter_page_figure_bboxes

    # Page 1000x1000:
    # Box 0: main composite diagram [100, 100, 600, 500] (area 200,000)
    # Box 1: nested sub-panel inside Box 0 [120, 120, 350, 480] (100% contained in Box 0 -> dropped)
    # Box 2: tiny icon/voltmeter symbol [610, 200, 660, 250] (area 2,500 = 0.25% < 1.2%, gap_x=10 < 50 -> merged into Box 0)
    # Box 3: separate second figure at bottom [100, 650, 600, 900] (area 125,000 -> kept)
    boxes = [
        [100, 100, 600, 500],
        [120, 120, 350, 480],
        [610, 200, 660, 250],
        [100, 650, 600, 900],
    ]
    surviving = _filter_page_figure_bboxes(boxes, page_width=1000.0, page_height=1000.0)
    assert len(surviving) == 2
    assert surviving[0][0] == 0
    assert surviving[0][1] == (100.0, 100.0, 660.0, 500.0)
    assert surviving[1][0] == 3
    assert surviving[1][1] == (100.0, 650.0, 600.0, 900.0)


def test_preserve_marginalia_and_glossary_definitions():
    """Verifies 6a: margin glossary definitions and footnote markers are preserved even if labeled as furniture."""
    from backend.services.extraction_postprocess import _is_marginalia_or_glossary_note

    assert _is_marginalia_or_glossary_note("¹ Osmose: Gerichtete Diffusion durch eine Membran.") is True
    assert _is_marginalia_or_glossary_note("^2 Katalysator beschleunigt chemische Reaktionen.") is True
    assert _is_marginalia_or_glossary_note("1 Substrat bezeichnet den Ausgangsstoff einer Reaktion.") is True
    assert _is_marginalia_or_glossary_note("Worterklärung: Homöostase bezeichnet das Gleichgewicht.") is True
    assert _is_marginalia_or_glossary_note("500 KAPITEL 11. OPTIK") is False

    raw_vlm = "## 3.4 Stofftransport durch Membranen\n\nSemipermeable Membranen lassen nur bestimmte Teilchen passieren."
    docling_layout = {
        "furniture_by_page": {
            0: [
                {"type": "page_header", "text": "KAPITEL 3 ZELLBIOLOGIE 84", "page_idx": 0},
                {
                    "type": "page_footer",
                    "text": "¹ Semipermeabel: Halbdurchlässig für ausgewählte Moleküle.",
                    "page_idx": 0,
                },
                {
                    "type": "furniture",
                    "text": "Worterklärung: Konzentrationsgefälle ist der Unterschied der Teilchendichte.",
                    "page_idx": 0,
                },
            ]
        },
        "text_blocks_by_page": {
            0: [
                {
                    "type": "text",
                    "text": "Semipermeable Membranen lassen nur bestimmte Teilchen passieren.",
                    "page_idx": 0,
                }
            ]
        },
    }
    fused = fuse_vlm_page_with_docling(
        raw_vlm,
        page_images=[],
        phys_num=84,
        docling_layout=docling_layout,
        page_idx=0,
    )
    assert "KAPITEL 3 ZELLBIOLOGIE 84" not in fused
    assert "¹ Semipermeabel: Halbdurchlässig für ausgewählte Moleküle." in fused
    assert "Worterklärung: Konzentrationsgefälle ist der Unterschied der Teilchendichte." in fused


def test_vlm_diagram_prompt_and_custom_rules_prompt_strengthening():
    """Verifies 3c: VLM coordinate diagram axis rules and Buchkonferenz custom rules prompt instructions."""
    from backend.services.prompts import VLM_IMAGE_PROMPT, build_custom_rules_block

    assert "x-Achse:" in VLM_IMAGE_PROMPT
    assert "y-Achse:" in VLM_IMAGE_PROMPT
    assert "<Bild>...</Bild>" in VLM_IMAGE_PROMPT

    block = build_custom_rules_block("Aufgaben als ##### Überschrift 5 formatieren.")
    assert "##### Aufgaben" in block
    assert "#### M1" in block
    assert "#### Stichwort" in block







