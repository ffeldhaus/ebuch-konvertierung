import { test, expect } from '@playwright/test';
import path from 'path';
import fs from 'fs';

test.describe('E-Buch Real Model Pipeline Integration Test (Infinity + Gemma 8-Bit)', () => {

  test('should execute full unmocked pipeline with Infinity extraction, Gemma VLM and standardisation', async ({ page }) => {
    test.setTimeout(300000); // 5 minutes budget for real MLX GPU pipeline (cold start + Infinity + Gemma VLM + Gemma LLM)

    const startTime = Date.now();
    await page.goto('/');

    // 1. Verify workspace is loaded
    await expect(page.locator('#workspace-title')).toContainText('E-Buch Standard Konverter');

    // 2. Select Infinity-Parser2-Flash engine for fast GPU execution (~2s / page)
    await page.selectOption('#engine-select', 'infinity');

    // 3. Select standard ruleset
    await page.selectOption('#ruleset-select', 'uebertragungsregeln_09_2025');

    // 4. Upload test educational PDF (Physics/Optics with image)
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.click('#dropzone');
    const fileChooser = await fileChooserPromise;
    const testPdfPath = path.resolve(process.cwd(), 'testdata/test_educational.pdf');
    await fileChooser.setFiles(testPdfPath);

    // Wait for file status to appear
    await expect(page.locator('#file-status')).toBeVisible();
    await expect(page.locator('#process-btn')).toBeEnabled();

    // 5. Select page 45 (single page to execute quickly)
    await page.fill('#pages-input', '45');
    await expect(page.locator('#describe-images-toggle')).toBeChecked();

    // 6. Click process to start real model pipeline
    await page.click('#process-btn');

    // Stepper should change to active extraction
    await expect(page.locator('#step-2-indicator')).toHaveClass(/text-indigo-400/);

    // 7. Wait for completion and verify download button enabled
    await expect(page.locator('#download-docx-btn')).toBeEnabled({ timeout: 240000 });

    const durationSec = ((Date.now() - startTime) / 1000).toFixed(1);
    console.log(`[PIPELINE INTEGRATION] Real pipeline finished in ${durationSec}s`);

    // 8. Verify raw markdown output from Infinity Parser
    const rawContent = await page.inputValue('#raw-markdown-textarea');
    expect(rawContent).toBeTruthy();
    expect(rawContent).toContain('((');

    // 9. Verify standardized markdown output from Gemma VLM + E-Buch Standardisation
    const standardisedContent = await page.inputValue('#standardised-markdown-textarea');
    expect(standardisedContent).toBeTruthy();
    expect(standardisedContent).toContain('<Bild>');
    expect(standardisedContent).toContain('</Bild>');
    expect(standardisedContent).toContain('((');

    // 10. Persist run artifact to benchmarks/runs for immediate reuse in benchmark analysis
    const benchmarkRunDir = path.resolve(process.cwd(), 'benchmarks/runs');
    if (!fs.existsSync(benchmarkRunDir)) {
      fs.mkdirSync(benchmarkRunDir, { recursive: true });
    }

    const timestamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14);
    const benchmarkPayload = {
      run_id: `pipeline_integration_${timestamp}`,
      timestamp: new Date().toISOString(),
      engine: 'infinity',
      model: 'gemma-4-12b-it-8bit',
      duration_seconds: parseFloat(durationSec),
      dataset: 'test_educational.pdf',
      page_range: '45',
      raw_markdown_length: rawContent.length,
      standardised_markdown_length: standardisedContent.length,
      has_image_descriptions: standardisedContent.includes('<Bild>'),
      sample_output: standardisedContent.slice(0, 500)
    };

    const runFilePath = path.join(benchmarkRunDir, `run_pipeline_integration_${timestamp}.json`);
    fs.writeFileSync(runFilePath, JSON.stringify(benchmarkPayload, null, 2), 'utf-8');
    console.log(`[PIPELINE INTEGRATION] Benchmark artifact written to: ${runFilePath}`);
  });

});
