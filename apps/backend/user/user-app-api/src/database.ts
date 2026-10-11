import { Injectable, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { randomUUID } from 'node:crypto';
import { Pool, type PoolClient } from 'pg';
import type {
  Assessment,
  AuditEvent,
  Decision,
  DecisionInput,
  ScoreRequest,
  ScoreResponse,
} from '@wiut/contracts';
import type { AppConfig } from './config.js';
import { ApiProblem } from './problem.js';
import type { AuthContext } from './auth-types.js';
import type { StoredBusiness } from './business.js';

interface AssessmentRow {
  id: string;
  business_id: string;
  requested_amount: number | null;
  amount_unit: 'UZS' | 'index';
  as_of_date: string;
  status: 'pending' | 'completed' | 'failed';
  created_at: Date;
  request_id: string;
  input_hash: string;
  result: ScoreResponse | null;
  error: string | null;
  decision: (Omit<Decision, 'created_at'> & { created_at: string }) | null;
}
const selection = `SELECT a.id, a.business_id, a.requested_amount, to_char(a.as_of_date, 'YYYY-MM-DD') AS as_of_date,
  a.amount_unit, a.status, a.created_at, a.request_id, a.input_hash, a.result, a.error,
  CASE WHEN d.id IS NULL THEN NULL ELSE jsonb_build_object('id', d.id, 'assessment_id', d.assessment_id,
    'decision', d.decision, 'reviewer_name', d.reviewer_name, 'reviewer_user_id', d.reviewer_user_id, 'notes', d.notes, 'created_at', d.created_at) END AS decision
  FROM assessments a JOIN businesses b ON b.id=a.business_id AND b.tenant_id=a.tenant_id LEFT JOIN decisions d ON d.assessment_id = a.id AND d.tenant_id=a.tenant_id`;

@Injectable()
export class Database implements OnModuleInit, OnModuleDestroy {
  readonly pool: Pool;
  constructor(config: AppConfig) {
    this.pool = new Pool({
      connectionString: config.DATABASE_URL,
      max: 10,
      connectionTimeoutMillis: 4000,
      query_timeout: 10000,
      application_name: 'wiut-hackathon',
    });
    this.pool.on('error', () => {
      console.error('A database connection was interrupted.');
    });
  }

  async onModuleInit() {
    const client = await this.pool.connect();
    try {
      await client.query('BEGIN');
      await client.query(
        "SELECT pg_advisory_xact_lock(hashtext('wiut-hackathon-schema-v1'))",
      );
      await client.query(`
        CREATE TABLE IF NOT EXISTS app_users (
          id uuid PRIMARY KEY, email text NOT NULL UNIQUE, display_name text NOT NULL,
          password_hash text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
        );
        ALTER TABLE app_users ADD COLUMN IF NOT EXISTS mfa_secret_encrypted text;
        ALTER TABLE app_users ADD COLUMN IF NOT EXISTS mfa_pending_secret_encrypted text;
        ALTER TABLE app_users ADD COLUMN IF NOT EXISTS mfa_pending_expires_at timestamptz;
        ALTER TABLE app_users ADD COLUMN IF NOT EXISTS mfa_last_counter bigint;
        ALTER TABLE app_users ADD COLUMN IF NOT EXISTS account_recovery_key_hash text;
        CREATE TABLE IF NOT EXISTS mfa_recovery_codes (
          user_id uuid NOT NULL REFERENCES app_users(id), code_hash text NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(user_id,code_hash)
        );
        CREATE TABLE IF NOT EXISTS tenants (
          id uuid PRIMARY KEY, name text NOT NULL, is_legacy boolean NOT NULL DEFAULT false,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        INSERT INTO tenants(id,name,is_legacy) VALUES('00000000-0000-4000-8000-000000000001','Legacy demonstration',true) ON CONFLICT(id) DO NOTHING;
        CREATE TABLE IF NOT EXISTS memberships (
          user_id uuid NOT NULL REFERENCES app_users(id), tenant_id uuid NOT NULL REFERENCES tenants(id),
          role text NOT NULL CHECK(role IN ('admin','officer')), created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY(user_id,tenant_id)
        );
        CREATE TABLE IF NOT EXISTS auth_sessions (
          token_hash text PRIMARY KEY, user_id uuid NOT NULL REFERENCES app_users(id),
          tenant_id uuid NOT NULL REFERENCES tenants(id), csrf_token text NOT NULL,
          expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
          FOREIGN KEY(user_id,tenant_id) REFERENCES memberships(user_id,tenant_id)
        );
        CREATE INDEX IF NOT EXISTS auth_sessions_expiry_idx ON auth_sessions(expires_at);
        CREATE TABLE IF NOT EXISTS invitations (
          id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenants(id), email text NOT NULL,
          role text NOT NULL CHECK(role IN ('admin','officer')), token_hash text NOT NULL UNIQUE,
          created_by uuid NOT NULL REFERENCES app_users(id), expires_at timestamptz NOT NULL,
          accepted_by uuid REFERENCES app_users(id), revoked_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS invitations_tenant_idx ON invitations(tenant_id,created_at DESC);
        CREATE TABLE IF NOT EXISTS security_events (
          id uuid PRIMARY KEY, tenant_id uuid REFERENCES tenants(id), actor_user_id uuid REFERENCES app_users(id),
          event_type text NOT NULL, request_id text NOT NULL, metadata jsonb NOT NULL DEFAULT '{}',
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS schema_migrations(name text PRIMARY KEY,applied_at timestamptz NOT NULL DEFAULT now());
        INSERT INTO schema_migrations(name) VALUES('account-security-v1') ON CONFLICT(name) DO NOTHING;
        DO $$ BEGIN
          IF to_regclass('public.synthetic_businesses') IS NOT NULL AND to_regclass('public.businesses') IS NOT NULL THEN
            RAISE EXCEPTION 'Both legacy and current business tables exist; preserve data and reconcile before startup';
          END IF;
          IF to_regclass('public.synthetic_businesses') IS NOT NULL THEN
            ALTER TABLE synthetic_businesses RENAME TO businesses;
          END IF;
        END $$;
        CREATE TABLE IF NOT EXISTS businesses (
          id text PRIMARY KEY, name text NOT NULL, sector text NOT NULL, location text NOT NULL,
          archetype text NOT NULL, transactions jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS assessments (
          id uuid PRIMARY KEY, business_id text NOT NULL REFERENCES businesses(id),
          requested_amount double precision, as_of_date date NOT NULL,
          status text NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
          request_id text NOT NULL, input_hash text NOT NULL, request_input jsonb NOT NULL,
          result jsonb, error text, created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz
        );
        CREATE INDEX IF NOT EXISTS assessments_business_created_idx ON assessments(business_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS decisions (
          id uuid PRIMARY KEY, assessment_id uuid NOT NULL UNIQUE REFERENCES assessments(id),
          decision text NOT NULL CHECK (decision IN ('approved', 'declined', 'needs_information')),
          reviewer_name text NOT NULL, notes text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS audit_events (
          id uuid PRIMARY KEY, business_id text NOT NULL REFERENCES businesses(id),
          assessment_id uuid REFERENCES assessments(id), event_type text NOT NULL, request_id text NOT NULL,
          actor text NOT NULL, metadata jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS audit_events_business_created_idx ON audit_events(business_id, created_at DESC);
        ALTER TABLE businesses ADD COLUMN IF NOT EXISTS data_source text NOT NULL DEFAULT 'synthetic' CHECK(data_source IN ('user_provided','synthetic'));
        ALTER TABLE businesses ADD COLUMN IF NOT EXISTS amount_unit text NOT NULL DEFAULT 'index' CHECK(amount_unit IN ('UZS','index'));
        ALTER TABLE businesses ADD COLUMN IF NOT EXISTS archived_at timestamptz;
        ALTER TABLE assessments ADD COLUMN IF NOT EXISTS amount_unit text NOT NULL DEFAULT 'index' CHECK(amount_unit IN ('UZS','index'));
        ALTER TABLE businesses ALTER COLUMN data_source DROP DEFAULT;
        ALTER TABLE businesses ALTER COLUMN amount_unit DROP DEFAULT;
        ALTER TABLE businesses ADD COLUMN IF NOT EXISTS tenant_id uuid REFERENCES tenants(id);
        ALTER TABLE assessments ADD COLUMN IF NOT EXISTS tenant_id uuid REFERENCES tenants(id);
        ALTER TABLE decisions ADD COLUMN IF NOT EXISTS tenant_id uuid REFERENCES tenants(id);
        ALTER TABLE decisions ADD COLUMN IF NOT EXISTS reviewer_user_id uuid REFERENCES app_users(id);
        ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS tenant_id uuid REFERENCES tenants(id);
        ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS actor_user_id uuid REFERENCES app_users(id);
        UPDATE businesses SET tenant_id='00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL;
        UPDATE assessments a SET tenant_id=b.tenant_id FROM businesses b WHERE a.business_id=b.id AND a.tenant_id IS NULL;
        UPDATE decisions d SET tenant_id=a.tenant_id FROM assessments a WHERE d.assessment_id=a.id AND d.tenant_id IS NULL;
        UPDATE audit_events e SET tenant_id=b.tenant_id FROM businesses b WHERE e.business_id=b.id AND e.tenant_id IS NULL;
        ALTER TABLE businesses ALTER COLUMN tenant_id SET NOT NULL;
        ALTER TABLE assessments ALTER COLUMN tenant_id SET NOT NULL;
        ALTER TABLE decisions ALTER COLUMN tenant_id SET NOT NULL;
        ALTER TABLE audit_events ALTER COLUMN tenant_id SET NOT NULL;
        CREATE INDEX IF NOT EXISTS businesses_tenant_created_idx ON businesses(tenant_id,created_at DESC);
        CREATE INDEX IF NOT EXISTS assessments_tenant_business_idx ON assessments(tenant_id,business_id,created_at DESC);
        CREATE INDEX IF NOT EXISTS audit_tenant_created_idx ON audit_events(tenant_id,created_at DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS businesses_tenant_id_unique ON businesses(tenant_id,id);
        CREATE UNIQUE INDEX IF NOT EXISTS assessments_tenant_id_unique ON assessments(tenant_id,id);
        DO $$ BEGIN
          IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='assessments_tenant_business_fk') THEN
            ALTER TABLE assessments ADD CONSTRAINT assessments_tenant_business_fk FOREIGN KEY(tenant_id,business_id) REFERENCES businesses(tenant_id,id);
          END IF;
          IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='decisions_tenant_assessment_fk') THEN
            ALTER TABLE decisions ADD CONSTRAINT decisions_tenant_assessment_fk FOREIGN KEY(tenant_id,assessment_id) REFERENCES assessments(tenant_id,id);
          END IF;
          IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='audit_tenant_business_fk') THEN
            ALTER TABLE audit_events ADD CONSTRAINT audit_tenant_business_fk FOREIGN KEY(tenant_id,business_id) REFERENCES businesses(tenant_id,id);
          END IF;
          IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='audit_tenant_assessment_fk') THEN
            ALTER TABLE audit_events ADD CONSTRAINT audit_tenant_assessment_fk FOREIGN KEY(tenant_id,assessment_id) REFERENCES assessments(tenant_id,id);
          END IF;
        END $$;
      `);
      const archivedMigration = await client.query(
        "SELECT 1 FROM schema_migrations WHERE name='archive-synthetic-portfolio-v2'",
      );
      if (!archivedMigration.rowCount) {
        const archived = await client.query<{
          id: string;
          tenant_id: string;
          archived_at: Date;
        }>(
          "UPDATE businesses SET archived_at=now() WHERE data_source='synthetic' AND archived_at IS NULL RETURNING id,tenant_id,archived_at",
        );
        for (const row of archived.rows)
          await this.audit(
            {
              business_id: row.id,
              assessment_id: null,
              event_type: 'business_archived',
              request_id: 'migration:archive-synthetic-portfolio-v2',
              actor: 'system',
              metadata: {
                reason: 'legacy_synthetic_portfolio',
                migration: 'archive-synthetic-portfolio-v2',
                data_source: 'synthetic',
                amount_unit: 'index',
                archived_at: row.archived_at.toISOString(),
              },
            },
            row.tenant_id,
            client,
          );
        await client.query(
          "INSERT INTO schema_migrations(name) VALUES('archive-synthetic-portfolio-v2')",
        );
      }
      // A single API process is supported. Pending attempts left by an interrupted process remain auditable.
      const interrupted = await client.query<{
        id: string;
        business_id: string;
        request_id: string;
        input_hash: string;
        tenant_id: string;
      }>(
        "UPDATE assessments SET status='failed', error='Assessment interrupted before a model response was saved.', completed_at=now() WHERE status='pending' RETURNING id,business_id,request_id,input_hash,tenant_id",
      );
      for (const row of interrupted.rows) {
        await this.audit(
          {
            business_id: row.business_id,
            assessment_id: row.id,
            event_type: 'assessment_failed',
            request_id: row.request_id,
            actor: 'system',
            metadata: {
              input_hash: row.input_hash,
              reason: 'process_interrupted',
            },
          },
          row.tenant_id,
          client,
        );
      }
      await client.query('COMMIT');
    } catch (error) {
      await client.query('ROLLBACK');
      throw error;
    } finally {
      client.release();
    }
  }

  async onModuleDestroy() {
    await this.pool.end();
  }
  async health() {
    await this.pool.query('SELECT 1');
  }
  async businesses(tenantId: string): Promise<StoredBusiness[]> {
    return (
      await this.pool.query<StoredBusiness>(
        'SELECT id,name,sector,location,archetype,transactions,data_source,amount_unit,archived_at FROM businesses WHERE tenant_id=$1 AND archived_at IS NULL ORDER BY created_at DESC,id LIMIT 200',
        [tenantId],
      )
    ).rows;
  }
  async business(id: string, tenantId: string): Promise<StoredBusiness | null> {
    return (
      (
        await this.pool.query<StoredBusiness>(
          'SELECT id,name,sector,location,archetype,transactions,data_source,amount_unit,archived_at FROM businesses WHERE id=$1 AND tenant_id=$2',
          [id, tenantId],
        )
      ).rows[0] ?? null
    );
  }

  async importBusiness(
    business: StoredBusiness,
    requestId: string,
    auth: AuthContext,
  ) {
    const client = await this.pool.connect();
    try {
      await client.query('BEGIN');
      await client.query(
        'INSERT INTO businesses(id,name,sector,location,archetype,transactions,tenant_id,data_source,amount_unit) VALUES($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9)',
        [
          business.id,
          business.name,
          business.sector,
          business.location,
          business.archetype,
          JSON.stringify(business.transactions),
          auth.tenant.id,
          business.data_source,
          business.amount_unit,
        ],
      );
      await this.audit(
        {
          business_id: business.id,
          assessment_id: null,
          event_type: 'business_imported',
          request_id: requestId,
          actor: auth.user.display_name,
          metadata: {
            data_source: business.data_source,
            amount_unit: business.amount_unit,
            amount_conversion:
              business.amount_unit === 'UZS'
                ? '1 amount_index = 1 UZS'
                : 'No currency conversion declared',
            transaction_count: business.transactions.length,
            actor_user_id: auth.user.id,
          },
        },
        auth.tenant.id,
        client,
      );
      await client.query('COMMIT');
    } catch (error) {
      await client.query('ROLLBACK');
      throw error;
    } finally {
      client.release();
    }
  }

  async beginAssessment(
    id: string,
    request: ScoreRequest,
    requestId: string,
    hash: string,
    auth: AuthContext,
  ) {
    const client = await this.pool.connect();
    try {
      await client.query('BEGIN');
      const inserted = await client.query(
        "INSERT INTO assessments(id,business_id,requested_amount,as_of_date,status,request_id,input_hash,request_input,tenant_id,amount_unit) SELECT $1,$2,$3,$4,'pending',$5,$6,$7::jsonb,$8,amount_unit FROM businesses WHERE id=$2 AND tenant_id=$8 AND archived_at IS NULL",
        [
          id,
          request.business_id,
          request.requested_amount,
          request.as_of_date,
          requestId,
          hash,
          JSON.stringify(request),
          auth.tenant.id,
        ],
      );
      if (!inserted.rowCount)
        throw new ApiProblem(
          404,
          'Business not found',
          'The business is unavailable for a new assessment.',
        );
      await this.audit(
        {
          business_id: request.business_id,
          assessment_id: id,
          event_type: 'assessment_requested',
          request_id: requestId,
          actor: auth.user.display_name,
          metadata: {
            input_hash: hash,
            transaction_count: request.transactions.length,
            requested_amount_uzs: request.requested_amount,
            as_of_date: request.as_of_date,
            actor_user_id: auth.user.id,
          },
        },
        auth.tenant.id,
        client,
      );
      await client.query('COMMIT');
    } catch (error) {
      await client.query('ROLLBACK');
      throw error;
    } finally {
      client.release();
    }
  }

  async finishAssessment(
    id: string,
    result: ScoreResponse | null,
    error: string | null,
    tenantId: string,
    failureStatus?: number,
  ) {
    const client = await this.pool.connect();
    try {
      await client.query('BEGIN');
      const completed = await client.query<{
        business_id: string;
        request_id: string;
        input_hash: string;
      }>(
        "UPDATE assessments SET status=$2,result=$3::jsonb,error=$4,completed_at=now() WHERE id=$1 AND tenant_id=$5 AND status='pending' RETURNING business_id,request_id,input_hash",
        [
          id,
          result ? 'completed' : 'failed',
          result ? JSON.stringify(result) : null,
          error,
          tenantId,
        ],
      );
      const row = completed.rows[0];
      if (!row)
        throw new ApiProblem(
          409,
          'Assessment already finalized',
          'The assessment attempt has already been finalized.',
        );
      await this.audit(
        {
          business_id: row.business_id,
          assessment_id: id,
          event_type: result ? 'assessment_completed' : 'assessment_failed',
          request_id: row.request_id,
          actor: 'system',
          metadata: {
            input_hash: row.input_hash,
            ...(result
              ? {
                  model_version: result.model_version,
                  model_request_id: result.request_id,
                  result,
                }
              : { reason: error, status: failureStatus }),
          },
        },
        tenantId,
        client,
      );
      await client.query('COMMIT');
    } catch (err) {
      await client.query('ROLLBACK');
      throw err;
    } finally {
      client.release();
    }
  }

  private mapAssessment(row: AssessmentRow): Assessment {
    if (row.status === 'pending')
      throw new ApiProblem(
        409,
        'Assessment in progress',
        'The assessment is waiting for an ML response.',
      );
    return {
      ...row,
      status: row.status,
      created_at: row.created_at.toISOString(),
      decision: row.decision
        ? {
            ...row.decision,
            created_at: new Date(row.decision.created_at).toISOString(),
          }
        : null,
    };
  }
  async assessment(id: string, tenantId: string): Promise<Assessment | null> {
    if (
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
        id,
      )
    )
      return null;
    const row = (
      await this.pool.query<AssessmentRow>(
        `${selection} WHERE a.id=$1 AND a.tenant_id=$2`,
        [id, tenantId],
      )
    ).rows[0];
    return row ? this.mapAssessment(row) : null;
  }
  async assessments(
    tenantId: string,
    businessId?: string,
  ): Promise<Assessment[]> {
    const rows = await this.pool.query<AssessmentRow>(
      `${selection} WHERE a.tenant_id=$1 AND a.status <> 'pending' ${businessId ? 'AND a.business_id=$2' : 'AND b.archived_at IS NULL'} ORDER BY a.created_at DESC,a.id LIMIT 100`,
      businessId ? [tenantId, businessId] : [tenantId],
    );
    return rows.rows.map((row) => this.mapAssessment(row));
  }
  async latestAssessment(businessId: string, tenantId: string) {
    return (
      (await this.latestAssessments([businessId], tenantId)).get(businessId) ??
      null
    );
  }

  async latestAssessments(
    businessIds: string[],
    tenantId: string,
  ): Promise<Map<string, Assessment>> {
    if (businessIds.length === 0) return new Map();
    const rows = await this.pool.query<AssessmentRow>(
      `${selection} WHERE a.tenant_id=$2 AND a.id IN (
        SELECT DISTINCT ON (business_id) id FROM assessments
        WHERE business_id = ANY($1::text[]) AND tenant_id=$2 AND status <> 'pending'
        ORDER BY business_id,created_at DESC,id
      )`,
      [businessIds, tenantId],
    );
    return new Map(
      rows.rows.map((row) => [row.business_id, this.mapAssessment(row)]),
    );
  }

  async assessmentBusinessId(
    id: string,
    tenantId: string,
  ): Promise<string | null> {
    if (
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
        id,
      )
    )
      return null;
    return (
      (
        await this.pool.query<{ business_id: string }>(
          'SELECT business_id FROM assessments WHERE id=$1 AND tenant_id=$2',
          [id, tenantId],
        )
      ).rows[0]?.business_id ?? null
    );
  }

  async recordDecision(
    id: string,
    input: DecisionInput,
    requestId: string,
    auth: AuthContext,
  ): Promise<Assessment> {
    const client = await this.pool.connect();
    try {
      await client.query('BEGIN');
      const assessment = (
        await client.query<{ business_id: string; status: string }>(
          'SELECT business_id,status FROM assessments WHERE id=$1 AND tenant_id=$2 FOR UPDATE',
          [id, auth.tenant.id],
        )
      ).rows[0];
      if (!assessment)
        throw new ApiProblem(
          404,
          'Assessment not found',
          'The requested assessment does not exist.',
        );
      if (assessment.status !== 'completed')
        throw new ApiProblem(
          409,
          'Assessment cannot be reviewed',
          'Only an assessment with a valid ML response can receive a final human review.',
        );
      if (
        (
          await client.query(
            'SELECT 1 FROM decisions WHERE assessment_id=$1 AND tenant_id=$2',
            [id, auth.tenant.id],
          )
        ).rowCount
      )
        throw new ApiProblem(
          409,
          'Decision already recorded',
          'This assessment already has a human decision. Create a new assessment to review new evidence.',
        );
      const decisionId = randomUUID();
      await client.query(
        'INSERT INTO decisions(id,assessment_id,decision,reviewer_name,notes,tenant_id,reviewer_user_id) VALUES($1,$2,$3,$4,$5,$6,$7)',
        [
          decisionId,
          id,
          input.decision,
          auth.user.display_name,
          input.notes,
          auth.tenant.id,
          auth.user.id,
        ],
      );
      await this.audit(
        {
          business_id: assessment.business_id,
          assessment_id: id,
          event_type: 'decision_recorded',
          request_id: requestId,
          actor: auth.user.display_name,
          metadata: {
            decision_id: decisionId,
            decision: input.decision,
            notes: input.notes,
            actor_user_id: auth.user.id,
          },
        },
        auth.tenant.id,
        client,
      );
      await client.query('COMMIT');
      return (await this.assessment(id, auth.tenant.id))!;
    } catch (error) {
      await client.query('ROLLBACK');
      throw error;
    } finally {
      client.release();
    }
  }

  async audit(
    event: Omit<AuditEvent, 'id' | 'created_at'>,
    tenantId: string,
    client?: PoolClient,
  ) {
    await (client ?? this.pool).query(
      'INSERT INTO audit_events(id,business_id,assessment_id,event_type,request_id,actor,metadata,tenant_id,actor_user_id) SELECT $1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9 WHERE EXISTS(SELECT 1 FROM businesses WHERE id=$2 AND tenant_id=$8)',
      [
        randomUUID(),
        event.business_id,
        event.assessment_id,
        event.event_type,
        event.request_id,
        event.actor,
        JSON.stringify(event.metadata),
        tenantId,
        event.actor_user_id ?? event.metadata.actor_user_id ?? null,
      ],
    );
  }
  async auditEvents(
    tenantId: string,
    businessId?: string,
  ): Promise<AuditEvent[]> {
    const result = await this.pool.query<
      Omit<AuditEvent, 'created_at'> & { created_at: Date }
    >(
      `SELECT e.id,e.business_id,e.assessment_id,e.event_type,e.request_id,e.actor,e.actor_user_id,e.metadata,e.created_at FROM audit_events e JOIN businesses b ON b.id=e.business_id AND b.tenant_id=e.tenant_id WHERE e.tenant_id=$1 ${businessId ? 'AND e.business_id=$2' : 'AND b.archived_at IS NULL'} ORDER BY e.created_at DESC,e.id LIMIT 500`,
      businessId ? [tenantId, businessId] : [tenantId],
    );
    return result.rows.map((row) => ({
      ...row,
      created_at: row.created_at.toISOString(),
    }));
  }
}
