import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { type AuthSession } from '@wiut/contracts';
import {
  Download,
  KeyRound,
  Loader2,
  LockKeyhole,
  ShieldCheck,
} from 'lucide-react';
import { toast } from 'sonner';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { api } from '@/lib/api';

type SecurityAction = 'setup' | 'disable' | 'codes' | 'recovery' | 'password';
const actionTitles: Record<SecurityAction, string> = {
  setup: 'Set up authenticator',
  disable: 'Turn off two-step verification',
  codes: 'Replace authenticator backup codes',
  recovery: 'Generate account recovery code',
  password: 'Change password',
};
const actionDescriptions: Record<SecurityAction, string> = {
  setup: 'Confirm your password to connect an authenticator app.',
  disable:
    'Your account will use only a password to sign in. Confirm your password and current second factor.',
  codes:
    'The previous backup codes will stop working. Each new code can be used once in place of an authenticator code.',
  recovery:
    'This private code lets you reset a forgotten password and regain access if your authenticator is lost. Any previous account recovery code will stop working.',
  password:
    'Use at least 12 characters. Your other signed-in sessions will end.',
};

export function AccountSecurityPage({
  session,
  onSessionChange,
}: {
  session: AuthSession;
  onSessionChange: (next: AuthSession) => Promise<void>;
}) {
  const security = useQuery({
    queryKey: ['account-security', session.user.id],
    queryFn: api.security,
  });
  const [action, setAction] = useState<SecurityAction | null>(null);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [factorMethod, setFactorMethod] = useState('totp');
  const [factor, setFactor] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [setup, setSetup] = useState<{
    secret: string;
    expires_at: string;
  } | null>(null);
  const [setupCode, setSetupCode] = useState('');
  const [generated, setGenerated] = useState<{
    kind: 'account' | 'authenticator';
    codes: string[];
  } | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    if (!setup) return;
    const expiry = window.setTimeout(
      () => {
        setSetup(null);
        setSetupCode('');
        setError(null);
        toast.info('Authenticator setup expired. Start setup again.');
      },
      Math.max(0, new Date(setup.expires_at).getTime() - Date.now()),
    );
    return () => window.clearTimeout(expiry);
  }, [setup]);

  function clearFields() {
    setCurrentPassword('');
    setNewPassword('');
    setConfirmPassword('');
    setFactor('');
    setFactorMethod('totp');
    setError(null);
  }
  function openAction(next: SecurityAction) {
    clearFields();
    setAction(next);
  }
  async function perform(operation: () => Promise<void>) {
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      await operation();
    } catch (caught) {
      if (alive.current)
        setError(caught instanceof Error ? caught.message : 'Please retry.');
    } finally {
      if (alive.current) setPending(false);
    }
  }
  async function submitAction() {
    if (!action) return;
    const verify = {
      current_password: currentPassword,
      ...(security.data?.mfa_enabled && action !== 'setup'
        ? factorMethod === 'backup'
          ? { recovery_code: factor.trim() }
          : { totp_code: factor.trim() }
        : {}),
    };
    await perform(async () => {
      if (action === 'password' && newPassword !== confirmPassword)
        throw new Error('The new passwords do not match.');
      if (action === 'setup') {
        const result = await api.setupMfa({
          current_password: currentPassword,
        });
        if (!alive.current) return;
        setSetup({ secret: result.secret, expires_at: result.expires_at });
        setSetupCode('');
      } else if (action === 'disable') {
        await api.disableMfa(verify);
        if (!alive.current) return;
        toast.success('Two-step verification turned off');
      } else if (action === 'codes') {
        const result = await api.rotateMfaCodes(verify);
        if (!alive.current) return;
        setGenerated({ kind: 'authenticator', codes: result.recovery_codes });
      } else if (action === 'recovery') {
        const result = await api.rotateRecoveryKey(verify);
        if (!alive.current) return;
        setGenerated({ kind: 'account', codes: [result.recovery_key] });
      } else {
        const next = await api.changePassword({
          ...verify,
          new_password: newPassword,
        });
        if (!alive.current) return;
        clearFields();
        setAction(null);
        await onSessionChange(next);
        toast.success('Password changed. Other sessions have ended.');
        return;
      }
      clearFields();
      setAction(null);
      await security.refetch();
    });
  }
  function downloadCodes() {
    if (!generated) return;
    const account = generated.kind === 'account';
    const contents = [
      `FlowCredit ${account ? 'account recovery code' : 'authenticator backup codes'}`,
      session.user.email,
      '',
      ...generated.codes,
      '',
      account
        ? 'Use once with Forgot password to reset your password and two-step verification.'
        : 'Use each code once in place of your authenticator code when signing in.',
      'Store this file privately. Anyone with an account recovery code can regain access to your account.',
    ].join('\n');
    const url = URL.createObjectURL(
      new Blob([contents], { type: 'text/plain;charset=utf-8' }),
    );
    const link = document.createElement('a');
    link.href = url;
    link.download = account
      ? 'flowcredit-account-recovery.txt'
      : 'flowcredit-authenticator-backup-codes.txt';
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
  }

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <p className="text-xs font-medium tracking-widest text-primary uppercase">
          Your account
        </p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
          Account security
        </h1>
        <p className="mt-2 break-all text-sm text-muted-foreground">
          Protect your sign-in and recovery access for {session.user.email}.
        </p>
      </div>
      {security.isPending ? (
        <Skeleton className="h-48 w-full" />
      ) : security.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Account settings unavailable</AlertTitle>
          <AlertDescription>
            {security.error.message}
            <Button
              variant="outline"
              size="sm"
              onClick={() => void security.refetch()}
            >
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      ) : security.data ? (
        <div className="grid gap-5 md:grid-cols-2">
          <Card className="gap-5 shadow-none">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ShieldCheck className="size-5 text-primary" />
                Two-step verification
              </CardTitle>
              <CardDescription>
                Add a time-based code from your authenticator app when signing
                in.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Badge
                variant={security.data.mfa_enabled ? 'default' : 'secondary'}
              >
                {security.data.mfa_enabled ? 'Enabled' : 'Not enabled'}
              </Badge>
              {security.data.mfa_enabled ? (
                <>
                  <p className="text-sm text-muted-foreground">
                    {security.data.recovery_codes_remaining} unused
                    authenticator backup codes. Each can replace your app code
                    once.
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="outline"
                      onClick={() => openAction('codes')}
                    >
                      Replace backup codes
                    </Button>
                    <Button
                      variant="ghost"
                      onClick={() => openAction('disable')}
                    >
                      Turn off
                    </Button>
                  </div>
                </>
              ) : (
                <>
                  {!security.data.mfa_available && (
                    <p className="text-sm text-muted-foreground">
                      Authenticator setup is temporarily unavailable. Ask your
                      administrator to enable account protection on the server.
                    </p>
                  )}
                  <Button
                    disabled={!security.data.mfa_available}
                    onClick={() => openAction('setup')}
                  >
                    Set up authenticator
                  </Button>
                </>
              )}
            </CardContent>
          </Card>
          <Card className="gap-5 shadow-none">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <KeyRound className="size-5 text-primary" />
                Account recovery
              </CardTitle>
              <CardDescription>
                Keep a private recovery code to reset a forgotten password
                without email delivery.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Badge
                variant={
                  security.data.recovery_key_configured
                    ? 'default'
                    : 'secondary'
                }
              >
                {security.data.recovery_key_configured
                  ? 'Recovery code saved'
                  : 'No recovery code'}
              </Badge>
              <p className="text-sm leading-relaxed text-muted-foreground">
                Save it somewhere safe outside this app. Using it resets your
                password, turns off two-step verification, and ends all
                signed-in sessions.
              </p>
              <Button variant="outline" onClick={() => openAction('recovery')}>
                {security.data.recovery_key_configured
                  ? 'Replace recovery code'
                  : 'Generate recovery code'}
              </Button>
            </CardContent>
          </Card>
          <Card className="gap-5 shadow-none md:col-span-2">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <LockKeyhole className="size-5 text-primary" />
                Password
              </CardTitle>
              <CardDescription>
                A unique password protects every workspace attached to your
                account.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button variant="outline" onClick={() => openAction('password')}>
                Change password
              </Button>
            </CardContent>
          </Card>
        </div>
      ) : null}

      <Dialog
        open={action !== null}
        onOpenChange={(open) => {
          if (!open && !pending) {
            setAction(null);
            clearFields();
          }
        }}
      >
        <DialogContent
          className="max-h-[90dvh] overflow-y-auto"
          showCloseButton={!pending}
          onEscapeKeyDown={(event) => {
            if (pending) event.preventDefault();
          }}
          onPointerDownOutside={(event) => {
            if (pending) event.preventDefault();
          }}
        >
          <DialogHeader>
            <DialogTitle>
              {action ? actionTitles[action] : 'Confirm account access'}
            </DialogTitle>
            <DialogDescription>
              {action ? actionDescriptions[action] : ''}
            </DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              void submitAction();
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="security-current-password">
                Current password
              </Label>
              <Input
                id="security-current-password"
                type="password"
                autoComplete="current-password"
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
                required
                maxLength={128}
                disabled={pending}
              />
            </div>
            {action === 'password' && (
              <>
                <div className="space-y-2">
                  <Label htmlFor="security-new-password">New password</Label>
                  <Input
                    id="security-new-password"
                    type="password"
                    autoComplete="new-password"
                    value={newPassword}
                    onChange={(event) => setNewPassword(event.target.value)}
                    required
                    minLength={12}
                    maxLength={128}
                    disabled={pending}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="security-confirm-password">
                    Confirm new password
                  </Label>
                  <Input
                    id="security-confirm-password"
                    type="password"
                    autoComplete="new-password"
                    value={confirmPassword}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                    required
                    minLength={12}
                    maxLength={128}
                    disabled={pending}
                  />
                </div>
              </>
            )}
            {security.data?.mfa_enabled && action !== 'setup' && (
              <>
                <div className="space-y-2">
                  <Label htmlFor="security-factor-method">
                    Verification method
                  </Label>
                  <Select
                    value={factorMethod}
                    onValueChange={(value) => {
                      setFactorMethod(value);
                      setFactor('');
                    }}
                    disabled={pending}
                  >
                    <SelectTrigger id="security-factor-method">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="totp">Authenticator app</SelectItem>
                      <SelectItem value="backup">
                        Authenticator backup code
                      </SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="security-factor">
                    {factorMethod === 'backup'
                      ? 'Authenticator backup code'
                      : 'Authenticator code'}
                  </Label>
                  <Input
                    id="security-factor"
                    value={factor}
                    onChange={(event) => setFactor(event.target.value)}
                    autoComplete="one-time-code"
                    inputMode={factorMethod === 'totp' ? 'numeric' : 'text'}
                    pattern={factorMethod === 'totp' ? '[0-9]{6}' : undefined}
                    maxLength={factorMethod === 'totp' ? 6 : 100}
                    required
                    disabled={pending}
                  />
                  <p className="text-xs text-muted-foreground">
                    Use a fresh app code or an unused backup code for each
                    change.
                  </p>
                </div>
              </>
            )}
            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={pending}
                onClick={() => {
                  setAction(null);
                  clearFields();
                }}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={pending}>
                {pending && <Loader2 className="animate-spin" />}
                {pending
                  ? 'Please wait…'
                  : action === 'setup'
                    ? 'Continue setup'
                    : 'Confirm change'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={setup !== null}
        onOpenChange={(open) => {
          if (!open && !pending) {
            setSetup(null);
            setSetupCode('');
            setError(null);
          }
        }}
      >
        <DialogContent
          className="max-h-[90dvh] overflow-y-auto"
          showCloseButton={!pending}
          onEscapeKeyDown={(event) => {
            if (pending) event.preventDefault();
          }}
          onPointerDownOutside={(event) => {
            if (pending) event.preventDefault();
          }}
        >
          <DialogHeader>
            <DialogTitle>Connect your authenticator</DialogTitle>
            <DialogDescription>
              In your authenticator app, add a time-based account using this
              setup key, then enter its six-digit code. This setup expires after
              10 minutes.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <p className="break-all text-sm">
              <span className="text-muted-foreground">Account:</span> FlowCredit
              · {session.user.email}
            </p>
            <Label htmlFor="authenticator-setup-key">
              Authenticator setup key
            </Label>
            <Input
              id="authenticator-setup-key"
              value={setup?.secret ?? ''}
              readOnly
              autoComplete="off"
              className="font-mono text-xs"
            />
            <p className="text-xs text-muted-foreground">
              Keep this key private. The app uses six digits, a 30-second
              interval, and the standard SHA-1 setting.
            </p>
          </div>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              void perform(async () => {
                const result = await api.confirmMfa({ totp_code: setupCode });
                if (!alive.current) return;
                setSetup(null);
                setSetupCode('');
                setGenerated({
                  kind: 'authenticator',
                  codes: result.recovery_codes,
                });
                toast.success('Two-step verification enabled');
                await security.refetch();
              });
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="authenticator-confirm-code">
                Authenticator code
              </Label>
              <Input
                id="authenticator-confirm-code"
                autoComplete="one-time-code"
                inputMode="numeric"
                pattern="[0-9]{6}"
                maxLength={6}
                value={setupCode}
                onChange={(event) => setSetupCode(event.target.value)}
                disabled={pending}
                required
              />
            </div>
            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={pending}
                onClick={() => {
                  setSetup(null);
                  setSetupCode('');
                  setError(null);
                }}
              >
                Cancel setup
              </Button>
              <Button type="submit" disabled={pending}>
                {pending && <Loader2 className="animate-spin" />}Enable two-step
                verification
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={generated !== null}
        onOpenChange={(open) => {
          if (!open) setGenerated(null);
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {generated?.kind === 'account'
                ? 'Save your account recovery code'
                : 'Save your authenticator backup codes'}
            </DialogTitle>
            <DialogDescription>
              These codes are shown once. Store them privately before closing
              this window.
            </DialogDescription>
          </DialogHeader>
          {generated?.kind === 'account' ? (
            <div className="space-y-2">
              <Label htmlFor="account-recovery-code">
                Account recovery code
              </Label>
              <Input
                id="account-recovery-code"
                value={generated.codes[0]}
                readOnly
                autoComplete="off"
                className="font-mono text-xs"
              />
            </div>
          ) : (
            <div
              aria-label="Authenticator backup codes"
              className="grid gap-2 rounded-md border bg-muted/30 p-4 font-mono text-sm sm:grid-cols-2"
            >
              {generated?.codes.map((code) => (
                <span key={code} className="min-w-0 break-all">
                  {code}
                </span>
              ))}
            </div>
          )}
          <Alert>
            <KeyRound />
            <AlertDescription>
              {generated?.kind === 'account'
                ? 'Anyone holding this code can reset your password and two-step verification. It can be used once with Forgot password.'
                : 'Use each backup code once in place of your authenticator code. These do not reset a forgotten password.'}
            </AlertDescription>
          </Alert>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={downloadCodes}>
              <Download />
              Download codes
            </Button>
            <Button type="button" onClick={() => setGenerated(null)}>
              I saved my codes
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
