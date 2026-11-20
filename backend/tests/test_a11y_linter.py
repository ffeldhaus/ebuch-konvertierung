import pytest
from backend.services.a11y_linter import lint_markdown

def test_lint_perfect_ebuch():
    md = """# Kapitel 1: Optik

((45))

Das Licht breitet sich bei 20 °C zu 100 % geradlinig um 90° aus. Hierzu ein Experiment^1:

-\\tErster Schritt: Aufbau
-\\tZweiter Schritt: Messung

#### M1 Strahlengang am Prisma

<Bild> Zeichnung:
Beschreibung mit Bildtext: Lichtquelle \\xra{weißes Licht} Prisma \\to Spektrum (~l = 400 nm bis 780 nm).
</Bild>

Formel der Brechung: n_1 * sin(~a) = n_2 * sin(~b) sowie \\f{1}{2} m v^2.

Hier ist ein wichtiger Begriff{1}.

#### Worterklärungen

^1: Optischer Versuch zur Dispersion.

((46))

<Anmerkung> 1 Dies ist eine Erklaerung der Brechung. </Anmerkung>
"""
    report = lint_markdown(md)
    assert report.score == 100
    assert report.passed is True
    assert len(report.issues) == 0

def test_lint_heading_hierarchy_skip():
    md = """# Kapitel 1

### Übersprungene Ebene
Etwas Text.
"""
    report = lint_markdown(md)
    assert any(i.rule == "heading_hierarchy" for i in report.issues)
    assert report.score < 100

def test_lint_image_missing_or_placeholder():
    md = """# Kapitel 1
<Bild> Abbildung ohne Beschreibung </Bild>
<Bild>
"""
    report = lint_markdown(md)
    rules = [i.rule for i in report.issues]
    assert "image_placeholder" in rules or "image_unclosed" in rules

def test_lint_footnote_mismatch():
    md = """# Text
Begriff ohne Erklaerung{1}.
"""
    report = lint_markdown(md)
    rules = [i.rule for i in report.issues]
    assert "footnote_missing_definition" in rules

def test_lint_list_tab_delimiter():
    md = """# Text
- Falsche Liste mit Leerzeichen
* Noch eine falsche Liste
"""
    report = lint_markdown(md)
    rules = [i.rule for i in report.issues]
    assert "list_delimiter" in rules

def test_lint_page_number_format():
    md = """# Text
Seite 45
"""
    report = lint_markdown(md)
    rules = [i.rule for i in report.issues]
    assert "page_number_format" in rules


def test_lint_image_format_requires_multiline_fibs_block():
    legacy = "# Text\n\n<Bild> Foto: Ein Haus am See. </Bild>\n"
    rules = [i.rule for i in lint_markdown(legacy).issues]
    assert "image_format" in rules

    fibs = "# Text\n\n<Bild> Foto:\nBeschreibung: Ein Haus am See.\n</Bild>\n"
    rules = [i.rule for i in lint_markdown(fibs).issues]
    assert "image_format" not in rules


def test_lint_unicode_scripts_flagged_and_autofixed():
    from backend.services.a11y_linter import autofix_markdown
    md = "# Text\n\nWasser hat die Formel H₂O.\n"
    rules = [i.rule for i in lint_markdown(md).issues]
    assert "unicode_script" in rules
    fixed, fixes = autofix_markdown(md + "\n<Bild> Foto: Ein Glas. </Bild>\n")
    assert "H_2O" in fixed
    assert "<Bild> Foto:\nBeschreibung: Ein Glas.\n</Bild>" in fixed
    assert lint_markdown(fixed).score == 100


def test_autofix_markdown_fixes_all_common_issues():
    from backend.services.a11y_linter import autofix_markdown
    faulty_md = """# Kapitel 1: Start
### Übersprungene Unterüberschrift

Seite 45

- Falsche Liste ohne Tab
1. Nummerierte Liste ohne Tab

<L> x = \\sqrt{16} </L>

Begrifferklärung{1}.
<Anmerkung> 1 Erklärung </Anmerkung>
"""
    fixed_md, applied_fixes = autofix_markdown(faulty_md)
    assert len(applied_fixes) > 0
    assert "-\tFalsche Liste" in fixed_md
    assert "1.\tNummerierte Liste" in fixed_md
    assert "## Übersprungene" in fixed_md
    assert "((45))" in fixed_md
    assert "<L>" not in fixed_md and "</L>" not in fixed_md

    # Run linter on fixed markdown
    report = lint_markdown(fixed_md)
    assert report.score == 100
    assert report.passed is True


def test_lint_and_autofix_preserve_caption_and_exercise_headings():
    from backend.services.a11y_linter import autofix_markdown, lint_markdown

    # Document-specific rule: Level 4 for image captions and Level 3 for tasks directly under H1/H2
    custom_doc = """# 1. Hauptkapitel

((1))

Hier ist ein einleitender Absatz.

#### Abbildung 1.1: Schematischer Aufbau des Experiments.

Text nach dem Bild.

### Aufgabe 1: Berechnen Sie den Brechungsindex.

-\\tTeilaufgabe a
-\\tTeilaufgabe b

((2))
"""
    # 1. Linting should not flag H1 -> H4 for Abbildung or H1 -> H3 for Aufgabe as hierarchy errors
    report = lint_markdown(custom_doc)
    assert not any(i.rule == "heading_hierarchy" for i in report.issues)
    assert report.score == 100

    # 2. Autofix must strictly preserve '#### Abbildung' and '### Aufgabe' without altering their levels
    fixed, fixes = autofix_markdown(custom_doc)
    assert "#### Abbildung 1.1: Schematischer Aufbau des Experiments." in fixed
    assert "### Aufgabe 1: Berechnen Sie den Brechungsindex." in fixed


def test_lint_syntactic_fibs_rules_3a():
    """Tests 3a syntactic & FIBS checks: unbalanced tags, unconverted images/tables,
    page monotonicity/duplicates, unresolved small tables, markdown bold, copyright, raw blanks."""
    faulty = """# 1. Kapitel

((2))

((2))

Dies ist **fetter Text** mit © Symbol und Lücke ____.

![](images/pic1.png)

<table><tr><td>A</td><td>B</td></tr></table>

<Rahmen>
Unbalancierter Rahmen ohne Ende.

<Tabelle>
Spalte 1\tSpalte 2
Wert 1\tWert 2
</Tabelle>

((1))
"""
    report = lint_markdown(faulty, table_max_cells=10)
    rules = {i.rule for i in report.issues}
    assert "page_number_duplicate" in rules
    assert "page_number_non_monotonic" in rules
    assert "fibs_markdown_bold" in rules
    assert "fibs_copyright_symbol" in rules
    assert "fibs_raw_fill_in_blanks" in rules
    assert "image_unconverted_markdown" in rules
    assert "html_table_unconverted" in rules
    assert "rahmen_unbalanced" in rules
    assert "table_unresolved_small" in rules


def test_lint_source_completeness_checks_3b():
    """Tests 3b source-aware completeness checks: missing page markers and omitted captioned images."""
    raw_md = """((10))

# Kapitel 1

![](images/exp1.png)
Abbildung 1.1: Versuchsaufbau zur Lichtbrechung

((11))

Weiterer Text auf Seite 11.
"""
    # Standardised output dropped ((11)) and omitted the captioned image on page 10
    std_md = """((10))

# Kapitel 1

Abbildung 1.1: Versuchsaufbau zur Lichtbrechung

Weiterer Text auf Seite 11.
"""
    report = lint_markdown(std_md, raw_markdown=raw_md, expected_pages=2)
    rules = {i.rule for i in report.issues}
    assert "page_number_missing" in rules
    assert "image_omitted" in rules


def test_autofix_extended_3a_fixes():
    """Tests autofix for consecutive duplicate page markers, **bold**, ©/®, and ____ blanks."""
    from backend.services.a11y_linter import autofix_markdown

    md = """# Kapitel 1

((10))

((10))

Ein **wichtiger** Begriff © mit Lücke: 5 + 3 = ____.
"""
    fixed, applied = autofix_markdown(md)
    assert fixed.count("((10))") == 1
    assert "_wichtiger_" in fixed
    assert "©" not in fixed
    assert "_..._" in fixed
    report = lint_markdown(fixed)
    assert report.score == 100


def test_lint_bild_allows_enumerated_prose_and_nue_or_newline_descriptions():
    """Verify 2b: no false list_delimiter or image_format issues on human FIBS <Bild> blocks."""
    from backend.services.a11y_linter import autofix_markdown

    md = """# Kapitel 1: Mechanik

((10))

<Bild> Grafik:
Beschreibung mit Bildtext:
1. Zustand: Feder entspannt.
2. Zustand: Feder gespannt.
- Pfeil zeigt nach rechts.
</Bild>

<Bild> Foto: n. ü. </Bild>

<Bild> Schema: n. ü. [siehe Text] </Bild>
"""
    report = lint_markdown(md)
    assert report.score == 100
    assert report.issues == []

    fixed, _ = autofix_markdown(md)
    assert "1. Zustand: Feder entspannt." in fixed
    assert "1.\tZustand" not in fixed


def test_lint_and_autofix_fibs_09_2025_notation_and_all_golden_files():
    """Verifies FIBS 09/2025 degree/percent checks, M1/B1/Randspalte headings, and 100/100 on all 20 golden files."""
    from pathlib import Path
    from backend.services.a11y_linter import autofix_markdown

    faulty = (
        "# Kapitel 1\n\n"
        "((10))\n\n"
        "Wasser siedet bei $100\\,^\\circ\\text{C}$ (%engl. boiling point%) mit 50% Dampf.\n"
    )
    rep = lint_markdown(faulty)
    rule_names = {i.rule for i in rep.issues}
    assert "fibs_degree_latex" in rule_names
    assert "fibs_unannounced_percent_emphasis" in rule_names

    fixed, fixes = autofix_markdown(faulty)
    assert len(fixes) >= 2
    assert "100 °C" in fixed
    assert "(_engl. boiling point_)" in fixed
    assert "50 % Dampf" in fixed
    assert lint_markdown(fixed).score == 100

    # Announced %...% via <Anmerkung> must score 100/100
    announced = (
        "# Kapitel 1\n\n"
        "((10))\n\n"
        "<Anmerkung>\nIn diesem Text bedeutet %Wort% kursive Schrift.\n</Anmerkung>\n\n"
        "Ein %kursiv% gesetztes Wort.\n"
    )
    assert lint_markdown(announced).score == 100

    golden_dir = Path(__file__).resolve().parents[2] / "testdata" / "golden"
    golden_files = sorted(golden_dir.glob("*.uebertragungsregeln_09_2025.golden.md"))
    assert len(golden_files) >= 20
    for gpath in golden_files:
        txt = gpath.read_text(encoding="utf-8")
        assert "$" not in txt, f"Unexpected $-delimiter in {gpath.name}"
        g_rep = lint_markdown(txt)
        assert g_rep.score == 100, f"Lint < 100 in {gpath.name}: {g_rep.issues}"


def test_lint_plural_rubric_headings_and_buchkonferenz_custom_rules():
    """Verifies 14a: plural FIBS rubric headings and explicit Buchkonferenz custom_rules levels."""
    from backend.services.feedback_service import compare_lint_reports
    from scripts.run_benchmark import evaluate_a11y

    md_plural = (
        "((1))\n\n"
        "# Mechanik und Energie\n\n"
        "## 1.1 Erhaltungssätze\n\n"
        "### Impulserhaltung\n\n"
        "Impuls bleibt im abgeschlossenen System erhalten.\n\n"
        "##### Aufgaben\n\n"
        "##### 1\n\n"
        "Berechnen Sie den Gesamtimpuls nach dem Stoß.\n\n"
        "#### M Steckbrief\n\n"
        "<Rahmen>\n_Isaac Newton (1643-1727)_\nBegründer der klassischen Mechanik.\n</Rahmen>\n\n"
        "##### Zusatztraining\n\n"
        "Bestimmen Sie die Geschwindigkeit.\n"
    )
    # Without custom_rules, '##### Aufgaben' passes via plural _SEMANTIC_HEADING_RE,
    # whereas custom '##### Zusatztraining' (jumping from H4/H3) would only pass when declared in custom_rules
    rules = (
        "##### Überschrift 5:\n"
        "- das Wort 'Aufgaben:' und jeweils die Aufgabennummer als Ü.\n"
        "Zusatztraining in Ü5\n"
    )
    rep_with_rules = lint_markdown(md_plural, custom_rules=rules)
    assert rep_with_rules.score == 100
    assert rep_with_rules.issues == []

    a11y_dict = evaluate_a11y(md_plural, expected_pages=1, custom_rules=rules)
    assert a11y_dict["score"] == 100

    cmp = compare_lint_reports(md_plural, md_plural, custom_rules=rules)
    assert cmp["score_original"] == 100
    assert cmp["score_revised"] == 100

    # Genuine accidental hierarchy jump (H1 -> H3 normal chapter heading) must still trigger warning!
    bad_jump = "((1))\n\n# Kapitel 1\n\n### 1.1 Übersprungene Ebene\n"
    rep_bad = lint_markdown(bad_jump, custom_rules=rules)
    assert any(i.rule == "heading_hierarchy" for i in rep_bad.issues)


def test_lint_u5_aufgabennummern_exempts_bare_decimal_and_prefixed_task_numbers():
    """Verifies 18a: ##### 1, ##### 1.1, and ##### A1 are exempted when Ü5 specifies Aufgabennummern."""
    md_u5_nums = (
        "((12))\n\n"
        "# 1 Grundlagen der Mechanik\n\n"
        "## 1.2 Kräfte im Gleichgewicht\n\n"
        "Ein Körper bleibt in Ruhe, wenn sich alle wirkenden Kräfte aufheben.\n\n"
        "##### 1\n"
        "[einfach]\n\n"
        "Nennen Sie zwei Beispiele für Kräftegleichgewicht.\n\n"
        "##### 1.1\n"
        "[mittel]\n\n"
        "Zeichnen Sie ein Kräfteparallelogramm.\n\n"
        "### Material mit Aufgaben\n\n"
        "##### A1\n"
        "[schwierig]\n\n"
        "Berechnen Sie die resultierende Ersatzkraft.\n"
    )
    for rules_variant in (
        "##### Überschrift 5: Aufgabennummern\n",
        "Ü5: Aufgabennummern\n",
        "Aufgabennummern als Ü5\n",
    ):
        rep = lint_markdown(md_u5_nums, custom_rules=rules_variant)
        assert not any(i.rule == "heading_hierarchy" for i in rep.issues)
        assert rep.score == 100


def test_lint_u4_text_subheadings_and_double_page_photo_opener():
    """Verifies 19e: H1/H2 -> H4 exemption under Buchkonferenz Ü4 text subheadings and spread/raw page counting."""
    bk_rules = (
        "# Überschrift 1: Hauptkapitel\n"
        "## Überschrift 2: Teilkapitel\n"
        "### Überschrift 3: Methode, Basiskonzept, Exkurs\n"
        "#### Überschrift 4: schwarze Textüberschriften, kapitelinterne Überschriften\n"
        "##### Überschrift 5: Aufgabennummern\n\n"
        "## Bilder\n"
        "- Den Abbildungen ein M voranstellen (z. B. M1 + Bildtitel)\n"
    )
    md_spread = (
        "((170)) / ((171))\n\n"
        "# 3 Stofftransport und Energieumsatz\n\n"
        "#### Überblick zum Kapitelauftakt\n\n"
        "Zellen tauschen fortlaufend Stoffe und Energie mit ihrer Umgebung aus.\n\n"
        "((172))\n\n"
        "## 3.1 Diffusion durch Grenzschichten\n\n"
        "#### Konzentrationsausgleich im Modellversuch\n\n"
        "Teilchen bewegen sich aufgrund ihrer thermischen Eigenbewegung entlang des Gradienten.\n\n"
        "#### M1 Konzentrationsverlauf über die Zeit\n\n"
        "<Bild> Diagramm:\n"
        "Beschreibung mit Bildtext: Zeitachse t in s \\to Konzentration c in mol/L.\n"
        "</Bild>\n"
    )
    rep_spread = lint_markdown(md_spread, expected_pages=3, custom_rules=bk_rules)
    assert rep_spread.issues == []
    assert rep_spread.score == 100

    # When page 171 in a 3-page selection (170-172) is a textless full-bleed photo in raw_markdown (only 2 non-empty raw pages),
    # standardized output with 2 marked pages must NOT be penalized for matching raw_markdown's page count.
    raw_photo_opener = (
        "((170))\n\n"
        "# 3 Stofftransport und Energieumsatz\n\n"
        "((171))\n\n"
        "((172))\n\n"
        "## 3.1 Diffusion durch Grenzschichten\n\n"
        "Teilchen bewegen sich entlang des Gradienten.\n"
    )
    std_photo_opener = (
        "((170))\n\n"
        "# 3 Stofftransport und Energieumsatz\n\n"
        "((172))\n\n"
        "## 3.1 Diffusion durch Grenzschichten\n\n"
        "Teilchen bewegen sich entlang des Gradienten.\n"
    )
    rep_raw_match = lint_markdown(
        std_photo_opener,
        raw_markdown=raw_photo_opener,
        expected_pages=3,
        custom_rules=bk_rules,
    )
    assert not any(i.rule == "page_number_missing" for i in rep_raw_match.issues)
    assert rep_raw_match.score == 100


def test_lint_minimized_fibs_fractions_and_roots_never_trigger_footnote_warnings():
    """Verifies that \\f{1}{3}, \\f{1}{10}, \\s{3}, and \\s[3]{27} never trigger footnote_missing_definition."""
    md = (
        "((10))\n\n"
        "# 1 Bruchrechnung und Wurzeln\n\n"
        "Es gilt \\f{1}{3} + \\f{1}{10} = \\f{13}{30}, geschachtelt \\f{\\f{1}{2}}{3} = \\f{1}{6} "
        "sowie \\s{3}, \\s[3]{27} = 3 und 2,3\\ol{45}.\n"
    )
    rep = lint_markdown(md)
    assert rep.issues == []
    assert rep.score == 100


def test_all_stage2_golden_files_score_100_in_lint_markdown():
    """Verifies that every *.uebertragungsregeln_09_2025.golden.md in testdata/golden/ scores 100/100."""
    from pathlib import Path

    golden_dir = Path(__file__).resolve().parents[2] / "testdata" / "golden"
    golden_files = sorted(golden_dir.glob("*.uebertragungsregeln_09_2025.golden.md"))
    assert len(golden_files) >= 19
    for g_path in golden_files:
        rep = lint_markdown(g_path.read_text(encoding="utf-8"))
        assert rep.score == 100, f"{g_path.name} scored {rep.score}: {rep.issues}"





