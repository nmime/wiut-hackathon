import { readFile } from 'node:fs/promises';
import { expect, test, type Page } from '@playwright/test';
import { AssessmentSchema } from '../libs/common/api-contracts/src/index';
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
  if (!(await button.isVisible()))
    await page
      .getByRole('button', { name: 'Toggle sidebar', exact: true })
      .click();
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

test('an officer imports synthetic history, assesses, records a decision, and reopens the persisted review', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const input = importInput('Browser flow');
  await page.goto('/');
  await page
    .getByRole('button', { name: 'Import business', exact: true })
    .click();
  const dialog = page.getByRole('dialog', {
    name: 'Import synthetic business',
  });
  await dialog.getByLabel('Business name').fill(input.name);
  await dialog.getByLabel('Sector', { exact: true }).fill(input.sector);
  await dialog.getByLabel('Location', { exact: true }).fill(input.location);
  await dialog
    .getByLabel('Transaction JSON')
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
  await page.getByLabel('Reviewer name').fill('Browser Officer');
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
    page.getByText('Browser Officer', { exact: true }),
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
  expect(exported.decision?.reviewer_name).toBe('Browser Officer');
  expect(exported.decision?.decision).toBe('needs_information');
  expect(exported.result?.model_version).toBe('test-only-fixture-v1');

  await page.reload();
  await openBusiness(page, input.name);
  await expect(
    page.getByText('Browser Officer', { exact: true }),
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
        reviewer_name: 'Historical Officer',
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
    page.getByText('Historical Officer', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Record decision', exact: true }),
  ).toBeHidden();
  await page.reload();
  await expect(
    page.getByRole('heading', { name: business.name, exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText('Historical Officer', { exact: true }),
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
  expect(exported.decision?.reviewer_name).toBe('Historical Officer');
});

test('invalid imports stay editable and show a useful validation error', async ({
  page,
}) => {
  await page.goto('/');
  await page
    .getByRole('button', { name: 'Import business', exact: true })
    .click();
  const dialog = page.getByRole('dialog', {
    name: 'Import synthetic business',
  });
  await dialog
    .getByLabel('Business name')
    .fill('Synthetic Invalid Browser Case');
  await dialog.getByLabel('Sector', { exact: true }).fill('Retail');
  await dialog.getByLabel('Location', { exact: true }).fill('Tashkent');
  await dialog.getByLabel('Transaction JSON').fill('{invalid json');
  await dialog
    .getByRole('button', { name: 'Import business', exact: true })
    .click();
  await expect(
    dialog.getByText('Import could not be completed', { exact: true }),
  ).toBeVisible();
  await expect(
    dialog.getByText(
      'Transaction JSON is invalid. Paste a JSON array of transactions.',
      { exact: true },
    ),
  ).toBeVisible();
  await expect(dialog.getByLabel('Transaction JSON')).toHaveValue(
    '{invalid json',
  );
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(dialog).toBeHidden();
});

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
