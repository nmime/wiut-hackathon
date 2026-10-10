import { useEffect, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { type AuthSession } from '@wiut/contracts';
import {
  ArrowRight,
  Building2,
  FileCheck2,
  FlaskConical,
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
import { api } from '@/lib/api';
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
  useEffect(() => {
    const onHashChange = () => {
      const token = readInvitationToken();
      if (token) {
        setInvitationToken(token);
        setJoining(true);
        setTab('register');
      }
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);
  const mutation = useMutation({
    mutationFn: () =>
      tab === 'login'
        ? api.login({ email, password })
        : api.register({
            email,
            password,
            display_name: displayName,
            ...(joining
              ? { invitation_token: invitationToken }
              : { tenant_name: tenantName }),
          }),
    onSuccess: (session) => onAuthenticated(session, tab === 'register'),
  });

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
            WIUT Hackathon 2026
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
          <FlaskConical className="size-4" /> Borrower cases and transactions
          are synthetic.
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
              {tab === 'login'
                ? 'Welcome back'
                : joining
                  ? 'Join your team'
                  : 'Start your workspace'}
            </CardTitle>
            <CardDescription className="leading-relaxed">
              {tab === 'login'
                ? 'Sign in to your bank or team workspace.'
                : joining
                  ? 'Create your account using the invitation from your workspace admin.'
                  : 'Create an account and a private workspace for your credit team.'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Tabs
              value={tab}
              onValueChange={(value) => {
                if (!mutation.isPending) {
                  setTab(value);
                  setPassword('');
                  mutation.reset();
                }
              }}
              className="gap-5"
            >
              <TabsList className="w-full">
                <TabsTrigger value="login" disabled={mutation.isPending}>
                  Sign in
                </TabsTrigger>
                <TabsTrigger value="register" disabled={mutation.isPending}>
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
                  mutation.mutate();
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
                      disabled={mutation.isPending}
                      placeholder="Your full name"
                    />
                  </div>
                  {joining ? (
                    <div className="space-y-2">
                      <Label htmlFor="auth-invitation">Invitation token</Label>
                      <Input
                        id="auth-invitation"
                        value={invitationToken}
                        onChange={(event) =>
                          setInvitationToken(event.target.value)
                        }
                        autoComplete="off"
                        required={tab === 'register' && joining}
                        maxLength={200}
                        disabled={mutation.isPending}
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
                        onChange={(event) => setTenantName(event.target.value)}
                        required={tab === 'register' && !joining}
                        minLength={2}
                        maxLength={100}
                        disabled={mutation.isPending}
                        placeholder="e.g. Tashkent Credit Team"
                      />
                    </div>
                  )}
                  <Button
                    variant="link"
                    size="sm"
                    type="button"
                    className="h-auto px-0 text-xs"
                    disabled={mutation.isPending}
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
                    disabled={mutation.isPending}
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
                    disabled={mutation.isPending}
                  />
                  {tab === 'register' && (
                    <p className="text-xs text-muted-foreground">
                      Use at least 12 characters. Your password stays private.
                    </p>
                  )}
                </div>
                {mutation.isError && (
                  <Alert variant="destructive" role="alert">
                    <AlertTitle>
                      {tab === 'login'
                        ? 'Sign-in failed'
                        : 'Account could not be created'}
                    </AlertTitle>
                    <AlertDescription>
                      {mutation.error.message}
                    </AlertDescription>
                  </Alert>
                )}
                <Button
                  className="w-full"
                  type="submit"
                  disabled={mutation.isPending}
                >
                  {mutation.isPending ? (
                    <Loader2 className="animate-spin" />
                  ) : (
                    <ArrowRight />
                  )}
                  {mutation.isPending
                    ? 'Please wait…'
                    : tab === 'login'
                      ? 'Sign in to workspace'
                      : joining
                        ? 'Create account and join team'
                        : 'Create account and workspace'}
                </Button>
              </form>
            </Tabs>
          </CardContent>
        </Card>
        <p className="mt-6 max-w-md text-center text-xs leading-relaxed text-muted-foreground">
          This hackathon workspace uses synthetic borrower data. Amount indices
          are separate from currency. Every final review is made by a person.
        </p>
      </section>
    </main>
  );
}
