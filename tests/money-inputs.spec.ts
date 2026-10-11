import type { Locator, Page } from '@playwright/test';
import { expect, test } from './auth-fixtures';
import { importBusiness } from './helpers';

async function paste(page: Page, input: Locator, text: string) {
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.evaluate((value) => navigator.clipboard.writeText(value), text);
  await input.focus();
  await input.press('ControlOrMeta+V');
}

test('requested UZS amounts group while editing and submit the exact numeric value or optional null', async ({
  page,
  request,
}) => {
  const business = await importBusiness(request, 'Grouped monetary input');
  await page.goto(`/#business/${business.id}`);
  const amount = page.getByLabel('Requested amount (UZS, optional)');
  await expect(amount).toBeVisible();
  await page.getByRole('tab', { name: 'Transactions', exact: true }).click();
  const search = page.getByLabel('Filter transactions');
  for (const groupedAmount of ['10,000,000', '10 000 000']) {
    await search.fill(groupedAmount);
    const table = page.getByRole('table', { name: 'Transaction history' });
    await expect(table.getByRole('row')).toHaveCount(2);
    await expect(table).toContainText('10,000,000 UZS');
  }
  await amount.fill('12500000');
  await expect(amount).toHaveValue('12,500,000');
  await amount.evaluate((input: HTMLInputElement) =>
    input.setSelectionRange(2, 2),
  );
  await amount.pressSequentially('9');
  await expect(amount).toHaveValue('129,500,000');
  expect(
    await amount.evaluate((input: HTMLInputElement) => input.selectionStart),
  ).toBe(3);
  await amount.press('Backspace');
  await expect(amount).toHaveValue('12,500,000');
  expect(
    await amount.evaluate((input: HTMLInputElement) => input.selectionStart),
  ).toBe(2);
  await amount.evaluate((input: HTMLInputElement) =>
    input.setSelectionRange(2, 2),
  );
  await amount.press('Delete');
  await expect(amount).toHaveValue('1,200,000');
  await amount.fill('12500000');
  await amount.evaluate((input: HTMLInputElement) =>
    input.setSelectionRange(3, 3),
  );
  await amount.press('Backspace');
  await expect(amount).toHaveValue('1,500,000');
  await amount.fill('');
  await paste(page, amount, '12 500 000.50');
  await expect(amount).toHaveValue('12,500,000.50');
  await amount.evaluate((input: HTMLInputElement) =>
    input.setSelectionRange(2, 2),
  );
  await amount.pressSequentially('x');
  await expect(amount).toHaveValue('12,500,000.50');
  expect(
    await amount.evaluate((input: HTMLInputElement) => input.selectionStart),
  ).toBe(2);
  await amount.pressSequentially('.');
  await expect(amount).toHaveValue('12,500,000.50');
  expect(
    await amount.evaluate((input: HTMLInputElement) => input.selectionStart),
  ).toBe(2);
  await amount.evaluate((input: HTMLInputElement) =>
    input.setSelectionRange(10, 10),
  );
  await amount.pressSequentially('.');
  await expect(amount).toHaveValue('12,500,000.50');
  expect(
    await amount.evaluate((input: HTMLInputElement) => input.selectionStart),
  ).toBe(10);
  await amount.evaluate((input: HTMLInputElement) =>
    input.setSelectionRange(3, 6),
  );
  await amount.pressSequentially('x');
  await expect(amount).toHaveValue('12,500,000.50');
  expect(
    await amount.evaluate((input: HTMLInputElement) => [
      input.selectionStart,
      input.selectionEnd,
    ]),
  ).toEqual([3, 6]);
  await amount.press('End');
  await amount.pressSequentially('1');
  await expect(amount).toHaveValue('12,500,000.50');
  await amount.press('ControlOrMeta+A');
  await paste(page, amount, '12,34');
  await expect(amount).toHaveValue('12,500,000.50');
  await expect(
    page.getByText(
      'Use commas or spaces for thousands and a dot for decimals.',
    ),
  ).toBeVisible();

  const submitted = page.waitForRequest(
    (value) =>
      value.url().endsWith('/api/assessments') && value.method() === 'POST',
  );
  const completed = page.waitForResponse(
    (value) =>
      value.url().endsWith('/api/assessments') &&
      value.request().method() === 'POST',
  );
  await page
    .getByRole('button', { name: 'Run assessment', exact: true })
    .click();
  expect((await submitted).postDataJSON().requested_amount).toBe(12_500_000.5);
  expect((await completed).status()).toBe(201);

  await amount.fill('');
  const emptySubmitted = page.waitForRequest(
    (value) =>
      value.url().endsWith('/api/assessments') && value.method() === 'POST',
  );
  await page
    .getByRole('button', { name: 'Run assessment', exact: true })
    .click();
  expect((await emptySubmitted).postDataJSON().requested_amount).toBeNull();
});

test('showcase revenue displays full grouped UZS, accepts comma paste, and preserves its generation scale', async ({
  page,
}) => {
  await page.goto('/#showcase');
  await page
    .getByRole('button', { name: 'Create showcase workspace', exact: true })
    .click();
  const revenue = page.getByLabel('Base monthly revenue (UZS)');
  await expect(revenue).toHaveValue('30,000,000');
  await expect(page.getByText(/30,000,000 = 30 million/)).toBeVisible();
  await revenue.fill('');
  await paste(page, revenue, '42,000,000.25');
  await expect(revenue).toHaveValue('42,000,000.25');
  await page.getByLabel('Number of cases').fill('1');
  const generated = page.waitForResponse(
    (value) =>
      value.url().endsWith('/api/showcase/generate') &&
      value.request().method() === 'POST',
  );
  await page
    .getByRole('button', { name: 'Generate showcase cases', exact: true })
    .click();
  const response = await generated;
  expect(response.status()).toBe(201);
  expect(response.request().postDataJSON().monthly_revenue_uzs).toBe(
    42_000_000.25,
  );
  expect(
    (await response.json()).items[0].showcase_provenance.monthly_revenue_uzs,
  ).toBe(42_000_000.25);
  await expect(revenue).toHaveValue('42,000,000.25');
});
