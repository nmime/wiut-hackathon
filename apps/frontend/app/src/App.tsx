import { lazy, Suspense, useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BusinessImportSchema } from '@wiut/contracts';
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
import { api } from '@/lib/api';

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

type Page = 'overview' | 'businesses' | 'reviews' | 'audit';
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
  return {
    page: ['overview', 'businesses', 'reviews', 'audit'].includes(hash)
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
];

export default function App() {
  return (
    <TooltipProvider>
      <SidebarProvider>
        <WorkspaceApp />
      </SidebarProvider>
      <Toaster richColors theme="light" closeButton />
    </TooltipProvider>
  );
}

function WorkspaceApp() {
  const queryClient = useQueryClient();
  const { setOpenMobile } = useSidebar();
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
  const activeLabel = navigation.find((item) => item.id === page)!.label;

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
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel className="px-3 text-[10px] tracking-widest uppercase">
              Workspace
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu className="gap-1">
                {navigation.map((item) => (
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
              Workspace
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
