import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { expect, test } from '@playwright/test';
import {
  AssessmentListSchema,
  AssessmentSchema,
  AuditListSchema,
  HealthSchema,
  ScoreResponseSchema,
} from '../../libs/common/api-contracts/src/index';
import {
  REAL_API_URL,
  REAL_AS_OF_DATE,
  REAL_ML_URL,
  assessRealBusiness,
  importRealBusiness,
} from './helpers';

test('the trained synthetic ML service produces input-sensitive validated outputs through NestJS and preserves a human review', async ({
  request,
}) => {
  const health = HealthSchema.parse(
    await (await request.get(`${REAL_API_URL}/health`)).json(),
  );
  expect(health.ml_configured).toBe(true);
  const positive = await importRealBusiness(request, 'positive');
  const negative = await importRealBusiness(request, 'negative');
  const stronger = await assessRealBusiness(request, positive.id);
  const weaker = await assessRealBusiness(request, negative.id);
  const strong = ScoreResponseSchema.parse(stronger.result);
  const weak = ScoreResponseSchema.parse(weaker.result);
  expect(strong.business_id).toBe(positive.id);
  expect(weak.business_id).toBe(negative.id);
  expect(strong.as_of_date).toBe(REAL_AS_OF_DATE);
  expect(strong.capacity_score).toBeGreaterThan(weak.capacity_score);
  expect(strong.cashflow_summary.net_monthly_surplus_index).toBeGreaterThan(0);
  expect(weak.cashflow_summary.net_monthly_surplus_index).toBeLessThan(0);
  expect(strong.recommended_loan.suggested_principal_index).toBeGreaterThan(0);
  expect(strong.adaptive_schedule).toHaveLength(
    strong.recommended_loan.suggested_term_months,
  );
  expect(weak.recommended_loan.suggested_principal_index).toBe(0);
  expect(weak.adaptive_schedule).toEqual([]);
  expect(strong.model_version).toBe(weak.model_version);
  expect(strong.request_id).not.toBe(weak.request_id);

  const direct = await request.post(`${REAL_ML_URL}/score`, {
    data: {
      business_id: positive.id,
      as_of_date: REAL_AS_OF_DATE,
      currency: 'UZS',
      requested_amount: null,
      transactions: positive.transactions,
    },
  });
  expect(direct.status()).toBe(200);
  const directResult = ScoreResponseSchema.parse(await direct.json());
  expect(directResult.capacity_score).toBe(strong.capacity_score);
  expect(directResult.recommended_loan).toEqual(strong.recommended_loan);

  const response = await request.post(
    `${REAL_API_URL}/assessments/${stronger.id}/decisions`,
    {
      data: {
        decision: 'needs_information',
        reviewer_name: 'Synthetic ML Officer',
        notes:
          'Synthetic model transport verified; request updated expense evidence before approval.',
      },
    },
  );
  expect(response.status()).toBe(201);
  const reviewed = AssessmentSchema.parse(await response.json());
  expect(reviewed.decision?.reviewer_name).toBe('Synthetic ML Officer');
  const history = AssessmentListSchema.parse(
    await (
      await request.get(`${REAL_API_URL}/assessments`, {
        params: { business_id: positive.id },
      })
    ).json(),
  );
  expect(history.items[0]?.decision).toEqual(reviewed.decision);
  const audit = AuditListSchema.parse(
    await (
      await request.get(`${REAL_API_URL}/audit`, {
        params: { business_id: positive.id },
      })
    ).json(),
  );
  expect(
    audit.items.filter((event) => event.event_type === 'assessment_completed'),
  ).toHaveLength(1);
  expect(
    audit.items.filter((event) => event.event_type === 'decision_recorded'),
  ).toHaveLength(1);
  expect(JSON.stringify(audit.items)).toContain(stronger.input_hash);
  expect(JSON.stringify(audit.items)).toContain(strong.model_version);
  expect(JSON.stringify(audit.items)).toContain(strong.request_id);
  const mlAudit = (
    await readFile(
      resolve(
        __dirname,
        '../../ml-service/runtime/real-integration-audit.jsonl',
      ),
      'utf8',
    )
  )
    .trim()
    .split('\n')
    .map((row) => JSON.parse(row) as Record<string, unknown>);
  const mlCompletion = mlAudit.find(
    (event) =>
      event.request_id === strong.request_id &&
      event.event === 'assessment_completed',
  );
  expect(mlCompletion?.model_version).toBe(strong.model_version);
  expect(mlCompletion?.input_hash).toMatch(/^[a-f0-9]{64}$/);
  // JSON transport treats signed zero identically across Python and Nest.
  expect(JSON.parse(JSON.stringify(mlCompletion?.result))).toEqual(
    JSON.parse(JSON.stringify(strong)),
  );
});

test('rescaling amount indices preserves capacity and scales the actual model forecast and repayment', async ({
  request,
}) => {
  const scale = 0.0001;
  const originalBusiness = await importRealBusiness(request, 'positive');
  const scaledBusiness = await importRealBusiness(request, 'positive', scale);
  const original = ScoreResponseSchema.parse(
    (await assessRealBusiness(request, originalBusiness.id)).result,
  );
  const scaled = ScoreResponseSchema.parse(
    (await assessRealBusiness(request, scaledBusiness.id)).result,
  );
  expect(scaled.capacity_score).toBeCloseTo(original.capacity_score, 8);
  expect(scaled.confidence).toBeCloseTo(original.confidence, 8);
  expect(scaled.recommended_loan.suggested_principal_index / scale).toBeCloseTo(
    original.recommended_loan.suggested_principal_index,
    6,
  );
  expect(
    scaled.recommended_loan.max_affordable_installment_index / scale,
  ).toBeCloseTo(original.recommended_loan.max_affordable_installment_index, 6);
  for (let month = 0; month < 12; month++) {
    expect(
      scaled.seasonality.monthly_forecast_index[month]! / scale,
    ).toBeCloseTo(original.seasonality.monthly_forecast_index[month]!, 6);
    expect(
      scaled.adaptive_schedule[month]!.installment_index / scale,
    ).toBeCloseTo(original.adaptive_schedule[month]!.installment_index, 6);
  }
});

test('the browser renders a real model response and adaptive schedule and records a human decision', async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const business = await importRealBusiness(request, 'positive');
  await page.goto('/');
  await page.getByRole('button', { name: 'Businesses', exact: true }).click();
  await page.getByLabel('Find a business').fill(business.name);
  await page.getByRole('button', { name: business.name, exact: true }).click();
  await page.getByLabel('Assessment date').fill(REAL_AS_OF_DATE);
  const responseEvent = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/assessments' &&
      response.request().method() === 'POST',
  );
  await page
    .getByRole('button', { name: 'Run assessment', exact: true })
    .click();
  const response = await responseEvent;
  expect(response.status()).toBe(201);
  const assessment = AssessmentSchema.parse(await response.json());
  const result = ScoreResponseSchema.parse(assessment.result);
  expect(result.model_version).not.toBe('test-only-fixture-v1');
  await expect(
    page.getByRole('progressbar', {
      name: `Capacity score ${result.capacity_score} out of 100`,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole('heading', { name: 'Model cash-flow summary', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText('Adaptive repayment schedule', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText('TEST FIXTURE ONLY', { exact: true }),
  ).toHaveCount(0);
  await page.getByLabel('Reviewer name').fill('Real Integration Officer');
  await page
    .getByLabel('Review notes')
    .fill(
      'This synthetic case was reviewed against its actual local model result.',
    );
  await page
    .getByRole('button', { name: 'Record decision', exact: true })
    .click();
  const confirmation = page.getByRole('dialog', {
    name: 'Record this decision?',
  });
  await confirmation
    .getByRole('button', { name: 'Confirm decision', exact: true })
    .click();
  await expect(
    page.getByText('Real Integration Officer', { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByText('Real Integration Officer', { exact: true }),
  ).toBeVisible();
  const event = page.waitForEvent('download');
  await page
    .getByRole('button', { name: 'Export assessment', exact: true })
    .click();
  const download = await event;
  const path = test.info().outputPath('real-model-assessment.json');
  await download.saveAs(path);
  const exported = AssessmentSchema.parse(
    JSON.parse(await readFile(path, 'utf8')),
  );
  expect(exported.id).toBe(assessment.id);
  expect(exported.result).toEqual(result);
  expect(exported.decision?.reviewer_name).toBe('Real Integration Officer');
  await page.screenshot({
    path: test.info().outputPath('real-model-desktop.png'),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    ),
  ).toBe(false);
  await page.screenshot({
    path: test.info().outputPath('real-model-mobile.png'),
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
