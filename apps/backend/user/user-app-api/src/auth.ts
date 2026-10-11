import {
  Injectable,
  type CanActivate,
  type ExecutionContext,
  SetMetadata,
} from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import {
  createHash,
  randomBytes,
  randomUUID,
  scrypt,
  timingSafeEqual,
} from 'node:crypto';
import type { FastifyReply, FastifyRequest } from 'fastify';
import type { PoolClient } from 'pg';
import {
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
  AccountRecoverSchema,
  PasswordChangeSchema,
  InvitationAcceptSchema,
  InvitationCreateResponseSchema,
  InvitationCreateSchema,
  InvitationSchema,
  TeamSchema,
  TenantCreateSchema,
  TenantSwitchSchema,
  type AuthSession,
  type Invitation,
  type TenantRole,
  type TenantKind,
} from '@wiut/contracts';
import type { AppConfig } from './config.js';
import type { AuthContext } from './auth-types.js';
import { Database } from './database.js';
import { ApiProblem, validate } from './problem.js';
import {
  authenticatorUri,
  decryptTotp,
  encryptTotp,
  newRecoveryCodes,
  newTotpSecret,
  recoveryHash,
  totpCounter,
} from './account-security.js';

declare module 'fastify' {
  interface FastifyRequest {
    auth?: AuthContext;
  }
}
export const Public = () => SetMetadata('wiut:public', true);
export const SessionRefresh = () => SetMetadata('wiut:session-refresh', true);
export const secretToken = () => randomBytes(32).toString('base64url');
export const tokenHash = (token: string) =>
  createHash('sha256').update(token).digest('hex');

function derivePassword(password: string, salt: Buffer): Promise<Buffer> {
  return new Promise((resolve, reject) =>
    scrypt(
      password,
      salt,
      64,
      { N: 32768, r: 8, p: 1, maxmem: 64 * 1024 * 1024 },
      (error, key) => (error ? reject(error) : resolve(key)),
    ),
  );
}
export async function passwordHash(password: string): Promise<string> {
  if (Buffer.byteLength(password, 'utf8') > 512)
    throw new ApiProblem(400, 'Invalid password', 'The password is too long.');
  const salt = randomBytes(16);
  const hash = await derivePassword(password, salt);
  return `scrypt-v1$${salt.toString('base64url')}$${hash.toString('base64url')}`;
}
export async function verifyPassword(
  password: string,
  encoded: string | undefined,
): Promise<boolean> {
  if (Buffer.byteLength(password, 'utf8') > 512) return false;
  const parts = encoded?.split('$');
  const valid =
    parts?.length === 3 &&
    parts[0] === 'scrypt-v1' &&
    /^[A-Za-z0-9_-]{22}$/.test(parts[1]!) &&
    /^[A-Za-z0-9_-]{86}$/.test(parts[2]!);
  const actual = await derivePassword(
    password,
    valid ? Buffer.from(parts![1]!, 'base64url') : Buffer.alloc(16),
  );
  const expected = valid
    ? Buffer.from(parts![2]!, 'base64url')
    : Buffer.alloc(64);
  return timingSafeEqual(actual, expected) && Boolean(valid);
}
export function readSessionCookie(
  header: string | undefined,
  cookieName: string,
): string | null {
  const matches = (header ?? '')
    .split(';')
    .map((value) => value.trim())
    .filter((value) => value.startsWith(`${cookieName}=`));
  if (matches.length !== 1) return null;
  const token = matches[0]!.slice(cookieName.length + 1);
  return /^[A-Za-z0-9_-]{43}$/.test(token) ? token : null;
}
export function assertCsrf(actual: unknown, expected: string) {
  if (
    typeof actual !== 'string' ||
    !/^[A-Za-z0-9_-]{43}$/.test(actual) ||
    !timingSafeEqual(Buffer.from(actual), Buffer.from(expected))
  )
    throw new ApiProblem(
      403,
      'Request rejected',
      'Refresh the session before submitting this request.',
    );
}

interface SessionRow {
  id: string;
  email: string;
  display_name: string;
  tenant_id: string;
  tenant_name: string;
  tenant_kind: TenantKind;
  role: TenantRole;
  csrf_token: string;
}
interface SecurityUserRow {
  id: string;
  email: string;
  password_hash: string;
  mfa_secret_encrypted: string | null;
  mfa_pending_secret_encrypted: string | null;
  mfa_pending_expires_at: Date | null;
  mfa_last_counter: string | null;
  account_recovery_key_hash: string | null;
}
interface FactorInput {
  totp_code?: string;
  recovery_code?: string;
}
interface InviteRow {
  id: string;
  tenant_id: string;
  email: string;
  role: TenantRole;
  created_at: Date;
  expires_at: Date;
  accepted_by: string | null;
  revoked_at: Date | null;
}
export function invitationView(row: InviteRow): Invitation {
  return InvitationSchema.parse({
    id: row.id,
    email: row.email,
    role: row.role,
    created_at: row.created_at.toISOString(),
    expires_at: row.expires_at.toISOString(),
    status: row.accepted_by
      ? 'accepted'
      : row.revoked_at
        ? 'revoked'
        : row.expires_at.getTime() <= Date.now()
          ? 'expired'
          : 'pending',
  });
}

@Injectable()
export class AuthService {
  private readonly attempts = new Map<
    string,
    { count: number; until: number }
  >();
  readonly cookieName: string;
  constructor(
    private readonly database: Database,
    private readonly config: AppConfig,
  ) {
    this.cookieName = config.SESSION_COOKIE_SECURE
      ? '__Host-wiut_session'
      : 'wiut_session';
  }
  assertOrigin(request: FastifyRequest) {
    const origin = request.headers.origin;
    if (
      typeof origin !== 'string' ||
      !this.config.corsOrigins.includes(origin) ||
      request.headers['sec-fetch-site'] === 'cross-site'
    )
      throw new ApiProblem(
        403,
        'Origin rejected',
        'Submit this request from the configured application origin.',
      );
  }
  private rateLimit(request: FastifyRequest, action: string, email: string) {
    const now = Date.now();
    for (const [key, entry] of this.attempts)
      if (entry.until <= now) this.attempts.delete(key);
    if (this.attempts.size > 10000)
      throw new ApiProblem(
        429,
        'Try again later',
        'Authentication is temporarily rate limited.',
      );
    for (const key of [
      `${action}:ip:${request.ip}`,
      `${action}:email:${email}`,
    ]) {
      const entry = this.attempts.get(key) ?? {
        count: 0,
        until: now + 15 * 60 * 1000,
      };
      entry.count++;
      this.attempts.set(key, entry);
      if (entry.count > this.config.AUTH_RATE_LIMIT_MAX)
        throw new ApiProblem(
          429,
          'Try again later',
          'Too many authentication attempts. Try again in 15 minutes.',
        );
    }
  }
  private cookie(reply: FastifyReply, token: string | null) {
    reply.header(
      'set-cookie',
      `${this.cookieName}=${token ?? ''}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${token ? this.config.SESSION_TTL_HOURS * 3600 : 0}${this.config.SESSION_COOKIE_SECURE ? '; Secure' : ''}`,
    );
  }
  private async transaction<T>(
    operation: (client: PoolClient) => Promise<T>,
  ): Promise<T> {
    const client = await this.database.pool.connect();
    try {
      await client.query('BEGIN');
      const result = await operation(client);
      await client.query('COMMIT');
      return result;
    } catch (error) {
      await client.query('ROLLBACK');
      throw error;
    } finally {
      client.release();
    }
  }
  private async security(
    client: Pick<PoolClient, 'query'>,
    event: string,
    requestId: string,
    userId: string | null,
    tenantId: string | null,
    metadata: Record<string, unknown> = {},
  ) {
    await client.query(
      'INSERT INTO security_events(id,tenant_id,actor_user_id,event_type,request_id,metadata) VALUES($1,$2,$3,$4,$5,$6::jsonb)',
      [
        randomUUID(),
        tenantId,
        userId,
        event,
        requestId,
        JSON.stringify(metadata),
      ],
    );
  }
  private async loadContext(
    hash: string,
    client?: PoolClient,
  ): Promise<AuthContext | null> {
    const database = client ?? this.database.pool;
    const row = (
      await database.query<SessionRow>(
        `SELECT u.id,u.email,u.display_name,s.tenant_id,t.name AS tenant_name,t.kind AS tenant_kind,m.role,s.csrf_token
      FROM auth_sessions s JOIN app_users u ON u.id=s.user_id JOIN tenants t ON t.id=s.tenant_id
      JOIN memberships m ON m.user_id=u.id AND m.tenant_id=t.id WHERE s.token_hash=$1 AND s.expires_at>now()`,
        [hash],
      )
    ).rows[0];
    if (!row) return null;
    const tenants = (
      await database.query<{
        id: string;
        name: string;
        role: TenantRole;
        kind: TenantKind;
      }>(
        'SELECT t.id,t.name,m.role,t.kind FROM memberships m JOIN tenants t ON t.id=m.tenant_id WHERE m.user_id=$1 ORDER BY t.created_at,t.id',
        [row.id],
      )
    ).rows;
    return {
      ...AuthSessionSchema.parse({
        user: { id: row.id, email: row.email, display_name: row.display_name },
        tenant: {
          id: row.tenant_id,
          name: row.tenant_name,
          role: row.role,
          kind: row.tenant_kind,
        },
        tenants,
        csrf_token: row.csrf_token,
      }),
      session_hash: hash,
    };
  }
  async authenticate(request: FastifyRequest): Promise<AuthContext> {
    const token = readSessionCookie(request.headers.cookie, this.cookieName);
    const context = token ? await this.loadContext(tokenHash(token)) : null;
    if (!context)
      throw new ApiProblem(
        401,
        'Sign in required',
        'Sign in to access this workspace.',
      );
    return context;
  }
  session(auth: AuthContext): AuthSession {
    return AuthSessionSchema.parse(auth);
  }
  private async createSession(
    client: PoolClient,
    userId: string,
    tenantId: string,
  ) {
    const token = secretToken(),
      hash = tokenHash(token);
    await client.query('DELETE FROM auth_sessions WHERE expires_at<=now()');
    await client.query(
      'DELETE FROM auth_sessions WHERE token_hash IN (SELECT token_hash FROM auth_sessions WHERE user_id=$1 ORDER BY created_at DESC OFFSET 9)',
      [userId],
    );
    await client.query(
      "INSERT INTO auth_sessions(token_hash,user_id,tenant_id,csrf_token,expires_at) VALUES($1,$2,$3,$4,now()+$5*interval '1 hour')",
      [hash, userId, tenantId, secretToken(), this.config.SESSION_TTL_HOURS],
    );
    return { token, context: (await this.loadContext(hash, client))! };
  }
  private invitationUnavailable(): never {
    throw new ApiProblem(
      400,
      'Invitation unavailable',
      'This invitation is unavailable, expired, already used, or belongs to a different email address.',
    );
  }
  private async consumeInvitation(
    client: PoolClient,
    token: string,
    email: string,
    userId: string,
    requestId: string,
  ): Promise<string> {
    const row = (
      await client.query<InviteRow>(
        'SELECT * FROM invitations WHERE token_hash=$1 FOR UPDATE',
        [tokenHash(token)],
      )
    ).rows[0];
    if (
      !row ||
      row.email !== email ||
      row.accepted_by ||
      row.revoked_at ||
      row.expires_at.getTime() <= Date.now()
    )
      this.invitationUnavailable();
    await client.query('SELECT 1 FROM app_users WHERE id=$1 FOR UPDATE', [
      userId,
    ]);
    if (
      (
        await client.query('SELECT 1 FROM memberships WHERE user_id=$1', [
          userId,
        ])
      ).rowCount! >= 20
    )
      throw new ApiProblem(
        409,
        'Workspace limit reached',
        'An account can belong to at most 20 workspaces.',
      );
    if (
      (
        await client.query(
          'SELECT 1 FROM memberships WHERE user_id=$1 AND tenant_id=$2',
          [userId, row.tenant_id],
        )
      ).rowCount
    )
      throw new ApiProblem(
        409,
        'Already a member',
        'You already belong to this workspace.',
      );
    await client.query(
      'INSERT INTO memberships(user_id,tenant_id,role) VALUES($1,$2,$3)',
      [userId, row.tenant_id, row.role],
    );
    await client.query('UPDATE invitations SET accepted_by=$2 WHERE id=$1', [
      row.id,
      userId,
    ]);
    await this.security(
      client,
      'invitation_accepted',
      requestId,
      userId,
      row.tenant_id,
      { invitation_id: row.id, role: row.role },
    );
    return row.tenant_id;
  }
  async register(body: unknown, request: FastifyRequest, reply: FastifyReply) {
    this.assertOrigin(request);
    const input = validate(AuthRegisterSchema, body);
    this.rateLimit(request, 'register', input.email);
    const encoded = await passwordHash(input.password);
    const result = await this.transaction(async (client) => {
      await client.query(
        "SELECT pg_advisory_xact_lock(hashtext('wiut-register-tenant-v1'))",
      );
      if (
        (
          await client.query('SELECT 1 FROM app_users WHERE email=$1', [
            input.email,
          ])
        ).rowCount
      )
        throw new ApiProblem(
          409,
          'Account already exists',
          'Sign in with this account to continue.',
        );
      const userId = randomUUID();
      await client.query(
        'INSERT INTO app_users(id,email,display_name,password_hash) VALUES($1,$2,$3,$4)',
        [userId, input.email, input.display_name, encoded],
      );
      let tenantId: string;
      if (input.invitation_token)
        tenantId = await this.consumeInvitation(
          client,
          input.invitation_token,
          input.email,
          userId,
          request.id,
        );
      else {
        const legacy = (
          await client.query<{ id: string }>(
            'SELECT id FROM tenants WHERE is_legacy=true AND NOT EXISTS(SELECT 1 FROM memberships WHERE tenant_id=tenants.id) FOR UPDATE',
          )
        ).rows[0];
        if (legacy) {
          tenantId = legacy.id;
          await client.query('UPDATE tenants SET name=$2 WHERE id=$1', [
            tenantId,
            input.tenant_name,
          ]);
        } else {
          tenantId = randomUUID();
          await client.query('INSERT INTO tenants(id,name) VALUES($1,$2)', [
            tenantId,
            input.tenant_name,
          ]);
        }
        await client.query(
          "INSERT INTO memberships(user_id,tenant_id,role) VALUES($1,$2,'admin')",
          [userId, tenantId],
        );
      }
      await this.security(
        client,
        'account_registered',
        request.id,
        userId,
        tenantId,
      );
      return this.createSession(client, userId, tenantId);
    });
    this.cookie(reply, result.token);
    return this.session(result.context);
  }
  async login(body: unknown, request: FastifyRequest, reply: FastifyReply) {
    this.assertOrigin(request);
    const input = validate(AuthLoginSchema, body);
    this.rateLimit(request, 'login', input.email);
    const user = (
      await this.database.pool.query<{ id: string; password_hash: string }>(
        'SELECT id,password_hash FROM app_users WHERE email=$1',
        [input.email],
      )
    ).rows[0];
    if (!(await verifyPassword(input.password, user?.password_hash)) || !user) {
      await this.security(
        this.database.pool,
        'account_sign_in_failed',
        request.id,
        user?.id ?? null,
        null,
      );
      throw new ApiProblem(
        401,
        'Sign in failed',
        'The email or password is incorrect.',
      );
    }
    let result;
    try {
      result = await this.transaction(async (client) => {
        const locked = (
          await client.query<SecurityUserRow>(
            'SELECT * FROM app_users WHERE id=$1 FOR UPDATE',
            [user.id],
          )
        ).rows[0];
        if (!locked || locked.password_hash !== user.password_hash)
          throw new ApiProblem(
            401,
            'Sign in failed',
            'The email or password is incorrect.',
          );
        await this.verifyFactor(client, locked, input, 401);
        const tenant = (
          await client.query<{ tenant_id: string }>(
            'SELECT tenant_id FROM memberships WHERE user_id=$1 ORDER BY created_at,tenant_id LIMIT 1',
            [user.id],
          )
        ).rows[0];
        if (!tenant)
          throw new ApiProblem(
            401,
            'Sign in failed',
            'This account has no workspace membership.',
          );
        await this.security(
          client,
          'account_signed_in',
          request.id,
          user.id,
          tenant.tenant_id,
        );
        return this.createSession(client, user.id, tenant.tenant_id);
      });
    } catch (error) {
      await this.security(
        this.database.pool,
        'account_sign_in_failed',
        request.id,
        user.id,
        null,
        {
          reason:
            error instanceof ApiProblem
              ? (error.code ?? 'request_rejected')
              : 'service_unavailable',
        },
      );
      throw error;
    }
    this.cookie(reply, result.token);
    return this.session(result.context);
  }
  async logout(auth: AuthContext, requestId: string, reply: FastifyReply) {
    await this.transaction(async (client) => {
      await client.query('DELETE FROM auth_sessions WHERE token_hash=$1', [
        auth.session_hash,
      ]);
      await this.security(
        client,
        'account_signed_out',
        requestId,
        auth.user.id,
        auth.tenant.id,
      );
    });
    this.cookie(reply, null);
    return { ok: true as const };
  }
  private async verifyFactor(
    client: PoolClient,
    user: SecurityUserRow,
    input: FactorInput,
    status: 401 | 403 = 403,
  ) {
    if (!user.mfa_secret_encrypted) return;
    if (!input.totp_code && !input.recovery_code)
      throw new ApiProblem(
        status,
        'Authenticator required',
        'Enter a fresh authenticator code or an unused MFA recovery code.',
        undefined,
        'mfa_required',
      );
    if (input.recovery_code) {
      const consumed = await client.query(
        'DELETE FROM mfa_recovery_codes WHERE user_id=$1 AND code_hash=$2 RETURNING code_hash',
        [user.id, recoveryHash(user.id, input.recovery_code, 'mfa')],
      );
      if (consumed.rowCount) return;
    } else if (input.totp_code) {
      const secret = decryptTotp(
        user.mfa_secret_encrypted,
        this.config.AUTH_ENCRYPTION_KEY,
        user.id,
        'enabled',
      );
      const counter = totpCounter(
        secret,
        input.totp_code,
        user.mfa_last_counter === null ? null : Number(user.mfa_last_counter),
      );
      if (counter !== null) {
        await client.query(
          'UPDATE app_users SET mfa_last_counter=$2 WHERE id=$1',
          [user.id, counter],
        );
        return;
      }
    }
    throw new ApiProblem(
      status,
      'Verification failed',
      'The code is invalid or already used. Enter a fresh authenticator code or an unused MFA recovery code.',
      undefined,
      'invalid_factor',
    );
  }
  private async verifyCurrent(
    client: PoolClient,
    user: SecurityUserRow,
    input: FactorInput & { current_password: string },
  ) {
    if (!(await verifyPassword(input.current_password, user.password_hash)))
      throw new ApiProblem(
        403,
        'Verification failed',
        'The current password is incorrect.',
        undefined,
        'invalid_credentials',
      );
    await this.verifyFactor(client, user, input);
  }
  private async securityAction<T>(
    action: string,
    auth: AuthContext,
    request: FastifyRequest,
    operation: (client: PoolClient, user: SecurityUserRow) => Promise<T>,
  ): Promise<T> {
    this.rateLimit(request, 'security', auth.user.email);
    try {
      return await this.transaction(async (client) => {
        const user = (
          await client.query<SecurityUserRow>(
            'SELECT * FROM app_users WHERE id=$1 FOR UPDATE',
            [auth.user.id],
          )
        ).rows[0];
        if (
          !user ||
          !(
            await client.query(
              'SELECT 1 FROM auth_sessions WHERE token_hash=$1 AND user_id=$2 AND expires_at>now()',
              [auth.session_hash, auth.user.id],
            )
          ).rowCount
        )
          throw new ApiProblem(
            401,
            'Sign in required',
            'Sign in to access this workspace.',
          );
        const result = await operation(client, user);
        await this.security(
          client,
          action,
          request.id,
          auth.user.id,
          auth.tenant.id,
        );
        return result;
      });
    } catch (error) {
      await this.security(
        this.database.pool,
        `${action}_failed`,
        request.id,
        auth.user.id,
        auth.tenant.id,
        {
          reason:
            error instanceof ApiProblem
              ? (error.code ?? 'request_rejected')
              : 'service_unavailable',
        },
      );
      throw error;
    }
  }
  private async revokeOtherSessions(client: PoolClient, auth: AuthContext) {
    await client.query(
      'DELETE FROM auth_sessions WHERE user_id=$1 AND token_hash<>$2',
      [auth.user.id, auth.session_hash],
    );
  }
  private async replaceRecoveryCodes(
    client: PoolClient,
    userId: string,
  ): Promise<string[]> {
    const codes = newRecoveryCodes();
    await client.query('DELETE FROM mfa_recovery_codes WHERE user_id=$1', [
      userId,
    ]);
    for (const code of codes)
      await client.query(
        'INSERT INTO mfa_recovery_codes(user_id,code_hash) VALUES($1,$2)',
        [userId, recoveryHash(userId, code, 'mfa')],
      );
    return codes;
  }
  async securityStatus(auth: AuthContext) {
    const user = (
      await this.database.pool.query<SecurityUserRow>(
        'SELECT * FROM app_users WHERE id=$1',
        [auth.user.id],
      )
    ).rows[0];
    if (!user)
      throw new ApiProblem(
        401,
        'Sign in required',
        'Sign in to access this workspace.',
      );
    const remaining = (
      await this.database.pool.query<{ count: string }>(
        'SELECT count(*) FROM mfa_recovery_codes WHERE user_id=$1',
        [auth.user.id],
      )
    ).rows[0]!.count;
    return AuthSecuritySchema.parse({
      mfa_available: Boolean(this.config.AUTH_ENCRYPTION_KEY),
      mfa_enabled: Boolean(user.mfa_secret_encrypted),
      recovery_codes_remaining: Number(remaining),
      recovery_key_configured: Boolean(user.account_recovery_key_hash),
      mfa_setup_expires_at:
        user.mfa_pending_expires_at &&
        user.mfa_pending_expires_at.getTime() > Date.now()
          ? user.mfa_pending_expires_at.toISOString()
          : null,
    });
  }
  async setupMfa(body: unknown, auth: AuthContext, request: FastifyRequest) {
    const input = validate(MfaSetupSchema, body);
    return this.securityAction(
      'mfa_setup_started',
      auth,
      request,
      async (client, user) => {
        if (user.mfa_secret_encrypted)
          throw new ApiProblem(
            409,
            'Authenticator already enabled',
            'Disable the current authenticator before enrolling another device.',
          );
        await this.verifyCurrent(client, user, input);
        const secret = newTotpSecret(),
          expires = new Date(Date.now() + 10 * 60 * 1000);
        await client.query(
          'UPDATE app_users SET mfa_pending_secret_encrypted=$2,mfa_pending_expires_at=$3 WHERE id=$1',
          [
            user.id,
            encryptTotp(
              secret,
              this.config.AUTH_ENCRYPTION_KEY,
              user.id,
              'pending',
            ),
            expires,
          ],
        );
        return MfaSetupResponseSchema.parse({
          secret,
          otpauth_uri: authenticatorUri(secret, user.email),
          expires_at: expires.toISOString(),
        });
      },
    );
  }
  async confirmMfa(body: unknown, auth: AuthContext, request: FastifyRequest) {
    const input = validate(MfaConfirmSchema, body);
    return this.securityAction(
      'mfa_enabled',
      auth,
      request,
      async (client, user) => {
        if (
          user.mfa_secret_encrypted ||
          !user.mfa_pending_secret_encrypted ||
          !user.mfa_pending_expires_at ||
          user.mfa_pending_expires_at.getTime() <= Date.now()
        )
          throw new ApiProblem(
            409,
            'Setup expired',
            'Start a new authenticator setup before confirming.',
          );
        const secret = decryptTotp(
          user.mfa_pending_secret_encrypted,
          this.config.AUTH_ENCRYPTION_KEY,
          user.id,
          'pending',
        );
        const counter = totpCounter(secret, input.totp_code, null);
        if (counter === null)
          throw new ApiProblem(
            403,
            'Verification failed',
            'The authenticator code is invalid. Check your device clock and try again.',
            undefined,
            'invalid_factor',
          );
        await client.query(
          'UPDATE app_users SET mfa_secret_encrypted=$2,mfa_last_counter=$3,mfa_pending_secret_encrypted=NULL,mfa_pending_expires_at=NULL WHERE id=$1',
          [
            user.id,
            encryptTotp(
              secret,
              this.config.AUTH_ENCRYPTION_KEY,
              user.id,
              'enabled',
            ),
            counter,
          ],
        );
        const codes = await this.replaceRecoveryCodes(client, user.id);
        await this.revokeOtherSessions(client, auth);
        return MfaRecoveryCodesResponseSchema.parse({ recovery_codes: codes });
      },
    );
  }
  async disableMfa(body: unknown, auth: AuthContext, request: FastifyRequest) {
    const input = validate(AuthVerifySchema, body);
    return this.securityAction(
      'mfa_disabled',
      auth,
      request,
      async (client, user) => {
        await this.verifyCurrent(client, user, input);
        await client.query(
          'UPDATE app_users SET mfa_secret_encrypted=NULL,mfa_last_counter=NULL,mfa_pending_secret_encrypted=NULL,mfa_pending_expires_at=NULL WHERE id=$1',
          [user.id],
        );
        await client.query('DELETE FROM mfa_recovery_codes WHERE user_id=$1', [
          user.id,
        ]);
        await this.revokeOtherSessions(client, auth);
        return { ok: true as const };
      },
    );
  }
  async rotateMfaRecoveryCodes(
    body: unknown,
    auth: AuthContext,
    request: FastifyRequest,
  ) {
    const input = validate(AuthVerifySchema, body);
    return this.securityAction(
      'mfa_recovery_codes_rotated',
      auth,
      request,
      async (client, user) => {
        if (!user.mfa_secret_encrypted)
          throw new ApiProblem(
            409,
            'Authenticator required',
            'Enable an authenticator before generating MFA recovery codes.',
          );
        await this.verifyCurrent(client, user, input);
        const codes = await this.replaceRecoveryCodes(client, user.id);
        await this.revokeOtherSessions(client, auth);
        return MfaRecoveryCodesResponseSchema.parse({ recovery_codes: codes });
      },
    );
  }
  async rotateAccountRecoveryKey(
    body: unknown,
    auth: AuthContext,
    request: FastifyRequest,
  ) {
    const input = validate(AuthVerifySchema, body);
    return this.securityAction(
      'account_recovery_key_rotated',
      auth,
      request,
      async (client, user) => {
        await this.verifyCurrent(client, user, input);
        const key = secretToken();
        await client.query(
          'UPDATE app_users SET account_recovery_key_hash=$2 WHERE id=$1',
          [user.id, recoveryHash(user.id, key, 'account')],
        );
        await this.revokeOtherSessions(client, auth);
        return AccountRecoveryKeyResponseSchema.parse({ recovery_key: key });
      },
    );
  }
  async changePassword(
    body: unknown,
    auth: AuthContext,
    request: FastifyRequest,
  ) {
    const input = validate(PasswordChangeSchema, body);
    if (input.current_password === input.new_password)
      throw new ApiProblem(
        400,
        'Choose a new password',
        'The new password must differ from the current password.',
      );
    return this.securityAction(
      'password_changed',
      auth,
      request,
      async (client, user) => {
        await this.verifyCurrent(client, user, input);
        const encoded = await passwordHash(input.new_password);
        await client.query(
          'UPDATE app_users SET password_hash=$2,mfa_pending_secret_encrypted=NULL,mfa_pending_expires_at=NULL WHERE id=$1',
          [user.id, encoded],
        );
        await this.revokeOtherSessions(client, auth);
        await client.query(
          'UPDATE auth_sessions SET csrf_token=$2 WHERE token_hash=$1',
          [auth.session_hash, secretToken()],
        );
        return this.session(
          (await this.loadContext(auth.session_hash, client))!,
        );
      },
    );
  }
  async recoverAccount(
    body: unknown,
    request: FastifyRequest,
    reply: FastifyReply,
  ) {
    this.assertOrigin(request);
    const input = validate(AccountRecoverSchema, body);
    this.rateLimit(request, 'recover', input.email);
    const encoded = await passwordHash(input.new_password);
    const result = await this.transaction(async (client) => {
      const user = (
        await client.query<SecurityUserRow>(
          'SELECT * FROM app_users WHERE email=$1 FOR UPDATE',
          [input.email],
        )
      ).rows[0];
      const suppliedHash = recoveryHash(
        user?.id ?? 'unknown',
        input.recovery_key,
        'account',
      );
      const expectedHash = user?.account_recovery_key_hash ?? '0'.repeat(64);
      const valid =
        timingSafeEqual(
          Buffer.from(suppliedHash, 'hex'),
          Buffer.from(expectedHash, 'hex'),
        ) && Boolean(user?.account_recovery_key_hash);
      if (!valid || !user) {
        await this.security(
          client,
          'account_recovery_failed',
          request.id,
          user?.id ?? null,
          null,
        );
        return false;
      }
      await client.query(
        'UPDATE app_users SET password_hash=$2,account_recovery_key_hash=NULL,mfa_secret_encrypted=NULL,mfa_last_counter=NULL,mfa_pending_secret_encrypted=NULL,mfa_pending_expires_at=NULL WHERE id=$1',
        [user.id, encoded],
      );
      await client.query('DELETE FROM mfa_recovery_codes WHERE user_id=$1', [
        user.id,
      ]);
      await client.query('DELETE FROM auth_sessions WHERE user_id=$1', [
        user.id,
      ]);
      await this.security(
        client,
        'account_recovered',
        request.id,
        user.id,
        null,
      );
      return true;
    });
    if (!result)
      throw new ApiProblem(
        401,
        'Recovery failed',
        'The account recovery code is invalid or already used.',
        undefined,
        'invalid_recovery',
      );
    this.cookie(reply, null);
    return { ok: true as const };
  }
  private admin(auth: AuthContext) {
    if (auth.tenant.role !== 'admin')
      throw new ApiProblem(
        403,
        'Administrator required',
        'Only workspace administrators can manage this team.',
      );
  }
  async team(auth: AuthContext) {
    this.admin(auth);
    const members = (
      await this.database.pool.query(
        'SELECT u.id,u.email,u.display_name,m.role,m.created_at AS joined_at FROM memberships m JOIN app_users u ON u.id=m.user_id WHERE m.tenant_id=$1 ORDER BY m.created_at,u.id LIMIT 500',
        [auth.tenant.id],
      )
    ).rows.map((row) => ({
      ...row,
      joined_at: (row.joined_at as Date).toISOString(),
    }));
    const invitations = (
      await this.database.pool.query<InviteRow>(
        'SELECT * FROM invitations WHERE tenant_id=$1 ORDER BY created_at DESC,id LIMIT 100',
        [auth.tenant.id],
      )
    ).rows.map(invitationView);
    return TeamSchema.parse({ members, invitations });
  }
  async createTenant(
    body: unknown,
    auth: AuthContext,
    requestId: string,
    kind: TenantKind = 'bank',
  ) {
    const input = validate(TenantCreateSchema, body);
    await this.transaction(async (client) => {
      await client.query('SELECT 1 FROM app_users WHERE id=$1 FOR UPDATE', [
        auth.user.id,
      ]);
      const currentSession = await client.query(
        'SELECT 1 FROM auth_sessions WHERE token_hash=$1 AND user_id=$2 AND tenant_id=$3 AND csrf_token=$4 AND expires_at>now() FOR UPDATE',
        [auth.session_hash, auth.user.id, auth.tenant.id, auth.csrf_token],
      );
      if (!currentSession.rowCount)
        throw new ApiProblem(
          409,
          'Session changed',
          'Refresh your session before creating a workspace.',
        );
      if (
        (
          await client.query('SELECT 1 FROM memberships WHERE user_id=$1', [
            auth.user.id,
          ])
        ).rowCount! >= 20
      )
        throw new ApiProblem(
          409,
          'Workspace limit reached',
          'An account can belong to at most 20 workspaces.',
        );
      const id = randomUUID();
      await client.query('INSERT INTO tenants(id,name,kind) VALUES($1,$2,$3)', [
        id,
        input.name,
        kind,
      ]);
      await client.query(
        "INSERT INTO memberships(user_id,tenant_id,role) VALUES($1,$2,'admin')",
        [auth.user.id, id],
      );
      await client.query(
        'UPDATE auth_sessions SET tenant_id=$2,csrf_token=$3 WHERE token_hash=$1',
        [auth.session_hash, id, secretToken()],
      );
      await this.security(
        client,
        kind === 'showcase'
          ? 'showcase_workspace_created'
          : 'workspace_created',
        requestId,
        auth.user.id,
        id,
        { kind },
      );
    });
    return this.session((await this.loadContext(auth.session_hash))!);
  }
  async switchTenant(body: unknown, auth: AuthContext, requestId: string) {
    const input = validate(TenantSwitchSchema, body);
    await this.transaction(async (client) => {
      if (
        !(
          await client.query(
            'SELECT 1 FROM memberships WHERE user_id=$1 AND tenant_id=$2',
            [auth.user.id, input.tenant_id],
          )
        ).rowCount
      )
        throw new ApiProblem(
          404,
          'Workspace not found',
          'The requested workspace does not exist.',
        );
      await client.query(
        'UPDATE auth_sessions SET tenant_id=$2,csrf_token=$3 WHERE token_hash=$1',
        [auth.session_hash, input.tenant_id, secretToken()],
      );
      await this.security(
        client,
        'workspace_switched',
        requestId,
        auth.user.id,
        input.tenant_id,
      );
    });
    return this.session((await this.loadContext(auth.session_hash))!);
  }
  async createInvitation(
    body: unknown,
    auth: AuthContext,
    requestId: string,
    origin: string,
  ) {
    this.admin(auth);
    if (!this.config.corsOrigins.includes(origin))
      throw new ApiProblem(
        403,
        'Origin rejected',
        'Submit this request from the configured application origin.',
      );
    const input = validate(InvitationCreateSchema, body),
      token = secretToken();
    const row = await this.transaction(async (client) => {
      await client.query('SELECT 1 FROM tenants WHERE id=$1 FOR UPDATE', [
        auth.tenant.id,
      ]);
      if (
        (
          await client.query(
            'SELECT 1 FROM memberships m JOIN app_users u ON u.id=m.user_id WHERE m.tenant_id=$1 AND u.email=$2',
            [auth.tenant.id, input.email],
          )
        ).rowCount
      )
        throw new ApiProblem(
          409,
          'Already a member',
          'This account already belongs to the workspace.',
        );
      if (
        (
          await client.query(
            'SELECT 1 FROM invitations WHERE tenant_id=$1 AND email=$2 AND accepted_by IS NULL AND revoked_at IS NULL AND expires_at>now()',
            [auth.tenant.id, input.email],
          )
        ).rowCount
      )
        throw new ApiProblem(
          409,
          'Invitation already pending',
          'Revoke the existing invitation before creating another.',
        );
      const result = (
        await client.query<InviteRow>(
          "INSERT INTO invitations(id,tenant_id,email,role,token_hash,created_by,expires_at) VALUES($1,$2,$3,$4,$5,$6,now()+interval '7 days') RETURNING *",
          [
            randomUUID(),
            auth.tenant.id,
            input.email,
            input.role,
            tokenHash(token),
            auth.user.id,
          ],
        )
      ).rows[0]!;
      await this.security(
        client,
        'invitation_created',
        requestId,
        auth.user.id,
        auth.tenant.id,
        { invitation_id: result.id, email: input.email, role: input.role },
      );
      return result;
    });
    return InvitationCreateResponseSchema.parse({
      invitation: invitationView(row),
      token,
      invitation_url: `${origin}/#invite?token=${token}`,
    });
  }
  async acceptInvitation(body: unknown, auth: AuthContext, requestId: string) {
    const input = validate(InvitationAcceptSchema, body);
    await this.transaction(async (client) => {
      const tenantId = await this.consumeInvitation(
        client,
        input.token,
        auth.user.email,
        auth.user.id,
        requestId,
      );
      await client.query(
        'UPDATE auth_sessions SET tenant_id=$2,csrf_token=$3 WHERE token_hash=$1',
        [auth.session_hash, tenantId, secretToken()],
      );
    });
    return this.session((await this.loadContext(auth.session_hash))!);
  }
  async revokeInvitation(id: string, auth: AuthContext, requestId: string) {
    this.admin(auth);
    if (
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
        id,
      )
    )
      throw new ApiProblem(
        404,
        'Invitation not found',
        'The requested invitation does not exist.',
      );
    await this.transaction(async (client) => {
      const row = (
        await client.query<InviteRow>(
          'SELECT * FROM invitations WHERE id=$1 AND tenant_id=$2 FOR UPDATE',
          [id, auth.tenant.id],
        )
      ).rows[0];
      if (!row)
        throw new ApiProblem(
          404,
          'Invitation not found',
          'The requested invitation does not exist.',
        );
      if (row.accepted_by)
        throw new ApiProblem(
          409,
          'Invitation already accepted',
          'An accepted invitation cannot be revoked.',
        );
      await client.query(
        'UPDATE invitations SET revoked_at=COALESCE(revoked_at,now()) WHERE id=$1 AND tenant_id=$2',
        [id, auth.tenant.id],
      );
      await this.security(
        client,
        'invitation_revoked',
        requestId,
        auth.user.id,
        auth.tenant.id,
        { invitation_id: id },
      );
    });
    return { ok: true as const };
  }
}

@Injectable()
export class AuthGuard implements CanActivate {
  constructor(
    private readonly auth: AuthService,
    private readonly reflector: Reflector,
  ) {}
  async canActivate(context: ExecutionContext): Promise<boolean> {
    if (
      this.reflector.getAllAndOverride<boolean>('wiut:public', [
        context.getHandler(),
        context.getClass(),
      ])
    )
      return true;
    const request = context.switchToHttp().getRequest<FastifyRequest>();
    request.auth = await this.auth.authenticate(request);
    const expectedTenant = request.headers['x-tenant-id'];
    const refresh = this.reflector.getAllAndOverride<boolean>(
      'wiut:session-refresh',
      [context.getHandler(), context.getClass()],
    );
    if (
      !refresh &&
      expectedTenant !== undefined &&
      expectedTenant !== request.auth.tenant.id
    )
      throw new ApiProblem(
        409,
        'Workspace changed',
        'Your active workspace changed. Refresh the session before continuing.',
      );
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method)) {
      this.auth.assertOrigin(request);
      assertCsrf(request.headers['x-csrf-token'], request.auth.csrf_token);
    }
    return true;
  }
}
