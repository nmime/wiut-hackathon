import { randomUUID } from 'node:crypto';
import { test, expect, TEST_PASSWORD } from './auth-fixtures';
import { importInput } from './helpers';
import { importFormat, openImport } from './ui-helpers';

test.use({ authenticate: false });

test('account registration, invitations, workspace switching, logout, and login work in the browser', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const email = `browser-owner-${randomUUID()}@example.test`;
  const firstName = `Browser bank ${randomUUID().slice(0, 8)}`;
  const secondName = `Second bank ${randomUUID().slice(0, 8)}`;
  await page.goto('/');
  await page.getByRole('tab', { name: 'Create account', exact: true }).click();
  await page
    .getByLabel('Full name', { exact: true })
    .fill('Browser Auth Admin');
  await page.getByLabel('Workspace name', { exact: true }).fill(firstName);
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page.getByLabel('Password', { exact: true }).fill(TEST_PASSWORD);
  await page
    .getByRole('button', { name: 'Create account and workspace', exact: true })
    .click();
  await expect(
    page.getByRole('combobox', { name: 'Switch workspace' }),
  ).toContainText(firstName);

  const input = importInput('Browser private workspace');
  const dialog = await openImport(page);
  await importFormat(page, dialog, 'JSON');
  await dialog.getByLabel('Business name').fill(input.name);
  await dialog.getByLabel('Sector', { exact: true }).fill(input.sector);
  await dialog.getByLabel('Location', { exact: true }).fill(input.location);
  await dialog
    .getByLabel('Transaction data')
    .fill(JSON.stringify(input.transactions));
  await dialog
    .getByRole('button', { name: 'Import business', exact: true })
    .click();
  await expect(
    page.getByRole('heading', { name: input.name, exact: true }),
  ).toBeVisible();
  await page
    .getByRole('button', { name: 'Team & access', exact: true })
    .click();
  const inviteEmail = `browser-invite-${randomUUID()}@example.test`;
  await page.getByLabel('Teammate email').fill(inviteEmail);
  await page
    .getByRole('button', { name: 'Create invitation', exact: true })
    .click();
  const link = page.getByLabel('Invitation link');
  await expect(link).toBeVisible();
  const invitationUrl = await link.inputValue();
  expect(new URL(invitationUrl).origin).toBe('http://127.0.0.1:5174');
  expect(new URL(invitationUrl).hash).toMatch(
    /^#invite\?token=[A-Za-z0-9_-]{43}$/,
  );
  await page.getByRole('button', { name: 'Done', exact: true }).click();
  await expect(page.getByText(inviteEmail, { exact: true })).toBeVisible();

  await page
    .getByRole('button', { name: 'Create workspace', exact: true })
    .click();
  const create = page.getByRole('dialog');
  await create.getByLabel('Workspace name', { exact: true }).fill(secondName);
  await create
    .getByRole('button', { name: 'Create new workspace', exact: true })
    .click();
  await expect(
    page.getByRole('combobox', { name: 'Switch workspace' }),
  ).toContainText(secondName);
  await expect(
    page.getByRole('heading', { name: input.name, exact: true }),
  ).toBeHidden();
  await page.getByRole('button', { name: 'Businesses', exact: true }).click();
  await page.getByLabel('Find a business').fill(input.name);
  await expect(
    page.getByRole('button', { name: input.name, exact: true }),
  ).toBeHidden();
  await page.getByRole('combobox', { name: 'Switch workspace' }).click();
  await page.getByRole('option', { name: new RegExp(firstName) }).click();
  await expect(
    page.getByRole('combobox', { name: 'Switch workspace' }),
  ).toContainText(firstName);
  await page.getByRole('button', { name: 'Businesses', exact: true }).click();
  await page.getByLabel('Find a business').fill(input.name);
  await expect(
    page.getByRole('button', { name: input.name, exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(
    page.getByRole('button', { name: 'Sign in to workspace', exact: true }),
  ).toBeVisible();
  await page.reload();
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page.getByLabel('Password', { exact: true }).fill(TEST_PASSWORD);
  await page
    .getByRole('button', { name: 'Sign in to workspace', exact: true })
    .click();
  await expect(
    page.getByRole('combobox', { name: 'Switch workspace' }),
  ).toContainText(firstName);
  expect(errors).toEqual([]);
});

test('an invited officer joins through the public link and mobile authentication fits the viewport', async ({
  page,
  playwright,
}) => {
  const { registerAccount, TEST_ORIGIN } = await import('./auth-fixtures');
  const { API_URL } = await import('./helpers');
  const owner = await registerAccount(playwright, API_URL, {
    tenantName: 'Invited browser bank',
  });
  const email = `browser-officer-${randomUUID()}@example.test`;
  try {
    const response = await owner.request.post(`${API_URL}/invitations`, {
      data: { email, role: 'officer' },
      headers: { origin: TEST_ORIGIN },
    });
    expect(response.status()).toBe(201);
    const invite = await response.json();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(invite.invitation_url);
    await expect(
      page.getByRole('button', {
        name: 'Create account and join team',
        exact: true,
      }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth > window.innerWidth + 1,
      ),
    ).toBe(false);
    await page
      .getByLabel('Full name', { exact: true })
      .fill('Browser Invited Officer');
    await page.getByLabel('Email', { exact: true }).fill(email);
    await page.getByLabel('Password', { exact: true }).fill(TEST_PASSWORD);
    await page
      .getByRole('button', {
        name: 'Create account and join team',
        exact: true,
      })
      .click();
    await page
      .getByRole('button', { name: 'Toggle sidebar', exact: true })
      .click();
    await expect(
      page.getByRole('combobox', { name: 'Switch workspace' }),
    ).toContainText('Invited browser bank');
    await expect(
      page.getByRole('button', { name: 'Team & access', exact: true }),
    ).toBeHidden();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth > window.innerWidth + 1,
      ),
    ).toBe(false);
  } finally {
    await owner.request.dispose();
  }
});

test.describe('a workspace changed outside this tab', () => {
  test.use({ authenticate: true });
  test('a stale tab refreshes its session before displaying the newly selected tenant', async ({
    page,
    request,
  }) => {
    const { API_URL, importBusiness } = await import('./helpers');
    const business = await importBusiness(
      request,
      'Stale tab private evidence',
    );
    await page.goto('/');
    await expect(
      page.getByRole('button', { name: 'Businesses', exact: true }),
    ).toBeVisible();
    const secondName = `Externally switched ${randomUUID().slice(0, 8)}`;
    const changed = await request.post(`${API_URL}/tenants`, {
      data: { name: secondName },
    });
    expect(changed.status()).toBe(201);
    const staleResponse = page.waitForResponse(
      (response) =>
        response.status() === 409 &&
        new URL(response.url()).pathname === `/api/businesses/${business.id}`,
    );
    await page.getByRole('button', { name: 'Businesses', exact: true }).click();
    await page.getByLabel('Find a business').fill(business.name);
    await page
      .getByRole('button', { name: business.name, exact: true })
      .click();
    expect((await staleResponse).status()).toBe(409);
    await expect(
      page.getByRole('combobox', { name: 'Switch workspace' }),
    ).toContainText(secondName);
    await page.getByRole('button', { name: 'Businesses', exact: true }).click();
    await page.getByLabel('Find a business').fill(business.name);
    await expect(
      page.getByRole('button', { name: business.name, exact: true }),
    ).toBeHidden();
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await expect(
      page.getByRole('button', { name: 'Sign in to workspace', exact: true }),
    ).toBeVisible();
  });
});
