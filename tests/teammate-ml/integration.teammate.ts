import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { expect, registerAccount, test } from '../auth-fixtures';
import {
  AssessmentListSchema,
  AssessmentSchema,
  AuditListSchema,
  BusinessDetailSchema,
  ProblemSchema,
  ScoreResponseSchema,
} from '../../libs/common/api-contracts/src/index';
import {
  TEAMMATE_API_URL,
  TEAMMATE_AS_OF,
  TEAMMATE_ML_URL,
  assessTeammateBusiness,
  importTeammateBusiness,
  teammateBusinessInput,
} from './helpers';

test.use({ authApiUrl: TEAMMATE_API_URL });

async function candidateAudit() {
  return (
    await readFile(
      resolve(
        __dirname,
        '../../teammate-ml-service/runtime/teammate-integration-audit.jsonl',
      ),
      'utf8',
    )
  )
    .trim()
    .split('\n')
    .map((row) => JSON.parse(row) as Record<string, unknown>);
}

test('the private candidate serves actual UZS forecasts and interest through Nest and persists its original result', async ({
  request,
}) => {
  const healthResponse = await request.get(`${TEAMMATE_ML_URL}/health`);
  expect(healthResponse.status()).toBe(200);
  const health = await healthResponse.json();
  expect(health.model_version).toMatch(/^teammate-v1-m-/);
  expect(health.model_artifact_sha256).toMatch(/^[a-f0-9]{64}$/);
  expect(health.bridge_source_sha256).toMatch(/^[a-f0-9]{64}$/);
  expect(health.source_archive_sha256).toBe(
    'c0a062c8b700fe0824fbcb746db4615d1fab3ad8c7360adf7133e706ea2039db',
  );
  expect(health.model_version).toContain(
    health.model_artifact_sha256.slice(0, 12),
  );
  expect(health.model_version).toContain(
    health.bridge_source_sha256.slice(0, 8),
  );
  const positive = await importTeammateBusiness(request, 'positive');
  const negative = await importTeammateBusiness(request, 'negative');
  const strongAssessment = await assessTeammateBusiness(request, positive.id);
  const weakAssessment = await assessTeammateBusiness(request, negative.id);
  const strong = ScoreResponseSchema.parse(strongAssessment.result);
  const weak = ScoreResponseSchema.parse(weakAssessment.result);
  expect(strong.model_version).toBe(health.model_version);
  expect(strong.model_version).toBe(weak.model_version);
  expect(strong.capacity_score).toBeGreaterThan(weak.capacity_score);
  expect(strong.recommended_loan.suggested_principal_index).toBeGreaterThan(0);
  expect(weak.recommended_loan.suggested_principal_index).toBe(0);
  expect(weak.adaptive_schedule).toEqual([]);
  expect(strong.flags).toEqual(
    expect.arrayContaining([
      'synthetic_training_only',
      'teammate_candidate',
      'category_unavailable',
      'counterparty_unavailable',
      'amount_index_1_to_1_uzs',
      'calendar_components_preserved',
      'human_review_required',
      'annual_rate_24_percent',
    ]),
  );
  expect(strong.flags).not.toContain('zero_interest_mvp');
  expect(strong.flags).not.toContain('public_revenue_transfer_used');
  expect(strong.forecast_provenance?.real_revenue_weight).toBe(0);
  expect(strong.loan_terms?.annual_rate).toBe(0.24);
  expect(strong.loan_terms?.requested_amount_policy).toBe('capacity_checked');
  expect(strong.loan_terms!.total_interest_index).toBeGreaterThan(0);
  const scheduledTotal = strong.adaptive_schedule.reduce(
    (total, row) => total + row.installment_index,
    0,
  );
  expect(strong.loan_terms!.total_repayment_index).toBeCloseTo(
    scheduledTotal,
    2,
  );
  expect(strong.loan_terms!.total_repayment_index).toBeCloseTo(
    strong.recommended_loan.suggested_principal_index +
      strong.loan_terms!.total_interest_index,
    2,
  );
  expect(strong.loan_terms!.total_repayment_index).toBeGreaterThan(
    strong.recommended_loan.suggested_principal_index,
  );
  const directResponse = await request.post(`${TEAMMATE_ML_URL}/score`, {
    data: {
      business_id: positive.id,
      as_of_date: TEAMMATE_AS_OF,
      currency: 'UZS',
      requested_amount: null,
      transactions: positive.transactions,
    },
  });
  expect(directResponse.status(), await directResponse.text()).toBe(200);
  const direct = ScoreResponseSchema.parse(await directResponse.json());
  expect(direct.recommended_loan).toEqual(strong.recommended_loan);
  expect(direct.adaptive_schedule).toEqual(strong.adaptive_schedule);
  expect(direct.loan_terms).toEqual(strong.loan_terms);
  expect(direct.seasonality).toEqual(strong.seasonality);
  expect(direct.capacity_score).toBe(strong.capacity_score);
  const saved = AssessmentSchema.parse(
    await (
      await request.get(
        `${TEAMMATE_API_URL}/assessments/${strongAssessment.id}`,
      )
    ).json(),
  );
  expect(saved.result).toEqual(strong);
  expect(saved.input_hash).toMatch(/^[a-f0-9]{64}$/);
  const nestAudit = AuditListSchema.parse(
    await (
      await request.get(`${TEAMMATE_API_URL}/audit`, {
        params: { business_id: positive.id },
      })
    ).json(),
  );
  expect(JSON.stringify(nestAudit.items)).toContain(strong.model_version);
  expect(JSON.stringify(nestAudit.items)).toContain(strong.request_id);
  expect(JSON.stringify(nestAudit.items)).toContain(saved.input_hash);
  const mlEvents = (await candidateAudit()).filter(
    (entry) => entry.request_id === strong.request_id,
  );
  expect(mlEvents.map((entry) => entry.event)).toEqual([
    'assessment_requested',
    'assessment_completed',
  ]);
  for (const entry of mlEvents) {
    expect(entry.model_artifact_sha256).toBe(health.model_artifact_sha256);
    expect(entry.bridge_source_sha256).toBe(health.bridge_source_sha256);
    expect(entry.source_archive_sha256).toBe(health.source_archive_sha256);
  }
  const completed = mlEvents[1];
  expect(completed?.model_artifact_sha256).toBe(health.model_artifact_sha256);
  expect(completed?.model_version).toBe(strong.model_version);
  expect(completed?.input_hash).toMatch(/^[a-f0-9]{64}$/);
  expect(completed?.result).toEqual(strong);
  expect(completed?.vendor_assessments).toBeInstanceOf(Array);
  expect((completed?.vendor_assessments as unknown[]).length).toBeGreaterThan(
    0,
  );
});

test('requested UZS amounts are genuinely capacity checked rather than silently treated as context', async ({
  request,
}) => {
  const business = await importTeammateBusiness(request, 'positive');
  const baseline = ScoreResponseSchema.parse(
    (await assessTeammateBusiness(request, business.id)).result,
  );
  const requested = baseline.recommended_loan.suggested_principal_index * 0.25;
  expect(requested).toBeGreaterThan(0);
  const smaller = ScoreResponseSchema.parse(
    (await assessTeammateBusiness(request, business.id, requested)).result,
  );
  expect(smaller.recommended_loan.suggested_principal_index).toBeCloseTo(
    requested,
    2,
  );
  expect(smaller.loan_terms?.requested_amount_policy).toBe('capacity_checked');
  const excessive = ScoreResponseSchema.parse(
    (await assessTeammateBusiness(request, business.id, 1e12)).result,
  );
  expect(excessive.flags).toContain('requested_amount_exceeds_main_capacity');
  expect(excessive.recommended_loan.suggested_principal_index).toBeCloseTo(
    baseline.recommended_loan.suggested_principal_index,
    2,
  );
  expect(excessive.recommended_loan.suggested_principal_index).toBeLessThan(
    1e12,
  );
  expect(excessive.loan_terms?.annual_rate).toBe(0.24);
});

test('insufficient history and midmonth cutoffs return actionable errors and persist failed attempts without invented results', async ({
  request,
}) => {
  for (const scenario of [
    {
      name: 'short',
      asOf: TEAMMATE_AS_OF,
      keep: (timestamp: string) => timestamp >= '2025-07-01',
      reason: /at least six|at least 6|six complete|6 complete/i,
    },
    {
      name: 'midmonth',
      asOf: '2025-09-29',
      keep: (_timestamp: string) => true,
      reason: /month.end|last day/i,
    },
  ]) {
    const input = teammateBusinessInput('positive');
    input.name = `${scenario.name} ${input.name}`;
    input.transactions = input.transactions.filter((row) =>
      scenario.keep(row.ts),
    );
    const imported = await request.post(`${TEAMMATE_API_URL}/businesses`, {
      data: input,
    });
    expect(imported.status()).toBe(201);
    const business = BusinessDetailSchema.parse(await imported.json());
    const scored = await request.post(`${TEAMMATE_API_URL}/assessments`, {
      data: { business_id: business.id, as_of_date: scenario.asOf },
    });
    expect(scored.status()).toBe(502);
    const problem = ProblemSchema.parse(await scored.json());
    expect(problem.detail).toMatch(scenario.reason);
    const history = AssessmentListSchema.parse(
      await (
        await request.get(`${TEAMMATE_API_URL}/assessments`, {
          params: { business_id: business.id },
        })
      ).json(),
    );
    expect(history.items).toHaveLength(1);
    const attempt = history.items[0]!;
    expect(attempt.status).toBe('failed');
    expect(attempt.result).toBeNull();
    expect(attempt.error).toMatch(scenario.reason);
    const audit = AuditListSchema.parse(
      await (
        await request.get(`${TEAMMATE_API_URL}/audit`, {
          params: { business_id: business.id },
        })
      ).json(),
    );
    expect(audit.items.map((event) => event.event_type)).toEqual(
      expect.arrayContaining(['assessment_requested', 'assessment_failed']),
    );
    const mlEvents = (await candidateAudit()).filter(
      (entry) => entry.request_id === attempt.request_id,
    );
    expect(mlEvents.map((entry) => entry.event)).toEqual([
      'assessment_requested',
      'assessment_failed',
    ]);
    expect(mlEvents[1]?.status).toBe(422);
    expect(mlEvents[1]?.result).toBeUndefined();
  }
});

test('human candidate decisions are durable and another bank cannot read or modify them', async ({
  request,
  playwright,
}) => {
  const business = await importTeammateBusiness(request, 'positive');
  const assessment = await assessTeammateBusiness(request, business.id);
  const reviewedResponse = await request.post(
    `${TEAMMATE_API_URL}/assessments/${assessment.id}/decisions`,
    {
      data: {
        decision: 'needs_information',
        notes:
          'Candidate trained on synthetic data; request actual expense evidence before accepting terms.',
      },
    },
  );
  expect(reviewedResponse.status()).toBe(201);
  const reviewed = AssessmentSchema.parse(await reviewedResponse.json());
  expect(reviewed.decision?.reviewer_user_id).toBeTruthy();
  expect(reviewed.decision?.reviewer_name).toBe('Integration Officer');
  const duplicate = await request.post(
    `${TEAMMATE_API_URL}/assessments/${assessment.id}/decisions`,
    { data: { decision: 'approved', notes: 'Attempt to overwrite' } },
  );
  expect(duplicate.status()).toBe(409);
  const outsider = await registerAccount(playwright, TEAMMATE_API_URL);
  try {
    for (const path of [
      `/businesses/${business.id}`,
      `/assessments/${assessment.id}`,
      `/assessments?business_id=${business.id}`,
      `/audit?business_id=${business.id}`,
    ]) {
      expect(
        (await outsider.request.get(`${TEAMMATE_API_URL}${path}`)).status(),
      ).toBe(404);
    }
    const unauthorized = await outsider.request.post(
      `${TEAMMATE_API_URL}/assessments/${assessment.id}/decisions`,
      { data: { decision: 'approved', notes: 'Cross-tenant attempt' } },
    );
    expect(unauthorized.status()).toBe(404);
    const saved = AssessmentSchema.parse(
      await (
        await request.get(`${TEAMMATE_API_URL}/assessments/${assessment.id}`)
      ).json(),
    );
    expect(saved.result).toEqual(assessment.result);
    expect(saved.decision).toEqual(reviewed.decision);
    const audit = AuditListSchema.parse(
      await (
        await request.get(`${TEAMMATE_API_URL}/audit`, {
          params: { business_id: business.id },
        })
      ).json(),
    );
    expect(
      audit.items.filter((entry) => entry.event_type === 'decision_recorded'),
    ).toHaveLength(1);
  } finally {
    await outsider.request.dispose();
  }
});

test('the private wrapper exposes no vendor demo or anonymous decision endpoints', async ({
  request,
}) => {
  for (const path of [
    '/',
    '/v1/demo/generate',
    '/v1/audit/verify',
    '/v1/assessments/unknown',
  ]) {
    expect((await request.get(`${TEAMMATE_ML_URL}${path}`)).status()).toBe(404);
  }
  const decision = await request.post(
    `${TEAMMATE_ML_URL}/v1/assessments/unknown/decision`,
    {
      data: { officer_id: 'forged', decision: 'approved' },
    },
  );
  expect(decision.status()).toBe(404);
});

test('offsets crossing a month boundary preserve the supplied calendar components', async ({
  request,
}) => {
  const business = await importTeammateBusiness(request, 'positive');
  const transactions = [
    ...business.transactions,
    {
      ts: '2025-09-30T23:30:00Z',
      direction: 'in' as const,
      channel: 'qr' as const,
      amount_index: 1_000_000,
    },
  ];
  const results = [];
  for (const timestamp of [
    '2025-09-30T23:30:00Z',
    '2025-09-30T23:30:00-03:00',
  ]) {
    const response = await request.post(`${TEAMMATE_ML_URL}/score`, {
      data: {
        business_id: business.id,
        as_of_date: TEAMMATE_AS_OF,
        requested_amount: null,
        currency: 'UZS',
        transactions: [
          ...transactions.slice(0, -1),
          { ...transactions.at(-1), ts: timestamp },
        ],
      },
    });
    expect(response.status(), await response.text()).toBe(200);
    results.push(ScoreResponseSchema.parse(await response.json()));
  }
  expect(results[1]?.cashflow_summary).toEqual(results[0]?.cashflow_summary);
  expect(results[1]?.seasonality).toEqual(results[0]?.seasonality);
  expect(results[1]?.adaptive_schedule).toEqual(results[0]?.adaptive_schedule);
  expect(results[1]?.flags).toContain('calendar_components_preserved');
});

test('the browser shows actual candidate APR, interest, repayment and human review after reload and export', async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const business = await importTeammateBusiness(request, 'positive');
  await page.goto('/');
  await page.getByRole('button', { name: 'Businesses', exact: true }).click();
  await page.getByLabel('Find a business').fill(business.name);
  await page.getByRole('button', { name: business.name, exact: true }).click();
  await page.getByLabel('Assessment date').fill(TEAMMATE_AS_OF);
  const responseEvent = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/assessments' &&
      response.request().method() === 'POST',
  );
  await page
    .getByRole('button', { name: 'Run assessment', exact: true })
    .click();
  const response = await responseEvent;
  expect(response.status(), await response.text()).toBe(201);
  const assessment = AssessmentSchema.parse(await response.json());
  const result = ScoreResponseSchema.parse(assessment.result);
  await expect(
    page.getByText('Annual interest 24%', { exact: true }),
  ).toBeVisible();
  const formatAmount = (value: number) =>
    `${new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(value)} UZS`;
  await expect(
    page
      .getByText('Total interest', { exact: true })
      .locator('..')
      .locator('dd'),
  ).toHaveText(formatAmount(result.loan_terms!.total_interest_index));
  await expect(
    page
      .getByText('Total repayment', { exact: true })
      .locator('..')
      .locator('dd'),
  ).toHaveText(formatAmount(result.loan_terms!.total_repayment_index));
  await expect(
    page.getByRole('progressbar', { name: /^Capacity score .+ out of 100$/ }),
  ).toHaveAttribute('aria-valuenow', String(result.capacity_score));
  await expect(
    page.getByText('Adaptive repayment schedule', { exact: true }),
  ).toBeVisible();
  expect(result.flags).not.toContain('zero_interest_mvp');
  expect(result.forecast_provenance?.real_revenue_weight).toBe(0);
  await expect(
    page.getByText(/real.data accuracy|validated real.borrower accuracy/i),
  ).toHaveCount(0);
  await page
    .getByLabel('Review notes')
    .fill(
      'Actual interest-bearing candidate output reviewed by a human; this input is synthetic test data.',
    );
  await page
    .getByRole('button', { name: 'Record decision', exact: true })
    .click();
  await page
    .getByRole('dialog', { name: 'Record this decision?' })
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
    page.getByText('Annual interest 24%', { exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByRole('main')
      .getByText('Integration Officer', { exact: true })
      .first(),
  ).toBeVisible();
  const downloadEvent = page.waitForEvent('download');
  await page
    .getByRole('button', { name: 'Export assessment', exact: true })
    .click();
  const download = await downloadEvent;
  const exportPath = test.info().outputPath('teammate-assessment.json');
  await download.saveAs(exportPath);
  const exported = AssessmentSchema.parse(
    JSON.parse(await readFile(exportPath, 'utf8')),
  );
  expect(exported.id).toBe(assessment.id);
  expect(exported.amount_unit).toBe('UZS');
  expect(exported.result).toEqual(result);
  expect(exported.decision?.reviewer_name).toBe('Integration Officer');
  await page.screenshot({
    path: test.info().outputPath('teammate-desktop.png'),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    ),
  ).toBe(false);
  await page.screenshot({
    path: test.info().outputPath('teammate-mobile.png'),
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

test('the browser labels the native eight-month-history annuity fallback accurately', async ({
  page,
  request,
}) => {
  const input = teammateBusinessInput('positive');
  input.name = `Annuity ${input.name}`;
  input.transactions = input.transactions.filter(
    (transaction) => transaction.ts >= '2025-02-01',
  );
  const imported = await request.post(`${TEAMMATE_API_URL}/businesses`, {
    data: input,
  });
  expect(imported.status()).toBe(201);
  const business = BusinessDetailSchema.parse(await imported.json());
  await page.goto('/');
  await page.getByRole('button', { name: 'Businesses', exact: true }).click();
  await page.getByLabel('Find a business').fill(business.name);
  await page.getByRole('button', { name: business.name, exact: true }).click();
  await page.getByLabel('Assessment date').fill(TEAMMATE_AS_OF);
  const event = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/assessments' &&
      response.request().method() === 'POST',
  );
  await page
    .getByRole('button', { name: 'Run assessment', exact: true })
    .click();
  const response = await event;
  expect(response.status(), await response.text()).toBe(201);
  const result = ScoreResponseSchema.parse(
    AssessmentSchema.parse(await response.json()).result,
  );
  expect(result.loan_terms?.schedule_type).toBe('annuity');
  expect(result.loan_terms?.annual_rate).toBe(0.24);
  expect(result.flags).toContain('adaptive_schedule_unavailable_annuity_used');
  expect(result.flags).toContain('history_mode_no_seasonality');
  expect(result.recommended_loan.suggested_principal_index).toBeGreaterThan(0);
  expect(result.adaptive_schedule).toHaveLength(12);
  // The shared field retains its existing transport name, while the loan terms
  // declare that the actual native schedule is an interest-bearing annuity.
  const payments = result.adaptive_schedule.map((row) => row.installment_index);
  expect(Math.max(...payments) - Math.min(...payments)).toBeLessThanOrEqual(
    0.02,
  );
  await expect(
    page.getByText('Annual interest 24%', { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/^annuity schedule$/i)).toBeVisible();
  await expect(
    page.getByText('Annuity repayment schedule', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText('Adaptive repayment schedule', { exact: true }),
  ).toHaveCount(0);
  await page.screenshot({
    path: test.info().outputPath('teammate-annuity-desktop.png'),
    fullPage: true,
  });
});
