import { resolve } from 'node:path';
import { defineConfig, devices } from '@playwright/test';

const repositoryRoot = resolve(__dirname, '..');

// Separate opt-in verification: the private teammate candidate is never selected
// for standard fixture tests or the frozen real-revenue model's regression suite.
export default defineConfig({
  testDir: './teammate-ml',
  testMatch: '**/*.teammate.ts',
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
        outputFolder: resolve(repositoryRoot, 'playwright-report/teammate-ml'),
      },
    ],
  ],
  outputDir: '../test-results/teammate-ml',
  use: {
    baseURL: 'http://127.0.0.1:5177',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'teammate-ml-chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: [
    {
      command:
        'uv run --frozen --directory teammate-ml-service uvicorn teammate_bridge.api:app --host 127.0.0.1 --port 8111',
      cwd: repositoryRoot,
      url: 'http://127.0.0.1:8111/health',
      env: { ML_AUDIT_PATH: 'runtime/teammate-integration-audit.jsonl' },
      timeout: 60_000,
      reuseExistingServer: false,
    },
    {
      command: 'node apps/backend/user/user-app-api/dist/main.js',
      cwd: repositoryRoot,
      url: 'http://127.0.0.1:3011/api/health',
      env: {
        NODE_ENV: 'test',
        DATABASE_URL:
          process.env.WIUT_TEAMMATE_ML_DATABASE_URL ??
          'postgresql://wiut:wiut_dev@127.0.0.1:55432/wiut_teammate_ml',
        API_HOST: '127.0.0.1',
        API_PORT: '3011',
        ML_SERVICE_URL: 'http://127.0.0.1:8111',
        ML_TIMEOUT_MS: '8000',
        CORS_ORIGINS: 'http://127.0.0.1:5177',
        AUTH_RATE_LIMIT_MAX: '200',
      },
      timeout: 60_000,
      reuseExistingServer: false,
    },
    {
      command: 'pnpm --filter @wiut/web dev --port 5177 --strictPort',
      cwd: repositoryRoot,
      url: 'http://127.0.0.1:5177',
      env: { VITE_API_PROXY_URL: 'http://127.0.0.1:3011' },
      timeout: 60_000,
      reuseExistingServer: false,
    },
  ],
});
