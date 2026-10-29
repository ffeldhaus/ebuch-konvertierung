"""
Unit tests for deterministic FIBS formatting helpers (backend/services/fibs_formatting.py).

Covers the Phase-1 items derived from verified feedback (AGENTS.md §7):
  - multi-line <Bild> format with "Bildart:" and "Beschreibung mit Bildtext:" / "Beschreibung:"
  - structured VLM output parsing (Bildart, Text im Bild, dekorativ)
  - decorative image detection context (no caption / no text reference)
  - list normalisation inside image descriptions
  - Unicode sub-/superscripts → _ / ^ notation
  - Versalien (all-caps emphasis) → normal case + _…_ (only with in-document evidence)
All snippets are synthetic (own wording) – no text from analysed textbooks.
"""
import pytest

from backend.services import fibs_formatting as ff
from backend.services.fibs_postprocess import post_process_structure
from backend.services.prompts import SYSTEM_PROMPTS, VLM_IMAGE_PROMPT
from backend.services.vlm_describer import parse_vlm_description


# ---------------------------------------------------------------------------
# <Bild> formatting
# ---------------------------------------------------------------------------

def test_format_bild_tag_with_text():
    out = ff.format_bild_tag("Strukturdiagramm", "Wasser \\to Dampf", has_text=True)
    assert out == "<Bild> Strukturdiagramm:\nBeschreibung mit Bildtext: Wasser \\to Dampf\n</Bild>"


def test_format_bild_tag_without_text_and_default_type():
    out = ff.format_bild_tag("", "Ein rotes Fahrrad steht vor einer Mauer.", has_text=False)
    assert out == "<Bild> Abbildung:\nBeschreibung: Ein rotes Fahrrad steht vor einer Mauer.\n</Bild>"


def test_format_bild_tag_multiline_description_keeps_lines():
    desc = "Zwei Kästen sind verbunden.\nKasten A \\to Kasten B"
    out = ff.format_bild_tag("Flussdiagramm", desc, has_text=True)
    assert out.splitlines() == [
        "<Bild> Flussdiagramm:",
        "Beschreibung mit Bildtext: Zwei Kästen sind verbunden.",
        "Kasten A \\to Kasten B",
        "</Bild>",
    ]


def test_normalize_description_lists_uses_tab_markers_consistently():
    desc = "Das Bild zeigt drei Gegenstände:\n* eine Tasse\n• ein Löffel\n  - ein kleiner Teller\n**Hinweis** am Rand"
    out = ff.normalize_description_lists(desc)
    assert out.splitlines() == [
        "Das Bild zeigt drei Gegenstände:",
        "-\teine Tasse",
        "-\tein Löffel",
        "  -\tein kleiner Teller",
        "Hinweis am Rand",
    ]


@pytest.mark.parametrize("single, expected", [
    ("<Bild> Foto: Ein Baum im Nebel. </Bild>",
     "<Bild> Foto:\nBeschreibung: Ein Baum im Nebel.\n</Bild>"),
    ("<Bild> Ein Baum im Nebel, daneben steht: Wald </Bild>",
     "<Bild> Abbildung:\nBeschreibung: Ein Baum im Nebel, daneben steht: Wald\n</Bild>"),
    ("<Bild> Diagramm: Beschreibung mit Bildtext: Achse x </Bild>",
     "<Bild> Diagramm:\nBeschreibung mit Bildtext: Achse x\n</Bild>"),
])
def test_normalize_bild_tags_converts_single_line(single, expected):
    assert ff.normalize_bild_tags(single) == expected


def test_normalize_bild_tags_is_idempotent_on_multiline():
    block = "<Bild> 2 Fotos:\nBeschreibung: Links ein Hund, rechts eine Katze.\n</Bild>"
    md = f"Text davor.\n\n{block}\n\nText danach."
    assert ff.normalize_bild_tags(md) == md
    assert ff.normalize_bild_tags(ff.normalize_bild_tags(md)) == md


def test_normalize_bild_tags_leaves_numbered_caption_blocks_untouched():
    # Caption handling (heading vs. tag) is still an open rule question → no reinterpretation
    md = "<Bild> Abbildung 3: Querschnitt eines Rohrs. </Bild>"
    assert ff.normalize_bild_tags(md) == md


def test_normalize_bild_tags_normalizes_bullets_and_bold_inside_description():
    md = "<Bild> Diagramm:\nBeschreibung:\n* **Erster Punkt**\n• Zweiter Punkt\n</Bild>"
    assert ff.normalize_bild_tags(md) == (
        "<Bild> Diagramm:\nBeschreibung:\n-\tErster Punkt\n-\tZweiter Punkt\n</Bild>"
    )


# ---------------------------------------------------------------------------
# Structured VLM output
# ---------------------------------------------------------------------------

def test_parse_vlm_description_structured():
    raw = (
        "BILDART: Mindmap\n"
        "TEXT_IM_BILD: ja\n"
        "DEKORATIV: nein\n"
        "BESCHREIBUNG:\n"
        "Zentrum \\to Ast eins\n"
        "Zentrum \\to Ast zwei"
    )
    parsed = parse_vlm_description(raw)
    assert parsed.image_type == "Mindmap"
    assert parsed.has_text is True
    assert parsed.decorative is False
    assert parsed.description == "Zentrum \\to Ast eins\nZentrum \\to Ast zwei"


def test_parse_vlm_description_decorative_and_markdown_noise():
    raw = "**BILDART:** Zeichnung\n**TEXT_IM_BILD:** nein\n**DEKORATIV:** ja\n**BESCHREIBUNG:** Verschnörkelte Ranke."
    parsed = parse_vlm_description(raw)
    assert parsed.image_type == "Zeichnung"
    assert parsed.has_text is False
    assert parsed.decorative is True
    assert parsed.description == "Verschnörkelte Ranke."


def test_parse_vlm_description_unstructured_fallback():
    parsed = parse_vlm_description("Ein Foto eines Sees mit Bergen.")
    assert parsed.image_type == ""
    assert parsed.has_text is None
    assert parsed.decorative is False
    assert parsed.description == "Ein Foto eines Sees mit Bergen."


def test_vlm_prompt_contains_structural_rules():
    p = VLM_IMAGE_PROMPT
    assert "BILDART:" in p and "TEXT_IM_BILD:" in p and "DEKORATIV:" in p and "BESCHREIBUNG:" in p
    assert "\\to" in p  # diagram arrows
    assert "Aufzählung" in p  # avoid bullet lists


def test_bild_tag_from_vlm_builds_tag_or_drops_decorative():
    structured = parse_vlm_description(
        "BILDART: Foto\nTEXT_IM_BILD: nein\nDEKORATIV: nein\nBESCHREIBUNG:\nEin Glas Wasser."
    )
    assert ff.bild_tag_from_vlm(structured, has_caption=False) == \
        "<Bild> Foto:\nBeschreibung: Ein Glas Wasser.\n</Bild>"
    deco = parse_vlm_description(
        "BILDART: Zeichnung\nTEXT_IM_BILD: nein\nDEKORATIV: ja\nBESCHREIBUNG:\nEine Zierlinie."
    )
    # Decorative + no caption → not transferred at all
    assert ff.bild_tag_from_vlm(deco, has_caption=False) == ""
    # Decorative per VLM but captioned → keep (conservative, a caption implies content relevance)
    assert ff.bild_tag_from_vlm(deco, has_caption=True).startswith("<Bild> Zeichnung:")


# ---------------------------------------------------------------------------
# Caption / text-reference context for decorative detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("before, after, expected", [
    ("Ein normaler Absatz.", "Noch ein Absatz.", False),
    ("Ein normaler Absatz.", "Abb. 3 Aufbau einer Lampe", True),
    ("Abbildung 2: Querschnitt", "Weiter im Text.", True),
    ("Text.", "M4 Messreihe im Vergleich", True),
    ("Text.", "_Bild 1:_ Versuchsaufbau", True),
    ("Abbildung 2: Querschnitt\n\n((12-13))", "Weiter im Text.", True),
])
def test_has_caption_context(before, after, expected):
    md = f"{before}\n\n![](images/x.png)\n\n{after}"
    start = md.index("![")
    end = md.index(")", start) + 1
    assert ff.has_caption_context(md, start, end, alt_text="") is expected


def test_has_caption_context_meaningful_alt_text():
    md = "Absatz.\n\n![Schnitt durch ein Blatt](images/x.png)\n\nAbsatz."
    start = md.index("![")
    end = md.index(")", start) + 1
    assert ff.has_caption_context(md, start, end, alt_text="Schnitt durch ein Blatt") is True
    assert ff.has_caption_context(md, start, end, alt_text="image") is False


# ---------------------------------------------------------------------------
# Unicode sub-/superscripts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src, expected", [
    ("H₂O", "H_2O"),
    ("C₆H₁₂O₆", "C_6H_{12}O_6"),
    ("Mg²⁺ und Cl⁻", "Mg^{2+} und Cl^-"),
    ("SO₄²⁻", "SO_4^{2-}"),
    ("Fläche in m² und Volumen in cm³", "Fläche in m^2 und Volumen in cm^3"),
    ("10⁶ Zellen", "10^6 Zellen"),
    ("x² + y²", "x^2 + y^2"),
])
def test_convert_unicode_scripts(src, expected):
    assert ff.convert_unicode_scripts(src) == expected


def test_convert_unicode_scripts_keeps_footnote_like_superscripts():
    # Superscript digit right after a longer word or punctuation is a footnote reference, not a formula
    assert ff.convert_unicode_scripts("Diese Aussage¹ gilt.") == "Diese Aussage¹ gilt."
    assert ff.convert_unicode_scripts("Ende des Satzes.² Neu") == "Ende des Satzes.² Neu"


# ---------------------------------------------------------------------------
# Versalien
# ---------------------------------------------------------------------------

def test_normalize_versalien_with_document_evidence():
    md = "Der Begriff Kristall wird erklärt.\n\nEin KRISTALL besteht aus Teilchen."
    out = ff.normalize_versalien(md)
    assert "Ein _Kristall_ besteht aus Teilchen." in out


def test_normalize_versalien_keeps_abbreviations_without_evidence():
    md = "Die UNESCO und die Norm DIN sowie CO2 bleiben. Der Kristall glänzt."
    assert ff.normalize_versalien(md) == md


def test_normalize_versalien_runs_and_existing_emphasis():
    md = "Gold und Silber sind Metalle.\n\nGOLD UND SILBER glänzen.\n\nNur _SILBER_ läuft an."
    out = ff.normalize_versalien(md)
    assert "_Gold und Silber_ glänzen." in out
    assert "Nur _Silber_ läuft an." in out


def test_normalize_versalien_headings_without_underscores():
    md = "## LICHT UND SCHATTEN\n\nLicht fällt auf eine Wand und erzeugt Schatten."
    out = ff.normalize_versalien(md)
    assert out.splitlines()[0] == "## Licht und Schatten"
    md_italic = "## _LICHT UND SCHATTEN_\n\nLicht fällt auf eine Wand und erzeugt Schatten."
    assert ff.normalize_versalien(md_italic).splitlines()[0] == "## Licht und Schatten"


def test_normalize_versalien_skips_protected_spans():
    md = "Text mit Wert und $WERT_1$ sowie <Bild> Foto:\nBeschreibung mit Bildtext: WERT\n</Bild>"
    assert ff.normalize_versalien(md) == md


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------

def test_post_process_structure_applies_fibs_formatting():
    md = (
        "# Stoffe\n\n"
        "Ein Kristall entsteht beim Abkühlen. Jeder KRISTALL hat eine Form.\n\n"
        "Die Formel lautet CO₂ und das Ion heißt NH₄⁺.\n\n"
        "<Bild> Foto: Ein Kristall auf einem Tisch. </Bild>\n"
    )
    out = post_process_structure(md)
    assert "Jeder _Kristall_ hat eine Form." in out
    assert "CO_2" in out and "NH_4^+" in out
    assert "<Bild> Foto:\nBeschreibung: Ein Kristall auf einem Tisch.\n</Bild>" in out


def test_post_process_structure_unwraps_orphan_sentence_number_braces():
    md = (
        "-\tZuerst gehst du raus. {1}\n"
        "-\tDa steht ein Fahrradständer. {2}\n\n"
        "Ein Begriff mit echter Fußnote{3}.\n\n"
        "<Anmerkung> 3 Echte Fußnotenerklärung. </Anmerkung>\n"
    )
    out = post_process_structure(md)
    assert "{1}" not in out and "Zuerst gehst du raus. 1" in out
    assert "{2}" not in out and "Da steht ein Fahrradständer. 2" in out
    assert "Fußnote{3}." in out
    assert "<Anmerkung> 3 Echte Fußnotenerklärung. </Anmerkung>" in out



def test_system_prompt_contains_new_fibs_rules():
    prompt = SYSTEM_PROMPTS["uebertragungsregeln_09_2025"]
    assert "Beschreibung mit Bildtext:" in prompt
    assert "dekorativ" in prompt.lower()
    assert "\\\\to" in prompt or "\\to" in prompt
    assert "Versalien" in prompt
    assert "Unicode" in prompt


def test_vlm_describer_uses_shared_prompt():
    import inspect
    from backend.services import vlm_describer
    from backend.services import llm_service

    assert "VLM_IMAGE_PROMPT" in inspect.getsource(vlm_describer)
    assert "VLM_IMAGE_PROMPT" in inspect.getsource(llm_service.describe_image)


def test_post_process_structure_wraps_diverse_callout_boxes():
    md = (
        "((10))\n\n"
        "**Strukturelle Eigenschaften des Versmaßes**\n\n"
        "Form und metrische Freiheit im Gedicht:\n\n"
        "- Hebungen: Vier Hebungen pro Zeile.\n"
        "- Senkungen: Freie Füllung.\n\n"
        "**LEARNING OBJECTIVES**\n\n"
        "By the end of this section, you will be able to:\n\n"
        "- Describe the roles of cells\n"
        "- Summarize the cell theory\n\n"
        "**CAREER CONNECTION**\n\n"
        "**Laboratory Specialist**\n\n"
        "Have you ever heard of a medical test? In this test, a doctor takes a small sample.\n\n"
        "Specialists are professionals who study cells through microscopic examinations.\n\n"
        "## Next Section\n\n"
        "**Versuchsprotokoll V4.1 – Gefahrstoffhinweise:**\n\n"
        "Materialien & Chemikalien: Reagenzgläser, Wasserbad.\n\n"
        "Durchführung: 3 mL Säure werden vorsichtig erwärmt.\n\n"
        "Beobachtung: Es bildet sich eine fruchtige Phase.\n\n"
        "Auswertung: Es stellt sich ein Gleichgewicht ein.\n\n"
        "**Bild 5.1: Interferenzmuster**\n\n"
        "- Kohärenzbedingung: Konstante Phasenbeziehung.\n"
        "- Verstärkung: Ganzzahliges Vielfaches.\n\n"
        "**Bild 5.2: Schematische Darstellung einer Photozelle**\n\n"
        "Vakuum-Photozelle mit bestrahlter Kathode und Ringanode.\n"
    )
    out = post_process_structure(md, raw_markdown=md)
    assert "<Rahmen>\n_Strukturelle Eigenschaften des Versmaßes_\nForm und metrische Freiheit im Gedicht:\n-\t_Hebungen:_" in out or "<Rahmen>\n_Strukturelle Eigenschaften des Versmaßes_\nForm und metrische Freiheit im Gedicht:\n-\tHebungen:" in out
    assert "<Rahmen>\n_LEARNING OBJECTIVES_\nBy the end of this section, you will be able to:\n-\tDescribe the roles of cells\n-\tSummarize the cell theory\n</Rahmen>" in out
    assert "<Rahmen>\n_CAREER CONNECTION: Laboratory Specialist_\nHave you ever heard of a medical test?" in out
    assert "Specialists are professionals who study cells through microscopic examinations.\n</Rahmen>" in out
    assert "<Rahmen>\n_Versuchsprotokoll V4.1 – Gefahrstoffhinweise:_" in out
    assert "-\t_Auswertung:_ Es stellt sich ein Gleichgewicht ein.\n</Rahmen>" in out
    assert "<Rahmen>\n_Bild 5.1: Interferenzmuster_" in out
    assert "<Rahmen>\n_Bild 5.2:" not in out

    # Also verify that if Gemma promotes a callout box title or short task prompt to '# Title',
    # post_process_structure demotes it back using raw_markdown and wraps the callout box in <Rahmen>
    gemma_promoted_md = (
        "((44))\n\n"
        "# Kapitel 3: Grammatik\n\n"
        "# Wo? (Dativ - Lage/Ruhe):\n\n"
        "Das Buch liegt auf dem Tisch.\n\n"
        "# Sprachschatz – Verben der Bewegung und Position\n\n"
        "- legen / liegen\n"
        "- stellen / stehen\n"
    )
    raw_ref_md = (
        "((44))\n\n"
        "# Kapitel 3: Grammatik\n\n"
        "**Wo? (Dativ - Lage/Ruhe):**\n\n"
        "Das Buch liegt auf dem Tisch.\n\n"
        "**Sprachschatz – Verben der Bewegung und Position**\n\n"
        "- legen / liegen\n"
        "- stellen / stehen\n"
    )
    out_promoted = post_process_structure(gemma_promoted_md, raw_markdown=raw_ref_md)
    assert "# Wo?" not in out_promoted
    assert "# Sprachschatz" not in out_promoted
    assert "<Rahmen>\n_Sprachschatz – Verben der Bewegung und Position_\n-\tlegen / liegen\n-\tstellen / stehen\n</Rahmen>" in out_promoted


def test_post_process_structure_composite_images_and_caption_headings():
    raw_md = (
        "((311))\n\n"
        "## 4.2 Strukturformeln\n\n"
        "![](images/picture_3_aaa.png)\n\n"
        "![](images/picture_4_bbb.png)\n\n"
        "### Abb. 4.1: Strukturformeln der Veresterung\n\n"
        "Im dynamischen Gleichgewicht bleibt der Quotient konstant.\n\n"
        "((312))\n\n"
        "#### Abb. 5.2: Beugung am optischen Gitter\n\n"
        "Schematischer Strahlengang am Mehrfachspalt.\n"
    )
    out = post_process_structure(raw_md, raw_markdown=raw_md)
    assert "#### Abb. 4.1: Strukturformeln der Veresterung" in out
    assert "#### Abb. 5.2: Beugung am optischen Gitter" in out
    assert out.count("<Bild>") == 1


# ---------------------------------------------------------------------------
# Phase 3a: PDF Vector Figure Crop, bbox_1000, Heading Clustering & Eurobraille
# ---------------------------------------------------------------------------


def test_normalize_bbox_to_1000_and_render_pdf_figure_crop():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from PIL import Image

    from backend.services.pdf_render_service import (
        compute_gemma4_optimal_dimensions,
        normalize_bbox_to_1000,
        render_pdf_figure_crop,
    )

    # 1. BOTTOMLEFT origin (standard PDF / Docling default)
    bbox_bl = SimpleNamespace(l=60.0, b=400.0, r=540.0, t=700.0, coord_origin="BOTTOMLEFT")
    norm_bl = normalize_bbox_to_1000(bbox_bl, page_width=600.0, page_height=1000.0)
    assert norm_bl == [100, 300, 900, 600]

    # 2. TOPLEFT origin sequence
    norm_tl = normalize_bbox_to_1000([30.0, 100.0, 300.0, 500.0], 600.0, 1000.0, coord_origin="TOPLEFT")
    assert norm_tl == [50, 100, 500, 500]

    # Invalid inputs return None
    assert normalize_bbox_to_1000(None, 600.0, 1000.0) is None
    assert normalize_bbox_to_1000([10, 10, 10, 10], 600.0, 1000.0) is None

    # 3. Vector sub-rectangle crop via pypdfium2 page.render(scale=..., crop=...)
    fake_page = MagicMock()
    fake_page.get_size.return_value = (600.0, 1000.0)
    fake_bitmap = MagicMock()
    fake_bitmap.to_pil.return_value = Image.new("RGB", (1392, 1740), color=(255, 255, 255))
    fake_page.render.return_value = fake_bitmap

    cropped = render_pdf_figure_crop(
        fake_page,
        [100, 200, 500, 500],
        target_longest_edge=2048,
        is_normalized_1000=True,
    )
    assert cropped is not None
    assert cropped.size == (1392, 1776)
    assert cropped.width % 48 == 0 and cropped.height % 48 == 0
    fake_page.render.assert_called_once()
    call_kwargs = fake_page.render.call_args.kwargs
    assert 0.2 <= call_kwargs["scale"] <= 8.0
    left_cut, bottom_cut, right_cut, top_cut = call_kwargs["crop"]
    assert pytest.approx(left_cut) == 60.0
    assert pytest.approx(bottom_cut) == 500.0
    assert pytest.approx(right_cut) == 300.0
    assert pytest.approx(top_cut) == 200.0

    # Unaligned mode preserves raw bitmap dimensions directly
    fake_bitmap.to_pil.return_value = Image.new("RGB", (1024, 768), color=(255, 255, 255))
    unaligned = render_pdf_figure_crop(
        fake_page,
        [100, 200, 500, 500],
        target_longest_edge=2048,
        is_normalized_1000=True,
        align_for_gemma4=False,
    )
    assert unaligned is not None
    assert unaligned.size == (1024, 768)

    # Degenerate tiny box returns None
    assert render_pdf_figure_crop(fake_page, [100, 100, 101, 101], is_normalized_1000=True) is None

    # 4. Verify Gemma 4 zero-downscaling fixed-point invariant across aspect ratios and token tiers
    from transformers.models.gemma4_unified.image_processing_gemma4_unified import (
        get_aspect_ratio_preserving_size,
    )

    for soft_tokens in (280, 560, 1120):
        for rw, rh in ((240.0, 300.0), (480.0, 300.0), (160.0, 100.0), (209.0, 963.0), (500.0, 120.0)):
            opt_w, opt_h = compute_gemma4_optimal_dimensions(rw, rh, max_soft_tokens=soft_tokens)
            assert opt_w % 48 == 0 and opt_h % 48 == 0
            assert (opt_w // 48) * (opt_h // 48) <= soft_tokens
            assert get_aspect_ratio_preserving_size(opt_h, opt_w, 16, soft_tokens * 9, 3) == (
                opt_h,
                opt_w,
            )

    # 5. Smart pure embedded raster extraction vs. hybrid/vector fallback
    import pypdfium2.raw as pdfium_c

    from backend.services.pdf_render_service import extract_raw_pdf_image

    pure_img_obj = MagicMock()
    pure_img_obj.type = pdfium_c.FPDF_PAGEOBJ_IMAGE
    pure_img_obj.get_bounds.return_value = (60.0, 500.0, 300.0, 800.0)
    pure_img_obj.get_px_size.return_value = (480, 600)
    pure_img_obj.get_matrix.return_value = SimpleNamespace(a=240.0, b=0.0, c=0.0, d=300.0, e=60.0, f=500.0)
    pure_bm = MagicMock()
    pure_bm.to_pil.return_value = Image.new("RGB", (480, 600), color=(120, 160, 200))
    pure_img_obj.get_bitmap.return_value = pure_bm

    raster_page = MagicMock()
    raster_page.get_size.return_value = (600.0, 1000.0)
    raster_page.get_bbox.return_value = (0.0, 0.0, 600.0, 1000.0)
    raster_page.get_objects.return_value = [pure_img_obj]

    raw_extracted, token_cap = extract_raw_pdf_image(raster_page, 60.0, 500.0, 300.0, 800.0)
    assert raw_extracted is not None
    assert raw_extracted.size == (480, 600)
    assert token_cap == 280  # 480x600 low-res JPEG is capped to 280 soft tokens instead of 1120

    # render_pdf_figure_crop uses direct bitmap without calling raster_page.render()
    direct_aligned = render_pdf_figure_crop(
        raster_page,
        [100, 200, 500, 500],
        is_normalized_1000=True,
        align_for_gemma4=True,
    )
    assert direct_aligned is not None
    assert direct_aligned.width % 48 == 0 and direct_aligned.height % 48 == 0
    assert (direct_aligned.width // 48) * (direct_aligned.height // 48) <= 280
    raster_page.render.assert_not_called()

    # Hybrid figure with overlaid text label inside bbox falls back to vector page.render()
    overlaid_text_obj = MagicMock()
    overlaid_text_obj.type = pdfium_c.FPDF_PAGEOBJ_TEXT
    overlaid_text_obj.get_bounds.return_value = (120.0, 600.0, 180.0, 620.0)
    raster_page.get_objects.return_value = [pure_img_obj, overlaid_text_obj]
    raster_page.render.return_value = fake_bitmap

    raw_hybrid, hybrid_cap = extract_raw_pdf_image(raster_page, 60.0, 500.0, 300.0, 800.0)
    assert raw_hybrid is None
    assert hybrid_cap is None

    hybrid_rendered = render_pdf_figure_crop(
        raster_page,
        [100, 200, 500, 500],
        is_normalized_1000=True,
        align_for_gemma4=True,
    )
    assert hybrid_rendered is not None
    raster_page.render.assert_called_once()

    # Image with transparent SMask (alpha < 250) falls back to page.render() but preserves native token cap
    raster_page.render.reset_mock()
    smask_rgba = Image.new("RGBA", (480, 600), color=(120, 160, 200, 0))
    pure_bm.to_pil.return_value = smask_rgba
    raster_page.get_objects.return_value = [pure_img_obj]

    raw_smask, smask_cap = extract_raw_pdf_image(raster_page, 60.0, 500.0, 300.0, 800.0)
    assert raw_smask is None
    assert smask_cap == 280


def test_cluster_heading_heights_and_clamp_heading_outline_levels():
    from backend.services.extraction_postprocess import (
        clamp_heading_outline_levels,
        cluster_heading_heights,
    )

    # Descending height clustering within tolerance
    means = cluster_heading_heights([28.0, 26.0, 18.0, 17.0, 11.0], tol=4.0)
    assert means == [27.0, 17.5, 11.0]
    assert cluster_heading_heights([]) == []

    # Sequential outline clamping without breaking FIBS '### Aufgabe N:' under H1/H2
    raw_md = (
        "# Kapitel 1: Grundlagen\n\n"
        "#### 1.1 Übersprungene Ebene\n\n"
        "Text.\n\n"
        "# Kapitel 2: Übungen\n\n"
        "### Aufgabe 1: Direkte FIBS-Aufgabe unter H1\n"
    )
    clamped = clamp_heading_outline_levels(raw_md)
    assert "## 1.1 Übersprungene Ebene" in clamped
    assert "### Aufgabe 1: Direkte FIBS-Aufgabe unter H1" in clamped


def test_find_non_latin1_chars_and_parse_suggestions():
    from backend.services.prompts import build_char_replacement_prompt

    sample = "Winkel α = 30°, Pfeil → und H₂O sowie α erneut und ☐ Kästchen."
    found = ff.find_non_latin1_chars(sample, existing_map={"→": {"replacement": "\\rightarrow", "active": False}})
    chars_by_glyph = {item.ch: item for item in found}

    # ASCII and Latin-1 ('°' is U+00B0 <= U+00FF) must be excluded
    assert "°" not in chars_by_glyph
    assert "A" not in chars_by_glyph

    # Non-Latin-1 characters (> U+00FF) are counted and sorted by codepoint
    assert [item.ch for item in found] == sorted([item.ch for item in found], key=ord)
    assert chars_by_glyph["α"].count == 2
    assert chars_by_glyph["α"].hex_code == "U+03B1"
    assert chars_by_glyph["α"].replacement == "\\alpha"
    assert chars_by_glyph["→"].replacement == "\\rightarrow"
    assert chars_by_glyph["→"].active is False
    assert chars_by_glyph["₂"].replacement == "_2"
    assert chars_by_glyph["☐"].replacement == "[ ]"

    prompt = build_char_replacement_prompt("α (Code U+03B1)\n🔊 (Code U+1F50A)")
    assert "EuroBraille-Zeichensatz" in prompt
    assert "U+03B1" in prompt

    # JSON response with <think> block and code fences
    raw_json = (
        "<think>Überlege passende LaTeX-Ersetzungen...</think>\n"
        "```json\n"
        '{"vorschlaege": [\n'
        '  {"code": "U+03B1", "zeichen": "α", "ersetzung": "Greek alpha: `\\\\alpha`"},\n'
        '  {"code": "U+1F50A", "zeichen": "🔊", "ersetzung": "Lautsprecher: [Audio]"},\n'
        '  {"code": "U+9999", "zeichen": "香", "ersetzung": "[Unangefragt]"}\n'
        "]}\n"
        "```"
    )
    parsed_json = ff.parse_char_replacement_suggestions(raw_json, ["α", "🔊"])
    assert parsed_json == {"α": "\\alpha", "🔊": "[Audio]"}

    # Line-based fallback format
    raw_lines = "- U+03B2: \\beta\n- → → `\\to`"
    parsed_lines = ff.parse_char_replacement_suggestions(raw_lines, ["β", "→"])
    assert parsed_lines == {"β": "\\beta", "→": "\\to"}


def test_layout_and_char_replacement_api_endpoints(tmp_path, monkeypatch):
    import json
    from fastapi.testclient import TestClient
    import backend.main as main_mod

    monkeypatch.setattr(main_mod, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("E2E_MOCK", "true")

    task_id = "test-layout-task-123"
    auto_dir = tmp_path / task_id / "auto"
    auto_dir.mkdir(parents=True)
    cl_path = auto_dir / "sample_content_list.json"
    cl_path.write_text(
        json.dumps([
            {
                "type": "title",
                "text": "Kapitel 1",
                "page_idx": 0,
                "text_level": 1,
                "bbox": [0, 0, 200, 18.0],
                "bbox_1000": [100, 80, 600, 130],
                "is_callout_box": False,
            },
            {
                "type": "image",
                "text": "![](images/pic0.png)",
                "page_idx": 0,
                "bbox_1000": [120, 200, 800, 550],
            },
        ]),
        encoding="utf-8",
    )

    client = TestClient(main_mod.app)
    res_layout = client.get(f"/api/tasks/{task_id}/layout")
    assert res_layout.status_code == 200
    body = res_layout.json()
    assert body["task_id"] == task_id
    assert body["physical_start_page"] == 1
    assert len(body["blocks"]) == 2
    assert body["blocks"][0]["bbox_1000"] == [100, 80, 600, 130]
    assert body["blocks"][1]["type"] == "image"

    res_missing = client.get("/api/tasks/nonexistent-task-id/layout")
    assert res_missing.status_code == 404

    res_suggest = client.post(
        "/api/char-replacements/suggest",
        json={"chars": ["α", "→", "☐", "🔊"]},
    )
    assert res_suggest.status_code == 200
    suggestions = res_suggest.json()["suggestions"]
    assert suggestions["α"] == "\\alpha"
    assert suggestions["→"] == "\\to"
    assert suggestions["☐"] == "[ ]"
    assert suggestions["🔊"] == "[Audio]"


