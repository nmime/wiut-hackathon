import { test } from 'node:test';
import assert from 'node:assert/strict';
import type { ExecutionContext } from '@nestjs/common';
import type { Reflector } from '@nestjs/core';
import type { FastifyReply, FastifyRequest } from 'fastify';
import Fastify from 'fastify';
import { AuthSessionSchema } from '@wiut/contracts';
import {
  AuthGuard,
  AuthService,
  assertCsrf,
  invitationView,
  passwordHash,
  readSessionCookie,
  secretToken,
  tokenHash,
  verifyPassword,
} from './auth.js';
import type { AuthContext } from './auth-types.js';
import { loadConfig, trustProxyPolicy } from './config.js';
import type { Database } from './database.js';
import { ApiProblem } from './problem.js';

const auth: AuthContext = {
  user: {
    id: '11111111-1111-4111-8111-111111111111',
    email: 'officer@example.test',
    display_name: 'Authenticated officer',
  },
  tenant: {
    id: '22222222-2222-4222-8222-222222222222',
    name: 'Test bank',
    kind: 'bank',
    role: 'officer',
  },
  tenants: [],
  csrf_token: 'a'.repeat(43),
  session_hash: 'hashed-session',
};
const request = (
  headers: Record<string, string | undefined> = {},
  method = 'POST',
) =>
  ({
    headers,
    method,
    ip: '127.0.0.1',
    id: 'auth-unit-request',
  }) as FastifyRequest;
const status = (number: number) => (error: unknown) =>
  error instanceof ApiProblem && error.status === number;

test('passwords use randomized scrypt salts and reject wrong or absent credentials', async () => {
  const first = await passwordHash('correct-horse-battery-staple');
  const second = await passwordHash('correct-horse-battery-staple');
  assert.match(first, /^scrypt-v1\$[A-Za-z0-9_-]{22}\$[A-Za-z0-9_-]{86}$/);
  assert.notEqual(first, second);
  assert.ok(!first.includes('correct-horse'));
  assert.equal(
    await verifyPassword('correct-horse-battery-staple', first),
    true,
  );
  assert.equal(await verifyPassword('incorrect-password', first), false);
  assert.equal(await verifyPassword('incorrect-password', undefined), false);
  assert.equal(await verifyPassword('incorrect-password', 'malformed'), false);
});

test('session cookies reject duplicate or malformed tokens and never use raw tokens as storage keys', () => {
  const token = secretToken();
  assert.equal(token.length, 43);
  assert.match(tokenHash(token), /^[a-f0-9]{64}$/);
  assert.notEqual(tokenHash(token), token);
  assert.equal(
    readSessionCookie(`other=1; wiut_session=${token}`, 'wiut_session'),
    token,
  );
  for (const header of [
    undefined,
    'wiut_session=short',
    `wiut_session=${token}; wiut_session=${token}`,
    `__Host-wiut_session=${token}`,
  ])
    assert.equal(readSessionCookie(header, 'wiut_session'), null);
});

test('CSRF requires exact token and rejects absent, array, short or forged tokens', () => {
  assert.doesNotThrow(() => assertCsrf(auth.csrf_token, auth.csrf_token));
  for (const token of [undefined, [auth.csrf_token], 'a', 'b'.repeat(43)])
    assert.throws(() => assertCsrf(token, auth.csrf_token), status(403));
});

test('origin validation is exact and does not trust forwarded headers', () => {
  const service = new AuthService({} as Database, loadConfig({}));
  assert.doesNotThrow(() =>
    service.assertOrigin(request({ origin: 'http://localhost:5173' })),
  );
  for (const headers of [
    {},
    { origin: 'https://evil.example' },
    { origin: 'http://localhost:5173.evil.example' },
    { origin: 'http://localhost:5173', 'sec-fetch-site': 'cross-site' },
    { 'x-forwarded-host': 'localhost:5173' },
  ])
    assert.throws(() => service.assertOrigin(request(headers)), status(403));
});

test('authentication limiter checks IP even when attackers change email', async () => {
  const database = {
    pool: { query: async () => ({ rows: [] }) },
  } as unknown as Database;
  const service = new AuthService(
    database,
    loadConfig({ AUTH_RATE_LIMIT_MAX: '1' }),
  );
  const reply = {} as FastifyReply;
  await assert.rejects(
    service.login(
      { email: 'a@example.test', password: 'incorrect-password' },
      request({ origin: 'http://localhost:5173' }),
      reply,
    ),
    status(401),
  );
  await assert.rejects(
    service.login(
      { email: 'b@example.test', password: 'incorrect-password' },
      request({ origin: 'http://localhost:5173' }),
      reply,
    ),
    status(429),
  );
});

test('authenticated mutation guard rejects missing CSRF before product execution', async () => {
  const service = {
    authenticate: async () => auth,
    assertOrigin: () => {},
  } as unknown as AuthService;
  const reflector = { getAllAndOverride: () => false } as unknown as Reflector;
  const guard = new AuthGuard(service, reflector);
  let req = request();
  const context = {
    getHandler: () => {},
    getClass: () => {},
    switchToHttp: () => ({ getRequest: () => req }),
  } as unknown as ExecutionContext;
  await assert.rejects(guard.canActivate(context), status(403));
  req.headers['x-csrf-token'] = auth.csrf_token;
  assert.equal(await guard.canActivate(context), true);
  req = request({}, 'GET');
  assert.equal(await guard.canActivate(context), true);
});

test('production defaults require Secure host cookie, with explicit local HTTP override only', () => {
  const production = loadConfig({ NODE_ENV: 'production' });
  assert.equal(production.SESSION_COOKIE_SECURE, true);
  assert.equal(
    new AuthService({} as Database, production).cookieName,
    '__Host-wiut_session',
  );
  const local = loadConfig({
    NODE_ENV: 'production',
    SESSION_COOKIE_SECURE: 'false',
  });
  assert.equal(
    new AuthService({} as Database, local).cookieName,
    'wiut_session',
  );
  assert.throws(() => loadConfig({ SESSION_COOKIE_SECURE: 'yes' }));
  assert.throws(() => loadConfig({ SESSION_TTL_HOURS: '169' }));
});

test('proxy trust is disabled by default and accepts only explicit zero or one hop', () => {
  assert.equal(loadConfig({}).TRUST_PROXY_HOPS, 0);
  assert.equal(loadConfig({ TRUST_PROXY_HOPS: '0' }).TRUST_PROXY_HOPS, 0);
  assert.equal(loadConfig({ TRUST_PROXY_HOPS: '1' }).TRUST_PROXY_HOPS, 1);
  for (const value of ['-1', '2', '1.5', 'true'])
    assert.throws(() => loadConfig({ TRUST_PROXY_HOPS: value }));
});

test('Fastify ignores forged forwarded IP by default and trusts only the nearest configured hop', async () => {
  for (const hops of [0, 1]) {
    const config = loadConfig({ TRUST_PROXY_HOPS: String(hops) });
    const server = Fastify({ trustProxy: trustProxyPolicy(config) });
    try {
      server.get('/ip', async (request) => ({ ip: request.ip }));
      const reply = await server.inject({
        method: 'GET',
        url: '/ip',
        remoteAddress: '198.51.100.8',
        headers: { 'x-forwarded-for': '10.0.0.1, 203.0.113.6' },
      });
      assert.equal(reply.statusCode, 200);
      assert.equal(
        reply.json().ip,
        hops === 0 ? '198.51.100.8' : '203.0.113.6',
      );
    } finally {
      await server.close();
    }
  }
});

test('expected tenant guard rejects stale reads and mutations but permits session refresh', async () => {
  const service = {
    authenticate: async () => auth,
    assertOrigin: () => {},
  } as unknown as AuthService;
  let refresh = false;
  const reflector = {
    getAllAndOverride: (key: string) =>
      key === 'wiut:session-refresh' && refresh,
  } as unknown as Reflector;
  const guard = new AuthGuard(service, reflector);
  let req = request(
    { 'x-tenant-id': '33333333-3333-4333-8333-333333333333' },
    'GET',
  );
  const context = {
    getHandler: () => {},
    getClass: () => {},
    switchToHttp: () => ({ getRequest: () => req }),
  } as unknown as ExecutionContext;
  await assert.rejects(guard.canActivate(context), status(409));
  req = request({
    'x-tenant-id': '33333333-3333-4333-8333-333333333333',
    'x-csrf-token': auth.csrf_token,
  });
  await assert.rejects(guard.canActivate(context), status(409));
  req = request({ 'x-tenant-id': auth.tenant.id }, 'GET');
  assert.equal(await guard.canActivate(context), true);
  refresh = true;
  req = request({ 'x-tenant-id': 'stale' }, 'GET');
  assert.equal(await guard.canActivate(context), true);
});

test('session response strips storage hashes and administrator operations reject officers', async () => {
  const service = new AuthService({} as Database, loadConfig({}));
  assert.deepEqual(service.session(auth), AuthSessionSchema.parse(auth));
  assert.equal('session_hash' in service.session(auth), false);
  await assert.rejects(service.team(auth), status(403));
  await assert.rejects(
    service.createInvitation(
      { email: 'join@example.test', role: 'officer' },
      auth,
      'test-request',
      'http://localhost:5173',
    ),
    status(403),
  );
  await assert.rejects(
    service.revokeInvitation('unknown', auth, 'test-request'),
    status(403),
  );
});

test('invitation list view removes stored secrets and distinguishes expired/revoked/accepted', () => {
  const row = {
    id: 'invite',
    tenant_id: auth.tenant.id,
    email: 'join@example.test',
    role: 'officer' as const,
    created_at: new Date('2026-01-01T00:00:00Z'),
    expires_at: new Date('2099-01-01T00:00:00Z'),
    accepted_by: null,
    revoked_at: null,
    token_hash: 'storage-secret',
  };
  assert.equal(invitationView(row).status, 'pending');
  assert.equal('token_hash' in invitationView(row), false);
  assert.equal('tenant_id' in invitationView(row), false);
  assert.equal(
    invitationView({ ...row, expires_at: new Date('2020-01-01T00:00:00Z') })
      .status,
    'expired',
  );
  assert.equal(
    invitationView({ ...row, revoked_at: new Date() }).status,
    'revoked',
  );
  assert.equal(
    invitationView({ ...row, accepted_by: auth.user.id }).status,
    'accepted',
  );
});

test('an expired or unknown session never authenticates and token lookups use only hashes', async () => {
  const token = secretToken();
  let calls = 0;
  const database = {
    pool: {
      query: async (sql: string, values: string[]) => {
        calls++;
        assert.ok(sql.includes('s.expires_at>now()'));
        assert.equal(values[0], tokenHash(token));
        assert.notEqual(values[0], token);
        return { rows: [] };
      },
    },
  } as unknown as Database;
  const service = new AuthService(database, loadConfig({}));
  await assert.rejects(
    service.authenticate(request({ cookie: `wiut_session=${token}` }, 'GET')),
    status(401),
  );
  await assert.rejects(service.authenticate(request({}, 'GET')), status(401));
  assert.equal(calls, 1);
});
