"""Unit tests for mathematical and chemical formula standardisation."""

from backend.services.formula_service import standardize_formulas, strip_l_tags


def test_standardize_raw_dollar_delimiters():
    """Verifies that inline and display dollar delimiters are preserved without <L> tags."""
    raw = "Hier ist eine Formel: $a^2 + b^2 = c^2$ und noch eine:\n$$\\frac{1}{2} \\cdot g \\cdot t^2$$"
    standardised = standardize_formulas(raw)
    assert "$a^2 + b^2 = c^2$" in standardised
    assert "$$\\frac{1}{2} \\cdot g \\cdot t^2$$" in standardised
    assert "<L>" not in standardised


def test_strip_l_tags():
    """Verifies stripping of legacy <L> tags."""
    raw = r"<L> c = 299.792 \, \text{km/s} </L> und <L> n </L>"
    stripped = strip_l_tags(raw)
    assert "<L>" not in stripped and "</L>" not in stripped
    assert "c = 299.792" in stripped


def test_standardize_fractions_and_roots():
    r"""Verifies normalization of \dfrac to \frac and preservation of roots."""
    raw = r"<L>\dfrac{a + b}{c - d}</L> und <L>\sqrt[3]{x^3 + y^3}</L>"
    standardised = standardize_formulas(raw)
    assert "<L>" not in standardised and "</L>" not in standardised
    # \dfrac should be normalized to \frac
    assert "\\frac{a + b}{c - d}" in standardised
    assert "\\sqrt[3]{x^3 + y^3}" in standardised


def test_standardize_chemistry():
    """Verifies preservation of chemical reaction equations inside LaTeX math."""
    raw = r"Bei der Verbrennung: $2 \text{H}_2 + \text{O}_2 \rightarrow 2 \text{H}_2\text{O}$ entsteht Wasser."
    standardised = standardize_formulas(raw)
    assert "<L>" not in standardised
    assert "2 \\text{H}_2 + \\text{O}_2 \\rightarrow 2 \\text{H}_2\\text{O}" in standardised


def test_standardize_aligned_environments():
    """Verifies stripping of aligned environments into flat equation lines."""
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
    r"""Verifies SI unit wrapping and multi-letter subscript \text{...} conversion."""
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
    """Verifies Unicode math equation and integral conversion to LaTeX."""
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
    """Verifies that formula_service.py contains no hardcoded test-document phrases."""
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
    """Verifies coalescing of split math fragments, HTML entities, and empirical formulas."""
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
    assert "90°" in res
    assert "80 °C" in res
    assert "^\\circ" not in res
    assert "$v_{\\text{hin}} = v_{\\text{rück}}$" in res
    assert "$K_c \\approx 4{,}0$" in res
    assert "$E_{\\text{kin,max}} = h \\cdot f - W_A = e \\cdot U_G$" in res
    assert "$\\Delta s = d \\cdot \\sin(\\alpha_k) = k \\cdot \\lambda$" in res
    assert "$\\Delta s = d \\cdot \\sin(\\alpha_k) = (k + \\frac{1}{2}) \\cdot \\lambda$" in res
    assert "$f_G = \\frac{W_A}{h}$" in res
    assert "$p = \\frac{E}{c} = \\frac{h}{\\lambda}$" in res
    assert "$C_{0.142}H_{0.284}$" in res


def test_strip_hallucinated_ocr_pseudo_formulas():
    """Verifies 5a: hallucinated OCR pseudo-formulas with invalid uppercase/subscript mixes are stripped."""
    raw = "Im Diagramm steht $CCN_1C_2C$ sowie $XYZ_1A_2$ neben der Formel $H_2SO_4$ und $CH_3COOH$."
    res = standardize_formulas(raw)
    assert "CCN_1C_2C" not in res
    assert "XYZ_1A_2" not in res
    assert "$H_2SO_4$" in res
    assert "$CH_3COOH$" in res


def test_plain_degrees_temperatures_and_percentages_both_modes():
    """Verifies 3b: temperatures, angles, and percentages never emit ^\\circ and follow FIBS spacing."""
    raw = (
        "Siedepunkt bei $80\\,^\\circ\\text{C}$, Stickstoff bei -196°C und Papier bei 451°F.\n"
        "Drehung um etwa 45 ° um die Achse in die $90^\\circ$-Stellung bei 0 ° N und $14{,}1^\\circ$.\n"
        "Anteil 50%, Lösung $50\\,\\%$, aber 5%-Klausel und 100%ig bleiben zusammen."
    )
    for mode in (False, True):
        res = standardize_formulas(raw, fibs_mode=mode)
        assert "^\\circ" not in res
        assert "80 °C" in res
        assert "-196 °C" in res
        assert "451 °F" in res
        assert "etwa 45° um" in res
        assert "90°-Stellung" in res
        assert "0° N" in res
        assert "14,1°" in res
        assert "Anteil 50 %," in res
        assert "Lösung 50 %," in res
        assert "5%-Klausel" in res
        assert "100%ig" in res


def test_fibs_mode_bare_latex_tilde_greek_micro_and_arrows():
    """Verifies 3a & 7a: fibs_mode=True emits bare Augenbit-LaTeX without $...$, tilde Greek, and FIBS arrows."""
    raw = (
        "Dosis: 0,001 $\\mu$g bzw. 0,001µg und Spaltbreite 2 $\\mu$m bzw. 2µm sowie $1{,}67\\,\\mu\\text{m}$.\n"
        "Beugung: $\\Delta s = d \\cdot \\sin(\\alpha_1) = k \\cdot \\lambda$ und $\\gamma + \\beta = \\delta$.\n"
        "$$\\text{CH}_3\\text{COOH} + \\text{C}_2\\text{H}_5\\text{OH} \\rightleftharpoons \\text{CH}_3\\text{COOC}_2\\text{H}_5 + \\text{H}_2\\text{O}$$\n"
        "$$2\\,\\text{SO}_2\\text{(g)} + \\text{O}_2\\text{(g)} \\xrightarrow{\\text{Kat., } 450\\,^\\circ\\text{C}} 2\\,\\text{SO}_3\\text{(g)}$$\n"
        "Signalweg: $A \\xrightarrow{\\text{ATP} \\rightarrow \\text{ADP}} B \\longrightarrow C$."
    )
    res = standardize_formulas(raw, fibs_mode=True)
    assert "$" not in res
    assert "\\text{" not in res
    assert "{,}" not in res
    assert "\\," not in res
    assert "0,001 ~mg bzw. 0,001 ~mg" in res
    assert "2 ~mm bzw. 2 ~mm sowie 1,67 ~mm" in res
    assert "~D s = d * sin(~a_1) = k * ~l" in res
    assert "~g + ~b = ~d" in res
    assert "CH_3COOH + C_2H_5OH \\lra CH_3COOC_2H_5 + H_2O" in res
    assert "2 SO_2(g) + O_2(g) \\xra{Kat., 450 °C} 2 SO_3(g)" in res
    assert "A \\xra{ATP \\to ADP} B \\to C" in res


def test_tilde_greek_spelled_out_words_normalized_to_fibs_single_letter():
    """Verifies 14d: half-converted '~alpha', '~beta', '~Omega', '~eta', '~theta', '~Theta' map to official FIBS tokens."""
    sample = (
        "Messung an ~alpha-Strahlung, ~beta-Teilchen, ~gamma-Quanten, ~Delta-Werten, "
        "~eta-Wirkungsgrad, ~theta-Winkel, ~vartheta-Skala, ~Theta-Tensor, ~varphi-Phase, ~varepsilon-Wert, "
        "~mu-Mesonen und ~Omega-Widerstand (nicht ~betrachten oder `~beta` oder https://example.org/~alpha/doc)."
    )
    out = standardize_formulas(sample, fibs_mode=True)
    assert "~a-Strahlung" in out
    assert "~b-Teilchen" in out
    assert "~g-Quanten" in out
    assert "~D-Werten" in out
    assert "~j-Wirkungsgrad" in out
    assert "~h-Winkel" in out
    assert "~h-Skala" in out
    assert "~H-Tensor" in out
    assert "~f-Phase" in out
    assert "~e-Wert" in out
    assert "~m-Mesonen" in out
    assert "~W-Widerstand" in out
    assert "~betrachten" in out
    assert "`~beta`" in out
    assert "https://example.org/~alpha/doc" in out


def test_fibs_minimiertes_latex_commands_vectors_indices_and_bruchschreibweisen():
    """Verifies official FIBS Handreichung minimized commands, Greek eta/theta, vectors, and fraction rules."""
    sample = (
        "Brüche & Wurzeln: $\\frac{\\frac{m_1}{m_2}}{1 + \\dfrac{a}{b}}$, $\\tfrac{3}{8}$, $\\sqrt{x}$, $\\sqrt[3]{27}$, $\\overline{AB}$, $2,3\\overline 4$.\n"
        "Relationen: $x \\to \\infty$, $a \\approx b$, $p \\equiv q$, $p \\not\\equiv r$, $1\\,\\text{cm} \\hat{=} 5\\,\\text{km}$, "
        "$x \\le y \\ge z$, $d \\ll L \\gg r$, $a != 0$, $x \\pm 2 \\mp 1$.\n"
        "Klammern, Pfeile & Mengen: $\\langle u, v \\rangle$, $A \\Rightarrow B \\Leftrightarrow C \\Leftarrow D$, "
        "$x \\mapsto x^2$, $A \\leftarrow B$, $4\\,\\text{NO} \\xrightarrow[320\\text{ bis }400^\\circ\\text{C}]{\\text{Katalysator}} 2\\,\\text{N}_2$, "
        "$M = \\emptyset$, $x \\in \\mathbb{R}$, $n \\in \\mathds{N}$, $A \\subset B \\subseteq C \\supset D \\supseteq E$, $\\exists x$, $g \\parallel h$.\n"
        "Punkte, Produkte & Funktionen: $1, 2, \\dots, n$, $a_1 + \\cdots + a_n$, $3 \\cdot 10^8$, C2·0,05, "
        "$\\sin(\\theta) + \\cos(\\vartheta) + \\tan(\\eta) + \\cot(\\Theta) + \\arcsin(x)$, $\\ln(x) + \\lg(y) + \\log_2(z)$, "
        "sum_{i=1}^n a^3_i und int_0^1 x dx.\n"
        "Vektoren & Brüche: $\\vec a$, $\\vec \\omega$, $\\vec{p}_1$, $\\vec{F}_A$, (-1/2), y = -1/2, 1/-2, 1/2 - 1/4, 1/1.000.000, 1/2 x, "
        "Verwendung von $-Zeichen in `=B2+$F$1` sowie =A2+$F$1."
    )
    out = standardize_formulas(sample, fibs_mode=True)
    assert r"\f{\f{m_1}{m_2}}{1 + \f{a}{b}}" in out
    assert r"\f{3}{8}" in out
    assert r"\s{x}" in out
    assert r"\s[3]{27}" in out
    assert r"\ol{AB}" in out
    assert r"2,3\ol{4}" in out
    assert r"x \to \8" in out
    assert r"a \apx b" in out
    assert r"p \eqv q" in out
    assert r"p \n \eqv r" in out
    assert r"1 cm \^= 5 km" in out
    assert "x <= y >= z" in out
    assert "d << L >> r" in out
    assert r"a \neq 0" in out
    assert r"x \pm 2 \mp 1" in out
    assert r"\l< u, v \r>" in out
    assert r"A \Ra B \Lra C \La D" in out
    assert r"x \mt x^2" in out
    assert r"A \la B" in out
    assert r"\xra[320 bis 400 °C]{Katalysator}" in out
    assert r"M = \es" in out
    assert r"x \in \R" in out
    assert r"n \in \N" in out
    assert r"A \sbs B \sbse C \sps D \spsq E" in out
    assert r"\ex x" in out
    assert r"g \| h" in out
    assert "1, 2, ..., n" in out
    assert r"a_1 + \cd + a_n" in out
    assert "3 * 10^8" in out
    assert "C2*0,05" in out
    assert "sin(~h) + cos(~h) + tan(~j) + cot(~H) + arcsin(x)" in out
    assert r"\ln(x) + \lg(y) + \log_2(z)" in out
    assert r"\sum_{i=1}^n a_i^3" in out
    assert r"\int_0^1 x dx" in out
    assert r"\vec{a}" in out
    assert r"\vec{~w}" in out
    assert r"\vec{p_1}" in out
    assert r"\vec{F_A}" in out
    assert r"(-\f{1}{2})" in out
    assert r"y = -\f{1}{2}" in out
    assert r"\f{1}{-2}" in out
    assert "1/2 - 1/4" in out
    assert "1/1.000.000" in out
    assert r"\f{1}{2}x" in out
    assert "$-Zeichen" in out
    assert "`=B2+$F$1`" in out
    assert "=A2+$F$1" in out
    assert "__FIBS_BARE_PROT_" not in out
    assert "__STD_DOLLAR_PROT_" not in out





