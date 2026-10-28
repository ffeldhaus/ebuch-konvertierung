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

