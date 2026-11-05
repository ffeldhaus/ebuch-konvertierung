"""Unit tests for FIBS post-processing of heading-prefixed page markers and VLM repetition loops."""

import re

from backend.services.fibs_postprocess import (
    deduplicate_page_numbers,
    normalize_heading_page_markers,
    post_process_structure,
)


def test_normalize_heading_page_markers_splits_inline_and_strips_empty_headings():
    """Verifies normalization of ``#### ((294))``, ``### ((294)) Titel``, and empty ``####``."""
    raw = (
        "((293))\n\n"
        "Erster Absatz.\n\n"
        "####\n\n"
        "#### ((294))\n\n"
        "Zweiter Absatz.\n\n"
        "### ((295)) 4.2 Elektrische Felder\n\n"
        "Dritter Absatz.\n"
    )
    norm = normalize_heading_page_markers(raw)
    assert "#### ((294))" not in norm
    assert "\n((294))\n" in norm
    assert "### ((295))" not in norm
    assert "((295))\n\n### 4.2 Elektrische Felder" in norm
    assert not re.search(r"(?m)^[ \t]*#{1,6}[ \t]*$", norm)


def test_post_process_structure_strips_single_char_heading_loops_and_normalizes_page_markers():
    """Verifies that post_process_structure strips >= 8 single-char headings, empty headings,
    and normalizes heading-prefixed page markers without duplicating page numbers.
    """
    loop_block = "\n\n".join(f"#### {chr(65 + (i % 26))}" for i in range(12))
    md = (
        "((293))\n\n"
        "## 5.1 Magnetische Flussdichte\n\n"
        "Die magnetische Flussdichte wird in Tesla gemessen.\n\n"
        f"{loop_block}\n\n"
        "####\n\n"
        "((294))\n\n"
        "#### ((294))\n\n"
        "### ((294)) Versuchsauswertung\n\n"
        "Die Messwerte zeigen einen linearen Zusammenhang.\n"
    )
    processed = post_process_structure(md)
    assert "#### A" not in processed
    assert "#### L" not in processed
    assert not re.search(r"(?m)^[ \t]*#{1,6}[ \t]*$", processed)
    markers = re.findall(r"\(\((\d+)\)\)", processed)
    assert markers == ["293", "294"]
    assert "### Versuchsauswertung" in processed
    assert "Die Messwerte zeigen einen linearen Zusammenhang." in processed


def test_deduplicate_page_numbers_normalizes_heading_prefixed_duplicates():
    """Verifies that deduplicate_page_numbers collapses ``((294))`` and ``#### ((294))``."""
    md = "((294))\n\nText auf Seite 294.\n\n#### ((294))\n\nWeiterer Text auf Seite 294."
    cleaned = deduplicate_page_numbers(md)
    assert re.findall(r"\(\((\d+)\)\)", cleaned) == ["294"]
    assert "####" not in cleaned


def test_infer_heading_hierarchy_protects_bild_and_tabelle_and_bare_integer_headings():
    """Verifies 1a and 1b: <Bild> and <Tabelle> inner lines are protected from heading promotion,
    inner '#' prefixes inside <Bild> are stripped, and '# 2 ...' caption headings are demoted.
    """
    from backend.services.fibs_postprocess import infer_heading_hierarchy

    raw = "# Teil 4, Messreihe\n## 3.2 Elektrische Ladung\n"
    md = (
        "((10))\n\n"
        "# 3.2 Elektrische Ladung\n\n"
        "# 2 Schematischer Aufbau einer Messzelle im Querschnitt\n\n"
        "<Bild> Grafik:\n"
        "Beschreibung mit Bildtext: Übersicht der Messzelle.\n"
        "# Teil 4, Messreihe\n"
        "### Na^+-Ionen im Kanal\n"
        "</Bild>\n\n"
        "<Tabelle>\n\n"
        "| Teil 4, Messreihe | Wert |\n"
        "| :--- | :--- |\n"
        "| Probe A | 12 |\n\n"
        "</Tabelle>\n"
    )
    res = infer_heading_hierarchy(md, raw_markdown=raw)
    assert "## 3.2 Elektrische Ladung" in res
    assert "#### 2 Schematischer Aufbau einer Messzelle im Querschnitt" in res
    assert "\n# 2 Schematischer Aufbau" not in res
    assert "\n# Teil 4, Messreihe" not in res
    assert "\nTeil 4, Messreihe\n" in res
    assert "\nNa^+-Ionen im Kanal\n" in res
    assert "| Teil 4, Messreihe | Wert |" in res


def test_run_in_bullet_subheadings_and_false_positive_placeholder_tabelle():
    """Verifies 1d and 2a: run-in bullet subheadings split into #### and placeholder tables drop."""
    md = (
        "((20))\n\n"
        "## 4.1 Grundlagen der Mechanik •\n\n"
        "### Material A • Kräfte im Gleichgewicht\n\n"
        "**Trägheitsprinzip** • Ein Körper verharrt im Zustand der Ruhe oder der gleichförmigen Bewegung.\n\n"
        "Reibungskraft • Sie wirkt stets entgegen der Bewegungsrichtung.\n\n"
        "<Tabelle>\n\n"
        "| Geschwindigkeit in m/s | Zeit in s |\n"
        "| :--- | :--- |\n"
        "| _..._ | _..._ |\n\n"
        "</Tabelle>\n"
    )
    res = post_process_structure(md)
    assert "## 4.1 Grundlagen der Mechanik\n" in res
    assert "### Material A: Kräfte im Gleichgewicht" in res
    assert "#### Trägheitsprinzip\n\nEin Körper verharrt" in res
    assert "#### Reibungskraft\n\nSie wirkt stets" in res
    assert "<Tabelle>" not in res
    assert "Geschwindigkeit in m/s" not in res


def test_buchkonferenz_custom_rules_tables_captions_tasks_hierarchy_ions_and_frontmatter():
    """Verifies 1c, 2c, 3b, 4a, 5b, and 6b when Buchkonferenz custom_rules are provided."""
    custom_rules = (
        "Fach: Naturwissenschaften\n"
        "Titel: Musterlehrbuch Oberstufe\n"
        "Verlag: Musterverlag\n\n"
        "<Anmerkung>\n"
        "Informationen zur Übertragung:\n"
        "- Die Randspalten wurden in den Fließtext integriert.\n"
        "</Anmerkung>\n\n"
        "Gliederung:\n"
        "# Überschrift 1: Hauptthema\n"
        "## Überschrift 2: Unterkapitel\n"
        '### Überschrift 3: Titel von besonders hervorgehobenen Seiten wie "Material", "ÜBERBLICK", "IM BLICKPUNKT"\n'
        '#### Überschrift 4: Kapitelinterne Überschriften, "Material A", Abbildungsunterschriften (den Abbildungsnummern ein M vorangestellt)\n'
        '##### Überschrift 5: "Aufgaben:" und jeweils die Aufgabennummer als Ü\n'
    )
    md = (
        "((50))\n\n"
        "## IM BLICKPUNKT • Energieumsatz im Alltag\n\n"
        "# Elektrische Vorgänge an Grenzflächen\n\n"
        "_Worterklärung:_\n\n"
        "Die Konzentration von $K^+$ und $Na^+$ sowie $Ca^{2+}$ in $H_2O$ beträgt $10 \\, \\mu\\text{g}$.\n"
        "Die Reaktion verläuft gemäß $$A \\xrightarrow{\\text{Katalysator}} B$$.\n\n"
        "<Bild> Grafik:\n"
        "Beschreibung mit Bildtext: Verlauf der Spannung über die Zeit.\n"
        "</Bild>\n\n"
        "Zeit in ms\n\n"
        "2 Schematischer Verlauf der elektrischen Spannung an der Membran\n\n"
        "<Tabelle>\n\n"
        "| Parameter | Zustand 1 | Zustand 2 |\n"
        "| :--- | :--- | :--- |\n"
        "| Spannung | -70 mV | +30 mV |\n"
        "| Dauer | 2 ms | |\n\n"
        "</Tabelle>\n\n"
        "Aufgaben: 1 Beschreiben Sie den Aufbau der Messanordnung.\n"
        "2 Erklären Sie die Wirkung der Ionenverteilung.\n"
        "### A1 Vergleichen Sie die beiden Kurvenverläufe.\n"
    )
    res = post_process_structure(md, custom_rules=custom_rules)

    # 6b: Frontmatter <Anmerkung> prepended before ((50))
    assert res.startswith("<Anmerkung>\nInformationen zur Übertragung:")
    assert res.index("</Anmerkung>") < res.index("((50))")

    # 1c: Heading hierarchy normalization
    assert "### IM BLICKPUNKT: Energieumsatz im Alltag" in res
    assert "#### Elektrische Vorgänge an Grenzflächen" in res
    assert "#### Worterklärung:" in res

    # 5b: Inline ions, molecules, units, and reaction arrows
    assert "K^+" in res and "$K^+$" not in res
    assert "Na^+" in res and "$Na^+$" not in res
    assert "Ca^{2+}" in res and "$Ca^{2+}$" not in res
    assert "H_2O" in res and "$H_2O$" not in res
    assert "10 ~mg" in res
    assert "\\xra{Katalysator}" in res

    # 3b: Figure caption M-prefix moved before <Bild> and orphan axis label removed
    cap_pos = res.find("#### M2 Schematischer Verlauf der elektrischen Spannung an der Membran")
    bild_pos = res.find("<Bild> Grafik:")
    assert cap_pos != -1 and cap_pos < bild_pos
    assert "\nZeit in ms\n" not in res

    # 2c: Small table resolved into <Anmerkung> + _Header_: Value paragraphs
    assert "<Anmerkung>\nDie folgende Tabelle wurde aufgelöst.\n</Anmerkung>" in res
    assert "_Parameter_: Spannung; _Zustand 1_: -70 mV; _Zustand 2_: +30 mV" in res
    assert "_Parameter_: Dauer; _Zustand 1_: 2 ms" in res

    # 4a: Tasks formatted as ##### Aufgaben + ##### <Nr> + paragraph
    assert "##### Aufgaben\n\n##### 1\n\nBeschreiben Sie den Aufbau der Messanordnung." in res
    assert "##### 2\n\nErklären Sie die Wirkung der Ionenverteilung." in res
    assert "##### A1\n\nVergleichen Sie die beiden Kurvenverläufe." in res

