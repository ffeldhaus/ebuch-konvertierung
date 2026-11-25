"""Deterministic FIBS (Übertragungsregeln Stand 09/2025) formatting helpers."""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from backend.services import fibs_constants as fc
from backend.services.models import CharOccurrence, VlmDescriptionResult


def _clean_context_text(text: str) -> str:
    """Strips page markers and image payloads from raw page context.

    Args:
        text: Raw Markdown slice from a textbook page.

    Returns:
        Cleaned context string with other images replaced by ``OTHER_IMAGE_PLACEHOLDER``.
    """
    text = fc.IMAGE_BLOCK_RE.sub(fc.OTHER_IMAGE_PLACEHOLDER, text)
    text = fc.MD_IMAGE_RE.sub(fc.OTHER_IMAGE_PLACEHOLDER, text)
    text = fc.PAGE_MARKER_LINE_RE.sub("", text)
    text = fc.MULTI_NEWLINE_RE.sub("\n\n", text)
    return text.strip()


def image_page_context(
    markdown: str,
    start: int,
    end: int,
    max_chars: int = fc.VLM_CONTEXT_MAX_CHARS,
    *,
    page_bounds: list[int] | None = None,
) -> str:
    """Extracts read-only page text context around the image span ``markdown[start:end]``.

    Args:
        markdown: Full document Markdown string.
        start: Start character index of the target image tag.
        end: End character index of the target image tag.
        max_chars: Maximum character budget for the returned context.
        page_bounds: Optional precomputed page boundary offsets covering ``0..len(markdown)``.

    Returns:
        Cleaned, length-capped page context with ``IMAGE_POSITION_MARKER`` at the
        target image position.
    """
    markdown = markdown or ""
    if page_bounds is not None:
        bounds = page_bounds
    else:
        starts = [m.start() for m in fc.PAGE_MARKER_LINE_RE.finditer(markdown)]
        bounds = ([0] if not starts or starts[0] > 0 else []) + starts + [len(markdown)]
    page_idx = max(i for i in range(len(bounds) - 1) if bounds[i] <= start)
    p_start, p_end = bounds[page_idx], bounds[page_idx + 1]

    current_raw = markdown[p_start:start] + fc.IMAGE_POSITION_MARKER + markdown[end:p_end]
    current = _clean_context_text(current_raw)
    context = current
    first_line = ""
    for line in current.splitlines():
        s = line.strip()
        if s and s not in (fc.OTHER_IMAGE_PLACEHOLDER, fc.IMAGE_POSITION_MARKER):
            first_line = s
            break
    if page_idx > 0 and not fc.HEADING_LINE_RE.match(first_line):
        previous = _clean_context_text(markdown[bounds[page_idx - 1] : p_start])
        if previous:
            headings = list(fc.HEADING_LINE_RE.finditer(previous))
            tail = previous[headings[-1].start() :].strip() if headings else previous
            context = f"{tail}\n\n{current}"

    if len(context) <= max_chars:
        return context
    idx = context.find(fc.IMAGE_POSITION_MARKER)
    if idx < 0:
        return context[-max_chars:]
    after = context[idx : idx + max(max_chars // 3, len(fc.IMAGE_POSITION_MARKER))]
    before = context[max(0, idx - (max_chars - len(after))) : idx]
    return (before + after)[:max_chars]


def image_contexts_for_markdown(
    markdown: str,
    match_to_path: dict[str, str],
    max_chars: int = fc.VLM_CONTEXT_MAX_CHARS,
) -> dict[str, str]:
    """Computes read-only page context for each unique image file referenced in ``markdown``.

    Args:
        markdown: Full document Markdown string.
        match_to_path: Mapping from raw Markdown image syntax to resolved file path.
        max_chars: Maximum character count per context entry.

    Returns:
        Dictionary mapping each image file path to its surrounding page context.
    """
    markdown = markdown or ""
    starts = [m.start() for m in fc.PAGE_MARKER_LINE_RE.finditer(markdown)]
    bounds = ([0] if not starts or starts[0] > 0 else []) + starts + [len(markdown)]
    contexts: dict[str, str] = {}
    search_offsets: dict[str, int] = {}
    for match_text, path in match_to_path.items():
        if path in contexts:
            continue
        pos = markdown.find(match_text, search_offsets.get(match_text, 0))
        if pos < 0:
            pos = markdown.find(match_text)
        if pos < 0:
            continue
        end = pos + len(match_text)
        search_offsets[match_text] = end
        contexts[path] = image_page_context(
            markdown,
            pos,
            end,
            max_chars,
            page_bounds=bounds,
        )
    return contexts


def clean_bildart(bildart: str) -> str:
    """Sanitizes and validates a raw FIBS ``BILDART`` label (at most 4 words, not a sentence).

    Args:
        bildart: Raw image type string from VLM or Markdown.

    Returns:
        Cleaned image type label, or ``""`` if invalid.
    """
    s = fc.BILDART_CLEAN_RE.sub("", bildart or "").strip().rstrip(":").strip()
    if not s or len(s) > 40 or len(s.split()) > 4:
        return ""
    if not fc.BILDART_TOKEN_RE.fullmatch(s):
        return ""
    if s.split()[0].lower() in fc.SENTENCE_STARTERS or s.lower().startswith("beschreibung"):
        return ""
    return s


def normalize_description_lists(description: str) -> str:
    r"""Normalizes bullet lists and removes bold markers inside an image description.

    Args:
        description: Raw VLM or fallback image description body.

    Returns:
        Normalized description where bullets use ``-\\t`` and blank lines are removed.
    """
    out: list[str] = []
    for line in (description or "").splitlines():
        raw = line.rstrip()
        m = fc.DESC_BULLET_LINE_RE.match(raw)
        if m:
            indent = m.group(1).replace("\t", "  ")
            raw = "  " * (len(indent) // 2) + "-\t" + m.group(2).strip()
        else:
            raw = raw.strip()
        raw = fc.BOLD_SPAN_RE.sub(r"\1", raw)
        if raw:
            out.append(raw)
    return "\n".join(out)


def format_bild_tag(bildart: str, description: str, has_text: bool | None) -> str:
    """Formats a canonical multi-line FIBS ``<Bild>`` block.

    Args:
        bildart: Short image type label (e.g. ``"Foto"``, ``"Diagramm"``).
        description: Accessibility description text.
        has_text: Whether the image contains visible text labels.

    Returns:
        Formatted multi-line ``<Bild>...</Bild>`` string.
    """
    art = clean_bildart(bildart) or fc.DEFAULT_IMAGE_TYPE
    desc = normalize_description_lists(description) or fc.MISSING_DESCRIPTION
    label = "Beschreibung mit Bildtext:" if has_text else "Beschreibung:"
    body = f"{label}\n{desc}" if desc.startswith("-\t") else f"{label} {desc}"
    return f"<Bild> {art}:\n{body}\n</Bild>"


def normalize_bild_tags(markdown: str) -> str:
    """Converts ``<Bild>`` tags into the canonical multi-line FIBS format.

    Args:
        markdown: Markdown string potentially containing single-line or unformatted ``<Bild>`` tags.

    Returns:
        Markdown string with normalized multi-line ``<Bild>`` blocks.
    """
    if not markdown or "<Bild>" not in markdown:
        return markdown

    def repl(m: re.Match[str]) -> str:
        inner = m.group(1).strip()
        if not inner or fc.CAPTION_BLOCK_RE.match(inner):
            return m.group(0)
        lines = [line.rstrip() for line in inner.split("\n")]
        first = lines[0].strip()
        head = fc.BILDART_HEAD_RE.match(first)

        bildart = clean_bildart(head.group(1)) if head else ""
        rest = "\n".join([head.group(2)] + lines[1:]).strip() if head and bildart else inner
        desc_match = fc.DESC_LABEL_RE.match(rest)
        if desc_match:
            label = desc_match.group(0)
            raw_desc = rest[desc_match.end() :].strip()
        else:
            label = "Beschreibung:"
            raw_desc = rest
        norm_desc = normalize_description_lists(raw_desc)
        body = (
            f"{label}\n{norm_desc}"
            if norm_desc.startswith("-\t")
            else (f"{label} {norm_desc}" if norm_desc else label)
        )
        return f"<Bild> {bildart or fc.DEFAULT_IMAGE_TYPE}:\n{body}\n</Bild>"

    return fc.IMAGE_BLOCK_RE.sub(repl, markdown)


def bild_tag_from_vlm(
    result: VlmDescriptionResult,
    has_caption: bool,
    alt_text: str = "",
) -> str:
    """Converts a ``VlmDescriptionResult`` into the final FIBS ``<Bild>`` tag or drops decorative images.

    Args:
        result: Validated ``VlmDescriptionResult`` from the VLM service.
        has_caption: Whether structural caption/label evidence exists around the image.
        alt_text: Optional fallback alt text from the Markdown image tag.

    Returns:
        Formatted ``<Bild>...</Bild>`` block, or ``""`` if the image is purely decorative.
    """
    if result.decorative and not has_caption:
        return ""
    description = result.description or (alt_text or "").strip()
    return format_bild_tag(result.image_type, description, result.has_text)


def _neighbour_line(markdown: str, pos: int, direction: int) -> str:
    """Finds the nearest non-empty line before or after ``pos``, skipping page markers.

    Args:
        markdown: Full Markdown text.
        pos: Character position in ``markdown``.
        direction: ``-1`` to search backwards, ``+1`` to search forwards.

    Returns:
        Stripped neighbor line, or ``""`` if none exists.
    """
    if direction < 0:
        cur_end = markdown.rfind("\n", 0, pos)
        while cur_end >= 0:
            nl = markdown.rfind("\n", 0, cur_end)
            s = markdown[nl + 1 : cur_end].strip()
            if s and not fc.PAGE_MARKER_ONLY_RE.fullmatch(s):
                return s
            cur_end = nl
        return ""

    nl_after = markdown.find("\n", pos)
    if nl_after < 0:
        return ""
    cur_start = nl_after + 1
    n = len(markdown)
    while cur_start <= n:
        nl = markdown.find("\n", cur_start)
        end_idx = n if nl < 0 else nl
        s = markdown[cur_start:end_idx].strip()
        if s and not fc.PAGE_MARKER_ONLY_RE.fullmatch(s):
            return s
        if nl < 0:
            break
        cur_start = nl + 1
    return ""


def has_caption_context(markdown: str, start: int, end: int, alt_text: str = "") -> bool:
    """Checks for structural evidence that the image at ``markdown[start:end]`` is content-relevant.

    Args:
        markdown: Full document Markdown string.
        start: Start index of the image match.
        end: End index of the image match.
        alt_text: Alt text extracted from the Markdown image syntax.

    Returns:
        True if the image has a meaningful alt text, inline text on the same line,
        or an adjacent figure/material caption.
    """
    alt = (alt_text or "").strip()
    if (
        alt
        and not fc.GENERIC_ALT_RE.match(alt)
        and len(alt.split()) >= 2
        and not fc.IMAGE_EXT_RE.search(alt)
    ):
        return True

    line_start = markdown.rfind("\n", 0, start) + 1
    line_end = markdown.find("\n", end)
    line_end = len(markdown) if line_end < 0 else line_end
    same_line = markdown[line_start:start] + markdown[end:line_end]
    same_line = fc.BILD_TAG_DELIM_RE.sub("", same_line).strip()
    if same_line:
        return True

    for neighbour in (
        _neighbour_line(markdown, line_start, -1),
        _neighbour_line(markdown, line_end, +1),
    ):
        if neighbour and (
            (fc.CAPTION_WORD_RE.match(neighbour) and re.search(r"\d|:", neighbour[:30]))
            or fc.CAPTION_LABEL_RE.match(neighbour)
        ):
            return True
    return False


def convert_unicode_scripts(text: str) -> str:
    """Converts Unicode subscripts and superscripts to FIBS ``_`` and ``^`` notation.

    Superscript digits without a sign directly following a word of at least 3 letters
    or punctuation (e.g. ``Aussage¹``) are preserved for footnote processing.

    Args:
        text: Input Markdown text.

    Returns:
        Text with Unicode sub-/superscripts converted (e.g. ``H_2O``, ``Fe^{3+}``).
    """
    if not text:
        return text
    text = fc.SUB_RE.sub(
        lambda m: f"_{s}" if len(s := m.group(0).translate(fc.SUB_MAP)) == 1 else f"_{{{s}}}",
        text,
    )

    def sup(m: re.Match[str]) -> str:
        s = m.group(0)
        if not any(c in "⁺⁻" for c in s):
            before = text[: m.start()]
            word = fc.TRAILING_WORD_RE.search(before)
            if (word and len(word.group(1)) >= 3) or fc.TRAILING_PUNCT_RE.search(before):
                return s
        t = s.translate(fc.SUP_MAP)
        return f"^{t}" if len(t) == 1 else f"^{{{t}}}"

    return fc.SUP_RE.sub(sup, text)


def _has_person_name_prefix(line_prefix: str) -> bool:
    """Checks whether ``line_prefix`` ends with a given name, initial, or person title.

    Args:
        line_prefix: Text preceding an ALL-CAPS candidate on the current line.

    Returns:
        True if ``line_prefix`` indicates a person-name surname context.
    """
    cleaned = line_prefix.rstrip("_")
    pm = fc.PERSON_PREFIX_RE.search(cleaned)
    if not pm:
        return False
    word = pm.group(1)
    if not word:
        return True  # Initial (e.g. 'G. ') or academic title (e.g. 'Dr. ', 'Prof. ')
    low = word.lower()
    if low in fc.PERSON_ROLE_PREFIXES:
        return True
    if low in fc.NON_NAME_CAPITALIZED_WORDS:
        return False
    if low.endswith((
        "ung", "heit", "keit", "schaft", "tum", "nis", "ment", "tion", "tät",
        "system", "verfahren", "protokoll", "standard", "format", "modell",
        "begriff", "wort", "stoff", "enzym", "molekül", "gesetz", "prinzip",
    )):
        return False
    return True


def _is_convertible_versalien_part(
    part: str,
    *,
    has_name_prefix: bool,
    in_multiword_run: bool,
    followed_by_compound_hyphen: bool,
) -> bool:
    """Determines whether an ALL-CAPS sub-token without document evidence is a real word/name.

    Args:
        part: Uppercase alphabetic token without hyphens.
        has_name_prefix: Whether the run is preceded by a person given name, initial, or title.
        in_multiword_run: Whether the token belongs to a multi-word ALL-CAPS phrase.
        followed_by_compound_hyphen: Whether the run is followed by ``-<Word>`` (acronym compound).

    Returns:
        True if ``part`` should be recased to mixed-case instead of kept as an acronym.
    """
    u = part.upper()
    if u in fc.PROTECTED_ACRONYMS or u in fc.VALID_CHEMICAL_ELEMENTS:
        return False
    if fc.ROMAN_NUMERAL_RE.fullmatch(u):
        return False
    if in_multiword_run and u.lower() in fc.VERSALIEN_CONNECTORS:
        return True
    if followed_by_compound_hyphen and not has_name_prefix:
        return False
    if re.search(r"(.)\1\1", u):
        return False

    vowels = sum(1 for ch in u if ch in "AEIOUÄÖÜY")
    if has_name_prefix and len(u) >= 4:
        if vowels < 1 or vowels / len(u) > 0.75:
            return False
        # Reject pure consonant-cluster endings typical of 4-letter initialisms (e.g. 'OFDM', 'VLIW')
        if len(u) == 4 and (
            not any(ch in "AEIOUÄÖÜY" for ch in u[1:])
            or re.match(r"^[BCDFGHJKLMNPQRSTVWXZ]{3}", u)
        ):
            return False
        return True

    if len(u) < 5:
        return False
    vowel_groups = re.findall(r"[AEIOUÄÖÜY]+", u)
    if len(vowel_groups) < 2:
        return False
    if any(len(vg) >= 3 and vg not in ("EAU", "IEU") for vg in vowel_groups):
        return False
    eff_u = u.replace("SCH", "S").replace("CH", "C").replace("CK", "K")
    if re.search(r"[BCDFGHJKLMNPQRSTVWXZ]{4,}", eff_u):
        return False
    v_ratio = vowels / len(u)
    return 0.25 <= v_ratio <= 0.65


def normalize_versalien(markdown: str) -> str:
    """Converts ALL-CAPS / small-caps emphasis words and person names to ``_Wort_`` emphasis.

    Protects genuine acronyms and technical abbreviations (e.g. ``UNESCO``, ``DNA``, ``ATP``,
    ``IUPAC``), chemical elements, and Roman numerals while converting both words attested in
    mixed-case elsewhere in ``markdown`` and pronounceable ALL-CAPS person surnames or
    multi-syllable emphasis words (e.g. ``Charles BEST`` -> ``Charles _Best_``,
    ``Christoph KOLUMBUS`` -> ``Christoph _Kolumbus_``, ``ACHTUNG`` -> ``_Achtung_``).
    Inside ``#`` headings, Versalien are recased without ``_..._`` markers.

    Args:
        markdown: Input Markdown string.

    Returns:
        Markdown string with Versalien normalized to ``_Wort_`` (or plain mixed-case in headings).
    """
    if not markdown or not fc.FOUR_CAPS_RE.search(markdown):
        return markdown

    forms: dict[str, Counter[str]] = {}
    for w in fc.WORD_RE.findall(markdown):
        if not w.isupper() and len(w) >= 2:
            forms.setdefault(w.lower(), Counter())[w] += 1
    known = {k: c.most_common(1)[0][0] for k, c in forms.items()}
    hard_protected: list[tuple[int, int]] = []
    bild_spans: list[tuple[int, int]] = []
    for m_prot in fc.PROTECTED_ALL_CAPS_RE.finditer(markdown):
        if m_prot.group(0).startswith("<Bild>"):
            bild_spans.append(m_prot.span())
        else:
            hard_protected.append(m_prot.span())

    def is_hard_protected(a: int, b: int) -> bool:
        return any(ps < b and a < pe for ps, pe in hard_protected)

    def is_in_bild(a: int, b: int) -> bool:
        return any(ps < b and a < pe for ps, pe in bild_spans)

    out: list[str] = []
    last = 0
    for m in fc.CAPS_RUN_RE.finditer(markdown):
        if is_hard_protected(m.start(), m.end()):
            continue
        in_bild_block = is_in_bild(m.start(), m.end())
        lead_u, run, trail_u = m.group(1), m.group(2), m.group(3)
        words = run.split()
        parts = [p for w in words for p in w.split("-")]
        if not any(len(p) >= 4 for p in parts):
            continue
        if any(
            p.upper() in fc.PROTECTED_ACRONYMS or fc.ROMAN_NUMERAL_RE.fullmatch(p)
            for p in parts
        ):
            continue

        line_start = markdown.rfind("\n", 0, m.start()) + 1
        line_prefix = markdown[line_start : m.start()]
        has_name_prefix = _has_person_name_prefix(line_prefix)
        if in_bild_block and not has_name_prefix:
            continue
        after_run = markdown[m.end() :]
        followed_by_hyphen = bool(re.match(r"^-[A-Za-zÄÖÜäöüß]", after_run))
        in_multi = len(words) > 1

        all_known = all(p.lower() in known for p in parts)
        if not all_known:
            if not all(
                (p.lower() in known)
                or _is_convertible_versalien_part(
                    p,
                    has_name_prefix=has_name_prefix and idx_w == 0,
                    in_multiword_run=in_multi,
                    followed_by_compound_hyphen=followed_by_hyphen,
                )
                for idx_w, w in enumerate(words)
                for p in w.split("-")
            ):
                continue

        def _recase_part(part_tok: str, is_first_in_run: bool) -> str:
            low = part_tok.lower()
            if low in known:
                return known[low]
            if in_multi and not is_first_in_run and low in fc.VERSALIEN_CONNECTORS:
                return low
            return part_tok[0].upper() + part_tok[1:].lower()

        recased_words: list[str] = []
        for idx_w, w in enumerate(words):
            sub_parts = w.split("-")
            recased_words.append(
                "-".join(
                    _recase_part(sp, idx_w == 0 and idx_sp == 0)
                    for idx_sp, sp in enumerate(sub_parts)
                )
            )
        recased = " ".join(recased_words)

        is_heading = bool(fc.HEADING_LINE_RE.match(markdown[line_start:]))
        if (
            is_heading
            or not fc.LINE_DECORATION_RE.sub("", line_prefix)
            or fc.SENTENCE_END_PREFIX_RE.search(line_prefix)
        ):
            recased = recased[0].upper() + recased[1:]

        if bool(lead_u) != bool(trail_u):
            # Inside an outer _..._ emphasis span on one boundary: preserve outer underscore
            replacement = f"{lead_u}{recased}{trail_u}"
        elif is_heading:
            replacement = recased
        else:
            replacement = f"_{recased}_"

        out.append(markdown[last : m.start()])
        out.append(replacement)
        last = m.end()
    out.append(markdown[last:])
    return "".join(out)


def normalize_fibs_units_and_percent(text: str) -> str:
    r"""Normalizes FIBS 09/2025 units, degrees, percentages, promille, thousands, and coordinates.

    Applies FIBS Section 8.1 and LaTeX-Handreichung rules deterministically outside code and URLs:
      - Unwraps standalone ``$80\,^\circ\text{C}$``, ``$90^\circ$``, ``$36^\circ 14' 10''$``,
        ``$50\,\%$``, and ``$5\,\permil$`` spans.
      - Replaces ``<num>^\circ\text{C}`` -> ``<num> °C`` and ``<num>^\circ`` -> ``<num>°``.
      - Formats temperatures with one space before ``°C`` / ``°F`` (``33°C`` -> ``33 °C``).
      - Formats angles, arcminutes, and arcseconds without spaces (``45 °`` -> ``45°``,
        ``36° 14′ 10″`` -> ``36°14'10''``).
      - Formats percentages with one space before ``%`` (``50%`` -> ``50 %``), preserving
        hyphenated and suffixed forms (``5%-Klausel``, ``100%ig``).
      - Normalizes ``‰`` and ``\textperthousand`` to ``\permil`` with one leading space
        after numbers (``5‰`` / ``5\permil`` -> ``5 \permil``).
      - Repairs micromol units (``~mol``, ``µmol``, ``μmol`` -> ``~mmol``).
      - Normalizes German thousands separators with dots (``300 000`` -> ``300.000``,
        ``10000`` -> ``10.000``, ``5143`` -> ``5.143``, ``1400 cm^3`` -> ``1.400 cm^3``)
        while preserving years, dates, postal codes, ISBNs, page markers, and decimals.
      - Normalizes 2D/3D point coordinates in parentheses to ``(x|y)`` without spaces
        (``(0; 50)`` -> ``(0|50)``, ``P(2; -5)`` -> ``P(2|-5)``).

    Args:
        text: Input Markdown text.

    Returns:
        Text with normalized FIBS units, numbers, and coordinate formatting.
    """
    if not text:
        return text

    protected_spans: list[str] = []

    def _mask(m: re.Match[str]) -> str:
        protected_spans.append(m.group(0))
        return f"__FIBS_PROT_{len(protected_spans) - 1}__"

    work = fc.UNIT_PERCENT_PROTECTED_RE.sub(_mask, text)

    # 1. Unwrap standalone $...$ angles with arcminutes/arcseconds, temperatures, and plain angles
    def _unwrap_dollar_dms(m: re.Match[str]) -> str:
        deg = m.group(1).replace("{,}", ",").replace("−", "-")
        mins = m.group(2).replace("{,}", ",")
        secs = (m.group(3) or "").replace("{,}", ",")
        return f"{deg}°{mins}'{secs}''" if secs else f"{deg}°{mins}'"

    work = re.sub(
        r"\$\s*([-+−]?\d+(?:(?:\{,\}|[.,])\d+)?)\s*(?:\\,|\s)*(?:°|\^\s*\{?\\circ\}?)\s*(?:\\,|\s)*"
        r"(\d{1,2}(?:(?:\{,\}|[.,])\d+)?)\s*(?:\^\s*\{?\s*\\prime\s*\}?|\\prime(?![a-zA-Z])|′|'(?!'))"
        r"(?:\s*(?:\\,|\s)*(\d{1,2}(?:(?:\{,\}|[.,])\d+)?)\s*"
        r"(?:\^\s*\{?\s*(?:\\prime\s*){2}\}?|(?:\\prime\s*){2}(?![a-zA-Z])|″|''|′′|'[ \t]+'))?\s*\$",
        _unwrap_dollar_dms,
        work,
    )

    def _unwrap_dollar_deg(m: re.Match[str]) -> str:
        num = m.group(1).replace("{,}", ",").replace("−", "-")
        cf = m.group(2) or m.group(3)
        return f"{num} °{cf}" if cf else f"{num}°"

    work = re.sub(
        r"\$\s*([-+−]?\d+(?:(?:\{,\}|[.,])\d+)?)\s*(?:\\,|\s)*(?:°|\^\s*\{?\\circ\}?)\s*"
        r"(?:\\(?:text|mathrm)\s*\{\s*([CF])\s*\}|([CF]))?\s*\$",
        _unwrap_dollar_deg,
        work,
    )

    # 2. Unwrap standalone $...$ percentages and promille (e.g. '$50\,\%$', '$5\,\permil$')
    def _unwrap_dollar_pct(m: re.Match[str]) -> str:
        num = m.group(1).replace("{,}", ",").replace("−", "-")
        tail = work[m.end() :]
        if tail.startswith("-") or re.match(r"^ig", tail):
            return f"{num}%"
        return f"{num} %"

    work = re.sub(
        r"\$\s*([-+−]?\d+(?:(?:\{,\}|[.,])\d+)?)\s*(?:\\,|\s)*\\?%\s*\$",
        _unwrap_dollar_pct,
        work,
    )
    work = re.sub(
        r"\$\s*([-+−]?\d+(?:(?:\{,\}|[.,])\d+)?)\s*(?:\\,|\s)*"
        r"(?:‰|\\(?:textperthousand|permil)(?![a-zA-Z]))\s*\$",
        lambda m: f"{m.group(1).replace('{,}', ',').replace('−', '-')} \\permil",
        work,
    )

    # 3. Convert numeric ^\circ inside compound formulas (e.g. '\xrightarrow{450\,^\circ\text{C}}', '\alpha < 10^\circ')
    work = re.sub(
        r"([-+−]?\d+(?:(?:\{,\}|[.,])\d+)?)\s*(?:\\,|\s)*\^\s*\{?\\circ\}?\s*"
        r"(?:\\(?:text|mathrm)\s*\{\s*([CF])\s*\}|([CF])\b)",
        lambda m: f"{m.group(1).replace('{,}', ',')} °{m.group(2) or m.group(3)}",
        work,
    )
    work = re.sub(
        r"(\d+(?:(?:\{,\}|[.,])\d+)?)\s*(?:\\,|\s)*\^\s*\{?\\circ\}?"
        r"(?!\s*(?:\\(?:text|mathrm)\s*\{\s*[CF]\s*\}|[CF]\b))",
        lambda m: f"{m.group(1).replace('{,}', ',')}°",
        work,
    )

    # 4. Plain temperature spacing: '<num> °C' / '<num> °F' (1 space after number, none before C/F)
    work = re.sub(
        r"([-+]?\d+(?:[.,]\d+)?)[ \t]*°[ \t]*([CF])\b",
        r"\1 °\2",
        work,
    )

    # 5. Plain angle / coordinate / arcminute / arcsecond spacing: '<num>°' and '36°14'10'''
    work = re.sub(
        r"(\d+(?:[.,]\d+)?)[ \t]+°(?![ \t]*[CF]\b)",
        r"\1°",
        work,
    )
    work = re.sub(
        r"(\d+(?:[.,]\d+)?)°[ \t]*(\d{1,2}(?:[.,]\d+)?)[ \t]*"
        r"(?:\^\s*\{?\s*\\prime\s*\}?|\\prime(?![a-zA-Z])|′|'(?!'))"
        r"(?:[ \t]*(\d{1,2}(?:[.,]\d+)?)[ \t]*"
        r"(?:\^\s*\{?\s*(?:\\prime\s*){2}\}?|(?:\\prime\s*){2}(?![a-zA-Z])|″|''|′′|'[ \t]+'))?"
        r"(?![a-z0-9'])",
        lambda m: f"{m.group(1)}°{m.group(2)}'{m.group(3)}''"
        if m.group(3)
        else f"{m.group(1)}°{m.group(2)}'",
        work,
    )

    # 6. Plain percentage spacing: '<num> %' except before '-' or 'ig...' (and skip '\%' inside $...$)
    work = re.sub(
        r"(\d)[ \t]*(?<!\\)%(?!-|ig)",
        r"\1 %",
        work,
    )

    # 7. Promille normalization: '‰' and '\textperthousand' -> '\permil' with 1 space after numbers
    work = re.sub(
        r"(?:\\textperthousand(?![a-zA-Z])|‰)(?=[A-Za-z])",
        lambda _: r"\permil ",
        work,
    )
    work = re.sub(r"\\textperthousand(?![a-zA-Z])|‰", lambda _: r"\permil", work)
    work = re.sub(r"(\d)[ \t]*\\permil(?![a-zA-Z])", r"\1 \\permil", work)

    # 8. Micromol normalization: 'µmol'/'μmol' and merged '~mol' -> '~mmol'
    work = re.sub(r"(\d)[ \t]*[µμ]mol(?![A-Za-z])", r"\1 ~mmol", work)
    work = re.sub(r"(?<![A-Za-z\\])[µμ]mol(?![A-Za-z])", "~mmol", work)
    work = re.sub(r"(\d)[ \t]*~mol(?![A-Za-z])", r"\1 ~mmol", work)
    work = re.sub(r"(?<![A-Za-z~\\])~mol(?![A-Za-z])", "~mmol", work)

    # 9. Thousands separator dots (5.143, 200.000, 1.400 cm^3), preserving years/dates/PLZs/IDs/decimals
    num_prot: list[str] = []

    def _mask_num(m: re.Match[str]) -> str:
        num_prot.append(m.group(0))
        return f"__FIBS_NUM_{len(num_prot) - 1}__"

    work = fc.THOUSANDS_PROTECTED_RE.sub(_mask_num, work)

    def _fmt_spaced_thousands(m: re.Match[str]) -> str:
        raw = m.group(1)
        line_s = work.rfind("\n", 0, m.start()) + 1
        if re.search(r"\d[ \t]+$", work[line_s : m.start()]) or re.match(
            r"^[ \t]+\d", work[m.end() :]
        ):
            return raw
        parts = re.split(r"[ \u00a0\u202f]", raw)
        if len(parts) >= 3:
            vals = [int(p) for p in parts]
            step = vals[1] - vals[0]
            if step > 0 and all(vals[i + 1] - vals[i] == step for i in range(len(vals) - 1)):
                return raw
        return ".".join(parts)

    work = re.sub(
        r"(?<![0-9.,/\\A-Za-z_])([1-9]\d{0,2}(?:[ \u00a0\u202f]\d{3})+)(?![0-9]|\.[0-9]|[A-Za-z_])",
        _fmt_spaced_thousands,
        work,
    )

    def _fmt_large_int(m: re.Match[str]) -> str:
        digits = m.group(1)
        if len(digits) == 5 and not digits.endswith("000"):
            line_s = work.rfind("\n", 0, m.start()) + 1
            before = work[line_s : m.start()]
            after = work[m.end() :]
            m_city = re.match(
                r"^[ \t]+([A-ZÄÖÜ][a-zäöüß]{2,})(?:[ \t]*(?:[,.;:\n)\]|]|$|[/-][A-ZÄÖÜ]"
                r"|(?:am|an|im|in|ob|bei|vor|unter)[ \t]+[A-ZÄÖÜ]))",
                after,
            )
            if (
                m_city
                and m_city.group(1) not in fc.THOUSANDS_UNIT_NOUNS
                and (
                    not before.strip()
                    or re.search(
                        r"(?:,\s*|\b(?:in|aus|nach|bei|zu|von)[ \t]+|[(\[|\t][ \t]*)$",
                        before,
                        re.IGNORECASE,
                    )
                )
            ):
                return digits
        return f"{int(digits):,}".replace(",", ".")

    work = re.sub(
        r"(?<![0-9.,/\\A-Za-z_])([1-9]\d{4,})(?![0-9]|\.[0-9]|[A-Za-z_])",
        _fmt_large_int,
        work,
    )

    def _fmt_4digit_int(m: re.Match[str]) -> str:
        digits = m.group(1)
        line_s = work.rfind("\n", 0, m.start()) + 1
        before = work[line_s : m.start()]
        if fc.THOUSANDS_YEAR_PREFIX_RE.search(before):
            return digits
        if int(digits) >= 2100 or fc.THOUSANDS_4DIGIT_UNIT_RE.match(work[m.end() :]):
            return f"{digits[0]}.{digits[1:]}"
        return digits

    work = re.sub(
        r"(?<![0-9.,/\\A-Za-z_])([1-9]\d{3})(?![0-9]|\.[0-9]|[A-Za-z_])",
        _fmt_4digit_int,
        work,
    )

    for idx, val in reversed(list(enumerate(num_prot))):
        work = work.replace(f"__FIBS_NUM_{idx}__", val)

    # 10. Point coordinates in round parentheses: (0; 50) -> (0|50), P(2; -5) -> P(2|-5)
    def _fmt_num_coord(m: re.Match[str]) -> str:
        parts = [g.replace("−", "-") for g in m.groups() if g is not None]
        return f"({'|'.join(parts)})"

    work = fc.COORD_NUM_RE.sub(_fmt_num_coord, work)

    def _fmt_var_coord(m: re.Match[str]) -> str:
        if m.group(1) is not None:
            parts = [g for g in (m.group(2), m.group(3), m.group(4)) if g is not None]
            return f"{m.group(1)}({'|'.join(parts)})"
        parts = [g for g in (m.group(5), m.group(6), m.group(7)) if g is not None]
        return f"({'|'.join(parts)})"

    work = fc.COORD_VAR_RE.sub(_fmt_var_coord, work)

    for idx, val in enumerate(protected_spans):
        work = work.replace(f"__FIBS_PROT_{idx}__", val)
    return work


def clean_repl_value(value: Any) -> str:
    """Sanitizes a raw LLM/VLM replacement suggestion down to the pure replacement string.

    Ported from ``lightonocr/lib.mjs`` (``cleanReplValue``): extracts the last backticked
    code span if present, isolates a single LaTeX command or script token, strips leading
    descriptive prefixes before ``:``/``=``, removes control characters, and caps length at 40.

    Args:
        value: Raw replacement value returned by the model.

    Returns:
        Cleaned replacement string (at most 40 characters), or ``""`` if invalid.
    """
    v = re.sub(r"[\x00-\x1f\x7f]", "", str(value or "")).strip()
    if not v:
        return ""
    ticks = list(re.finditer(r"`([^`]+)`", v))
    if ticks:
        v = ticks[-1].group(1).strip()
    if "\\" in v:
        m = re.search(r"\\[a-zA-Z]+|\\[^a-zA-Z\s]|[\^_~]\{[^}]*\}|[\^_~][\w\d]", v)
        if m:
            v = m.group(0).strip()
    else:
        m = re.search(r"[:=]\s*(.+)$", v)
        if m:
            v = m.group(1).strip()
    v = re.split(r"\s*[,;]\s*", v)[0].strip()
    v = re.sub(r"^[\"'`]+|[\"'`]+$", "", v)
    v = re.sub(r"\s*[.,;]\s*$", "", v).strip()
    return "" if len(v) > 40 else v


def find_non_latin1_chars(
    text: str,
    existing_map: dict[str, dict[str, Any]] | None = None,
) -> list[CharOccurrence]:
    """Scans text for non-Latin1 characters (``ord(ch) > 0xFF``) outside Eurobraille.

    Counts occurrences, sorts by Unicode codepoint ascending, and merges any known
    replacements from ``existing_map`` or ``EUROBRAILLE_CHAR_FALLBACK_MAP``.

    Args:
        text: Input Markdown or document text to scan.
        existing_map: Optional mapping ``{ch: {"replacement": str, "active": bool}}``
            of user-configured replacements to merge.

    Returns:
        List of ``CharOccurrence`` domain models sorted by codepoint.
    """
    counts: Counter[str] = Counter()
    for ch in str(text or ""):
        cp = ord(ch)
        if cp <= 0xFF or ch.isspace():
            continue
        counts[ch] += 1

    existing = existing_map or {}
    occurrences: list[CharOccurrence] = []
    for ch, count in sorted(counts.items(), key=lambda item: ord(item[0])):
        cp = ord(ch)
        hex_code = f"U+{cp:04X}"
        entry = existing.get(ch) or existing.get(hex_code) or {}
        if isinstance(entry, str):
            repl = entry
            active = True
        elif isinstance(entry, dict):
            repl = str(entry.get("replacement", "") or "")
            active = bool(entry.get("active", True))
        else:
            repl = ""
            active = True
        if not repl and ch in fc.EUROBRAILLE_CHAR_FALLBACK_MAP:
            repl = fc.EUROBRAILLE_CHAR_FALLBACK_MAP[ch]
        occurrences.append(
            CharOccurrence(
                ch=ch,
                code=cp,
                hex_code=hex_code,
                count=count,
                replacement=repl,
                active=active,
            )
        )
    return occurrences


def parse_char_replacement_suggestions(
    raw_output: str,
    requested_chars: list[str],
) -> dict[str, str]:
    """Parses LLM output into a validated ``{char: replacement}`` mapping for ``requested_chars``.

    Strips ``<think>...</think>`` blocks and Markdown code fences, parses either a JSON
    object/array (``{"vorschlaege": [...]}``) or line-based ``U+XXXX: ...`` / ``<ch>: ...``
    fallbacks, sanitizes values via ``clean_repl_value``, and discards unrequested characters.

    Args:
        raw_output: Raw text or JSON response from the LLM.
        requested_chars: List of characters (> U+00FF) that were requested.

    Returns:
        Dictionary mapping each matched requested character to its sanitized replacement.
    """
    valid_chars: set[str] = {
        ch[0]
        for ch in (requested_chars or [])
        if isinstance(ch, str) and len(ch) >= 1 and ord(ch[0]) > 0xFF
    }
    if not valid_chars or not raw_output:
        return {}

    cp_map: dict[str, str] = {f"{ord(c):04X}": c for c in valid_chars}
    out: dict[str, str] = {}

    quelltext = re.sub(r"<think>[\s\S]*?</think>", "", str(raw_output), flags=re.IGNORECASE).strip()

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", quelltext, flags=re.IGNORECASE)
    candidate = ""
    if fence:
        candidate = fence.group(1).strip()
    else:
        a_brace, b_brace = quelltext.find("{"), quelltext.rfind("}")
        a_brack, b_brack = quelltext.find("["), quelltext.rfind("]")
        if a_brace >= 0 and b_brace > a_brace:
            candidate = quelltext[a_brace : b_brace + 1]
        elif a_brack >= 0 and b_brack > a_brack:
            candidate = quelltext[a_brack : b_brack + 1]

    if candidate:
        try:
            obj = json.loads(candidate)
            if isinstance(obj, list):
                items = obj
            elif isinstance(obj, dict):
                items = (
                    obj.get("vorschlaege")
                    or obj.get("suggestions")
                    or obj.get("items")
                    or obj.get("ersetzungen")
                    or obj.get("replacements")
                )
                if items is None:
                    # Support direct {"α": "\\alpha", "U+03B1": "\\alpha"} dictionary format
                    for k, v in obj.items():
                        k_str = str(k).strip()
                        code_key = re.sub(r"^U\+?", "", k_str.upper()).zfill(4)
                        ch = cp_map.get(code_key) or (k_str if k_str in valid_chars else None)
                        val = clean_repl_value(v)
                        if ch and val and ch not in out:
                            out[ch] = val
                    if out:
                        return out
                    items = []
            else:
                items = []

            for entry in items if isinstance(items, list) else []:
                if not isinstance(entry, dict):
                    continue
                code_raw = str(
                    entry.get("code") or entry.get("codepoint") or entry.get("cp") or ""
                ).upper()
                code_norm = re.sub(r"^U\+?", "", code_raw).zfill(4) if code_raw else ""
                zeichen = str(
                    entry.get("zeichen") or entry.get("char") or entry.get("glyph") or ""
                )
                ch = cp_map.get(code_norm) or (zeichen if zeichen in valid_chars else None)
                wert = clean_repl_value(
                    entry.get("ersetzung")
                    or entry.get("replacement")
                    or entry.get("value")
                    or entry.get("text")
                    or ""
                )
                if not ch or not wert:
                    continue
                if ch not in out:
                    out[ch] = wert
            if out:
                return out
        except Exception:
            pass

    for raw_line in quelltext.splitlines():
        line = raw_line.strip()
        line = re.sub(r"^[-*•]\s*", "", line)
        line = re.sub(r"^\d+[.)]\s*", "", line)
        line = line.replace("**", "")
        line = re.sub(r"^\||\|$", "", line).strip()
        if not line or len(line) > 200:
            continue
        ch = None
        rest = ""
        m_code = re.search(
            r"\bU?\+?([0-9A-Fa-f]{2,6})\b\s*(?:[:=→>\-–—|]+|\s)\s*(.+)$",
            line,
        )
        if m_code:
            ch = cp_map.get(m_code.group(1).upper().zfill(4))
            rest = m_code.group(2)
        else:
            first_ch = line[0]
            if first_ch in valid_chars:
                ch = first_ch
                rest = re.sub(r"^\s*[:=→>\-–—|]+\s*", "", line[1:])
        if not ch or not rest:
            continue
        wert = clean_repl_value(re.sub(r"^\|", "", rest))
        if not wert or "\n" in wert:
            continue
        if ch not in out:
            out[ch] = wert

    return out

