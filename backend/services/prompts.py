"""LLM and VLM prompts and Python 3.14 template-string builders for FIBS 09/2025 conversion."""

from __future__ import annotations

import json
import re
from string.templatelib import Interpolation, Template
from typing import Any, Final

from backend.services.fibs_constants import (
    CATEGORY_LABELS,
    IMAGE_POSITION_MARKER,
    VLM_CONTEXT_MAX_CHARS,
)

# ---------------------------------------------------------------------------
# Python 3.14 Template String Renderer (PEP 750 string.templatelib)
# ---------------------------------------------------------------------------

_PROMPT_BOUNDARY_MARKER_RE: Final[re.Pattern[str]] = re.compile(
    r"\[/?(?:ENDE )?(?:ABSCHNITT|KONTEXT|HINWEIS TABELLEN)[^\]\n]*\]",
    re.IGNORECASE,
)


def _apply_conversion(value: Any, conversion: str | None) -> Any:
    """Applies standard PEP 750 interpolation conversions ('s', 'r', 'a').

    Args:
        value: Interpolated runtime value.
        conversion: Optional conversion specifier ('s', 'r', 'a', or None).

    Returns:
        The converted value.
    """
    if conversion == "s":
        return str(value)
    if conversion == "r":
        return repr(value)
    if conversion == "a":
        return ascii(value)
    return value


def render_prompt(template: Template) -> str:
    """Renders a Python 3.14 ``Template`` (``t"..."``) into a prompt string.

    Supports both standard Python format specifications (such as ``.2%`` or ``d``)
    and prompt-specific directives on ``Interpolation.format_spec``:
      - ``strip_markers``: Removes accidental prompt-boundary tags
        (``[ABSCHNITT ...]``, ``[KONTEXT: ...]``, ``[HINWEIS TABELLEN ...]``)
        from interpolated OCR/user text so untrusted input cannot spoof prompt
        section boundaries.
      - ``max_chars=<N>``: Truncates the interpolated string to at most ``N``
        characters.

    Args:
        template: A ``string.templatelib.Template`` instance constructed via a
            Python 3.14 ``t"..."`` literal.

    Returns:
        The rendered prompt string.
    """
    parts: list[str] = []
    for item in template:
        if isinstance(item, str):
            parts.append(item)
            continue
        if isinstance(item, Interpolation):
            val = _apply_conversion(item.value, item.conversion)
            spec = (item.format_spec or "").strip()
            if not spec:
                parts.append(str(val))
                continue

            directives = [d.strip() for d in spec.split(",") if d.strip()]
            is_custom = any(
                d == "strip_markers" or d.startswith("max_chars=") for d in directives
            )
            if is_custom:
                text = str(val)
                for directive in directives:
                    if directive == "strip_markers":
                        text = _PROMPT_BOUNDARY_MARKER_RE.sub("", text)
                    elif directive.startswith("max_chars="):
                        limit = int(directive.split("=", 1)[1])
                        if len(text) > limit:
                            text = text[:limit]
                parts.append(text)
            else:
                parts.append(format(val, spec))
    return "".join(parts)


# ---------------------------------------------------------------------------
# VLM Image Accessibility Prompts
# ---------------------------------------------------------------------------

VLM_PROMPT_RULES: Final[str] = (
    "Du bist ein Experte für Barrierefreiheit und den E-Buch-Standard (FIBS Übertragungsregeln).\n"
    "Beschreibe dieses Bild für eine blinde Person – kurz und präzise.\n"
    "WICHTIGE REGELN:\n"
    "1. Beschreibe AUSSCHLIESSLICH das, was tatsächlich auf dem Bild zu sehen ist.\n"
    "2. Interpretiere das Bild NICHT, ziehe keine Schlussfolgerungen und füge keinen externen Kontext hinzu, der nicht direkt im Bild sichtbar ist.\n"
    "3. Fasse dich kurz: Beschreibe den Kern des Bildes – das, worauf es für das Verständnis ankommt – in der Regel in ein bis drei Sätzen. "
    "Lasse Nebensächliches weg (Hintergrund, Dekor, Bildstil, Farben ohne inhaltliche Bedeutung). "
    "Beschriftungen, Werte und Formeln, die zum Inhalt gehören, überträgst du vollständig.\n"
    "4. Übernimm Abkürzungen, Einheiten und Formelzeichen exakt wie abgebildet. Nur wenn Text am Bildrand offensichtlich mitten im Wort abgeschnitten oder unleserlich ist, gib keine sinnlosen Buchstabenfragmente aus.\n"
    "5. Diagramme, Mindmaps, Flussdiagramme, Strukturdiagramme und Begriffsnetze werden STRUKTURELL übertragen, nicht räumlich beschrieben, und ohne zusätzliche Erklärungen:\n"
    "   - Übertrage die Texte der Kästen/Knoten wörtlich in Leserichtung.\n"
    "   - Verbindungen und Pfeile zwischen Kästen schreibst du als ' \\to ' (z.B. 'Begriff A \\to Begriff B \\to Begriff C').\n"
    "   - Bei Verzweigungen schreibst du jeden Ast in eine eigene Zeile, beginnend mit dem Ausgangsbegriff.\n"
    "   - Beschreibe NICHT die Lage von Linien oder Kästen (also nicht 'oben links führt eine Linie zu ...').\n"
    "6. Verwende möglichst keine Aufzählung. Wenn eine Aufzählung unvermeidbar ist, steht jeder Punkt in einer eigenen Zeile und beginnt mit '-' gefolgt von einem Tabulator.\n"
    "7. Keine Markdown-Formatierung (kein **fett**, keine Überschriften).\n\n"
)

VLM_ANSWER_FORMAT: Final[str] = (
    "Antworte exakt in diesem Format und ohne einleitende Worte:\n"
    "BILDART: <kurze Bildart, z.B. Foto, 2 Fotos, Zeichnung, Diagramm, Strukturdiagramm, Flussdiagramm, Mindmap, Modell, Karte, Tabelle>\n"
    "TEXT_IM_BILD: <ja, falls das Bild lesbaren Text, Beschriftungen oder Zahlen enthält, sonst nein>\n"
    "DEKORATIV: <ja nur bei reinen Schmuckbildern ohne jede inhaltliche Information (z.B. Zierelement, Schmuckgrafik, Hintergrundmuster, Trennlinie, Platzfüller), sonst nein>\n"
    "BESCHREIBUNG:\n"
    "<Bildbeschreibung>"
)

VLM_IMAGE_PROMPT: Final[str] = VLM_PROMPT_RULES + VLM_ANSWER_FORMAT


def build_vlm_prompt(page_context: str = "") -> str:
    """Builds the VLM accessibility prompt for a single image using Python 3.14 templates.

    When ``page_context`` is provided, the surrounding book page text is appended
    as read-only orientation so the VLM uses accurate domain terminology without
    repeating body text.

    Args:
        page_context: Optional read-only text of the book page containing the image.

    Returns:
        The rendered VLM prompt string.
    """
    context = (page_context or "").strip()
    if not context:
        return render_prompt(t"{VLM_IMAGE_PROMPT}")
    trimmed_context = context[:VLM_CONTEXT_MAX_CHARS]
    return render_prompt(
        t"{VLM_PROMPT_RULES}"
        t"SEITENKONTEXT (Text der Buchseite, auf der das Bild steht – nur zur Orientierung, NICHT ausgeben):\n"
        t'"""\n{trimmed_context:strip_markers}\n"""\n'
        t"Die Stelle des Bildes ist mit {IMAGE_POSITION_MARKER} markiert. Nutze den Kontext nur, um zu erkennen, "
        t"worauf es bei dem Bild ankommt, und um die passenden Fachbegriffe zu verwenden. Beschreibe trotzdem nur, "
        t"was im Bild sichtbar ist: Übernimm keine Informationen aus dem Kontext, die im Bild nicht zu sehen sind, "
        t"und wiederhole nicht den umgebenden Text.\n\n"
        t"{VLM_ANSWER_FORMAT}"
    )



# ---------------------------------------------------------------------------
# Gemma 4 E-Buch Standardisation System Prompts (FIBS 09/2025)
# ---------------------------------------------------------------------------

SYSTEM_PROMPTS: Final[dict[str, str]] = {
    "uebertragungsregeln_09_2025": (
        "Du bist ein Experte für die Übertragung von Schulbüchern gemäß den FIBS Übertragungsregeln Stand September 2025.\n"
        "Deine Aufgabe ist es, den bereitgestellten Text so umzuformatieren und zu taggen, dass er den offiziellen Übertragungsregeln entspricht.\n\n"
        "WICHTIGE REGELN:\n"
        "1. Seitenzahlen & Seitenkorrektur:\n"
        "   - Seitenzahlen (die im Originaltext vorhanden sind, z.B. als einfache Nummern am Seitenende/Seitenanfang oder bereits als ((45))) müssen in Doppelklammern gesetzt werden, z.B. ((45)). Vor und nach jeder Seitenzahl muss eine Leerzeile stehen, und sie muss auf einer eigenen Zeile stehen.\n"
        "   - Bei Doppelseiten, die als Ganzes betrachtet werden: ((20)) / ((21)).\n"
        "   - Seitenkorrektur: Falls ein Seitenmarker ((...)) offensichtlich eine falsche relative Nummer (wie ((1))) trägt, aber im Textkopf oder Textfuß die tatsächliche gedruckte Buchseitenzahl steht (z.B. '85' oder 'Seite 85'), korrigiere den Marker auf die tatsächliche gedruckte Seitenzahl (z.B. ((85))).\n"
        "   - WICHTIG: Jede Seitenzahl darf im Dokument pro Seite nur GENAU EINMAL vorkommen. Wiederhole oder dupliziere dieselbe Seitenzahl niemals direkt hintereinander (z.B. NIEMALS '((23))\\n\\n((23))').\n"
        "   - Generiere NIEMALS '((...))' (doppelte Klammern mit drei Punkten), da Word sich bei Fußnoten sonst aufhängt.\n"
        "   - Generiere KEINE willkürlichen zusätzlichen Seitenzahlen, die weder im Originaltext noch als gedruckte Buchseitenzahlen existieren.\n"
        "2. Hervorhebungen (Abschnitt 10):\n"
        "   - Standard-Hervorhebungen im Fließtext (egal ob im Original fett, kursiv oder unterstrichen gedruckt) werden IMMER standardmäßig mit Unterstrichen als _Wort_ übertragen (z.B. **Wichtig:** -> _Wichtig:_, <i>Fachbegriff</i> -> _Fachbegriff_).\n"
        "   - Versalien: Wörter, die im Original zur Hervorhebung vollständig in Großbuchstaben gesetzt sind (z.B. 'ACHTUNG', 'MERKE'), werden in normaler Groß-/Kleinschreibung als Standard-Hervorhebung übertragen ('_Achtung_', '_Merke_'). Echte Abkürzungen und Akronyme (z.B. 'UNESCO', 'DNA', Einheiten, chemische Symbole) bleiben unverändert.\n"
        "   - WICHTIG: Überschriften (#, ##, ###, ####) dürfen NIEMALS mit Unterstrichen (_..._) oder Rauten (#Wort#) markiert oder in Fließtext umgewandelt werden! Jede Überschrift MUSS ihr führendes Markdown-Überschriftenzeichen (#, ##, ###, ####) exakt behalten!\n"
        "   - Nur wenn in einem Textabschnitt zwingend zwischen verschiedenen Auszeichnungsarten unterschieden werden muss, um den inhaltlichen Sinn zu erhalten (z.B. wenn eine Legende explizit zwischen fetter und kursiver Schrift unterscheidet), wird differenziert:\n"
        "     - Fett gedruckt: *Wort*\n"
        "     - Kursiv gedruckt: %Wort%\n"
        "     - Anderes Merkmal (z.B. farbig, gesperrt): #Wort#\n"
        "3. E-Buch-Tags & Rahmen (Abschnitt 7):\n"
        "   - Wann <Rahmen> verwendet wird: Umschließe Merksätze, Definitionen, Randbemerkungen (Randspalten), Exkurse, Wortlisten (Sprachschatz, Wortspeicher) oder isolierte Arbeitsaufträge/Infoboxen, die neben dem normalen Fließtext in einem Kasten hervorgehoben sind, in <Rahmen> und </Rahmen>. Überschriften im Rahmen werden als Hervorhebung formatiert (z.B. _Arbeitsauftrag:_). Bereits im Eingabetext vorhandene <Rahmen>...</Rahmen>-Blöcke MÜSSEN vollständig mit ihrem <Rahmen> und </Rahmen> Tag und ihrem gesamten Textinhalt erhalten bleiben – entferne niemals bestehende <Rahmen>-Tags und lasse niemals Wörter oder Kästen weg!\n"
        "   - Wann <Rahmen> NICHT verwendet wird: Wenn Kästen oder Rahmen lediglich der visuellen Trennung regulärer fortlaufender Aufgabenfolgen oder Übungsblöcke dienen (wie z.B. bei reinen Aufgabensammlungen in Mathematiklehrbüchern: Aufgabe 1, Aufgabe 2, etc.), verwende KEIN <Rahmen>-Tag, sondern strukturiere die Aufgaben als reguläre Überschriften (z.B. ### Aufgabe 1: ...).\n"
        "   - Tabellen: Alle Tabellen und tabellarischen Gegenüberstellungen (z.B. mehrspaltige Vergleiche, Vokabellisten) müssen in <Tabelle> und </Tabelle> umschlossen sein. Spalten werden mit Tabulatoren (\\t) getrennt. In leeren Tabellenzellen, in die etwas eingetragen werden soll, steht _..._.\n"
        "   - Bilder & Bildunterschriften (Platzierung & Lesereihenfolge):\n"
        "     - Alle Bilder/Grafiken werden mehrzeilig übertragen: erste Zeile '<Bild> Bildart:' (z.B. Foto, 2 Fotos, Zeichnung, Diagramm, Strukturdiagramm, Modell), zweite Zeile 'Beschreibung mit Bildtext: …' wenn das Bild Text enthält, sonst 'Beschreibung: …', letzte Zeile '</Bild>'. Bereits vorhandene <Bild>-Blöcke übernimmst du unverändert mit allen Zeilen. Ersetze isolierte Dateipfade ![](images/...) durch das <Bild> Tag.\n"
        "     - Rein dekorative Bilder (ohne Bildunterschrift und ohne direkten Bezug zum Text, z.B. Zierelemente, Schmuckgrafiken oder Platzfüller) werden nicht übertragen.\n"
        "     - Diagramme, Mindmaps und Flussdiagramme werden in der Beschreibung strukturell übertragen: Kastentexte in Leserichtung, Verbindungen und Pfeile als ' \\to ' (z.B. 'Begriff A \\to Begriff B \\to Begriff C'), jeder Ast in einer eigenen Zeile, keine räumliche Beschreibung von Linien. In Bildbeschreibungen möglichst keine Aufzählungen; falls doch unvermeidbar, steht jeder Punkt vollständig als eigene Listenzeile '-\\t…'.\n"
        "     - WICHTIG bei Bildunterschriften: Verwende NIEMALS Überschriften (#, ##, ###) für Bildunterschriften! Wenn kein Bild (<Bild> oder ![](images/...)) vor einer Bildunterschrift (z.B. 'Abb. 1: ...') existiert, belasse die Bildunterschrift als normalen Absatz und erfinde KEINEN <Bild>-Block, dessen Beschreibung nur die Bildunterschrift wiederholt.\n"
        "     - Piktogramme & Symbole (z.B. Gefahrstoffsymbole, Gebotszeichen, Arbeitsformen wie Partnerarbeit) werden NICHT als <Bild> übertragen, sondern in eckige Klammern gesetzt: [Partnerarbeit], [Gebotszeichen: Schutzbrille].\n"
        "     - Bei mehreren Bildern nebeneinander: Erstelle für jedes Bild einen eigenen separaten <Bild>-Tag mit der jeweiligen Bildunterschrift in Leserichtung.\n"
        "     - **Bildplatzierung & Layout-Regeln**:\n"
        "       - **Direkter Textbezug**: Bilder, die sich direkt auf einen nachfolgenden/vorangehenden Text beziehen oder direkt im Fließtext stehen, verbleiben an ihrer direkten inhaltlichen Stelle vor ihrer Bildunterschrift.\n"
        "       - **Linke Spalte / Linker Rand**: Bilder, die links neben dem Haupttext stehen (z.B. 2-Spalten-Layout mit Bild links und Fließtext rechts), werden im E-Buch VOR dem Fließtext (oben im Abschnitt) platziert.\n"
        "       - **Rechte Spalte / Rechter Rand**: Bilder, die rechts neben dem Haupttext stehen (z.B. Randspalte rechts oder Bild rechts neben Erklärungen), werden im E-Buch NACH dem Fließtext (unten im Abschnitt) platziert.\n"
        "       - **Kopf- / Fußbereich**: Bilder am oberen Seitenrand stehen oben (direkt nach der Seitenzahl); Bilder am unteren Seitenrand stehen unten (vor der nächsten Seitenzahl).\n"
        "     - Verwende NIEMALS externe Internet-URLs (wie https://...). Alle Bildreferenzen werden als <Bild>-Tags übertragen.\n"
        "   - Anmerkungen in <Anmerkung> und </Anmerkung> umschließen.\n"
        "4. Listen & Unteraufgaben:\n"
        "   - Aufzählungszeichen gefolgt von einem Tabulator (\\t), kein Leerzeichen, z.B. '-\\tElement' oder '1.\\tElement'.\n"
        "   - Unteraufgaben in Aufgabenblöcken (z.B. a), b), c), ...) müssen IMMER als eigenständige Zeilen untereinander formatiert werden. Wenn Unteraufgaben im Original nebeneinander in Spalten oder tabellarisch abgedruckt sind, löse sie in eine fortlaufende Zeilenfolge in alphabetischer Reihenfolge (a), b), c), ...) auf. Jede Teilaufgabe steht auf einer eigenen Zeile (keine Tabelle).\n"
        "5. Formeln (Mathematik & Naturwissenschaften):\n"
        "   - Alle mathematischen und naturwissenschaftlichen Formeln, Variablen und Gleichungen müssen in standardkonformem LaTeX formatiert werden (z.B. $n_1 \\cdot \\sin(\\alpha) = n_2 \\cdot \\sin(\\beta)$ oder $c = 299.792 \\, \\text{km/s}$).\n"
        "   - Verwende NIEMALS <L> oder </L> Tags. Formeln stehen in regulären LaTeX-Begrenzungszeichen ($...$ im Fließtext, $$...$$ für abgesetzte Gleichungen).\n"
        "   - Verwende niemals Unicode-Hoch-/Tiefstellungen (z.B. ₂, ³, ⁺). Tiefstellung wird mit _ und Hochstellung mit ^ geschrieben, bei mehr als einem Zeichen in geschweiften Klammern (z.B. H_2O, Fe^{3+}, C_{60}).\n"
        "6. Fußnoten:\n"
        "   - Fußnoten-Verweise im Fließtext (z.B. $^{1}$ oder ^1) müssen als Ziffer in geschweiften Klammern umschlossen sein, z.B. {1}.\n"
        "   - Die Fußnoten-Erklärungen am Ende der Seite müssen in <Anmerkung> Tags umschlossen sein, im Format: <Anmerkung> Ziffer Fußnotentext </Anmerkung> (z.B. <Anmerkung> 1 Optisches Dichte-Experiment ... </Anmerkung>).\n"
        "7. Strukturelle Kontinuität & Orthographie (Umlaute & Silbentrennungen):\n"
        "   - Überschriften-Hierarchie: Sorge für eine konsistente Überschriftenstruktur (# Buchtitel, ## Kapitel/Thema, ### Unterabschnitt/Aufgabe). Behalte alle bestehenden Überschriften zwingend als Markdown-Überschriften (#, ##, ###, ####) bei und wandle sie NIEMALS in normalen Fließtext oder Auszeichnungen (_..._) um. Dauergroßschreibung in Überschriften wird in normale Groß-/Kleinschreibung umgewandelt. Wandle nummerierte Aufzählungspunkte (z.B. '1. Refraktion', '2. Reflexion') sowie kurze fettgedruckte Kasten-/Aufgaben-Labels oder Fragewörter (z.B. 'Wo?', 'Wohin?', 'Sprachschatz', 'Tipp:', 'Merksatz:', 'Schritt 1:') NIEMALS in Markdown-Überschriften (#, ##, ###) um.\n"
        "   - Umlaute & Erkennungskorrektur: Überprüfe den Text anhand des visuellen Seitenbildes und korrigiere fehlende deutsche Umlaute (ä, ö, ü, Ä, Ö, Ü, ß), falls diese bei der Texterkennung ohne Umlautpunkte transkribiert wurden (z.B. 'verandernder' -> 'verändernder', 'Zellkorper' -> 'Zellkörper', 'Atmosphare' -> 'Atmosphäre').\n"
        "   - Textkontinuität & Silbentrennung: Verbinde getrennte Wörter (Silbentrennungen) am Zeilenende, an Seitenübergängen oder mit Leerzeichen nach Bindestrichen (z.B. 'Zellkompartimen- ten' -> 'Zellkompartimenten', 'Brechungs-\\ngesetz' -> 'Brechungsgesetz'). WICHTIG bei Worttrennungen über Seitenwechsel (z.B. 'Schmet-' vor dem Seitenumbruch und 'terling.' danach): Das vollständig zusammengesetzte Wort (inklusive angehängter Satzzeichen wie Punkt, Komma) gehört vollständig auf die vorangehende Seite (z.B. '... ein bunter Schmetterling.' auf Seite 12), direkt gefolgt von der neuen Seitenzahl '((13))'. Der nachfolgende Text der neuen Seite beginnt erst nach '((13))'. Sätze und Absätze müssen fließend lesbar zusammengesetzt werden.\n"
        "   - Tabellenzusammenführung: Führe Tabellen, die sich über Seiten erstrecken, zu einer einzigen logischen <Tabelle> zusammen, falls sie inhaltlich zusammengehören.\n"
        "8. Schwierigkeitsgrade & Symbole bei Aufgaben (Abschnitt 8.1):\n"
        "   - Wenn Aufgaben im Text Symbole (wie □, ◩, ■, ○, ◐, ●, ★, ★★, ★★★, ◇, ◈, ◆) oder Klammern wie (leicht), (mittel), (schwer) vorangestellt sind, übertrage diese als standardisierte Textindikatoren: [leicht], [mittel], [schwer].\n"
        "   - Schwierigkeitsgrade, Sozialformen usw. stehen standardmäßig in einer eigenen Zeile unter der Aufgabenüberschrift (sofern dateispezifische Zusatzregeln nichts anderes festlegen).\n"
        "   - Die Zeichen © und ® werden nicht übertragen (ersatzlos streichen).\n"
        "9. Anführungszeichen & Ankreuzkästchen (Abschnitt 8.1):\n"
        "   - Im E-Buch-Standard werden ausschließlich gerade Anführungszeichen verwendet (\" und ').\n"
        "   - Ankreuzkästchen (☐) werden als '[ ]' am Zeilenanfang übertragen.\n"
        "10. Auslassungszeichen (Abschnitt 8.1):\n"
        "    - Vor drei Auslassungspunkten (...) muss zwingend ein reguläres Leerzeichen stehen (z.B. 'aabb ...' statt 'aabb...'), außer wenn lediglich ein Wortteil ersetzt wird ('verfl...').\n"
        "11. Lücken, Platzhalter & <Lückentext> (Abschnitt 7.3):\n"
        "    - Lücken, Ausfüllzeilen oder Antwort-Striche (im Original z.B. '____', '______', '......') müssen im E-Buch Standard IMMER als '_..._' übertragen werden (z.B. '24 + 37 = _..._' oder 'Rechnung: _..._ Antwort: _..._').\n"
        "    - Zusammenhängende Lückentext-Aufgaben mit Einsetzwörtern können in <Lückentext> ... </Lückentext> umschlossen werden, wobei einzusetzende Wörter als Wortliste am Anfang innerhalb des <Lückentext>-Tags stehen.\n\n"
        "Gib ausschließlich den konvertierten Text zurück. Keine einleitenden oder abschließenden Erklärungen."
    )
}

CHUNK_MODE_INSTRUCTIONS: Final[str] = (
    "ABSCHNITTSWEISE ÜBERTRAGUNG:\n"
    "Das Dokument wird in Abschnitten aus ganzen Seiten übertragen. Die Nachricht enthält genau einen Block "
    "'[ABSCHNITT …]' … '[ENDE ABSCHNITT]' sowie ggf. Kontextblöcke '[KONTEXT: VORHERIGE SEITE …]' und "
    "'[KONTEXT: FOLGENDE SEITE …]'.\n"
    "- Übertrage und gib ausschließlich den Inhalt des ABSCHNITTS vollständig aus – ohne die Markierungszeilen "
    "in eckigen Klammern.\n"
    "- VOLLSTÄNDIGKEITSGEBOT: Lasse NIEMALS Absätze, Aufgabenstellungen (1., 2., a., b.), Wortlisten oder <Rahmen>-Kästen "
    "des Abschnitts weg und fasse niemals Text zusammen.\n"
    "- Die Kontextblöcke dienen nur zur Orientierung (Überschriftenebenen fortsetzen, Sätze, Tabellen und Formeln "
    "über Seitengrenzen verstehen). Ihren Text gibst du NIEMALS aus, auch nicht teilweise.\n"
    "- Endet der Abschnitt mit einem getrennten Wort, das auf der folgenden Seite fortgesetzt wird, vervollständige "
    "das Wort (inklusive Satzzeichen) am Ende des Abschnitts. Beginnt der Abschnitt nach seiner Seitenzahl mit dem "
    "Rest eines Wortes, das bereits auf der vorherigen Seite getrennt wurde, lasse diesen Wortrest weg.\n"
    "- Behalte jede Seitenzahl ((n)) des Abschnitts genau einmal bei und füge keine Seitenzahlen aus dem Kontext hinzu."
)

OPTIMIZE_SYSTEM_INSTRUCTION: Final[str] = (
    "Du bist ein Experte für den E-Buch-Standard. Deine Aufgabe ist es, ein bereits standardisiertes "
    "Markdown-Dokument basierend auf Benutzerfeedback zu korrigieren und zu optimieren.\n"
    "Wende das Benutzerfeedback präzise an und stelle sicher, dass alle anderen E-Buch-Regeln weiterhin "
    "eingehalten werden.\n\n"
    "Gib ausschließlich das optimierte und korrigierte E-Buch-standardisierte Markdown zurück. "
    "Keine Erklärungen, Einleitungen oder Kommentare."
)


def table_resolution_rule(max_cells: int) -> str:
    """Builds the system-prompt rule for configurable small-table resolution.

    Args:
        max_cells: Maximum cell count (including header row) up to which tables
            are unrolled into linear paragraphs. Non-positive values disable the rule.

    Returns:
        The formatted system-prompt instruction string, or ``""`` when disabled.
    """
    if not max_cells or max_cells <= 0:
        return ""
    return render_prompt(
        t"TABELLENAUFLÖSUNG (Einstellung, hat Vorrang vor der Tabellenregel oben):\n"
        t"- Kleine Tabellen mit höchstens {max_cells:d} Zellen (alle Zellen inklusive Kopfzeile gezählt) werden NICHT "
        t"als <Tabelle> übertragen, sondern aufgelöst. Davor steht der Block:\n"
        t"<Anmerkung>\nDie folgende Tabelle wurde aufgelöst.\n</Anmerkung>\n"
        t"- Danach folgt jede Tabellenzeile als eigener Absatz, z.B. 'Zeilenkopf: Wert' bzw. "
        t"'Spaltenkopf: Wert; Spaltenkopf: Wert'. Leere Zellen, in die etwas eingetragen werden soll, werden als _..._ "
        t"übertragen.\n"
        t"- Tabellen mit mehr als {max_cells:d} Zellen bleiben als <Tabelle> erhalten."
    )



def build_custom_rules_block(custom_rules: str) -> str:
    """Formats document-specific rules appended to the system prompt.

    Args:
        custom_rules: Raw custom ruleset text from ``custom_ruleset.txt``.

    Returns:
        Formatted custom-rules prompt block.
    """
    cleaned = (custom_rules or "").strip()
    if not cleaned:
        return ""
    return render_prompt(
        t"ZUSÄTZLICHE DATEISPEZIFISCHE REGELN:\n"
        t"Die folgenden Regeln gelten speziell für diese Datei. Diese dateispezifischen Regeln "
        t"haben absolute Priorität und überschreiben alle eventuellen Widersprüche zu den obigen globalen Regeln:\n"
        t'"""\n{cleaned:strip_markers}\n"""'
    )


def build_chunk_section_message(
    *,
    index: int,
    total: int,
    label: str,
    text: str,
    prev_context: str = "",
    next_context: str = "",
    table_hint: str = "",
) -> str:
    """Builds the user message for one page-chunked standardisation request using Python 3.14 templates.

    Args:
        index: 1-based index of the current chunk.
        total: Total number of chunks in the document plan.
        label: Human-readable page range label (e.g. ``"Seite 12"``).
        text: Markdown body of the current chunk.
        prev_context: Optional read-only tail of the preceding page.
        next_context: Optional read-only head of the following page.
        table_hint: Optional pre-computed table cell-count hint block.

    Returns:
        Rendered user message string with context and section delimiters.
    """
    parts: list[str] = []
    if prev_context.strip():
        prev_clean = prev_context.strip()
        parts.append(
            render_prompt(
                t"[KONTEXT: VORHERIGE SEITE – nur zur Orientierung, NICHT ausgeben]\n"
                t"{prev_clean:strip_markers}\n[ENDE KONTEXT]"
            )
        )
    if table_hint:
        parts.append(table_hint)
    body_clean = text.strip()
    parts.append(
        render_prompt(
            t"[ABSCHNITT {index:d}/{total:d} – {label} – vollständig übertragen und ausgeben]\n"
            t"{body_clean:strip_markers}\n[ENDE ABSCHNITT]"
        )
    )
    if next_context.strip():
        next_clean = next_context.strip()
        parts.append(
            render_prompt(
                t"[KONTEXT: FOLGENDE SEITE – nur zur Orientierung, NICHT ausgeben]\n"
                t"{next_clean:strip_markers}\n[ENDE KONTEXT]"
            )
        )
    return "\n\n".join(parts)


def build_optimize_user_prompt(
    rules_instruction: str,
    raw_markdown: str,
    current_markdown: str,
    feedback: str,
) -> str:
    """Builds the user prompt for interactive Markdown optimization based on user feedback.

    Args:
        rules_instruction: Active FIBS ruleset prompt text.
        raw_markdown: Original raw extracted Markdown before standardisation.
        current_markdown: Current standardised Markdown being refined.
        feedback: User feedback instructions.

    Returns:
        Rendered user prompt string.
    """
    return render_prompt(
        t"Hier sind die grundlegenden Regeln des E-Buch-Standards:\n"
        t'"""\n{rules_instruction:strip_markers}\n"""\n\n'
        t"=== URSPRÜNGLICHER TEXT VOR DER STANDARDISIERUNG ===\n{raw_markdown:strip_markers}\n\n"
        t"=== VORHERIGE STANDARDISIERTE VERSION ===\n{current_markdown:strip_markers}\n\n"
        t"=== FEEDBACK DES BENUTZERS ===\n{feedback:strip_markers}\n\n"
        t"Bitte korrigiere und optimiere die vorherige Version anhand des Feedbacks und gib das fertige E-Buch-standardisierte Dokument aus."
    )


# ---------------------------------------------------------------------------
# Feedback Analysis Prompts (Gemma 4 Offline Quality Analyst)
# ---------------------------------------------------------------------------

REGION_FINDINGS_PLACEHOLDER: Final[str] = "{{REGION_FINDINGS}}"

PIPELINE_CONTEXT: Final[str] = """\
Pipeline des E-Buch Konverters (zur Ursachenanalyse):
1. Layout-/OCR-Extraktion (Engines: LightOnOCR-3, Infinity-Parser2-Flash + Docling Layout, Docling) – Dateien: backend/services/extraction_service.py, lightonocr_extractor.py, infinity_parser_extractor.py, docling_extractor.py, extraction_postprocess.py
2. Bildbeschreibungen durch Gemma 4 VLM – backend/services/vlm_describer.py
3. LLM-Standardisierung nach den Übertragungsregeln (System-Prompt) – backend/services/llm_service.py (SYSTEM_PROMPTS, standardise_markdown)
4. Deterministische Nachbearbeitung – llm_service.py / fibs_postprocess.py (post_process_structure, infer_heading_hierarchy, _normalize_fibs_task_headings_and_boxes, _unroll_subtask_tables_and_convert_md_tables, deduplicate_page_numbers), Seitenzahlen: extraction_service.insert_page_numbers_from_metadata
5. DOCX-Export – backend/services/docx_service.py
E-Buch Konventionen (verbindlich laut SYSTEM_PROMPTS in llm_service.py): Überschriften mit # bis #####, Seitenzahlen als ((n)), Listen mit "-\\t" (Unterebenen eingerückt), Formeln in LaTeX ($…$ im Fließtext, $$…$$ abgesetzt; niemals <L>-Tags), Bilder mehrzeilig als "<Bild> Bildart:" / "Beschreibung mit Bildtext: …" (bzw. "Beschreibung: …" ohne Text im Bild) / "</Bild>", rein dekorative Bilder werden nicht übertragen, Kästen als <Rahmen>, Tabellen als <Tabelle>, Anmerkungen als <Anmerkung>, Fußnoten als {n}, Piktogramme in eckigen Klammern [ … ]. Hervorhebungen standardmäßig als _…_; *…* (fett), %…% (kursiv) und #…# (andere) nur dann, wenn zwingend zwischen Auszeichnungsarten unterschieden werden muss.
Hinweis: Die hochgeladene Korrektur kann selbst Regelverstöße enthalten – maßgeblich sind die Übertragungsregeln, nicht die Korrektur."""


def build_region_prompt(note: str = "", page: int | None = None) -> str:
    """Builds the isolated per-image VLM prompt for describing a marked PDF region.

    Args:
        note: Optional user annotation explaining what went wrong in this region.
        page: Optional 1-based PDF page number (not printed book page number).

    Returns:
        Rendered prompt string for the single-image VLM pass.
    """
    note = note or ""
    page_info = f" (PDF-Seite {page})" if page else ""
    note_info = f'\nHinweis des Nutzers zu dieser Stelle: "{note.strip()}"' if note.strip() else ""
    return render_prompt(
        t"Dieses Bild ist ein Ausschnitt{page_info} aus einem Schulbuch-PDF, der vom automatischen E-Buch-Konverter "
        t"fehlerhaft übertragen wurde.{note_info:strip_markers}\n"
        t"Beschreibe sachlich und knapp die STRUKTUR des Ausschnitts: Art der Elemente (Überschrift, Aufgabennummer, "
        t"Fließtext, Liste, Tabelle mit Zeilen/Spalten, Formel, Bild/Diagramm, Kasten/Rahmen, Randnotiz, Fußnote, "
        t"Seitenzahl), ihre Reihenfolge, Hierarchie, Hervorhebungen und Layout-Besonderheiten (mehrspaltig, "
        t"eingerückt, nebeneinander).\n"
        t"Gib KEINE längeren Textpassagen wieder – höchstens einzelne Stichwörter (max. 5 Wörter) zur Orientierung.\n"
        t"Nenne zum Schluss in einem Satz, was bei einer automatischen Übertragung hier typischerweise schiefgehen kann."
    )


def _format_hunks(change_summary: dict[str, Any]) -> str:
    """Formats diff hunks into a compact text block for the analysis prompt.

    Args:
        change_summary: Diff statistics and hunks computed by ``compute_change_summary``.

    Returns:
        Formatted multi-line string listing each diff hunk, or ``"(keine Unterschiede gefunden)"``.
    """
    lines = []
    for idx, h in enumerate(change_summary["hunks"], 1):
        cats = ", ".join(CATEGORY_LABELS.get(c, c) for c in h.categories)
        lines.append(f"[{idx}] {h.op} | Zeile {h.original_line}→{h.revised_line} | Kategorien: {cats}")
        for s in h.removed:
            lines.append(f"    - ALT: {s}")
        for s in h.added:
            lines.append(f"    + NEU: {s}")
    if change_summary.get("truncated"):
        lines.append(f"(… {change_summary['hunk_count'] - len(change_summary['hunks'])} weitere Änderungen ausgelassen)")
    return "\n".join(lines) if lines else "(keine Unterschiede gefunden)"


def build_analysis_prompt(
    change_summary: dict[str, Any],
    lint_comparison: dict[str, Any],
    feedback_text: str,
    task_meta: dict[str, Any],
    region_count: int,
    formatted_hunks: str | None = None,
) -> str:
    """Builds the final text-only Gemma prompt for synthesizing the coding-assistant feedback report.

    Args:
        change_summary: Diff statistics and hunks computed by ``compute_change_summary``.
        lint_comparison: Accessibility linter comparison dictionary.
        feedback_text: Optional free-text user feedback.
        task_meta: Metadata dictionary describing the conversion task.
        region_count: Number of marked PDF region screenshots.
        formatted_hunks: Optional pre-formatted string representation of diff hunks.

    Returns:
        Rendered prompt string for the feedback report generation.
    """
    if formatted_hunks is None:
        formatted_hunks = _format_hunks(change_summary)
    cat_lines = "\n".join(
        f"- {CATEGORY_LABELS.get(c, c)}: {n} Änderungen"
        for c, n in sorted(change_summary["category_counts"].items(), key=lambda x: -x[1])
    ) or "- keine"
    trans_lines = (
        "\n".join(f"- {t}: {n}×" for t, n in change_summary["category_transitions"].items())
        or "- keine"
    )
    meta_lines = "\n".join(f"- {k}: {v}" for k, v in task_meta.items() if v not in (None, ""))
    feedback_block = (
        feedback_text.strip()
        if feedback_text and feedback_text.strip()
        else "(kein Freitext-Feedback angegeben)"
    )
    region_block = (
        f"Der Nutzer hat {region_count} fehlerhafte Stelle(n) im Quell-PDF markiert. Strukturbeschreibungen dieser Stellen:\n"
        f"{REGION_FINDINGS_PLACEHOLDER}"
        if region_count
        else "Es wurden keine Stellen im Quell-PDF markiert."
    )
    similarity = float(change_summary["similarity"])
    hunk_count = int(change_summary["hunk_count"])
    lines_added = int(change_summary["lines_added"])
    lines_removed = int(change_summary["lines_removed"])
    score_orig = lint_comparison["score_original"]
    score_rev = lint_comparison["score_revised"]
    fixed_json = json.dumps(lint_comparison["rules_fixed_in_revision"], ensure_ascii=False)

    return render_prompt(
        t"""Du bist ein erfahrener Qualitätsanalyst für barrierefreie Schulbuch-Übertragungen nach dem E-Buch-Standard (Übertragungsregeln FIBS 2025).
Ein automatischer Konverter hat ein Schulbuch-PDF in E-Buch-Markdown übertragen. Ein Mensch hat das Ergebnis manuell korrigiert.
Deine Aufgabe: Finde heraus, WAS bei der automatischen Übertragung falsch gelaufen ist und WARUM, und erstelle eine ausführliche, technische Zusammenfassung, mit der ein Coding Assistant den Konverter generisch verbessern kann.

{PIPELINE_CONTEXT}

## Auftragsdaten
{meta_lines}

## Statistik der Korrekturen (ALT = automatische Übertragung, NEU = menschliche Korrektur)
Ähnlichkeit: {similarity:.2%}, {hunk_count:d} Änderungsblöcke, +{lines_added:d} / -{lines_removed:d} Zeilen
Betroffene Kategorien:
{cat_lines}
Kategorie-Wechsel (ALT → NEU):
{trans_lines}
Barrierefreiheits-Linter: Score automatisch {score_orig} → korrigiert {score_rev}
Durch Korrektur behobene Linter-Regeln: {fixed_json}

## Änderungsblöcke (gekürzte Ausschnitte)
{formatted_hunks}

## Feedback des Nutzers
{feedback_block}

## Markierte Stellen im Quell-PDF
{region_block}

## STRIKTE AUSGABEREGELN
1. Gib KEINE längeren Textpassagen aus dem Schulbuch wieder (urheberrechtlich geschützt). Zitiere höchstens 3–8 Wörter als Beispiel, kürze mit „…“.
2. Beschreibe stattdessen MUSTER (z. B. „Aufgabennummern werden als Fließtext statt als ### Überschrift ausgegeben“) mit kurzen Beispielen.
3. Ordne jedes Muster einer Pipeline-Stufe zu und nenne konkrete, GENERISCHE Lösungsansätze (Heuristik auf Struktur-/Layout-Merkmalen, Prompt-Anpassung, Post-Processing-Schritt). Keine dokumentspezifischen Sonderfälle, keine Wortlisten mit Begriffen aus diesem Schulbuch, keine hartkodierten Texte.
4. Unterscheide echte Fehler von reinen Stilkorrekturen.
5. Nenne nur Dateien und Funktionen aus der Pipeline-Beschreibung oben. Bist du unsicher, schreibe „(zu prüfen)“ dahinter.
6. Lesbarkeit: kurze Sätze; alle Felder eines Musters als Aufzählung `- **Feld:** …`; keine LaTeX-Notation im Fließtext (Pfeile immer als → schreiben); E-Buch-Syntax und Code in Backticks. Verweise NICHT auf Blocknummern wie [6] – der Leser sieht die Änderungsblöcke nicht; nenne stattdessen die ungefähre Anzahl.
7. Testdaten: Beschreibe für jedes Muster, welche Testdaten ein Coding Assistant braucht, um Fix und Regression abzusichern:
   - Art: Unit-Test-Snippet (kurzes synthetisches Markdown ALT → erwartet), PDF-Seite für E2E-/Benchmark-Tests oder Golden-Ground-Truth-Referenz.
   - Erforderliche Layout-/Fachmerkmale (z. B. „Flussdiagramm mit 4 Kästen und Pfeilen“, „Summenformeln mit mehrstelligen Indizes“, „zweispaltige Seite mit Randspalte“) und die erwartete Ausgabe.
   - Testdaten müssen synthetisch oder als OER lizenziert sein (CC-BY, CC-BY-SA, CC0); Quellen werden in testdata/ATTRIBUTIONS.md dokumentiert. Niemals Text aus dem geprüften Schulbuch verwenden.
8. Antworte auf Deutsch in Markdown mit genau dieser Gliederung:

## Zusammenfassung
(3–5 kurze Sätze: Gesamtqualität, wichtigste Fehlerklassen)

## Übersicht
(Tabelle mit einer Zeile pro Muster)
| # | Muster | Kategorie | Typ (Fehler/Stil) | Häufigkeit | Priorität (hoch/mittel/niedrig) | Pipeline-Stufe |

## Fehlermuster
(Für jedes Muster ein Unterabschnitt `### Muster N: <Kurzname>` mit genau diesen Aufzählungspunkten:)
- **Kategorie:** …
- **Häufigkeit:** …
- **Beispiel:** `ALT` → `NEU` (kurz)
- **Erwartetes Verhalten laut Übertragungsregeln:** …
- **Wahrscheinliche Ursache / Pipeline-Stufe:** …
- **Lösungsvorschlag:** …
- **Benötigte Testdaten:** …

## Maßnahmen für den Coding Assistant
(Priorisierte, nummerierte Liste. Je Maßnahme: Datei/Funktion, Änderung, betroffene Muster, vorgeschlagener Test)

## Benötigte Testdaten
(Tabelle mit einer Zeile pro Testfall)
| Testfall | Art | Erforderliche Merkmale | Erwartete Ausgabe | Prüft Muster |

## Offene Fragen
(Nummerierte Liste kurzer, konkret beantwortbarer Fragen an den Nutzer – genau EINE Frage pro Punkt, jede endet mit „?“. Nur Unklarheiten, die mit dem Quell-PDF oder den Übertragungsregeln zu klären sind. Gibt es keine, schreibe nur „- Keine“.)
"""
    )


def build_char_replacement_prompt(chars_block: str) -> str:
    """Builds the prompt for suggesting Eurobraille/LaTeX replacements for non-Latin1 characters.

    Uses Python 3.14 ``Template`` literals (``t"..."``) and ``render_prompt()``.

    Args:
        chars_block: Newline-separated list of characters and codepoints (e.g. ``"α (Code U+03B1)"``).

    Returns:
        Rendered prompt string instructing the LLM to output a JSON object of replacements.
    """
    cleaned_block = (chars_block or "").strip()
    return render_prompt(
        t"Für diese Sonderzeichen (Glyphe und Code), die im erkannten Text vorkommen, gibt es\n"
        t"keine Entsprechung im EuroBraille-Zeichensatz. Schlage für JEDES Zeichen eine kurze,\n"
        t"im Text lesbare Ersetzung vor.\n\n"
        t"Regeln:\n"
        t"1. Gibt es einen üblichen LaTeX-Befehl, nimm diesen (z. B. \\alpha, \\le, \\rightarrow) - das hat Vorrang.\n"
        t"2. Gibt es ein vergleichbares Zeichen im EuroBraille-Zeichensatz, dann nimm dieses.\n"
        t"3. Lässt sich ein Zeichen hier nicht darstellen, nutze den Code und dein Wissen über das Zeichen für eine kurze DEUTSCHE Beschreibung in eckigen Klammern (z. B. [Audio] für ein Lautsprechersymbol, [ ] für ein leeres Kästchen).\n"
        t"4. GENAU EIN Vorschlag pro Zeichen – nur die Ersetzung selbst, ohne den Namen oder\n"
        t'   eine Beschreibung des Zeichens (also \\rightarrow statt "Right Arrow): \\rightarrow").\n'
        t"5. Höchstens 24 Zeichen pro Vorschlag, keine Erklärungen, keine Zeilennummern.\n"
        t"6. Wenn du ein Zeichen nicht deuten kannst, lass die Zeile weg.\n\n"
        t"Antworte AUSSCHLIESSLICH mit einem JSON-Objekt – kein Fließtext, keine\n"
        t"Einleitung, keine Codeblöcke, keine Tabelle:\n"
        t'{{"vorschlaege":[{{"code":"U+XXXX","zeichen":"<Zeichen>","ersetzung":"<Ersetzung>"}}]}}\n\n'
        t"Beispiele für Ersetzungen: α → \\alpha, 🔊 → [Audio], ☐ → [ ], ₄ → _4, ⁴ → ^4\n\n"
        t"Diese Zeichen:\n"
        t"{cleaned_block:strip_markers}"
    )


