"""Deterministic FIBS (Übertragungsregeln Stand 09/2025) formatting helpers."""

from __future__ import annotations

import re
from collections import Counter

from backend.services import fibs_constants as fc
from backend.services.models import VlmDescriptionResult


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


def normalize_versalien(markdown: str) -> str:
    """Converts ALL-CAPS emphasis words (Versalien) to normal case with ``_Wort_`` emphasis.

    To protect genuine acronyms and abbreviations (e.g. ``UNESCO``, ``DNA``), an
    all-caps run is only converted when every constituent word also appears in
    normal mixed-case spelling elsewhere in the same document.

    Args:
        markdown: Input Markdown string.

    Returns:
        Markdown string with Versalien normalized to ``_Wort_`` (or normal case in headings).
    """
    if not markdown or not fc.FOUR_CAPS_RE.search(markdown):
        return markdown

    forms: dict[str, Counter[str]] = {}
    for w in fc.WORD_RE.findall(markdown):
        if not w.isupper() and len(w) >= 2:
            forms.setdefault(w.lower(), Counter())[w] += 1
    known = {k: c.most_common(1)[0][0] for k, c in forms.items()}
    protected: list[tuple[int, int]] = [
        m.span() for m in fc.PROTECTED_ALL_CAPS_RE.finditer(markdown)
    ]

    def is_protected(a: int, b: int) -> bool:
        return any(ps < b and a < pe for ps, pe in protected)

    out: list[str] = []
    last = 0
    for m in fc.CAPS_RUN_RE.finditer(markdown):
        if is_protected(m.start(), m.end()):
            continue
        run = m.group(2)
        words = run.split()
        parts = [p for w in words for p in w.split("-")]
        if not any(len(p) >= 4 for p in parts) or not all(p.lower() in known for p in parts):
            continue

        recased = " ".join("-".join(known[p.lower()] for p in w.split("-")) for w in words)
        line_start = markdown.rfind("\n", 0, m.start()) + 1
        line_prefix = markdown[line_start : m.start()]
        is_heading = bool(fc.HEADING_LINE_RE.match(markdown[line_start:]))
        if (
            is_heading
            or not fc.LINE_DECORATION_RE.sub("", line_prefix)
            or fc.SENTENCE_END_PREFIX_RE.search(line_prefix)
        ):
            recased = recased[0].upper() + recased[1:]

        replacement = recased if is_heading else f"_{recased}_"
        out.append(markdown[last : m.start()])
        out.append(replacement)
        last = m.end()
    out.append(markdown[last:])
    return "".join(out)
