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


def test_global_u4_captions_buchkonferenz_prefix_priority_long_split_and_echo_cleanup():
    """Verifies 2b & 8: default FIBS M-prefix, Buchkonferenz B/empty priority, >140-char split,
    adjacent <Anmerkung> caption promotion, <Bild> echo stripping, and bullet verb guard.
    """
    # 1. Default FIBS Sek. I/II (custom_rules=None): bare '1 Freikletterin' inside <Anmerkung>
    # + 'Am unteren Bildrand steht der Text: 4 ...' + leading 'Material A • ...' + leading '• Verb...'
    md_default = (
        "((80))\n\n"
        "• Registrieren Messfühler einen Temperaturanstieg, schaltet der Regler um.\n\n"
        "<Bild> Foto:\n"
        "Beschreibung mit Bildtext: Material A • Höhenanpassung im Gebirge. "
        "Eine Sportlerin klettert an einer steilen Felswand. "
        "Am unteren Bildrand steht der Text: 1 Sportlerin in der Felswand\n"
        "</Bild>\n\n"
        "<Anmerkung> 1 Sportlerin in der Felswand </Anmerkung>\n\n"
        "<Bild> Strukturdiagramm:\n"
        "Beschreibung mit Bildtext: Übersicht eines geschlossenen Regelkreises.\n"
        "</Bild>\n\n"
        "4 Schematischer Aufbau eines technischen Regelkreises mit Störgröße. "
        "Bei Abweichungen vom Sollwert greift das Stellglied korrigierend in die Regelstrecke ein und gleicht Schwankungen kontinuierlich aus.\n"
    )
    out_default = post_process_structure(md_default)
    assert "#### Registrieren" not in out_default
    assert "-\tRegistrieren Messfühler einen Temperaturanstieg" in out_default
    assert "#### Material A: Höhenanpassung im Gebirge" in out_default
    assert "Material A •" not in out_default
    assert "Am unteren Bildrand steht der Text" not in out_default
    assert "<Anmerkung> 1 Sportlerin" not in out_default
    assert "#### M1 Sportlerin in der Felswand\n\n<Bild> Foto:" in out_default
    # Long caption (>140 chars) split into #### M4 ... + Standard paragraph above <Bild>
    assert (
        "#### M4 Schematischer Aufbau eines technischen Regelkreises mit Störgröße\n\n"
        "Bei Abweichungen vom Sollwert greift das Stellglied korrigierend in die Regelstrecke ein "
        "und gleicht Schwankungen kontinuierlich aus.\n\n"
        "<Bild> Strukturdiagramm:"
    ) in out_default

    # 2. Buchkonferenz explicit 'B' prefix overrides Gemma's default 'M'
    md_gemma_m = (
        "((12))\n\n"
        "#### M3 Elektrische Feldlinien zwischen Platten\n\n"
        "<Bild> Grafik:\nBeschreibung: Parallele Linien.\n</Bild>\n"
    )
    out_b = post_process_structure(
        md_gemma_m,
        custom_rules="Den Abbildungsnummern wird ein B vorangestellt.",
    )
    assert "#### B3 Elektrische Feldlinien zwischen Platten" in out_b
    assert "#### M3" not in out_b

    # 3. Buchkonferenz forbids prefix / Grundschule ruleset -> no letter prepended
    out_none = post_process_structure(
        md_gemma_m,
        custom_rules="Den Abbildungsnummern wird kein Buchstabe vorangestellt.",
    )
    assert "#### 3 Elektrische Feldlinien zwischen Platten" in out_none
    out_gs = post_process_structure(
        "((5))\n\n<Bild> Zeichnung:\nBeschreibung: Apfelbaum.\n</Bild>\n\n2 Der Apfelbaum im Herbst\n",
        ruleset_key="grundschule",
    )
    assert "#### 2 Der Apfelbaum im Herbst" in out_gs


def test_emphasis_normalization_and_linked_worterklaerungen_and_randspalten():
    """Verifies 4a (unannounced %/* -> _Wort_, announced preserved) and 5a (linked Worterklärungen & Randspalte)."""
    # 4a: Unannounced %Wort% and *Wort* become _Wort_, percentages stay 50 %
    md_emph = "((10))\n\nDer %wichtige% Wert steigt um 50 % bei *konstanter* Masse (12,1 % C, 87,9 % H)."
    out_emph = post_process_structure(md_emph)
    assert "_wichtige_" in out_emph
    assert "_konstanter_" in out_emph
    assert "50 %" in out_emph
    assert "12,1 % C, 87,9 % H" in out_emph
    assert "%wichtige%" not in out_emph

    # Announced differentiated emphasis in <Anmerkung> stays intact
    md_legend = (
        "<Anmerkung>\nBedeutung: *Wort* = fett, %Wort% = kursiv.\n</Anmerkung>\n\n"
        "((10))\n\nEin *fetter* und %kursiver% Ausdruck."
    )
    out_legend = post_process_structure(md_legend)
    assert "*fetter*" in out_legend
    assert "%kursiver%" in out_legend

    # 5a: Linked Worterklärungen + #### Randspalte
    md_gloss = (
        "((304))\n\n"
        "Die Homöostase{1} beschreibt ein dynamisches Gleichgewicht. Auch die Osmose spielt eine Rolle.\n\n"
        "<Rahmen>\n_Randspalte_\nMerke dir den Unterschied zwischen geschlossenem und offenem System.\n</Rahmen>\n\n"
        "<Anmerkung> 1 Homöostase: Aufrechterhaltung konstanter innerer Bedingungen. </Anmerkung>\n\n"
        "Osmose (griech. osmos = Eindringen)\n"
    )
    out_gloss = post_process_structure(
        md_gloss,
        custom_rules="Worterklärungen sind im Dokument verlinkt.",
    )
    assert "Homöostase^1" in out_gloss
    assert "Osmose^2" in out_gloss
    assert "#### Randspalte\n\n<Rahmen>\nMerke dir den Unterschied" in out_gloss
    assert "#### Worterklärungen" in out_gloss
    assert "-\t^1: Homöostase: Aufrechterhaltung konstanter innerer Bedingungen." in out_gloss
    assert "-\t^2: Osmose (griech. osmos = Eindringen)" in out_gloss


def test_multiword_italic_asterisk_guard_bounded_anmerkung_and_latin_stem_glossary():
    """Verifies Phase 4 fixes: multi-word *italic* preservation, bounded <Anmerkung> % check, Latin stem linking, and page marker newlines."""
    from backend.services.a11y_linter import lint_markdown
    from backend.services.fibs_postprocess import restore_false_positive_trailing_asterisks

    # 1. Multi-word *italic phrase* converted to _italic phrase_ must NOT have closing _ corrupted to *
    raw_src = "Die Pflanze *Solanum tuberosum* liefert Stärke bis zum Prognosejahr 2035*."
    std_candidate = "Die Pflanze _Solanum tuberosum_ liefert Stärke bis zum Prognosejahr 2035_."
    restored = restore_false_positive_trailing_asterisks(std_candidate, raw_src)
    assert "_Solanum tuberosum_" in restored
    assert "_Solanum tuberosum*" not in restored
    assert "2035*" in restored

    # 2. Separate <Anmerkung> blocks + '50 %' in body prose must NOT mask unannounced %Kursivwort%
    md_multi_anm = (
        "((12))\n\n"
        "<Anmerkung>\nDie folgende Tabelle wurde aufgelöst.\n</Anmerkung>\n\n"
        "Der Wirkungsgrad steigt um 50 % beim %Carnot-Prozess% im Labor.\n\n"
        "<Anmerkung>\nUnterstrichene Wörter sind hervorgehoben.\n</Anmerkung>\n"
    )
    lint_rep = lint_markdown(md_multi_anm)
    assert any(iss.rule == "fibs_unannounced_percent_emphasis" for iss in lint_rep.issues)
    cleaned_anm = post_process_structure(md_multi_anm)
    assert "_Carnot-Prozess_" in cleaned_anm
    assert "%Carnot-Prozess%" not in cleaned_anm

    # 3. Latin '-ere' & Greek '-os' marginalia match _Highlighted_ body terms and preserve newline before ((next))
    md_pages = (
        "((20))\n\n"
        "Spezielle _Rezeptoren_ registrieren Änderungen in der _Thermodynamik_.\n\n"
        "_lat_. _recipere_ = _aufnehmen_\n\n"
        "_griech_. _thermos_ = _warm_\n\n"
        "_lat_. _ignotus_ = _unbekannt_\n\n"
        "((21))\n\n"
        "<Bild> Foto:\nBeschreibung: Wärmebildkamera.\n</Bild>\n\n"
        "1 Thermografieaufnahme eines Hauses\n\n"
        "### Wärmestrahlung im Vakuum\n"
    )
    out_pages = post_process_structure(
        md_pages,
        custom_rules=(
            "Überschrift 1: Hauptthema, Grafiken mit M1 als Ü4 (####), "
            "Worterklärungen sind im Dokument verlinkt."
        ),
    )
    assert "_Rezeptoren_^1" in out_pages
    assert "_Thermodynamik_^2" in out_pages
    assert "-\t^1: lat. _recipere_ = aufnehmen" in out_pages
    assert "-\t^2: griech. _thermos_ = warm" in out_pages
    assert "\n((21))\n" in out_pages
    assert out_pages.index("### Wärmestrahlung im Vakuum") < out_pages.index("#### M1 Thermografieaufnahme")
    assert out_pages.index("#### M1 Thermografieaufnahme") < out_pages.index("<Bild> Foto:")


def test_glossary_rahmen_unwrap_steckbrief_dedup_captions_and_subtasks():
    """Verifies 14b, 14d, and additional page-level fixes (panel headings, A1 subtasks, page-top <Bild>)."""
    buchkonferenz = (
        "# Überschrift 1:\nHauptthema\n"
        "### Überschrift 3:\n- Material\n"
        "#### Überschrift 4:\n- Kapitelinterne Überschriften\n- Abbildungsunterschriften\n- Material A (Material Ü3)\n"
        "##### Überschrift 5:\n- das Wort 'Aufgaben:' und jeweils die Aufgabennummer als Ü.\n"
        "<Anmerkung>\n- Zur besseren Orientierung wird den Abbildungsnummern ein M vorangestellt.\n"
        "- Worterklärungen sind im Dokument verlinkt\n</Anmerkung>"
    )

    md_input = (
        "((50))\n\n"
        "<Bild> 2 Fotos:\nBeschreibung: Vergleich zweier Linsenformen.\n</Bild>\n\n"
        "##### 1\n\n"
        "Linsenarten in der Optik:\n"
        "-\tA Sammellinse,\n"
        "-\tB Zerstreuungslinse\n\n"
        "#### Brechung an Linsen\n\n"
        "Lichtstrahlen werden beim Übergang in dichtere Medien _gebrochen_ und an Brennpunkten _fokussiert_.\n\n"
        "<Rahmen>\n"
        "_lat._ _frangere_\n"
        "= _brechen_\n\n"
        "_fokussieren_\n"
        "= Strahlen in einem Brennpunkt bündeln\n"
        "</Rahmen>\n\n"
        "#### M2\n\n"
        "<Bild> Zeichnung:\nBeschreibung: Strahlengang an einer Sammellinse.\n</Bild>\n\n"
        "_Strahlengang parallel einfallender Lichtbündel (Schema)_\n\n"
        "((51))\n\n"
        "### Material\n\n"
        "#### Material A: Optische Instrumente\n\n"
        "<Bild> Zeichnung:\nBeschreibung: Aufbau eines Mikroskops.\n</Bild>\n\n"
        "### B\n\n"
        "Ein Lichtmikroskop kombiniert Objektiv und Okular zur starken Vergrößerung.\n\n"
        "#### A1\n"
        "Erläutern Sie die Funktion des Objektivs.\n\n"
        "#### A2\n"
        "Planen Sie ein Experiment zur Bestimmung der Brennweite.\n\n"
        "((52))\n\n"
        "### Spektralanalyse\n\n"
        "#### M3\n\n"
        "<Bild> Zeichnung:\nBeschreibung: Aufbau eines Prismenspektrometers.\n</Bild>\n\n"
        "##### Aufgaben\n\n"
        "##### 1\n"
        "Beschreiben Sie die Dispersion von weißem Licht.\n\n"
        "##### 3\n"
        "Aufbau eines Spektrometers:\n"
        "A Eintrittsspalt\n"
        "B Glasprisma\n\n"
        "((53))\n\n"
        "#### Regelkreis der Temperatur\n\n"
        "<Bild> Flussdiagramm:\n"
        "Beschreibung mit Bildtext: Thermostat \\to Heizkörper \\to Raumtemperatur \\to Messfühler.\n"
        "</Bild>\n\n"
        "Bei Abweichungen von ~beta-Werten regelt der Thermostat die Heizleistung automatisch nach.\n\n"
        "---\n\n"
        "Dem in Leiden tätigen Physiker Heike Kamerlingh Onnes gelang es 1908 erstmals zusammen mit seinem "
        "Laborteam, Helium bei tiefsten Temperaturen zu verflüssigen und die Supraleitung zu entdecken.\n\n"
        "---\n\n"
        "#### M4 Regelung der Raumtemperatur durch Thermostat und Heizkörper\n\n"
        "<Bild> Foto mit Text:\n"
        "Beschreibung mit Bildtext: Ein Porträtfoto eines Forschers im dunklen Anzug steht rechts. "
        "Links daneben befindet sich ein Textblock unter der Überschrift Heike Kamerlingh _Onnes_ (1853–1926), "
        "der beschreibt, wie ihm 1908 gelang, Helium zu verflüssigen.\n"
        "</Bild>\n"
    )

    out = post_process_structure(md_input, raw_markdown=md_input, custom_rules=buchkonferenz)

    # Page 50: opening section heading promoted to ### before M1 + <Bild>, glossary <Rahmen> unwrapped & linked, M2 titled
    assert out.index("### Brechung an Linsen") < out.index("#### M1 Linsenarten in der Optik: A Sammellinse, B Zerstreuungslinse")
    assert "#### M2 Strahlengang parallel einfallender Lichtbündel (Schema)" in out
    assert "_fokussiert_^2" in out or "_fokussiert_^1" in out
    assert "<Rahmen>\n_lat._" not in out
    assert "#### Worterklärungen" in out

    # Page 51: spurious '### B' gone, standalone '#### A1' / '#### A2' promoted to '##### Aufgaben' + '##### A1' / '##### A2'
    assert "\n### B\n" not in out
    assert "##### Aufgaben\n\n##### A1" in out
    assert "##### A2" in out

    # Page 52: false task '##### 3' attached to bare '#### M3'
    assert "#### M3 Aufbau eines Spektrometers: A Eintrittsspalt, B Glasprisma" in out
    assert "##### 3" not in out

    # Page 53: '~beta-Werten' -> '~b-Werten', M4 relocated above Flussdiagramm, Steckbrief wrapped as <Rahmen>, portrait deduplicated
    assert "~b-Werten" in out
    assert "#### M4 Regelung der Raumtemperatur durch Thermostat und Heizkörper\n\n<Bild> Flussdiagramm:" in out
    assert "#### M Steckbrief\n\n<Rahmen>\n_Heike Kamerlingh Onnes (1853-1926)_" in out or "#### M Steckbrief\n\n<Rahmen>\n_Heike Kamerlingh Onnes (1853–1926)_" in out
    assert "<Bild> Foto:\nBeschreibung: Ein Porträtfoto eines Forschers im dunklen Anzug steht rechts.\n</Bild>" in out




