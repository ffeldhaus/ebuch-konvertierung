import { test, expect } from '@playwright/test';
import path from 'path';

test.describe('E-Buch Standard Konverter E2E Flow', () => {

  test('should guide user through upload, extraction, standardisation, and DOCX download', async ({ page }) => {
    test.setTimeout(900000); // Allow enough time for CPU/GPU pipeline extraction and standardisation
    // 1. Visit the application
    await page.goto('/');
    page.on('console', msg => console.log('BROWSER LOG:', msg.text()));
    page.on('pageerror', err => console.log('BROWSER PAGE ERROR:', err.message));
    await expect(page.locator('#workspace-title')).toContainText('E-Buch Standard Konverter');
    
    // Check initial stepper state (Step 1 is active, others are not)
    await expect(page.locator('#step-1-indicator')).toHaveClass(/text-indigo-400/);
    await expect(page.locator('#step-2-indicator')).toHaveClass(/text-slate-500/);

    // 2. Select the E-Buch ruleset
    await page.selectOption('#ruleset-select', 'uebertragungsregeln_09_2025');

    // 2. Initial state: Additional ruleset should be disabled
    await expect(page.locator('#ruleset-upload-zone')).toHaveClass(/cursor-not-allowed/);
    await expect(page.locator('#ruleset-file-input')).toBeDisabled();

    // 3. Upload the test educational PDF file
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.click('#dropzone');
    const fileChooser = await fileChooserPromise;
    
    // Use the pre-generated mock educational PDF file in the test_data folder
    const testPdfPath = path.resolve(process.cwd(), 'testdata/test_educational.pdf');
    await fileChooser.setFiles(testPdfPath);

    // Check file status is shown and button is active
    await expect(page.locator('#file-status')).toBeVisible();
    await expect(page.locator('#selected-file-name')).toContainText('test_educational.pdf');
    await expect(page.locator('#process-btn')).toBeEnabled();
    await expect(page.locator('#process-btn')).toContainText('Extraktion starten');

    // Verify ruleset upload is now enabled
    await expect(page.locator('#ruleset-upload-zone')).not.toHaveClass(/cursor-not-allowed/);
    await expect(page.locator('#ruleset-file-input')).toBeEnabled();

    // Upload custom file-specific ruleset
    const rulesetChooserPromise = page.waitForEvent('filechooser');
    await page.click('#ruleset-upload-zone');
    const rulesetChooser = await rulesetChooserPromise;
    const rulesetPath = path.resolve(process.cwd(), 'testdata/test_educational_rules.txt');
    await rulesetChooser.setFiles(rulesetPath);
    await expect(page.locator('#ruleset-status-text')).toContainText('test_educational_rules.txt');

    // Select page 45 (single page to run quickly)
    await page.fill('#pages-input', '45');
    await expect(page.locator('#describe-images-toggle')).toBeVisible();
    await expect(page.locator('#describe-images-toggle')).toBeChecked();

    // 4. Click the process button to start the pipeline
    await page.click('#process-btn');

    // Stepper should change to active extraction
    await expect(page.locator('#step-2-indicator')).toHaveClass(/text-indigo-400/);

    // Wait for the extraction and standardisation to complete
    // We expect the download button to be enabled when conversion is ready
    await expect(page.locator('#download-docx-btn')).toBeEnabled({ timeout: 720000 });
    
    // Stepper should show ready to export
    await expect(page.locator('#step-4-indicator')).toHaveClass(/text-indigo-400/);

    // Check that both textareas contain processed data
    const rawContent = await page.inputValue('#raw-markdown-textarea');
    expect(rawContent).toContain('#'); // Should have markdown headings
    
    const standardisedContent = await page.inputValue('#standardised-markdown-textarea');
    expect(standardisedContent).toContain('<Bild>'); // Should contain standard E-Buch image tags
    expect(standardisedContent).toContain('Versuchsaufbau'); // Must have caption text or VLM description details
    expect(standardisedContent).toContain('(('); // Should contain page number references

    // 4.5 Test uploading custom style template (.dotx format)
    await page.selectOption('#template-mode-select', 'custom');
    const templateChooserPromise = page.waitForEvent('filechooser');
    await page.click('#template-upload-zone');
    const templateChooser = await templateChooserPromise;
    const testDotxPath = path.resolve(process.cwd(), 'assets/templates/Dokumentenvorlage FIBS 25.05.2025_NEU.dotx');
    await templateChooser.setFiles(testDotxPath);
    
    // Check that template status is updated
    await expect(page.locator('#template-status-text')).toContainText('Dokumentenvorlage FIBS');

    // 5. Test interactive LLM-driven optimization of standardized markdown
    await page.fill('#optimization-prompt-input', 'Füge am Ende des Textes ein neues Kapitel ((46)) mit Überschrift H1 "Neues Testkapitel" und Text "Standardisierter Text." hinzu.');
    await page.click('#btn-optimize');

    // Wait for the optimization response (we expect input prompt to be cleared)
    await expect(page.locator('#optimization-prompt-input')).toHaveValue('', { timeout: 120000 });

    const optimisedContent = await page.inputValue('#standardised-markdown-textarea');
    expect(optimisedContent).toContain('Neues Testkapitel');



    // 5.6 Verify PDF page pills & navigation
    await expect(page.locator('#pdf-page-pills-container')).toBeVisible();
    const pagePills = page.locator('#pdf-page-pills-container .pdf-page-pill');
    if (await pagePills.count() > 0) {
      await pagePills.first().click();
    }

    // 6. Click the "Word-Datei erzeugen" button to build the final document
    await page.click('#download-docx-btn');

    // Verify it transitions to completed stepper state
    await expect(page.locator('#step-4-indicator')).toHaveClass(/text-emerald-400/, { timeout: 30000 });
    
    // Download actions buttons should be visible
    await expect(page.locator('#download-actions')).toBeVisible();
  });

  test('should show error modal for invalid page selections', async ({ page }) => {
    // 1. Visit the application
    await page.goto('/');

    // 2. Upload the test educational PDF file
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.click('#dropzone');
    const fileChooser = await fileChooserPromise;
    const testPdfPath = path.resolve(process.cwd(), 'testdata/test_educational.pdf');
    await fileChooser.setFiles(testPdfPath);

    // Wait for the upload to complete (start button enabled)
    await expect(page.locator('#process-btn')).toBeEnabled();

    // 3. Input an out of bounds page number (e.g. 5)
    await page.fill('#pages-input', '5');
    await page.locator('#pages-input').blur();

    // 4. Verify inline error is visible and contains expected text
    await expect(page.locator('#pages-input-error')).toBeVisible();
    await expect(page.locator('#pages-input-error-text')).toContainText('liegt außerhalb des gültigen Bereichs');
    await expect(page.locator('#pages-input')).toHaveClass(/border-rose-500/);

    // 5. Try clicking extraction button while invalid - processing is blocked
    await page.click('#process-btn');
    await expect(page.locator('#pages-input-error')).toBeVisible();
    await expect(page.locator('#step-2-indicator')).not.toHaveClass(/text-indigo-400/);

    // 6. Input an invalid character string
    await page.fill('#pages-input', '1, 2, abc');
    await page.locator('#pages-input').blur();
    await expect(page.locator('#pages-input-error')).toBeVisible();
    await expect(page.locator('#pages-input-error-text')).toContainText('ungültige Zeichen');

    // 7. Input valid page number - error is cleared and process button enabled
    await page.fill('#pages-input', '45');
    await page.locator('#pages-input').blur();
    await expect(page.locator('#pages-input-error')).toBeHidden();
    await expect(page.locator('#pages-input')).not.toHaveClass(/border-rose-500/);
    await expect(page.locator('#process-btn')).toBeEnabled();
  });

  test('should guide user through extraction using Docling OCR, standardisation, and DOCX download', async ({ page }) => {
    test.setTimeout(720000);
    await page.goto('/');
    page.on('console', msg => console.log('[Docling E2E] BROWSER LOG:', msg.text()));
    
    // 1. Select the ruleset
    await page.selectOption('#ruleset-select', 'uebertragungsregeln_09_2025');

    // 2. Select Docling engine
    await page.selectOption('#engine-select', 'docling');

    // 3. Upload PDF
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.click('#dropzone');
    const fileChooser = await fileChooserPromise;
    const testPdfPath = path.resolve(process.cwd(), 'testdata/test_educational.pdf');
    await fileChooser.setFiles(testPdfPath);

    await expect(page.locator('#process-btn')).toBeEnabled();

    // Select page 45 (single page to run quickly)
    await page.fill('#pages-input', '45');

    // 4. Click process
    await page.click('#process-btn');

    // 5. Wait for download button to be enabled
    await expect(page.locator('#download-docx-btn')).toBeEnabled({ timeout: 720000 });

    // 6. Check that outputs contain standardized data with hierarchical headings
    const rawContent = await page.inputValue('#raw-markdown-textarea');
    expect(rawContent).toBeTruthy();

    const standardisedContent = await page.inputValue('#standardised-markdown-textarea');
    expect(standardisedContent).toContain('(('); // Page marker
    expect(standardisedContent).toMatch(/#\s+/); // H1 main chapter heading
    expect(standardisedContent).toMatch(/##\s+/); // H2 sub-section hierarchical heading
  });

  test('should guide user through extraction of deutsch_textanalyse alternating page numbers starting at 85', async ({ page }) => {
    test.setTimeout(450000);
    await page.goto('/');
    
    // Upload the alternating pages PDF
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.click('#dropzone');
    const fileChooser = await fileChooserPromise;
    const testPdfPath = path.resolve(process.cwd(), 'testdata/deutsch_textanalyse.pdf');
    await fileChooser.setFiles(testPdfPath);

    await expect(page.locator('#process-btn')).toBeEnabled();

    // Select page 85
    await page.fill('#pages-input', '85');

    // Click process
    await page.click('#process-btn');

    // Wait for completion (up to 5 mins)
    await expect(page.locator('#download-docx-btn')).toBeEnabled({ timeout: 300000 });

    const rawContent = await page.inputValue('#raw-markdown-textarea');
    expect(rawContent).toContain('((85))');
  });

  test('should guide user through extraction of mathe_grade3 centered page numbers starting at 1', async ({ page }) => {
    test.setTimeout(450000);
    await page.goto('/');
    
    // Upload the centered page PDF
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.click('#dropzone');
    const fileChooser = await fileChooserPromise;
    const testPdfPath = path.resolve(process.cwd(), 'testdata/mathe_grade3.pdf');
    await fileChooser.setFiles(testPdfPath);

    await expect(page.locator('#process-btn')).toBeEnabled();

    // Select page 1
    await page.fill('#pages-input', '1');

    // Click process
    await page.click('#process-btn');

    // Wait for completion (up to 5 mins)
    await expect(page.locator('#download-docx-btn')).toBeEnabled({ timeout: 300000 });

    const rawContent = await page.inputValue('#raw-markdown-textarea');
    expect(rawContent).toContain('((1))');
  });

  test('should allow selecting Docling extraction engine and extracting document', async ({ page }) => {
    test.setTimeout(300000);
    await page.goto('/');
    
    // Select Docling
    await page.selectOption('#engine-select', 'docling');
    
    // Upload educational PDF
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.click('#dropzone');
    const fileChooser = await fileChooserPromise;
    const testPdfPath = path.resolve(process.cwd(), 'testdata/test_educational.pdf');
    await fileChooser.setFiles(testPdfPath);

    await expect(page.locator('#process-btn')).toBeEnabled();

    // Select page range
    await page.fill('#pages-input', '45-48');

    // Click process
    await page.click('#process-btn');

    // Wait for completion
    await expect(page.locator('#download-docx-btn')).toBeEnabled({ timeout: 300000 });

    const rawContent = await page.inputValue('#raw-markdown-textarea');
    expect(rawContent).toContain('((45))');
  });

  test('should allow aborting active conversion in workspace', async ({ page }) => {
    test.setTimeout(60000);
    await page.goto('/');
    
    // Select Docling
    await page.selectOption('#engine-select', 'docling');
    
    // Upload educational PDF
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.click('#dropzone');
    const fileChooser = await fileChooserPromise;
    const testPdfPath = path.resolve(process.cwd(), 'testdata/test_educational.pdf');
    await fileChooser.setFiles(testPdfPath);

    await expect(page.locator('#process-btn')).toBeEnabled();

    // Click process
    await page.click('#process-btn');

    // Abort button should be visible
    await expect(page.locator('#abort-process-btn')).toBeVisible({ timeout: 5000 });

    // Click abort
    await page.click('#abort-process-btn');

    // Progress container and abort button should be hidden, process button restored
    await expect(page.locator('#abort-process-btn')).toBeHidden({ timeout: 10000 });
    await expect(page.locator('#pipeline-progress-container')).toBeHidden({ timeout: 10000 });
    await expect(page.locator('#process-btn')).toBeEnabled({ timeout: 10000 });
  });

  test('should display raw markdown when reloading page during task processing', async ({ page }) => {
    test.setTimeout(60000);
    
    // 1. Create a task directly with raw_markdown set and status processing
    const uploadRes = await page.request.post('/api/upload', {
      multipart: {
        file: {
          name: 'test_reload.pdf',
          mimeType: 'application/pdf',
          buffer: Buffer.from('%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n>>\nendobj\ntrailer\n<<\n/Root 1 0 R\n>>\n%%EOF')
        }
      }
    });
    expect(uploadRes.ok()).toBeTruthy();
    const taskData = await uploadRes.json();
    const taskId = taskData.task_id;

    // Simulate task progressing to image description phase by calling /api/standardise or updating backend task state
    // In e2e mock mode or via frontend, navigate to taskId url or reattach
    await page.goto(`/?task_id=${taskId}`);
    
    // Check that workspace opened with the active task
    await expect(page.locator('#file-status')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('#selected-file-name')).toContainText('test_reload.pdf');
  });

  test('should support custom benchmark and manual ground truth evaluation view', async ({ page }) => {
    test.setTimeout(300000);
    await page.goto('/');

    // 1. Switch to Benchmark & Evaluation mode via the header dropdown
    await page.selectOption('#main-mode-select', 'benchmark');
    await expect(page.locator('#main-benchmark-view')).toBeVisible();
    await expect(page.locator('#main-workspace-view')).toBeHidden();

    // 2. Upload Source PDF
    const sourceChooserPromise = page.waitForEvent('filechooser');
    await page.click('#bench-source-dropzone');
    const sourceChooser = await sourceChooserPromise;
    const testPdfPath = path.resolve(process.cwd(), 'testdata/test_educational.pdf');
    await sourceChooser.setFiles(testPdfPath);
    await expect(page.locator('#bench-source-badge')).toBeVisible();
    await expect(page.locator('#bench-source-filename')).toContainText('test_educational.pdf');

    // 3. Upload Ground Truth Markdown
    const gtChooserPromise = page.waitForEvent('filechooser');
    await page.click('#bench-gt-dropzone');
    const gtChooser = await gtChooserPromise;
    const gtMdPath = path.resolve(process.cwd(), 'testdata/golden/test_educational.uebertragungsregeln_09_2025.golden.md');
    await gtChooser.setFiles(gtMdPath);
    await expect(page.locator('#bench-gt-badge')).toBeVisible();

    // 4. Select only Docling to run fast
    for (const id of ['#bench-eng-infinity', '#bench-eng-lightonocr']) {
      const box = page.locator(id);
      if ((await box.count()) > 0 && (await box.isChecked())) await box.uncheck();
    }
    await page.check('#bench-eng-docling');

    // 5. Run Benchmark
    await expect(page.locator('#start-custom-benchmark-btn')).toBeEnabled({ timeout: 10000 });
    await page.click('#start-custom-benchmark-btn');

    // 6. Verify Results Dashboard
    await expect(page.locator('#bench-results-section')).toBeVisible({ timeout: 180000 });
    await expect(page.locator('#bench-ranking-cards')).toContainText('Docling');
    await expect(page.locator('#bench-matrix-tbody')).toContainText('Docling');
    await expect(page.locator('#bench-tab-pane-diff')).toBeVisible();

    // 7. Verify Re-evaluate button functionality
    await expect(page.locator('#bench-reevaluate-btn')).toBeVisible();
    await page.click('#bench-reevaluate-btn');
    await expect(page.locator('#bench-reevaluate-btn')).toBeEnabled({ timeout: 60000 });
    await expect(page.locator('#bench-ranking-cards')).toContainText('Docling');

    // Switch back to Übertragung mode
    await page.selectOption('#main-mode-select', 'workspace');
    await expect(page.locator('#main-workspace-view')).toBeVisible();
    await expect(page.locator('#main-benchmark-view')).toBeHidden();
  });

  test('mode dropdown offers Übertragung, Benchmark & Feedback and persists selection', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => localStorage.removeItem('activeMainViewTab'));
    await page.reload();

    const select = page.locator('#main-mode-select');
    await expect(select.locator('option')).toHaveText(['📄 Übertragung', '⚖️ Benchmark & Evaluierung', '💬 Feedback', '⚙️ Einstellungen']);
    await expect(select).toHaveValue('workspace');
    await expect(page.locator('#header-pane-toggles')).toBeVisible();

    await page.selectOption('#main-mode-select', 'feedback');
    await expect(page.locator('#main-feedback-view')).toBeVisible();
    await expect(page.locator('#main-workspace-view')).toBeHidden();
    await expect(page.locator('#main-benchmark-view')).toBeHidden();
    await expect(page.locator('#header-pane-toggles')).toBeHidden();

    // Selection survives a reload
    await page.reload();
    await expect(page.locator('#main-mode-select')).toHaveValue('feedback');
    await expect(page.locator('#main-feedback-view')).toBeVisible();

    await page.selectOption('#main-mode-select', 'workspace');
    await expect(page.locator('#main-workspace-view')).toBeVisible();
  });

  test('settings mode: table resolution threshold is loaded, validated and saved', async ({ page }) => {
    // Mock the settings API so the real assets/settings.json is never touched by E2E runs.
    let stored = 6;
    const schema = [{
      key: 'table_resolve_max_cells', type: 'integer', default: 6, min: 0, max: 200,
      group: 'Übertragungsregeln', label: 'Tabellen auflösen bis … Zellen',
      description: 'Kleine Tabellen werden aufgelöst. 0 = nie auflösen.',
    }];
    const puts: unknown[] = [];
    await page.route('**/api/settings', async (route) => {
      if (route.request().method() === 'PUT') {
        const body = route.request().postDataJSON() as { values: { table_resolve_max_cells: number } };
        puts.push(body);
        stored = body.values.table_resolve_max_cells;
      }
      await route.fulfill({ json: { values: { table_resolve_max_cells: stored }, schema } });
    });

    await page.goto('/');
    await page.selectOption('#main-mode-select', 'settings');
    await expect(page.locator('#main-settings-view')).toBeVisible();
    await expect(page.locator('#main-workspace-view')).toBeHidden();
    await expect(page.locator('#header-pane-toggles')).toBeHidden();

    const input = page.locator('#setting-table_resolve_max_cells');
    await expect(input).toHaveValue('6');
    await expect(page.getByText('Tabellen auflösen bis … Zellen')).toBeVisible();

    // Invalid value is rejected client-side, nothing is sent
    await input.fill('-4');
    await page.click('#settings-save-btn');
    await expect(page.locator('#settings-status')).toContainText('ganze Zahl zwischen 0 und 200');
    expect(puts).toHaveLength(0);

    // Valid value is saved
    await input.fill('8');
    await page.click('#settings-save-btn');
    await expect(page.locator('#settings-status')).toContainText('Gespeichert');
    expect(puts).toEqual([{ values: { table_resolve_max_cells: 8 } }]);

    // Reset fills in the defaults (saving is explicit)
    await page.click('#settings-reset-btn');
    await expect(input).toHaveValue('6');

    // The view is restored after a reload and shows the stored value
    await page.reload();
    await expect(page.locator('#main-settings-view')).toBeVisible();
    await expect(page.locator('#setting-table_resolve_max_cells')).toHaveValue('8');
    await page.selectOption('#main-mode-select', 'workspace');
  });

  test('feedback mode: answer Gemma\'s open questions in a modal and copy report with answers', async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    const report = '## Zusammenfassung\nKurz.\n\n## Offene Fragen\n1. Frage A?\n2. Frage B?\n\n---\n\n## Anhang: Automatisch ermittelte Kennzahlen\n';
    const answered = report.replace('1. Frage A?\n2. Frage B?',
      '1. Frage A?\n   - **Antwort:** Antwort A\n2. Frage B?\n   - **Antwort:** – (übersprungen, weiterhin offen)');
    let posted: unknown = null;
    // Stub the stored-report API so the modal flow is tested without running Gemma
    await page.route('**/api/feedback/reports', r => r.fulfill({ json: { reports: [
      { feedback_id: 'f1', task_id: 't1', created_at: 1760000000, original_name: 'demo.pdf', region_count: 0 }] } }));
    await page.route('**/api/feedback/reports/t1/f1', r => r.fulfill({ json: {
      task_id: 't1', feedback_id: 'f1', report, meta: {},
      open_questions: [{ question: 'Frage A?', answer: null }, { question: 'Frage B?', answer: null }] } }));
    await page.route('**/api/feedback/reports/t1/f1/answers', async r => {
      posted = r.request().postDataJSON();
      await r.fulfill({ json: { report: answered, open_questions: [
        { question: 'Frage A?', answer: 'Antwort A' }, { question: 'Frage B?', answer: null }] } });
    });

    await page.goto('/');
    await page.selectOption('#main-mode-select', 'feedback');
    await page.selectOption('#fb-reports-select', 't1/f1');
    const answerBtn = page.locator('#fb-answer-questions-btn');
    await expect(answerBtn).toHaveText('❓ Offene Fragen beantworten (2)');

    // Step through: answer question 1, skip question 2 (last step saves)
    await answerBtn.click();
    const modal = page.locator('#fb-questions-modal');
    await expect(modal).toBeVisible();
    await expect(page.locator('#fb-question-counter')).toHaveText('Frage 1 von 2');
    await expect(page.locator('#fb-question-text')).toHaveText('Frage A?');
    await expect(page.locator('#fb-answer-input')).toBeFocused();
    await page.fill('#fb-answer-input', 'Antwort A');
    await page.click('#fb-question-next-btn');
    await expect(page.locator('#fb-question-text')).toHaveText('Frage B?');
    await expect(page.locator('#fb-question-next-btn')).toHaveText('Antworten übernehmen ✓');
    // Back keeps the draft
    await page.click('#fb-question-prev-btn');
    await expect(page.locator('#fb-answer-input')).toHaveValue('Antwort A');
    await page.keyboard.press('Control+Enter');
    await page.click('#fb-question-skip-btn');

    await expect(modal).toBeHidden();
    expect(posted).toEqual({ answers: ['Antwort A', null] });
    await expect(page.locator('#fb-report-content')).toContainText('Antwort: Antwort A');
    await expect(page.locator('#fb-report-content')).toContainText('weiterhin offen');
    await expect(answerBtn).toHaveText('✏️ Antworten bearbeiten (1/2)');

    // The copied report contains the answers
    await page.click('#fb-copy-report-btn');
    const clip = await page.evaluate(() => navigator.clipboard.readText());
    expect(clip).toContain('**Antwort:** Antwort A');

    // Esc closes the modal without saving
    posted = null;
    await answerBtn.click();
    await expect(modal).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(modal).toBeHidden();
    expect(posted).toBeNull();
  });

  test('feedback mode: PDF page numbers start at 1 and mouse wheel flips page by page', async ({ page, request }) => {
    test.setTimeout(60000);
    await page.goto('/');
    await page.selectOption('#main-mode-select', 'feedback');

    // test_educational.pdf has 4 PDF pages whose printed page numbers start at 45
    await page.click('#fb-toggle-new-job-btn');
    await page.setInputFiles('#fb-new-transfer-input', {
      name: 'auto.md', mimeType: 'text/markdown', buffer: Buffer.from('# Test\n\n((45))\n\nText\n'),
    });
    await page.setInputFiles('#fb-new-pdf-input', path.resolve(process.cwd(), 'testdata/test_educational.pdf'));
    await page.click('#fb-create-job-btn');
    await expect(page.locator('#fb-job-select')).not.toHaveValue('', { timeout: 15000 });
    const taskId = await page.inputValue('#fb-job-select');

    try {
      // Labels are PDF page numbers, never extracted/printed page numbers
      await expect(page.locator('#fb-page-select option')).toHaveText(['Seite 1 / 4', 'Seite 2 / 4', 'Seite 3 / 4', 'Seite 4 / 4']);
      await page.selectOption('#fb-page-select', '0');
      await expect(page.locator('#fb-page-image')).toBeVisible({ timeout: 20000 });
      await expect(page.locator('#fb-page-image')).toHaveAttribute('src', /\/pages\/0\b/);

      // One wheel gesture (several events) flips exactly one page
      const stage = page.locator('#fb-page-stage');
      await stage.hover();
      for (let i = 0; i < 5; i++) await page.mouse.wheel(0, 40);
      await expect(page.locator('#fb-page-select')).toHaveValue('1');
      await page.waitForTimeout(400);
      await expect(page.locator('#fb-page-select')).toHaveValue('1');

      // Next gesture flips one more page, scrolling up goes back
      await page.mouse.wheel(0, 120);
      await expect(page.locator('#fb-page-select')).toHaveValue('2');
      await page.waitForTimeout(400);
      await page.mouse.wheel(0, -120);
      await expect(page.locator('#fb-page-select')).toHaveValue('1');
      await expect(page.locator('#fb-page-image')).toHaveAttribute('src', /\/pages\/1\b/);

      // Stage itself never scrolls fluidly
      expect(await stage.evaluate(el => el.scrollTop)).toBe(0);

      // Keyboard paging for accessibility
      await stage.focus();
      await page.keyboard.press('PageDown');
      await expect(page.locator('#fb-page-select')).toHaveValue('2');
      await page.keyboard.press('Home');
      await expect(page.locator('#fb-page-select')).toHaveValue('0');
    } finally {
      await request.delete(`/api/tasks/${taskId}`);
    }
  });

  test('feedback mode: create job, upload revision, mark PDF region and get Gemma analysis', async ({ page, request }) => {
    // Real Gemma 4 runs when an existing (non-mock) backend is reused; allow up to 10 minutes.
    test.setTimeout(600000);
    const startedAt = Date.now();
    await page.goto('/');
    await page.selectOption('#main-mode-select', 'feedback');
    await expect(page.locator('#main-feedback-view')).toBeVisible();
    await expect(page.locator('#fb-analyze-btn')).toBeDisabled();

    // 1. Job missing from history -> create a new one from an MD export + source PDF
    await page.click('#fb-toggle-new-job-btn');
    await expect(page.locator('#fb-new-job-form')).toBeVisible();
    await expect(page.locator('#fb-create-job-btn')).toBeDisabled();
    const goldenMd = path.resolve(process.cwd(), 'testdata/golden/test_educational.uebertragungsregeln_09_2025.golden.md');
    await page.setInputFiles('#fb-new-transfer-input', goldenMd);
    await page.setInputFiles('#fb-new-pdf-input', path.resolve(process.cwd(), 'testdata/test_educational.pdf'));
    await page.click('#fb-create-job-btn');

    await expect(page.locator('#fb-job-select')).not.toHaveValue('', { timeout: 15000 });
    const taskId = await page.inputValue('#fb-job-select');
    try {
      await expect(page.locator('#fb-job-artifacts')).toContainText('Markdown-Quelle');
      await expect(page.locator('#fb-job-artifacts')).toContainText('Quell-PDF');

      // 2. Upload the revised transfer (Markdown)
      await page.setInputFiles('#fb-revised-input', {
        name: 'korrigiert.md',
        mimeType: 'text/markdown',
        buffer: Buffer.from('# Kapitel 1\n\n((45))\n\n### Aufgabe 1: Lichtbrechung\n\n-\tPunkt eins\n-\tPunkt zwei\n\n<Bild> Foto: Versuchsaufbau mit Prisma. </Bild>\n'),
      });
      await expect(page.locator('#fb-revised-badge')).toBeVisible();
      await expect(page.locator('#fb-analyze-btn')).toBeEnabled();

      // 3. Free-text feedback
      await page.fill('#fb-feedback-text', 'Aufgabennummern wurden nicht als Überschrift erkannt, Listen ohne Tabulator.');

      // 4. Mark a region on the rendered PDF page and extract it as PNG
      await expect(page.locator('#fb-page-image')).toBeVisible({ timeout: 20000 });
      const box = await page.locator('#fb-page-overlay').boundingBox();
      expect(box).not.toBeNull();
      await page.mouse.move(box!.x + box!.width * 0.1, box!.y + box!.height * 0.1);
      await page.mouse.down();
      await page.mouse.move(box!.x + box!.width * 0.6, box!.y + box!.height * 0.4, { steps: 8 });
      await page.mouse.up();
      await expect(page.locator('#fb-selection-rect')).toBeVisible();
      await page.fill('#fb-region-note', 'Überschrift fehlt');
      await page.click('#fb-add-region-btn');
      await expect(page.locator('#fb-region-count')).toHaveText('1');
      await expect(page.locator('#fb-regions-list')).toContainText('Überschrift fehlt');
      await expect(page.locator('#fb-regions-list a[download$=".png"]')).toHaveCount(1);

      // 5. Run the analysis – live Gemma panel shows logs + streamed tokens
      await page.click('#fb-analyze-btn');
      await expect(page.locator('#fb-live-panel')).toBeVisible();
      await expect(page.locator('#fb-live-warning')).toContainText('ungefiltert');
      await expect(page.locator('#fb-live-log li').first()).toBeAttached({ timeout: 60000 });


      // 6. Verify the final (filtered) report
      await expect(page.locator('#fb-result-section')).toBeVisible({ timeout: 580000 });
      await expect(page.locator('#fb-report-content')).toContainText('Zusammenfassung');
      await expect(page.locator('#fb-report-content')).toContainText('Benötigte Testdaten');
      await expect(page.locator('#fb-report-content')).toContainText('Anhang: Automatisch ermittelte Kennzahlen');
      await expect(page.locator('#fb-reports-select option')).not.toHaveCount(1);
      // Gemma's open questions are asked automatically if present – close without answering
      if (await page.locator('#fb-questions-modal').isVisible()) {
        await expect(page.locator('#fb-question-text')).not.toBeEmpty();
        await page.click('#fb-questions-close-btn');
        await expect(page.locator('#fb-questions-modal')).toBeHidden();
      }
      // Live output contained the region stream and the report stream; panel collapses after success
      await expect(page.locator('#fb-live-output')).toContainText('Markierte Stelle 1');
      await expect(page.locator('#fb-live-output')).toContainText('Fehleranalyse (Bericht)');
      await expect(page.locator('#fb-live-stats')).not.toHaveText('0 Tokens');
      await expect(page.locator('#fb-live-panel')).not.toHaveAttribute('open', '');
      await expect(page.locator('#fb-live-indicator')).not.toHaveClass(/is-active/);
    } finally {
      await request.delete(`/api/tasks/${taskId}`);
      console.log(`[E2E] Feedback flow duration: ${Math.round((Date.now() - startedAt) / 1000)}s`);
    }
  });

  test('interrupted task: shows "Unterbrochen", resumes via "Fortsetzen" and reattaches to the task stream', async ({ page }) => {
    test.setTimeout(30000);
    const taskId = 'e2e-interrupted-task';
    let resumed = false;
    const now = Date.now() / 1000;
    const baseTask = {
      task_id: taskId, original_name: 'unterbrochen.pdf', extension: '.pdf', engine: 'infinity',
      pages: '1-2', physical_start_page: 1, created_at: now - 600, started_at: now - 600, finished_at: null,
      job_kind: 'standardisation',
    };
    const interrupted = { ...baseTask, status: 'interrupted', resumable: true,
      progress: { percent: 92, current: 0, total: 0, phase: 'Unterbrochen – Lade Gemma VLM Modell...' } };
    const processing = { ...baseTask, status: 'processing', resumable: false,
      progress: { percent: 95, current: 0, total: 0, phase: 'Analysiere Bild 3/5 (VLM)...' } };

    await page.route('**/api/tasks', r => r.fulfill({ json: [resumed ? processing : interrupted] }));
    await page.route(`**/api/tasks/${taskId}/resume`, r => {
      resumed = true;
      return r.fulfill({ json: { status: 'resumed', stage: 'standardisation', task_id: taskId } });
    });
    await page.route(`**/api/tasks/${taskId}/state`, r => r.fulfill({ json: {
      ...(resumed ? processing : interrupted), raw_markdown: '# Roh', standardised_markdown: null, page_count: 2,
    } }));
    await page.route(`**/api/tasks/${taskId}/stream`, r => r.fulfill({
      contentType: 'application/x-ndjson',
      body: [
        { status: 'log', message: '▶️ Verarbeitung wird fortgesetzt (Standardisierung mit Bildbeschreibungen).', replay: true },
        { status: 'progress', percent: 98, phase: 'Wende Übertragungsregeln an (Gemma)...' },
        { status: 'stream_snapshot', text: '# Kapi' },
        { status: 'token', delta: 'tel' },
        { status: 'completed', stage: 'standardisation', markdown: '# Kapitel\n\nFertig übertragen.' },
      ].map(e => JSON.stringify(e)).join('\n') + '\n',
    }));
    await page.route(`**/api/pdf/${taskId}`, r => r.fulfill({ contentType: 'application/pdf', body: '%PDF-1.4' }));

    await page.goto('/');
    await page.click('#toggle-tasks-btn');
    const badge = page.locator('#tasks-list .task-status-badge').first();
    await expect(badge).toHaveText(/Unterbrochen/i);
    await expect(badge).toHaveAttribute('data-status', 'interrupted');

    await page.click(`#resume-btn-${taskId}`);
    await expect.poll(() => resumed).toBe(true);

    // Workspace reattached: final standardised markdown from the stream is shown
    await expect(page.locator('#standardised-markdown-textarea')).toHaveValue(/Fertig übertragen\./, { timeout: 10000 });
    await expect(page.locator('#logs-console')).toContainText('fortgesetzt');
    await expect(page.locator(`#resume-btn-${taskId}`)).toHaveCount(0);
  });

  test('Phase 3b: interactive grounding BBox overlay and Eurobraille (> U+00FF) character replacement assistant', async ({ page }) => {
    test.setTimeout(30000);
    const taskId = 'e2e-phase3b-task';
    const now = Date.now() / 1000;
    const completedTask = {
      task_id: taskId,
      original_name: 'physik_seite45.pdf',
      extension: '.pdf',
      engine: 'infinity',
      pages: '45-46',
      physical_start_page: 45,
      page_count: 2,
      status: 'completed',
      resumable: false,
      created_at: now - 120,
      started_at: now - 120,
      finished_at: now - 10,
      progress: { percent: 100, current: 2, total: 2, phase: 'Abgeschlossen' },
      raw_markdown: '((45))\n\n# 1 Mechanik\n\nWinkel α ≤ 90° → Kraft wirkt nach rechts.',
      standardised_markdown: '((45))\n\n# 1 Mechanik\n\nWinkel α ≤ 90° → Kraft wirkt nach rechts.\n\n((46))\n\nZweite Seite mit Pfeil →.',
    };

    // 1x1 transparent PNG
    const pngBase64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';
    const pngBuffer = Buffer.from(pngBase64, 'base64');

    await page.route('**/api/tasks', r => r.fulfill({ json: [completedTask] }));
    await page.route(`**/api/tasks/${taskId}/state`, r => r.fulfill({ json: completedTask }));
    await page.route(`**/api/pdf/${taskId}**`, r => r.fulfill({ contentType: 'application/pdf', body: '%PDF-1.4' }));
    await page.route(`**/api/feedback/jobs/${taskId}/pages/**`, r => r.fulfill({
      contentType: 'image/png',
      body: pngBuffer,
    }));
    await page.route(`**/api/tasks/${taskId}/layout`, r => r.fulfill({
      json: {
        task_id: taskId,
        physical_start_page: 45,
        blocks: [
          {
            type: 'title',
            text: '# 1 Mechanik',
            page_idx: 0,
            bbox_1000: [80, 60, 520, 120],
            text_level: 1,
            is_callout_box: false,
          },
          {
            type: 'text',
            text: 'Winkel α ≤ 90° → Kraft wirkt nach rechts.',
            page_idx: 0,
            bbox_1000: [80, 150, 880, 260],
            text_level: null,
            is_callout_box: false,
          },
          {
            type: 'text',
            text: 'Zweite Seite mit Pfeil →.',
            page_idx: 1,
            bbox_1000: [80, 100, 750, 200],
            text_level: null,
            is_callout_box: false,
          },
        ],
      },
    }));
    let suggestedChars: string[] = [];
    await page.route('**/api/char-replacements/suggest', async r => {
      const body = r.request().postDataJSON();
      suggestedChars = body.chars || [];
      await r.fulfill({
        json: {
          suggestions: {
            'α': '\\alpha',
            '≤': '\\le',
            '→': '\\rightarrow',
          },
        },
      });
    });

    await page.goto(`/?task_id=${taskId}`);
    await expect(page.locator('#standardised-markdown-textarea')).toHaveValue(/Winkel α ≤ 90° → Kraft/);

    // 1. Verify BBox Overlay toggle & rendering
    await page.click('#toggle-pane-pdf');
    await expect(page.locator('#panel-pdf-container')).toBeVisible();
    await expect(page.locator('#btn-toggle-bbox-overlay')).toHaveAttribute('aria-pressed', 'false');

    await page.click('#btn-toggle-bbox-overlay');
    await expect(page.locator('#btn-toggle-bbox-overlay')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('#pdf-bbox-viewer')).toBeVisible();
    await expect(page.locator('#bbox-page-indicator')).toHaveText('Seite 1 / 2');

    const rects = page.locator('#bbox-overlay-layer .bbox-rect');
    await expect(rects).toHaveCount(2);
    await expect(rects.nth(0)).toHaveAttribute('data-block-type', 'title');
    await expect(rects.nth(1)).toHaveAttribute('data-block-type', 'text');

    // Filter chip test
    await page.locator('#bbox-filter-chips .bbox-filter-chip[data-filter="title"]').click();
    await expect(rects).toHaveCount(1);
    await page.locator('#bbox-filter-chips .bbox-filter-chip[data-filter="all"]').click();
    await expect(rects).toHaveCount(2);

    // Next page navigation in BBox overlay
    await page.click('#bbox-next-page');
    await expect(page.locator('#bbox-page-indicator')).toHaveText('Seite 2 / 2');
    await expect(rects).toHaveCount(1);

    // 2. Verify Eurobraille (> U+00FF) Character Replacement Assistant
    // Characters > U+00FF in document: α (U+03B1), → (U+2192), ≤ (U+2264). Note: ° (U+00B0) and ä/ü are <= U+00FF.
    const badge = page.locator('#char-replace-badge');
    await expect(badge).toBeVisible();
    await expect(badge).toHaveText('3');

    await page.click('#btn-char-replacements');
    const modal = page.locator('#char-replace-modal');
    await expect(modal).toBeVisible();

    const rows = page.locator('#char-replace-tbody tr[data-char]');
    await expect(rows).toHaveCount(3);
    await expect(page.locator('#char-replace-tbody')).toContainText('U+03B1');
    await expect(page.locator('#char-replace-tbody')).toContainText('U+2192');
    await expect(page.locator('#char-replace-tbody')).toContainText('U+2264');

    // Fetch AI suggestions via POST /api/char-replacements/suggest
    await page.click('#btn-suggest-char-replacements');
    await expect.poll(() => suggestedChars.length).toBe(3);
    await expect(page.locator('.char-replace-input[data-char="α"]')).toHaveValue('\\alpha');
    await expect(page.locator('.char-replace-input[data-char="≤"]')).toHaveValue('\\le');
    await expect(page.locator('.char-replace-input[data-char="→"]')).toHaveValue('\\rightarrow');

    // Apply replacements to Markdown editor
    await page.click('#btn-apply-char-replacements');
    await expect(modal).toBeHidden();
    await expect(page.locator('#standardised-markdown-textarea')).toHaveValue(
      '((45))\n\n# 1 Mechanik\n\nWinkel \\alpha \\le 90° \\rightarrow Kraft wirkt nach rechts.\n\n((46))\n\nZweite Seite mit Pfeil \\rightarrow.'
    );
    await expect(badge).toBeHidden();

    // Verify localStorage persistence
    const savedStorage = await page.evaluate(() => localStorage.getItem('ebuch_char_replacements_v1'));
    expect(savedStorage).toBeTruthy();
    expect(JSON.parse(savedStorage!)).toMatchObject({
      'α': { replacement: '\\alpha', active: true },
      '≤': { replacement: '\\le', active: true },
      '→': { replacement: '\\rightarrow', active: true },
    });
  });

});



