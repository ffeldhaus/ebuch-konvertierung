from backend.services.formula_service import standardize_formulas, strip_l_tags


def test_standardize_raw_dollar_delimiters():
    # Formulas are cleaned and kept as standard LaTeX without <L>
    raw = "Hier ist eine Formel: $a^2 + b^2 = c^2$ und noch eine:\n$$\\frac{1}{2} \\cdot g \\cdot t^2$$"
    standardised = standardize_formulas(raw)
    assert "$a^2 + b^2 = c^2$" in standardised
    assert "$$\\frac{1}{2} \\cdot g \\cdot t^2$$" in standardised
    assert "<L>" not in standardised


def test_strip_l_tags():
    raw = r"<L> c = 299.792 \, \text{km/s} </L> und <L> n </L>"
    stripped = strip_l_tags(raw)
    assert "<L>" not in stripped and "</L>" not in stripped
    assert "c = 299.792" in stripped


def test_standardize_fractions_and_roots():
    raw = r"<L>\dfrac{a + b}{c - d}</L> und <L>\sqrt[3]{x^3 + y^3}</L>"
    standardised = standardize_formulas(raw)
    assert "<L>" not in standardised and "</L>" not in standardised
    # \dfrac should be normalized to \frac
    assert "\\frac{a + b}{c - d}" in standardised
    assert "\\sqrt[3]{x^3 + y^3}" in standardised


def test_standardize_chemistry():
    raw = r"Bei der Verbrennung: $2 \text{H}_2 + \text{O}_2 \rightarrow 2 \text{H}_2\text{O}$ entsteht Wasser."
    standardised = standardize_formulas(raw)
    assert "<L>" not in standardised
    assert "2 \\text{H}_2 + \\text{O}_2 \\rightarrow 2 \\text{H}_2\\text{O}" in standardised


def test_standardize_aligned_environments():
    raw = """<L>\\begin{aligned}
2x + 3y &= 7 \\\\
4x - y &= 5
\\end{aligned}</L>"""
    standardised = standardize_formulas(raw)
    assert "<L>" not in standardised
    assert "\\begin{aligned}" not in standardised
    assert "\\end{aligned}" not in standardised
    assert "2x + 3y = 7" in standardised
    assert "4x - y = 5" in standardised


def test_generic_si_units_and_multiletter_subscripts():
    raw = (
        "Die Phasengeschwindigkeit beträgt $v = 1.450$ m/s bzw. $2.9979 \\times 10^8$ m/s.\n"
        "Der Index $n_{Wasser}$ und die Energie $E_{Photon} = h \\cdot f$ werden bestimmt."
    )
    res = standardize_formulas(raw)
    assert "$v = 1.450 \\, \\text{m/s}$" in res
    assert "$2.9979 \\times 10^8 \\, \\text{m/s}$" in res
    assert "$n_{\\text{Wasser}}$" in res
    assert "$E_{\\text{Photon}} = h \\cdot f$" in res


def test_generic_unicode_equations_and_limits():
    from backend.services.formula_service import convert_pdf_formula_bbox_text_to_latex

    raw = (
        "Für das Grenzverhalten gilt lim_{x -> ∞} f(x) = +∞.\n"
        "Am Gitter gilt Δs = d · sin(α) sowie F = m · a und E = h · f."
    )
    res = standardize_formulas(raw)
    assert "\\Delta s = d \\cdot \\sin(\\alpha)" in res
    assert "$F = m \\cdot a$" in res
    assert "$E = h \\cdot f$" in res

    # Verify generic integral + square-root parsing on unseen variable names and constants
    bbox_int = convert_pdf_formula_bbox_text_to_latex("∞∫-∞ e -t 2 dt = √(2π + t 2 + 5) (3.4)")
    assert bbox_int == "$$\\int_{-\\infty}^{\\infty} e^{-t^2} \\, dt = \\sqrt{2\\pi + t^2 + 5}$$ (3.4)"


def test_no_hardcoded_test_document_phrases_in_formula_service():
    import inspect
    import backend.services.formula_service as fs

    src = inspect.getsource(fs)
    forbidden_phrases = [
        "MathML-Render-Beispiel",
        "komplexe Blockgleichung",
        "Eine gleichwertige Form ist",
        "Es lautet:",
        "Lichtgeschwindigkeit",
        "Wellenlänge",
        "299.792",
        "2.9979",
        "n_Glas",
        "nGlas",
        "\\pi + x^2 - 1",
        "Formel: $U =",
    ]
    for phrase in forbidden_phrases:
        assert phrase not in src, f"Hardcoded test-data leak '{phrase}' found in formula_service.py"


def test_coalesce_split_equations_reactions_and_html_entities():
    raw = (
        "Schwellenwerte (d &lt; 15 cm, d &lt; 25 cm) und ($d_{\\text{rechts}}$ &gt; $d_{\\text{links}}$).\n"
        "Geradeaus fahren (v = 50 %) und 90° drehen bei (80 °C).\n"
        "Gleichgewicht ($v_{\\text{hin}}$ = v_rück) mit Kc ≈ 4,0.\n"
        "- Energiebilanz: E_kin,max = h · f - W_A = e · U_G.\n"
        "- Verstärkung: Δs = d · sin(α_k) = k · λ.\n"
        "- Auslöschung: Δs = d · sin(α_k) = (k + ½) · λ.\n"
        "- Grenzfrequenz: f_G = W_A / h und Impuls: p = E / c = h / λ.\n"
        "- Empirische Formel: C0.142H0.284 ergibt CH2.\n"
    )
    res = standardize_formulas(raw)
    assert "$d < 15\\,\\text{cm}$" in res
    assert "$d_{\\text{rechts}} > d_{\\text{links}}$" in res
    assert "$v = 50\\,\\%$" in res
    assert "$90^\\circ$" in res
    assert "$80\\,^\\circ\\text{C}$" in res
    assert "$v_{\\text{hin}} = v_{\\text{rück}}$" in res
    assert "$K_c \\approx 4{,}0$" in res
    assert "$E_{\\text{kin,max}} = h \\cdot f - W_A = e \\cdot U_G$" in res
    assert "$\\Delta s = d \\cdot \\sin(\\alpha_k) = k \\cdot \\lambda$" in res
    assert "$\\Delta s = d \\cdot \\sin(\\alpha_k) = (k + \\frac{1}{2}) \\cdot \\lambda$" in res
    assert "$f_G = \\frac{W_A}{h}$" in res
    assert "$p = \\frac{E}{c} = \\frac{h}{\\lambda}$" in res
    assert "$C_{0.142}H_{0.284}$" in res



