import { chromium } from 'playwright';
import { spawn, execSync } from 'child_process';
import fs from 'fs';
import path from 'path';
import { fileURLToPath, pathToFileURL } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_DIR = path.resolve(__dirname, '..');
const ASSETS_DIR = process.env.EBUCH_VIDEO_ASSETS_DIR || path.join(PROJECT_DIR, 'assets', 'video_capture');
const AUDIO_DIR = path.join(ASSETS_DIR, 'audio');
const FRAMES_DIR = path.join(ASSETS_DIR, 'frames');
const SCENES_DIR = path.join(ASSETS_DIR, 'scenes');
const ARTIFACT_DIR = process.env.EBUCH_VIDEO_ARTIFACT_DIR || path.join(ASSETS_DIR, 'artifacts');

fs.rmSync(FRAMES_DIR, { recursive: true, force: true });
fs.rmSync(SCENES_DIR, { recursive: true, force: true });
fs.mkdirSync(FRAMES_DIR, { recursive: true });
fs.mkdirSync(SCENES_DIR, { recursive: true });
fs.mkdirSync(ARTIFACT_DIR, { recursive: true });

const manifest = JSON.parse(fs.readFileSync(path.join(AUDIO_DIR, 'manifest.json'), 'utf-8'));
const goldenFibsMd = `((45))

# Kapitel 4: Wellenoptik und Interferenz

## 4.1 Das Doppelspaltexperiment

In diesem Kapitel untersuchen wir die Beugung von Licht an engen Spalten sowie die resultierenden Interferenzmuster auf einem Beobachtungsschirm. Trifft kohärentes, monochromatisches Licht der Wellenlänge $\\lambda$ auf einen Doppelspalt mit dem Spaltabstand $d$, so überlagern sich die Elementarwellen hinter den Spalten{1}.

#### Abb. 4.1: Schematischer Versuchsaufbau zum Doppelspaltexperiment mit kohärenter Lichtquelle

<Bild> Schematische Darstellung:
Beschreibung: Links sendet eine Laserquelle monochromatisches Licht aus, das auf eine Doppelspaltblende mit Spaltabstand $d$ trifft. Rechts befindet sich ein Beobachtungsschirm im Abstand $L$, auf dem helle Interferenzmaxima und dunkle Minima als Streifenmuster sichtbar sind.
</Bild>

#### Merksatz:

<Rahmen>
Konstruktive Interferenz (Maxima) tritt auf, wenn der Gangunterschied $\\Delta s$ ein ganzzahliges Vielfaches der Wellenlänge $\\lambda$ ist: $\\Delta s = k \\cdot \\lambda$.
</Rahmen>

### Übungsaufgaben zur Interferenz

##### Aufgabe 1 [leicht]
Berechnen Sie den Winkel des ersten Maximums für rotes Laserlicht ($\\lambda = 633 \\text{ nm}$) bei einem Spaltabstand von $d = 0{,}25 \\text{ mm}$.

##### Aufgabe 2 [mittel]
Erläutern Sie, wie sich das Interferenzbild auf dem Schirm verändert, wenn der Abstand zwischen Doppelspalt und Schirm verdoppelt wird.

##### Aufgabe 3 [schwer]
Leiten Sie die Näherungsformel für kleine Winkel her{2} und prüfen Sie deren Gültigkeit für das dritte Maximum.

((46))

### Vergleich: Korpuskel- vs. Wellenmodell

<Tabelle>

| Modell | Annahme | Erklärte Phänomene |
| :--- | :--- | :--- |
| Korpuskelmodell | Licht besteht aus diskreten Teilchen (Photonen). | Photoelektrischer Effekt ($E = h \\cdot f$), Compton-Streuung |
| Wellenmodell | Licht breitet sich als elektromagnetische Transversalwelle aus. | Beugung, Interferenz am Doppelspalt, Polarisation |

</Tabelle>

#### Mathematische Formeln im Fließtext:

Die Energie-Masse-Äquivalenz lautet $E = mc^2$, die Phasenbeziehung $\\alpha + \\beta = \\gamma$ und für das Intensitätsintegral über den Schirmbereich gilt:

$$\\int_{a}^{b} x^2 \\, dx$$

<Anmerkung> 1 Vgl. Born & Wolf (1999): Principles of Optics, Kapitel 7. </Anmerkung>
<Anmerkung> 2 Für kleine Winkel $\\theta$ im Bogenmaß gilt die Kleinwinkelnäherung $\\sin(\\theta) \\approx \\tan(\\theta) \\approx \\theta$. </Anmerkung>`;

const rawExtractedMd = `Seite 45

# Kapitel 4: Wellenoptik und Interferenz

## 4.1 Das Doppelspaltexperiment

In diesem Kapitel untersuchen wir die Beugung von Licht an engen Spalten sowie die resultierenden Interferenzmuster auf einem Beobachtungsschirm. Trifft kohärentes, monochromatisches Licht der Wellenlänge λ auf einen Doppelspalt mit dem Spaltabstand d, so überlagern sich die Elementarwellen hinter den Spalten¹.

![Abb. 4.1: Schematischer Versuchsaufbau](images/page_1_img_1.png)
Abb. 4.1: Schematischer Versuchsaufbau zum Doppelspaltexperiment mit kohärenter Lichtquelle

Merke: Konstruktive Interferenz (Maxima) tritt auf, wenn der Gangunterschied Δs ein ganzzahliges Vielfaches der Wellenlänge λ ist: Δs = k · λ.

### Übungsaufgaben zur Interferenz

○ Aufgabe 1
Berechnen Sie den Winkel des ersten Maximums für rotes Laserlicht (λ = 633 nm) bei einem Spaltabstand von d = 0,25 mm.

◐ Aufgabe 2
Erläutern Sie, wie sich das Interferenzbild auf dem Schirm verändert, wenn der Abstand zwischen Doppelspalt und Schirm verdoppelt wird.

● Aufgabe 3
Leiten Sie die Näherungsformel für kleine Winkel her² und prüfen Sie deren Gültigkeit für das dritte Maximum.

---
Seite 46

### Vergleich: Korpuskel- vs. Wellenmodell

| Spalte A (Korpuskelmodell) | Spalte B (Wellenmodell) |
|---|---|
| Licht besteht aus diskreten Teilchen (Photonen). | Licht breitet sich als elektromagnetische Welle aus. |
| Erklärt den photoelektrischen Effekt (E = h · f). | Erklärt Beugung und Interferenz am Doppelspalt. |

#### Mathematische Formeln im Fließtext:

Die Energie-Masse-Äquivalenz lautet E = mc², die Phasenbeziehung α + β = γ und für das Intensitätsintegral über den Schirmbereich gilt:

∫_a^b x² dx

---
¹ Vgl. Born & Wolf (1999): Principles of Optics, Kapitel 7.
² Für kleine Winkel θ im Bogenmaß gilt die Kleinwinkelnäherung sin(θ) ≈ tan(θ) ≈ θ.`;

async function waitForUrl(url, timeoutMs = 25000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(url);
      if (res.ok) return true;
    } catch { }
    await new Promise(r => setTimeout(r, 300));
  }
  throw new Error(`Timeout waiting for ${url}`);
}

async function injectVideoHud(page) {
  await page.evaluate(() => {
    if (document.getElementById('video-hud-root')) return;

    const style = document.createElement('style');
    style.textContent = `
      body {
        transform-origin: 0 0 !important;
        transition: none !important;
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
        border: 3.5px solid #4f46e5;
        border-radius: 12px;
        box-shadow: 0 0 0 9999px rgba(15, 23, 42, 0.28), 0 0 28px rgba(79, 70, 229, 0.75), inset 0 0 12px rgba(99, 102, 241, 0.2);
        transition: none !important;
        opacity: 0;
      }
      #video-spotlight-label {
        position: absolute;
        top: -38px;
        left: 0;
        background: linear-gradient(135deg, #4f46e5, #7c3aed);
        color: #ffffff;
        font-size: 13.5px;
        font-weight: 700;
        padding: 5px 14px;
        border-radius: 8px;
        white-space: nowrap;
        box-shadow: 0 6px 18px rgba(79, 70, 229, 0.65);
        border: 1px solid rgba(255,255,255,0.35);
      }
      #video-timelapse-badge {
        position: fixed;
        top: 96px;
        left: 50%;
        transform: translateX(-50%) scale(0.9);
        background: linear-gradient(135deg, rgba(16, 185, 129, 0.96), rgba(5, 150, 105, 0.96));
        color: #ffffff;
        font-size: 16px;
        font-weight: 800;
        padding: 10px 26px;
        border-radius: 999px;
        box-shadow: 0 12px 32px rgba(16, 185, 129, 0.6);
        border: 2px solid rgba(255,255,255,0.45);
        display: flex;
        align-items: center;
        gap: 10px;
        opacity: 0;
        transition: none !important;
        z-index: 1000001;
      }
      #video-lower-third {
        position: fixed;
        bottom: 22px;
        left: 50%;
        transform: translateX(-50%);
        width: 1480px;
        background: rgba(15, 23, 42, 0.96);
        backdrop-filter: blur(14px);
        border: 1px solid rgba(99, 102, 241, 0.5);
        border-radius: 16px;
        padding: 14px 26px;
        box-shadow: 0 16px 40px rgba(0, 0, 0, 0.75);
        display: flex;
        align-items: center;
        gap: 20px;
        z-index: 1000002;
      }
      #video-step-pill {
        background: linear-gradient(135deg, #4f46e5, #9333ea);
        color: #fff;
        font-weight: 800;
        font-size: 13px;
        padding: 6px 14px;
        border-radius: 10px;
        white-space: nowrap;
        box-shadow: 0 4px 12px rgba(79, 70, 229, 0.45);
      }
      #video-caption-text {
        color: #f8fafc;
        font-size: 16px;
        font-weight: 500;
        line-height: 1.42;
      }
      /* Side-aligned Light-Background Callout so right-side Editor remains 100% visible */
      #video-md-callout {
        position: fixed;
        top: 47%;
        left: 29%;
        transform: translate(-50%, -50%);
        width: 680px;
        max-width: 48vw;
        background: #ffffff;
        border: 3px solid #6366f1;
        border-radius: 18px;
        padding: 22px 26px;
        box-shadow: 0 24px 60px rgba(0, 0, 0, 0.7), 0 0 0 4px rgba(99, 102, 241, 0.25);
        color: #0f172a;
        font-family: 'JetBrains Mono', 'Segoe UI', system-ui, monospace;
        font-size: 14.5px;
        line-height: 1.6;
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
      <div id="video-timelapse-badge">⚡ Zeitraffer — Lokale KI-Analyse (Infinity-Parser2-Flash + Docling Layout)</div>
      <div id="video-md-callout"></div>
      <div id="video-lower-third">
        <div id="video-step-pill">Schritt 1 / 11</div>
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
      if (cfg.timelapse) {
        const progContainer = document.getElementById('pipeline-progress-container');
        if (progContainer) {
          progContainer.classList.remove('hidden');
          document.getElementById('pipeline-progress-phase').textContent = 'Extrahiere Layout, Formeln & Tabellen (Infinity-Parser2-Flash + Docling Layout)...';
          document.getElementById('pipeline-progress-pages').textContent = '1 / 2 Seiten';
          document.getElementById('pipeline-progress-bar').style.width = '68%';
          document.getElementById('pipeline-progress-percent').textContent = '68%';
        }
      }
      const { selectors = [], customBox = null, spotlightLabel = '', pad = 8 } = cfg;
      const sp = document.getElementById('video-spotlight');
      const spLabel = document.getElementById('video-spotlight-label');
      if (!sp || !spLabel) return;

      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      if (customBox) {
        minX = customBox.x;
        minY = customBox.y;
        maxX = customBox.x + customBox.w;
        maxY = customBox.y + customBox.h;
      } else if (selectors.length > 0) {
        for (const sel of selectors) {
          const el = document.querySelector(sel);
          if (el) {
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;
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
        const sx = Math.max(8, Math.round(minX - pad));
        const sy = Math.max(8, Math.round(minY - pad));
        const sw = Math.max(24, Math.min(1912 - sx, Math.round((maxX - minX) + pad * 2)));
        const sh = Math.max(24, Math.min(942 - sy, Math.round((maxY - minY) + pad * 2)));

        sp.style.opacity = '1';
        sp.style.left = `${sx}px`;
        sp.style.top = `${sy}px`;
        sp.style.width = `${sw}px`;
        sp.style.height = `${sh}px`;

        spLabel.textContent = spotlightLabel || '';
        spLabel.style.display = spotlightLabel ? 'block' : 'none';

        // Horizontal alignment: prevent label from clipping off right edge of 1920px viewport
        if (sx > 1180) {
          spLabel.style.left = 'auto';
          spLabel.style.right = '0px';
        } else {
          spLabel.style.left = '0px';
          spLabel.style.right = 'auto';
        }

        // Vertical alignment: place above box unless box is near top of screen
        if (sy < 48) {
          if (sy + sh < 895) {
            spLabel.style.top = 'calc(100% + 8px)';
            spLabel.style.bottom = 'auto';
          } else {
            spLabel.style.top = '10px';
            spLabel.style.left = sx > 1180 ? 'auto' : '10px';
            spLabel.style.right = sx > 1180 ? '10px' : 'auto';
          }
        } else {
          spLabel.style.top = '-38px';
          spLabel.style.bottom = 'auto';
        }
      } else {
        sp.style.opacity = '0';
      }
    };

    window.focusOnSelectors = (config) => {
      const {
        step,
        caption,
        selectors = [],
        customBox = null,
        zoom = 1.0,
        spotlightLabel = '',
        timelapse = false,
        mdCallout = null,
        pad = 8,
      } = config;

      window._currentFocusConfig = config;

      if (step) document.getElementById('video-step-pill').textContent = step;
      if (caption !== undefined) document.getElementById('video-caption-text').textContent = caption;

      // 1. Reset body transform first to measure unscaled target bounding box
      document.body.style.transform = 'none';
      void document.body.offsetHeight;

      let uMinX = Infinity, uMinY = Infinity, uMaxX = -Infinity, uMaxY = -Infinity;
      if (customBox) {
        uMinX = customBox.x;
        uMinY = customBox.y;
        uMaxX = customBox.x + customBox.w;
        uMaxY = customBox.y + customBox.h;
      } else if (selectors.length > 0) {
        for (const sel of selectors) {
          const el = document.querySelector(sel);
          if (el) {
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
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

      // 2. Apply synchronous zoom transform so target is comfortably inside [20..1900] x [52..925]
      if (zoom > 1.0 && uMinX !== Infinity) {
        const cx = (uMinX + uMaxX) / 2;
        const cy = (uMinY + uMaxY) / 2;
        let tx = 960 - cx * zoom;
        let ty = 460 - cy * zoom;

        // Clamp to viewport bounds [1920*(1-zoom), 0]
        tx = Math.min(0, Math.max(1920 * (1 - zoom), tx));
        ty = Math.min(0, Math.max(1080 * (1 - zoom), ty));

        // Ensure target box itself is never pushed off-screen
        if (uMaxX * zoom + tx > 1896) tx = 1896 - uMaxX * zoom;
        if (uMinX * zoom + tx < 16) tx = 16 - uMinX * zoom;
        if (uMaxY * zoom + ty > 925) ty = 925 - uMaxY * zoom;
        if (uMinY * zoom + ty < 52) ty = 52 - uMinY * zoom;

        document.body.style.transform = `translate(${Math.round(tx)}px, ${Math.round(ty)}px) scale(${zoom})`;
        void document.body.offsetHeight;
      } else {
        document.body.style.transform = 'none';
        void document.body.offsetHeight;
      }

      // 3. Measure live post-transform DOM bounding rects for 100% pixel-exact spotlight
      window.refreshSpotlight();

      const tl = document.getElementById('video-timelapse-badge');
      tl.style.opacity = timelapse ? '1' : '0';
      tl.style.transform = timelapse ? 'translateX(-50%) scale(1)' : 'translateX(-50%) scale(0.9)';

      const mc = document.getElementById('video-md-callout');
      if (mdCallout) {
        mc.style.opacity = '1';
        mc.innerHTML = mdCallout;
      } else {
        mc.style.opacity = '0';
      }
    };
  });
}

async function main() {
  console.log('[1/4] Starting Backend (FastAPI) and Frontend (Vite)...');
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

    async function recordScene(sceneIndex, actionsBySec) {
      const seg = manifest[sceneIndex];
      const sceneDir = path.join(FRAMES_DIR, seg.id);
      fs.mkdirSync(sceneDir, { recursive: true });

      const totalSec = seg.duration_sec + 0.45;
      const totalFrames = Math.max(1, Math.round(totalSec * FPS));
      const triggered = new Set();

      console.log(`  -> Recording Scene ${sceneIndex + 1}/11 (${seg.id}): ${totalSec.toFixed(2)}s (${totalFrames} frames)...`);

      for (let f = 0; f < totalFrames; f++) {
        const t = f / FPS;
        for (const [secStr, fn] of Object.entries(actionsBySec)) {
          const sec = parseFloat(secStr);
          if (t >= sec && !triggered.has(secStr)) {
            triggered.add(secStr);
            await fn();
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

      const sceneMp4 = path.join(SCENES_DIR, `${seg.id}.mp4`);
      execSync(
        `ffmpeg -y -framerate ${FPS} -i "${sceneDir}/frame_%04d.jpg" -i "${seg.wav_path}" ` +
        `-c:v libx264 -preset fast -crf 17 -r 30 -pix_fmt yuv420p ` +
        `-c:a aac -b:a 192k -ar 24000 -shortest "${sceneMp4}"`,
        { stdio: 'ignore' }
      );
      return sceneMp4;
    }

    // =========================================================================
    // SCENE 1 (01_overview): UI Overview & 4-Step Workflow Stepper
    // =========================================================================
    await recordScene(0, {
      '0.0': async () => {
        await page.evaluate((cap) => {
          window.focusOnSelectors({
            step: 'Schritt 1 / 11 • Benutzeroberfläche',
            caption: cap,
            zoom: 1.0,
            selectors: [],
          });
        }, manifest[0].text);
      },
      '4.5': async () => {
        await page.evaluate((cap) => {
          window.focusOnSelectors({
            step: 'Schritt 1 / 11 • 4-Phasen-Workflow',
            caption: cap,
            zoom: 1.18,
            selectors: ['#step-1-indicator', '#step-2-indicator', '#step-3-indicator', '#step-4-indicator'],
            pad: 10,
            spotlightLabel: '4-Stufen-Workflow: Upload → Extraktion → Übertragungsregeln → Word-Export',
          });
        }, manifest[0].text);
      },
      '12.0': async () => {
        await page.evaluate((cap) => {
          window.focusOnSelectors({
            step: 'Schritt 1 / 11 • Arbeitsbereich',
            caption: cap,
            zoom: 1.0,
            selectors: ['#left-sidebar', '#panel-standardised-container', '#right-sidebar'],
            pad: 4,
            spotlightLabel: 'Dreigeteilter Arbeitsbereich: Konfiguration links • Editoren mittig • Word-Export rechts',
          });
        }, manifest[0].text);
      },
    });

    // =========================================================================
    // SCENE 2 (02_upload_and_rules): Left Sidebar — PDF Upload & Additional Rules
    // =========================================================================
    await recordScene(1, {
      '0.0': async () => {
        await page.selectOption('#ruleset-select', 'uebertragungsregeln_09_2025');
        await page.evaluate((cap) => {
          window.focusOnSelectors({
            step: 'Schritt 2 / 11 • Schulbuch-PDF & Übertragungsregeln',
            caption: cap,
            zoom: 1.25,
            selectors: ['#ruleset-select', '#dropzone'],
            pad: 8,
            spotlightLabel: 'FIBS Übertragungsregeln (September 2025) & Schulbuch-PDF Upload',
          });
        }, manifest[1].text);
      },
      '4.5': async () => {
        const fileInput = page.locator('#file-input');
        await fileInput.setInputFiles(path.join(PROJECT_DIR, 'testdata/test_educational.pdf'));
        await page.evaluate((cap) => {
          window.focusOnSelectors({
            step: 'Schritt 2 / 11 • Schulbuch geladen',
            caption: cap,
            zoom: 1.25,
            selectors: ['#ruleset-select', '#file-status'],
            pad: 8,
            spotlightLabel: 'Geladen: test_educational.pdf (Physik & Mathematik)',
          });
        }, manifest[1].text);
      },
      '8.5': async () => {
        // Show additional rules configured/uploaded
        await page.evaluate((cap) => {
          const rulesetActions = document.getElementById('ruleset-actions');
          const rulesetBadge = document.getElementById('ruleset-badge');
          if (rulesetActions && rulesetBadge) {
            rulesetActions.classList.remove('hidden');
            rulesetBadge.textContent = 'zusatzregeln_physik.txt (Aktiv)';
          }
          window.focusOnSelectors({
            step: 'Schritt 2 / 11 • Zusätzliche Fachregeln eingebunden',
            caption: cap,
            zoom: 1.25,
            selectors: ['#additional-ruleset-container', '#ruleset-actions'],
            pad: 8,
            spotlightLabel: 'Zusatzregeln für Physik & Formeln eingebunden',
          });
        }, manifest[1].text);
      },
    });

    // =========================================================================
    // SCENE 3 (03_pages_selection): Pages Selection (45-46)
    // =========================================================================
    await recordScene(2, {
      '0.0': async () => {
        await page.fill('#pages-input', '45, 46');
        await page.evaluate((cap) => {
          window.focusOnSelectors({
            step: 'Schritt 3 / 11 • Seitenauswahl (Buchseiten 45 & 46)',
            caption: cap,
            zoom: 1.25,
            selectors: ['#pages-select-container'],
            pad: 8,
            spotlightLabel: 'Gezielte Auswahl: Buchseiten 45 und 46',
          });
        }, manifest[2].text);
      },
    });

    // =========================================================================
    // SCENE 4 (04_engine_selection): Engine Selection (Infinity + Docling Layout)
    // =========================================================================
    await recordScene(3, {
      '0.0': async () => {
        await page.selectOption('#engine-select', 'infinity');
        await page.evaluate((cap) => {
          window.focusOnSelectors({
            step: 'Schritt 4 / 11 • Extraktions-Engine: Infinity-Parser2-Flash + Docling Layout',
            caption: cap,
            zoom: 1.25,
            selectors: ['#engine-select-container'],
            pad: 8,
            spotlightLabel: 'Infinity-Parser2-Flash + Docling Layout (Beste Formel- & Scan-OCR)',
          });
        }, manifest[3].text);
      },
    });

    // =========================================================================
    // SCENE 5 (05_conversion_processing): Start Conversion + Timelapse
    // =========================================================================
    await recordScene(4, {
      '0.0': async () => {
        await page.evaluate((cap) => {
          const btn = document.getElementById('process-btn');
          if (btn) btn.scrollIntoView({ block: 'center' });
          window.focusOnSelectors({
            step: 'Schritt 5 / 11 • Start der lokalen Pipeline',
            caption: cap,
            zoom: 1.25,
            selectors: ['#process-btn'],
            pad: 8,
            spotlightLabel: 'Klick auf „Extraktion starten“',
            timelapse: false,
          });
        }, manifest[4].text);
      },
      '2.5': async () => {
        await page.evaluate(() => document.getElementById('process-btn').click());
        await page.evaluate((cap) => {
          const progContainer = document.getElementById('pipeline-progress-container');
          if (progContainer) progContainer.classList.remove('hidden');
          document.getElementById('pipeline-progress-phase').textContent = 'Extrahiere Layout, Formeln & Tabellen (Infinity-Parser2-Flash + Docling Layout)...';
          document.getElementById('pipeline-progress-pages').textContent = '1 / 2 Seiten';
          document.getElementById('pipeline-progress-bar').style.width = '55%';
          document.getElementById('pipeline-progress-percent').textContent = '55%';
          window.focusOnSelectors({
            step: 'Schritt 5 / 11 • ⚡ Zeitraffer: Lokale Analyse',
            caption: cap,
            zoom: 1.0,
            selectors: ['#pipeline-progress-container'],
            pad: 6,
            spotlightLabel: 'Lokale KI-Verarbeitung (innerhalb weniger Minuten)',
            timelapse: true,
          });
        }, manifest[4].text);
      },
      '6.0': async () => {
        // Wait in background for backend completion, then populate markdown
        await page.waitForFunction(() => {
          const btn = document.getElementById('download-docx-btn');
          return btn && !btn.disabled;
        }, { timeout: 60000 });

        await page.evaluate(({ rawMd, stdMd, cap }) => {
          const pdfPanel = document.getElementById('panel-pdf-container');
          if (pdfPanel && !pdfPanel.classList.contains('hidden')) {
            document.getElementById('toggle-pane-pdf').click();
          }
          const rawPanel = document.getElementById('panel-raw-container');
          if (rawPanel && rawPanel.classList.contains('hidden')) {
            document.getElementById('toggle-pane-raw').click();
          }

          const rawTa = document.getElementById('raw-markdown-textarea');
          const stdTa = document.getElementById('standardised-markdown-textarea');
          rawTa.value = rawMd;
          rawTa.dispatchEvent(new Event('input', { bubbles: true }));
          stdTa.value = stdMd;
          stdTa.dispatchEvent(new Event('input', { bubbles: true }));

          window.focusOnSelectors({
            step: 'Schritt 5 / 11 • Extraktion & Standardisierung abgeschlossen',
            caption: cap,
            zoom: 1.0,
            selectors: ['#panel-raw-container', '#panel-standardised-container'],
            pad: 6,
            spotlightLabel: 'Erfolgreich abgeschlossen: Roh-Markdown (links) & Fibs-Markdown (rechts)',
            timelapse: false,
          });
        }, { rawMd: rawExtractedMd, stdMd: goldenFibsMd, cap: manifest[4].text });
      },
    });

    // =========================================================================
    // SCENE 6 (06_page45_structure): Side-by-Side (Page 45: ((45)) & Hierarchy)
    // =========================================================================
    await recordScene(5, {
      '0.0': async () => {
        await page.evaluate((cap) => {
          const rawTa = document.getElementById('raw-markdown-textarea');
          const stdTa = document.getElementById('standardised-markdown-textarea');
          rawTa.scrollTop = 0;
          stdTa.scrollTop = 0;
          window.focusOnSelectors({
            step: 'Schritt 6 / 11 • Direktvergleich & Seitenmarker ((45))',
            caption: cap,
            zoom: 1.0,
            selectors: ['#panel-standardised-container'],
            pad: 6,
            spotlightLabel: 'Direktvergleich Seite 45: Roh-Extraktion vs. Fibs 09/2025',
            mdCallout: `
              <div style="font-size:16px; font-weight:800; color:#4f46e5; margin-bottom:12px;">✓ Buchseitenzahl &amp; Überschriften-Hierarchie (Fibs 09/2025)</div>
              <div style="background:#f8fafc; border:1px solid #cbd5e1; border-radius:10px; padding:16px; font-size:14px; line-height:1.65;">
                <span style="color:#b91c1c; font-weight:800; font-size:16px;">((45))</span> <span style="color:#64748b; font-size:12px;">← Doppelte runde Klammern als Buchseitenmarker</span><br><br>
                <span style="color:#0284c7; font-weight:700;"># Kapitel 4: Wellenoptik und Interferenz</span><br>
                <span style="color:#0369a1; font-weight:700;">## 4.1 Das Doppelspaltexperiment</span><br><br>
                <span style="color:#334155;">In diesem Kapitel untersuchen wir die Beugung von Licht an engen Spalten...</span>
              </div>
            `,
          });
        }, manifest[5].text);
      },
    });

    // =========================================================================
    // SCENE 7 (07_bild_and_difficulty): <Bild>-Tag & [leicht]/[mittel]/[schwer]
    // =========================================================================
    await recordScene(6, {
      '0.0': async () => {
        await page.evaluate((cap) => {
          const rawTa = document.getElementById('raw-markdown-textarea');
          const stdTa = document.getElementById('standardised-markdown-textarea');
          rawTa.scrollTop = 160;
          stdTa.scrollTop = 160;
          window.focusOnSelectors({
            step: 'Schritt 7 / 11 • <Bild>-Tag & Aufgabenmarker',
            caption: cap,
            zoom: 1.0,
            selectors: ['#panel-standardised-container'],
            pad: 6,
            spotlightLabel: 'Barrierefreie <Bild>-Beschreibung & Schwierigkeitsgrade',
            mdCallout: `
              <div style="font-size:16px; font-weight:800; color:#4f46e5; margin-bottom:12px;">✓ Bildtitel (Ü4) über &lt;Bild&gt; &amp; Aufgaben-Schwierigkeitsgrade</div>
              <div style="background:#f8fafc; border:1px solid #cbd5e1; border-radius:10px; padding:16px; font-size:14px; line-height:1.65;">
                <span style="color:#0f172a; font-weight:700;">#### Abb. 4.1: Schematischer Versuchsaufbau...</span><br>
                <span style="color:#7c3aed; font-weight:800;">&lt;Bild&gt; Schematische Darstellung:</span><br>
                <span style="color:#475569; font-style:italic;">Beschreibung: Links sendet eine Laserquelle...</span><br>
                <span style="color:#7c3aed; font-weight:800;">&lt;/Bild&gt;</span><br><br>
                <span style="color:#16a34a; font-weight:700;">##### Aufgabe 1 [leicht]</span><br>
                <span style="color:#d97706; font-weight:700;">##### Aufgabe 2 [mittel]</span><br>
                <span style="color:#dc2626; font-weight:700;">##### Aufgabe 3 [schwer]</span>
              </div>
            `,
          });
        }, manifest[6].text);
      },
    });

    // =========================================================================
    // SCENE 8 (08_page46_math_tables_footnotes): Page 46 — <Tabelle>, LaTeX & <Anmerkung>
    // =========================================================================
    await recordScene(7, {
      '0.0': async () => {
        await page.evaluate((cap) => {
          const rawTa = document.getElementById('raw-markdown-textarea');
          const stdTa = document.getElementById('standardised-markdown-textarea');
          rawTa.scrollTop = 480;
          stdTa.scrollTop = 480;
          window.focusOnSelectors({
            step: 'Schritt 8 / 11 • Seite 46: <Tabelle>, LaTeX & Fußnoten',
            caption: cap,
            zoom: 1.0,
            selectors: ['#panel-standardised-container'],
            pad: 6,
            spotlightLabel: 'Seite 46: <Tabelle>, LaTeX-Formeln & <Anmerkung>',
            mdCallout: `
              <div style="font-size:16px; font-weight:800; color:#4f46e5; margin-bottom:12px;">✓ Strukturierte Tabelle, LaTeX &amp; Fußnoten am Seitenende</div>
              <div style="background:#f8fafc; border:1px solid #cbd5e1; border-radius:10px; padding:16px; font-size:14px; line-height:1.65;">
                <span style="color:#b91c1c; font-weight:800;">((46))</span><br><br>
                <span style="color:#7c3aed; font-weight:800;">&lt;Tabelle&gt;</span><br>
                <span style="color:#334155; font-family:monospace; font-size:12px;">| Modell | Annahme | Erklärte Phänomene |</span><br>
                <span style="color:#7c3aed; font-weight:800;">&lt;/Tabelle&gt;</span><br><br>
                <span style="color:#0284c7; font-weight:700;">LaTeX:</span> <code>$E = mc^2$</code>, <code>$$\\int_{a}^{b} x^2 \\, dx$$</code><br><br>
                <span style="color:#ea580c; font-weight:700;">&lt;Anmerkung&gt;</span> 1 Vgl. Born &amp; Wolf (1999): Principles of Optics... <span style="color:#ea580c; font-weight:700;">&lt;/Anmerkung&gt;</span>
              </div>
            `,
          });
        }, manifest[7].text);
      },
    });

    // =========================================================================
    // SCENE 9 (09_diff_view): High-Contrast Diff View (Consistent Light Theme)
    // =========================================================================
    await recordScene(8, {
      '0.0': async () => {
        await page.evaluate((cap) => {
          document.documentElement.classList.add('theme-light');
          document.getElementById('btn-diff-standardised').click();
          const diffEl = document.getElementById('standardised-diff-view');
          if (diffEl) diffEl.scrollTop = 0;
          window.focusOnSelectors({
            step: 'Schritt 9 / 11 • Differenz-Ansicht (Regelprüfung Seite 45)',
            caption: cap,
            zoom: 1.0,
            selectors: ['#panel-standardised-container'],
            pad: 6,
            spotlightLabel: 'Differenz-Ansicht: Farbliche Hervorhebung aller FIBS-Anpassungen (Seite 45)',
            mdCallout: null,
          });
        }, manifest[8].text);
      },
      '4.8': async () => {
        await page.evaluate((cap) => {
          document.documentElement.classList.add('theme-light');
          const diffEl = document.getElementById('standardised-diff-view');
          if (diffEl) diffEl.scrollTop = 320;
          window.focusOnSelectors({
            step: 'Schritt 9 / 11 • Differenz-Ansicht (Tabellen & Formeln Seite 46)',
            caption: cap,
            zoom: 1.0,
            selectors: ['#panel-standardised-container'],
            pad: 6,
            spotlightLabel: 'Differenz-Ansicht: Farbliche Hervorhebung von <Tabelle>, LaTeX & Fußnoten (Seite 46)',
            mdCallout: null,
          });
        }, manifest[8].text);
      },
    });

    // =========================================================================
    // SCENE 10 (10_export_and_profile): Right Sidebar — Profile & Word Export
    // =========================================================================
    await recordScene(9, {
      '0.0': async () => {
        await page.evaluate((cap) => {
          document.getElementById('btn-edit-standardised').click();
          window.focusOnSelectors({
            step: 'Schritt 10 / 11 • Zielgruppen-Profil & Word-Vorlage',
            caption: cap,
            zoom: 1.25,
            selectors: ['#profile-select', '#template-mode-select'],
            pad: 12,
            spotlightLabel: 'Zielgruppen-Profil & Offizielle Fibs-Dokumentvorlage (.dotx)',
            mdCallout: null,
          });
        }, manifest[9].text);
      },
      '4.5': async () => {
        await page.evaluate(() => {
          const dlActions = document.getElementById('download-actions');
          if (dlActions) dlActions.classList.remove('hidden');
          document.getElementById('download-docx-btn').click();
        });
        await page.evaluate((cap) => {
          window.focusOnSelectors({
            step: 'Schritt 10 / 11 • Word-Export (.docx) bereitgestellt',
            caption: cap,
            zoom: 1.25,
            selectors: ['#download-actions', '#download-docx-btn'],
            pad: 12,
            spotlightLabel: 'Word-Export gestartet: Barrierefreies Word-Dokument erstellt',
            mdCallout: null,
          });
        }, manifest[9].text);
      },
    });

    // =========================================================================
    // SCENE 11 (11_docx_fullscreen_result): Paginated Fullscreen DOCX Presentation
    // =========================================================================
    await page.goto(pathToFileURL(path.join(ASSETS_DIR, 'docx_fullscreen_viewer.html')).href, { waitUntil: 'load' });
    await injectVideoHud(page);

    await recordScene(10, {
      '0.0': async () => {
        await page.evaluate((cap) => {
          window.scrollTo({ top: 0, behavior: 'instant' });
          window.focusOnSelectors({
            step: 'Schritt 11 / 11 • Vollbild: Fertiges Word-Dokument (.docx)',
            caption: cap,
            zoom: 1.0,
            selectors: ['#page-45'],
            pad: 12,
            spotlightLabel: 'Seite 45: ((45)), Überschriften, barrierefreies <Bild> und Übungsaufgaben',
          });
        }, manifest[10].text);
      },
      '7.0': async () => {
        await page.evaluate((cap) => {
          const p46 = document.getElementById('page-46');
          if (p46) p46.scrollIntoView({ behavior: 'instant', block: 'center' });
          window.focusOnSelectors({
            step: 'Schritt 11 / 11 • Seitenumbruch & Seite 46 (Tabelle & Formeln)',
            caption: cap,
            zoom: 1.0,
            selectors: ['#page-46'],
            pad: 12,
            spotlightLabel: 'Seitenumbruch vor ((46)), native Tabelle, LaTeX-Integral & Fußnoten',
          });
        }, manifest[10].text);
      },
    });

    await browser.close();

    // Concatenate all 11 scene MP4s into the final video
    console.log('[3/4] Concatenating all 11 synchronized scenes into final 1080p MP4...');
    const concatListPath = path.join(SCENES_DIR, 'concat.txt');
    const concatLines = manifest.map(seg => `file '${path.join(SCENES_DIR, `${seg.id}.mp4`)}'`).join('\n');
    fs.writeFileSync(concatListPath, concatLines, 'utf-8');

    const finalArtifactVideo = path.join(ARTIFACT_DIR, 'ebuch_konverter_erklaervideo_de.mp4');
    const finalRepoVideo = path.join(PROJECT_DIR, 'ebuch_konverter_erklaervideo_de.mp4');

    execSync(
      `ffmpeg -y -f concat -safe 0 -i "${concatListPath}" -c copy "${finalArtifactVideo}"`,
      { stdio: 'inherit' }
    );
    fs.copyFileSync(finalArtifactVideo, finalRepoVideo);
    console.log(`[4/4] Done! Video written to:\n  - ${finalArtifactVideo}\n  - ${finalRepoVideo}`);
  } finally {
    backendProc.kill('SIGTERM');
    frontendProc.kill('SIGTERM');
  }
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
