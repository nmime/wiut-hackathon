import { readFile } from 'node:fs/promises';
import {
  AssessmentSchema,
  AuthSessionSchema,
  BusinessListSchema,
  ShowcaseGenerationSchema,
} from '../libs/common/api-contracts/src/index';
import { expect, test } from './auth-fixtures';
import { API_URL } from './helpers';
import { importFormat, openImport } from './ui-helpers';

test('in-site showcase creation, generation, marked exports, scoring, review, and bank return work', async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const bank = AuthSessionSchema.parse(
    await (await request.get(`${API_URL}/auth/session`)).json(),
  );
  await page.goto('/#showcase');
  await expect(
    page.getByRole('heading', { name: 'Showcase lab', exact: true }),
  ).toBeVisible();
  await page
    .getByLabel('Showcase workspace name')
    .fill('Browser-only showcase');
  await page
    .getByRole('button', { name: 'Create showcase workspace', exact: true })
    .click();
  await expect(page.getByTestId('showcase-disclosure')).toBeVisible();
  await expect(page.getByLabel('Number of cases')).toBeVisible();
  await page.getByLabel('Last complete month').fill('2026-09');
  const generationEvent = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/showcase/generate' &&
      response.request().method() === 'POST',
  );
  await page
    .getByRole('button', { name: 'Generate showcase cases', exact: true })
    .click();
  const generatedResponse = await generationEvent;
  expect(generatedResponse.status()).toBe(201);
  const batch = ShowcaseGenerationSchema.parse(await generatedResponse.json());
  expect(batch.items).toHaveLength(6);
  const business = batch.items.find(
    (item) => item.showcase_provenance?.scenario === 'stable',
  )!;
  await expect(
    page.getByRole('table', { name: 'Showcase cases', exact: true }),
  ).toBeVisible();
  const csvEvent = page.waitForEvent('download');
  await page
    .getByRole('button', {
      name: `Export synthetic CSV for ${business.name}`,
      exact: true,
    })
    .click();
  const csv = await csvEvent;
  expect(csv.suggestedFilename()).toContain('showcase-synthetic');
  const csvPath = test.info().outputPath('showcase-synthetic.csv');
  await csv.saveAs(csvPath);
  const csvText = await readFile(csvPath, 'utf8');
  expect(csvText).toContain('data_source,amount_unit,generator_version');
  expect(csvText).toContain('synthetic,UZS,showcase-v1');
  const jsonEvent = page.waitForEvent('download');
  await page
    .getByRole('button', { name: 'Export last batch JSON', exact: true })
    .click();
  const json = await jsonEvent;
  const jsonPath = test.info().outputPath('showcase-batch.json');
  await json.saveAs(jsonPath);
  expect(JSON.parse(await readFile(jsonPath, 'utf8'))).toMatchObject({
    workspace_kind: 'showcase',
    data_source: 'synthetic',
    amount_unit: 'UZS',
  });
  await page.screenshot({
    path: test.info().outputPath('showcase-desktop.png'),
    fullPage: true,
  });
  await page
    .getByRole('button', {
      name: `Open showcase case ${business.name}`,
      exact: true,
    })
    .click();
  await expect(
    page.getByRole('heading', { name: business.name, exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel('Assessment date')).toHaveValue('2026-09-30');
  const assessmentEvent = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/assessments' &&
      response.request().method() === 'POST',
  );
  await page
    .getByRole('button', { name: 'Run assessment', exact: true })
    .click();
  const assessmentResponse = await assessmentEvent;
  expect(assessmentResponse.status()).toBe(201);
  const assessment = AssessmentSchema.parse(await assessmentResponse.json());
  expect(assessment.status).toBe('completed');
  await page.getByLabel('Decision', { exact: true }).click();
  await page
    .getByRole('option', { name: 'Needs more information', exact: true })
    .click();
  await page
    .getByLabel('Review notes')
    .fill('Showcase-only browser review of explicitly generated inputs.');
  await page
    .getByRole('button', { name: 'Record decision', exact: true })
    .click();
  await page
    .getByRole('dialog', { name: 'Record this decision?' })
    .getByRole('button', { name: 'Confirm decision', exact: true })
    .click();
  await expect(
    page.getByRole('button', { name: 'Record decision', exact: true }),
  ).toBeHidden();
  const resultEvent = page.waitForEvent('download');
  await page
    .getByRole('button', { name: 'Export assessment', exact: true })
    .click();
  const result = await resultEvent;
  const resultPath = test.info().outputPath('showcase-assessment.json');
  await result.saveAs(resultPath);
  const resultJson = JSON.parse(await readFile(resultPath, 'utf8'));
  expect(JSON.stringify(resultJson)).toContain('synthetic');
  expect(JSON.stringify(resultJson)).toContain('showcase-v1');
  await page.goto('/#showcase');
  await page.reload();
  await expect(
    page.getByRole('table', { name: 'Showcase cases', exact: true }),
  ).toBeVisible();
  await expect(page.getByTestId('showcase-disclosure')).toBeVisible();
  await page
    .getByRole('button', { name: 'Open bank workspace', exact: true })
    .click();
  await expect(page.getByTestId('showcase-disclosure')).toHaveCount(0);
  await expect(
    page.getByRole('button', {
      name: 'Import first business',
      exact: true,
    }),
  ).toBeVisible();
  const current = AuthSessionSchema.parse(
    await (await request.get(`${API_URL}/auth/session`)).json(),
  );
  expect(current.tenant.id).toBe(bank.tenant.id);
  expect(
    BusinessListSchema.parse(
      await (await request.get(`${API_URL}/businesses`)).json(),
    ).items,
  ).toEqual([]);
  expect(
    (await request.get(`${API_URL}/assessments/${assessment.id}`)).status(),
  ).toBe(404);
  const importDialog = await openImport(page);
  await importFormat(page, importDialog, 'CSV');
  await importDialog
    .getByLabel('Business name')
    .fill('Must reject generated export');
  await importDialog.getByLabel('Sector', { exact: true }).fill('Test retail');
  await importDialog
    .getByLabel('Location', { exact: true })
    .fill('Test district');
  await importDialog.getByLabel('Upload transaction file').setInputFiles({
    name: csv.suggestedFilename(),
    mimeType: 'text/csv',
    buffer: Buffer.from(csvText),
  });
  await importDialog
    .getByRole('button', { name: 'Import business', exact: true })
    .click();
  await expect(
    importDialog.getByText(/generated showcase data/i),
  ).toBeVisible();
  expect(
    BusinessListSchema.parse(
      await (await request.get(`${API_URL}/businesses`)).json(),
    ).items,
  ).toEqual([]);
  expect(errors).toEqual([]);
});

test('showcase creation and generated cases fit a mobile viewport', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/#showcase');
  await expect(
    page.getByRole('heading', { name: 'Showcase lab', exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByLabel('Showcase workspace name').fill('Mobile test-only lab');
  await page
    .getByRole('button', { name: 'Create showcase workspace', exact: true })
    .click();
  await expect(page.getByLabel('Number of cases')).toBeVisible();
  await page.getByLabel('Number of cases').fill('1');
  await page.getByLabel('Last complete month').fill('2026-09');
  await page
    .getByRole('button', { name: 'Generate showcase cases', exact: true })
    .click();
  await expect(
    page.getByRole('table', { name: 'Showcase cases', exact: true }),
  ).toBeVisible();
  for (const id of [
    'showcase-scenario',
    'showcase-count',
    'showcase-months',
    'showcase-end-month',
    'showcase-revenue',
    'showcase-seed',
    'showcase-return',
  ]) {
    const bounds = await page.locator(`#${id}`).boundingBox();
    expect(bounds, `${id} must be visible`).not.toBeNull();
    expect(bounds!.x, id).toBeGreaterThanOrEqual(0);
    expect(
      bounds!.x + bounds!.width,
      `${id} must fit without clipping`,
    ).toBeLessThanOrEqual(390);
  }
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: test.info().outputPath('showcase-mobile.png'),
    fullPage: true,
  });
});
