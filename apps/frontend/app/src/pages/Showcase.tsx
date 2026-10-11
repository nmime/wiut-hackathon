import { useState } from 'react';
import {
  useIsMutating,
  useMutation,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query';
import type {
  AuthSession,
  ShowcaseGenerate,
  ShowcaseGeneration,
} from '@wiut/contracts';
import {
  ArrowRight,
  Download,
  FlaskConical,
  Landmark,
  Loader2,
  Plus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
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
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty';
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { api } from '@/lib/api';
import {
  assessmentLabel,
  businessExport,
  compactNumber,
  downloadJson,
  downloadTransactions,
} from '@/lib/format';

const scenarios = [
  {
    value: 'mixed',
    label: 'Mixed scenario pack',
    description:
      'A varied set of steady, seasonal, growing, declining, volatile, and short histories. Six cases covers every pattern.',
  },
  {
    value: 'stable',
    label: 'Steady trading',
    description: 'Regular revenue and operating costs with modest variation.',
  },
  {
    value: 'seasonal',
    label: 'Seasonal peaks',
    description: 'Recurring busy and quiet months with seasonal cash flow.',
  },
  {
    value: 'growing',
    label: 'Growing revenue',
    description: 'A business whose monthly revenue grows over its history.',
  },
  {
    value: 'declining',
    label: 'Revenue decline',
    description: 'Falling revenue with costs that adjust more slowly.',
  },
  {
    value: 'volatile',
    label: 'Unpredictable trading',
    description: 'Irregular transaction volumes and uneven monthly cash flow.',
  },
  {
    value: 'short_history',
    label: 'Short history',
    description:
      'At most four complete months, to exercise limited-history handling and model validation.',
  },
] as const;

function previousCompleteMonth() {
  const date = new Date();
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() - 1, 1))
    .toISOString()
    .slice(0, 7);
}

export function ShowcasePage({
  session,
  businesses,
  onSessionChange,
  onOpen,
}: {
  session: AuthSession;
  businesses: UseQueryResult<Awaited<ReturnType<typeof api.businesses>>, Error>;
  onSessionChange: (next: AuthSession) => Promise<void>;
  onOpen: (id: string) => void;
}) {
  const queryClient = useQueryClient();
  const pendingMutations = useIsMutating();
  const isShowcase = session.tenant.kind === 'showcase';
  const labs = session.tenants.filter((tenant) => tenant.kind === 'showcase');
  const banks = session.tenants.filter((tenant) => tenant.kind === 'bank');
  const [name, setName] = useState(
    `${session.user.display_name}'s Showcase`.slice(0, 100),
  );
  const [createOpen, setCreateOpen] = useState(false);
  const [scenario, setScenario] =
    useState<NonNullable<ShowcaseGenerate['scenario']>>('mixed');
  const [months, setMonths] = useState('24');
  const [count, setCount] = useState('6');
  const [seed, setSeed] = useState('7261');
  const [revenue, setRevenue] = useState('30000000');
  const [endMonth, setEndMonth] = useState(previousCompleteMonth);
  const [lastBatch, setLastBatch] = useState<ShowcaseGeneration | null>(null);
  const [returnWorkspace, setReturnWorkspace] = useState(banks[0]?.id ?? '');
  const createLab = useMutation({
    mutationFn: () => api.createShowcaseTenant({ name }),
    onSuccess: onSessionChange,
    onError: (error) =>
      toast.error('Showcase workspace could not be created', {
        description: error.message,
      }),
  });
  const switchWorkspace = useMutation({
    mutationFn: (tenantId: string) => api.switchTenant({ tenant_id: tenantId }),
    onSuccess: onSessionChange,
    onError: (error) =>
      toast.error('Workspace could not be opened', {
        description: error.message,
      }),
  });
  const generate = useMutation({
    mutationFn: () =>
      api.generateShowcase({
        scenario,
        seed: Number(seed),
        months: Number(months),
        count: Number(count),
        monthly_revenue_uzs: Number(revenue),
        end_month: endMonth,
      }),
    onSuccess: (batch) => {
      setLastBatch(batch);
      void queryClient.invalidateQueries();
      toast.success(
        `${batch.items.length} showcase ${batch.items.length === 1 ? 'case' : 'cases'} generated`,
        { description: 'Open a case to run the connected scoring model.' },
      );
    },
  });
  const selectedScenario = scenarios.find((item) => item.value === scenario)!;
  const items = businesses.data?.items ?? [];
  const remaining = Math.max(0, 100 - items.length);

  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <p className="flex items-center gap-2 text-xs font-medium tracking-widest text-primary uppercase">
            <FlaskConical className="size-4" />
            Testing & demonstrations
          </p>
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            Showcase lab
          </h1>
          <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
            Generate business histories, run the scoring model, and practice
            human review in a dedicated workspace.
          </p>
        </div>
        {isShowcase && (
          <Button
            variant="outline"
            onClick={() => {
              createLab.reset();
              setCreateOpen(true);
            }}
            disabled={pendingMutations > 0}
          >
            <Plus />
            Create another lab
          </Button>
        )}
      </div>

      {!isShowcase ? (
        <div className="grid min-w-0 grid-cols-1 gap-6 lg:grid-cols-2">
          <Card className="min-w-0 shadow-none">
            <CardHeader>
              <CardTitle>Create your showcase workspace</CardTitle>
              <CardDescription>
                Your bank portfolio stays separate. You become the admin of the
                new lab, which starts empty.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form
                className="space-y-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  createLab.mutate();
                }}
              >
                <div className="space-y-2">
                  <Label htmlFor="showcase-name">Showcase workspace name</Label>
                  <Input
                    id="showcase-name"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    minLength={2}
                    maxLength={100}
                    required
                    disabled={pendingMutations > 0}
                  />
                </div>
                {createLab.isError && (
                  <Alert variant="destructive">
                    <AlertDescription>
                      {createLab.error.message}
                    </AlertDescription>
                  </Alert>
                )}
                <Button type="submit" disabled={pendingMutations > 0}>
                  {createLab.isPending ? (
                    <Loader2 className="animate-spin" />
                  ) : (
                    <FlaskConical />
                  )}
                  Create showcase workspace
                </Button>
              </form>
            </CardContent>
          </Card>
          <Card className="min-w-0 shadow-none">
            <CardHeader>
              <CardTitle>Separate space, complete workflow</CardTitle>
              <CardDescription>
                Rehearse the same steps your credit officers use.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <ol className="space-y-3 text-sm text-muted-foreground">
                <li>
                  1. Choose a scenario, history length, and reproducible seed.
                </li>
                <li>
                  2. Generate declared synthetic transaction amounts in UZS.
                </li>
                <li>
                  3. Run a real model assessment and record a practice decision.
                </li>
              </ol>
              <Alert>
                <ShieldCheck />
                <AlertTitle>Illustrative inputs, computed results</AlertTitle>
                <AlertDescription>
                  These cases are fictional. Their assessments exercise the
                  scoring flow and do not establish real borrower accuracy.
                  Exports retain synthetic provenance for testing.
                </AlertDescription>
              </Alert>
            </CardContent>
          </Card>
          {labs.length > 0 && (
            <Card className="min-w-0 shadow-none lg:col-span-2">
              <CardHeader>
                <CardTitle>Your showcase workspaces</CardTitle>
                <CardDescription>
                  Continue an existing demonstration.
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-3">
                {labs.map((lab) => (
                  <Button
                    key={lab.id}
                    variant="outline"
                    className="max-w-full min-w-0"
                    disabled={pendingMutations > 0}
                    onClick={() => switchWorkspace.mutate(lab.id)}
                  >
                    <FlaskConical />
                    <span className="min-w-0 max-w-64 truncate">
                      {lab.name}
                    </span>
                    <ArrowRight />
                  </Button>
                ))}
              </CardContent>
            </Card>
          )}
        </div>
      ) : (
        <>
          <div className="grid min-w-0 grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
            <Card
              className="min-w-0 shadow-none"
              data-testid="showcase-generator-card"
            >
              <CardHeader>
                <CardTitle>Generate a scenario pack</CardTitle>
                <CardDescription>
                  Same seed and settings reproduce the input transactions. Each
                  generation creates separate cases with a fresh audit trail.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <form
                  className="min-w-0 space-y-5"
                  onSubmit={(event) => {
                    event.preventDefault();
                    generate.mutate();
                  }}
                >
                  <div className="space-y-2">
                    <Label htmlFor="showcase-scenario">
                      Cash flow scenario
                    </Label>
                    <Select
                      value={scenario}
                      onValueChange={(value) =>
                        setScenario(value as typeof scenario)
                      }
                      disabled={generate.isPending}
                    >
                      <SelectTrigger
                        id="showcase-scenario"
                        className="w-full min-w-0"
                      >
                        <SelectValue className="min-w-0 flex-1 truncate text-left" />
                      </SelectTrigger>
                      <SelectContent>
                        {scenarios.map((item) => (
                          <SelectItem key={item.value} value={item.value}>
                            {item.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <p className="text-xs leading-relaxed text-muted-foreground">
                      {selectedScenario.description}
                    </p>
                  </div>
                  <div className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2">
                    <div className="min-w-0 space-y-2">
                      <Label htmlFor="showcase-count">Number of cases</Label>
                      <Input
                        id="showcase-count"
                        type="number"
                        min={1}
                        max={6}
                        step={1}
                        required
                        value={count}
                        onChange={(event) => setCount(event.target.value)}
                        disabled={generate.isPending}
                      />
                    </div>
                    <div className="min-w-0 space-y-2">
                      <Label htmlFor="showcase-months">
                        History length (months)
                      </Label>
                      <Input
                        id="showcase-months"
                        type="number"
                        min={3}
                        max={36}
                        step={1}
                        required
                        value={months}
                        onChange={(event) => setMonths(event.target.value)}
                        disabled={generate.isPending}
                      />
                    </div>
                    <div className="min-w-0 space-y-2">
                      <Label htmlFor="showcase-end-month">
                        Last complete month
                      </Label>
                      <Input
                        id="showcase-end-month"
                        type="month"
                        max={previousCompleteMonth()}
                        required
                        value={endMonth}
                        onChange={(event) => setEndMonth(event.target.value)}
                        disabled={generate.isPending}
                      />
                    </div>
                    <div className="min-w-0 space-y-2">
                      <Label htmlFor="showcase-revenue">
                        Base monthly revenue (UZS)
                      </Label>
                      <Input
                        id="showcase-revenue"
                        type="number"
                        min={1_000_000}
                        max={1_000_000_000}
                        step="any"
                        required
                        value={revenue}
                        onChange={(event) => setRevenue(event.target.value)}
                        disabled={generate.isPending}
                      />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="showcase-seed">Reproducible seed</Label>
                    <div className="flex min-w-0 gap-2">
                      <Input
                        id="showcase-seed"
                        type="number"
                        min={0}
                        max={4_294_967_295}
                        step={1}
                        required
                        value={seed}
                        onChange={(event) => setSeed(event.target.value)}
                        disabled={generate.isPending}
                      />
                      <Button
                        type="button"
                        variant="outline"
                        aria-label="Choose a random seed"
                        disabled={generate.isPending}
                        onClick={() =>
                          setSeed(
                            String(
                              crypto.getRandomValues(new Uint32Array(1))[0],
                            ),
                          )
                        }
                      >
                        <RefreshCw />
                      </Button>
                    </div>
                  </div>
                  {(scenario === 'short_history' ||
                    scenario === 'mixed' ||
                    Number(months) < 12) && (
                    <Alert>
                      <FlaskConical />
                      <AlertTitle>
                        Limited-history cases are intentional
                      </AlertTitle>
                      <AlertDescription>
                        Short histories may trigger warnings or be rejected by a
                        scoring model. The short-history scenario uses at most
                        four months. No successful result is forced.
                      </AlertDescription>
                    </Alert>
                  )}
                  {generate.isError && (
                    <Alert variant="destructive" role="alert">
                      <AlertTitle>Generation could not complete</AlertTitle>
                      <AlertDescription>
                        {generate.error.message}
                      </AlertDescription>
                    </Alert>
                  )}
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-xs text-muted-foreground">
                      {remaining} of 100 active case slots available
                    </p>
                    <Button
                      type="submit"
                      disabled={
                        pendingMutations > 0 ||
                        businesses.isPending ||
                        businesses.isError ||
                        remaining < Number(count)
                      }
                    >
                      {generate.isPending ? (
                        <Loader2 className="animate-spin" />
                      ) : (
                        <Sparkles />
                      )}
                      {generate.isPending
                        ? 'Generating cases…'
                        : 'Generate showcase cases'}
                    </Button>
                  </div>
                </form>
              </CardContent>
            </Card>
            <div className="min-w-0 space-y-6">
              <Card className="min-w-0 shadow-none">
                <CardHeader>
                  <CardTitle>Designed for a useful demonstration</CardTitle>
                  <CardDescription>
                    Scenario inputs are under your control.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4 text-sm text-muted-foreground">
                  <p>
                    Start with a mixed pack and 24 months. Compare a steady case
                    with a declining or seasonal business using their cash flow
                    charts and the connected model's forecasts.
                  </p>
                  <p>
                    UZS values are generated directly at the chosen revenue
                    scale. They do not represent observed customers or a
                    currency conversion from indexed data.
                  </p>
                  <p>
                    Assessments and practice decisions are persisted and
                    audited. Generated cases do not train or change the deployed
                    ML model.
                  </p>
                </CardContent>
              </Card>
              {banks.length > 0 && (
                <Card
                  className="min-w-0 shadow-none"
                  data-testid="showcase-return-card"
                >
                  <CardHeader>
                    <CardTitle>Back to your bank workspace</CardTitle>
                    <CardDescription>
                      Continue working with actual business histories.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <Label htmlFor="showcase-return">Bank workspace</Label>
                    <Select
                      value={returnWorkspace}
                      onValueChange={setReturnWorkspace}
                      disabled={pendingMutations > 0}
                    >
                      <SelectTrigger
                        id="showcase-return"
                        className="w-full min-w-0"
                      >
                        <SelectValue className="min-w-0 flex-1 truncate text-left" />
                      </SelectTrigger>
                      <SelectContent>
                        {banks.map((bank) => (
                          <SelectItem key={bank.id} value={bank.id}>
                            {bank.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button
                      variant="outline"
                      className="w-full"
                      disabled={pendingMutations > 0 || !returnWorkspace}
                      onClick={() => switchWorkspace.mutate(returnWorkspace)}
                    >
                      <Landmark />
                      Open bank workspace
                    </Button>
                  </CardContent>
                </Card>
              )}
            </div>
          </div>
          <Card className="min-w-0 gap-0 shadow-none">
            <CardHeader className="border-b pb-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="space-y-2">
                  <CardTitle>Showcase cases</CardTitle>
                  <CardDescription>
                    Open a case to inspect inputs, run an assessment, and record
                    a practice decision.
                  </CardDescription>
                </div>
                {lastBatch && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      downloadJson(
                        `showcase-synthetic-batch-${lastBatch.provenance.seed}.json`,
                        {
                          workspace_kind: 'showcase',
                          data_source: 'synthetic',
                          amount_unit: 'UZS',
                          provenance: lastBatch.provenance,
                          businesses: lastBatch.items.map(businessExport),
                        },
                      )
                    }
                  >
                    <Download />
                    Export last batch JSON
                  </Button>
                )}
              </div>
              {lastBatch && (
                <p role="status" className="text-xs text-muted-foreground">
                  Generated {lastBatch.items.length} cases · Seed{' '}
                  {lastBatch.provenance.seed} · Through{' '}
                  {lastBatch.provenance.end_month} · Synthetic UZS inputs
                </p>
              )}
            </CardHeader>
            <CardContent className="px-0">
              {businesses.isPending ? (
                <div className="space-y-4 p-6">
                  <Skeleton className="h-12 w-full" />
                  <Skeleton className="h-12 w-full" />
                </div>
              ) : businesses.isError ? (
                <Alert variant="destructive" className="m-4 w-auto">
                  <AlertTitle>Cases could not be loaded</AlertTitle>
                  <AlertDescription className="space-y-3">
                    <p>{businesses.error.message}</p>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void businesses.refetch()}
                    >
                      Retry
                    </Button>
                  </AlertDescription>
                </Alert>
              ) : items.length === 0 ? (
                <Empty className="py-10">
                  <EmptyHeader>
                    <EmptyMedia variant="icon">
                      <FlaskConical />
                    </EmptyMedia>
                    <EmptyTitle>No showcase cases yet</EmptyTitle>
                    <EmptyDescription>
                      Choose your settings above and generate the first pack.
                    </EmptyDescription>
                  </EmptyHeader>
                </Empty>
              ) : (
                <div className="overflow-x-auto">
                  <Table aria-label="Showcase cases" tabIndex={0}>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="pl-6">Business</TableHead>
                        <TableHead>History</TableHead>
                        <TableHead>Transactions</TableHead>
                        <TableHead>Review</TableHead>
                        <TableHead className="pr-6 text-right">
                          Actions
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {items.map((business) => {
                        const generated = lastBatch?.items.find(
                          (item) => item.id === business.id,
                        );
                        return (
                          <TableRow key={business.id}>
                            <TableCell className="pl-6">
                              <Button
                                variant="link"
                                className="h-auto max-w-64 justify-start p-0 text-left whitespace-normal"
                                onClick={() => onOpen(business.id)}
                              >
                                {business.name}
                              </Button>
                              <p className="mt-1 text-xs text-muted-foreground">
                                {business.showcase_provenance?.scenario.replaceAll(
                                  '_',
                                  ' ',
                                )}
                              </p>
                            </TableCell>
                            <TableCell>
                              {business.history_months} months
                            </TableCell>
                            <TableCell>
                              {compactNumber(business.transaction_count)}
                            </TableCell>
                            <TableCell>
                              <Badge
                                variant="secondary"
                                className="font-normal"
                              >
                                {assessmentLabel(business.latest_assessment)}
                              </Badge>
                            </TableCell>
                            <TableCell className="pr-6 text-right">
                              <div className="flex justify-end gap-2">
                                {generated && (
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    aria-label={`Export synthetic CSV for ${business.name}`}
                                    onClick={() =>
                                      downloadTransactions(generated)
                                    }
                                  >
                                    <Download />
                                    CSV
                                  </Button>
                                )}
                                <Button
                                  variant="outline"
                                  size="sm"
                                  aria-label={`Open showcase case ${business.name}`}
                                  onClick={() => onOpen(business.id)}
                                >
                                  Open case
                                  <ArrowRight />
                                </Button>
                              </div>
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create another showcase lab</DialogTitle>
            <DialogDescription>
              A separate empty workspace for generated cases and practice
              reviews.
            </DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              createLab.mutate();
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="another-showcase-name">
                Showcase workspace name
              </Label>
              <Input
                id="another-showcase-name"
                minLength={2}
                maxLength={100}
                required
                value={name}
                onChange={(event) => setName(event.target.value)}
                disabled={createLab.isPending}
              />
            </div>
            {createLab.isError && (
              <Alert variant="destructive">
                <AlertDescription>{createLab.error.message}</AlertDescription>
              </Alert>
            )}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={createLab.isPending}
                onClick={() => setCreateOpen(false)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={createLab.isPending}>
                {createLab.isPending ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <Plus />
                )}
                Create showcase workspace
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
