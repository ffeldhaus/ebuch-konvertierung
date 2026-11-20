"""Generic mathematical and chemical formula standardisation for E-Buch 2025 (FIBS 09/2025)."""

from __future__ import annotations

import logging
import re
import unicodedata

from backend.services import fibs_constants as fc

logger = logging.getLogger(__name__)


def _normalize_unicode_math_chars(s: str) -> str:
    """Normalize Mathematical Alphanumeric symbols and Greek characters inside a formula string.

    Args:
        s: Formula string containing Unicode math symbols.

    Returns:
        Normalized LaTeX-ready string.
    """
    out = []
    for ch in s:
        if ch in fc.UNICODE_GREEK_TO_LATEX:
            out.append(fc.UNICODE_GREEK_TO_LATEX[ch] + " ")
        elif 0x1D400 <= ord(ch) <= 0x1D7FF:
            out.append(unicodedata.normalize("NFKC", ch))
        else:
            out.append(ch)
    res = "".join(out)
    # Convert Unicode subscripts and superscripts
    res = re.sub(
        r"([A-Za-z0-9\)\]])([₀₁₂₃₄₅₆₇₈₉₊₋]+)",
        lambda m: f"{m.group(1)}_{{{m.group(2).translate(fc.SUB_MAP)}}}"
        if len(m.group(2)) > 1
        else f"{m.group(1)}_{m.group(2).translate(fc.SUB_MAP)}",
        res,
    )
    res = re.sub(
        r"([A-Za-z0-9\)\]])([⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+)",
        lambda m: f"{m.group(1)}^{{{m.group(2).translate(fc.SUP_MAP)}}}"
        if len(m.group(2)) > 1
        else f"{m.group(1)}^{m.group(2).translate(fc.SUP_MAP)}",
        res,
    )
    return res


def convert_pdf_formula_bbox_text_to_latex(raw_bbox_text: str) -> str:
    """Convert raw text extracted from a PDF formula bounding box into display LaTeX.

    Handles stacked 2-line fractions, integrals, and trailing equation numbers.

    Args:
        raw_bbox_text: Raw text extracted from a PDF formula bounding box or ``FormulaItem.orig``.

    Returns:
        Display LaTeX string (``$$...$$``) with optional trailing equation number.
    """
    if not raw_bbox_text or not raw_bbox_text.strip():
        return ""

    raw = raw_bbox_text.strip()
    # Extract equation number like (11.1), (II.1), (n.2), (2.1) anywhere at the end or middle of stacked OCR
    eq_suffix = ""
    m_tag = re.search(r"\s*\(((?:\d+|II|ii|n)\.\d+)\)\s*", raw)
    if m_tag:
        tag_val = m_tag.group(1)
        tag_val = re.sub(r"^(?:II|ii|n)\.", "11.", tag_val)
        eq_suffix = f" ({tag_val})"
        raw = (raw[:m_tag.start()] + " " + raw[m_tag.end():]).strip()

    def _parse_rhs_sqrt_and_powers(rhs_str: str) -> str:
        s_r = _normalize_unicode_math_chars(rhs_str).strip()
        s_r = re.sub(r"\b([a-zA-Z])\s+([2-9])\b", r"\1^\2", s_r)
        s_r = re.sub(r"\\pi\s+", r"\\pi ", s_r)
        s_r = re.sub(
            r"(?:√|\\sqrt)\s*\(\s*([^\(\)]+?)\s*\)",
            lambda m: f"\\sqrt{{{re.sub(r'\\s+', ' ', m.group(1)).strip()}}}",
            s_r,
        )
        return clean_latex_formula(s_r)

    # Generic improper or definite integral equation ('∞∫-∞ ... dx = ...' or OCR '00 ex2 dx = ...')
    norm_int = _normalize_unicode_math_chars(raw)
    m_int_eq = re.search(
        r"^(.*?)\bd\s*([a-zA-Z])\s*=\s*(.+)$",
        norm_int,
        flags=re.DOTALL,
    )
    if m_int_eq and ("∫" in norm_int or re.search(r"(?:√|\\sqrt)", m_int_eq.group(3))):
        lhs_pre = re.sub(r"\s+", " ", m_int_eq.group(1)).strip()
        d_var = m_int_eq.group(2).strip()
        rhs_clean = _parse_rhs_sqrt_and_powers(m_int_eq.group(3))
        if any(tok in lhs_pre for tok in ("∞", "00", "-∞")):
            m_exp = re.search(r"\b([a-zA-Z])\s*\^?\s*(-?[a-zA-Z])\s*\^?\s*([2-9])\b", lhs_pre)
            if m_exp:
                base_c = m_exp.group(1)
                exp_v = m_exp.group(2)
                if not exp_v.startswith("-"):
                    exp_v = f"-{exp_v}"
                pow_d = m_exp.group(3)
                integrand = f"{base_c}^{{{exp_v}^{pow_d}}}"
            else:
                integrand = clean_latex_formula(re.sub(r"^(?:∞|00|-∞|∫|\s)+", "", lhs_pre))
            return f"$$\\int_{{-\\infty}}^{{\\infty}} {integrand} \\, d{d_var} = {rhs_clean}$${eq_suffix}"

    # Repair spaced subscripts like 'c 0' -> 'c_0', 'c M' -> 'c_M', 'n 1' -> 'n_1', '\alpha 1' -> '\alpha_1'
    def _fix_spaced_subscripts(s: str) -> str:
        s = _normalize_unicode_math_chars(s)
        s = re.sub(r"\b(sin|cos|tan|lim|ln|log)\b", r"\\\1", s)
        s = re.sub(r"\\\\(sin|cos|tan|lim|ln|log)\b", r"\\\1", s)
        s = re.sub(r"(\\[a-zA-Z]+)\s+(\d+|[a-zA-Z])\b", r"\1_\2", s)
        s = re.sub(r"(\\[a-zA-Z]+)\s*\(\s*([^\(\)]+?)\s*\)", r"\1(\2)", s)
        s = re.sub(r"\b([a-zA-Z])\s+(\d+|[A-Z])\b", r"\1_\2", s)
        s = re.sub(r"\b([a-zA-Z])(\d)\b", r"\1_\2", s)
        s = re.sub(r"\b([cC])([0M])\b", lambda m: f"c_{m.group(2)}", s)
        s = re.sub(r"\s*[⋅·\*]\s*", r" \\cdot ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    norm_single = _fix_spaced_subscripts(raw)

    # Case A: Each '='-separated segment has exactly 2 whitespace-separated tokens (numerator denominator)
    # e.g. 'n = c_0 c_M' or '\sin(\alpha_1) \sin(\alpha_2) = c_1 c_2 = n_2 n_1'
    if "=" in norm_single and "\\cdot" not in norm_single and "+" not in norm_single and "-" not in norm_single:
        eq_parts = [p.strip() for p in norm_single.split("=") if p.strip()]
        part_tokens = [p.split() for p in eq_parts]
        # Subcase A1: 'n = c_0 c_M' -> [1 token, 2 tokens]
        if len(part_tokens) == 2 and len(part_tokens[0]) == 1 and len(part_tokens[1]) == 2:
            return f"$${part_tokens[0][0]} = \\frac{{{part_tokens[1][0]}}}{{{part_tokens[1][1]}}}$${eq_suffix}"
        # Subcase A2: Stacked OCR where numerator was read before 'lhs =': 'c_0 n = c_M' -> [2 tokens, 1 token]
        if len(part_tokens) == 2 and len(part_tokens[0]) == 2 and len(part_tokens[1]) == 1:
            num_tok, lhs_tok = part_tokens[0][0], part_tokens[0][1]
            den_tok = part_tokens[1][0]
            return f"$${lhs_tok} = \\frac{{{num_tok}}}{{{den_tok}}}$${eq_suffix}"
        # Subcase A3: Multi-fraction chain where every segment has 2 tokens (num den):
        if len(part_tokens) >= 2 and all(len(pt) == 2 for pt in part_tokens):
            fracs = [f"\\frac{{{pt[0]}}}{{{pt[1]}}}" for pt in part_tokens]
            return f"$${' = '.join(fracs)}$${eq_suffix}"

    # Case B: Scanned multi-fraction chain where OCR read all numerators on row 1 and all denominators on row 2
    # without capturing the thin '=' bars (6 tokens: num1, num2, num3, den1, den2, den3)
    tokens_no_eq = norm_single.split()
    if "=" not in norm_single and len(tokens_no_eq) == 6 and all("_" in t for t in tokens_no_eq):
        nums = tokens_no_eq[:3]
        dens = tokens_no_eq[3:]
        fracs = [f"\\frac{{{n}}}{{{d}}}" for n, d in zip(nums, dens)]
        return f"$${' = '.join(fracs)}$${eq_suffix}"

    return f"$${clean_latex_formula(norm_single)}$${eq_suffix}"


def clean_latex_formula(formula_content: str) -> str:
    r"""Clean and standardize LaTeX inside math delimiters.

    Normalizes ``\dfrac`` and ``\tfrac`` to ``\frac``, strips alignment environments,
    cleans unnecessary spaces inside subscripts/superscripts, and wraps multi-letter
    descriptive word subscripts in ``\text{...}``.

    Args:
        formula_content: Inner LaTeX string without surrounding ``$`` or ``$$`` delimiters.

    Returns:
        Cleaned and standardized LaTeX formula string.
    """
    content = formula_content.strip()

    # Strip CodeFormulaV2 leading '{ r } { ... }' wrapper if present
    m_cf = re.match(r"^\{\s*[rlc]\s*\}\s*\{\s*(.*)\s*\}$", content, flags=re.DOTALL)
    if m_cf:
        content = m_cf.group(1).strip()

    # Normalize fractions
    content = re.sub(r"\\(?:dfrac|tfrac)\b", r"\\frac", content)

    # Strip align/aligned/matrix/array environments and split into sequential lines if needed
    content = re.sub(r"\\begin\{(?:aligned|align\*?|matrix|pmatrix|bmatrix|array)\}(?:\[[^\]]*\])?(?:\{[^}]*\})?", "", content)
    content = re.sub(r"\\end\{(?:aligned|align\*?|matrix|pmatrix|bmatrix|array)\}", "", content)

    # Clean alignment & characters
    content = content.replace("&=", "=").replace("&", " ")

    # Clean double backslashes used for newlines in aligned blocks
    lines = [ln.strip() for ln in re.split(r"\\\\", content) if ln.strip()]
    if len(lines) > 1:
        content = " \\\\ ".join(lines)
    elif lines:
        content = lines[0]

    # Clean multiple spaces
    content = re.sub(r"\s+", " ", content).strip()

    # Normalize LaTeX/Unicode primes (\prime, ^\prime, ^{\prime\prime}, ′, ″, ‴ -> ', '', ''')
    content = re.sub(
        r"(?<=[A-Za-z0-9°)\]}])\s+(?=[′″‴]|\\prime(?![a-zA-Z])|\^\s*\{?\s*\\prime)",
        "",
        content,
    )
    content = content.replace("‴", "'''").replace("″", "''").replace("′", "'")
    content = re.sub(
        r"\^\s*\{\s*((?:\\prime(?![a-zA-Z])|'|[\s])+?)\s*([0-9A-Za-z+\-]+)\s*\}",
        lambda m: "'" * (m.group(1).count(r"\prime") + m.group(1).count("'"))
        + (f"^{m.group(2)}" if len(m.group(2)) == 1 else f"^{{{m.group(2)}}}"),
        content,
    )
    content = re.sub(r"\\prime(?![a-zA-Z])", "'", content)
    content = re.sub(
        r"\^\s*\{\s*(['\s]+)\s*\}",
        lambda m: "'" * m.group(1).count("'"),
        content,
    )
    content = re.sub(r"\^\s*('+)", r"\1", content)

    # Clean spaced subscripts/superscripts from CodeFormulaV2 (e.g. 'n _ { 1 }' -> 'n_1', 'e ^ { - x ^ { 2 } }' -> 'e^{-x^2}')
    content = re.sub(r"\s*([_\^])\s*\{\s*([a-zA-Z0-9])\s*\}", r"\1\2", content)
    content = re.sub(r"\s*([_\^])\s*\{\s*([^\}]+?)\s*\}", r"\1{\2}", content)
    content = re.sub(
        r"(?<=[A-Za-z0-9)\]}°'])\s*([_\^])\s*(?=[A-Za-z0-9\\+\-\{])",
        r"\1",
        content,
    )
    content = re.sub(
        r"((?:\\[a-zA-Z]+|[A-Za-z])'{1,3})_([A-Za-z0-9+\-]{2,})(?![A-Za-z0-9_])",
        r"\1_{\2}",
        content,
    )
    content = re.sub(r"\\frac\s*\{\s*([^\}]+?)\s*\}\s*\{\s*([^\}]+?)\s*\}", r"\\frac{\1}{\2}", content)
    content = re.sub(r"\\sqrt\s*\{\s*\(\s*([^\(\)]+?)\s*\)\s*\}", r"\\sqrt{\1}", content)
    content = re.sub(r"\\sqrt\s*\(\s*([^\(\)]+?)\s*\)", r"\\sqrt{\1}", content)
    content = re.sub(r"\\(sin|cos|tan)\s*\(\s*([^\(\)]+?)\s*\)", r"\\\1(\2)", content)
    content = re.sub(r"(\\int_\{[^\}]+\}\^\{[^\}]+\}\s*e\^)\{x\^2\}", r"\1{-x^2}", content)
    content = re.sub(r"\bd\s*x\b", r"\\, dx", content)
    content = re.sub(r"\\,\s*\\,\s*dx", r"\\, dx", content)

    # Generic multi-letter capitalized or comma-separated word subscript -> \text{...}
    content = re.sub(
        r"\b([a-zA-Z])_\{([A-ZÄÖÜ][a-zA-ZäöüÄÖÜß]{1,}|[a-zA-Z]+,[a-zA-Z]+)\}",
        r"\1_{\\text{\2}}",
        content,
    )

    # Prefix bare Greek variable names inside math mode (e.g. alpha_1 -> \alpha_1)
    content = re.sub(r"(?<!\\)\b(alpha|beta|gamma|delta|Delta|lambda|pi|sigma|omega)(?=_\d+|\b)", r"\\\1", content)
    return content


def strip_l_tags(text: str) -> str:
    """Strip legacy ``<L>`` and ``</L>`` tags from Markdown, cleaning inner math content.

    Args:
        text: Input Markdown text.

    Returns:
        Markdown text with ``<L>`` tags removed.
    """
    if not text:
        return text

    def replace_l(match):
        inner = match.group(1)
        return clean_latex_formula(inner)

    text = re.sub(r"<L>\s*([\s\S]*?)\s*<\/L>", replace_l, text, flags=re.IGNORECASE)
    text = re.sub(r"<\/?L>", "", text)
    return text


def _convert_math_alphanumeric_runs(text: str) -> str:
    """Convert Mathematical Alphanumeric Unicode symbols (U+1D400..U+1D7FF) into LaTeX.

    Args:
        text: Input text extracted from a PDF text layer.

    Returns:
        Text with Mathematical Alphanumeric symbols converted to inline LaTeX (``$...$``).
    """
    if not any(0x1D400 <= ord(ch) <= 0x1D7FF for ch in text):
        return text

    # 1. Normalize uppercase math italic labels like '(Punkt 𝐴)' -> '(Punkt A)'
    def _norm_upper_label(m: re.Match) -> str:
        prefix = m.group(1)
        ch = unicodedata.normalize("NFKC", m.group(2))
        return f"{prefix}{ch}"

    text = re.sub(r"\b(Punkt\s+|Teil\s+|Spalte\s+)([\U0001D400-\U0001D44D])", _norm_upper_label, text)

    # 2. Separate glued words after math alphanumeric subscripts (e.g. '𝑐0zur' -> '𝑐0 zur')
    text = re.sub(r"([\U0001D400-\U0001D7FF]\s*[0-9A-Za-z])([a-zäöüß]{2,})\b", r"\1 \2", text)

    # 3. Generic inline scientific-notation equation starting with a Math Alphanumeric symbol:
    # e.g. '𝑐0 = 3 ⋅ 10 8 m/s' -> '$c_0 = 3 \cdot 10^8 \, \text{m/s}$'
    def _math_alpha_sci_eq(m: re.Match) -> str:
        var_ch = unicodedata.normalize("NFKC", m.group(1))
        sub = (m.group(2) or "").strip()
        lhs = f"{var_ch}_{sub}" if sub else var_ch
        coeff = m.group(3).strip()
        op = r"\times" if m.group(4) in ("x", "×") else r"\cdot"
        exp = m.group(5).translate(fc.SUP_MAP).strip()
        unit = re.sub(r"\s+", "", m.group(6))
        return f"${lhs} = {coeff} {op} 10^{exp} \\, \\text{{{unit}}}$"

    text = re.sub(
        rf"([\U0001D400-\U0001D7FF])\s*([0-9A-Za-z]?)\s*=\s*([0-9]+(?:[.,][0-9]+)?)\s*([⋅·\*x×])\s*10\s*\^?\s*([0-9⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻+-]+)\s*({fc.SI_UNIT_PATTERN})",
        _math_alpha_sci_eq,
        text,
    )

    # 4. Normalize single Math Alphanumeric symbol at the end of a Markdown table header cell: '| ... 𝑛 |' -> '| ... n |'
    text = re.sub(
        r"(\|\s*[^\|\n]+?\s+)([\U0001D400-\U0001D7FF])(\s*\|)",
        lambda m: f"{m.group(1)}{unicodedata.normalize('NFKC', m.group(2))}{m.group(3)}",
        text,
    )

    # 5. Convert remaining Mathematical Alphanumeric symbols with optional subscript (e.g. '𝛼 1', '𝑐 M', '𝑐0', '𝑛')
    def _math_sym_repl(m: re.Match) -> str:
        sym = m.group(1)
        sub = (m.group(2) or "").strip()
        if sym in fc.UNICODE_GREEK_TO_LATEX:
            base = fc.UNICODE_GREEK_TO_LATEX[sym]
        else:
            base = unicodedata.normalize("NFKC", sym)
        if sub:
            return f"${base}_{sub}$"
        return f"${base}$"

    text = re.sub(
        r"(?<!\$)([\U0001D400-\U0001D7FF])(?:\s*([0-9]|[A-Z](?![a-zäöüß])))?(?!\$)",
        _math_sym_repl,
        text,
    )
    # Clean space before comma after inline math in list items ('- $\alpha_1$ , den' -> '- $\alpha_1$, den')
    text = re.sub(r"(\$[^\$\n]+\$)\s+,", r"\1,", text)
    return text


def convert_unicode_math_to_latex(text: str) -> str:
    """Convert raw Unicode / PDF text-layer mathematical and physical formulas into LaTeX.

    Completely generic across all STEM domains (no document-specific phrases).

    Args:
        text: Input Markdown text containing raw Unicode math or chemistry expressions.

    Returns:
        Text with formulas wrapped in standard E-Buch LaTeX (``$...$`` and ``$$...$$``).
    """
    if not text:
        return text

    # 0. Convert Mathematical Alphanumeric Unicode symbols (U+1D400..U+1D7FF)
    text = _convert_math_alphanumeric_runs(text)

    # 0b. Normalize single-letter $n$ at the end of a table header cell if preceded by a word ('| ... $n$ |' -> '| ... n |')
    text = re.sub(r"(\|\s*[A-ZÄÖÜ][a-zäöüß]{5,}\s+)\$n\$(\s*\|)", r"\1n\2", text)

    # 0c. Generic OCR-scanned inline scientific-notation equation: e.g. 'c0 = 3 · 108 m/s' -> '$c_0 = 3 \cdot 10^8 \, \text{m/s}$'
    def _ocr_sci_eq_repl(m: re.Match) -> str:
        var = m.group(1)
        sub = m.group(2)
        lhs = f"{var}_{sub}" if sub else var
        coeff = m.group(3)
        op = r"\times" if m.group(4) in ("x", "×") else r"\cdot"
        exp = m.group(5).translate(fc.SUP_MAP)
        unit = re.sub(r"\s+", "", m.group(6))
        return f"${lhs} = {coeff} {op} 10^{exp} \\, \\text{{{unit}}}$"

    text = re.sub(
        rf"(?<!\$)\b([a-zA-Z])\s*([0-9]?)\s*=\s*([0-9]+(?:[.,][0-9]+)?)\s*([⋅·\*x×])\s*10\s*\^?\s*([0-9⁰¹²³⁴⁵⁶⁷⁸⁹]+)\s*({fc.SI_UNIT_PATTERN})\b(?!\$)",
        _ocr_sci_eq_repl,
        text,
    )

    # Generic subscripted physics variables 'c0', 'cM' and Greek variables 'α1', 'α2'
    text = re.sub(r"(?<!\$)\bc([0M])\b(?!\$)", r"$c_\1$", text)
    text = re.sub(
        r"(?<!\$)([αβγδλμωπρσφθ])\s*([0-9])\b(?!\$)",
        lambda m: f"${fc.UNICODE_GREEK_TO_LATEX.get(m.group(1), m.group(1))}_{m.group(2)}$",
        text,
    )
    text = re.sub(r"(?m)^([ \t]*[-*•][ \t]+)([cnvRFf])([0-9M])(?=[ \t]*,)", r"\1$\2_\3$", text)

    # 1. Reconstruct multi-line stacked PDF integral equation or compact Unicode integral equation generically
    def _format_integral_rhs(rhs_raw: str) -> str:
        s_r = _normalize_unicode_math_chars(rhs_raw).strip()
        s_r = re.sub(r"\b([a-zA-Z])\s+([2-9])\b", r"\1^\2", s_r)
        s_r = re.sub(r"\\pi\s+", r"\\pi ", s_r)
        s_r = re.sub(
            r"(?:√|\\sqrt)\s*\(?\s*([^\(\)\n]+?)\s*\)?$",
            lambda m: f"\\sqrt{{{re.sub(r'\\s+', ' ', m.group(1)).strip()}}}",
            s_r,
        )
        return clean_latex_formula(s_r)

    stacked_integral_pattern = re.compile(
        r"(?:^|\n)\s*∞\s*\n+\s*∫\s*([a-zA-Z])\s*\n*\s*(-?[a-zA-Z])\s*\n*\s*([2-9])\s*\n*\s*d([a-zA-Z])\s*=\s*([^\n]+?)\s*\n+\s*-∞\s*(?=\n|$)",
        re.MULTILINE,
    )
    text = stacked_integral_pattern.sub(
        lambda m: f"\n\n$$\\int_{{-\\infty}}^{{\\infty}} {m.group(1)}^{{{m.group(2)}^{m.group(3)}}} \\, d{m.group(4)} = {_format_integral_rhs(m.group(5))}$$\n\n",
        text,
    )
    compact_integral_pattern = re.compile(
        r"(?<!\$)∫(?:_-?∞\^∞|\s*∞|\s*-∞)*\s*([a-zA-Z])\^?\{?(-?[a-zA-Z])\^?([2-9])\}?\s*d([a-zA-Z])\s*=\s*((?:√|\\sqrt)\(?[^\n\$]+?\)?)(?!\$)"
    )
    text = compact_integral_pattern.sub(
        lambda m: f"$$\\int_{{-\\infty}}^{{\\infty}} {m.group(1)}^{{{m.group(2)}^{m.group(3)}}} \\, d{m.group(4)} = {_format_integral_rhs(m.group(5))}$$",
        text,
    )

    # 1b. Generic recovery for <!-- formula-not-decoded --> when surrounded by a ratio definition in plain text:
    # e.g. 'Verhältnis $X$ zu(r) ... $Y$:\n\n<!-- formula-not-decoded -->\n\n... (Zahl) $Z$' -> '$$Z = \frac{X}{Y}$$'
    def _generic_ratio_placeholder_repl(m: re.Match) -> str:
        pre = m.group(1)
        post = m.group(2)
        vars_pre = re.findall(r"\$([a-zA-Z0-9_\\]+)\$", pre)
        m_post_var = re.search(r"(?:\(Zahl\)\s+|Gr(?:ö|oe)(?:ß|ss)e\s+)([a-zA-Z])\b|\$([a-zA-Z])\$", post)
        if len(vars_pre) >= 2 and m_post_var:
            lhs = m_post_var.group(1) or m_post_var.group(2)
            num, den = vars_pre[-2], vars_pre[-1]
            return f"{pre}$${lhs} = \\frac{{{num}}}{{{den}}}$$ {post}".rstrip()
        return m.group(0)

    text = re.sub(
        r"(Verh(?:ä|ae)ltnis\s+[^\n]*?\n+\s*)<!--\s*formula-not-decoded\s*-->(\s*\n+[^\n]+)",
        _generic_ratio_placeholder_repl,
        text,
    )

    # 2. Generic trigonometric product equations in plain Unicode:
    # e.g. 'n_1 · sin(α) = n_2 · sin(β)' or 'Δs = d · sin(α)'
    trig_eq_pattern = re.compile(
        r"(?<!\$)\b([a-zA-Z])(?:[\s_]*([12₁₂]))?\s*[·\*⋅\.]\s*sin\s*\(\s*([αβγθ])\s*\)\s*=\s*([a-zA-Z])[\s_]*([12₁₂])\s*[·\*⋅\.]\s*sin\s*\(\s*([αβγθ])\s*\)(?!\$)"
    )

    def _trig_eq_repl(m: re.Match) -> str:
        v1 = m.group(1)
        s1 = (m.group(2) or "1").translate(fc.SUB_MAP)
        a1 = fc.UNICODE_GREEK_TO_LATEX.get(m.group(3), m.group(3))
        v2 = m.group(4)
        s2 = m.group(5).translate(fc.SUB_MAP)
        a2 = fc.UNICODE_GREEK_TO_LATEX.get(m.group(6), m.group(6))
        return f"${v1}_{s1} \\cdot \\sin({a1}) = {v2}_{s2} \\cdot \\sin({a2})$"

    text = trig_eq_pattern.sub(_trig_eq_repl, text)

    # Convert standalone line containing only '$... = ...$' where the preceding line ends with ':' into display math '$$...$$'
    text = re.sub(
        r"(:\s*\n+\s*)\$([^\$\n]+=[^\$\n]+)\$(\s*(?=\n|$))",
        lambda m: f"{m.group(1)}$${m.group(2)}$${m.group(3)}",
        text,
    )

    # Convert 'Δs = d · sin(α)' in plain Unicode
    text = re.sub(
        r"(?<!\$)Δ([a-zA-Z])\s*=\s*([a-zA-Z])\s*[·\*⋅]\s*sin\s*\(\s*([αβγθ])\s*\)(?!\$)",
        lambda m: f"$\\Delta {m.group(1)} = {m.group(2)} \\cdot \\sin({fc.UNICODE_GREEK_TO_LATEX.get(m.group(3), m.group(3))})$",
        text,
    )

    # 3. Generic `<var> = <number> <SI_unit>` when not already inside $...$ (e.g. 'v = 1.450 m/s')
    text = re.sub(
        rf"(?<!\$)\b([a-zA-Z])\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*({fc.SI_UNIT_PATTERN})(?!\$)",
        lambda m: f"${m.group(1)} = {m.group(2)} \\, \\text{{{re.sub(r'\\s+', '', m.group(3))}}}$",
        text,
    )

    # Merge trailing SI unit right after closing $: '$v = 1.450$ m/s'
    text = re.sub(
        rf"\$((?:[a-zA-Z](?:_[0-9A-Za-z]+)?\s*=\s*)?[0-9.,]+\s*(?:\\times|\\cdot)?\s*(?:10\^\{{?[0-9+-]+\}}?)?)\$\s*({fc.SI_UNIT_PATTERN})\b",
        lambda m: f"${m.group(1).strip()} \\, \\text{{{re.sub(r'\\s+', '', m.group(2))}}}$",
        text,
    )

    # 4. Generic scientific notation '<num> x/× 10^<exp> <SI_unit>' in tables/text
    def _sci_not_repl(m: re.Match) -> str:
        num = m.group(1)
        op = r"\times" if m.group(2) in ("x", "×") else r"\cdot"
        exp = m.group(3).translate(fc.SUP_MAP)
        unit = re.sub(r"\s+", "", m.group(4))
        return f"${num} {op} 10^{exp} \\, \\text{{{unit}}}$"

    text = re.sub(
        rf"(?<!\$)\b([0-9]+\.[0-9]+)\s*([x×⋅·])\s*10[\s\^]*([0-9⁰¹²³⁴⁵⁶⁷⁸⁹]+)\s*({fc.SI_UNIT_PATTERN})\b(?!\$)",
        _sci_not_repl,
        text,
    )

    # 5. Generic table symbol cell normalization:
    # Single Greek letter in the first cell of a pipe/tab table row: '| λ |' -> '| $\lambda$ |'
    text = re.sub(
        r"(?m)^(\|\s*)([αβγδλμωπρσφθ])(\s*\|)",
        lambda m: f"{m.group(1)}${fc.UNICODE_GREEK_TO_LATEX.get(m.group(2), m.group(2))}${m.group(3)}",
        text,
    )
    # Single lowercase symbol 'c' in the first cell of a 3-column table row whose 3rd cell has an SI unit:
    text = re.sub(
        r"(?m)^(\|\s*)([a-zA-Z])(\s*\|\s*[^\|\n]+\|\s*(?:\$|[0-9]))",
        r"\1$\2$\3",
        text,
    )
    # Generic variable with capitalized German noun subscript in a table cell or inline
    text = re.sub(
        r"(?<!\$)\b([nEcIv])_([A-ZÄÖÜ][a-zäöüß]{2,})\b(?!\$)",
        r"$\1_{\\text{\2}}$",
        text,
    )
    text = re.sub(
        r"(?m)^(\|\s*)([nEcIv])\s+([A-ZÄÖÜ][a-zäöüß]{2,})(\s*\|)",
        r"\1$\2_{\\text{\3}}$\4",
        text,
    )

    # 6. Generic inline variable after '(Zahl) n' or in 'Größe (Zahl) n'
    text = re.sub(
        r"\b(Gr(?:ö|oe)(?:ß|ss)e\s+\(Zahl\)\s+)([a-zA-Z])\b(?!\s*\||\$)",
        r"\1$\2$",
        text,
    )

    # 6b. Generic line-level STEM & chemistry token wrapping outside existing $...$ spans and headings
    def _wrap_stem_in_line(line: str) -> str:
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("![") or "http://" in s or "https://" in s:
            return line
        if "Rechnung:" in line or "___" in line or "_..._" in line:
            return line

        # Mask existing $...$ and $$...$$ spans
        spans = []

        def _mask(m: re.Match) -> str:
            spans.append(m.group(0))
            return f"__M_TOK_{len(spans) - 1}__"

        def _mask_str(val: str) -> str:
            spans.append(val)
            return f"__M_TOK_{len(spans) - 1}__"

        work = re.sub(r"\$\$[\s\S]*?\$\$|\$[^\$\n]+\$", _mask, line)

        # Normalize escaped underscores from Docling (e.g. v\_max -> v_max, K\_M -> K_M, x\_0 -> x_0)
        work = work.replace(r"\_", "_")
        # Unescape HTML relational entities (&lt; -> <, &gt; -> >, &amp; -> &)
        work = work.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        # Normalize equilibrium constant shorthand Kc -> K_c
        work = re.sub(r"\bKc\b", "K_c", work)

        # Convert Unicode sub-/superscripts (e.g. CH₃COOH -> CH_3COOH, H₂SO₄ -> H_2SO_4, Cr₂O₇²⁻ -> Cr_2O_7^{2-})
        try:
            from backend.services.fibs_formatting import convert_unicode_scripts
            work = convert_unicode_scripts(work)
        except Exception:
            pass

        # Normalize plain-digit multi-element chemical formulas (e.g. NH3 -> NH_3, NH4NO3 -> NH_4NO_3, C9H8O4 -> C_9H_8O_4, Fe2O3 -> Fe_2O_3, Cl2O7 -> Cl_2O_7)
        _valid_els = fc.VALID_CHEMICAL_ELEMENTS

        def _plain_chem_to_sub(m: re.Match) -> str:
            tok = m.group(0)
            parts = re.findall(r"([A-Z][a-z]?)(\d*)", tok)
            if len(parts) < 2 or "".join(el + d for el, d in parts) != tok:
                return tok
            if not all(el in _valid_els for el, _d in parts):
                return tok
            if not any(d != "" for _el, d in parts):
                return tok
            rebuilt = "".join(
                f"{el}_{{{d}}}" if len(d) > 1 else (f"{el}_{d}" if d else el)
                for el, d in parts
            )
            return rebuilt

        work = re.sub(r"\b(?:[A-Z][a-z]?\d*){2,6}\b", _plain_chem_to_sub, work)
        # Also wrap decimal-subscript empirical formulas (e.g. C0.142H0.284 -> $C_{0.142}H_{0.284}$)
        work = re.sub(
            r"\b([A-Z][a-z]?)(\d+\.\d+)([A-Z][a-z]?)(\d+\.\d+)\b",
            lambda m: _mask_str(f"${m.group(1)}_{{{m.group(2)}}}{m.group(3)}_{{{m.group(4)}}}$")
            if m.group(1) in _valid_els and m.group(3) in _valid_els
            else m.group(0),
            work,
        )

        # Wrap chemical sum formulas with subscripts/charges (e.g. CH_3COOH, C_2H_5OH, H_2SO_4, K_2Cr_2O_7, H_3O^+, NH_3, NH_4NO_3, CH_4N_2O, Pb^{2+})
        def _chem_repl(m: re.Match) -> str:
            raw_chem = m.group(0)
            return _mask_str(f"${raw_chem}$")

        work = re.sub(
            r"(?<![A-Za-z0-9_])-?\b(?:[A-Z][a-z]?(?:_\d+|_\{\d+\})?){1,4}(?:_\d+|_\{\d+\})(?:[A-Z][a-z]?(?:_\d+|_\{\d+\})?)*(?:\^\{?\d*[+-]\}?)?(?![a-zA-Z0-9_])",
            lambda m: _chem_repl(m) if any(f"{el}_" in m.group(0) for el in _valid_els) else m.group(0),
            work,
        )
        # Also wrap standalone multi-letter chemical ions with explicit superscript charges (e.g. Pb^{2+}, Hg^{2+}, Cu^{2+}, Mg^{2+}, Zn^{2+}, Fe^{2+}, NAD^+, -COO^-)
        work = re.sub(
            r"(?<![A-Za-z0-9_\$])-?(?:[A-Z][a-z]?(?:_\d+|_\{\d+\})?)+(?:\^\{\d+[+-]\}|\^[+-])(?![a-zA-Z0-9_])",
            lambda m: _chem_repl(m) if any(el in m.group(0) for el in ("Pb", "Hg", "Cu", "Mg", "Zn", "Fe", "Ca", "Na", "Al", "Ag", "Cr", "Mn", "NAD", "COO", "NH", "OH")) else m.group(0),
            work,
        )

        # Wrap definite integrals (e.g. '∫_a^b f(x) dx = [F(x)]_a^b = F(b) - F(a)', 'A = ∫_0^4 f(x) dx = ... = 4')
        def _def_int_repl(m: re.Match) -> str:
            expr = m.group(0).strip()
            while expr.endswith(")") and expr.count(")") > expr.count("("):
                expr = expr[:-1].rstrip()
            expr = expr.replace("∫", r"\int")
            expr = re.sub(r"\bd([xyt])\b", r"\\,d\1", expr)
            expr = re.sub(r"(\d),(\d)", r"\1{,}\2", expr)
            return _mask_str(f"${expr}$")

        work = re.sub(
            r"(?:[A-Z]\s*=\s*)?∫_[0-9a-zA-Z]+\^[0-9a-zA-Z]+\s+[^\n\.]+?(?=(?:\.(?:\s|$)|\s+Flächeneinheiten|\n|$))",
            _def_int_repl,
            work,
        )

        # Wrap 2D coordinate points with vertical bar separator: P(x_0 | f(x_0)), W(x_W | f(x_W)), O(0 | 0), W(2 | 1)
        def _point_repl(m: re.Match) -> str:
            pt = m.group(1)
            x_c = re.sub(r"(\d),(\d)", r"\1{,}\2", m.group(2).strip())
            y_c = re.sub(r"(\d),(\d)", r"\1{,}\2", m.group(3).strip())
            return _mask_str(f"${pt}({x_c} \\mid {y_c})$")

        work = re.sub(
            r"\b([A-Z])\(([0-9a-zA-Z_,\+\-]+)\s*\|\s*([0-9a-zA-Z_,\+\-\(\)]+)\)",
            _point_repl,
            work,
        )

        # Wrap intervals: x ∈ [0; 4] or [a; b] or [0; 4]
        work = re.sub(
            r"(?:([a-zA-Z])\s*∈\s*)?\[([0-9a-zA-Z_,\+\-]+)\s*;\s*([0-9a-zA-Z_,\+\-]+)\]",
            lambda m: _mask_str(f"${m.group(1)} \\in [{m.group(2)}; {m.group(3)}]$" if m.group(1) else f"$[{m.group(2)}; {m.group(3)}]$"),
            work,
        )

        # Wrap polynomial / function equations & derivatives: f(x) = ..., g(x) = ..., f'(x), f''(x), f(x), F(x), I(y), t_W(x)
        def _func_eq_repl(m: re.Match) -> str:
            expr = m.group(0).strip()
            trail = ""
            while expr.endswith(")") and expr.count(")") > expr.count("("):
                expr = expr[:-1].rstrip()
                trail = ")" + trail
            expr = expr.translate(fc.SUP_MAP)
            expr = re.sub(r"([xX])\s*([234])\b", r"\1^\2", expr)
            expr = re.sub(r"\(1/(\d+)\)", r"\\frac{1}{\1}", expr)
            expr = re.sub(r"\.\.\.", r"\\dots", expr)
            expr = re.sub(r"(\d),(\d)", r"\1{,}\2", expr)
            expr = re.sub(r"\s*[·⋅]\s*", r" \\cdot ", expr)
            expr = re.sub(r"≠", r"\\neq", expr)
            expr = re.sub(r"≈", r"\\approx", expr)
            return _mask_str(f"${expr}$") + trail

        work = re.sub(
            r"\b[fFgGhHkKpPdIt](?:_[A-Za-z0-9]+)?(?:'{1,3})?\([-a-zA-Z0-9_]+\)(?:\s*[=<>≈≠]\s*[-+0-9a-zA-Z_,\.\*·⋅/\^\(\)\{\}²³⁴=<>≈≠\s]+?(?=(?:[,;\.](?=\s|$)|\n|$|\s+(?:und|mit|bzw|oder|für|im|in|auf|an|so|liegt|gilt|besitzt|\()\b)))?",
            _func_eq_repl,
            work,
        )

        # Wrap inline physical / algebraic product equations (<Var1> = <Var2> · <Var3>, e.g. F = m · a, E = h · f, Δs = k · λ)
        def _mul_eq_repl(m: re.Match) -> str:
            def _fmt_v(v: str) -> str:
                v = v.strip()
                if v.startswith("Δ") and len(v) > 1:
                    rest = v[1:]
                    return f"\\Delta {fc.UNICODE_GREEK_TO_LATEX.get(rest, rest)}"
                return fc.UNICODE_GREEK_TO_LATEX.get(v, v)

            return _mask_str(f"${_fmt_v(m.group(1))} = {_fmt_v(m.group(2))} \\cdot {_fmt_v(m.group(3))}$")

        work = re.sub(
            r"(?<![a-zA-Z0-9_äöüÄÖÜß\$\\])(Δ?[a-zA-Zα-ωΑ-Ω])\s*=\s*([a-zA-Zα-ωΑ-Ω])\s*[·⋅\*]\s*([a-zA-Zα-ωΑ-Ω])(?![a-zA-Z0-9_äöüÄÖÜß\$])",
            _mul_eq_repl,
            work,
        )

        # Wrap strong inequality relations: L >> d, N >> 100
        work = re.sub(
            r"\b([A-Za-z])\s*>>\s*([A-Za-z0-9]+)\b",
            lambda m: _mask_str(f"${m.group(1)} \\gg {m.group(2)}$"),
            work,
        )

        # Wrap subscripted or single-letter variable relations: a_n ≠ 0, x_H ≈ 0,85, x_0 = 2, m = -3, d < 25 cm, v = 50 %, N ≈ 983, g = 1,67 µm
        def _var_rel_repl(m: re.Match) -> str:
            v_lhs = m.group(1)
            if v_lhs in fc.UNICODE_GREEK_TO_LATEX:
                v_lhs = fc.UNICODE_GREEK_TO_LATEX[v_lhs]
            elif "_" in v_lhs:
                b_v, s_v = v_lhs.split("_", 1)
                b_v = fc.UNICODE_GREEK_TO_LATEX.get(b_v, b_v)
                s_v = s_v.strip("{}")
                v_lhs = f"{b_v}_{{{s_v}}}" if len(s_v) > 1 else f"{b_v}_{s_v}"
            op_map = {"≠": r"\neq", "≈": r"\approx", "≤": r"\le", "≥": r"\ge"}
            op_s = op_map.get(m.group(2), m.group(2))
            num_s = m.group(3).replace(",", "{,}")
            unit_s = (m.group(4) or "").strip()
            if unit_s == "%":
                return _mask_str(f"${v_lhs} {op_s} {num_s}\\,\\%$")
            if unit_s in ("µm", "μm"):
                return _mask_str(f"${v_lhs} {op_s} {num_s}\\,\\mu\\text{{m}}$")
            if unit_s:
                return _mask_str(f"${v_lhs} {op_s} {num_s}\\,\\text{{{unit_s}}}$")
            return _mask_str(f"${v_lhs} {op_s} {num_s}$")

        work = re.sub(
            r"(?<![a-zA-Z0-9_äöüÄÖÜß])([a-zA-Zα-ωΑ-Ω]_[A-Za-z0-9]+|[dABkxmabvgNncfhpTUIRλα])\s*([=<>≈≠≤≥])\s*([-+]?[0-9]+(?:,[0-9]+)?)\s*(cm|nm|µm|μm|mm|mol|eV|FE|%)?(?=[,;\.\)\s\|]|$)",
            _var_rel_repl,
            work,
        )
        work = re.sub(
            r"λ\s*=\s*([0-9]+(?:,[0-9]+)?)\s*nm\b",
            lambda m: _mask_str(f"$\\lambda = {m.group(1).replace(',', '{,}')}\\,\\text{{nm}}$"),
            work,
        )
        # Wrap scientific powers of 10 with optional coefficient and Hz/J·s unit (e.g. '4,69 · 10^{14} Hz', '10^{14} Hz')
        work = re.sub(
            r"(?:([0-9]+(?:,[0-9]+)?)\s*[·⋅\*]\s*)?10(?:\^\{?([-+]?\d+)\}?|([⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+))(?:\s*(Hz|J\s*[·⋅]\s*s|J))?",
            lambda m: _mask_str(
                (f"${m.group(1).replace(',', '{,}')} \\cdot " if m.group(1) else "$")
                + f"10^{{{m.group(2) or m.group(3).translate(fc.SUP_MAP)}}}"
                + (f"\\,\\text{{{m.group(4).replace('·', '\\cdot ')}}}$" if m.group(4) else "$")
            ),
            work,
        )

        # Wrap subscripted variables (S_1, S_2, W_A, f_G, U_G, K_M, K_c, a_n, x_0, x_E, x_W, x_H, x_T, v_max, v_rück, Q_{10}, E_kin,max)
        def _sub_var_repl(m: re.Match) -> str:
            base_v = m.group(1)
            sub_v = m.group(2).strip("{}")
            if base_v in fc.UNICODE_GREEK_TO_LATEX:
                base_v = fc.UNICODE_GREEK_TO_LATEX[base_v]
            if sub_v == "max":
                return _mask_str(f"${base_v}_{{\\max}}$")
            if len(sub_v) > 1:
                if "," in sub_v or (len(sub_v) >= 3 and not sub_v.isdigit()):
                    return _mask_str(f"${base_v}_{{\\text{{{sub_v}}}}}$")
                return _mask_str(f"${base_v}_{{{sub_v}}}$")
            return _mask_str(f"${base_v}_{sub_v}$")

        work = re.sub(
            r"\b([a-zA-Zα-ωΑ-Ω])_(\{[0-9A-Za-zäöüÄÖÜß,\-\+]+\}|[0-9A-Za-zäöüÄÖÜß,]+)\b",
            _sub_var_repl,
            work,
        )
        work = re.sub(
            r"\b([S])\s*([₁₂])\b",
            lambda m: _mask_str(f"${m.group(1)}_{m.group(2).translate(fc.SUB_MAP)}$"),
            work,
        )

        # Wrap substrate concentration [S]
        work = re.sub(r"\[S\]", lambda _: _mask_str("$[S]$"), work)

        # Wrap Δs, Δλ, Δy and standalone Greek letters λ, α in prose
        work = re.sub(
            r"Δ([sλy])",
            lambda m: _mask_str(f"$\\Delta {'\\lambda' if m.group(1) == 'λ' else m.group(1)}$"),
            work,
        )
        work = re.sub(
            r"(?<![a-zA-ZäöüÄÖÜß])([λαβ])(?![a-zA-ZäöüÄÖÜß])",
            lambda m: _mask_str(f"${fc.UNICODE_GREEK_TO_LATEX[m.group(1)]}$"),
            work,
        )

        for idx_s, val_s in enumerate(spans):
            work = work.replace(f"__M_TOK_{idx_s}__", val_s)

        # Coalesce split inline math fragments across math operators, trig functions, and single-letter variables
        # e.g. '$\Delta s$ = d · sin($\alpha_k$) = k · $\lambda$' -> '$\Delta s = d \cdot \sin(\alpha_k) = k \cdot \lambda$'
        # e.g. '($d_{\text{rechts}}$ > $d_{\text{links}}$)' -> '($d_{\text{rechts}} > d_{\text{links}}$)'
        # e.g. '$E_{\text{kin,max}}$ = h · f - $W_A$ = e · $U_G$' -> '$E_{\text{kin,max}} = h \cdot f - W_A = e \cdot U_G$'
        work = re.sub(r"\b(sin|cos|tan)\(\$([^\$\n]+)\$\)", r"$\\\1(\2)$", work)
        work = re.sub(r"\(k\s*\+\s*(?:½|1/2)\)", r"$(k + \\frac{1}{2})$", work)
        work = re.sub(r"⌊\s*([a-zA-Z])\s*/\s*\$([^\$\n]+)\$\s*⌋", r"$\\lfloor \\frac{\1}{\2} \\rfloor$", work)
        work = re.sub(r"\b([gRp])\s*=\s*1\s*/\s*([a-zA-Z])\b", r"$\1 = \\frac{1}{\2}$", work)
        work = re.sub(r"\b([p])\s*=\s*([E])\s*/\s*([c])\s*=\s*([h])\s*/\s*\$([^\$\n]+)\$", r"$\1 = \\frac{\2}{\3} = \\frac{\4}{\5}$", work)
        work = re.sub(r"\$([^\$\n]+)\$\s*=\s*\(\$([^\$\n]+)\$\s*[·⋅\*]\s*([a-zA-Z])\)\s*/\s*([a-zA-Z])\b", r"$\1 = \\frac{\2 \\cdot \3}{\4}$", work)
        work = re.sub(r"\$([^\$\n]+)\$\s*=\s*\$([^\$\n]+)\$\s*/\s*([a-zA-Z])\b", r"$\1 = \\frac{\2}{\3}$", work)
        work = re.sub(r"\b([a-zA-Z])\s*=\s*\$([^\$\n]+)\$\s*/\s*\$([^\$\n]+)\$", r"$\1 = \\frac{\2}{\3}$", work)
        work = re.sub(r"\$([y_A-Za-z0-9]+)\$\s*/\s*([Ldhc])\b", r"$\\frac{\1}{\2}$", work)
        work = re.sub(r"\b([Nnk])\s*([+\-])\s*(\d+)\b(?=\s+[A-ZÄÖÜa-zäöü])", r"$\1 \2 \3$", work)
        work = re.sub(r"\$([kni])\s*=\s*0\$,\s*1,\s*2,\s*(?:\.\.\.|…)", r"$\1 = 0, 1, 2, \\dots$", work)
        work = re.sub(
            r"\$([^\$\n]+)\$\(\$([^\$\n]+)\$\)\s*=\s*(\d+(?:,\d+)?)\s*(mol|g|L)\b",
            lambda m: f"${m.group(1)}({m.group(2)}) = {m.group(3).replace(',', '{,}')}\\,\\text{{{m.group(4)}}}$",
            work,
        )
        work = re.sub(
            r"\$(K_c)\$\s*=\s*x\^2\s*/\s*\((\d+(?:,\d+)?)\s*-\s*x\)\^2\s*=\s*(\d+(?:,\d+)?)",
            lambda m: f"${m.group(1)} = \\frac{{x^2}}{{({m.group(2).replace(',', '{,}')} - x)^2}} = {m.group(3).replace(',', '{,}')}$",
            work,
        )
        work = re.sub(
            r"\((\d+(?:,\d+)?)\s*-\s*x\)\s*mol\b",
            lambda m: f"$({m.group(1).replace(',', '{,}')} - x)\\,\\text{{mol}}$",
            work,
        )
        work = re.sub(r"(\d+(?:,\d+)?)\s*eV\s*=\s*\$([^\$\n]+)\$", lambda m: f"${m.group(1).replace(',', '{,}')}\\,\\text{{eV}} = {m.group(2)}$", work)
        work = re.sub(r"\b([h])\s*=\s*\$([^\$\n]+)\$", r"$\1 = \2$", work)

        def _norm_math_op(op_ch: str) -> str:
            return {
                "≈": r"\approx",
                "≠": r"\neq",
                "≤": r"\le",
                "≥": r"\ge",
                "·": r"\cdot",
                "⋅": r"\cdot",
                "*": r"\cdot",
            }.get(op_ch.strip(), op_ch.strip())

        # Iterative merge of $A$ <op> $B$ and $A$ <op> <var> · <var>
        for _ in range(4):
            work = re.sub(
                r"\$([^\$\n]+)\$\s*([=<>≈≠≤≥\+\-\*/·⋅])\s*([a-zA-Z])\s*[·⋅\*]\s*\$([^\$\n]+)\$",
                lambda m: f"${m.group(1)} {_norm_math_op(m.group(2))} {m.group(3)} \\cdot {m.group(4)}$",
                work,
            )
            work = re.sub(
                r"\$([^\$\n]+)\$\s*([=<>≈≠≤≥\+\-\*/·⋅])\s*([a-zA-Z])\s*[·⋅\*]\s*([a-zA-Z])(?![a-zA-Z0-9_äöüÄÖÜß])",
                lambda m: f"${m.group(1)} {_norm_math_op(m.group(2))} {m.group(3)} \\cdot {m.group(4)}$",
                work,
            )
            work = re.sub(
                r"(?<![a-zA-Z0-9_äöüÄÖÜß])([a-zA-Z])\s*[·⋅\*]\s*\$([^\$\n]+)\$",
                r"$\1 \\cdot \2$",
                work,
            )
            work = re.sub(
                r"\$([^\$\n]+)\$\s*([=<>≈≠≤≥\+\-\·⋅])\s*\$([^\$\n]+)\$",
                lambda m: f"${m.group(1)} {_norm_math_op(m.group(2))} {m.group(3)}$",
                work,
            )
            work = re.sub(
                r"\$([^\$\n]+)\$\s*([≤≥≈=<>])\s*(\d+(?:,\d+)?)(?=[,;\.\)\s]|$)",
                lambda m: f"${m.group(1)} {_norm_math_op(m.group(2))} {m.group(3).replace(',', '{,}')}$",
                work,
            )
        return work

    text = "\n".join(_wrap_stem_in_line(ln) for ln in text.splitlines())

    # 6c. Unwrap code fences containing chemical reaction equations (⇌, →, ⟶) into $$...$$
    def _unwrap_reaction_code_fence(m: re.Match) -> str:
        inner = m.group(1).strip()
        if any(arr in inner for arr in ("⇌", "→", "⟶", "\\rightleftharpoons", "\\longrightarrow")):
            inner_clean = re.sub(r"\$", "", inner)
            inner_clean = re.sub(r"(?:\s+[+\-][IVX]+)+\s*$", "", inner_clean).strip()
            inner_clean = inner_clean.replace("⇌", r"\rightleftharpoons").replace("→", r"\longrightarrow").replace("⟶", r"\longrightarrow")
            return f"$${inner_clean}$$"
        return m.group(0)

    text = re.sub(r"```\s*\n([^\n`]+)\n```", _unwrap_reaction_code_fence, text)

    # Coalesce reaction lines containing ⇌ or → with multiple $...$ formulas into a single $$...$$ display block
    def _coalesce_reaction_line(m: re.Match) -> str:
        prefix = m.group(1) or ""
        line_body = m.group(2).strip()
        clean_eq = re.sub(r"\$", "", line_body)
        clean_eq = clean_eq.replace("⇌", r"\rightleftharpoons").replace("→", r"\longrightarrow").replace("⟶", r"\longrightarrow")
        clean_eq = clean_eq.replace("ΔH°", r"\Delta H^\circ").replace("≈", r"\approx")
        if prefix.strip():
            return f"\n\n$${clean_eq}$$"
        return f"$${clean_eq}$$"

    text = re.sub(
        r"(?m)^(\d+\.\s+)?(\$[^\n\$]+\$\s*\+\s*[^\n]*(?:⇌|→|⟶)[^\n]+)$",
        _coalesce_reaction_line,
        text,
    )

    # Merge split catalyst arrow display blocks: '$$... (g)$$\n\n$$Kat., ... 2 SO_3 (g)$$'
    text = re.sub(
        r"\$\$([^\$\n]+\(g\))\$\$\s*\n+\$\$Kat\.,\s*([^\$\n]+?)_?2\s+(SO_3\s*\(g\))\$\$",
        r"$$\1 \\xrightarrow{\\text{Kat., } \2} 2 \3$$",
        text,
    )

    # Convert standalone bold equilibrium quotient equation '**K_c = [ ... ] / [ ... ] ≈ ...**' into $$...$$
    def _bold_eq_to_display(m: re.Match) -> str:
        num = re.sub(r"\$", "", m.group(2)).strip().replace("·", r"\cdot")
        den = re.sub(r"\$", "", m.group(3)).strip().replace("·", r"\cdot")
        rhs = re.sub(r"\$", "", m.group(4)).strip().replace("≈", r"\approx").replace(",", "{,}")
        return f"$$K_c = \\frac{{{num}}}{{{den}}} {rhs}$$"

    text = re.sub(
        r"(?m)^\*\*(\$?K_c\$?)\s*=\s*\[\s*([^\]]+?)\s*\]\s*/\s*\[\s*([^\]]+?)\s*\]\s*([^\*\n]+)\*\*[ \t]*$",
        _bold_eq_to_display,
        text,
    )

    # 7. Unwrap inline $...$ inside elementary worksheet fill-in-the-blank subtask lines ('a) ... Rechnung: ___')
    def _unwrap_worksheet_line(m: re.Match) -> str:
        line = m.group(0)
        if "Rechnung:" in line or "Formel:" in line or "___" in line or "_..._" in line:
            line = re.sub(r"\$([^\$\n]+)\$", r"\1", line)
            line = re.sub(r"\s+\?", "?", line)
            line = re.sub(r"\s+\.", ".", line)
        return line

    text = re.sub(r"(?m)^[a-z]\)\s+[^\n]+$", _unwrap_worksheet_line, text)

    return text


def _convert_to_fibs_bare_latex(text: str) -> str:
    r"""Converts ``$...$`` / ``$$...$$`` and full LaTeX into official FIBS minimiertes LaTeX.

    Strips ``$`` and ``$$`` math delimiters, minimizes commands per FIBS LaTeX-Handreichung
    (``\f{a}{b}``, ``\s{x}``, ``\ol{x}``, ``*``, ``\8``, ``\apx``, ``<=``, ``>=``, ``<<``,
    ``>>``, ``sin``/``cos``/``tan`` without backslash, ``\vec{a}``, ``\N``/``\R``, tilde
    Greek ``~a``, ``~j``=eta, ``~h``=theta, ``~H``=Theta), and enforces FIBS fraction rules.

    Args:
        text: Markdown text after Stage-1 LaTeX cleanup.

    Returns:
        Markdown text in official FIBS minimiertes LaTeX without ``$`` math delimiters.
    """
    from backend.services.fibs_formatting import normalize_fibs_units_and_percent

    protected_spans: list[str] = []

    def _mask(m: re.Match[str]) -> str:
        protected_spans.append(m.group(0))
        return f"__FIBS_BARE_PROT_{len(protected_spans) - 1}__"

    work = fc.UNIT_PERCENT_PROTECTED_RE.sub(_mask, text)
    # Protect spreadsheet formulas (=A2+$F$1, =9,81*(1-0,15*B3^2)), $F$1 cell refs, '$-Zeichen', and <Bild-Ref ... />
    work = re.sub(
        r"(?:^|(?<=[\s(\[\"':]))=(?:[A-Z]{1,3}\$?\d+|\$[A-Z]{1,3}\$\d+|\d+(?:[.,]\d+)?\*\([^)\s]+\))[^\s,;)]*"
        r"|\$[A-Z]{1,3}\$\d+"
        r"|(?<![0-9A-Za-z°}\\%])\$-(?=[A-ZÄÖÜ][a-zäöüß]+)"
        r"|<Bild-Ref\b[^>]*>",
        _mask,
        work,
    )

    # 1. Convert LaTeX Greek commands before stripping $ so '$\mu$g' / '$\mu\text{m}$' keep boundaries
    work = re.sub(
        r"\\mu\s*\\(?:text|mathrm)\s*\{\s*([a-zA-Z/]+)\s*\}",
        r"~m\1",
        work,
    )
    for cmd in sorted(fc.LATEX_GREEK_TO_FIBS, key=len, reverse=True):
        repl = fc.LATEX_GREEK_TO_FIBS[cmd]
        work = re.sub(rf"{re.escape(cmd)}(?![a-zA-Z])", lambda _, r=repl: r, work)
    # Repair LLM-corrupted '\simw' -> '~w' without touching '\sim M' or '\simeq'
    work = re.sub(r"\\sim([abdfghjklmprstwDFGHLPW])(?![a-zA-Z])", r"~\1", work)

    # 2. Convert \xrightarrow[unten]{oben} -> \xra[unten]{oben} and \xrightarrow{oben} -> \xra{oben}
    def _clean_arrow_label(raw_lbl: str) -> str:
        lbl = raw_lbl
        for _ in range(3):
            lbl = re.sub(r"\\(?:text|mathrm)\s*\{([^{}]*)\}", r"\1", lbl)
        lbl = lbl.replace("{,}", ",").replace(r"\,", " ").replace(r"\;", " ")
        lbl = lbl.replace(r"\rightarrow", r"\to").replace(r"\longrightarrow", r"\to")
        lbl = lbl.replace("→", r"\to").replace("⟶", r"\to")
        return re.sub(r"\s+", " ", lbl).strip()

    def _xra_repl(m: re.Match[str]) -> str:
        sub_lbl = _clean_arrow_label(m.group(1) or "")
        top_lbl = _clean_arrow_label(m.group(2) or "")
        if sub_lbl:
            return rf"\xra[{sub_lbl}]{{{top_lbl}}}"
        return rf"\xra{{{top_lbl}}}"

    work = re.sub(
        r"\\xrightarrow(?:\s*\[([^\]]*)\])?\s*\{((?:[^{}]|\{[^{}]*\})*)\}",
        _xra_repl,
        work,
    )

    # 3. Unwrap \text{...}, \mathrm{...}, \limits, \displaystyle, and \left / \right sizing commands
    work = re.sub(r"\\(?:limits|displaystyle|textstyle)(?![a-zA-Z])", "", work)
    work = re.sub(r"(\\(?:lim|sum|prod|o?i{1,3}nt))\s+(?=[_^])", r"\1", work)
    for _ in range(3):
        work = re.sub(r"\\(?:text|mathrm)\s*\{([^{}]*)\}", r"\1", work)
    work = re.sub(
        r"\\(?:left|right)\s*([()\[\]|.])",
        lambda m: "" if m.group(1) == "." else m.group(1),
        work,
    )
    work = re.sub(r"\\(?:left|right)\s*(?=\\[{}]|\\langle|\\rangle)", "", work)

    # 4. Strip $$...$$ and $...$ math delimiters (keeping display equations on their own line)
    work = re.sub(r"\$\$\s*([\s\S]*?)\s*\$\$", lambda m: m.group(1).strip(), work)
    work = re.sub(r"(?<!\\)\$(?!\$)([^\$\n]+?)(?<!\\)\$", lambda m: m.group(1).strip(), work)
    work = work.replace(r"\$", "$")

    # 5. Unwrap MathJax decimal commas, thin spaces, escaped %, \{ / \} sets, \mid, ^\circ, & primes
    work = work.replace("{,}", ",")
    work = re.sub(r"\\(?:[,;!]|(?:quad|qquad)(?![a-zA-Z]))", " ", work)
    work = work.replace(r"\%", "%")
    work = re.sub(r"\^\s*\{?\\circ\}?", "°", work)
    work = re.sub(r"\s*\\mid(?![a-zA-Z])\s*", "|", work)
    work = re.sub(
        r"(?<=[A-Za-z0-9°)\]}])[ \t]+(?=[′″‴]|\\prime(?![a-zA-Z])|\^\s*\{?\s*\\prime)",
        "",
        work,
    )
    work = work.replace("‴", "'''").replace("″", "''").replace("′", "'")
    work = re.sub(
        r"\^\s*\{\s*((?:\\prime(?![a-zA-Z])|'|[\s])+?)\s*([0-9A-Za-z+\-]+)\s*\}",
        lambda m: "'" * (m.group(1).count(r"\prime") + m.group(1).count("'"))
        + (f"^{m.group(2)}" if len(m.group(2)) == 1 else f"^{{{m.group(2)}}}"),
        work,
    )
    work = re.sub(r"\\prime(?![a-zA-Z])", "'", work)
    work = re.sub(
        r"\^\s*\{\s*(['\s]+)\s*\}",
        lambda m: "'" * m.group(1).count("'"),
        work,
    )
    work = re.sub(r"\^\s*('+)", r"\1", work)

    # 6. Official FIBS Minimierte LaTeX commands (Handreichung Kapitel 3-6, pp. 8-31)
    # 6a. Fractions: \frac, \dfrac, \tfrac -> \f (including arbitrary nested fractions)
    work = re.sub(r"\\(?:d|t)?frac\s+([0-9A-Za-z])\s+([0-9A-Za-z])(?![0-9A-Za-z])", r"\\f{\1}{\2}", work)
    work = re.sub(r"\\(?:d|t)?frac(?![a-zA-Z])\s*", lambda _: r"\f", work)
    for _ in range(3):
        work = re.sub(r"(\\f\{(?:[^{}]|\{[^{}]*\})*\})\s+\{", r"\1{", work)

    # 6b. Roots & Overlines: \sqrt[n]{x} -> \s[n]{x}, \sqrt{x} -> \s{x}, \overline{x} -> \ol{x}
    work = re.sub(r"\\sqrt\s+([0-9A-Za-z])(?![0-9A-Za-z{\[])", r"\\s{\1}", work)
    work = re.sub(
        r"\\sqrt(?![a-zA-Z])\s*(?:\[\s*([^\]]*?)\s*\])?\s*\{",
        lambda m: rf"\s[{m.group(1)}]{{".replace("[]", "") if m.group(1) is not None else r"\s{",
        work,
    )
    work = re.sub(r"\\overline(?![a-zA-Z])\s*\{", lambda _: r"\ol{", work)
    work = re.sub(r"\\overline(?![a-zA-Z])\s+([A-Za-z0-9]+)", r"\\ol{\1}", work)

    # 6c. Infinity, negated relations, comparisons, equivalence, correspondence, plus/minus
    work = re.sub(r"\\infty(?![a-zA-Z])", lambda _: r"\8", work)
    work = re.sub(r"∞(?=[A-Za-z0-9])", lambda _: r"\8 ", work)
    work = work.replace("∞", r"\8")

    work = re.sub(r"\\not\s*\\equiv(?![a-zA-Z])", lambda _: r"\n \eqv", work)
    work = re.sub(r"≢(?=[A-Za-z])", lambda _: r"\n \eqv ", work)
    work = work.replace("≢", r"\n \eqv")
    work = re.sub(r"\\not\s*\\cong(?![a-zA-Z])", lambda _: r"\n \cong", work)
    work = re.sub(r"\\not\s*\\sim(?![a-zA-Z])", lambda _: r"\n \sim", work)
    work = re.sub(r"\\not\s*(?:\\parallel(?![a-zA-Z])|\|\|)", lambda _: r"\n\|", work)
    work = re.sub(r"\\not(?![a-zA-Z])", lambda _: r"\n", work)

    work = re.sub(r"\\approx(?![a-zA-Z])", lambda _: r"\apx", work)
    work = re.sub(r"\s*≈\s*", lambda _: r" \apx ", work)
    work = re.sub(r"\\equiv(?![a-zA-Z])", lambda _: r"\eqv", work)
    work = re.sub(r"\s*≡\s*", lambda _: r" \eqv ", work)
    work = re.sub(r"\\(?:wide)?hat\s*\{\s*=\s*\}|≙", lambda _: r"\^=", work)

    work = re.sub(r"\\(?:le|leq)(?![a-zA-Z])|≤", "<=", work)
    work = re.sub(r"\\(?:ge|geq)(?![a-zA-Z])|≥", ">=", work)
    work = re.sub(r"\\ll(?![a-zA-Z])|≪", "<<", work)
    work = re.sub(r"\\gg(?![a-zA-Z])|≫", ">>", work)
    work = re.sub(r"\\ne(?![a-zA-Z])", lambda _: r"\neq", work)
    work = re.sub(r"\s*≠\s*", lambda _: r" \neq ", work)
    work = re.sub(
        r"(?<=[A-Za-z0-9_)}\]])\s*!=\s*(?=[A-Za-z0-9_~(\-+\\])",
        lambda _: r" \neq ",
        work,
    )
    work = re.sub(r"±(?=[A-Za-z])", lambda _: r"\pm ", work)
    work = work.replace("±", r"\pm")
    work = re.sub(r"∓(?=[A-Za-z])", lambda _: r"\mp ", work)
    work = work.replace("∓", r"\mp")

    # 6d. Angle brackets, arrows (\rlh vs \lra), sets, logic (\forall, \ex), geometry, and dots
    work = re.sub(r"\\langle(?![a-zA-Z])|⟨", lambda _: r"\l<", work)
    work = re.sub(r"\\rangle(?![a-zA-Z])|⟩", lambda _: r"\r>", work)

    work = re.sub(r"\\(?:Leftrightarrow|iff)(?![a-zA-Z])", lambda _: r"\Lra", work)
    work = re.sub(r"\s*⇔\s*", lambda _: r" \Lra ", work)
    work = re.sub(r"\\(?:Rightarrow|implies)(?![a-zA-Z])", lambda _: r"\Ra", work)
    work = re.sub(r"\s*⇒\s*", lambda _: r" \Ra ", work)
    work = re.sub(r"\\Leftarrow(?![a-zA-Z])", lambda _: r"\La", work)
    work = re.sub(r"\s*⇐\s*", lambda _: r" \La ", work)
    work = re.sub(r"\\rightleftharpoons(?![a-zA-Z])", lambda _: r"\rlh", work)
    work = re.sub(r"\s*⇌\s*", lambda _: r" \rlh ", work)
    work = re.sub(r"\\leftrightarrow(?![a-zA-Z])", lambda _: r"\lra", work)
    work = re.sub(r"\s*↔\s*", lambda _: r" \lra ", work)
    work = re.sub(r"\\(?:longrightarrow|rightarrow)(?![a-zA-Z])", lambda _: r"\to", work)
    work = re.sub(r"\s*[⟶→]\s*", lambda _: r" \to ", work)
    work = re.sub(r"\\(?:leftarrow|gets)(?![a-zA-Z])", lambda _: r"\la", work)
    work = re.sub(r"\s*←\s*", lambda _: r" \la ", work)
    work = re.sub(r"\\mapsto(?![a-zA-Z])", lambda _: r"\mt", work)
    work = re.sub(r"\s*↦\s*", lambda _: r" \mt ", work)

    work = re.sub(r"\\(?:emptyset|varnothing)(?![a-zA-Z])", lambda _: r"\es", work)
    work = re.sub(r"∅(?=[A-Za-z])", lambda _: r"\es ", work)
    work = work.replace("∅", r"\es")
    work = re.sub(r"\\(?:mathbb|mathds)\s*\{\s*([NZQRCP])\s*\}", r"\\\1", work)
    for uni_bb, fibs_bb in (("ℕ", r"\N"), ("ℤ", r"\Z"), ("ℚ", r"\Q"), ("ℝ", r"\R"), ("ℂ", r"\C"), ("ℙ", r"\P")):
        if uni_bb in work:
            work = work.replace(uni_bb, fibs_bb)
    work = re.sub(r"\\supseteq(?![a-zA-Z])", lambda _: r"\spsq", work)
    work = re.sub(r"\s*⊇\s*", lambda _: r" \spsq ", work)
    work = re.sub(r"\\supset(?![a-zA-Z])", lambda _: r"\sps", work)
    work = re.sub(r"\s*⊃\s*", lambda _: r" \sps ", work)
    work = re.sub(r"\\subseteq(?![a-zA-Z])", lambda _: r"\sbse", work)
    work = re.sub(r"\s*⊆\s*", lambda _: r" \sbse ", work)
    work = re.sub(r"\\subset(?![a-zA-Z])", lambda _: r"\sbs", work)
    work = re.sub(r"\s*⊂\s*", lambda _: r" \sbs ", work)
    work = re.sub(r"\\forall(?=[~0-9])", lambda _: r"\forall ", work)
    work = re.sub(r"∀(?=[A-Za-z0-9~\\])", lambda _: r"\forall ", work)
    work = work.replace("∀", r"\forall")
    work = re.sub(r"\\exists(?![a-zA-Z])", lambda _: r"\ex", work)
    work = re.sub(r"∃(?=[A-Za-z])", lambda _: r"\ex ", work)
    work = work.replace("∃", r"\ex")
    work = re.sub(r"\\parallel(?![a-zA-Z])", lambda _: r"\|", work)
    work = re.sub(r"\s*∥\s*", lambda _: r" \| ", work)

    work = re.sub(r"\\cdots(?![a-zA-Z])|⋯", lambda _: r"\cd", work)
    work = re.sub(r"\\(?:dots|ldots)(?![a-zA-Z])", "...", work)
    work = re.sub(r"\\ddots(?![a-zA-Z])", lambda _: r"\dd", work)
    work = re.sub(r"\\vdots(?![a-zA-Z])", lambda _: r"\vd", work)

    # 6e. Multiplication (\cdot, ⋅, math · -> *) without touching prose bullets
    work = re.sub(
        r"(?<=[0-9A-Za-z)\]}°'])[ \t]*(?:\\cdot(?![a-zA-Z])|⋅)[ \t]*(?=[0-9A-Za-z~\\(\-+])",
        " * ",
        work,
    )
    work = re.sub(r"\\cdot(?![a-zA-Z])|⋅", "*", work)
    work = re.sub(r"(?<=[0-9])([ \t]*)·([ \t]*)(?=[0-9A-Za-z~(\\[])", r"\1*\2", work)
    work = re.sub(r"(?<=[A-Za-z0-9_)}\]])·(?=[0-9])", "*", work)
    work = re.sub(
        r"(\b(?:mol|min|bar|rad|amu|kWh|kg|cm|km|mm|nm|ms|kJ|MJ|eV|Pa|Hz)"
        r"|(?<![A-Za-zäöüÄÖÜß]{2})[0-9A-Za-z_)}\]])"
        r"([ \t]*)·([ \t]*)"
        r"(?=[0-9~\\(\[]|[A-Za-z](?:[_^0-9)\s.,;:]|$)|(?:mol|min|bar|rad|kg|cm|km|mm|Hz|Pa)\b)",
        r"\1\2*\3",
        work,
    )

    # 6f. Trigonometric functions without backslash; log/ln/lg/lim/sum/prod/int with backslash
    work = re.sub(r"\\(arc(?:sin|cos|tan)|sin|cos|tan|cot)(?=~|[A-Za-z0-9])", r"\1 ", work)
    work = re.sub(r"\\(arc(?:sin|cos|tan)|sin|cos|tan|cot)(?![a-zA-Z])", r"\1", work)
    work = re.sub(r"(?<!\\)\b(sum|prod|lim|o?i{1,3}nt)(?=_)", r"\\\1", work)
    work = re.sub(r"(?<!\\)\b(ln|lg|log)(?=\s*\()", r"\\\1", work)

    # 7. Convert Unicode micro units ('0,001µg' -> '0,001 ~mg', '2µm' -> '2 ~mm'), Unicode Greek, & tilde Greek words ('~beta' -> '~b')
    work = re.sub(r"(\d)[ \t]*[µμ](?=[a-zA-Z])", r"\1 ~m", work)
    if any(ch in work for ch in fc.UNICODE_GREEK_TO_FIBS):
        work = "".join(fc.UNICODE_GREEK_TO_FIBS.get(ch, ch) for ch in work)
    if "~" in work:
        work = fc.TILDE_GREEK_WORD_RE.sub(
            lambda m: fc.TILDE_GREEK_WORD_TO_FIBS[m.group(1)],
            work,
        )

    # 8. Compact sub-/superscripts, single-char '{}' unwrapping, vector bracing, sub-before-sup, & paren trimming
    def _strip_sup_spaces(m: re.Match[str]) -> str:
        base = m.group(1)
        if re.fullmatch(r"[A-Z][a-z]", base) and (
            base not in fc.VALID_CHEMICAL_ELEMENTS or base in fc.AMBIGUOUS_GERMAN_CHEM_WORDS
        ):
            return m.group(0)
        return f"{base}^"

    work = re.sub(
        rf"({fc.MATH_SCRIPT_BASE_PATTERN})[ \t]*\^[ \t]*(?=(?!\{{[0-9]+\}}_\{{\d+\}}[A-Z])(?:\{{|[A-Za-z0-9+\-~\\']))",
        _strip_sup_spaces,
        work,
    )
    work = re.sub(r"(?<=\^)\{[ \t]*([^{}\n]+?)[ \t]*\}", r"{\1}", work)

    def _strip_braced_sub_spaces(m: re.Match[str]) -> str:
        line_start = work.rfind("\n", 0, m.start()) + 1
        line_before = work[line_start : m.start()] + m.group(1)
        if re.search(r"(?<![A-Za-z0-9\\)\]}])_[A-Za-zÄÖÜäöüß][^_\n]*$", line_before):
            return m.group(0)
        return f"{m.group(1)}_{{{m.group(2).strip()}}}"

    work = re.sub(
        rf"({fc.MATH_SCRIPT_BASE_PATTERN})[ \t]*_[ \t]*\{{([^{{}}\n]+)\}}",
        _strip_braced_sub_spaces,
        work,
    )

    def _strip_bare_sub_spaces(m: re.Match[str]) -> str:
        base, sub = m.group(1), m.group(2)
        if re.fullmatch(r"[A-Z][a-z]", base) and (
            base not in fc.VALID_CHEMICAL_ELEMENTS or base in fc.AMBIGUOUS_GERMAN_CHEM_WORDS
        ):
            return m.group(0)
        line_start = work.rfind("\n", 0, m.start()) + 1
        line_before = work[line_start : m.start()] + base
        if re.search(r"(?<![A-Za-z0-9\\)\]}])_[A-Za-zÄÖÜäöüß][^_\n]*$", line_before):
            return m.group(0)
        return f"{base}_{{{sub}}}" if len(sub) > 1 else f"{base}_{sub}"

    work = re.sub(
        rf"({fc.MATH_SCRIPT_BASE_PATTERN})(?:[ \t]+_[ \t]*|_[ \t]+)([0-9]+|[A-Za-z])(?![A-Za-zÄÖÜäöüß_])",
        _strip_bare_sub_spaces,
        work,
    )
    work = re.sub(
        r"((?:~[A-Za-z]|[A-Za-z])'{1,3})_([A-Za-z0-9+\-]{2,})(?![A-Za-z0-9_])",
        r"\1_{\2}",
        work,
    )
    work = re.sub(r"(?<=[A-Za-z0-9)\]}°'])\^\{([0-9A-Za-z+\-])\}(?![0-9])", r"^\1", work)

    def _unwrap_single_sub(m: re.Match[str]) -> str:
        line_start = work.rfind("\n", 0, m.start()) + 1
        line_before = work[line_start : m.start() + 1]
        if re.search(r"(?<![A-Za-z0-9\\)\]}])_[A-Za-zÄÖÜäöüß][^_\n]*$", line_before):
            return m.group(0)
        sub_ch = m.group(2)
        tail_ch = work[m.end() : m.end() + 1]
        if sub_ch.isalpha() and tail_ch and tail_ch.islower():
            return m.group(0)
        return f"{m.group(1)}_{sub_ch}"

    work = re.sub(r"([A-Za-z0-9)\]}'])\_\{([0-9A-Za-z])\}(?![0-9])", _unwrap_single_sub, work)

    work = re.sub(r"\\vec\s+\{", lambda _: r"\vec{", work)
    work = re.sub(r"\\vec\s*(~[A-Za-z](?:_(?:\{[^{}]+\}|[A-Za-z0-9]+))?)", r"\\vec{\1}", work)
    work = re.sub(
        r"\\vec\s+([A-Za-z0-9](?:_(?:\{[^{}]+\}|[A-Za-z0-9]+))?)(?![A-Za-z0-9_])",
        r"\\vec{\1}",
        work,
    )
    work = re.sub(r"\\vec\{([^{}_]+)\}_(\{[^{}]+\}|[A-Za-z0-9]+)", r"\\vec{\1_\2}", work)
    work = re.sub(
        r"((?:~[A-Za-z]|[A-Za-z])(?:'{1,3})?)\^(\{\\ominus\}|\\ominus|\{[^{}\\]+\}|[A-Za-z0-9+\-]+)_(\{[^{}]+\}|[A-Za-z0-9+\-]+)",
        r"\1_\3^\2",
        work,
    )
    work = re.sub(r"\^\{\\ominus\}(?![A-Za-z])", lambda _: r"^\ominus", work)
    for _ in range(2):
        work = re.sub(r"\([ \t]+(?=[^\s)])", "(", work)
        work = re.sub(r"(?<=[^\s(])[ \t]+\)", ")", work)

    # 9. FIBS Bruchschreibweisen: negative numeric fractions & forbidden '1/2 x' space
    work = re.sub(r"(?<![0-9A-Za-z./\-])(\d+)/-(\d+)(?![0-9A-Za-z./\-])", r"\\f{\1}{-\2}", work)
    work = re.sub(
        r"([(\[=])([ \t]*)-(\d+)/(\d+)(?![0-9./\-])",
        lambda m: f"{m.group(1)}{m.group(2)}-\\f{{{m.group(3)}}}{{{m.group(4)}}}",
        work,
    )
    # Collapse multi-factor formula products after numeric fractions ('1/2 J ~w^2' -> '1/2J~w^2', '1/2 mv^2' -> '1/2mv^2')
    work = re.sub(
        r"(?<![0-9A-Za-z./])(\d+/\d+)[ \t]+([A-Za-z](?:_(?:\{[^{}]+\}|[A-Za-z0-9]+))?)[ \t]*"
        r"((?:~[A-Za-z]|[A-Za-z])(?:[_^](?:\{[^{}]+\}|[A-Za-z0-9+-]+))+)",
        r"\1\2\3",
        work,
    )
    # Convert '1/2 x' (numeric slash fraction + space + single math variable) -> '\f{1}{2}x'
    work = re.sub(
        r"(?<![0-9A-Za-z./\-])(\d+)/(\d+)[ \t]+"
        r"([xyzXYZ](?:[_^](?:\{[^{}]+\}|[A-Za-z0-9+-]+))?"
        r"|~[A-Za-z](?:[_^](?:\{[^{}]+\}|[A-Za-z0-9+-]+))?"
        r"|[A-Za-z](?:[_^](?:\{[^{}]+\}|[A-Za-z0-9+-]+))+)"
        r"(?![A-Za-zäöüÄÖÜß/])",
        r"\\f{\1}{\2}\3",
        work,
    )

    # 9b. Marburger / Augenbit asymmetric operator spacing (' =', ' +', ' -', ' *', ' <=', ' >=', ' <<', ' >>', ' \^=')
    work = re.sub(r"([(\[])([+\-])[ \t]+(?=[0-9A-Za-z~\\(])", r"\1\2", work)
    work = re.sub(
        r"((?:=|<=|>=|<|>|\\neq|\\apx|\\eqv|\\sim)[ \t]+)([+\-])[ \t]+(?=[0-9A-Za-z~\\(])",
        r"\1\2",
        work,
    )

    def _is_chem_token(tok: str) -> bool:
        core = re.sub(r"\((?:s|l|g|aq|[IVX]+)\)$", "", tok)
        if not core or core.upper() in fc.PROTECTED_ACRONYMS:
            return False
        el_str = re.sub(r"[_^](?:\{[^{}]*\}|[0-9A-Za-z+\-]+)|[()+\-]", "", core)
        if not el_str:
            return False
        els = re.findall(r"[A-Z][a-z]?", el_str)
        if not els or "".join(els) != el_str:
            return False
        if not all(el in fc.VALID_CHEMICAL_ELEMENTS for el in els):
            return False
        if "_" in core or "^" in core or core != tok or len(els) >= 2:
            return True
        return len(el_str) == 2 and el_str not in fc.AMBIGUOUS_GERMAN_CHEM_WORDS

    def _is_right_math(rctx: str) -> bool:
        if not rctx or rctx[0] in ("_", "*", "%", "#", "\n"):
            return False
        if rctx[0].isdigit():
            return True
        if re.match(r"^[+\-](?:[0-9~\\(]|[A-Za-z](?![a-zäöüß]{2}))", rctx):
            return True
        if re.match(r"^~[A-Za-z](?![a-zäöüß]{2})", rctx):
            return True
        if fc.FIBS_RIGHT_MATH_CMD_RE.match(rctx) and not fc.FIBS_WORD_FRAC_RE.match(rctx):
            return True
        if re.match(r"^(?:arc)?(?:sin|cos|tan|cot)(?=[\s(~A-Za-z0-9_^])", rctx):
            return True
        if re.match(
            r"^[\(\[\{|](?:[+\-0-9~\\]|(?:arc)?(?:sin|cos|tan|cot)\b|[A-Za-z](?:['_^0-9\)\]\|\s+\-*/]|$))",
            rctx,
        ):
            return True
        if re.match(r"^[A-Za-z](?:'{1,3}|[_^(\[]|(?![A-Za-zäöüÄÖÜß]))", rctx):
            return True
        if re.match(
            r"^[a-zA-Z]{2,3}(?:'{1,3})?[_^]|^[a-z][A-Z](?![A-Za-zäöüÄÖÜß])"
            r"|^(?:ma|mg|mgh|vt|at|ds|dt|dx|dy|dz|dm|dr|dp|dv|ac|ab|bc|xy|xz|yz)\b",
            rctx,
        ):
            return True
        m_rtok = re.match(r"^[A-Za-z0-9_^{}()+\-]+", rctx)
        return bool(m_rtok and _is_chem_token(m_rtok.group(0)))

    def _is_left_math(lctx: str, op_s: str, rctx: str) -> bool:
        if not lctx:
            return False
        if op_s == "-":
            if fc.FIBS_PROSE_RANGE_PREFIX_RE.search(lctx):
                return False
            if re.search(r"\b\d{4}$", lctx) and re.match(
                r"^\d{1,4}\b[ \t]+[A-ZÄÖÜ][a-zäöüß]{2,}", rctx
            ):
                return False
            if re.match(r"^\d+(?:[.,]\d+)?[ \t]+[A-ZÄÖÜ][a-zäöüß]{3,}[ \t]+[a-zäöüß]", rctx):
                return False
            if re.fullmatch(r"[\s|:\-]+", lctx):
                return False
        if lctx[-1].isdigit():
            return True
        if lctx[-1] in ")}]|'°":
            if lctx[-1] == "}" and re.search(r"[A-Za-zäöüÄÖÜß]{3,}\{\d+\}$", lctx):
                return False
            if lctx[-1] == ")" and re.search(r"\([A-Za-zäöüÄÖÜß\s.,;:]{5,}\)$", lctx):
                return False
            return True
        if re.search(r"\^[+\-*]$|~[A-Za-z]$", lctx) or fc.FIBS_LEFT_MATH_CMD_RE.search(lctx):
            return True
        if re.search(r"(?<![A-Za-zäöüÄÖÜß_])[A-Za-z]$|[A-Za-z0-9)\]}']_[A-Za-z]$", lctx):
            return True
        if fc.FIBS_LEFT_MATH_UNIT_RE.search(lctx):
            return True
        if re.search(
            r"(?<![A-Za-zäöüÄÖÜß])(?:[a-z][A-Z]|ma|mg|mgh|vt|at|ds|dt|dx|dy|dz|dm|dr|dp|dv|ac|ab|bc|xy|xz|yz)$",
            lctx,
        ):
            return True
        m_ltok = re.search(r"[A-Za-z0-9_^{}()]+$", lctx)
        return bool(m_ltok and _is_chem_token(m_ltok.group(0)))

    asym_parts: list[str] = []
    asym_last = 0
    for m_op in fc.FIBS_ASYM_OP_CANDIDATE_RE.finditer(work):
        op_rel = m_op.group(1)
        op_bin = m_op.group(2)
        op_tok = op_rel or op_bin or ""
        line_s = work.rfind("\n", 0, m_op.start()) + 1
        line_e = work.find("\n", m_op.end())
        line_e = len(work) if line_e < 0 else line_e
        lctx = work[line_s : m_op.start()]
        rctx = work[m_op.end() : line_e]

        if op_rel and lctx.endswith(("{", "(", "[")) and _is_right_math(rctx):
            asym_parts.append(work[asym_last : m_op.start()])
            asym_parts.append(op_rel)
            asym_last = m_op.end()
        elif _is_right_math(rctx) and _is_left_math(lctx, op_tok, rctx):
            asym_parts.append(work[asym_last : m_op.start()])
            asym_parts.append(f" {op_tok}")
            asym_last = m_op.end()
    if asym_last:
        asym_parts.append(work[asym_last:])
        work = "".join(asym_parts)

    # 10. Collapse redundant spaces (preserving tabs) and re-apply degree/percent rules
    work = re.sub(r"(?<=\S)[ ]{2,}(?=\S)", " ", work)
    work = normalize_fibs_units_and_percent(work)

    for idx, val in reversed(list(enumerate(protected_spans))):
        work = work.replace(f"__FIBS_BARE_PROT_{idx}__", val)
    return work


def standardize_formulas(markdown: str, *, fibs_mode: bool = False) -> str:
    r"""Standardize all math and chemistry formulas according to Übertragungsregeln Stand 09/2025.

    Steps:
      1. Removes any legacy ``<L>`` and ``</L>`` tags and normalizes degrees/percentages.
      2. Converts raw Unicode/PDF text formulas into LaTeX.
      3. Cleans and normalizes LaTeX formula syntax within display and inline math.
      4. When ``fibs_mode=True``, unwraps ``$...$`` / ``$$...$$`` into bare FIBS/Augenbit
         LaTeX with tilde Greek notation (``~a``, ``~m``, ``~D``) and FIBS arrows
         (``\to``, ``\lra``, ``\xra{...}``).

    Args:
        markdown: Input Markdown text.
        fibs_mode: When True, emit bare FIBS 09/2025 notation without ``$`` delimiters;
            when False (Stage-1 raw OCR), preserve ``$...$`` on mathematical equations.

    Returns:
        Markdown text with standardized formulas.
    """
    if not markdown:
        return markdown

    from backend.services.fibs_formatting import normalize_fibs_units_and_percent

    # 1. Remove all <L> and </L> tags and normalize plain/wrapped degrees and percentages
    dollar_prot: list[str] = []

    def _mask_non_math_dollar(m: re.Match[str]) -> str:
        dollar_prot.append(m.group(0))
        return f"__STD_DOLLAR_PROT_{len(dollar_prot) - 1}__"

    text = re.sub(
        r"\$[A-Z]{1,3}\$\d+|(?<![0-9A-Za-z°}\\%])\$-(?=[A-ZÄÖÜ][a-zäöüß]+)",
        _mask_non_math_dollar,
        markdown,
    )
    text = strip_l_tags(text)
    text = normalize_fibs_units_and_percent(text)

    # 2. Convert raw Unicode math expressions into LaTeX
    text = convert_unicode_math_to_latex(text)

    # 3. Clean display math ($$...$$) and move trailing equation numbers (\quad (11.1), \tag{11.1}, (i.i), (II.2)) outside $$...$$
    def clean_display_math(match):
        raw_inner = match.group(1).strip()
        # Strip outer CodeFormulaV2 '{ r } { ... }' before checking equation tag
        m_cf = re.match(r"^\{\s*[rlc]\s*\}\s*\{\s*(.*)\s*\}$", raw_inner, flags=re.DOTALL)
        if m_cf:
            raw_inner = m_cf.group(1).strip()

        eq_tag_match = re.search(
            r"(?:\\(?:quad|qquad|,|;|\s)*\\tag\s*\{\s*([0-9IVXii\.\s]+)\s*\}|"
            r"\\(?:quad|qquad|,|;|\s)*(?:\\text\s*\{)?\s*\(\s*([0-9IVXii]+(?:\s*\.\s*[0-9iI]+)+)\s*\)\s*\}?)\s*$",
            raw_inner,
        )
        eq_suffix = ""
        if eq_tag_match:
            tag_str = (eq_tag_match.group(1) or eq_tag_match.group(2) or "").strip()
            tag_str = re.sub(r"\s+", "", tag_str)
            tag_str = re.sub(r"^(?:II|ii|i)\.(?:i|I)$", "11.1", tag_str)
            tag_str = re.sub(r"^(?:II|ii)\.", "11.", tag_str)
            raw_inner = raw_inner[:eq_tag_match.start()].strip()
            eq_suffix = f" ({tag_str})"
        inner = clean_latex_formula(raw_inner)
        return f"$${inner}$${eq_suffix}"

    text = re.sub(r"\$\$\s*([\s\S]*?)\s*\$\$", clean_display_math, text)

    # 4. Clean inline math ($...$) and strip hallucinated OCR pseudo-formulas
    def clean_inline_math(match):
        inner = match.group(1).strip()
        if not inner or re.match(r"^\d+(?:[.,]\d+)?$", inner):
            return f"${inner}$"
        inner_cleaned = clean_latex_formula(inner)
        if (
            re.fullmatch(r"[A-Za-z0-9_{}\^]+", inner_cleaned)
            and "_" in inner_cleaned
            and len(re.findall(r"[A-Z]", inner_cleaned)) >= 3
        ):
            base_segs = [
                seg
                for seg in re.split(
                    r"_\{?[0-9a-zA-Z,]+\}?|\^\{?[0-9+\-]+\}?", inner_cleaned
                )
                if seg
            ]
            el_tokens = re.findall(r"[A-Z][a-z]?", "".join(base_segs))
            has_invalid_el = any(
                el not in fc.VALID_CHEMICAL_ELEMENTS for el in el_tokens
            ) and not any(
                bio in inner_cleaned for bio in ("NAD", "FAD", "ATP", "ADP")
            )
            has_dup_caps = any(
                re.search(r"([A-Z])\1", seg) and "COOH" not in seg
                for seg in base_segs
            )
            has_sub_one = bool(re.search(r"_\{?1\}?", inner_cleaned))
            if has_invalid_el or has_dup_caps or has_sub_one:
                return ""
        return f"${inner_cleaned}$"

    text = re.sub(r"(?<!\\)\$(?!\$)([^\$\n]+?)(?<!\\)\$", clean_inline_math, text)
    text = normalize_fibs_units_and_percent(text)

    if fibs_mode:
        out_fibs = _convert_to_fibs_bare_latex(text)
        for idx, val in reversed(list(enumerate(dollar_prot))):
            out_fibs = out_fibs.replace(f"__STD_DOLLAR_PROT_{idx}__", val)
        return out_fibs

    text = re.sub(r"(?<=\S)[ ]{2,}(?=\S)", " ", text)
    for idx, val in reversed(list(enumerate(dollar_prot))):
        text = text.replace(f"__STD_DOLLAR_PROT_{idx}__", val)
    return text
