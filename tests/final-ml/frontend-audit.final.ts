import { readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import {
  AssessmentSchema,
  AuthSessionSchema,
  BusinessListSchema,
  ShowcaseGenerationSchema,
} from '../../libs/common/api-contracts/src/index';
import { expect, test } from '../auth-fixtures';
import { amountLabel } from '../../apps/frontend/app/src/lib/format';
import { FINAL_API_URL } from './helpers';

test.use({
  authApiUrl: FINAL_API_URL,
  video: { mode: 'on', size: { width: 1280, height: 900 } },
});

test('desktop and mobile routes plus a declared showcase use the actual final model', async ({
  page,
  request,
  browser,
}) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const bank = AuthSessionSchema.parse(
    await (await request.get(`${FINAL_API_URL}/auth/session`)).json(),
  );
  expect(
    BusinessListSchema.parse(
      await (await request.get(`${FINAL_API_URL}/businesses`)).json(),
    ).items,
  ).toEqual([]);

  const anonymous = await browser.newContext();
  try {
    const auth = await anonymous.newPage();
    for (const width of [1440, 390]) {
      await auth.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      await auth.goto('http://127.0.0.1:5178');
      await expect(
        auth.getByRole('tab', { name: 'Sign in', exact: true }),
      ).toBeVisible();
      expect(
        await auth.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await auth
        .getByRole('tab', { name: 'Create account', exact: true })
        .click();
      await expect(
        auth.getByLabel('Workspace name', { exact: true }),
      ).toBeVisible();
      expect(
        await auth.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await auth.screenshot({
        path: test.info().outputPath(`auth-${width}.png`),
      });
    }
  } finally {
    await anonymous.close();
  }

  const routes = [
    ['overview', 'A clearer view of business cash flow.'],
    ['businesses', 'Businesses'],
    ['reviews', 'Review history'],
    ['audit', 'Audit trail'],
    ['team', 'Team & access'],
    ['security', 'Account security'],
    ['showcase', 'Showcase lab'],
    ['invite', 'Join a workspace'],
  ];
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    for (const [route, title] of routes) {
      await page.goto(`/#${route}`);
      await expect(
        page.getByRole('heading', { name: title, exact: true }),
      ).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        `${route} at ${width}px`,
      ).toBe(true);
      await page.screenshot({
        path: test.info().outputPath(`route-${route}-${width}.png`),
      });
    }
  }

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/#showcase');
  await page.reload();
  await expect(
    page.getByRole('heading', { name: 'Showcase lab', exact: true }),
  ).toBeVisible();
  await page
    .getByLabel('Showcase workspace name')
    .fill('FlowCredit submission showcase');
  const createEvent = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/auth/showcase-tenants' &&
      response.request().method() === 'POST',
  );
  await page
    .getByRole('button', { name: 'Create showcase workspace', exact: true })
    .click();
  const createResponse = await createEvent;
  expect(createResponse.status(), await createResponse.text()).toBe(201);
  const created = AuthSessionSchema.parse(await createResponse.json());
  expect(created.tenant.kind).toBe('showcase');
  await expect(page.getByTestId('showcase-disclosure')).toBeVisible();
  await page.getByLabel('Last complete month').fill('2026-09');
  await page.getByLabel('History length (months)').fill('36');
  await page.getByLabel('Reproducible seed').fill('20261011');
  const generationEvent = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/showcase/generate' &&
      response.request().method() === 'POST',
  );
  await page
    .getByRole('button', { name: 'Generate showcase cases', exact: true })
    .click();
  const batch = ShowcaseGenerationSchema.parse(
    await (await generationEvent).json(),
  );
  expect(batch.items).toHaveLength(6);
  const business = batch.items.find(
    (item) => item.showcase_provenance?.scenario === 'stable',
  )!;
  expect(business.data_source).toBe('synthetic');
  await page.screenshot({
    path: test.info().outputPath('actual-showcase-lab-desktop.png'),
    fullPage: true,
  });
  const seasonal = batch.items.find(
    (item) => item.showcase_provenance?.scenario === 'seasonal',
  )!;
  await page
    .getByRole('button', {
      name: `Open showcase case ${seasonal.name}`,
      exact: true,
    })
    .click();
  const seasonalAssessmentEvent = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/assessments' &&
      response.request().method() === 'POST',
  );
  await page
    .getByRole('button', { name: 'Run assessment', exact: true })
    .click();
  const seasonalAssessment = AssessmentSchema.parse(
    await (await seasonalAssessmentEvent).json(),
  );
  expect(seasonalAssessment.status).toBe('completed');
  expect(seasonalAssessment.result?.loan_terms?.annual_rate).toBe(0.24);
  await writeFile(
    test.info().outputPath('actual-seasonal-accounting-check.json'),
    JSON.stringify(
      { generation: batch, assessment: seasonalAssessment },
      null,
      2,
    ),
  );
  await page.goto('/#showcase');
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
  await expect(
    page.getByText(
      /current real-data scorer records this amount as context only/,
    ),
  ).toHaveCount(0);
  const assessmentEvent = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/assessments' &&
      response.request().method() === 'POST',
  );
  await page
    .getByRole('button', { name: 'Run assessment', exact: true })
    .click();
  const assessment = AssessmentSchema.parse(
    await (await assessmentEvent).json(),
  );
  expect(assessment.status).toBe('completed');
  const result = assessment.result!;
  expect(result.flags).toContain('final_combined_model');
  expect(result.loan_terms?.annual_rate).toBe(0.24);
  expect(result.recommended_loan.suggested_principal_index).toBeGreaterThan(0);
  await expect(
    page.getByText('Annual interest 24%', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText('Real-data revenue model', { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/^Synthetic net forecast/)).toHaveCount(0);
  await expect(
    page.getByText('Fixed annuity comparison', { exact: true }),
  ).toBeVisible();
  const events = (
    await readFile(
      resolve(
        __dirname,
        '../../hybrid-runtime/runtime/final-integration-audit.jsonl',
      ),
      'utf8',
    )
  )
    .trim()
    .split('\n')
    .map((line) => JSON.parse(line));
  const financial = events.find(
    (event) =>
      event.event === 'assessment_completed' &&
      event.request_id === result.request_id,
  ).financial_evidence.assessment;
  const paymentChart = page
    .locator('[data-chart]')
    .filter({ hasText: 'Fixed annuity comparison' });
  await paymentChart.locator('.recharts-bar-rectangle').first().hover();
  await expect(
    page.getByText(
      `Fixed annuity comparison: ${amountLabel(financial.comparison.annuity_rows[0].payment, 'UZS')}`,
      { exact: true },
    ),
  ).toBeVisible();
  await page.mouse.move(0, 0);
  for (const value of [
    result.loan_terms!.total_interest_index,
    result.loan_terms!.total_repayment_index,
  ]) {
    await expect(
      page.getByText(amountLabel(value, 'UZS'), { exact: true }),
    ).toBeVisible();
  }
  const recommendation = page.getByRole('heading', {
    name: `Payment capacity · ${business.name}`,
    exact: true,
  });
  await expect(
    page.getByText('Assessment completed', { exact: true }),
  ).toHaveCount(0);
  await recommendation.scrollIntoViewIfNeeded();
  await page.evaluate(() => {
    const heading = [...document.querySelectorAll('h2')].find((node) =>
      node.textContent?.startsWith('Payment capacity ·'),
    );
    if (heading)
      window.scrollTo(0, heading.getBoundingClientRect().top + scrollY - 60);
  });
  await page.screenshot({
    path: test.info().outputPath('actual-final-showcase-desktop.png'),
  });
  await page.screenshot({
    path: test.info().outputPath('actual-final-showcase-desktop-full.png'),
    fullPage: true,
  });
  for (const width of [640, 768, 1024]) {
    await page.setViewportSize({ width, height: 1000 });
    await recommendation.scrollIntoViewIfNeeded();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      `Assessment with full UZS amounts fits at ${width}px`,
    ).toBe(true);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await recommendation.scrollIntoViewIfNeeded();
  await recommendation.evaluate((heading) =>
    window.scrollTo(0, heading.getBoundingClientRect().top + scrollY - 20),
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: test.info().outputPath('actual-final-showcase-mobile.png'),
  });
  await page.screenshot({
    path: test.info().outputPath('actual-final-showcase-mobile-full.png'),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page
    .getByLabel('Review notes')
    .fill(
      'Practice review on explicitly generated showcase inputs; no real lending decision or accuracy claim.',
    );
  await page
    .getByRole('button', { name: 'Record decision', exact: true })
    .click();
  const decisionEvent = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname ===
        `/api/assessments/${assessment.id}/decisions` &&
      response.request().method() === 'POST',
  );
  await page
    .getByRole('dialog', { name: 'Record this decision?' })
    .getByRole('button', { name: 'Confirm decision', exact: true })
    .click();
  expect((await decisionEvent).status()).toBe(201);
  await page.goto('/#reviews');
  await expect(
    page.getByRole('heading', { name: 'Review history', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(business.name, { exact: true }).first(),
  ).toBeVisible();
  await page.goto('/#audit');
  await expect(
    page.getByRole('heading', { name: 'Audit trail', exact: true }),
  ).toBeVisible();
  await page.goto('/#showcase');
  await page
    .getByRole('button', { name: 'Open bank workspace', exact: true })
    .click();
  await expect(page.getByTestId('showcase-disclosure')).toHaveCount(0);
  await expect(
    page.getByRole('button', { name: 'Import first business', exact: true }),
  ).toBeVisible();
  const current = AuthSessionSchema.parse(
    await (await page.request.get(`${FINAL_API_URL}/auth/session`)).json(),
  );
  expect(current.tenant.id).toBe(bank.tenant.id);
  expect(
    BusinessListSchema.parse(
      await (await page.request.get(`${FINAL_API_URL}/businesses`)).json(),
    ).items,
  ).toEqual([]);
  expect(errors).toEqual([]);
});
