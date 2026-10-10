import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadConfig } from './config.js';

test('local configuration defaults use isolated dev ports and honest absent ML state', () => {
  const config = loadConfig({});
  assert.equal(config.API_HOST, '127.0.0.1');
  assert.equal(config.API_PORT, 3000);
  assert.equal(config.ML_TIMEOUT_MS, 8000);
  assert.equal(config.ML_SERVICE_URL, undefined);
  assert.equal(new URL(config.DATABASE_URL).port, '55432');
  assert.deepEqual(config.corsOrigins, [
    'http://localhost:5173',
    'http://127.0.0.1:5173',
  ]);
});

test('invalid connection protocols, secrets in ML URL, timeout and wildcard origins are rejected', () => {
  for (const environment of [
    { DATABASE_URL: 'http://localhost/db' },
    { ML_SERVICE_URL: 'http://secret:password@localhost:8000' },
    { ML_SERVICE_URL: 'ftp://localhost:8000' },
    { ML_SERVICE_URL: 'https://localhost:8000?api_key=secret' },
    { ML_TIMEOUT_MS: '0' },
    { ML_TIMEOUT_MS: '60001' },
    { API_PORT: '70000' },
    { CORS_ORIGINS: '*' },
    { CORS_ORIGINS: 'https://demo.example/path' },
  ]) {
    assert.throws(() => loadConfig(environment), /Invalid environment/);
  }
  assert.equal(loadConfig({ ML_SERVICE_URL: '   ' }).ML_SERVICE_URL, undefined);
});
