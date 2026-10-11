import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { test, expect, TEST_PASSWORD } from './auth-fixtures';
import { API_URL } from './helpers';

// Authentication secrets must not be recorded in screenshots or traces, even
// when they belong only to an isolated test account.
test.use({ screenshot: 'off', trace: 'off' });

async function enrollmentCode(secret: string) {
  const module = await import(
    pathToFileURL(
      resolve(
        __dirname,
        '../apps/backend/user/user-app-api/dist/account-security.js',
      ),
    ).href
  );
  return module.hotp(secret, Math.floor(Date.now() / 30_000) - 1) as string;
}

test('authenticator setup, a backup-code sign-in and verified disable work through the browser', async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const session = await (await request.get(`${API_URL}/auth/session`)).json();
  await page.goto('/');
  await page
    .getByRole('button', { name: 'Account security', exact: true })
    .click();
  await page
    .getByRole('button', { name: 'Set up authenticator', exact: true })
    .click();
  let dialog = page.getByRole('dialog');
  await dialog
    .getByLabel('Current password', { exact: true })
    .fill(TEST_PASSWORD);
  await dialog
    .getByRole('button', { name: 'Continue setup', exact: true })
    .click();
  await expect(
    page.getByRole('heading', {
      name: 'Connect your authenticator',
      exact: true,
    }),
  ).toBeVisible();
  const secret = await dialog
    .getByLabel('Authenticator setup key')
    .inputValue();
  await dialog
    .getByLabel('Authenticator code', { exact: true })
    .fill(await enrollmentCode(secret));
  await dialog
    .getByRole('button', { name: 'Enable two-step verification', exact: true })
    .click();
  await expect(
    page.getByRole('heading', {
      name: 'Save your authenticator backup codes',
      exact: true,
    }),
  ).toBeVisible();
  const codes = await dialog
    .locator('[aria-label="Authenticator backup codes"] span')
    .allTextContents();
  expect(codes.length).toBe(10);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    ),
  ).toBe(false);
  const codeGrid = dialog.locator('[aria-label="Authenticator backup codes"]');
  expect(
    await codeGrid.evaluate(
      (element) => element.scrollWidth > element.clientWidth + 1,
    ),
  ).toBe(false);
  await dialog
    .getByRole('button', { name: 'I saved my codes', exact: true })
    .click();
  await expect(page.getByText('Enabled', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Authenticator setup key')).toBeHidden();
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await page.getByLabel('Email', { exact: true }).fill(session.user.email);
  await page.getByLabel('Password', { exact: true }).fill(TEST_PASSWORD);
  await page
    .getByRole('button', { name: 'Sign in to workspace', exact: true })
    .click();
  await expect(
    page.getByRole('heading', { name: 'Verify your sign-in', exact: true }),
  ).toBeVisible();
  await page.getByRole('combobox', { name: 'Verification method' }).click();
  await page
    .getByRole('option', { name: 'Authenticator backup code', exact: true })
    .click();
  await page.locator('#auth-factor').fill(codes[0]);
  await page
    .getByRole('button', { name: 'Verify and sign in', exact: true })
    .click();
  await page
    .getByRole('button', { name: 'Account security', exact: true })
    .click();
  await expect(
    page.getByText('9 unused authenticator backup codes.', { exact: false }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Turn off', exact: true }).click();
  dialog = page.getByRole('dialog');
  await dialog
    .getByLabel('Current password', { exact: true })
    .fill('Wrong-Password-Test-2026!');
  await dialog.getByRole('combobox', { name: 'Verification method' }).click();
  await page
    .getByRole('option', { name: 'Authenticator backup code', exact: true })
    .click();
  await dialog.locator('#security-factor').fill(codes[1]);
  await dialog
    .getByRole('button', { name: 'Confirm change', exact: true })
    .click();
  await expect(dialog.getByRole('alert')).toBeVisible();
  await dialog
    .getByLabel('Current password', { exact: true })
    .fill(TEST_PASSWORD);
  await dialog
    .getByRole('button', { name: 'Confirm change', exact: true })
    .click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText('Not enabled', { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test('password change refreshes the browser session and offline recovery resets the password once', async ({
  page,
  request,
  playwright,
}) => {
  const session = await (await request.get(`${API_URL}/auth/session`)).json();
  const changedPassword = 'Changed-Password-Test-Only-2026!';
  const recoveredPassword = 'Recovered-Password-Test-Only-2026!';
  await page.goto('/#security');
  await page
    .getByRole('button', { name: 'Generate recovery code', exact: true })
    .click();
  let dialog = page.getByRole('dialog');
  await dialog
    .getByLabel('Current password', { exact: true })
    .fill(TEST_PASSWORD);
  await dialog
    .getByRole('button', { name: 'Confirm change', exact: true })
    .click();
  await expect(
    page.getByRole('heading', {
      name: 'Save your account recovery code',
      exact: true,
    }),
  ).toBeVisible();
  const recoveryCode = await dialog
    .getByLabel('Account recovery code', { exact: true })
    .inputValue();
  expect(recoveryCode.length).toBe(43);
  await dialog
    .getByRole('button', { name: 'I saved my codes', exact: true })
    .click();
  await expect(
    page.getByLabel('Account recovery code', { exact: true }),
  ).toBeHidden();
  await page.reload();
  await expect(
    page.getByText('Recovery code saved', { exact: true }),
  ).toBeVisible();
  const otherSession = await playwright.request.newContext({
    extraHTTPHeaders: { origin: 'http://127.0.0.1:5174' },
  });
  const signedInElsewhere = await otherSession.post(`${API_URL}/auth/login`, {
    data: { email: session.user.email, password: TEST_PASSWORD },
  });
  expect(signedInElsewhere.status()).toBe(200);
  await page
    .getByRole('button', { name: 'Change password', exact: true })
    .click();
  dialog = page.getByRole('dialog');
  await dialog
    .getByLabel('Current password', { exact: true })
    .fill(TEST_PASSWORD);
  await dialog
    .getByLabel('New password', { exact: true })
    .fill(changedPassword);
  await dialog
    .getByLabel('Confirm new password', { exact: true })
    .fill(changedPassword);
  await dialog
    .getByRole('button', { name: 'Confirm change', exact: true })
    .click();
  await expect(dialog).toBeHidden();
  await expect(
    page.getByRole('heading', { name: 'Account security', exact: true }),
  ).toBeVisible();
  const currentSessionResponse = await request.get(`${API_URL}/auth/session`);
  expect(currentSessionResponse.status()).toBe(200);
  expect((await currentSessionResponse.json()).csrf_token).not.toBe(
    session.csrf_token,
  );
  expect((await otherSession.get(`${API_URL}/auth/session`)).status()).toBe(
    401,
  );
  await otherSession.dispose();
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await page
    .getByRole('button', { name: 'Forgot password?', exact: true })
    .click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByLabel('Email', { exact: true }).fill(session.user.email);
  await page
    .getByLabel('Account recovery code', { exact: true })
    .fill(recoveryCode);
  await page
    .getByLabel('New password', { exact: true })
    .fill(recoveredPassword);
  await page
    .getByLabel('Confirm new password', { exact: true })
    .fill(recoveredPassword);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    ),
  ).toBe(false);
  await page
    .getByRole('button', { name: 'Reset password', exact: true })
    .click();
  await expect(
    page.getByRole('heading', { name: 'Password reset', exact: true }),
  ).toBeVisible();
  await page
    .getByRole('button', { name: 'Back to sign in', exact: true })
    .click();
  await page.getByLabel('Password', { exact: true }).fill(recoveredPassword);
  await page
    .getByRole('button', { name: 'Sign in to workspace', exact: true })
    .click();
  await page.goto('/#security');
  await expect(
    page.getByText('No recovery code', { exact: true }),
  ).toBeVisible();
  await expect(page.getByText('Not enabled', { exact: true })).toBeVisible();
  // Once-only behavior is observed through the same public endpoint the form uses.
  const reused = await request.post(`${API_URL}/auth/recover`, {
    data: {
      email: session.user.email,
      recovery_key: recoveryCode,
      new_password: changedPassword,
    },
    headers: { origin: 'http://127.0.0.1:5174' },
  });
  expect(reused.status()).toBe(401);
  expect((await reused.json()).code).toBe('invalid_recovery');
});
