"""Data models for E-Buch conversion, FIBS accessibility linting, and feedback analysis."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.services import fibs_constants as fc


class DomainModel(BaseModel):
    """Base Pydantic domain model with assignment validation and attribute docstrings."""

    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
        use_attribute_docstrings=True,
    )


class VlmDescriptionResult(DomainModel):
    """Structured VLM image description parsed from Qwen/Gemma output."""

    image_type: str = ""
    """FIBS image category label (e.g. 'Foto', 'Diagramm', 'Grafik')."""
    has_text: bool | None = None
    """Whether the image contains readable text or labels, or None if unspecified."""
    decorative: bool = False
    """Whether the VLM classified the image as purely decorative."""
    description: str = ""
    """Factual visual description text without structural header lines."""


class PageSegment(DomainModel):
    """A single page segment split from extracted Markdown along ``((n))`` markers."""

    page: str | None = None
    """Printed book page number from the ((n)) marker, or None for preamble text."""
    text: str = ""
    """Raw Markdown content belonging to this page segment."""


class TableDescription(DomainModel):
    """Cell count and resolution decision for one table in Markdown."""

    cells: int = Field(default=0, ge=0)
    """Total number of cells counted across all table rows."""
    resolve: bool = False
    """Whether the table has few enough cells to be linearly resolved into paragraphs."""


class StandardisationChunk(DomainModel):
    """A planned page-chunked Gemma standardisation request."""

    index: int = Field(ge=1)
    """1-based sequential index of this chunk within the document plan."""
    text: str
    """Primary Markdown section to be standardised in this request."""
    pages: list[str | None] = Field(default_factory=list)
    """Ordered list of printed page identifiers covered by this chunk."""
    part: int | None = None
    """1-based sub-page part index when an oversized page is split across chunks."""
    prev_context: str = ""
    """Read-only trailing excerpt from the preceding page or chunk."""
    next_context: str = ""
    """Read-only leading excerpt from the following page or chunk."""
    prev_page: str | None = None
    """Page identifier of prev_context for echo trimming, if any."""
    next_page: str | None = None
    """Page identifier of next_context for echo trimming, if any."""
    estimated_request_tokens: int = 0
    """Estimated total prompt and output budget tokens for this request."""

    @property
    def label(self) -> str:
        """Human-readable German label for the page range covered by this chunk.

        Returns:
            Formatted label such as ``"Seite 12"`` or ``"Seiten 12–13 (Teil 1)"``.
        """
        valid_pages = [p for p in self.pages if p]
        if not valid_pages:
            base = "Vorspann"
        elif len(valid_pages) == 1:
            base = f"Seite {valid_pages[0]}"
        else:
            base = f"Seiten {valid_pages[0]}–{valid_pages[-1]}"
        return f"{base} (Teil {self.part})" if self.part else base

    @property
    def max_output_tokens(self) -> int:
        """Maximum output token allowance for this chunk based on its input length.

        Returns:
            Bounded output token limit for the LLM call.
        """
        est_tokens = int(len(self.text or "") / fc.CHARS_PER_TOKEN) + 1
        return min(
            fc.GEMMA_MAX_OUTPUT_TOKENS,
            int(est_tokens * fc.OUTPUT_TOKEN_FACTOR) + fc.OUTPUT_TOKEN_MARGIN,
        )


class LintIssue(DomainModel):
    """A single FIBS accessibility linter finding."""

    rule: str
    """Machine-readable rule identifier (e.g. 'heading_hierarchy')."""
    severity: Literal["error", "warning", "info"]
    """Issue severity level ('error', 'warning', or 'info')."""
    line: int = Field(ge=1)
    """1-based line number in the inspected Markdown document."""
    message: str
    """Actionable German diagnostic message explaining the violation."""
    snippet: str = ""
    """Short excerpt of the offending Markdown line or block."""


class LintReport(DomainModel):
    """Structured FIBS 09/2025 accessibility compliance report."""

    score: int = Field(ge=0, le=100)
    """Overall compliance score between 0 and 100."""
    passed: bool
    """Whether the document has zero errors and zero warnings."""
    error_count: int = Field(ge=0)
    """Number of 'error' severity findings."""
    warning_count: int = Field(ge=0)
    """Number of 'warning' severity findings."""
    info_count: int = Field(ge=0)
    """Number of 'info' severity findings."""
    categories: dict[str, bool] = Field(default_factory=dict)
    """Per-category pass/fail flags (e.g. headings, images, tables)."""
    issues: list[LintIssue] = Field(default_factory=list)
    """List of individual LintIssue findings detected in the document."""


class DiffHunk(DomainModel):
    """Shortened diff hunk between an automatic transfer and a manual revision."""

    op: str
    """Diff opcode tag ('replace', 'delete', or 'insert')."""
    original_line: int
    """1-based starting line number in the original automatic transfer."""
    revised_line: int
    """1-based starting line number in the manually revised transfer."""
    removed: list[str] = Field(default_factory=list)
    """Shortened non-empty line snippets removed from the original transfer."""
    added: list[str] = Field(default_factory=list)
    """Shortened non-empty line snippets added in the revised transfer."""
    removed_line_count: int = 0
    """Total number of lines removed in this hunk."""
    added_line_count: int = 0
    """Total number of lines added in this hunk."""
    categories: list[str] = Field(default_factory=list)
    """Sorted structural E-Buch categories affected by this hunk."""


class OpenQuestion(DomainModel):
    """An open rule/layout question parsed from ``## Offene Fragen`` in a feedback report."""

    question: str
    """Question text directed at the user or domain expert."""
    answer: str | None = None
    """User-provided answer string, or None if unanswered/skipped."""


class SettingSchemaEntry(DomainModel):
    """Schema metadata and validation bounds for a single persistent application setting."""

    key: str
    """Unique machine-readable setting identifier in settings.json."""
    type: Literal["integer"] = "integer"
    """Value data type of the setting (currently 'integer')."""
    default: int
    """Default integer value used when the setting is not persisted."""
    min: int
    """Minimum allowed integer value (inclusive)."""
    max: int
    """Maximum allowed integer value (inclusive)."""
    group: str
    """German UI section heading under which the setting is grouped."""
    label: str
    """German human-readable label displayed next to the input control."""
    description: str
    """German help text explaining the effect and bounds of the setting."""

