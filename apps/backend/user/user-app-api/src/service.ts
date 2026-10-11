import { Injectable } from '@nestjs/common';
import { createHash, randomUUID } from 'node:crypto';
import {
  AssessmentListSchema,
  AssessmentSchema,
  AuditListSchema,
  BusinessDetailSchema,
  BusinessImportSchema,
  BusinessListSchema,
  LegacySyntheticBusinessImportSchema,
  CreateAssessmentSchema,
  DecisionInputSchema,
  HealthSchema,
  ScoreRequestSchema,
  type CreateAssessment,
  type ScoreRequest,
  type DecisionInput,
} from '@wiut/contracts';
import type { AppConfig } from './config.js';
import { Database } from './database.js';
import { MlClient } from './ml.js';
import { ApiProblem, errorMessage, validate } from './problem.js';
import { businessDetail, type StoredBusiness } from './business.js';
import type { AuthContext } from './auth-types.js';

function knownBusinessId(body: unknown): string | undefined {
  if (typeof body !== 'object' || body === null || !('business_id' in body))
    return undefined;
  const value = body.business_id;
  return typeof value === 'string' && value.length <= 100 ? value : undefined;
}
export function inputHash(input: unknown) {
  return createHash('sha256')
    .update(JSON.stringify(input) ?? 'null')
    .digest('hex');
}

@Injectable()
export class ProductService {
  constructor(
    private readonly database: Database,
    private readonly ml: MlClient,
    private readonly config: AppConfig,
  ) {}

  async health() {
    await this.database.health();
    return HealthSchema.parse({
      status: 'ok',
      database: 'connected',
      ml_configured: Boolean(this.config.ML_SERVICE_URL),
      synthetic_data: false,
    });
  }

  async businesses(auth: AuthContext) {
    const stored = await this.database.businesses(auth.tenant.id);
    const latest = await this.database.latestAssessments(
      stored.map((business) => business.id),
      auth.tenant.id,
    );
    const items = stored.map((business) => {
      const {
        transactions: _transactions,
        monthly_cashflow: _monthly,
        ...summary
      } = businessDetail(business);
      return {
        ...summary,
        latest_assessment: latest.get(business.id) ?? null,
      };
    });
    return BusinessListSchema.parse({
      items,
      synthetic: items.some((item) => item.data_source === 'synthetic'),
    });
  }
  async business(id: string, auth: AuthContext) {
    const stored = await this.database.business(id, auth.tenant.id);
    if (!stored)
      throw new ApiProblem(
        404,
        'Business not found',
        'The requested business does not exist.',
      );
    return BusinessDetailSchema.parse({
      ...businessDetail(stored),
      latest_assessment: await this.database.latestAssessment(
        id,
        auth.tenant.id,
      ),
    });
  }
  async importBusiness(body: unknown, requestId: string, auth: AuthContext) {
    const legacy =
      this.config.NODE_ENV === 'test' &&
      typeof body === 'object' &&
      body !== null &&
      'data_source' in body &&
      body.data_source === 'synthetic';
    const input = legacy
      ? validate(LegacySyntheticBusinessImportSchema, body)
      : validate(BusinessImportSchema, body);
    const transactions = input.transactions
      .map((row) =>
        'amount' in row
          ? {
              ts: row.ts,
              direction: row.direction,
              channel: row.channel,
              amount_index: row.amount,
            }
          : row,
      )
      .sort((a, b) => a.ts.localeCompare(b.ts));
    const first = new Date(`${transactions[0]!.ts.slice(0, 7)}-01T00:00:00Z`);
    const last = new Date(
      `${transactions.at(-1)!.ts.slice(0, 7)}-01T00:00:00Z`,
    );
    if (
      (last.getUTCFullYear() - first.getUTCFullYear()) * 12 +
        last.getUTCMonth() -
        first.getUTCMonth() >=
      240
    )
      throw new ApiProblem(
        400,
        'Invalid transaction history',
        'Imports support at most 240 calendar months of transaction history.',
      );
    const business: StoredBusiness = {
      id: `business-${randomUUID()}`,
      name: input.name,
      sector: input.sector,
      location: input.location,
      archetype: legacy ? 'Test fixture' : 'Uploaded transaction history',
      data_source: legacy ? 'synthetic' : 'user_provided',
      amount_unit: legacy ? 'index' : 'UZS',
      archived_at: null,
      transactions,
    };
    await this.database.importBusiness(business, requestId, auth);
    return BusinessDetailSchema.parse(businessDetail(business));
  }

  async createAssessment(body: unknown, requestId: string, auth: AuthContext) {
    let input: CreateAssessment;
    let scoringInput: ScoreRequest;
    try {
      input = validate(CreateAssessmentSchema, body);
      const business = await this.database.business(
        input.business_id,
        auth.tenant.id,
      );
      if (!business)
        throw new ApiProblem(
          404,
          'Business not found',
          'The requested business does not exist.',
        );
      if (business.archived_at)
        throw new ApiProblem(
          409,
          'Business archived',
          'Archived businesses retain their history and cannot receive new assessments.',
        );
      const transactions = business.transactions.filter(
        (transaction) => transaction.ts.slice(0, 10) <= input.as_of_date,
      );
      if (transactions.length === 0)
        throw new ApiProblem(
          400,
          'No eligible transactions',
          'Choose an assessment date on or after the first transaction.',
        );
      scoringInput = validate(ScoreRequestSchema, {
        ...input,
        currency: 'UZS',
        transactions,
      });
    } catch (error) {
      const businessId = knownBusinessId(body);
      if (
        error instanceof ApiProblem &&
        businessId &&
        (await this.database.business(businessId, auth.tenant.id))
      ) {
        await this.database.audit(
          {
            business_id: businessId,
            assessment_id: null,
            event_type: 'assessment_rejected',
            request_id: requestId,
            actor: auth.user.display_name,
            metadata: {
              input_hash: inputHash(body),
              reason: error.detail,
              status: error.status,
              actor_user_id: auth.user.id,
              ...(error.errors ? { errors: error.errors } : {}),
            },
          },
          auth.tenant.id,
        );
      }
      throw error;
    }
    const id = randomUUID();
    await this.database.beginAssessment(
      id,
      scoringInput,
      requestId,
      inputHash(scoringInput),
      auth,
    );
    let result;
    try {
      result = await this.ml.score(scoringInput, requestId);
    } catch (error) {
      await this.database.finishAssessment(
        id,
        null,
        errorMessage(error),
        auth.tenant.id,
        error instanceof ApiProblem ? error.status : 503,
      );
      throw error;
    }
    await this.database.finishAssessment(id, result, null, auth.tenant.id);
    return AssessmentSchema.parse(
      await this.database.assessment(id, auth.tenant.id),
    );
  }

  async assessments(auth: AuthContext, businessId?: string) {
    if (businessId) await this.business(businessId, auth);
    return AssessmentListSchema.parse({
      items: await this.database.assessments(auth.tenant.id, businessId),
    });
  }
  async assessment(id: string, auth: AuthContext) {
    const assessment = await this.database.assessment(id, auth.tenant.id);
    if (!assessment)
      throw new ApiProblem(
        404,
        'Assessment not found',
        'The requested assessment does not exist.',
      );
    return AssessmentSchema.parse(assessment);
  }
  async decide(
    id: string,
    body: unknown,
    requestId: string,
    auth: AuthContext,
  ) {
    const businessId = await this.database.assessmentBusinessId(
      id,
      auth.tenant.id,
    );
    if (!businessId)
      throw new ApiProblem(
        404,
        'Assessment not found',
        'The requested assessment does not exist.',
      );
    let input: DecisionInput | undefined;
    try {
      input = validate(DecisionInputSchema, body);
      return AssessmentSchema.parse(
        await this.database.recordDecision(id, input, requestId, auth),
      );
    } catch (error) {
      if (error instanceof ApiProblem) {
        await this.database.audit(
          {
            business_id: businessId,
            assessment_id: id,
            event_type: 'decision_rejected',
            request_id: requestId,
            actor: auth.user.display_name,
            metadata: {
              input_hash: inputHash(body),
              reason: error.detail,
              status: error.status,
              actor_user_id: auth.user.id,
              ...(input
                ? {
                    submission: {
                      ...input,
                      reviewer_name: auth.user.display_name,
                    },
                  }
                : {}),
              ...(error.errors ? { errors: error.errors } : {}),
            },
          },
          auth.tenant.id,
        );
      }
      throw error;
    }
  }
  async audit(auth: AuthContext, businessId?: string) {
    if (businessId) await this.business(businessId, auth);
    return AuditListSchema.parse({
      items: await this.database.auditEvents(auth.tenant.id, businessId),
    });
  }
}
