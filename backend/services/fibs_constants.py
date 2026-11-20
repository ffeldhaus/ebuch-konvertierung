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

ROMAN_NUMERAL_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?=[IVXLCDMivxlcdm]+$)M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$",
    re.IGNORECASE,
)
ROMAN_VALUES: Final[dict[str, int]] = {
    "I": 1,
    "V": 5,
    "X": 10,
    "L": 50,
    "C": 100,
    "D": 500,
    "M": 1000,
}

PAGE_MARKER_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\(\((?:\d+|[IVXLCDMivxlcdm]+)(?:\s*[-–]\s*(?:\d+|[IVXLCDMivxlcdm]+))?\)\)[^\n]*$",
    re.MULTILINE,
)
PAGE_MARKER_ONLY_RE: Final[re.Pattern[str]] = re.compile(
    r"\(\((?:\d+|[IVXLCDMivxlcdm]+)(?:\s*[-–]\s*(?:\d+|[IVXLCDMivxlcdm]+))?\)\)(?:\s*/\s*\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\))?"
)
HEADING_LINE_RE: Final[re.Pattern[str]] = re.compile(r"^[ \t]*#{1,6}\s+\S", re.MULTILINE)
IMAGE_BLOCK_RE: Final[re.Pattern[str]] = re.compile(r"<Bild>(.*?)</Bild>", re.DOTALL)
BILD_FULL_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r"<Bild\b[^>]*>[\s\S]*?</Bild>", re.IGNORECASE
)
BILD_REF_TAG_RE: Final[re.Pattern[str]] = re.compile(
    r"<Bild-Ref\b(?:[^>]*?\bid=[\"']?|\s+)(BILD_\d+)(?:[\"']?[^>]*?)?/?>([ \t]*</Bild-Ref[ \t]*>)?",
    re.IGNORECASE,
)
BILD_OR_REF_RE: Final[re.Pattern[str]] = re.compile(
    r"<Bild\b[^>]*>[\s\S]*?</Bild>|<Bild-Ref\b[^>]*?/?>([ \t]*</Bild-Ref[ \t]*>)?",
    re.IGNORECASE,
)
BILD_TAG_DELIM_RE: Final[re.Pattern[str]] = re.compile(r"</?Bild>")
SPLIT_DECIMAL_HEADING_RE: Final[re.Pattern[str]] = re.compile(
    r"^(#{1,4}\s+)([A-ZÄÖÜ][^\n\d#]{2,45}?)\s+([1-9]\d?\s*\.\s*[1-9]\d?(?:\s*\.)?)\s+([A-Za-zÄÖÜäöüß]\S.*)$"
)
SPLIT_HEADING_EXCLUDED_PREFIX_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:Abb(?:ildung)?|Bild|Grafik|Fig(?:ur|ure)?|Tab(?:elle)?|Table|Kapitel|Chapter|"
    r"Abschnitt|Section|Teil|Part|Lektion|Band|Aufgaben?|Übung(?:en)?|Beispiele?|Examples?|"
    r"Versuche?|Experimente?|Material(?:ien)?|Quellen?|Exkurse?|Methoden?|Schema|Karte|"
    r"Diagramm|Foto)\b",
    re.IGNORECASE,
)
POINT_DIFFICULTY_TAG_RE: Final[re.Pattern[str]] = re.compile(
    r"\[([123])\s*Punkte?\]", re.IGNORECASE
)
H5_TASK_NUMBER_HEADING_RE: Final[re.Pattern[str]] = re.compile(
    r"^#####[ \t]+(?!Aufgaben\b)([A-LN-Z]?\d+(?:\.\d+)*[a-z]?)[ \t]*$"
)
STANDALONE_DIFFICULTY_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:[○◐●□◩■◇◈◆★☆]+[ \t]*)?\[(?:einfach|leicht|mittel|schwierig|schwer)\](?:[ \t]+\[[^\]]+\])*$",
    re.IGNORECASE,
)
TRAILING_DIFFICULTY_TAG_RE: Final[re.Pattern[str]] = re.compile(
    r"[ \t]+(\[(?:einfach|leicht|mittel|schwierig|schwer)\])([.,;:!?])?[ \t]*$",
    re.IGNORECASE,
)
PREPRESS_MARK_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]+)?[^\n]*\b(?:Abschnittsmark\w*|Schnittmarken?|"
    r"Passkreuze?|Falzmarken?|Druckkontrollstreifen|Farbkontrollstreifen)\b[^\n]*$",
    re.IGNORECASE,
)
INDESIGN_FOOTER_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:^[ \t]*---[ \t]*\n+)?"
    r"(?:^[ \t]*(?:[-*•][ \t]+)?(?:\*\*|_)*(?:Page[ \t]+Numbers?|Date|Time):?(?:\*\*|_)*:?[ \t]*"
    r"(?:\d{1,4}(?:[–-]\d{1,4})?|\d{2}\.\d{2}\.\d{4}|\d{2}:\d{2}(?::\d{2})?(?:[ \t]*Uhr)?)[ \t]*\n+)*"
    r"^[ \t]*(?:[-*•][ \t]+)?(?:"
    r"(?:(?:\*\*|_)*(?:Page[ \t]+Numbers?|Date|Time):?(?:\*\*|_)*:?[ \t]*[^|\n]+[ \t]*\|?[ \t]*)*"
    r"(?:\*\*|_)*Document[ \t]+ID:?(?:\*\*|_)*:?[ \t]*[^\n]*?\.ind[bd](?![A-Za-z0-9])[^\n]*"
    r"|[^\s#<>]+\.ind[bd](?![A-Za-z0-9])"
    r"(?:[ \t]+(?:\d{1,4}(?:[–-]\d{1,4})?|\d{2}\.\d{2}\.\d{4}|\d{2}:\d{2}(?::\d{2})?(?:[ \t]*Uhr)?|©[^\n]*))*[ \t]*"
    r")$"
    r"(?:\n+[ \t]*(?:[-*•][ \t]+)?(?:\*\*|_)*(?:Page[ \t]+Numbers?|Date|Time):?(?:\*\*|_)*:?[ \t]*"
    r"(?:\d{1,4}(?:[–-]\d{1,4})?|\d{2}\.\d{2}\.\d{4}|\d{2}:\d{2}(?::\d{2})?(?:[ \t]*Uhr)?)[ \t]*)*",
    re.IGNORECASE | re.MULTILINE,
)
DOT_BULLET_RUN_RE: Final[re.Pattern[str]] = re.compile(r"[•●○◦∙⋅]{2,3}")
ECHO_WORD_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[a-zäöüß0-9]{2,}")
DIDACTIC_RUBRIC_BANNER_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:Methode|Basiskonzepte?|Exkurs|Praktikum|Streifzug|Im\s+Blickpunkt|Überblick)"
    r"(?:\s*:\s*\S.*|\s*[:•·\-–]?\s+[A-ZÄÖÜ][^\n.]{2,90})?$",
    re.IGNORECASE,
)
STANDALONE_RUBRIC_LABEL_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:Methode|Basiskonzepte?|Exkurs|Praktikum|Streifzug|Im\s+Blickpunkt|Überblick):?$",
    re.IGNORECASE,
)
FOLIO_EDGE_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"^\d+\s+|\s+\d+$")
VLM_GENERIC_BILDART_ONLY_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:\d+\s+)?(?:Mikroskopische\s+Aufnahme(?:n)?|Lichtmikroskopische\s+Aufnahme(?:n)?|"
    r"Elektronenmikroskopische\s+Aufnahme(?:n)?|Foto(?:s|grafie)?|Foto\s+mit\s+Text|"
    r"Zeichnung(?:en)?|Schematische\s+Darstellung|Schema|Strukturdiagramm|Flussdiagramm|"
    r"Balkendiagramm|Säulendiagramm|Kreisdiagramm|Liniendiagramm|Diagramm(?:e)?|"
    r"Abbildung(?:en)?|Schaubild|Grafik(?:en)?|Illustration|Modell|Karte)\.?$",
    re.IGNORECASE,
)
VLM_DESC_BOILERPLATE_HEADING_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:Eine?|Zwei|Drei|Vier|Mehrere|Links|Rechts|Oben|Unten|"
    r"Das\s+(?:Diagramm|Foto|Bild|Schema|Schaubild|Modell)|"
    r"Die\s+(?:Abbildung|Zeichnung|Grafik|Darstellung|Aufnahme))\s+.*?"
    r"\b(?:zeigt|zeigen|dargestellt|abgebildet|zu\s+sehen|veranschaulicht|illustriert)\b",
    re.IGNORECASE,
)
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
    r"\$\$.*?\$\$|\$[^$\n]+\$|<Bild>.*?</Bild>|<Rahmen>\s*\n_[^\n]+_|`[^`\n]*`|https?://\S+|\[[^\]\n]*\]|\\[a-zA-Z]+(?:\{(?:[^{}\n]|\{[^{}\n]*\})*\})*",
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

PROTECTED_ACRONYMS: Final[frozenset[str]] = frozenset({
    "ADAC", "ADHS", "ADP", "AFB", "AIDS", "AMP", "ANSI", "ASCII", "ASEAN", "ASIC", "ATP",
    "BIOS", "BIP", "BNE", "BRD", "CAMP", "CERN", "CGMP", "CHOH", "CMOS", "CMYK", "CONH",
    "COOC", "COOH", "COVID", "CPU", "CRISPR", "DAX", "DDR", "DIN", "DIV", "DLR", "DNA",
    "DOI", "DRAM", "DSGVO", "EDTA", "EEG", "EEPROM", "EFTA", "EKG", "ELISA", "EMG", "EPROM",
    "EPSP", "ESA", "EWU", "FAD", "FADH", "FIBS", "FIFO", "FPGA", "GABA", "GATT", "GDP",
    "GDPR", "GHS", "GPU", "GTP", "HDMI", "HEPES", "HTML", "HTTP", "HTTPS", "IBAN", "IEEE",
    "IPCC", "IPSP", "ISBN", "ISO", "ISSN", "IUPAC", "JAWS", "JPEG", "JSON", "LAN", "LASER",
    "LIDAR", "LIFO", "LKW", "MAK", "MASER", "MAX", "MDAX", "MERS", "MIDI", "MIN", "MMS",
    "MOD", "MPEG", "MRNA", "MRSA", "MRT", "NAD", "NADH", "NADP", "NADPH", "NAFTA", "NAND",
    "NASA", "NATO", "NIAID", "NOR", "NPU", "NVDA", "NVME", "OECD", "OPEC", "OSZE", "PAGE",
    "PCR", "PIN", "PKW", "PNS", "RADAR", "RAID", "RAM", "RGBA", "RKI", "RNA", "ROM",
    "RRNA", "RUBISCO", "SARS", "SATA", "SCUBA", "SDS", "SEPA", "SIRNA", "SONAR", "SPNV",
    "SRAM", "STIKO", "STP", "SWIFT", "TAN", "TIFF", "TOML", "TRGS", "TRIPS", "TRIS", "TRNA",
    "TÜV", "UDSSR", "UEFI", "UNHCR", "UNESCO", "UNICEF", "UNO", "URL", "USA", "USB",
    "USMCA", "UTF", "VDE", "VLAN", "VNS", "WAN", "WEBP", "WHO", "WLAN", "XETRA", "XML",
    "XNOR", "XOR", "YAML", "ZDF", "ZNS", "ÖPNV",
})

VERSALIEN_CONNECTORS: Final[frozenset[str]] = frozenset({
    "und", "oder", "der", "die", "das", "des", "dem", "den", "ein", "eine", "einer",
    "einem", "einen", "im", "in", "am", "an", "auf", "aus", "bei", "mit", "von", "vom",
    "zum", "zur", "zu", "für", "über", "unter", "vor", "nach", "van", "de", "la",
    "of", "the", "and", "for", "to",
})

NON_NAME_CAPITALIZED_WORDS: Final[frozenset[str]] = frozenset({
    "der", "die", "das", "des", "dem", "den", "ein", "eine", "einer", "einem", "einen",
    "eines", "kein", "keine", "dieser", "diese", "dieses", "jeder", "jede", "jedes",
    "alle", "viele", "einige", "mehrere", "beide", "manche", "solche", "welche",
    "im", "in", "am", "an", "auf", "aus", "bei", "mit", "nach", "seit", "von", "vom",
    "vor", "zu", "zum", "zur", "für", "über", "unter", "durch", "gegen", "ohne", "um",
    "zwischen", "während", "wegen", "trotz", "als", "wie", "wenn", "weil", "dass", "ob",
    "oder", "und", "aber", "doch", "denn", "sondern", "auch", "nur", "noch", "schon",
    "erst", "sehr", "hier", "dort", "heute", "immer", "nicht", "norm", "typ", "teil",
    "abbildung", "tabelle", "kapitel", "abschnitt", "aufgabe", "übung", "beispiel",
    "the", "this", "that", "these", "those", "from", "with", "into", "when", "where",
    "while", "each", "every", "many", "most", "some",
})

PERSON_ROLE_PREFIXES: Final[frozenset[str]] = frozenset({
    "herr", "frau", "dr", "prof", "professor", "professorin", "sir", "lord", "lady",
    "graf", "fürst", "herzog", "könig", "königin", "kaiser", "kaiserin", "papst",
    "philosoph", "physiker", "chemiker", "biologe", "mathematiker", "forscher",
    "forscherin", "arzt", "ärztin", "autor", "autorin", "dichter", "entdecker",
    "general", "präsident", "kanzler", "minister", "seefahrer", "astronom",
})

PERSON_PREFIX_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:(?:Dr|Prof|Dipl|Ing|Med)\.\s+|[A-ZÄÖÜ]\.\s+|"
    r"([A-ZÄÖÜ][a-zäöüß]{1,20})(?:\s+[A-ZÄÖÜ]\.)?(?:\s+(?:von|van|de|del|della|da|di|du|la|le|zu))?\s+)$"
)

# German conjunctions and prepositions that follow a suspended hyphen (Ergänzungsstrich)
SUSPENDED_HYPHEN_FOLLOWERS: Final[frozenset[str]] = frozenset({
    "und",
    "oder",
    "bzw",
    "sowie",
    "bis",
    "zu",
    "zum",
    "zur",
    "wie",
    "als",
    "gegen",
    "für",
    "mit",
    "ohne",
    "von",
    "vom",
    "in",
    "im",
    "an",
    "am",
    "auf",
    "aus",
    "bei",
    "nach",
    "über",
    "unter",
    "vor",
    "zwischen",
    "statt",
})
SUSPENDED_HYPHEN_LOOKAHEAD: Final[str] = "|".join(
    rf"{w}\b" for w in sorted(SUSPENDED_HYPHEN_FOLLOWERS, key=len, reverse=True)
)
INLINE_HYPHEN_SPACE_RE: Final[re.Pattern[str]] = re.compile(
    rf"\b([a-zA-ZäöüÄÖÜß]{{2,}})-\s+(?!{SUSPENDED_HYPHEN_LOOKAHEAD})([a-zäöüß][a-zA-ZäöüÄÖÜß]{{2,}})\b"
)

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

GEMMA_REQUEST_TOKEN_BUDGET: Final[int] = int(os.environ.get("GEMMA_REQUEST_TOKEN_BUDGET", "16000"))
GEMMA_MAX_OUTPUT_TOKENS: Final[int] = 8192
CHARS_PER_TOKEN: Final[float] = 3.0
OUTPUT_TOKEN_FACTOR: Final[float] = 1.3
OUTPUT_TOKEN_MARGIN: Final[int] = 256
CONTEXT_MAX_TOKENS: Final[int] = 1000
MAX_PAGES_PER_CHUNK: Final[int] = 2
FRAME_TOKENS: Final[int] = 200
IDLE_TIMEOUT_SECONDS: Final[float] = 60.0

PAGE_MARKER_START_RE: Final[re.Pattern[str]] = re.compile(
    r"^\(\(((?:\d+|[IVXLCDMivxlcdm]+))\)\)", re.MULTILINE
)
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

UNICODE_GREEK_TO_FIBS: Final[dict[str, str]] = {
    "𝛼": "~a", "α": "~a",
    "𝛽": "~b", "β": "~b",
    "𝛾": "~g", "γ": "~g", "Γ": "~G",
    "𝛿": "~d", "δ": "~d",
    "𝛥": "~D", "Δ": "~D", "∆": "~D",
    "𝜀": "~e", "𝜖": "~e", "ε": "~e", "ϵ": "~e",
    "ζ": "~z",
    "η": "~h",
    "𝜃": "~q", "θ": "~q", "ϑ": "~q", "Θ": "~Q",
    "ι": "~i",
    "κ": "~k",
    "𝜆": "~l", "λ": "~l", "Λ": "~L",
    "𝜇": "~m", "μ": "~m", "µ": "~m",
    "ν": "~n",
    "ξ": "~x", "Ξ": "~X",
    "𝜋": "~p", "π": "~p", "Π": "~P",
    "𝜌": "~r", "ρ": "~r",
    "𝜎": "~s", "σ": "~s", "ς": "~s", "Σ": "~S",
    "𝜏": "~t", "τ": "~t",
    "υ": "~u", "Υ": "~U",
    "𝜑": "~f", "𝜙": "~f", "φ": "~f", "ϕ": "~f", "Φ": "~F",
    "χ": "~c",
    "ψ": "~y", "Ψ": "~Y",
    "𝜔": "~w", "ω": "~w",
    "𝛺": "~W", "Ω": "~W", "Ω": "~W",
}

LATEX_GREEK_TO_FIBS: Final[dict[str, str]] = {
    r"\alpha": "~a",
    r"\beta": "~b",
    r"\gamma": "~g",
    r"\Gamma": "~G",
    r"\delta": "~d",
    r"\Delta": "~D",
    r"\epsilon": "~e",
    r"\varepsilon": "~e",
    r"\zeta": "~z",
    r"\eta": "~h",
    r"\theta": "~q",
    r"\vartheta": "~q",
    r"\Theta": "~Q",
    r"\iota": "~i",
    r"\kappa": "~k",
    r"\lambda": "~l",
    r"\Lambda": "~L",
    r"\mu": "~m",
    r"\nu": "~n",
    r"\xi": "~x",
    r"\Xi": "~X",
    r"\pi": "~p",
    r"\Pi": "~P",
    r"\rho": "~r",
    r"\varrho": "~r",
    r"\sigma": "~s",
    r"\varsigma": "~s",
    r"\Sigma": "~S",
    r"\tau": "~t",
    r"\upsilon": "~u",
    r"\Upsilon": "~U",
    r"\phi": "~f",
    r"\varphi": "~f",
    r"\Phi": "~F",
    r"\chi": "~c",
    r"\psi": "~y",
    r"\Psi": "~Y",
    r"\omega": "~w",
    r"\Omega": "~W",
}

TILDE_GREEK_WORD_TO_FIBS: Final[dict[str, str]] = {
    "alpha": "~a",
    "beta": "~b",
    "gamma": "~g",
    "Gamma": "~G",
    "delta": "~d",
    "Delta": "~D",
    "epsilon": "~e",
    "zeta": "~z",
    "eta": "~h",
    "theta": "~q",
    "Theta": "~Q",
    "iota": "~i",
    "kappa": "~k",
    "lambda": "~l",
    "Lambda": "~L",
    "mu": "~m",
    "my": "~m",
    "nu": "~n",
    "xi": "~x",
    "Xi": "~X",
    "pi": "~p",
    "Pi": "~P",
    "rho": "~r",
    "sigma": "~s",
    "Sigma": "~S",
    "tau": "~t",
    "upsilon": "~u",
    "Upsilon": "~U",
    "phi": "~f",
    "Phi": "~F",
    "chi": "~c",
    "psi": "~y",
    "Psi": "~Y",
    "omega": "~w",
    "Omega": "~W",
}

TILDE_GREEK_WORD_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Za-z0-9\\])~("
    + "|".join(sorted(TILDE_GREEK_WORD_TO_FIBS, key=len, reverse=True))
    + r")(?![a-zA-Z])"
)

DIDACTIC_BOX_HEADER_RE: Final[re.Pattern[str]] = re.compile(
    r"^[ \t]*[*_#]*[ \t]*(?:Steckbrief|Kurzbiografie|Biografie|Merksatz|Merke|Infobox|"
    r"Exkurs|Methode|Hintergrund|Praxis|Wichtig|Tipp|Hinweis|Definition)[ \t]*:?[ \t]*[*_]*$",
    re.IGNORECASE,
)

UNIT_PERCENT_PROTECTED_RE: Final[re.Pattern[str]] = re.compile(
    r"```[\s\S]*?```|`[^`\n]*`|https?://\S+"
)

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

# ---------------------------------------------------------------------------
# Eurobraille (> U+00FF) Deterministic Fallback Replacement Map
# ---------------------------------------------------------------------------

EUROBRAILLE_CHAR_FALLBACK_MAP: Final[dict[str, str]] = {
    **UNICODE_GREEK_TO_LATEX,
    **DIFFICULTY_SYMBOL_MAP,
    "ϵ": r"\varepsilon",
    "ζ": r"\zeta",
    "η": r"\eta",
    "ϑ": r"\vartheta",
    "ι": r"\iota",
    "κ": r"\kappa",
    "ν": r"\nu",
    "ξ": r"\xi",
    "ο": "o",
    "ς": r"\varsigma",
    "υ": r"\upsilon",
    "ϕ": r"\varphi",
    "χ": r"\chi",
    "ψ": r"\psi",
    "Γ": r"\Gamma",
    "Θ": r"\Theta",
    "Λ": r"\Lambda",
    "Ξ": r"\Xi",
    "Π": r"\Pi",
    "Σ": r"\Sigma",
    "Υ": r"\Upsilon",
    "Φ": r"\Phi",
    "Ψ": r"\Psi",
    "₀": "_0",
    "₁": "_1",
    "₂": "_2",
    "₃": "_3",
    "₄": "_4",
    "₅": "_5",
    "₆": "_6",
    "₇": "_7",
    "₈": "_8",
    "₉": "_9",
    "⁰": "^0",
    "¹": "^1",
    "²": "^2",
    "³": "^3",
    "⁴": "^4",
    "⁵": "^5",
    "⁶": "^6",
    "⁷": "^7",
    "⁸": "^8",
    "⁹": "^9",
    "⁺": "^+",
    "⁻": "^-",
    "₊": "_+",
    "₋": "_-",
    "→": r"\to",
    "←": r"\leftarrow",
    "↔": r"\leftrightarrow",
    "⇒": r"\Rightarrow",
    "⇐": r"\Leftarrow",
    "⇔": r"\Leftrightarrow",
    "↦": r"\mapsto",
    "↑": r"\uparrow",
    "↓": r"\downarrow",
    "≤": r"\le",
    "≥": r"\ge",
    "≠": r"\neq",
    "≈": r"\approx",
    "≡": r"\equiv",
    "±": r"\pm",
    "∓": r"\mp",
    "×": r"\times",
    "÷": r"\div",
    "·": r"\cdot",
    "⋅": r"\cdot",
    "•": r"\cdot",
    "∞": r"\infty",
    "∈": r"\in",
    "∉": r"\notin",
    "⊂": r"\subset",
    "⊃": r"\supset",
    "⊆": r"\subseteq",
    "⊇": r"\supseteq",
    "∪": r"\cup",
    "∩": r"\cap",
    "∅": r"\emptyset",
    "∀": r"\forall",
    "∃": r"\exists",
    "∇": r"\nabla",
    "∂": r"\partial",
    "∑": r"\sum",
    "∏": r"\prod",
    "∫": r"\int",
    "√": r"\sqrt{}",
    "∝": r"\propto",
    "⊥": r"\perp",
    "∥": r"\parallel",
    "∠": r"\angle",
    "△": r"\triangle",
    "☐": "[ ]",
    "☑": "[x]",
    "☒": "[x]",
    "✓": "[x]",
    "✔": "[x]",
    "✗": "[ ]",
    "✘": "[ ]",
    "🔊": "[Audio]",
    "🎧": "[Audio]",
    "🎬": "[Video]",
    "🎥": "[Video]",
    "–": "-",
    "—": "-",
    "−": "-",
    "„": '"',
    "“": '"',
    "”": '"',
    "‚": "'",
    "‘": "'",
    "’": "'",
    "…": "...",
    "€": "EUR",
    "‰": "Promille",
}

# ---------------------------------------------------------------------------
# Workload-Aware Pipeline Progress Constants
# ---------------------------------------------------------------------------

PROGRESS_EXTRACTION_INIT_SECONDS: Final[dict[str, float]] = {
    "docling": 4.0,
    "lightonocr": 6.0,
    "lightonocr3": 6.0,
    "infinity": 12.0,
    "non_pdf": 0.5,
}
PROGRESS_EXTRACTION_SECONDS_PER_PAGE: Final[dict[str, float]] = {
    "docling": 1.2,
    "lightonocr": 14.0,
    "lightonocr3": 14.0,
    "infinity": 75.0,
    "non_pdf": 0.2,
}
PROGRESS_VLM_INIT_SECONDS: Final[float] = 13.0
PROGRESS_VLM_SECONDS_PER_IMAGE: Final[float] = 55.0
PROGRESS_VLM_CACHED_SECONDS_PER_IMAGE: Final[float] = 0.2
PROGRESS_GEMMA_INIT_SECONDS: Final[float] = 10.0
PROGRESS_GEMMA_SECONDS_PER_CHUNK: Final[float] = 75.0
PROGRESS_GEMMA_ESTIMATED_PAGES_PER_CHUNK: Final[float] = 1.8
PROGRESS_MIN_EXTRACTION_PERCENT: Final[int] = 5
PROGRESS_MAX_EXTRACTION_PERCENT: Final[int] = 70
PROGRESS_FINALIZE_PERCENT: Final[int] = 99


