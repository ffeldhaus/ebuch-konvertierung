"""Synthetic unit tests for Endkontrolle math, unit, number, coordinate, and prompt fixes."""

from __future__ import annotations

import pytest

from backend.services.fibs_constants import EUROBRAILLE_CHAR_FALLBACK_MAP
from backend.services.fibs_formatting import normalize_fibs_units_and_percent
from backend.services.formula_service import standardize_formulas
from backend.services.prompts import SYSTEM_PROMPTS, VLM_PROMPT_RULES, build_custom_rules_block


def test_fix5_micromol_unit_normalization_and_prompts() -> None:
    """Verifies Fix #5: ~mol / µmol / μmol normalize to ~mmol and prompts list micro units."""
    raw = (
        "Stoffmenge: 5 ~mol, 12,5~mol/L, 3 µmol, 4µmol/min, 2 μmol und bereits korrekt 7 ~mmol.\n"
        "Unverändert: 10 mol, ~molar, `5 ~mol`, https://example.org/~mol/test."
    )
    out = normalize_fibs_units_and_percent(raw)
    assert "5 ~mmol," in out
    assert "12,5 ~mmol/L," in out
    assert "3 ~mmol," in out
    assert "4 ~mmol/min," in out
    assert "2 ~mmol und bereits korrekt 7 ~mmol." in out
    assert "10 mol," in out
    assert "~molar," in out
    assert "`5 ~mol`" in out
    assert "https://example.org/~mol/test" in out
    assert normalize_fibs_units_and_percent(out) == out

    sys_prompt = SYSTEM_PROMPTS["uebertragungsregeln_09_2025"]
    for prompt_text in (sys_prompt, VLM_PROMPT_RULES):
        for expected in ("µmol -> ~mmol", "µm -> ~mm", "µg -> ~mg", "µl -> ~ml", "µs -> ~ms"):
            assert expected in prompt_text


def test_fix6a_bare_tilde_proportionality_without_false_positives() -> None:
    r"""Verifies Fix #6a: bare tilde proportionality becomes \sim while guarding ~a and ~ 10."""
    raw = (
        "Proportionalitäten: ~a ~ M, ~a ~ F, a ~ F, s ~ t^2, F ~ \\f{1}{r^2}, ~D~w ~ ~Dt, T ~ \\s{l}.\n"
        "Keine Proportionalität: Winkel ~a, Näherung t ~ 10 s, etwa ~ 10 m, a ~ etwa 5, x ~ ca. 3."
    )
    out = standardize_formulas(raw, fibs_mode=True)
    assert r"~a \sim M," in out
    assert r"~a \sim F," in out
    assert r"a \sim F," in out
    assert r"s \sim t^2," in out
    assert r"F \sim \f{1}{r^2}," in out
    assert r"~D~w \sim ~Dt," in out
    assert r"T \sim \s{l}." in out
    assert "Winkel ~a," in out
    assert "t ~ 10 s," in out
    assert "etwa ~ 10 m," in out
    assert "a ~ etwa 5," in out
    assert "x ~ ca. 3." in out
    assert standardize_formulas(out, fibs_mode=True) == out


def test_fix6b_stray_spaces_before_math_punctuation_preserve_division_and_ellipsis() -> None:
    """Verifies Fix #6b: stray spaces before punctuation after math are removed safely."""
    raw = (
        "Die Energie E , die am Weg \\vec{s} :\n"
        "Für die Höhe h , so ergibt sich zur Zeit ~Dt : Die Bewegung endet mit M =rF .\n"
        "Außerdem Kraft F_G ; Winkel \\angle(g,h) , Quotient \\f{M}{~a} . Zeit ~Dt :\n"
        "Division 12 :4 und Verhältnis 1 : 2 sowie a : b bleiben; Auslassung aabb ... auch."
    )
    out = standardize_formulas(raw, fibs_mode=True)
    assert "Die Energie E, die am Weg \\vec{s}:" in out
    assert "Für die Höhe h, so ergibt sich zur Zeit ~Dt: Die Bewegung endet mit M =rF." in out
    assert "Kraft F_G; Winkel \\angle(g,h), Quotient \\f{M}{~a}. Zeit ~Dt:" in out
    assert "Division 12 :4" in out
    assert "Verhältnis 1 : 2" in out
    assert "sowie a : b bleiben;" in out
    assert "Auslassung aabb ... auch." in out


def test_fix6c_marburger_delta_and_implicit_product_tightening() -> None:
    r"""Verifies Fix #6c: tight ~D and implicit products while preserving alphabetic command spacing."""
    raw = (
        "Änderungen: ~D (pr), ~D \\vec{s_i}, \\f{r ~Dp}{~Dt}, L =J ~w, M =J ~a, ~D s = d * sin(~a).\n"
        "Befehle & Einheiten behalten Abstand: ~a \\sim M, x \\neq 0, cos ~a, x \\to \\8, "
        "~D (Delta), ~D ist groß, 10 ~mg, 2 ~mm, 5 ~mmol, r_i ~w."
    )
    out = standardize_formulas(raw, fibs_mode=True)
    assert "~D(pr)," in out
    assert r"~D\vec{s_i}," in out
    assert r"\f{r~Dp}{~Dt}," in out
    assert "L =J~w," in out
    assert "M =J~a," in out
    assert "~Ds =d *sin(~a)." in out
    assert r"~a \sim M," in out
    assert r"x \neq 0," in out
    assert "cos ~a," in out
    assert r"x \to \8," in out
    assert "~D (Delta)," in out
    assert "~D ist groß," in out
    assert "10 ~mg, 2 ~mm, 5 ~mmol, r_i ~w." in out


def test_fix6d_algebraic_fractions_not_flattened_and_spaced_bare_fractions_converted() -> None:
    r"""Verifies Fix #6d: \f{...}{...} stays intact, spaced bare var fractions become \f, units keep /."""
    raw = (
        "Brüche: \\f{M}{~a}, \\f{~Dp}{~Dt}, \\f{~DL}{~Dt}, \\f{F}{a}.\n"
        "Spaced bare: F =~Dp / ~Dt und M = ~DL / ~Dt sowie J = M / ~a und a = F / m.\n"
        "Einheiten & Zahlenbrüche: 9,81 m/s^2, 3 kg m^2/s, 1/2, Gruppe A / B, ((20)) / ((21))."
    )
    out = standardize_formulas(raw, fibs_mode=True)
    assert r"\f{M}{~a}, \f{~Dp}{~Dt}, \f{~DL}{~Dt}, \f{F}{a}." in out
    assert r"F =\f{~Dp}{~Dt} und M =\f{~DL}{~Dt} sowie J =\f{M}{~a} und a =\f{F}{m}." in out
    assert "9,81 m/s^2, 3 kg m^2/s, 1/2, Gruppe A / B, ((20)) / ((21))." in out

    sys_prompt = SYSTEM_PROMPTS["uebertragungsregeln_09_2025"]
    assert r"\f{M}{~a}" in sys_prompt
    assert r"\f{~Dp}{~Dt}" in sys_prompt
    assert "m/s^2" in sys_prompt


def test_fix6e_sqrt_multitoken_and_angle_preservation() -> None:
    r"""Verifies Fix #6e: \sqrt{2as} -> \s{2as} without splitting and \angle(g,h) is preserved."""
    raw = (
        "Wurzeln: $\\sqrt{2as}$, $\\sqrt{2 a s}$, $\\sqrt{\\frac{2s}{a}}$, $\\sqrt[3]{27x}$, "
        "\\sqrt(2as), \\sqrt 2as, √(2as).\n"
        "Winkel vs. Skalarprodukt: $\\alpha = \\angle(g,h)$, ∠(g,h), ∠ABC, $\\langle u, v \\rangle$."
    )
    out = standardize_formulas(raw, fibs_mode=True)
    assert r"\s{2as}, \s{2 a s}, \s{\f{2s}{a}}, \s[3]{27x}, \s{2as}, \s{2as}, \s{2as}." in out
    assert r"\s{2a} s" not in out
    assert r"~a =\angle(g,h), \angle(g,h), \angle ABC, \l< u, v \r>." in out
    assert r"\l<(g,h)\r>" not in out


def test_fix10_biology_latin_species_names_rule_in_prompts() -> None:
    """Verifies Fix #10: prompts explicitly exclude Latin biological species binomials from _..._."""
    sys_prompt = SYSTEM_PROMPTS["uebertragungsregeln_09_2025"]
    assert "Homo sapiens" in sys_prompt
    assert "Zea mays" in sys_prompt
    assert "Papaver somniferum" in sys_prompt
    assert "NICHT mit Unterstrichen" in sys_prompt

    custom_block = build_custom_rules_block("Kursive Wörter als _Wort_.")
    assert "Homo sapiens" in custom_block


@pytest.mark.parametrize(
    "src, expected",
    [
        ("Licht legt 300 000 km pro Sekunde zurück.", "Licht legt 300.000 km pro Sekunde zurück."),
        ("Abstand 30 000 m, Wert 5 143 und 1 400.", "Abstand 30.000 m, Wert 5.143 und 1.400."),
        ("Große Zahlen: 10000 und 1000000 sowie 200000.", "Große Zahlen: 10.000 und 1.000.000 sowie 200.000."),
        ("Messwerte: 5143 sowie 1400 cm^3 und 1500 Euro.", "Messwerte: 5.143 sowie 1.400 cm^3 und 1.500 Euro."),
        ("Vor 1400 Jahren lebten 1800 Einwohner dort.", "Vor 1.400 Jahren lebten 1.800 Einwohner dort."),
        # Protected years, dates, ranges, PLZ, ISBN, page markers, codes, decimals, axis ticks
        ("Datum: 1.1.2026, August 2026, im Jahr 1974, seit 1990.", "Datum: 1.1.2026, August 2026, im Jahr 1974, seit 1990."),
        ("Lebensdaten: 1816-1893 und (1816-1893) sowie 2500 v. Chr.", "Lebensdaten: 1816-1893 und (1816-1893) sowie 2500 v. Chr."),
        ("Epochen: circa 2500 BCE, 2600–1900 BCE, 2600-1900 v. Chr., 2400 BC und 1200 AD.", "Epochen: circa 2500 BCE, 2600–1900 BCE, 2600-1900 v. Chr., 2400 BC und 1200 AD."),
        ("Codes: _Mediencode 74108-18:_ mithilfe des Mediencodes 74108-18, Webcode 54321-07, Code 88120.", "Codes: _Mediencode 74108-18:_ mithilfe des Mediencodes 74108-18, Webcode 54321-07, Code 88120."),
        ("Jahresreihe: 1990 2000 2010 2020 2030* 2040* 2050*.", "Jahresreihe: 1990 2000 2010 2020 2030* 2040* 2050*."),
        ("Adresse: Musterstraße 5, 50667 Köln, PLZ 10115, D-80331, 01067 Dresden.", "Adresse: Musterstraße 5, 50667 Köln, PLZ 10115, D-80331, 01067 Dresden."),
        ("Verweise: ((1234)), S. 2500, Seite 5143, § 2100, Nr. 5143, ISBN 978-3-12-772410-3, Buchnummer 5143.", "Verweise: ((1234)), S. 2500, Seite 5143, § 2100, Nr. 5143, ISBN 978-3-12-772410-3, Buchnummer 5143."),
        ("Dezimal & Skala: 0,49051 und 2.9979 und Achse 100 200 300.", "Dezimal & Skala: 0,49051 und 2.9979 und Achse 100 200 300."),
        ("Platzhalter: <Bild-Ref id=\"BILD_2500\" /> und ![](images/page_12345.png).", "Platzhalter: <Bild-Ref id=\"BILD_2500\" /> und ![](images/page_12345.png)."),
    ],
)
def test_fix11_thousands_separator_dots_and_exclusions(src: str, expected: str) -> None:
    """Verifies Fix #11: thousands separator dots with strict exclusions and idempotence."""
    out = normalize_fibs_units_and_percent(src)
    assert out == expected
    assert normalize_fibs_units_and_percent(out) == expected


def test_fix11_thousands_rules_in_prompts() -> None:
    """Verifies Fix #11 rules are documented in both VLM and standardisation prompts."""
    for prompt_text in (SYSTEM_PROMPTS["uebertragungsregeln_09_2025"], VLM_PROMPT_RULES):
        assert "5.143" in prompt_text
        assert "200.000" in prompt_text
        assert "1.1.2026" in prompt_text


def test_fix12_coordinates_pipe_notation_and_guards() -> None:
    """Verifies Fix #12: 2D/3D coordinates use (x|y) without spaces, sparing intervals/sets/prose."""
    raw = (
        "Punkte: (0; 50), (-1,5; 2,5), P(2; -5), A(-3 | 4), Q(1; 2; 3), S(x_0; y_0), (x; y).\n"
        "Unverändert: Intervall [0; 1], Menge {1; 2}, Index x_{1; 2}, Hinweis (vgl. S. 3; 4), ((12))."
    )
    out = normalize_fibs_units_and_percent(raw)
    assert "(0|50), (-1,5|2,5), P(2|-5), A(-3|4), Q(1|2|3), S(x_0|y_0), (x|y)." in out
    assert "Intervall [0; 1], Menge {1; 2}, Index x_{1; 2}, Hinweis (vgl. S. 3; 4), ((12))." in out
    assert normalize_fibs_units_and_percent(out) == out

    for prompt_text in (SYSTEM_PROMPTS["uebertragungsregeln_09_2025"], VLM_PROMPT_RULES):
        assert "(4|7)" in prompt_text
        assert "A(-3|4)" in prompt_text


def test_fix13_promille_constant_and_prose_word_distinction() -> None:
    r"""Verifies Fix #13: EUROBRAILLE map maps ‰ -> \permil and prompts keep prose 'Promille'."""
    assert EUROBRAILLE_CHAR_FALLBACK_MAP["‰"] == r"\permil"

    raw = "Grenzwert 0,5 ‰ bzw. 5‰, im Satz aber ein Promille oder zwei Promille."
    out = normalize_fibs_units_and_percent(raw)
    assert r"0,5 \permil bzw. 5 \permil" in out
    assert "ein Promille oder zwei Promille." in out

    for prompt_text in (SYSTEM_PROMPTS["uebertragungsregeln_09_2025"], VLM_PROMPT_RULES):
        assert r"0,5 \permil" in prompt_text
        assert "ein Promille" in prompt_text


def test_fix16a_no_bild_ref_id_leakage_trigger_in_prompts() -> None:
    """Verifies Fix #16a: prompts remove the bare '#### M<Nr>' fallback trigger and warn against ID leaks."""
    sys_prompt = SYSTEM_PROMPTS["uebertragungsregeln_09_2025"]
    assert "oder schreibe nur '#### M<Nr>' allein" not in sys_prompt
    assert "hat NICHTS mit gedruckten Bildnummern" in sys_prompt
    assert "BILD_026" in sys_prompt
    assert "M026" in sys_prompt
    assert "ohne eine erfundene leere '#### M...'-Überschrift" in sys_prompt
