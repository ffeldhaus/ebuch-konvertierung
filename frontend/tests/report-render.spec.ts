import { test, expect } from '@playwright/test';
import { renderReportMarkdown } from '../src/feedback';

/**
 * Fast, browser-free checks of the safe report Markdown renderer used in the Feedback mode.
 */
test.describe('Feedback report renderer', () => {
  test('keeps ordered list numbering across nested bullet lists and blank lines', () => {
    const html = renderReportMarkdown(
      '1.  **`llm_service.py`**: Prompt\n' +
      '    *   Regel A\n' +
      '    *   Regel B\n' +
      '\n' +
      '2.  **Tests**\n' +
      '    - Snippet\n'
    );
    // Exactly one ordered list containing both items, each with a nested <ul>
    expect(html.match(/<ol>/g)?.length).toBe(1);
    expect(html.match(/<ul>/g)?.length).toBe(2);
    expect(html).toMatch(/<li><strong><code>llm_service.py<\/code><\/strong>: Prompt\s*<ul>\s*<li>Regel A\s*<\/li>/);
    expect(html).toContain('<li><strong>Tests</strong>');
  });

  test('renders overview tables and escapes model HTML', () => {
    const html = renderReportMarkdown('| # | Muster |\n| :--- | :--- |\n| 1 | <script>x</script> |');
    expect(html).toContain('<table>');
    expect(html).toContain('&lt;script&gt;');
    expect(html).not.toContain('<script>');
  });

  test('starts a new list after a heading', () => {
    const html = renderReportMarkdown('- a\n### Muster 2\n- b');
    expect(html.match(/<ul>/g)?.length).toBe(2);
  });
});
