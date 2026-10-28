import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './frontend/tests',
  testMatch: process.env.RUN_BENCHMARK
    ? '**/benchmark.spec.ts'
    : process.env.RUN_PIPELINE
    ? '**/pipeline-integration.spec.ts'
    : ['**/e2e.spec.ts', '**/report-render.spec.ts'],
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1, // Keep sequential to avoid database/port conflicts
  reporter: 'html',
  use: {
    baseURL: 'http://localhost:3000',
    trace: 'on-first-retry',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  // Launch both Vite frontend and FastAPI backend automatically
  webServer: [
    {
      command: './node_modules/.bin/vite --port 3000',
      url: 'http://localhost:3000',
      reuseExistingServer: !process.env.CI,
      timeout: 10000,
    },
    {
      command: (process.env.RUN_BENCHMARK || process.env.RUN_PIPELINE)
        ? 'PYTHONPATH=. .venv/bin/uvicorn backend.main:app --port 8000'
        : 'E2E_MOCK=true PYTHONPATH=. .venv/bin/uvicorn backend.main:app --port 8000',
      url: 'http://localhost:8000/docs',
      reuseExistingServer: !process.env.CI,
      timeout: 15000,
    }
  ],
});
