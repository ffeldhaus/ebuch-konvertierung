/**
 * Feedback mode controller.
 *
 * Lets the user:
 *  1. pick a processed job from the history (or create one from an MD/DOCX export),
 *  2. upload the manually revised transfer,
 *  3. add optional feedback (text or file),
 *  4. mark incorrectly transferred regions in the source PDF (exported as PNG),
 * and streams a Gemma 4 analysis report from `/api/feedback/analyze`.
 */

interface FeedbackJob {
  task_id: string;
  original_name: string;
  status: string;
  engine: string | null;
  pages: string | null;
  page_count: number;
  physical_start_page: number;
  created_at: number | null;
  finished_at: number | null;
  has_markdown: boolean;
  has_docx: boolean;
  has_pdf: boolean;
  report_count: number;
}

interface MarkedRegion {
  blob: Blob;
  url: string;
  page: number;       // PDF page number (1-based), independent of printed/extracted page numbers
  note: string;
}

interface FeedbackReportSummary {
  feedback_id: string;
  task_id: string;
  created_at: number | null;
  original_name: string | null;
  region_count: number | null;
}

/** One parsed entry of the report's "Offene Fragen" section (answer null = open/skipped). */
interface OpenQuestion {
  question: string;
  answer: string | null;
}

export interface FeedbackControllerOptions {
  showError: (message: string, title: string) => void;
}

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

/** Escapes HTML special characters. */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Inline markdown (code, bold, italic) on already escaped text. */
function renderInline(text: string): string {
  return text
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>');
}

/**
 * Minimal, safe Markdown renderer for the analysis report
 * (headings, lists, tables, code blocks, horizontal rules, paragraphs).
 * All content is HTML-escaped first, so model output can never inject markup.
 */
export function renderReportMarkdown(markdown: string): string {
  const lines = escapeHtml(markdown).split('\n');
  const out: string[] = [];
  // Open lists, innermost last; `indent` = leading spaces of the list's items
  const listStack: { type: 'ul' | 'ol'; indent: number }[] = [];
  let inCode = false;
  let table: string[][] = [];

  const closeList = () => {
    while (listStack.length) out.push(`</li></${listStack.pop()!.type}>`);
  };
  const flushTable = () => {
    if (!table.length) return;
    const [head, ...body] = table;
    out.push('<table><thead><tr>' + head.map(c => `<th>${renderInline(c)}</th>`).join('') + '</tr></thead><tbody>' +
      body.map(r => '<tr>' + r.map(c => `<td>${renderInline(c)}</td>`).join('') + '</tr>').join('') + '</tbody></table>');
    table = [];
  };
  /** Adds a list item, opening/closing nested lists based on indentation. */
  const addListItem = (indent: number, type: 'ul' | 'ol', content: string, start: number) => {
    while (listStack.length && indent < listStack[listStack.length - 1].indent) {
      out.push(`</li></${listStack.pop()!.type}>`);
    }
    const top = listStack[listStack.length - 1];
    const open = () => out.push(type === 'ol' && start > 1 ? `<ol start="${start}">` : `<${type}>`);
    if (!top || indent > top.indent) {
      open();
      listStack.push({ type, indent });
    } else if (top.type !== type) {
      out.push(`</li></${top.type}>`);
      listStack.pop();
      open();
      listStack.push({ type, indent });
    } else {
      out.push('</li>');
    }
    out.push(`<li>${renderInline(content)}`);
  };

  for (const raw of lines) {
    const line = raw.replace(/\t/g, '    ').trimEnd();
    if (line.trimStart().startsWith('```')) {
      closeList(); flushTable();
      out.push(inCode ? '</code></pre>' : '<pre><code>');
      inCode = !inCode;
      continue;
    }
    if (inCode) { out.push(raw + '\n'); continue; }

    if (/^\s*\|.*\|\s*$/.test(line)) {
      closeList();
      const cells = line.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());
      if (!cells.every(c => /^:?-{2,}:?$/.test(c))) table.push(cells);
      continue;
    }
    flushTable();

    // Blank lines keep an open list alive (models often separate items with empty lines)
    if (!line.trim()) continue;

    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      closeList();
      const level = Math.min(heading[1].length + 1, 6); // h1 is reserved for the page
      out.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
      continue;
    }
    if (/^-{3,}$/.test(line.trim())) { closeList(); out.push('<hr>'); continue; }

    const ul = line.match(/^(\s*)[-*+]\s+(.*)$/);
    const ol = line.match(/^(\s*)(\d+)[.)]\s+(.*)$/);
    if (ul) { addListItem(ul[1].length, 'ul', ul[2], 1); continue; }
    if (ol) { addListItem(ol[1].length, 'ol', ol[3], parseInt(ol[2], 10)); continue; }

    // Indented continuation text belongs to the current list item
    if (listStack.length && /^\s+\S/.test(line)) { out.push(`<br>${renderInline(line.trim())}`); continue; }
    closeList();
    out.push(`<p>${renderInline(line)}</p>`);
  }
  closeList(); flushTable();
  if (inCode) out.push('</code></pre>');
  return out.join('\n');
}

export class FeedbackController {
  private opts: FeedbackControllerOptions;
  private initialized = false;

  private jobs: FeedbackJob[] = [];
  private selectedJob: FeedbackJob | null = null;
  private revisedFile: File | null = null;
  private regions: MarkedRegion[] = [];
  private currentPageIdx = 0;
  private selection: { x: number; y: number; w: number; h: number } | null = null;
  private dragStart: { x: number; y: number } | null = null;
  private currentReport = '';
  private currentReportName = 'feedback_analyse.md';
  private currentReportRef: { taskId: string; feedbackId: string } | null = null;
  private isAnalyzing = false;
  // Open questions modal state
  private openQuestions: OpenQuestion[] = [];
  private draftAnswers: (string | null)[] = [];
  private questionIdx = 0;
  private isSavingAnswers = false;
  // Wheel paging state: one page per wheel gesture (no fluid scrolling)
  private wheelAccum = 0;
  private wheelLocked = false;
  private wheelLastEvent = 0;
  private wheelLastFlip = 0;

  // Elements
  private jobSelect = $<HTMLSelectElement>('fb-job-select');
  private jobArtifacts = $<HTMLDivElement>('fb-job-artifacts');
  private refreshJobsBtn = $<HTMLButtonElement>('fb-refresh-jobs-btn');
  private toggleNewJobBtn = $<HTMLButtonElement>('fb-toggle-new-job-btn');
  private newJobForm = $<HTMLDivElement>('fb-new-job-form');
  private newTransferInput = $<HTMLInputElement>('fb-new-transfer-input');
  private newPdfInput = $<HTMLInputElement>('fb-new-pdf-input');
  private createJobBtn = $<HTMLButtonElement>('fb-create-job-btn');
  private revisedDropzone = $<HTMLDivElement>('fb-revised-dropzone');
  private revisedInput = $<HTMLInputElement>('fb-revised-input');
  private revisedFilename = $<HTMLParagraphElement>('fb-revised-filename');
  private revisedBadge = $<HTMLSpanElement>('fb-revised-badge');
  private feedbackText = $<HTMLTextAreaElement>('fb-feedback-text');
  private feedbackFileInput = $<HTMLInputElement>('fb-feedback-file-input');
  private pageSelect = $<HTMLSelectElement>('fb-page-select');
  private pagePrevBtn = $<HTMLButtonElement>('fb-page-prev-btn');
  private pageNextBtn = $<HTMLButtonElement>('fb-page-next-btn');
  private pageStage = $<HTMLDivElement>('fb-page-stage');
  private pagePlaceholder = $<HTMLParagraphElement>('fb-page-placeholder');
  private canvasWrap = $<HTMLDivElement>('fb-page-canvas-wrap');
  private pageImage = $<HTMLImageElement>('fb-page-image');
  private overlay = $<HTMLDivElement>('fb-page-overlay');
  private selectionRect = $<HTMLDivElement>('fb-selection-rect');
  private regionNote = $<HTMLInputElement>('fb-region-note');
  private addRegionBtn = $<HTMLButtonElement>('fb-add-region-btn');
  private addFullPageBtn = $<HTMLButtonElement>('fb-add-fullpage-btn');
  private regionsList = $<HTMLUListElement>('fb-regions-list');
  private regionCount = $<HTMLSpanElement>('fb-region-count');
  private analyzeBtn = $<HTMLButtonElement>('fb-analyze-btn');
  private reportsSelect = $<HTMLSelectElement>('fb-reports-select');
  private progress = $<HTMLDivElement>('fb-progress');
  private progressPhase = $<HTMLParagraphElement>('fb-progress-phase');
  private progressPercent = $<HTMLSpanElement>('fb-progress-percent');
  private progressBar = $<HTMLDivElement>('fb-progress-bar');
  private progressLog = $<HTMLParagraphElement>('fb-progress-log');
  // Live Gemma output (unfiltered, local only, never persisted)
  private livePanel = $<HTMLDetailsElement>('fb-live-panel');
  private liveLog = $<HTMLOListElement>('fb-live-log');
  private liveOutput = $<HTMLDivElement>('fb-live-output');
  private liveStats = $<HTMLSpanElement>('fb-live-stats');
  private liveIndicator = $<HTMLSpanElement>('fb-live-indicator');
  private liveTarget: HTMLPreElement | null = null;
  private livePending = '';
  private liveFrame = 0;
  private liveTokenCount = 0;
  private liveSectionStart = 0;
  private resultSection = $<HTMLElement>('fb-result-section');
  private reportContent = $<HTMLElement>('fb-report-content');
  private copyReportBtn = $<HTMLButtonElement>('fb-copy-report-btn');
  private downloadReportBtn = $<HTMLButtonElement>('fb-download-report-btn');
  private answerQuestionsBtn = $<HTMLButtonElement>('fb-answer-questions-btn');
  private questionsModal = $<HTMLDivElement>('fb-questions-modal');
  private questionCounter = $<HTMLSpanElement>('fb-question-counter');
  private questionSteps = $<HTMLDivElement>('fb-question-steps');
  private questionText = $<HTMLParagraphElement>('fb-question-text');
  private answerInput = $<HTMLTextAreaElement>('fb-answer-input');
  private questionPrevBtn = $<HTMLButtonElement>('fb-question-prev-btn');
  private questionSkipBtn = $<HTMLButtonElement>('fb-question-skip-btn');
  private questionNextBtn = $<HTMLButtonElement>('fb-question-next-btn');
  private questionsCloseBtn = $<HTMLButtonElement>('fb-questions-close-btn');

  constructor(opts: FeedbackControllerOptions) {
    this.opts = opts;
  }

  /** Called whenever the Feedback view becomes visible. */
  activate() {
    if (!this.initialized) {
      this.bindEvents();
      this.initialized = true;
    }
    this.loadJobs(this.selectedJob?.task_id);
    this.loadReports();
  }

  // -------------------------------------------------------------------------
  // Event binding
  // -------------------------------------------------------------------------

  private bindEvents() {
    this.jobSelect.addEventListener('change', () => this.selectJob(this.jobSelect.value));
    this.refreshJobsBtn.addEventListener('click', () => this.loadJobs(this.selectedJob?.task_id));

    this.toggleNewJobBtn.addEventListener('click', () => {
      const open = this.newJobForm.classList.toggle('hidden') === false;
      this.toggleNewJobBtn.setAttribute('aria-expanded', String(open));
    });
    this.newTransferInput.addEventListener('change', () => {
      this.createJobBtn.disabled = !this.newTransferInput.files?.length;
    });
    this.createJobBtn.addEventListener('click', () => this.createJob());

    // Revised transfer upload (click, keyboard, drag & drop)
    this.revisedDropzone.addEventListener('click', () => this.revisedInput.click());
    this.revisedDropzone.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this.revisedInput.click(); }
    });
    this.revisedInput.addEventListener('change', () => {
      if (this.revisedInput.files?.length) this.setRevisedFile(this.revisedInput.files[0]);
    });
    this.revisedDropzone.addEventListener('dragover', (e) => {
      e.preventDefault();
      this.revisedDropzone.classList.add('border-emerald-500', 'bg-emerald-500/10');
    });
    this.revisedDropzone.addEventListener('dragleave', () => {
      this.revisedDropzone.classList.remove('border-emerald-500', 'bg-emerald-500/10');
    });
    this.revisedDropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      this.revisedDropzone.classList.remove('border-emerald-500', 'bg-emerald-500/10');
      if (e.dataTransfer?.files.length) this.setRevisedFile(e.dataTransfer.files[0]);
    });

    // Page navigation
    this.pageSelect.addEventListener('change', () => this.showPage(parseInt(this.pageSelect.value, 10)));
    this.pagePrevBtn.addEventListener('click', () => this.showPage(this.currentPageIdx - 1));
    this.pageNextBtn.addEventListener('click', () => this.showPage(this.currentPageIdx + 1));
    this.pageStage.addEventListener('wheel', (e) => this.onWheel(e), { passive: false });
    this.pageStage.addEventListener('keydown', (e) => this.onStageKeydown(e));

    // Rectangle selection via pointer events (mouse, pen and touch)
    this.overlay.addEventListener('pointerdown', (e) => this.onPointerDown(e));
    this.overlay.addEventListener('pointermove', (e) => this.onPointerMove(e));
    this.overlay.addEventListener('pointerup', (e) => this.onPointerUp(e));
    this.overlay.addEventListener('pointercancel', () => { this.dragStart = null; });

    this.addRegionBtn.addEventListener('click', () => this.addRegion(false));
    this.addFullPageBtn.addEventListener('click', () => this.addRegion(true));

    this.analyzeBtn.addEventListener('click', () => this.runAnalysis());
    this.reportsSelect.addEventListener('change', () => this.openStoredReport(this.reportsSelect.value));
    this.copyReportBtn.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(this.currentReport);
        this.flashButton(this.copyReportBtn, '✅ Kopiert');
      } catch {
        this.opts.showError('Der Bericht konnte nicht in die Zwischenablage kopiert werden.', 'Kopieren fehlgeschlagen');
      }
    });
    this.downloadReportBtn.addEventListener('click', () => {
      const blob = new Blob([this.currentReport], { type: 'text/markdown;charset=utf-8' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = this.currentReportName;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    });

    // Open questions modal
    this.answerQuestionsBtn.addEventListener('click', () => this.openQuestionsModal());
    this.questionNextBtn.addEventListener('click', () => this.nextQuestion(false));
    this.questionSkipBtn.addEventListener('click', () => this.nextQuestion(true));
    this.questionPrevBtn.addEventListener('click', () => this.prevQuestion());
    this.questionsCloseBtn.addEventListener('click', () => this.closeQuestionsModal());
    this.questionsModal.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.preventDefault(); this.closeQuestionsModal(); }
      else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); this.nextQuestion(false); }
    });
    // Click on the backdrop (outside the card) closes without saving
    this.questionsModal.addEventListener('click', (e) => {
      if (e.target === this.questionsModal) this.closeQuestionsModal();
    });
  }

  // -------------------------------------------------------------------------
  // Jobs
  // -------------------------------------------------------------------------

  private async loadJobs(selectId?: string) {
    try {
      const resp = await fetch('/api/feedback/jobs');
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      this.jobs = (data.jobs as FeedbackJob[]).filter(j => j.has_markdown || j.has_docx);
    } catch (e) {
      console.error('Failed to load feedback jobs:', e);
      this.jobs = [];
    }

    this.jobSelect.innerHTML = '';
    const placeholder = new Option(
      this.jobs.length ? '-- Bearbeiteten Auftrag wählen --' : '-- Keine Aufträge mit Übertragung gefunden --', '');
    this.jobSelect.add(placeholder);
    for (const job of this.jobs) {
      const date = job.finished_at || job.created_at;
      const dateStr = date ? new Date(date * 1000).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' }) : '';
      const flags = [job.has_markdown ? 'MD' : '', job.has_docx ? 'DOCX' : '', job.has_pdf ? 'PDF' : ''].filter(Boolean).join('/');
      const pages = job.pages ? ` · S. ${job.pages}` : '';
      this.jobSelect.add(new Option(`${job.original_name}${pages} · ${dateStr} [${flags}]`, job.task_id));
    }
    if (selectId && this.jobs.some(j => j.task_id === selectId)) {
      this.jobSelect.value = selectId;
    }
    this.selectJob(this.jobSelect.value, false);
  }

  private selectJob(taskId: string, resetRegions = true) {
    const job = this.jobs.find(j => j.task_id === taskId) || null;
    const changed = job?.task_id !== this.selectedJob?.task_id;
    this.selectedJob = job;

    if (changed && resetRegions) this.clearRegions();
    this.renderArtifacts();
    if (changed || !job) this.setupPageViewer();
    this.updateAnalyzeState();
  }

  private renderArtifacts() {
    const job = this.selectedJob;
    if (!job) {
      this.jobArtifacts.classList.add('hidden');
      this.jobArtifacts.innerHTML = '';
      return;
    }
    const badge = (ok: boolean, label: string, href?: string) => {
      const cls = ok
        ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
        : 'bg-slate-800 text-slate-500 border-slate-700 line-through';
      const content = `${ok ? '✓' : '✗'} ${label}`;
      return ok && href
        ? `<a href="${href}" class="fb-artifact px-2 py-0.5 rounded-full border ${cls} hover:brightness-125" title="${label} herunterladen" download>${content}</a>`
        : `<span class="fb-artifact px-2 py-0.5 rounded-full border ${cls}">${content}</span>`;
    };
    const base = `/api/feedback/jobs/${encodeURIComponent(job.task_id)}/files`;
    this.jobArtifacts.innerHTML = [
      badge(job.has_markdown, 'Markdown-Quelle', `${base}/markdown`),
      badge(job.has_docx, 'DOCX-Export', `${base}/docx`),
      badge(job.has_pdf, 'Quell-PDF'),
      job.engine ? `<span class="text-slate-500">Engine: ${escapeHtml(job.engine)}</span>` : '',
    ].join('');
    this.jobArtifacts.classList.remove('hidden');
  }

  private async createJob() {
    const transfer = this.newTransferInput.files?.[0];
    if (!transfer) return;
    const fd = new FormData();
    fd.append('transfer_file', transfer);
    const pdf = this.newPdfInput.files?.[0];
    if (pdf) fd.append('source_pdf', pdf);

    this.createJobBtn.disabled = true;
    this.createJobBtn.textContent = 'Lege Auftrag an…';
    try {
      const resp = await fetch('/api/feedback/jobs', { method: 'POST', body: fd });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
      this.newTransferInput.value = '';
      this.newPdfInput.value = '';
      this.newJobForm.classList.add('hidden');
      this.toggleNewJobBtn.setAttribute('aria-expanded', 'false');
      await this.loadJobs(data.task_id);
    } catch (e) {
      this.opts.showError(`Der Auftrag konnte nicht angelegt werden: ${(e as Error).message}`, 'Auftrag anlegen fehlgeschlagen');
    } finally {
      this.createJobBtn.textContent = 'Auftrag anlegen';
      this.createJobBtn.disabled = !this.newTransferInput.files?.length;
    }
  }

  // -------------------------------------------------------------------------
  // Revised transfer
  // -------------------------------------------------------------------------

  private setRevisedFile(file: File) {
    const ext = file.name.toLowerCase().split('.').pop() || '';
    if (!['md', 'txt', 'docx'].includes(ext)) {
      this.opts.showError('Bitte die überarbeitete Übertragung als .docx, .md oder .txt hochladen.', 'Ungültiges Dateiformat');
      return;
    }
    this.revisedFile = file;
    this.revisedFilename.textContent = file.name;
    this.revisedBadge.classList.remove('hidden');
    this.updateAnalyzeState();
  }

  private updateAnalyzeState() {
    this.analyzeBtn.disabled = this.isAnalyzing || !this.selectedJob || !this.revisedFile;
  }

  // -------------------------------------------------------------------------
  // PDF page viewer & region marking
  // -------------------------------------------------------------------------

  private setupPageViewer() {
    const job = this.selectedJob;
    const enabled = !!job && job.has_pdf && job.page_count > 0;
    this.pageSelect.innerHTML = '';
    this.pageSelect.disabled = !enabled;
    this.addFullPageBtn.disabled = !enabled;
    this.setSelection(null);

    if (!enabled || !job) {
      this.canvasWrap.classList.add('hidden');
      this.pagePlaceholder.classList.remove('hidden');
      this.pagePlaceholder.textContent = job
        ? 'Für diesen Auftrag ist kein Quell-PDF gespeichert – Markierungen sind nicht möglich.'
        : 'Wähle einen Auftrag mit Quell-PDF, um Stellen zu markieren.';
      this.pagePrevBtn.disabled = this.pageNextBtn.disabled = true;
      return;
    }

    for (let i = 0; i < job.page_count; i++) {
      this.pageSelect.add(new Option(`Seite ${this.pdfPage(i)} / ${job.page_count}`, String(i)));
    }
    // Jump to the first page of the processed range if available
    this.showPage(this.firstSelectedPageIdx(job));
  }

  /** PDF page number (1-based). Deliberately ignores printed/extracted page numbers. */
  private pdfPage(idx: number): number {
    return idx + 1;
  }

  /**
   * Maps the first entry of the job's page selection to a PDF page index, so the
   * viewer opens where the transfer started. The selection was entered in printed
   * page numbers (offset by physical_start_page); this is only used for the jump,
   * never for display.
   */
  private firstSelectedPageIdx(job: FeedbackJob): number {
    const m = (job.pages || '').match(/\d+/);
    if (!m) return 0;
    const physical = parseInt(m[0], 10);
    const start = job.physical_start_page || 1;
    let idx = physical - start;
    if (idx < 0 || idx >= job.page_count) idx = physical - 1;
    return Math.min(Math.max(idx, 0), job.page_count - 1);
  }

  private showPage(idx: number) {
    const job = this.selectedJob;
    if (!job || !job.has_pdf) return;
    idx = Math.min(Math.max(idx, 0), job.page_count - 1);
    this.currentPageIdx = idx;
    this.pageSelect.value = String(idx);
    this.pagePrevBtn.disabled = idx <= 0;
    this.pageNextBtn.disabled = idx >= job.page_count - 1;
    this.setSelection(null);

    this.pagePlaceholder.classList.remove('hidden');
    this.pagePlaceholder.textContent = 'Lade Seite…';
    this.pageImage.onload = () => {
      this.pagePlaceholder.classList.add('hidden');
      this.canvasWrap.classList.remove('hidden');
    };
    this.pageImage.onerror = () => {
      this.canvasWrap.classList.add('hidden');
      this.pagePlaceholder.textContent = 'Seite konnte nicht geladen werden.';
    };
    this.pageImage.alt = `Seite ${this.pdfPage(idx)} von ${job.page_count} des Quell-PDFs`;
    this.pageImage.src = this.pageUrl(job, idx);
    this.preloadNeighbours(job, idx);
  }

  private pageUrl(job: FeedbackJob, idx: number): string {
    return `/api/feedback/jobs/${encodeURIComponent(job.task_id)}/pages/${idx}?scale=2`;
  }

  /** Preloads the previous and next page (into the HTTP cache) so wheel paging feels instant. */
  private preloadNeighbours(job: FeedbackJob, idx: number) {
    for (const i of [idx - 1, idx + 1]) {
      if (i >= 0 && i < job.page_count) new Image().src = this.pageUrl(job, i);
    }
  }

  /**
   * Mouse wheel / trackpad paging: exactly one page per gesture.
   * Deltas are accumulated until a threshold is reached; afterwards the gesture is
   * locked until the wheel pauses (handles trackpad inertia) or a short interval
   * passes (allows continuous paging with a notched mouse wheel).
   */
  private onWheel(e: WheelEvent) {
    const job = this.selectedJob;
    if (!job || !job.has_pdf || e.ctrlKey) return; // keep pinch-zoom untouched
    e.preventDefault();

    const now = performance.now();
    if (now - this.wheelLastEvent > 180) { this.wheelLocked = false; this.wheelAccum = 0; }
    if (this.wheelLocked && now - this.wheelLastFlip > 600) { this.wheelLocked = false; this.wheelAccum = 0; }
    this.wheelLastEvent = now;
    if (this.wheelLocked || this.dragStart) return;

    // Normalise line/page delta modes to pixels
    const factor = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
    this.wheelAccum += (Math.abs(e.deltaY) >= Math.abs(e.deltaX) ? e.deltaY : e.deltaX) * factor;
    if (Math.abs(this.wheelAccum) < 40) return;

    const target = this.currentPageIdx + (this.wheelAccum > 0 ? 1 : -1);
    this.wheelAccum = 0;
    this.wheelLocked = true;
    this.wheelLastFlip = now;
    if (target >= 0 && target < job.page_count) this.showPage(target);
  }

  /** Keyboard paging when the page stage has focus. */
  private onStageKeydown(e: KeyboardEvent) {
    const job = this.selectedJob;
    if (!job || !job.has_pdf) return;
    const map: Record<string, number> = {
      PageDown: this.currentPageIdx + 1, ArrowDown: this.currentPageIdx + 1, ArrowRight: this.currentPageIdx + 1,
      PageUp: this.currentPageIdx - 1, ArrowUp: this.currentPageIdx - 1, ArrowLeft: this.currentPageIdx - 1,
      Home: 0, End: job.page_count - 1,
    };
    if (!(e.key in map)) return;
    e.preventDefault();
    this.showPage(map[e.key]);
  }

  private relativePoint(e: PointerEvent) {
    const rect = this.overlay.getBoundingClientRect();
    return {
      x: Math.min(Math.max(e.clientX - rect.left, 0), rect.width),
      y: Math.min(Math.max(e.clientY - rect.top, 0), rect.height),
    };
  }

  private onPointerDown(e: PointerEvent) {
    if (e.button !== 0) return;
    this.overlay.setPointerCapture(e.pointerId);
    this.dragStart = this.relativePoint(e);
    this.setSelection({ ...this.dragStart, w: 0, h: 0 });
  }

  private onPointerMove(e: PointerEvent) {
    if (!this.dragStart) return;
    const p = this.relativePoint(e);
    this.setSelection({
      x: Math.min(p.x, this.dragStart.x),
      y: Math.min(p.y, this.dragStart.y),
      w: Math.abs(p.x - this.dragStart.x),
      h: Math.abs(p.y - this.dragStart.y),
    });
  }

  private onPointerUp(e: PointerEvent) {
    if (!this.dragStart) return;
    this.onPointerMove(e);
    this.dragStart = null;
    if (this.selection && (this.selection.w < 6 || this.selection.h < 6)) this.setSelection(null);
  }

  private setSelection(sel: { x: number; y: number; w: number; h: number } | null) {
    this.selection = sel;
    if (!sel) {
      this.selectionRect.classList.add('hidden');
    } else {
      Object.assign(this.selectionRect.style, {
        left: `${sel.x}px`, top: `${sel.y}px`, width: `${sel.w}px`, height: `${sel.h}px`,
      });
      this.selectionRect.classList.remove('hidden');
    }
    this.addRegionBtn.disabled = !sel || sel.w < 6 || sel.h < 6;
  }

  /** Crops the current selection (or the full page) from the rendered page image into a PNG blob. */
  private async cropToPng(fullPage: boolean): Promise<Blob | null> {
    const img = this.pageImage;
    if (!img.naturalWidth) return null;
    const scaleX = img.naturalWidth / img.clientWidth;
    const scaleY = img.naturalHeight / img.clientHeight;
    const sel = fullPage || !this.selection
      ? { x: 0, y: 0, w: img.clientWidth, h: img.clientHeight }
      : this.selection;
    const sx = Math.round(sel.x * scaleX);
    const sy = Math.round(sel.y * scaleY);
    const sw = Math.max(1, Math.round(sel.w * scaleX));
    const sh = Math.max(1, Math.round(sel.h * scaleY));

    const canvas = document.createElement('canvas');
    canvas.width = sw;
    canvas.height = sh;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    ctx.drawImage(img, sx, sy, sw, sh, 0, 0, sw, sh);
    return new Promise(resolve => canvas.toBlob(b => resolve(b), 'image/png'));
  }

  private async addRegion(fullPage: boolean) {
    const blob = await this.cropToPng(fullPage);
    if (!blob) {
      this.opts.showError('Der Ausschnitt konnte nicht erstellt werden.', 'Markierung fehlgeschlagen');
      return;
    }
    this.regions.push({
      blob,
      url: URL.createObjectURL(blob),
      page: this.pdfPage(this.currentPageIdx),
      note: this.regionNote.value.trim(),
    });
    this.regionNote.value = '';
    this.setSelection(null);
    this.renderRegions();
  }

  private clearRegions() {
    this.regions.forEach(r => URL.revokeObjectURL(r.url));
    this.regions = [];
    this.renderRegions();
  }

  private renderRegions() {
    this.regionCount.textContent = String(this.regions.length);
    this.regionsList.innerHTML = '';
    if (!this.regions.length) {
      const li = document.createElement('li');
      li.className = 'fb-empty text-[10px] text-slate-500 italic';
      li.textContent = 'Noch keine Stellen markiert.';
      this.regionsList.appendChild(li);
      return;
    }
    this.regions.forEach((r, i) => {
      const li = document.createElement('li');
      li.className = 'fb-region-item flex items-start gap-2 p-2 rounded-lg bg-slate-950 border border-slate-800';
      li.innerHTML = `
        <img src="${r.url}" alt="Markierte Stelle ${i + 1}, PDF-Seite ${r.page}" class="w-16 h-16 object-contain rounded bg-white flex-shrink-0">
        <div class="flex-1 min-w-0 space-y-1">
          <p class="text-[10px] font-bold text-slate-200">Stelle ${i + 1} · PDF-Seite ${r.page}</p>
          <p class="text-[10px] text-slate-400 break-words">${r.note ? escapeHtml(r.note) : '<em>ohne Notiz</em>'}</p>
          <div class="flex gap-2 text-[10px]">
            <a href="${r.url}" download="fehlerstelle_${i + 1}_seite_${r.page}.png" class="text-indigo-400 hover:text-indigo-300">PNG speichern</a>
            <button type="button" data-remove="${i}" class="fb-remove-region text-rose-400 hover:text-rose-300">Entfernen</button>
          </div>
        </div>`;
      li.querySelector<HTMLButtonElement>('[data-remove]')!.addEventListener('click', () => {
        URL.revokeObjectURL(r.url);
        this.regions.splice(i, 1);
        this.renderRegions();
      });
      this.regionsList.appendChild(li);
    });
  }

  // -------------------------------------------------------------------------
  // Analysis
  // -------------------------------------------------------------------------

  private setProgress(percent: number, phase?: string) {
    const p = Math.max(0, Math.min(100, Math.round(percent)));
    this.progressBar.style.width = `${p}%`;
    this.progressPercent.textContent = `${p}%`;
    if (phase) this.progressPhase.textContent = phase;
  }

  // ---- Live panel ---------------------------------------------------------

  /** True if the scroll container is (nearly) at the bottom – only then we auto-scroll. */
  private static isAtBottom(el: HTMLElement): boolean {
    return el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  }

  private resetLive() {
    if (this.liveFrame) cancelAnimationFrame(this.liveFrame);
    this.liveFrame = 0;
    this.livePending = '';
    this.liveTarget = null;
    this.liveTokenCount = 0;
    this.liveLog.replaceChildren();
    this.liveOutput.replaceChildren();
    this.liveStats.textContent = '0 Tokens';
    this.livePanel.open = true;
    this.livePanel.classList.remove('hidden');
    this.liveIndicator.classList.add('is-active');
  }

  private appendLiveLog(message: string) {
    const stick = FeedbackController.isAtBottom(this.liveLog);
    const li = document.createElement('li');
    const time = new Date().toLocaleTimeString('de-DE', { hour12: false });
    li.textContent = `${time}  ${message}`;
    if (/error|fehler|failed|traceback/i.test(message)) li.classList.add('is-error');
    else if (/warn/i.test(message)) li.classList.add('is-warning');
    this.liveLog.appendChild(li);
    // Bound DOM size for very chatty logs
    while (this.liveLog.childElementCount > 500) this.liveLog.firstElementChild?.remove();
    if (stick) this.liveLog.scrollTop = this.liveLog.scrollHeight;
  }

  /** Starts a new streamed block ("Stelle N" or "Bericht") in the live output. */
  private startLiveSection(section: string, index: number | null) {
    this.flushLive();
    const block = document.createElement('div');
    block.className = 'fb-live-block';
    const h = document.createElement('h5');
    h.className = 'fb-live-block-title';
    h.textContent = section === 'region' ? `🔍 Markierte Stelle ${index ?? ''}`.trim() : '📝 Fehleranalyse (Bericht)';
    const pre = document.createElement('pre');
    pre.className = 'fb-live-text';
    block.append(h, pre);
    this.liveOutput.appendChild(block);
    this.liveTarget = pre;
    this.liveSectionStart = performance.now();
  }

  private queueLiveToken(delta: string) {
    if (!this.liveTarget) this.startLiveSection('report', null);
    this.livePending += delta;
    this.liveTokenCount += 1;
    if (!this.liveFrame) this.liveFrame = requestAnimationFrame(() => this.flushLive());
  }

  /** Appends buffered tokens in one DOM write (batched per animation frame). */
  private flushLive() {
    if (this.liveFrame) cancelAnimationFrame(this.liveFrame);
    this.liveFrame = 0;
    if (!this.livePending || !this.liveTarget) return;
    const stick = FeedbackController.isAtBottom(this.liveOutput);
    this.liveTarget.appendChild(document.createTextNode(this.livePending));
    this.livePending = '';
    const secs = (performance.now() - this.liveSectionStart) / 1000;
    this.liveStats.textContent = `${this.liveTokenCount} Tokens` + (secs > 0.5 ? ` · Abschnitt ${secs.toFixed(0)}s` : '');
    if (stick) this.liveOutput.scrollTop = this.liveOutput.scrollHeight;
  }

  private finishLive(success: boolean) {
    this.flushLive();
    this.liveIndicator.classList.remove('is-active');
    // Collapse after success so the filtered report gets the focus; keep open on errors for diagnosis
    if (success) this.livePanel.open = false;
  }

  private async runAnalysis() {
    if (!this.selectedJob || !this.revisedFile || this.isAnalyzing) return;
    const fd = new FormData();
    fd.append('task_id', this.selectedJob.task_id);
    fd.append('revised_file', this.revisedFile);
    if (this.feedbackText.value.trim()) fd.append('feedback_text', this.feedbackText.value.trim());
    const fbFile = this.feedbackFileInput.files?.[0];
    if (fbFile) fd.append('feedback_file', fbFile);
    this.regions.forEach((r, i) => fd.append('regions', r.blob, `region_${i + 1}.png`));
    fd.append('regions_meta', JSON.stringify(this.regions.map(r => ({ page: r.page, note: r.note }))));

    this.isAnalyzing = true;
    this.updateAnalyzeState();
    this.progress.classList.remove('hidden');
    this.resultSection.classList.add('hidden');
    this.progressLog.textContent = '';
    this.resetLive();
    this.setProgress(2, 'Sende Daten an den lokalen Server…');
    const started = performance.now();
    let success = false;

    try {
      const resp = await fetch('/api/feedback/analyze', { method: 'POST', body: fd });
      if (!resp.ok || !resp.body) {
        let detail = `HTTP ${resp.status}`;
        try { detail = (await resp.json()).detail || detail; } catch { /* ignore */ }
        throw new Error(detail);
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let finished = false;
      while (!finished) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (!line.trim()) continue;
          const ev = JSON.parse(line);
          if (ev.status === 'progress') {
            const elapsed = Math.round((performance.now() - started) / 1000);
            this.setProgress(ev.percent, `${ev.phase} (${elapsed}s)`);
            this.appendLiveLog(`▶ ${ev.phase}`);
          } else if (ev.status === 'log') {
            this.progressLog.textContent = ev.message;
            this.appendLiveLog(ev.message);
          } else if (ev.status === 'section') {
            this.startLiveSection(ev.section, ev.index ?? null);
          } else if (ev.status === 'token') {
            this.queueLiveToken(ev.delta);
          } else if (ev.status === 'completed') {
            this.setProgress(100, 'Analyse abgeschlossen');
            this.appendLiveLog('✔ Analyse abgeschlossen – gefilterter Bericht wird angezeigt.');
            this.showReport(ev.report, `feedback_${this.selectedJob.original_name.replace(/\.[^.]+$/, '')}_${ev.feedback_id}.md`,
              { taskId: this.selectedJob.task_id, feedbackId: ev.feedback_id }, ev.open_questions || []);
            finished = true;
            success = true;
          } else if (ev.status === 'error') {
            throw new Error(ev.message);
          }
        }
      }
      if (!finished) throw new Error('Die Verbindung wurde vor Abschluss der Analyse beendet.');
      this.loadReports();
      this.loadJobs(this.selectedJob.task_id);
    } catch (e) {
      this.appendLiveLog(`✖ Fehler: ${(e as Error).message}`);
      this.opts.showError(`Die Feedback-Analyse ist fehlgeschlagen: ${(e as Error).message}`, 'Analyse fehlgeschlagen');
    } finally {
      this.finishLive(success);
      this.isAnalyzing = false;
      this.updateAnalyzeState();
      setTimeout(() => this.progress.classList.add('hidden'), 1200);
    }
    // Ask Gemma's open questions right away (user can answer or skip each one)
    if (success && this.openQuestions.some(q => q.answer === null)) this.openQuestionsModal();
  }

  private showReport(report: string, filename: string, ref: { taskId: string; feedbackId: string } | null,
    questions: OpenQuestion[], scroll = true) {
    this.currentReport = report;
    this.currentReportName = filename;
    this.currentReportRef = ref;
    this.openQuestions = questions;
    this.reportContent.innerHTML = renderReportMarkdown(report);
    this.resultSection.classList.remove('hidden');
    this.updateQuestionsButton();
    if (scroll) this.resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // -------------------------------------------------------------------------
  // Open questions (answered in a modal, written back into the report)
  // -------------------------------------------------------------------------

  private updateQuestionsButton() {
    const total = this.openQuestions.length;
    const answered = this.openQuestions.filter(q => q.answer).length;
    this.answerQuestionsBtn.classList.toggle('hidden', total === 0 || !this.currentReportRef);
    this.answerQuestionsBtn.textContent = answered
      ? `✏️ Antworten bearbeiten (${answered}/${total})`
      : `❓ Offene Fragen beantworten (${total})`;
  }

  private openQuestionsModal() {
    if (!this.openQuestions.length || !this.currentReportRef) return;
    this.draftAnswers = this.openQuestions.map(q => q.answer);
    const firstOpen = this.openQuestions.findIndex(q => q.answer === null);
    this.questionIdx = firstOpen >= 0 ? firstOpen : 0;
    this.questionsModal.classList.remove('hidden');
    this.renderQuestion();
  }

  private closeQuestionsModal() {
    if (this.isSavingAnswers) return;
    this.questionsModal.classList.add('hidden');
    this.answerQuestionsBtn.focus();
  }

  private renderQuestion() {
    const total = this.openQuestions.length;
    const i = this.questionIdx;
    this.questionCounter.textContent = `Frage ${i + 1} von ${total}`;
    // Model output may contain **bold** markers – show plain text
    this.questionText.textContent = this.openQuestions[i].question.replace(/\*\*/g, '');
    this.answerInput.value = this.draftAnswers[i] ?? '';
    this.questionPrevBtn.disabled = i === 0;
    this.questionNextBtn.textContent = i === total - 1 ? 'Antworten übernehmen ✓' : 'Weiter →';
    this.questionSteps.replaceChildren(...this.openQuestions.map((_, k) => {
      const dot = document.createElement('span');
      dot.className = 'fb-question-step'
        + (k === i ? ' is-current' : this.draftAnswers[k] ? ' is-answered' : '');
      return dot;
    }));
    this.answerInput.focus();
  }

  /** Stores the current input as draft (skip = no answer). */
  private storeDraft(skip: boolean) {
    const value = this.answerInput.value.trim();
    this.draftAnswers[this.questionIdx] = skip || !value ? null : value;
  }

  private nextQuestion(skip: boolean) {
    if (this.isSavingAnswers) return;
    this.storeDraft(skip);
    if (this.questionIdx < this.openQuestions.length - 1) {
      this.questionIdx += 1;
      this.renderQuestion();
    } else {
      this.saveAnswers();
    }
  }

  private prevQuestion() {
    if (this.questionIdx === 0 || this.isSavingAnswers) return;
    this.storeDraft(false);
    this.questionIdx -= 1;
    this.renderQuestion();
  }

  /** Persists all answers; the backend rewrites the "Offene Fragen" section of the report. */
  private async saveAnswers() {
    if (!this.currentReportRef) return;
    const { taskId, feedbackId } = this.currentReportRef;
    this.isSavingAnswers = true;
    [this.questionNextBtn, this.questionSkipBtn, this.questionPrevBtn].forEach(b => { b.disabled = true; });
    this.questionNextBtn.textContent = 'Speichere…';
    try {
      const resp = await fetch(`/api/feedback/reports/${taskId}/${feedbackId}/answers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answers: this.draftAnswers }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
      this.isSavingAnswers = false;
      this.closeQuestionsModal();
      this.showReport(data.report, this.currentReportName, this.currentReportRef, data.open_questions || [], false);
      this.flashButton(this.copyReportBtn, '📋 Kopieren (inkl. Antworten)');
    } catch (e) {
      this.isSavingAnswers = false;
      this.opts.showError(`Die Antworten konnten nicht gespeichert werden: ${(e as Error).message}`, 'Speichern fehlgeschlagen');
    } finally {
      this.isSavingAnswers = false;
      [this.questionNextBtn, this.questionSkipBtn].forEach(b => { b.disabled = false; });
      this.questionPrevBtn.disabled = this.questionIdx === 0;
      this.questionNextBtn.textContent = 'Antworten übernehmen ✓';
    }
  }

  // -------------------------------------------------------------------------
  // Stored reports
  // -------------------------------------------------------------------------

  private async loadReports() {
    try {
      const resp = await fetch('/api/feedback/reports');
      if (!resp.ok) return;
      const reports = (await resp.json()).reports as FeedbackReportSummary[];
      this.reportsSelect.innerHTML = '';
      this.reportsSelect.add(new Option(reports.length ? '-- Früheren Bericht öffnen --' : '-- Noch keine Berichte --', ''));
      for (const r of reports) {
        const date = r.created_at ? new Date(r.created_at * 1000).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' }) : r.feedback_id;
        this.reportsSelect.add(new Option(`${r.original_name || r.task_id} · ${date}`, `${r.task_id}/${r.feedback_id}`));
      }
    } catch (e) {
      console.error('Failed to load feedback reports:', e);
    }
  }

  private async openStoredReport(value: string) {
    if (!value) return;
    try {
      const resp = await fetch(`/api/feedback/reports/${value}`);
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
      this.showReport(data.report, `feedback_${data.feedback_id}.md`,
        { taskId: data.task_id, feedbackId: data.feedback_id }, data.open_questions || []);
    } catch (e) {
      this.opts.showError(`Bericht konnte nicht geladen werden: ${(e as Error).message}`, 'Bericht laden fehlgeschlagen');
    }
  }

  private flashButton(btn: HTMLButtonElement, text: string) {
    const original = btn.textContent;
    btn.textContent = text;
    setTimeout(() => { btn.textContent = original; }, 1500);
  }
}
