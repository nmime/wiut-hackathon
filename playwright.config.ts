import { defineConfig, devices } from '@playwright/test';

const databaseUrl =
  process.env.WIUT_TEST_DATABASE_URL ??
  'postgresql://wiut:wiut_dev@127.0.0.1:55432/wiut_test';
const noMlDatabaseUrl =
  process.env.WIUT_NO_ML_DATABASE_URL ??
  'postgresql://wiut:wiut_dev@127.0.0.1:55432/wiut_no_ml';

// The test stack is deliberately separate from the developer app and database.
// The ML fixture is synthetic test data, never a production scoring fallback.
export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:5174',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: 'node tests/ml-fixture.mjs',
      url: 'http://127.0.0.1:8101/health',
      env: { NODE_ENV: 'test', WIUT_TEST_FIXTURE: '1' },
      reuseExistingServer: false,
    },
    {
      command: 'node apps/backend/user/user-app-api/dist/main.js',
      url: 'http://127.0.0.1:3001/api/health',
      env: {
        NODE_ENV: 'test',
        DATABASE_URL: databaseUrl,
        API_HOST: '127.0.0.1',
        API_PORT: '3001',
        ML_SERVICE_URL: 'http://127.0.0.1:8101',
        ML_TIMEOUT_MS: '250',
        CORS_ORIGINS: 'http://127.0.0.1:5174',
        AUTH_RATE_LIMIT_MAX: '200',
        // Fixed key only for the isolated test database, never production.
        AUTH_ENCRYPTION_KEY: '8'.repeat(64),
      },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: 'node apps/backend/user/user-app-api/dist/main.js',
      url: 'http://127.0.0.1:3002/api/health',
      env: {
        NODE_ENV: 'test',
        DATABASE_URL: noMlDatabaseUrl,
        API_HOST: '127.0.0.1',
        API_PORT: '3002',
        ML_SERVICE_URL: '',
        // Exercise fail-closed MFA availability without inheriting the dev key.
        AUTH_ENCRYPTION_KEY: '',
        CORS_ORIGINS: 'http://127.0.0.1:5174',
        AUTH_RATE_LIMIT_MAX: '200',
      },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: 'pnpm --filter @wiut/web dev --port 5174 --strictPort',
      url: 'http://127.0.0.1:5174',
      env: { VITE_API_PROXY_URL: 'http://127.0.0.1:3001' },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
