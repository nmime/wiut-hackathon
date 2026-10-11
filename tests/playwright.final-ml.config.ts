import { resolve } from 'node:path';
import { defineConfig, devices } from '@playwright/test';

const repositoryRoot = resolve(__dirname, '..');

// Actual final scorer in an isolated test stack. Borrower fixtures remain
// synthetic and cannot enter the development or production bank portfolios.
export default defineConfig({
  testDir: './final-ml',
  testMatch: '**/*.final.ts',
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: [
    ['list'],
    [
      'html',
      {
        open: 'never',
        outputFolder: resolve(repositoryRoot, 'playwright-report/final-ml'),
      },
    ],
  ],
  outputDir: '../test-results/final-ml',
  use: {
    baseURL: 'http://127.0.0.1:5178',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'final-ml-chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: [
    {
      command: 'bash scripts/serve_final_model.sh',
      cwd: repositoryRoot,
      url: 'http://127.0.0.1:8112/health',
      env: {
        FINAL_MODEL_PORT: '8112',
        ML_AUDIT_PATH: resolve(
          repositoryRoot,
          'hybrid-runtime/runtime/final-integration-audit.jsonl',
        ),
      },
      timeout: 60_000,
      reuseExistingServer: false,
    },
    {
      command: 'node apps/backend/user/user-app-api/dist/main.js',
      cwd: repositoryRoot,
      url: 'http://127.0.0.1:3012/api/health',
      env: {
        NODE_ENV: 'test',
        DATABASE_URL:
          process.env.WIUT_FINAL_ML_DATABASE_URL ??
          'postgresql://wiut:wiut_dev@127.0.0.1:55432/wiut_final_ml',
        API_HOST: '127.0.0.1',
        API_PORT: '3012',
        ML_SERVICE_URL: 'http://127.0.0.1:8112',
        ML_TIMEOUT_MS: '8000',
        CORS_ORIGINS: 'http://127.0.0.1:5178',
        AUTH_RATE_LIMIT_MAX: '200',
      },
      timeout: 60_000,
      reuseExistingServer: false,
    },
    {
      command: 'pnpm --filter @wiut/web dev --port 5178 --strictPort',
      cwd: repositoryRoot,
      url: 'http://127.0.0.1:5178',
      env: { VITE_API_PROXY_URL: 'http://127.0.0.1:3012' },
      timeout: 60_000,
      reuseExistingServer: false,
    },
  ],
});
