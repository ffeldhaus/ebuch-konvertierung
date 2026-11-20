"""E-Buch 2025 (FIBS 09/2025) accessibility linter and deterministic autofixer."""

from __future__ import annotations

import re

from backend.services.fibs_constants import CAPTION_BLOCK_RE, UNIT_PERCENT_PROTECTED_RE
from backend.services.fibs_formatting import (
    convert_unicode_scripts,
    normalize_bild_tags,
    normalize_fibs_units_and_percent,
)
from backend.services.fibs_postprocess import (
    deduplicate_page_numbers,
    restore_false_positive_trailing_asterisks,
)
from backend.services.models import LintIssue, LintReport

_SEMANTIC_HEADING_RE = re.compile(
    r"^(?:Abbildung(?:en)?|Abb|Bild(?:er)?|Grafik(?:en)?|Figure[ns]?|Fig|Aufgaben?|Übung(?:en)?|"
    r"Beispiele?|Tabellen?|Tab|Infobox(?:en)?|Merksatz|Merksätze|Definition(?:en)?|"
    r"[MBQ]\s*\d+[a-z]?|[MBQ]\s+(?:Steckbriefe?|Tabellen?|Material(?:ien)?)|"
    r"Material(?:ien)?|Quellen?|Steckbriefe?|Exkurse?|Zusammenfassung(?:en)?|"
    r"Worterklärungen?|Worterklaerungen?|Randspalten?)\b\.?",
    re.IGNORECASE,
)
_UNANNOUNCED_PCT_EMPH_RE = re.compile(
    r"(?<![0-9\\])(?<!\d )%([A-Za-zÄÖÜäöüß][^%\t\n]{0,80}?[A-Za-zÄÖÜäöüß.')])%(?![A-Za-zÄÖÜäöüß])"
)
_EMPHASIS_LEGEND_ANM_RE = re.compile(
    r"<Anmerkung\b[^>]*>(?:(?!</Anmerkung>)[\s\S])*?"
    r"(?:kursiv|\*[^\n<]*fett|#[^\n<]*unterstrichen|Hervorhebung\w*[^\n<]*(?:%|\*|#)|%[^\n<]*(?:kursiv|Hervorhebung))"
    r"(?:(?!</Anmerkung>)[\s\S])*?</Anmerkung>",
    re.IGNORECASE,
)


def lint_markdown(
    content: str,
    *,
    raw_markdown: str | None = None,
    expected_pages: int | None = None,
    table_max_cells: int | None = None,
    custom_rules: str | None = None,
) -> LintReport:
    """Validate Markdown content against the E-Buch 2025 accessibility standard (FIBS 09/2025).

    When optional ``raw_markdown`` or ``expected_pages`` are provided, also runs source-aware
    completeness cross-checks (e.g., dropped page markers or lost non-decorative images).

    Args:
        content: Standardised E-Buch Markdown text to validate.
        raw_markdown: Optional Stage-1 OCR Markdown for source-aware image and page count checks.
        expected_pages: Optional expected number of physical book pages.
        table_max_cells: Optional cell threshold below which tables should be linearly resolved.
        custom_rules: Optional Buchkonferenz / document-specific ruleset text defining explicit
            heading levels (e.g. ``Überschrift 5: Aufgaben``, ``Aufgaben in Ü5``, ``Material Ü3``).

    Returns:
        A ``LintReport`` Pydantic model containing ``score``, ``passed``,
        ``error_count``, ``warning_count``, ``info_count``, ``categories``, and ``issues``.
    """
    issues: list[LintIssue] = []
    lines = content.splitlines()

    def _add_issue(rule: str, severity: str, line: int, message: str, snippet: str) -> None:
        issues.append(
            LintIssue(
                rule=rule,
                severity=severity,  # type: ignore[arg-type]
                line=line,
                message=message,
                snippet=snippet,
            )
        )

    # Parse explicit Buchkonferenz heading level assignments (1..6) from custom_rules
    custom_level_patterns: dict[int, list[re.Pattern[str]]] = {}
    allow_h1_h2_to_h4 = False
    if custom_rules and custom_rules.strip():
        level_chunks: list[tuple[int, str]] = []
        for m_sec in re.finditer(
            r"(?:^|\n)[ \t#*\-]*(?:(?:Überschrift|Ebene)\s*([1-6])|Ü([1-6]))\b[ \t]*:?[ \t]*([\s\S]*?)"
            r"(?=\n[ \t#*\-]*(?:(?:Überschrift|Ebene)\s*[1-6]|Ü[1-6])\b|\n#{1,6}\s+|\n[ \t*]*Sonstiges|\n[ \t*]*Anmerkungen|\n<Anmerkung|\Z)",
            custom_rules,
            re.IGNORECASE,
        ):
            lvl_val = int(m_sec.group(1) or m_sec.group(2))
            level_chunks.append((lvl_val, m_sec.group(3)))

        for m_inl in re.finditer(
            r"\b([A-ZÄÖÜa-zäöüß][A-ZÄÖÜa-zäöüß\- ]{1,35}?)\s+(?:(?:in|als|=|:)\s*)?(?:Überschrift\s*|Ü|H)([1-6])\b",
            custom_rules,
            re.IGNORECASE,
        ):
            term_inl = m_inl.group(1).strip(" -–—:;,()\"'„“")
            if term_inl and not re.search(r"\b(?:bis|und|oder|von|zu)\b$", term_inl, re.IGNORECASE):
                level_chunks.append((int(m_inl.group(2)), term_inl))

        for lvl_num, chunk_txt in level_chunks:
            pats = custom_level_patterns.setdefault(lvl_num, [])
            if lvl_num == 4 and re.search(
                r"Textüberschrift\w*|kapitelinterne\s+Überschrift\w*|Abschnittsüberschrift\w*|größere\s+Absätze",
                chunk_txt,
                re.IGNORECASE,
            ):
                allow_h1_h2_to_h4 = True
            if re.search(r"\b(?:Aufgaben?|Übungen?|Aufgabennummern?)\b", chunk_txt, re.IGNORECASE):
                pats.append(
                    re.compile(
                        r"^(?:Aufgaben?|Übungen?|[A-LN-Z]?\d+(?:\.\d+)*[a-z]?)[.:]?\s*$",
                        re.IGNORECASE,
                    )
                )
            if re.search(r"\b(?:Abbildungsunterschrift|Bildunterschrift)\w*", chunk_txt, re.IGNORECASE):
                pats.append(
                    re.compile(
                        r"^(?:[MBQ]\s*\d+[a-z]?|[MBQ]\s+Steckbriefe?|Abb(?:ildung)?\.?\s*\d+|Bild\s*\d+|Grafik\s*\d+|Figures?\s*\d+)\b",
                        re.IGNORECASE,
                    )
                )
            if re.search(r"\bMaterial\s+[A-Z]\b", chunk_txt):
                pats.append(re.compile(r"^Material\s+[A-Z]\b", re.IGNORECASE))
            if re.search(r"\bMaterial(?:ien)?\b(?!\s+[A-Z]\b)", chunk_txt, re.IGNORECASE):
                pats.append(re.compile(r"^Material(?:ien)?\b", re.IGNORECASE))
            for kw_m in re.finditer(
                r"(?:['\"„“]([A-ZÄÖÜa-zäöüß][A-ZÄÖÜa-zäöüß0-9 \-]{1,35}?):?['\"“”]"
                r"|\b(Randspalten?|Annotation(?:en)?|Steckbriefe?|Exkurse?|Merksatz|Merksätze|"
                r"Definition(?:en)?|Zusammenfassung(?:en)?|Quellen?|Tabellen?|Beispiele?|Infobox(?:en)?|"
                r"ÜBERBLICK|IM\s+BLICKPUNKT)\b)",
                chunk_txt,
                re.IGNORECASE,
            ):
                kw_tok = (kw_m.group(1) or kw_m.group(2) or "").strip()
                if kw_tok:
                    pats.append(re.compile(rf"^{re.escape(kw_tok)}\b", re.IGNORECASE))
            if len(chunk_txt.split()) <= 4 and re.fullmatch(r"[A-ZÄÖÜa-zäöüß][A-ZÄÖÜa-zäöüß0-9 \-]{1,35}", chunk_txt.strip()):
                pats.append(re.compile(rf"^{re.escape(chunk_txt.strip())}\b", re.IGNORECASE))

        if re.search(
            r"(?:(?:Überschrift|Ebene)\s*4|Ü\s*4)[\s\S]{0,180}(?:Textüberschrift\w*|kapitelinterne\s+Überschrift\w*|Abschnittsüberschrift\w*|größere\s+Absätze)"
            r"|(?:Textüberschrift\w*|kapitelinterne\s+Überschrift\w*|Abschnittsüberschrift\w*|größere\s+Absätze)[^\n]{0,60}(?:(?:Überschrift|Ebene)\s*4|Ü\s*4)",
            custom_rules,
            re.IGNORECASE,
        ):
            allow_h1_h2_to_h4 = True
        if re.search(
            r"[MBQ]1?\s*\+\s*Bildtitel|Den\s+Abbildungen\s+ein\s+[MBQ]\s+voranstellen",
            custom_rules,
            re.IGNORECASE,
        ):
            custom_level_patterns.setdefault(4, []).append(
                re.compile(r"^[MBQ]\s*\d+", re.IGNORECASE)
            )

    # 1. Heading Hierarchy Check
    current_level = 0
    for idx, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            is_semantic_element_heading = bool(_SEMANTIC_HEADING_RE.match(title))
            is_custom_level_heading = any(
                p.search(title) for p in custom_level_patterns.get(level, ())
            ) or (level == 4 and current_level in (1, 2) and allow_h1_h2_to_h4)
            if (
                current_level > 0
                and level > current_level + 1
                and not is_semantic_element_heading
                and not is_custom_level_heading
            ):
                _add_issue(
                    "heading_hierarchy",
                    "warning",
                    idx + 1,
                    f"Überschriftenebene übersprungen: von H{current_level} direkt zu H{level}.",
                    line.strip(),
                )
            current_level = level

    # 2. Image (<Bild>) Validation & Source-Aware Image Completeness
    open_bild_matches = list(re.finditer(r"<Bild\b[^>]*>", content, re.IGNORECASE))
    close_bild_matches = list(re.finditer(r"</Bild>", content, re.IGNORECASE))
    if len(open_bild_matches) != len(close_bild_matches):
        _add_issue(
            "image_unclosed",
            "error",
            1,
            f"Nicht geschlossene <Bild>-Tags gefunden ({len(open_bild_matches)} geöffnet, {len(close_bild_matches)} geschlossen).",
            "<Bild> ... </Bild>",
        )

    for m in re.finditer(r"<Bild\b[^>]*>(.*?)</Bild>", content, re.DOTALL | re.IGNORECASE):
        desc = m.group(1).strip()
        start_line = content[: m.start()].count("\n") + 1
        if not desc:
            _add_issue(
                "image_empty",
                "error",
                start_line,
                "Leeres <Bild>-Tag ohne Barrierefreiheits-Beschreibung gefunden.",
                m.group(0),
            )
        elif "abbildung ohne beschreibung" in desc.lower() or "bild ohne beschreibung" in desc.lower():
            _add_issue(
                "image_placeholder",
                "warning",
                start_line,
                "Platzhalter-Bildbeschreibung gefunden ('Abbildung ohne Beschreibung').",
                m.group(0),
            )
        if (
            desc
            and not CAPTION_BLOCK_RE.match(desc)
            and not re.match(r"^[^:\n]{1,60}:?\s+Beschreibung(?: mit Bildtext)?\s*:", desc, re.IGNORECASE)
            and not re.match(r"^Beschreibung(?: mit Bildtext)?\s*:", desc, re.IGNORECASE)
            and not re.search(r"\bn\.\s*ü\.|\bnicht übertragen\b", desc, re.IGNORECASE)
        ):
            _add_issue(
                "image_format",
                "info",
                start_line,
                "<Bild>-Block nicht im FIBS-Format ('<Bild> Bildart:' / 'Beschreibung mit Bildtext: …' bzw. 'Beschreibung: …' / '</Bild>').",
                m.group(0)[:120],
            )

    # Check for unconverted raw Markdown image links ![...](images/...)
    for idx, line in enumerate(lines):
        if re.search(r"!\[[^\]]*\]\((?:images/|https?://)[^)\n]+\)", line):
            _add_issue(
                "image_unconverted_markdown",
                "warning",
                idx + 1,
                "Nicht konvertierter Markdown-Bildpfad ![](...) gefunden. Muss als <Bild>-Block übertragen werden.",
                line.strip()[:120],
            )

    # Source-aware image cross-check against Stage 1 raw_markdown
    if raw_markdown:
        raw_imgs = re.findall(r"!\[[^\]]*\]\((?:images/)?[^)\n]+\)", raw_markdown)
        raw_captioned_imgs = re.findall(
            r"(?:!\[[^\]]+\]\([^)\n]+\)|!\[[^\]]*\]\([^)\n]+\)\s*\n+\s*(?:Abbildung|Abb\.|Bild|Grafik|Figure|Fig\.)\s+\d)",
            raw_markdown,
            re.IGNORECASE,
        )
        std_bild_count = len(open_bild_matches) + len(
            re.findall(r"<Anmerkung>\s*Abbildung nicht extrahiert", content, re.IGNORECASE)
        )
        if len(raw_captioned_imgs) > 0 and std_bild_count == 0 and len(raw_imgs) > 0:
            _add_issue(
                "image_omitted",
                "warning",
                1,
                f"Im Rohtext wurden {len(raw_imgs)} Abbildungen erkannt (davon {len(raw_captioned_imgs)} mit Bildunterschrift), aber im E-Buch ist kein <Bild>-Block vorhanden.",
                "<Bild> ... </Bild>",
            )

    # 2b. Unicode sub-/superscripts (H₂O, Fe³⁺) are not allowed – use _ / ^ notation (H_2O, Fe^{3+})
    for idx, line in enumerate(lines):
        if re.search(r"[₀-₉₊₋]|[⁰⁴-⁹⁺⁻]|[A-Za-z0-9][²³]", line):
            _add_issue(
                "unicode_script",
                "info",
                idx + 1,
                "Unicode-Hoch-/Tiefstellung gefunden. Tiefstellung mit _ und Hochstellung mit ^ schreiben (z.B. H_2O, Fe^{3+}).",
                line.strip()[:120],
            )

    # 3. Footnote Integrity ({n} vs <Anmerkung> n ... </Anmerkung>) & <Anmerkung> Tag Balance
    open_anm = len(re.findall(r"<Anmerkung\b[^>]*>", content, re.IGNORECASE))
    close_anm = len(re.findall(r"</Anmerkung>", content, re.IGNORECASE))
    if open_anm != close_anm:
        _add_issue(
            "anmerkung_unbalanced",
            "error",
            1,
            f"Nicht geschlossene <Anmerkung>-Tags gefunden ({open_anm} geöffnet, {close_anm} geschlossen).",
            "<Anmerkung> ... </Anmerkung>",
        )

    # Exclude math tags, LaTeX commands (\f{1}{2}, \s{3}, \frac{1}{2}, \xra{...}), and _{n}/^{n}/}{n} from footnote search
    content_without_math = re.sub(r"<L\b[^>]*>.*?</L>", "", content, flags=re.DOTALL | re.IGNORECASE)
    content_without_math = re.sub(r"\$\$.*?\$\$", "", content_without_math, flags=re.DOTALL)
    content_without_math = re.sub(r"\$.*?\$", "", content_without_math, flags=re.DOTALL)
    for _ in range(4):
        content_without_math = re.sub(
            r"\\[a-zA-Z]+(?:\s*\[[^\]]*\])*(?:\s*\{[^{}]*\})+",
            "",
            content_without_math,
        )
    inline_refs = set(re.findall(r"(?<![_\^\\}\]])\{(\d+)\}", content_without_math))
    note_defs = set()
    for m in re.finditer(r"<Anmerkung\b[^>]*>\s*(\d+)\s+(.*?)</Anmerkung>", content, re.DOTALL | re.IGNORECASE):
        note_defs.add(m.group(1))

    for ref in inline_refs:
        if ref not in note_defs:
            _add_issue(
                "footnote_missing_definition",
                "warning",
                1,
                f"Fußnotenverweis {{{ref}}} im Text hat keine zugehörige <Anmerkung> {ref} ... </Anmerkung> Definition.",
                f"{{{ref}}}",
            )

    # 4. List Formatting (Tab separator after bullet/number, outside <Bild> blocks)
    in_bild_list_check = False
    for idx, line in enumerate(lines):
        if re.search(r"<Bild\b", line, re.IGNORECASE):
            in_bild_list_check = True
        if not in_bild_list_check:
            if re.match(r"^[\-\*]\s+[^\t]", line) and not re.match(r"^[\-\*]\t", line):
                _add_issue(
                    "list_delimiter",
                    "info",
                    idx + 1,
                    "Listenpunkt muss nach dem Aufzählungszeichen einen Tabulator (\\t) statt eines Leerzeichens enthalten.",
                    line.strip(),
                )
            elif re.match(r"^\d+[\.\)]\s+[^\t]", line) and not re.match(r"^\d+[\.\)]\t", line):
                _add_issue(
                    "list_delimiter",
                    "info",
                    idx + 1,
                    "Nummerierte Liste muss nach der Ziffer einen Tabulator (\\t) statt eines Leerzeichens enthalten.",
                    line.strip(),
                )
        if re.search(r"</Bild>", line, re.IGNORECASE):
            in_bild_list_check = False

    # 5. Math Formula Tags (<L> and </L>)
    open_math = len(re.findall(r"<L\b[^>]*>", content, re.IGNORECASE))
    close_math = len(re.findall(r"</L>", content, re.IGNORECASE))
    if open_math != close_math:
        _add_issue(
            "math_unbalanced",
            "error",
            1,
            f"Unausgeglichene Formel-Tags <L> und </L> ({open_math} geöffnet, {close_math} geschlossen).",
            "<L> ... </L>",
        )
    elif open_math > 0:
        _add_issue(
            "math_legacy_l_tag",
            "info",
            1,
            "Veraltete Formel-Tags <L>...</L> gefunden (im FIBS-Standard 09/2025 ohne Begrenzungs-Tags übertragen).",
            "<L> ... </L>",
        )

    # 6. Page Number Formatting, Crash Hazard, Monotonicity & Completeness (FIBS Section 11.2)
    if "((...))" in content:
        _add_issue(
            "page_number_crash_hazard",
            "error",
            1,
            "Verbotene Zeichenfolge '((...))' gefunden (führt in Word bei Fußnoten zum Programmabsturz, FIBS Abschn. 11.2).",
            "((...))",
        )

    from backend.services.extraction_service import roman_to_int

    page_markers_with_lines: list[tuple[str, int]] = []
    for idx, line in enumerate(lines):
        line_clean = line.strip()
        m_unstd = re.match(r"^(?:Seite|Page)\s+(\d+|[IVXLCDMivxlcdm]+)$", line_clean, re.IGNORECASE)
        if m_unstd and (m_unstd.group(1).isdigit() or roman_to_int(m_unstd.group(1)) is not None):
            _add_issue(
                "page_number_format",
                "warning",
                idx + 1,
                f"Nicht standardisierte Seitenzahl gefunden ('{line_clean}'). Sollte als '((X))' formatiert sein.",
                line_clean,
            )
        m_pg = re.match(
            r"^\(\((\d+|[IVXLCDMivxlcdm]+)(?:\s*[-–]\s*(\d+|[IVXLCDMivxlcdm]+))?\)\)(?:\s*/\s*\(\((\d+|[IVXLCDMivxlcdm]+)\)\))*$",
            line_clean,
        )
        if m_pg:
            if m_pg.group(2):
                page_markers_with_lines.append((m_pg.group(1), idx + 1))
                page_markers_with_lines.append((m_pg.group(2), idx + 1))
            else:
                for pg_tok in re.findall(r"\(\((\d+|[IVXLCDMivxlcdm]+)\)\)", line_clean):
                    page_markers_with_lines.append((pg_tok, idx + 1))

    for i in range(1, len(page_markers_with_lines)):
        prev_pg, _ = page_markers_with_lines[i - 1]
        curr_pg, curr_line = page_markers_with_lines[i]
        if curr_pg.lower() == prev_pg.lower():
            _add_issue(
                "page_number_duplicate",
                "warning",
                curr_line,
                f"Doppelte aufeinanderfolgende Seitenzahl '(({curr_pg}))' gefunden (jede Buchseite darf nur einmal markiert werden).",
                f"(({curr_pg}))",
            )
        elif prev_pg.isdigit() and curr_pg.isdigit():
            if int(curr_pg) < int(prev_pg):
                _add_issue(
                    "page_number_non_monotonic",
                    "warning",
                    curr_line,
                    f"Nicht-monotone Seitenzahlreihenfolge: '(({curr_pg}))' folgt auf '(({prev_pg}))'.",
                    f"(({prev_pg})) -> (({curr_pg}))",
                )
        elif not prev_pg.isdigit() and not curr_pg.isdigit():
            prev_r = roman_to_int(prev_pg)
            curr_r = roman_to_int(curr_pg)
            if prev_r is not None and curr_r is not None and curr_r < prev_r:
                _add_issue(
                    "page_number_non_monotonic",
                    "warning",
                    curr_line,
                    f"Nicht-monotone Seitenzahlreihenfolge: '(({curr_pg}))' folgt auf '(({prev_pg}))'.",
                    f"(({prev_pg})) -> (({curr_pg}))",
                )

    raw_unique_pgs: list[str] = []
    if raw_markdown:
        from backend.services.fibs_postprocess import split_markdown_pages

        for r_seg in split_markdown_pages(raw_markdown):
            if not r_seg.page:
                continue
            m_rh = re.match(r"^(\(\([^\n]+\)[ \t]*)(?:\n([\s\S]*))?$", r_seg.text)
            r_hdr = m_rh.group(1) if m_rh else f"(({r_seg.page}))"
            r_body = (m_rh.group(2) if m_rh else "") or ""
            if not r_body.strip():
                continue
            for r_tok in re.findall(r"\(\((\d+|[IVXLCDMivxlcdm]+)\)\)", r_hdr):
                r_low = r_tok.lower()
                if r_low not in raw_unique_pgs:
                    raw_unique_pgs.append(r_low)
        if not raw_unique_pgs:
            raw_unique_pgs = list(
                dict.fromkeys(
                    p.lower()
                    for p in re.findall(r"\(\((\d+|[IVXLCDMivxlcdm]+)\)\)", raw_markdown)
                )
            )

    target_expected_pages = expected_pages
    if target_expected_pages is None and len(raw_unique_pgs) >= 2:
        target_expected_pages = len(raw_unique_pgs)
    if target_expected_pages and target_expected_pages >= 2:
        unique_pred_pgs = list(dict.fromkeys(p.lower() for p, _ in page_markers_with_lines))
        matched_raw_source = bool(raw_unique_pgs and len(unique_pred_pgs) >= len(raw_unique_pgs))
        if len(unique_pred_pgs) < target_expected_pages and not matched_raw_source:
            _add_issue(
                "page_number_missing",
                "warning",
                1,
                f"Fehlende Seitenmarker: {len(unique_pred_pgs)} von {target_expected_pages} erwarteten Buchseiten markiert.",
                f"{len(unique_pred_pgs)}/{target_expected_pages} Seiten",
            )

    # 7. Structural Tag Balance (<Rahmen>, <Tabelle>, <Lückentext>) & Table Resolution Checks (FIBS Section 7)
    open_rahmen = len(re.findall(r"<Rahmen\b[^>]*>", content, re.IGNORECASE))
    close_rahmen = len(re.findall(r"</Rahmen>", content, re.IGNORECASE))
    if open_rahmen != close_rahmen:
        _add_issue(
            "rahmen_unbalanced",
            "error",
            1,
            f"Nicht geschlossene <Rahmen>-Tags gefunden ({open_rahmen} geöffnet, {close_rahmen} geschlossen).",
            "<Rahmen> ... </Rahmen>",
        )

    open_tab = len(re.findall(r"<Tabelle\b[^>]*>", content, re.IGNORECASE))
    close_tab = len(re.findall(r"</Tabelle>", content, re.IGNORECASE))
    if open_tab != close_tab:
        _add_issue(
            "tabelle_unbalanced",
            "error",
            1,
            f"Nicht geschlossene <Tabelle>-Tags gefunden ({open_tab} geöffnet, {close_tab} geschlossen).",
            "<Tabelle> ... </Tabelle>",
        )

    if re.search(r"<table\b[^>]*>", content, re.IGNORECASE):
        _add_issue(
            "html_table_unconverted",
            "error",
            1,
            "Nicht konvertierte HTML-Tabelle (<table>) gefunden. Tabellen müssen als <Tabelle>...</Tabelle> oder aufgelöster Text übertragen werden.",
            "<table> ... </table>",
        )

    if table_max_cells is not None and table_max_cells > 0:
        for m_tab in re.finditer(r"<Tabelle\b[^>]*>(.*?)</Tabelle>", content, re.DOTALL | re.IGNORECASE):
            tab_inner = m_tab.group(1).strip()
            tab_rows = [
                r
                for r in tab_inner.splitlines()
                if r.strip() and not re.match(r"^[\s\|:\-]+$", r.strip().strip("|"))
            ]
            cell_count = 0
            for r in tab_rows:
                if "\t" in r:
                    cell_count += len([c for c in r.split("\t") if c.strip()])
                elif "|" in r:
                    cell_count += len([c for c in r.strip("|").split("|") if c.strip()])
                else:
                    cell_count += 1
            if 0 < cell_count <= table_max_cells:
                start_line = content[: m_tab.start()].count("\n") + 1
                _add_issue(
                    "table_unresolved_small",
                    "info",
                    start_line,
                    f"Kleine Tabelle mit {cell_count} Zellen (Schwellenwert <= {table_max_cells}) sollte in linearen Fließtext aufgelöst werden.",
                    m_tab.group(0)[:100],
                )

    open_luecke = len(re.findall(r"<Lückentext\b[^>]*>", content, re.IGNORECASE))
    close_luecke = len(re.findall(r"</Lückentext>", content, re.IGNORECASE))
    if open_luecke != close_luecke:
        _add_issue(
            "lueckentext_unbalanced",
            "error",
            1,
            f"Nicht geschlossene <Lückentext>-Tags gefunden ({open_luecke} geöffnet, {close_luecke} geschlossen).",
            "<Lückentext> ... </Lückentext>",
        )

    # 8. FIBS Typography, Degree & Emphasis Rules (Section 7.3, 8.1, 10)
    has_emphasis_legend = bool(
        _EMPHASIS_LEGEND_ANM_RE.search(content)
        or (
            re.search(r"\bfett", content, re.IGNORECASE)
            and re.search(r"\bkursiv", content, re.IGNORECASE)
        )
    )
    in_bild_block = False
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if re.search(r"<Bild\b", stripped, re.IGNORECASE):
            in_bild_block = True
        if not stripped:
            if re.search(r"</Bild>", stripped, re.IGNORECASE):
                in_bild_block = False
            continue
        if not in_bild_block and ("©" in stripped or "®" in stripped):
            _add_issue(
                "fibs_copyright_symbol",
                "info",
                idx + 1,
                "Symbol © oder ® gefunden (wird gemäß FIBS Abschn. 8.1 ersatzlos gestrichen).",
                stripped[:120],
            )
        if re.search(r"</Bild>", stripped, re.IGNORECASE):
            in_bild_block = False
        line_no_code = UNIT_PERCENT_PROTECTED_RE.sub("", stripped)
        if re.search(r"\^\s*\{?\\circ\}?", line_no_code):
            _add_issue(
                "fibs_degree_latex",
                "info",
                idx + 1,
                "LaTeX-Grad-Notation ('^\\circ') gefunden. Gemäß FIBS Abschn. 8.1 direkt als '°' übertragen (z. B. '80 °C', '90°').",
                stripped[:120],
            )
        if not has_emphasis_legend and _UNANNOUNCED_PCT_EMPH_RE.search(line_no_code):
            _add_issue(
                "fibs_unannounced_percent_emphasis",
                "info",
                idx + 1,
                "Unangekündigte %-Hervorhebung gefunden. Gemäß FIBS Abschn. 10 standardmäßig _Wort_ verwenden (oder per <Anmerkung> erläutern).",
                stripped[:120],
            )
        line_no_math = re.sub(r"\$[^\$\n]+\$", "", line_no_code)
        if re.search(r"_{4,}", line_no_math):
            _add_issue(
                "fibs_raw_fill_in_blanks",
                "info",
                idx + 1,
                "Nicht standardisierte Ausfüll-Linie ('____') gefunden. Muss gemäß FIBS Abschn. 7.3 als '_..._' übertragen werden.",
                stripped[:120],
            )
        if not stripped.startswith("#") and re.search(r"\*\*[^*\n]+\*\*", line_no_math):
            _add_issue(
                "fibs_markdown_bold",
                "info",
                idx + 1,
                "Markdown-Fettdruck (**...**) gefunden. Im FIBS-Standard wird Hervorhebung als _Wort_ (oder *Wort* bei Differenzierung) übertragen.",
                stripped[:120],
            )

    errors = sum(1 for i in issues if i.severity == "error")
    warnings = sum(1 for i in issues if i.severity == "warning")
    infos = sum(1 for i in issues if i.severity == "info")

    deductions = (errors * 20) + (warnings * 10) + (infos * 2)
    score = max(0, 100 - deductions)

    categories: dict[str, bool] = {
        "headings": not any(i.rule == "heading_hierarchy" for i in issues),
        "images": not any("image" in i.rule for i in issues),
        "footnotes": not any("footnote" in i.rule or "anmerkung" in i.rule for i in issues),
        "lists": not any(i.rule == "list_delimiter" for i in issues),
        "math": not any(
            i.rule in ("math_unbalanced", "math_legacy_l_tag", "fibs_degree_latex")
            for i in issues
        ),
        "pages": not any("page_number" in i.rule for i in issues),
        "boxes": not any("rahmen" in i.rule or "lueckentext" in i.rule for i in issues),
        "tables": not any("tabelle" in i.rule or "table" in i.rule for i in issues),
    }

    return LintReport(
        score=score,
        passed=errors == 0 and warnings == 0,
        error_count=errors,
        warning_count=warnings,
        info_count=infos,
        categories=categories,
        issues=issues,
    )


def autofix_markdown(content: str) -> tuple[str, list[str]]:
    r"""Apply deterministic corrections to resolve common E-Buch 2025 accessibility issues.

    Corrections applied:
      1. Replaces spaces after list bullets/numbers with required tabulators (``\\t``).
      2. Adjusts skipped heading hierarchy levels to be sequential (e.g., H1 -> H3 to H1 -> H2).
      3. Normalizes non-standard page numbers (e.g., ``Seite 45`` -> ``((45))``).
      4. Strips legacy ``<L>`` math tags into bare FIBS LaTeX and normalizes ``°`` / ``%`` spacing.
      5. Strips copyright symbols outside ``<Bild>`` blocks, converts ``____`` to ``_..._``,
         and normalizes ``**bold**`` or unannounced ``%italic%`` to ``_..._``.

    Args:
        content: Markdown content to repair.

    Returns:
        A tuple ``(fixed_markdown, applied_fix_descriptions)``.
    """
    applied_fixes: list[str] = []
    lines = content.splitlines()
    fixed_lines: list[str] = []
    has_emphasis_legend = bool(
        _EMPHASIS_LEGEND_ANM_RE.search(content)
        or (
            re.search(r"\bfett", content, re.IGNORECASE)
            and re.search(r"\bkursiv", content, re.IGNORECASE)
        )
    )

    current_heading_level = 0
    in_bild_autofix = False

    for idx, line in enumerate(lines):
        modified_line = line
        stripped = line.strip()
        if re.search(r"<Bild\b", stripped, re.IGNORECASE):
            in_bild_autofix = True

        page_match = re.match(r"^(?:Seite|Page)\s+(\d+)$", stripped, re.IGNORECASE)
        if page_match:
            p_num = page_match.group(1)
            fixed_lines.append("")
            fixed_lines.append(f"(({p_num}))")
            fixed_lines.append("")
            applied_fixes.append(
                f"Zeile {idx + 1}: Seitenzahl 'Seite {p_num}' zu standardisiertem '(({p_num}))' konvertiert."
            )
            continue

        bullet_match = re.match(r"^(\s*)([\-\*])[ ]+([^\t].*)$", modified_line) if not in_bild_autofix else None
        num_match = re.match(r"^(\s*)(\d+[\.\)])[ ]+([^\t].*)$", modified_line) if not in_bild_autofix else None

        if bullet_match:
            indent, bullet, rest = bullet_match.groups()
            modified_line = f"{indent}-\t{rest}"
            applied_fixes.append(
                f"Zeile {idx + 1}: Tabulator (\\t) nach Aufzählungszeichen '{bullet}' eingefügt."
            )
        elif num_match:
            indent, num, rest = num_match.groups()
            modified_line = f"{indent}{num}\t{rest}"
            applied_fixes.append(
                f"Zeile {idx + 1}: Tabulator (\\t) nach Ziffer '{num}' eingefügt."
            )

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", modified_line)
        if heading_match:
            hashes, title = heading_match.groups()
            level = len(hashes)
            is_semantic_element_heading = bool(_SEMANTIC_HEADING_RE.match(title.strip()))
            if (
                current_heading_level > 0
                and level > current_heading_level + 1
                and not is_semantic_element_heading
            ):
                target_level = current_heading_level + 1
                modified_line = f"{'#' * target_level} {title}"
                applied_fixes.append(
                    f"Zeile {idx + 1}: Überschrift 'H{level}' auf logische Ebene 'H{target_level}' korrigiert."
                )
                current_heading_level = target_level
            else:
                current_heading_level = level

        if "<L>" in modified_line or "</L>" in modified_line or re.search(r"</?L\b", modified_line, re.IGNORECASE):
            modified_line = re.sub(
                r"<L\b[^>]*>\s*(.*?)\s*</L>", r"\1", modified_line, flags=re.IGNORECASE
            )
            modified_line = re.sub(r"<\/?L\b[^>]*>", "", modified_line, flags=re.IGNORECASE)
            applied_fixes.append(
                f"Zeile {idx + 1}: Veraltete <L> Formel-Tags in direktes FIBS-LaTeX umgewandelt."
            )

        if not in_bild_autofix and ("©" in modified_line or "®" in modified_line):
            modified_line = re.sub(r"\s*[©®]", "", modified_line)
            applied_fixes.append(f"Zeile {idx + 1}: Symbol © / ® gemäß FIBS Abschn. 8.1 entfernt.")
        if re.search(r"</Bild>", stripped, re.IGNORECASE):
            in_bild_autofix = False

        if re.search(r"_{4,}", modified_line):
            modified_line = re.sub(r"_{4,}", "_..._", modified_line)
            applied_fixes.append(f"Zeile {idx + 1}: Ausfüll-Linie '____' zu '_..._' standardisiert.")

        if not modified_line.lstrip().startswith("#") and re.search(
            r"\*\*[^*\n]+\*\*", modified_line
        ):
            modified_line = re.sub(r"\*\*([^*\n]+)\*\*", r"_\1_", modified_line)
            applied_fixes.append(
                f"Zeile {idx + 1}: Markdown-Fettdruck (**...**) zu FIBS-Hervorhebung (_..._) umgewandelt."
            )

        if not has_emphasis_legend and _UNANNOUNCED_PCT_EMPH_RE.search(modified_line):
            modified_line = _UNANNOUNCED_PCT_EMPH_RE.sub(r"_\1_", modified_line)
            applied_fixes.append(
                f"Zeile {idx + 1}: Unangekündigte %-Hervorhebung zu _..._ standardisiert."
            )

        fixed_lines.append(modified_line)

    result_text = "\n".join(fixed_lines)

    deduped_pages = deduplicate_page_numbers(result_text)
    if deduped_pages != result_text:
        applied_fixes.append("Doppelte aufeinanderfolgende Seitenzahlen ((num)) bereinigt.")
        result_text = deduped_pages

    converted = convert_unicode_scripts(result_text)
    if converted != result_text:
        applied_fixes.append("Unicode-Hoch-/Tiefstellungen in _/^-Schreibweise umgewandelt.")
        result_text = converted

    normalized_units = normalize_fibs_units_and_percent(result_text)
    if normalized_units != result_text:
        applied_fixes.append("Grad- (° / °C) und Prozentangaben (%) gemäß FIBS Abschn. 8.1 standardisiert.")
        result_text = normalized_units

    normalized = normalize_bild_tags(result_text)
    if normalized != result_text:
        applied_fixes.append(
            "<Bild>-Blöcke in das mehrzeilige FIBS-Format (Bildart / Beschreibung) überführt."
        )
        result_text = normalized

    restored_stars = restore_false_positive_trailing_asterisks(result_text)
    if restored_stars != result_text:
        applied_fixes.append("Falsch umgewandelte Fußnoten-Sterne (z.B. 2030* 2040*) wiederhergestellt.")
        result_text = restored_stars

    result_text = re.sub(r"\n{3,}", "\n\n", result_text)

    return result_text, applied_fixes
