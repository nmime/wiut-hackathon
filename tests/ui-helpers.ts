import { expect, type Locator, type Page } from '@playwright/test';

export async function openImport(page: Page) {
  await page
    .getByRole('button', { name: /^Import (?:first )?business$/ })
    .first()
    .click();
  const dialog = page.getByRole('dialog', {
    name: 'Import business',
    exact: true,
  });
  await expect(dialog).toBeVisible();
  return dialog;
}

export async function importFormat(
  page: Page,
  dialog: Locator,
  format: 'CSV' | 'JSON',
) {
  await dialog.getByLabel('Import format', { exact: true }).click();
  await page.getByRole('option', { name: format, exact: true }).click();
}
