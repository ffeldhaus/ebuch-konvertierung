"""Constants, regular expressions, and lookup tables for FIBS 09/2025 E-Buch conversion."""

from __future__ import annotations

import os
import re
from typing import Final

# ---------------------------------------------------------------------------
# Image & <Bild> Formatting Constants
# ---------------------------------------------------------------------------

DEFAULT_IMAGE_TYPE: Final[str] = "Abbildung"
MISSING_DESCRIPTION: Final[str] = "Abbildung ohne Beschreibung"
IMAGE_POSITION_MARKER: Final[str] = "[HIER STEHT DAS BILD]"
OTHER_IMAGE_PLACEHOLDER: Final[str] = "[Bild]"
VLM_CONTEXT_MAX_CHARS: Final[int] = 4000

SENTENCE_STARTERS: Final[frozenset[str]] = frozenset({
    "ein", "eine", "einer", "der", "die", "das", "den", "dem", "es", "hier", "zu", "im", "in",
    "auf", "man", "sie", "er", "links", "rechts", "oben", "unten", "a", "an", "the",
})

PAGE_MARKER_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\(\(\d+(?:\s*[-–]\s*\d+)?\)\)[^\n]*$",
    re.MULTILINE,
)
PAGE_MARKER_ONLY_RE: Final[re.Pattern[str]] = re.compile(
    r"\(\(\d+(?:\s*[-–]\s*\d+)?\)\)(?:\s*/\s*\(\(\d+\)\))?"
)
HEADING_LINE_RE: Final[re.Pattern[str]] = re.compile(r"^[ \t]*#{1,6}\s+\S", re.MULTILINE)
IMAGE_BLOCK_RE: Final[re.Pattern[str]] = re.compile(r"<Bild>(.*?)</Bild>", re.DOTALL)
BILD_TAG_DELIM_RE: Final[re.Pattern[str]] = re.compile(r"</?Bild>")
MD_IMAGE_RE: Final[re.Pattern[str]] = re.compile(r"!\[[^\]]*\]\([^)]*\)")
MULTI_NEWLINE_RE: Final[re.Pattern[str]] = re.compile(r"\n{3,}")
BILDART_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[\wÄÖÜäöüß][\wÄÖÜäöüß ./\-–]*")
BILDART_CLEAN_RE: Final[re.Pattern[str]] = re.compile(r"[*_#`]")
BILDART_HEAD_RE: Final[re.Pattern[str]] = re.compile(r"^([^:\n]+):[ \t]*(.*)$")
DESC_BULLET_LINE_RE: Final[re.Pattern[str]] = re.compile(r"^([ \t]*)[-*•–+][ \t]+(\S.*)$")
BOLD_SPAN_RE: Final[re.Pattern[str]] = re.compile(r"\*\*(.+?)\*\*")
DESC_LABEL_RE: Final[re.Pattern[str]] = re.compile(r"^Beschreibung(?: mit Bildtext)?:")
VLM_DESC_HEADER_RE: Final[re.Pattern[str]] = re.compile(r"(?im)^[ \t]*BESCHREIBUNG[ \t]*:[ \t]*")
VLM_BILDART_HEADER_RE: Final[re.Pattern[str]] = re.compile(r"(?im)^[ \t]*BILDART[ \t]*:")
VLM_FIELD_RE_MAP: Final[dict[str, re.Pattern[str]]] = {
    name: re.compile(rf"(?im)^[ \t]*{name}[ \t]*:[ \t]*(.+?)[ \t]*$")
    for name in ("BILDART", "TEXT_IM_BILD", "DEKORATIV")
}
CAPTION_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:Abb(?:ildung)?\.?|Bild|Grafik|Fig(?:ur|ure|\.)?)\s*\d",
    re.IGNORECASE,
)
CAPTION_WORD_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:#{1,6}\s+)?[_*%#\s]*(?:Abb(?:ildung)?|Bild|Grafik|Foto|Fig(?:ur|ure)?|Tab(?:elle)?|Material|Quelle)\b\.?\s*\d*",
    re.IGNORECASE,
)
CAPTION_LABEL_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:#{1,6}\s+)?[_*%#\s]*[A-Z]{1,2}\d{1,2}[a-z]?\b"
)
GENERIC_ALT_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:image|img|bild|figure|fig|picture|abbildung|grafik|foto)?[\s_\-]*\d*$",
    re.IGNORECASE,
)
IMAGE_EXT_RE: Final[re.Pattern[str]] = re.compile(r"\.(?:png|jpe?g|gif)$", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Unicode Sub-/Superscript & Versalien Constants
# ---------------------------------------------------------------------------

SUB_MAP: Final[dict[int, int]] = str.maketrans("₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎", "0123456789+-=()")
SUP_MAP: Final[dict[int, int]] = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ", "0123456789+-=()n")
SUB_RE: Final[re.Pattern[str]] = re.compile(r"[₀-₉₊₋₌₍₎]+")
SUP_RE: Final[re.Pattern[str]] = re.compile(r"[⁰¹²³⁴-⁹⁺⁻⁼⁽⁾ⁿ]+")
TRAILING_WORD_RE: Final[re.Pattern[str]] = re.compile(r"([A-Za-zÄÖÜäöüß]+)$")
TRAILING_PUNCT_RE: Final[re.Pattern[str]] = re.compile(r"[.,;:!?)\"']$")

SUP_TO_DIGIT: Final[dict[str, str]] = {
    "¹": "1",
    "²": "2",
    "³": "3",
    "⁴": "4",
    "⁵": "5",
    "⁶": "6",
    "⁷": "7",
    "⁸": "8",
    "⁹": "9",
}

PROTECTED_ALL_CAPS_RE: Final[re.Pattern[str]] = re.compile(
    r"\$\$.*?\$\$|\$[^$\n]+\$|<Bild>.*?</Bild>|<Rahmen>\s*\n_[^\n]+_|`[^`\n]*`|https?://\S+|\[[^\]\n]*\]",
    re.DOTALL,
)
CAPS_TOKEN_PATTERN: Final[str] = r"[A-ZÄÖÜ]{2,}(?:-[A-ZÄÖÜ]{2,})*"
CAPS_RUN_RE: Final[re.Pattern[str]] = re.compile(
    rf"(?<![\wÄÖÜäöüß])(_?)({CAPS_TOKEN_PATTERN}(?:[ ]+{CAPS_TOKEN_PATTERN})*)(_?)(?![\wÄÖÜäöüß])"
)
FOUR_CAPS_RE: Final[re.Pattern[str]] = re.compile(r"[A-ZÄÖÜ]{4,}")
WORD_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-zÄÖÜäöüß]+")
LINE_DECORATION_RE: Final[re.Pattern[str]] = re.compile(r"[\s_*>\-\t]")
SENTENCE_END_PREFIX_RE: Final[re.Pattern[str]] = re.compile(r"[.!?:]\s*$")

# ---------------------------------------------------------------------------
# Task Difficulty Symbol Mapping (FIBS Section 8.1)
# ---------------------------------------------------------------------------

DIFFICULTY_SYMBOL_MAP: Final[dict[str, str]] = {
    "□": "[leicht]",
    "◩": "[mittel]",
    "■": "[schwer]",
    "★★★": "[schwer]",
    "★★": "[mittel]",
    "★": "[leicht]",
    "◇": "[leicht]",
    "◈": "[mittel]",
    "◆": "[schwer]",
}

# ---------------------------------------------------------------------------
# LLM Token Budget & Page-Chunking Constants
# ---------------------------------------------------------------------------

GEMMA_REQUEST_TOKEN_BUDGET: Final[int] = int(os.environ.get("GEMMA_REQUEST_TOKEN_BUDGET", "11000"))
GEMMA_MAX_OUTPUT_TOKENS: Final[int] = 8192
CHARS_PER_TOKEN: Final[float] = 3.0
OUTPUT_TOKEN_FACTOR: Final[float] = 1.3
OUTPUT_TOKEN_MARGIN: Final[int] = 256
CONTEXT_MAX_TOKENS: Final[int] = 1000
MAX_PAGES_PER_CHUNK: Final[int] = 2
FRAME_TOKENS: Final[int] = 200
IDLE_TIMEOUT_SECONDS: Final[float] = 60.0

PAGE_MARKER_START_RE: Final[re.Pattern[str]] = re.compile(r"^\(\((\d+)\)\)", re.MULTILINE)
BLOCK_TAGS: Final[tuple[tuple[str, str], ...]] = (
    ("<Tabelle", "</Tabelle>"),
    ("<Bild>", "</Bild>"),
    ("<Rahmen", "</Rahmen>"),
    ("<Anmerkung>", "</Anmerkung>"),
    ("<Lückentext", "</Lückentext>"),
    ("<Zeilennummerierung>", "</Zeilennummerierung>"),
    ("<table", "</table>"),  # Intermediate HTML table from raw OCR before FIBS <Tabelle> conversion
)

# ---------------------------------------------------------------------------
# STEM & Chemistry Formula Constants
# ---------------------------------------------------------------------------

UNICODE_GREEK_TO_LATEX: Final[dict[str, str]] = {
    "𝛼": r"\alpha", "α": r"\alpha",
    "𝛽": r"\beta", "β": r"\beta",
    "𝛾": r"\gamma", "γ": r"\gamma",
    "𝛿": r"\delta", "δ": r"\delta",
    "𝛥": r"\Delta", "Δ": r"\Delta",
    "𝜀": r"\epsilon", "𝜖": r"\epsilon", "ε": r"\epsilon",
    "𝜃": r"\theta", "θ": r"\theta",
    "𝜆": r"\lambda", "λ": r"\lambda",
    "𝜇": r"\mu", "μ": r"\mu",
    "𝜋": r"\pi", "π": r"\pi",
    "𝜌": r"\rho", "ρ": r"\rho",
    "𝜎": r"\sigma", "σ": r"\sigma",
    "𝜏": r"\tau", "τ": r"\tau",
    "𝜑": r"\phi", "𝜙": r"\phi", "φ": r"\phi",
    "𝜔": r"\omega", "ω": r"\omega",
    "𝛺": r"\Omega", "Ω": r"\Omega",
}

SI_UNIT_PATTERN: Final[str] = (
    r"(?:km/s|m/s(?:\^2|²)?|cm/s|m/s|Hz|kHz|MHz|GHz|eV|keV|MeV|J\s*[·⋅\*]\s*s|mol/L|L/mol)"
)

VALID_CHEMICAL_ELEMENTS: Final[frozenset[str]] = frozenset({
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca",
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr",
    "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn",
    "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
    "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
    "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th",
    "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm",
    "Md", "No", "Lr", "Rf", "Db", "Sg", "Bh", "Hs", "Mt", "Ds",
    "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
})

# ---------------------------------------------------------------------------
# DOCX Export Constants (FIBS 09/2025 Section 2.1.1)
# ---------------------------------------------------------------------------

FIBS_FONT_NAME: Final[str] = "Verdana"
FIBS_BODY_FONT_SIZE_PT: Final[float] = 14.0
FIBS_LINE_SPACING: Final[float] = 1.5
FIBS_MARGIN_CM: Final[float] = 2.0
FIBS_HEADING_SPACE_AFTER_PT: Final[float] = 6.0
FIBS_TABLE_TOP_MARGIN_DXA: Final[str] = "142"
FIBS_HEADING_SIZES_PT: Final[dict[int, float]] = {
    1: 20.0,
    2: 18.0,
    3: 16.0,
    4: 14.0,
    5: 14.0,
}
DOCX_LIST_MARKER_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:[-*+•]\s|[-*+]\t|\d+[.)]\s|[a-zA-Z][.)]\t|\[[ xX]?\])"
)

# ---------------------------------------------------------------------------
# Feedback Analysis Constants
# ---------------------------------------------------------------------------

TRANSFER_EXTENSIONS: Final[frozenset[str]] = frozenset({".md", ".txt", ".docx"})
FEEDBACK_EXTENSIONS: Final[frozenset[str]] = frozenset({".md", ".txt", ".docx", ".pdf"})
MAX_VERBATIM_WORDS: Final[int] = 12
SKIPPED_ANSWER: Final[str] = "– (übersprungen, weiterhin offen)"
MAX_ANSWER_CHARS: Final[int] = 2000

CATEGORY_LABELS: Final[dict[str, str]] = {
    "heading": "Überschriften",
    "page_marker": "Seitenzahlen ((n))",
    "image": "Bilder / Bildbeschreibungen",
    "list": "Listen",
    "math": "Formeln / Mathematik",
    "table": "Tabellen",
    "frame": "Rahmen / Kästen",
    "annotation": "Anmerkungen",
    "footnote": "Fußnoten",
    "emphasis": "Hervorhebungen",
    "text": "Fließtext",
    "whitespace": "Leerzeilen / Abstände",
}
