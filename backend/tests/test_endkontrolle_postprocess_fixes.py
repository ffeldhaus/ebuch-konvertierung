"""Synthetic unit tests for Track 3 FIBS post-processing, TOC scoping, Buchkonferenz & echo dedup."""

from __future__ import annotations

from backend.services.a11y_linter import lint_markdown
from backend.services.fibs_postprocess import (
    infer_heading_hierarchy,
    post_process_structure,
    split_markdown_pages,
)
from backend.services.llm_service import deduplicate_cross_page_echoes


def test_fix3_figure_prefix_b_and_headings_before_bild_never_become_aufgaben() -> None:
    """Fix #3: Configured figure prefix (B1/B2) and number headings before <Bild>/<Bild-Ref> are not hijacked into Aufgaben."""
    bk_rules = (
        "### Überschrift 3: Methode, Material\n"
        "#### Überschrift 4: Abbildungsunterschriften (B + Bildunterschrift)\n"
        "##### Überschrift 5: Aufgaben und Aufgabennummern\n"
    )
    md = (
        "((14))\n\n"
        "### Material\n\n"
        "#### B1\n\n"
        "<Bild> Grafik:\nBeschreibung: Schema einer Optikbank.\n</Bild>\n\n"
        "#### B2 Strahlengang an einer Sammellinse\n\n"
        "<Bild> Diagramm:\nBeschreibung: Drei Lichtstrahlen schneiden sich im Brennpunkt.\n</Bild>\n\n"
        "#### 3\n\n"
        '<Bild-Ref id="BILD_003" />\n\n'
        "##### 4\n\n"
        "<Bild> Foto:\nBeschreibung: Messaufbau auf einem Labortisch.\n</Bild>\n\n"
        "3 Erkläre die dargestellte Versuchsanordnung.\n\n"
        "<Bild> Zeichnung:\nBeschreibung: Skizze mit zwei Spiegeln.\n</Bild>\n\n"
        "##### Aufgaben\n\n"
        "#### A1\n\n"
        "Erläutern Sie den Verlauf des Parallelstrahls.\n"
    )

    out = post_process_structure(md, custom_rules=bk_rules)

    assert "##### B1" not in out
    assert "##### B2" not in out
    assert "#### B1" in out
    assert "#### B2 Strahlengang an einer Sammellinse" in out
    assert "##### Aufgaben\n\n##### 3" not in out
    assert "##### Aufgaben\n\n##### 4" not in out
    # Real task inside Aufgaben still works
    assert "##### Aufgaben\n\n##### A1" in out
    assert out.count("##### Aufgaben") == 1


def test_fix4b_rahmen_emphasis_giant_h4_demotion_and_merke_heading() -> None:
    """Fix #4b: Strips full/chunked _..._ inside <Rahmen>, demotes giant #### summaries, and adds #### Merke."""
    bk_rules = (
        "#### Überschrift 4: Merke + Rahmen-Tag (grüne Zusammenfassung)\n"
        "##### Überschrift 5: Aufgaben und Aufgabennummern\n"
    )
    long_summary = (
        "In einem abgeschlossenen System bleibt die gesamte mechanische Energie konstant. "
        "Potenzielle und kinetische Energie lassen sich verlustfrei ineinander umwandeln."
    )
    long_pre_task = (
        "Die Geschwindigkeit gibt an, welche Strecke ein Körper in einer bestimmten Zeitspanne zurücklegt. "
        "Bei gleichförmiger Bewegung bleibt das Verhältnis aus Weg und Zeit konstant."
    )
    md = (
        "((22))\n\n"
        "### Energieerhaltung im Modell\n\n"
        "Ein kurzer Einleitungssatz führt in das Thema ein.\n\n"
        "<Rahmen>\n"
        "_Die Gesamtenergie in einem abgeschlossenen System mit CO_2 bleibt stets erhalten._ "
        "_Sie kann weder neu erschaffen noch vollständig vernichtet werden._\n"
        "</Rahmen>\n\n"
        "#### Randspalte\n\n"
        "<Rahmen>\n"
        "Ein _Katalysator_ senkt die _Aktivierungsenergie_ einer chemischen Reaktion.\n"
        "</Rahmen>\n\n"
        "<Rahmen>\n"
        f"#### {long_summary}\n"
        "</Rahmen>\n\n"
        f"#### {long_pre_task}\n\n"
        "##### Aufgaben\n\n"
        "1 Nenne zwei Energieformen.\n"
    )

    out = post_process_structure(md, custom_rules=bk_rules)

    # Full/multi-chunk _..._ inside <Rahmen> unwrapped while preserving CO_2 and selective emphasis
    assert (
        "Die Gesamtenergie in einem abgeschlossenen System mit CO_2 bleibt stets erhalten. "
        "Sie kann weder neu erschaffen noch vollständig vernichtet werden."
    ) in out
    assert "_Die Gesamtenergie" not in out
    assert "Ein _Katalysator_ senkt die _Aktivierungsenergie_ einer chemischen Reaktion." in out

    # Giant multi-sentence #### inside <Rahmen> and right before ##### Aufgaben demoted to prose
    assert f"#### {long_summary}" not in out
    assert f"<Rahmen>\n{long_summary}\n</Rahmen>" in out
    assert f"#### {long_pre_task}" not in out
    assert f"\n{long_pre_task}\n" in out

    # Buchkonferenz 'Merke + Rahmen-Tag' adds #### Merke above unheaded <Rahmen> but not above #### Randspalte
    assert out.count("#### Merke\n\n<Rahmen>") == 2
    assert "#### Randspalte\n\n<Rahmen>" in out
    assert "#### Randspalte\n\n#### Merke" not in out


def test_fix7b_and_20_dedup_across_bild_demote_etymology_and_prevent_h3_to_h5_jump() -> None:
    """Fixes #7b-1, #7b-2, and #20: same-page heading dedup across <Bild>/<Bild-Ref>, etymology demotion, H3->H5 guard."""
    md = (
        "((30))\n\n"
        "# Kapitel 1 Grundlagen\n\n"
        "## 1.1 Zellvorgänge\n\n"
        "### Der Wasserkreislauf\n\n"
        "#### Verdunstung und Kondensation\n\n"
        "<Bild> Grafik:\nBeschreibung: Pfeile zeigen aufsteigenden Wasserdampf.\n</Bild>\n\n"
        "#### Verdunstung und Kondensation\n\n"
        "Wasser steigt aus Gewässern auf und bildet Wolken.\n\n"
        "#### Osmose\n\n"
        '<Bild-Ref id="BILD_009" />\n\n'
        "#### Osmose\n\n"
        "Lösungsmittel strömt durch eine halbdurchlässige Membran.\n\n"
        "### lat. vegetare = beleben\n\n"
        "#### engl. stress = Druck, Anspannung\n\n"
        "### Vergleich der Zelltypen\n\n"
        "##### A\n\n"
        "Tierische Zelle ohne Zellwand.\n\n"
        "##### B\n\n"
        "Pflanzliche Zelle mit Chloroplasten.\n"
    )

    out = post_process_structure(md)

    # 7b-1: Duplicate headings separated only by <Bild> or <Bild-Ref> are deduplicated
    assert out.count("#### Verdunstung und Kondensation") == 1
    assert out.count("#### Osmose") == 1

    # 7b-2: Margin etymology headings are demoted to plain text
    assert "### lat. vegetare = beleben" not in out
    assert "lat. vegetare = beleben" in out
    assert "#### engl. stress = Druck, Anspannung" not in out
    assert "engl. stress = Druck, Anspannung" in out

    # 20: Isolated ##### A / ##### B without #### parent demoted to plain text -> zero H3->H5 lint warning
    assert "##### A" not in out
    assert "##### B" not in out
    assert "\nA\n\nTierische Zelle ohne Zellwand." in out
    assert "\nB\n\nPflanzliche Zelle mit Chloroplasten." in out

    report = lint_markdown(out)
    skip_issues = [iss for iss in report.issues if iss.rule == "heading_hierarchy"]
    assert skip_issues == [], f"Unexpected heading hierarchy issues: {skip_issues}"


def test_fix14_toc_heading_overrides_scoped_to_target_page_plus_minus_one() -> None:
    """Fix #14: Repeating chapter names on later summary/exercise pages are NOT promoted to TOC H1/H2."""
    bk_rules = (
        "# Überschrift 1: Hauptkapitel\n"
        "## Überschrift 2: Teilkapitel\n"
        "### Überschrift 3: Methode, Exkurs\n"
        "#### Überschrift 4: schwarze Textüberschriften\n"
    )
    directory_info = {
        "has_any_directory": True,
        "detected_types": ["toc"],
        "toc_entries": [
            {"title": "1 Kinematik", "clean_title": "Kinematik", "page": 10, "level": 1},
            {"title": "2 Dynamik", "clean_title": "Dynamik", "page": 30, "level": 2},
            {"title": "Grundwissen", "clean_title": "Grundwissen", "page": 82, "level": 2},
        ],
        "heading_levels": {
            "1 kinematik": 1,
            "kinematik": 1,
            "2 dynamik": 2,
            "dynamik": 2,
            "grundwissen": 2,
        },
    }
    md_p10 = (
        "((10))\n\n"
        "### Kinematik\n\n"
        "Bewegungslehre beschreibt Ort, Geschwindigkeit und Beschleunigung.\n"
    )
    out_p10 = post_process_structure(
        md_p10,
        raw_markdown=md_p10,
        directory_info=directory_info,
        custom_rules=bk_rules,
    )
    assert "# Kinematik" in out_p10

    md_p82 = (
        "((82))\n\n"
        "### Grundwissen\n\n"
        "### Zusammenfassung der Themen\n\n"
        "#### Kinematik\n\n"
        "Gleichförmige Bewegungen besitzen eine konstante Geschwindigkeit.\n\n"
        "#### Dynamik\n\n"
        "Kräfte ändern den Bewegungszustand eines Körpers.\n\n"
        "((83))\n\n"
        "#### Kinematik\n\n"
        "Aufgaben zur Wiederholung der Bewegungslehre.\n"
    )
    out_p82 = post_process_structure(
        md_p82,
        raw_markdown=md_p82,
        directory_info=directory_info,
        custom_rules=bk_rules,
    )
    pages_82 = {seg.page: seg.text for seg in split_markdown_pages(out_p82)}

    # Target page ((82)) applies its own TOC H2 'Grundwissen'
    assert "## Grundwissen" in pages_82["82"]
    # Repeating sub-topics on ((82)) and ((83)) stay #### (NOT promoted to # or ##)
    assert "#### Kinematik" in pages_82["82"]
    assert "#### Dynamik" in pages_82["82"]
    assert "\n# Kinematik" not in pages_82["82"]
    assert "\n## Dynamik" not in pages_82["82"]
    assert "#### Kinematik" in pages_82["83"]
    assert "\n# Kinematik" not in pages_82["83"]

    report = lint_markdown(out_p82)
    skip_issues = [iss for iss in report.issues if iss.rule == "heading_hierarchy"]
    assert skip_issues == [], f"Unexpected heading hierarchy issues: {skip_issues}"

    # Safe fallback when document has NO ((N)) page markers at all
    no_pages_out = infer_heading_hierarchy("### Kinematik\n\nText.", directory_info=directory_info)
    assert "# Kinematik" in no_pages_out


def test_fix15_no_repeated_aufgaben_after_inline_figure_headings() -> None:
    """Fix #15: Inline figure/table headings inside an active Aufgaben block do not re-emit ##### Aufgaben."""
    bk_rules = (
        "#### Überschrift 4: Abbildungsunterschriften (mit M)\n"
        "##### Überschrift 5: Aufgaben und Aufgabennummern\n"
    )
    md = (
        "((44))\n\n"
        "##### Aufgaben\n\n"
        "##### 23\n\n"
        "Berechne die mittlere Geschwindigkeit aus dem Diagramm.\n\n"
        "#### M1 Weg-Zeit-Diagramm einer Messfahrt\n\n"
        "<Bild> Diagramm:\nBeschreibung: Lineare Kurve im Weg-Zeit-Koordinatensystem.\n</Bild>\n\n"
        "##### 24\n\n"
        "Bestimme die Beschleunigung im zweiten Abschnitt.\n\n"
        "#### B2 Schaltplan des Experiments\n\n"
        '<Bild-Ref id="BILD_012" />\n\n'
        "##### 25\n\n"
        "Vergleiche die Messreihen in der folgenden Übersicht.\n\n"
        "#### Tab. 1 Messwerte der Spannung\n\n"
        "<Tabelle>\n| Zeit | Spannung | Strom | Leistung |\n| --- | --- | --- | --- |\n"
        "| 1 s | 2 V | 0,5 A | 1 W |\n| 2 s | 4 V | 1,0 A | 4 W |\n</Tabelle>\n\n"
        "##### 26\n\n"
        "Bewerte die Messgenauigkeit.\n"
    )

    out = post_process_structure(md, custom_rules=bk_rules, table_max_cells=6)

    assert out.count("##### Aufgaben") == 1
    assert "##### 23" in out
    assert "##### 24" in out
    assert "##### 25" in out
    assert "##### 26" in out


def test_fix16b_strip_literal_nr_and_bild_ref_leaked_ghost_headings() -> None:
    """Fix #16b: Strips literal <Nr> placeholders, zero-padded M026/B034 headings, and unbacked bare M26 ghosts."""
    raw_md = (
        "((50))\n\n"
        "### Messmethoden\n\n"
        "1 Aufbau eines Spektrometers\n\n"
        '<Bild-Ref id="BILD_026" />\n\n'
        "Text ohne die Zahl sechsundzwanzig.\n"
    )
    llm_md = (
        "((50))\n\n"
        "### Messmethoden\n\n"
        "#### M<Nr>\n\n"
        "#### B<Nr> Beispieltitel\n\n"
        "##### <Nr>\n\n"
        "#### M026\n\n"
        "#### B034\n\n"
        "#### M26\n\n"
        "<Bild> Grafik:\nBeschreibung: Prisma zerlegt weißes Licht.\n</Bild>\n\n"
        "#### M1 Aufbau eines Spektrometers\n\n"
        "<Bild> Zeichnung:\nBeschreibung: Lichtquelle, Spalt und Schirm.\n</Bild>\n\n"
        "Die Kalibrierung erfolgt anhand bekannter Spektrallinien.\n\n"
        "#### M12 Kalibrierungskurve\n\n"
        "<Bild> Diagramm:\nBeschreibung: Kurve mit Wellenlängen auf der Achse.\n</Bild>\n"
    )

    out = post_process_structure(llm_md, raw_markdown=raw_md)

    assert "<Nr>" not in out
    assert "M026" not in out
    assert "B034" not in out
    assert "#### M26" not in out
    # Genuine low/titled figure numbers remain intact
    assert "#### M1 Aufbau eines Spektrometers" in out
    assert "#### M12 Kalibrierungskurve" in out


def test_fix18_buchkonferenz_material_mit_aufgaben_and_lettered_colon_u4() -> None:
    """Fix #18: Enforces #### A: colon convention and restores missing ### Material mit Aufgaben."""
    bk_rules = (
        "### Überschrift 3: Methode, Basiskonzept, Material mit Aufgaben\n"
        "#### Überschrift 4: Materialüberschriften (z. B. A: Versuchsaufbau, B: Auswertung)\n"
        "##### Überschrift 5: Aufgaben und Aufgabennummern\n"
    )
    raw_md = (
        "((64))\n\n"
        "Material\nmit Aufgaben\n\n"
        "A Versuchsaufbau mit Messfühler\n\n"
        "Der Sensor misst die Temperatur im Wasserbad.\n\n"
        "B Auswertung der Messreihe\n\n"
        "Die Messwerte steigen gleichmäßig an.\n\n"
        "Aufgaben\n\n"
        "1 Beschreibe den Versuchsaufbau.\n"
    )
    # Gemma dropped the 'Material mit Aufgaben' banner and omitted colons on A / B
    llm_md = (
        "((64))\n\n"
        "#### A Versuchsaufbau mit Messfühler\n\n"
        "Der Sensor misst die Temperatur im Wasserbad.\n\n"
        "#### B Auswertung der Messreihe\n\n"
        "Die Messwerte steigen gleichmäßig an.\n\n"
        "##### Aufgaben\n\n"
        "##### 1\n\n"
        "Beschreibe den Versuchsaufbau.\n"
    )

    out = post_process_structure(llm_md, raw_markdown=raw_md, custom_rules=bk_rules)

    assert "### Material mit Aufgaben\n\n#### A: Versuchsaufbau mit Messfühler" in out
    assert "#### B: Auswertung der Messreihe" in out
    assert out.count("### Material mit Aufgaben") == 1

    # Also test split-line 'Material\nmit Aufgaben' and boxed '<Rahmen>Material mit Aufgaben</Rahmen>'
    split_md = (
        "((65))\n\n"
        "<Rahmen>\n_Material mit Aufgaben_\n</Rahmen>\n\n"
        "#### A Messreihe im Labor\n\n"
        "##### Aufgaben\n\n"
        "##### 1\n\n"
        "Werte die Daten aus.\n"
    )
    out_split = post_process_structure(split_md, custom_rules=bk_rules)
    assert "### Material mit Aufgaben" in out_split
    assert "#### A: Messreihe im Labor" in out_split
    assert "<Rahmen>" not in out_split


def test_fix19_deduplicate_cross_page_echoes_handles_prefix_variations_and_long_echoes() -> None:
    """Fix #19: Strips multi-block echoes with M1/1 heading variations while keeping genuinely new P+1 content."""
    assembled = (
        "((40))\n\n"
        "# 2 Optik und Lichtbrechung\n\n"
        "#### M1 Reflexion am ebenen Spiegel\n\n"
        "Ein Lichtstrahl trifft unter dem Einfallswinkel auf eine glatte Spiegelfläche auf.\n\n"
        "#### M2 Brechung beim Übergang in Glas\n\n"
        "Beim Eintritt in ein optisch dichteres Medium wird der Lichtstrahl zum Lot hin gebrochen.\n\n"
        "Kurzer Merksatz zur Lichtausbreitung.\n\n"
        "#### M3 Totalreflexion im Prisma\n\n"
        "Überschreitet der Einfallswinkel den Grenzwinkel, tritt vollständige Reflexion auf.\n\n"
        "##### Aufgaben\n\n"
        "##### 1\n\n"
        "Zeichne den Strahlengang an einer planparallelen Glasplatte maßstabsgetreu ein.\n\n"
        "((41))\n\n"
        "# 2 Optik und Lichtbrechung\n\n"
        "#### 1 Reflexion am ebenen Spiegel\n\n"
        "Ein Lichtstrahl trifft unter dem Einfallswinkel auf eine glatte Spiegelfläche auf.\n\n"
        "#### B2: Brechung beim Übergang in Glas\n\n"
        "Beim Eintritt in ein optisch dichteres Medium wird der Lichtstrahl zum Lot hin gebrochen.\n\n"
        "Kurzer Merksatz zur Lichtausbreitung.\n\n"
        "#### 3 Totalreflexion im Prisma\n\n"
        "Überschreitet der Einfallswinkel den Grenzwinkel, tritt vollständige Reflexion auf.\n\n"
        "##### Aufgaben\n\n"
        "##### 1\n\n"
        "Zeichne den Strahlengang an einer planparallelen Glasplatte maßstabsgetreu ein.\n\n"
        '<Bild-Ref id="BILD_041" />\n\n'
        "#### M4 Zerlegung von weißem Licht\n\n"
        "Weißes Licht fächert sich hinter einem Glasprisma in ein kontinuierliches Farbspektrum auf.\n"
    )

    cleaned = deduplicate_cross_page_echoes(assembled)
    segs = {s.page: s.text for s in split_markdown_pages(cleaned)}

    p41 = segs["41"]
    assert "Reflexion am ebenen Spiegel" not in p41
    assert "Brechung beim Übergang in Glas" not in p41
    assert "Kurzer Merksatz zur Lichtausbreitung." not in p41
    assert "Totalreflexion im Prisma" not in p41
    assert "planparallelen Glasplatte" not in p41
    assert "##### Aufgaben" not in p41
    assert '<Bild-Ref id="BILD_041" />' in p41
    assert "#### M4 Zerlegung von weißem Licht" in p41
    assert "kontinuierliches Farbspektrum" in p41

    # Different figure number and genuinely new Aufgaben block on P+1 must NEVER be stripped
    distinct_md = (
        "((50))\n\n"
        "#### M1 Aufbau einer Batterie\n\n"
        "##### Aufgaben\n\n"
        "##### 1\n\n"
        "Nenne die Bestandteile einer galvanischen Zelle.\n\n"
        "((51))\n\n"
        "#### M2 Aufbau einer Batterie\n\n"
        "##### Aufgaben\n\n"
        "##### 2\n\n"
        "Berechne die elektrische Spannung der Reihenschaltung.\n"
    )
    distinct_out = deduplicate_cross_page_echoes(distinct_md)
    p51 = {s.page: s.text for s in split_markdown_pages(distinct_out)}["51"]
    assert "#### M2 Aufbau einer Batterie" in p51
    assert "##### Aufgaben" in p51
    assert "Berechne die elektrische Spannung der Reihenschaltung." in p51
