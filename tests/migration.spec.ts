import { randomUUID, createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { expect, test } from '@playwright/test';
import { ScoreResponseSchema } from '../libs/common/api-contracts/src/index';
import { FIXTURE_URL, AS_OF_DATE, importInput } from './helpers';

// The database is created and dropped by this test. It never alters a developer
// database, and all legacy observations/model responses are explicit fixtures.
test('legacy migration archives once without reseeding or losing accounts, assessments, decisions, or historical access', async ({
  request,
}) => {
  test.setTimeout(60_000);
  const backendRoot = resolve(__dirname, '../apps/backend/user/user-app-api');
  const backendRequire = createRequire(resolve(backendRoot, 'package.json'));
  backendRequire('reflect-metadata');
  const { Pool } = backendRequire('pg');
  const { Database } = await import(
    pathToFileURL(resolve(backendRoot, 'dist/database.js')).href
  );
  const { ProductService } = await import(
    pathToFileURL(resolve(backendRoot, 'dist/service.js')).href
  );
  const { passwordHash, verifyPassword } = await import(
    pathToFileURL(resolve(backendRoot, 'dist/auth.js')).href
  );
  const databaseName = `wiut_migration_test_${randomUUID().replaceAll('-', '')}`;
  const connectionUrl = new URL(
    process.env.WIUT_TEST_DATABASE_URL ??
      'postgresql://wiut:wiut_dev@127.0.0.1:55432/wiut_test',
  );
  const administration = new Pool({ connectionString: connectionUrl.href });
  connectionUrl.pathname = `/${databaseName}`;
  let database: InstanceType<typeof Database> | undefined;
  let created = false;
  try {
    await administration.query(`CREATE DATABASE "${databaseName}"`);
    created = true;
    database = new Database({ DATABASE_URL: connectionUrl.href });
    const tenantId = randomUUID();
    const userId = randomUUID();
    const businessIds = Array.from(
      { length: 6 },
      () => `legacy-${randomUUID()}`,
    );
    const assessmentIds = [randomUUID(), randomUUID()];
    const decisionId = randomUUID();
    const legacyAuditId = randomUUID();
    const legacyPassword = 'Test-only-Legacy-Passphrase-2026!';
    const password = await passwordHash(legacyPassword);
    const transactions = importInput().transactions.map(
      ({ amount, ...rest }) => ({
        ...rest,
        amount_index: amount / 100_000,
      }),
    );
    const scoringInput = {
      business_id: businessIds[0],
      as_of_date: AS_OF_DATE,
      currency: 'UZS',
      requested_amount: null,
      transactions,
    };
    const scored = await request.post(`${FIXTURE_URL}/score`, {
      data: scoringInput,
    });
    expect(scored.status()).toBe(200);
    const result = ScoreResponseSchema.parse(await scored.json());
    const inputHash = createHash('sha256')
      .update(JSON.stringify(scoringInput))
      .digest('hex');
    await database.pool.query(`
      CREATE TABLE app_users(id uuid PRIMARY KEY,email text NOT NULL UNIQUE,display_name text NOT NULL,password_hash text NOT NULL,created_at timestamptz NOT NULL DEFAULT now());
      CREATE TABLE tenants(id uuid PRIMARY KEY,name text NOT NULL,is_legacy boolean NOT NULL DEFAULT false,created_at timestamptz NOT NULL DEFAULT now());
      CREATE TABLE memberships(user_id uuid NOT NULL REFERENCES app_users(id),tenant_id uuid NOT NULL REFERENCES tenants(id),role text NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(user_id,tenant_id));
      CREATE TABLE synthetic_businesses(id text PRIMARY KEY,name text NOT NULL,sector text NOT NULL,location text NOT NULL,archetype text NOT NULL,transactions jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),tenant_id uuid NOT NULL REFERENCES tenants(id));
      CREATE TABLE assessments(id uuid PRIMARY KEY,business_id text NOT NULL REFERENCES synthetic_businesses(id),requested_amount double precision,as_of_date date NOT NULL,status text NOT NULL,request_id text NOT NULL,input_hash text NOT NULL,request_input jsonb NOT NULL,result jsonb,error text,created_at timestamptz NOT NULL DEFAULT now(),completed_at timestamptz,tenant_id uuid NOT NULL REFERENCES tenants(id));
      CREATE TABLE decisions(id uuid PRIMARY KEY,assessment_id uuid NOT NULL UNIQUE REFERENCES assessments(id),decision text NOT NULL,reviewer_name text NOT NULL,notes text NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),tenant_id uuid NOT NULL REFERENCES tenants(id),reviewer_user_id uuid REFERENCES app_users(id));
      CREATE TABLE audit_events(id uuid PRIMARY KEY,business_id text NOT NULL REFERENCES synthetic_businesses(id),assessment_id uuid REFERENCES assessments(id),event_type text NOT NULL,request_id text NOT NULL,actor text NOT NULL,metadata jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),tenant_id uuid NOT NULL REFERENCES tenants(id),actor_user_id uuid REFERENCES app_users(id));
    `);
    await database.pool.query('INSERT INTO tenants(id,name) VALUES($1,$2)', [
      tenantId,
      'Legacy test bank',
    ]);
    await database.pool.query(
      'INSERT INTO app_users(id,email,display_name,password_hash) VALUES($1,$2,$3,$4)',
      [userId, 'legacy@example.test', 'Legacy Test Officer', password],
    );
    await database.pool.query(
      "INSERT INTO memberships(user_id,tenant_id,role) VALUES($1,$2,'admin')",
      [userId, tenantId],
    );
    for (const [index, id] of businessIds.entries()) {
      await database.pool.query(
        'INSERT INTO synthetic_businesses(id,name,sector,location,archetype,transactions,tenant_id) VALUES($1,$2,$3,$4,$5,$6::jsonb,$7)',
        [
          id,
          `Legacy test case ${index}`,
          'Test retail',
          'Test district',
          'test_fixture',
          JSON.stringify(transactions),
          tenantId,
        ],
      );
    }
    for (const id of assessmentIds) {
      await database.pool.query(
        "INSERT INTO assessments(id,business_id,requested_amount,as_of_date,status,request_id,input_hash,request_input,result,tenant_id) VALUES($1,$2,NULL,$3,'completed',$4,$5,$6::jsonb,$7::jsonb,$8)",
        [
          id,
          businessIds[0],
          AS_OF_DATE,
          `legacy-request-${id}`,
          inputHash,
          JSON.stringify(scoringInput),
          JSON.stringify(result),
          tenantId,
        ],
      );
    }
    await database.pool.query(
      "INSERT INTO decisions(id,assessment_id,decision,reviewer_name,notes,tenant_id,reviewer_user_id) VALUES($1,$2,'needs_information','Legacy Test Officer','Preserve this original human review.',$3,$4)",
      [decisionId, assessmentIds[0], tenantId, userId],
    );
    await database.pool.query(
      "INSERT INTO audit_events(id,business_id,assessment_id,event_type,request_id,actor,metadata,tenant_id,actor_user_id) VALUES($1,$2,$3,'decision_recorded','legacy-audit-request','Legacy Test Officer',$4::jsonb,$5,$6)",
      [
        legacyAuditId,
        businessIds[0],
        assessmentIds[0],
        JSON.stringify({ decision_id: decisionId, actor_user_id: userId }),
        tenantId,
        userId,
      ],
    );

    const snapshot = async () => ({
      users: (
        await database!.pool.query(
          'SELECT id,email,display_name,password_hash,created_at FROM app_users ORDER BY id',
        )
      ).rows,
      members: (
        await database!.pool.query(
          'SELECT * FROM memberships ORDER BY user_id,tenant_id',
        )
      ).rows,
      assessments: (
        await database!.pool.query(
          'SELECT id,business_id,requested_amount,as_of_date,status,request_id,input_hash,request_input,result,error,created_at,completed_at,tenant_id FROM assessments ORDER BY id',
        )
      ).rows,
      decisions: (
        await database!.pool.query('SELECT * FROM decisions ORDER BY id')
      ).rows,
      legacyAudit: (
        await database!.pool.query('SELECT * FROM audit_events WHERE id=$1', [
          legacyAuditId,
        ])
      ).rows,
    });
    const original = await snapshot();
    const auth = {
      user: {
        id: userId,
        email: 'legacy@example.test',
        display_name: 'Legacy Test Officer',
      },
      tenant: { id: tenantId, name: 'Legacy test bank', role: 'admin' },
      tenants: [],
      csrf_token: 'a'.repeat(43),
      session_hash: 'test-only-legacy-session',
    };
    let firstArchives: unknown;
    let firstAudit: unknown;
    for (let startup = 0; startup < 2; startup++) {
      await database.onModuleInit();
      expect(await snapshot()).toEqual(original);
      expect(
        (
          await database.pool.query(
            'SELECT mfa_secret_encrypted,mfa_pending_secret_encrypted,mfa_pending_expires_at,mfa_last_counter,account_recovery_key_hash FROM app_users ORDER BY id',
          )
        ).rows,
      ).toEqual([
        {
          mfa_secret_encrypted: null,
          mfa_pending_secret_encrypted: null,
          mfa_pending_expires_at: null,
          mfa_last_counter: null,
          account_recovery_key_hash: null,
        },
      ]);
      expect(
        (
          await database.pool.query(
            'SELECT count(*)::int AS count FROM mfa_recovery_codes',
          )
        ).rows[0].count,
      ).toBe(0);
      expect(
        (
          await database.pool.query(
            "SELECT count(*)::int AS count FROM schema_migrations WHERE name='account-security-v1'",
          )
        ).rows[0].count,
      ).toBe(1);
      expect(
        await verifyPassword(legacyPassword, original.users[0].password_hash),
      ).toBe(true);
      const businesses = (
        await database.pool.query(
          'SELECT id,data_source,amount_unit,archived_at FROM businesses ORDER BY id',
        )
      ).rows;
      expect(businesses).toHaveLength(6);
      expect(
        businesses.every(
          (row: {
            data_source: string;
            amount_unit: string;
            archived_at: Date | null;
          }) =>
            row.data_source === 'synthetic' &&
            row.amount_unit === 'index' &&
            row.archived_at instanceof Date,
        ),
      ).toBe(true);
      const archiveAudit = (
        await database.pool.query(
          "SELECT * FROM audit_events WHERE event_type='business_archived' ORDER BY business_id",
        )
      ).rows;
      expect(archiveAudit).toHaveLength(6);
      expect(
        (
          await database.pool.query(
            "SELECT count(*)::int AS count FROM schema_migrations WHERE name='archive-synthetic-portfolio-v2'",
          )
        ).rows[0].count,
      ).toBe(1);
      if (startup === 0) {
        firstArchives = businesses;
        firstAudit = archiveAudit;
      } else {
        expect(businesses).toEqual(firstArchives);
        expect(archiveAudit).toEqual(firstAudit);
      }
      expect(await database.businesses(tenantId)).toEqual([]);
      expect(await database.assessments(tenantId)).toEqual([]);
      expect(await database.auditEvents(tenantId)).toEqual([]);
      const service = new ProductService(database, {}, {});
      const detail = await service.business(businessIds[0], auth);
      expect(detail.archived_at).toBeTruthy();
      expect(detail.amount_unit).toBe('index');
      expect(
        (await service.assessments(auth, businessIds[0])).items,
      ).toHaveLength(2);
      const assessment = await service.assessment(assessmentIds[0], auth);
      expect(assessment.result).toEqual(result);
      expect(assessment.input_hash).toBe(inputHash);
      expect(assessment.decision?.id).toBe(decisionId);
      expect(assessment.decision?.reviewer_user_id).toBe(userId);
      expect(
        (await service.audit(auth, businessIds[0])).items.map(
          (event: { id: string }) => event.id,
        ),
      ).toEqual(expect.arrayContaining([legacyAuditId]));
    }
    expect(
      (
        await database.pool.query(
          'SELECT count(*)::int AS count FROM app_users',
        )
      ).rows[0].count,
    ).toBe(1);
    expect(
      (
        await database.pool.query(
          'SELECT count(*)::int AS count FROM assessments',
        )
      ).rows[0].count,
    ).toBe(2);
    const service = new ProductService(database, {}, {});
    await expect(
      service.createAssessment(
        {
          business_id: businessIds[0],
          as_of_date: AS_OF_DATE,
        },
        'test-only-archived-attempt',
        auth,
      ),
    ).rejects.toMatchObject({
      status: 409,
      title: 'Business archived',
    });
    expect(
      (await service.audit(auth, businessIds[0])).items.filter(
        (event: { request_id: string; event_type: string }) =>
          event.request_id === 'test-only-archived-attempt' &&
          event.event_type === 'assessment_rejected',
      ),
    ).toHaveLength(1);
    const foreign = { ...auth, tenant: { ...auth.tenant, id: randomUUID() } };
    await expect(
      service.business(businessIds[0], foreign),
    ).rejects.toMatchObject({ status: 404 });
    await expect(
      service.assessment(assessmentIds[0], foreign),
    ).rejects.toMatchObject({ status: 404 });
    expect(await snapshot()).toEqual(original);
  } finally {
    if (database) await database.onModuleDestroy();
    if (created)
      await administration.query(
        `DROP DATABASE "${databaseName}" WITH (FORCE)`,
      );
    await administration.end();
  }
});
