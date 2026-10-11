import { useEffect, useState } from 'react';
import { type AuthSession } from '@wiut/contracts';
import {
  ArrowRight,
  Building2,
  FileCheck2,
  Landmark,
  Loader2,
  ShieldCheck,
} from 'lucide-react';
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
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { api, ApiError } from '@/lib/api';
import { readInvitationToken } from '@/lib/route';

export function AuthPage({
  onAuthenticated,
  notice,
}: {
  onAuthenticated: (
    session: AuthSession,
    resetRoute?: boolean,
  ) => Promise<void>;
  notice?: string;
}) {
  const initialToken = readInvitationToken();
  const [tab, setTab] = useState(initialToken ? 'register' : 'login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [tenantName, setTenantName] = useState('');
  const [invitationToken, setInvitationToken] = useState(initialToken);
  const [joining, setJoining] = useState(Boolean(initialToken));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [mfaRequired, setMfaRequired] = useState(false);
  const [factorMethod, setFactorMethod] = useState('totp');
  const [factor, setFactor] = useState('');
  const [recovering, setRecovering] = useState(false);
  const [recoveryKey, setRecoveryKey] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [recovered, setRecovered] = useState(false);
  function resetStep() {
    setError(null);
    setMfaRequired(false);
    setFactor('');
    setFactorMethod('totp');
    setPassword('');
    setRecoveryKey('');
    setNewPassword('');
    setConfirmPassword('');
  }
  async function submit() {
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      if (recovering) {
        if (newPassword !== confirmPassword)
          throw new Error('The new passwords do not match.');
        await api.recoverAccount({
          email,
          recovery_key: recoveryKey.trim(),
          new_password: newPassword,
        });
        resetStep();
        setRecovered(true);
      } else {
        const next =
          tab === 'login'
            ? await api.login({
                email,
                password,
                ...(mfaRequired
                  ? factorMethod === 'backup'
                    ? { recovery_code: factor.trim() }
                    : { totp_code: factor.trim() }
                  : {}),
              })
            : await api.register({
                email,
                password,
                display_name: displayName,
                ...(joining
                  ? { invitation_token: invitationToken }
                  : { tenant_name: tenantName }),
              });
        resetStep();
        await onAuthenticated(next, tab === 'register');
      }
    } catch (caught) {
      if (
        caught instanceof ApiError &&
        caught.code === 'mfa_required' &&
        !recovering
      ) {
        setMfaRequired(true);
        setFactor('');
      } else {
        setError(caught instanceof Error ? caught : new Error('Please retry.'));
      }
    } finally {
      setPending(false);
    }
  }
  useEffect(() => {
    const onHashChange = () => {
      const token = readInvitationToken();
      if (token) {
        resetStep();
        setRecovering(false);
        setInvitationToken(token);
        setJoining(true);
        setTab('register');
      }
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  return (
    <main className="grid min-h-dvh bg-background lg:grid-cols-[1fr_1fr]">
      <section className="hidden flex-col justify-between border-r bg-emerald-950 p-12 text-white lg:flex xl:p-16">
        <div className="flex items-center gap-3">
          <Landmark className="size-8 text-emerald-300" />
          <div>
            <p className="text-xl font-semibold tracking-tight">FlowCredit</p>
            <p className="text-xs text-emerald-200/80">
              Credit review workspace
            </p>
          </div>
        </div>
        <div className="max-w-lg space-y-8 py-12">
          <Badge
            className="border-emerald-600/50 bg-emerald-900/60 text-emerald-100"
            variant="outline"
          >
            For banks and credit teams
          </Badge>
          <div className="space-y-4">
            <h2 className="text-4xl leading-tight font-semibold tracking-tight xl:text-5xl">
              See the cash flow.
              <br />
              Make the call.
            </h2>
            <p className="text-base leading-relaxed text-emerald-100/80">
              A shared workspace for your credit team, from transaction history
              to an accountable human decision.
            </p>
          </div>
          <div className="space-y-5">
            {[
              {
                icon: Building2,
                title: 'Your team, your workspace',
                description:
                  'Separate portfolios for each bank or team, with admin and credit-officer access.',
              },
              {
                icon: FileCheck2,
                title: 'Evidence for every review',
                description:
                  'Cash flow forecasts, seasonal payment schedules, and a permanent decision record.',
              },
              {
                icon: ShieldCheck,
                title: 'Human-led decisions',
                description:
                  'The model measures payment capacity. Your officer records the final outcome.',
              },
            ].map(({ icon: Icon, title, description }) => (
              <div key={title} className="flex gap-4">
                <Icon className="mt-0.5 size-5 shrink-0 text-emerald-300" />
                <div>
                  <p className="text-sm font-medium">{title}</p>
                  <p className="mt-1 text-sm leading-relaxed text-emerald-100/70">
                    {description}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
        <p className="flex items-center gap-2 text-xs text-emerald-200/70">
          <ShieldCheck className="size-4" /> Your team's evidence. Your team's
          decision.
        </p>
      </section>
      <section className="flex min-w-0 flex-col items-center justify-center px-5 py-10 sm:px-10">
        <div className="mb-8 flex items-center gap-3 lg:hidden">
          <Landmark className="size-7 text-primary" />
          <span className="text-xl font-semibold tracking-tight">
            FlowCredit
          </span>
        </div>
        <Card className="w-full max-w-md gap-6 shadow-none">
          <CardHeader className="space-y-2">
            <CardTitle
              role="heading"
              aria-level={1}
              className="text-2xl tracking-tight"
            >
              {recovering
                ? recovered
                  ? 'Password reset'
                  : 'Recover your account'
                : tab === 'login'
                  ? mfaRequired
                    ? 'Verify your sign-in'
                    : 'Welcome back'
                  : joining
                    ? 'Join your team'
                    : 'Start your workspace'}
            </CardTitle>
            <CardDescription className="leading-relaxed">
              {recovering
                ? 'Use your saved account recovery code to reset your password.'
                : tab === 'login'
                  ? mfaRequired
                    ? 'Complete two-step verification to open your workspace.'
                    : 'Sign in to your bank or team workspace.'
                  : joining
                    ? 'Create your account using the invitation from your workspace admin.'
                    : 'Create an account and a private workspace for your credit team.'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {recovering ? (
              recovered ? (
                <div className="space-y-5">
                  <Alert>
                    <ShieldCheck />
                    <AlertDescription>
                      Your password was reset and all previous sessions ended.
                      Two-step verification is now off. After signing in,
                      generate a new account recovery code and reconnect your
                      authenticator.
                    </AlertDescription>
                  </Alert>
                  <Button
                    className="w-full"
                    onClick={() => {
                      setRecovering(false);
                      setRecovered(false);
                      setTab('login');
                      resetStep();
                    }}
                  >
                    Back to sign in
                  </Button>
                </div>
              ) : (
                <form
                  className="space-y-4"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void submit();
                  }}
                >
                  <div className="space-y-2">
                    <Label htmlFor="recover-email">Email</Label>
                    <Input
                      id="recover-email"
                      type="email"
                      autoComplete="username"
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                      maxLength={254}
                      required
                      disabled={pending}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="recover-key">Account recovery code</Label>
                    <Input
                      id="recover-key"
                      autoComplete="off"
                      value={recoveryKey}
                      onChange={(event) => setRecoveryKey(event.target.value)}
                      maxLength={100}
                      required
                      disabled={pending}
                    />
                    <p className="text-xs text-muted-foreground">
                      Use the code saved from Account security. Authenticator
                      backup codes cannot reset a password.
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="recover-password">New password</Label>
                    <Input
                      id="recover-password"
                      type="password"
                      autoComplete="new-password"
                      value={newPassword}
                      onChange={(event) => setNewPassword(event.target.value)}
                      minLength={12}
                      maxLength={128}
                      required
                      disabled={pending}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="recover-confirm">
                      Confirm new password
                    </Label>
                    <Input
                      id="recover-confirm"
                      type="password"
                      autoComplete="new-password"
                      value={confirmPassword}
                      onChange={(event) =>
                        setConfirmPassword(event.target.value)
                      }
                      minLength={12}
                      maxLength={128}
                      required
                      disabled={pending}
                    />
                  </div>
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    Recovery ends all signed-in sessions and turns off two-step
                    verification. Your saved recovery code can be used once.
                  </p>
                  {error && (
                    <Alert variant="destructive">
                      <AlertTitle>Account recovery failed</AlertTitle>
                      <AlertDescription>{error.message}</AlertDescription>
                    </Alert>
                  )}
                  <Button className="w-full" type="submit" disabled={pending}>
                    {pending && <Loader2 className="animate-spin" />}Reset
                    password
                  </Button>
                  <Button
                    className="w-full"
                    type="button"
                    variant="ghost"
                    disabled={pending}
                    onClick={() => {
                      setRecovering(false);
                      resetStep();
                    }}
                  >
                    Back to sign in
                  </Button>
                </form>
              )
            ) : (
              <Tabs
                value={tab}
                onValueChange={(value) => {
                  if (!pending) {
                    setTab(value);
                    setPassword('');
                    resetStep();
                  }
                }}
                className="gap-5"
              >
                <TabsList className="w-full">
                  <TabsTrigger value="login" disabled={pending}>
                    Sign in
                  </TabsTrigger>
                  <TabsTrigger value="register" disabled={pending}>
                    Create account
                  </TabsTrigger>
                </TabsList>
                {notice && (
                  <Alert>
                    <ShieldCheck />
                    <AlertDescription>
                      {notice}
                      {notice.startsWith('The backend') && (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => window.location.reload()}
                        >
                          Retry connection
                        </Button>
                      )}
                    </AlertDescription>
                  </Alert>
                )}
                <form
                  className="space-y-4"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void submit();
                  }}
                >
                  <TabsContent value="register" className="mt-0 space-y-4">
                    <div className="space-y-2">
                      <Label htmlFor="auth-name">Full name</Label>
                      <Input
                        id="auth-name"
                        value={displayName}
                        onChange={(event) => setDisplayName(event.target.value)}
                        autoComplete="name"
                        minLength={2}
                        maxLength={100}
                        required={tab === 'register'}
                        disabled={pending}
                        placeholder="Your full name"
                      />
                    </div>
                    {joining ? (
                      <div className="space-y-2">
                        <Label htmlFor="auth-invitation">
                          Invitation token
                        </Label>
                        <Input
                          id="auth-invitation"
                          value={invitationToken}
                          onChange={(event) =>
                            setInvitationToken(event.target.value)
                          }
                          autoComplete="off"
                          required={tab === 'register' && joining}
                          maxLength={200}
                          disabled={pending}
                          placeholder="Paste your invitation token"
                        />
                        <p className="text-xs text-muted-foreground">
                          Use the same email address your admin invited.
                        </p>
                      </div>
                    ) : (
                      <div className="space-y-2">
                        <Label htmlFor="auth-workspace">Workspace name</Label>
                        <Input
                          id="auth-workspace"
                          value={tenantName}
                          onChange={(event) =>
                            setTenantName(event.target.value)
                          }
                          required={tab === 'register' && !joining}
                          minLength={2}
                          maxLength={100}
                          disabled={pending}
                          placeholder="e.g. Tashkent Credit Team"
                        />
                      </div>
                    )}
                    <Button
                      variant="link"
                      size="sm"
                      type="button"
                      className="h-auto px-0 text-xs"
                      disabled={pending}
                      onClick={() => setJoining(!joining)}
                    >
                      {joining
                        ? 'Create a new workspace instead'
                        : 'Have a team invitation?'}
                    </Button>
                  </TabsContent>
                  <div className="space-y-2">
                    <Label htmlFor="auth-email">Email</Label>
                    <Input
                      id="auth-email"
                      type="email"
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                      autoComplete="username"
                      maxLength={254}
                      required
                      disabled={pending || mfaRequired}
                      placeholder="you@example.com"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="auth-password">Password</Label>
                    <Input
                      id="auth-password"
                      type="password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      autoComplete={
                        tab === 'login' ? 'current-password' : 'new-password'
                      }
                      minLength={tab === 'register' ? 12 : undefined}
                      maxLength={128}
                      required
                      disabled={pending || mfaRequired}
                    />
                    {tab === 'register' && (
                      <p className="text-xs text-muted-foreground">
                        Use at least 12 characters. Your password stays private.
                      </p>
                    )}
                  </div>
                  {mfaRequired && tab === 'login' && (
                    <div className="space-y-4">
                      <div className="space-y-2">
                        <Label htmlFor="auth-factor-method">
                          Verification method
                        </Label>
                        <Select
                          value={factorMethod}
                          onValueChange={(value) => {
                            setFactorMethod(value);
                            setFactor('');
                            setError(null);
                          }}
                          disabled={pending}
                        >
                          <SelectTrigger id="auth-factor-method">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="totp">
                              Authenticator app
                            </SelectItem>
                            <SelectItem value="backup">
                              Authenticator backup code
                            </SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="auth-factor">
                          {factorMethod === 'backup'
                            ? 'Authenticator backup code'
                            : 'Authenticator code'}
                        </Label>
                        <Input
                          id="auth-factor"
                          value={factor}
                          onChange={(event) => setFactor(event.target.value)}
                          autoComplete="one-time-code"
                          inputMode={
                            factorMethod === 'totp' ? 'numeric' : 'text'
                          }
                          pattern={
                            factorMethod === 'totp' ? '[0-9]{6}' : undefined
                          }
                          maxLength={factorMethod === 'totp' ? 6 : 100}
                          required
                          disabled={pending}
                          autoFocus
                        />
                        <p className="text-xs text-muted-foreground">
                          {factorMethod === 'backup'
                            ? 'Each backup code works once.'
                            : 'Enter the six-digit code from your authenticator app.'}
                        </p>
                      </div>
                      <Button
                        type="button"
                        variant="link"
                        className="h-auto px-0 text-xs"
                        disabled={pending}
                        onClick={resetStep}
                      >
                        Use another account
                      </Button>
                    </div>
                  )}
                  {Boolean(error) && (
                    <Alert variant="destructive" role="alert">
                      <AlertTitle>
                        {tab === 'login'
                          ? 'Sign-in failed'
                          : 'Account could not be created'}
                      </AlertTitle>
                      <AlertDescription>{error?.message}</AlertDescription>
                    </Alert>
                  )}
                  <Button className="w-full" type="submit" disabled={pending}>
                    {pending ? (
                      <Loader2 className="animate-spin" />
                    ) : (
                      <ArrowRight />
                    )}
                    {pending
                      ? 'Please wait…'
                      : tab === 'login'
                        ? mfaRequired
                          ? 'Verify and sign in'
                          : 'Sign in to workspace'
                        : joining
                          ? 'Create account and join team'
                          : 'Create account and workspace'}
                  </Button>
                </form>
                {tab === 'login' && (
                  <Button
                    type="button"
                    variant="link"
                    className="h-auto px-0 text-xs"
                    disabled={pending}
                    onClick={() => {
                      resetStep();
                      setRecovering(true);
                      setRecovered(false);
                    }}
                  >
                    Forgot password?
                  </Button>
                )}
              </Tabs>
            )}
          </CardContent>
        </Card>
        <p className="mt-6 max-w-md text-center text-xs leading-relaxed text-muted-foreground">
          Start with an empty portfolio, import transaction history in UZS, and
          invite your team. Every final review is made by a person.
        </p>
      </section>
    </main>
  );
}
