import { test, expect } from '@playwright/test';
import path from 'path';
import fs from 'fs';

test.describe('E2E Processing Benchmark', () => {
  test('Run quality and speed benchmark for LightOnOCR-3, Infinity-Parser2-Flash, and Docling', async ({ page }) => {
    test.setTimeout(1800000); // 30 minutes limit

    const results: any = {
      lightonocr: { duration: 0, pagesOk: false, imagesCount: 0, altTextOk: false, formulasOk: false, footnotesOk: false, difficultyOk: false, error: null },
      infinity: { duration: 0, pagesOk: false, imagesCount: 0, altTextOk: false, formulasOk: false, footnotesOk: false, difficultyOk: false, error: null },
      docling: { duration: 0, pagesOk: false, imagesCount: 0, altTextOk: false, formulasOk: false, footnotesOk: false, difficultyOk: false, error: null }
    };

    const runFlow = async (engine: 'lightonocr' | 'infinity' | 'docling') => {
      page.on('console', msg => console.log(`[Browser - ${engine}] ${msg.text()}`));
      await page.goto('/');
      await page.evaluate(() => localStorage.clear());
      await page.goto('/');
      
      // 1. Select the standard ruleset
      await page.selectOption('#ruleset-select', 'uebertragungsregeln_09_2025');

      // 2. Select the extraction engine option
      await page.selectOption('#engine-select', engine);

      // 3. Upload the test educational PDF
      const fileChooserPromise = page.waitForEvent('filechooser');
      await page.click('#dropzone');
      const fileChooser = await fileChooserPromise;
      const testPdfPath = path.resolve(process.cwd(), 'testdata/test_educational.pdf');
      await fileChooser.setFiles(testPdfPath);
      await expect(page.locator('#process-btn')).toBeEnabled();

      // Fill the pages selection range
      await page.fill('#pages-input', '45-48');

      // Upload custom file-specific ruleset
      const rulesetChooserPromise = page.waitForEvent('filechooser');
      await page.click('#ruleset-upload-zone');
      const rulesetChooser = await rulesetChooserPromise;
      const rulesetPath = path.resolve(process.cwd(), 'testdata/test_educational_rules.txt');
      await rulesetChooser.setFiles(rulesetPath);
      await expect(page.locator('#ruleset-status-text')).toContainText('test_educational_rules.txt');

      // 4. Click process button and record start time
      const startTime = Date.now();
      await page.click('#process-btn');
      
      // Wait for standardisation and pipeline completion
      await expect(page.locator('#download-docx-btn')).toBeEnabled({ timeout: 1200000 });
      const duration = (Date.now() - startTime) / 1000;

      // 5. Read output content
      const standardisedContent = await page.inputValue('#standardised-markdown-textarea');

      // 6. Quality Assertions
      const pagesOk = standardisedContent.includes('((45))') && 
                      standardisedContent.includes('((46))') &&
                      standardisedContent.includes('((47))') &&
                      standardisedContent.includes('((48))');
                      
      const imagesCount = (standardisedContent.match(/<Bild/g) || []).length;
      
      // Verify alt-text is present and not dummy placeholder
      const altTextOk = standardisedContent.includes('<Bild') && 
                        !standardisedContent.includes('Abbildung ohne Beschreibung') &&
                        standardisedContent.includes('Versuchsaufbau');

      // Verify formulas representation is correct
      const formulasOk = standardisedContent.includes('n1 * sin(') || 
                         standardisedContent.includes('n_1') || 
                         standardisedContent.includes('n1') ||
                         standardisedContent.includes('lambda');

      // Verify footnotes representation
      const footnotesOk = standardisedContent.includes('Optisches Dichte-Experiment') && 
                          standardisedContent.includes('Snelliussche Brechungsgesetz');

      // Verify difficulty indicators translation (accessible formatting)
      const difficultyOk = standardisedContent.includes('○ [leicht]') &&
                           standardisedContent.includes('◐ [mittel]') &&
                           standardisedContent.includes('● [schwer]');

      return { duration, pagesOk, imagesCount, altTextOk, formulasOk, footnotesOk, difficultyOk };
    };

    console.log('--- Starting LightOnOCR-3 Benchmark Run ---');
    try {
      const runRes = await runFlow('lightonocr');
      results.lightonocr = { ...runRes, error: null };
    } catch (e: any) {
      console.error('LightOnOCR-3 run failed:', e);
      results.lightonocr.error = e.message || String(e);
    }

    console.log('--- Starting Infinity-Parser2-Flash Benchmark Run ---');
    try {
      const runRes = await runFlow('infinity');
      results.infinity = { ...runRes, error: null };
    } catch (e: any) {
      console.error('Infinity-Parser2-Flash run failed:', e);
      results.infinity.error = e.message || String(e);
    }

    console.log('--- Starting Docling Benchmark Run ---');
    try {
      const runRes = await runFlow('docling');
      results.docling = { ...runRes, error: null };
    } catch (e: any) {
      console.error('Docling run failed:', e);
      results.docling.error = e.message || String(e);
    }

    // Format comparison table
    const logContent = `
========================================================================================
                      E2E EXTRACTION BENCHMARK RESULTS
========================================================================================
Timestamp: ${new Date().toISOString()}
Metric                     | LightOnOCR-3         | Infinity-Parser2     | Docling (IBM)
---------------------------+----------------------+----------------------+---------------------
Time Elapsed (s)           | ${results.lightonocr.error ? 'Error'.padEnd(20) : results.lightonocr.duration.toFixed(1).padEnd(20)} | ${results.infinity.error ? 'Error'.padEnd(20) : results.infinity.duration.toFixed(1).padEnd(20)} | ${results.docling.error ? 'Error'.padEnd(19) : results.docling.duration.toFixed(1).padEnd(19)}
Page Boundary Markers Ok   | ${results.lightonocr.error ? 'N/A'.padEnd(20) : (results.lightonocr.pagesOk ? 'Yes (Pass)'.padEnd(20) : 'No (Fail)'.padEnd(20))} | ${results.infinity.error ? 'N/A'.padEnd(20) : (results.infinity.pagesOk ? 'Yes (Pass)'.padEnd(20) : 'No (Fail)'.padEnd(20))} | ${results.docling.error ? 'N/A'.padEnd(19) : (results.docling.pagesOk ? 'Yes (Pass)'.padEnd(19) : 'No (Fail)'.padEnd(19))}
Images Found Count         | ${results.lightonocr.error ? 'N/A'.padEnd(20) : results.lightonocr.imagesCount.toString().padEnd(20)} | ${results.infinity.error ? 'N/A'.padEnd(20) : results.infinity.imagesCount.toString().padEnd(20)} | ${results.docling.error ? 'N/A'.padEnd(19) : results.docling.imagesCount.toString().padEnd(19)}
Accessibility Descriptions | ${results.lightonocr.error ? 'N/A'.padEnd(20) : (results.lightonocr.altTextOk ? 'Yes (Pass)'.padEnd(20) : 'No (Fail)'.padEnd(20))} | ${results.infinity.error ? 'N/A'.padEnd(20) : (results.infinity.altTextOk ? 'Yes (Pass)'.padEnd(20) : 'No (Fail)'.padEnd(20))} | ${results.docling.error ? 'N/A'.padEnd(19) : (results.docling.altTextOk ? 'Yes (Pass)'.padEnd(19) : 'No (Fail)'.padEnd(19))}
Math Formulas Intact       | ${results.lightonocr.error ? 'N/A'.padEnd(20) : (results.lightonocr.formulasOk ? 'Yes (Pass)'.padEnd(20) : 'No (Fail)'.padEnd(20))} | ${results.infinity.error ? 'N/A'.padEnd(20) : (results.infinity.formulasOk ? 'Yes (Pass)'.padEnd(20) : 'No (Fail)'.padEnd(20))} | ${results.docling.error ? 'N/A'.padEnd(19) : (results.docling.formulasOk ? 'Yes (Pass)'.padEnd(19) : 'No (Fail)'.padEnd(19))}
Footnotes Formatted        | ${results.lightonocr.error ? 'N/A'.padEnd(20) : (results.lightonocr.footnotesOk ? 'Yes (Pass)'.padEnd(20) : 'No (Fail)'.padEnd(20))} | ${results.infinity.error ? 'N/A'.padEnd(20) : (results.infinity.footnotesOk ? 'Yes (Pass)'.padEnd(20) : 'No (Fail)'.padEnd(20))} | ${results.docling.error ? 'N/A'.padEnd(19) : (results.docling.footnotesOk ? 'Yes (Pass)'.padEnd(19) : 'No (Fail)'.padEnd(19))}
Difficulty Indicators Ok   | ${results.lightonocr.error ? 'N/A'.padEnd(20) : (results.lightonocr.difficultyOk ? 'Yes (Pass)'.padEnd(20) : 'No (Fail)'.padEnd(20))} | ${results.infinity.error ? 'N/A'.padEnd(20) : (results.infinity.difficultyOk ? 'Yes (Pass)'.padEnd(20) : 'No (Fail)'.padEnd(20))} | ${results.docling.error ? 'N/A'.padEnd(19) : (results.docling.difficultyOk ? 'Yes (Pass)'.padEnd(19) : 'No (Fail)'.padEnd(19))}
========================================================================================
LightOnOCR-3 Error Details:| ${results.lightonocr.error || 'None'}
Infinity Error Details:    | ${results.infinity.error || 'None'}
Docling Error Details:     | ${results.docling.error || 'None'}
========================================================================================
`;

    console.log(logContent);

    const logPath = path.resolve(process.cwd(), 'benchmark_results.log');
    fs.appendFileSync(logPath, logContent, 'utf-8');
    console.log(`Saved benchmark results to persistent log: ${logPath}`);

    if (results.lightonocr.error) {
      throw new Error(`LightOnOCR-3 run failed: ${results.lightonocr.error}`);
    }
    if (results.infinity.error) {
      throw new Error(`Infinity run failed: ${results.infinity.error}`);
    }
    if (results.docling.error) {
      throw new Error(`Docling run failed: ${results.docling.error}`);
    }

    expect(results.lightonocr.duration).toBeGreaterThan(0);
    expect(results.infinity.duration).toBeGreaterThan(0);
    expect(results.docling.duration).toBeGreaterThan(0);
  });
});
