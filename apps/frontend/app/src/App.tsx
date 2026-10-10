import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import {
  useIsMutating,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { BusinessImportSchema, type AuthSession } from '@wiut/contracts';
import {
  Building2,
  ChevronRight,
  ClipboardCheck,
  FileClock,
  FlaskConical,
  HeartPulse,
  Import,
  Landmark,
  LayoutDashboard,
  LogOut,
  Plus,
  Users,
  Loader2,
  ShieldCheck,
  Upload,
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
import { Separator } from '@/components/ui/separator';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
  useSidebar,
} from '@/components/ui/sidebar';
import { Textarea } from '@/components/ui/textarea';
import { TooltipProvider } from '@/components/ui/tooltip';
import { Toaster } from '@/components/ui/sonner';
import {
  api,
  ApiError,
  resetApiSession,
  SESSION_EXPIRED_EVENT,
  SESSION_WORKSPACE_CHANGED_EVENT,
} from '@/lib/api';
import { readInvitationToken } from '@/lib/route';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

const OverviewPage = lazy(() =>
  import('@/pages/Overview').then((module) => ({
    default: module.OverviewPage,
  })),
);
const BusinessesPage = lazy(() =>
  import('@/pages/Businesses').then((module) => ({
    default: module.BusinessesPage,
  })),
);
const BusinessWorkspace = lazy(() =>
  import('@/pages/BusinessWorkspace').then((module) => ({
    default: module.BusinessWorkspace,
  })),
);
const ReviewsPage = lazy(() =>
  import('@/pages/Reviews').then((module) => ({ default: module.ReviewsPage })),
);
const AuditPage = lazy(() =>
  import('@/pages/Audit').then((module) => ({ default: module.AuditPage })),
);

const AuthPage = lazy(() =>
  import('@/pages/Auth').then((module) => ({ default: module.AuthPage })),
);

const TeamPage = lazy(() =>
  import('@/pages/Team').then((module) => ({ default: module.TeamPage })),
);
const InvitationPage = lazy(() =>
  import('@/pages/Team').then((module) => ({ default: module.InvitationPage })),
);

type Page = 'overview' | 'businesses' | 'reviews' | 'audit' | 'team' | 'invite';
type WorkspaceRoute = {
  page: Page;
  businessId: string | null;
  assessmentId: string | null;
};
function readRoute(): WorkspaceRoute {
  const hash = window.location.hash.slice(1);
  if (hash.startsWith('business/')) {
    const [id, query] = hash.slice(9).split('?');
    try {
      return {
        page: 'businesses',
        businessId: decodeURIComponent(id ?? ''),
        assessmentId: new URLSearchParams(query).get('assessment'),
      };
    } catch {
      return { page: 'businesses', businessId: null, assessmentId: null };
    }
  }
  if (hash.startsWith('invite'))
    return { page: 'invite', businessId: null, assessmentId: null };
  return {
    page: ['overview', 'businesses', 'reviews', 'audit', 'team'].includes(hash)
      ? (hash as Page)
      : 'overview',
    businessId: null,
    assessmentId: null,
  };
}
const navigation = [
  { id: 'overview' as const, label: 'Overview', icon: LayoutDashboard },
  { id: 'businesses' as const, label: 'Businesses', icon: Building2 },
  { id: 'reviews' as const, label: 'Review history', icon: ClipboardCheck },
  { id: 'audit' as const, label: 'Audit trail', icon: FileClock },
  { id: 'team' as const, label: 'Team & access', icon: Users },
];

const SESSION_BROADCAST_KEY = 'flowcredit-session-change';

export default function App() {
  const queryClient = useQueryClient();
  const [session, setSession] = useState<AuthSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<string | undefined>();
  const generation = useRef(0);

  async function replaceSession(
    next: AuthSession | null,
    options: {
      resetRoute?: boolean;
      broadcast?: boolean;
      notice?: string;
    } = {},
  ) {
    const current = ++generation.current;
    resetApiSession(null);
    setLoading(true);
    setSession(null);
    await queryClient.cancelQueries();
    if (current !== generation.current) return;
    queryClient.clear();
    resetApiSession(next?.csrf_token ?? null, next?.tenant.id ?? null);
    if (options.resetRoute) window.location.hash = 'overview';
    setSession(next);
    setNotice(options.notice);
    setLoading(false);
    if (options.broadcast !== false) {
      try {
        localStorage.setItem(
          SESSION_BROADCAST_KEY,
          `${Date.now()}-${Math.random()}`,
        );
      } catch {
        /* Browser storage is optional; cookie authentication remains available. */
      }
    }
  }

  useEffect(() => {
    let disposed = false;
    async function loadSession() {
      const current = ++generation.current;
      resetApiSession(null);
      setLoading(true);
      setSession(null);
      await queryClient.cancelQueries();
      if (disposed || current !== generation.current) return;
      queryClient.clear();
      try {
        const next = await api.session();
        if (disposed || current !== generation.current) return;
        resetApiSession(next.csrf_token, next.tenant.id);
        setSession(next);
        setNotice(undefined);
      } catch (error) {
        if (disposed || current !== generation.current) return;
        setNotice(
          error instanceof ApiError && error.status === 401
            ? undefined
            : 'The backend could not be reached. You can retry signing in when the connection returns.',
        );
      }
      setLoading(false);
    }
    const expired = () => {
      void replaceSession(null, {
        broadcast: false,
        notice: 'Your session ended. Sign in again to continue.',
      });
    };
    const workspaceChanged = () => {
      window.location.hash = 'overview';
      void loadSession();
    };
    const storageChanged = (event: StorageEvent) => {
      if (event.key === SESSION_BROADCAST_KEY) workspaceChanged();
    };
    void loadSession();
    window.addEventListener(SESSION_EXPIRED_EVENT, expired);
    window.addEventListener(SESSION_WORKSPACE_CHANGED_EVENT, workspaceChanged);
    window.addEventListener('storage', storageChanged);
    return () => {
      disposed = true;
      window.removeEventListener(SESSION_EXPIRED_EVENT, expired);
      window.removeEventListener(
        SESSION_WORKSPACE_CHANGED_EVENT,
        workspaceChanged,
      );
      window.removeEventListener('storage', storageChanged);
    };
  }, [queryClient]);

  return (
    <TooltipProvider>
      {loading ? (
        <main className="flex min-h-dvh items-center justify-center bg-background p-6">
          <div className="space-y-4 text-center">
            <Landmark className="mx-auto size-9 text-primary" />
            <p className="text-lg font-semibold">FlowCredit</p>
            <p
              role="status"
              className="flex items-center justify-center gap-2 text-sm text-muted-foreground"
            >
              <Loader2 className="size-4 animate-spin" />
              Opening your workspace…
            </p>
          </div>
        </main>
      ) : session ? (
        <SidebarProvider>
          <WorkspaceApp
            key={`${session.user.id}-${session.tenant.id}`}
            session={session}
            onSessionChange={(next, resetRoute = true) =>
              replaceSession(next, { resetRoute })
            }
            onSignedOut={() =>
              replaceSession(null, {
                resetRoute: true,
                notice: 'You have signed out.',
              })
            }
          />
        </SidebarProvider>
      ) : (
        <Suspense
          fallback={
            <main
              role="status"
              className="flex min-h-dvh items-center justify-center gap-2 text-sm text-muted-foreground"
            >
              <Loader2 className="size-4 animate-spin" />
              Opening sign-in…
            </main>
          }
        >
          <AuthPage
            notice={notice}
            onAuthenticated={(next, resetRoute) =>
              replaceSession(next, { resetRoute })
            }
          />
        </Suspense>
      )}
      <Toaster richColors theme="light" closeButton />
    </TooltipProvider>
  );
}

function WorkspaceApp({
  session,
  onSessionChange,
  onSignedOut,
}: {
  session: AuthSession;
  onSessionChange: (next: AuthSession, resetRoute?: boolean) => Promise<void>;
  onSignedOut: () => Promise<void>;
}) {
  const queryClient = useQueryClient();
  const { setOpenMobile } = useSidebar();
  const pendingMutations = useIsMutating();
  const [createWorkspaceOpen, setCreateWorkspaceOpen] = useState(false);
  const [workspaceName, setWorkspaceName] = useState('');
  const switchWorkspace = useMutation({
    mutationFn: (id: string) => api.switchTenant({ tenant_id: id }),
    onSuccess: (next) => onSessionChange(next),
    onError: (error) =>
      toast.error('Workspace could not be opened', {
        description: error.message,
      }),
  });
  const createWorkspace = useMutation({
    mutationFn: () => api.createTenant({ name: workspaceName }),
    onSuccess: (next) => onSessionChange(next),
    onError: (error) =>
      toast.error('Workspace could not be created', {
        description: error.message,
      }),
  });
  const signOut = useMutation({
    mutationFn: api.logout,
    onSuccess: onSignedOut,
    onError: (error) => {
      if (!(error instanceof ApiError && error.status === 401))
        toast.error('Sign-out failed', { description: error.message });
    },
  });
  const [route, setRoute] = useState<WorkspaceRoute>(readRoute);
  const { page, businessId, assessmentId: initialAssessmentId } = route;
  useEffect(() => {
    document.getElementById('main-content')?.focus({ preventScroll: true });
  }, [page, businessId]);
  useEffect(() => {
    const onHashChange = () => {
      setRoute(readRoute());
      setOpenMobile(false);
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, [setOpenMobile]);
  const [importOpen, setImportOpen] = useState(false);
  const [name, setName] = useState('');
  const [sector, setSector] = useState('');
  const [location, setLocation] = useState('');
  const [transactionJson, setTransactionJson] = useState('');
  const [importError, setImportError] = useState<string | null>(null);
  const health = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: 30_000,
  });
  const businesses = useQuery({
    queryKey: ['businesses'],
    queryFn: api.businesses,
  });
  const assessments = useQuery({
    queryKey: ['assessments'],
    queryFn: () => api.assessments(),
  });
  const audit = useQuery({ queryKey: ['audit'], queryFn: () => api.audit() });
  const importMutation = useMutation({
    mutationFn: api.importBusiness,
    onSuccess: (business) => {
      void queryClient.invalidateQueries();
      setImportOpen(false);
      setName('');
      setSector('');
      setLocation('');
      setTransactionJson('');
      setImportError(null);
      openBusiness(business.id);
      toast.success('Business imported', {
        description: 'Synthetic transactions are ready for review.',
      });
    },
    onError: (error) => setImportError(error.message),
  });

  function navigate(target: Page) {
    window.location.hash = target;
    setRoute({ page: target, businessId: null, assessmentId: null });
    setOpenMobile(false);
  }
  function openBusiness(id: string, assessmentId?: string) {
    window.location.hash = `business/${encodeURIComponent(id)}${assessmentId ? `?assessment=${encodeURIComponent(assessmentId)}` : ''}`;
    setRoute({
      page: 'businesses',
      businessId: id,
      assessmentId: assessmentId ?? null,
    });
    setOpenMobile(false);
    window.scrollTo({ top: 0, behavior: 'instant' });
  }
  const activeLabel =
    page === 'invite'
      ? 'Team invitation'
      : navigation.find((item) => item.id === page)!.label;

  return (
    <>
      <a
        href="#main-content"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById('main-content')?.focus();
        }}
        className="sr-only fixed top-2 left-2 z-50 rounded-md bg-card px-4 py-2 text-sm shadow focus:not-sr-only"
      >
        Skip to main content
      </a>
      <Sidebar variant="inset">
        <SidebarHeader className="p-5">
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                size="lg"
                onClick={() => navigate('overview')}
                className="gap-3 p-0 hover:bg-transparent"
              >
                <Landmark className="size-8! text-primary" aria-hidden="true" />
                <div className="grid text-left">
                  <span className="text-lg font-semibold tracking-tight">
                    FlowCredit
                  </span>
                  <span className="text-xs text-muted-foreground">
                    Credit review workspace
                  </span>
                </div>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
          <div className="mt-4 space-y-2">
            <Label
              htmlFor="workspace-switch"
              className="text-[10px] tracking-widest text-muted-foreground uppercase"
            >
              Active workspace
            </Label>
            <Select
              value={session.tenant.id}
              onValueChange={(id) => {
                if (id !== session.tenant.id) switchWorkspace.mutate(id);
              }}
              disabled={pendingMutations > 0}
            >
              <SelectTrigger
                id="workspace-switch"
                aria-label="Switch workspace"
                className="w-full min-w-0"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {session.tenants.map((tenant) => (
                  <SelectItem key={tenant.id} value={tenant.id}>
                    {tenant.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              variant="ghost"
              size="sm"
              className="w-full justify-start px-2 text-xs text-muted-foreground"
              disabled={pendingMutations > 0}
              onClick={() => {
                createWorkspace.reset();
                setWorkspaceName('');
                setCreateWorkspaceOpen(true);
              }}
            >
              <Plus className="size-3.5" />
              Create workspace
            </Button>
          </div>
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel className="px-3 text-[10px] tracking-widest uppercase">
              Workspace
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu className="gap-1">
                {navigation
                  .filter(
                    (item) =>
                      item.id !== 'team' || session.tenant.role === 'admin',
                  )
                  .map((item) => (
                    <SidebarMenuItem key={item.id}>
                      <SidebarMenuButton
                        aria-label={item.label}
                        onClick={() => navigate(item.id)}
                        isActive={page === item.id}
                        className="h-10 px-3 data-[active=true]:bg-emerald-50 data-[active=true]:text-emerald-800"
                      >
                        <item.icon />
                        <span>{item.label}</span>
                        {item.id === 'businesses' && businesses.data && (
                          <span className="ml-auto text-xs text-muted-foreground">
                            {businesses.data.items.length}
                          </span>
                        )}
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter className="gap-4 p-4">
          <div className="min-w-0 rounded-md border bg-muted/20 p-3">
            <p
              className="truncate text-sm font-medium"
              title={session.user.display_name}
            >
              {session.user.display_name}
            </p>
            <p
              className="mt-1 truncate text-[11px] text-muted-foreground"
              title={session.user.email}
            >
              {session.user.email}
            </p>
            <div className="mt-3 flex items-center justify-between gap-2">
              <Badge variant="secondary" className="text-[10px]">
                {session.tenant.role === 'admin' ? 'Admin' : 'Credit officer'}
              </Badge>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs"
                disabled={pendingMutations > 0}
                onClick={() => signOut.mutate()}
              >
                <LogOut className="size-3.5" />
                Sign out
              </Button>
            </div>
          </div>
          <Card className="gap-3 border-dashed bg-background shadow-none">
            <CardHeader className="px-4 py-0">
              <CardTitle className="flex items-center gap-2 text-sm">
                <FlaskConical className="size-4 text-primary" /> Synthetic
                sandbox
              </CardTitle>
              <CardDescription className="text-xs leading-relaxed">
                Explore business cash flow safely. All cases use synthetic
                transaction data.
              </CardDescription>
            </CardHeader>
            <CardContent className="px-4">
              <Badge variant="secondary" className="text-[10px]">
                WIUT Hackathon 2026
              </Badge>
            </CardContent>
          </Card>
          <div className="flex items-center gap-3 px-2">
            <ShieldCheck className="size-5 text-muted-foreground" />
            <div>
              <p className="text-xs font-medium">Human-led decisions</p>
              <p className="text-[11px] text-muted-foreground">
                Every review is recorded
              </p>
            </div>
          </div>
        </SidebarFooter>
      </Sidebar>
      <SidebarInset className="min-w-0 overflow-hidden border bg-background shadow-none md:mr-3 md:border">
        <header className="flex min-h-16 items-center justify-between gap-4 border-b bg-card px-4 sm:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <SidebarTrigger aria-label="Toggle sidebar" />
            <Separator orientation="vertical" className="h-4!" />
            <span className="hidden text-sm text-muted-foreground sm:inline">
              {session.tenant.name}
            </span>
            <ChevronRight className="hidden size-3 text-muted-foreground sm:block" />
            <span className="truncate text-sm font-medium">{activeLabel}</span>
            {businessId && (
              <ChevronRight className="size-3 text-muted-foreground" />
            )}
            {businessId && (
              <span className="hidden text-sm text-muted-foreground sm:inline">
                Business review
              </span>
            )}
          </div>
          <Badge variant="outline" className="shrink-0 gap-1.5 font-normal">
            <FlaskConical className="size-3" />
            <span className="hidden sm:inline">Synthetic data only</span>
            <span className="sm:hidden">Sandbox</span>
          </Badge>
        </header>
        <main
          id="main-content"
          tabIndex={-1}
          className="mx-auto w-full max-w-[1440px] flex-1 space-y-6 p-4 sm:p-6 lg:p-8"
        >
          {health.isError && (
            <Alert variant="destructive">
              <HeartPulse />
              <AlertTitle>Backend unavailable</AlertTitle>
              <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
                <span>{health.error.message}</span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    void health.refetch();
                    void businesses.refetch();
                    void assessments.refetch();
                    void audit.refetch();
                  }}
                >
                  Retry connection
                </Button>
              </AlertDescription>
            </Alert>
          )}
          <Suspense
            fallback={
              <div className="space-y-5">
                <Skeleton className="h-10 w-64" />
                <Skeleton className="h-32 w-full" />
                <Skeleton className="h-64 w-full" />
              </div>
            }
          >
            {page === 'team' &&
              (session.tenant.role === 'admin' ? (
                <TeamPage session={session} />
              ) : (
                <Alert>
                  <ShieldCheck />
                  <AlertTitle>Administrator access required</AlertTitle>
                  <AlertDescription>
                    Team settings are managed by your workspace admin. Your
                    credit-officer access includes the portfolio, assessments,
                    and human review decisions.
                  </AlertDescription>
                </Alert>
              ))}
            {page === 'invite' && (
              <InvitationPage
                token={readInvitationToken()}
                session={session}
                onAccepted={onSessionChange}
                onBack={() => navigate('overview')}
              />
            )}
            {page === 'overview' && (
              <OverviewPage
                businesses={businesses}
                assessments={assessments}
                mlConfigured={health.data?.ml_configured}
                onOpen={openBusiness}
                onViewBusinesses={() => navigate('businesses')}
                onImport={() => setImportOpen(true)}
              />
            )}
            {page === 'businesses' && !businessId && (
              <BusinessesPage
                businesses={businesses}
                onOpen={openBusiness}
                onImport={() => setImportOpen(true)}
              />
            )}
            {page === 'businesses' && businessId && (
              <BusinessWorkspace
                key={businessId}
                businessId={businessId}
                reviewerName={session.user.display_name}
                initialAssessmentId={initialAssessmentId}
                mlConfigured={health.data?.ml_configured}
                onBack={() => navigate('businesses')}
                onSelectAssessment={(id) =>
                  openBusiness(businessId, id ?? undefined)
                }
              />
            )}
            {page === 'reviews' && (
              <ReviewsPage
                assessments={assessments}
                businesses={businesses.data?.items ?? []}
                onOpen={openBusiness}
              />
            )}
            {page === 'audit' && (
              <AuditPage
                audit={audit}
                businesses={businesses.data?.items ?? []}
                onOpen={openBusiness}
              />
            )}
          </Suspense>
        </main>
        <footer className="flex flex-wrap items-center justify-between gap-2 border-t bg-card px-6 py-4 text-[11px] text-muted-foreground">
          <span>FlowCredit · Transparent capacity assessment</span>
          <span className="flex items-center gap-1.5">
            <span
              className={`size-1.5 rounded-full ${health.data && !health.isError ? 'bg-emerald-500' : 'bg-amber-500'}`}
            />
            {health.data && !health.isError
              ? 'API connected · Data persisted'
              : 'Waiting for API connection'}
          </span>
        </footer>
      </SidebarInset>
      <Dialog
        open={createWorkspaceOpen}
        onOpenChange={(open) => {
          if (!createWorkspace.isPending) setCreateWorkspaceOpen(open);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create a workspace</DialogTitle>
            <DialogDescription>
              Create a separate workspace for another bank or team. You will be
              its admin, with a fresh synthetic demo portfolio.
            </DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              createWorkspace.mutate();
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="new-workspace-name">Workspace name</Label>
              <Input
                id="new-workspace-name"
                value={workspaceName}
                onChange={(event) => setWorkspaceName(event.target.value)}
                minLength={2}
                maxLength={100}
                required
                disabled={createWorkspace.isPending}
                placeholder="e.g. Samarkand Review Team"
              />
            </div>
            {createWorkspace.isError && (
              <Alert variant="destructive">
                <AlertDescription>
                  {createWorkspace.error.message}
                </AlertDescription>
              </Alert>
            )}
            <DialogFooter>
              <Button
                variant="outline"
                type="button"
                disabled={createWorkspace.isPending}
                onClick={() => setCreateWorkspaceOpen(false)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={createWorkspace.isPending}>
                {createWorkspace.isPending ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <Plus />
                )}
                Create new workspace
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog
        open={importOpen}
        onOpenChange={(open) => {
          if (!importMutation.isPending) {
            setImportOpen(open);
            setImportError(null);
          }
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Import synthetic business</DialogTitle>
            <DialogDescription>
              Add a case using synthetic transaction history. Amount indices
              stay separate from currency.
            </DialogDescription>
          </DialogHeader>
          <form
            className="space-y-5"
            onSubmit={(event) => {
              event.preventDefault();
              setImportError(null);
              let transactions: unknown;
              try {
                transactions = JSON.parse(transactionJson);
              } catch {
                setImportError(
                  'Transaction JSON is invalid. Paste a JSON array of transactions.',
                );
                return;
              }
              const parsed = BusinessImportSchema.safeParse({
                name,
                sector,
                location,
                data_source: 'synthetic',
                transactions,
              });
              if (!parsed.success) {
                setImportError(
                  parsed.error.issues
                    .slice(0, 4)
                    .map((issue) => `${issue.path.join('.')}: ${issue.message}`)
                    .join(' · '),
                );
                return;
              }
              importMutation.mutate(parsed.data);
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="import-name">Business name</Label>
              <Input
                id="import-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="e.g. Synthetic Corner Bakery"
                maxLength={100}
                required
                disabled={importMutation.isPending}
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="import-sector">Sector</Label>
                <Input
                  id="import-sector"
                  value={sector}
                  onChange={(event) => setSector(event.target.value)}
                  placeholder="e.g. Food & beverage"
                  maxLength={100}
                  required
                  disabled={importMutation.isPending}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="import-location">Location</Label>
                <Input
                  id="import-location"
                  value={location}
                  onChange={(event) => setLocation(event.target.value)}
                  placeholder="e.g. Tashkent"
                  maxLength={100}
                  required
                  disabled={importMutation.isPending}
                />
              </div>
            </div>
            <div className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Label htmlFor="import-transactions">Transaction JSON</Label>
                <Label
                  htmlFor="transaction-file"
                  className="cursor-pointer gap-1.5 text-xs text-muted-foreground"
                >
                  <Upload className="size-3.5" /> Upload JSON file
                </Label>
                <Input
                  id="transaction-file"
                  type="file"
                  accept=".json,application/json"
                  className="sr-only"
                  disabled={importMutation.isPending}
                  onChange={async (event) => {
                    const file = event.target.files?.[0];
                    if (!file) return;
                    if (file.size > 3_000_000) {
                      setImportError(
                        'The JSON file must be smaller than 3 MB, matching the API request limit.',
                      );
                      return;
                    }
                    try {
                      const parsed: unknown = JSON.parse(await file.text());
                      if (
                        parsed &&
                        typeof parsed === 'object' &&
                        !Array.isArray(parsed) &&
                        'transactions' in parsed
                      ) {
                        const object = parsed as Record<string, unknown>;
                        setTransactionJson(
                          JSON.stringify(object.transactions, null, 2),
                        );
                        if (typeof object.name === 'string')
                          setName(object.name);
                        if (typeof object.sector === 'string')
                          setSector(object.sector);
                        if (typeof object.location === 'string')
                          setLocation(object.location);
                      } else
                        setTransactionJson(JSON.stringify(parsed, null, 2));
                      setImportError(null);
                    } catch {
                      setImportError('The uploaded file is not valid JSON.');
                    }
                    event.target.value = '';
                  }}
                />
              </div>
              <Textarea
                id="import-transactions"
                value={transactionJson}
                onChange={(event) => setTransactionJson(event.target.value)}
                className="min-h-44 font-mono text-xs"
                placeholder={
                  '[\n  { "ts": "2026-09-01T10:00:00Z", "direction": "in",\n    "channel": "card", "amount_index": 100 }\n]'
                }
                required
                disabled={importMutation.isPending}
              />
              <p className="text-xs text-muted-foreground">
                Required keys: ts, direction (in/out), channel
                (card/transfer/qr/cash_in/other), amount_index (positive
                number). Up to 20,000 records.
              </p>
            </div>
            {importError && (
              <Alert variant="destructive">
                <AlertTitle>Import could not be completed</AlertTitle>
                <AlertDescription>{importError}</AlertDescription>
              </Alert>
            )}
            <Alert>
              <FlaskConical />
              <AlertDescription>
                Submitting this form declares that the business and all
                transactions are synthetic. Do not upload real customer or bank
                data.
              </AlertDescription>
            </Alert>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={importMutation.isPending}
                onClick={() => setImportOpen(false)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={importMutation.isPending}>
                {importMutation.isPending ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <Import />
                )}
                Import business
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
