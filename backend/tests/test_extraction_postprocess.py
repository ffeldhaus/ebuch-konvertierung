"""Unit tests for engine-neutral extraction post-processing and hybrid Docling fusion."""

import json
import os
import tempfile

from backend.services.extraction_postprocess import (
    apply_extraction_postprocess,
    associate_image_captions,
    clean_duplicate_itemization,
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


def test_running_footer_with_internal_dash_and_pipe_is_stripped_with_trailing_captions():
    """Verifies stripping of running footers with internal dashes and pipe separators,
    including when 1-2 figure caption lines trail behind the footer and across pages.
    """
    footer = "Mechanik – Energieerhaltung | 43"
    raw_vlm = (
        "## 3.2 Erhaltungssatz der mechanischen Energie\n\n"
        "Kinetische Energie und potenzielle Energie wandeln sich ineinander um.\n\n"
        "Berechne die Differenz 100 - 43 als Übungswert für die Messreihe.\n\n"
        "Für ein abgeschlossenes System bleibt die Gesamtenergie konstant.\n\n"
        "Alle Reibungsverluste werden im idealisierten Modell vernachlässigt.\n\n"
        f"{footer}\n\n"
        "Abbildung 3.1: Pendelversuch zur Umwandlung von Lage- und Bewegungsenergie.\n\n"
        "Abbildung 3.2: Energieflussdiagramm des Fadenpendels."
    )
    fused = fuse_vlm_page_with_docling(raw_vlm, [], phys_num=43)
    assert footer not in fused
    assert "Berechne die Differenz 100 - 43" in fused
    assert "Abbildung 3.1: Pendelversuch" in fused
    assert "Abbildung 3.2: Energieflussdiagramm" in fused

    pages_md = (
        "((41))\n\nErster Absatz.\n\nZweiter Absatz.\n\nDritter Absatz.\n\n"
        "41 | Mechanik – Energieerhaltung\n\n"
        "Abbildung 3.0: Einstiegsversuch.\n\n"
        "((42))\n\nVierter Absatz.\n\nFünfter Absatz.\n\nSechster Absatz.\n\n"
        "Mechanik – Energieerhaltung | 42\n\n"
        "Abbildung 3.1: Zwischenstand.\n\n"
        "Abbildung 3.2: Vergleichsmessung.\n\n"
        "((43))\n\nSiebter Absatz.\n\nAchter Absatz.\n\nNeunter Absatz.\n\n"
        "Mechanik – Energieerhaltung – 43"
    )
    cleaned = clean_running_headers_and_footers(pages_md)
    assert "Mechanik – Energieerhaltung" not in cleaned
    assert "Abbildung 3.0: Einstiegsversuch." in cleaned
    assert "Abbildung 3.1: Zwischenstand." in cleaned
    assert "Abbildung 3.2: Vergleichsmessung." in cleaned


def test_clean_duplicate_itemization_reorders_swapped_column_tasks_and_preserves_normal_groups():
    """Verifies Step 7 reorders column-swapped numbered task runs (4..10 + intro + 1..3 -> intro + 1..10)
    while leaving separate normal 1..2 + 1..2 exercise groups untouched.
    """
    swapped_md = (
        "((65))\n\n"
        "## B Aufgaben zur Wärmelehre\n\n"
        "4 Berechne die benötigte Wärmemenge für 2 kg Wasser.\n\n"
        "5 Vergleiche die spezifischen Wärmekapazitäten von Kupfer und Eisen.\n"
        "6 Erkläre den Temperaturverlauf im Mischkalorimeter.\n"
        "7 Zeichne ein Temperatur-Zeit-Diagramm der Abkühlung.\n"
        "8 Bestimme den Siedepunkt bei vermindertem Druck.\n"
        "9 Beschreibe den Energieübertrag durch Wärmestrahlung.\n"
        "10 Formuliere eine Hypothese zum Schmelzvorgang.\n\n"
        "Bearbeite die folgenden Grundaufgaben mithilfe der Stoffwerttabelle.\n\n"
        "1 Nenne die Einheit der thermischen Energie.\n\n"
        "2 Lies die Wärmekapazität von Aluminium ab.\n"
        "3 Ordne die Materialien nach ihrer Wärmeleitfähigkeit.\n\n"
        "## C Weitere Übungen\n\n"
        "1 Erste einfache Übungsaufgabe.\n"
        "2 Zweite einfache Übungsaufgabe.\n\n"
        "1 Nächste kurze Kontrollfrage.\n"
        "2 Zweite kurze Kontrollfrage.\n"
    )
    cleaned = clean_duplicate_itemization(swapped_md)
    assert cleaned.index("Bearbeite die folgenden Grundaufgaben") < cleaned.index("1 Nenne die Einheit")
    last_pos = cleaned.index("Bearbeite die folgenden Grundaufgaben")
    for expected in (
        "1 Nenne die Einheit",
        "2 Lies die Wärmekapazität",
        "3 Ordne die Materialien",
        "4 Berechne die benötigte",
        "5 Vergleiche die spezifischen",
        "6 Erkläre den Temperaturverlauf",
        "7 Zeichne ein Temperatur-Zeit-Diagramm",
        "8 Bestimme den Siedepunkt",
        "9 Beschreibe den Energieübertrag",
        "10 Formuliere eine Hypothese",
    ):
        pos = cleaned.index(expected)
        assert pos > last_pos, f"Expected '{expected}' after previous item"
        last_pos = pos

    c_tail = cleaned[cleaned.index("## C Weitere Übungen") :]
    assert (
        "1 Erste einfache Übungsaufgabe.\n2 Zweite einfache Übungsaufgabe.\n\n"
        "1 Nächste kurze Kontrollfrage.\n2 Zweite kurze Kontrollfrage."
    ) in c_tail


def test_foreign_language_hallucination_guard_rebuilds_from_pdf_blocks():
    """Verifies 1a: English VLM hallucination on a German PDF page is discarded and rebuilt in reading order."""
    docling_layout = {
        "text_blocks_by_page": {
            0: [
                {
                    "type": "section_header",
                    "text": "Wärmeleitung und Konvektion in Gebäuden",
                    "page_idx": 0,
                    "bbox_1000": [80, 90, 760, 130],
                },
                {
                    "type": "text",
                    "text": (
                        "Thermische Energie strömt stets von Bereichen höherer Temperatur zu Bereichen "
                        "niedrigerer Temperatur durch Wärmeleitung, Konvektion und Wärmestrahlung."
                    ),
                    "page_idx": 0,
                    "bbox_1000": [80, 160, 470, 420],
                },
                {
                    "type": "text",
                    "text": (
                        "Moderne Wärmedämmverbundsysteme reduzieren den Wärmedurchgangskoeffizienten "
                        "von Außenwänden erheblich und senken den jährlichen Heizenergiebedarf."
                    ),
                    "page_idx": 0,
                    "bbox_1000": [510, 160, 900, 420],
                },
            ]
        }
    }
    hallucinated_vlm = (
        "![](images/thermo_0.png)\n\n"
        "Elephants are large herbivorous mammals native to sub-Saharan Africa and Southeast Asia. "
        "Aristotle was an ancient Greek philosopher and polymath whose writings covered metaphysics."
    )
    fused = fuse_vlm_page_with_docling(
        hallucinated_vlm,
        page_images=[],
        phys_num=58,
        docling_layout=docling_layout,
        page_idx=0,
    )
    assert "Elephants" not in fused
    assert "Aristotle" not in fused
    assert "## Wärmeleitung und Konvektion in Gebäuden" in fused
    assert "Wärmedämmverbundsysteme reduzieren" in fused
    assert "![](images/thermo_0.png)" in fused
    assert fused.index("## Wärmeleitung und Konvektion") < fused.index("![](images/thermo_0.png)")


def test_missing_column_and_top_title_recovery_without_loop():
    """Verifies 1a: missing columns, tasks, and top titles are recovered in reading order even when had_loop is False."""
    docling_layout = {
        "text_blocks_by_page": {
            0: [
                {
                    "type": "title",
                    "text": "Mechanische Schwingungen von Fadenpendeln",
                    "page_idx": 0,
                    "bbox_1000": [80, 85, 780, 125],
                },
                {
                    "type": "text",
                    "text": "Bei kleinen Auslenkwinkeln verläuft die Rückstellkraft näherungsweise proportional zur Auslenkung.",
                    "page_idx": 0,
                    "bbox_1000": [80, 160, 470, 380],
                },
                {
                    "type": "text",
                    "text": "Die Schwingungsdauer hängt ausschließlich von der Pendellänge und der Fallbeschleunigung ab.",
                    "page_idx": 0,
                    "bbox_1000": [510, 160, 900, 380],
                },
                {
                    "type": "text",
                    "text": "A1 Berechnen Sie die Periodendauer für ein Pendel der Länge zwei Meter.",
                    "page_idx": 0,
                    "bbox_1000": [510, 410, 900, 470],
                },
            ]
        }
    }
    partial_vlm = "Bei kleinen Auslenkwinkeln verläuft die Rückstellkraft näherungsweise proportional zur Auslenkung."
    fused = fuse_vlm_page_with_docling(
        partial_vlm,
        page_images=[],
        phys_num=72,
        docling_layout=docling_layout,
        page_idx=0,
    )
    assert "## Mechanische Schwingungen von Fadenpendeln" in fused
    assert "Die Schwingungsdauer hängt ausschließlich" in fused
    assert "A1 Berechnen Sie die Periodendauer" in fused
    assert (
        fused.index("## Mechanische Schwingungen")
        < fused.index("Bei kleinen Auslenkwinkeln")
        < fused.index("Die Schwingungsdauer hängt")
        < fused.index("A1 Berechnen Sie")
    )


def test_intra_line_ngram_loop_and_multiline_heading_cycle_cleaning():
    """Verifies 1b: intra-line n-gram loops (>250 chars) and multi-line cycles with # headings are cleaned."""
    from backend.services.extraction_postprocess import clean_vlm_repetition_loops

    intra_loop_line = "![] (https://www.physik-portal.example/diagramm" + ("-100" * 65) + ".png)"
    cycle_block = (
        "## Material A\n\n"
        "### Material B\n\n"
        "#### Das Magnetfeld stromdurchflossener Spulen\n\n"
        "Magnetische Feldlinien bilden stets geschlossene Kurven im Raum."
    )
    raw = f"Einleitender Satz zur Magnetostatik.\n\n{intra_loop_line}\n\n{cycle_block}\n\n{cycle_block}\n\n{cycle_block}"
    cleaned, had_loop = clean_vlm_repetition_loops(raw)
    assert had_loop is True
    assert "-100-100" not in cleaned
    assert "physik-portal.example" not in cleaned
    assert cleaned.count("## Material A") == 1
    assert cleaned.count("#### Das Magnetfeld stromdurchflossener Spulen") == 1
    assert "Einleitender Satz zur Magnetostatik." in cleaned


def test_in_figure_text_label_deduplication_preserves_captions_and_tasks():
    """Verifies 1b: orphan diagram labels from figure_bboxes are stripped while captions, headings, and tasks stay."""
    docling_layout = {
        "layout_blocks": [
            {
                "type": "image",
                "text": "![](images/picture_0_0_induktion.png)",
                "page_idx": 0,
                "bbox_1000": [100, 150, 880, 520],
            }
        ],
        "figure_texts_by_page": {
            0: ["Spannungsmessgerät", "Kupferspule", "Permanentmagnet", "Eisenkern"]
        },
        "heading_blocks": [
            {
                "type": "title",
                "text": "Elektromagnetische Induktion",
                "page_idx": 0,
                "bbox": [0, 0, 300, 18],
                "bbox_1000": [80, 80, 620, 120],
                "is_body_sized": False,
            }
        ],
        "text_blocks_by_page": {
            0: [
                {
                    "type": "section_header",
                    "text": "Elektromagnetische Induktion",
                    "page_idx": 0,
                    "bbox_1000": [80, 80, 620, 120],
                },
                {
                    "type": "text",
                    "text": "Bewegt man einen Magneten relativ zu einer Spule, wird eine elektrische Spannung induziert.",
                    "page_idx": 0,
                    "bbox_1000": [80, 580, 880, 660],
                },
            ]
        },
    }
    raw_vlm = (
        "## Elektromagnetische Induktion\n\n"
        "Spannungsmessgerät\n"
        "Kupferspule\n"
        "Eisenkern\n\n"
        "1 Versuchsaufbau zur elektromagnetischen Induktion\n\n"
        "Bewegt man einen Magneten relativ zu einer Spule, wird eine elektrische Spannung induziert.\n\n"
        "1 Erläutern Sie die Ursache der gemessenen Induktionsspannung.\n\n"
        "A1 Bestimmen Sie die Polung bei umgekehrter Bewegungsrichtung."
    )
    fused = fuse_vlm_page_with_docling(
        raw_vlm,
        page_images=["picture_0_0_induktion.png"],
        phys_num=91,
        docling_layout=docling_layout,
        page_idx=0,
    )
    assert "Spannungsmessgerät" not in fused
    assert "Kupferspule" not in fused
    assert "Eisenkern" not in fused
    assert "## Elektromagnetische Induktion" in fused
    assert "![](images/picture_0_0_induktion.png)\n\n1 Versuchsaufbau zur elektromagnetischen Induktion" in fused
    assert "1 Erläutern Sie die Ursache der gemessenen Induktionsspannung." in fused
    assert "A1 Bestimmen Sie die Polung bei umgekehrter Bewegungsrichtung." in fused


def test_pdf_font_span_emphasis_enrichment_single_handle(tmp_path):
    """Verifies 1c: pypdfium2 FPDFText_GetFontInfo extracts Bold/Italic spans while skipping headings and >=25-word italic intros."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    from backend.services.extraction_postprocess import extract_pdf_page_details

    pdf_file = str(tmp_path / "font_spans_test.pdf")
    c = canvas.Canvas(pdf_file, pagesize=A4)
    _pw, ph = A4

    # Large bold heading (16pt -> must NOT become inline **...** span)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(60, ph - 80, " Elektrische Leitfähigkeit von Metallen")

    # Whole-paragraph italic intro (>= 25 words -> must NOT become inline *...* span)
    c.setFont("Helvetica-Oblique", 10)
    c.drawString(60, ph - 115, "In diesem einführenden Abschnitt untersuchen wir ausführlich das Verhalten verschiedener")
    c.drawString(60, ph - 130, "metallischer Leiter unter wechselnden thermischen Bedingungen im physikalischen Schülerlabor")
    c.drawString(60, ph - 145, "anhand präziser Widerstandsmessungen mit kalibrierten digitalen Messinstrumenten und Stromquellen.")

    # Body paragraph with inline bold ('Widerstandswert') and multi-word italic ('Cuprum metallicum')
    y_body = ph - 185
    c.setFont("Helvetica", 10)
    c.drawString(60, y_body, "Der spezifische ")
    x_cur = 60 + c.stringWidth("Der spezifische ", "Helvetica", 10)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x_cur, y_body, "Widerstandswert")
    x_cur += c.stringWidth("Widerstandswert", "Helvetica-Bold", 10)
    c.setFont("Helvetica", 10)
    c.drawString(x_cur, y_body, " einer Probe aus ")
    x_cur += c.stringWidth(" einer Probe aus ", "Helvetica", 10)
    c.setFont("Helvetica-Oblique", 10)
    c.drawString(x_cur, y_body, "Cuprum metallicum")
    x_cur += c.stringWidth("Cuprum metallicum", "Helvetica-Oblique", 10)
    c.setFont("Helvetica", 10)
    c.drawString(x_cur, y_body, " steigt linear an.")
    c.showPage()
    c.save()

    details = extract_pdf_page_details(pdf_file)
    spans = details["font_spans_by_page"].get(0, [])
    span_map = {s["text"]: s["style"] for s in spans}
    assert span_map.get("Widerstandswert") == "bold"
    assert span_map.get("Cuprum metallicum") == "italic"
    assert not any("Leitfähigkeit" in s["text"] for s in spans)
    assert not any("einführenden Abschnitt" in s["text"] for s in spans)

    unformatted_vlm = (
        "## Elektrische Leitfähigkeit von Metallen\n\n"
        "In diesem einführenden Abschnitt untersuchen wir ausführlich das Verhalten verschiedener "
        "metallischer Leiter unter wechselnden thermischen Bedingungen im physikalischen Schülerlabor "
        "anhand präziser Widerstandsmessungen mit kalibrierten digitalen Messinstrumenten und Stromquellen.\n\n"
        "Der spezifische Widerstandswert einer Probe aus Cuprum metallicum steigt linear an."
    )
    fused = fuse_vlm_page_with_docling(
        unformatted_vlm,
        page_images=[],
        phys_num=14,
        docling_layout={"font_spans_by_page": {0: spans}},
        page_idx=0,
    )
    assert "**Widerstandswert**" in fused
    assert "*Cuprum metallicum*" in fused
    assert "## Elektrische Leitfähigkeit von Metallen" in fused
    assert "*In diesem einführenden Abschnitt" not in fused


def test_bare_number_captions_and_material_heading_bbox_image_matching():
    """Verifies 2a: bare-number captions pair with images while tasks/steps do not, and unmatched images match Material headings by y0."""
    raw_captions_and_tasks = (
        "## Optische Instrumente\n\n"
        "1 Historisches Spiegelteleskop mit Messingtubus\n\n"
        "2 Strahlengang an einer achromatischen Sammellinse\n\n"
        "### 1 Präzisionsmikrometer\n\n"
        "1. Licht tritt parallel zur optischen Achse in das Objektiv ein.\n\n"
        "1 Erläutern Sie die Entstehung des Zwischenbildes.\n\n"
        "2 Vergleichen Sie Linsenteleskop und Spiegelteleskop.\n\n"
        "3 Wie verändert sich die Vergrößerung bei kleinerer Okularbrennweite?"
    )
    fused = fuse_vlm_page_with_docling(
        raw_captions_and_tasks,
        page_images=["img_tel.png", "img_lens.png", "img_mic.png"],
        phys_num=63,
    )
    assert "![](images/img_tel.png)\n\n1 Historisches Spiegelteleskop mit Messingtubus" in fused
    assert "![](images/img_lens.png)\n\n2 Strahlengang an einer achromatischen Sammellinse" in fused
    assert "![](images/img_mic.png)\n\n1 Präzisionsmikrometer" in fused
    assert "### 1 Präzisionsmikrometer" not in fused
    assert "1. Licht tritt parallel" in fused
    assert "1 Erläutern Sie" in fused

    # Unmatched images matched by bbox_1000 y0 to Material A and Material B headings
    material_vlm = (
        "## Material A: Wellenausbreitung im Wasserbecken\n\n"
        "Kreisförmige Wellenfronten breiten sich gleichmäßig aus.\n\n"
        "## Material B: Interferenz an der Doppelblende\n\n"
        "Hinter den Öffnungen überlagern sich die Elementarwellen."
    )
    mat_layout = {
        "heading_blocks": [
            {
                "type": "title",
                "text": "Material A: Wellenausbreitung im Wasserbecken",
                "page_idx": 0,
                "bbox": [0, 0, 350, 16],
                "bbox_1000": [80, 90, 820, 125],
                "is_body_sized": False,
            },
            {
                "type": "title",
                "text": "Material B: Interferenz an der Doppelblende",
                "page_idx": 0,
                "bbox": [0, 0, 350, 16],
                "bbox_1000": [80, 510, 820, 545],
                "is_body_sized": False,
            },
        ],
        "layout_blocks": [
            {
                "type": "image",
                "text": "![](images/picture_0_0_matA.png)",
                "page_idx": 0,
                "bbox_1000": [120, 150, 780, 440],
            },
            {
                "type": "image",
                "text": "![](images/picture_0_1_matB.png)",
                "page_idx": 0,
                "bbox_1000": [120, 570, 780, 860],
            },
        ],
    }
    fused_mat = fuse_vlm_page_with_docling(
        material_vlm,
        page_images=["picture_0_0_matA.png", "picture_0_1_matB.png"],
        phys_num=64,
        docling_layout=mat_layout,
        page_idx=0,
    )
    pos_hdr_a = fused_mat.index("## Material A")
    pos_img_a = fused_mat.index("![](images/picture_0_0_matA.png)")
    pos_hdr_b = fused_mat.index("## Material B")
    pos_img_b = fused_mat.index("![](images/picture_0_1_matB.png)")
    assert pos_hdr_a < pos_img_a < pos_hdr_b < pos_img_b


def test_neighbor_page_context_sidecar_extraction_and_loading(tmp_path):
    """Verifies 1d: extract_pdf_pages writes .neighbors.json and load_pdf_neighbor_context loads it cleanly."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    from backend.services.extraction_service import extract_pdf_pages, load_pdf_neighbor_context

    src_pdf = str(tmp_path / "source_4p.pdf")
    c = canvas.Canvas(src_pdf, pagesize=A4)
    page_texts = [
        "Vorwort auf römischer Seite I.",
        "Inhalt auf Buchseite 10 beginnt mit einem getrennten Wort.",
        "Inhalt auf Buchseite 11 führt das Kapitel fort.",
        "Nachfolgeseite 12 schließt den Abschnitt ab.",
    ]
    for pt in page_texts:
        c.setFont("Helvetica", 11)
        c.drawString(72, 700, pt)
        c.showPage()
    c.save()

    labels = ["I", "10", "11", "12"]

    # Middle selection (pages 10-11 -> prev=I, next=12)
    mid_out = str(tmp_path / "mid.pdf")
    assert extract_pdf_pages(src_pdf, "10-11", mid_out, page_labels=labels) is True
    mid_ctx = load_pdf_neighbor_context(mid_out)
    assert mid_ctx["prev_page"] == "I"
    assert "Vorwort auf römischer Seite I." in mid_ctx["prev_text"]
    assert mid_ctx["next_page"] == "12"
    assert "Nachfolgeseite 12" in mid_ctx["next_text"]

    # Start selection (page I -> no prev keys, only next=10)
    first_out = str(tmp_path / "first.pdf")
    assert extract_pdf_pages(src_pdf, "I", first_out, page_labels=labels) is True
    first_ctx = load_pdf_neighbor_context(first_out)
    assert "prev_page" not in first_ctx
    assert "prev_text" not in first_ctx
    assert first_ctx["next_page"] == "10"

    # End selection (page 12 -> prev=11, no next keys)
    last_out = str(tmp_path / "last.pdf")
    assert extract_pdf_pages(src_pdf, "12", last_out, page_labels=labels) is True
    last_ctx = load_pdf_neighbor_context(last_out)
    assert last_ctx["prev_page"] == "11"
    assert "next_page" not in last_ctx
    assert "next_text" not in last_ctx


def test_off_page_spread_clip_filtering_and_severe_truncation_rebuild(tmp_path):
    """Verifies off-page spread text filtering, short etymology marginalia detection, and <25% recall PDF rebuild."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    from backend.services.extraction_postprocess import (
        _is_marginalia_or_glossary_note,
        extract_pdf_page_details,
    )

    # 1. Off-page spread text (x < 0 and x > page_width) is excluded from pdf_text_by_page
    spread_pdf = str(tmp_path / "spread_clip.pdf")
    c = canvas.Canvas(spread_pdf, pagesize=A4)
    pw, ph = A4
    c.setFont("Helvetica", 11)
    c.drawString(-420, ph - 120, "Verborgener Nachbartext auf der linken Druckbogenseite")
    c.drawString(pw + 80, ph - 140, "Verborgener Randtext rechts außerhalb des Zuschnitts")
    c.drawString(72, ph - 160, "Sichtbarer Haupttext innerhalb des gültigen Seitenbereichs")
    c.showPage()
    c.save()

    details = extract_pdf_page_details(spread_pdf)
    page_txt = "\n".join(b["text"] for b in details["pdf_blocks_by_page"].get(0, []))
    assert "Sichtbarer Haupttext innerhalb des gültigen Seitenbereichs" in page_txt
    assert "Verborgener Nachbartext" not in page_txt
    assert "Verborgener Randtext" not in page_txt

    # 2. Short Latin/Greek etymologies and 'Term = Definition' marginalia are recognized
    assert _is_marginalia_or_glossary_note("lat. attrahere = anziehen") is True
    assert _is_marginalia_or_glossary_note("griech. thermos = warm") is True
    assert _is_marginalia_or_glossary_note("Induktion = Erzeugung einer elektrischen Spannung") is True

    # 3. Severe VLM truncation (<25% recall on dense >=50-word PDF page) rebuilds all paragraphs & headings
    p1 = (
        "Elektrische Schwingkreise bestehen im einfachsten Fall aus einer idealen Induktivität "
        "und einem verlustfreien Plattenkondensator in geschlossener Reihenschaltung."
    )
    p2 = (
        "Während einer vollständigen Periode pendelt die gespeicherte Feldenergie periodisch "
        "zwischen dem elektrischen Kondensatorfeld und dem magnetischen Spulenfeld hin und her."
    )
    p3 = (
        "In realen Bauelementen bewirkt der ohmsche Leitungswiderstand eine fortlaufende "
        "Umwandlung elektromagnetischer Energie in thermische Verlustwärme der Drähte."
    )
    p4 = (
        "Durch rückgekoppelte Verstärkerschaltungen lässt sich diese Dämpfung kompensieren, "
        "sodass ungedämpfte harmonische Sinusschwingungen konstanter Amplitude entstehen."
    )
    docling_layout = {
        "text_blocks_by_page": {
            0: [
                {
                    "type": "title",
                    "text": "Elektromagnetische Schwingkreise und Dämpfung",
                    "page_idx": 0,
                    "bbox_1000": [80, 75, 780, 115],
                },
                {"type": "text", "text": p1, "page_idx": 0, "bbox_1000": [80, 150, 480, 320]},
                {"type": "text", "text": p2, "page_idx": 0, "bbox_1000": [80, 340, 480, 510]},
                {"type": "text", "text": p3, "page_idx": 0, "bbox_1000": [510, 150, 910, 320]},
                {"type": "text", "text": p4, "page_idx": 0, "bbox_1000": [510, 340, 910, 510]},
            ]
        }
    }
    severely_truncated_vlm = "![](images/circuit_0.png)\n\nKondensatorplatte"
    fused = fuse_vlm_page_with_docling(
        severely_truncated_vlm,
        page_images=["circuit_0.png"],
        phys_num=108,
        docling_layout=docling_layout,
        page_idx=0,
    )
    assert "## Elektromagnetische Schwingkreise und Dämpfung" in fused
    assert "Plattenkondensator in geschlossener Reihenschaltung" in fused
    assert "magnetischen Spulenfeld hin und her" in fused
    assert "thermische Verlustwärme der Drähte" in fused
    assert "ungedämpfte harmonische Sinusschwingungen" in fused


def test_skeleton_cycle_dedup_mermaid_strip_callout_rescue_and_diagram_headings():
    """Verifies 14b, 14c, and spurious in-diagram '#' heading & raw Mermaid stripping."""
    from backend.services.extraction_postprocess import (
        clean_markdown_fences,
        clean_vlm_repetition_loops,
    )

    # 1. 14c: Incrementing '#### Material A..Z' stub loop drops completely when titled Material heading precedes
    stub_loop = "\n\n".join(f"#### Material {chr(65 + (i % 26))}" for i in range(30))
    page_with_loop = (
        "((15))\n\n"
        "### Material A • Wärmeleitung in Metallen\n\n"
        "Kupfer leitet thermische Energie besonders effektiv.\n\n"
        "![](images/pic_1.png)\n\n"
        f"{stub_loop}\n\n"
        "![](images/pic_2.png)\n\n"
        "#### Material B\n\n"
        "#### Material C\n\n"
        "#### Material D\n\n"
        "#### Material E\n\n"
        "#### Material F\n\n"
        "#### Material G\n\n"
        "Nachfolgender Absatz bleibt vollständig erhalten."
    )
    cleaned_loop, had_loop = clean_vlm_repetition_loops(page_with_loop)
    assert had_loop is True
    assert "### Material A • Wärmeleitung in Metallen" in cleaned_loop
    assert "![](images/pic_1.png)" in cleaned_loop
    assert "![](images/pic_2.png)" in cleaned_loop
    assert "\n#### Material A\n" not in cleaned_loop
    assert "\n#### Material G\n" not in cleaned_loop
    assert "Nachfolgender Absatz bleibt vollständig erhalten." in cleaned_loop

    # Distinct TOC lines must NOT collapse
    toc_md = "\n".join([
        "1.1 Kinematik der Punktmasse",
        "1.2 Dynamik und Kraftgesetze",
        "1.3 Arbeit und mechanische Energie",
        "1.4 Impulserhaltung beim Stoß",
        "1.5 Kreisbewegung und Gravitation",
        "1.6 Mechanische Schwingungen",
        "1.7 Wellenausbreitung in Medien",
    ])
    toc_cleaned, toc_loop = clean_vlm_repetition_loops(toc_md)
    assert toc_loop is False
    assert "1.7 Wellenausbreitung in Medien" in toc_cleaned

    # 2. Raw Mermaid leak stripped cleanly
    raw_mermaid = (
        "Einleitungstext vor dem Diagramm.\n\n"
        "mermaid graph TD\n"
        "    A[Sensor] --> B[Regler]\n"
        "    B --> C[Stellglied]\n\n"
        "![3 Regelkreis der Temperatursteuerung](images/ctrl.png)\n\n"
        "3 Regelkreis der Temperatursteuerung"
    )
    no_mermaid = clean_markdown_fences(raw_mermaid)
    assert "mermaid graph" not in no_mermaid
    assert "A[Sensor]" not in no_mermaid
    assert "![3 Regelkreis der Temperatursteuerung](images/ctrl.png)" in no_mermaid

    # 3. 14b + Additional Item 1: Steckbrief callout wrapping & spurious in-diagram '#' headings stripped
    bio_prose = (
        "Der im schottischen Edinburgh geborene Physiker James Clerk Maxwell formulierte im Jahr 1864 "
        "erstmals die Grundgleichungen der Elektrodynamik und sagte elektromagnetische Wellen voraus."
    )
    layout_callout_and_fig = {
        "heading_blocks": [
            {"text": "Elektromagnetische Wellen", "page_idx": 0, "bbox_1000": [80, 90, 500, 125]},
        ],
        "figure_texts_by_page": {
            0: ["Dipolantenne", "Magnetfeldlinie", "elektrisches-", "Wirbelfeld", "A", "B"],
        },
        "text_blocks_by_page": {
            0: [
                {"type": "section_header", "text": "Elektromagnetische Wellen", "page_idx": 0, "bbox_1000": [80, 90, 500, 125]},
                {"type": "text", "text": "Wechselnde Felder breiten sich mit Lichtgeschwindigkeit im Raum aus.", "page_idx": 0, "bbox_1000": [80, 140, 480, 260]},
                {"type": "text", "text": "STECKBRIEF", "page_idx": 0, "bbox_1000": [520, 140, 680, 165], "is_callout_box": True},
                {"type": "text", "text": "James Clerk Maxwell (1831–1879)", "page_idx": 0, "bbox_1000": [520, 175, 860, 200], "is_callout_box": True},
                {"type": "text", "text": bio_prose, "page_idx": 0, "bbox_1000": [520, 210, 920, 420], "is_callout_box": True},
            ]
        },
    }
    vlm_in = (
        "## Elektromagnetische Wellen\n\n"
        "### A\n\n"
        "![](images/antenna.png)\n\n"
        "### Dipolantenne\n\n"
        "### elektrisches Wirbelfeld\n\n"
        "#### B\n\n"
        "Wechselnde Felder breiten sich mit Lichtgeschwindigkeit im Raum aus.\n\n"
        "---\n\n"
        f"{bio_prose}\n\n"
        "---"
    )
    fused_p = fuse_vlm_page_with_docling(
        vlm_in,
        page_images=["antenna.png"],
        phys_num=42,
        docling_layout=layout_callout_and_fig,
        page_idx=0,
    )
    assert "## Elektromagnetische Wellen" in fused_p
    assert "### A" not in fused_p
    assert "#### B" not in fused_p
    assert "### Dipolantenne" not in fused_p
    assert "### elektrisches Wirbelfeld" not in fused_p
    assert "#### Steckbrief" in fused_p
    assert "<Rahmen>\n_James Clerk Maxwell (1831–1879)_" in fused_p


def test_split_decimal_heading_dedup_3dot_vector_difficulty_and_italic_intro(
    tmp_path, monkeypatch
):
    """Verifies 18a Part 2: split decimal headings, 3-dot PDF vector difficulty + zero-overhead guard, and >=15-word italic intro."""
    import pypdfium2 as pdfium
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    from backend.services.extraction_postprocess import (
        extract_pdf_page_details,
        fuse_vlm_page_with_docling,
        normalize_split_decimal_headings,
        reconstruct_title_hierarchy,
    )

    # 1. Split 2-line decimal section headings + unnumbered duplicate drop (preserving Abbildung 4.1)
    raw_headings = (
        "((14))\n\n"
        "# Grundlagen der Systemanalyse\n\n"
        "## Grundlagen 3.5 der Systemanalyse\n\n"
        "#### Abbildung 4.1 Übersicht des Regelkreises\n\n"
        "## Funktioneller Aufbau 1.1 von Sensoren\n"
    )
    norm_h = normalize_split_decimal_headings(raw_headings)
    assert "# Grundlagen der Systemanalyse" not in norm_h
    assert "## 3.5 Grundlagen der Systemanalyse" in norm_h
    assert "#### Abbildung 4.1 Übersicht des Regelkreises" in norm_h
    assert "## 1.1 Funktioneller Aufbau von Sensoren" in norm_h
    assert "## 3.5 Grundlagen der Systemanalyse" in reconstruct_title_hierarchy(raw_headings)

    # 2. Synthetic 2-page PDF:
    #    - Page 0: heading + 17-word all-italic intro paragraph, NO 3-dot triplets (must NOT call page.render!)
    #    - Page 1: 3 tasks with [T,F,F]=1, [T,T,F]=2, [T,T,T]=3 vector circles + bottom printer mark at y=10 (ignored)
    pdf_path = str(tmp_path / "synthetic_3dot_tasks.pdf")
    c = canvas.Canvas(pdf_path, pagesize=A4)
    _pw, ph = A4

    # Page 0: Heading + 17-word italic intro paragraph
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, ph - 80, "2.1 Thermische Ausgleichsprozesse")
    c.setFont("Helvetica-Oblique", 11)
    c.drawString(
        72,
        ph - 110,
        "In geschlossenen Systemen gleichen sich unterschiedliche Temperaturen durch Wärmeleitung und Konvektion schrittweise vollständig aneinander an.",
    )
    c.drawString(72, ph - 126, "Dabei bleibt die innere Gesamtenergie konstant erhalten.")
    c.showPage()

    # Page 1: Tasks with 3-dot vector circles + bottom y=10 printer mark
    c.setFont("Helvetica", 11)
    tasks_spec = [
        (ph - 120, "1 Benennen Sie die drei Übertragungsarten.", [True, False, False]),
        (ph - 160, "2 Vergleichen Sie Wärmeleitung und Konvektion.", [True, True, False]),
        (ph - 200, "3 Entwickeln Sie ein Modell zur Wärmedämmung.", [True, True, True]),
    ]
    c.setLineWidth(0.7)
    for y_pos, txt_ln, dot_fills in tasks_spec:
        c.drawString(72, y_pos, txt_ln)
        base_x = 340.0
        for d_i, is_filled in enumerate(dot_fills):
            cx = base_x + d_i * 6.0
            cy = y_pos + 3.5
            if is_filled:
                c.setFillColorRGB(0.1, 0.1, 0.1)
                c.circle(cx, cy, 2.0, stroke=1, fill=1)
            else:
                c.setFillColorRGB(1.0, 1.0, 1.0)
                c.circle(cx, cy, 2.0, stroke=1, fill=1)

    # Bottom printer mark at y = 10 pt (must be ignored by y > 20 pt guard)
    for d_i in range(3):
        c.setFillColorRGB(0.0, 0.0, 0.0)
        c.circle(100.0 + d_i * 6.0, 10.0, 2.0, stroke=1, fill=1)
    c.showPage()
    c.save()

    render_pages: list[int] = []
    orig_render = pdfium.PdfPage.render

    def _spy_render(self, *args, **kwargs):
        render_pages.append(1)
        return orig_render(self, *args, **kwargs)

    monkeypatch.setattr(pdfium.PdfPage, "render", _spy_render)

    pdf_doc = pdfium.PdfDocument(pdf_path)
    try:
        details = extract_pdf_page_details(pdf_doc)
    finally:
        pdf_doc.close()

    # Zero-overhead guard: Page 0 was NOT rendered; only Page 1 (with triplets) was rendered once!
    assert len(render_pages) == 1
    assert 0 not in details["task_difficulties_by_page"]
    # 17-word (>= 15) all-italic intro paragraph right under heading on Page 0 suppressed italic font_spans
    p0_italic_spans = [
        sp for sp in details["font_spans_by_page"].get(0, []) if sp.get("style") == "italic"
    ]
    assert p0_italic_spans == []

    p1_diffs = details["task_difficulties_by_page"].get(1, [])
    assert [d["points"] for d in p1_diffs] == [1, 2, 3]

    # Fuse VLM page output (containing raw '•••' on tasks) with layout containing task_difficulties_by_page
    vlm_page_1 = (
        "Aufgaben\n\n"
        "1 Benennen Sie die drei Übertragungsarten. •••\n\n"
        "2 Vergleichen Sie Wärmeleitung und Konvektion. •••\n\n"
        "3 Entwickeln Sie ein Modell zur Wärmedämmung. •••"
    )
    fused = fuse_vlm_page_with_docling(
        vlm_page_1,
        page_images=[],
        phys_num=25,
        docling_layout={"task_difficulties_by_page": {1: p1_diffs}},
        page_idx=1,
    )
    assert "•••" not in fused
    assert "1 Benennen Sie die drei Übertragungsarten. [1 Punkt]" in fused
    assert "2 Vergleichen Sie Wärmeleitung und Konvektion. [2 Punkte]" in fused
    assert "3 Entwickeln Sie ein Modell zur Wärmedämmung. [3 Punkte]" in fused


def test_two_col_3dot_order_diagram_circle_rejection_rubric_banner_rescue_and_spaced_decimal(
    tmp_path,
):
    """Verifies 19b (2-col reading order + diagram particle rejection), 19c (rubric banner rescue), and 19d (1 . 1)."""
    import pypdfium2 as pdfium
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    from backend.services.extraction_postprocess import (
        extract_pdf_page_details,
        normalize_split_decimal_headings,
    )

    # 19d.1: Spaced decimal '1 . 1' normalized and deduplicated against preceding '## 1.1 ...'
    spaced_md = (
        "((40))\n\n"
        "## 1.1 Funktioneller Aufbau von Sensoren\n\n"
        "#### Funktioneller Aufbau 1 . 1 von Sensoren\n"
    )
    norm_spaced = normalize_split_decimal_headings(spaced_md)
    assert norm_spaced.count("1.1 Funktioneller Aufbau von Sensoren") == 1
    assert "## 1.1 Funktioneller Aufbau von Sensoren" in norm_spaced
    assert "1 . 1" not in norm_spaced

    pdf_path = str(tmp_path / "synthetic_19bc.pdf")
    c = canvas.Canvas(pdf_path, pagesize=A4)
    pw, ph = A4

    # Page 0: Top-of-page rubric banner ('methode' + 'Modellbildung im Experiment' at y_1000 <= 60)
    # AND 2-column tasks where right-column task 3 sits vertically ABOVE lower left-column task 2!
    c.setFont("Helvetica-Bold", 10)
    c.drawString(48, ph - 26, "methode")
    c.setFont("Helvetica-Bold", 13)
    c.drawString(48, ph - 44, "Modellbildung im Experiment")

    c.setFont("Helvetica", 10)
    # Left column: x = 48..255 (col 0)
    left_tasks = [
        (ph - 130, "1 Beschreiben Sie den Aufbau.", 245.0, [True, False, False]),
        (ph - 240, "2 Vergleichen Sie beide Kurven.", 245.0, [True, True, False]),
    ]
    # Right column: x = 315..530 (col 1; gutter [260..305] is completely empty!)
    right_tasks = [
        (ph - 160, "3 Beurteilen Sie das Modell.", 515.0, [True, True, True]),
    ]
    c.setLineWidth(0.7)
    for y_pos, txt_ln, dot_x, fills in left_tasks + right_tasks:
        c.drawString(48 if dot_x < 300 else 315, y_pos, txt_ln)
        for d_i, is_f in enumerate(fills):
            cx = dot_x + d_i * 6.0
            cy = y_pos + 3.2
            c.setFillColorRGB(0.1, 0.1, 0.1) if is_f else c.setFillColorRGB(1.0, 1.0, 1.0)
            c.circle(cx, cy, 2.0, stroke=1, fill=1)
    c.showPage()

    # Page 1: Genuine folio running header ('48   Kapitel 2') + diagram with 3 collinear circles and ion label 'H +'
    c.setFont("Helvetica", 9)
    c.drawString(48, ph - 28, "48   Kapitel 2")
    c.setFont("Helvetica", 11)
    c.drawString(48, ph - 120, "Regulärer Fließtext auf der zweiten Seite mit mehr als zwanzig Zeichen.")
    # Diagram circles with ion token 'H +' (no task prose, no bullet glyphs) and empty-text circles
    c.setFont("Helvetica", 8)
    c.drawString(360, ph - 300, "H +")
    for base_x, base_y in ((380.0, ph - 298.0), (380.0, ph - 420.0)):
        for d_i in range(3):
            c.setFillColorRGB(0.1, 0.1, 0.1)
            c.circle(base_x + d_i * 6.0, base_y, 2.0, stroke=1, fill=1)
    c.showPage()
    c.save()

    pdf_doc = pdfium.PdfDocument(pdf_path)
    try:
        details = extract_pdf_page_details(pdf_doc)
    finally:
        pdf_doc.close()

    # 19b: Page 0 difficulties sorted in 2-column reading order [1, 2, 3] instead of row-major [1, 3, 2]
    p0_diffs = details["task_difficulties_by_page"].get(0, [])
    assert [d["points"] for d in p0_diffs] == [1, 2, 3]

    # 19b: Page 1 diagram circles ('H +' and textless) rejected completely
    assert 1 not in details["task_difficulties_by_page"]

    # 19c: Page 0 rubric banner rescued from furniture_by_page, while Page 1 folio header stays in furniture_by_page
    p0_furn_txts = [f["text"] for f in details["furniture_by_page"].get(0, [])]
    assert "methode" not in p0_furn_txts
    assert "Modellbildung im Experiment" not in p0_furn_txts
    p0_body_joined = " ".join(b["text"] for b in details["pdf_blocks_by_page"].get(0, []))
    assert "methode" in p0_body_joined
    assert "Modellbildung im Experiment" in p0_body_joined

    p1_furn_txts = [f["text"] for f in details["furniture_by_page"].get(1, [])]
    assert any("48" in t for t in p1_furn_txts)


def test_strip_prepress_marks_echoed_running_h1_and_indesign_footer_blocks():
    """Verifies 22a: prepress crop/section marks, echoed running H1s, and .indb/.indd footers are stripped."""
    raw_doc = (
        "((10))\n\n"
        "# 2 Thermodynamik\n\n"
        "Einführung in die Zustandsgrößen idealer Gase.\n\n"
        "---\n"
        "**Page Number:** 10\n"
        "**Date:** 14.10.2025\n"
        "**Time:** 09:42:15\n"
        "**Document ID:** Lehrbuch_Gesamt_Druck.indb\n\n"
        "((11))\n\n"
        "Der Druck steigt proportional zur Temperatur bei konstantem Volumen.\n\n"
        "Document ID: Kapitel_02_Einzeln.indd\n\n"
        "((12))\n\n"
        "#### 2 Abschnittsmarke\n\n"
        "# Thermodynamik\n\n"
        "## 2.1 Spezifische Wärmekapazität\n\n"
        "Schnittmarken Passkreuze Farbkontrollstreifen\n\n"
        "Die aufgenommene Wärme hängt vom Stoff und der Masse ab.\n"
    )
    cleaned = clean_running_headers_and_footers(raw_doc)
    recovered = recover_text_truncation(cleaned)

    assert "Abschnittsmarke" not in recovered
    assert "Schnittmarken" not in recovered
    assert "Farbkontrollstreifen" not in recovered
    assert ".indb" not in recovered
    assert ".indd" not in recovered
    assert "Page Number" not in recovered
    assert "Document ID" not in recovered
    assert "# 2 Thermodynamik" in recovered
    assert "\n# Thermodynamik\n" not in recovered
    assert "## 2.1 Spezifische Wärmekapazität" in recovered

    fused = fuse_vlm_page_with_docling(
        "#### Abschnittsmarkierung\n\n## 3.2 Elektrische Felder\n\nFeldlinien verlaufen von Plus nach Minus.\n\n"
        "---\n**Page Numbers:** 34\n**Date:** 02.11.2025\n**Time:** 16:05\n**Document ID:** Teilband_B.indb",
        page_images=[],
        phys_num=34,
    )
    assert "Abschnittsmarkierung" not in fused
    assert "Teilband_B.indb" not in fused
    assert "Page Numbers" not in fused
    assert "Feldlinien verlaufen von Plus nach Minus." in fused













