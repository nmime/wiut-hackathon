import { randomUUID } from 'node:crypto';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import type { APIRequestContext, PlaywrightWorkerArgs } from '@playwright/test';
import {
  AuthSecuritySchema,
  AuthSessionSchema,
  MfaSetupResponseSchema,
  MfaRecoveryCodesResponseSchema,
  AccountRecoveryKeyResponseSchema,
  ProblemSchema,
} from '../libs/common/api-contracts/src/index';
import {
  expect,
  test,
  registerAccount,
  TEST_PASSWORD,
  TEST_ORIGIN,
} from './auth-fixtures';
import { API_URL } from './helpers';

const backendRoot = resolve(__dirname, '../apps/backend/user/user-app-api');
const backendRequire = createRequire(resolve(backendRoot, 'package.json'));
const { Pool } = backendRequire('pg');
const databaseUrl =
  process.env.WIUT_TEST_DATABASE_URL ??
  'postgresql://wiut:wiut_dev@127.0.0.1:55432/wiut_test';
async function hotp(secret: string, counter: number) {
  const module = await import(
    pathToFileURL(resolve(backendRoot, 'dist/account-security.js')).href
  );
  return module.hotp(secret, counter) as string;
}
async function enroll(request: APIRequestContext) {
  const response = await request.post(`${API_URL}/auth/mfa/setup`, {
    data: { current_password: TEST_PASSWORD },
  });
  expect(response.status(), await response.text()).toBe(200);
  const setup = MfaSetupResponseSchema.parse(await response.json());
  const code = await hotp(setup.secret, Math.floor(Date.now() / 30000) - 1);
  const confirmed = await request.post(`${API_URL}/auth/mfa/confirm`, {
    data: { totp_code: code },
  });
  expect(confirmed.status(), await confirmed.text()).toBe(200);
  return {
    setup,
    ...MfaRecoveryCodesResponseSchema.parse(await confirmed.json()),
  };
}
async function anonymous(playwright: PlaywrightWorkerArgs['playwright']) {
  return playwright.request.newContext({
    extraHTTPHeaders: { origin: TEST_ORIGIN },
  });
}

test('MFA enrollment encrypts secrets, stores only recovery hashes, revokes prior sessions and atomically prevents OTP/recovery replay', async ({
  request,
  playwright,
}) => {
  const user = AuthSessionSchema.parse(
    await (await request.get(`${API_URL}/auth/session`)).json(),
  );
  const oldSession = await anonymous(playwright),
    factorClientA = await anonymous(playwright),
    factorClientB = await anonymous(playwright);
  const pool = new Pool({ connectionString: databaseUrl });
  try {
    expect(
      (
        await oldSession.post(`${API_URL}/auth/login`, {
          data: { email: user.user.email, password: TEST_PASSWORD },
        })
      ).status(),
    ).toBe(200);
    const enrollment = await enroll(request);
    expect((await oldSession.get(`${API_URL}/auth/session`)).status()).toBe(
      401,
    );
    const state = AuthSecuritySchema.parse(
      await (await request.get(`${API_URL}/auth/security`)).json(),
    );
    expect(state).toMatchObject({
      mfa_available: true,
      mfa_enabled: true,
      recovery_codes_remaining: 10,
    });
    const stored = (
      await pool.query(
        'SELECT mfa_secret_encrypted,mfa_pending_secret_encrypted,mfa_last_counter FROM app_users WHERE id=$1',
        [user.user.id],
      )
    ).rows[0];
    expect(stored.mfa_secret_encrypted).not.toContain(enrollment.setup.secret);
    expect(stored.mfa_pending_secret_encrypted).toBeNull();
    const hashes = (
      await pool.query(
        'SELECT code_hash FROM mfa_recovery_codes WHERE user_id=$1',
        [user.user.id],
      )
    ).rows;
    expect(hashes).toHaveLength(10);
    expect(JSON.stringify(hashes)).not.toContain(enrollment.recovery_codes[0]);
    const missing = await factorClientA.post(`${API_URL}/auth/login`, {
      data: { email: user.user.email, password: TEST_PASSWORD },
    });
    expect(missing.status()).toBe(401);
    expect(ProblemSchema.parse(await missing.json()).code).toBe('mfa_required');
    expect((await factorClientA.storageState()).cookies).toEqual([]);
    const code = await hotp(
      enrollment.setup.secret,
      Math.floor(Date.now() / 30000),
    );
    const otp = await Promise.all(
      [factorClientA, factorClientB].map((client) =>
        client.post(`${API_URL}/auth/login`, {
          data: {
            email: user.user.email,
            password: TEST_PASSWORD,
            totp_code: code,
          },
        }),
      ),
    );
    expect(otp.map((r) => r.status()).sort()).toEqual([200, 401]);
    const recovery = await Promise.all(
      [factorClientA, factorClientB].map((client) =>
        client.post(`${API_URL}/auth/login`, {
          data: {
            email: user.user.email,
            password: TEST_PASSWORD,
            recovery_code: enrollment.recovery_codes[0],
          },
        }),
      ),
    );
    expect(recovery.map((r) => r.status()).sort()).toEqual([200, 401]);
    expect(
      AuthSecuritySchema.parse(
        await (await request.get(`${API_URL}/auth/security`)).json(),
      ).recovery_codes_remaining,
    ).toBe(9);
    const audit = (
      await pool.query(
        'SELECT event_type,metadata FROM security_events WHERE actor_user_id=$1',
        [user.user.id],
      )
    ).rows;
    expect(audit.map((r: { event_type: string }) => r.event_type)).toEqual(
      expect.arrayContaining([
        'mfa_enabled',
        'account_signed_in',
        'account_sign_in_failed',
      ]),
    );
    expect(JSON.stringify(audit)).not.toContain(enrollment.setup.secret);
    expect(JSON.stringify(audit)).not.toContain(enrollment.recovery_codes[0]);
  } finally {
    await oldSession.dispose();
    await factorClientA.dispose();
    await factorClientB.dispose();
    await pool.end();
  }
});

test('password changes require current credentials and fresh MFA, rotate CSRF and revoke other sessions', async ({
  request,
  playwright,
}) => {
  const session = AuthSessionSchema.parse(
    await (await request.get(`${API_URL}/auth/session`)).json(),
  );
  const enrollment = await enroll(request),
    other = await anonymous(playwright);
  const newPassword = 'Changed-Test-Only-Passphrase-2026!';
  try {
    expect(
      (
        await other.post(`${API_URL}/auth/login`, {
          data: {
            email: session.user.email,
            password: TEST_PASSWORD,
            recovery_code: enrollment.recovery_codes[0],
          },
        })
      ).status(),
    ).toBe(200);
    const wrong = await request.post(`${API_URL}/auth/password`, {
      data: {
        current_password: 'Wrong-Current-Password-2026!',
        new_password: newPassword,
        recovery_code: enrollment.recovery_codes[1],
      },
    });
    expect(wrong.status()).toBe(403);
    expect((await request.get(`${API_URL}/auth/session`)).status()).toBe(200);
    const noFactor = await request.post(`${API_URL}/auth/password`, {
      data: { current_password: TEST_PASSWORD, new_password: newPassword },
    });
    expect(noFactor.status()).toBe(403);
    expect(ProblemSchema.parse(await noFactor.json()).code).toBe(
      'mfa_required',
    );
    const changed = await request.post(`${API_URL}/auth/password`, {
      data: {
        current_password: TEST_PASSWORD,
        new_password: newPassword,
        recovery_code: enrollment.recovery_codes[1],
      },
    });
    expect(changed.status(), await changed.text()).toBe(200);
    const refreshed = AuthSessionSchema.parse(await changed.json());
    expect(refreshed.csrf_token).not.toBe(session.csrf_token);
    expect((await other.get(`${API_URL}/auth/session`)).status()).toBe(401);
    expect(
      (
        await request.post(`${API_URL}/auth/recovery-key`, {
          data: {
            current_password: newPassword,
            recovery_code: enrollment.recovery_codes[2],
          },
        })
      ).status(),
    ).toBe(403);
    expect(
      (
        await other.post(`${API_URL}/auth/login`, {
          data: {
            email: session.user.email,
            password: TEST_PASSWORD,
            recovery_code: enrollment.recovery_codes[2],
          },
        })
      ).status(),
    ).toBe(401);
    expect(
      (
        await other.post(`${API_URL}/auth/login`, {
          data: {
            email: session.user.email,
            password: newPassword,
            recovery_code: enrollment.recovery_codes[2],
          },
        })
      ).status(),
    ).toBe(200);
  } finally {
    await other.dispose();
  }
});

test('offline account recovery is once-use, neutral on invalid accounts, resets MFA and revokes every session without issuing a new one', async ({
  request,
  playwright,
}) => {
  const session = AuthSessionSchema.parse(
    await (await request.get(`${API_URL}/auth/session`)).json(),
  );
  const first = AccountRecoveryKeyResponseSchema.parse(
    await (
      await request.post(`${API_URL}/auth/recovery-key`, {
        data: { current_password: TEST_PASSWORD },
      })
    ).json(),
  );
  const rotated = AccountRecoveryKeyResponseSchema.parse(
    await (
      await request.post(`${API_URL}/auth/recovery-key`, {
        data: { current_password: TEST_PASSWORD },
      })
    ).json(),
  );
  expect(rotated.recovery_key).not.toBe(first.recovery_key);
  const enrollment = await enroll(request),
    a = await anonymous(playwright),
    b = await anonymous(playwright);
  const newPassword = 'Recovered-Test-Only-Passphrase-2026!';
  const pool = new Pool({ connectionString: databaseUrl });
  try {
    const input = {
      email: session.user.email,
      recovery_key: rotated.recovery_key,
      new_password: newPassword,
    };
    const stale = await a.post(`${API_URL}/auth/recover`, {
      data: { ...input, recovery_key: first.recovery_key },
    });
    const nonexistent = await a.post(`${API_URL}/auth/recover`, {
      data: { ...input, email: `unknown-${randomUUID()}@example.test` },
    });
    expect(stale.status()).toBe(401);
    expect(nonexistent.status()).toBe(401);
    expect(ProblemSchema.parse(await stale.json()).detail).toBe(
      ProblemSchema.parse(await nonexistent.json()).detail,
    );
    const results = await Promise.all(
      [a, b].map((client) =>
        client.post(`${API_URL}/auth/recover`, { data: input }),
      ),
    );
    expect(results.map((r) => r.status()).sort()).toEqual([200, 401]);
    for (const client of [request, a, b])
      expect((await client.get(`${API_URL}/auth/session`)).status()).toBe(401);
    const stored = (
      await pool.query(
        'SELECT account_recovery_key_hash,mfa_secret_encrypted,password_hash FROM app_users WHERE id=$1',
        [session.user.id],
      )
    ).rows[0];
    expect(stored.account_recovery_key_hash).toBeNull();
    expect(stored.mfa_secret_encrypted).toBeNull();
    expect(stored.password_hash).not.toContain(newPassword);
    expect(
      (
        await pool.query('SELECT 1 FROM mfa_recovery_codes WHERE user_id=$1', [
          session.user.id,
        ])
      ).rowCount,
    ).toBe(0);
    expect(
      (
        await a.post(`${API_URL}/auth/login`, {
          data: {
            email: session.user.email,
            password: TEST_PASSWORD,
            recovery_code: enrollment.recovery_codes[0],
          },
        })
      ).status(),
    ).toBe(401);
    const login = await a.post(`${API_URL}/auth/login`, {
      data: { email: session.user.email, password: newPassword },
    });
    expect(login.status()).toBe(200);
    expect(AuthSessionSchema.parse(await login.json()).user.id).toBe(
      session.user.id,
    );
    expect(
      AuthSecuritySchema.parse(
        await (await a.get(`${API_URL}/auth/security`)).json(),
      ),
    ).toMatchObject({ mfa_enabled: false, recovery_key_configured: false });
    expect(
      (
        await pool.query(
          "SELECT 1 FROM security_events WHERE actor_user_id=$1 AND event_type='account_recovered'",
          [session.user.id],
        )
      ).rowCount,
    ).toBe(1);
  } finally {
    await a.dispose();
    await b.dispose();
    await pool.end();
  }
});

test('MFA disable and recovery-code rotation need password and fresh factors; revoked sessions cannot alter credentials', async ({
  request,
  playwright,
}) => {
  const session = AuthSessionSchema.parse(
    await (await request.get(`${API_URL}/auth/session`)).json(),
  );
  const enrollment = await enroll(request),
    other = await anonymous(playwright);
  try {
    const login = await other.post(`${API_URL}/auth/login`, {
      data: {
        email: session.user.email,
        password: TEST_PASSWORD,
        recovery_code: enrollment.recovery_codes[0],
      },
    });
    const second = AuthSessionSchema.parse(await login.json());
    expect(
      (
        await request.post(`${API_URL}/auth/mfa/disable`, {
          data: { current_password: TEST_PASSWORD },
        })
      ).status(),
    ).toBe(403);
    const rotatedResponse = await request.post(
      `${API_URL}/auth/mfa/recovery-codes`,
      {
        data: {
          current_password: TEST_PASSWORD,
          recovery_code: enrollment.recovery_codes[1],
        },
      },
    );
    expect(rotatedResponse.status()).toBe(200);
    const rotated = MfaRecoveryCodesResponseSchema.parse(
      await rotatedResponse.json(),
    );
    expect(rotated.recovery_codes).not.toEqual(enrollment.recovery_codes);
    expect(
      (
        await other.post(`${API_URL}/auth/password`, {
          headers: { 'x-csrf-token': second.csrf_token },
          data: {
            current_password: TEST_PASSWORD,
            new_password: 'Attempt-From-Revoked-Session-2026!',
            recovery_code: rotated.recovery_codes[0],
          },
        })
      ).status(),
    ).toBe(401);
    expect(
      (
        await other.post(`${API_URL}/auth/login`, {
          data: {
            email: session.user.email,
            password: TEST_PASSWORD,
            recovery_code: enrollment.recovery_codes[2],
          },
        })
      ).status(),
    ).toBe(401);
    const disabled = await request.post(`${API_URL}/auth/mfa/disable`, {
      data: {
        current_password: TEST_PASSWORD,
        recovery_code: rotated.recovery_codes[0],
      },
    });
    expect(disabled.status()).toBe(200);
    expect(
      AuthSecuritySchema.parse(
        await (await request.get(`${API_URL}/auth/security`)).json(),
      ),
    ).toMatchObject({ mfa_enabled: false, recovery_codes_remaining: 0 });
    expect(
      (
        await other.post(`${API_URL}/auth/login`, {
          data: { email: session.user.email, password: TEST_PASSWORD },
        })
      ).status(),
    ).toBe(200);
  } finally {
    await other.dispose();
  }
});

test('security mutations preserve CSRF/origin protection and fail closed without an encryption key', async ({
  request,
  playwright,
}) => {
  const noHeader = await playwright.request.newContext({
    storageState: await request.storageState(),
    extraHTTPHeaders: { origin: TEST_ORIGIN },
  });
  const unconfigured = await registerAccount(
    playwright,
    'http://127.0.0.1:3002/api',
  );
  try {
    expect(
      (
        await noHeader.post(`${API_URL}/auth/recovery-key`, {
          data: { current_password: TEST_PASSWORD },
        })
      ).status(),
    ).toBe(403);
    expect(
      (
        await request.post(`${API_URL}/auth/mfa/setup`, {
          headers: { origin: 'https://untrusted.example' },
          data: { current_password: TEST_PASSWORD },
        })
      ).status(),
    ).toBe(403);
    const state = AuthSecuritySchema.parse(
      await (
        await unconfigured.request.get(
          'http://127.0.0.1:3002/api/auth/security',
        )
      ).json(),
    );
    expect(state.mfa_available).toBe(false);
    expect(
      (
        await unconfigured.request.post(
          'http://127.0.0.1:3002/api/auth/mfa/setup',
          { data: { current_password: TEST_PASSWORD } },
        )
      ).status(),
    ).toBe(503);
    expect(
      AuthSecuritySchema.parse(
        await (
          await unconfigured.request.get(
            'http://127.0.0.1:3002/api/auth/security',
          )
        ).json(),
      ).mfa_enabled,
    ).toBe(false);
  } finally {
    await noHeader.dispose();
    await unconfigured.request.dispose();
  }
});

test('credential and session checks remain current when a reset wins a concurrent user-row lock', async ({
  request,
  playwright,
}) => {
  const session = AuthSessionSchema.parse(
    await (await request.get(`${API_URL}/auth/session`)).json(),
  );
  const pool = new Pool({ connectionString: databaseUrl }),
    client = await pool.connect(),
    loginClient = await anonymous(playwright);
  const module = await import(
    pathToFileURL(resolve(backendRoot, 'dist/auth.js')).href
  );
  const newPassword = 'Concurrent-Reset-Test-Only-2026!';
  const encoded = await module.passwordHash(newPassword);
  let transaction = false;
  try {
    await client.query('BEGIN');
    transaction = true;
    await client.query('SELECT 1 FROM app_users WHERE id=$1 FOR UPDATE', [
      session.user.id,
    ]);
    const pending = loginClient.post(`${API_URL}/auth/login`, {
      data: { email: session.user.email, password: TEST_PASSWORD },
    });
    await expect
      .poll(async () =>
        Number(
          (
            await pool.query(
              "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND application_name='wiut-hackathon' AND wait_event_type='Lock' AND query LIKE 'SELECT * FROM app_users WHERE id=$1 FOR UPDATE%'",
            )
          ).rows[0].count,
        ),
      )
      .toBeGreaterThan(0);
    await client.query('UPDATE app_users SET password_hash=$2 WHERE id=$1', [
      session.user.id,
      encoded,
    ]);
    await client.query('COMMIT');
    transaction = false;
    expect((await pending).status()).toBe(401);
    expect((await loginClient.storageState()).cookies).toEqual([]);

    await client.query('BEGIN');
    transaction = true;
    await client.query('SELECT 1 FROM app_users WHERE id=$1 FOR UPDATE', [
      session.user.id,
    ]);
    const pendingMutation = request.post(`${API_URL}/auth/recovery-key`, {
      data: { current_password: newPassword },
    });
    await expect
      .poll(async () =>
        Number(
          (
            await pool.query(
              "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND application_name='wiut-hackathon' AND wait_event_type='Lock' AND query LIKE 'SELECT * FROM app_users WHERE id=$1 FOR UPDATE%'",
            )
          ).rows[0].count,
        ),
      )
      .toBeGreaterThan(0);
    await client.query('DELETE FROM auth_sessions WHERE user_id=$1', [
      session.user.id,
    ]);
    await client.query('COMMIT');
    transaction = false;
    expect((await pendingMutation).status()).toBe(401);
    expect(
      (
        await pool.query(
          'SELECT account_recovery_key_hash FROM app_users WHERE id=$1',
          [session.user.id],
        )
      ).rows[0].account_recovery_key_hash,
    ).toBeNull();
  } finally {
    if (transaction) await client.query('ROLLBACK');
    client.release();
    await pool.end();
    await loginClient.dispose();
  }
});
