import { randomUUID } from 'node:crypto';
import {
  AssessmentSchema,
  BusinessListSchema,
  AuditListSchema,
  ProblemSchema,
  InvitationCreateResponseSchema,
  TeamSchema,
  AuthSessionSchema,
} from '../libs/common/api-contracts/src/index';
import {
  expect,
  test,
  registerAccount,
  TEST_PASSWORD,
  TEST_ORIGIN,
} from './auth-fixtures';
import { API_URL, AS_OF_DATE, importBusiness, importInput } from './helpers';

test('anonymous callers cannot access or mutate tenant data', async ({
  playwright,
}) => {
  const anonymous = await playwright.request.newContext({
    extraHTTPHeaders: { origin: TEST_ORIGIN },
  });
  try {
    for (const path of [
      '/auth/session',
      '/businesses',
      '/assessments',
      '/audit',
      '/team',
    ]) {
      const response = await anonymous.get(`${API_URL}${path}`);
      expect(response.status(), path).toBe(401);
      expect(ProblemSchema.parse(await response.json()).status).toBe(401);
    }
    const response = await anonymous.post(`${API_URL}/businesses`, {
      data: importInput('Anonymous import'),
    });
    expect(response.status()).toBe(401);
  } finally {
    await anonymous.dispose();
  }
});

test('email-bound invitations give officers access only to their bank and admin team operations stay protected', async ({
  request,
  playwright,
}) => {
  const owner = AuthSessionSchema.parse(
    await (await request.get(`${API_URL}/auth/session`)).json(),
  );
  const business = await importBusiness(request, 'Invited officer access');
  const email = `invited-${randomUUID()}@example.test`;
  const response = await request.post(`${API_URL}/invitations`, {
    data: { email, role: 'officer' },
  });
  expect(response.status()).toBe(201);
  const invite = InvitationCreateResponseSchema.parse(await response.json());
  const officer = await registerAccount(playwright, API_URL, {
    email,
    displayName: 'Invited Credit Officer',
    invitationToken: invite.token,
  });
  try {
    expect(officer.session.tenant).toEqual({
      ...owner.tenant,
      role: 'officer',
    });
    expect(
      (
        await officer.request.get(`${API_URL}/businesses/${business.id}`)
      ).status(),
    ).toBe(200);
    expect((await officer.request.get(`${API_URL}/team`)).status()).toBe(403);
    expect(
      (
        await officer.request.post(`${API_URL}/invitations`, {
          data: { email: 'forbidden@example.test', role: 'admin' },
        })
      ).status(),
    ).toBe(403);
    expect(
      (
        await officer.request.delete(
          `${API_URL}/invitations/${invite.invitation.id}`,
        )
      ).status(),
    ).toBe(403);
    const team = TeamSchema.parse(
      await (await request.get(`${API_URL}/team`)).json(),
    );
    expect(
      team.members.find((member) => member.id === officer.session.user.id)
        ?.role,
    ).toBe('officer');
    expect(
      team.invitations.find((item) => item.id === invite.invitation.id)?.status,
    ).toBe('accepted');
    expect(JSON.stringify(team)).not.toContain(invite.token);
    const score = await officer.request.post(`${API_URL}/assessments`, {
      data: { business_id: business.id, as_of_date: AS_OF_DATE },
    });
    expect(score.status()).toBe(201);
    const assessment = AssessmentSchema.parse(await score.json());
    const reviewed = await officer.request.post(
      `${API_URL}/assessments/${assessment.id}/decisions`,
      {
        data: {
          decision: 'needs_information',
          notes: 'The invited authenticated officer reviewed this evidence.',
        },
      },
    );
    expect(reviewed.status()).toBe(201);
    expect(
      AssessmentSchema.parse(await reviewed.json()).decision?.reviewer_name,
    ).toBe('Invited Credit Officer');
  } finally {
    await officer.request.dispose();
  }
});

test('invitation tokens are email-bound, one-use, and revocable', async ({
  request,
  playwright,
}) => {
  const email = `revoked-${randomUUID()}@example.test`;
  const created = InvitationCreateResponseSchema.parse(
    await (
      await request.post(`${API_URL}/invitations`, {
        data: { email, role: 'officer' },
      })
    ).json(),
  );
  const anonymous = await playwright.request.newContext({
    extraHTTPHeaders: { origin: TEST_ORIGIN },
  });
  try {
    const wrongEmail = await anonymous.post(`${API_URL}/auth/register`, {
      data: {
        email: `wrong-${randomUUID()}@example.test`,
        password: TEST_PASSWORD,
        display_name: 'Wrong invite recipient',
        invitation_token: created.token,
      },
    });
    expect(wrongEmail.status()).toBe(400);
    expect(
      (
        await request.delete(`${API_URL}/invitations/${created.invitation.id}`)
      ).ok(),
    ).toBe(true);
    const revoked = await anonymous.post(`${API_URL}/auth/register`, {
      data: {
        email,
        password: TEST_PASSWORD,
        display_name: 'Revoked invite recipient',
        invitation_token: created.token,
      },
    });
    expect(revoked.status()).toBe(400);
    const reuseEmail = `reuse-${randomUUID()}@example.test`;
    const usable = InvitationCreateResponseSchema.parse(
      await (
        await request.post(`${API_URL}/invitations`, {
          data: { email: reuseEmail, role: 'officer' },
        })
      ).json(),
    );
    const member = await registerAccount(playwright, API_URL, {
      email: reuseEmail,
      invitationToken: usable.token,
    });
    try {
      const reused = await member.request.post(
        `${API_URL}/invitations/accept`,
        { data: { token: usable.token } },
      );
      expect(reused.status()).toBe(400);
    } finally {
      await member.request.dispose();
    }
  } finally {
    await anonymous.dispose();
  }
});

test('switching workspaces rotates CSRF and exposes only the selected tenant data', async ({
  request,
  playwright,
}) => {
  const first = AuthSessionSchema.parse(
    await (await request.get(`${API_URL}/auth/session`)).json(),
  );
  const business = await importBusiness(request, 'First workspace only');
  const created = await request.post(`${API_URL}/tenants`, {
    data: { name: 'Second isolated bank' },
  });
  expect(created.status()).toBe(201);
  const second = AuthSessionSchema.parse(await created.json());
  expect(second.tenant.id).not.toBe(first.tenant.id);
  expect(second.tenants.map((item) => item.id)).toEqual(
    expect.arrayContaining([first.tenant.id, second.tenant.id]),
  );
  expect(
    (await request.get(`${API_URL}/businesses/${business.id}`)).status(),
  ).toBe(404);
  expect(
    (
      await request.post(`${API_URL}/businesses`, {
        data: importInput('Stale CSRF'),
      })
    ).status(),
  ).toBe(403);
  const current = await playwright.request.newContext({
    storageState: await request.storageState(),
    extraHTTPHeaders: {
      origin: TEST_ORIGIN,
      'x-csrf-token': second.csrf_token,
    },
  });
  try {
    const outsider = await registerAccount(playwright, API_URL);
    try {
      expect(
        (
          await current.post(`${API_URL}/tenants/switch`, {
            data: { tenant_id: outsider.session.tenant.id },
          })
        ).status(),
      ).toBe(404);
    } finally {
      await outsider.request.dispose();
    }
    const back = await current.post(`${API_URL}/tenants/switch`, {
      data: { tenant_id: first.tenant.id },
    });
    expect(back.status()).toBe(200);
    const restored = AuthSessionSchema.parse(await back.json());
    expect(restored.tenant.id).toBe(first.tenant.id);
    expect(restored.csrf_token).not.toBe(second.csrf_token);
    expect(
      (await current.get(`${API_URL}/businesses/${business.id}`)).status(),
    ).toBe(200);
  } finally {
    await current.dispose();
  }
});

test('sessions survive login, use protected cookies, reject bad credentials, and are revoked by logout', async ({
  playwright,
}) => {
  const email = `login-${randomUUID()}@example.test`;
  const owner = await registerAccount(playwright, API_URL, { email });
  const anonymous = await playwright.request.newContext({
    extraHTTPHeaders: { origin: TEST_ORIGIN },
  });
  try {
    const cookies = (await owner.request.storageState()).cookies;
    expect(cookies).toHaveLength(1);
    expect(cookies[0]?.httpOnly).toBe(true);
    expect(['Lax', 'Strict']).toContain(cookies[0]?.sameSite);
    expect(cookies[0]?.expires).toBeGreaterThan(Date.now() / 1000);
    const wrong = await anonymous.post(`${API_URL}/auth/login`, {
      data: { email, password: 'Incorrect-password-for-this-test!' },
    });
    expect(wrong.status()).toBe(401);
    const login = await anonymous.post(`${API_URL}/auth/login`, {
      data: { email: email.toUpperCase(), password: TEST_PASSWORD },
    });
    expect(login.status()).toBe(200);
    const session = await login.json();
    expect(session.user.id).toBe(owner.session.user.id);
    expect(session.tenant.id).toBe(owner.session.tenant.id);
    expect(JSON.stringify(session)).not.toMatch(/password_hash|session_hash/);
    const saved = await playwright.request.newContext({
      storageState: await anonymous.storageState(),
    });
    try {
      const logout = await anonymous.post(`${API_URL}/auth/logout`, {
        headers: { 'x-csrf-token': session.csrf_token },
      });
      expect(logout.ok()).toBe(true);
      expect((await anonymous.get(`${API_URL}/auth/session`)).status()).toBe(
        401,
      );
      expect((await saved.get(`${API_URL}/businesses`)).status()).toBe(401);
    } finally {
      await saved.dispose();
    }
  } finally {
    await owner.request.dispose();
    await anonymous.dispose();
  }
});

test('authenticated writes require CSRF and reject foreign origins', async ({
  request,
  playwright,
}) => {
  const noHeader = await playwright.request.newContext({
    storageState: await request.storageState(),
    extraHTTPHeaders: { origin: TEST_ORIGIN },
  });
  try {
    const missing = await noHeader.post(`${API_URL}/businesses`, {
      data: importInput('Missing CSRF'),
    });
    expect(missing.status()).toBe(403);
    const wrong = await request.post(`${API_URL}/businesses`, {
      headers: { 'x-csrf-token': 'invalid-token' },
      data: importInput('Wrong CSRF'),
    });
    expect(wrong.status()).toBe(403);
    const foreign = await request.post(`${API_URL}/businesses`, {
      headers: { origin: 'https://untrusted.example' },
      data: importInput('Foreign origin'),
    });
    expect(foreign.status()).toBe(403);
  } finally {
    await noHeader.dispose();
  }
});

test('a stale expected-tenant header rejects reads and writes without choosing another tenant', async ({
  request,
}) => {
  const session = AuthSessionSchema.parse(
    await (await request.get(`${API_URL}/auth/session`)).json(),
  );
  const wrong = '99999999-9999-4999-8999-999999999999';
  const response = await request.get(`${API_URL}/businesses`, {
    headers: { 'x-tenant-id': wrong },
  });
  expect(response.status()).toBe(409);
  expect(ProblemSchema.parse(await response.json()).title).toBe(
    'Workspace changed',
  );
  const mutation = await request.post(`${API_URL}/businesses`, {
    headers: { 'x-tenant-id': wrong },
    data: importInput('Stale expected tenant'),
  });
  expect(mutation.status()).toBe(409);
  const refresh = await request.get(`${API_URL}/auth/session`, {
    headers: { 'x-tenant-id': wrong },
  });
  expect(refresh.status()).toBe(200);
  expect(AuthSessionSchema.parse(await refresh.json()).tenant.id).toBe(
    session.tenant.id,
  );
  expect(
    (
      await request.get(`${API_URL}/businesses`, {
        headers: { 'x-tenant-id': session.tenant.id },
      })
    ).status(),
  ).toBe(200);
});

test('a second tenant cannot read, assess, review, or audit another tenant business', async ({
  request,
  playwright,
}) => {
  const business = await importBusiness(request, 'Private tenant evidence');
  const scoreResponse = await request.post(`${API_URL}/assessments`, {
    data: { business_id: business.id, as_of_date: AS_OF_DATE },
  });
  expect(scoreResponse.status()).toBe(201);
  const assessment = AssessmentSchema.parse(await scoreResponse.json());
  const outsider = await registerAccount(playwright, API_URL);
  try {
    const portfolio = BusinessListSchema.parse(
      await (await outsider.request.get(`${API_URL}/businesses`)).json(),
    );
    expect(portfolio.items.some((item) => item.id === business.id)).toBe(false);
    for (const path of [
      `/businesses/${business.id}`,
      `/assessments/${assessment.id}`,
      `/assessments?business_id=${business.id}`,
      `/audit?business_id=${business.id}`,
    ]) {
      const response = await outsider.request.get(`${API_URL}${path}`);
      expect(response.status(), path).toBe(404);
    }
    const assess = await outsider.request.post(`${API_URL}/assessments`, {
      data: { business_id: business.id, as_of_date: AS_OF_DATE },
    });
    expect(assess.status()).toBe(404);
    const review = await outsider.request.post(
      `${API_URL}/assessments/${assessment.id}/decisions`,
      {
        data: {
          decision: 'approved',
          notes: 'Unauthorized cross-tenant review must fail.',
        },
      },
    );
    expect(review.status()).toBe(404);
    const ownerRead = AssessmentSchema.parse(
      await (
        await request.get(`${API_URL}/assessments/${assessment.id}`)
      ).json(),
    );
    expect(ownerRead.decision).toBeNull();
    const outsiderAudit = AuditListSchema.parse(
      await (await outsider.request.get(`${API_URL}/audit`)).json(),
    );
    expect(
      outsiderAudit.items.some((item) => item.business_id === business.id),
    ).toBe(false);
  } finally {
    await outsider.request.dispose();
  }
});

test('a human decision is attributed to the signed-in user even when a name is forged', async ({
  request,
}) => {
  const session = await (await request.get(`${API_URL}/auth/session`)).json();
  const business = await importBusiness(request, 'Authenticated attribution');
  const assessment = AssessmentSchema.parse(
    await (
      await request.post(`${API_URL}/assessments`, {
        data: { business_id: business.id, as_of_date: AS_OF_DATE },
      })
    ).json(),
  );
  const response = await request.post(
    `${API_URL}/assessments/${assessment.id}/decisions`,
    {
      data: {
        decision: 'needs_information',
        reviewer_name: 'Forged administrator',
        notes: 'The actual authenticated reviewer must own this decision.',
      },
    },
  );
  expect(response.status()).toBe(201);
  const reviewed = AssessmentSchema.parse(await response.json());
  expect(reviewed.decision?.reviewer_name).toBe(session.user.display_name);
  expect(reviewed.decision?.reviewer_name).not.toBe('Forged administrator');
  const audit = AuditListSchema.parse(
    await (
      await request.get(`${API_URL}/audit?business_id=${business.id}`)
    ).json(),
  );
  expect(JSON.stringify(audit.items)).toContain(session.user.id);
});
