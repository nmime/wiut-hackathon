import type { APIRequestContext, PlaywrightWorkerArgs } from '@playwright/test';
import {
  AssessmentSchema,
  AuditListSchema,
  AuthSessionSchema,
  BusinessDetailSchema,
  BusinessListSchema,
  ProblemSchema,
  ShowcaseGenerationSchema,
} from '../libs/common/api-contracts/src/index';
import { expect, registerAccount, test, TEST_ORIGIN } from './auth-fixtures';
import { API_URL, AS_OF_DATE, importInput } from './helpers';

const generation = {
  scenario: 'mixed',
  seed: 7261,
  months: 24,
  count: 6,
  monthly_revenue_uzs: 30_000_000,
  end_month: '2026-09',
};

async function createLab(
  request: APIRequestContext,
  playwright: PlaywrightWorkerArgs['playwright'],
  apiUrl = API_URL,
  origin = TEST_ORIGIN,
) {
  const response = await request.post(`${apiUrl}/auth/showcase-tenants`, {
    data: { name: 'Test-only showcase workspace' },
  });
  expect(response.status(), await response.text()).toBe(201);
  const session = AuthSessionSchema.parse(await response.json());
  expect(session.tenant.kind).toBe('showcase');
  const lab = await playwright.request.newContext({
    storageState: await request.storageState(),
    extraHTTPHeaders: {
      origin,
      'x-csrf-token': session.csrf_token,
      'x-tenant-id': session.tenant.id,
    },
  });
  return { lab, session };
}

test('showcase opt-in creates an empty isolated lab and cannot seed bank workspaces', async ({
  request,
  playwright,
}) => {
  const bank = AuthSessionSchema.parse(
    await (await request.get(`${API_URL}/auth/session`)).json(),
  );
  expect(bank.tenant.kind).toBe('bank');
  expect(
    (
      await request.post(`${API_URL}/showcase/generate`, { data: generation })
    ).status(),
  ).toBe(403);
  // A client cannot turn registration or ordinary workspace creation into a lab.
  expect(
    (
      await request.post(`${API_URL}/tenants`, {
        data: { name: 'Spoofed lab', kind: 'showcase' },
      })
    ).status(),
  ).toBe(400);
  const { lab, session } = await createLab(request, playwright);
  try {
    expect(session.tenant.id).not.toBe(bank.tenant.id);
    expect(session.csrf_token).not.toBe(bank.csrf_token);
    expect(
      BusinessListSchema.parse(
        await (await lab.get(`${API_URL}/businesses`)).json(),
      ).items,
    ).toEqual([]);
    expect(
      (
        await request.post(`${API_URL}/showcase/generate`, {
          data: generation,
        })
      ).status(),
    ).toBe(403);
    expect(
      (
        await lab.post(`${API_URL}/showcase/generate`, {
          headers: { 'x-tenant-id': bank.tenant.id },
          data: generation,
        })
      ).status(),
    ).toBe(409);
    expect(
      (
        await lab.post(`${API_URL}/businesses`, {
          data: importInput('Real imports do not belong in a lab'),
        })
      ).status(),
    ).toBe(409);
    const response = await lab.post(`${API_URL}/showcase/generate`, {
      data: { ...generation, count: 1 },
    });
    expect(response.status(), await response.text()).toBe(201);
    const generated = ShowcaseGenerationSchema.parse(await response.json());
    expect(generated.items).toHaveLength(1);
    const switched = await lab.post(`${API_URL}/tenants/switch`, {
      data: { tenant_id: bank.tenant.id },
    });
    expect(switched.status()).toBe(200);
    expect(AuthSessionSchema.parse(await switched.json()).tenant.kind).toBe(
      'bank',
    );
    expect(
      BusinessListSchema.parse(
        await (await request.get(`${API_URL}/businesses`)).json(),
      ).items,
    ).toEqual([]);
    expect(
      (
        await request.get(`${API_URL}/businesses/${generated.items[0]!.id}`)
      ).status(),
    ).toBe(404);
  } finally {
    await lab.dispose();
  }
});

test('seeded showcase inputs are reproducible, diverse, disclosed, and use new identities', async ({
  request,
  playwright,
}) => {
  const { lab } = await createLab(request, playwright);
  try {
    const batches = [];
    for (let run = 0; run < 2; run++) {
      const response = await lab.post(`${API_URL}/showcase/generate`, {
        data: generation,
      });
      expect(response.status(), await response.text()).toBe(201);
      batches.push(ShowcaseGenerationSchema.parse(await response.json()));
    }
    const [first, second] = batches;
    expect(first!.items).toHaveLength(6);
    expect(
      first!.items.map((item) => item.showcase_provenance?.scenario),
    ).toEqual([
      'stable',
      'seasonal',
      'growing',
      'declining',
      'volatile',
      'short_history',
    ]);
    for (const [index, business] of first!.items.entries()) {
      const repeated = second!.items[index]!;
      expect(business.data_source).toBe('synthetic');
      expect(business.amount_unit).toBe('UZS');
      expect(business.archived_at).toBeNull();
      expect(business.showcase_provenance).toMatchObject({
        generator_version: 'showcase-v1',
        seed: 7261,
        end_month: '2026-09',
        monthly_revenue_uzs: 30_000_000,
        batch_index: index,
      });
      expect(business.id).not.toBe(repeated.id);
      expect(business.transactions).toEqual(repeated.transactions);
      expect(business.monthly_cashflow).toEqual(repeated.monthly_cashflow);
      expect(business.history_months).toBe(index === 5 ? 4 : generation.months);
      expect(
        BusinessDetailSchema.parse(
          await (await lab.get(`${API_URL}/businesses/${business.id}`)).json(),
        ).showcase_provenance,
      ).toEqual(business.showcase_provenance);
    }
    const portfolio = BusinessListSchema.parse(
      await (await lab.get(`${API_URL}/businesses`)).json(),
    );
    expect(portfolio.synthetic).toBe(true);
    expect(portfolio.items).toHaveLength(12);
    const audit = AuditListSchema.parse(
      await (await lab.get(`${API_URL}/audit`)).json(),
    );
    expect(
      audit.items.filter(
        (event) => event.event_type === 'showcase_business_generated',
      ),
    ).toHaveLength(12);
    expect(JSON.stringify(audit.items)).toContain('showcase-v1');
  } finally {
    await lab.dispose();
  }
});

test('showcase generation validates bounded inputs and preserves the portfolio on rejection', async ({
  request,
  playwright,
}) => {
  const { lab } = await createLab(request, playwright);
  try {
    const future = new Date();
    future.setUTCMonth(future.getUTCMonth() + 1);
    for (const changes of [
      { count: 0 },
      { count: 7 },
      { months: 2 },
      { months: 37 },
      { seed: -1 },
      { seed: 4_294_967_296 },
      { seed: 1.5 },
      { scenario: 'guaranteed_approval' },
      { monthly_revenue_uzs: 0 },
      { monthly_revenue_uzs: 1_000_000_001 },
      { end_month: '2026-13' },
      { end_month: future.toISOString().slice(0, 7) },
      { data_source: 'user_provided' },
    ]) {
      const response = await lab.post(`${API_URL}/showcase/generate`, {
        data: { ...generation, ...changes },
      });
      expect(response.status(), JSON.stringify(changes)).toBe(400);
      expect(ProblemSchema.parse(await response.json()).status).toBe(400);
    }
    expect(
      BusinessListSchema.parse(
        await (await lab.get(`${API_URL}/businesses`)).json(),
      ).items,
    ).toEqual([]);
  } finally {
    await lab.dispose();
  }
});

test('a showcase assessment and human decision persist with generation provenance and stay tenant scoped', async ({
  request,
  playwright,
}) => {
  const { lab } = await createLab(request, playwright);
  const outsider = await registerAccount(playwright, API_URL);
  try {
    const business = ShowcaseGenerationSchema.parse(
      await (
        await lab.post(`${API_URL}/showcase/generate`, {
          data: { ...generation, scenario: 'stable', count: 1 },
        })
      ).json(),
    ).items[0]!;
    const response = await lab.post(`${API_URL}/assessments`, {
      data: { business_id: business.id, as_of_date: AS_OF_DATE },
    });
    expect(response.status(), await response.text()).toBe(201);
    const assessment = AssessmentSchema.parse(await response.json());
    expect(assessment.status).toBe('completed');
    expect(assessment.amount_unit).toBe('UZS');
    expect(assessment.result?.business_id).toBe(business.id);
    const decision = await lab.post(
      `${API_URL}/assessments/${assessment.id}/decisions`,
      {
        data: {
          decision: 'needs_information',
          notes:
            'Showcase-only human review; generated inputs are not borrower evidence.',
        },
      },
    );
    expect(decision.status()).toBe(201);
    expect(
      AssessmentSchema.parse(await decision.json()).decision?.decision,
    ).toBe('needs_information');
    expect(
      AssessmentSchema.parse(
        await (await lab.get(`${API_URL}/assessments/${assessment.id}`)).json(),
      ).decision,
    ).not.toBeNull();
    const audit = AuditListSchema.parse(
      await (
        await lab.get(`${API_URL}/audit`, {
          params: { business_id: business.id },
        })
      ).json(),
    );
    expect(audit.items.map((event) => event.event_type)).toEqual(
      expect.arrayContaining([
        'showcase_business_generated',
        'assessment_requested',
        'assessment_completed',
        'decision_recorded',
      ]),
    );
    for (const path of [
      `/businesses/${business.id}`,
      `/assessments/${assessment.id}`,
      `/audit?business_id=${business.id}`,
    ]) {
      expect(
        (await outsider.request.get(`${API_URL}${path}`)).status(),
        path,
      ).toBe(404);
    }
    expect(
      (
        await outsider.request.post(`${API_URL}/assessments`, {
          data: { business_id: business.id, as_of_date: AS_OF_DATE },
        })
      ).status(),
    ).toBe(404);
  } finally {
    await lab.dispose();
    await outsider.request.dispose();
  }
});

test('anonymous showcase writes remain authenticated and CSRF protected', async ({
  request,
  playwright,
}) => {
  const anonymous = await playwright.request.newContext({
    extraHTTPHeaders: { origin: TEST_ORIGIN },
  });
  const noCsrf = await playwright.request.newContext({
    storageState: await request.storageState(),
    extraHTTPHeaders: { origin: TEST_ORIGIN },
  });
  try {
    for (const [path, data] of [
      ['/auth/showcase-tenants', { name: 'Anonymous lab' }],
      ['/showcase/generate', generation],
    ] as const) {
      expect(
        (await anonymous.post(`${API_URL}${path}`, { data })).status(),
      ).toBe(401);
      expect((await noCsrf.post(`${API_URL}${path}`, { data })).status()).toBe(
        403,
      );
    }
  } finally {
    await anonymous.dispose();
    await noCsrf.dispose();
  }
});

test('concurrent showcase batches cannot exceed the workspace cap or leave partial audit records', async ({
  request,
  playwright,
}) => {
  test.setTimeout(60_000);
  const { lab } = await createLab(request, playwright);
  try {
    const small = { ...generation, scenario: 'stable', months: 3 };
    for (let batch = 0; batch < 16; batch++) {
      const response = await lab.post(`${API_URL}/showcase/generate`, {
        data: small,
      });
      expect(response.status(), await response.text()).toBe(201);
    }
    const competing = await Promise.all(
      [1, 2].map(() =>
        lab.post(`${API_URL}/showcase/generate`, {
          data: { ...small, count: 4 },
        }),
      ),
    );
    expect(competing.map((response) => response.status()).sort()).toEqual([
      201, 409,
    ]);
    const rejected = competing.find((response) => response.status() === 409)!;
    expect(ProblemSchema.parse(await rejected.json()).title).toBe(
      'Showcase limit reached',
    );
    const portfolio = BusinessListSchema.parse(
      await (await lab.get(`${API_URL}/businesses`)).json(),
    );
    expect(portfolio.items).toHaveLength(100);
    const audit = AuditListSchema.parse(
      await (await lab.get(`${API_URL}/audit`)).json(),
    );
    expect(
      audit.items.filter(
        (event) => event.event_type === 'showcase_business_generated',
      ),
    ).toHaveLength(100);
  } finally {
    await lab.dispose();
  }
});
