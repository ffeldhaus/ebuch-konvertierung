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


def test_buchkonferenz_numbers_only_u5_point_difficulties_rubrics_u4_demotion_toc_u1_and_italic_intro():
    """Verifies 18a Part 2: Aufgabennummern without ##### Aufgaben, [einfach]/[mittel]/[schwierig],
    Ü3 rubrics, schwarze Textüberschriften Ü4 demotion, TOC Ü1 injection, and italic intro stripping.
    """
    bk_rules = (
        "# Überschrift 1: Hauptkapitel (stehen nur im Inhaltsverzeichnis, bitte übernehmen)\n"
        "## Überschrift 2: Teilkapitel (z. B. 2.1)\n"
        "### Überschrift 3: Methode, Basiskonzept, Exkurs, Material mit Aufgaben\n"
        "#### Überschrift 4: schwarze Textüberschriften, Abbildungsunterschriften (mit M)\n"
        "##### Überschrift 5: Aufgabennummern\n"
        "Sonstiges:\n"
        "- kursive Einleitungstexte: nicht fett!\n"
        "- Schwierigkeitsgrade bei Aufgaben:\n"
        "  1 Punkt: [einfach]\n"
        "  2 Punkte: [mittel]\n"
        "  3 Punkte: [schwierig]\n"
    )
    directory_info = {
        "has_any_directory": True,
        "detected_types": ["toc"],
        "toc_entries": [
            {"title": "1 Energieübertragung in technischen Systemen", "page": 60, "level": 1},
            {"title": "2.1 Thermische Ausgleichsvorgänge", "page": 60, "level": 2},
        ],
    }
    md_in = (
        "((60))\n\n"
        "# Thermische Ausgleichsvorgänge\n\n"
        "## Thermische 2.1 Ausgleichsvorgänge\n\n"
        "_In jedem abgeschlossenen System streben Teilbereiche unterschiedlicher Temperatur einem gemeinsamen Gleichgewichtszustand mit CO_2 zu._\n\n"
        "# Wärmeleitung in Festkörpern\n\n"
        "Metalle leiten thermische Energie besonders schnell weiter.\n\n"
        "## Konvektion in Flüssigkeiten\n\n"
        "Strömungen transportieren Wärme über größere Distanzen.\n\n"
        "((61))\n\n"
        "methode\n"
        "## Kalorimetrische Messung im Labor\n\n"
        "*Mit einem isolierten Kalorimeter lässt sich die übertragene Wärmemenge präzise im Experiment bestimmen.*\n\n"
        "basiskonzept • Energieerhaltung und Umwandlung\n\n"
        "exkurs: Historische Thermometer\n\n"
        "material mit aufgaben\n\n"
        "## A Versuchsaufbau mit Messfühler\n\n"
        "##### Aufgaben\n\n"
        "1 Benennen Sie die Bauteile des Kalorimeters [1 Punkt].\n\n"
        "2 Berechnen Sie die spezifische Wärmekapazität aus den Messdaten. [2 Punkte]\n\n"
        "### A1 Beurteilen Sie mögliche Wärmeverluste an die Umgebung [3 Punkte].\n"
    )

    out = post_process_structure(
        md_in,
        raw_markdown=md_in,
        directory_info=directory_info,
        custom_rules=bk_rules,
    )

    # TOC-only Ü1 injected right after ((60)), split decimal heading normalized & duplicate dropped
    assert "((60))\n\n# 1 Energieübertragung in technischen Systemen" in out
    assert "\n# Thermische Ausgleichsvorgänge\n" not in out
    assert "## 2.1 Thermische Ausgleichsvorgänge" in out

    # Italic intro paragraphs stripped of _..._ / *...* while keeping CO_2 subscript intact
    assert (
        "In jedem abgeschlossenen System streben Teilbereiche unterschiedlicher Temperatur "
        "einem gemeinsamen Gleichgewichtszustand mit CO_2 zu."
    ) in out
    assert "_In jedem abgeschlossenen System" not in out
    assert (
        "Mit einem isolierten Kalorimeter lässt sich die übertragene Wärmemenge präzise im Experiment bestimmen."
    ) in out
    assert "_Mit einem isolierten Kalorimeter" not in out

    # Unnumbered non-rubric subheadings demoted to #### (Ü4)
    assert "#### Wärmeleitung in Festkörpern" in out
    assert "#### Konvektion in Flüssigkeiten" in out
    assert "#### A Versuchsaufbau mit Messfühler" in out

    # Ü3 rubrics normalized cleanly
    assert "### Methode: Kalorimetrische Messung im Labor" in out
    assert "### Basiskonzept: Energieerhaltung und Umwandlung" in out
    assert "### Exkurs: Historische Thermometer" in out
    assert "### Material mit Aufgaben" in out

    # Ü5 Aufgabennummern WITHOUT '##### Aufgaben' + difficulty labels right beneath ##### <Nr>
    assert "##### Aufgaben" not in out
    assert "##### 1\n[einfach]\n\nBenennen Sie die Bauteile des Kalorimeters." in out
    assert (
        "##### 2\n[mittel]\n\nBerechnen Sie die spezifische Wärmekapazität aus den Messdaten."
        in out
    )
    assert (
        "##### A1\n[schwierig]\n\nBeurteilen Sie mögliche Wärmeverluste an die Umgebung."
        in out
    )
    assert "Punkt" not in out

    # When custom_rules does NOT define point-based difficulty labels, [1 Punkt]..[3 Punkte] are stripped cleanly
    out_plain = post_process_structure(
        "((10))\n\n### Aufgabe 1: Beschreiben Sie das Diagramm [2 Punkte].\n"
    )
    assert "[2 Punkte]" not in out_plain
    assert "Beschreiben Sie das Diagramm" in out_plain


def test_vlm_caption_echo_strip_rubric_banners_duplicate_headings_and_panel_pairs():
    """Verifies 19c (rubric banner combine), 19d (VLM echo strip + caption pairing + lead-in question guard + dedup), and 19f (panel pairs)."""
    bk_rules = (
        "## Überschrift 2: Teilkapitel\n"
        "### Überschrift 3: Methode, Basiskonzept, Exkurs, Material mit Aufgaben\n"
        "#### Überschrift 4: schwarze Textüberschriften, Abbildungsunterschriften (mit M)\n"
        "##### Überschrift 5: Aufgabennummern\n"
    )
    md_in = (
        "((70))\n\n"
        "## 1.4 Signalübertragung an Grenzflächen\n\n"
        "#### Signalübertragung 1 . 4 an Grenzflächen\n\n"
        "### Methode\n\n"
        "#### Messwerterfassung im Modellversuch\n\n"
        "#### M1 Mikroskopische Aufnahme\n\n"
        "<Bild> Mikroskopische Aufnahme:\n"
        "Beschreibung: Zellkultur im Phasenkontrast bei vierhundertfacher Vergrößerung.\n"
        "</Bild>\n\n"
        "1 Zellkultur unter dem Lichtmikroskop\n\n"
        "#### M2\n\n"
        "<Bild> Zeichnung:\n"
        "Beschreibung mit Bildtext: Vergleich von Rezeptorstruktur A im Ruhezustand und Rezeptorstruktur B nach Ligandenbindung.\n"
        "</Bild>\n\n"
        "_Konformationsänderung am Membranrezeptor (Schema)_\n\n"
        "### Rezeptorstruktur A\n\n"
        "##### A\n\n"
        "### Rezeptorstruktur B\n\n"
        "##### B\n\n"
        "#### M3 Eine schematische Darstellung eines Versuchsaufbaus zeigt eine Messkammer, die an d\n\n"
        "<Bild> Zeichnung:\n"
        "Beschreibung: Eine schematische Darstellung eines Versuchsaufbaus zeigt eine Messkammer, die an drei Elektroden angeschlossen ist.\n"
        "</Bild>\n\n"
        "#### Versuchsaufbau zur Diffusion\n\n"
        "### material mitaufgaben\n\n"
        "#### M4\n\n"
        "<Bild> Diagramm:\n"
        "Beschreibung: Zeitverlauf der Konzentration in zwei Kammern.\n"
        "</Bild>\n\n"
        "### Material mit Aufgaben\n\n"
        "##### 4\n\n"
        "Wie verändert sich die Konzentration in beiden Kammern nach dem Öffnen des Ventils im Zeitverlauf?\n\n"
        "##### 1\n\n"
        "Beschreiben Sie den Kurvenverlauf.\n"
    )

    out = post_process_structure(md_in, raw_markdown=md_in, custom_rules=bk_rules)

    # 19d.1 & 19d.3: Spaced decimal '1 . 4' normalized and deduplicated against '## 1.4 ...'
    assert out.count("1.4 Signalübertragung an Grenzflächen") == 1
    assert "## 1.4 Signalübertragung an Grenzflächen" in out

    # 19c: Standalone '### Methode' + '#### Messwerterfassung...' combined into '### Methode: ...'
    assert "### Methode: Messwerterfassung im Modellversuch" in out

    # 19d.2: VLM Bildart echo 'Mikroskopische Aufnahme' replaced by real printed post-</Bild> caption '1 Zellkultur...'
    assert "#### M1 Mikroskopische Aufnahme" not in out
    assert "#### M1 Zellkultur unter dem Lichtmikroskop" in out
    assert "\n1 Zellkultur unter dem Lichtmikroskop" not in out

    # 19f: Orphan diagram subheading + single-letter panel pairs ('### Rezeptorstruktur A' + '##### A', B) stripped,
    # while italic post-</Bild> caption promoted to '#### M2 ...'
    assert "#### M2 Konformationsänderung am Membranrezeptor (Schema)" in out
    assert "### Rezeptorstruktur A" not in out
    assert "### Rezeptorstruktur B" not in out
    assert "##### A" not in out
    assert "##### B" not in out

    # 19d.2: VLM hinweis boilerplate stripped from '#### M3 ...' and paired with lone '#### Versuchsaufbau zur Diffusion'
    assert "Eine schematische Darstellung eines Versuchsaufbaus" not in out.split("<Bild>")[2]
    assert "#### M3 Versuchsaufbau zur Diffusion\n\n<Bild> Zeichnung:" in out

    # 19d.3: '### material mitaufgaben' normalized and duplicate '### Material mit Aufgaben' on same page dropped
    assert "material mitaufgaben" not in out.lower()
    assert out.count("### Material mit Aufgaben") == 1

    # 19d.2: Question sentence under '##### 4' NOT attached to bare '#### M4'
    assert "#### M4\n\n<Bild> Diagramm:" in out
    assert "Wie verändert sich die Konzentration" in out


def test_post_process_strips_prepress_and_indesign_outside_bild_and_tabelle():
    """Verifies 22a in post_process_structure while protecting <Bild> and <Tabelle> blocks."""
    md_in = (
        "((20))\n\n"
        "# 3 Zellatmung\n\n"
        "Zellen gewinnen Energie durch den schrittweisen Abbau organischer Stoffe.\n\n"
        "---\n"
        "**Page Number:** 20\n"
        "**Date:** 19.11.2025\n"
        "**Time:** 08:15:30\n"
        "**Document ID:** Biologie_Band2.indb\n\n"
        "((22))\n\n"
        "#### 3 Abschnittsmarke\n\n"
        "# Zellatmung\n\n"
        "## 3.1 Glykolyse im Überblick\n\n"
        "<Bild> Grafik:\n"
        "Beschreibung mit Bildtext: Schema mit Abschnittsmarkierung A und B.\n"
        "</Bild>\n\n"
        "Document ID: Kapitel_03.indd\n"
    )
    out = post_process_structure(md_in)
    assert "#### 3 Abschnittsmarke" not in out
    assert "\n# Zellatmung\n" not in out
    assert "# 3 Zellatmung" in out
    assert "## 3.1 Glykolyse im Überblick" in out
    assert "Biologie_Band2.indb" not in out
    assert "Kapitel_03.indd" not in out
    assert "Page Number" not in out
    assert "Schema mit Abschnittsmarkierung A und B." in out


def test_lift_trailing_task_difficulty_tags_and_strip_stray_prose_tags():
    """Verifies 22b: sentence-trailing difficulty tags lift under ##### <Nr> and stray prose tags strip."""
    # 1. Generic FIBS mode (without custom_rules): trailing [schwierig] / [mittel] lifted under ##### <Nr>
    md_generic = (
        "((30))\n\n"
        "##### Aufgaben\n\n"
        "##### 1\n\n"
        "Beschreiben Sie den Aufbau einer Pflanzenzelle. [einfach]\n\n"
        "##### 2\n\n"
        "a)\tNennen Sie zwei Zellorganellen.\n"
        "b)\tBegründen Sie deren Funktion im Stoffwechsel [schwierig].\n\n"
        "<Bild> Diagramm:\n"
        "Beschreibung: Balkenvergleich für Gruppe A [mittel].\n"
        "</Bild>\n"
    )
    out_generic = post_process_structure(md_generic)
    assert "##### 1\n[einfach]\n\nBeschreiben Sie den Aufbau einer Pflanzenzelle." in out_generic
    assert (
        "##### 2\n[schwierig]\n\na)\tNennen Sie zwei Zellorganellen.\n"
        "b)\tBegründen Sie deren Funktion im Stoffwechsel."
    ) in out_generic
    assert "Balkenvergleich für Gruppe A [mittel]." in out_generic

    # 2. Buchkonferenz point_difficulty_map active: [leicht]/[schwer] normalized and stray prose [mittel] rescued/stripped
    bk_rules = (
        "##### Überschrift 5: Aufgabennummern\n"
        "Sonstiges:\n"
        "- Schwierigkeitsgrade bei Aufgaben:\n"
        "  1 Punkt: [einfach]\n"
        "  2 Punkte: [mittel]\n"
        "  3 Punkte: [schwierig]\n"
    )
    md_bk = (
        "((31))\n\n"
        "Die Messreihe zeigt eine deutliche Zunahme der Reaktionsrate bei Erwärmung. [mittel]\n\n"
        "##### 1\n\n"
        "Werten Sie die dargestellte Messreihe quantitativ aus.\n\n"
        "##### 2\n\n"
        "Formulieren Sie eine kurze Definition der Aktivierungsenergie. [leicht]\n\n"
        "((32))\n\n"
        "Einleitender Sachtext zur Katalyse im Laborversuch. [mittel]\n\n"
        "##### 1\n[einfach]\n\n"
        "Benennen Sie die verwendeten Reagenzien.\n\n"
        "##### 2\n\n"
        "Diskutieren Sie mögliche Fehlerquellen der Messung. [schwer]\n"
    )
    out_bk = post_process_structure(md_bk, custom_rules=bk_rules)
    assert "bei Erwärmung. [mittel]" not in out_bk
    assert "Die Messreihe zeigt eine deutliche Zunahme der Reaktionsrate bei Erwärmung." in out_bk
    assert "##### 1\n[mittel]\n\nWerten Sie die dargestellte Messreihe quantitativ aus." in out_bk
    assert (
        "##### 2\n[einfach]\n\nFormulieren Sie eine kurze Definition der Aktivierungsenergie."
        in out_bk
    )
    assert "im Laborversuch. [mittel]" not in out_bk
    assert "Einleitender Sachtext zur Katalyse im Laborversuch." in out_bk
    assert "##### 2\n[schwierig]\n\nDiskutieren Sie mögliche Fehlerquellen der Messung." in out_bk


def test_strip_math_and_variable_emphasis_footnote_brace_fix_and_excel_dollar_protection():
    """Verifies zero-bold on variables/formulas, {n} footnote brace safety on \\f{1}{3}, and Excel $F$1 safety."""
    from backend.services.fibs_postprocess import strip_math_and_variable_emphasis

    # 1. Exact user-reported rotation/mechanics cases
    assert post_process_structure("_E_kin_ = _1/2 J omega^2_.").strip() == "E_{kin} = 1/2J~w^2."
    assert (
        post_process_structure("Die Teilmassen _Delta m_i_ bestimmt man einzeln.").strip()
        == "Die Teilmassen ~Dm_i bestimmt man einzeln."
    )

    # 2. Split subscripts, vectors, integrals, spelled-out Greek, single-letter & multi-token math vs. prose emphasis
    complex_md = (
        "((15))\n\n"
        "Für _starre Körper_ gilt der _Drehimpulserhaltungssatz:_ Die _Wärmeenergie_ und der _Reaktionsweg_ "
        "werden mit der _Methode der kleinen Schritte_ (lat. _iterare_) berechnet; Lücke: _..._.\n\n"
        "Größen: _F_G_, _F_Z_, _F_R_, _E_R_, _E_s_, _s_0_, _v_0_, _v_i_, _r_i_, _m_1_, _v'_1_, _v'_{12}_, "
        "_E_{kin}_, _E_{pot}_, _E_{kin}(t)_, _F_s(s)_, _v(t)_, _a(t)_, _s(t)_, _a_Z_, _m_r^2_, "
        "\\int_0^_m r_^2 dm_.\n\n"
        "Vektoren & Tilde: \\vec{F_}_, \\vec{p_}_, \\vec{v_}_, \\vec{a_}_, \\vec{r_}_, \\vec{F_A_}_, "
        "\\vec{F_Z_}_, \\vec{\\simw_}_, ~w_, ~D _t_, ~D _E_.\n\n"
        "Griechisch & Produkte: Delta m_1, Delta v, Delta t, Delta omega, _r_i omega_, _alpha_, "
        "J alpha, r alpha, M/alpha, Jalpha, alpha ~ M, _m_, _F_, _v_, _r_, _s_, _t_, _J_, "
        "_ma_, _mg_, _mgh_, _rF_, _vt_, _at_, _mr^2_, _r(ma)_, _1/2 mv^2_.\n\n"
        "-\t_Grenzfrequenz f_G = \\frac{W_A}{h}:_ Unterhalb von f_G tritt kein Effekt auf.\n\n"
        "Brüche & Fußnoten: \\frac{1}{3} + \\f{1}{10} sowie bereits beschädigt \\frac{1}^3 und \\f{5}^12.\n\n"
        "Tabellenkalkulation: Verwendung von $-Zeichen, sodass die Formel `=B2+$F$1` bzw. =A2+$F$1 kopiert wird, "
        "wenn die Konstante im Feld $F$1 steht.\n"
    )
    out = post_process_structure(complex_md)

    # Genuine prose emphasis and gap markers stay intact
    assert "_starre Körper_" in out
    assert "_Drehimpulserhaltungssatz:_" in out
    assert "_Wärmeenergie_" in out
    assert "_Reaktionsweg_" in out
    assert "_Methode der kleinen Schritte_" in out
    assert "_iterare_" in out
    assert "_..._" in out

    # Split subscripts, functions, and integral bounds repaired without underscores around variables
    for expected_tok in (
        "F_G,", "F_Z,", "F_R,", "E_R,", "E_s,", "s_0,", "v_0,", "v_i,", "r_i,", "m_1,",
        "v'_1,", "v'_{12},", "E_{kin},", "E_{pot},", "E_{kin}(t),", "F_s(s),",
        "v(t),", "a(t),", "s(t),", "a_Z,", "m r^2,", r"\int_0^m r^2 dm.",
    ):
        assert expected_tok in out, f"Missing {expected_tok!r} in:\n{out}"

    # Vectors & tilde tokens cleaned
    for vec_tok in (
        r"\vec{F},", r"\vec{p},", r"\vec{v},", r"\vec{a},", r"\vec{r},",
        r"\vec{F_A},", r"\vec{F_Z},", r"\vec{~w},", "~w,", "~Dt,", "~DE.",
    ):
        assert vec_tok in out, f"Missing {vec_tok!r} in:\n{out}"

    # Spelled-out Greek & unwrapped products
    for prod_tok in (
        "~Dm_1,", "~Dv,", "~Dt,", "~D~w,", "r_i ~w,", "~a,",
        "J~a,", "r~a,", "M/~a,", r"~a \sim M,",
        " m, F, v, r, s, t, J,", "ma, mg, mgh, rF, vt, at, mr^2, r(ma), 1/2mv^2.",
    ):
        assert prod_tok in out, f"Missing {prod_tok!r} in:\n{out}"

    # Colon-terminated label splits trailing formula outside emphasis
    assert r"-\t_Grenzfrequenz_ f_G = \f{W_A}{h}:" in out or "-\t_Grenzfrequenz_ f_G = \\f{W_A}{h}:" in out

    # Fractions never corrupted into footnote superscripts ^3 / ^10, and corrupted \frac{1}^3 repaired
    assert r"\f{1}{3} + \f{1}{10}" in out
    assert r"beschädigt \f{1}{3} und \f{5}{12}." in out
    assert "^3" not in out and "^10" not in out and "^12" not in out

    # Excel $F$1 and prose $-Zeichen never leak __EMPH_PROT_ placeholders
    assert "__EMPH_PROT_" not in out
    assert "__MATH_EMPH_PROT_" not in out
    assert "Verwendung von $-Zeichen" in out
    assert "`=B2+$F$1`" in out
    assert "=A2+$F$1" in out
    assert "im Feld $F$1 steht." in out

    # Metalinguistic 'the letter _q_' preserved
    assert strip_math_and_variable_emphasis("the letter _q_ is followed by the letter _u_") == (
        "the letter _q_ is followed by the letter _u_"
    )

    # 3. Regression checks for all 5 real-textbook edge cases
    edge_md = (
        "((16))\n\n"
        "#### M2 Drehmoment M = rF oder _M = r_a F cos ~h\n\n"
        "Die _Winkelbeschleunigung ~a_ und das _Drehmoment M_ hängen zusammen.\n\n"
        "Werte: _~a, _~w, _~f, _~D ~w_, [_~a], ~D t_, \\f{~D p}{~D t_}, 9,81 m/s^2_, 9,81 ~m/s^2_, _m/s^2_.\n\n"
        "Terme: _m\\vec{v}, _m\\vec{a}, _J\\vec{~w}, -_m~w^2, _m~w^2, \\vec{p_1}_, \\f{_v^2}{r}.\n\n"
        "Stoß: _v'_1_ = _m_2_(2_v_2_ - _v_1_) + _v'_2_ sowie 2_v_2 - v_1.\n\n"
        "Quotienten & Produkte: _F/a_, _rDelta omega/~Dt_, rDelta omega, mr alpha, mr^2 alpha.\n"
    )
    edge_out = post_process_structure(edge_md)

    assert "#### M2 Drehmoment M = rF oder M = r_a F cos ~h" in edge_out
    assert "Die _Winkelbeschleunigung_ ~a und das _Drehmoment_ M hängen zusammen." in edge_out
    assert "Werte: ~a, ~w, ~f, ~D~w, [~a], ~Dt, \\f{~Dp}{~Dt}, 9,81 m/s^2, 9,81 m/s^2, m/s^2." in edge_out
    assert (
        "Terme: m\\vec{v}, m\\vec{a}, J\\vec{~w}, -m~w^2, m~w^2, \\vec{p_1}, \\f{v^2}{r}."
        in edge_out
    )
    assert "Stoß: v'_1 = m_2(2v_2 - v_1) + v'_2 sowie 2v_2 - v_1." in edge_out
    assert "Quotienten & Produkte: F/a, r~D~w/~Dt, r~D~w, mr~a, mr^2~a." in edge_out









