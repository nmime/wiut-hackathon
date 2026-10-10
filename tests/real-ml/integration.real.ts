import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { expect, registerAccount, test } from '../auth-fixtures';
import {
  AssessmentListSchema,
  AssessmentSchema,
  AuditListSchema,
  BusinessDetailSchema,
  HealthSchema,
  ScoreResponseSchema,
} from '../../libs/common/api-contracts/src/index';
import {
  REAL_API_URL,
  REAL_AS_OF_DATE,
  REAL_ML_URL,
  assessRealBusiness,
  importRealBusiness,
  realBusinessInput,
} from './helpers';

test.use({ authApiUrl: REAL_API_URL });

test('the real-data model serves validated outputs through NestJS and preserves a human review', async ({
  request,
}) => {
  const health = HealthSchema.parse(
    await (await request.get(`${REAL_API_URL}/health`)).json(),
  );
  expect(health.ml_configured).toBe(true);
  const modelHealth = await (await request.get(`${REAL_ML_URL}/health`)).json();
  expect(modelHealth.synthetic_training_only).toBe(false);
  expect(modelHealth.model_artifact_sha256).toMatch(/^[a-f0-9]{64}$/);
  expect(modelHealth.public_transfer_weight).toBeGreaterThanOrEqual(0.5);
  expect(modelHealth.public_training_targets).toBeGreaterThan(41364);
  expect(modelHealth.real_revenue_estimator_used).toBe(true);
  expect(
    modelHealth.public_training_sources.map(
      (source: { provider?: string }) => source.provider,
    ),
  ).toEqual(expect.arrayContaining(['abs', 'statcan', 'eurostat']));
  expect(
    modelHealth.public_training_sources.map(
      (source: { provider?: string }) => source.provider,
    ),
  ).not.toContain('ons');
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
  expect(strong.model_version).toBe(modelHealth.model_version);
  expect(strong.forecast_provenance).toBeTruthy();
  expect(
    strong.forecast_provenance!.real_revenue_weight,
  ).toBeGreaterThanOrEqual(0.5);
  expect(strong.forecast_provenance?.real_training_targets).toBe(
    modelHealth.public_training_targets,
  );
  expect(strong.forecast_provenance?.revenue_candidate).toBe(
    modelHealth.real_revenue_candidate,
  );
  expect(
    strong.forecast_provenance!.real_revenue_weight +
      strong.forecast_provenance!.synthetic_net_weight,
  ).toBeCloseTo(1, 10);
  expect(strong.flags).toContain('public_revenue_transfer_used');
  expect(strong.flags).not.toContain('public_revenue_transfer_not_selected');
  expect(strong.flags).toContain(
    modelHealth.expense_mode.startsWith('observed_cost_')
      ? 'observed_cost_projection'
      : 'synthetic_expense_model',
  );
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
  expect(directResult.seasonality).toEqual(strong.seasonality);
  expect(directResult.adaptive_schedule).toEqual(strong.adaptive_schedule);
  expect(directResult.flags).toEqual(strong.flags);
  expect(directResult.forecast_provenance).toEqual(strong.forecast_provenance);

  const response = await request.post(
    `${REAL_API_URL}/assessments/${stronger.id}/decisions`,
    {
      data: {
        decision: 'needs_information',
        reviewer_name: 'Integration Officer',
        notes:
          'Real-trained model transport verified on synthetic input; request updated expense evidence before approval.',
      },
    },
  );
  expect(response.status()).toBe(201);
  const reviewed = AssessmentSchema.parse(await response.json());
  expect(reviewed.decision?.reviewer_name).toBe('Integration Officer');
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
  expect(mlCompletion?.model_artifact_sha256).toBe(
    modelHealth.model_artifact_sha256,
  );
  expect(mlCompletion?.input_hash).toMatch(/^[a-f0-9]{64}$/);
  // JSON transport treats signed zero identically across Python and Nest.
  expect(JSON.parse(JSON.stringify(mlCompletion?.result))).toEqual(
    JSON.parse(JSON.stringify(strong)),
  );
});

test('real-scored assessments and human decisions remain isolated between bank tenants', async ({
  request,
  playwright,
}) => {
  const business = await importRealBusiness(request, 'positive');
  const assessment = await assessRealBusiness(request, business.id);
  const other = await registerAccount(playwright, REAL_API_URL);
  try {
    for (const path of [
      `/businesses/${business.id}`,
      `/assessments/${assessment.id}`,
      `/assessments?business_id=${business.id}`,
      `/audit?business_id=${business.id}`,
    ]) {
      expect((await other.request.get(`${REAL_API_URL}${path}`)).status()).toBe(
        404,
      );
    }
    const decision = await other.request.post(
      `${REAL_API_URL}/assessments/${assessment.id}/decisions`,
      { data: { decision: 'approved', notes: 'Cross-tenant attempt' } },
    );
    expect(decision.status()).toBe(404);
    const preserved = AssessmentSchema.parse(
      await (
        await request.get(`${REAL_API_URL}/assessments/${assessment.id}`)
      ).json(),
    );
    expect(preserved.result).toEqual(assessment.result);
    expect(preserved.decision).toBeNull();
  } finally {
    await other.request.dispose();
  }
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

test('the trained model preserves cold, dormant and partial-history evidence gates through NestJS', async ({
  request,
}) => {
  const cases = [
    {
      name: 'cold history',
      asOf: REAL_AS_OF_DATE,
      keep: (timestamp: string) => timestamp >= '2026-07-01',
      flags: ['short_history', 'cold_start_no_loan'],
      maximumConfidence: 0.25,
      expectedRealWeight: 0.25,
    },
    {
      name: 'stale history',
      asOf: REAL_AS_OF_DATE,
      keep: (timestamp: string) => timestamp < '2026-06-01',
      flags: ['stale_history_no_loan', 'missing_activity_months'],
      maximumConfidence: 0.25,
      expectedRealWeight: 0.25,
    },
    {
      name: 'fully dormant history',
      asOf: REAL_AS_OF_DATE,
      keep: (timestamp: string) => timestamp < '2025-10-01',
      flags: ['inactive_history_zero_forecast', 'stale_history_no_loan'],
      maximumConfidence: 0.25,
      expectedRealWeight: null,
    },
    {
      name: 'partial history',
      asOf: '2026-09-15',
      keep: (timestamp: string) =>
        timestamp >= '2026-09-01' && timestamp.slice(0, 10) <= '2026-09-15',
      flags: ['partial_history_only', 'cold_start_no_loan'],
      maximumConfidence: 0.03,
      expectedRealWeight: 0.25,
    },
    {
      name: 'expense-only history',
      asOf: REAL_AS_OF_DATE,
      keep: (_timestamp: string) => true,
      flags: ['zero_revenue_history_guard', 'nonpositive_historical_surplus'],
      maximumConfidence: 0.5,
      expectedRealWeight: 0.65,
      expenseOnly: true,
    },
  ];
  for (const scenario of cases) {
    const input = realBusinessInput('positive');
    input.name = `${scenario.name} ${input.name}`;
    input.transactions = input.transactions.filter(
      (transaction) =>
        scenario.keep(transaction.ts) &&
        (!scenario.expenseOnly || transaction.direction === 'out'),
    );
    const imported = await request.post(`${REAL_API_URL}/businesses`, {
      data: input,
    });
    expect(imported.status()).toBe(201);
    const business = BusinessDetailSchema.parse(await imported.json());
    const scored = await request.post(`${REAL_API_URL}/assessments`, {
      data: { business_id: business.id, as_of_date: scenario.asOf },
    });
    expect(scored.status(), await scored.text()).toBe(201);
    const assessment = AssessmentSchema.parse(await scored.json());
    const result = ScoreResponseSchema.parse(assessment.result);
    expect(result.flags).toEqual(expect.arrayContaining(scenario.flags));
    expect(result.confidence).toBeLessThanOrEqual(scenario.maximumConfidence);
    expect(result.capacity_score).toBe(0);
    expect(result.recommended_loan.suggested_principal_index).toBe(0);
    expect(result.adaptive_schedule).toEqual([]);
    expect(result.seasonality.monthly_forecast_index).toHaveLength(12);
    expect(result.as_of_date).toBe(scenario.asOf);
    if (scenario.expectedRealWeight === null) {
      expect(result.forecast_provenance).toBeNull();
      expect(result.flags).not.toContain('synthetic_net_model_used');
      expect(result.flags).not.toContain('public_revenue_transfer_used');
      expect(result.seasonality.monthly_forecast_index).toEqual(
        Array(12).fill(0),
      );
    } else {
      expect(result.forecast_provenance?.real_revenue_weight).toBe(
        scenario.expectedRealWeight,
      );
      expect(result.forecast_provenance?.synthetic_net_weight).toBe(
        1 - scenario.expectedRealWeight,
      );
    }
    expect(
      result.seasonality.monthly_forecast_index.every(Number.isFinite),
    ).toBe(true);
    const saved = AssessmentSchema.parse(
      await (
        await request.get(`${REAL_API_URL}/assessments/${assessment.id}`)
      ).json(),
    );
    expect(saved.result).toEqual(result);
    expect(saved.input_hash).toMatch(/^[a-f0-9]{64}$/);
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
  expect(result.flags).toContain('public_revenue_transfer_used');
  await expect(
    page.getByText('Forecast evidence', { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/^Public revenue forecast /)).toHaveText(
    `Public revenue forecast ${Number((result.forecast_provenance!.real_revenue_weight * 100).toFixed(2))}%`,
  );
  const capacityProgress = page.getByRole('progressbar', {
    name: /^Capacity score .+ out of 100$/,
  });
  await expect(capacityProgress).toBeVisible();
  await expect(capacityProgress).toHaveAttribute(
    'aria-valuenow',
    String(result.capacity_score),
  );
  await expect(
    page.getByRole('heading', { name: 'Model cash-flow summary', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText('Adaptive repayment schedule', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText('TEST FIXTURE ONLY', { exact: true }),
  ).toHaveCount(0);
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
    page
      .getByRole('main')
      .getByText('Integration Officer', { exact: true })
      .first(),
  ).toBeVisible();
  await page.reload();
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
  const path = test.info().outputPath('real-model-assessment.json');
  await download.saveAs(path);
  const exported = AssessmentSchema.parse(
    JSON.parse(await readFile(path, 'utf8')),
  );
  expect(exported.id).toBe(assessment.id);
  expect(exported.result).toEqual(result);
  expect(exported.decision?.reviewer_name).toBe('Integration Officer');
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
