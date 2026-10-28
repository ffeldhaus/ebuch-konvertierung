import json
import os
import tempfile
import pytest

from backend.services.extraction_postprocess import (
    apply_extraction_postprocess,
    associate_image_captions,
    clean_duplicate_itemization,
    clean_markdown_fences,
    clean_running_headers_and_footers,
    convert_html_tables_to_markdown,
    fix_escaped_dollars,
    recover_table_truncation,
    recover_text_truncation,
    reconstruct_title_hierarchy,
    sanitize_runaway_repetitions,
)


def test_recover_text_truncation_dehyphenates():
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
    raw = "Hier ist ein langer Satz,\nder auf der nächsten Zeile weitergeht."
    res = recover_text_truncation(raw)
    assert "Hier ist ein langer Satz, der auf der nächsten Zeile weitergeht." in res


def test_sanitize_runaway_repetitions_preserves_tables_and_blanks():
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
    raw = "Die Geschwindigkeit beträgt \\$c_0 = 3 \\cdot 10^8\\$ m/s.\n\n```markdown\n| A | B |\n| --- | --- |\n| 1 | 2 |\n```"
    cleaned = clean_markdown_fences(fix_escaped_dollars(raw))
    assert "$c_0 = 3 \\cdot 10^8$" in cleaned
    assert "```" not in cleaned
    assert "| A | B |" in cleaned


def test_insert_page_numbers_skips_furniture_anchors_and_detects_scanned_page_numbers(tmp_path):
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
    from backend.services.docx_service import convert_markdown_to_docx
    from docx import Document

    md = "((18)) / ((19))\n\n# Kapitel 3: Der geheime Kompass\n\nText auf der Doppelseite."
    out_docx = str(tmp_path / "spread_test.docx")
    convert_markdown_to_docx(md, out_docx)
    doc = Document(out_docx)
    xml_str = doc.element.xml
    assert 'w:name="page_18_19"' in xml_str


def test_one_col_toc_unroll_and_post_process_boxes_and_split_tables():
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




