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
    "Du bist ein Experte für Barrierefreiheit und den E-Buch-Standard (FIBS Übertragungsregeln Stand 09/2025).\n"
    "Beschreibe dieses Bild für eine blinde Person – kurz und präzise.\n"
    "WICHTIGE REGELN:\n"
    "1. Beschreibe AUSSCHLIESSLICH das, was tatsächlich auf dem Bild zu sehen ist.\n"
    "2. Interpretiere das Bild NICHT, ziehe keine Schlussfolgerungen und füge keinen externen Kontext hinzu, der nicht direkt im Bild sichtbar ist.\n"
    "3. Fasse dich kurz: Beschreibe den Kern des Bildes – das, worauf es für das Verständnis ankommt – in der Regel in ein bis drei Sätzen. "
    "Lasse Nebensächliches weg (Hintergrund, Dekor, Bildstil, Farben ohne inhaltliche Bedeutung). "
    "Beschriftungen, Werte und Formeln, die zum Inhalt gehören, überträgst du vollständig.\n"
    "4. WICHTIG gegen Bildunterschriften-Wiederholung: Wiederhole NIEMALS Bildunterschriften ('1 ...', 'Abb. 1 ...', 'M1 ...', 'B1 ...') oder Abschnittsüberschriften ('Material A • ...'), die am oberen oder unteren Bildrand angeschnitten sind, innerhalb von BESCHREIBUNG! Nur wenn Text am Bildrand mitten im Wort abgeschnitten oder unleserlich ist, gib keine sinnlosen Buchstabenfragmente aus.\n"
    "5. Formeln, Griechisch, Grad & Prozent im Bild (FIBS-Minimiertes-LaTeX ohne $-Begrenzer):\n"
    "   - Verwende NIEMALS $...$ oder $$...$$ und setze Variablen oder Formeln NIEMALS in _..._ oder **...**! Schreibe Formeln direkt in minimiertem FIBS-LaTeX (z. B. H_2O, Ca^{2+}, \\f{a}{b} statt \\frac{a}{b}, \\s{x} statt \\sqrt{x}, * statt \\cdot, sin/cos/tan ohne Backslash, \\8 für unendlich, \\apx für ungefähr, <=/>=/<</>>, \\ol{x}, \\vec{a}).\n"
    "   - Schreibe griechische Buchstaben und Mikro-Einheiten IMMER in offizieller FIBS-Tilde-Notation: ~a (alpha), ~b (beta), ~g (gamma), ~d (delta), ~D (Delta), ~e (epsilon), ~j (eta), ~h (theta), ~H (Theta), ~l (lambda), ~m (mu/mikro, z. B. '0,001 ~mg', '2 ~mm', '~a-Kette'), ~f (phi), ~w (omega), ~W (Omega) – niemals '\\alpha', 'alpha-' oder Unicode 'α'/'µ'.\n"
    "   - Temperaturen mit Leerzeichen vor °C ('33 °C', niemals '^\\circ'), Winkel ohne Leerzeichen ('90°'), Prozent mit Leerzeichen ('50 %').\n"
    "6. Diagramme, Mindmaps, Flussdiagramme, Strukturdiagramme und Begriffsnetze werden STRUKTURELL übertragen, nicht räumlich beschrieben, und ohne zusätzliche Erklärungen:\n"
    "   - Übertrage die Texte der Kästen/Knoten wörtlich in Leserichtung.\n"
    "   - Unbeschriftete Verbindungen und Pfeile zwischen Kästen schreibst du als ' \\to ' (z. B. 'Begriff A \\to Begriff B \\to Begriff C'), Gleichgewichtspfeile als ' \\lra '.\n"
    "   - Beschriftete Pfeile (mit Text auf, über oder neben dem Pfeil) schreibst du als ' \\xra{Beschriftung} ' (z. B. 'A \\xra{ATP \\to ADP} B', 'Regler \\xra{Ausschüttung} Stellgröße').\n"
    "   - Bei Verzweigungen schreibst du jeden Ast in eine eigene Zeile, beginnend mit dem Ausgangsbegriff.\n"
    "   - Beschreibe NICHT die Lage von Linien oder Kästen (also nicht 'oben links führt eine Linie zu ...').\n"
    "   - Bei Koordinaten-/Kurven-/Liniendiagrammen (Diagramm) gib immer 'x-Achse: <Größe mit Einheit und Wertebereich>', 'y-Achse: <Größe mit Einheit und Wertebereich>' sowie den Kurvenverlauf mit den wichtigsten Werten (z. B. Start-, Extrem-/Scheitel- und Endwerte) an.\n"
    "7. Verwende möglichst keine Aufzählung. Wenn eine Aufzählung unvermeidbar ist, steht jeder Punkt in einer eigenen Zeile und beginnt mit '-' gefolgt von einem Tabulator.\n"
    "8. Keine Markdown-Formatierung (kein **fett**, niemals Markdown-Überschriften wie #, ##, ### innerhalb von <Bild>...</Bild>).\n\n"
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
        "   - Seitenzahlen (die im Originaltext vorhanden sind, z.B. als einfache Nummern am Seitenende/Seitenanfang oder bereits als ((45))) müssen in Doppelklammern gesetzt werden, z.B. ((45)). Römische Seitenzahlen im Buch (z.B. ((I)), ((II)) oder ((i)), ((ii))) werden ebenso exakt in Doppelklammern als ((I)) bzw. ((i)) beibehalten. Vor und nach jeder Seitenzahl muss eine Leerzeile stehen, und sie muss auf einer eigenen Zeile stehen.\n"
        "   - Bei Doppelseiten, die als Ganzes betrachtet werden: ((20)) / ((21)).\n"
        "   - Seitenkorrektur: Falls ein Seitenmarker ((...)) offensichtlich eine falsche relative Nummer (wie ((1))) trägt, aber im Textkopf oder Textfuß die tatsächliche gedruckte Buchseitenzahl steht (z.B. '85' oder 'Seite 85'), korrigiere den Marker auf die tatsächliche gedruckte Seitenzahl (z.B. ((85))).\n"
        "   - WICHTIG: Jede Seitenzahl darf im Dokument pro Seite nur GENAU EINMAL vorkommen. Wiederhole oder dupliziere dieselbe Seitenzahl niemals direkt hintereinander (z.B. NIEMALS '((23))\\n\\n((23))').\n"
        "   - Generiere NIEMALS '((...))' (doppelte Klammern mit drei Punkten), da Word sich bei Fußnoten sonst aufhängt.\n"
        "   - Generiere KEINE willkürlichen zusätzlichen Seitenzahlen, die weder im Originaltext noch als gedruckte Buchseitenzahlen existieren.\n"
        "2. Hervorhebungen (Abschnitt 10):\n"
        "   - ALLE sprachlichen Hervorhebungen im Fließtext (egal ob fett, halbfett, kursiv, unterstrichen, Versalien oder Kapitälchen) werden IMMER einheitlich mit Unterstrichen als _Wort_ übertragen (z. B. **Wichtig:** -> _Wichtig:_, <i>Fachbegriff</i> -> _Fachbegriff_).\n"
        "   - WICHTIG – KEINE HERVORHEBUNG BEI VARIABLEN & FORMELN: Mathematische und naturwissenschaftliche Variablen, Formelzeichen, Symbole, Terme, Gleichungen und Rechnungen dürfen NIEMALS fett bzw. mit Unterstrichen (_..._, **...**, *...*) markiert werden – weder inline im Fließtext (z. B. E_{kin} = 1/2J~w^2, ~Dm_i, m, \\vec{F} – NIEMALS _E_kin_, _m_ oder _Delta m_i_!) noch auf einer eigenen Zeile (hervorgehobene Formeln stehen ohne Unterstriche allein in einer Extra-Zeile). Selbst wenn Kursivdruck sonst als _Wort_ übertragen wird, gilt dies NIEMALS für kursiv gesetzte Formelzeichen!\n"
        "   - Versalien & Kapitälchen-Personennamen: Wörter in Großbuchstaben/Kapitälchen zur Hervorhebung ('ACHTUNG' -> '_Achtung_', 'MERKE' -> '_Merke_') sowie Nachnamen in Kapitälchen/Großbuchstaben ('Charles BEST' -> 'Charles _Best_', 'Christoph KOLUMBUS' -> 'Christoph _Kolumbus_') werden in normaler Groß-/Kleinschreibung als _Wort_ übertragen. Echte Akronyme und Abkürzungen ('UNESCO', 'DNA', 'ATP', 'IUPAC', Einheiten, chemische Symbole) bleiben unverändert.\n"
        "   - WICHTIG: Überschriften (# bis #####) sowie Spalten-/Zeilenköpfe in Tabellen dürfen NIEMALS mit Unterstrichen (_..._) oder Rauten (#Wort#) umschlossen oder in Fließtext umgewandelt werden! Jede Überschrift MUSS ihr führendes Markdown-Überschriftenzeichen exakt behalten!\n"
        "   - Verwende NIEMALS *Wort*, %Wort% oder #Wort#, AUSSER die Vorlage stellt im selben Abschnitt explizit mehrere Hervorhebungsarten inhaltlich gegenüber UND eine vorangestellte <Anmerkung> erklärt deren Bedeutung:\n"
        "     - Fett gedruckt: *Wort*\n"
        "     - Kursiv gedruckt: %Wort%\n"
        "     - Anderes Merkmal (z. B. unterstrichen, farbig): #Wort#\n"
        "3. E-Buch-Tags, Rahmen & Bildunterschriften (Abschnitt 5.3, 7, 8.4):\n"
        "   - Wann <Rahmen> verwendet wird: Umschließe Merksätze, Definitionen, Randbemerkungen (Randspalten), Exkurse, Wortlisten (Sprachschatz, Wortspeicher) oder isolierte Arbeitsaufträge/Infoboxen, die neben dem normalen Fließtext in einem Kasten hervorgehoben sind, in <Rahmen> und </Rahmen>. Überschriften im Rahmen werden als Hervorhebung formatiert (z. B. _Arbeitsauftrag:_). Bereits im Eingabetext vorhandene <Rahmen>...</Rahmen>-Blöcke MÜSSEN vollständig mit ihrem <Rahmen> und </Rahmen> Tag und ihrem gesamten Textinhalt erhalten bleiben – entferne niemals bestehende <Rahmen>-Tags und lasse niemals Wörter oder Kästen weg!\n"
        "   - Wann <Rahmen> NICHT verwendet wird: Wenn Kästen oder Rahmen lediglich der visuellen Trennung regulärer fortlaufender Aufgabenfolgen oder Übungsblöcke dienen (z. B. Aufgabe 1, Aufgabe 2), verwende KEIN <Rahmen>-Tag, sondern strukturiere die Aufgaben als reguläre Überschriften (z. B. ### Aufgabe 1: ...).\n"
        "   - Tabellen: Alle Tabellen und tabellarischen Gegenüberstellungen müssen in <Tabelle> und </Tabelle> umschlossen sein. Spalten werden mit Tabulatoren (\\t) getrennt. In leeren Tabellenzellen, in die etwas eingetragen werden soll, steht _..._.\n"
        "   - Bilder & Bildunterschriften (§5.3, §7.1.1.2, §8.4):\n"
        "     - Bereits erstellte VLM-Bildbeschreibungen stehen im Eingabetext als einzeilige Platzhalter '<Bild-Ref id=\"BILD_001\" typ=\"...\" hinweis=\"...\" />'. Nutze 'typ' und 'hinweis' ausschließlich zur Orientierung, um jedes Bild seiner passenden Bildüberschrift ('#### M<Nr> <Titel>' direkt ÜBER dem Bild) zuzuordnen und an der richtigen Stelle in Leserichtung zu platzieren.\n"
        "     - WICHTIG gegen erfundene Bildtitel: Erfinde NIEMALS einen Bildtitel ('#### M<Nr> ...' oder '#### Abb. ...') aus den Attributen 'typ=\"...\"' oder 'hinweis=\"...\"' von '<Bild-Ref>'! Verwende für die Bildüberschrift ausschließlich eine tatsächlich im Dokument gedruckte Bildunterschrift (oder schreibe nur '#### M<Nr>' allein ohne Zusatztext, falls im Original keine Bildunterschrift vorhanden ist).\n"
        "     - WICHTIG für '<Bild-Ref>': Gib in deiner Ausgabe für jedes vorhandene 'BILD_xxx' AUSSCHLIESSLICH '<Bild-Ref id=\"BILD_001\" />' in einer eigenen Zeile aus (kopiere 'typ' und 'hinweis' NICHT mit, lasse KEINE 'BILD_xxx'-ID des Abschnitts weg und schreibe für ein vorhandenes 'BILD_xxx' NIEMALS einen neuen '<Bild>...</Bild>'-Block!).\n"
        "     - Nur isolierte Roh-Dateipfade '![](images/...)', für die noch kein '<Bild-Ref>' existiert, wandelst du mehrzeilig um: erste Zeile '<Bild> Bildart:' (z. B. Foto, 2 Fotos, Zeichnung, Diagramm, Strukturdiagramm, Modell), zweite Zeile 'Beschreibung mit Bildtext: …' wenn das Bild Text enthält, sonst 'Beschreibung: …', letzte Zeile '</Bild>'.\n"
        "     - Offizielle Regel für Bildtitel / Bildunterschriften (Sek. I/II): Bildtitel und Bildunterschriften stehen ÜBER dem '<Bild-Ref id=\"BILD_...\" />' (bzw. '<Bild>'-Block) als Überschrift 4 ('#### M<Nr> <Titel>', '#### Abb. <Nr>: <Titel>' bzw. mit dem in der Buchkonferenz festgelegten Kennbuchstaben wie 'B'), OHNE die Bildunterschrift nach dem Bild oder innerhalb von '<Bild>' zu wiederholen! Nur wenn auf der Seite gar kein Bild ('<Bild-Ref>', '<Bild>' oder '![](...)') zu einer isolierten Bildunterschrift existiert, erfinde KEINEN künstlichen Bild-Block.\n"
        "     - Rein dekorative Bilder (ohne Bildunterschrift und ohne direkten Bezug zum Text, z. B. Zierelemente, Schmuckgrafiken oder Platzfüller) werden nicht übertragen.\n"
        "     - Diagramme, Mindmaps und Flussdiagramme werden in der Beschreibung strukturell übertragen: Kastentexte in Leserichtung, unbeschriftete Pfeile als ' \\to ' (z. B. 'Begriff A \\to Begriff B \\to Begriff C'), beschriftete Pfeile als ' \\xra{Beschriftung} ' (z. B. 'Regler \\xra{Ausschüttung} Stellgröße'), Gleichgewichtspfeile als ' \\lra ', jeder Ast in einer eigenen Zeile, keine räumliche Beschreibung von Linien. In Bildbeschreibungen möglichst keine Aufzählungen; falls doch unvermeidbar, steht jeder Punkt vollständig als eigene Listenzeile '-\\t…'.\n"
        "     - Piktogramme & Symbole (z. B. Gefahrstoffsymbole, Gebotszeichen, Arbeitsformen wie Partnerarbeit) werden NICHT als <Bild> übertragen, sondern in eckige Klammern gesetzt: [Partnerarbeit], [Gebotszeichen: Schutzbrille].\n"
        "     - Bei mehreren Bildern nebeneinander: Erstelle für jedes Bild einen eigenen separaten <Bild>-Tag mit der jeweiligen Bildunterschrift darüber in Leserichtung.\n"
        "     - **Bildplatzierung & Layout-Regeln**:\n"
        "       - **Direkter Textbezug**: Bilder mit direktem Textbezug stehen an ihrer inhaltlichen Stelle unmittelbar unter ihrer Bildüberschrift ('#### ...').\n"
        "       - **Linke Spalte / Linker Rand**: Bilder links neben dem Haupttext stehen im E-Buch VOR dem Fließtext (oben im Abschnitt).\n"
        "       - **Rechte Spalte / Rechter Rand**: Bilder rechts neben dem Haupttext stehen im E-Buch NACH dem Fließtext (unten im Abschnitt).\n"
        "       - **Kopf- / Fußbereich**: Bilder am oberen Seitenrand stehen oben (direkt nach der Seitenzahl); Bilder am unteren Seitenrand stehen unten (vor der nächsten Seitenzahl).\n"
        "     - Verwende NIEMALS externe Internet-URLs (wie https://...) für Bilder. Alle Bildreferenzen werden als <Bild>-Tags übertragen.\n"
        "   - Anmerkungen in <Anmerkung> und </Anmerkung> umschließen.\n"
        "4. Listen & Unteraufgaben:\n"
        "   - Aufzählungszeichen gefolgt von einem Tabulator (\\t), kein Leerzeichen, z. B. '-\\tElement' oder '1.\\tElement'.\n"
        "   - Unteraufgaben in Aufgabenblöcken (z. B. a), b), c), ...) müssen IMMER als eigenständige Zeilen untereinander formatiert werden. Nebeneinander oder tabellarisch abgedruckte Teilaufgaben werden in alphabetischer Reihenfolge (a), b), c), ...) zeilenweise aufgelöst (keine Tabelle).\n"
        "5. Formeln, Minimiertes FIBS-LaTeX, Bruchschreibweisen, Griechisch, Grad & Prozent (Abschnitt 7.7, 8.1, 8.2 & FIBS LaTeX-Handreichung):\n"
        "   - WICHTIG: Verwende NIEMALS $...$, $$...$$ oder <L>...</L> Begrenzungszeichen und NIEMALS \\text{...}, \\mathrm{...}, \\, oder {,}!\n"
        "   - Offizielles Minimiertes FIBS-LaTeX: Brüche als \\f{a}{b} (NIEMALS \\frac{a}{b}), Wurzeln als \\s{x} bzw. \\s[n]{x} (NIEMALS \\sqrt), Überstrich als \\ol{x}, Malzeichen IMMER als * (NIEMALS \\cdot oder ·, z. B. n_1 * sin(~a_1) = n_2 * sin(~a_2), 3 * 10^8), Winkelfunktionen sin, cos, tan, cot, arcsin, arccos, arctan OHNE Backslash (\\ln, \\lg, \\log, \\lim, \\sum, \\prod, \\int, \\oint, \\iint, \\iiint MIT Backslash), \\8 statt \\infty, \\apx statt \\approx, \\eqv statt \\equiv (\\n \\eqv), \\^= statt \\hat{=}, <=, >=, <<, >> statt \\le, \\ge, \\ll, \\gg, \\neq, \\pm, \\mp, \\l< und \\r> statt \\langle/\\rangle, Pfeile \\to, \\la, \\lra, \\mt, \\Ra, \\La, \\Lra, \\xra{oben} bzw. \\xra[unten]{oben}, Mengen/Logik \\es, \\N, \\Z, \\Q, \\R, \\C, \\P, \\sbs, \\sbse, \\sps, \\spsq, \\ex, \\|, Punkte ... bzw. \\cd, Vektoren immer geklammert ohne Leerzeichen (\\vec{a}, \\vec{~w}, \\vec{F_A}), immer zuerst Index vor Exponent (a_1^3).\n"
        "   - FIBS-Bruchschreibweisen: Einfache positive Zahlenbrüche (1/2, 1/1.000.000, 1/2 - 1/4) und eindeutige Einheiten (km/h, m/s) dürfen mit / geschrieben werden. Sobald Buchstaben/Variablen oder Rechnungen im Zähler/Nenner stehen (v = \\f{s}{t}, \\f{a + b}{c}), bei negativen Brüchen (-\\f{1}{2}, \\f{1}{-2}) oder vor Einzelvariablen (\\f{1}{2}x – NIEMALS '1/2 x' mit Leerzeichen!) ausführliche Schreibweise \\f{...}{...} verwenden (oder Produkte kompakt ohne Leerzeichen wie E_{kin} = 1/2J~w^2).\n"
        "   - Griechische Buchstaben & Mikro-Präfix IMMER in offizieller FIBS-Tilde-Notation: ~a (alpha), ~b (beta), ~g (gamma), ~G (Gamma), ~d (delta), ~D (Delta, z. B. ~Dm_i, ~Dt), ~e (epsilon), ~z (zeta), ~j (eta!), ~h (theta/vartheta!), ~H (Theta!), ~i (iota), ~k (kappa), ~l (lambda), ~L (Lambda), ~m (mu/mikro, z. B. '0,001 ~mg', '2 ~mm'), ~n (nu), ~x (xi), ~p (pi), ~r (rho), ~s (sigma), ~S (Sigma), ~t (tau), ~u (upsilon), ~f (phi/varphi), ~F (Phi), ~c (chi), ~y (psi), ~w (omega), ~W (Omega).\n"
        "   - Temperaturen mit Leerzeichen vor °C/°F ('33 °C', '-196 °C', niemals '^\\circ'), Winkel ohne Leerzeichen ('90°', '14,1°', niemals '^\\circ'), Prozentangaben mit Leerzeichen vor % ('50 %', Ausnahme '5%-Klausel', '100%ig').\n"
        "   - Verwende niemals Unicode-Hoch-/Tiefstellungen (z. B. ₂, ³, ⁺). Tiefstellung wird mit _ und Hochstellung mit ^ geschrieben, bei mehr als einem Zeichen in geschweiften Klammern (z. B. H_2O, Fe^{3+}, C_{60}, E_{kin}).\n"
        "6. Fußnoten, Worterklärungen & Randspalten (Abschnitt 8.6, 11):\n"
        "   - Kurze Worterklärungen (1–5 Wörter) oder Seiten-Querverweise stehen einheitlich direkt inline in eckigen Klammern [...].\n"
        "   - Längere verknüpfte Worterklärungen aus der Randspalte werden im Text mit ^1 markiert und am Abschnittsende unter '#### Worterklärungen' als '^1: Erklärungstext' aufgeführt; klassische Seitenfußnoten als {1} im Text mit '<Anmerkung> 1 Fußnotentext </Anmerkung>' am Seitenende.\n"
        "   - Sonstige Randspalten-Kästen ohne Fußnotenziffer stehen unter '#### Randspalte' in <Rahmen>...</Rahmen>.\n"
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
    "- VOLLSTÄNDIGKEITSGEBOT: Lasse NIEMALS Absätze, Aufgabenstellungen (1., 2., a., b.), Wortlisten, "
    "<Bild-Ref>-Platzhalter oder <Rahmen>-Kästen des Abschnitts weg und fasse niemals Text zusammen.\n"
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
        t'"""\n{cleaned:strip_markers}\n"""\n'
        t"STRIKTE DURCHSETZUNG DER BUCHKONFERENZ-REGELN:\n"
        t"- Halte jede in den dateispezifischen Regeln definierte Überschriften-Hierarchie (# bis #####) strikt ein "
        t"(wenn z.B. '##### Überschrift 5' für 'Aufgaben:' und jede Aufgabennummer festgelegt ist, gib '##### Aufgaben' "
        t"sowie jede Aufgabennummer '##### <Nr>' jeweils auf einer eigenen Zeile aus und setze den Aufgabentext als "
        t"separaten Absatz darunter).\n"
        t"- Wenn für Bildunterschriften/Material-Kürzel eine Überschriftenebene oder Platzierung vor dem Bild festgelegt "
        t"ist (z.B. '#### M1 ...' vor dem Bild), platziere die Überschrift/Bildunterschrift direkt ÜBER "
        t"'<Bild-Ref id=\"BILD_001\" />' (bzw. '<Bild>...</Bild>'), gib für vorhandene 'BILD_xxx'-Platzhalter "
        t"NUR '<Bild-Ref id=\"BILD_001\" />' in einer eigenen Zeile aus und wiederhole die Bildunterschrift NICHT nach dem Bild.\n"
        t"- Trenne vorangestellte fettgedruckte oder mit Punkt/Bullet abgetrennte Absatz-Stichwörter "
        t"('Stichwort • Text...' bzw. '**Stichwort** • Text...') gemäß der festgelegten Überschriftenebene "
        t"in eine eigene Überschrift und einen nachfolgenden Absatz auf (z.B. '#### Stichwort\\n\\nText...').\n"
        t"- Selbst wenn dateispezifische Regeln kursive Wörter als _Wort_ hervorheben, dürfen mathematische/physikalische "
        t"Variablen, Formelzeichen, Symbole und Gleichungen NIEMALS mit _..._ umschlossen werden (immer E_{{kin}} = 1/2J~w^2, "
        t"~Dm_i, \\f{{a}}{{b}}, \\s{{x}}, * statt \\cdot, sin/cos/tan ohne Backslash, ~j = eta, ~h = theta)."
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
E-Buch Konventionen (verbindlich laut SYSTEM_PROMPTS in prompts.py): Überschriften mit # bis #####, Seitenzahlen als ((n)), Listen mit "-\\t" (Unterebenen eingerückt), Formeln direkt in minimiertem FIBS-LaTeX OHNE $-Begrenzer, OHNE _..._-Hervorhebung um Variablen/Formeln und niemals <L>-Tags (\\f{a}{b} statt \\frac, \\s{x} statt \\sqrt, * statt \\cdot, sin/cos/tan ohne Backslash, \\8, \\apx, <=/>=/<</>>, \\ol{x}, \\vec{a}; Griechisch/Mikro als ~a, ~b, ~g, ~d, ~D, ~j=eta, ~h=theta, ~H=Theta, ~l, ~m, ~f, ~w, ~W; Pfeile \\to, \\la, \\lra, \\Ra, \\Lra, \\xra{Text}; Grad/Prozent als 33 °C, 90°, 50 %), Bildtitel über <Bild> als "#### M<Nr> <Titel>" bzw. "#### Abb. <Nr>: <Titel>", Bilder mehrzeilig als "<Bild> Bildart:" / "Beschreibung mit Bildtext: …" (bzw. "Beschreibung: …" ohne Text im Bild) / "</Bild>", rein dekorative Bilder werden nicht übertragen, Kästen als <Rahmen>, Tabellen als <Tabelle>, Anmerkungen als <Anmerkung>, Fußnoten als {n} bzw. Worterklärungen mit ^1 und "#### Worterklärungen", Piktogramme in eckigen Klammern [ … ]. Sprachliche Hervorhebungen einheitlich als _…_ (inkl. Kapitälchen-Namen wie _Best_), niemals jedoch um Variablen oder Formeln; *…*, %…% und #…# nur bei expliziter inhaltlicher Differenzierung mit vorangestellter <Anmerkung>.
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
        lines.append(
            f"[{idx}] {h.op} | Zeile {h.original_line}→{h.revised_line} "
            f"(-{h.removed_line_count}/+{h.added_line_count} Zeilen) | Kategorien: {cats}"
        )
        for s in h.removed:
            lines.append(f"    - ALT: {s}")
        if h.removed_line_count > len(h.removed):
            lines.append(f"    - ALT: (… +{h.removed_line_count - len(h.removed)} weitere ALT-Zeilen)")
        for s in h.added:
            lines.append(f"    + NEU: {s}")
        if h.added_line_count > len(h.added):
            lines.append(f"    + NEU: (… +{h.added_line_count - len(h.added)} weitere NEU-Zeilen)")
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
    custom_ruleset: str = "",
) -> str:
    """Builds the final text-only Gemma prompt for synthesizing the coding-assistant feedback report.

    Args:
        change_summary: Diff statistics and hunks computed by ``compute_change_summary``.
        lint_comparison: Accessibility linter comparison dictionary.
        feedback_text: Optional free-text user feedback.
        task_meta: Metadata dictionary describing the conversion task.
        region_count: Number of marked PDF region screenshots.
        formatted_hunks: Optional pre-formatted string representation of diff hunks.
        custom_ruleset: Optional document-specific custom ruleset (``custom_ruleset.txt``).

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
    anomalies = change_summary.get("structural_anomalies") or []
    anomalies_lines = (
        "\n".join(f"- {a}" for a in anomalies)
        if anomalies
        else "- (keine automatischen Struktur-Anomalien erkannt)"
    )
    meta_lines = "\n".join(f"- {k}: {v}" for k, v in task_meta.items() if v not in (None, ""))
    custom_rules_clean = (custom_ruleset or "").strip()
    custom_rules_section = (
        render_prompt(
            t"\n## Dateispezifische Zusatzregeln (Buchkonferenz / custom_ruleset.txt)\n"
            t"{custom_rules_clean:strip_markers,max_chars=4000}\n"
        )
        if custom_rules_clean
        else ""
    )
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
{custom_rules_section}
## Statistik der Korrekturen (ALT = automatische Übertragung, NEU = menschliche Korrektur)
Ähnlichkeit: {similarity:.2%}, {hunk_count:d} Änderungsblöcke, +{lines_added:d} / -{lines_removed:d} Zeilen
Betroffene Kategorien:
{cat_lines}
Kategorie-Wechsel (ALT → NEU):
{trans_lines}
Barrierefreiheits-Linter: Score automatisch {score_orig} → korrigiert {score_rev}
Durch Korrektur behobene Linter-Regeln: {fixed_json}

## Automatisch erkannte Struktur-Anomalien & Mengenvergleiche
{anomalies_lines}

## Änderungsblöcke (gekürzte Ausschnitte)
{formatted_hunks}

## Feedback des Nutzers
{feedback_block}

## Markierte Stellen im Quell-PDF
{region_block}

## STRIKTE AUSGABEREGELN
1. Gib KEINE längeren Textpassagen aus dem Schulbuch wieder (urheberrechtlich geschützt). Zitiere höchstens 3–8 Wörter als Beispiel, kürze mit „…“.
2. Beschreibe stattdessen MUSTER (z. B. „Aufgabennummern werden als Fließtext statt als ### Überschrift ausgegeben“) mit kurzen Beispielen. Jede kritische Anomalie unter „## Automatisch erkannte Struktur-Anomalien & Mengenvergleiche“ MUSS als Muster im Bericht abgedeckt werden.
3. Ordne jedes Muster einer Pipeline-Stufe zu und nenne konkrete, GENERISCHE Lösungsansätze (Heuristik auf Struktur-/Layout-Merkmalen, Prompt-Anpassung, Post-Processing-Schritt). Keine dokumentspezifischen Sonderfälle, keine Wortlisten mit Begriffen aus diesem Schulbuch, keine hartkodierten Texte.
4. Unterscheide echte Fehler von reinen Stilkorrekturen. WICHTIG: `ALT` ist IMMER die fehlerhafte automatische Übertragung des Konverters; `NEU` ist die menschliche Referenz-Korrektur (das Zielformat). Verwechsle NIEMALS die Richtung `ALT` → `NEU`! Im `<Bild>`-Block sind laut FIBS 09/2025 BEIDE Präfixe gültig: `Beschreibung mit Bildtext:` (wenn Text/Beschriftung im Bild vorkommt) und `Beschreibung:` (ohne Bildtext) – empfiehl NIEMALS, `Beschreibung mit Bildtext:` pauschal zu entfernen.
5. Nenne nur Dateien und Funktionen aus der Pipeline-Beschreibung oben. Bist du unsicher, schreibe „(zu prüfen)“ dahinter. Falls dateispezifische Zusatzregeln (`custom_ruleset.txt`) angegeben sind, prüfe, ob `ALT` diese verletzt hat, und stelle KEINE offenen Fragen zu Punkten, die bereits in den Zusatzregeln beantwortet sind.
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


# ---------------------------------------------------------------------------
# Golden Ground-Truth Verification & Repair Prompts (Stage-1 RAW + Stage-2 FIBS)
# ---------------------------------------------------------------------------

OCR_RAW_GOLDEN_RULES: Final[str] = (
    "OCR RAW GOLDEN RULES (`<id>.raw.golden.md`):\n"
    "1. Verbatim Completeness & Reading Order: Every word, number, label, table cell, and task on the PDF page must be transcribed verbatim in natural reading order.\n"
    "2. Two-Up Double-Page Spreads (Doppelseiten auf einer PDF-Seite): If a single PDF page contains two textbook pages side-by-side (left page and right page), the ENTIRE left textbook page must be transcribed top-to-bottom BEFORE the right textbook page begins. Never interleave columns, material boxes (M1..M8), or tasks across the central gutter. Strip standalone margin double-page numbers (`52 53`, `16 17`, `88 89`) and `.indd`/`.indb` print-production slugs.\n"
    "3. Physical Page Markers: Keep the exact physical page markers `((num))` matching `physical_pages` on standalone lines separated by blank lines.\n"
    "4. Structure & Formatting: Format chapter/section/material/task titles with Markdown headings (`#`, `##`, `###`), tables as Markdown pipe tables (`| ... |`), math/science formulas as `$...$` LaTeX, and retain all `![...](...)` image links intact.\n"
    "5. Zero Broken Hyphens (Trennstriche): Join all mid-word line-break hyphens (`Aufga-ben` -> `Aufgaben`) while keeping true compound hyphens (`Klima- und Vegetationszonen`, `Nord- oder Südpol`)."
)


def build_golden_verification_prompt(
    doc_id: str,
    pdf_path: str,
    preview_png_path: str,
    raw_path: str,
    fibs_path: str,
    physical_pages: list[int],
    ruleset_key: str = "uebertragungsregeln_09_2025",
) -> str:
    """Builds the canonical prompt for Gemini 4 (`agy --print=...`) Golden Ground-Truth verification and repair.

    Embeds both ``OCR_RAW_GOLDEN_RULES`` and ``SYSTEM_PROMPTS[ruleset_key]`` so ``ebuch-testdaten``
    never drifts when ``ebuch-konvertierung`` rules evolve.
    """
    fibs_rules = SYSTEM_PROMPTS.get(ruleset_key, SYSTEM_PROMPTS["uebertragungsregeln_09_2025"])
    return render_prompt(
        t"You are auditing and repairing the Golden Ground-Truth files for document `{doc_id}`.\n"
        t"- Source PDF page 1 visual render: `{preview_png_path}` (from `{pdf_path}`, physical_pages: `{physical_pages}`)\n"
        t"- Stage-1 OCR RAW Golden file: `{raw_path}`\n"
        t"- Stage-2 FIBS 09/2025 Golden file: `{fibs_path}`\n\n"
        t"INSTRUCTIONS:\n"
        t"1. Call `read_file` on `{preview_png_path}`, `{raw_path}` (StartLine=1, EndLine=170), and `{fibs_path}` (StartLine=1, EndLine=190) in a single turn. Do NOT invoke subagents, do NOT run bash commands, and do NOT read additional slices unless editing.\n"
        t"2. Visually verify from `{preview_png_path}` whether the page is a 2-up double-page spread (two textbook pages side-by-side). Verify that the left page is completely transcribed before the right page, that columns/boxes/tasks are not interleaved across the gutter, and that standalone margin page pairs (`52 53`, `16 17`, `88 89`) and `.indd`/`.indb` slugs are removed.\n"
        t"3. Verify and actively improve `{raw_path}` and `{fibs_path}` using `edit_file` if any structural, heading, `<Rahmen>`, or task formatting defect is visible, following:\n\n"
        t"{OCR_RAW_GOLDEN_RULES}\n\n"
        t"FIBS 09/2025 ÜBERTRAGUNGSREGELN (`<id>.uebertragungsregeln_09_2025.golden.md`):\n"
        t"{fibs_rules}\n\n"
        t"CRITICAL INVARIANTS WHEN EDITING:\n"
        t"- Preserve the exact physical page markers `{physical_pages}` as `((num))` in monotonic order.\n"
        t"- Preserve all `![...](...)` tags in `{raw_path}` and all `<Bild>...</Bild>` blocks in `{fibs_path}`.\n"
        t"- Never delete textbook body words (word recall against the PDF must remain >= 98.5%).\n"
        t"- Preserve footnote/forecast asterisks on years or coordinates (e.g. `2030* 2040* 2050*`).\n"
        t"- Perform at most 1-2 targeted `edit_file` calls if needed, then immediately output a concise 5-line summary of what you verified and repaired and stop."
    )



