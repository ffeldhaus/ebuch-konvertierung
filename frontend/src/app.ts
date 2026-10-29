import { FeedbackController } from './feedback';
import { SettingsController } from './settings';

// Stepper and state management
type ProcessState = 'idle' | 'uploading' | 'extracting' | 'standardising' | 'ready_to_export' | 'completed' | 'error';
// Main application modes selectable via the header dropdown
type MainView = 'workspace' | 'benchmark' | 'feedback' | 'settings';

class AppController {
  // Top Header elements
  private togglePanePdfBtn = document.getElementById('toggle-pane-pdf') as HTMLButtonElement;
  private togglePaneRawBtn = document.getElementById('toggle-pane-raw') as HTMLButtonElement;
  private togglePaneStandardisedBtn = document.getElementById('toggle-pane-standardised') as HTMLButtonElement;
  private themeSelect = document.getElementById('theme-select') as HTMLSelectElement;
  
  // Sidebar elements
  private leftSidebar = document.getElementById('left-sidebar') as HTMLElement;
  private rightSidebar = document.getElementById('right-sidebar') as HTMLElement;
  private leftSidebarHandle = document.getElementById('left-sidebar-handle') as HTMLDivElement;
  private rightSidebarHandle = document.getElementById('right-sidebar-handle') as HTMLDivElement;
  private dropzone = document.getElementById('dropzone') as HTMLDivElement;
  private fileInput = document.getElementById('file-input') as HTMLInputElement;
  private fileStatus = document.getElementById('file-status') as HTMLDivElement;
  private selectedFileName = document.getElementById('selected-file-name') as HTMLSpanElement;
  private cancelFileBtn = document.getElementById('cancel-file-btn') as HTMLButtonElement;
  private processBtn = document.getElementById('process-btn') as HTMLButtonElement;
  private abortProcessBtn = document.getElementById('abort-process-btn') as HTMLButtonElement;
  private pipelineAbortBtn = document.getElementById('pipeline-abort-btn') as HTMLButtonElement;
  private activeAbortController: AbortController | null = null;
  // Bounded automatic reattach attempts after a dropped task stream (server job keeps running).
  private reconnectAttempts = 0;
  // Task whose log history was already replayed into the UI log (skip replays on reconnect).
  private replayedTaskId: string | null = null;
  private rulesetSelect = document.getElementById('ruleset-select') as HTMLSelectElement;
  private rulesetUploadZone = document.getElementById('ruleset-upload-zone') as HTMLDivElement;
  private rulesetFileInput = document.getElementById('ruleset-file-input') as HTMLInputElement;
  private rulesetStatusText = document.getElementById('ruleset-status-text') as HTMLParagraphElement;
  private rulesetActions = document.getElementById('ruleset-actions') as HTMLDivElement;
  private rulesetBadge = document.getElementById('ruleset-badge') as HTMLSpanElement;
  private inspectRulesetBtn = document.getElementById('inspect-ruleset-btn') as HTMLButtonElement;
  private rulesetModal = document.getElementById('ruleset-modal') as HTMLDivElement;
  private rulesetModalContent = document.getElementById('ruleset-modal-content') as HTMLDivElement;
  private rulesetModalStats = document.getElementById('ruleset-modal-stats') as HTMLSpanElement;
  private closeRulesetModalBtn = document.getElementById('close-ruleset-modal-btn') as HTMLButtonElement;
  private closeRulesetModalBtnBottom = document.getElementById('close-ruleset-modal-btn-bottom') as HTMLButtonElement;
  private copyRulesetBtn = document.getElementById('copy-ruleset-btn') as HTMLButtonElement;
  private parsedRulesetContent: string = '';
  private logsConsole = document.getElementById('logs-console') as HTMLDivElement;
  private toggleLogsBtn = document.getElementById('toggle-logs-btn') as HTMLButtonElement;
  private logsConsoleContainer = document.getElementById('logs-console-container') as HTMLDivElement;
  private logsArrow = document.getElementById('logs-arrow') as unknown as SVGElement;
  private toggleTasksBtn = document.getElementById('toggle-tasks-btn') as HTMLButtonElement;
  private tasksManagerContainer = document.getElementById('tasks-manager-container') as HTMLDivElement;
  private tasksArrow = document.getElementById('tasks-arrow') as unknown as SVGElement;
  private activeTasksBadge = document.getElementById('active-tasks-badge') as HTMLSpanElement;
  private tasksList = document.getElementById('tasks-list') as HTMLDivElement;
  private pagesSelectContainer = document.getElementById('pages-select-container') as HTMLDivElement;
  private pagesInput = document.getElementById('pages-input') as HTMLInputElement;
  private pagesInputError = document.getElementById('pages-input-error') as HTMLParagraphElement;
  private pagesInputErrorText = document.getElementById('pages-input-error-text') as HTMLSpanElement;
  private engineSelectContainer = document.getElementById('engine-select-container') as HTMLDivElement;
  private engineSelect = document.getElementById('engine-select') as HTMLSelectElement;
  private langSelectContainer = document.getElementById('lang-select-container') as HTMLDivElement;
  private langSelect = document.getElementById('lang-select') as HTMLSelectElement;
  private describeImagesToggle = document.getElementById('describe-images-toggle') as HTMLInputElement | null;

  // Split Panel containers
  private panelPdf = document.getElementById('panel-pdf-container') as HTMLElement;
  private panelRaw = document.getElementById('panel-raw-container') as HTMLElement;
  private panelStandardised = document.getElementById('panel-standardised-container') as HTMLElement;
  
  private pdfViewerFrame = document.getElementById('pdf-viewer-frame') as HTMLIFrameElement;
  
  // Textareas
  private rawMarkdownTextarea = document.getElementById('raw-markdown-textarea') as HTMLTextAreaElement;
  private standardisedMarkdownTextarea = document.getElementById('standardised-markdown-textarea') as HTMLTextAreaElement;
  private rawMarkdownRendered = document.getElementById('raw-markdown-rendered') as HTMLDivElement;
  private standardisedMarkdownRendered = document.getElementById('standardised-markdown-rendered') as HTMLDivElement;
  private standardisedMarkdownDiff = document.getElementById('standardised-markdown-diff') as HTMLDivElement;
  private diffViewContent = document.getElementById('diff-view-content') as HTMLDivElement;

  // Toolbars & Buttons
  private toolbarRaw = document.getElementById('toolbar-raw') as HTMLDivElement;
  private toolbarStandardised = document.getElementById('toolbar-standardised') as HTMLDivElement;
  private btnRenderRaw = document.getElementById('btn-render-raw') as HTMLButtonElement;
  private btnEditStandardised = document.getElementById('btn-edit-standardised') as HTMLButtonElement;
  private btnRenderStandardised = document.getElementById('btn-render-standardised') as HTMLButtonElement;
  private btnDiffStandardised = document.getElementById('btn-diff-standardised') as HTMLButtonElement;
  private optimizationPromptInput = document.getElementById('optimization-prompt-input') as HTMLInputElement;
  private btnOptimize = document.getElementById('btn-optimize') as HTMLButtonElement;

  // Right Export Panel
  private templateModeSelect = document.getElementById('template-mode-select') as HTMLSelectElement;
  private templateUploadContainer = document.getElementById('template-upload-container') as HTMLDivElement;
  private templateUploadZone = document.getElementById('template-upload-zone') as HTMLDivElement;
  private templateFileInput = document.getElementById('template-file-input') as HTMLInputElement;
  private templateStatusText = document.getElementById('template-status-text') as HTMLParagraphElement;
  
  private downloadActions = document.getElementById('download-actions') as HTMLDivElement;
  private downloadRawBtn = document.getElementById('download-raw-btn') as HTMLButtonElement;
  private downloadStandardBtn = document.getElementById('download-standard-btn') as HTMLButtonElement;
  private downloadDocxBtn = document.getElementById('download-docx-btn') as HTMLButtonElement;
  
  // Progress Bar elements
  private progressContainer = document.getElementById('pipeline-progress-container') as HTMLDivElement;
  private progressPhase = document.getElementById('pipeline-progress-phase') as HTMLSpanElement;
  private progressPages = document.getElementById('pipeline-progress-pages') as HTMLSpanElement;
  private progressBar = document.getElementById('pipeline-progress-bar') as HTMLDivElement;
  private progressPercent = document.getElementById('pipeline-progress-percent') as HTMLSpanElement;

  // Stepper steps
  private step1 = document.getElementById('step-1-indicator') as HTMLDivElement;
  private step2 = document.getElementById('step-2-indicator') as HTMLDivElement;
  private step3 = document.getElementById('step-3-indicator') as HTMLDivElement;
  private step4 = document.getElementById('step-4-indicator') as HTMLDivElement;

  // Modal elements
  private errorModal = document.getElementById('error-modal') as HTMLDivElement;
  private errorModalTitle = document.getElementById('error-modal-title') as HTMLHeadingElement;
  private errorModalMessage = document.getElementById('error-modal-message') as HTMLParagraphElement;
  private errorModalCloseBtn = document.getElementById('error-modal-close-btn') as HTMLButtonElement;

  private pdfPagePillsContainer = document.getElementById('pdf-page-pills-container') as HTMLElement;

  // Interactive Grounding BBox Overlay elements
  private btnToggleBboxOverlay = document.getElementById('btn-toggle-bbox-overlay') as HTMLButtonElement | null;
  private pdfBboxViewer = document.getElementById('pdf-bbox-viewer') as HTMLDivElement | null;
  private bboxPrevPageBtn = document.getElementById('bbox-prev-page') as HTMLButtonElement | null;
  private bboxNextPageBtn = document.getElementById('bbox-next-page') as HTMLButtonElement | null;
  private bboxPageIndicator = document.getElementById('bbox-page-indicator') as HTMLSpanElement | null;
  private bboxFilterChips = document.getElementById('bbox-filter-chips') as HTMLDivElement | null;
  private bboxPageImg = document.getElementById('bbox-page-img') as HTMLImageElement | null;
  private bboxOverlayLayer = document.getElementById('bbox-overlay-layer') as HTMLDivElement | null;

  // Eurobraille / ISO 8859-1 (> U+00FF) Character Replacement Assistant elements
  private btnCharReplacements = document.getElementById('btn-char-replacements') as HTMLButtonElement | null;
  private charReplaceBadge = document.getElementById('char-replace-badge') as HTMLSpanElement | null;
  private charReplaceModal = document.getElementById('char-replace-modal') as HTMLDivElement | null;
  private closeCharReplaceModalBtn = document.getElementById('close-char-replace-modal') as HTMLButtonElement | null;
  private cancelCharReplaceModalBtn = document.getElementById('cancel-char-replace-modal') as HTMLButtonElement | null;
  private btnSuggestCharReplacements = document.getElementById('btn-suggest-char-replacements') as HTMLButtonElement | null;
  private btnExportCharMap = document.getElementById('btn-export-char-map') as HTMLButtonElement | null;
  private btnImportCharMap = document.getElementById('btn-import-char-map') as HTMLButtonElement | null;
  private charMapFileInput = document.getElementById('char-map-file-input') as HTMLInputElement | null;
  private charReplaceStatus = document.getElementById('char-replace-status') as HTMLSpanElement | null;
  private charReplaceTbody = document.getElementById('char-replace-tbody') as HTMLTableSectionElement | null;
  private btnApplyCharReplacements = document.getElementById('btn-apply-char-replacements') as HTMLButtonElement | null;

  // Top Navigation Tabs & Views
  private mainModeSelect = document.getElementById('main-mode-select') as HTMLSelectElement;
  private headerStepper = document.getElementById('header-stepper') as HTMLDivElement;
  private headerPaneToggles = document.getElementById('header-pane-toggles') as HTMLDivElement;
  private mainWorkspaceView = document.getElementById('main-workspace-view') as HTMLDivElement;
  private mainBenchmarkView = document.getElementById('main-benchmark-view') as HTMLDivElement;
  private mainFeedbackView = document.getElementById('main-feedback-view') as HTMLDivElement;
  private feedbackController: FeedbackController | null = null;
  private mainSettingsView = document.getElementById('main-settings-view') as HTMLDivElement | null;
  private settingsController: SettingsController | null = null;

  // Benchmark Elements
  private startCustomBenchmarkBtn = document.getElementById('start-custom-benchmark-btn') as HTMLButtonElement;
  private benchSourceDropzone = document.getElementById('bench-source-dropzone') as HTMLDivElement;
  private benchSourceFileInput = document.getElementById('bench-source-file-input') as HTMLInputElement;
  private benchSourceFilename = document.getElementById('bench-source-filename') as HTMLParagraphElement;
  private benchSourceBadge = document.getElementById('bench-source-badge') as HTMLSpanElement;
  private benchGtDropzone = document.getElementById('bench-gt-dropzone') as HTMLDivElement;
  private benchGtFileInput = document.getElementById('bench-gt-file-input') as HTMLInputElement;
  private benchGtFilename = document.getElementById('bench-gt-filename') as HTMLParagraphElement;
  private benchGtBadge = document.getElementById('bench-gt-badge') as HTMLSpanElement;
  private benchRulesDropzone = document.getElementById('bench-rules-dropzone') as HTMLDivElement;
  private benchRulesFileInput = document.getElementById('bench-rules-file-input') as HTMLInputElement;
  private benchRulesFilename = document.getElementById('bench-rules-filename') as HTMLParagraphElement;
  private benchRulesBadge = document.getElementById('bench-rules-badge') as HTMLSpanElement;
  private benchCustomRulesTextarea = document.getElementById('bench-custom-rules-textarea') as HTMLTextAreaElement;
  private benchRulesetSelect = document.getElementById('bench-ruleset-select') as HTMLSelectElement;
  private benchPagesInput = document.getElementById('bench-pages-input') as HTMLInputElement;
  private benchPagesInputError = document.getElementById('bench-pages-input-error') as HTMLParagraphElement;
  private benchPagesInputErrorText = document.getElementById('bench-pages-input-error-text') as HTMLSpanElement;
  private benchEngInfinity = document.getElementById('bench-eng-infinity') as HTMLInputElement;
  private benchEngLightonocr = document.getElementById('bench-eng-lightonocr') as HTMLInputElement;
  private benchEngDocling = document.getElementById('bench-eng-docling') as HTMLInputElement;
  private benchLiveStatus = document.getElementById('bench-live-status') as HTMLDivElement;
  private benchLivePhase = document.getElementById('bench-live-phase') as HTMLParagraphElement;
  private benchResultsSection = document.getElementById('bench-results-section') as HTMLDivElement;
  private benchRankingCards = document.getElementById('bench-ranking-cards') as HTMLDivElement;
  private benchMatrixTbody = document.getElementById('bench-matrix-tbody') as HTMLTableSectionElement;
  private benchDiffEngineSelect = document.getElementById('bench-diff-engine-select') as HTMLSelectElement;
  private benchDownloadDocxBtn = document.getElementById('bench-download-docx-btn') as HTMLAnchorElement;
  private benchHistorySelect = document.getElementById('bench-history-select') as HTMLSelectElement;
  private benchDeleteHistoryBtn = document.getElementById('bench-delete-history-btn') as HTMLButtonElement;
  private benchSkipEngineBtn = document.getElementById('bench-skip-engine-btn') as HTMLButtonElement;
  private benchAbortBtn = document.getElementById('bench-abort-btn') as HTMLButtonElement;
  private benchLiveProgressPct = document.getElementById('bench-live-progress-pct') as HTMLSpanElement;
  private benchLiveProgressBar = document.getElementById('bench-live-progress-bar') as HTMLDivElement;
  private benchLiveStepBadge = document.getElementById('bench-live-step-badge') as HTMLSpanElement;
  private benchLiveLogs = document.getElementById('bench-live-logs') as HTMLDivElement;
  private benchTabBtnDiff = document.getElementById('bench-tab-btn-diff') as HTMLButtonElement;
  private benchTabBtnRaw = document.getElementById('bench-tab-btn-raw') as HTMLButtonElement;
  private benchTabBtnStd = document.getElementById('bench-tab-btn-std') as HTMLButtonElement;
  private benchTabBtnJudge = document.getElementById('bench-tab-btn-judge') as HTMLButtonElement;
  private benchTabPaneDiff = document.getElementById('bench-tab-pane-diff') as HTMLDivElement;
  private benchTabPaneRaw = document.getElementById('bench-tab-pane-raw') as HTMLDivElement;
  private benchTabPaneStd = document.getElementById('bench-tab-pane-std') as HTMLDivElement;
  private benchTabPaneJudge = document.getElementById('bench-tab-pane-judge') as HTMLDivElement;
  private benchReevaluateBtn = document.getElementById('bench-reevaluate-btn') as HTMLButtonElement;
  private benchReevaluateIcon = document.getElementById('bench-reevaluate-icon') as HTMLSpanElement;
  private benchReevaluateText = document.getElementById('bench-reevaluate-text') as HTMLSpanElement;

  private activeFile: File | null = null;
  private activeBenchSourceFile: File | null = null;
  private activeBenchGtFile: File | null = null;
  private activeBenchRulesFile: File | null = null;
  private activeBenchSourcePageCount: number = 0;
  private activeBenchPhysicalStartPage: number = 1;
  private benchEvaluationResults: any = null;
  private activeBenchmarkTaskId: string | null = null;
  private benchmarkPollInterval: any = null;
  private taskId: string | null = null;
  private activePageCount: number = 0;
  private physicalStartPage: number = 1;
  private currentPdfPage: number = -1;
  private currentRawMarkdown: string = '';
  private currentStandardisedMarkdown: string = '';

  // Pane toggles state
  private isPdfPaneVisible = false;
  private isRawPaneVisible = false;
  private isStandardisedPaneVisible = true;
  private isLeftSidebarCollapsed = false;
  private isRightSidebarCollapsed = false;
  private isScrollSyncEnabled = true;
  private activeScrollSource: HTMLElement | null = null;
  private scrollTimeout: any = null;

  // Rendering toggle states
  private isRawRendered = false;
  private isStandardisedRendered = false;

  // Grounding BBox Overlay state
  private isBboxOverlayActive = false;
  private currentBboxPageIdx = 0;
  private activeBboxFilter = 'all';
  private layoutCache = new Map<string, {
    physical_start_page: number;
    blocks: Array<{
      type: string;
      text: string;
      page_idx: number;
      bbox_1000: number[];
      text_level?: number | null;
      is_callout_box?: boolean;
    }>;
  }>();

  // Eurobraille Character Replacement state
  private charReplacements = new Map<string, { replacement: string; active: boolean }>();

  constructor() {
    if (this.describeImagesToggle) {
      this.describeImagesToggle.checked = true;
    }
    if (this.engineSelect) {
      this.engineSelect.value = 'infinity';
    }
    this.loadCharReplacementsFromStorage();
    this.initEventListeners();
    this.initBboxOverlayEvents();
    this.initCharReplacementEvents();
    this.handleEngineChange();
    this.updatePaneVisibility();
    this.initTaskManager();
    this.initTheme();
    this.initAccessibility();
    this.initScrollSync();
    this.initBenchmarkEvents();
    this.updateRulesetUploadState(false);
    this.updateCharReplaceBadge();
  }

  private initEventListeners() {
    // Collapsible left sidebar via divider handle
    this.leftSidebarHandle.addEventListener('click', () => {
      this.isLeftSidebarCollapsed = !this.isLeftSidebarCollapsed;
      this.leftSidebarHandle.setAttribute('aria-expanded', (!this.isLeftSidebarCollapsed).toString());
      if (this.isLeftSidebarCollapsed) {
        this.leftSidebar.style.width = '0px';
      } else {
        this.leftSidebar.style.width = '320px';
      }
    });

    // Collapsible right sidebar via divider handle
    this.rightSidebarHandle.addEventListener('click', () => {
      this.isRightSidebarCollapsed = !this.isRightSidebarCollapsed;
      this.rightSidebarHandle.setAttribute('aria-expanded', (!this.isRightSidebarCollapsed).toString());
      if (this.isRightSidebarCollapsed) {
        this.rightSidebar.style.width = '0px';
      } else {
        this.rightSidebar.style.width = '288px';
      }
    });

    // Collapsible Live-Log accordion
    let isLogsConsoleOpen = false;
    this.toggleLogsBtn.addEventListener('click', () => {
      isLogsConsoleOpen = !isLogsConsoleOpen;
      if (isLogsConsoleOpen) {
        this.logsConsoleContainer.classList.remove('hidden');
        this.logsArrow.classList.add('rotate-90');
        this.logsConsole.scrollTop = this.logsConsole.scrollHeight;
      } else {
        this.logsConsoleContainer.classList.add('hidden');
        this.logsArrow.classList.remove('rotate-90');
      }
    });

    // Pane display toggles
    this.togglePanePdfBtn.addEventListener('click', () => {
      this.isPdfPaneVisible = !this.isPdfPaneVisible;
      this.updatePaneVisibility();
    });
    this.togglePaneRawBtn.addEventListener('click', () => {
      this.isRawPaneVisible = !this.isRawPaneVisible;
      this.updatePaneVisibility();
    });
    this.togglePaneStandardisedBtn.addEventListener('click', () => {
      this.isStandardisedPaneVisible = !this.isStandardisedPaneVisible;
      // Guarantee at least one pane is visible
      if (!this.isPdfPaneVisible && !this.isRawPaneVisible && !this.isStandardisedPaneVisible) {
        this.isStandardisedPaneVisible = true;
      }
      this.updatePaneVisibility();
    });

    // File input selections
    this.dropzone.addEventListener('click', () => this.fileInput.click());
    this.fileInput.addEventListener('change', (e) => this.handleFileSelect(e));
    
    // Drag-and-drop zone handlers
    this.dropzone.addEventListener('dragover', (e) => {
      e.preventDefault();
      this.dropzone.classList.add('border-indigo-500', 'bg-indigo-500/10');
    });
    this.dropzone.addEventListener('dragleave', () => {
      this.dropzone.classList.remove('border-indigo-500', 'bg-indigo-500/10');
    });
    this.dropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      this.dropzone.classList.remove('border-indigo-500', 'bg-indigo-500/10');
      if (e.dataTransfer?.files.length) {
        this.setFile(e.dataTransfer.files[0]);
      }
    });

    this.cancelFileBtn.addEventListener('click', () => this.resetFile());
    this.engineSelect.addEventListener('change', () => this.handleEngineChange());
    this.pagesInput.addEventListener('input', () => this.notifyParametersChanged());
    this.pagesInput.addEventListener('change', () => this.notifyParametersChanged());
    this.langSelect.addEventListener('change', () => this.notifyParametersChanged());
    this.rulesetSelect.addEventListener('change', () => this.notifyParametersChanged());

    // Error modal event listeners
    this.errorModalCloseBtn.addEventListener('click', () => this.hideErrorModal());
    this.errorModal.addEventListener('click', (e) => {
      if (e.target === this.errorModal) {
        this.hideErrorModal();
      }
    });
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !this.errorModal.classList.contains('hidden')) {
        this.hideErrorModal();
      }
    });

    // Textarea input & page pill updates
    this.standardisedMarkdownTextarea.addEventListener('input', () => {
      this.updatePagePills();
      this.updateCharReplaceBadge();
    });
    this.rawMarkdownTextarea.addEventListener('input', () => {
      this.updateCharReplaceBadge();
    });

    // Bidirectional cursor tracking: sync editor cursor position to PDF page
    const syncCursorToPdf = () => {
      const text = this.standardisedMarkdownTextarea.value;
      const cursorPos = this.standardisedMarkdownTextarea.selectionStart;
      const textBefore = text.slice(0, cursorPos);
      const matches = [...textBefore.matchAll(/\(\((\d+)\)\)/g)];
      if (matches.length > 0) {
        const activePage = parseInt(matches[matches.length - 1][1], 10);
        this.updatePdfPage(activePage);
        this.highlightPagePill(activePage);
      }
    };
    this.standardisedMarkdownTextarea.addEventListener('click', syncCursorToPdf);
    this.standardisedMarkdownTextarea.addEventListener('keyup', syncCursorToPdf);

    // Process button triggers pipeline
    this.processBtn.addEventListener('click', () => this.startProcessing());

    // Markdown render toggles
    this.btnRenderRaw.addEventListener('click', () => this.toggleRawRender());
    // Panel 3 mode switcher
    this.btnEditStandardised.addEventListener('click', () => this.setStandardisedPanelMode('edit'));
    this.btnRenderStandardised.addEventListener('click', () => this.setStandardisedPanelMode('preview'));
    this.btnDiffStandardised.addEventListener('click', () => this.setStandardisedPanelMode('diff'));

    // Quick markdown toolbar helper tags insertion
    this.initToolbarHelper(this.toolbarRaw, this.rawMarkdownTextarea);
    this.initToolbarHelper(this.toolbarStandardised, this.standardisedMarkdownTextarea);

    // Style layout templates upload zone trigger
    this.templateModeSelect.addEventListener('change', () => this.handleTemplateModeChange());
    this.templateUploadZone.addEventListener('click', () => this.templateFileInput.click());
    this.templateFileInput.addEventListener('change', () => this.handleTemplateSelect());

    // Custom ruleset upload trigger & inspection
    this.rulesetUploadZone.addEventListener('click', () => {
      if (this.taskId && !this.rulesetFileInput.disabled) {
        this.rulesetFileInput.click();
      }
    });
    this.rulesetFileInput.addEventListener('change', () => this.handleRulesetSelect());
    if (this.inspectRulesetBtn) {
      this.inspectRulesetBtn.addEventListener('click', () => this.openRulesetModal());
    }
    if (this.closeRulesetModalBtn) {
      this.closeRulesetModalBtn.addEventListener('click', () => this.closeRulesetModal());
    }
    if (this.closeRulesetModalBtnBottom) {
      this.closeRulesetModalBtnBottom.addEventListener('click', () => this.closeRulesetModal());
    }
    if (this.rulesetModal) {
      this.rulesetModal.addEventListener('click', (e) => {
        if (e.target === this.rulesetModal) this.closeRulesetModal();
      });
    }
    if (this.copyRulesetBtn) {
      this.copyRulesetBtn.addEventListener('click', () => {
        navigator.clipboard.writeText(this.parsedRulesetContent || '');
        const prevHtml = this.copyRulesetBtn.innerHTML;
        this.copyRulesetBtn.innerHTML = '<span>✓</span><span>Kopiert!</span>';
        setTimeout(() => {
          if (this.copyRulesetBtn) this.copyRulesetBtn.innerHTML = prevHtml;
        }, 2000);
      });
    }

    // Export button actions
    this.downloadRawBtn.addEventListener('click', () => this.downloadTextFile('raw-extracted.md', this.rawMarkdownTextarea.value));
    this.downloadStandardBtn.addEventListener('click', () => this.downloadTextFile('ebuch-standardised.md', this.standardisedMarkdownTextarea.value));
    this.downloadDocxBtn.addEventListener('click', () => this.triggerDocxExport());

    // Abort conversion button actions
    if (this.abortProcessBtn) {
      this.abortProcessBtn.addEventListener('click', () => this.abortCurrentConversion());
    }
    if (this.pipelineAbortBtn) {
      this.pipelineAbortBtn.addEventListener('click', () => this.abortCurrentConversion());
    }

    // Workspace pages input blur & input validation
    if (this.pagesInput) {
      this.pagesInput.addEventListener('blur', () => {
        const val = this.pagesInput.value.trim();
        if (!val) {
          this.clearInputError(this.pagesInput, this.pagesInputError);
          return;
        }
        if (this.activePageCount > 0) {
          const validation = this.validatePages(val, this.activePageCount, this.physicalStartPage);
          if (!validation.isValid) {
            this.showInputError(this.pagesInput, this.pagesInputError, this.pagesInputErrorText, validation.error || 'Ungültige Seitenauswahl.');
          } else {
            this.clearInputError(this.pagesInput, this.pagesInputError);
          }
        }
      });
      this.pagesInput.addEventListener('input', () => {
        const val = this.pagesInput.value.trim();
        if (!val || this.activePageCount === 0) {
          this.clearInputError(this.pagesInput, this.pagesInputError);
          return;
        }
        const validation = this.validatePages(val, this.activePageCount, this.physicalStartPage);
        if (validation.isValid) {
          this.clearInputError(this.pagesInput, this.pagesInputError);
        }
      });
    }

    // Optimization actions
    this.btnOptimize.addEventListener('click', () => this.optimizeTask());
    this.optimizationPromptInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        this.optimizeTask();
      }
    });
  }

  private updatePaneVisibility() {
    const activeClass = 'bg-indigo-600 border-indigo-500 text-white';
    const inactiveClass = 'bg-slate-800 border-slate-700 text-slate-400 hover:text-white';

    // 1. Update header button visual states
    this.togglePanePdfBtn.className = `px-2.5 py-1.5 rounded-md font-semibold transition-all duration-150 text-xs ${this.isPdfPaneVisible ? activeClass : inactiveClass}`;
    this.togglePaneRawBtn.className = `px-2.5 py-1.5 rounded-md font-semibold transition-all duration-150 text-xs ${this.isRawPaneVisible ? activeClass : inactiveClass}`;
    this.togglePaneStandardisedBtn.className = `px-2.5 py-1.5 rounded-md font-semibold transition-all duration-150 text-xs ${this.isStandardisedPaneVisible ? activeClass : inactiveClass}`;

    // 2. Toggle pane classes
    if (this.isPdfPaneVisible) this.panelPdf.classList.remove('hidden');
    else this.panelPdf.classList.add('hidden');

    if (this.isRawPaneVisible) this.panelRaw.classList.remove('hidden');
    else this.panelRaw.classList.add('hidden');

    if (this.isStandardisedPaneVisible) this.panelStandardised.classList.remove('hidden');
    else this.panelStandardised.classList.add('hidden');
  }

  private initToolbarHelper(toolbar: HTMLDivElement, textarea: HTMLTextAreaElement) {
    const buttons = toolbar.querySelectorAll('button');
    buttons.forEach((btn) => {
      btn.addEventListener('click', () => {
        const tag = btn.getAttribute('data-tag');
        if (tag) {
          this.insertOrWrapAtCursor(textarea, tag);
        }
      });
    });
  }

  private insertOrWrapAtCursor(textarea: HTMLTextAreaElement, tag: string) {
    const startPos = textarea.selectionStart;
    const endPos = textarea.selectionEnd;
    const value = textarea.value;
    const selectedText = value.substring(startPos, endPos);
    
    let insertion: string;
    
    // Wrap markers if select exists
    if (tag === '*' || tag === '%' || tag === '_') {
      insertion = `${tag}${selectedText || 'Text'}${tag}`;
    } else if (tag.includes('  ')) {
      // E.g. "<L>  </L>", parse by double space and insert selection inside
      const parts = tag.split('  ');
      insertion = `${parts[0]}${selectedText || ''}${parts[1]}`;
    } else {
      insertion = `${tag}${selectedText}`;
    }
    
    textarea.value = value.substring(0, startPos) + insertion + value.substring(endPos, value.length);
    textarea.selectionStart = textarea.selectionEnd = startPos + insertion.length;
    textarea.focus();
    
    // Auto-update rendered preview if it is currently displayed
    if (textarea === this.rawMarkdownTextarea && this.isRawRendered) {
      this.updateRawRenderPreview();
    } else if (textarea === this.standardisedMarkdownTextarea && this.isStandardisedRendered) {
      this.updateStandardisedRenderPreview();
    }
    this.updateCharReplaceBadge();
  }

  private parseMarkdownTables(text: string): string {
    return text.replace(/(?:^[ \t]*\|.+?\|[ \t]*(?:\r?\n|$)){2,}/gm, (tableMatch) => {
      const lines = tableMatch.trim().split(/\r?\n/).map(l => l.trim()).filter(Boolean);
      if (lines.length < 2) return tableMatch;

      let headerLine = '';
      const bodyLines: string[] = [];

      for (let idx = 0; idx < lines.length; idx++) {
        const line = lines[idx];
        const inner = line.replace(/^\||\|$/g, '').trim();
        // Check if delimiter row (|---|---| or |:---:|)
        if (/^[\s|:-]+$/.test(inner)) {
          if (idx === 1 && !headerLine && lines[0]) {
            headerLine = lines[0];
          }
          continue;
        }
        if (idx === 0) {
          headerLine = line;
        } else {
          bodyLines.push(line);
        }
      }

      const parseCells = (l: string) => l.replace(/^\||\|$/g, '').split('|').map(c => c.trim());

      let html = '<div class="overflow-x-auto my-3"><table class="w-full text-left text-xs text-slate-300 border-collapse bg-slate-900/60 rounded-lg border border-slate-800">';
      
      if (headerLine) {
        const headers = parseCells(headerLine);
        html += '<thead class="bg-slate-950/80 text-slate-200 border-b border-slate-800"><tr>';
        for (const h of headers) {
          html += `<th class="py-2 px-3 font-semibold">${h}</th>`;
        }
        html += '</tr></thead>';
      }

      html += '<tbody class="divide-y divide-slate-800/60">';
      for (const rowLine of bodyLines) {
        const cells = parseCells(rowLine);
        html += '<tr class="hover:bg-slate-800/30 transition-colors">';
        for (const cell of cells) {
          html += `<td class="py-2 px-3">${cell}</td>`;
        }
        html += '</tr>';
      }
      html += '</tbody></table></div>';
      return html;
    });
  }

  private renderMarkdownToHtml(markdown: string): string {
    if (!markdown) return '<p class="text-slate-500 italic">Kein Inhalt vorhanden.</p>';
    
    let resolvedMarkdown = markdown;
    if (this.taskId) {
      resolvedMarkdown = resolvedMarkdown.replace(
        /!\[([\s\S]*?)\]\((?:images\/)?([^)]+)\)/g,
        (_match, alt, filename) => {
          return `![${alt}](/api/tasks/${this.taskId}/images/${filename})`;
        }
      );
    }
    
    let html = resolvedMarkdown;
    
    // Basic escapes to prevent layout breaking
    html = html.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    
    // Unescape table-related HTML tags so they render properly
    html = html.replace(/&lt;(\/?(?:table|thead|tbody|tfoot|tr|th|td)\b[\s\S]*?)&gt;/gi, '<$1>');
    
    // Render E-Buch Tags
    html = html.replace(/&lt;Bild&gt;(.*?)&lt;\/Bild&gt;/gi, '<div class="my-3 p-3 bg-indigo-950/20 border border-indigo-800/40 rounded-lg"><strong class="text-indigo-400">Bild:</strong> $1</div>');
    
    // Render <Tabelle> blocks (supporting GFM pipe tables and tab-separated rows)
    html = html.replace(/&lt;Tabelle&gt;([\s\S]*?)&lt;\/Tabelle&gt;/gi, (_m, content) => {
      let inner = content.trim();
      if (inner.includes('|')) {
        inner = this.parseMarkdownTables(inner);
      } else if (inner.includes('\t')) {
        const lines = inner.split(/\r?\n/).filter(Boolean);
        inner = '<div class="overflow-x-auto my-2"><table class="w-full text-left text-xs text-slate-300 border-collapse bg-slate-900/60 rounded-lg border border-slate-800"><tbody class="divide-y divide-slate-800/60">';
        for (const line of lines) {
          const cells = line.split('\t').map((c: string) => c.trim());
          inner += '<tr class="hover:bg-slate-800/30 transition-colors">';
          for (const cell of cells) {
            inner += `<td class="py-2 px-3">${cell}</td>`;
          }
          inner += '</tr>';
        }
        inner += '</tbody></table></div>';
      }
      return `<div class="my-3 p-3 bg-slate-900 border border-slate-800 rounded-lg"><strong class="text-slate-400 block mb-1">Tabelle:</strong>${inner}</div>`;
    });
    
    // Also parse standalone Markdown pipe tables outside <Tabelle>
    html = this.parseMarkdownTables(html);

    html = html.replace(/&lt;Rahmen&gt;(.*?)&lt;\/Rahmen&gt;/gi, '<div class="my-3 p-4 bg-slate-900 border-l-4 border-indigo-500 rounded-r-lg"><strong class="text-indigo-400">Merksatz/Rahmen:</strong> $1</div>');
    html = html.replace(/&lt;Anmerkung&gt;(.*?)&lt;\/Anmerkung&gt;/gi, '<div class="my-3 p-3 bg-amber-950/20 border border-amber-800/40 rounded-lg text-amber-300"><strong class="text-amber-400">Anmerkung:</strong> $1</div>');
    
    // Math blocks
    html = html.replace(/&lt;L&gt;(.*?)&lt;\/L&gt;/gi, '<code class="px-1.5 py-0.5 bg-slate-900 border border-slate-800 rounded text-pink-400">$1</code>');
    
    // Standard Headings
    html = html.replace(/^### (.*$)/gim, '<h3 class="text-sm font-bold text-slate-200 mt-4 mb-1">$1</h3>');
    html = html.replace(/^## (.*$)/gim, '<h2 class="text-sm font-bold text-slate-200 mt-4 mb-1">$1</h2>');
    html = html.replace(/^# (.*$)/gim, '<h1 class="text-base font-bold text-white mt-5 mb-2">$1</h1>');
    
    // List item mapping
    html = html.replace(/^-\t(.*$)/gim, '<li class="ml-4 list-disc text-slate-350">$1</li>');
    
    // Page indicators
    html = html.replace(/\(\((\d+)\)\)/g, '<div data-page-anchor="$1" class="text-[9px] font-bold text-slate-500 border-t border-slate-800/50 pt-1.5 my-3">Seite $1</div>');
    
    // Formatting marks
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.*?)\*/g, '<strong>$1</strong>');
    html = html.replace(/%(.*?)%/g, '<em>$1</em>');
    html = html.replace(/(?<![\w/])_([^_]+)_(?![\w])/g, '<u>$1</u>');

    // Render Markdown Images (after formatting marks to preserve image URLs)
    html = html.replace(/!\[([\s\S]*?)\]\((.*?)\)/g, '<div class="my-2"><img src="$2" alt="$1" class="max-h-60 rounded border border-slate-700 bg-slate-950/40 p-1" /></div>');
    
    // Line breaks
    html = html.replace(/\n/g, '<br>');
    // Clean up unwanted <br> tags inside and around table/div blocks
    html = html.replace(/(<\/?(?:table|thead|tbody|tfoot|tr|th|td|div)\b[^>]*>)\s*<br>/gi, '$1');
    html = html.replace(/<br>\s*(<\/?(?:table|thead|tbody|tfoot|tr|th|td|div)\b)/gi, '$1');
    
    return html;
  }

  private toggleRawRender() {
    this.isRawRendered = !this.isRawRendered;
    if (this.isRawRendered) {
      this.btnRenderRaw.textContent = 'Editor';
      this.btnRenderRaw.classList.add('bg-indigo-600', 'border-indigo-500');
      this.btnRenderRaw.classList.remove('bg-slate-800', 'border-slate-700');
      this.rawMarkdownTextarea.classList.add('hidden');
      this.rawMarkdownRendered.classList.remove('hidden');
      this.updateRawRenderPreview();
    } else {
      this.btnRenderRaw.textContent = 'Rendern';
      this.btnRenderRaw.classList.remove('bg-indigo-600', 'border-indigo-500');
      this.btnRenderRaw.classList.add('bg-slate-800', 'border-slate-700');
      this.rawMarkdownRendered.classList.add('hidden');
      this.rawMarkdownTextarea.classList.remove('hidden');
    }
  }

  private updateRawRenderPreview() {
    this.rawMarkdownRendered.innerHTML = this.renderMarkdownToHtml(this.rawMarkdownTextarea.value);
  }

  private setStandardisedPanelMode(mode: 'edit' | 'preview' | 'diff') {
    const activeClass = 'bg-indigo-600 border-indigo-500 text-white';
    const inactiveClass = 'bg-slate-800 border-slate-700 text-slate-350 hover:text-white';
    
    // 1. Reset all button visual states
    this.btnEditStandardised.className = `px-2 py-0.5 rounded text-[10px] font-semibold transition-colors ${mode === 'edit' ? activeClass : inactiveClass}`;
    this.btnRenderStandardised.className = `px-2 py-0.5 rounded text-[10px] font-semibold transition-colors ${mode === 'preview' ? activeClass : inactiveClass}`;
    this.btnDiffStandardised.className = `px-2 py-0.5 rounded text-[10px] font-semibold transition-colors ${mode === 'diff' ? activeClass : inactiveClass}`;
    
    // 2. Toggle content and toolbar visibility
    this.standardisedMarkdownTextarea.classList.add('hidden');
    this.standardisedMarkdownRendered.classList.add('hidden');
    this.standardisedMarkdownDiff.classList.add('hidden');
    this.toolbarStandardised.classList.add('hidden');
    
    if (mode === 'edit') {
      this.standardisedMarkdownTextarea.classList.remove('hidden');
      this.toolbarStandardised.classList.remove('hidden');
    } else if (mode === 'preview') {
      this.standardisedMarkdownRendered.classList.remove('hidden');
      this.updateStandardisedRenderPreview();
    } else if (mode === 'diff') {
      this.standardisedMarkdownDiff.classList.remove('hidden');
      this.updateDiffView();
    }
  }

  private updateStandardisedRenderPreview() {
    this.standardisedMarkdownRendered.innerHTML = this.renderMarkdownToHtml(this.standardisedMarkdownTextarea.value);
  }

  private async updateDiffView() {
    this.diffViewContent.innerHTML = '<div class="text-slate-400 italic">Berechne Differenzen...</div>';
    
    const rawVal = this.rawMarkdownTextarea.value;
    const stdVal = this.standardisedMarkdownTextarea.value;
    
    try {
      const response = await fetch('/api/diff', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ raw: rawVal, std: stdVal })
      });
      
      if (!response.ok) {
        throw new Error('Differenzberechnung fehlgeschlagen.');
      }
      
      const data = await response.json();
      if (data.status === 'success' && data.segments) {
        this.renderDiffSegments(data.segments);
      } else {
        throw new Error('Ungültige Antwort vom Server.');
      }
    } catch (err: any) {
      this.diffViewContent.innerHTML = `<div class="text-red-400">Fehler beim Laden der Differenzanzeige: ${err.message}</div>`;
    }
  }

  private renderDiffSegments(segments: Array<{type: string, text: string, category: string}>) {
    this.diffViewContent.innerHTML = this.renderDiffSegmentsToHtml(segments);
  }

  private async handleTemplateSelect() {
    const files = this.templateFileInput.files;
    if (!files || !files.length) return;
    
    if (!this.taskId) {
      this.log('Bitte lade zuerst eine PDF- oder Word-Datei hoch, um eine Designvorlage zu verknüpfen.', 'error');
      this.templateFileInput.value = '';
      return;
    }
    
    const file = files[0];
    const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
    if (ext !== '.docx' && ext !== '.dotx') {
      this.log('Die Designvorlage muss eine Word .docx oder .dotx Datei sein.', 'error');
      return;
    }
    
    this.templateStatusText.textContent = `Lade hoch: ${file.name}...`;
    this.log(`Lade custom DOCX-Vorlage hoch: ${file.name}...`);
    
    const formData = new FormData();
    formData.append('task_id', this.taskId);
    formData.append('file', file);
    
    try {
      const res = await fetch('/api/upload-template', {
        method: 'POST',
        body: formData
      });
      
      if (!res.ok) throw new Error('Vorlage Upload fehlgeschlagen.');
      this.templateStatusText.textContent = `Vorlage: ${file.name}`;
      this.log(`DOCX-Vorlage erfolgreich verknüpft.`, 'success');
    } catch (e: any) {
      this.templateStatusText.textContent = 'Vorlage fehlgeschlagen.';
      this.log(`Fehler bei Vorlage: ${e.message}`, 'error');
    }
  }

  private notifyParametersChanged() {
    if (this.activeFile && this.taskId) {
      this.processBtn.disabled = false;
      this.processBtn.textContent = 'Extraktion starten';
      this.processBtn.classList.remove('bg-slate-800', 'text-slate-500', 'cursor-not-allowed', 'border-slate-700', 'opacity-80', 'bg-emerald-600', 'bg-rose-600');
      this.processBtn.classList.add('bg-indigo-600', 'text-white', 'hover:bg-indigo-500', 'shadow-lg', 'shadow-indigo-500/20');
    }
  }

  private handleEngineChange() {
    this.notifyParametersChanged();
    const isSpecialEngine = this.engineSelect.value === 'lightonocr' || this.engineSelect.value === 'docling' || this.engineSelect.value === 'infinity';
    if (isSpecialEngine) {
      this.langSelectContainer.classList.add('hidden');
    } else {
      if (this.activeFile) {
        const ext = this.activeFile.name.substring(this.activeFile.name.lastIndexOf('.')).toLowerCase();
        if (ext === '.pdf') {
          this.langSelectContainer.classList.remove('hidden');
        }
      } else {
        this.langSelectContainer.classList.remove('hidden');
      }
    }
  }

  private handleTemplateModeChange() {
    const mode = this.templateModeSelect.value;
    if (mode === 'custom') {
      this.templateUploadContainer.classList.remove('hidden');
    } else {
      this.templateUploadContainer.classList.add('hidden');
    }
  }

  private async handleRulesetSelect() {
    const files = this.rulesetFileInput.files;
    if (!files || !files.length) return;
    
    if (!this.taskId) {
      this.log('Bitte lade zuerst eine PDF- oder Word-Datei hoch, um zusätzliche Regeln zu verknüpfen.', 'error');
      this.rulesetFileInput.value = '';
      return;
    }
    
    const file = files[0];
    const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
    if (ext !== '.txt' && ext !== '.md' && ext !== '.pdf' && ext !== '.docx') {
      this.log('Zusätzliche Regeln müssen eine Text-, PDF- oder Word-Datei (.txt, .md, .pdf, .docx) sein.', 'error');
      return;
    }
    
    // Block extraction and ruleset upload while processing
    const prevBtnText = this.processBtn.textContent || 'Extraktion starten';
    const wasBtnDisabled = this.processBtn.disabled;
    this.processBtn.disabled = true;
    this.processBtn.classList.add('opacity-60', 'cursor-not-allowed');
    this.processBtn.textContent = 'Regeln werden analysiert...';
    this.rulesetFileInput.disabled = true;
    this.rulesetUploadZone.classList.add('opacity-50', 'pointer-events-none');
    
    this.rulesetStatusText.textContent = `Analysiere ${file.name}...`;
    this.log(`Lade dateispezifische Regeln hoch: ${file.name}...`);
    
    const formData = new FormData();
    formData.append('task_id', this.taskId);
    formData.append('file', file);
    
    try {
      const res = await fetch('/api/upload-ruleset', {
        method: 'POST',
        body: formData
      });
      
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Ruleset Upload fehlgeschlagen.');
      }
      const data = await res.json();
      this.parsedRulesetContent = data.content || '';
      
      this.rulesetStatusText.textContent = `Regeln: ${file.name}`;
      if (this.rulesetBadge) {
        this.rulesetBadge.textContent = file.name;
        this.rulesetBadge.title = file.name;
      }
      if (this.rulesetActions) {
        this.rulesetActions.classList.remove('hidden');
      }
      this.log(`Zusätzliche dateispezifische Regeln erfolgreich verknüpft (${(data.chars || 0).toLocaleString()} Zeichen).`, 'success');
    } catch (e: any) {
      this.rulesetStatusText.textContent = 'Upload fehlgeschlagen.';
      this.log(`Fehler bei Regeln: ${e.message}`, 'error');
    } finally {
      this.rulesetFileInput.disabled = false;
      this.rulesetUploadZone.classList.remove('opacity-50', 'pointer-events-none');
      if (this.activeFile) {
        this.processBtn.disabled = wasBtnDisabled;
        this.processBtn.classList.remove('opacity-60', 'cursor-not-allowed');
        this.processBtn.textContent = prevBtnText;
      }
    }
  }

  private openRulesetModal() {
    if (!this.rulesetModal || !this.rulesetModalContent) return;
    this.rulesetModalContent.textContent = this.parsedRulesetContent || '(Keine Regeln gefunden oder Datei ist leer)';
    if (this.rulesetModalStats) {
      const len = this.parsedRulesetContent ? this.parsedRulesetContent.length : 0;
      const lines = this.parsedRulesetContent ? this.parsedRulesetContent.split('\n').length : 0;
      this.rulesetModalStats.textContent = `${len.toLocaleString()} Zeichen (${lines} Zeilen)`;
    }
    this.rulesetModal.classList.remove('hidden');
  }

  private closeRulesetModal() {
    if (!this.rulesetModal) return;
    this.rulesetModal.classList.add('hidden');
  }

  private updateRulesetUploadState(enabled: boolean) {
    if (!this.rulesetUploadZone || !this.rulesetFileInput) return;
    if (enabled && this.taskId) {
      this.rulesetUploadZone.classList.remove('cursor-not-allowed', 'opacity-50', 'pointer-events-none');
      this.rulesetUploadZone.classList.add('cursor-pointer', 'hover:bg-slate-850/30');
      this.rulesetFileInput.disabled = false;
      if (this.rulesetStatusText && (this.rulesetStatusText.textContent?.includes('erst Dokument') || !this.rulesetStatusText.textContent)) {
        this.rulesetStatusText.textContent = 'Zusätzliche Regeln hochladen';
      }
    } else {
      this.rulesetUploadZone.classList.add('cursor-not-allowed', 'opacity-50', 'pointer-events-none');
      this.rulesetUploadZone.classList.remove('cursor-pointer', 'hover:bg-slate-850/30');
      this.rulesetFileInput.disabled = true;
      if (this.rulesetStatusText) {
        this.rulesetStatusText.textContent = 'Zusätzliche Regeln hochladen (erst Dokument hochladen)';
      }
      this.rulesetFileInput.value = '';
      this.parsedRulesetContent = '';
      if (this.rulesetActions) {
        this.rulesetActions.classList.add('hidden');
      }
    }
  }

  private async abortCurrentConversion() {
    if (!this.taskId) return;
    const currentTaskId = this.taskId;
    this.log('Breche laufende Konvertierung ab...', 'info');

    if (this.activeAbortController) {
      this.activeAbortController.abort();
      this.activeAbortController = null;
    }

    try {
      await fetch(`/api/tasks/${currentTaskId}/abort`, { method: 'POST' });
    } catch (e) {
      console.error('Error sending abort request:', e);
    }

    this.handleConversionAborted();
  }

  private handleConversionAborted() {
    if (this.activeAbortController) {
      this.activeAbortController.abort();
      this.activeAbortController = null;
    }

    this.progressContainer.classList.add('hidden');
    if (this.abortProcessBtn) this.abortProcessBtn.classList.add('hidden');
    this.log('🛑 Konvertierung wurde abgebrochen.', 'error');
    this.updateStepper('idle');
    
    this.processBtn.disabled = false;
    this.processBtn.classList.remove('bg-slate-800', 'text-slate-500', 'cursor-not-allowed', 'border-slate-700', 'opacity-80');
    this.processBtn.classList.add('bg-indigo-600', 'text-white', 'hover:bg-indigo-500', 'shadow-lg', 'shadow-indigo-500/20');
    this.processBtn.textContent = 'Extraktion starten';
    
    this.refreshTasksList();
  }

  private log(message: string, type: 'info' | 'error' | 'success' = 'info') {
    const time = new Date().toLocaleTimeString();
    let colorClass = 'text-slate-400';
    if (type === 'error') colorClass = 'text-red-400 font-semibold';
    if (type === 'success') colorClass = 'text-emerald-400 font-semibold';
    
    const logEl = document.createElement('div');
    logEl.className = colorClass;
    logEl.innerHTML = `<span class="text-slate-650">[${time}]</span> ${message}`;
    
    this.logsConsole.appendChild(logEl);
    this.logsConsole.scrollTop = this.logsConsole.scrollHeight;
  }

  private handleFileSelect(e: Event) {
    const target = e.target as HTMLInputElement;
    if (target.files?.length) {
      this.setFile(target.files[0]);
    }
  }

  private async setFile(file: File) {
    const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
    if (ext !== '.pdf' && ext !== '.docx') {
      this.log(`Falsches Dateiformat: ${file.name}.`, 'error');
      return;
    }
    
    this.activeFile = file;
    this.selectedFileName.textContent = file.name;
    this.fileStatus.classList.remove('hidden');
    this.dropzone.classList.add('hidden');
    
    // Toggle selective page and lang visibility based on file type
    if (ext === '.docx') {
      this.pagesSelectContainer.classList.add('hidden');
      this.engineSelectContainer.classList.add('hidden');
      this.langSelectContainer.classList.add('hidden');
    } else {
      this.pagesSelectContainer.classList.remove('hidden');
      this.engineSelectContainer.classList.remove('hidden');
      if (this.engineSelect.value === 'lightonocr' || this.engineSelect.value === 'docling' || this.engineSelect.value === 'infinity') {
        this.langSelectContainer.classList.add('hidden');
      } else {
        this.langSelectContainer.classList.remove('hidden');
      }
    }
    
    // Disable process button and pages input during upload
    this.pagesInput.disabled = true;
    this.pagesInput.classList.add('cursor-not-allowed', 'opacity-60');
    this.pagesInput.placeholder = 'Ermittle Seitenzahl...';

    this.processBtn.disabled = true;
    this.processBtn.classList.remove('hidden', 'bg-indigo-600', 'text-white', 'hover:bg-indigo-500', 'shadow-lg', 'shadow-indigo-500/20');
    this.processBtn.classList.add('bg-slate-800', 'text-slate-500', 'cursor-not-allowed', 'border-slate-700');
    this.processBtn.textContent = 'Lade hoch...';
    
    try {
      this.updateStepper('uploading');
      this.log('Lade Datei zum Server hoch...');
      const uploadFormData = new FormData();
      uploadFormData.append('file', file);
      
      const uploadRes = await fetch('/api/upload', {
         method: 'POST',
         body: uploadFormData,
      });
      
      if (!uploadRes.ok) throw new Error('Upload failed.');
      const uploadData = await uploadRes.json();
      this.taskId = uploadData.task_id;
      this.activePageCount = uploadData.page_count || 0;
      this.physicalStartPage = uploadData.physical_start_page || 1;
      localStorage.setItem('active_task_id', uploadData.task_id);
      this.updateRulesetUploadState(true);
      this.log(`Datei hochgeladen. Task-ID: ${this.taskId}`, 'success');
      if (uploadData.directories?.has_any_directory) {
        const typesList = (uploadData.directories.detected_types || []).join(', ');
        const tocCount = (uploadData.directories.toc_entries || []).length;
        this.log(
          `📑 Verzeichnis-Check (${uploadData.directories.checked_pages || 1} S. geprüft): ${typesList} erkannt (${tocCount} Gliederungseinträge, Startseite: ${this.physicalStartPage}).`,
          'info'
        );
      }

      // Enable pages input if PDF
      if (ext === '.pdf' && this.activePageCount > 0) {
        this.pagesInput.disabled = false;
        this.pagesInput.classList.remove('cursor-not-allowed', 'opacity-60');
        this.pagesInput.placeholder = `z. B. 1-5, 8 (Dokument hat ${this.activePageCount} ${this.activePageCount === 1 ? 'Seite' : 'Seiten'})`;
      } else {
        this.pagesInput.disabled = true;
        this.pagesInput.classList.add('cursor-not-allowed', 'opacity-60');
        this.pagesInput.placeholder = 'Nur für PDF-Dokumente';
      }

      // Show PDF preview immediately
      this.pdfViewerFrame.src = `/api/pdf/${this.taskId}`;
      this.isPdfPaneVisible = true;
      this.updatePaneVisibility();

      // Enable processing button
      this.processBtn.disabled = false;
      this.processBtn.classList.remove('hidden', 'bg-slate-800', 'text-slate-500', 'cursor-not-allowed', 'border-slate-700');
      this.processBtn.classList.add('bg-indigo-600', 'text-white', 'hover:bg-indigo-500', 'shadow-lg', 'shadow-indigo-500/20');
      this.processBtn.textContent = 'Extraktion starten';
      
      this.updateStepper('idle');
      this.refreshTasksList();
    } catch (err: any) {
      this.log(`Upload-Fehler: ${err.message}`, 'error');
      this.resetFile();
    }
  }

  private resetFile() {
    this.activeFile = null;
    this.taskId = null;
    this.activePageCount = 0;
    this.physicalStartPage = 1;
    localStorage.removeItem('active_task_id');
    this.fileInput.value = '';
    this.fileStatus.classList.add('hidden');
    this.dropzone.classList.remove('hidden');
    
    this.processBtn.disabled = true;
    this.processBtn.classList.remove('bg-indigo-600', 'text-white', 'hover:bg-indigo-500', 'shadow-lg', 'shadow-indigo-500/20');
    this.processBtn.classList.add('bg-slate-800', 'text-slate-500', 'cursor-not-allowed', 'border-slate-700');
    this.processBtn.textContent = 'Extraktion starten';
    
    this.pagesInput.value = '';
    this.pagesInput.disabled = true;
    this.pagesInput.classList.add('cursor-not-allowed', 'opacity-60');
    this.pagesInput.classList.remove('border-rose-500');
    this.pagesInput.classList.add('border-slate-800');
    this.pagesInput.placeholder = 'Erst Dokument hochladen...';
    this.engineSelect.value = 'infinity';
    this.langSelect.value = 'en';
    this.engineSelectContainer.classList.remove('hidden');
    this.handleEngineChange();
    
    this.downloadActions.classList.add('hidden');
    this.rawMarkdownTextarea.value = '';
    this.standardisedMarkdownTextarea.value = '';
    this.rawMarkdownRendered.innerHTML = '';
    this.standardisedMarkdownRendered.innerHTML = '';
    this.pdfViewerFrame.src = 'about:blank';
    this.templateModeSelect.value = 'default';
    this.templateUploadContainer.classList.add('hidden');
    this.templateStatusText.textContent = 'Vorlage hochladen (.docx, .dotx)';
    this.templateFileInput.value = '';
    
    this.updateRulesetUploadState(false);
    if (this.abortProcessBtn) this.abortProcessBtn.classList.add('hidden');
    if (this.activeAbortController) {
      this.activeAbortController.abort();
      this.activeAbortController = null;
    }
    
    this.downloadDocxBtn.disabled = true;
    this.downloadDocxBtn.classList.add('bg-slate-800', 'text-slate-500', 'cursor-not-allowed', 'border-slate-700');
    this.downloadDocxBtn.classList.remove('bg-gradient-to-tr', 'from-indigo-500', 'to-purple-600', 'text-white');
    this.downloadDocxBtn.textContent = 'Word-Datei erzeugen';

    // Reset Optimization controls
    this.btnOptimize.disabled = true;
    this.optimizationPromptInput.disabled = true;
    this.optimizationPromptInput.value = '';

    // Reset Pages input
    this.pagesInput.value = '';
    this.pagesSelectContainer.classList.remove('hidden');

    // Reset Progress Bar
    this.progressContainer.classList.add('hidden');
    this.progressPhase.textContent = 'Bereite Extraktion vor...';
    this.progressBar.style.width = '0%';
    this.progressPercent.textContent = '0%';

    // Show standardized editor by default
    this.isPdfPaneVisible = false;
    this.isRawPaneVisible = false;
    this.isStandardisedPaneVisible = true;
    this.updatePaneVisibility();
    this.setStandardisedPanelMode('edit');
    this.setBboxOverlayActive(false);
    this.updatePagePills();
    this.updateCharReplaceBadge();

    this.log('Datei zurückgesetzt.');
    this.updateStepper('idle');
  }

  private updateStepper(state: ProcessState) {
    const steps = [this.step1, this.step2, this.step3, this.step4];
    
    steps.forEach((step, idx) => {
      const bubble = step.querySelector('span') as HTMLSpanElement;
      bubble.className = 'w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold border';
      step.className = 'flex items-center space-x-1.5 transition-colors duration-300 text-xs font-semibold';
      
      if (idx === 0) { // Step 1
        if (state === 'idle') {
          bubble.classList.add('bg-indigo-500/20', 'border-indigo-500', 'text-indigo-300');
          step.classList.add('text-indigo-400');
        } else {
          bubble.classList.add('bg-emerald-500/20', 'border-emerald-500', 'text-emerald-300');
          step.classList.add('text-emerald-400');
        }
      }
      
      else if (idx === 1) { // Step 2 (Extract)
        if (state === 'extracting') {
          bubble.classList.add('bg-indigo-500/20', 'border-indigo-500', 'text-indigo-300');
          step.classList.add('text-indigo-400');
        } else if (state === 'standardising' || state === 'ready_to_export' || state === 'completed') {
          bubble.classList.add('bg-emerald-500/20', 'border-emerald-500', 'text-emerald-300');
          step.classList.add('text-emerald-400');
        } else {
          bubble.classList.add('bg-slate-800', 'border-slate-700', 'text-slate-500');
          step.classList.add('text-slate-500');
        }
      }
      
      else if (idx === 2) { // Step 3 (Standardise)
        if (state === 'standardising') {
          bubble.classList.add('bg-indigo-500/20', 'border-indigo-500', 'text-indigo-300');
          step.classList.add('text-indigo-400');
        } else if (state === 'ready_to_export' || state === 'completed') {
          bubble.classList.add('bg-emerald-500/20', 'border-emerald-500', 'text-emerald-300');
          step.classList.add('text-emerald-400');
        } else {
          bubble.classList.add('bg-slate-800', 'border-slate-700', 'text-slate-500');
          step.classList.add('text-slate-500');
        }
      }
      
      else if (idx === 3) { // Step 4 (DOCX Export)
        if (state === 'ready_to_export') {
          bubble.classList.add('bg-indigo-500/20', 'border-indigo-500', 'text-indigo-300');
          step.classList.add('text-indigo-400');
        } else if (state === 'completed') {
          bubble.classList.add('bg-emerald-500/20', 'border-emerald-500', 'text-emerald-300');
          step.classList.add('text-emerald-400');
        } else {
          bubble.classList.add('bg-slate-800', 'border-slate-700', 'text-slate-500');
          step.classList.add('text-slate-500');
        }
      }
    });
  }

  private async startProcessing() {
    console.log('startProcessing: entry', { activeFile: this.activeFile?.name, taskId: this.taskId, activePageCount: this.activePageCount });
    if (!this.activeFile || !this.taskId) {
      console.log('startProcessing: activeFile or taskId is missing');
      return;
    }

    // Validate PDF pages selection first before changing UI state
    const isPdf = this.activeFile.name.toLowerCase().endsWith('.pdf');
    if (isPdf && this.activePageCount > 0) {
      const pagesVal = this.pagesInput.value.trim();
      const validation = this.validatePages(pagesVal, this.activePageCount, this.physicalStartPage);
      console.log('startProcessing: validation result', { pagesVal, validation });
      if (!validation.isValid) {
        this.showInputError(this.pagesInput, this.pagesInputError, this.pagesInputErrorText, validation.error || 'Ungültige Seitenauswahl.');
        this.pagesInput.focus();
        return;
      } else {
        this.clearInputError(this.pagesInput, this.pagesInputError);
      }
    }

    this.processBtn.disabled = true;
    this.processBtn.textContent = 'Analysiere...';
    this.processBtn.classList.remove('hover:bg-indigo-500', 'bg-emerald-600', 'bg-rose-600');
    this.processBtn.classList.add('cursor-not-allowed', 'opacity-80', 'bg-indigo-600', 'text-white');
    if (this.abortProcessBtn) this.abortProcessBtn.classList.remove('hidden');

    // Reset previous outputs and download states if re-extracting
    this.currentRawMarkdown = '';
    this.currentStandardisedMarkdown = '';
    this.rawMarkdownTextarea.value = '';
    this.standardisedMarkdownTextarea.value = '';
    if (this.isRawRendered) this.updateRawRenderPreview();
    if (this.isStandardisedRendered) this.updateStandardisedRenderPreview();
    this.downloadDocxBtn.disabled = true;
    this.downloadDocxBtn.classList.add('cursor-not-allowed', 'bg-slate-800', 'text-slate-500', 'border-slate-700');
    this.downloadDocxBtn.classList.remove('bg-gradient-to-tr', 'from-indigo-500', 'to-purple-600', 'text-white', 'hover:opacity-90', 'shadow-md');

    this.activeAbortController = new AbortController();

    try {
      this.isRawPaneVisible = true; // Auto open raw extract pane
      this.updatePaneVisibility();
      this.currentRawMarkdown = '';
      this.rawMarkdownTextarea.value = '';

      // Refresh task manager listing
      this.refreshTasksList();

      // 2. Extract
      this.updateStepper('extracting');
      this.log('Starte Inhalts-Extraktion (Markdown Konvertierung)...');
      
      const extractFormData = new FormData();
      extractFormData.append('task_id', this.taskId!);
      const pagesVal = this.pagesInput.value.trim();
      if (pagesVal) {
        extractFormData.append('pages', pagesVal);
      }
      extractFormData.append('engine', this.engineSelect.value);
      extractFormData.append('method', 'auto');
      extractFormData.append('lang', this.langSelect.value);
      
      const extractRes = await fetch('/api/extract', {
        method: 'POST',
        body: extractFormData,
        signal: this.activeAbortController.signal,
      });
      
      if (!extractRes.ok) {
        const errData = await extractRes.json().catch(() => ({}));
        throw new Error(errData.detail || 'Extraktion fehlgeschlagen.');
      }
      
      const reader = extractRes.body?.getReader();
      if (!reader) throw new Error('Streaming von Antwortdaten wird von diesem Browser nicht unterstützt.');
      
      const decoder = new TextDecoder();
      let buffer = '';
      
      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          buffer += decoder.decode();
          break;
        }
        
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;
          
          try {
            const data = JSON.parse(trimmed);
            if (data.status === 'log') {
              this.log(data.message);
            } else if (data.status === 'progress') {
              this.progressContainer.classList.remove('hidden');
              this.progressPhase.textContent = data.phase;
              this.progressPages.textContent = `${data.current} / ${data.total} Seiten`;
              this.progressBar.style.width = `${data.percent}%`;
              this.progressPercent.textContent = `${data.percent}%`;
            } else if (data.status === 'raw_chunk') {
              if (data.delta) {
                if (!this.currentRawMarkdown) {
                  this.currentRawMarkdown = data.delta;
                } else {
                  this.currentRawMarkdown += '\n\n' + data.delta;
                }
                this.rawMarkdownTextarea.value = this.currentRawMarkdown;
                this.rawMarkdownTextarea.scrollTop = this.rawMarkdownTextarea.scrollHeight;
                if (this.isRawRendered) this.updateRawRenderPreview();
              }
            } else if (data.status === 'aborted') {
              this.handleConversionAborted();
              return;
            } else if (data.status === 'error') {
              throw new Error(data.message);
            } else if (data.status === 'completed') {
              this.progressBar.style.width = '90%';
              this.progressPercent.textContent = '90%';
              this.progressPhase.textContent = 'Bereite Standardisierung vor...';
              this.currentRawMarkdown = data.markdown;
              this.rawMarkdownTextarea.value = this.currentRawMarkdown;
              this.log(`Extraktion beendet. ${data.image_count} Bilder extrahiert.`, 'success');
              if (this.isRawRendered) this.updateRawRenderPreview();
            }
          } catch (e: any) {
            console.error('JSON parsing error in stream:', e, trimmed);
            if (e.message.includes('fehlgeschlagen') || e.message.includes('Systemfehler') || e.message.includes('nicht gefunden')) {
              throw e;
            }
          }
        }
      }

      if (buffer.trim()) {
        const trimmed = buffer.trim();
        try {
          const data = JSON.parse(trimmed);
          if (data.status === 'log') {
            this.log(data.message);
          } else if (data.status === 'progress') {
            this.progressContainer.classList.remove('hidden');
            this.progressPhase.textContent = data.phase;
            this.progressPages.textContent = `${data.current} / ${data.total} Seiten`;
            this.progressBar.style.width = `${data.percent}%`;
            this.progressPercent.textContent = `${data.percent}%`;
          } else if (data.status === 'aborted') {
            this.handleConversionAborted();
            return;
          } else if (data.status === 'error') {
            throw new Error(data.message);
          } else if (data.status === 'completed') {
            this.progressBar.style.width = '90%';
            this.progressPercent.textContent = '90%';
            this.progressPhase.textContent = 'Bereite Standardisierung vor...';
            this.currentRawMarkdown = data.markdown;
            this.rawMarkdownTextarea.value = this.currentRawMarkdown;
            this.log(`Extraktion beendet. ${data.image_count} Bilder extrahiert.`, 'success');
            if (this.isRawRendered) this.updateRawRenderPreview();
          }
        } catch (e: any) {
          console.error('JSON parsing error in stream tail:', e, trimmed);
        }
      }

      // Refresh tasks list state
      this.refreshTasksList();

      // Retrieve physical start page from state before standardisation
      try {
        const stateRes = await fetch(`/api/tasks/${this.taskId}/state`);
        if (stateRes.ok) {
          const stateData = await stateRes.json();
          this.physicalStartPage = stateData.physical_start_page || 1;
        }
      } catch (e) {
        console.error('Error fetching physical start page:', e);
      }

      // 3. Standardise
      await this.standardiseTask(this.taskId!);

    } catch (err: any) {
      if (this.abortProcessBtn) this.abortProcessBtn.classList.add('hidden');
      if (err.name === 'AbortError' || err.message.includes('aborted') || err.message.includes('abgebrochen')) {
        this.handleConversionAborted();
        return;
      }
      this.progressContainer.classList.add('hidden');
      this.log(`Fehler bei der Konvertierung: ${err.message}`, 'error');
      this.updateStepper('error');
      this.processBtn.textContent = 'Erneut versuchen';
      this.processBtn.disabled = false;
      this.processBtn.classList.remove('cursor-not-allowed', 'opacity-80');
      this.refreshTasksList();
    } finally {
      if (this.abortProcessBtn) this.abortProcessBtn.classList.add('hidden');
    }
  }

  private initTaskManager() {
    let isTasksManagerOpen = false;
    this.toggleTasksBtn.addEventListener('click', () => {
      isTasksManagerOpen = !isTasksManagerOpen;
      if (isTasksManagerOpen) {
        this.tasksManagerContainer.classList.remove('hidden');
        this.tasksArrow.classList.add('rotate-90');
        this.refreshTasksList();
      } else {
        this.tasksManagerContainer.classList.add('hidden');
        this.tasksArrow.classList.remove('rotate-90');
      }
    });

    // Check tasks list immediately and register auto polling interval (every 4 seconds)
    this.refreshTasksList();
    setInterval(() => this.refreshTasksList(), 4000);

    // Restore task state on page reload (check URL query param first, then localStorage)
    const urlParams = new URLSearchParams(window.location.search);
    const paramTaskId = urlParams.get('task_id');
    const savedTaskId = paramTaskId || localStorage.getItem('active_task_id');
    if (savedTaskId) {
      this.reattachTask(savedTaskId);
    }
  }

  private async refreshTasksList() {
    try {
      const res = await fetch('/api/tasks');
      if (!res.ok) return;
      const tasks = await res.json();
      
      // Update active tasks badge
      const activeCount = tasks.filter((t: any) => t.status === 'processing').length;
      if (activeCount > 0) {
        this.activeTasksBadge.classList.remove('hidden');
        this.activeTasksBadge.textContent = String(activeCount);
      } else {
        this.activeTasksBadge.classList.add('hidden');
      }
      
      // Render list
      if (tasks.length === 0) {
        this.tasksList.innerHTML = '<p class="text-slate-500 text-[10px] italic py-1">Keine aktiven Prozesse im Hintergrund.</p>';
        return;
      }
      
      this.tasksList.innerHTML = '';
      tasks.forEach((t: any) => {
        const isCurrent = (t.task_id === this.taskId);
        const card = document.createElement('div');
        card.className = `p-2 bg-slate-950 rounded-lg border ${isCurrent ? 'border-indigo-500/50 bg-indigo-950/5' : 'border-slate-850'} flex flex-col space-y-1.5 text-[10px]`;
        
        let statusColor = 'bg-slate-900 text-slate-400 border-slate-800';
        if (t.status === 'processing') statusColor = 'bg-indigo-950 text-indigo-400 border-indigo-900 animate-pulse';
        else if (t.status === 'completed') statusColor = 'bg-emerald-950 text-emerald-400 border-emerald-900';
        else if (t.status === 'failed') statusColor = 'bg-rose-950 text-rose-400 border-rose-900';
        else if (t.status === 'interrupted') statusColor = 'bg-amber-950 text-amber-400 border-amber-900';
        const statusLabels: Record<string, string> = {
          processing: 'Läuft', queued: 'Wartet', completed: 'Fertig', failed: 'Fehler',
          aborted: 'Abgebrochen', interrupted: 'Unterbrochen', pending: 'Bereit',
        };
        const statusLabel = statusLabels[t.status] || t.status;
        const canResume = !!t.resumable && (t.status === 'interrupted' || t.status === 'failed');
        
        const percent = t.progress?.percent || 0;
        const phase = t.progress?.phase || 'Warten...';

        const formatTime = (ts?: number) => {
          if (!ts) return '';
          const d = new Date(ts * 1000);
          return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        };

        const formatDuration = (startTs?: number, endTs?: number) => {
          if (!startTs || !endTs) return '';
          const diff = Math.max(0, Math.floor(endTs - startTs));
          const mins = Math.floor(diff / 60);
          const secs = diff % 60;
          if (mins > 0) return `${mins}m ${secs}s`;
          return `${secs}s`;
        };

        const startTs = t.started_at || t.created_at;
        const endTs = t.finished_at;
        const startTimeStr = startTs ? formatTime(startTs) : '';
        const endTimeStr = endTs ? formatTime(endTs) : '';
        const durationStr = (startTs && endTs) ? formatDuration(startTs, endTs) : '';
        
        card.innerHTML = `
          <div class="flex items-center justify-between">
            <span class="font-semibold text-slate-350 truncate w-32" title="${t.original_name}">${t.original_name}</span>
            <span class="task-status-badge px-1.5 py-0.5 rounded border text-[8px] font-bold tracking-wider uppercase ${statusColor}" data-status="${t.status}">${statusLabel}</span>
          </div>
          ${startTimeStr ? `
            <div class="flex items-center justify-between text-[9px] text-slate-400 font-mono">
              <span title="Startzeit">Start: ${startTimeStr}</span>
              ${endTimeStr ? `<span title="Endzeit (Dauer: ${durationStr})">Ende: ${endTimeStr}${durationStr ? ` (${durationStr})` : ''}</span>` : (t.status === 'processing' ? '<span class="text-indigo-400 animate-pulse">Läuft...</span>' : '')}
            </div>
          ` : ''}
          ${t.status === 'processing' ? `
            <div class="flex items-center justify-between text-[9px] text-slate-500 font-mono">
              <span class="truncate w-24">${phase}</span>
              <span>${percent}%</span>
            </div>
            <div class="w-full bg-slate-900 rounded-full h-1 overflow-hidden">
              <div class="bg-indigo-500 h-full transition-all duration-300" style="width: ${percent}%"></div>
            </div>
          ` : ''}
          ${t.status === 'interrupted' ? `
            <div class="text-[9px] text-amber-400/90 font-mono truncate" title="${phase}">${phase} (${percent}%)</div>
          ` : ''}
          <div class="flex items-center justify-end space-x-3 pt-1.5 border-t border-slate-900/60 text-[9px]">
            ${canResume ? `<button id="resume-btn-${t.task_id}" class="resume-btn font-semibold text-amber-400 hover:text-amber-300 transition-colors" data-id="${t.task_id}">Fortsetzen</button>` : ''}
            <button class="reattach-btn font-semibold text-slate-400 hover:text-white transition-colors" data-id="${t.task_id}">Öffnen</button>
            <button class="delete-btn font-semibold text-red-500 hover:text-red-400 transition-colors" data-id="${t.task_id}">Löschen</button>
          </div>
        `;
        
        // Event listeners
        card.querySelector('.resume-btn')?.addEventListener('click', () => this.resumeTask(t.task_id));
        card.querySelector('.reattach-btn')?.addEventListener('click', () => this.reattachTask(t.task_id));
        card.querySelector('.delete-btn')?.addEventListener('click', () => this.deleteTask(t.task_id));
        
        this.tasksList.appendChild(card);
      });
    } catch (err) {
      console.error('Error listing tasks:', err);
    }
  }

  /**
   * Resume an interrupted/failed task on the server (POST /api/tasks/{id}/resume)
   * and reattach the workspace to its live stream.
   */
  private async resumeTask(taskId: string) {
    try {
      this.log('Setze unterbrochene Verarbeitung fort...', 'info');
      const res = await fetch(`/api/tasks/${taskId}/resume`, { method: 'POST' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Fortsetzen fehlgeschlagen.');
      }
      const data = await res.json();
      this.log(`Verarbeitung fortgesetzt (${data.stage === 'pipeline' ? 'Extraktion + Standardisierung' : 'Standardisierung'}).`, 'success');
      await this.reattachTask(taskId);
      this.refreshTasksList();
    } catch (err: any) {
      this.log(`Fehler beim Fortsetzen: ${err.message}`, 'error');
    }
  }

  /** Interrupted tasks (backend restart / lost job) can be resumed from the task list. */
  private handleTaskInterrupted(message?: string) {
    this.progressContainer.classList.add('hidden');
    if (this.abortProcessBtn) this.abortProcessBtn.classList.add('hidden');
    this.updateStepper('error');
    this.processBtn.textContent = 'Unterbrochen – in Prozessliste fortsetzen';
    this.processBtn.disabled = false;
    this.processBtn.classList.remove('cursor-not-allowed', 'opacity-80');
    this.log(`⚠️ ${message || 'Verarbeitung wurde unterbrochen.'} Über „Fortsetzen“ in der Prozessliste kann sie wieder aufgenommen werden.`, 'error');
    this.refreshTasksList();
  }

  private async reattachTask(taskId: string) {
    try {
      this.log(`Verbinde mit Prozess-ID: ${taskId}...`, 'info');
      this.taskId = taskId;
      localStorage.setItem('active_task_id', taskId);
      
      // 1. Fetch task state
      const res = await fetch(`/api/tasks/${taskId}/state`);
      if (!res.ok) throw new Error('Task-Zustand konnte nicht abgerufen werden.');
      const data = await res.json();
      
      // Update UI file name
      this.selectedFileName.textContent = data.original_name;
      this.activeFile = new File([], data.original_name);
      this.activePageCount = data.page_count || 0;
      this.physicalStartPage = data.physical_start_page || 1;
      
      // Restore select inputs
      if (data.engine) {
        this.engineSelect.value = data.engine;
      }
      if (data.pages) {
        this.pagesInput.value = data.pages;
      }
      if (data.extension === '.pdf' && this.activePageCount > 0) {
        this.pagesInput.disabled = false;
        this.pagesInput.classList.remove('cursor-not-allowed', 'opacity-60');
        this.pagesInput.placeholder = `z. B. 1-5, 8 (Dokument hat ${this.activePageCount} ${this.activePageCount === 1 ? 'Seite' : 'Seiten'})`;
      }
      if (data.lang) {
        this.langSelect.value = data.lang;
      }
      
      const ext = data.original_name.substring(data.original_name.lastIndexOf('.')).toLowerCase();
      if (ext === '.docx') {
        this.pagesSelectContainer.classList.add('hidden');
        this.engineSelectContainer.classList.add('hidden');
        this.langSelectContainer.classList.add('hidden');
      } else {
        this.pagesSelectContainer.classList.remove('hidden');
        this.engineSelectContainer.classList.remove('hidden');
        this.handleEngineChange();
      }
      
      this.fileStatus.classList.remove('hidden');
      this.dropzone.classList.add('hidden');
      this.processBtn.disabled = true;
      this.processBtn.classList.remove('bg-indigo-600', 'text-white');
      this.processBtn.classList.add('bg-slate-800', 'text-slate-500', 'cursor-not-allowed');
      this.processBtn.textContent = 'Verarbeitung läuft...';
      
      // Set PDF Preview
      this.pdfViewerFrame.src = `/api/pdf/${taskId}`;
      this.updateRulesetUploadState(true);
      
      // Unconditionally restore raw markdown and standardised markdown if present
      if (data.raw_markdown) {
        this.currentRawMarkdown = data.raw_markdown;
        this.rawMarkdownTextarea.value = this.currentRawMarkdown;
        if (this.isRawRendered) this.updateRawRenderPreview();
      }
      if (data.standardised_markdown) {
        this.currentStandardisedMarkdown = data.standardised_markdown;
        this.standardisedMarkdownTextarea.value = this.currentStandardisedMarkdown;
        if (this.isStandardisedRendered) this.updateStandardisedRenderPreview();
      }
      this.updatePagePills();
      this.updateCharReplaceBadge();
      if (this.isBboxOverlayActive) {
        this.loadAndRenderBboxOverlay();
      }

      if (data.status === 'processing') {
        // Show progress bar container and reset bar width
        this.progressContainer.classList.remove('hidden');
        this.progressBar.style.width = `${data.progress.percent}%`;
        this.progressPercent.textContent = `${data.progress.percent}%`;
        this.progressPhase.textContent = data.progress.phase;
        this.progressPages.textContent = `${data.progress.current} / ${data.progress.total} Seiten`;
        
        if (this.abortProcessBtn) this.abortProcessBtn.classList.remove('hidden');
        
        const isStandardising = (data.progress.percent || 0) >= 90 || data.progress.phase?.includes('Standardis') || data.progress.phase?.includes('Bildanalyse') || data.progress.phase?.includes('Render');
        this.updateStepper(isStandardising ? 'standardising' : 'extracting');
        
        this.isPdfPaneVisible = true;
        this.isRawPaneVisible = true;
        this.updatePaneVisibility();
        
        // Start log stream receiver to print stdout and wait for completion
        this.listenToLogs(taskId);
      } else if (data.status === 'interrupted') {
        this.handleTaskInterrupted(data.progress?.phase);
      } else if (data.status === 'aborted') {
        this.progressContainer.classList.add('hidden');
        if (this.abortProcessBtn) this.abortProcessBtn.classList.add('hidden');
        this.updateStepper('idle');
        this.processBtn.textContent = 'Extraktion starten';
        this.processBtn.disabled = false;
        this.processBtn.classList.remove('bg-slate-800', 'cursor-not-allowed', 'opacity-80');
        this.processBtn.classList.add('bg-indigo-600', 'text-white');
        this.log('Prozess wurde zuvor abgebrochen.', 'info');
      } else if (data.status === 'completed') {
        this.progressContainer.classList.add('hidden');
        if (this.abortProcessBtn) this.abortProcessBtn.classList.add('hidden');
        this.currentRawMarkdown = data.raw_markdown || '';
        this.rawMarkdownTextarea.value = this.currentRawMarkdown;
        if (this.isRawRendered) this.updateRawRenderPreview();
        
        this.currentStandardisedMarkdown = data.standardised_markdown || '';
        this.standardisedMarkdownTextarea.value = this.currentStandardisedMarkdown;
        if (this.isStandardisedRendered) this.updateStandardisedRenderPreview();
        this.updatePagePills();
        this.updateCharReplaceBadge();
        
        this.updateStepper('ready_to_export');
        this.downloadActions.classList.remove('hidden');

        // Enable Optimization controls
        this.btnOptimize.disabled = false;
        this.optimizationPromptInput.disabled = false;
        
        this.downloadDocxBtn.disabled = false;
        this.downloadDocxBtn.classList.remove('bg-slate-800', 'text-slate-500', 'cursor-not-allowed', 'border-slate-700');
        this.downloadDocxBtn.classList.add('bg-gradient-to-tr', 'from-indigo-500', 'to-purple-600', 'text-white', 'hover:opacity-90', 'shadow-md');
        
        this.processBtn.textContent = 'Extraktion abgeschlossen';
        this.processBtn.classList.add('bg-emerald-600', 'text-white');
        this.processBtn.classList.remove('bg-slate-800');
        this.processBtn.disabled = false;
        this.processBtn.classList.remove('cursor-not-allowed');
        
        this.isPdfPaneVisible = false;
        this.isRawPaneVisible = false;
        this.isStandardisedPaneVisible = true;
        this.updatePaneVisibility();
        
        this.log('Zustand wiederhergestellt. Inhalt steht zur Korrektur bereit.', 'success');
      } else if (data.status === 'failed') {
        this.progressContainer.classList.add('hidden');
        if (this.abortProcessBtn) this.abortProcessBtn.classList.add('hidden');
        this.updateStepper('error');
        this.processBtn.textContent = 'Fehlgeschlagen / Erneut versuchen';
        this.processBtn.disabled = false;
        this.processBtn.classList.remove('cursor-not-allowed');
        this.processBtn.classList.add('bg-rose-600', 'text-white');
        this.log('Prozess war fehlgeschlagen.', 'error');
      }
    } catch (err: any) {
      this.log(`Fehler beim Verbinden: ${err.message}`, 'error');
      this.resetFile();
    }
  }

  /**
   * Attach to a running task via GET /api/tasks/{id}/stream. The server replays
   * logs, progress and already streamed Gemma tokens, then sends live events.
   * Closing this stream never cancels the server job; if the connection drops
   * (e.g. after system sleep) we reconnect automatically.
   */
  private async listenToLogs(taskId: string) {
    let terminal = false;
    try {
      const streamRes = await fetch(`/api/tasks/${taskId}/stream`);
      if (!streamRes.ok) throw new Error('Verbindung zum Log-Stream abgebrochen.');
      
      const reader = streamRes.body?.getReader();
      if (!reader) return;
      
      const decoder = new TextDecoder();
      let buffer = '';
      
      const skipReplayedLogs = this.replayedTaskId === taskId;
      this.replayedTaskId = taskId;
      const handleEvent = (data: any) => {
        if (this.taskId !== taskId) return;
        if (data.status === 'log') {
          if (data.replay && skipReplayedLogs) return;
          this.log(data.message);
        } else if (data.status === 'progress') {
          this.progressContainer.classList.remove('hidden');
          this.progressPhase.textContent = data.phase;
          if (data.total) this.progressPages.textContent = `${data.current} / ${data.total} Seiten`;
          this.progressBar.style.width = `${data.percent}%`;
          this.progressPercent.textContent = `${data.percent}%`;
        } else if (data.status === 'raw_chunk') {
          if (data.delta) {
            this.currentRawMarkdown = this.currentRawMarkdown ? `${this.currentRawMarkdown}\n\n${data.delta}` : data.delta;
            this.rawMarkdownTextarea.value = this.currentRawMarkdown;
            this.rawMarkdownTextarea.scrollTop = this.rawMarkdownTextarea.scrollHeight;
            if (this.isRawRendered) this.updateRawRenderPreview();
          }
        } else if (data.status === 'stream_snapshot') {
          // Replay of Gemma tokens generated while this client was not attached
          this.isStandardisedPaneVisible = true;
          this.updatePaneVisibility();
          this.standardisedMarkdownTextarea.value = data.text || '';
        } else if (data.status === 'token') {
          if (!this.isStandardisedPaneVisible) {
            this.isStandardisedPaneVisible = true;
            this.updatePaneVisibility();
          }
          this.standardisedMarkdownTextarea.value += data.delta;
          this.standardisedMarkdownTextarea.scrollTop = this.standardisedMarkdownTextarea.scrollHeight;
        } else if (data.status === 'interrupted') {
          terminal = true;
          this.handleTaskInterrupted(data.message);
        } else if (data.status === 'aborted') {
          terminal = true;
          this.handleConversionAborted();
        } else if (data.status === 'error') {
          terminal = true;
          this.log(`Fehler: ${data.message}`, 'error');
          this.updateStepper('error');
          this.progressContainer.classList.add('hidden');
          if (this.abortProcessBtn) this.abortProcessBtn.classList.add('hidden');
          this.processBtn.textContent = 'Erneut versuchen';
          this.processBtn.disabled = false;
          this.processBtn.classList.remove('cursor-not-allowed');
          this.refreshTasksList();
        } else if (data.status === 'completed') {
          terminal = true;
          if (data.stage === 'standardisation') {
            this.currentStandardisedMarkdown = data.markdown;
            this.standardisedMarkdownTextarea.value = data.markdown;
            this.updatePagePills();
            this.log('Regeln erfolgreich angewendet. Inhalt steht zur Korrektur bereit.', 'success');
            this.finalizeStandardisedView();
            this.refreshTasksList();
          } else {
            this.progressBar.style.width = '90%';
            this.progressPercent.textContent = '90%';
            this.progressPhase.textContent = 'Bereite Standardisierung vor...';
            this.currentRawMarkdown = data.markdown;
            this.rawMarkdownTextarea.value = this.currentRawMarkdown;
            this.log(`Extraktion beendet. ${data.image_count ?? 0} Bilder extrahiert.`, 'success');
            if (this.isRawRendered) this.updateRawRenderPreview();
            // Trigger standardise (attaches if the server already chained it)
            this.standardiseTask(taskId);
          }
        }
      };

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          buffer += decoder.decode();
          break;
        }
        
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;
          try {
            handleEvent(JSON.parse(trimmed));
          } catch (e: any) {
            console.error('JSON stream error:', e);
          }
        }
      }
      if (buffer.trim()) {
        try { handleEvent(JSON.parse(buffer.trim())); } catch (e) { console.error('JSON stream tail error:', e); }
      }
    } catch (err: any) {
      this.log(`Stream-Verbindung verloren: ${err.message}`, 'error');
    }

    // Stream ended without a final event: the server job keeps running – reconnect.
    if (terminal) {
      this.reconnectAttempts = 0;
    } else {
      this.scheduleReconnect(taskId);
    }
  }

  private async standardiseTask(taskId: string) {
    if (!this.activeAbortController) {
      this.activeAbortController = new AbortController();
    }
    if (this.abortProcessBtn) this.abortProcessBtn.classList.remove('hidden');

    try {
      this.updateStepper('standardising');
      this.log('Wende E-Buch Formatierungsregeln (Anwendung Übertragungsregeln) an...');
      
      const ruleset = this.rulesetSelect.value;
      const describeImages = this.describeImagesToggle ? this.describeImagesToggle.checked : true;
      const standardiseRes = await fetch('/api/standardise', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task_id: taskId,
          markdown: this.currentRawMarkdown,
          ruleset: ruleset,
          describe_images: describeImages,
        }),
        signal: this.activeAbortController.signal,
      });
      
      if (!standardiseRes.ok) {
        const errData = await standardiseRes.json().catch(() => ({}));
        throw new Error(errData.detail || 'Standardisierung fehlgeschlagen.');
      }
      
      const reader = standardiseRes.body?.getReader();
      if (!reader) throw new Error('Streaming von Antwortdaten wird von diesem Browser nicht unterstützt.');
      
      let completed = false;
      let streamError: string | null = null;
      const decoder = new TextDecoder();
      let buffer = '';
      
      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          buffer += decoder.decode();
          break;
        }
        
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;
          
          try {
            const data = JSON.parse(trimmed);
            if (data.status === 'token') {
              if (!this.isStandardisedPaneVisible) {
                this.isStandardisedPaneVisible = true;
                this.updatePaneVisibility();
              }
              this.standardisedMarkdownTextarea.value += data.delta;
              this.standardisedMarkdownTextarea.scrollTop = this.standardisedMarkdownTextarea.scrollHeight;
            } else if (data.status === 'stream_snapshot') {
              this.standardisedMarkdownTextarea.value = data.text || '';
            } else if (data.status === 'progress') {
              this.progressContainer.classList.remove('hidden');
              this.progressPhase.textContent = data.phase;
              this.progressBar.style.width = `${data.percent}%`;
              this.progressPercent.textContent = `${data.percent}%`;
            } else if (data.status === 'log') {
              this.log(data.message);
            } else if (data.status === 'aborted') {
              this.handleConversionAborted();
              return;
            } else if (data.status === 'interrupted') {
              this.handleTaskInterrupted(data.message);
              return;
            } else if (data.status === 'error') {
              streamError = data.message || 'Standardisierung fehlgeschlagen.';
            } else if (data.status === 'completed') {
              completed = true;
              this.reconnectAttempts = 0;
              this.progressContainer.classList.add('hidden');
              this.currentStandardisedMarkdown = data.markdown;
              this.standardisedMarkdownTextarea.value = this.currentStandardisedMarkdown;
              this.updatePagePills();
              this.log('Regeln erfolgreich angewendet. Inhalt steht zur Korrektur bereit.', 'success');
            }
          } catch (e: any) {
            console.error('JSON parsing error in standardise stream:', e, trimmed);
          }
        }
      }
      
      if (buffer.trim()) {
        const trimmed = buffer.trim();
        try {
          const data = JSON.parse(trimmed);
          if (data.status === 'token') {
            this.standardisedMarkdownTextarea.value += data.delta;
            this.standardisedMarkdownTextarea.scrollTop = this.standardisedMarkdownTextarea.scrollHeight;
          } else if (data.status === 'progress') {
            this.progressContainer.classList.remove('hidden');
            this.progressPhase.textContent = data.phase;
            this.progressBar.style.width = `${data.percent}%`;
            this.progressPercent.textContent = `${data.percent}%`;
          } else if (data.status === 'aborted') {
            this.handleConversionAborted();
            return;
          } else if (data.status === 'interrupted') {
            this.handleTaskInterrupted(data.message);
            return;
          } else if (data.status === 'error') {
            streamError = data.message || 'Standardisierung fehlgeschlagen.';
          } else if (data.status === 'completed') {
            completed = true;
            this.reconnectAttempts = 0;
            this.progressContainer.classList.add('hidden');
            this.currentStandardisedMarkdown = data.markdown;
            this.standardisedMarkdownTextarea.value = this.currentStandardisedMarkdown;
            this.updatePagePills();
            this.log('Regeln erfolgreich angewendet. Inhalt steht zur Korrektur bereit.', 'success');
          }
        } catch (e: any) {
          console.error('JSON parsing error in standardise stream tail:', e, trimmed);
        }
      }
      if (streamError) throw new Error(streamError);
      if (!completed) {
        // Stream ended without a final event: the server job keeps running.
        this.scheduleReconnect(taskId);
        return;
      }
      this.finalizeStandardisedView();

    } catch (err: any) {
      if (err.name === 'AbortError') {
        // Only the client detached (view reset / explicit abort already handled) – the server job is unaffected.
        return;
      }
      if (err instanceof TypeError) {
        // Network error (e.g. after system sleep): reattach to the still running server job.
        this.scheduleReconnect(taskId);
        return;
      }
      if (this.abortProcessBtn) this.abortProcessBtn.classList.add('hidden');
      if (err.message.includes('aborted') || err.message.includes('abgebrochen')) {
        this.handleConversionAborted();
        return;
      }
      this.log(`Fehler bei der Standardisierung: ${err.message}`, 'error');
      this.updateStepper('error');
      this.processBtn.textContent = 'Erneut versuchen';
      this.processBtn.disabled = false;
      this.processBtn.classList.remove('cursor-not-allowed');
      this.processBtn.classList.add('bg-rose-600', 'text-white');
      this.refreshTasksList();
    } finally {
      if (this.abortProcessBtn && this.taskId !== taskId) this.abortProcessBtn.classList.add('hidden');
    }
  }

  /**
   * Reconnect to a still running server job after the stream dropped (bounded retries).
   * The job itself is owned by the backend and keeps running meanwhile.
   */
  private scheduleReconnect(taskId: string) {
    if (this.taskId !== taskId) return;
    if (this.reconnectAttempts >= 40) {
      this.log('Neuverbindung aufgegeben – Prozess über die Prozessliste erneut öffnen.', 'error');
      return;
    }
    this.reconnectAttempts++;
    this.log('Verbindung getrennt – Verarbeitung läuft im Hintergrund weiter. Verbinde neu...', 'info');
    setTimeout(async () => {
      if (this.taskId !== taskId) return;
      try {
        const res = await fetch(`/api/tasks/${taskId}/state`);
        if (!res.ok) throw new Error('state unavailable');
        await this.reattachTask(taskId);
      } catch {
        this.scheduleReconnect(taskId);
      }
    }, 3000);
  }

  /** Shared UI finalisation once the standardised transfer is available. */
  private finalizeStandardisedView() {
    this.progressContainer.classList.add('hidden');
    if (this.abortProcessBtn) this.abortProcessBtn.classList.add('hidden');
    // Update view if currently in preview or diff mode
    if (this.btnDiffStandardised.classList.contains('bg-indigo-600')) {
      this.updateDiffView();
    } else if (this.btnRenderStandardised.classList.contains('bg-indigo-600')) {
      this.updateStandardisedRenderPreview();
    }
    
    // Auto open standardised pane
    this.isStandardisedPaneVisible = true;
    this.updatePaneVisibility();

    // Ready to export DOCX
    this.updateStepper('ready_to_export');
    this.downloadActions.classList.remove('hidden');

    // Enable Optimization controls
    this.btnOptimize.disabled = false;
    this.optimizationPromptInput.disabled = false;
    
    // Update download DOCX button
    this.downloadDocxBtn.disabled = false;
    this.downloadDocxBtn.classList.remove('bg-slate-800', 'text-slate-500', 'cursor-not-allowed', 'border-slate-700');
    this.downloadDocxBtn.classList.add('bg-gradient-to-tr', 'from-indigo-500', 'to-purple-600', 'text-white', 'hover:opacity-90', 'shadow-md');
    this.downloadDocxBtn.textContent = 'Word-Datei erzeugen';

    this.processBtn.textContent = 'Erneut extrahieren';
    this.processBtn.classList.add('bg-indigo-600', 'text-white', 'hover:bg-indigo-500');
    this.processBtn.classList.remove('bg-emerald-600', 'bg-slate-800', 'cursor-not-allowed', 'opacity-80');
    this.processBtn.disabled = false;
  }

  private async deleteTask(taskId: string) {
    if (!confirm('Möchtest du diesen Prozess und alle dazugehörigen Dateien wirklich löschen?')) return;
    try {
      const res = await fetch(`/api/tasks/${taskId}`, {
        method: 'DELETE'
      });
      if (!res.ok) throw new Error('Konnte Task nicht löschen.');
      this.log(`Prozess ${taskId} gelöscht.`, 'success');
      
      if (this.taskId === taskId) {
        this.resetFile();
      }
      this.refreshTasksList();
    } catch (err: any) {
      this.log(`Fehler beim Löschen: ${err.message}`, 'error');
    }
  }

  private async triggerDocxExport() {
    if (!this.taskId) return;
    
    this.log('Erzeuge native Word DOCX Datei...');
    const editedMarkdown = this.standardisedMarkdownTextarea.value;
    
    try {
      const res = await fetch('/api/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task_id: this.taskId,
          markdown: editedMarkdown,
          template_mode: this.templateModeSelect.value
        })
      });
      
      if (!res.ok) throw new Error('DOCX-Erzeugung fehlgeschlagen.');
      const data = await res.json();
      this.log('DOCX-Dokument erfolgreich erzeugt. Starte Download...', 'success');
      
      // Auto trigger download
      window.location.href = data.download_url;
      this.updateStepper('completed');
    } catch (err: any) {
      this.log(`Fehler beim DOCX-Export: ${err.message}`, 'error');
    }
  }

  private downloadTextFile(filename: string, text: string) {
    const element = document.createElement('a');
    element.setAttribute('href', 'data:text/markdown;charset=utf-8,' + encodeURIComponent(text));
    element.setAttribute('download', filename);
    element.style.display = 'none';
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
    this.log(`Datei heruntergeladen: ${filename}`);
  }

  private async optimizeTask() {
    if (!this.taskId) return;
    const prompt = this.optimizationPromptInput.value.trim();
    if (!prompt) return;

    try {
      this.btnOptimize.disabled = true;
      this.optimizationPromptInput.disabled = true;
      this.btnOptimize.innerHTML = `
        <svg class="animate-spin h-3.5 w-3.5 text-white mr-1.5 inline-block" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <span>Optimiert...</span>
      `;
      this.log('Optimiere E-Buch Markdown basierend auf Benutzerfeedback...');

      const ruleset = this.rulesetSelect.value;
      const currentMarkdown = this.standardisedMarkdownTextarea.value;

      const optimizeRes = await fetch('/api/optimize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task_id: this.taskId,
          prompt: prompt,
          current_markdown: currentMarkdown,
          ruleset: ruleset,
        }),
      });

      if (!optimizeRes.ok) throw new Error('Optimierung fehlgeschlagen.');
      const optimizedData = await optimizeRes.json();
      
      this.currentStandardisedMarkdown = optimizedData.markdown;
      this.standardisedMarkdownTextarea.value = this.currentStandardisedMarkdown;
      this.updatePagePills();
      this.updateCharReplaceBadge();
      this.log('E-Buch Markdown erfolgreich optimiert.', 'success');
      this.optimizationPromptInput.value = '';

      // Update view if currently in preview or diff mode
      if (this.btnDiffStandardised.classList.contains('bg-indigo-600')) {
        this.updateDiffView();
      } else if (this.btnRenderStandardised.classList.contains('bg-indigo-600')) {
        this.updateStandardisedRenderPreview();
      }
    } catch (err: any) {
      this.log(`Fehler bei der Optimierung: ${err.message}`, 'error');
    } finally {
      this.btnOptimize.disabled = false;
      this.optimizationPromptInput.disabled = false;
      this.btnOptimize.innerHTML = `<span>Optimieren</span>`;
    }
  }

  private initTheme() {
    // 1. Read persistent theme from localStorage
    const savedTheme = localStorage.getItem('color-scheme') || 'system';
    this.themeSelect.value = savedTheme;
    this.applyTheme(savedTheme);

    // 2. Add event listener to select
    this.themeSelect.addEventListener('change', () => {
      const selected = this.themeSelect.value;
      if (selected === 'system') {
        localStorage.removeItem('color-scheme');
      } else {
        localStorage.setItem('color-scheme', selected);
      }
      this.applyTheme(selected);
    });

    // 3. React to system preference changes at runtime
    const mediaDark = window.matchMedia('(prefers-color-scheme: dark)');
    const mediaContrast = window.matchMedia('(prefers-contrast: more)');
    
    const systemThemeChange = () => {
      if (this.themeSelect.value === 'system') {
        this.applyTheme('system');
      }
    };
    
    mediaDark.addEventListener('change', systemThemeChange);
    if (mediaContrast.addEventListener) {
      mediaContrast.addEventListener('change', systemThemeChange);
    }
  }

  private applyTheme(theme: string) {
    // Reset theme classes on html
    const htmlEl = document.documentElement;
    htmlEl.classList.remove('theme-light', 'theme-high-contrast');
    
    // Reset prose-invert classes
    this.rawMarkdownRendered.classList.remove('prose-invert');
    this.standardisedMarkdownRendered.classList.remove('prose-invert');
    
    let resolvedTheme = theme;
    if (theme === 'system') {
      const mediaContrast = window.matchMedia('(prefers-contrast: more)');
      const mediaDark = window.matchMedia('(prefers-color-scheme: dark)');
      
      if (mediaContrast.matches) {
        resolvedTheme = 'high-contrast';
      } else if (mediaDark.matches) {
        resolvedTheme = 'dark';
      } else {
        resolvedTheme = 'light';
      }
    }
    
    const metaScheme = document.querySelector('meta[name="color-scheme"]');
    
    if (resolvedTheme === 'light') {
      htmlEl.classList.add('theme-light');
      if (metaScheme) metaScheme.setAttribute('content', 'light');
    } else if (resolvedTheme === 'high-contrast') {
      htmlEl.classList.add('theme-high-contrast');
      if (metaScheme) metaScheme.setAttribute('content', 'dark');
    } else { // default dark
      if (metaScheme) metaScheme.setAttribute('content', 'dark');
      this.rawMarkdownRendered.classList.add('prose-invert');
      this.standardisedMarkdownRendered.classList.add('prose-invert');
    }
  }

  private initAccessibility() {
    // Keyboard listener for left sidebar handle
    this.leftSidebarHandle.addEventListener('keydown', (e: KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        this.leftSidebarHandle.click();
      }
    });

    // Keyboard listener for right sidebar handle
    this.rightSidebarHandle.addEventListener('keydown', (e: KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        this.rightSidebarHandle.click();
      }
    });
  }

  private initScrollSync() {
    this.isScrollSyncEnabled = true;

    const handleScrollBound = this.handleScroll.bind(this);
    
    this.rawMarkdownTextarea.addEventListener('scroll', handleScrollBound);
    this.rawMarkdownRendered.addEventListener('scroll', handleScrollBound);
    this.standardisedMarkdownTextarea.addEventListener('scroll', handleScrollBound);
    this.standardisedMarkdownRendered.addEventListener('scroll', handleScrollBound);
  }

  private getDivAnchors(div: HTMLDivElement): { pageNum: number; pos: number }[] {
    const anchors: { pageNum: number; pos: number }[] = [];
    const elements = Array.from(div.querySelectorAll('[data-page-anchor]'));
    elements.forEach(el => {
      const pageNum = parseInt(el.getAttribute('data-page-anchor') || '', 10);
      if (!isNaN(pageNum)) {
        const pos = (el as HTMLElement).offsetTop - div.offsetTop;
        anchors.push({ pageNum, pos });
      }
    });
    return anchors.sort((a, b) => a.pos - b.pos);
  }

  private getTextareaAnchors(textarea: HTMLTextAreaElement): { pageNum: number; pos: number }[] {
    const anchors: { pageNum: number; pos: number }[] = [];
    const text = textarea.value;
    const lines = text.split('\n');
    const totalLines = lines.length;
    const scrollHeight = textarea.scrollHeight;
    
    lines.forEach((line, index) => {
      const match = line.match(/\(\((\d+)\)\)/);
      if (match) {
        const pageNum = parseInt(match[1], 10);
        if (!isNaN(pageNum)) {
          const pos = (index / totalLines) * scrollHeight;
          anchors.push({ pageNum, pos });
        }
      }
    });
    return anchors.sort((a, b) => a.pos - b.pos);
  }

  private getScrollAnchors(el: HTMLElement): { pageNum: number; pos: number }[] {
    if (el instanceof HTMLTextAreaElement) {
      return this.getTextareaAnchors(el);
    } else if (el instanceof HTMLDivElement) {
      return this.getDivAnchors(el);
    }
    return [];
  }

  private updatePdfPage(pageNum: number) {
    if (pageNum === this.currentPdfPage || pageNum <= 0) return;
    this.currentPdfPage = pageNum;
    const relativePage = this.physicalStartPage > 0 ? (pageNum - this.physicalStartPage + 1) : pageNum;
    if (relativePage >= 1) {
      this.currentBboxPageIdx = relativePage - 1;
      if (this.isBboxOverlayActive) {
        this.renderBboxPage();
      }
    }
    if (this.pdfViewerFrame && this.taskId) {
      try {
        if (relativePage >= 1) {
          const url = `/api/pdf/${this.taskId}#page=${relativePage}`;
          const iframeWindow = this.pdfViewerFrame.contentWindow;
          if (iframeWindow) {
            iframeWindow.location.replace(url);
          } else {
            this.pdfViewerFrame.src = url;
          }
        }
      } catch (e) {
        console.error('Error syncing PDF scroll page:', e);
        if (relativePage >= 1) {
          this.pdfViewerFrame.src = `/api/pdf/${this.taskId}#page=${relativePage}`;
        }
      }
    }
  }

  private handleScroll(e: Event) {
    if (!this.isScrollSyncEnabled) return;
    const source = e.currentTarget as HTMLElement;
    
    if (this.activeScrollSource && this.activeScrollSource !== source) return;
    this.activeScrollSource = source;
    
    const scrollTop = source.scrollTop;
    const maxScroll = source.scrollHeight - source.clientHeight;
    
    const sourceAnchors = this.getScrollAnchors(source);
    const targets = [
      this.rawMarkdownTextarea,
      this.rawMarkdownRendered,
      this.standardisedMarkdownTextarea,
      this.standardisedMarkdownRendered
    ];
    
    let activePageNum = -1;
    
    if (sourceAnchors.length > 0 && maxScroll > 0) {
      let activeAnchorIdx = -1;
      for (let idx = 0; idx < sourceAnchors.length; idx++) {
        if (sourceAnchors[idx].pos <= scrollTop) {
          activeAnchorIdx = idx;
        } else {
          break;
        }
      }
      
      if (activeAnchorIdx === -1) {
        activePageNum = sourceAnchors[0].pageNum;
      } else {
        activePageNum = sourceAnchors[activeAnchorIdx].pageNum;
      }
      
      targets.forEach(target => {
        if (target && target !== source && !target.classList.contains('hidden')) {
          const targetAnchors = this.getScrollAnchors(target);
          const targetMaxScroll = target.scrollHeight - target.clientHeight;
          
          if (targetAnchors.length > 0 && targetMaxScroll > 0) {
            if (activeAnchorIdx === -1) {
              const nextSource = sourceAnchors[0];
              const nextTarget = targetAnchors.find(a => a.pageNum === nextSource.pageNum);
              if (nextTarget && nextSource.pos > 0) {
                const pct = scrollTop / nextSource.pos;
                target.scrollTop = pct * nextTarget.pos;
              } else {
                const pct = scrollTop / maxScroll;
                target.scrollTop = pct * targetMaxScroll;
              }
            } else if (activeAnchorIdx === sourceAnchors.length - 1) {
              const prevSource = sourceAnchors[activeAnchorIdx];
              const prevTarget = targetAnchors.find(a => a.pageNum === prevSource.pageNum);
              if (prevTarget && maxScroll > prevSource.pos) {
                const pct = (scrollTop - prevSource.pos) / (maxScroll - prevSource.pos);
                target.scrollTop = prevTarget.pos + pct * (targetMaxScroll - prevTarget.pos);
              } else {
                const pct = scrollTop / maxScroll;
                target.scrollTop = pct * targetMaxScroll;
              }
            } else {
              const prevSource = sourceAnchors[activeAnchorIdx];
              const nextSource = sourceAnchors[activeAnchorIdx + 1];
              const prevTarget = targetAnchors.find(a => a.pageNum === prevSource.pageNum);
              const nextTarget = targetAnchors.find(a => a.pageNum === nextSource.pageNum);
              
              if (prevTarget && nextTarget && nextSource.pos > prevSource.pos) {
                const pct = (scrollTop - prevSource.pos) / (nextSource.pos - prevSource.pos);
                target.scrollTop = prevTarget.pos + pct * (nextTarget.pos - prevTarget.pos);
              } else {
                const pct = scrollTop / maxScroll;
                target.scrollTop = pct * targetMaxScroll;
              }
            }
          } else {
            const pct = scrollTop / (maxScroll || 1);
            target.scrollTop = pct * targetMaxScroll;
          }
        }
      });
    } else {
      const pct = scrollTop / (maxScroll || 1);
      targets.forEach(target => {
        if (target && target !== source && !target.classList.contains('hidden')) {
          target.scrollTop = pct * (target.scrollHeight - target.clientHeight);
        }
      });
    }
    
    if (activePageNum > 0) {
      this.updatePdfPage(activePageNum);
    }
    
    clearTimeout(this.scrollTimeout);
    this.scrollTimeout = setTimeout(() => {
      this.activeScrollSource = null;
    }, 100);
  }

  private validatePages(pagesVal: string, pageCount: number, physicalStartPage?: number): { isValid: boolean; error?: string } {
    if (!pagesVal.trim()) {
      return { isValid: true };
    }
    
    if (!/^[0-9,\-\s]+$/.test(pagesVal)) {
      return { 
        isValid: false, 
        error: 'Die Seitenauswahl enthält ungültige Zeichen. Erlaubt sind nur Zahlen, Kommas, Bindestriche und Leerzeichen (z. B. "1, 3, 5-10").' 
      };
    }

    const parts = pagesVal.split(',');
    const allPages: number[] = [];
    for (let part of parts) {
      part = part.trim();
      if (!part) continue;
      
      if (part.includes('-')) {
        const subparts = part.split('-');
        if (subparts.length !== 2) {
          return {
            isValid: false,
            error: `Ungültiger Seitenbereich: "${part}". Ein Bereich muss genau zwei Zahlen getrennt durch einen Bindestrich enthalten (z. B. "5-10").`
          };
        }
        const startStr = subparts[0].trim();
        const endStr = subparts[1].trim();
        if (!/^\d+$/.test(startStr) || !/^\d+$/.test(endStr)) {
          return {
            isValid: false,
            error: `Ungültiger Seitenbereich: "${part}". Start- und Endwert müssen positive Ganzzahlen sein.`
          };
        }
        const start = parseInt(startStr, 10);
        const end = parseInt(endStr, 10);
        if (start === 0 || end === 0) {
          return {
            isValid: false,
            error: `Ungültiger Seitenbereich: "${part}". Seitenzahlen müssen bei 1 beginnen.`
          };
        }
        if (start > end) {
          return {
            isValid: false,
            error: `Ungültiger Seitenbereich: "${part}". Der Startwert muss kleiner oder gleich dem Endwert sein.`
          };
        }
        for (let p = start; p <= end; p++) {
          allPages.push(p);
        }
      } else {
        if (!/^\d+$/.test(part)) {
          return {
            isValid: false,
            error: `Ungültige Seitenzahl: "${part}". Seitenzahlen müssen positive Ganzzahlen sein.`
          };
        }
        const p = parseInt(part, 10);
        if (p === 0) {
          return {
            isValid: false,
            error: `Ungültige Seitenzahl: "${part}". Seitenzahlen müssen bei 1 beginnen.`
          };
        }
        allPages.push(p);
      }
    }
    
    if (allPages.length === 0) {
      return { isValid: true };
    }

    const minPage = Math.min(...allPages);
    const maxPage = Math.max(...allPages);
    const totalSelected = allPages.length;

    const physicalStart = physicalStartPage || this.physicalStartPage || 1;
    const isPhysicalOffset = physicalStart > 1 || minPage > (pageCount + 5);

    if (isPhysicalOffset) {
      for (const p of allPages) {
        if (p < physicalStart || p >= physicalStart + pageCount) {
          if (p < 1 || p > pageCount) {
            return {
              isValid: false,
              error: `Seitenzahl "${p}" liegt außerhalb des gültigen Bereichs (relativ 1-${pageCount} oder physisch ${physicalStart}-${physicalStart + pageCount - 1}).`
            };
          }
        }
      }
      if (totalSelected > pageCount) {
        return {
          isValid: false,
          error: `Seitenauswahl umfasst ${totalSelected} Seiten, aber die PDF-Datei hat nur ${pageCount} ${pageCount === 1 ? 'Seite' : 'Seiten'}.`
        };
      }
    } else {
      if (maxPage > pageCount) {
        return {
          isValid: false,
          error: `Seitenauswahl "${maxPage}" liegt außerhalb des gültigen Bereichs (1-${pageCount}).`
        };
      }
    }
    
    return { isValid: true };
  }

  private showInputError(input: HTMLInputElement, errorElem: HTMLElement | null, errorTextElem: HTMLElement | null, errorMsg: string) {
    input.classList.remove('border-slate-800', 'focus:border-indigo-500');
    input.classList.add('border-rose-500', 'focus:border-rose-500', 'bg-rose-950/20');
    if (errorElem && errorTextElem) {
      errorTextElem.textContent = errorMsg;
      errorElem.classList.remove('hidden');
    }
  }

  private clearInputError(input: HTMLInputElement, errorElem: HTMLElement | null) {
    input.classList.remove('border-rose-500', 'focus:border-rose-500', 'bg-rose-950/20');
    input.classList.add('border-slate-800', 'focus:border-indigo-500');
    if (errorElem) {
      errorElem.classList.add('hidden');
    }
  }

  private showErrorModal(message: string, title: string = 'Seitenauswahl fehlerhaft') {
    if (this.errorModalTitle) {
      this.errorModalTitle.textContent = title;
    }
    this.errorModalMessage.textContent = message;
    this.errorModal.classList.remove('hidden');
    this.errorModalCloseBtn.focus();
  }

  private showToast(message: string) {
    const toast = document.createElement('div');
    toast.className = 'fixed bottom-6 right-6 z-50 px-4 py-3 rounded-xl bg-slate-900/95 border border-emerald-500/50 text-emerald-300 shadow-2xl flex items-center space-x-2 text-xs font-semibold pointer-events-none transition-all duration-300 backdrop-blur-md';
    toast.innerHTML = `<span>${message}</span>`;
    document.body.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 300);
    }, 3500);
  }

  private hideErrorModal() {
    this.errorModal.classList.add('hidden');
    const isBenchView = this.mainBenchmarkView && !this.mainBenchmarkView.classList.contains('hidden');
    if (isBenchView && this.benchPagesInput) {
      this.benchPagesInput.focus();
    } else if (this.pagesInput) {
      this.pagesInput.focus();
    }
  }

  private updatePagePills() {
    if (!this.pdfPagePillsContainer) return;
    const md = this.standardisedMarkdownTextarea.value || this.rawMarkdownTextarea.value;
    const matches = [...md.matchAll(/\(\((\d+)\)\)/g)];
    const uniquePages = [...new Set(matches.map(m => parseInt(m[1], 10)))].sort((a, b) => a - b);
    
    if (uniquePages.length === 0) {
      this.pdfPagePillsContainer.innerHTML = '<span class="text-[9px] bg-slate-800 text-slate-400 px-1.5 py-0.5 rounded border border-slate-750">PDF-Vorschau</span>';
      return;
    }

    this.pdfPagePillsContainer.innerHTML = uniquePages.map(p => `
      <button data-page="${p}" class="pdf-page-pill text-[9px] bg-slate-800 hover:bg-indigo-600 hover:text-white text-slate-300 px-1.5 py-0.5 rounded border border-slate-700 transition-colors cursor-pointer flex-shrink-0" title="Springe zu Seite ${p}">
        S. ${p}
      </button>
    `).join('');

    this.pdfPagePillsContainer.querySelectorAll('.pdf-page-pill').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const p = parseInt((e.currentTarget as HTMLElement).getAttribute('data-page') || '1', 10);
        this.jumpToPage(p);
      });
    });
    this.updateCharReplaceBadge();
  }

  private jumpToPage(pageNum: number) {
    this.updatePdfPage(pageNum);
    this.highlightPagePill(pageNum);

    // Jump editor scroll & cursor to ((pageNum))
    const text = this.standardisedMarkdownTextarea.value;
    const tag = `((${pageNum}))`;
    const idx = text.indexOf(tag);
    if (idx !== -1) {
      this.standardisedMarkdownTextarea.focus();
      this.standardisedMarkdownTextarea.setSelectionRange(idx, idx + tag.length);
      
      const linesBefore = text.slice(0, idx).split('\n').length;
      const totalLines = text.split('\n').length;
      const ratio = linesBefore / totalLines;
      this.standardisedMarkdownTextarea.scrollTop = ratio * this.standardisedMarkdownTextarea.scrollHeight;
    }
  }

  private highlightPagePill(pageNum: number) {
    if (!this.pdfPagePillsContainer) return;
    this.pdfPagePillsContainer.querySelectorAll('.pdf-page-pill').forEach(el => {
      const p = parseInt(el.getAttribute('data-page') || '0', 10);
      if (p === pageNum) {
        el.className = 'pdf-page-pill text-[9px] bg-indigo-600 text-white font-bold px-1.5 py-0.5 rounded border border-indigo-400 shadow-sm transition-colors cursor-pointer flex-shrink-0';
      } else {
        el.className = 'pdf-page-pill text-[9px] bg-slate-800 hover:bg-indigo-600 hover:text-white text-slate-300 px-1.5 py-0.5 rounded border border-slate-700 transition-colors cursor-pointer flex-shrink-0';
      }
    });
  }

  // -------------------------------------------------------------
  // Interactive Grounding BBox Overlay (#pdf-bbox-viewer)
  // -------------------------------------------------------------

  private initBboxOverlayEvents() {
    if (this.btnToggleBboxOverlay) {
      this.btnToggleBboxOverlay.addEventListener('click', () => {
        this.setBboxOverlayActive(!this.isBboxOverlayActive);
      });
    }
    if (this.bboxPrevPageBtn) {
      this.bboxPrevPageBtn.addEventListener('click', () => {
        if (this.currentBboxPageIdx > 0) {
          this.currentBboxPageIdx--;
          this.renderBboxPage();
          const physPage = (this.physicalStartPage || 1) + this.currentBboxPageIdx;
          this.currentPdfPage = physPage;
          this.highlightPagePill(physPage);
        }
      });
    }
    if (this.bboxNextPageBtn) {
      this.bboxNextPageBtn.addEventListener('click', () => {
        const totalPages = this.getTotalBboxPages();
        if (this.currentBboxPageIdx < totalPages - 1) {
          this.currentBboxPageIdx++;
          this.renderBboxPage();
          const physPage = (this.physicalStartPage || 1) + this.currentBboxPageIdx;
          this.currentPdfPage = physPage;
          this.highlightPagePill(physPage);
        }
      });
    }
  }

  private setBboxOverlayActive(active: boolean) {
    this.isBboxOverlayActive = active;
    if (this.btnToggleBboxOverlay) {
      this.btnToggleBboxOverlay.setAttribute('aria-pressed', String(active));
      if (active) {
        this.btnToggleBboxOverlay.classList.remove('bg-slate-800', 'text-slate-300', 'border-slate-700');
        this.btnToggleBboxOverlay.classList.add('bg-indigo-600', 'text-white', 'border-indigo-500');
      } else {
        this.btnToggleBboxOverlay.classList.remove('bg-indigo-600', 'text-white', 'border-indigo-500');
        this.btnToggleBboxOverlay.classList.add('bg-slate-800', 'text-slate-300', 'border-slate-700');
      }
    }

    if (active) {
      if (!this.isPdfPaneVisible) {
        this.isPdfPaneVisible = true;
        this.updatePaneVisibility();
      }
      this.pdfViewerFrame.classList.add('hidden');
      this.pdfBboxViewer?.classList.remove('hidden');
      this.loadAndRenderBboxOverlay();
    } else {
      this.pdfBboxViewer?.classList.add('hidden');
      this.pdfViewerFrame.classList.remove('hidden');
    }
  }

  private getTotalBboxPages(): number {
    const cached = this.taskId ? this.layoutCache.get(this.taskId) : undefined;
    let maxBlockPage = 0;
    if (cached && cached.blocks.length > 0) {
      for (const b of cached.blocks) {
        if (b.page_idx + 1 > maxBlockPage) {
          maxBlockPage = b.page_idx + 1;
        }
      }
    }
    return Math.max(1, this.activePageCount, maxBlockPage);
  }

  private async loadAndRenderBboxOverlay() {
    if (!this.taskId) {
      this.renderBboxPage();
      return;
    }
    const taskId = this.taskId;
    if (!this.layoutCache.has(taskId)) {
      try {
        const res = await fetch(`/api/tasks/${taskId}/layout`);
        if (res.ok) {
          const data = await res.json();
          this.layoutCache.set(taskId, {
            physical_start_page: data.physical_start_page || this.physicalStartPage || 1,
            blocks: Array.isArray(data.blocks) ? data.blocks : [],
          });
          if (data.physical_start_page) {
            this.physicalStartPage = data.physical_start_page;
          }
        } else {
          this.layoutCache.set(taskId, { physical_start_page: this.physicalStartPage || 1, blocks: [] });
        }
      } catch (e) {
        console.warn('Could not load layout blocks for task:', e);
        this.layoutCache.set(taskId, { physical_start_page: this.physicalStartPage || 1, blocks: [] });
      }
    }
    this.renderBboxPage();
  }

  private getBboxCategoryMeta(block: { type: string; is_callout_box?: boolean }): {
    key: string;
    tagLabel: string;
    chipLabel: string;
    color: string;
  } {
    const rawType = (block.type || 'text').toLowerCase();
    if (block.is_callout_box || rawType === 'callout' || rawType === 'aside_text') {
      return { key: rawType, tagLabel: 'callout', chipLabel: 'Rahmen', color: '#ea580c' };
    }
    if (rawType === 'title' || rawType === 'section_header' || rawType === 'heading' || rawType === 'section') {
      return { key: rawType, tagLabel: 'title', chipLabel: 'Überschrift', color: '#d97706' };
    }
    if (rawType === 'image' || rawType === 'picture' || rawType === 'figure' || rawType === 'chart') {
      return { key: rawType, tagLabel: 'image', chipLabel: 'Bild', color: '#0d9488' };
    }
    if (rawType === 'table') {
      return { key: rawType, tagLabel: 'table', chipLabel: 'Tabelle', color: '#dc2626' };
    }
    if (rawType === 'formula' || rawType === 'equation') {
      return { key: rawType, tagLabel: 'formula', chipLabel: 'Formel', color: '#0891b2' };
    }
    if (
      rawType === 'page_header' ||
      rawType === 'page_footer' ||
      rawType === 'header' ||
      rawType === 'footer' ||
      rawType === 'page_number' ||
      rawType === 'furniture'
    ) {
      return { key: rawType, tagLabel: 'furniture', chipLabel: 'Kopf-/Fußzeile', color: '#64748b' };
    }
    if (rawType === 'list' || rawType === 'list_item') {
      return { key: rawType, tagLabel: 'text', chipLabel: 'Liste', color: '#0284c7' };
    }
    if (rawType === 'caption' || rawType === 'footnote') {
      return { key: rawType, tagLabel: 'text', chipLabel: 'Bildtext', color: '#b45309' };
    }
    return { key: rawType, tagLabel: 'text', chipLabel: 'Text', color: '#2563eb' };
  }

  private renderBboxPage() {
    if (!this.bboxOverlayLayer || !this.bboxFilterChips || !this.bboxPageIndicator) return;

    const totalPages = this.getTotalBboxPages();
    if (this.currentBboxPageIdx >= totalPages) {
      this.currentBboxPageIdx = Math.max(0, totalPages - 1);
    }
    if (this.currentBboxPageIdx < 0) {
      this.currentBboxPageIdx = 0;
    }

    this.bboxPageIndicator.textContent = `Seite ${this.currentBboxPageIdx + 1} / ${totalPages}`;
    if (this.bboxPrevPageBtn) {
      this.bboxPrevPageBtn.disabled = this.currentBboxPageIdx <= 0;
    }
    if (this.bboxNextPageBtn) {
      this.bboxNextPageBtn.disabled = this.currentBboxPageIdx >= totalPages - 1;
    }

    if (this.bboxPageImg && this.taskId) {
      const targetSrc = `/api/feedback/jobs/${this.taskId}/pages/${this.currentBboxPageIdx}?scale=2.0`;
      if (this.bboxPageImg.getAttribute('src') !== targetSrc) {
        this.bboxPageImg.src = targetSrc;
      }
    }

    const cached = this.taskId ? this.layoutCache.get(this.taskId) : undefined;
    const allBlocks = cached?.blocks || [];
    const pageBlocks = allBlocks.filter(b => (b.page_idx || 0) === this.currentBboxPageIdx);

    // Count blocks by type on current page
    const countsByType = new Map<string, { count: number; chipLabel: string; color: string }>();
    for (const b of pageBlocks) {
      const meta = this.getBboxCategoryMeta(b);
      const existing = countsByType.get(meta.key);
      if (existing) {
        existing.count++;
      } else {
        countsByType.set(meta.key, { count: 1, chipLabel: meta.chipLabel, color: meta.color });
      }
    }

    // If active filter is not present on this page, reset to 'all'
    if (this.activeBboxFilter !== 'all' && !countsByType.has(this.activeBboxFilter)) {
      this.activeBboxFilter = 'all';
    }

    // Render filter chips
    this.bboxFilterChips.replaceChildren();
    const allChip = document.createElement('button');
    allChip.type = 'button';
    allChip.className = 'bbox-filter-chip';
    allChip.dataset.filter = 'all';
    allChip.setAttribute('aria-pressed', String(this.activeBboxFilter === 'all'));
    allChip.innerHTML = `<span>Alle</span><span class="font-mono tabular-nums text-[9px] opacity-80">${pageBlocks.length}</span>`;
    allChip.addEventListener('click', () => {
      this.activeBboxFilter = 'all';
      this.renderBboxPage();
    });
    this.bboxFilterChips.appendChild(allChip);

    for (const [typeKey, info] of countsByType.entries()) {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'bbox-filter-chip';
      chip.dataset.filter = typeKey;
      chip.style.setProperty('--bbox-color', info.color);
      chip.setAttribute('aria-pressed', String(this.activeBboxFilter === typeKey));
      chip.innerHTML = `<span class="bbox-filter-chip-dot"></span><span>${info.chipLabel}</span><span class="font-mono tabular-nums text-[9px] opacity-80">${info.count}</span>`;
      chip.addEventListener('click', () => {
        this.activeBboxFilter = this.activeBboxFilter === typeKey ? 'all' : typeKey;
        this.renderBboxPage();
      });
      this.bboxFilterChips.appendChild(chip);
    }

    // Render bounding box rectangles
    this.bboxOverlayLayer.replaceChildren();
    pageBlocks.forEach((b, idx) => {
      const meta = this.getBboxCategoryMeta(b);
      if (this.activeBboxFilter !== 'all' && meta.key !== this.activeBboxFilter) return;
      if (!Array.isArray(b.bbox_1000) || b.bbox_1000.length < 4) return;

      const [x1, y1, x2, y2] = b.bbox_1000;
      const rect = document.createElement('div');
      rect.className = 'bbox-rect';
      rect.dataset.blockType = b.type;
      rect.dataset.blockIdx = String(idx);
      rect.style.left = `${x1 / 10}%`;
      rect.style.top = `${y1 / 10}%`;
      rect.style.width = `${Math.max(0.5, (x2 - x1) / 10)}%`;
      rect.style.height = `${Math.max(0.5, (y2 - y1) / 10)}%`;
      rect.style.setProperty('--bbox-color', meta.color);

      const snippet = (b.text || '').trim();
      rect.title = snippet ? `[${meta.tagLabel}] ${snippet}` : `[${meta.tagLabel}]`;

      const tag = document.createElement('span');
      tag.className = 'bbox-tag';
      tag.textContent = meta.tagLabel;
      rect.appendChild(tag);

      rect.addEventListener('mouseenter', () => {
        rect.classList.add('is-active');
      });
      rect.addEventListener('mouseleave', () => {
        rect.classList.remove('is-active');
      });
      rect.addEventListener('click', () => {
        this.bboxOverlayLayer?.querySelectorAll('.bbox-rect.is-active').forEach(el => el.classList.remove('is-active'));
        rect.classList.add('is-active');
        if (snippet) {
          this.highlightMarkdownSnippet(snippet);
        }
      });

      this.bboxOverlayLayer!.appendChild(rect);
    });
  }

  private highlightMarkdownSnippet(snippet: string) {
    const cleaned = snippet.replace(/^#+\s*/, '').trim();
    if (!cleaned) return;

    const candidates = [
      cleaned,
      cleaned.split(/\r?\n/)[0].trim(),
      cleaned.slice(0, 32).trim(),
    ].filter(Boolean);

    const trySelectInTextarea = (textarea: HTMLTextAreaElement): boolean => {
      const content = textarea.value;
      if (!content) return false;
      for (const needle of candidates) {
        const idx = content.indexOf(needle);
        if (idx !== -1) {
          textarea.focus();
          textarea.setSelectionRange(idx, idx + needle.length);
          const linesBefore = content.slice(0, idx).split('\n').length;
          const totalLines = Math.max(1, content.split('\n').length);
          textarea.scrollTop = Math.max(0, (linesBefore / totalLines) * textarea.scrollHeight - textarea.clientHeight * 0.35);
          return true;
        }
      }
      return false;
    };

    if (this.isStandardisedPaneVisible && !this.standardisedMarkdownTextarea.classList.contains('hidden')) {
      if (trySelectInTextarea(this.standardisedMarkdownTextarea)) return;
    }
    if (this.isRawPaneVisible && !this.rawMarkdownTextarea.classList.contains('hidden')) {
      if (trySelectInTextarea(this.rawMarkdownTextarea)) return;
    }
    if (! trySelectInTextarea(this.standardisedMarkdownTextarea)) {
      trySelectInTextarea(this.rawMarkdownTextarea);
    }
  }

  // -------------------------------------------------------------
  // Eurobraille / ISO 8859-1 (> U+00FF) Character Replacement Assistant
  // -------------------------------------------------------------

  private loadCharReplacementsFromStorage() {
    try {
      const raw = localStorage.getItem('ebuch_char_replacements_v1');
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') return;
      for (const [ch, entry] of Object.entries(parsed)) {
        if (typeof entry === 'string') {
          this.charReplacements.set(ch, { replacement: entry, active: true });
        } else if (entry && typeof entry === 'object') {
          const obj = entry as { replacement?: string; value?: string; active?: boolean };
          this.charReplacements.set(ch, {
            replacement: String(obj.replacement ?? obj.value ?? ''),
            active: obj.active !== false,
          });
        }
      }
    } catch (e) {
      console.warn('Could not load ebuch_char_replacements_v1 from localStorage:', e);
    }
  }

  private saveCharReplacementsToStorage() {
    try {
      const serialized: Record<string, { replacement: string; active: boolean }> = {};
      for (const [ch, cfg] of this.charReplacements.entries()) {
        serialized[ch] = { replacement: cfg.replacement, active: cfg.active };
      }
      localStorage.setItem('ebuch_char_replacements_v1', JSON.stringify(serialized));
    } catch (e) {
      console.warn('Could not persist ebuch_char_replacements_v1:', e);
    }
  }

  private getActiveMarkdownForCharScan(): string {
    return this.standardisedMarkdownTextarea.value || this.rawMarkdownTextarea.value || '';
  }

  private scanNonLatin1Chars(text: string): Array<{ char: string; code: string; count: number }> {
    const counts = new Map<string, number>();
    for (const ch of text) {
      const cp = ch.codePointAt(0) ?? 0;
      if (cp <= 0xff || /\s/.test(ch)) continue;
      counts.set(ch, (counts.get(ch) ?? 0) + 1);
    }
    return [...counts.entries()]
      .map(([char, count]) => {
        const cp = char.codePointAt(0) ?? 0;
        const code = 'U+' + cp.toString(16).toUpperCase().padStart(4, '0');
        return { char, code, count };
      })
      .sort((a, b) => (a.char.codePointAt(0) ?? 0) - (b.char.codePointAt(0) ?? 0));
  }

  private updateCharReplaceBadge() {
    if (!this.charReplaceBadge) return;
    const items = this.scanNonLatin1Chars(this.getActiveMarkdownForCharScan());
    if (items.length > 0) {
      this.charReplaceBadge.textContent = String(items.length);
      this.charReplaceBadge.classList.remove('hidden');
    } else {
      this.charReplaceBadge.textContent = '0';
      this.charReplaceBadge.classList.add('hidden');
    }
  }

  private initCharReplacementEvents() {
    if (this.btnCharReplacements) {
      this.btnCharReplacements.addEventListener('click', () => this.openCharReplaceModal());
    }
    if (this.closeCharReplaceModalBtn) {
      this.closeCharReplaceModalBtn.addEventListener('click', () => this.closeCharReplaceModal());
    }
    if (this.cancelCharReplaceModalBtn) {
      this.cancelCharReplaceModalBtn.addEventListener('click', () => this.closeCharReplaceModal());
    }
    if (this.charReplaceModal) {
      this.charReplaceModal.addEventListener('click', (e) => {
        if (e.target === this.charReplaceModal) {
          this.closeCharReplaceModal();
        }
      });
    }
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && this.charReplaceModal && !this.charReplaceModal.classList.contains('hidden')) {
        this.closeCharReplaceModal();
      }
    });
    if (this.btnSuggestCharReplacements) {
      this.btnSuggestCharReplacements.addEventListener('click', () => this.fetchCharReplacementSuggestions());
    }
    if (this.btnApplyCharReplacements) {
      this.btnApplyCharReplacements.addEventListener('click', () => this.applyCharReplacements());
    }
    if (this.btnExportCharMap) {
      this.btnExportCharMap.addEventListener('click', () => this.exportCharReplacementsJson());
    }
    if (this.btnImportCharMap && this.charMapFileInput) {
      this.btnImportCharMap.addEventListener('click', () => this.charMapFileInput!.click());
      this.charMapFileInput.addEventListener('change', () => this.importCharReplacementsJson());
    }
  }

  private openCharReplaceModal() {
    if (!this.charReplaceModal) return;
    this.renderCharReplaceTable();
    this.charReplaceModal.classList.remove('hidden');
  }

  private closeCharReplaceModal() {
    if (!this.charReplaceModal) return;
    this.charReplaceModal.classList.add('hidden');
  }

  private syncCharTableInputsToMap() {
    if (!this.charReplaceTbody) return;
    const rows = this.charReplaceTbody.querySelectorAll('tr[data-char]');
    rows.forEach(row => {
      const ch = row.getAttribute('data-char');
      if (!ch) return;
      const input = row.querySelector('.char-replace-input') as HTMLInputElement | null;
      const checkbox = row.querySelector('.char-replace-active') as HTMLInputElement | null;
      this.charReplacements.set(ch, {
        replacement: input ? input.value : '',
        active: checkbox ? checkbox.checked : true,
      });
    });
  }

  private renderCharReplaceTable() {
    if (!this.charReplaceTbody) return;
    const items = this.scanNonLatin1Chars(this.getActiveMarkdownForCharScan());
    this.charReplaceTbody.replaceChildren();

    if (items.length === 0) {
      const tr = document.createElement('tr');
      tr.innerHTML = '<td colspan="5" class="py-6 px-4 text-center text-slate-500 italic">Keine Zeichen oberhalb von U+00FF im aktuellen Dokument gefunden.</td>';
      this.charReplaceTbody.appendChild(tr);
      if (this.charReplaceStatus) {
        this.charReplaceStatus.textContent = '0 Zeichen > U+00FF';
      }
      return;
    }

    let unresolvedCount = 0;
    for (const item of items) {
      const saved = this.charReplacements.get(item.char) ?? { replacement: '', active: true };
      if (!saved.replacement.trim()) unresolvedCount++;

      const tr = document.createElement('tr');
      tr.dataset.char = item.char;
      tr.className = 'hover:bg-slate-900/50 transition-colors';

      const tdChar = document.createElement('td');
      tdChar.className = 'py-2 px-4 font-mono text-sm font-bold text-slate-100';
      tdChar.textContent = item.char;

      const tdCode = document.createElement('td');
      tdCode.className = 'py-2 px-4 font-mono tabular-nums text-slate-400';
      tdCode.textContent = item.code;

      const tdCount = document.createElement('td');
      tdCount.className = 'py-2 px-4 font-mono tabular-nums text-slate-300';
      tdCount.textContent = String(item.count);

      const tdInput = document.createElement('td');
      tdInput.className = 'py-2 px-4';
      const input = document.createElement('input');
      input.type = 'text';
      input.className = 'char-replace-input w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1 text-xs font-mono text-slate-100 focus:outline-none focus:border-indigo-500';
      input.value = saved.replacement;
      input.dataset.char = item.char;
      input.placeholder = 'z. B. \\rightarrow';
      input.setAttribute('aria-label', `Ersetzung für ${item.char} (${item.code})`);
      input.addEventListener('input', () => {
        const cur = this.charReplacements.get(item.char) ?? { replacement: '', active: true };
        this.charReplacements.set(item.char, { replacement: input.value, active: cur.active });
        this.saveCharReplacementsToStorage();
      });
      tdInput.appendChild(input);

      const tdActive = document.createElement('td');
      tdActive.className = 'py-2 px-4 text-center';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.className = 'char-replace-active rounded border-slate-700 bg-slate-950 text-indigo-600 focus:ring-indigo-500 cursor-pointer';
      checkbox.checked = saved.active;
      checkbox.dataset.char = item.char;
      checkbox.setAttribute('aria-label', `Ersetzung für ${item.char} aktivieren`);
      checkbox.addEventListener('change', () => {
        const cur = this.charReplacements.get(item.char) ?? { replacement: input.value, active: true };
        this.charReplacements.set(item.char, { replacement: cur.replacement, active: checkbox.checked });
        this.saveCharReplacementsToStorage();
      });
      tdActive.appendChild(checkbox);

      tr.append(tdChar, tdCode, tdCount, tdInput, tdActive);
      this.charReplaceTbody.appendChild(tr);
    }

    if (this.charReplaceStatus) {
      this.charReplaceStatus.textContent = unresolvedCount > 0
        ? `${items.length} Zeichen > U+00FF (${unresolvedCount} offen)`
        : `${items.length} Zeichen > U+00FF (alle zugeordnet)`;
    }
  }

  private async fetchCharReplacementSuggestions() {
    this.syncCharTableInputsToMap();
    const items = this.scanNonLatin1Chars(this.getActiveMarkdownForCharScan());
    if (items.length === 0) return;

    const unresolved = items
      .filter(it => !(this.charReplacements.get(it.char)?.replacement.trim()))
      .map(it => it.char);
    const charsToQuery = unresolved.length > 0 ? unresolved : items.map(it => it.char);

    if (this.btnSuggestCharReplacements) {
      this.btnSuggestCharReplacements.disabled = true;
    }
    if (this.charReplaceStatus) {
      this.charReplaceStatus.textContent = `Lade Vorschläge für ${charsToQuery.length} Zeichen…`;
    }

    try {
      const res = await fetch('/api/char-replacements/suggest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chars: charsToQuery }),
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      const suggestions: Record<string, string> = data.suggestions || {};
      let appliedCount = 0;
      for (const [ch, val] of Object.entries(suggestions)) {
        if (typeof val === 'string' && val.trim()) {
          this.charReplacements.set(ch, { replacement: val.trim(), active: true });
          appliedCount++;
        }
      }
      this.saveCharReplacementsToStorage();
      this.renderCharReplaceTable();
      if (this.charReplaceStatus) {
        this.charReplaceStatus.textContent = `${appliedCount} Vorschläge übernommen`;
      }
    } catch (e: any) {
      if (this.charReplaceStatus) {
        this.charReplaceStatus.textContent = `Fehler: ${e.message || 'Vorschläge fehlgeschlagen'}`;
      }
    } finally {
      if (this.btnSuggestCharReplacements) {
        this.btnSuggestCharReplacements.disabled = false;
      }
    }
  }

  private applyCharReplacements() {
    this.syncCharTableInputsToMap();
    this.saveCharReplacementsToStorage();

    const useStandardised = Boolean(this.standardisedMarkdownTextarea.value);
    let targetText = useStandardised
      ? this.standardisedMarkdownTextarea.value
      : this.rawMarkdownTextarea.value;

    let replacedOccurrences = 0;
    for (const [ch, cfg] of this.charReplacements.entries()) {
      if (!cfg.active || !cfg.replacement) continue;
      if (targetText.includes(ch)) {
        const parts = targetText.split(ch);
        replacedOccurrences += parts.length - 1;
        targetText = parts.join(cfg.replacement);
      }
    }

    if (useStandardised) {
      this.standardisedMarkdownTextarea.value = targetText;
      this.currentStandardisedMarkdown = targetText;
      if (this.isStandardisedRendered) {
        this.updateStandardisedRenderPreview();
      }
      if (this.btnDiffStandardised.classList.contains('bg-indigo-600')) {
        this.updateDiffView();
      }
    } else {
      this.rawMarkdownTextarea.value = targetText;
      this.currentRawMarkdown = targetText;
      if (this.isRawRendered) {
        this.updateRawRenderPreview();
      }
    }

    this.updatePagePills();
    this.updateCharReplaceBadge();
    this.closeCharReplaceModal();
    if (replacedOccurrences > 0) {
      this.log(`${replacedOccurrences} Sonderzeichen (> U+00FF) im Text ersetzt.`, 'success');
    }
  }

  private exportCharReplacementsJson() {
    this.syncCharTableInputsToMap();
    this.saveCharReplacementsToStorage();
    const out: Record<string, string> = {};
    for (const [ch, cfg] of this.charReplacements.entries()) {
      if (cfg.replacement) {
        out[ch] = cfg.replacement;
      }
    }
    const jsonStr = JSON.stringify(out, null, 2);
    const el = document.createElement('a');
    el.setAttribute('href', 'data:application/json;charset=utf-8,' + encodeURIComponent(jsonStr));
    el.setAttribute('download', 'sonderzeichen-ersetzungen.json');
    el.style.display = 'none';
    document.body.appendChild(el);
    el.click();
    document.body.removeChild(el);
  }

  private async importCharReplacementsJson() {
    const file = this.charMapFileInput?.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      if (parsed && typeof parsed === 'object') {
        for (const [ch, val] of Object.entries(parsed)) {
          if (typeof val === 'string') {
            this.charReplacements.set(ch, { replacement: val, active: true });
          } else if (val && typeof val === 'object') {
            const obj = val as { replacement?: string; value?: string; active?: boolean };
            this.charReplacements.set(ch, {
              replacement: String(obj.replacement ?? obj.value ?? ''),
              active: obj.active !== false,
            });
          }
        }
        this.saveCharReplacementsToStorage();
        this.renderCharReplaceTable();
      }
    } catch (e: any) {
      if (this.charReplaceStatus) {
        this.charReplaceStatus.textContent = `JSON-Import fehlgeschlagen: ${e.message}`;
      }
    } finally {
      if (this.charMapFileInput) {
        this.charMapFileInput.value = '';
      }
    }
  }

  // -------------------------------------------------------------
  // Custom Benchmark & Evaluation UI Methods
  // -------------------------------------------------------------

  private initBenchmarkEvents() {
    // Mode dropdown switching (Übertragung / Benchmark & Evaluierung / Feedback)
    if (this.mainModeSelect) {
      this.mainModeSelect.addEventListener('change', () => {
        this.switchMainView(this.mainModeSelect.value as MainView);
      });
    }

    // Source PDF upload & drag/drop
    if (this.benchSourceDropzone && this.benchSourceFileInput) {
      this.benchSourceDropzone.addEventListener('click', () => this.benchSourceFileInput.click());
      this.benchSourceFileInput.addEventListener('change', (e) => {
        const input = e.target as HTMLInputElement;
        if (input.files?.length) {
          this.handleBenchmarkSourceSelect(input.files[0]);
        }
      });
      this.benchSourceDropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        this.benchSourceDropzone.classList.add('border-indigo-500', 'bg-indigo-500/10');
      });
      this.benchSourceDropzone.addEventListener('dragleave', () => {
        this.benchSourceDropzone.classList.remove('border-indigo-500', 'bg-indigo-500/10');
      });
      this.benchSourceDropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        this.benchSourceDropzone.classList.remove('border-indigo-500', 'bg-indigo-500/10');
        if (e.dataTransfer?.files.length) {
          this.handleBenchmarkSourceSelect(e.dataTransfer.files[0]);
        }
      });
    }

    // Ground Truth Markdown upload & drag/drop
    if (this.benchGtDropzone && this.benchGtFileInput) {
      this.benchGtDropzone.addEventListener('click', () => this.benchGtFileInput.click());
      this.benchGtFileInput.addEventListener('change', (e) => {
        const input = e.target as HTMLInputElement;
        if (input.files?.length) {
          this.handleBenchmarkGtSelect(input.files[0]);
        }
      });
      this.benchGtDropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        this.benchGtDropzone.classList.add('border-emerald-500', 'bg-emerald-500/10');
      });
      this.benchGtDropzone.addEventListener('dragleave', () => {
        this.benchGtDropzone.classList.remove('border-emerald-500', 'bg-emerald-500/10');
      });
      this.benchGtDropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        this.benchGtDropzone.classList.remove('border-emerald-500', 'bg-emerald-500/10');
        if (e.dataTransfer?.files.length) {
          this.handleBenchmarkGtSelect(e.dataTransfer.files[0]);
        }
      });
    }

    // Document-Specific Custom Rules upload & drag/drop
    if (this.benchRulesDropzone && this.benchRulesFileInput) {
      this.benchRulesDropzone.addEventListener('click', () => this.benchRulesFileInput.click());
      this.benchRulesFileInput.addEventListener('change', (e) => {
        const input = e.target as HTMLInputElement;
        if (input.files?.length) {
          this.handleBenchmarkRulesSelect(input.files[0]);
        }
      });
      this.benchRulesDropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        this.benchRulesDropzone.classList.add('border-purple-500', 'bg-purple-500/10');
      });
      this.benchRulesDropzone.addEventListener('dragleave', () => {
        this.benchRulesDropzone.classList.remove('border-purple-500', 'bg-purple-500/10');
      });
      this.benchRulesDropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        this.benchRulesDropzone.classList.remove('border-purple-500', 'bg-purple-500/10');
        if (e.dataTransfer?.files.length) {
          this.handleBenchmarkRulesSelect(e.dataTransfer.files[0]);
        }
      });
    }

    // Start benchmark button
    if (this.startCustomBenchmarkBtn) {
      this.startCustomBenchmarkBtn.addEventListener('click', () => this.handleCustomBenchmarkRun());
    }

    // Skip current engine button
    if (this.benchSkipEngineBtn) {
      this.benchSkipEngineBtn.addEventListener('click', () => this.handleSkipEngine());
    }

    // Abort benchmark button
    if (this.benchAbortBtn) {
      this.benchAbortBtn.addEventListener('click', () => this.handleAbortBenchmark());
    }

    // History select dropdown & delete button
    if (this.benchHistorySelect) {
      this.benchHistorySelect.addEventListener('change', () => {
        const val = this.benchHistorySelect.value;
        if (val) {
          this.loadHistoricalRun(val);
          if (this.benchDeleteHistoryBtn) this.benchDeleteHistoryBtn.classList.remove('hidden');
        } else {
          if (this.benchDeleteHistoryBtn) this.benchDeleteHistoryBtn.classList.add('hidden');
        }
      });
    }

    if (this.benchDeleteHistoryBtn) {
      this.benchDeleteHistoryBtn.addEventListener('click', async () => {
        const val = this.benchHistorySelect?.value;
        if (!val) return;
        try {
          await fetch(`/api/benchmark/history/${val}`, { method: 'DELETE' });
          if (this.benchDeleteHistoryBtn) this.benchDeleteHistoryBtn.classList.add('hidden');
          if (this.benchResultsSection) this.benchResultsSection.classList.add('hidden');
          this.loadBenchmarkHistory();
        } catch (e) {
          console.error('Failed deleting benchmark history run:', e);
        }
      });
    }

    // Inspector Tab Buttons
    if (this.benchTabBtnDiff) this.benchTabBtnDiff.addEventListener('click', () => this.switchInspectorTab('diff'));
    if (this.benchTabBtnRaw) this.benchTabBtnRaw.addEventListener('click', () => this.switchInspectorTab('raw'));
    if (this.benchTabBtnStd) this.benchTabBtnStd.addEventListener('click', () => this.switchInspectorTab('std'));
    if (this.benchTabBtnJudge) this.benchTabBtnJudge.addEventListener('click', () => this.switchInspectorTab('judge'));

    // Engine diff switcher
    if (this.benchDiffEngineSelect) {
      this.benchDiffEngineSelect.addEventListener('change', () => {
        this.renderDiffForEngine(this.benchDiffEngineSelect.value);
      });
    }

    // Re-evaluate button
    if (this.benchReevaluateBtn) {
      this.benchReevaluateBtn.addEventListener('click', () => {
        this.reEvaluateCurrentBenchmark();
      });
    }

    // Benchmark pages input blur & input validation
    if (this.benchPagesInput) {
      this.benchPagesInput.addEventListener('blur', () => {
        const val = this.benchPagesInput.value.trim();
        if (!val) {
          this.clearInputError(this.benchPagesInput, this.benchPagesInputError);
          return;
        }
        if (this.activeBenchSourcePageCount > 0) {
          const validation = this.validatePages(val, this.activeBenchSourcePageCount, this.activeBenchPhysicalStartPage);
          if (!validation.isValid) {
            this.showInputError(this.benchPagesInput, this.benchPagesInputError, this.benchPagesInputErrorText, validation.error || 'Ungültige Seitenauswahl.');
          } else {
            this.clearInputError(this.benchPagesInput, this.benchPagesInputError);
          }
        }
      });
      this.benchPagesInput.addEventListener('input', () => {
        const val = this.benchPagesInput.value.trim();
        if (!val || this.activeBenchSourcePageCount === 0) {
          this.clearInputError(this.benchPagesInput, this.benchPagesInputError);
          return;
        }
        const validation = this.validatePages(val, this.activeBenchSourcePageCount, this.activeBenchPhysicalStartPage);
        if (validation.isValid) {
          this.clearInputError(this.benchPagesInput, this.benchPagesInputError);
        }
      });
    }

    // Restore saved main view tab state from localStorage
    const savedTab = localStorage.getItem('activeMainViewTab');
    if (savedTab === 'workspace' || savedTab === 'benchmark' || savedTab === 'feedback' || savedTab === 'settings') {
      this.switchMainView(savedTab);
    }

    // Load initial benchmark history & check for active task on page load
    this.loadBenchmarkHistory();
    this.checkActiveBenchmarkTaskOnLoad();
  }

  private switchMainView(view: MainView) {
    if (!this.mainWorkspaceView || !this.mainBenchmarkView || !this.mainFeedbackView) return;

    localStorage.setItem('activeMainViewTab', view);
    if (this.mainModeSelect && this.mainModeSelect.value !== view) {
      this.mainModeSelect.value = view;
    }

    this.mainWorkspaceView.classList.toggle('hidden', view !== 'workspace');
    this.mainBenchmarkView.classList.toggle('hidden', view !== 'benchmark');
    this.mainFeedbackView.classList.toggle('hidden', view !== 'feedback');
    if (this.mainSettingsView) this.mainSettingsView.classList.toggle('hidden', view !== 'settings');

    // Stepper and pane toggles only make sense in the Übertragung mode
    if (this.headerStepper) this.headerStepper.classList.toggle('md:flex', view === 'workspace');
    if (this.headerPaneToggles) this.headerPaneToggles.classList.toggle('hidden', view !== 'workspace');

    if (view === 'feedback') {
      if (!this.feedbackController) {
        this.feedbackController = new FeedbackController({
          showError: (message, title) => this.showErrorModal(message, title),
        });
      }
      this.feedbackController.activate();
    }

    if (view === 'settings') {
      if (!this.settingsController) this.settingsController = new SettingsController();
      this.settingsController.activate();
    }
  }

  private async handleBenchmarkSourceSelect(file: File) {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      this.showErrorModal('Bitte wählen Sie eine gültige PDF-Datei als Quelldokument aus.', 'Ungültiges Dateiformat');
      return;
    }
    this.activeBenchSourceFile = file;
    if (this.benchSourceFilename) this.benchSourceFilename.textContent = file.name;
    if (this.benchSourceBadge) this.benchSourceBadge.classList.remove('hidden');

    if (this.benchPagesInput) {
      this.benchPagesInput.disabled = true;
      this.benchPagesInput.classList.add('cursor-not-allowed', 'opacity-60');
      this.benchPagesInput.placeholder = 'Ermittle Seitenzahl...';
    }

    // Fetch page count and physical page offset
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await fetch('/api/pdf/page-count', { method: 'POST', body: formData });
      if (res.ok) {
        const data = await res.json();
        this.activeBenchSourcePageCount = data.page_count || 0;
        this.activeBenchPhysicalStartPage = data.physical_start_page || 1;
        if (this.benchPagesInput) {
          if (this.activeBenchSourcePageCount > 0) {
            this.benchPagesInput.disabled = false;
            this.benchPagesInput.classList.remove('cursor-not-allowed', 'opacity-60');
            this.benchPagesInput.placeholder = `z. B. 1-5, 8 (Dokument hat ${this.activeBenchSourcePageCount} ${this.activeBenchSourcePageCount === 1 ? 'Seite' : 'Seiten'})`;
          } else {
            this.benchPagesInput.disabled = true;
            this.benchPagesInput.classList.add('cursor-not-allowed', 'opacity-60');
            this.benchPagesInput.placeholder = 'Konnte Seitenzahl nicht ermitteln';
          }
        }
      }
    } catch (e) {
      console.warn('Could not determine benchmark PDF page count:', e);
      if (this.benchPagesInput) {
        this.benchPagesInput.disabled = true;
        this.benchPagesInput.classList.add('cursor-not-allowed', 'opacity-60');
        this.benchPagesInput.placeholder = 'Fehler beim Laden der PDF';
      }
    }
  }

  private handleBenchmarkGtSelect(file: File) {
    const fn = file.name.toLowerCase();
    if (!fn.endsWith('.md') && !fn.endsWith('.txt') && !fn.endsWith('.docx')) {
      this.showErrorModal('Bitte wählen Sie eine Markdown (.md), Text- (.txt) oder Word-Datei (.docx) als Ground Truth Referenz aus.', 'Ungültiges Dateiformat');
      return;
    }
    this.activeBenchGtFile = file;
    if (this.benchGtFilename) this.benchGtFilename.textContent = file.name;
    if (this.benchGtBadge) this.benchGtBadge.classList.remove('hidden');
  }

  private handleBenchmarkRulesSelect(file: File) {
    const fn = file.name.toLowerCase();
    if (!fn.endsWith('.txt') && !fn.endsWith('.md') && !fn.endsWith('.docx') && !fn.endsWith('.pdf')) {
      this.showErrorModal('Bitte wählen Sie eine Word- (.docx), Markdown- (.md), Text- (.txt) oder PDF-Datei für die spezifischen Regeln aus.', 'Ungültiges Dateiformat');
      return;
    }
    this.activeBenchRulesFile = file;
    if (this.benchRulesFilename) this.benchRulesFilename.textContent = file.name;
    if (this.benchRulesBadge) this.benchRulesBadge.classList.remove('hidden');
  }

  private async handleCustomBenchmarkRun() {
    if (!this.activeBenchSourceFile) {
      this.showErrorModal('Bitte laden Sie zuerst ein Quell-PDF hoch.', 'Quelldokument fehlt');
      return;
    }
    if (!this.activeBenchGtFile) {
      this.showErrorModal('Bitte laden Sie eine Ground Truth Referenzdatei (.md oder .docx) hoch.', 'Ground Truth fehlt');
      return;
    }

    // Validate page range against source PDF page count
    const pagesVal = this.benchPagesInput?.value.trim();
    if (pagesVal && this.activeBenchSourcePageCount > 0) {
      const validation = this.validatePages(pagesVal, this.activeBenchSourcePageCount, this.activeBenchPhysicalStartPage);
      if (!validation.isValid) {
        this.showInputError(this.benchPagesInput, this.benchPagesInputError, this.benchPagesInputErrorText, validation.error || 'Ungültige Seitenauswahl.');
        if (this.benchPagesInput) this.benchPagesInput.focus();
        return;
      } else {
        this.clearInputError(this.benchPagesInput, this.benchPagesInputError);
      }
    }

    // Collect checked engines
    const selectedEngines: string[] = [];
    if (this.benchEngInfinity?.checked) selectedEngines.push('infinity');
    if (this.benchEngLightonocr?.checked) selectedEngines.push('lightonocr');
    if (this.benchEngDocling?.checked) selectedEngines.push('docling');

    if (selectedEngines.length === 0) {
      this.showErrorModal('Bitte wählen Sie mindestens eine Extraktions-Engine für den Benchmark aus.', 'Keine Engine gewählt');
      return;
    }

    const ruleset = this.benchRulesetSelect ? this.benchRulesetSelect.value : 'uebertragungsregeln_09_2025';

    // Show live status UI immediately
    if (this.benchLiveStatus) this.benchLiveStatus.classList.remove('hidden');
    if (this.benchResultsSection) this.benchResultsSection.classList.add('hidden');
    if (this.startCustomBenchmarkBtn) this.startCustomBenchmarkBtn.disabled = true;
    if (this.benchSkipEngineBtn) this.benchSkipEngineBtn.classList.remove('hidden');
    if (this.benchAbortBtn) this.benchAbortBtn.classList.remove('hidden');
    if (this.benchLivePhase) this.benchLivePhase.textContent = 'Initialisiere Benchmark & lade Dokumente...';
    if (this.benchLiveProgressPct) this.benchLiveProgressPct.textContent = '1.0%';
    if (this.benchLiveProgressBar) this.benchLiveProgressBar.style.width = '1.0%';
    if (this.benchLiveLogs) {
      const tStr = new Date().toLocaleTimeString();
      this.benchLiveLogs.innerHTML = `<div><span class="text-slate-500 font-mono">[${tStr}]</span> <span class="text-indigo-300 font-bold">🚀 Lade Quell-PDF '${this.activeBenchSourceFile.name}' & Referenz '${this.activeBenchGtFile.name}' hoch...</span></div><div><span class="text-slate-500 font-mono">[${tStr}]</span> <span class="text-slate-300">Ground Truth Parsing & Dokumentenverarbeitung startet...</span></div>`;
      this.benchLiveLogs.scrollTop = this.benchLiveLogs.scrollHeight;
    }

    try {
      const formData = new FormData();
      formData.append('source_file', this.activeBenchSourceFile);
      formData.append('ground_truth_file', this.activeBenchGtFile);
      if (this.activeBenchRulesFile) {
        formData.append('custom_rules_file', this.activeBenchRulesFile);
      }
      const customRulesText = this.benchCustomRulesTextarea?.value.trim();
      if (customRulesText) {
        formData.append('custom_rules_text', customRulesText);
      }
      const pagesVal = this.benchPagesInput?.value.trim();
      if (pagesVal) {
        formData.append('pages', pagesVal);
      }
      formData.append('ruleset', ruleset);
      formData.append('engines', selectedEngines.join(','));

      const response = await fetch('/api/benchmark/custom-evaluate', {
        method: 'POST',
        body: formData
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || 'Benchmark konnte nicht gestartet werden');
      }

      const data = await response.json();
      this.activeBenchmarkTaskId = data.task_id;
      this.startBenchmarkTaskPolling(data.task_id);

    } catch (e: any) {
      this.showErrorModal(e.message || 'Die Evaluierung konnte nicht gestartet werden.', 'Benchmark Fehler');
      if (this.benchLiveStatus) this.benchLiveStatus.classList.add('hidden');
      if (this.startCustomBenchmarkBtn) this.startCustomBenchmarkBtn.disabled = false;
    }
  }

  private async checkActiveBenchmarkTaskOnLoad() {
    try {
      const res = await fetch('/api/benchmark/active');
      if (res.ok) {
        const data = await res.json();
        if (data.has_active && data.task) {
          this.activeBenchmarkTaskId = data.task.task_id;
          if (this.benchHistorySelect && this.benchHistorySelect.querySelector(`option[value="${data.task.task_id}"]`)) {
            this.benchHistorySelect.value = data.task.task_id;
          }
          if (this.benchDeleteHistoryBtn) this.benchDeleteHistoryBtn.classList.remove('hidden');
          if (this.benchLiveStatus) this.benchLiveStatus.classList.remove('hidden');
          if (this.startCustomBenchmarkBtn) this.startCustomBenchmarkBtn.disabled = true;
          this.startBenchmarkTaskPolling(data.task.task_id);
        }
      }
    } catch (e) {
      console.warn('Could not check active benchmark task:', e);
    }
  }

  private startBenchmarkTaskPolling(taskId: string) {
    this.activeBenchmarkTaskId = taskId;
    if (this.benchLiveStatus) this.benchLiveStatus.classList.remove('hidden');
    if (this.startCustomBenchmarkBtn) this.startCustomBenchmarkBtn.disabled = true;

    if (this.benchmarkPollInterval) {
      clearInterval(this.benchmarkPollInterval);
    }

    const poll = async () => {
      try {
        const res = await fetch(`/api/benchmark/tasks/${taskId}/status`);
        if (!res.ok) {
          if (this.benchmarkPollInterval) clearInterval(this.benchmarkPollInterval);
          this.benchmarkPollInterval = null;
          this.activeBenchmarkTaskId = null;
          if (this.benchLiveStatus) this.benchLiveStatus.classList.add('hidden');
          if (this.startCustomBenchmarkBtn) this.startCustomBenchmarkBtn.disabled = false;
          return;
        }

        const task = await res.json();

        // 1. Update UI Elements
        if (this.benchLivePhase) {
          this.benchLivePhase.textContent = task.current_phase || 'Verarbeite Benchmark...';
        }
        if (this.benchLiveStepBadge) {
          this.benchLiveStepBadge.textContent = `Engine ${Math.min((task.current_engine_idx || 0) + 1, task.total_engines || 1)} / ${task.total_engines || 1}`;
        }
        if (this.benchLiveProgressPct) {
          this.benchLiveProgressPct.textContent = `${task.progress_percent || 0.0}%`;
        }
        if (this.benchLiveProgressBar) {
          this.benchLiveProgressBar.style.width = `${task.progress_percent || 0.0}%`;
        }

        // 2. Render Live Logs
        if (this.benchLiveLogs && task.logs) {
          this.benchLiveLogs.innerHTML = task.logs.map((l: any) => {
            const levelCol = l.level === 'error' ? 'text-rose-400 font-bold' : l.level === 'warning' ? 'text-amber-400' : 'text-slate-300';
            return `<div><span class="text-slate-500 font-mono">[${l.time}]</span> <span class="${levelCol}">${l.message}</span></div>`;
          }).join('');
          this.benchLiveLogs.scrollTop = this.benchLiveLogs.scrollHeight;
        }

        // 3. Terminal state check
        if (task.status === 'completed' || task.status === 'aborted' || task.status === 'failed') {
          if (this.benchmarkPollInterval) clearInterval(this.benchmarkPollInterval);
          this.benchmarkPollInterval = null;
          this.activeBenchmarkTaskId = null;

          if (this.startCustomBenchmarkBtn) this.startCustomBenchmarkBtn.disabled = false;
          if (this.benchSkipEngineBtn) this.benchSkipEngineBtn.classList.add('hidden');
          if (this.benchAbortBtn) this.benchAbortBtn.classList.add('hidden');

          // Keep live status and activity log visible so the user can inspect what occurred
          if (this.benchLiveStatus) {
            this.benchLiveStatus.classList.remove('hidden');
            if (this.benchLivePhase) {
              this.benchLivePhase.textContent = task.status === 'completed' 
                ? '✅ Benchmark erfolgreich abgeschlossen'
                : task.status === 'aborted' ? '🛑 Benchmark abgebrochen' : '⚠️ Benchmark mit Fehlern beendet';
            }
          }

          if (task.results && task.results.rankings && task.results.rankings.length > 0) {
            this.lastCompletedBenchmarkTaskId = taskId;
            task.results.task_id = taskId;
            this.benchEvaluationResults = task.results;
            this.renderBenchmarkResults(this.benchEvaluationResults);
          } else if (task.status === 'aborted') {
            this.showErrorModal('Der Benchmark wurde auf Benutzerwunsch abgebrochen.', 'Benchmark Abgebrochen');
          } else if (task.status === 'failed') {
            this.showErrorModal(task.error_message || 'Ein schwerwiegender Fehler ist aufgetreten.', 'Benchmark Fehler');
          }

          this.loadBenchmarkHistory();
        }
      } catch (e) {
        console.error('Polling error:', e);
      }
    };

    poll();
    this.benchmarkPollInterval = setInterval(poll, 1500);
  }

  private async handleSkipEngine() {
    if (!this.activeBenchmarkTaskId) return;
    try {
      await fetch(`/api/benchmark/tasks/${this.activeBenchmarkTaskId}/skip`, { method: 'POST' });
    } catch (e) {
      console.error('Failed to skip engine:', e);
    }
  }

  private async handleAbortBenchmark() {
    const taskId = this.activeBenchmarkTaskId;
    if (this.benchmarkPollInterval) {
      clearInterval(this.benchmarkPollInterval);
      this.benchmarkPollInterval = null;
    }
    this.activeBenchmarkTaskId = null;
    if (this.benchLiveStatus) this.benchLiveStatus.classList.add('hidden');
    if (this.startCustomBenchmarkBtn) this.startCustomBenchmarkBtn.disabled = false;

    if (taskId) {
      try {
        await fetch(`/api/benchmark/tasks/${taskId}/abort`, { method: 'POST' });
      } catch (e) {
        console.error('Failed to abort benchmark:', e);
      }
    }
  }

  private async loadBenchmarkHistory() {
    if (!this.benchHistorySelect) return;
    try {
      const res = await fetch('/api/benchmark/history');
      if (!res.ok) return;

      const data = await res.json();
      if (data.history) {
        this.benchHistorySelect.innerHTML = '<option value="">-- Benchmark-Verlauf wählen --</option>' +
          data.history.map((h: any) => {
            const badge = h.type === 'official' ? '🏆 Leaderboard' : '✍️ Custom';
            return `<option value="${h.run_id}">${badge}: ${h.title} (${h.date}) - Top Score: ${h.top_score}</option>`;
          }).join('');
      }
    } catch (e) {
      console.warn('Could not load benchmark history:', e);
    }
  }

  private async loadHistoricalRun(runId: string) {
    try {
      const res = await fetch(`/api/benchmark/history/${runId}`);
      if (!res.ok) {
        this.showErrorModal('Der historische Benchmark wurde nicht gefunden.', 'Fehler beim Laden');
        return;
      }

      const data = await res.json();

      // Check if this run is currently active / running
      if (data.status === 'running' || data.status === 'queued') {
        if (this.benchResultsSection) this.benchResultsSection.classList.add('hidden');
        if (this.benchLiveStatus) this.benchLiveStatus.classList.remove('hidden');
        if (this.startCustomBenchmarkBtn) this.startCustomBenchmarkBtn.disabled = true;
        this.activeBenchmarkTaskId = runId;
        this.startBenchmarkTaskPolling(runId);
        return;
      }

      const evalData = data.evaluation || data.results;

      if (data.type === 'custom' && evalData && evalData.rankings && evalData.rankings.length > 0) {
        this.activeBenchmarkTaskId = runId;
        if (this.startCustomBenchmarkBtn) this.startCustomBenchmarkBtn.disabled = false;
        if (this.benchSkipEngineBtn) this.benchSkipEngineBtn.classList.add('hidden');
        if (this.benchAbortBtn) this.benchAbortBtn.classList.add('hidden');
        if (this.benchReevaluateBtn) this.benchReevaluateBtn.classList.remove('hidden');

        // Render historical activity logs if available
        if (data.logs && data.logs.length > 0 && this.benchLiveLogs && this.benchLiveStatus) {
          this.benchLiveLogs.innerHTML = data.logs.map((l: any) => {
            const levelCol = l.level === 'error' ? 'text-rose-400 font-bold' : l.level === 'warning' ? 'text-amber-400' : 'text-slate-300';
            return `<div><span class="text-slate-500 font-mono">[${l.time}]</span> <span class="${levelCol}">${l.message}</span></div>`;
          }).join('');
          if (this.benchLivePhase) this.benchLivePhase.textContent = '✅ Benchmark-Verlauf (Abgeschlossen)';
          if (this.benchLiveStepBadge) this.benchLiveStepBadge.textContent = `${data.engines?.length || 1} Engine(s)`;
          if (this.benchLiveProgressPct) this.benchLiveProgressPct.textContent = '100.0%';
          if (this.benchLiveProgressBar) this.benchLiveProgressBar.style.width = '100%';
          this.benchLiveStatus.classList.remove('hidden');
        } else if (this.benchLiveStatus) {
          this.benchLiveStatus.classList.add('hidden');
        }

        this.benchEvaluationResults = evalData;
        this.renderBenchmarkResults(this.benchEvaluationResults);
      } else if (data.type === 'official' && data.run_data) {
        if (this.benchReevaluateBtn) this.benchReevaluateBtn.classList.add('hidden');
        if (this.benchLiveStatus) this.benchLiveStatus.classList.add('hidden');
        if (this.startCustomBenchmarkBtn) this.startCustomBenchmarkBtn.disabled = false;
        const rawList = data.run_data.summary_digital || data.run_data.summary?.digital || (Array.isArray(data.run_data.summary) ? data.run_data.summary : []);
        const rankings = rawList.map((d: any) => ({
          engine: d.engine,
          version: d.version || 'v2.140',
          license: 'Apache 2.0',
          composite_score: d.composite_uebertragung_2025 ?? d.uebertragungsregeln_09_2025 ?? d.composite_raw ?? d.raw_score ?? 0.0,
          headings_score: d.ueb_headings ?? d.headings_f1 ?? d.raw_headings ?? 80.0,
          formulas_score: d.ueb_formulas ?? d.formulas_stem ?? d.raw_formulas ?? 90.0,
          tables_score: d.ueb_tables ?? d.tables_struct ?? d.raw_tables ?? 90.0,
          continuity_score: d.ueb_continuity ?? d.reading_flow ?? d.raw_continuity ?? 85.0,
          a11y_score: d.ueb_a11y ?? d.a11y ?? d.raw_a11y ?? 90.0,
          judge_score: d.ueb_judge ?? d.llm_judge ?? d.raw_judge ?? 85.0,
          judge_feedback: `Offizieller Leaderboard Benchmark Run (${data.run_data.timestamp}) über ${d.docs_evaluated ?? data.run_data.datasets_count ?? data.run_data.datasets?.length ?? 4} Dokumente.`,
          speed_sec_per_page: d.sec_per_page ?? d.avg_speed_sec_per_page ?? 1.5,
          total_duration_seconds: 15.0,
          extracted_markdown: `# Leaderboard Report\n\nEngine: ${d.engine}\nScore: ${d.composite_uebertragung_2025 ?? d.uebertragungsregeln_09_2025 ?? 0}`,
          diff_html: '<p class="text-slate-400 italic">Offizieller Leaderboard-Run Record. Detail-Diffs sind in benchmarks/runs/ gespeichert.</p>'
        }));

        this.benchEvaluationResults = {
          timestamp: data.run_data.timestamp,
          ruleset: 'uebertragungsregeln_09_2025',
          page_count: 10,
          rankings: rankings
        };
        this.renderBenchmarkResults(this.benchEvaluationResults);
      } else {
        if (this.benchResultsSection) this.benchResultsSection.classList.add('hidden');
        if (this.benchLiveStatus) this.benchLiveStatus.classList.add('hidden');
        if (this.startCustomBenchmarkBtn) this.startCustomBenchmarkBtn.disabled = false;
        this.showErrorModal(
          data.error_message || 'Dieser historische Benchmark-Run enthält keine vollständigen Auswertungsdaten.',
          'Keine Details verfügbar'
        );
      }
    } catch {
      this.showErrorModal('Der historische Benchmark konnte nicht geladen werden.', 'Fehler beim Laden');
    }
  }

  private lastCompletedBenchmarkTaskId: string | null = null;

  private async reEvaluateCurrentBenchmark() {
    const taskId = this.activeBenchmarkTaskId || this.lastCompletedBenchmarkTaskId || this.benchEvaluationResults?.task_id || this.benchHistorySelect?.value;
    if (!taskId) {
      this.showErrorModal('Keine aktive oder ausgewählte Evaluierung gefunden.', 'Neu-Evaluierung');
      return;
    }

    if (this.benchReevaluateBtn) {
      this.benchReevaluateBtn.disabled = true;
      if (this.benchReevaluateIcon) this.benchReevaluateIcon.classList.add('animate-spin');
      if (this.benchReevaluateText) this.benchReevaluateText.textContent = 'Evaluiere neu...';
    }

    try {
      const res = await fetch(`/api/benchmark/tasks/${taskId}/re-evaluate`, {
        method: 'POST'
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({ detail: 'Unbekannter Serverfehler' }));
        throw new Error(errData.detail || 'Neu-Evaluierung fehlgeschlagen');
      }

      const data = await res.json();
      const results = data.results || data.evaluation;
      if (results) {
        this.benchEvaluationResults = results;
        this.renderBenchmarkResults(this.benchEvaluationResults);
        this.loadBenchmarkHistory(); // refresh dropdown with updated scores

        // If logs returned, update live activity log container as well
        if (data.logs && data.logs.length > 0 && this.benchLiveLogs) {
          this.benchLiveLogs.innerHTML = data.logs.map((l: any) => {
            const levelCol = l.level === 'error' ? 'text-rose-400 font-bold' : l.level === 'warning' ? 'text-amber-400' : 'text-slate-300';
            return `<div><span class="text-slate-500 font-mono">[${l.time || ''}]</span> <span class="${levelCol}">${l.message}</span></div>`;
          }).join('');
        }

        this.showToast('✅ Alle Metriken & LLM-Judge erfolgreich neu evaluiert!');
      }
    } catch (e: any) {
      console.error('Re-evaluation error:', e);
      this.showErrorModal(e.message || 'Fehler bei der Neu-Evaluierung.', 'Neu-Evaluierung fehlgeschlagen');
    } finally {
      if (this.benchReevaluateBtn) {
        this.benchReevaluateBtn.disabled = false;
        if (this.benchReevaluateIcon) this.benchReevaluateIcon.classList.remove('animate-spin');
        if (this.benchReevaluateText) this.benchReevaluateText.textContent = 'Neu evaluieren';
      }
    }
  }

  private switchInspectorTab(tab: 'diff' | 'raw' | 'std' | 'judge') {
    const btns = [
      { id: 'diff', el: this.benchTabBtnDiff, pane: this.benchTabPaneDiff },
      { id: 'raw', el: this.benchTabBtnRaw, pane: this.benchTabPaneRaw },
      { id: 'std', el: this.benchTabBtnStd, pane: this.benchTabPaneStd },
      { id: 'judge', el: this.benchTabBtnJudge, pane: this.benchTabPaneJudge }
    ];

    btns.forEach(b => {
      if (b.id === tab) {
        b.el?.classList.add('bg-indigo-600/30', 'text-indigo-200', 'border-indigo-500/40');
        b.el?.classList.remove('bg-slate-950', 'text-slate-400');
        b.pane?.classList.remove('hidden');
      } else {
        b.el?.classList.remove('bg-indigo-600/30', 'text-indigo-200', 'border-indigo-500/40');
        b.el?.classList.add('bg-slate-950', 'text-slate-400');
        b.pane?.classList.add('hidden');
      }
    });

    if (this.benchDiffEngineSelect && this.benchDiffEngineSelect.value) {
      this.renderDiffForEngine(this.benchDiffEngineSelect.value);
    }
  }

  private renderBenchmarkResults(data: any) {
    if (!data || !data.rankings || !this.benchResultsSection) return;

    this.benchResultsSection.classList.remove('hidden');

    const engineLabels: Record<string, string> = {
      infinity: '⚡ Infinity-Parser2',
      lightonocr: '🔥 LightOnOCR-3',
      docling: '🚀 Docling',
    };

    // 1. Top Ranking Cards
    if (this.benchRankingCards) {
      this.benchRankingCards.innerHTML = data.rankings.map((r: any, idx: number) => {
        const isFirst = idx === 0;
        const borderCol = isFirst ? 'border-amber-500/50 bg-amber-950/20' : 'border-slate-800 bg-slate-900/70';
        const rankBadge = isFirst ? 'bg-amber-500/20 text-amber-300 border-amber-500/40' : 'bg-slate-800 text-slate-300 border-slate-700';
        const label = engineLabels[r.engine] || r.engine;

        return `
          <div data-engine="${r.engine}" class="bench-rank-card glass-card p-4 rounded-xl border ${borderCol} shadow-lg flex flex-col justify-between space-y-3 cursor-pointer hover:border-indigo-500/60 transition-all">
            <div class="flex items-center justify-between">
              <span class="px-2.5 py-0.5 rounded-full text-xs font-bold border ${rankBadge}">
                Rang #${idx + 1}
              </span>
              <span class="text-[10px] text-slate-400 font-mono">${r.speed_sec_per_page} s/Seite</span>
            </div>
            <div>
              <h4 class="text-sm font-bold text-white tracking-tight">${label}</h4>
              <p class="text-[10px] text-slate-400 mt-0.5">${r.license}</p>
            </div>
            <div class="pt-2 border-t border-slate-800/80 flex items-baseline justify-between">
              <span class="text-[11px] text-slate-400">Gesamt-Score:</span>
              <span class="text-xl font-bold font-mono text-indigo-400">${r.composite_score}<span class="text-xs text-slate-500">/100</span></span>
            </div>
          </div>
        `;
      }).join('');

      this.benchRankingCards.querySelectorAll('.bench-rank-card').forEach(card => {
        card.addEventListener('click', (e) => {
          const eng = (e.currentTarget as HTMLElement).getAttribute('data-engine');
          if (eng && this.benchDiffEngineSelect) {
            this.benchDiffEngineSelect.value = eng;
            this.renderDiffForEngine(eng);
            this.benchDiffEngineSelect.scrollIntoView({ behavior: 'smooth' });
          }
        });
      });
    }

    // 2. Matrix Table Rows
    if (this.benchMatrixTbody) {
      this.benchMatrixTbody.innerHTML = data.rankings.map((r: any, idx: number) => {
        const label = engineLabels[r.engine] || r.engine;
        const rowBg = idx === 0 ? 'bg-indigo-950/20' : 'hover:bg-slate-900/40';

        return `
          <tr data-engine="${r.engine}" class="bench-matrix-row ${rowBg} transition-colors cursor-pointer hover:bg-indigo-950/40">
            <td class="py-3 px-3 font-bold text-amber-400">#${idx + 1}</td>
            <td class="py-3 px-3 font-bold text-white">${label}</td>
            <td class="py-3 px-3 text-slate-400 text-[11px]">${r.license}</td>
            <td class="py-3 px-3 font-mono font-bold text-indigo-300 text-sm">${r.composite_score}/100</td>
            <td class="py-3 px-3 font-mono text-slate-200">${r.headings_score}%</td>
            <td class="py-3 px-3 font-mono text-slate-200">${r.formulas_score}%</td>
            <td class="py-3 px-3 font-mono text-slate-200">${r.tables_score}%</td>
            <td class="py-3 px-3 font-mono text-slate-200">${r.continuity_score}%</td>
            <td class="py-3 px-3 font-mono text-slate-200">${r.a11y_score}%</td>
            <td class="py-3 px-3 font-mono text-slate-200">${r.judge_score}%</td>
            <td class="py-3 px-3 font-mono text-slate-400">${r.speed_sec_per_page} s</td>
          </tr>
        `;
      }).join('');

      this.benchMatrixTbody.querySelectorAll('.bench-matrix-row').forEach(row => {
        row.addEventListener('click', (e) => {
          const eng = (e.currentTarget as HTMLElement).getAttribute('data-engine');
          if (eng && this.benchDiffEngineSelect) {
            this.benchDiffEngineSelect.value = eng;
            this.renderDiffForEngine(eng);
            this.benchDiffEngineSelect.scrollIntoView({ behavior: 'smooth' });
          }
        });
      });
    }

    // 3. Populate Engine Diff Selector
    if (this.benchDiffEngineSelect) {
      this.benchDiffEngineSelect.innerHTML = data.rankings.map((r: any) => {
        const label = engineLabels[r.engine] || r.engine;
        return `<option value="${r.engine}">${label} (Score: ${r.composite_score})</option>`;
      }).join('');

      if (data.rankings.length > 0) {
        this.renderDiffForEngine(data.rankings[0].engine);
      }
    }
  }

  private renderDiffSegmentsToHtml(segments: any): string {
    if (!segments) {
      return '<p class="text-slate-500 italic">Keine Diff-Daten vorhanden.</p>';
    }
    if (typeof segments === 'string') {
      if (segments.trim().startsWith('<')) {
        return segments;
      }
      return `<div class="font-mono text-xs leading-relaxed whitespace-pre-wrap select-text p-2 font-normal">${segments}</div>`;
    }
    if (!Array.isArray(segments) || segments.length === 0) {
      return '<p class="text-slate-500 italic">Keine Diff-Daten vorhanden.</p>';
    }

    let html = '<div class="font-mono text-xs leading-relaxed whitespace-pre-wrap select-text p-3 font-normal">';
    for (const seg of segments) {
      const text = typeof seg.text === 'string' ? seg.text : (typeof seg.value === 'string' ? seg.value : String(seg || ''));
      const escapedText = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

      const cat = seg.category || 'none';
      if (seg.type === 'equal') {
        html += escapedText;
      } else if (seg.type === 'insert') {
        html += `<ins class="diff-insert diff-cat-${cat}">${escapedText}</ins>`;
      } else if (seg.type === 'delete') {
        html += `<del class="diff-delete diff-cat-${cat}">${escapedText}</del>`;
      } else {
        html += escapedText;
      }
    }
    html += '</div>';
    return html;
  }

  private renderDiffForEngine(engineName: string) {
    if (!this.benchEvaluationResults || !this.benchEvaluationResults.rankings) return;

    const engineData = this.benchEvaluationResults.rankings.find((r: any) => r.engine === engineName);
    if (!engineData) return;

    // Tab 1: Diff HTML
    if (this.benchTabPaneDiff) {
      this.benchTabPaneDiff.innerHTML = this.renderDiffSegmentsToHtml(engineData.diff_html);
    }

    // Tab 2: Raw Markdown (pre-LLM)
    if (this.benchTabPaneRaw) {
      this.benchTabPaneRaw.textContent = engineData.raw_markdown || engineData.extracted_markdown || 'Kein Roh-Markdown verfügbar.';
    }

    // Tab 3: Standardized Markdown (post-LLM)
    if (this.benchTabPaneStd) {
      this.benchTabPaneStd.textContent = engineData.extracted_markdown || 'Kein standardisiertes Markdown verfügbar.';
    }

    // Tab 4: Gemma 4 LLM-Judge Analysis
    if (this.benchTabPaneJudge) {
      this.benchTabPaneJudge.innerHTML = `
        <div class="p-4 rounded-xl bg-indigo-950/30 border border-indigo-500/30 space-y-2">
          <div class="flex items-center justify-between">
            <span class="font-bold text-indigo-300 text-sm flex items-center space-x-1.5">
              <span>🤖</span>
              <span>Gemma 4 12B LLM-Judge Gesamturteil</span>
            </span>
            <span class="px-2.5 py-0.5 rounded-full text-xs font-mono font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/40">
              ${engineData.judge_score}%
            </span>
          </div>
          <p class="text-slate-300 leading-relaxed italic text-xs">
            "${engineData.judge_feedback || 'Keine detaillierte LLM-Judge Begründung verfügbar.'}"
          </p>
        </div>

        <div class="grid grid-cols-2 md:grid-cols-3 gap-3">
          <div class="p-3 rounded-lg bg-slate-900 border border-slate-800">
            <span class="text-[10px] text-slate-400 font-semibold block">Überschriften-Hierarchie</span>
            <span class="text-base font-bold font-mono text-emerald-400">${engineData.headings_score}%</span>
          </div>
          <div class="p-3 rounded-lg bg-slate-900 border border-slate-800">
            <span class="text-[10px] text-slate-400 font-semibold block">Formeln & STEM</span>
            <span class="text-base font-bold font-mono text-purple-400">${engineData.formulas_score}%</span>
          </div>
          <div class="p-3 rounded-lg bg-slate-900 border border-slate-800">
            <span class="text-[10px] text-slate-400 font-semibold block">Tabellen-Treue</span>
            <span class="text-base font-bold font-mono text-cyan-400">${engineData.tables_score}%</span>
          </div>
          <div class="p-3 rounded-lg bg-slate-900 border border-slate-800">
            <span class="text-[10px] text-slate-400 font-semibold block">Lesefluss & Dehyphenation</span>
            <span class="text-base font-bold font-mono text-indigo-400">${engineData.continuity_score}%</span>
          </div>
          <div class="p-3 rounded-lg bg-slate-900 border border-slate-800">
            <span class="text-[10px] text-slate-400 font-semibold block">Barrierefreiheit (A11y)</span>
            <span class="text-base font-bold font-mono text-amber-400">${engineData.a11y_score}%</span>
          </div>
          <div class="p-3 rounded-lg bg-slate-900 border border-slate-800">
            <span class="text-[10px] text-slate-400 font-semibold block">Geschwindigkeit</span>
            <span class="text-base font-bold font-mono text-slate-200">${engineData.speed_sec_per_page}s/S</span>
          </div>
        </div>
      `;
    }

    // DOCX download button
    if (this.benchDownloadDocxBtn) {
      if (engineData.has_docx && engineData.docx_url) {
        this.benchDownloadDocxBtn.classList.remove('hidden');
        this.benchDownloadDocxBtn.href = engineData.docx_url;
      } else {
        this.benchDownloadDocxBtn.classList.add('hidden');
      }
    }
  }
}

// Instantiate app
document.addEventListener('DOMContentLoaded', () => {
  new AppController();
});
