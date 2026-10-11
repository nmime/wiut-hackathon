import { SwaggerModule, type OpenAPIObject } from '@nestjs/swagger';
import type { INestApplication } from '@nestjs/common';
import { z } from 'zod';
import {
  AssessmentListSchema,
  AssessmentSchema,
  AuditListSchema,
  BusinessDetailSchema,
  BusinessImportSchema,
  BusinessListSchema,
  CreateAssessmentSchema,
  DecisionInputSchema,
  HealthSchema,
  ProblemSchema,
  AuthRegisterSchema,
  AuthLoginSchema,
  AuthSessionSchema,
  AuthSecuritySchema,
  AuthVerifySchema,
  MfaSetupSchema,
  MfaSetupResponseSchema,
  MfaConfirmSchema,
  MfaRecoveryCodesResponseSchema,
  AccountRecoveryKeyResponseSchema,
  AccountRecoverSchema,
  PasswordChangeSchema,
  TeamSchema,
  TenantCreateSchema,
  TenantSwitchSchema,
  InvitationCreateSchema,
  InvitationCreateResponseSchema,
  InvitationAcceptSchema,
  SuccessSchema,
  ShowcaseGenerateSchema,
  ShowcaseGenerationSchema,
} from '@wiut/contracts';
import type { AppConfig } from './config.js';

export function setupDocumentation(app: INestApplication, config: AppConfig) {
  const schemas = {
    Health: HealthSchema,
    Businesses: BusinessListSchema,
    Business: BusinessDetailSchema,
    BusinessImport: BusinessImportSchema,
    AssessmentInput: CreateAssessmentSchema,
    Assessment: AssessmentSchema,
    Assessments: AssessmentListSchema,
    DecisionInput: DecisionInputSchema,
    Audit: AuditListSchema,
    Problem: ProblemSchema,
    AuthRegister: AuthRegisterSchema,
    AuthLogin: AuthLoginSchema,
    AuthSession: AuthSessionSchema,
    AuthSecurity: AuthSecuritySchema,
    AuthVerify: AuthVerifySchema,
    MfaSetup: MfaSetupSchema,
    MfaSetupResponse: MfaSetupResponseSchema,
    MfaConfirm: MfaConfirmSchema,
    MfaRecoveryCodesResponse: MfaRecoveryCodesResponseSchema,
    AccountRecoveryKeyResponse: AccountRecoveryKeyResponseSchema,
    AccountRecover: AccountRecoverSchema,
    PasswordChange: PasswordChangeSchema,
    Team: TeamSchema,
    TenantCreate: TenantCreateSchema,
    TenantSwitch: TenantSwitchSchema,
    InvitationCreate: InvitationCreateSchema,
    InvitationCreateResponse: InvitationCreateResponseSchema,
    InvitationAccept: InvitationAcceptSchema,
    Success: SuccessSchema,
    ShowcaseGenerate: ShowcaseGenerateSchema,
    ShowcaseGeneration: ShowcaseGenerationSchema,
  };
  const components = Object.fromEntries(
    Object.entries(schemas).map(([name, schema]) => {
      const json = z.toJSONSchema(schema, { unrepresentable: 'any' });
      const { $schema: _dialect, ...body } = json;
      return [name, body];
    }),
  );
  const response = (schema: string, description: string) => ({
    description,
    content: {
      'application/json': {
        schema: { $ref: `#/components/schemas/${schema}` },
      },
    },
  });
  const operation = (
    summary: string,
    output: string,
    input?: string,
    parameters?: Array<Record<string, unknown>>,
    successStatus: number = input ? 201 : 200,
  ) => ({
    summary,
    tags: ['Capacity review'],
    security: [
      input ? { sessionCookie: [], csrfToken: [] } : { sessionCookie: [] },
    ],
    parameters: [
      ...(parameters ?? []),
      {
        name: 'x-tenant-id',
        in: 'header',
        required: false,
        schema: { type: 'string', format: 'uuid' },
        description:
          'Optional expected active workspace. Mismatch rejects with409 Workspace changed; never chooses the tenant. Ignored on public routes and GET /auth/session.',
      },
    ],
    ...(input
      ? {
          requestBody: {
            required: true,
            content: {
              'application/json': {
                schema: { $ref: `#/components/schemas/${input}` },
              },
            },
          },
        }
      : {}),
    responses: {
      [successStatus]: response(output, 'Success'),
      ...Object.fromEntries(
        [400, 401, 403, 404, 409, 429, 502, 503, 504].map((status) => [
          status,
          {
            description:
              'Request rejected or service unavailable. Assessment and human decision rejections for known businesses are audited.',
            content: {
              'application/problem+json': {
                schema: { $ref: '#/components/schemas/Problem' },
              },
            },
          },
        ]),
      ),
    },
  });
  const pathId = [
    { name: 'id', in: 'path', required: true, schema: { type: 'string' } },
  ];
  const businessFilter = [
    {
      name: 'business_id',
      in: 'query',
      required: false,
      schema: { type: 'string', maxLength: 100 },
    },
  ];
  const document = {
    openapi: '3.1.0',
    info: {
      title: 'WIUT capacity review API',
      version: '0.1.0',
      description:
        'Import user-provided transactions in UZS into an initially empty workspace. Scores estimate payment capacity; a human records each final decision. Imported amount values map explicitly 1:1 to the unchanged ML amount_index transport: one index equals one UZS for a business or assessment with amount_unit=UZS. Archived legacy synthetic records keep original indices with amount_unit=index and no currency conversion. The configured model requires borrower-level validation before relying on its forecasts or recommendations. Explicitly opted-in showcase tenants contain generated synthetic UZS histories, never real portfolios. Auth session workspace kind is bank or showcase; clients cannot choose kind on ordinary registration or workspace creation. Only showcase tenants can generate cases; real-data imports into showcase tenants are rejected. Generation accepts 1–6 cases, 3–36 months, a uint32 seed, and a monthly revenue scale of 1 million–1 billion UZS. A lab has at most 100 active cases. The generation input and resolved per-case provenance are persisted and audited. Showcase inputs do not supply repayment outcomes or validate model accuracy. Opaque HttpOnly sessions select a tenant; all domain resources are tenant-scoped. Mutations require a trusted application Origin and x-csrf-token; x-tenant-id optionally rejects stale workspace state. Administrators manage invitations; admins and officers review businesses. Decision identities come from the session; reviewer_name input is deprecated and ignored. Default lists omit archived businesses and their history; direct IDs and explicit business_id history filters preserve historical access. Lists are bounded to 200 businesses, 100 assessments, 500 domain audit events, 500 members and 100 invitations. Invitations expire after seven days; email ownership is not independently verified. Optional authenticator MFA uses six-digit SHA1 TOTP with a 30-second period, one-use backup codes, encrypted secrets and replay protection. Login responds with Problem.code=mfa_required after correct password when a second factor is missing. Password changes and security credential rotations require current credentials and fresh MFA when enabled, and revoke other sessions. An independently saved one-use account recovery key resets password, disables MFA and revokes all sessions; it cannot be retrieved later and must be rotated after recovery. No email recovery, email delivery or external identity provider is included.',
    },
    paths: {
      '/api/health': {
        get: {
          ...operation('Database readiness and ML configuration', 'Health'),
          security: [],
        },
      },
      '/api/auth/register': {
        post: {
          ...operation(
            'Register administrator workspace or accept invitation while registering',
            'AuthSession',
            'AuthRegister',
          ),
          security: [],
        },
      },
      '/api/auth/login': {
        post: {
          ...operation(
            'Sign in with email and password',
            'AuthSession',
            'AuthLogin',
            undefined,
            200,
          ),
          security: [],
        },
      },
      '/api/auth/session': {
        get: operation(
          'Current signed-in user, active tenant, memberships and CSRF token',
          'AuthSession',
        ),
      },
      '/api/auth/security': {
        get: operation(
          'Current account authenticator and recovery-code availability; secrets omitted',
          'AuthSecurity',
        ),
      },
      '/api/auth/mfa/setup': {
        post: operation(
          'Start password-verified authenticator enrollment; secret expires in ten minutes',
          'MfaSetupResponse',
          'MfaSetup',
          undefined,
          200,
        ),
      },
      '/api/auth/mfa/confirm': {
        post: operation(
          'Confirm authenticator; return ten once-displayed recovery codes and revoke other sessions',
          'MfaRecoveryCodesResponse',
          'MfaConfirm',
          undefined,
          200,
        ),
      },
      '/api/auth/mfa/disable': {
        post: operation(
          'Disable MFA with current password and fresh factor; revoke other sessions',
          'Success',
          'AuthVerify',
          undefined,
          200,
        ),
      },
      '/api/auth/mfa/recovery-codes': {
        post: operation(
          'Replace all MFA backup codes with current credentials; revoke other sessions',
          'MfaRecoveryCodesResponse',
          'AuthVerify',
          undefined,
          200,
        ),
      },
      '/api/auth/recovery-key': {
        post: operation(
          'Generate a once-displayed account recovery key, invalidate the previous key and revoke other sessions',
          'AccountRecoveryKeyResponse',
          'AuthVerify',
          undefined,
          200,
        ),
      },
      '/api/auth/password': {
        post: operation(
          'Change password with current credentials, revoke other sessions and rotate current CSRF',
          'AuthSession',
          'PasswordChange',
          undefined,
          200,
        ),
      },
      '/api/auth/recover': {
        post: {
          ...operation(
            'Consume offline account recovery key; reset password and MFA, revoke all sessions without signing in',
            'Success',
            'AccountRecover',
            undefined,
            200,
          ),
          security: [],
        },
      },
      '/api/auth/logout': {
        post: {
          ...operation('Revoke current session and clear cookie', 'Success'),
          security: [{ sessionCookie: [], csrfToken: [] }],
        },
      },
      '/api/team': {
        get: operation(
          'Administrator-only members and invitations; secret tokens omitted',
          'Team',
        ),
      },
      '/api/tenants': {
        post: operation(
          'Create a workspace and become its administrator; switch active tenant',
          'AuthSession',
          'TenantCreate',
        ),
      },
      '/api/auth/showcase-tenants': {
        post: operation(
          'Opt in to a separate empty showcase workspace; become administrator, switch active tenant and rotate CSRF',
          'AuthSession',
          'TenantCreate',
        ),
      },
      '/api/showcase/generate': {
        post: operation(
          'Generate one to six explicitly synthetic UZS cases in the current showcase workspace only; persist seed and provenance with each audited case',
          'ShowcaseGeneration',
          'ShowcaseGenerate',
        ),
      },
      '/api/tenants/switch': {
        post: operation(
          'Switch to an existing workspace membership and rotate CSRF token',
          'AuthSession',
          'TenantSwitch',
          undefined,
          200,
        ),
      },
      '/api/invitations': {
        post: operation(
          'Administrator creates a seven-day invitation; token returned once',
          'InvitationCreateResponse',
          'InvitationCreate',
        ),
      },
      '/api/invitations/accept': {
        post: operation(
          'Join invited workspace with matching signed-in email and rotate CSRF token',
          'AuthSession',
          'InvitationAccept',
          undefined,
          200,
        ),
      },
      '/api/invitations/{id}': {
        delete: {
          ...operation(
            'Administrator revokes an invitation in this tenant',
            'Success',
            undefined,
            pathId,
          ),
          security: [{ sessionCookie: [], csrfToken: [] }],
        },
      },
      '/api/businesses': {
        get: operation(
          'List active businesses in the current workspace',
          'Businesses',
        ),
        post: operation(
          'Import user-provided UZS transactions (maximum 240 months)',
          'Business',
          'BusinessImport',
        ),
      },
      '/api/businesses/{id}': {
        get: operation(
          'Business transactions and observed cash flow',
          'Business',
          undefined,
          pathId,
        ),
      },
      '/api/assessments': {
        get: operation(
          'Recent completed and failed assessments',
          'Assessments',
          undefined,
          businessFilter,
        ),
        post: operation(
          'Persist an attempt and call the configured ML /score endpoint',
          'Assessment',
          'AssessmentInput',
        ),
      },
      '/api/assessments/{id}': {
        get: operation(
          'Read an assessment with its human decision',
          'Assessment',
          undefined,
          pathId,
        ),
      },
      '/api/assessments/{id}/decisions': {
        post: operation(
          'Record the first human decision atomically',
          'Assessment',
          'DecisionInput',
          pathId,
        ),
      },
      '/api/audit': {
        get: operation(
          'Read durable assessment and decision audit events',
          'Audit',
          undefined,
          businessFilter,
        ),
      },
    },
    components: {
      schemas: components,
      securitySchemes: {
        sessionCookie: {
          type: 'apiKey',
          in: 'cookie',
          name: config.SESSION_COOKIE_SECURE
            ? '__Host-wiut_session'
            : 'wiut_session',
          description:
            'Opaque session cookie issued by login/register; HttpOnly, SameSite=Strict; Secure enabled by default in production.',
        },
        csrfToken: {
          type: 'apiKey',
          in: 'header',
          name: 'x-csrf-token',
          description:
            'Current session token from GET /api/auth/session; rotates on tenant changes. Also send an allowed application Origin.',
        },
      },
    },
  } as unknown as OpenAPIObject;
  SwaggerModule.setup('api/docs', app, document, {
    jsonDocumentUrl: 'api/openapi.json',
    swaggerOptions: { persistAuthorization: false },
  });
}
