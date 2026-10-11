import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { expect, registerAccount, test } from '../auth-fixtures';
import {
  AssessmentSchema,
  AuditListSchema,
  ScoreResponseSchema,
} from '../../libs/common/api-contracts/src/index';
import {
  FINAL_API_URL,
  FINAL_AS_OF_DATE,
  FINAL_ML_URL,
  assessFinalBusiness,
  importFinalBusiness,
} from './helpers';

test.use({ authApiUrl: FINAL_API_URL });

async function finalAudit() {
  return (
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
    .map((line) => JSON.parse(line) as Record<string, any>);
}

test('one actual final scorer persists its real-component identity and genuine 24% seasonal loan through Nest', async ({
  request,
}) => {
  const healthResponse = await request.get(`${FINAL_ML_URL}/health`);
  expect(healthResponse.status()).toBe(200);
  const health = await healthResponse.json();
  expect(health.model_version).toMatch(/^final-v1-/);
  expect(health.model_artifact_sha256).toMatch(/^[a-f0-9]{64}$/);
  expect(health.serving_mode).toBe('final_combined_model');
  expect(health.identity_scope).toBe('complete_local_model_assembly');
  expect(health.annual_interest_rate).toBe(0.24);
  expect(health.real_revenue_weight).toBe(1);
  expect(health.synthetic_net_weight).toBe(0);
  expect(health.component_identity.revenue.baseline_sha256).toBe(
    '31693530f17dbd481752d0996b0d4131c65ee0af859346a8f83aea7f17283b96',
  );
  const business = await importFinalBusiness(request, 'stable');
  const assessment = await assessFinalBusiness(request, business.id);
  const result = ScoreResponseSchema.parse(assessment.result);
  expect(result.model_version).toBe(health.model_version);
  expect(result.flags).toContain('verdict_affordable');
  expect(result.flags).toContain('offered_schedule_capacity_checked');
  expect(result.flags).not.toContain('zero_interest_mvp');
  expect(result.recommended_loan.suggested_principal_index).toBeGreaterThan(0);
  expect(result.loan_terms?.annual_rate).toBe(0.24);
  expect(result.loan_terms?.schedule_type).toBe('adaptive');
  expect(result.loan_terms?.requested_amount_policy).toBe('capacity_checked');
  expect(result.loan_terms!.total_interest_index).toBeGreaterThan(0);
  const repayments = result.adaptive_schedule.reduce(
    (total, row) => total + row.installment_index,
    0,
  );
  expect(result.loan_terms!.total_repayment_index).toBeCloseTo(repayments, 2);
  expect(repayments).toBeCloseTo(
    result.recommended_loan.suggested_principal_index +
      result.loan_terms!.total_interest_index,
    2,
  );
  expect(result.forecast_provenance?.real_revenue_weight).toBe(1);
  expect(result.forecast_provenance?.synthetic_net_weight).toBe(0);
  expect(result.forecast_provenance?.expense_mode).toBe(
    'observed_cost_projection',
  );
  const direct = await request.post(`${FINAL_ML_URL}/score`, {
    data: {
      business_id: business.id,
      as_of_date: FINAL_AS_OF_DATE,
      currency: 'UZS',
      requested_amount: null,
      transactions: business.transactions,
    },
  });
  expect(direct.status(), await direct.text()).toBe(200);
  const directResult = ScoreResponseSchema.parse(await direct.json());
  expect(directResult.recommended_loan).toEqual(result.recommended_loan);
  expect(directResult.loan_terms).toEqual(result.loan_terms);
  expect(directResult.adaptive_schedule).toEqual(result.adaptive_schedule);
  const saved = AssessmentSchema.parse(
    await (
      await request.get(`${FINAL_API_URL}/assessments/${assessment.id}`)
    ).json(),
  );
  expect(saved.result).toEqual(result);
  const mlEvents = (await finalAudit()).filter(
    (row) => row.request_id === result.request_id,
  );
  expect(mlEvents.map((row) => row.event)).toEqual([
    'assessment_requested',
    'assessment_completed',
  ]);
  const completed = mlEvents[1]!;
  expect(completed.model_artifact_sha256).toBe(health.model_artifact_sha256);
  expect(completed.component_identity).toEqual(health.component_identity);
  expect(completed.result).toEqual(result);
  expect(completed.financial_evidence.revenue_forecast.grid).toHaveLength(12);
  const financial = completed.financial_evidence.assessment;
  expect(financial.offered.actual_within_capacity).toBe(true);
  expect(financial.comparison.same_principal).toBe(
    result.recommended_loan.suggested_principal_index,
  );
  expect(financial.comparison.same_annual_rate).toBe(0.24);
  expect(financial.comparison.offered_overload_months).toBe(0);
  expect(result.capacity_score).toBe(financial.score);
  expect(completed.transactions).toBeUndefined();
});

test('observed sustained decline suppresses the main loan while feasible seasonal and uncertain medians retain offers', async ({
  request,
}) => {
  const declining = await importFinalBusiness(request, 'declining');
  const seasonal = await importFinalBusiness(request, 'seasonal');
  const elevated = await importFinalBusiness(request, 'elevated');
  const declineResult = ScoreResponseSchema.parse(
    (await assessFinalBusiness(request, declining.id)).result,
  );
  expect(declineResult.flags).toContain('verdict_decline');
  expect(declineResult.flags).toContain('sustained_decline_guard');
  expect(declineResult.recommended_loan.suggested_principal_index).toBe(0);
  expect(declineResult.adaptive_schedule).toEqual([]);
  expect(declineResult.capacity_score).toBe(0);
  const seasonalResult = ScoreResponseSchema.parse(
    (await assessFinalBusiness(request, seasonal.id)).result,
  );
  expect(seasonalResult.flags).not.toContain('verdict_decline');
  expect(
    seasonalResult.recommended_loan.suggested_principal_index,
  ).toBeGreaterThan(0);
  const payments = seasonalResult.adaptive_schedule.map(
    (row) => row.installment_index,
  );
  expect(Math.max(...payments) - Math.min(...payments)).toBeGreaterThan(1);
  const elevatedResult = ScoreResponseSchema.parse(
    (await assessFinalBusiness(request, elevated.id)).result,
  );
  expect(elevatedResult.flags).toContain('verdict_elevated_risk');
  expect(
    elevatedResult.recommended_loan.suggested_principal_index,
  ).toBeGreaterThan(0);
  expect(elevatedResult.explanation.advisory.join(' ')).toMatch(
    /officer|human review/i,
  );
});

test('requested principal is solved against its actual offered schedule and excessive requests remain explicitly capped', async ({
  request,
}) => {
  const business = await importFinalBusiness(request, 'seasonal');
  const baseline = ScoreResponseSchema.parse(
    (await assessFinalBusiness(request, business.id)).result,
  );
  const requested =
    Math.floor(baseline.recommended_loan.suggested_principal_index * 25) / 100;
  const smaller = ScoreResponseSchema.parse(
    (await assessFinalBusiness(request, business.id, requested)).result,
  );
  expect(smaller.recommended_loan.suggested_principal_index).toBeCloseTo(
    requested,
    2,
  );
  const excessive = ScoreResponseSchema.parse(
    (await assessFinalBusiness(request, business.id, 1e12)).result,
  );
  expect(excessive.flags).toContain(
    'requested_amount_exceeds_offered_capacity',
  );
  expect(excessive.recommended_loan.suggested_principal_index).toBe(
    baseline.recommended_loan.suggested_principal_index,
  );
});

test('final recommendations and officer decisions remain durable and isolated between bank tenants', async ({
  request,
  playwright,
}) => {
  const business = await importFinalBusiness(request, 'stable');
  const assessment = await assessFinalBusiness(request, business.id);
  const decisionResponse = await request.post(
    `${FINAL_API_URL}/assessments/${assessment.id}/decisions`,
    {
      data: {
        decision: 'needs_information',
        notes:
          'Human review of the final scorer on disclosed synthetic integration input.',
      },
    },
  );
  expect(decisionResponse.status()).toBe(201);
  const reviewed = AssessmentSchema.parse(await decisionResponse.json());
  const other = await registerAccount(playwright, FINAL_API_URL);
  try {
    for (const path of [
      `/businesses/${business.id}`,
      `/assessments/${assessment.id}`,
      `/assessments?business_id=${business.id}`,
      `/audit?business_id=${business.id}`,
    ]) {
      expect(
        (await other.request.get(`${FINAL_API_URL}${path}`)).status(),
      ).toBe(404);
    }
    const unauthorized = await other.request.post(
      `${FINAL_API_URL}/assessments/${assessment.id}/decisions`,
      { data: { decision: 'approved', notes: 'Cross-tenant attempt' } },
    );
    expect(unauthorized.status()).toBe(404);
    const preserved = AssessmentSchema.parse(
      await (
        await request.get(`${FINAL_API_URL}/assessments/${assessment.id}`)
      ).json(),
    );
    expect(preserved.result).toEqual(assessment.result);
    expect(preserved.decision).toEqual(reviewed.decision);
    const audit = AuditListSchema.parse(
      await (
        await request.get(`${FINAL_API_URL}/audit`, {
          params: { business_id: business.id },
        })
      ).json(),
    );
    expect(
      audit.items.filter((row) => row.event_type === 'decision_recorded'),
    ).toHaveLength(1);
    expect(JSON.stringify(audit.items)).toContain(
      assessment.result!.request_id,
    );
  } finally {
    await other.request.dispose();
  }
});

test('the browser renders each advisory verdict and actual interest while preserving a human final decision', async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  for (const scenario of [
    { kind: 'stable' as const, label: 'Affordable' },
    {
      kind: 'elevated' as const,
      label: 'Elevated risk — officer review required',
    },
    { kind: 'declining' as const, label: 'Decline recommendation' },
  ]) {
    const business = await importFinalBusiness(request, scenario.kind);
    const assessment = await assessFinalBusiness(request, business.id);
    await page.goto('/');
    await page.getByRole('button', { name: 'Businesses', exact: true }).click();
    await page.getByLabel('Find a business').fill(business.name);
    await page
      .getByRole('button', { name: business.name, exact: true })
      .click();
    await expect(page.getByText(scenario.label, { exact: true })).toBeVisible();
    await expect(
      page.getByText('Annual interest 24%', { exact: true }),
    ).toBeVisible();
    await page.reload();
    await expect(page.getByText(scenario.label, { exact: true })).toBeVisible();
    if (scenario.kind === 'elevated') {
      await page.setViewportSize({ width: 375, height: 812 });
      await expect(
        page.getByText(scenario.label, { exact: true }),
      ).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBe(true);
      await page.setViewportSize({ width: 1280, height: 720 });
    }
    if (scenario.kind === 'stable') {
      await page
        .getByLabel('Review notes')
        .fill('Final model recommendation reviewed on synthetic test inputs.');
      await page
        .getByRole('button', { name: 'Record decision', exact: true })
        .click();
      const recordedDecision = page.waitForResponse(
        (response) =>
          response.request().method() === 'POST' &&
          new URL(response.url()).pathname ===
            new URL(`${FINAL_API_URL}/assessments/${assessment.id}/decisions`)
              .pathname,
      );
      await page
        .getByRole('dialog', { name: 'Record this decision?' })
        .getByRole('button', { name: 'Confirm decision', exact: true })
        .click();
      expect((await recordedDecision).status()).toBe(201);
      const saved = AssessmentSchema.parse(
        await (
          await request.get(`${FINAL_API_URL}/assessments/${assessment.id}`)
        ).json(),
      );
      expect(saved.decision?.decision).toBe('needs_information');
      expect(saved.result).toEqual(assessment.result);
    }
  }
  expect(errors).toEqual([]);
});
