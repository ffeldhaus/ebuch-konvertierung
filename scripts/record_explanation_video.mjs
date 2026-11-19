import { chromium } from 'playwright';
import { spawn, execSync } from 'child_process';
import fs from 'fs';
import path from 'path';
import { fileURLToPath, pathToFileURL } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_DIR = path.resolve(__dirname, '..');
const ASSETS_DIR =
  process.env.EBUCH_VIDEO_ASSETS_DIR || path.join(PROJECT_DIR, 'assets', 'video_capture');
const AUDIO_DIR = path.join(ASSETS_DIR, 'audio');
const FRAMES_DIR = path.join(ASSETS_DIR, 'frames');
const SCENES_DIR = path.join(ASSETS_DIR, 'scenes');
const ARTIFACT_DIR =
  process.env.EBUCH_VIDEO_ARTIFACT_DIR || path.join(ASSETS_DIR, 'artifacts');

function resolveFfmpegBinary() {
  if (process.env.FFMPEG_PATH && fs.existsSync(process.env.FFMPEG_PATH)) {
    return process.env.FFMPEG_PATH;
  }
  const venvFfmpeg = path.join(
    PROJECT_DIR,
    '.venv/lib/python3.14/site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1'
  );
  if (fs.existsSync(venvFfmpeg)) {
    return venvFfmpeg;
  }
  return 'ffmpeg';
}

const FFMPEG_BIN = resolveFfmpegBinary();
const ONLY_SCENES_SET = new Set(
  (process.env.EBUCH_ONLY_SCENE || '')
    .split(',')
    .map(s => s.trim())
    .filter(Boolean)
);

if (ONLY_SCENES_SET.size === 0) {
  fs.rmSync(FRAMES_DIR, { recursive: true, force: true });
  fs.rmSync(SCENES_DIR, { recursive: true, force: true });
}
fs.mkdirSync(FRAMES_DIR, { recursive: true });
fs.mkdirSync(SCENES_DIR, { recursive: true });
fs.mkdirSync(ARTIFACT_DIR, { recursive: true });

const manifest = JSON.parse(fs.readFileSync(path.join(AUDIO_DIR, 'manifest.json'), 'utf-8'));

// Load rendered page 501 PNG from physik_optik_sample.pdf
const page501PngPath = path.join(ASSETS_DIR, 'pdf_pages', 'physik_optik_p2.png');
const page501DataUrl = `data:image/png;base64,${fs.readFileSync(page501PngPath).toString('base64')}`;

// Real Raw & FIBS 09/2025 Markdown for pages 501–502 of physik_optik_sample.pdf
const rawOptikMd = `((501))

# Kapitel 11. Optik

## 11.6. Licht in unterschiedlichen Medien

Dabei wird der Lichtstrahl immer so gebrochen, dass der Brechungswinkel (engl. angle of refraction; Winkel zwischen dem gebrochenen Lichtstrahl und dem Lot) immer kleiner als der Einfallswinkel (Winkel zwischen dem einfallenden Lichtstrahl und dem Lot) ist. Trifft der Lichtstrahl senkrecht auf die Oberfläche, kommt es zu keiner Ablenkung.

Wie stark ein Lichtstrahl gebrochen wird, hängt von dem jeweiligen (durchsichtigen) Material ab. Nimmst du zum Beispiel Wasser statt Glas, ist der Brechungswinkel (bei gleichem Einfallswinkel) größer – er weicht weniger stark von seiner ursprünglichen Richtung ab.

Bei genauer Betrachtung siehst du auch einen reflektierten Strahl. Tatsächlich teilt sich die Lichtenergie beim Auftreffen an der Grenzschicht der beiden Medien in einen reflektierten und einen gebrochenen Anteil auf.

Links:
- WebApp: Lichtbrechung

### 11.6.2 Fermatsches Prinzip

Welche Eigenschaft eines (lichtdurchlässigen) Materials bestimmt eigentlich, wie stark ein Lichtstrahl gebrochen wird? Der Grund ist, dass sich Licht in unterschiedlichen Materialien unterschiedlich schnell ausbreitet. Während die Geschwindigkeit von Licht an Luft fast der Vakuum-Lichtgeschwindigkeit von $c_0 = 3 \\cdot 10^8 \\text{ m/s}$ entspricht, ist sie in Wasser und Glas kleiner.

![Abbildung 11.51: Wie erreicht der Rettungsschwimmer den Ertrinkenden am schnellsten?](images/abb_11_51.png)
Abbildung 11.51: Wie erreicht der Rettungsschwimmer den Ertrinkenden am schnellsten?

Sieh dir das Bild 11.51 an. Du bist ein Rettungsschwimmer und befindest dich am Strand (Punkt A). Plötzlich entdeckst du im Wasser einen Ertrinkenden (Punkt B). Welchen Weg nimmst du, um ihn am schnellsten zu retten?

Normalerweise ist die Luftlinie der kürzeste Weg. Allerdings kannst du am Strand wesentlich schneller laufen als im Wasser. Daher wird es klüger sein, etwas länger am Strand zu laufen und dann erst abzubiegen. Der Weg wird dadurch zwar länger, aber zeitlich kürzer! In Bild 11.52 siehst du den zeitlich kürzesten Weg für den konkreten Fall, dass der Rettungsschwimmer viermal so schnell am Strand läuft wie im Wasser.

Licht verhält sich nach demselben Prinzip: Ein Lichtstrahl wird stets so gebrochen, dass er die zwei Punkte in kürzester Zeit durchläuft. Dieses Verhalten von Licht wird Fermatsches Prinzip (engl. Fermat's principle) – nach Pierre de Fermat – genannt.

Vielleicht fragst du dich, woher das Licht im Voraus "weiß", welches der kürzeste Weg ist? Siehst du dir die Laufzeitkurve in 11.52 (unten) genau an, stellst du fest, dass sich die Laufzeit um das Minimum herum nur ganz wenig ändert. Das Licht nimmt sozusagen alle Lichtwege gleichzeitig (Wellenphänomen), aber um das Minimum herum findet konstruktive Interferenz statt, alle anderen Wege löschen sich durch destruktive Interferenz aus.

((502))

![Abbildung 11.52: Laufzeit beim Rettungsschwimmer-Problem](images/abb_11_52.png)
Abbildung 11.52: Laufzeit beim Rettungsschwimmer-Problem

### 11.6.3 Brechungsindex

Wie schnell sich Licht in einem Medium ausbreitet, wird oft nicht als Geschwindigkeitswert angegeben. Wegen der großen Zahlen wird stattdessen das Verhältnis der Vakuum-Lichtgeschwindigkeit $c_0$ zur Ausbreitungsgeschwindigkeit $c_M$ des Lichts im Medium (Material) angegeben:

$$n = \\frac{c_0}{c_M}$$ (11.1)

Diese materialabhängige dimensionslose Größe (Zahl) $n$ wird Brechungsindex oder Brechzahl (engl. refractive index) des jeweiligen Materials genannt. Hat ein Medium einen Brechungsindex von 2 ist die Lichtgeschwindigkeit gerade halb so groß wie in Vakuum. Zur Orientierung findest du in der Tabelle die Brechzahlen einiger optischer Medien:

| Material | Brechungsindex n |
| :--- | :--- |
| Vakuum | 1 |
| Luft | 1,000292 |
| Eis | 1,31 |
| Wasser | 1,33 |
| Augenlinse (Mensch) | 1,35 - 1,42 |
| Glas | 1,45 - 1,93 |
| Fensterglas | ca. 1,5 |
| Diamant | 2,42 |

Für den Brechungsindex wird oft auch die Bezeichnung optische Dichte verwendet. Je größer die optische Dichte, desto langsamer breitet sich Licht in diesem Medium aus. Das ist eine recht anschauliche Vorstellung. Der Begriff der Dichte ist prinzipiell unabhängig von dem der optischen Dichte eines Materials. Vielfach haben aber Medien mit einer größeren Dichte auch eine größere optische Dichte.`;

const fibsOptikMd = fs.readFileSync(path.join(ASSETS_DIR, 'demo_fibs_501_502.md'), 'utf-8');

// =============================================================================
// Large Editorial Inline SVG Concept Diagrams
// =============================================================================
const ARCHITECTURE_SVG_HTML = `
  <div style="display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid #cbd5e1; padding-bottom:12px; margin-bottom:16px;">
    <div>
      <div style="font-size:19px; font-weight:800; color:#0f172a; letter-spacing:-0.01em;">
        Zweistufige lokale Verarbeitung — 100 % Offline auf Ihrem Rechner
      </div>
      <div style="font-size:13.5px; color:#475569; margin-top:2px;">
        Sämtliche Schritte laufen datenschutzkonform auf lokaler Hardware ohne Cloud-Übertragung
      </div>
    </div>
    <div style="background:#ecfdf5; color:#065f46; border:1px solid #a7f3d0; border-radius:6px; padding:6px 14px; font-size:12.5px; font-weight:700;">
      Lokal &amp; Datenschutzkonform
    </div>
  </div>
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1260 320" width="100%" style="display:block;">
    <defs>
      <marker id="arrowBlue" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M 0 1.5 L 8.5 5 L 0 8.5 z" fill="#2563eb"/>
      </marker>
      <marker id="arrowTeal" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M 0 1.5 L 8.5 5 L 0 8.5 z" fill="#0d9488"/>
      </marker>
    </defs>

    <!-- Card 1: Schulbuch-PDF -->
    <rect x="8" y="14" width="256" height="236" rx="10" fill="#f8fafc" stroke="#94a3b8" stroke-width="1.5"/>
    <rect x="8" y="14" width="256" height="6" rx="3" fill="#475569"/>
    <g transform="translate(96, 36)">
      <rect x="0" y="0" width="80" height="68" rx="6" fill="#ffffff" stroke="#64748b" stroke-width="1.8"/>
      <line x1="12" y1="14" x2="54" y2="14" stroke="#0f172a" stroke-width="3" stroke-linecap="round"/>
      <line x1="12" y1="25" x2="68" y2="25" stroke="#94a3b8" stroke-width="2"/>
      <line x1="12" y1="33" x2="64" y2="33" stroke="#94a3b8" stroke-width="2"/>
      <rect x="12" y="42" width="28" height="16" rx="2" fill="#dbeafe" stroke="#2563eb" stroke-width="1.2"/>
      <rect x="44" y="42" width="24" height="16" rx="2" fill="#fef3c7" stroke="#d97706" stroke-width="1.2"/>
    </g>
    <text x="136" y="130" text-anchor="middle" font-family="Inter, sans-serif" font-size="15.5" font-weight="800" fill="#0f172a">Schulbuch-PDF</text>
    <text x="136" y="154" text-anchor="middle" font-family="Inter, sans-serif" font-size="12.5" fill="#475569">Digitale Seiten oder Buchscans</text>
    <text x="136" y="176" text-anchor="middle" font-family="Inter, sans-serif" font-size="12.5" fill="#475569">• Mehrspaltiges Layout</text>
    <text x="136" y="196" text-anchor="middle" font-family="Inter, sans-serif" font-size="12.5" fill="#475569">• Mathematische Formeln</text>
    <text x="136" y="216" text-anchor="middle" font-family="Inter, sans-serif" font-size="12.5" fill="#475569">• Abbildungen &amp; Tabellen</text>

    <!-- Arrow 1 -->
    <line x1="270" y1="132" x2="318" y2="132" stroke="#2563eb" stroke-width="3" marker-end="url(#arrowBlue)"/>

    <!-- Card 2: Stufe 1 Optische Seitenanalyse -->
    <rect x="326" y="14" width="292" height="236" rx="10" fill="#eff6ff" stroke="#2563eb" stroke-width="2"/>
    <rect x="342" y="28" width="84" height="22" rx="4" fill="#2563eb"/>
    <text x="384" y="43" text-anchor="middle" font-family="Inter, sans-serif" font-size="11.5" font-weight="700" fill="#ffffff">STUFE 1</text>
    <g transform="translate(544, 28)">
      <rect x="0" y="0" width="56" height="44" rx="6" fill="#ffffff" stroke="#2563eb" stroke-width="1.6"/>
      <rect x="7" y="7" width="18" height="12" rx="1.5" fill="#bfdbfe" stroke="#2563eb" stroke-width="1.2"/>
      <rect x="29" y="7" width="20" height="28" rx="1.5" fill="#99f6e4" stroke="#0d9488" stroke-width="1.2"/>
      <rect x="7" y="23" width="18" height="12" rx="1.5" fill="#fde68a" stroke="#d97706" stroke-width="1.2"/>
    </g>
    <text x="342" y="92" font-family="Inter, sans-serif" font-size="16" font-weight="800" fill="#1e3a8a">Optische Seitenanalyse</text>
    <text x="342" y="118" font-family="Inter, sans-serif" font-size="13" fill="#1e293b">✓ Texte, Formeln &amp; Tabellen erfassen</text>
    <text x="342" y="142" font-family="Inter, sans-serif" font-size="13" fill="#1e293b">✓ Kopf- und Fußzeilen ausblenden</text>
    <text x="342" y="166" font-family="Inter, sans-serif" font-size="13" fill="#1e293b">✓ Bilder ausschneiden &amp; beschreiben</text>
    <text x="342" y="190" font-family="Inter, sans-serif" font-size="13" fill="#1e293b">✓ Überschriften-Ebenen erkennen</text>
    <rect x="342" y="206" width="260" height="28" rx="5" fill="#dbeafe"/>
    <text x="472" y="224" text-anchor="middle" font-family="ui-monospace, monospace" font-size="12" font-weight="700" fill="#1d4ed8">Ergebnis: 1. Extrahiertes Markdown</text>

    <!-- Arrow 2 -->
    <line x1="624" y1="132" x2="672" y2="132" stroke="#0d9488" stroke-width="3" marker-end="url(#arrowTeal)"/>

    <!-- Card 3: Stufe 2 KI-Regel-Standardisierung -->
    <rect x="680" y="14" width="292" height="236" rx="10" fill="#f0fdfa" stroke="#0d9488" stroke-width="2"/>
    <rect x="696" y="28" width="84" height="22" rx="4" fill="#0d9488"/>
    <text x="738" y="43" text-anchor="middle" font-family="Inter, sans-serif" font-size="11.5" font-weight="700" fill="#ffffff">STUFE 2</text>
    <g transform="translate(898, 28)">
      <rect x="0" y="0" width="56" height="44" rx="6" fill="#ffffff" stroke="#0d9488" stroke-width="1.6"/>
      <circle cx="28" cy="22" r="12" fill="#ccfbf1" stroke="#0d9488" stroke-width="1.5"/>
      <text x="28" y="26" text-anchor="middle" font-family="Inter, sans-serif" font-size="10.5" font-weight="800" fill="#0f766e">KI</text>
    </g>
    <text x="696" y="92" font-family="Inter, sans-serif" font-size="16" font-weight="800" fill="#134e4a">FIBS-Regel-Anwendung</text>
    <text x="696" y="118" font-family="Inter, sans-serif" font-size="13" fill="#1e293b">✓ Lokales Sprachmodell Gemma 4</text>
    <text x="696" y="142" font-family="Inter, sans-serif" font-size="13" fill="#1e293b">✓ Offizielle FIBS-Regeln (09/2025)</text>
    <text x="696" y="166" font-family="Inter, sans-serif" font-size="13" fill="#1e293b">✓ Buchseitenmarker ((501)), &lt;Bild&gt;</text>
    <text x="696" y="190" font-family="Inter, sans-serif" font-size="13" fill="#1e293b">✓ Zusatzregeln der Buchkonferenz</text>
    <rect x="696" y="206" width="260" height="28" rx="5" fill="#ccfbf1"/>
    <text x="826" y="224" text-anchor="middle" font-family="ui-monospace, monospace" font-size="12" font-weight="700" fill="#0f766e">Ergebnis: 2. E-Buch-Markdown</text>

    <!-- Arrow 3 -->
    <line x1="978" y1="132" x2="1024" y2="132" stroke="#0d9488" stroke-width="3" marker-end="url(#arrowTeal)"/>

    <!-- Card 4: Barrierefreies Word-Dokument -->
    <rect x="1032" y="14" width="220" height="236" rx="10" fill="#f8fafc" stroke="#059669" stroke-width="2"/>
    <rect x="1032" y="14" width="220" height="6" rx="3" fill="#059669"/>
    <g transform="translate(1108, 34)">
      <rect x="0" y="0" width="68" height="64" rx="6" fill="#2563eb"/>
      <text x="34" y="42" text-anchor="middle" font-family="Inter, sans-serif" font-size="28" font-weight="800" fill="#ffffff">W</text>
    </g>
    <text x="1142" y="124" text-anchor="middle" font-family="Inter, sans-serif" font-size="15.5" font-weight="800" fill="#0f172a">Word-Export (.docx)</text>
    <text x="1142" y="150" text-anchor="middle" font-family="Inter, sans-serif" font-size="12.5" fill="#334155">• FIBS-Formatvorlagen</text>
    <text x="1142" y="172" text-anchor="middle" font-family="Inter, sans-serif" font-size="12.5" fill="#334155">• Verdana 14 pt, 1,5-zeilig</text>
    <text x="1142" y="194" text-anchor="middle" font-family="Inter, sans-serif" font-size="12.5" fill="#334155">• Seitenumbrüche &amp; Tabellen</text>
    <text x="1142" y="216" text-anchor="middle" font-family="Inter, sans-serif" font-size="12.5" fill="#334155">• Screenreader-Textmarken</text>

    <!-- Bottom Banner -->
    <rect x="8" y="268" width="1244" height="44" rx="8" fill="#0f172a"/>
    <circle cx="38" cy="290" r="10" fill="#10b981"/>
    <path d="M 33.5 290 L 36.8 293.3 L 43 287" fill="none" stroke="#ffffff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
    <text x="60" y="295" font-family="Inter, sans-serif" font-size="13.5" font-weight="600" fill="#f8fafc">
      100 % Offline-Betrieb auf dem eigenen Gerät  •  Geschützte Verlagswerke verlassen zu keinem Zeitpunkt Ihren Arbeitsplatzrechner
    </text>
  </svg>
`;

const EXTRACTION_CONCEPT_SVG_HTML = `
  <div style="display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid #cbd5e1; padding-bottom:12px; margin-bottom:14px;">
    <div>
      <div style="font-size:19px; font-weight:800; color:#0f172a; letter-spacing:-0.01em;">
        Was bei der Seitenanalyse passiert — Von der Buchseite zur klaren Lesestruktur
      </div>
      <div style="font-size:13.5px; color:#475569; margin-top:2px;">
        Jede Seite wird gleichzeitig textlich und optisch ausgewertet, bereinigt und geordnet
      </div>
    </div>
    <div style="background:#eff6ff; color:#1d4ed8; border:1px solid #bfdbfe; border-radius:6px; padding:6px 14px; font-size:12.5px; font-weight:700;">
      Text + Optik kombiniert
    </div>
  </div>
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1260 356" width="100%" style="display:block;">
    <defs>
      <marker id="arrowFlow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
        <path d="M 0 1.5 L 8.5 5 L 0 8.5 z" fill="#2563eb"/>
      </marker>
    </defs>

    <!-- LEFT: Illustrated Printed Textbook Page -->
    <rect x="16" y="8" width="490" height="338" rx="10" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1.5"/>
    <text x="38" y="34" font-family="Inter, sans-serif" font-size="14" font-weight="800" fill="#334155">1. Gedruckte Buchseite (Vorlage)</text>

    <!-- White Textbook Sheet -->
    <rect x="38" y="48" width="446" height="282" rx="6" fill="#ffffff" stroke="#94a3b8" stroke-width="1.5"/>

    <!-- Running Header crossed out -->
    <rect x="54" y="58" width="414" height="24" rx="4" fill="#fee2e2" stroke="#ef4444" stroke-width="1.2" stroke-dasharray="4 3"/>
    <text x="64" y="74" font-family="Inter, sans-serif" font-size="11" fill="#991b1b">11.6. LICHT IN UNTERSCHIEDLICHEN MEDIEN</text>
    <text x="456" y="74" text-anchor="end" font-family="Inter, sans-serif" font-size="11" font-weight="700" fill="#991b1b">501</text>
    <line x1="58" y1="70" x2="424" y2="70" stroke="#dc2626" stroke-width="1.5"/>

    <!-- Section Heading -->
    <rect x="54" y="92" width="248" height="24" rx="4" fill="#fef3c7" stroke="#d97706" stroke-width="1.3"/>
    <text x="64" y="108" font-family="Inter, sans-serif" font-size="12.5" font-weight="800" fill="#92400e">11.6.2 Fermatsches Prinzip</text>

    <!-- Paragraph + Formula -->
    <rect x="54" y="124" width="414" height="44" rx="4" fill="#eff6ff" stroke="#3b82f6" stroke-width="1.2"/>
    <line x1="64" y1="138" x2="446" y2="138" stroke="#64748b" stroke-width="2.2" stroke-linecap="round"/>
    <line x1="64" y1="152" x2="290" y2="152" stroke="#64748b" stroke-width="2.2" stroke-linecap="round"/>
    <rect x="302" y="143" width="154" height="18" rx="3" fill="#cffafe" stroke="#0891b2" stroke-width="1.1"/>
    <text x="379" y="156" text-anchor="middle" font-family="Georgia, serif" font-size="11.5" font-weight="700" fill="#0e7490">c₀ = 3 · 10⁸ m/s</text>

    <!-- Figure with crop marks -->
    <rect x="54" y="178" width="198" height="92" rx="4" fill="#f0fdfa" stroke="#0d9488" stroke-width="1.8" stroke-dasharray="5 3"/>
    <rect x="68" y="188" width="170" height="32" fill="#fef08a"/>
    <rect x="68" y="220" width="170" height="32" fill="#bfdbfe"/>
    <line x1="84" y1="194" x2="162" y2="220" stroke="#dc2626" stroke-width="2"/>
    <line x1="162" y1="220" x2="212" y2="246" stroke="#dc2626" stroke-width="2"/>
    <text x="153" y="264" text-anchor="middle" font-family="Inter, sans-serif" font-size="10" font-weight="700" fill="#0f766e">Abb. 11.51 (Ausschnitt)</text>

    <!-- Info Box / Table on right of figure -->
    <rect x="264" y="178" width="204" height="92" rx="4" fill="#fff7ed" stroke="#ea580c" stroke-width="1.4"/>
    <text x="276" y="196" font-family="Inter, sans-serif" font-size="11" font-weight="700" fill="#9a3412">Tabelle / Infokasten</text>
    <line x1="274" y1="206" x2="456" y2="206" stroke="#fdba74" stroke-width="1.2"/>
    <text x="276" y="222" font-family="Inter, sans-serif" font-size="10.5" fill="#431407">Material        | Brechzahl n</text>
    <text x="276" y="238" font-family="Inter, sans-serif" font-size="10.5" fill="#431407">Wasser         | 1,33</text>
    <text x="276" y="254" font-family="Inter, sans-serif" font-size="10.5" fill="#431407">Fensterglas  | ca. 1,5</text>

    <!-- Bottom footer crossed out -->
    <rect x="54" y="282" width="414" height="36" rx="4" fill="#eff6ff" stroke="#3b82f6" stroke-width="1.2"/>
    <line x1="64" y1="296" x2="448" y2="296" stroke="#64748b" stroke-width="2.2" stroke-linecap="round"/>
    <line x1="64" y1="309" x2="380" y2="309" stroke="#64748b" stroke-width="2.2" stroke-linecap="round"/>

    <!-- CENTER ARROW -->
    <g transform="translate(522, 146)">
      <rect x="0" y="0" width="156" height="64" rx="10" fill="#1e293b"/>
      <text x="78" y="26" text-anchor="middle" font-family="Inter, sans-serif" font-size="12.5" font-weight="700" fill="#93c5fd">Automatische</text>
      <text x="78" y="45" text-anchor="middle" font-family="Inter, sans-serif" font-size="12.5" font-weight="700" fill="#ffffff">Strukturierung</text>
      <line x1="158" y1="32" x2="196" y2="32" stroke="#2563eb" stroke-width="3.2" marker-end="url(#arrowFlow)"/>
    </g>

    <!-- RIGHT: Clean Structured Reading Flow -->
    <rect x="728" y="8" width="516" height="338" rx="10" fill="#f8fafc" stroke="#2563eb" stroke-width="2"/>
    <text x="752" y="34" font-family="Inter, sans-serif" font-size="14" font-weight="800" fill="#1e3a8a">2. Bereinigte, barrierefreie Lesereihenfolge</text>

    <!-- Step Row 1 -->
    <rect x="750" y="48" width="472" height="50" rx="7" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.2"/>
    <rect x="750" y="48" width="6" height="50" rx="3" fill="#ef4444"/>
    <text x="770" y="69" font-family="Inter, sans-serif" font-size="13" font-weight="700" fill="#0f172a">Kopf- und Fußzeilen ausgeblendet • Buchseite ((501)) gesichert</text>
    <text x="770" y="88" font-family="Inter, sans-serif" font-size="12" fill="#475569">Störende Kolumnentitel am Seitenrand unterbrechen nicht mehr den Lesefluss.</text>

    <!-- Step Row 2 -->
    <rect x="750" y="108" width="472" height="50" rx="7" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.2"/>
    <rect x="750" y="108" width="6" height="50" rx="3" fill="#d97706"/>
    <text x="770" y="129" font-family="Inter, sans-serif" font-size="13" font-weight="700" fill="#0f172a">Überschriften &amp; Absätze klar gegliedert</text>
    <text x="770" y="148" font-family="Inter, sans-serif" font-size="12" fill="#475569">Kapitel- und Teilüberschriften erhalten die richtige Gliederungsebene.</text>

    <!-- Step Row 3 -->
    <rect x="750" y="168" width="472" height="50" rx="7" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.2"/>
    <rect x="750" y="168" width="6" height="50" rx="3" fill="#0d9488"/>
    <text x="770" y="189" font-family="Inter, sans-serif" font-size="13" font-weight="700" fill="#0f172a">Abbildungen ausgeschnitten &amp; im Kontext beschrieben</text>
    <text x="770" y="208" font-family="Inter, sans-serif" font-size="12" fill="#475569">Jede Grafik wird einzeln betrachtet und mit passendem Seitentext beschrieben.</text>

    <!-- Step Row 4 -->
    <rect x="750" y="228" width="472" height="50" rx="7" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.2"/>
    <rect x="750" y="228" width="6" height="50" rx="3" fill="#2563eb"/>
    <text x="770" y="249" font-family="Inter, sans-serif" font-size="13" font-weight="700" fill="#0f172a">Formeln, Infokästen &amp; Tabellen strukturiert erfasst</text>
    <text x="770" y="268" font-family="Inter, sans-serif" font-size="12" fill="#475569">Mathematische Ausdrücke und Spaltentabellen bleiben vollständig erhalten.</text>

    <!-- Step Row 5 -->
    <rect x="750" y="288" width="472" height="44" rx="7" fill="#eff6ff" stroke="#93c5fd" stroke-width="1.2"/>
    <text x="986" y="315" text-anchor="middle" font-family="Inter, sans-serif" font-size="12.5" font-weight="700" fill="#1d4ed8">
      Bereit für die automatische Anwendung der FIBS-Übertragungsregeln
    </text>
  </svg>
`;

async function waitForUrl(url, timeoutMs = 25000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(url);
      if (res.ok) return true;
    } catch {}
    await new Promise(r => setTimeout(r, 300));
  }
  throw new Error(`Timeout waiting for ${url}`);
}

async function injectVideoHud(page) {
  await page.evaluate(() => {
    if (document.getElementById('video-hud-root')) return;

    const style = document.createElement('style');
    style.textContent = `
      html.theme-light {
        background-color: #f1f5f9 !important;
      }
      body {
        transform-origin: 0 0 !important;
        transition: none !important;
      }
      /* Ensure Benchmark & Feedback cards have crisp light-theme contrast */
      html.theme-light #main-benchmark-view .glass-card,
      html.theme-light #main-feedback-view .glass-card {
        background: #ffffff !important;
        border: 1px solid #cbd5e1 !important;
        box-shadow: 0 4px 16px rgba(15, 23, 42, 0.06) !important;
      }
      html.theme-light #main-benchmark-view h2,
      html.theme-light #main-benchmark-view h3,
      html.theme-light #main-benchmark-view h4,
      html.theme-light #main-benchmark-view h5,
      html.theme-light #main-feedback-view h2,
      html.theme-light #main-feedback-view h3,
      html.theme-light #main-feedback-view .fb-live-summary span {
        color: #0f172a !important;
      }
      #video-hud-root {
        position: fixed;
        inset: 0;
        pointer-events: none;
        z-index: 999999;
        overflow: hidden;
        font-family: Inter, system-ui, -apple-system, sans-serif;
      }
      #video-spotlight {
        position: fixed;
        border: 2.5px solid #2563eb;
        border-radius: 8px;
        box-shadow: 0 0 0 9999px rgba(15, 23, 42, 0.22);
        transition: none !important;
        opacity: 0;
      }
      #video-spotlight-label {
        position: absolute;
        top: -36px;
        left: 0;
        background: #0f172a;
        color: #f8fafc;
        font-size: 13px;
        font-weight: 600;
        padding: 5px 13px;
        border-radius: 6px;
        white-space: nowrap;
        border: 1px solid #2563eb;
      }
      #video-open-mode-menu {
        position: fixed;
        background: #ffffff;
        border: 2px solid #2563eb;
        border-radius: 9px;
        box-shadow: 0 18px 38px rgba(15, 23, 42, 0.28);
        padding: 6px;
        width: 248px;
        z-index: 1000003;
        display: none;
        font-family: Inter, system-ui, -apple-system, sans-serif;
      }
      .video-mode-item {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 8px 11px;
        border-radius: 6px;
        font-size: 13px;
        font-weight: 600;
        color: #1e293b;
      }
      .video-mode-item.is-active {
        background: #eff6ff;
        color: #1d4ed8;
        font-weight: 700;
      }
      #video-lower-third {
        position: fixed;
        bottom: 16px;
        left: 28px;
        right: 28px;
        width: auto;
        max-width: 1864px;
        background: #0f172a;
        border: 1px solid #334155;
        border-left: 4px solid #2563eb;
        border-radius: 10px;
        padding: 14px 26px;
        box-shadow: 0 12px 32px rgba(15, 23, 42, 0.45);
        display: flex;
        align-items: center;
        gap: 22px;
        z-index: 1000002;
      }
      #video-meta-col {
        display: flex;
        align-items: center;
        flex-shrink: 0;
        border-right: 1px solid #334155;
        padding-right: 20px;
      }
      #video-step-pill {
        color: #93c5fd;
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        font-variant-numeric: tabular-nums;
        font-weight: 700;
        font-size: 15.5px;
        letter-spacing: -0.01em;
        white-space: nowrap;
      }
      #video-caption-text {
        color: #f8fafc;
        font-size: 20.5px;
        font-weight: 450;
        line-height: 1.45;
      }
      #video-md-callout {
        position: fixed;
        top: 45%;
        left: 50%;
        transform: translate(-50%, -50%);
        width: 1320px;
        max-width: 92vw;
        background: #ffffff;
        border: 2px solid #2563eb;
        border-radius: 12px;
        padding: 22px 28px;
        box-shadow: 0 20px 48px rgba(15, 23, 42, 0.36);
        color: #0f172a;
        font-family: Inter, system-ui, -apple-system, sans-serif;
        font-size: 14px;
        line-height: 1.55;
        opacity: 0;
        transition: none !important;
        z-index: 1000000;
      }
    `;
    document.head.appendChild(style);

    const hud = document.createElement('div');
    hud.id = 'video-hud-root';
    hud.innerHTML = `
      <div id="video-spotlight"><div id="video-spotlight-label"></div></div>
      <div id="video-open-mode-menu">
        <div class="video-mode-item is-active"><span>📄 Übertragung</span><span>✓</span></div>
        <div class="video-mode-item"><span>⚖️ Benchmark &amp; Evaluierung</span><span></span></div>
        <div class="video-mode-item"><span>💬 Feedback</span><span></span></div>
        <div class="video-mode-item"><span>⚙️ Einstellungen</span><span></span></div>
      </div>
      <div id="video-md-callout"></div>
      <div id="video-lower-third">
        <div id="video-meta-col">
          <div id="video-step-pill">Schritt 1 / 17</div>
        </div>
        <div id="video-caption-text"></div>
      </div>
    `;
    document.documentElement.appendChild(hud);

    window._currentFocusConfig = null;

    window.refreshSpotlight = () => {
      document.documentElement.classList.add('theme-light');
      const themeSel = document.getElementById('theme-select');
      if (themeSel && themeSel.value !== 'light') themeSel.value = 'light';
      const cfg = window._currentFocusConfig;
      if (!cfg) return;

      const openMenu = document.getElementById('video-open-mode-menu');
      if (openMenu) {
        if (cfg.showModeDropdown) {
          const modeSel = document.getElementById('main-mode-select');
          if (modeSel) {
            const r = modeSel.getBoundingClientRect();
            openMenu.style.left = `${Math.round(r.left - 4)}px`;
            openMenu.style.top = `${Math.round(r.bottom + 6)}px`;
            openMenu.style.display = 'block';
          }
        } else {
          openMenu.style.display = 'none';
        }
      }

      const { selectors = [], customBox = null, spotlightLabel = '', pad = 6 } = cfg;
      const sp = document.getElementById('video-spotlight');
      const spLabel = document.getElementById('video-spotlight-label');
      if (!sp || !spLabel) return;

      let minX = Infinity,
        minY = Infinity,
        maxX = -Infinity,
        maxY = -Infinity;
      if (customBox) {
        minX = customBox.x;
        minY = customBox.y;
        maxX = customBox.x + customBox.w;
        maxY = customBox.y + customBox.h;
      } else if (selectors.length > 0) {
        for (const sel of selectors) {
          const el = document.querySelector(sel);
          if (el) {
            const cStyle = window.getComputedStyle(el);
            if (
              cStyle.display === 'none' ||
              cStyle.visibility === 'hidden' ||
              cStyle.opacity === '0'
            ) {
              continue;
            }
            const r = el.getBoundingClientRect();
            if (r.width > 2 && r.height > 2) {
              minX = Math.min(minX, r.left);
              minY = Math.min(minY, r.top);
              maxX = Math.max(maxX, r.right);
              maxY = Math.max(maxY, r.bottom);
            }
          }
        }
      }

      if (minX !== Infinity && maxX > minX && maxY > minY) {
        const sx = Math.max(4, Math.round(minX - pad));
        const sy = Math.max(4, Math.round(minY - pad));
        const sw = Math.max(24, Math.min(1916 - sx, Math.round(maxX - minX + pad * 2)));
        // Full-height spotlight allowed all the way to bottom of viewport (1076px)
        const sh = Math.max(24, Math.min(1076 - sy, Math.round(maxY - minY + pad * 2)));

        sp.style.opacity = '1';
        sp.style.left = `${sx}px`;
        sp.style.top = `${sy}px`;
        sp.style.width = `${sw}px`;
        sp.style.height = `${sh}px`;

        spLabel.textContent = spotlightLabel || '';
        spLabel.style.display = spotlightLabel ? 'block' : 'none';

        if (cfg.labelLeft) {
          spLabel.style.left = cfg.labelLeft;
          spLabel.style.right = 'auto';
        } else if (sx > 1180) {
          spLabel.style.left = 'auto';
          spLabel.style.right = '0px';
        } else {
          spLabel.style.left = '0px';
          spLabel.style.right = 'auto';
        }

        if (sy < 46) {
          if (sy + sh < 890) {
            spLabel.style.top = 'calc(100% + 8px)';
            spLabel.style.bottom = 'auto';
          } else {
            spLabel.style.top = '10px';
            if (!cfg.labelLeft) {
              spLabel.style.left = sx > 1180 ? 'auto' : '12px';
              spLabel.style.right = sx > 1180 ? '12px' : 'auto';
            }
          }
        } else {
          spLabel.style.top = '-36px';
          spLabel.style.bottom = 'auto';
        }
      } else {
        sp.style.opacity = '0';
      }
    };

    window.focusOnSelectors = config => {
      const {
        step,
        caption,
        selectors = [],
        customBox = null,
        zoom = 1.0,
        mdCallout = null,
        calloutPos = null,
        calloutWidth = '1320px',
        allowBottomOverscroll = false,
      } = config;

      window._currentFocusConfig = config;

      if (step) document.getElementById('video-step-pill').textContent = step;
      if (caption !== undefined) {
        document.getElementById('video-caption-text').textContent = caption;
      }

      document.body.style.transform = 'none';
      void document.body.offsetHeight;

      let uMinX = Infinity,
        uMinY = Infinity,
        uMaxX = -Infinity,
        uMaxY = -Infinity;
      if (customBox) {
        uMinX = customBox.x;
        uMinY = customBox.y;
        uMaxX = customBox.x + customBox.w;
        uMaxY = customBox.y + customBox.h;
      } else if (selectors.length > 0) {
        for (const sel of selectors) {
          const el = document.querySelector(sel);
          if (el) {
            const cStyle = window.getComputedStyle(el);
            if (cStyle.display === 'none' || cStyle.visibility === 'hidden') continue;
            const r = el.getBoundingClientRect();
            if (r.width > 2 && r.height > 2) {
              uMinX = Math.min(uMinX, r.left);
              uMinY = Math.min(uMinY, r.top);
              uMaxX = Math.max(uMaxX, r.right);
              uMaxY = Math.max(uMaxY, r.bottom);
            }
          }
        }
      }

      if (zoom > 1.0 && uMinX !== Infinity) {
        const cx = (uMinX + uMaxX) / 2;
        const cy = (uMinY + uMaxY) / 2;
        const targetScreenY = config.zoomTargetY || 460;
        let tx = 960 - cx * zoom;
        let ty = targetScreenY - cy * zoom;

        tx = Math.min(0, Math.max(1920 * (1 - zoom), tx));
        if (!allowBottomOverscroll) {
          ty = Math.min(0, Math.max(1080 * (1 - zoom), ty));
        } else {
          ty = Math.min(0, ty);
        }

        if (uMaxX * zoom + tx > 1892) tx = 1892 - uMaxX * zoom;
        if (uMinX * zoom + tx < 20) tx = 20 - uMinX * zoom;
        // Ensure zoomed target sits comfortably above #video-lower-third (top ~950px)
        if (uMaxY * zoom + ty > 855) ty = 855 - uMaxY * zoom;
        if (uMinY * zoom + ty < 56) ty = 56 - uMinY * zoom;

        document.body.style.transform = `translate(${Math.round(tx)}px, ${Math.round(ty)}px) scale(${zoom})`;
        void document.body.offsetHeight;
      } else {
        document.body.style.transform = 'none';
        void document.body.offsetHeight;
      }

      window.refreshSpotlight();

      const mc = document.getElementById('video-md-callout');
      if (mdCallout) {
        mc.style.opacity = '1';
        mc.style.width = calloutWidth;
        mc.innerHTML = mdCallout;
        mc.style.left = (calloutPos && calloutPos.left) || '50%';
        mc.style.top = (calloutPos && calloutPos.top) || '45%';
      } else {
        mc.style.opacity = '0';
      }
    };
  });
}

async function main() {
  console.log(
    `[1/4] Starting Backend (FastAPI) and Frontend (Vite) [ffmpeg: ${FFMPEG_BIN}]...`
  );
  const backendProc = spawn(
    path.join(PROJECT_DIR, '.venv/bin/uvicorn'),
    ['backend.main:app', '--port', '8000'],
    {
      cwd: PROJECT_DIR,
      env: { ...process.env, PYTHONPATH: PROJECT_DIR, E2E_MOCK: 'true' },
      stdio: 'ignore',
    }
  );

  const frontendProc = spawn(
    process.execPath,
    ['./node_modules/vite/bin/vite.js', '--port', '3000'],
    {
      cwd: PROJECT_DIR,
      env: { ...process.env },
      stdio: 'ignore',
    }
  );

  try {
    await waitForUrl('http://localhost:8000/docs');
    await waitForUrl('http://localhost:3000');
    console.log('[2/4] Servers ready. Launching Playwright Chromium (1920x1080)...');

    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
      viewport: { width: 1920, height: 1080 },
      deviceScaleFactor: 1,
    });
    const page = await context.newPage();
    await page.goto('http://localhost:3000', { waitUntil: 'networkidle' });
    await injectVideoHud(page);

    const FPS = 12;
    const byId = Object.fromEntries(manifest.map((m, idx) => [m.id, idx]));

    async function recordBeat(beatId, actionsBySec) {
      const sceneIndex = byId[beatId];
      if (sceneIndex === undefined) {
        throw new Error(`Unknown beatId in manifest: ${beatId}`);
      }
      const seg = manifest[sceneIndex];
      const sceneDir = path.join(FRAMES_DIR, seg.id);
      const sceneMp4 = path.join(SCENES_DIR, `${seg.id}.mp4`);

      if (ONLY_SCENES_SET.size > 0 && !ONLY_SCENES_SET.has(seg.id) && fs.existsSync(sceneMp4)) {
        for (const fn of Object.values(actionsBySec)) {
          await fn(seg);
        }
        return sceneMp4;
      }

      fs.rmSync(sceneDir, { recursive: true, force: true });
      fs.mkdirSync(sceneDir, { recursive: true });

      const totalSec = seg.duration_sec;
      const totalFrames = Math.max(1, Math.round(totalSec * FPS));
      const triggered = new Set();

      console.log(
        `  -> Recording [${String(sceneIndex + 1).padStart(2, '0')}/${manifest.length}] ` +
          `${seg.id} (${seg.voice}): ${totalSec.toFixed(2)}s (${totalFrames} frames)...`
      );

      for (let f = 0; f < totalFrames; f++) {
        const t = f / FPS;
        for (const [secStr, fn] of Object.entries(actionsBySec)) {
          const sec = parseFloat(secStr);
          if (t >= sec && !triggered.has(secStr)) {
            triggered.add(secStr);
            await fn(seg);
          }
        }
        await page.evaluate(() => {
          if (typeof window.refreshSpotlight === 'function') {
            window.refreshSpotlight();
          }
        });
        const framePath = path.join(sceneDir, `frame_${String(f).padStart(4, '0')}.jpg`);
        await page.screenshot({ path: framePath, type: 'jpeg', quality: 92 });
      }

      execSync(
        `"${FFMPEG_BIN}" -y -framerate ${FPS} -i "${sceneDir}/frame_%04d.jpg" -i "${seg.wav_path}" ` +
          `-c:v libx264 -preset fast -crf 17 -r 30 -pix_fmt yuv420p ` +
          `-c:a aac -b:a 192k -ar 24000 -shortest "${sceneMp4}"`,
        { stdio: 'ignore' }
      );
      return sceneMp4;
    }

    // =========================================================================
    // 01a_welcome: Clean unhighlighted welcome view (NO spotlight, NO zoom)
    // =========================================================================
    await recordBeat('01a_welcome', {
      '0.0': async seg => {
        await page.evaluate(s => {
          window.focusOnSelectors({
            step: s.step_label,
            caption: s.caption_text,
            zoom: 1.0,
            selectors: [],
            spotlightLabel: '',
          });
        }, seg);
      },
    });

    // =========================================================================
    // 01b_header_overview: Top header continuously highlighted
    // =========================================================================
    await recordBeat('01b_header_overview', {
      '0.0': async seg => {
        await page.evaluate(s => {
          window.focusOnSelectors({
            step: s.step_label,
            caption: s.caption_text,
            zoom: 1.0,
            selectors: ['header'],
            pad: 4,
            spotlightLabel: 'Kopfleiste: 4-Stufen-Prozessanzeige • Farbschema • Teilansichten',
            showModeDropdown: false,
          });
        }, seg);
      },
    });

    // =========================================================================
    // 01c_header_modes_dropdown: Header stays highlighted + Mode dropdown open
    // =========================================================================
    await recordBeat('01c_header_modes_dropdown', {
      '0.0': async seg => {
        await page.evaluate(s => {
          window.focusOnSelectors({
            step: s.step_label,
            caption: s.caption_text,
            zoom: 1.0,
            selectors: ['header'],
            pad: 4,
            labelLeft: '500px',
            spotlightLabel: 'Modus-Menü geöffnet: Übertragung • Benchmark • Feedback • Einstellungen',
            showModeDropdown: true,
          });
        }, seg);
      },
    });

    // =========================================================================
    // 02a_workspace_left: Left sidebar highlighted & explained
    // =========================================================================
    await recordBeat('02a_workspace_left', {
      '0.0': async seg => {
        await page.evaluate(s => {
          window.focusOnSelectors({
            step: s.step_label,
            caption: s.caption_text,
            zoom: 1.0,
            selectors: ['#left-sidebar'],
            pad: 4,
            spotlightLabel: 'Linke Seitenleiste: Regelsatz, Upload & Erkennungs-Optionen',
            showModeDropdown: false,
          });
        }, seg);
      },
    });

    // =========================================================================
    // 02b_workspace_center: Center main area highlighted & explained
    // =========================================================================
    await recordBeat('02b_workspace_center', {
      '0.0': async seg => {
        await page.evaluate(s => {
          const rawPanel = document.getElementById('panel-raw-container');
          if (rawPanel) rawPanel.classList.remove('hidden');
          const toggleRaw = document.getElementById('toggle-pane-raw');
          if (toggleRaw) {
            toggleRaw.className =
              'px-2.5 py-0.5 rounded-md font-semibold text-white bg-indigo-650 border border-indigo-550 transition-all duration-150 h-full';
          }
          window.focusOnSelectors({
            step: s.step_label,
            caption: s.caption_text,
            zoom: 1.0,
            selectors: ['main'],
            pad: 4,
            spotlightLabel: 'Mittlerer Hauptbereich: Dokument-Vorschau & Markdown-Editoren',
          });
        }, seg);
      },
    });

    // =========================================================================
    // 02c_workspace_right: Right sidebar highlighted & explained
    // =========================================================================
    await recordBeat('02c_workspace_right', {
      '0.0': async seg => {
        await page.evaluate(s => {
          window.focusOnSelectors({
            step: s.step_label,
            caption: s.caption_text,
            zoom: 1.0,
            selectors: ['#right-sidebar'],
            pad: 4,
            spotlightLabel: 'Rechte Seitenleiste: Zielgruppen-Profil, Vorlage & Word-Export',
          });
        }, seg);
      },
    });

    // =========================================================================
    // 03_concept_architecture: Large SVG 2-Stage Offline Architecture Overlay
    // =========================================================================
    await recordBeat('03_concept_architecture', {
      '0.0': async seg => {
        await page.evaluate(
          ({ s, svgHtml }) => {
            window.focusOnSelectors({
              step: s.step_label,
              caption: s.caption_text,
              zoom: 1.0,
              selectors: ['header'],
              pad: 4,
              spotlightLabel: '',
              calloutWidth: '1340px',
              calloutPos: { left: '50%', top: '46%' },
              mdCallout: svgHtml,
            });
          },
          { s: seg, svgHtml: ARCHITECTURE_SVG_HTML }
        );
      },
    });

    // =========================================================================
    // 04a_ruleset_select: NO zoom, ONLY ruleset label + dropdown highlighted
    // =========================================================================
    await recordBeat('04a_ruleset_select', {
      '0.0': async seg => {
        await page.selectOption('#ruleset-select', 'uebertragungsregeln_09_2025');
        await page.evaluate(s => {
          window.focusOnSelectors({
            step: s.step_label,
            caption: s.caption_text,
            zoom: 1.0,
            selectors: ['label[for="ruleset-select"]', '#ruleset-select'],
            pad: 6,
            spotlightLabel: 'Regelsatz: Übertragungsregeln FIBS (September 2025)',
          });
        }, seg);
      },
    });

    // =========================================================================
    // 04b_document_upload: Separate upload beat (neutral name, optional rules)
    // =========================================================================
    await recordBeat('04b_document_upload', {
      '0.0': async seg => {
        await page.evaluate(s => {
          window.focusOnSelectors({
            step: s.step_label,
            caption: s.caption_text,
            zoom: 1.0,
            selectors: ['#dropzone', '#additional-ruleset-container'],
            pad: 6,
            spotlightLabel: 'Schulbuch-Upload & optionale Zusatzregeln',
          });
        }, seg);
      },
      '1.2': async seg => {
        const fileInput = page.locator('#file-input');
        await fileInput.setInputFiles({
          name: 'schulbuch_kapitel.pdf',
          mimeType: 'application/pdf',
          buffer: fs.readFileSync(path.join(PROJECT_DIR, 'testdata/physik_optik_sample.pdf')),
        });
        await page.waitForTimeout(550);
        await page.evaluate(s => {
          const rulesetActions = document.getElementById('ruleset-actions');
          const rulesetBadge = document.getElementById('ruleset-badge');
          if (rulesetActions && rulesetBadge) {
            rulesetActions.classList.remove('hidden');
            rulesetBadge.textContent = 'zusatzregeln_physik.txt';
          }
          window.focusOnSelectors({
            step: s.step_label,
            caption: s.caption_text,
            zoom: 1.0,
            selectors: ['#file-status', '#additional-ruleset-container'],
            pad: 6,
            spotlightLabel: 'Kapitel geladen • Optionale Zusatzregeln der Buchkonferenz aktiv',
          });
        }, seg);
      },
    });

    // =========================================================================
    // 05_page_selection: Book pages 501, 502 (NO zoom)
    // =========================================================================
    await recordBeat('05_page_selection', {
      '0.0': async seg => {
        await page.fill('#pages-input', '501, 502');
        await page.evaluate(s => {
          if (document.activeElement instanceof HTMLElement) {
            document.activeElement.blur();
          }
          const errEl = document.getElementById('pages-input-error');
          if (errEl) errEl.classList.add('hidden');
          window.focusOnSelectors({
            step: s.step_label,
            caption: s.caption_text,
            zoom: 1.0,
            selectors: ['#pages-select-container'],
            pad: 6,
            spotlightLabel: 'Seitenauswahl: Gedruckte Buchseiten 501 und 502',
            calloutWidth: '640px',
            calloutPos: { left: '56%', top: '45%' },
            mdCallout: `
              <div style="font-size:16px; font-weight:800; color:#0f172a; border-bottom:1px solid #e2e8f0; padding-bottom:8px; margin-bottom:12px;">
                Automatische Buchseiten-Zuordnung
              </div>
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 580 120" width="100%" style="display:block;">
                <rect x="4" y="12" width="170" height="94" rx="8" fill="#eff6ff" stroke="#2563eb" stroke-width="1.5"/>
                <text x="89" y="42" text-anchor="middle" font-family="Inter, sans-serif" font-size="12" font-weight="700" fill="#1e3a8a">Eingabe Buchseiten</text>
                <text x="89" y="74" text-anchor="middle" font-family="ui-monospace, monospace" font-size="20" font-weight="800" fill="#2563eb">501, 502</text>
                <line x1="180" y1="59" x2="212" y2="59" stroke="#64748b" stroke-width="2.5"/>
                <rect x="218" y="12" width="164" height="94" rx="8" fill="#f8fafc" stroke="#94a3b8" stroke-width="1.5"/>
                <text x="300" y="42" text-anchor="middle" font-family="Inter, sans-serif" font-size="12" font-weight="700" fill="#334155">PDF-Dateiseiten</text>
                <text x="300" y="74" text-anchor="middle" font-family="Inter, sans-serif" font-size="15" font-weight="700" fill="#0f172a">Seite 2 &amp; Seite 3</text>
                <line x1="388" y1="59" x2="418" y2="59" stroke="#0d9488" stroke-width="2.5"/>
                <rect x="424" y="12" width="152" height="94" rx="8" fill="#f0fdfa" stroke="#0d9488" stroke-width="1.5"/>
                <text x="500" y="42" text-anchor="middle" font-family="Inter, sans-serif" font-size="12" font-weight="700" fill="#134e4a">Im E-Buch-Text</text>
                <text x="500" y="74" text-anchor="middle" font-family="ui-monospace, monospace" font-size="17" font-weight="800" fill="#0f766e">((501))  ((502))</text>
              </svg>
            `,
          });
        }, seg);
      },
    });

    // =========================================================================
    // 06_engine_selection: 3 Local Engines + Image Descriptions (NO zoom)
    // =========================================================================
    await recordBeat('06_engine_selection', {
      '0.0': async seg => {
        await page.selectOption('#engine-select', 'infinity');
        await page.evaluate(s => {
          window.focusOnSelectors({
            step: s.step_label,
            caption: s.caption_text,
            zoom: 1.0,
            selectors: ['#engine-select-container', '#describe-images-toggle-container'],
            pad: 6,
            spotlightLabel: 'Erkennungs-Variante & automatische Bildbeschreibungen',
            calloutWidth: '680px',
            calloutPos: { left: '56%', top: '46%' },
            mdCallout: `
              <div style="font-size:16px; font-weight:800; color:#0f172a; border-bottom:1px solid #e2e8f0; padding-bottom:8px; margin-bottom:12px;">
                Drei lokale Erkennungs-Varianten je nach Buchvorlage
              </div>
              <div style="display:flex; flex-direction:column; gap:10px; font-size:13.5px;">
                <div style="background:#eff6ff; border:1.5px solid #2563eb; border-radius:8px; padding:11px 14px;">
                  <strong style="color:#1d4ed8;">1. Höchste Genauigkeit (Standard)</strong><br>
                  <span style="color:#334155;">Empfohlen für MINT-Lehrwerke, mathematische Formeln, mehrspaltige Tabellen und Buchscans</span>
                </div>
                <div style="background:#f8fafc; border:1px solid #cbd5e1; border-radius:8px; padding:11px 14px;">
                  <strong style="color:#0f172a;">2. Kompakte &amp; speicherschonende Erkennung</strong><br>
                  <span style="color:#475569;">Schnelle optische Seitenanalyse bei geringerem Arbeitsspeicherbedarf</span>
                </div>
                <div style="background:#f8fafc; border:1px solid #cbd5e1; border-radius:8px; padding:11px 14px;">
                  <strong style="color:#0f172a;">3. Schnelle Fließtext-Erfassung</strong><br>
                  <span style="color:#475569;">Besonders hohes Tempo für rein digital gesetzte Lesebücher und Textkapitel</span>
                </div>
              </div>
            `,
          });
        }, seg);
      },
    });

    // =========================================================================
    // 07_concept_extraction: Large Intuitive Non-Technical SVG Diagram
    // =========================================================================
    await recordBeat('07_concept_extraction', {
      '0.0': async seg => {
        await page.evaluate(
          ({ s, svgHtml }) => {
            window.focusOnSelectors({
              step: s.step_label,
              caption: s.caption_text,
              zoom: 1.0,
              selectors: [],
              spotlightLabel: '',
              calloutWidth: '1340px',
              calloutPos: { left: '50%', top: '45.5%' },
              mdCallout: svgHtml,
            });
          },
          { s: seg, svgHtml: EXTRACTION_CONCEPT_SVG_HTML }
        );
      },
    });

    // =========================================================================
    // 08a_start_extraction: Highlight "Extraktion starten" (NO zoom!)
    // =========================================================================
    await recordBeat('08a_start_extraction', {
      '0.0': async seg => {
        await page.evaluate(s => {
          // Ensure editors remain completely empty before & during extraction
          const rawTa = document.getElementById('raw-markdown-textarea');
          const stdTa = document.getElementById('standardised-markdown-textarea');
          if (rawTa) rawTa.value = '';
          if (stdTa) stdTa.value = '';

          window.focusOnSelectors({
            step: s.step_label,
            caption: s.caption_text,
            zoom: 1.0,
            selectors: ['#process-btn'],
            pad: 6,
            spotlightLabel: 'Verarbeitung starten',
          });
        }, seg);
      },
    });

    // =========================================================================
    // 08b_extraction_running: Clean progress bar, EMPTY editors, NO clutter!
    // =========================================================================
    await recordBeat('08b_extraction_running', {
      '0.0': async seg => {
        await page.evaluate(s => {
          // Keep Prozess-Verwaltung & Live-Protokoll strictly collapsed/clean
          const tasksContainer = document.getElementById('tasks-manager-container');
          const logsContainer = document.getElementById('logs-console-container');
          if (tasksContainer) tasksContainer.classList.add('hidden');
          if (logsContainer) logsContainer.classList.add('hidden');

          // Ensure both Markdown editors stay completely empty (no premature mock text!)
          const rawTa = document.getElementById('raw-markdown-textarea');
          const stdTa = document.getElementById('standardised-markdown-textarea');
          if (rawTa) rawTa.value = '';
          if (stdTa) stdTa.value = '';

          const prog = document.getElementById('pipeline-progress-container');
          if (prog) {
            prog.classList.remove('hidden');
            document.getElementById('pipeline-progress-phase').textContent =
              'Analysiere Seitenlayout, Formeln und Abbildungen (Buchseite 501)...';
            document.getElementById('pipeline-progress-pages').textContent = '1 / 2 Seiten';
            document.getElementById('pipeline-progress-bar').style.width = '38%';
            document.getElementById('pipeline-progress-percent').textContent = '38%';
          }

          window.focusOnSelectors({
            step: s.step_label,
            caption: s.caption_text,
            zoom: 1.0,
            selectors: ['#pipeline-progress-container'],
            pad: 4,
            spotlightLabel: 'Kompakte Fortschrittsanzeige während der lokalen Verarbeitung',
          });
        }, seg);
      },
      [String((manifest[byId['08b_extraction_running']].duration_sec * 0.52).toFixed(2))]:
        async () => {
          await page.evaluate(() => {
            document.getElementById('pipeline-progress-phase').textContent =
              'Wende FIBS-Übertragungsregeln auf Buchseiten 501–502 an (Gemma 4)...';
            document.getElementById('pipeline-progress-pages').textContent = '2 / 2 Seiten';
            document.getElementById('pipeline-progress-bar').style.width = '82%';
            document.getElementById('pipeline-progress-percent').textContent = '82%';
          });
        },
    });

    // =========================================================================
    // 09_bbox_grounding: Real Page 501 Image + Pixel-Accurate Layout-Boxen
    // =========================================================================
    await recordBeat('09_bbox_grounding', {
      '0.0': async seg => {
        await page.evaluate(
          async ({ imgUrl, rawMd, stdMd, s }) => {
            const prog = document.getElementById('pipeline-progress-container');
            if (prog) prog.classList.add('hidden');

            // Populate real extracted & FIBS-standardised Markdown now that analysis finished
            const rawTa = document.getElementById('raw-markdown-textarea');
            const stdTa = document.getElementById('standardised-markdown-textarea');
            rawTa.value = rawMd;
            rawTa.dispatchEvent(new Event('input', { bubbles: true }));
            stdTa.value = stdMd;
            stdTa.dispatchEvent(new Event('input', { bubbles: true }));

            // Enable export button, keep secondary download actions hidden until 14b!
            const dlBtn = document.getElementById('download-docx-btn');
            if (dlBtn) {
              dlBtn.disabled = false;
              dlBtn.className =
                'w-full bg-indigo-600 hover:bg-indigo-500 text-white font-semibold py-3 px-4 rounded-xl cursor-pointer border border-indigo-500 shadow-sm transition-all duration-200 text-xs';
            }
            const dlActions = document.getElementById('download-actions');
            if (dlActions) dlActions.classList.add('hidden');

            // Show Original PDF (with Layout-Boxen) + E-Buch Markdown
            const pdfPanel = document.getElementById('panel-pdf-container');
            const rawPanel = document.getElementById('panel-raw-container');
            const stdPanel = document.getElementById('panel-standardised-container');
            if (pdfPanel) pdfPanel.classList.remove('hidden');
            if (rawPanel) rawPanel.classList.add('hidden');
            if (stdPanel) stdPanel.classList.remove('hidden');

            const pdfFrame = document.getElementById('pdf-viewer-frame');
            const bboxViewer = document.getElementById('pdf-bbox-viewer');
            if (pdfFrame) pdfFrame.classList.add('hidden');
            if (bboxViewer) bboxViewer.classList.remove('hidden');

            const bboxBtn = document.getElementById('btn-toggle-bbox-overlay');
            if (bboxBtn) {
              bboxBtn.setAttribute('aria-pressed', 'true');
              bboxBtn.className =
                'px-2 py-0.5 rounded text-[10px] font-semibold bg-indigo-600 text-white border border-indigo-500 transition-colors flex items-center space-x-1 flex-shrink-0';
            }

            const indicator = document.getElementById('bbox-page-indicator');
            if (indicator) indicator.textContent = 'Buchseite 501 (1 / 2)';

            const img = document.getElementById('bbox-page-img');
            if (img) {
              img.style.width = '555px';
              img.style.height = 'auto';
              img.src = imgUrl;
              try {
                await img.decode();
              } catch {}
            }

            const chips = document.getElementById('bbox-filter-chips');
            if (chips) {
              chips.innerHTML = `
                <button type="button" class="bbox-filter-chip" aria-pressed="true"><span>Alle</span><span class="font-mono tabular-nums text-[9px] opacity-80">7</span></button>
                <button type="button" class="bbox-filter-chip" style="--bbox-color:#64748b"><span class="bbox-filter-chip-dot"></span><span>Kopfzeile</span></button>
                <button type="button" class="bbox-filter-chip" style="--bbox-color:#d97706"><span class="bbox-filter-chip-dot"></span><span>Überschrift</span></button>
                <button type="button" class="bbox-filter-chip" style="--bbox-color:#2563eb"><span class="bbox-filter-chip-dot"></span><span>Text</span></button>
                <button type="button" class="bbox-filter-chip" style="--bbox-color:#0891b2"><span class="bbox-filter-chip-dot"></span><span>Formel</span></button>
                <button type="button" class="bbox-filter-chip" style="--bbox-color:#0d9488"><span class="bbox-filter-chip-dot"></span><span>Bild</span></button>
              `;
            }

            const layer = document.getElementById('bbox-overlay-layer');
            if (layer) {
              const boxes = [
                { x1: 162, y1: 13, x2: 910, y2: 33, tag: 'Kopfzeile (ausgeblendet)', color: '#64748b' },
                { x1: 162, y1: 50, x2: 910, y2: 242, tag: 'Fließtext', color: '#2563eb' },
                { x1: 162, y1: 248, x2: 422, y2: 296, tag: 'Liste', color: '#7c3aed' },
                { x1: 162, y1: 311, x2: 458, y2: 335, tag: 'Überschrift', color: '#d97706' },
                { x1: 162, y1: 340, x2: 910, y2: 413, tag: 'Fließtext', color: '#2563eb' },
                { x1: 432, y1: 390, x2: 568, y2: 411, tag: 'Formel', color: '#0891b2' },
                { x1: 194, y1: 422, x2: 880, y2: 626, tag: 'Abbildung 11.51', color: '#0d9488' },
                { x1: 162, y1: 635, x2: 910, y2: 942, tag: 'Fließtext', color: '#2563eb' },
              ];
              layer.innerHTML = boxes
                .map(
                  b => `
                <div class="bbox-rect" style="left:${b.x1 / 10}%; top:${b.y1 / 10}%; width:${
                    (b.x2 - b.x1) / 10
                  }%; height:${(b.y2 - b.y1) / 10}%; --bbox-color:${b.color};">
                  <span class="bbox-tag">${b.tag}</span>
                </div>
              `
                )
                .join('');
            }

            window.focusOnSelectors({
              step: s.step_label,
              caption: s.caption_text,
              zoom: 1.0,
              selectors: ['#panel-pdf-container'],
              pad: 6,
              spotlightLabel: 'Layout-Boxen auf Buchseite 501: Kopfzeile, Überschrift, Text, Formel & Abbildung',
            });
          },
          { imgUrl: page501DataUrl, rawMd: rawOptikMd, stdMd: fibsOptikMd, s: seg }
        );
      },
    });

    // =========================================================================
    // 10_main_editors_comparison: FULL-HEIGHT highlight around both editors!
    // =========================================================================
    await recordBeat('10_main_editors_comparison', {
      '0.0': async seg => {
        await page.evaluate(s => {
          const pdfPanel = document.getElementById('panel-pdf-container');
          const rawPanel = document.getElementById('panel-raw-container');
          const stdPanel = document.getElementById('panel-standardised-container');
          if (pdfPanel) pdfPanel.classList.add('hidden');
          if (rawPanel) rawPanel.classList.remove('hidden');
          if (stdPanel) stdPanel.classList.remove('hidden');

          const togglePdfBtn = document.getElementById('toggle-pane-pdf');
          const toggleRawBtn = document.getElementById('toggle-pane-raw');
          if (togglePdfBtn) {
            togglePdfBtn.className =
              'px-2.5 py-0.5 rounded-md font-semibold text-slate-400 hover:text-white transition-all duration-150 h-full';
          }
          if (toggleRawBtn) {
            toggleRawBtn.className =
              'px-2.5 py-0.5 rounded-md font-semibold text-white bg-indigo-650 border border-indigo-550 transition-all duration-150 h-full';
          }

          document.getElementById('raw-markdown-textarea').scrollTop = 0;
          document.getElementById('standardised-markdown-textarea').scrollTop = 0;

          window.focusOnSelectors({
            step: s.step_label,
            caption: s.caption_text,
            zoom: 1.0,
            selectors: ['#panel-raw-container', '#panel-standardised-container'],
            pad: 5,
            spotlightLabel: 'Hauptbereich: 1. Extrahiertes Markdown (links) & 2. E-Buch-Standard-Markdown (rechts)',
          });
        }, seg);
      },
    });

    // =========================================================================
    // 11_fibs_concepts_content: FIBS Rules on ((501)) & ((502)) + Visual Card
    // =========================================================================
    await recordBeat('11_fibs_concepts_content', {
      '0.0': async seg => {
        await page.evaluate(s => {
          document.getElementById('standardised-markdown-textarea').scrollTop = 0;
          window.focusOnSelectors({
            step: s.step_label,
            caption: s.caption_text,
            zoom: 1.0,
            selectors: ['#panel-standardised-container'],
            pad: 5,
            spotlightLabel: 'Angewandte FIBS-Übertragungsregeln (Buchseiten 501–502)',
            calloutWidth: '670px',
            calloutPos: { left: '29%', top: '46%' },
            mdCallout: `
              <div style="font-size:16px; font-weight:800; color:#0f172a; border-bottom:1px solid #e2e8f0; padding-bottom:8px; margin-bottom:12px;">
                Wichtige FIBS-Auszeichnungen im Kapitel (Stand 09/2025)
              </div>
              <div style="display:flex; flex-direction:column; gap:9px; font-size:13px;">
                <div style="background:#f8fafc; border:1px solid #cbd5e1; border-left:3px solid #dc2626; border-radius:6px; padding:9px 12px;">
                  <strong style="font-family:ui-monospace, monospace; color:#b91c1c;">((501)) / ((502))</strong> — Originale Buchseitenzahlen in doppelten runden Klammern
                </div>
                <div style="background:#f8fafc; border:1px solid #cbd5e1; border-left:3px solid #2563eb; border-radius:6px; padding:9px 12px;">
                  <strong style="font-family:ui-monospace, monospace; color:#1d4ed8;"># / ## / ### / ####</strong> — Lückenlose Überschriften-Hierarchie inkl. Bildtitel
                </div>
                <div style="background:#f8fafc; border:1px solid #cbd5e1; border-left:3px solid #0d9488; border-radius:6px; padding:9px 12px;">
                  <strong style="font-family:ui-monospace, monospace; color:#0f766e;">&lt;Bild&gt; Zeichnung: … &lt;/Bild&gt;</strong> — Kompakte, sachliche Beschreibung ohne Deutung
                </div>
                <div style="background:#f8fafc; border:1px solid #cbd5e1; border-left:3px solid #d97706; border-radius:6px; padding:9px 12px;">
                  <strong style="font-family:ui-monospace, monospace; color:#b45309;">&lt;Tabelle&gt; … &lt;/Tabelle&gt; &amp; LaTeX</strong> — Datentabelle zum Brechungsindex &amp; Formeln
                </div>
              </div>
            `,
          });
        }, seg);
      },
      [String((manifest[byId['11_fibs_concepts_content']].duration_sec * 0.56).toFixed(2))]:
        async () => {
          await page.evaluate(() => {
            document.getElementById('standardised-markdown-textarea').scrollTop = 520;
            document.getElementById('raw-markdown-textarea').scrollTop = 520;
          });
        },
    });

    // =========================================================================
    // 12_diff_view: Color-coded Diff View ("Differenzen")
    // =========================================================================
    await recordBeat('12_diff_view', {
      '0.0': async seg => {
        await page.evaluate(s => {
          document.getElementById('btn-diff-standardised').click();
          const diffEl = document.getElementById('diff-view-content');
          if (diffEl) diffEl.scrollTop = 0;

          window.focusOnSelectors({
            step: s.step_label,
            caption: s.caption_text,
            zoom: 1.0,
            selectors: ['#panel-standardised-container'],
            pad: 5,
            spotlightLabel: 'Differenz-Ansicht: Farblich markierte Tags, Formatierungen & Textanpassungen',
          });
        }, seg);
      },
      [String((manifest[byId['12_diff_view']].duration_sec * 0.52).toFixed(2))]: async () => {
        await page.evaluate(() => {
          const diffEl = document.getElementById('diff-view-content');
          if (diffEl) diffEl.scrollTop = 360;
        });
      },
    });

    // =========================================================================
    // 13_ai_correction_bar: ZOOMED IN (1.45x) on #optimization-container!
    // =========================================================================
    await recordBeat('13_ai_correction_bar', {
      '0.0': async seg => {
        await page.evaluate(s => {
          document.getElementById('btn-edit-standardised').click();
          const stdTa = document.getElementById('standardised-markdown-textarea');
          if (stdTa) stdTa.scrollTop = 210;

          const optContainer = document.getElementById('optimization-container');
          const optInput = document.getElementById('optimization-prompt-input');
          const optBtn = document.getElementById('btn-optimize');
          if (optContainer) optContainer.classList.remove('hidden');
          if (optInput && optBtn) {
            optInput.disabled = false;
            optBtn.disabled = false;
            optBtn.style.cssText =
              'background-color:#2563eb !important; color:#ffffff !important; border-color:#1d4ed8 !important;';
            optInput.value =
              'Formuliere die Bildbeschreibung zu Abbildung 11.51 noch kompakter in zwei kurzen Sätzen.';
          }

          window.focusOnSelectors({
            step: s.step_label,
            caption: s.caption_text,
            zoom: 1.45,
            zoomTargetY: 740,
            allowBottomOverscroll: true,
            selectors: ['#optimization-container'],
            pad: 8,
            spotlightLabel: 'KI-Nachbearbeitung: Korrekturanweisung direkt im Editor ausführen',
          });
        }, seg);
      },
    });

    // =========================================================================
    // 14a_export_options: ONLY Profile & Template highlighted (NO download yet!)
    // =========================================================================
    await recordBeat('14a_export_options', {
      '0.0': async seg => {
        await page.evaluate(s => {
          // Ensure secondary downloads remain hidden during 14a!
          const dlActions = document.getElementById('download-actions');
          if (dlActions) dlActions.classList.add('hidden');
          const bottomWrap = document.querySelector('#right-sidebar > div:last-child');
          if (bottomWrap) bottomWrap.style.paddingBottom = '16px';

          window.focusOnSelectors({
            step: s.step_label,
            caption: s.caption_text,
            zoom: 1.0,
            selectors: [
              'label[for="profile-select"]',
              '#profile-select',
              'label[for="template-mode-select"]',
              '#template-mode-select',
            ],
            pad: 8,
            spotlightLabel: 'Export-Einstellungen: Zielgruppen-Profil & offizielle FIBS-Vorlage',
          });
        }, seg);
      },
    });

    // =========================================================================
    // 14b_export_download: NOW highlight Word export & reveal download buttons!
    // =========================================================================
    await recordBeat('14b_export_download', {
      '0.0': async seg => {
        await page.evaluate(s => {
          const dlActions = document.getElementById('download-actions');
          if (dlActions) dlActions.classList.remove('hidden');
          // Lift bottom action stack cleanly above the full-width lower-third
          const bottomWrap = document.querySelector('#right-sidebar > div:last-child');
          if (bottomWrap) bottomWrap.style.paddingBottom = '136px';

          window.focusOnSelectors({
            step: s.step_label,
            caption: s.caption_text,
            zoom: 1.0,
            selectors: ['#download-actions', '#download-docx-btn'],
            pad: 8,
            spotlightLabel: 'Ausgabe starten: Word-Datei (.docx) & Markdown-Dateien herunterladen',
          });
        }, seg);
      },
    });

    // =========================================================================
    // 15a_gdocs_page1 & 15b_gdocs_page2: Real Google-Docs-rendered FIBS .dotx!
    // =========================================================================
    await page.goto(
      pathToFileURL(path.join(ASSETS_DIR, 'docx_fullscreen_viewer.html')).href,
      { waitUntil: 'load' }
    );
    await injectVideoHud(page);

    await recordBeat('15a_gdocs_page1', {
      '0.0': async seg => {
        await page.evaluate(s => {
          window.scrollTo({ top: 0, behavior: 'instant' });
          window.focusOnSelectors({
            step: s.step_label,
            caption: s.caption_text,
            zoom: 1.0,
            selectors: ['#page-1', '#page-2'],
            pad: 8,
            spotlightLabel:
              'Echte FIBS-Formatvorlagen (Google Docs): Titelblock, ((501)), Überschrift 1–4 & <Bild>',
          });
        }, seg);
      },
    });

    await recordBeat('15b_gdocs_page2', {
      '0.0': async seg => {
        await page.evaluate(s => {
          const sp2 = document.getElementById('spread-2');
          if (sp2) {
            const y = sp2.getBoundingClientRect().top + window.scrollY - 76;
            window.scrollTo({ top: y, behavior: 'instant' });
          }
          window.focusOnSelectors({
            step: s.step_label,
            caption: s.caption_text,
            zoom: 1.0,
            selectors: ['#page-4', '#page-5'],
            pad: 8,
            spotlightLabel:
              'Seitenumbruch vor ((502)) • Formel (11.1) & gerahmte FIBS-Datentabelle',
          });
        }, seg);
      },
    });

    // =========================================================================
    // 16_benchmark_center: Compare against human-corrected Word + Auto Feedback
    // =========================================================================
    await page.goto('http://localhost:3000', { waitUntil: 'networkidle' });
    await injectVideoHud(page);

    await recordBeat('16_benchmark_center', {
      '0.0': async seg => {
        await page.selectOption('#main-mode-select', 'benchmark');
        await page.evaluate(() => {
          const sel = document.getElementById('main-mode-select');
          if (sel) sel.dispatchEvent(new Event('change', { bubbles: true }));
        });
        await page.waitForTimeout(350);
        await page.evaluate(s => {
          // Populate realistic completed comparison against a human-reviewed Word file
          const taskSel = document.getElementById('bench-source-task-select');
          if (taskSel) {
            taskSel.innerHTML =
              '<option value="optik-501" selected>Kapitel 11.6 – Licht in unterschiedlichen Medien (S. 501–502)</option>';
          }
          const srcFn = document.getElementById('bench-source-filename');
          const srcBadge = document.getElementById('bench-source-badge');
          if (srcFn) srcFn.textContent = 'schulbuch_kapitel.pdf (Buchseiten 501–502)';
          if (srcBadge) srcBadge.classList.remove('hidden');

          const gtFn = document.getElementById('bench-gt-filename');
          const gtBadge = document.getElementById('bench-gt-badge');
          if (gtFn) gtFn.textContent = 'kapitel_11_6_fachkraft_geprueft.docx';
          if (gtBadge) gtBadge.classList.remove('hidden');

          const hint = document.getElementById('bench-existing-transfer-hint');
          const engList = document.getElementById('bench-engines-container');
          if (hint) hint.classList.remove('hidden');
          if (engList) engList.classList.add('hidden');

          const resSec = document.getElementById('bench-results-section');
          if (resSec) resSec.classList.remove('hidden');

          const cards = document.getElementById('bench-ranking-cards');
          if (cards) {
            cards.innerHTML = `
              <div style="background:#eff6ff; border:1.5px solid #2563eb; border-radius:12px; padding:14px 16px;">
                <div style="font-size:11px; font-weight:700; color:#1e40af; text-transform:uppercase;">Gesamt-Übereinstimmung</div>
                <div style="font-size:26px; font-weight:800; color:#1d4ed8; font-family:ui-monospace, monospace; margin:4px 0;">96,8 %</div>
                <div style="font-size:11.5px; color:#334155;">Abgleich gegen geprüfte Word-Fassung</div>
              </div>
              <div style="background:#f8fafc; border:1px solid #cbd5e1; border-radius:12px; padding:14px 16px;">
                <div style="font-size:11px; font-weight:700; color:#475569; text-transform:uppercase;">Überschriften &amp; Seitenmarker</div>
                <div style="font-size:26px; font-weight:800; color:#059669; font-family:ui-monospace, monospace; margin:4px 0;">100,0 %</div>
                <div style="font-size:11.5px; color:#475569;">Alle Ebenen # bis #### &amp; ((501))–((502)) exakt</div>
              </div>
              <div style="background:#f8fafc; border:1px solid #cbd5e1; border-radius:12px; padding:14px 16px;">
                <div style="font-size:11px; font-weight:700; color:#475569; text-transform:uppercase;">Formeln &amp; Datentabelle</div>
                <div style="font-size:26px; font-weight:800; color:#0d9488; font-family:ui-monospace, monospace; margin:4px 0;">98,4 %</div>
                <div style="font-size:11.5px; color:#475569;">Brechzahl-Tabelle (8 Zeilen) vollständig</div>
              </div>
              <div style="background:#fffbeb; border:1px solid #fcd34d; border-radius:12px; padding:14px 16px;">
                <div style="font-size:11px; font-weight:700; color:#92400e; text-transform:uppercase;">Automatisches Regel-Feedback</div>
                <div style="font-size:26px; font-weight:800; color:#b45309; font-family:ui-monospace, monospace; margin:4px 0;">2 Hinweise</div>
                <div style="font-size:11.5px; color:#78350f;">Vorschläge zur Verbesserung der Zusatzregeln</div>
              </div>
            `;
          }

          const matrixTbody = document.getElementById('bench-matrix-tbody');
          if (matrixTbody) {
            matrixTbody.innerHTML = `
              <tr style="color:#0f172a; background:#ffffff;">
                <td class="py-2.5 px-3 font-bold text-blue-700">#1</td>
                <td class="py-2.5 px-3 font-semibold">Aktuelle Übertragung (S. 501–502)</td>
                <td class="py-2.5 px-3 font-mono text-[11px]">Lokal / Open</td>
                <td class="py-2.5 px-3 font-mono font-bold text-blue-700">96,8 %</td>
                <td class="py-2.5 px-3 font-mono">100,0 %</td>
                <td class="py-2.5 px-3 font-mono">97,5 %</td>
                <td class="py-2.5 px-3 font-mono">100,0 %</td>
                <td class="py-2.5 px-3 font-mono">98,2 %</td>
                <td class="py-2.5 px-3 font-mono text-emerald-700 font-bold">100 / 100</td>
                <td class="py-2.5 px-3 font-mono">95,0 %</td>
                <td class="py-2.5 px-3 font-mono">14,2 s</td>
              </tr>
            `;
          }

          window.focusOnSelectors({
            step: s.step_label,
            caption: s.caption_text,
            zoom: 1.0,
            selectors: [
              '#main-benchmark-view > div:nth-child(2)',
              '#bench-ranking-cards',
            ],
            pad: 8,
            spotlightLabel:
              'Benchmark & Evaluierung: Abgleich mit geprüfter Word-Datei & automatisches Regel-Feedback',
          });
        }, seg);
      },
    });

    // =========================================================================
    // 17a_feedback_input: Concrete Optics Feedback + PDF Marker on Page 501
    // =========================================================================
    await recordBeat('17a_feedback_input', {
      '0.0': async seg => {
        await page.selectOption('#main-mode-select', 'feedback');
        await page.evaluate(() => {
          const sel = document.getElementById('main-mode-select');
          if (sel) sel.dispatchEvent(new Event('change', { bubbles: true }));
        });
        // Wait for feedback.ts async refreshJobs() / refreshReports() to settle
        await page.waitForTimeout(450);

        await page.evaluate(
          async ({ imgUrl, s }) => {
            const jobSel = document.getElementById('fb-job-select');
            if (jobSel) {
              jobSel.innerHTML =
                '<option value="optik-501" selected>Kapitel 11.6 – Licht in unterschiedlichen Medien (Buchseiten 501–502)</option>';
            }
            const jobArt = document.getElementById('fb-job-artifacts');
            if (jobArt) {
              jobArt.classList.remove('hidden');
              jobArt.innerHTML = `
                <span style="background:#eff6ff; color:#1d4ed8; border:1px solid #bfdbfe; padding:2px 8px; border-radius:4px; font-weight:600;">✓ Quell-PDF (4 S.)</span>
                <span style="background:#ecfdf5; color:#047857; border:1px solid #a7f3d0; padding:2px 8px; border-radius:4px; font-weight:600;">✓ Automatische Übertragung</span>
              `;
            }

            const revFn = document.getElementById('fb-revised-filename');
            const revBadge = document.getElementById('fb-revised-badge');
            if (revFn) revFn.textContent = 'kapitel_11_6_korrigiert.docx';
            if (revBadge) revBadge.classList.remove('hidden');

            const fbText = document.getElementById('fb-feedback-text');
            if (fbText) {
              fbText.value =
                'Englische Fachbegriffe in Klammern wie (engl. Fermat’s principle) wurden kursiv mit Prozentzeichen gesetzt, sollen nach Buchkonferenz aber ohne Prozentzeichen übernommen werden. Zudem bitte Gleichungsnummern wie (11.1) hinter abgesetzten Formeln immer beibehalten.';
            }

            const analyzeBtn = document.getElementById('fb-analyze-btn');
            if (analyzeBtn) analyzeBtn.disabled = false;

            const addRegBtn = document.getElementById('fb-add-region-btn');
            if (addRegBtn) {
              addRegBtn.disabled = false;
              addRegBtn.style.cssText =
                'background-color:#fff1f2 !important; color:#be123c !important; border-color:#fda4af !important;';
            }

            // Populate right-hand PDF region marker on page 501!
            const placeholder = document.getElementById('fb-page-placeholder');
            const wrap = document.getElementById('fb-page-canvas-wrap');
            const pageImg = document.getElementById('fb-page-image');
            const pageSelect = document.getElementById('fb-page-select');
            const selRect = document.getElementById('fb-selection-rect');

            if (placeholder) placeholder.classList.add('hidden');
            if (wrap) wrap.classList.remove('hidden');
            if (pageSelect) {
              pageSelect.disabled = false;
              pageSelect.innerHTML = '<option selected>Buchseite 501 (PDF-Seite 2 / 4)</option>';
            }
            if (pageImg) {
              pageImg.style.height = '510px';
              pageImg.style.width = 'auto';
              pageImg.src = imgUrl;
              try {
                await pageImg.decode();
              } catch {}
            }
            if (selRect) {
              selRect.classList.remove('hidden');
              selRect.style.left = '15.8%';
              selRect.style.top = '78.6%';
              selRect.style.width = '75.5%';
              selRect.style.height = '6.2%';
            }

            const regNote = document.getElementById('fb-region-note');
            if (regNote) {
              regNote.value = 'Englischer Klammerzusatz ohne Kursiv-Prozentzeichen';
            }
            const regCount = document.getElementById('fb-region-count');
            if (regCount) regCount.textContent = '1';

            const regList = document.getElementById('fb-regions-list');
            if (regList) {
              regList.innerHTML = `
                <li style="background:#fff1f2; border:1px solid #fecdd3; border-radius:8px; padding:8px 10px; font-size:11px; color:#881337;">
                  <div style="font-weight:700; margin-bottom:2px;">📍 Buchseite 501 • Absatz 5</div>
                  <div style="color:#9f1239;">„…Fermatsches Prinzip (engl. Fermat’s principle)…“ — ohne %-Zeichen übernehmen</div>
                </li>
              `;
            }

            const resSec = document.getElementById('fb-result-section');
            if (resSec) resSec.classList.add('hidden');

            const fbView = document.getElementById('main-feedback-view');
            if (fbView) {
              fbView.style.paddingBottom = '24px';
              fbView.scrollTop = 0;
            }

            window.focusOnSelectors({
              step: s.step_label,
              caption: s.caption_text,
              zoom: 1.0,
              selectors: ['#main-feedback-view > div:nth-child(2)'],
              pad: 6,
              spotlightLabel:
                'Feedback-Eingabe: Korrigierte Word-Datei, Rückmeldung & markierte Stelle auf Buchseite 501',
            });
          },
          { imgUrl: page501DataUrl, s: seg }
        );
      },
    });

    // =========================================================================
    // 17b_feedback_report: Local Gemma-4 Pattern & Rule Suggestion Report
    // =========================================================================
    await recordBeat('17b_feedback_report', {
      '0.0': async seg => {
        await page.evaluate(s => {
          const resSec = document.getElementById('fb-result-section');
          const repContent = document.getElementById('fb-report-content');
          if (resSec && repContent) {
            resSec.classList.remove('hidden');
            repContent.innerHTML = `
              <div style="display:flex; align-items:center; justify-content:space-between; background:#eff6ff; border:1px solid #bfdbfe; border-radius:8px; padding:10px 14px; margin-bottom:14px; color:#1e3a8a; font-size:12.5px;">
                <span><strong>Auftrag:</strong> Kapitel 11.6 – Licht in unterschiedlichen Medien (S. 501–502)</span>
                <span style="font-family:ui-monospace, monospace; font-weight:700;">2 systematische Korrekturmuster erkannt • Urheberrechtsfilter aktiv</span>
              </div>

              <div style="display:grid; grid-template-columns:1fr 1fr; gap:14px;">
                <div style="background:#ffffff; border:1px solid #cbd5e1; border-left:4px solid #2563eb; border-radius:8px; padding:14px 16px;">
                  <div style="font-size:13.5px; font-weight:800; color:#0f172a; margin-bottom:6px;">
                    Muster 1: Fremdsprachige Fachbegriffe in Klammern nicht kursiv setzen
                  </div>
                  <div style="font-size:12.5px; color:#334155; line-height:1.5; margin-bottom:8px;">
                    <strong>Beobachtete Abweichung (S. 501 &amp; 502):</strong> Klammerzusätze nach <code>engl.</code> wurden automatisch in <code>%...%</code> eingeschlossen, in der geprüften Word-Fassung jedoch ohne Prozentzeichen belassen (3 Vorkommen).
                  </div>
                  <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:8px 10px; font-size:12px; color:#1d4ed8; font-weight:600;">
                    ✓ Vorgeschlagene Zusatzregel: „Englische Übersetzungen in runden Klammern nach ‚engl.‘ werden als normaler Fließtext ohne %-Markierung übertragen.“
                  </div>
                </div>

                <div style="background:#ffffff; border:1px solid #cbd5e1; border-left:4px solid #0d9488; border-radius:8px; padding:14px 16px;">
                  <div style="font-size:13.5px; font-weight:800; color:#0f172a; margin-bottom:6px;">
                    Muster 2: Rechtsbündige Gleichungsnummern hinter Formeln erhalten
                  </div>
                  <div style="font-size:12.5px; color:#334155; line-height:1.5; margin-bottom:8px;">
                    <strong>Beobachtete Abweichung (S. 502):</strong> Bei abgesetzten Gleichungen wird die Nummerierung am Zeilenende wie <code>(11.1)</code> für spätere Verweise im Kapiteltext benötigt.
                  </div>
                  <div style="background:#f0fdfa; border:1px solid #99f6e4; border-radius:6px; padding:8px 10px; font-size:12px; color:#0f766e; font-weight:600;">
                    ✓ Vorgeschlagene Regel-Ergänzung: „Gleichungsnummern in runden Klammern direkt hinter der abgesetzten Formel in derselben Zeile bewahren.“
                  </div>
                </div>
              </div>
            `;
          }

          const fbView = document.getElementById('main-feedback-view');
          if (fbView && resSec) {
            // Extra bottom padding so #fb-result-section scrolls cleanly above #video-lower-third
            fbView.style.paddingBottom = '156px';
            fbView.scrollTop = fbView.scrollHeight;
          }

          window.focusOnSelectors({
            step: s.step_label,
            caption: s.caption_text,
            zoom: 1.0,
            selectors: ['#fb-result-section'],
            pad: 8,
            spotlightLabel:
              'Lokale Gemma-4-Fehleranalyse: Gebündelte Fehlermuster & konkrete Regel-Vorschläge',
          });
        }, seg);
      },
    });

    await browser.close();

    console.log(
      `[3/4] Concatenating all ${manifest.length} synchronized beats into final 1080p MP4...`
    );
    const concatListPath = path.join(SCENES_DIR, 'concat.txt');
    const concatLines = manifest
      .map(seg => `file '${path.join(SCENES_DIR, `${seg.id}.mp4`)}'`)
      .join('\n');
    fs.writeFileSync(concatListPath, concatLines, 'utf-8');

    const finalArtifactVideo = path.join(ARTIFACT_DIR, 'ebuch_konverter_erklaervideo_de.mp4');
    const finalRepoVideo = path.join(PROJECT_DIR, 'ebuch_konverter_erklaervideo_de.mp4');

    execSync(
      `"${FFMPEG_BIN}" -y -f concat -safe 0 -i "${concatListPath}" -c:v copy -c:a aac -b:a 192k -ar 24000 "${finalArtifactVideo}"`,
      { stdio: 'inherit' }
    );
    fs.copyFileSync(finalArtifactVideo, finalRepoVideo);
    console.log(
      `[4/4] Done! Video written to:\n  - ${finalArtifactVideo}\n  - ${finalRepoVideo}`
    );
  } finally {
    backendProc.kill('SIGTERM');
    frontendProc.kill('SIGTERM');
  }
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
