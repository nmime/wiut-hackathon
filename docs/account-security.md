# Account security

Every signed-in member can open **Account security**. These controls apply to the account across all its workspace memberships. Workspace administrators cannot retrieve another person's secrets or reset their password through the team screen.

## Offline recovery

Generate an **account recovery key** while signed in by confirming your current password and, when enabled, a fresh MFA factor. Save the displayed key offline in a secure place. It is a random 256-bit credential, displayed once; the database holds a hash bound to the account and recovery purpose. Generating another key invalidates the previous one and revokes other sessions.

At sign-in, choose **Forgot password** and supply your email, recovery code and new password. The UI calls the account recovery key an account recovery code. A successful recovery consumes it, disables the authenticator, removes its backup codes and revokes every session. It does not sign you in automatically. Sign in with the new password, then generate a replacement recovery code and re-enable MFA if desired. An invalid, expired-by-rotation or already used key has the same rejection response as an unknown account.

There is no email delivery or automated support bypass. An account without a previously saved recovery key cannot use this recovery flow. Keep the recovery key separate from the device used to sign in.

## Authenticator and backup codes

Enable MFA by confirming your password, entering the displayed secret into a compatible authenticator as a time-based SHA-1 account, and submitting its six-digit code before the ten-minute setup expires. Enrollment is pending until confirmation succeeds. Confirming enrollment revokes other sessions and displays ten independent 128-bit MFA backup codes once.

MFA backup codes replace the authenticator code when signing in or confirming a security change; they do not reset a forgotten password. Each successful use consumes one code. Generating a new set invalidates every old code and revokes other sessions. Disabling MFA requires the current password and a fresh authenticator or unused backup code, then removes its codes and revokes other sessions.

Time-based codes use a 30-second step, allowing the adjacent steps for clock drift. An already accepted counter cannot be reused. Concurrent attempts serialize on the account row, so only one attempt can consume a given code. Keep the authenticator's clock synchronized and use a new code for each action. The implementation is checked against [RFC 4226](https://www.rfc-editor.org/rfc/rfc4226) and [RFC 6238](https://www.rfc-editor.org/rfc/rfc6238) vectors.

## Password changes and storage

Changing a password requires the current password and, when enabled, a fresh MFA factor. The current session remains signed in with a rotated CSRF token; other sessions are revoked. Passwords use scrypt. Security mutations retain the existing Origin and CSRF checks, authentication/recovery attempts are rate-limited, and successful and rejected security operations write audit events without plaintext secrets.

Authenticator secrets are encrypted using AES-256-GCM, with authentication bound to the account and pending/enabled state. `AUTH_ENCRYPTION_KEY` must be a persistent random 64-character hexadecimal value. Without it, new authenticator enrollment fails closed. Preserve it with database backups. Losing or replacing it prevents decryption of enrolled secrets, although unused MFA backup codes and the independent account recovery key remain usable. There is no automatic encryption-key rotation.

The UI keeps newly displayed secrets in temporary component state and clears them when dismissed or navigated away from. Secrets are not placed in URLs, browser persistent storage, query caches or audit metadata. Save them before closing their dialog; they cannot be recovered from the application.

## Operational limits

MFA is opt-in. This MVP does not provide passkeys, enforced workspace MFA policies, email verification, email alerts, a session-management screen or administrative account recovery. The rate limiter is process-local; operate one API process per database. Back up the database and private environment file together, and verify restores in a separate database. See [operations](operations.md).

The design follows the separation of login factors, recovery credentials and session invalidation described in the [OWASP MFA guidance](https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html) and [password recovery guidance](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html). These controls do not establish regulatory certification or real borrower model accuracy.
