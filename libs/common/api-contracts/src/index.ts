import { z } from 'zod';

const nonnegative = z.number().finite().nonnegative();
export const DateSchema = z.iso
  .date()
  .refine(
    (value) => !value.startsWith('0000'),
    'Date year must be between 0001 and 9999',
  );
export const TransactionSchema = z
  .object({
    ts: z
      .string()
      .regex(
        /^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$/,
      )
      .refine(
        (value) =>
          DateSchema.safeParse(value.slice(0, 10)).success &&
          Number.isFinite(
            Date.parse(
              value.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(value)
                ? value
                : `${value}Z`,
            ),
          ),
        'Invalid transaction timestamp',
      ),
    direction: z.enum(['in', 'out']),
    channel: z.enum(['card', 'transfer', 'qr', 'cash_in', 'other']),
    amount_index: z.number().finite().positive().max(1e12),
  })
  .strict();

export const ScoreRequestSchema = z
  .object({
    business_id: z.string().min(1).max(100),
    requested_amount: nonnegative.max(1e15).nullable().default(null),
    currency: z.literal('UZS').default('UZS'),
    as_of_date: DateSchema,
    transactions: z.array(TransactionSchema).min(1).max(20000),
  })
  .strict()
  .superRefine((value, ctx) => {
    if (value.transactions.some((t) => t.ts.slice(0, 10) > value.as_of_date)) {
      ctx.addIssue({
        code: 'custom',
        path: ['transactions'],
        message: 'Transactions must not be after the assessment date',
      });
    }
  });

export const ScoreResponseSchema = z
  .object({
    business_id: z.string().min(1).max(100),
    as_of_date: DateSchema,
    capacity_score: z.number().finite().min(0).max(100),
    score_band: z.enum(['low', 'medium', 'high']),
    cashflow_summary: z.object({
      avg_monthly_inflow_index: nonnegative,
      inflow_volatility: nonnegative,
      net_monthly_surplus_index: z.number().finite(),
      trend: z.enum(['growing', 'stable', 'declining']),
    }),
    recommended_loan: z.object({
      max_affordable_installment_index: nonnegative,
      suggested_principal_index: nonnegative,
      suggested_term_months: z.number().int().min(1).max(120),
      rationale: z.string().max(10000),
    }),
    seasonality: z.object({
      monthly_forecast_index: z.array(z.number().finite()).length(12),
      weak_months: z.array(z.number().int().min(1).max(12)).max(12),
      strong_months: z.array(z.number().int().min(1).max(12)).max(12),
    }),
    adaptive_schedule: z
      .array(
        z.object({
          month_offset: z.number().int().min(1).max(120),
          installment_index: nonnegative,
          note: z.enum(['reduced', 'normal', 'increased']),
        }),
      )
      .max(120),
    explanation: z.object({
      top_factors: z
        .array(
          z.object({
            factor: z.string().min(1).max(1000),
            impact: z.enum(['positive', 'negative']),
            weight: z.number().finite(),
          }),
        )
        .max(100),
      advisory: z.array(z.string().max(10000)).max(100),
    }),
    confidence: z.number().finite().min(0).max(1),
    flags: z.array(z.string().max(500)).max(100),
    model_version: z.string().min(1).max(100),
    request_id: z.string().min(1).max(200),
  })
  .superRefine((value, ctx) => {
    const { weak_months, strong_months } = value.seasonality;
    if (
      new Set(weak_months).size !== weak_months.length ||
      new Set(strong_months).size !== strong_months.length ||
      weak_months.some((m) => strong_months.includes(m))
    ) {
      ctx.addIssue({
        code: 'custom',
        path: ['seasonality'],
        message: 'Weak and strong months must be unique and disjoint',
      });
    }
    const schedule = value.adaptive_schedule;
    if (
      schedule.some((row, i) => row.month_offset !== i + 1) ||
      (schedule.length > 0 &&
        schedule.length !== value.recommended_loan.suggested_term_months)
    ) {
      ctx.addIssue({
        code: 'custom',
        path: ['adaptive_schedule'],
        message:
          'Schedule must contain contiguous one-based offsets matching the suggested term',
      });
    }
    if (
      value.recommended_loan.suggested_principal_index > 0 &&
      schedule.length === 0
    ) {
      ctx.addIssue({
        code: 'custom',
        path: ['adaptive_schedule'],
        message: 'A positive loan recommendation requires a repayment schedule',
      });
    }
  });

export const DecisionInputSchema = z
  .object({
    decision: z.enum(['approved', 'declined', 'needs_information']),
    reviewer_name: z.string().trim().min(2).max(100).optional(),
    notes: z.string().trim().min(5).max(3000),
  })
  .strict();
export const DecisionSchema = DecisionInputSchema.extend({
  reviewer_name: z.string().min(2).max(100),
  reviewer_user_id: z.string().nullable().default(null),
  id: z.string(),
  assessment_id: z.string(),
  created_at: z.iso.datetime(),
});
export const AssessmentSchema = z
  .object({
    id: z.string(),
    business_id: z.string(),
    requested_amount: nonnegative.nullable(),
    as_of_date: DateSchema,
    status: z.enum(['completed', 'failed']),
    created_at: z.iso.datetime(),
    request_id: z.string(),
    input_hash: z.string(),
    result: ScoreResponseSchema.nullable(),
    error: z.string().nullable(),
    decision: DecisionSchema.nullable(),
  })
  .superRefine((value, ctx) => {
    if (
      value.status === 'completed' &&
      (!value.result || value.error !== null)
    ) {
      ctx.addIssue({
        code: 'custom',
        message: 'Completed assessments must contain a result and no error',
      });
    }
    if (
      value.status === 'failed' &&
      (value.result !== null || value.decision !== null || !value.error?.trim())
    ) {
      ctx.addIssue({
        code: 'custom',
        message:
          'Failed assessments must contain an error, no result, and no decision',
      });
    }
    if (
      value.result &&
      (value.result.business_id !== value.business_id ||
        value.result.as_of_date !== value.as_of_date)
    ) {
      ctx.addIssue({
        code: 'custom',
        path: ['result'],
        message: 'Scoring result must match the assessment business and date',
      });
    }
    if (value.decision && value.decision.assessment_id !== value.id) {
      ctx.addIssue({
        code: 'custom',
        path: ['decision'],
        message: 'Decision must belong to this assessment',
      });
    }
  });
export const MonthlyCashflowSchema = z.object({
  month: z.string(),
  inflow_index: nonnegative,
  outflow_index: nonnegative,
  surplus_index: z.number().finite(),
});
export const BusinessSchema = z.object({
  id: z.string(),
  name: z.string(),
  sector: z.string(),
  location: z.string(),
  archetype: z.string(),
  history_months: z.number().int().nonnegative(),
  transaction_count: z.number().int().nonnegative(),
  avg_monthly_inflow_index: nonnegative,
  avg_monthly_surplus_index: z.number().finite(),
  trend: z.enum(['growing', 'stable', 'declining']),
  last_activity_date: DateSchema,
  data_source: z.literal('synthetic'),
  latest_assessment: AssessmentSchema.nullable(),
});
export const BusinessDetailSchema = BusinessSchema.extend({
  transactions: z.array(TransactionSchema),
  monthly_cashflow: z.array(MonthlyCashflowSchema),
});
export const BusinessListSchema = z.object({
  items: z.array(BusinessSchema),
  synthetic: z.literal(true),
});
export const BusinessImportSchema = z
  .object({
    name: z.string().trim().min(2).max(100),
    sector: z.string().trim().min(2).max(100),
    location: z.string().trim().min(2).max(100),
    data_source: z.literal('synthetic'),
    transactions: z.array(TransactionSchema).min(1).max(20000),
  })
  .strict();
export const CreateAssessmentSchema = z
  .object({
    business_id: z.string().min(1).max(100),
    requested_amount: nonnegative.max(1e15).nullable().default(null),
    as_of_date: DateSchema,
  })
  .strict();
export const AssessmentListSchema = z.object({
  items: z.array(AssessmentSchema),
});
export const AuditEventSchema = z.object({
  id: z.string(),
  business_id: z.string(),
  assessment_id: z.string().nullable(),
  event_type: z.enum([
    'business_imported',
    'assessment_requested',
    'assessment_completed',
    'assessment_failed',
    'assessment_rejected',
    'decision_recorded',
    'decision_rejected',
  ]),
  request_id: z.string(),
  created_at: z.iso.datetime(),
  actor: z.string(),
  actor_user_id: z.string().nullable().optional(),
  metadata: z.record(z.string(), z.unknown()),
});
export const AuditListSchema = z.object({ items: z.array(AuditEventSchema) });
export const HealthSchema = z.object({
  status: z.literal('ok'),
  database: z.literal('connected'),
  ml_configured: z.boolean(),
  synthetic_data: z.literal(true),
});
export const ProblemSchema = z.object({
  type: z.string(),
  title: z.string(),
  status: z.number(),
  detail: z.string(),
  request_id: z.string(),
  errors: z
    .array(z.object({ path: z.string(), message: z.string() }))
    .optional(),
});

export type Transaction = z.infer<typeof TransactionSchema>;
export type ScoreRequest = z.infer<typeof ScoreRequestSchema>;
export type ScoreResponse = z.infer<typeof ScoreResponseSchema>;
export type Business = z.infer<typeof BusinessSchema>;
export type BusinessDetail = z.infer<typeof BusinessDetailSchema>;
export type BusinessImport = z.infer<typeof BusinessImportSchema>;
export type CreateAssessment = z.infer<typeof CreateAssessmentSchema>;
export type Assessment = z.infer<typeof AssessmentSchema>;
export type DecisionInput = z.infer<typeof DecisionInputSchema>;
export type Decision = z.infer<typeof DecisionSchema>;
export type AuditEvent = z.infer<typeof AuditEventSchema>;
export type MonthlyCashflow = z.infer<typeof MonthlyCashflowSchema>;

export const EmailSchema = z
  .string()
  .trim()
  .toLowerCase()
  .pipe(z.email().max(254));
export const PasswordSchema = z.string().min(12).max(128);
export const TenantRoleSchema = z.enum(['admin', 'officer']);
export const AuthRegisterSchema = z
  .object({
    email: EmailSchema,
    password: PasswordSchema,
    display_name: z.string().trim().min(2).max(100),
    tenant_name: z.string().trim().min(2).max(100).optional(),
    invitation_token: z
      .string()
      .regex(/^[A-Za-z0-9_-]{43}$/)
      .optional(),
  })
  .strict()
  .refine(
    (value) => Boolean(value.tenant_name) !== Boolean(value.invitation_token),
    {
      message: 'Provide a workspace name or invitation token, but not both',
    },
  );
export const AuthLoginSchema = z
  .object({ email: EmailSchema, password: PasswordSchema })
  .strict();
export const AuthUserSchema = z.object({
  id: z.string(),
  email: EmailSchema,
  display_name: z.string(),
});
export const TenantSchema = z.object({
  id: z.string(),
  name: z.string(),
  role: TenantRoleSchema,
});
export const AuthSessionSchema = z.object({
  user: AuthUserSchema,
  tenant: TenantSchema,
  tenants: z.array(TenantSchema),
  csrf_token: z.string().regex(/^[A-Za-z0-9_-]{43}$/),
});
export const TenantCreateSchema = z
  .object({ name: z.string().trim().min(2).max(100) })
  .strict();
export const TenantSwitchSchema = z.object({ tenant_id: z.uuid() }).strict();
export const InvitationCreateSchema = z
  .object({ email: EmailSchema, role: TenantRoleSchema })
  .strict();
export const InvitationAcceptSchema = z
  .object({ token: z.string().regex(/^[A-Za-z0-9_-]{43}$/) })
  .strict();
export const InvitationSchema = z.object({
  id: z.string(),
  email: EmailSchema,
  role: TenantRoleSchema,
  created_at: z.iso.datetime(),
  expires_at: z.iso.datetime(),
  status: z.enum(['pending', 'accepted', 'revoked', 'expired']),
});
export const InvitationCreateResponseSchema = z.object({
  invitation: InvitationSchema,
  token: z.string(),
  invitation_url: z.url(),
});
export const TeamMemberSchema = AuthUserSchema.extend({
  role: TenantRoleSchema,
  joined_at: z.iso.datetime(),
});
export const TeamSchema = z.object({
  members: z.array(TeamMemberSchema),
  invitations: z.array(InvitationSchema),
});
export const SuccessSchema = z.object({ ok: z.literal(true) });
export type AuthRegister = z.infer<typeof AuthRegisterSchema>;
export type AuthLogin = z.infer<typeof AuthLoginSchema>;
export type AuthSession = z.infer<typeof AuthSessionSchema>;
export type Tenant = z.infer<typeof TenantSchema>;
export type TenantRole = z.infer<typeof TenantRoleSchema>;
export type Invitation = z.infer<typeof InvitationSchema>;
export type Team = z.infer<typeof TeamSchema>;
