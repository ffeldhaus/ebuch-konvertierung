#!/usr/bin/env python3
"""Synchronizes local FIBS PDF and DOCX reference rules in ``assets/rules/`` to Markdown.

Converts ``.pdf`` (via ``pypdfium2``) and ``.docx`` (via ``python-docx``) documents in
``assets/rules/`` into clean, ASCII-named ``.md`` siblings tracked by SHA-256 digests in
``assets/rules/.rules_manifest.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RULES_DIR = PROJECT_ROOT / "assets" / "rules"
MANIFEST_FILENAME = ".rules_manifest.json"
SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx"})

_UMLAUT_ASCII_MAP = str.maketrans({
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "Ä": "Ae",
    "Ö": "Oe",
    "Ü": "Ue",
    "ß": "ss",
})

_DECOMPOSED_UMLAUT_PAIRS: tuple[tuple[str, str], ...] = (
    ("¨a", "ä"),
    ("a¨", "ä"),
    ("¨o", "ö"),
    ("o¨", "ö"),
    ("¨u", "ü"),
    ("u¨", "ü"),
    ("¨A", "Ä"),
    ("A¨", "Ä"),
    ("¨O", "Ö"),
    ("O¨", "Ö"),
    ("¨U", "Ü"),
    ("U¨", "Ü"),
)

_FIBS_RUNNING_HEADER_RE = re.compile(
    r"(?m)^[ \t]*Förderzentrum[ \t]+für[ \t]+die[ \t]*\n+"
    r"[ \t]*integrative[ \t]*\n+"
    r"[ \t]*Beschulung[ \t]+blinder[ \t]+und[ \t]+sehbehinderter[ \t]*\n+"
    r"[ \t]*SuS[ \t]*(?:\n+|$)"
)


def ascii_markdown_filename(source_name: str) -> str:
    """Maps a source PDF/DOCX filename to a deterministic ASCII-safe ``.md`` filename.

    Args:
        source_name: Source filename (may be macOS NFD or Linux NFC).

    Returns:
        Normalized ASCII ``.md`` filename (e.g. ``Uebertragungsregeln_Stand_09_2025.md``).
    """
    nfc_stem = unicodedata.normalize("NFC", Path(source_name).stem)
    transliterated = nfc_stem.translate(_UMLAUT_ASCII_MAP)
    ascii_stem = (
        unicodedata.normalize("NFKD", transliterated)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    cleaned_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_stem).strip("_")
    return f"{cleaned_stem or 'rules'}.md"


def sha256_file(path: Path) -> str:
    """Computes the hex SHA-256 digest of a file on disk.

    Args:
        path: Path to the file.

    Returns:
        Lowercase hexadecimal SHA-256 digest string.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


_VOWEL_TO_UMLAUT = {
    "a": "ä",
    "o": "ö",
    "u": "ü",
    "A": "Ä",
    "O": "Ö",
    "U": "Ü",
}


def _extract_page_text_with_ot1_umlauts(textpage: Any) -> str:
    """Extracts page text and reattaches floating OT1 ``¨`` glyphs via char bounding boxes.

    Args:
        textpage: Open ``pypdfium2`` ``PdfTextPage`` handle.

    Returns:
        Raw page text with displaced OT1 diaeresis glyphs merged onto their base vowels.
    """
    raw_page = textpage.get_text_range() or ""
    if "¨" not in raw_page:
        return raw_page

    n_chars = textpage.count_chars()
    if n_chars <= 0:
        return raw_page

    chars = [textpage.get_text_range(i, 1) for i in range(n_chars)]
    umlaut_indices = [i for i, ch in enumerate(chars) if ch == "¨"]
    if not umlaut_indices:
        return raw_page

    vowel_boxes: list[tuple[int, float, float]] = []
    for idx, ch in enumerate(chars):
        if ch in _VOWEL_TO_UMLAUT:
            left, bottom, right, top = textpage.get_charbox(idx)
            vowel_boxes.append((idx, (left + right) * 0.5, (bottom + top) * 0.5))

    used_vowels: set[int] = set()
    for u_idx in umlaut_indices:
        u_left, u_bottom, u_right, u_top = textpage.get_charbox(u_idx)
        u_cx = (u_left + u_right) * 0.5
        u_cy = (u_bottom + u_top) * 0.5
        best_v_idx: int | None = None
        best_dist = 999.0
        for v_idx, v_cx, v_cy in vowel_boxes:
            if v_idx in used_vowels:
                continue
            dx = abs(u_cx - v_cx)
            dy = u_cy - v_cy
            if dx <= 5.5 and -2.0 <= dy <= 12.0:
                dist = dx + abs(dy) * 0.25
                if dist < best_dist:
                    best_dist = dist
                    best_v_idx = v_idx
        if best_v_idx is not None:
            used_vowels.add(best_v_idx)
            chars[best_v_idx] = _VOWEL_TO_UMLAUT[chars[best_v_idx]]
            chars[u_idx] = ""
            if u_idx > 0 and chars[u_idx - 1] == " ":
                nxt = chars[u_idx + 1] if u_idx + 1 < n_chars else "\n"
                if nxt in ("\r", "\n", " "):
                    chars[u_idx - 1] = ""

    return "".join(chars)


def normalize_pdf_artifacts(text: str) -> str:
    """Normalizes decomposed LaTeX PDF umlauts and math symbol artifacts.

    Args:
        text: Raw text extracted from a PDF page.

    Returns:
        Cleaned UTF-8 text with composed umlauts and ASCII tilde/caret/degree symbols.
    """
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").replace("\ufffe", "-")
    cleaned = unicodedata.normalize("NFC", cleaned)
    for src, dst in _DECOMPOSED_UMLAUT_PAIRS:
        if src in cleaned:
            cleaned = cleaned.replace(src, dst)
    cleaned = (
        cleaned.replace("\u223c", "~")
        .replace("\u02c6", "^")
        .replace("\u25e6", "°")
    )
    return cleaned


def convert_pdf_to_markdown(pdf_path: Path) -> str:
    """Extracts a FIBS reference PDF into clean page-marked Markdown.

    Args:
        pdf_path: Path to the source ``.pdf`` file.

    Returns:
        Markdown string with ``<!-- Seite N -->`` markers and stripped running headers/footers.
    """
    title = unicodedata.normalize("NFC", pdf_path.stem).replace("_", " ")
    sections: list[str] = [f"# {title}"]
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        for idx in range(len(doc)):
            page_num = idx + 1
            page = doc[idx]
            textpage = page.get_textpage()
            try:
                raw_page = _extract_page_text_with_ot1_umlauts(textpage)
            finally:
                textpage.close()
                page.close()

            page_text = normalize_pdf_artifacts(raw_page)
            page_text = _FIBS_RUNNING_HEADER_RE.sub("", page_text)

            lines = [ln.rstrip() for ln in page_text.splitlines()]
            while lines and not lines[0].strip():
                lines.pop(0)
            while lines and not lines[-1].strip():
                lines.pop()

            # Strip standalone page-footer or page-header number matching page_num or generic footer digits
            if lines and re.fullmatch(r"(?:Seite\s+)?\d{1,3}(?:\s+von\s+\d{1,3})?", lines[-1].strip()):
                lines.pop()
            while lines and not lines[-1].strip():
                lines.pop()

            body = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
            if body:
                sections.append(f"<!-- Seite {page_num} -->\n\n{body}")
            else:
                sections.append(f"<!-- Seite {page_num} -->")
    finally:
        doc.close()

    return "\n\n".join(sections) + "\n"


def _format_paragraph_runs(paragraph: Paragraph, *, allow_bold: bool = True) -> str:
    """Formats inline runs of a DOCX paragraph, coalescing contiguous bold spans.

    Args:
        paragraph: ``python-docx`` ``Paragraph`` instance.
        allow_bold: Whether bold runs should be wrapped in ``**...**``.

    Returns:
        Formatted inline Markdown string.
    """
    if not paragraph.runs:
        return paragraph.text.strip()

    segments: list[tuple[bool, str]] = []
    for run in paragraph.runs:
        txt = run.text
        if not txt:
            continue
        is_bold = bool(allow_bold and run.bold)
        if segments and segments[-1][0] == is_bold:
            segments[-1] = (is_bold, segments[-1][1] + txt)
        else:
            segments.append((is_bold, txt))

    out_parts: list[str] = []
    for is_bold, seg_txt in segments:
        if is_bold and seg_txt.strip():
            lead_ws = seg_txt[: len(seg_txt) - len(seg_txt.lstrip())]
            trail_ws = seg_txt[len(seg_txt.rstrip()) :]
            core = seg_txt.strip()
            out_parts.append(f"{lead_ws}**{core}**{trail_ws}")
        else:
            out_parts.append(seg_txt)
    return "".join(out_parts).strip()


def convert_docx_to_markdown(docx_path: Path) -> str:
    r"""Extracts a FIBS reference DOCX into structured Markdown.

    Preserves Heading 1–4 as ``##``–``#####``, bold runs (``**...**``), list items
    (``-\t...``), and tables (``<Tabelle>...</Tabelle>``).

    Args:
        docx_path: Path to the source ``.docx`` file.

    Returns:
        Markdown representation of the DOCX document.
    """
    doc = Document(str(docx_path))
    title = unicodedata.normalize("NFC", docx_path.stem).replace("_", " ")
    blocks: list[str] = [f"# {title}"]

    heading_map = {
        "title": "#",
        "titel": "#",
        "heading 1": "##",
        "überschrift 1": "##",
        "heading 2": "###",
        "überschrift 2": "###",
        "heading 3": "####",
        "überschrift 3": "####",
        "heading 4": "#####",
        "überschrift 4": "#####",
    }

    for child in doc.element.body.iterchildren():
        if isinstance(child, CT_P):
            para = Paragraph(child, doc)
            style_name = (para.style.name if para.style and para.style.name else "").strip().lower()
            heading_prefix = heading_map.get(style_name)
            if heading_prefix is None:
                m_h = re.match(r"^(?:heading|überschrift)\s*([1-4])\b", style_name)
                if m_h:
                    heading_prefix = "#" * (int(m_h.group(1)) + 1)

            if heading_prefix is not None:
                plain = _format_paragraph_runs(para, allow_bold=False)
                if plain:
                    blocks.append(f"{heading_prefix} {plain}")
                continue

            formatted = _format_paragraph_runs(para, allow_bold=True)
            if not formatted:
                continue

            has_num_pr = bool(para._p.pPr is not None and para._p.pPr.numPr is not None)
            is_list_style = style_name.startswith(("list", "aufzählung", "listenabsatz"))
            if has_num_pr or is_list_style:
                cleaned_item = re.sub(r"^[•\-*]\s+", "", formatted)
                blocks.append(f"-\t{cleaned_item}")
            elif re.match(r"^[•]\s+", formatted):
                cleaned_item = re.sub(r"^[•]\s+", "", formatted)
                blocks.append(f"-\t{cleaned_item}")
            else:
                blocks.append(formatted)

        elif isinstance(child, CT_Tbl):
            table = Table(child, doc)
            row_lines: list[str] = []
            for row in table.rows:
                cells = [
                    re.sub(r"\s+", " ", cell.text.replace("\r", " ").replace("\n", " ")).strip()
                    for cell in row.cells
                ]
                if any(cells):
                    row_lines.append("\t".join(cells))
            if row_lines:
                blocks.append("<Tabelle>\n" + "\n".join(row_lines) + "\n</Tabelle>")

    return "\n\n".join(blocks) + "\n"


def sync_rules_markdown(
    rules_dir: Path = DEFAULT_RULES_DIR,
    *,
    force: bool = False,
    check_only: bool = False,
) -> list[str]:
    """Synchronizes ``.pdf`` and ``.docx`` files in ``rules_dir`` to ``.md`` siblings.

    Args:
        rules_dir: Directory containing FIBS reference ``.pdf`` / ``.docx`` files.
        force: Regenerate all ``.md`` files regardless of cached SHA-256 digests.
        check_only: Verify freshness without writing ``.md`` files or updating the manifest.

    Returns:
        List of generated (or stale, when ``check_only=True``) Markdown filenames.
    """
    if not rules_dir.is_dir():
        return []

    source_files = sorted(
        (
            p
            for p in rules_dir.iterdir()
            if p.is_file()
            and p.suffix.lower() in SUPPORTED_EXTENSIONS
            and not p.name.startswith("~$")
        ),
        key=lambda p: unicodedata.normalize("NFC", p.name),
    )
    if not source_files:
        return []

    manifest_path = rules_dir / MANIFEST_FILENAME
    manifest: dict[str, dict[str, str]] = {}
    if manifest_path.is_file():
        try:
            loaded: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                manifest = {
                    unicodedata.normalize("NFC", str(k)): v
                    for k, v in loaded.items()
                    if isinstance(v, dict)
                }
        except (OSError, json.JSONDecodeError):
            manifest = {}

    changed_md_files: list[str] = []
    updated_manifest: dict[str, dict[str, str]] = {}
    manifest_dirty = False

    for src_path in source_files:
        src_key = unicodedata.normalize("NFC", src_path.name)
        md_name = ascii_markdown_filename(src_key)
        md_path = rules_dir / md_name
        src_hash = sha256_file(src_path)
        prev_entry = manifest.get(src_key)

        md_exists = md_path.is_file()
        current_md_hash = sha256_file(md_path) if md_exists else ""
        is_up_to_date = (
            not force
            and prev_entry is not None
            and prev_entry.get("sha256") == src_hash
            and prev_entry.get("markdown_file") == md_name
            and md_exists
            and prev_entry.get("markdown_sha256") == current_md_hash
        )

        if is_up_to_date:
            updated_manifest[src_key] = {
                "sha256": src_hash,
                "markdown_file": md_name,
                "markdown_sha256": current_md_hash,
            }
            continue

        changed_md_files.append(md_name)
        if check_only:
            continue

        if src_path.suffix.lower() == ".pdf":
            md_content = convert_pdf_to_markdown(src_path)
        else:
            md_content = convert_docx_to_markdown(src_path)

        md_path.write_text(md_content, encoding="utf-8")
        new_md_hash = sha256_file(md_path)
        updated_manifest[src_key] = {
            "sha256": src_hash,
            "markdown_file": md_name,
            "markdown_sha256": new_md_hash,
        }
        manifest_dirty = True

    if check_only:
        if set(manifest.keys()) != {unicodedata.normalize("NFC", p.name) for p in source_files}:
            for extra_key in sorted(set(manifest.keys()) - {unicodedata.normalize("NFC", p.name) for p in source_files}):
                changed_md_files.append(manifest[extra_key].get("markdown_file", extra_key))
        return changed_md_files

    if manifest_dirty or manifest != updated_manifest or not manifest_path.is_file():
        manifest_path.write_text(
            json.dumps(updated_manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    return changed_md_files


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``python -m scripts.sync_rules_markdown``.

    Args:
        argv: Optional CLI argument list.

    Returns:
        Process exit code (``0`` on success, ``1`` when ``--check`` detects stale files).
    """
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(
        description="Synchronize FIBS PDF/DOCX reference documents in assets/rules/ to Markdown."
    )
    parser.add_argument(
        "--rules-dir",
        type=Path,
        default=DEFAULT_RULES_DIR,
        help="Path to the rules directory (default: assets/rules).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate all Markdown files even when SHA-256 digests match.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit with code 1 if any Markdown file or manifest entry is out of date.",
    )
    args = parser.parse_args(argv)

    changed = sync_rules_markdown(
        args.rules_dir,
        force=args.force,
        check_only=args.check,
    )
    if args.check:
        if changed:
            print(
                f"Stale or missing rules Markdown files ({len(changed)}): {', '.join(changed)}",
                file=sys.stderr,
            )
            return 1
        print("All FIBS rules Markdown files are up-to-date.")
        return 0

    if changed:
        print(f"Synchronized {len(changed)} FIBS rules Markdown file(s): {', '.join(changed)}")
    else:
        print("All FIBS rules Markdown files already up-to-date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
