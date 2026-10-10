import { resolve } from 'node:path';
import { defineConfig, devices } from '@playwright/test';

const repositoryRoot = resolve(__dirname, '..');
const databaseUrl =
  process.env.WIUT_REAL_ML_DATABASE_URL ??
  'postgresql://wiut:wiut_dev@127.0.0.1:55432/wiut_real_ml';

// Opt-in only: requires the trained local real-data model, its Python environment,
// and a separate PostgreSQL database. The standard fixture suite is unchanged.
export default defineConfig({
  testDir: './real-ml',
  testMatch: '**/*.real.ts',
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
        outputFolder: resolve(repositoryRoot, 'playwright-report/real-ml'),
      },
    ],
  ],
  outputDir: '../test-results/real-ml',
  use: {
    baseURL: 'http://127.0.0.1:5176',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'real-ml-chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: [
    {
      command:
        'uv run --frozen --directory ml-service uvicorn capacity_ml.api:app --host 127.0.0.1 --port 8110',
      cwd: repositoryRoot,
      url: 'http://127.0.0.1:8110/health',
      env: { ML_AUDIT_PATH: 'runtime/real-integration-audit.jsonl' },
      timeout: 60_000,
      reuseExistingServer: false,
    },
    {
      command: 'node apps/backend/user/user-app-api/dist/main.js',
      cwd: repositoryRoot,
      url: 'http://127.0.0.1:3010/api/health',
      env: {
        NODE_ENV: 'test',
        DATABASE_URL: databaseUrl,
        API_HOST: '127.0.0.1',
        API_PORT: '3010',
        ML_SERVICE_URL: 'http://127.0.0.1:8110',
        ML_TIMEOUT_MS: '8000',
        CORS_ORIGINS: 'http://127.0.0.1:5176',
        AUTH_RATE_LIMIT_MAX: '200',
      },
      timeout: 60_000,
      reuseExistingServer: false,
    },
    {
      command: 'pnpm --filter @wiut/web dev --port 5176 --strictPort',
      cwd: repositoryRoot,
      url: 'http://127.0.0.1:5176',
      env: { VITE_API_PROXY_URL: 'http://127.0.0.1:3010' },
      timeout: 60_000,
      reuseExistingServer: false,
    },
  ],
});
