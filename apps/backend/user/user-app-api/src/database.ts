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
import {
  generateSyntheticBusinesses,
  type StoredBusiness,
} from './synthetic.js';

interface AssessmentRow {
  id: string;
  business_id: string;
  requested_amount: number | null;
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
  a.status, a.created_at, a.request_id, a.input_hash, a.result, a.error,
  CASE WHEN d.id IS NULL THEN NULL ELSE jsonb_build_object('id', d.id, 'assessment_id', d.assessment_id,
    'decision', d.decision, 'reviewer_name', d.reviewer_name, 'notes', d.notes, 'created_at', d.created_at) END AS decision
  FROM assessments a LEFT JOIN decisions d ON d.assessment_id = a.id`;

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
        CREATE TABLE IF NOT EXISTS synthetic_businesses (
          id text PRIMARY KEY, name text NOT NULL, sector text NOT NULL, location text NOT NULL,
          archetype text NOT NULL, transactions jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS assessments (
          id uuid PRIMARY KEY, business_id text NOT NULL REFERENCES synthetic_businesses(id),
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
          id uuid PRIMARY KEY, business_id text NOT NULL REFERENCES synthetic_businesses(id),
          assessment_id uuid REFERENCES assessments(id), event_type text NOT NULL, request_id text NOT NULL,
          actor text NOT NULL, metadata jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS audit_events_business_created_idx ON audit_events(business_id, created_at DESC);
      `);
      for (const business of generateSyntheticBusinesses()) {
        await client.query(
          'INSERT INTO synthetic_businesses(id, name, sector, location, archetype, transactions) VALUES($1,$2,$3,$4,$5,$6::jsonb) ON CONFLICT(id) DO NOTHING',
          [
            business.id,
            business.name,
            business.sector,
            business.location,
            business.archetype,
            JSON.stringify(business.transactions),
          ],
        );
      }
      // A single API process is supported. Pending attempts left by an interrupted process remain auditable.
      const interrupted = await client.query<{
        id: string;
        business_id: string;
        request_id: string;
        input_hash: string;
      }>(
        "UPDATE assessments SET status='failed', error='Assessment interrupted before a model response was saved.', completed_at=now() WHERE status='pending' RETURNING id,business_id,request_id,input_hash",
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
  async businesses(): Promise<StoredBusiness[]> {
    return (
      await this.pool.query<StoredBusiness>(
        'SELECT id,name,sector,location,archetype,transactions FROM synthetic_businesses ORDER BY created_at DESC,id LIMIT 200',
      )
    ).rows;
  }
  async business(id: string): Promise<StoredBusiness | null> {
    return (
      (
        await this.pool.query<StoredBusiness>(
          'SELECT id,name,sector,location,archetype,transactions FROM synthetic_businesses WHERE id=$1',
          [id],
        )
      ).rows[0] ?? null
    );
  }

  async importBusiness(business: StoredBusiness, requestId: string) {
    const client = await this.pool.connect();
    try {
      await client.query('BEGIN');
      await client.query(
        'INSERT INTO synthetic_businesses(id,name,sector,location,archetype,transactions) VALUES($1,$2,$3,$4,$5,$6::jsonb)',
        [
          business.id,
          business.name,
          business.sector,
          business.location,
          business.archetype,
          JSON.stringify(business.transactions),
        ],
      );
      await this.audit(
        {
          business_id: business.id,
          assessment_id: null,
          event_type: 'business_imported',
          request_id: requestId,
          actor: 'officer',
          metadata: {
            data_source: 'synthetic',
            transaction_count: business.transactions.length,
          },
        },
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
  ) {
    const client = await this.pool.connect();
    try {
      await client.query('BEGIN');
      await client.query(
        "INSERT INTO assessments(id,business_id,requested_amount,as_of_date,status,request_id,input_hash,request_input) VALUES($1,$2,$3,$4,'pending',$5,$6,$7::jsonb)",
        [
          id,
          request.business_id,
          request.requested_amount,
          request.as_of_date,
          requestId,
          hash,
          JSON.stringify(request),
        ],
      );
      await this.audit(
        {
          business_id: request.business_id,
          assessment_id: id,
          event_type: 'assessment_requested',
          request_id: requestId,
          actor: 'officer',
          metadata: {
            input_hash: hash,
            transaction_count: request.transactions.length,
            requested_amount_uzs: request.requested_amount,
            as_of_date: request.as_of_date,
          },
        },
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
        "UPDATE assessments SET status=$2,result=$3::jsonb,error=$4,completed_at=now() WHERE id=$1 AND status='pending' RETURNING business_id,request_id,input_hash",
        [
          id,
          result ? 'completed' : 'failed',
          result ? JSON.stringify(result) : null,
          error,
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
  async assessment(id: string): Promise<Assessment | null> {
    if (
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
        id,
      )
    )
      return null;
    const row = (
      await this.pool.query<AssessmentRow>(`${selection} WHERE a.id=$1`, [id])
    ).rows[0];
    return row ? this.mapAssessment(row) : null;
  }
  async assessments(businessId?: string): Promise<Assessment[]> {
    const rows = await this.pool.query<AssessmentRow>(
      `${selection} WHERE a.status <> 'pending' ${businessId ? 'AND a.business_id=$1' : ''} ORDER BY a.created_at DESC,a.id LIMIT 100`,
      businessId ? [businessId] : [],
    );
    return rows.rows.map((row) => this.mapAssessment(row));
  }
  async latestAssessment(businessId: string) {
    return (await this.assessments(businessId))[0] ?? null;
  }

  async assessmentBusinessId(id: string): Promise<string | null> {
    if (
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
        id,
      )
    )
      return null;
    return (
      (
        await this.pool.query<{ business_id: string }>(
          'SELECT business_id FROM assessments WHERE id=$1',
          [id],
        )
      ).rows[0]?.business_id ?? null
    );
  }

  async recordDecision(
    id: string,
    input: DecisionInput,
    requestId: string,
  ): Promise<Assessment> {
    const client = await this.pool.connect();
    try {
      await client.query('BEGIN');
      const assessment = (
        await client.query<{ business_id: string; status: string }>(
          'SELECT business_id,status FROM assessments WHERE id=$1 FOR UPDATE',
          [id],
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
          await client.query('SELECT 1 FROM decisions WHERE assessment_id=$1', [
            id,
          ])
        ).rowCount
      )
        throw new ApiProblem(
          409,
          'Decision already recorded',
          'This assessment already has a human decision. Create a new assessment to review new evidence.',
        );
      const decisionId = randomUUID();
      await client.query(
        'INSERT INTO decisions(id,assessment_id,decision,reviewer_name,notes) VALUES($1,$2,$3,$4,$5)',
        [decisionId, id, input.decision, input.reviewer_name, input.notes],
      );
      await this.audit(
        {
          business_id: assessment.business_id,
          assessment_id: id,
          event_type: 'decision_recorded',
          request_id: requestId,
          actor: input.reviewer_name,
          metadata: {
            decision_id: decisionId,
            decision: input.decision,
            notes: input.notes,
          },
        },
        client,
      );
      await client.query('COMMIT');
      return (await this.assessment(id))!;
    } catch (error) {
      await client.query('ROLLBACK');
      throw error;
    } finally {
      client.release();
    }
  }

  async audit(
    event: Omit<AuditEvent, 'id' | 'created_at'>,
    client?: PoolClient,
  ) {
    await (client ?? this.pool).query(
      'INSERT INTO audit_events(id,business_id,assessment_id,event_type,request_id,actor,metadata) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)',
      [
        randomUUID(),
        event.business_id,
        event.assessment_id,
        event.event_type,
        event.request_id,
        event.actor,
        JSON.stringify(event.metadata),
      ],
    );
  }
  async auditEvents(businessId?: string): Promise<AuditEvent[]> {
    const result = await this.pool.query<
      Omit<AuditEvent, 'created_at'> & { created_at: Date }
    >(
      `SELECT id,business_id,assessment_id,event_type,request_id,actor,metadata,created_at FROM audit_events ${businessId ? 'WHERE business_id=$1' : ''} ORDER BY created_at DESC,id LIMIT 500`,
      businessId ? [businessId] : [],
    );
    return result.rows.map((row) => ({
      ...row,
      created_at: row.created_at.toISOString(),
    }));
  }
}
