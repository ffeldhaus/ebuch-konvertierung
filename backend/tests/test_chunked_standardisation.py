"""
Tests for the chunked (page-wise) Gemma standardisation.

Background: sending a whole book (e.g. 27 pages / 129k characters) in a single
rapid-mlx request exceeds the Metal KV-cache cap (BackpressureError) and the
8192 output-token limit. The document is therefore standardised in sections of
whole pages, each request carrying the previous and the following page as
read-only context. A failing Gemma call must fail the task instead of silently
falling back to the rule-based standardiser.

All markdown below is synthetic test content.
"""
import pytest

import backend.services.llm_service as llm
from backend.services import fibs_constants as fc
from backend.services.fibs_postprocess import post_process_structure, split_markdown_pages
from backend.services.llm_service import (
    StandardisationAborted,
    StandardisationError,
    _trim_to_own_pages,
    build_chunk_user_message,
    build_standardisation_chunks,
    describe_tables,
    standardise_markdown,
)
from backend.services.models import StandardisationChunk
from backend.services.prompts import table_resolution_rule


def _page(num: int, body: str) -> str:
    return f"(({num}))\n\n{body}\n"


def _book(pages: dict[int, str]) -> str:
    return "\n".join(_page(n, b) for n, b in pages.items())


# ---------------------------------------------------------------------------
# Mock rapid-mlx client (OpenAI streaming interface)
# ---------------------------------------------------------------------------
class _Delta:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.delta = _Delta(content)


class _Chunk:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class RecordingClient:
    """Echoes the section between the [ABSCHNITT] markers (or the whole input)."""

    def __init__(self, fail_times: int = 0, error: Exception | None = None, empty: bool = False):
        self.calls: list[dict] = []
        self.fail_times = fail_times
        self.error = error or RuntimeError("Internal error during streaming")
        self.empty = empty
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                if outer.fail_times > 0:
                    outer.fail_times -= 1
                    raise outer.error
                if outer.empty:
                    return [_Chunk("")]
                user = kwargs["messages"][1]["content"]
                section = user
                if "[ABSCHNITT" in user:
                    # Echo only the section body between the header line and [ENDE ABSCHNITT]
                    start = user.index("[ABSCHNITT")
                    section = user[start:].split("\n", 1)[1].split("\n[ENDE ABSCHNITT]", 1)[0]
                half = len(section) // 2
                return [_Chunk(section[:half]), _Chunk(section[half:])]

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


# ---------------------------------------------------------------------------
# Page splitting & chunk planning
# ---------------------------------------------------------------------------
def test_split_markdown_pages_keeps_marker_with_its_page():
    md = "Vorspann ohne Seitenzahl.\n\n" + _book({10: "Erste Seite.", 11: "Zweite Seite."})
    pages = split_markdown_pages(md)
    assert [p.page for p in pages] == [None, "10", "11"]
    assert pages[1].text.startswith("((10))")
    assert "Zweite Seite." in pages[2].text
    # Lossless: concatenation restores the input
    assert "".join(p.text for p in pages) == md


def test_short_document_is_a_single_chunk_without_context():
    md = _book({1: "Kurzer Text.", 2: "Noch ein kurzer Text."})
    chunks = build_standardisation_chunks(md, system_prompt="S" * 300, token_budget=11000)
    assert len(chunks) == 1
    assert chunks[0].prev_context == ""
    assert chunks[0].next_context == ""
    assert chunks[0].text == md


def test_long_document_is_split_at_page_boundaries_with_neighbour_context():
    body = "Ein Satz über Kohlenstoffverbindungen und ihre Eigenschaften. " * 40  # ~2.5k chars per page
    md = _book({n: f"Seite {n}: {body}" for n in range(30, 36)})
    chunks = build_standardisation_chunks(md, system_prompt="S" * 3000, token_budget=6000)
    assert len(chunks) > 1
    # Every chunk starts with a page marker and the chunks reassemble the document losslessly
    assert "".join(c.text for c in chunks) == md
    for c in chunks:
        assert c.text.lstrip().startswith("((")
    # Context = tail of the previous page / head of the following page (truncated to the budget)
    assert chunks[0].prev_context == ""
    assert chunks[1].prev_context.strip()
    assert chunks[0].text.rstrip().endswith(chunks[1].prev_context.strip())
    assert chunks[-1].next_context == ""
    first_page_of_second = chunks[1].text.split("\n", 1)[0]
    assert first_page_of_second.startswith("((")
    assert chunks[0].next_context.startswith(first_page_of_second)
    # Request fits the budget (prompt + context + output allowance)
    for c in chunks:
        assert c.estimated_request_tokens <= 6000
    assert chunks[0].label.startswith("Seite")


def test_oversized_page_is_split_at_paragraphs_without_breaking_blocks():
    para = "Absatz mit erklärendem Text zur Reaktionsgleichung. " * 20
    table = "<Tabelle>\n" + "\n".join(f"Zeile {i}\tWert {i}" for i in range(40)) + "\n</Tabelle>"
    body = "\n\n".join([para, para, table, para, para, para])
    md = _page(40, body) + _page(41, "Kurze Folgeseite.")
    chunks = build_standardisation_chunks(md, system_prompt="S" * 600, token_budget=2500)
    assert len(chunks) >= 3
    assert "".join(c.text for c in chunks) == md
    for c in chunks:
        # A <Tabelle> block is never torn apart
        assert c.text.count("<Tabelle>") == c.text.count("</Tabelle>")


def test_chunk_user_message_marks_context_as_read_only():
    body = "Text " * 900
    md = _book({1: body, 2: body, 3: body})
    chunks = build_standardisation_chunks(md, system_prompt="S" * 600, token_budget=3500)
    middle = chunks[1]
    msg = build_chunk_user_message(middle, len(chunks), table_max_cells=0)
    assert "[KONTEXT: VORHERIGE SEITE" in msg
    assert "[KONTEXT: FOLGENDE SEITE" in msg
    assert "NICHT ausgeben" in msg
    assert f"[ABSCHNITT 2/{len(chunks)}" in msg
    assert msg.index("VORHERIGE SEITE") < msg.index("[ABSCHNITT") < msg.index("FOLGENDE SEITE")


# ---------------------------------------------------------------------------
# Table resolution setting
# ---------------------------------------------------------------------------
def test_context_pages_copied_by_gemma_are_removed():
    chunk = StandardisationChunk(index=2, text="((8))\n\nEigener Text.\n", pages=["8"],
                                 prev_page="7", next_page="9")
    leaked = "((7))\n\nKopierter Kontext.\n\n((8))\n\nEigener Text.\n\n((9))\n\nNoch mehr Kontext."
    assert _trim_to_own_pages(leaked, chunk) == "((8))\n\nEigener Text."
def test_empty_markdown_cells_are_counted_and_one_run_is_one_table():
    md = "| Kopf | Kopf |\n|---|---|\n|   |   |\n|   |   |\n\nText danach.\n"
    tables = describe_tables(md, max_cells=6)
    assert [t.cells for t in tables] == [6]
    # Pipe lines inside a code fence (e.g. ASCII-art formula from OCR) are not tables
    fenced = "```\nH H H\n| | |\n+---+---+\n|   |   |\n+---+---+\n|   |   |\n```\n"
    assert describe_tables(fenced + md, max_cells=6) == tables
    # An unclosed fence (truncated OCR output) runs to the end of the text
    assert describe_tables(md + "\n```\n|   |   |\n|   |   |\n", max_cells=6) == tables


def test_describe_tables_counts_cells_of_markdown_html_and_fibs_tables():
    md = (
        "| Bindung | Differenz |\n|---|---|\n| A-B | _..._ |\n| C-D | _..._ |\n\n"
        "<table><tr><th>x</th><th>y</th></tr><tr><td>1</td><td>2</td></tr></table>\n\n"
        "<Tabelle>\nKopf 1\tKopf 2\tKopf 3\nW1\tW2\tW3\nW4\tW5\tW6\n</Tabelle>\n"
    )
    tables = describe_tables(md, max_cells=6)
    assert [t.cells for t in tables] == [6, 4, 9]
    assert [t.resolve for t in tables] == [True, True, False]


def test_table_rule_and_hint_follow_the_configured_threshold():
    rule = table_resolution_rule(6)
    assert "höchstens 6 Zellen" in rule
    assert "Die folgende Tabelle wurde aufgelöst." in rule
    assert table_resolution_rule(0) == ""

    md = _page(5, "| a | b |\n|---|---|\n| c | d |")
    chunk = build_standardisation_chunks(md, system_prompt="S", token_budget=11000)[0]
    msg = build_chunk_user_message(chunk, 2, table_max_cells=6)
    assert "Tabelle 1: 4 Zellen" in msg
    assert "auflösen" in msg


def test_system_prompt_contains_table_rule_from_settings(monkeypatch):
    client = RecordingClient()
    monkeypatch.setattr(llm, "start_rapid_mlx", lambda: client)
    standardise_markdown(_page(1, "Kurzer Text."), table_max_cells=6)
    system_prompt = client.calls[0]["messages"][0]["content"]
    assert "höchstens 6 Zellen" in system_prompt


# ---------------------------------------------------------------------------
# Chunked standardisation end-to-end (mocked Gemma)
# ---------------------------------------------------------------------------
def test_standardise_markdown_runs_one_request_per_chunk_and_reassembles(monkeypatch):
    body = "Ein Satz über Reaktionen und Teilchenmodelle im Unterricht. " * 60
    md = _book({n: f"Inhalt der Seite {n}. {body}" for n in range(20, 26)})
    client = RecordingClient()
    monkeypatch.setattr(llm, "start_rapid_mlx", lambda: client)
    monkeypatch.setattr(fc, "GEMMA_REQUEST_TOKEN_BUDGET", 6000)

    tokens: list[str] = []
    progress: list[dict] = []
    result = standardise_markdown(
        md, table_max_cells=0, on_token_callback=tokens.append, on_progress=progress.append
    )

    assert len(client.calls) > 1
    for call in client.calls:
        # Dynamic output allowance keeps the projected KV cache bounded
        assert call["max_tokens"] <= 8192
        assert call["stream"] is True
    for n in range(20, 26):
        assert f"(({n}))" in result
        assert f"Inhalt der Seite {n}." in result
    assert "[ABSCHNITT" not in result and "[KONTEXT" not in result
    starts = [p for p in progress if p["event"] == "start"]
    assert len(starts) == len(client.calls)
    assert starts[0]["index"] == 1 and starts[-1]["index"] == starts[-1]["total"]


def test_echoed_section_markers_are_removed(monkeypatch):
    class EchoClient(RecordingClient):
        pass

    client = EchoClient()

    def create(**kwargs):
        client.calls.append(kwargs)
        return [_Chunk("[ABSCHNITT 1/1 – Seite 1]\n((1))\n\nText.\n[ENDE ABSCHNITT]")]

    client.chat.completions.create = create
    monkeypatch.setattr(llm, "start_rapid_mlx", lambda: client)
    result = standardise_markdown(_page(1, "Text."), table_max_cells=0)
    assert "[ABSCHNITT" not in result
    assert "[ENDE ABSCHNITT]" not in result
    assert "Text." in result


# ---------------------------------------------------------------------------
# No silent fallback
# ---------------------------------------------------------------------------
def test_transient_gemma_error_is_retried_once(monkeypatch):
    client = RecordingClient(fail_times=1)
    monkeypatch.setattr(llm, "start_rapid_mlx", lambda: client)
    monkeypatch.setattr(llm, "close_engine", lambda: None)
    progress: list[dict] = []
    result = standardise_markdown(_page(3, "Ein kurzer Absatz."), table_max_cells=0, on_progress=progress.append)
    assert "Ein kurzer Absatz." in result
    assert len(client.calls) == 2
    assert any(p["event"] == "retry" for p in progress)


def test_persistent_gemma_error_fails_instead_of_falling_back(monkeypatch):
    client = RecordingClient(fail_times=5)
    monkeypatch.setattr(llm, "start_rapid_mlx", lambda: client)
    monkeypatch.setattr(llm, "close_engine", lambda: None)
    monkeypatch.setattr(llm, "standardise_markdown_fallback",
                        lambda *a, **k: pytest.fail("rule-based fallback must not run"))
    with pytest.raises(StandardisationError) as exc:
        standardise_markdown(_page(3, "Ein kurzer Absatz."), table_max_cells=0)
    assert "Abschnitt 1/1" in str(exc.value)
    assert len(client.calls) == 2


def test_empty_gemma_answer_counts_as_failure(monkeypatch):
    client = RecordingClient(empty=True)
    monkeypatch.setattr(llm, "start_rapid_mlx", lambda: client)
    monkeypatch.setattr(llm, "close_engine", lambda: None)
    with pytest.raises(StandardisationError):
        standardise_markdown(_page(3, "Ein kurzer Absatz."), table_max_cells=0)


def test_missing_llm_fails_unless_fallback_is_explicitly_allowed(monkeypatch):
    monkeypatch.setattr(llm, "start_rapid_mlx", lambda: None)
    monkeypatch.setattr(llm, "_run_torch_cuda_llm", lambda *a, **k: None)
    monkeypatch.delenv("E2E_MOCK", raising=False)
    monkeypatch.delenv("ALLOW_RULE_BASED_FALLBACK", raising=False)
    with pytest.raises(StandardisationError):
        standardise_markdown("Some **bold** text.", table_max_cells=0)
    # Explicit opt-in (E2E mock / tests) still uses the deterministic standardiser
    assert standardise_markdown("Some **bold** text.", table_max_cells=0, allow_fallback=True) == "Some _bold_ text."


def test_abort_from_token_callback_stops_generation(monkeypatch):
    body = "Satz. " * 800
    md = _book({1: body, 2: body, 3: body})
    client = RecordingClient()
    monkeypatch.setattr(llm, "start_rapid_mlx", lambda: client)
    monkeypatch.setattr(fc, "GEMMA_REQUEST_TOKEN_BUDGET", 3500)

    def on_token(_delta):
        raise StandardisationAborted("abgebrochen")

    with pytest.raises(StandardisationAborted):
        standardise_markdown(md, table_max_cells=0, on_token_callback=on_token)
    # Aborted during the first section: no retry, no further sections
    assert len(client.calls) == 1


def test_four_page_document_splits_into_two_page_chunks_and_recovers_dropped_rahmen():
    # 1. Even when 4 pages have moderate token count (< 11000 budget), MAX_PAGES_PER_CHUNK=2
    # must split the 4-page document into 2 chunks of 2 pages each so Gemma never drops tail boxes.
    md_4pages = _book(
        {
            32: "Text auf Seite 32.",
            33: "Text auf Seite 33.",
            34: "Text auf Seite 34.",
            35: "Text auf Seite 35.",
        }
    )
    chunks = build_standardisation_chunks(md_4pages, system_prompt="S" * 300, token_budget=11000)
    assert len(chunks) == 2
    assert chunks[0].pages == ["32", "33"]
    assert chunks[1].pages == ["34", "35"]

    # 2. If Gemma omits a <Rahmen> block present in raw_markdown on page ((34)),
    # or strips <Rahmen> tags around a preserved box on page ((35)), post_process_structure recovers both.
    raw_md = (
        "((34))\n\n"
        "Haupttext auf Seite 34.\n\n"
        "<Rahmen>\n"
        "_Sprachschatz_\n"
        "-\tWo? rechts, links, gegenüber vom Park\n"
        "-\tWas tun? in Richtung gehen, abbiegen, überqueren\n"
        "</Rahmen>\n\n"
        "((35))\n\n"
        "Haupttext auf Seite 35.\n\n"
        "<Rahmen>\n"
        "_Methode: Wegbeschreibung prüfen_\n"
        "-\tSind alle Angaben genau?\n"
        "-\tWelche Verbesserungsvorschläge habt ihr?\n"
        "</Rahmen>\n"
    )
    gemma_incomplete = (
        "((34))\n\n"
        "Haupttext auf Seite 34.\n\n"
        "((35))\n\n"
        "Haupttext auf Seite 35.\n\n"
        "_Methode: Wegbeschreibung prüfen_\n"
        "-\tSind alle Angaben genau?\n"
        "-\tWelche Verbesserungsvorschläge habt ihr?\n"
    )
    recovered = post_process_structure(gemma_incomplete, raw_markdown=raw_md)
    assert recovered.count("<Rahmen>") == 2
    assert recovered.count("</Rahmen>") == 2
    assert "gegenüber vom Park" in recovered
    assert "überqueren" in recovered

