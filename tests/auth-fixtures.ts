import { randomUUID } from 'node:crypto';
import {
  test as base,
  expect,
  type APIRequestContext,
  type PlaywrightWorkerArgs,
} from '@playwright/test';
import { AuthSessionSchema } from '../libs/common/api-contracts/src/index';

type Playwright = PlaywrightWorkerArgs['playwright'];

export interface TestSession {
  user: { id: string; email: string; display_name: string };
  tenant: {
    id: string;
    name: string;
    role: 'admin' | 'officer';
    kind: 'bank' | 'showcase';
  };
  tenants: {
    id: string;
    name: string;
    role: 'admin' | 'officer';
    kind: 'bank' | 'showcase';
  }[];
  csrf_token: string;
}

export const TEST_PASSWORD = 'Test-Only-Strong-Passphrase-2026!';
export const TEST_ORIGIN = 'http://127.0.0.1:5174';

export function authOrigin(apiUrl: string) {
  const port = new URL(apiUrl).port;
  if (port === '3010') return 'http://127.0.0.1:5176';
  if (port === '3011') return 'http://127.0.0.1:5177';
  if (port === '3012') return 'http://127.0.0.1:5178';
  return TEST_ORIGIN;
}

export async function registerAccount(
  playwright: Playwright,
  apiUrl: string,
  options: {
    email?: string;
    displayName?: string;
    tenantName?: string;
    invitationToken?: string;
  } = {},
) {
  const anonymous = await playwright.request.newContext({
    extraHTTPHeaders: { origin: authOrigin(apiUrl) },
  });
  try {
    const response = await anonymous.post(`${apiUrl}/auth/register`, {
      data: {
        email: options.email ?? `integration-${randomUUID()}@example.test`,
        password: TEST_PASSWORD,
        display_name: options.displayName ?? 'Integration Officer',
        ...(options.invitationToken
          ? { invitation_token: options.invitationToken }
          : { tenant_name: options.tenantName ?? `Test bank ${randomUUID()}` }),
      },
    });
    expect(response.status(), await response.text()).toBe(201);
    const session = AuthSessionSchema.parse(await response.json());
    expect(session.csrf_token).toBeTruthy();
    const request = await playwright.request.newContext({
      storageState: await anonymous.storageState(),
      extraHTTPHeaders: {
        origin: authOrigin(apiUrl),
        'x-csrf-token': session.csrf_token,
      },
    });
    return { request, session };
  } finally {
    await anonymous.dispose();
  }
}

export const test = base.extend<{
  authApiUrl: string;
  authenticate: boolean;
}>({
  authApiUrl: ['http://127.0.0.1:3001/api', { option: true }],
  authenticate: [true, { option: true }],
  request: async ({ playwright, authApiUrl, authenticate }, use) => {
    const request = authenticate
      ? (await registerAccount(playwright, authApiUrl)).request
      : await playwright.request.newContext();
    try {
      await use(request);
    } finally {
      await request.dispose();
    }
  },
  page: async ({ page, request }, use) => {
    await page.context().addCookies((await request.storageState()).cookies);
    await use(page);
  },
});

export { expect };
