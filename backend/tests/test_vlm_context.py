"""
Tests for page-context-aware, compact VLM image descriptions.

Rule (user decision 14.10.): Gemma gets the text of the image's page. If that page does not
start with a heading, the text from the end of the previous page – starting at its last
heading, or the whole previous page if it has none – is prepended. The description itself
must stay compact and focus on the core of the image; the context only helps to pick the
relevant aspects and terminology (AGENTS.md: describe only what is visible).

All markdown below is synthetic.
"""
import json

from backend.services import fibs_formatting as ff
from backend.services import vlm_describer
from backend.services.fibs_constants import IMAGE_POSITION_MARKER, VLM_CONTEXT_MAX_CHARS
from backend.services.prompts import VLM_IMAGE_PROMPT, build_vlm_prompt


IMG_A = "![](images/a.png)"
IMG_B = "![](images/b.png)"


def _ctx(md: str, img: str) -> str:
    return ff.image_page_context(md, md.index(img), md.index(img) + len(img))


def test_context_is_the_current_page_when_it_starts_with_a_heading():
    md = (
        "((10))\n\n# Kapitel\n\nText auf Seite zehn.\n\n"
        "((11))\n\n## Versuch mit Kerzen\n\nAufbau des Versuchs.\n\n" + IMG_A + "\n\nAuswertung folgt.\n\n"
        "((12))\n\nFolgeseite.\n"
    )
    ctx = _ctx(md, IMG_A)
    assert "## Versuch mit Kerzen" in ctx
    assert "Aufbau des Versuchs." in ctx and "Auswertung folgt." in ctx
    assert "Text auf Seite zehn." not in ctx      # previous page not needed
    assert "Folgeseite." not in ctx               # following page never included
    assert "((11))" not in ctx                    # page markers are stripped
    assert IMAGE_POSITION_MARKER in ctx           # position of the image is marked
    assert "images/a.png" not in ctx


def test_previous_page_from_last_heading_is_added_when_page_starts_with_text():
    md = (
        "((20))\n\n## Erster Abschnitt\n\nAlter Inhalt.\n\n### Letzter Abschnitt\n\nBeginn des Satzes, der\n\n"
        "((21))\n\nweitergeht auf der neuen Seite.\n\n" + IMG_A + "\n"
    )
    ctx = _ctx(md, IMG_A)
    assert "### Letzter Abschnitt" in ctx
    assert "Beginn des Satzes, der" in ctx
    assert "weitergeht auf der neuen Seite." in ctx
    assert "Alter Inhalt." not in ctx
    assert "## Erster Abschnitt" not in ctx
    assert ctx.index("Letzter Abschnitt") < ctx.index("weitergeht")


def test_whole_previous_page_is_added_when_it_has_no_heading():
    md = (
        "((30))\n\nGanze Vorseite ohne Überschrift.\n\nZweiter Absatz.\n\n"
        "((31))\n\n" + IMG_A + "\n\nText nach dem Bild.\n"
    )
    ctx = _ctx(md, IMG_A)
    # Page 31 starts with an image (no heading) → previous page is included completely
    assert "Ganze Vorseite ohne Überschrift." in ctx and "Zweiter Absatz." in ctx
    assert "Text nach dem Bild." in ctx


def test_other_images_and_bild_blocks_are_reduced_to_placeholders():
    md = (
        "((5))\n\n# Titel\n\n" + IMG_B + "\n\n<Bild> Foto:\nBeschreibung: Lange alte Beschreibung.\n</Bild>\n\n"
        + IMG_A + "\n"
    )
    ctx = _ctx(md, IMG_A)
    assert "images/b.png" not in ctx
    assert "Lange alte Beschreibung." not in ctx
    assert ctx.count("[Bild]") == 2
    assert ctx.count(IMAGE_POSITION_MARKER) == 1


def test_document_without_page_markers_uses_whole_text_and_is_capped():
    md = "Einleitung.\n\n" + ("Langer Absatz. " * 800) + "\n\n" + IMG_A + "\n\nSchluss."
    ctx = _ctx(md, IMG_A)
    assert len(ctx) <= VLM_CONTEXT_MAX_CHARS
    # The text closest to the image is kept when trimming
    assert IMAGE_POSITION_MARKER in ctx and "Schluss." in ctx


def test_vlm_prompt_is_compact_and_context_is_read_only():
    base = VLM_IMAGE_PROMPT
    assert "kurz" in base.lower() or "kompakt" in base.lower()
    assert "Kern" in base
    assert build_vlm_prompt("") == base
    prompt = build_vlm_prompt("## Versuch\n\nText.")
    assert prompt.startswith(base.split("Antworte exakt")[0][:50])
    assert "SEITENKONTEXT" in prompt and "## Versuch" in prompt
    # The context must never become content of the description
    assert "nur, was im Bild" in prompt or "nur das, was im Bild" in prompt
    # The answer format stays last so the structured parser keeps working
    assert prompt.rstrip().endswith("<Bildbeschreibung>")


def test_image_contexts_for_markdown_maps_each_image_path():
    md = "((1))\n\n# A\n\nText eins.\n\n" + IMG_A + "\n\n((2))\n\n# B\n\nText zwei.\n\n" + IMG_B + "\n"
    contexts = ff.image_contexts_for_markdown(md, {IMG_A: "/x/a.png", IMG_B: "/x/b.png"})
    assert set(contexts) == {"/x/a.png", "/x/b.png"}
    assert "Text eins." in contexts["/x/a.png"] and "Text zwei." not in contexts["/x/a.png"]
    assert "Text zwei." in contexts["/x/b.png"]


def test_checkpoint_is_bound_to_prompt_and_context(tmp_path):
    import hashlib

    cache = tmp_path / "vlm_cache.json"
    p1 = build_vlm_prompt("Kontext 1")
    p2 = build_vlm_prompt("Kontext 2")
    key_a = f"/x/a.png#{hashlib.sha256(p1.encode('utf-8')).hexdigest()[:16]}"
    key_b = f"/x/a.png#{hashlib.sha256(p2.encode('utf-8')).hexdigest()[:16]}"
    vlm_describer.save_cache(str(cache), VLM_IMAGE_PROMPT, {key_a: "BESCHREIBUNG:\nEin Glas."})
    loaded = vlm_describer.load_cache(str(cache), VLM_IMAGE_PROMPT)
    assert loaded[key_a] == "BESCHREIBUNG:\nEin Glas."
    # A different page context yields a different key → image is described again
    assert key_b not in loaded
    # Old-format checkpoints (plain path keys, other prompt) are ignored
    cache.write_text(json.dumps({"prompt": "alt", "descriptions": {"/x/a.png": "x"}}), encoding="utf-8")
    assert vlm_describer.load_cache(str(cache), VLM_IMAGE_PROMPT) == {}
