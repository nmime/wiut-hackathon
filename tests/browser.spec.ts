import { readFile } from 'node:fs/promises';
import { type Page } from '@playwright/test';
import { expect, test } from './auth-fixtures';
import {
  AssessmentSchema,
  BusinessDetailSchema,
  BusinessImportSchema,
  BusinessListSchema,
} from '../libs/common/api-contracts/src/index';
import { importFormat, openImport } from './ui-helpers';
import {
  AS_OF_DATE,
  API_URL,
  NO_ML_API_URL,
  fixtureMode,
  importBusiness,
  importInput,
} from './helpers';

async function navigate(page: Page, label: string) {
  const button = page.getByRole('button', { name: new RegExp(`^${label}`) });
  const toggle = page.getByRole('button', {
    name: 'Toggle sidebar',
    exact: true,
  });
  await expect(toggle).toBeVisible();
  const inViewport =
    (await button.isVisible()) &&
    (await button.evaluate((element) => {
      const bounds = element.getBoundingClientRect();
      return (
        bounds.width > 0 && bounds.right > 0 && bounds.left < window.innerWidth
      );
    }));
  if (!inViewport) await toggle.click();
  await button.click();
  const sidebarClose = page.getByRole('button', { name: 'Close', exact: true });
  if (await sidebarClose.isVisible()) await sidebarClose.click();
}

async function openBusiness(page: Page, name: string) {
  await navigate(page, 'Businesses');
  await page.getByLabel('Find a business').fill(name);
  await page.getByRole('button', { name, exact: true }).click();
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
}

test('a fresh workspace displays an empty product without a sandbox or preloaded cases', async ({
  page,
  request,
}) => {
  await page.goto('/');
  await expect(
    page.getByRole('button', { name: 'Import first business', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(
      /synthetic sandbox|synthetic data only|synthetic transaction history/i,
    ),
  ).toHaveCount(0);
  expect(
    BusinessListSchema.parse(
      await (await request.get(`${API_URL}/businesses`)).json(),
    ).items,
  ).toEqual([]);
  await page.screenshot({
    path: test.info().outputPath('empty-workspace-desktop.png'),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    ),
  ).toBe(false);
  await page.screenshot({
    path: test.info().outputPath('empty-workspace-mobile.png'),
    fullPage: true,
  });
});

test('CSV currency imports preserve actual test amounts through reload and reimportable JSON and CSV exports', async ({
  page,
}) => {
  const input = importInput('CSV round trip');
  const csv = [
    'ts,direction,channel,amount',
    ...input.transactions.map(
      (transaction) =>
        `"${transaction.ts}",${transaction.direction},${transaction.channel},${transaction.amount}`,
    ),
  ].join('\n');
  await page.goto('/');
  const dialog = await openImport(page);
  await importFormat(page, dialog, 'CSV');
  await dialog.getByLabel('Business name').fill(input.name);
  await dialog.getByLabel('Sector', { exact: true }).fill(input.sector);
  await dialog.getByLabel('Location', { exact: true }).fill(input.location);
  await dialog.getByLabel('Upload transaction file').setInputFiles({
    name: 'test-only-transactions.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(csv),
  });
  await expect(dialog.getByLabel('Transaction data')).toHaveValue(csv);
  const responseEvent = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/businesses' &&
      response.request().method() === 'POST',
  );
  await dialog
    .getByRole('button', { name: 'Import business', exact: true })
    .click();
  const response = await responseEvent;
  expect(response.status()).toBe(201);
  const business = BusinessDetailSchema.parse(await response.json());
  expect(business.amount_unit).toBe('UZS');
  expect(business.data_source).toBe('user_provided');
  expect(
    business.transactions.map((transaction) => transaction.amount_index),
  ).toEqual(input.transactions.map((transaction) => transaction.amount));
  await expect(
    page.getByRole('heading', { name: input.name, exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/^12,750,000\s*UZS$/).first()).toBeVisible();
  await expect(
    page.getByText(
      /synthetic sandbox|synthetic data only|synthetic transaction history/i,
    ),
  ).toHaveCount(0);
  await page.reload();
  await expect(
    page.getByRole('heading', { name: input.name, exact: true }),
  ).toBeVisible();
  const jsonEvent = page.waitForEvent('download');
  await page
    .getByRole('button', { name: 'Download business JSON', exact: true })
    .click();
  const jsonDownload = await jsonEvent;
  const jsonPath = test.info().outputPath('currency-business.json');
  await jsonDownload.saveAs(jsonPath);
  const exported = BusinessImportSchema.parse(
    JSON.parse(await readFile(jsonPath, 'utf8')),
  );
  expect(exported).toEqual(input);
  await navigate(page, 'Businesses');
  const repeatedDialog = await openImport(page);
  await importFormat(page, repeatedDialog, 'JSON');
  await repeatedDialog.getByLabel('Upload transaction file').setInputFiles({
    name: 'test-only-business.json',
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify(exported)),
  });
  await expect(repeatedDialog.getByLabel('Business name')).toHaveValue(
    input.name,
  );
  await expect(
    repeatedDialog.getByLabel('Sector', { exact: true }),
  ).toHaveValue(input.sector);
  await expect(
    repeatedDialog.getByLabel('Location', { exact: true }),
  ).toHaveValue(input.location);
  const repeatedEvent = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/businesses' &&
      response.request().method() === 'POST',
  );
  await repeatedDialog
    .getByRole('button', { name: 'Import business', exact: true })
    .click();
  const repeated = await repeatedEvent;
  expect(repeated.status()).toBe(201);
  const reimported = BusinessDetailSchema.parse(await repeated.json());
  expect(reimported.id).not.toBe(business.id);
  expect(reimported.transactions).toEqual(business.transactions);
  await page.getByRole('tab', { name: 'Transactions', exact: true }).click();
  const csvEvent = page.waitForEvent('download');
  await page
    .getByRole('button', { name: 'Download transactions', exact: true })
    .click();
  const csvDownload = await csvEvent;
  const csvPath = test.info().outputPath('currency-transactions.csv');
  await csvDownload.saveAs(csvPath);
  const lines = (await readFile(csvPath, 'utf8')).trim().split(/\r?\n/);
  expect(lines[0]).toBe('ts,direction,channel,amount');
  expect(lines.slice(1).map((line) => Number(line.split(',')[3]))).toEqual(
    input.transactions.map((transaction) => transaction.amount),
  );
  await expect(
    page.getByRole('table', { name: 'Transaction history' }),
  ).toContainText('10,000,000');
  await page.screenshot({
    path: test.info().outputPath('currency-transactions-desktop.png'),
    fullPage: true,
  });
});

test('an officer imports UZS history, assesses, records a decision, and reopens the persisted review', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const input = importInput('Browser flow');
  await page.goto('/');
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
  await expect(dialog).toBeHidden();
  await expect(
    page.getByRole('heading', { name: input.name, exact: true }),
  ).toBeVisible();
  await page.getByLabel('Assessment date').fill(AS_OF_DATE);
  await page.getByLabel('Requested amount (UZS, optional)').fill('500');
  await page
    .getByRole('button', { name: 'Run assessment', exact: true })
    .click();
  await expect(
    page.getByText(/Model test-only-fixture-v1/).first(),
  ).toBeVisible();
  await expect(
    page.getByText('TEST FIXTURE ONLY', { exact: true }),
  ).toBeVisible();
  await page
    .getByRole('button', { name: 'Technical model details', exact: true })
    .click();
  const modelDetails = page.getByRole('dialog', {
    name: 'Technical model details',
  });
  await expect(
    modelDetails.getByText('TEST_FIXTURE_ONLY', { exact: true }),
  ).toBeVisible();
  await modelDetails
    .getByRole('button', { name: 'Close', exact: true })
    .click();
  await expect(
    page.getByRole('progressbar', { name: 'Capacity score 72 out of 100' }),
  ).toBeVisible();
  await expect(
    page.getByText('Officer decision', { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath('assessment-desktop.png'),
    fullPage: true,
  });

  await page.getByLabel('Decision', { exact: true }).click();
  await page
    .getByRole('option', { name: 'Needs more information', exact: true })
    .click();
  await page
    .getByLabel('Review notes')
    .fill(
      'Verify the updated synthetic operating expense history before approval.',
    );
  await page
    .getByRole('button', { name: 'Record decision', exact: true })
    .click();
  const confirmation = page.getByRole('dialog', {
    name: 'Record this decision?',
  });
  await expect(confirmation).toBeVisible();
  await confirmation
    .getByRole('button', { name: 'Confirm decision', exact: true })
    .click();
  await expect(confirmation).toBeHidden();
  await expect(
    page
      .getByRole('main')
      .getByText('Integration Officer', { exact: true })
      .first(),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Record decision', exact: true }),
  ).toBeHidden();

  const downloadEvent = page.waitForEvent('download');
  await page
    .getByRole('button', { name: 'Export assessment', exact: true })
    .click();
  const download = await downloadEvent;
  const downloadedPath = test.info().outputPath('assessment-export.json');
  await download.saveAs(downloadedPath);
  const exported = AssessmentSchema.parse(
    JSON.parse(await readFile(downloadedPath, 'utf8')),
  );
  expect(exported.decision?.reviewer_name).toBe('Integration Officer');
  expect(exported.decision?.decision).toBe('needs_information');
  expect(exported.result?.model_version).toBe('test-only-fixture-v1');
  expect(exported.amount_unit).toBe('UZS');

  await page.reload();
  await openBusiness(page, input.name);
  await expect(
    page
      .getByRole('main')
      .getByText('Integration Officer', { exact: true })
      .first(),
  ).toBeVisible();
  await expect(
    page.getByText(
      'Verify the updated synthetic operating expense history before approval.',
      { exact: true },
    ),
  ).toBeVisible();
  await navigate(page, 'Review history');
  await expect(
    page.getByRole('button', { name: input.name, exact: true }),
  ).toBeVisible();
  await navigate(page, 'Audit trail');
  await expect(
    page.getByText('Decision recorded', { exact: true }).first(),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test('opening an older reviewed assessment preserves its identity through reload and export', async ({
  page,
  request,
}) => {
  const business = await importBusiness(request, 'Historical review identity');
  const olderResponse = await request.post(`${API_URL}/assessments`, {
    data: {
      business_id: business.id,
      as_of_date: AS_OF_DATE,
      requested_amount: 100,
    },
  });
  expect(olderResponse.status()).toBe(201);
  const older = AssessmentSchema.parse(await olderResponse.json());
  const review = await request.post(
    `${API_URL}/assessments/${older.id}/decisions`,
    {
      data: {
        decision: 'needs_information',
        reviewer_name: 'Integration Officer',
        notes: 'This older assessment has a distinct preserved human review.',
      },
    },
  );
  expect(review.status()).toBe(201);
  const newerResponse = await request.post(`${API_URL}/assessments`, {
    data: {
      business_id: business.id,
      as_of_date: AS_OF_DATE,
      requested_amount: 200,
    },
  });
  expect(newerResponse.status()).toBe(201);
  const newer = AssessmentSchema.parse(await newerResponse.json());
  expect(newer.id).not.toBe(older.id);

  await page.goto('/');
  await navigate(page, 'Review history');
  const historicalRow = page
    .getByRole('row')
    .filter({ has: page.locator(`[title="${older.id}"]`) });
  await historicalRow
    .getByRole('button', { name: business.name, exact: true })
    .click();
  await expect(
    page.getByRole('heading', { name: business.name, exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByRole('main')
      .getByText('Integration Officer', { exact: true })
      .first(),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Record decision', exact: true }),
  ).toBeHidden();
  await page.reload();
  await expect(
    page.getByRole('heading', { name: business.name, exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByRole('main')
      .getByText('Integration Officer', { exact: true })
      .first(),
  ).toBeVisible();

  const event = page.waitForEvent('download');
  await page
    .getByRole('button', { name: 'Export assessment', exact: true })
    .click();
  const download = await event;
  const exportedPath = test.info().outputPath('historical-assessment.json');
  await download.saveAs(exportedPath);
  const exported = AssessmentSchema.parse(
    JSON.parse(await readFile(exportedPath, 'utf8')),
  );
  expect(exported.id).toBe(older.id);
  expect(exported.requested_amount).toBe(100);
  expect(exported.decision?.reviewer_name).toBe('Integration Officer');
});

test('invalid JSON, CSV headers, and amounts stay editable without creating a business', async ({
  page,
  request,
}) => {
  await page.goto('/');
  const dialog = await openImport(page);
  await importFormat(page, dialog, 'JSON');
  await dialog
    .getByLabel('Business name')
    .fill('Test-only invalid browser case');
  await dialog.getByLabel('Sector', { exact: true }).fill('Retail');
  await dialog.getByLabel('Location', { exact: true }).fill('Tashkent');
  await dialog.getByLabel('Transaction data').fill('{invalid json');
  await dialog
    .getByRole('button', { name: 'Import business', exact: true })
    .click();
  await expect(
    dialog.getByText('Import could not be completed', { exact: true }),
  ).toBeVisible();
  await expect(dialog.getByLabel('Transaction data')).toHaveValue(
    '{invalid json',
  );
  const input = importInput('Invalid currency amount');
  await dialog
    .getByLabel('Transaction data')
    .fill(JSON.stringify([{ ...input.transactions[0], amount: -10 }]));
  await dialog
    .getByRole('button', { name: 'Import business', exact: true })
    .click();
  await expect(
    dialog.getByText('Import could not be completed', { exact: true }),
  ).toBeVisible();
  await importFormat(page, dialog, 'CSV');
  for (const csv of [
    'ts,direction,channel,amount_index\n2025-01-15T10:00:00Z,in,card,100',
    'ts,direction,channel,amount\n2025-01-15T10:00:00Z,in,card,not-a-number',
  ]) {
    await dialog.getByLabel('Transaction data').fill(csv);
    await dialog
      .getByRole('button', { name: 'Import business', exact: true })
      .click();
    await expect(
      dialog.getByText('Import could not be completed', { exact: true }),
    ).toBeVisible();
    await expect(dialog.getByLabel('Transaction data')).toHaveValue(csv);
  }
  expect(
    BusinessListSchema.parse(
      await (await request.get(`${API_URL}/businesses`)).json(),
    ).items,
  ).toEqual([]);
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(dialog).toBeHidden();
});

test.describe('unconfigured ML browser', () => {
  test.use({ authApiUrl: NO_ML_API_URL });
  test('before ML integration the interface shows the actual connection state and no score', async ({
    page,
    request,
  }) => {
    const business = await importBusiness(
      request,
      'Awaiting teammate ML',
      NO_ML_API_URL,
    );
    await page.route('**/api/**', async (route) => {
      const original = new URL(route.request().url());
      const response = await route.fetch({
        url: `${NO_ML_API_URL.replace(/\/api$/, '')}${original.pathname}${original.search}`,
      });
      await route.fulfill({ response });
    });
    await page.goto('/');
    await expect(
      page.getByText('ML service is awaiting connection', { exact: true }),
    ).toBeVisible();
    await openBusiness(page, business.name);
    await expect(
      page.getByText('test-only-fixture-v1', { exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole('button', { name: 'Record decision', exact: true }),
    ).toBeHidden();
    await page.screenshot({
      path: test.info().outputPath('ml-awaiting-connection.png'),
      fullPage: true,
    });
  });
});

test('a failed ML attempt is visible without displaying an invented recommendation', async ({
  page,
  request,
}) => {
  const business = await importBusiness(request, 'Offline browser');
  await fixtureMode(request, business.id, 'unavailable');
  await page.goto('/');
  await openBusiness(page, business.name);
  await page.getByLabel('Assessment date').fill(AS_OF_DATE);
  await page
    .getByRole('button', { name: 'Run assessment', exact: true })
    .click();
  await expect(
    page.getByText('Assessment could not be completed', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText('test-only-fixture-v1', { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole('button', { name: 'Record decision', exact: true }),
  ).toBeHidden();
  await page.getByRole('tab', { name: /^Assessments/ }).click();
  await expect(
    page.getByText('Analysis failed', { exact: true }).first(),
  ).toBeVisible();
  await page.reload();
  await openBusiness(page, business.name);
  await page.getByRole('tab', { name: /^Assessments/ }).click();
  await expect(
    page.getByText('Analysis failed', { exact: true }).first(),
  ).toBeVisible();
});

test('mobile portfolio and assessment workspace fit the viewport', async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const business = await importBusiness(request, 'Mobile browser');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await openBusiness(page, business.name);
  await page.getByLabel('Assessment date').fill(AS_OF_DATE);
  await page
    .getByRole('button', { name: 'Run assessment', exact: true })
    .click();
  await expect(
    page.getByText(/Model test-only-fixture-v1/).first(),
  ).toBeVisible();
  const horizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1,
  );
  expect(horizontalOverflow).toBe(false);
  await page.screenshot({
    path: test.info().outputPath('assessment-mobile.png'),
    fullPage: true,
  });
  await page.getByRole('tab', { name: 'Transactions', exact: true }).click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    ),
  ).toBe(false);
  await page.screenshot({
    path: test.info().outputPath('transactions-mobile.png'),
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
