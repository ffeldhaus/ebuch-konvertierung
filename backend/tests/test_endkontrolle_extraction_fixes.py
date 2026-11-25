"""Synthetic unit tests for Track 1 Stage-1 extraction fixes (#9, #4a, #7a, #17/#8)."""

import json

from backend.services.extraction_postprocess import (
    _apply_pdf_font_spans_to_markdown,
    _enrich_flattened_tables_with_docling,
    detect_pdf_callout_rects_by_page,
    extract_pdf_page_details,
    fuse_vlm_page_with_docling,
    reconstruct_title_hierarchy,
    recover_table_truncation,
)


def test_fix9_block_level_bold_headings_and_mixed_multiword_spans_do_not_bleed(tmp_path):
    """Verifies Fix #9: standalone body-sized bold headings/labels never leak into font_spans,
    multi-word spans that also appear unstyled require neighbor context, and empty-context
    non-always_styled spans are skipped rather than globally applied.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    pdf_path = str(tmp_path / "fix9_font_spans.pdf")
    c = canvas.Canvas(pdf_path, pagesize=A4)
    _pw, ph = A4

    # Body-sized 1-word bold standalone heading (same 10pt size as body -> not caught by is_heading_para)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(60, ph - 80, "Katalyse")

    # Body-sized multi-word bold standalone heading / diagram label
    c.setFont("Helvetica-Bold", 10)
    c.drawString(60, ph - 110, "Leber und Niere")

    # All-bold summary block at body size (block-level styling, NOT inline emphasis)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(60, ph - 140, "Alle chemischen Reaktionen folgen dem Energieerhaltungssatz.")

    # Body prose mentioning 'Katalyse' and 'Leber und Niere' in plain text + genuine inline bold
    y1 = ph - 185
    c.setFont("Helvetica", 10)
    c.drawString(60, y1, "Die Katalyse beschleunigt Prozesse in Leber und Niere durch ")
    x1 = 60 + c.stringWidth("Die Katalyse beschleunigt Prozesse in Leber und Niere durch ", "Helvetica", 10)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x1, y1, "Aktivierungsenergie")
    x1 += c.stringWidth("Aktivierungsenergie", "Helvetica-Bold", 10)
    c.setFont("Helvetica", 10)
    c.drawString(x1, y1, " im Gewebe.")

    # Multi-word phrase 'mechanische Arbeit' appears BOLD once (with neighbor context) AND UNSTYLED once
    y2 = ph - 220
    c.setFont("Helvetica", 10)
    c.drawString(60, y2, "Dabei leistet die Feder ")
    x2 = 60 + c.stringWidth("Dabei leistet die Feder ", "Helvetica", 10)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x2, y2, "mechanische Arbeit")
    x2 += c.stringWidth("mechanische Arbeit", "Helvetica-Bold", 10)
    c.setFont("Helvetica", 10)
    c.drawString(x2, y2, " am Kolben.")

    y3 = ph - 245
    c.setFont("Helvetica", 10)
    c.drawString(60, y3, "Im zweiten Versuch bleibt mechanische Arbeit unverändert klein.")

    c.showPage()
    c.save()

    details = extract_pdf_page_details(pdf_path)
    spans = details["font_spans_by_page"].get(0, [])
    span_texts = [s["text"] for s in spans]

    # Block-level bold headings/labels/boxes must NEVER be extracted as inline font_spans
    assert "Katalyse" not in span_texts
    assert "Leber und Niere" not in span_texts
    assert not any("Energieerhaltungssatz" in t for t in span_texts)

    # Genuine inline bold term is extracted with always_styled=True
    akt_spans = [s for s in spans if s["text"] == "Aktivierungsenergie"]
    assert len(akt_spans) == 1
    assert akt_spans[0]["always_styled"] is True

    # Multi-word phrase that also appears unstyled on the same page MUST have always_styled=False
    mech_spans = [s for s in spans if s["text"] == "mechanische Arbeit"]
    assert len(mech_spans) == 1
    assert mech_spans[0]["always_styled"] is False
    assert mech_spans[0]["left"] == "Feder"

    raw_vlm = (
        "### Katalyse\n\n"
        "### Leber und Niere\n\n"
        "Die Katalyse beschleunigt Prozesse in Leber und Niere durch Aktivierungsenergie im Gewebe.\n\n"
        "Dabei leistet die Feder mechanische Arbeit am Kolben.\n\n"
        "Im zweiten Versuch bleibt mechanische Arbeit unverändert klein."
    )
    fused = fuse_vlm_page_with_docling(
        raw_vlm,
        page_images=[],
        phys_num=12,
        docling_layout={"font_spans_by_page": {0: spans}},
        page_idx=0,
    )
    assert "**Katalyse**" not in fused
    assert "**Leber und Niere**" not in fused
    assert "**Aktivierungsenergie**" in fused
    assert "Feder **mechanische Arbeit** am Kolben." in fused
    assert "bleibt mechanische Arbeit unverändert" in fused


def test_fix9_apply_font_spans_skips_non_always_styled_without_neighbors():
    """Verifies Fix #9b: _apply_pdf_font_spans_to_markdown never overrides always_styled=False when left/right are empty."""
    md = (
        "Der Stoff Alkohol beeinflusst die Signalübertragung im zentralen Nervensystem.\n"
        "Besonders die spezifische Dichte spielt in der Messung eine Rolle, nicht jede Dichte."
    )
    spans = [
        {"text": "Alkohol", "style": "bold", "left": "", "right": "", "always_styled": False},
        {"text": "Dichte", "style": "bold", "left": "spezifische", "right": "", "always_styled": False},
    ]
    out = _apply_pdf_font_spans_to_markdown(md, spans)
    assert "**Alkohol**" not in out
    assert "spezifische **Dichte** spielt" in out
    assert "nicht jede Dichte." in out


def test_fix4a_shaded_pdf_callout_boxes_without_merke_prefix_wrapped_in_rahmen(tmp_path):
    """Verifies Fix #4a: shaded vector callout boxes without literal 'Merke' prefix wrap in <Rahmen>,
    while invisible white rects, sequential exercises, and normal prose are never wrapped.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    pdf_path = str(tmp_path / "fix4a_callout_boxes.pdf")
    c = canvas.Canvas(pdf_path, pagesize=A4)
    pw, ph = A4

    # Pure white unstroked background rectangle (must be ignored by detect_pdf_callout_rects_by_page)
    c.setFillColorRGB(1.0, 1.0, 1.0)
    c.rect(50, ph - 260, 450, 180, stroke=0, fill=1)

    # Normal body prose outside any colored box
    c.setFillColorRGB(0.0, 0.0, 0.0)
    c.setFont("Helvetica", 10)
    c.drawString(60, ph - 90, "Bei einer gleichförmigen Kreisbewegung bleibt der Betrag der Geschwindigkeit konstant.")

    # Blue shaded physics law box (height 68pt, NO 'Merke' word!)
    c.setFillColorRGB(0.85, 0.92, 0.99)
    c.rect(55, ph - 210, 460, 68, stroke=0, fill=1)
    c.setFillColorRGB(0.0, 0.0, 0.0)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(65, ph - 162, "Erhaltungssatz des Drehimpulses:")
    c.setFont("Helvetica", 10)
    c.drawString(65, ph - 180, "In einem abgeschlossenen System bleibt der Gesamtdrehimpuls zeitlich konstant.")

    # Compact green shaded summary box (height 30pt — previously dropped by min_h=32!)
    c.setFillColorRGB(0.86, 0.96, 0.88)
    c.rect(55, ph - 280, 460, 30, stroke=0, fill=1)
    c.setFillColorRGB(0.0, 0.0, 0.0)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(65, ph - 268, "Zellen spezialisieren sich während der Entwicklung zu funktionalen Geweben.")

    # Shaded exercise area (must NEVER be wrapped in <Rahmen>!)
    c.setFillColorRGB(0.95, 0.95, 0.95)
    c.rect(55, ph - 410, 460, 90, stroke=0, fill=1)
    c.setFillColorRGB(0.0, 0.0, 0.0)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(65, ph - 338, "Aufgaben")
    c.setFont("Helvetica", 10)
    c.drawString(65, ph - 360, "1 Berechnen Sie den Drehimpuls einer rotierenden Scheibe.")
    c.drawString(65, ph - 380, "2 Erklären Sie die Änderung der Winkelgeschwindigkeit bei kleinerem Radius.")

    c.showPage()
    c.save()

    rects_by_page = detect_pdf_callout_rects_by_page(pdf_path)
    p0_rects = rects_by_page.get(0, [])
    # Should detect the 3 visible shaded boxes (including the 30pt green box) and ignore the white background
    assert len(p0_rects) == 3

    details = extract_pdf_page_details(pdf_path, callout_rects_by_page=rects_by_page)
    pdf_blocks = details["pdf_blocks_by_page"].get(0, [])
    assert any(b.get("is_callout_box") and "Drehimpulses" in b["text"] for b in pdf_blocks)
    assert any(b.get("is_callout_box") and "spezialisieren" in b["text"] for b in pdf_blocks)
    assert not any(b.get("is_callout_box") and "Kreisbewegung" in b["text"] for b in pdf_blocks)

    # VLM emitted law box with '###' title + formula, and compact summary box as a multi-sentence '###' heading
    vlm_md = (
        "Bei einer gleichförmigen Kreisbewegung bleibt der Betrag der Geschwindigkeit konstant.\n\n"
        "### Erhaltungssatz des Drehimpulses:\n\n"
        "In einem abgeschlossenen System bleibt der Gesamtdrehimpuls zeitlich konstant.\n\n"
        "$$L = J \\cdot \\omega = \\text{const.}$$\n\n"
        "### Zellen spezialisieren sich während der Entwicklung zu funktionalen Geweben.\n\n"
        "## Aufgaben\n\n"
        "1 Berechnen Sie den Drehimpuls einer rotierenden Scheibe.\n\n"
        "2 Erklären Sie die Änderung der Winkelgeschwindigkeit bei kleinerem Radius."
    )
    fused = fuse_vlm_page_with_docling(
        vlm_md,
        page_images=[],
        phys_num=77,
        docling_layout={"text_blocks_by_page": {0: pdf_blocks}},
        page_idx=0,
    )
    assert "<Rahmen>\n**Erhaltungssatz des Drehimpulses:**" in fused
    assert "$$L = J \\cdot \\omega = \\text{const.}$$\n</Rahmen>" in fused
    assert "<Rahmen>\nZellen spezialisieren sich während der Entwicklung zu funktionalen Geweben.\n</Rahmen>" in fused
    # Normal prose and sequential tasks remain outside <Rahmen>
    assert fused.count("<Rahmen>") == 2
    assert "## Aufgaben" in fused
    assert "1 Berechnen Sie den Drehimpuls" in fused

    # reconstruct_title_hierarchy must NOT promote bold titles inside <Rahmen> to headings
    hier = reconstruct_title_hierarchy(fused)
    assert "#### Erhaltungssatz des Drehimpulses:" not in hier
    assert "<Rahmen>\n**Erhaltungssatz des Drehimpulses:**" in hier


def test_fix7a_margin_etymologies_and_in_figure_labels_never_become_headings(tmp_path):
    """Verifies Fix #7a: margin etymologies and figure-overlapping labels never become Markdown headings."""
    # 1. Margin etymologies across languages must be demoted in fuse_vlm_page_with_docling (even without layout)
    #    and never promoted in reconstruct_title_hierarchy.
    vlm_etym = (
        "## 3.2 Aufbau der Rinde\n\n"
        "### lat. cortex = Rinde\n\n"
        "#### griech. synapsis = Verbindung\n\n"
        "### franz. milieu = Umgebung\n\n"
        "### arab. al-dschabr = Zusammenfügen\n\n"
        "Die äußere Schicht schützt das darunterliegende Gewebe."
    )
    fused_no_layout = fuse_vlm_page_with_docling(vlm_etym, page_images=[], phys_num=32)
    assert "## 3.2 Aufbau der Rinde" in fused_no_layout
    assert "### lat. cortex = Rinde" not in fused_no_layout
    assert "lat. cortex = Rinde" in fused_no_layout
    assert "#### griech. synapsis = Verbindung" not in fused_no_layout
    assert "griech. synapsis = Verbindung" in fused_no_layout
    assert "### franz. milieu = Umgebung" not in fused_no_layout
    assert "franz. milieu = Umgebung" in fused_no_layout
    assert "### arab. al-dschabr = Zusammenfügen" not in fused_no_layout
    assert "arab. al-dschabr = Zusammenfügen" in fused_no_layout

    bold_etym_md = (
        "## 3.2 Aufbau der Rinde\n\n"
        "**lat. cortex = Rinde**\n\n"
        "### gr. bios = Leben\n\n"
        "Regulärer Absatz über Gewebe."
    )
    reconstructed = reconstruct_title_hierarchy(bold_etym_md)
    assert "### lat. cortex = Rinde" not in reconstructed
    assert "**lat. cortex = Rinde**" in reconstructed
    assert "### gr. bios = Leben" not in reconstructed
    assert "gr. bios = Leben" in reconstructed

    # 2. Figure-overlapping heading_blocks / text_blocks must never register as headings,
    #    and VLM-emitted multi-word diagram axis titles / organism labels are stripped.
    layout_with_fig_headings = {
        "layout_blocks": [
            {
                "type": "image",
                "text": "![](images/picture_0_0_fig.png)",
                "page_idx": 0,
                "bbox_1000": [100, 200, 880, 620],
            }
        ],
        "heading_blocks": [
            {"text": "Stoffwechsel im Diagramm", "page_idx": 0, "bbox_1000": [80, 90, 600, 125]},
            # Axis title overlapping figure bbox
            {
                "text": "Konzentration des Enzyms in Millimol pro Liter",
                "page_idx": 0,
                "bbox_1000": [120, 220, 520, 250],
            },
            # Organism label tightly overlapping bottom-right of figure bbox (~40% overlap)
            {
                "text": "Süßwasserpolyp im Querschnitt",
                "page_idx": 0,
                "bbox_1000": [600, 605, 860, 635],
            },
        ],
        "text_blocks_by_page": {
            0: [
                {"type": "section_header", "text": "Stoffwechsel im Diagramm", "page_idx": 0, "bbox_1000": [80, 90, 600, 125]},
                {"type": "text", "text": "Die Kurve zeigt den zeitlichen Verlauf der Stoffumwandlung.", "page_idx": 0, "bbox_1000": [80, 680, 880, 740]},
            ]
        },
    }
    vlm_fig = (
        "## Stoffwechsel im Diagramm\n\n"
        "![](images/picture_0_0_fig.png)\n\n"
        "### Konzentration des Enzyms in Millimol pro Liter\n\n"
        "#### Süßwasserpolyp im Querschnitt\n\n"
        "Die Kurve zeigt den zeitlichen Verlauf der Stoffumwandlung."
    )
    fused_fig = fuse_vlm_page_with_docling(
        vlm_fig,
        page_images=["picture_0_0_fig.png"],
        phys_num=33,
        docling_layout=layout_with_fig_headings,
        page_idx=0,
    )
    assert "## Stoffwechsel im Diagramm" in fused_fig
    assert "### Konzentration des Enzyms" not in fused_fig
    assert "#### Süßwasserpolyp im Querschnitt" not in fused_fig
    assert "Die Kurve zeigt den zeitlichen Verlauf der Stoffumwandlung." in fused_fig

    # 3. reconstruct_title_hierarchy excludes figure-overlapping title blocks from content_list_path
    cl_path = tmp_path / "content_list.json"
    cl_path.write_text(
        json.dumps(
            [
                {"type": "image", "page_idx": 0, "bbox_1000": [100, 200, 800, 600]},
                {"type": "title", "text": "Kapitel 4 Wärmelehre", "page_idx": 0, "bbox": [0, 0, 300, 20], "bbox_1000": [80, 80, 500, 115]},
                {"type": "title", "text": "Temperaturachse in Kelvin", "page_idx": 0, "bbox": [0, 0, 200, 16], "bbox_1000": [150, 240, 420, 270]},
            ]
        ),
        encoding="utf-8",
    )
    plain_md = "Kapitel 4 Wärmelehre\n\nTemperaturachse in Kelvin\n\nMessung erfolgt in Kelvin."
    rec_cl = reconstruct_title_hierarchy(plain_md, content_list_path=str(cl_path))
    assert "# Kapitel 4 Wärmelehre" in rec_cl
    assert "# Temperaturachse in Kelvin" not in rec_cl
    assert "## Temperaturachse in Kelvin" not in rec_cl


def test_fix17_and_8_stage1_table_preservation_and_flattened_replacement():
    """Verifies Fix #17/#8: short-cell numeric tables survive alongside inline pipes, VLM-flattened
    tables are replaced in-place, tables_by_page is read from docling_layout, and structured
    multi-row comparison tables with long cells are NOT destroyed by recover_table_truncation.
    """
    # 1. Short-cell numeric/symbol table (> 6 cells) must NOT be dropped when cleaned_text contains '$|F|$'
    short_cell_tbl = (
        "| t | s | v | a |\n"
        "| --- | --- | --- | --- |\n"
        "| 1 | 2 | 4 | 4 |\n"
        "| 2 | 8 | 8 | 4 |\n"
        "| 3 | 18 | 12 | 4 |"
    )
    vlm_with_abs_pipe = (
        "## 2.3 Gleichmäßig beschleunigte Bewegung\n\n"
        "Die Beschleunigung hängt vom Betrag $|F|$ der wirkenden Kraft ab."
    )
    enriched_short = _enrich_flattened_tables_with_docling(vlm_with_abs_pipe, [short_cell_tbl])
    assert "| t | s | v | a |" in enriched_short
    assert "| 3 | 18 | 12 | 4 |" in enriched_short

    # 2. VLM-flattened multi-row table between intro prose and '## Aufgaben' is replaced IN-PLACE
    docling_comp_tbl = (
        "| Organ | Aktivierung A | Aktivierung B |\n"
        "| --- | --- | --- |\n"
        "| Herz | Frequenz steigt | Frequenz sinkt |\n"
        "| Pupille | Erweiterung | Verengung |\n"
        "| Bronchien | Erweiterung | Verengung |"
    )
    vlm_flattened = (
        "## Steuerung von Organfunktionen\n\n"
        "Der Organismus passt seine Leistungsbereitschaft laufend an wechselnde Anforderungen an.\n\n"
        "- Organ: Herz – Aktivierung A: Frequenz steigt – Aktivierung B: Frequenz sinkt\n"
        "- Pupille: Erweiterung / Verengung\n"
        "- Bronchien: Erweiterung / Verengung\n\n"
        "## Aufgaben\n\n"
        "1 Vergleichen Sie beide Steuerungszustände."
    )
    fused_tbl = fuse_vlm_page_with_docling(
        vlm_flattened,
        page_images=[],
        phys_num=64,
        docling_layout={"tables_by_page": {0: [docling_comp_tbl]}},
        page_idx=0,
    )
    assert "| Organ | Aktivierung A | Aktivierung B |" in fused_tbl
    assert "| Bronchien | Erweiterung | Verengung |" in fused_tbl
    # Flattened duplicate bullet list was replaced in-place (not left behind)
    assert "- Organ: Herz" not in fused_tbl
    assert fused_tbl.index("Leistungsbereitschaft") < fused_tbl.index("| Organ |") < fused_tbl.index("## Aufgaben")

    # 3. Structured multi-row comparison table with a >200-char descriptive cell is PRESERVED by recover_table_truncation
    long_desc = (
        "Langfristige Anpassung der Zellmembran durch vermehrte Einlagerung ungesättigter Fettsäuren, "
        "sodass die Beweglichkeit der Lipiddoppelschicht selbst bei stark absinkenden Umgebungstemperaturen "
        "vollständig erhalten bleibt."
    )
    assert len(long_desc) >= 200
    comparison_table_md = (
        "## Vergleich von Anpassungsmechanismen\n\n"
        "| Merkmal | Mechanismus A | Mechanismus B |\n"
        "| --- | --- | --- |\n"
        f"| Membranstruktur | {long_desc} | Keine Veränderung der Lipidzusammensetzung |\n"
        f"| Enzymaktivität | {long_desc} | Deutlicher Aktivitätsabfall unter zehn Grad |\n"
        "| Energiebedarf | Erhöhter ATP-Verbrauch in der Übergangsphase | Geringer Grundumsatz |"
    )
    recovered = recover_table_truncation(comparison_table_md)
    assert "| Merkmal | Mechanismus A | Mechanismus B |" in recovered
    assert "| Energiebedarf |" in recovered

    # 4. Genuine 2-column prose layout (no short structured header row) is STILL unrolled to paragraphs
    fake_layout_tbl = (
        f"| {long_desc} | {long_desc} |\n"
        "| --- | --- |\n"
        f"| {long_desc} | Zweiter Absatz im Spaltenlayout. |"
    )
    unrolled = recover_table_truncation(fake_layout_tbl)
    assert "| --- | --- |" not in unrolled
    assert "Zweiter Absatz im Spaltenlayout." in unrolled
