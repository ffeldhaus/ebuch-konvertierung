"""Running headers / footers (Kolumnentitel) are removed for every engine output.

Synthetic snippets only (own wording) – AGENTS.md §3/§7.4. The heuristics are generic:
repetition across page boundaries, page numbers glued to the title, boundary position.
"""
from backend.services.extraction_postprocess import clean_running_headers_and_footers

TITLE = "WASSER UND SEINE EIGENSCHAFTEN"


def _page(num: int, body: str, footer: str = "") -> str:
    return f"(({num}))\n\n{body}\n\n{footer}\n\n" if footer else f"(({num}))\n\n{body}\n\n"


def test_running_footer_with_page_numbers_and_heading_prefix_is_removed():
    """Verifies alternating running footers with page numbers and heading prefixes are removed."""
    # Alternating forms as produced by VLM extractors: plain, heading, heading with page number.
    md = (
        _page(10, "# 1 Wasser\n\nWasser ist ein Stoff.", TITLE)
        + _page(11, "Absatz über Dichte.", f"## 11 {TITLE}")
        + _page(12, "Absatz über Siedepunkt.", f"{TITLE} 12")
        + _page(13, "Absatz über Eis.", f"## {TITLE}")
        + _page(14, "Absatz über Dampf.", TITLE)
        + _page(15, "Absatz über Lösungen.", f"15 {TITLE}")
        + _page(16, f"Erster Absatz.\n\nZweiter Absatz.\n\n## 16 {TITLE}\n\nDritter Absatz.\n\nVierter Absatz.")
    )
    cleaned = clean_running_headers_and_footers(md)
    assert "EIGENSCHAFTEN" not in cleaned
    for text in ("# 1 Wasser", "Wasser ist ein Stoff.", "Absatz über Lösungen.", "((15))"):
        assert text in cleaned


def test_repeated_real_section_heading_at_page_top_is_kept():
    """Verifies repeated real section headings at the top of pages are preserved."""
    # A genuine section heading that happens to start several pages must not be treated as running header.
    md = "".join(_page(n, f"### Aufgaben\n\nA{n} Bearbeite die Aufgabe {n}.") for n in range(1, 8))
    cleaned = clean_running_headers_and_footers(md)
    assert cleaned.count("### Aufgaben") == 7


def test_bare_page_number_lines_at_page_boundary_are_removed():
    """Verifies bare page number lines at page boundaries are removed while mid-page numbers stay."""
    md = (
        _page(47, "Text der Seite.", "## 48")
        + _page(49, "Weiterer Text.\n\n50")
        + _page(51, "Liste:\n\n3\n\nEnde der Seite.")
    )
    cleaned = clean_running_headers_and_footers(md)
    assert "## 48" not in cleaned
    assert "\n50\n" not in cleaned
    # A number inside the page body is content, not a page number
    assert "\n3\n" in cleaned


def test_repeated_phrase_in_mid_page_is_kept():
    """Verifies repeated mid-page didactic phrases are preserved."""
    phrase = "Merke: Sicherheit geht vor."
    md = "".join(
        _page(n, f"Einleitung {n}.\n\nErster Absatz.\n\n{phrase}\n\nZweiter Absatz.\n\nDritter Absatz.\n\nSchluss {n}.")
        for n in range(1, 8)
    )
    cleaned = clean_running_headers_and_footers(md)
    assert cleaned.count(phrase) == 7


def test_page_markers_stay_on_their_own_line():
    """Verifies ((num)) page markers remain on their own line."""
    md = "Vorwort.\n((1))\nErste Seite.\n((2))\nZweite Seite.\n"
    cleaned = clean_running_headers_and_footers(md)
    assert "Vorwort.\n((1))\n" in cleaned
    assert "Erste Seite.\n((2))\n" in cleaned


def test_chapter_opening_heading_is_kept_once():
    """Verifies chapter opening heading is kept once while later running footers are stripped."""
    # The chapter starts with its title as heading; later pages repeat it as running footer.
    md = (
        _page(10, "# 1 Wasser und seine Eigenschaften\n\nEinleitender Text.\n\nMehr Text.")
        + _page(11, "Absatz über Dichte.\n\nNoch ein Absatz.", f"## 11 {TITLE}")
        + _page(12, "Absatz über Eis.\n\nNoch ein Absatz.", TITLE)
        + _page(13, "Absatz über Dampf.\n\nNoch ein Absatz.", f"{TITLE} 13")
    )
    cleaned = clean_running_headers_and_footers(md)
    assert "# 1 Wasser und seine Eigenschaften" in cleaned
    assert cleaned.lower().count("wasser und seine eigenschaften") == 1


def test_combined_two_part_docling_page_headers_stripped_anywhere_unless_opening(tmp_path):
    """Verifies combined lines formed by joining two page_header items on the same page are stripped."""
    import json

    from backend.services.extraction_postprocess import fuse_vlm_page_with_docling

    docling_layout = {
        "furniture_by_page": {
            0: [
                {"type": "page_header", "text": "ELEKTROTECHNIK", "page_idx": 0, "bbox_1000": [80, 28, 280, 52]},
                {"type": "page_header", "text": "Gleichstromkreise und Netzwerke", "page_idx": 0, "bbox_1000": [420, 28, 860, 52]},
            ]
        },
        "text_blocks_by_page": {
            0: [
                {"type": "section_header", "text": "Kirchhoffsche Regeln", "page_idx": 0, "bbox_1000": [80, 110, 520, 145]},
                {"type": "text", "text": "In jedem Knotenpunkt ist die Summe aller Ströme gleich null.", "page_idx": 0, "bbox_1000": [80, 170, 860, 260]},
            ]
        },
    }
    raw_vlm = (
        "ELEKTROTECHNIK Gleichstromkreise und Netzwerke\n\n"
        "## Kirchhoffsche Regeln\n\n"
        "In jedem Knotenpunkt ist die Summe aller Ströme gleich null.\n\n"
        "ELEKTROTECHNIK GLEICHSTROMKREISE UND NETZWERKE"
    )
    fused = fuse_vlm_page_with_docling(raw_vlm, [], phys_num=32, docling_layout=docling_layout, page_idx=0)
    assert "ELEKTROTECHNIK" not in fused
    assert "Gleichstromkreise und Netzwerke" not in fused
    assert "## Kirchhoffsche Regeln" in fused
    assert "Summe aller Ströme" in fused

    # Preserved when explicitly passed in opening_headers
    fused_open = fuse_vlm_page_with_docling(
        raw_vlm,
        [],
        phys_num=32,
        opening_headers=["## Gleichstromkreise und Netzwerke"],
        docling_layout=docling_layout,
        page_idx=0,
    )
    assert "## Gleichstromkreise und Netzwerke" in fused_open

    # Also stripped in clean_running_headers_and_footers via content_list.json
    cl_path = tmp_path / "cl.json"
    cl_path.write_text(
        json.dumps([
            {"type": "page_header", "text": "ELEKTROTECHNIK", "page_idx": 0},
            {"type": "page_header", "text": "Gleichstromkreise und Netzwerke", "page_idx": 0},
        ]),
        encoding="utf-8",
    )
    multi_md = "((32))\n\nELEKTROTECHNIK Gleichstromkreise und Netzwerke\n\n## Kirchhoffsche Regeln\n\nInhalt."
    cleaned_multi = clean_running_headers_and_footers(multi_md, content_list_path=str(cl_path))
    assert "ELEKTROTECHNIK" not in cleaned_multi
    assert "## Kirchhoffsche Regeln" in cleaned_multi

