import pytest
from backend.services.a11y_linter import lint_markdown

def test_lint_perfect_ebuch():
    md = """# Kapitel 1: Optik

((45))

Das Licht breitet sich geradlinig aus. Hierzu ein Experiment:

-\\tErster Schritt: Aufbau
-\\tZweiter Schritt: Messung

<Bild> Zeichnung:
Beschreibung: Ein Prisma bricht weiſses Licht in Spektralfarben.
</Bild>

Formel der Brechung: $n_1 \\cdot \\sin(\\alpha) = n_2 \\cdot \\sin(\\beta)$

Hier ist ein wichtiger Begriff{1}.

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
