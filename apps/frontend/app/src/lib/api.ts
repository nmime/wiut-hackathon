import {
  AssessmentListSchema,
  AuthLoginSchema,
  AuthRegisterSchema,
  AuthSessionSchema,
  AuthSecuritySchema,
  AuthVerifySchema,
  MfaSetupSchema,
  MfaSetupResponseSchema,
  MfaConfirmSchema,
  MfaRecoveryCodesResponseSchema,
  AccountRecoveryKeyResponseSchema,
  PasswordChangeSchema,
  AccountRecoverSchema,
  InvitationAcceptSchema,
  InvitationCreateSchema,
  InvitationCreateResponseSchema,
  SuccessSchema,
  TeamSchema,
  TenantCreateSchema,
  TenantSwitchSchema,
  type AuthLogin,
  type AuthRegister,
  type TenantRole,
  AssessmentSchema,
  AuditListSchema,
  BusinessDetailSchema,
  BusinessImportSchema,
  BusinessListSchema,
  CreateAssessmentSchema,
  DecisionInputSchema,
  HealthSchema,
  ProblemSchema,
  type BusinessImport,
  type CreateAssessment,
  type DecisionInput,
} from '@wiut/contracts';

type Parser<T> = { parse: (data: unknown) => T };
let csrfToken: string | null = null;
let expectedTenantId: string | null = null;
let sessionEpoch = 0;
export const SESSION_EXPIRED_EVENT = 'flowcredit-session-expired';
export const SESSION_WORKSPACE_CHANGED_EVENT = 'flowcredit-workspace-changed';

export function resetApiSession(
  token: string | null,
  tenantId: string | null = null,
) {
  csrfToken = token;
  expectedTenantId = tenantId;
  sessionEpoch += 1;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public requestId?: string,
    public code?: string,
  ) {
    super(message);
  }
}

function authInput<T>(schema: Parser<T>, input: unknown): T {
  try {
    return schema.parse(input);
  } catch (error) {
    const labels: Record<string, string> = {
      email: 'Email',
      password: 'Password',
      display_name: 'Full name',
      tenant_name: 'Workspace name',
      name: 'Workspace name',
      invitation_token: 'Invitation token',
      token: 'Invitation token',
      role: 'Team role',
      tenant_id: 'Workspace',
      current_password: 'Current password',
      new_password: 'New password',
      totp_code: 'Authenticator code',
      recovery_code: 'Authenticator backup code',
      recovery_key: 'Account recovery code',
    };
    const issues =
      error &&
      typeof error === 'object' &&
      'issues' in error &&
      Array.isArray(error.issues)
        ? (error.issues as { path: unknown[]; message: string }[])
        : [];
    throw new ApiError(
      issues.length
        ? issues
            .slice(0, 3)
            .map(
              (issue) =>
                `${labels[String(issue.path[0])] ?? 'Account details'}: ${issue.message}`,
            )
            .join(' · ')
        : 'Please check the account details and try again.',
      400,
    );
  }
}

async function request<T>(
  url: string,
  schema: Parser<T>,
  body?: unknown,
  options: { method?: 'GET' | 'POST' | 'DELETE'; publicRequest?: boolean } = {},
): Promise<T> {
  const epoch = sessionEpoch;
  const method = options.method ?? (body === undefined ? 'GET' : 'POST');
  let response: Response;
  try {
    response = await fetch(`/api${url}`, {
      method,
      headers: {
        Accept: 'application/json',
        ...(!options.publicRequest && expectedTenantId
          ? { 'X-Tenant-Id': expectedTenantId }
          : {}),
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...(!options.publicRequest && method !== 'GET' && csrfToken
          ? { 'X-CSRF-Token': csrfToken }
          : {}),
      },
      credentials: 'include',
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(
      'The API cannot be reached. Check that the backend is running, then retry.',
      0,
    );
  }
  if (!options.publicRequest && epoch !== sessionEpoch) {
    throw new ApiError(
      'Your workspace changed while this request was running. Please try again in the current workspace.',
      409,
    );
  }
  if (response.status === 401 && !options.publicRequest) {
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
  }
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiError(
      'The API returned an unreadable response. Please retry.',
      response.status,
    );
  }
  if (response.ok && !options.publicRequest && epoch !== sessionEpoch) {
    throw new ApiError(
      'Your workspace changed while this request was running. Please try again in the current workspace.',
      409,
    );
  }
  if (!response.ok) {
    const problem = ProblemSchema.safeParse(data);
    if (
      !options.publicRequest &&
      response.status === 409 &&
      problem.success &&
      problem.data.title === 'Workspace changed'
    ) {
      window.dispatchEvent(new Event(SESSION_WORKSPACE_CHANGED_EVENT));
    }
    throw new ApiError(
      problem.success
        ? problem.data.detail
        : `The request failed (${response.status}). Please retry.`,
      response.status,
      problem.success ? problem.data.request_id : undefined,
      problem.success ? problem.data.code : undefined,
    );
  }
  try {
    return schema.parse(data);
  } catch {
    throw new ApiError(
      'The API response did not match the expected contract. No unverified data is displayed.',
      response.status,
    );
  }
}

export const api = {
  health: () =>
    request('/health', HealthSchema, undefined, { publicRequest: true }),
  session: () =>
    request('/auth/session', AuthSessionSchema, undefined, {
      publicRequest: true,
    }),
  register: (input: AuthRegister) =>
    request(
      '/auth/register',
      AuthSessionSchema,
      authInput(AuthRegisterSchema, input),
      { publicRequest: true },
    ),
  login: (input: AuthLogin) =>
    request(
      '/auth/login',
      AuthSessionSchema,
      authInput(AuthLoginSchema, input),
      {
        publicRequest: true,
      },
    ),
  logout: () => request('/auth/logout', SuccessSchema, {}),
  security: () => request('/auth/security', AuthSecuritySchema),
  setupMfa: (input: { current_password: string }) =>
    request(
      '/auth/mfa/setup',
      MfaSetupResponseSchema,
      authInput(MfaSetupSchema, input),
    ),
  confirmMfa: (input: { totp_code: string }) =>
    request(
      '/auth/mfa/confirm',
      MfaRecoveryCodesResponseSchema,
      authInput(MfaConfirmSchema, input),
    ),
  disableMfa: (input: {
    current_password: string;
    totp_code?: string;
    recovery_code?: string;
  }) =>
    request(
      '/auth/mfa/disable',
      SuccessSchema,
      authInput(AuthVerifySchema, input),
    ),
  rotateMfaCodes: (input: {
    current_password: string;
    totp_code?: string;
    recovery_code?: string;
  }) =>
    request(
      '/auth/mfa/recovery-codes',
      MfaRecoveryCodesResponseSchema,
      authInput(AuthVerifySchema, input),
    ),
  rotateRecoveryKey: (input: {
    current_password: string;
    totp_code?: string;
    recovery_code?: string;
  }) =>
    request(
      '/auth/recovery-key',
      AccountRecoveryKeyResponseSchema,
      authInput(AuthVerifySchema, input),
    ),
  changePassword: (input: {
    current_password: string;
    new_password: string;
    totp_code?: string;
    recovery_code?: string;
  }) =>
    request(
      '/auth/password',
      AuthSessionSchema,
      authInput(PasswordChangeSchema, input),
    ),
  recoverAccount: (input: {
    email: string;
    recovery_key: string;
    new_password: string;
  }) =>
    request(
      '/auth/recover',
      SuccessSchema,
      authInput(AccountRecoverSchema, input),
      { publicRequest: true },
    ),
  team: () => request('/team', TeamSchema),
  createTenant: (input: { name: string }) =>
    request(
      '/tenants',
      AuthSessionSchema,
      authInput(TenantCreateSchema, input),
    ),
  switchTenant: (input: { tenant_id: string }) =>
    request(
      '/tenants/switch',
      AuthSessionSchema,
      authInput(TenantSwitchSchema, input),
    ),
  createInvitation: (input: { email: string; role: TenantRole }) =>
    request(
      '/invitations',
      InvitationCreateResponseSchema,
      authInput(InvitationCreateSchema, input),
    ),
  acceptInvitation: (input: { token: string }) =>
    request(
      '/invitations/accept',
      AuthSessionSchema,
      authInput(InvitationAcceptSchema, input),
    ),
  revokeInvitation: (id: string) =>
    request(
      `/invitations/${encodeURIComponent(id)}`,
      SuccessSchema,
      undefined,
      { method: 'DELETE' },
    ),
  businesses: () => request('/businesses', BusinessListSchema),
  business: (id: string) =>
    request(`/businesses/${encodeURIComponent(id)}`, BusinessDetailSchema),
  importBusiness: (input: BusinessImport) =>
    request(
      '/businesses',
      BusinessDetailSchema,
      BusinessImportSchema.parse(input),
    ),
  assessments: (businessId?: string) =>
    request(
      `/assessments${businessId ? `?business_id=${encodeURIComponent(businessId)}` : ''}`,
      AssessmentListSchema,
    ),
  assess: (input: CreateAssessment) =>
    request(
      '/assessments',
      AssessmentSchema,
      CreateAssessmentSchema.parse(input),
    ),
  assessment: (id: string) =>
    request(`/assessments/${encodeURIComponent(id)}`, AssessmentSchema),
  decide: (id: string, input: DecisionInput) =>
    request(
      `/assessments/${encodeURIComponent(id)}/decisions`,
      AssessmentSchema,
      DecisionInputSchema.parse(input),
    ),
  audit: (businessId?: string) =>
    request(
      `/audit${businessId ? `?business_id=${encodeURIComponent(businessId)}` : ''}`,
      AuditListSchema,
    ),
};
