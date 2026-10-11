import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  BusinessDetailSchema,
  ScoreRequestSchema,
  ShowcaseGenerateSchema,
} from '@wiut/contracts';
import type { AuthContext } from './auth-types.js';
import { businessDetail } from './business.js';
import { loadConfig } from './config.js';
import { Database } from './database.js';
import type { MlClient } from './ml.js';
import { ApiProblem } from './problem.js';
import { ProductService } from './service.js';
import {
  generateShowcaseBusinesses,
  resolveShowcaseParameters,
} from './showcase.js';

const auth: AuthContext = {
  user: {
    id: '11111111-1111-4111-8111-111111111111',
    email: 'officer@example.test',
    display_name: 'Showcase officer',
  },
  tenant: {
    id: '22222222-2222-4222-8222-222222222222',
    name: 'Explicit showcase',
    role: 'officer',
    kind: 'showcase',
  },
  tenants: [],
  csrf_token: 'a'.repeat(43),
  session_hash: 'test-session',
};
const parameters = (input: object = {}) =>
  resolveShowcaseParameters(
    ShowcaseGenerateSchema.parse({ end_month: '2026-09', ...input }),
    new Date('2026-10-11T00:00:00Z'),
  );
const status = (expected: number) => (error: unknown) =>
  error instanceof ApiProblem && error.status === expected;

test('showcase scenarios reproduce transactions and provenance while keeping each case identity unique', () => {
  const first = generateShowcaseBusinesses(parameters());
  const second = generateShowcaseBusinesses(parameters());
  assert.equal(first.length, 6);
  assert.equal(new Set([...first, ...second].map((row) => row.id)).size, 12);
  for (const [index, business] of first.entries()) {
    assert.deepEqual(business.transactions, second[index]!.transactions);
    assert.deepEqual(
      business.showcase_provenance,
      second[index]!.showcase_provenance,
    );
    const detail = BusinessDetailSchema.parse(businessDetail(business));
    assert.equal(detail.data_source, 'synthetic');
    assert.equal(detail.amount_unit, 'UZS');
    assert.equal(detail.history_months, index === 5 ? 4 : 24);
    assert.equal(detail.transaction_count, detail.history_months * 28);
    assert.equal(detail.showcase_provenance!.batch_index, index);
    ScoreRequestSchema.parse({
      business_id: business.id,
      as_of_date: '2026-09-30',
      transactions: business.transactions,
    });
  }
  const changed = generateShowcaseBusinesses(parameters({ seed: 7262 }));
  assert.notDeepEqual(first[0]!.transactions, changed[0]!.transactions);
  assert.equal(businessDetail(first[0]!).trend, 'stable');
  assert.equal(businessDetail(first[2]!).trend, 'growing');
  assert.equal(businessDetail(first[3]!).trend, 'declining');
});

test('maximum showcase values stay valid; month-end defaults use completed UTC months', () => {
  const maximum = parameters({
    seed: 4294967295,
    monthly_revenue_uzs: 1000000000,
    months: 36,
  });
  for (const business of generateShowcaseBusinesses(maximum))
    ScoreRequestSchema.parse({
      business_id: business.id,
      as_of_date: '2026-09-30',
      transactions: business.transactions,
    });
  assert.equal(
    resolveShowcaseParameters(
      ShowcaseGenerateSchema.parse({}),
      new Date('2026-01-01T00:00:00Z'),
    ).end_month,
    '2025-12',
  );
  assert.throws(() => parameters({ end_month: '2026-10' }), status(400));
  assert.throws(
    () => parameters({ end_month: '2000-01', months: 36 }),
    status(400),
  );
});

test('production generation is explicitly limited to showcase workspaces and actual imports stay in banks', async () => {
  let saved = 0;
  const database = {
    generateShowcase: async (
      rows: unknown[],
      requestId: string,
      context: AuthContext,
    ) => {
      assert.equal(rows.length, 2);
      assert.equal(requestId, 'test-generate');
      assert.equal(context.tenant.kind, 'showcase');
      saved++;
    },
  } as unknown as Database;
  const service = new ProductService(
    database,
    {} as MlClient,
    loadConfig({ NODE_ENV: 'production' }),
  );
  const bank = { ...auth, tenant: { ...auth.tenant, kind: 'bank' as const } };
  await assert.rejects(
    service.generateShowcase({ count: 2 }, 'test-generate', bank),
    status(403),
  );
  assert.equal(saved, 0);
  const response = await service.generateShowcase(
    { count: 2, scenario: 'stable', end_month: '2026-09' },
    'test-generate',
    auth,
  );
  assert.equal(saved, 1);
  assert.ok(
    response.items.every(
      (row) => row.showcase_provenance?.scenario === 'stable',
    ),
  );
  await assert.rejects(
    service.importBusiness({}, 'test-import', auth),
    status(409),
  );
});

function fakeDatabase(
  options: {
    kind?: string;
    count?: number;
    session?: boolean;
    failAudit?: boolean;
  } = {},
) {
  const queries: { sql: string; values: unknown[] }[] = [];
  let released = false;
  const client = {
    query: async (sql: string, values: unknown[] = []) => {
      queries.push({ sql, values });
      if (sql.startsWith('SELECT kind'))
        return { rows: [{ kind: options.kind ?? 'showcase' }], rowCount: 1 };
      if (sql.startsWith('SELECT 1 FROM auth_sessions'))
        return { rows: [], rowCount: options.session === false ? 0 : 1 };
      if (sql.startsWith('SELECT count'))
        return { rows: [{ count: String(options.count ?? 0) }], rowCount: 1 };
      if (sql.startsWith('INSERT INTO audit_events') && options.failAudit)
        throw new Error('Audit storage unavailable');
      return { rows: [], rowCount: 1 };
    },
    release: () => {
      released = true;
    },
  };
  const database = Object.assign(Object.create(Database.prototype), {
    pool: { connect: async () => client },
  }) as Database;
  return { database, queries, released: () => released };
}

test('showcase persistence locks the tenant before capacity checks, verifies current session, and records reproducible provenance', async () => {
  const fixture = fakeDatabase({ count: 98 });
  const businesses = generateShowcaseBusinesses(parameters({ count: 2 }));
  await fixture.database.generateShowcase(businesses, 'test-generate', auth);
  assert.ok(fixture.queries[1]!.sql.endsWith('FOR KEY SHARE'));
  assert.ok(fixture.queries[2]!.sql.endsWith('FOR UPDATE'));
  assert.deepEqual(fixture.queries[3]!.values, [
    auth.session_hash,
    auth.user.id,
    auth.tenant.id,
    auth.csrf_token,
  ]);
  const inserts = fixture.queries.filter((row) =>
    row.sql.startsWith('INSERT INTO businesses'),
  );
  const audits = fixture.queries.filter((row) =>
    row.sql.startsWith('INSERT INTO audit_events'),
  );
  assert.equal(inserts.length, 2);
  assert.equal(audits.length, 2);
  const metadata = JSON.parse(audits[0]!.values[6] as string);
  assert.deepEqual(metadata.provenance, businesses[0]!.showcase_provenance);
  assert.equal(metadata.purpose, 'testing_and_showcase_only');
  assert.equal(audits[0]!.values[3], 'showcase_business_generated');
  assert.equal(audits[0]!.values[7], auth.tenant.id);
  assert.equal(fixture.queries.at(-1)!.sql, 'COMMIT');
  assert.ok(fixture.released());
});

test('showcase persistence rejects bank tenants, stale sessions and overflow without inserts; audit failure rolls back the complete batch', async () => {
  const businesses = generateShowcaseBusinesses(parameters({ count: 2 }));
  for (const [options, expected] of [
    [{ kind: 'bank' }, 403],
    [{ session: false }, 409],
    [{ count: 99 }, 409],
  ] as const) {
    const fixture = fakeDatabase(options);
    await assert.rejects(
      fixture.database.generateShowcase(businesses, 'test-generate', auth),
      status(expected),
    );
    assert.equal(
      fixture.queries.some((row) =>
        row.sql.startsWith('INSERT INTO businesses'),
      ),
      false,
    );
    assert.equal(fixture.queries.at(-1)!.sql, 'ROLLBACK');
    assert.ok(fixture.released());
  }
  const fixture = fakeDatabase({ failAudit: true });
  await assert.rejects(
    fixture.database.generateShowcase(businesses, 'test-generate', auth),
    /Audit storage unavailable/,
  );
  assert.equal(fixture.queries.at(-1)!.sql, 'ROLLBACK');
  assert.ok(fixture.released());
  assert.equal(
    fixture.queries.some((row) => row.sql === 'COMMIT'),
    false,
  );
});
