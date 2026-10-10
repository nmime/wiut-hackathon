import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  CreateAssessmentSchema,
  DecisionInputSchema,
  type DecisionInput,
  type AuditEvent,
  type Assessment,
} from '@wiut/contracts';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ReferenceLine,
  XAxis,
  YAxis,
} from 'recharts';
import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  Download,
  FileClock,
  FlaskConical,
  Info,
  Loader2,
  Play,
  Search,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
  TriangleAlert,
} from 'lucide-react';
import { toast } from 'sonner';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart';
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
import { Progress } from '@/components/ui/progress';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { api, ApiError } from '@/lib/api';
import {
  assessmentLabel,
  compactNumber,
  dateLabel,
  downloadJson,
  downloadTransactions,
  eventLabel,
  indexNumber,
  monthLabel,
  timeLabel,
} from '@/lib/format';

export function BusinessWorkspace({
  businessId,
  initialAssessmentId,
  mlConfigured,
  onBack,
  onSelectAssessment,
}: {
  businessId: string;
  initialAssessmentId: string | null;
  mlConfigured: boolean | undefined;
  onBack: () => void;
  onSelectAssessment: (id: string | null) => void;
}) {
  const queryClient = useQueryClient();
  const businessQuery = useQuery({
    queryKey: ['business', businessId],
    queryFn: () => api.business(businessId),
  });
  const assessmentQuery = useQuery({
    queryKey: ['assessments', businessId],
    queryFn: () => api.assessments(businessId),
  });
  const auditQuery = useQuery({
    queryKey: ['audit', businessId],
    queryFn: () => api.audit(businessId),
  });
  const business = businessQuery.data;
  const [tab, setTab] = useState('cashflow');
  const [requestedAmount, setRequestedAmount] = useState('');
  const [assessmentDate, setAssessmentDate] = useState('');
  const [assessmentError, setAssessmentError] = useState<string | null>(null);
  const [assessmentRequestId, setAssessmentRequestId] = useState<
    string | undefined
  >(undefined);
  const [selectedAssessmentId, setSelectedAssessmentId] = useState<
    string | null
  >(initialAssessmentId);
  const [transactionSearch, setTransactionSearch] = useState('');
  const [direction, setDirection] = useState('all');
  const [channel, setChannel] = useState('all');
  const [transactionPage, setTransactionPage] = useState(0);
  const [decision, setDecision] =
    useState<DecisionInput['decision']>('needs_information');
  const [reviewer, setReviewer] = useState('');
  const [notes, setNotes] = useState('');
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [pendingDecision, setPendingDecision] = useState<{
    assessmentId: string;
    data: DecisionInput;
  } | null>(null);
  const [auditDetails, setAuditDetails] = useState<AuditEvent | null>(null);
  const selectedAssessmentQuery = useQuery({
    queryKey: ['assessment', businessId, selectedAssessmentId],
    enabled: !!selectedAssessmentId,
    queryFn: async () => {
      const value = await api.assessment(selectedAssessmentId!);
      if (value.business_id !== businessId)
        throw new Error(
          'The selected assessment belongs to a different business.',
        );
      return value;
    },
  });
  const assessments = assessmentQuery.data?.items ?? [];
  const assessment = selectedAssessmentId
    ? (assessments.find((item) => item.id === selectedAssessmentId) ??
      selectedAssessmentQuery.data ??
      null)
    : (assessments[0] ?? business?.latest_assessment ?? null);
  const result = assessmentError ? null : assessment?.result;
  const filteredTransactions = (business?.transactions ?? []).filter(
    (transaction) =>
      (direction === 'all' || transaction.direction === direction) &&
      (channel === 'all' || transaction.channel === channel) &&
      `${transaction.ts} ${transaction.channel} ${transaction.amount_index}`
        .toLowerCase()
        .includes(transactionSearch.toLowerCase()),
  );
  const totalPages = Math.max(1, Math.ceil(filteredTransactions.length / 20));
  const currentPage = Math.min(transactionPage, totalPages - 1);
  const pagedTransactions = filteredTransactions.slice(
    currentPage * 20,
    (currentPage + 1) * 20,
  );
  const cashflow = (business?.monthly_cashflow ?? []).map((month) => ({
    ...month,
    label: monthLabel(month.month),
  }));
  const forecast =
    result?.seasonality.monthly_forecast_index.map((value, index) => ({
      month: `M${index + 1}`,
      surplus: value,
    })) ?? [];
  const equalPayment = result?.adaptive_schedule.length
    ? result.adaptive_schedule.reduce(
        (sum, row) => sum + row.installment_index,
        0,
      ) / result.adaptive_schedule.length
    : 0;
  const schedule =
    result?.adaptive_schedule.map((row) => ({
      ...row,
      month: `M${row.month_offset}`,
      equal_payment: equalPayment,
    })) ?? [];

  useEffect(() => {
    setSelectedAssessmentId(initialAssessmentId);
    if (initialAssessmentId) setAssessmentError(null);
  }, [initialAssessmentId]);
  useEffect(() => {
    if (business?.last_activity_date)
      setAssessmentDate(business.last_activity_date);
  }, [business?.last_activity_date]);
  useEffect(() => {
    setDecisionError(null);
    setNotes('');
    setPendingDecision(null);
  }, [assessment?.id]);

  function selectAssessment(id: string | null) {
    setSelectedAssessmentId(id);
    setAssessmentError(null);
    setAssessmentRequestId(undefined);
    onSelectAssessment(id);
  }
  function cacheAssessment(value: Assessment) {
    queryClient.setQueryData(['assessment', businessId, value.id], value);
    queryClient.setQueryData<Awaited<ReturnType<typeof api.assessments>>>(
      ['assessments', businessId],
      (previous) => ({
        items: [
          value,
          ...(previous?.items ?? []).filter((item) => item.id !== value.id),
        ],
      }),
    );
  }

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['businesses'] }),
      queryClient.invalidateQueries({ queryKey: ['business', businessId] }),
      queryClient.invalidateQueries({ queryKey: ['assessments'] }),
      queryClient.invalidateQueries({ queryKey: ['audit'] }),
      queryClient.invalidateQueries({ queryKey: ['health'] }),
    ]);
  }
  const assessMutation = useMutation({
    mutationFn: api.assess,
    onSuccess: async (value) => {
      cacheAssessment(value);
      selectAssessment(value.id);
      await refresh();
      toast.success('Assessment completed', {
        description:
          'Review the recommendation before recording your decision.',
      });
    },
    onError: async (error) => {
      setAssessmentError(error.message);
      setAssessmentRequestId(
        error instanceof ApiError ? error.requestId : undefined,
      );
      setSelectedAssessmentId(null);
      onSelectAssessment(null);
      await refresh();
      toast.error('Assessment could not be completed', {
        description:
          error instanceof ApiError && error.status === 0
            ? 'Retry once the API is available.'
            : 'Check the audit trail for the recorded request outcome.',
      });
    },
  });
  const decisionMutation = useMutation({
    mutationFn: (input: { assessmentId: string; data: DecisionInput }) =>
      api.decide(input.assessmentId, input.data),
    onSuccess: async (value) => {
      cacheAssessment(value);
      selectAssessment(value.id);
      setPendingDecision(null);
      setDecisionError(null);
      await refresh();
      toast.success('Decision recorded', {
        description:
          'Your name, reason, and decision are now part of the audit trail.',
      });
    },
    onError: async (error) => {
      setPendingDecision(null);
      setDecisionError(error.message);
      await refresh();
    },
  });

  if (businessQuery.isPending)
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-16 w-72" />
        <div className="grid gap-4 md:grid-cols-3">
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
        </div>
        <Skeleton className="h-80 w-full" />
      </div>
    );
  if (businessQuery.isError || !business)
    return (
      <>
        <Button variant="ghost" className="-ml-3" onClick={onBack}>
          <ArrowLeft />
          Back to businesses
        </Button>
        <Alert variant="destructive">
          <AlertTitle>Business unavailable</AlertTitle>
          <AlertDescription>
            {businessQuery.error?.message ??
              'This business could not be found.'}
            <Button
              variant="outline"
              size="sm"
              onClick={() => void businessQuery.refetch()}
            >
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      </>
    );

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        className="-ml-3 text-muted-foreground"
        onClick={onBack}
      >
        <ArrowLeft />
        Back to businesses
      </Button>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
              {business.name}
            </h1>
            <Badge variant="outline" className="gap-1.5 font-normal">
              <FlaskConical className="size-3" />
              Synthetic
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground">
            {business.sector} · {business.location}
            <span className="mx-2 text-border">/</span>
            {business.archetype}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              downloadJson(`${business.id}-synthetic-business.json`, {
                name: business.name,
                sector: business.sector,
                location: business.location,
                data_source: 'synthetic',
                transactions: business.transactions,
              })
            }
          >
            <Download />
            Download sample JSON
          </Button>
          <Badge variant="secondary" className="h-8 font-normal">
            {assessmentLabel(business.latest_assessment)}
          </Badge>
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card className="gap-3 shadow-none">
          <CardHeader>
            <CardDescription>Monthly inflow average</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-semibold tabular-nums">
              {indexNumber(business.avg_monthly_inflow_index)}
              <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                index
              </span>
            </p>
            <p className="mt-2 text-xs text-muted-foreground">
              Observed transaction history
            </p>
          </CardContent>
        </Card>
        <Card className="gap-3 shadow-none">
          <CardHeader>
            <CardDescription>Monthly net surplus</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-semibold tabular-nums">
              {indexNumber(business.avg_monthly_surplus_index)}
              <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                index
              </span>
            </p>
            <p className="mt-2 text-xs text-muted-foreground">
              Average inflow minus outflow
            </p>
          </CardContent>
        </Card>
        <Card className="gap-3 shadow-none">
          <CardHeader>
            <CardDescription>Available history</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-semibold tabular-nums">
              {business.history_months}
              <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                months
              </span>
            </p>
            <p className="mt-2 text-xs text-muted-foreground">
              {compactNumber(business.transaction_count)} transactions
            </p>
          </CardContent>
        </Card>
        <Card className="gap-3 shadow-none">
          <CardHeader>
            <CardDescription>Observed inflow trend</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="flex items-center gap-2 text-2xl font-semibold capitalize">
              {business.trend === 'growing' ? (
                <TrendingUp className="size-5 text-primary" />
              ) : business.trend === 'declining' ? (
                <TrendingDown className="size-5 text-amber-600" />
              ) : (
                <ArrowRight className="size-5 text-muted-foreground" />
              )}
              {business.trend}
            </p>
            <p className="mt-2 text-xs text-muted-foreground">
              Latest activity: {dateLabel(business.last_activity_date)}
            </p>
          </CardContent>
        </Card>
      </div>
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Tabs value={tab} onValueChange={setTab} className="min-w-0 gap-5">
          <TabsList className="flex h-auto w-full flex-wrap justify-start sm:w-fit">
            <TabsTrigger value="cashflow">Cash flow</TabsTrigger>
            <TabsTrigger value="transactions">Transactions</TabsTrigger>
            <TabsTrigger value="assessments">
              Assessments
              {assessments.length > 0 && (
                <Badge
                  variant="secondary"
                  className="ml-1 px-1.5 py-0 text-[10px]"
                >
                  {assessments.length}
                </Badge>
              )}
            </TabsTrigger>
            <TabsTrigger value="audit">Audit</TabsTrigger>
          </TabsList>
          <TabsContent value="cashflow" className="space-y-5">
            <Card className="min-w-0 shadow-none">
              <CardHeader>
                <CardTitle className="text-base">Observed cash flow</CardTitle>
                <CardDescription>
                  Monthly inflows and outflows from {business.history_months}{' '}
                  months of synthetic history.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ChartContainer
                  config={{
                    inflow_index: { label: 'Inflow', color: 'var(--chart-1)' },
                    outflow_index: {
                      label: 'Outflow',
                      color: 'var(--chart-2)',
                    },
                  }}
                  className="h-64 w-full"
                >
                  <AreaChart
                    data={cashflow}
                    accessibilityLayer
                    margin={{ left: 0, right: 12, top: 10 }}
                  >
                    <defs>
                      <linearGradient
                        id="inflow-fill"
                        x1="0"
                        y1="0"
                        x2="0"
                        y2="1"
                      >
                        <stop
                          offset="0%"
                          stopColor="var(--color-inflow_index)"
                          stopOpacity={0.2}
                        />
                        <stop
                          offset="100%"
                          stopColor="var(--color-inflow_index)"
                          stopOpacity={0.01}
                        />
                      </linearGradient>
                    </defs>
                    <CartesianGrid vertical={false} strokeDasharray="3 3" />
                    <XAxis
                      dataKey="label"
                      tickLine={false}
                      axisLine={false}
                      tickMargin={10}
                      minTickGap={24}
                    />
                    <YAxis
                      tickLine={false}
                      axisLine={false}
                      width={48}
                      tickFormatter={compactNumber}
                    />
                    <ChartTooltip
                      content={
                        <ChartTooltipContent
                          formatter={(value, name) => (
                            <div className="flex min-w-36 justify-between gap-4">
                              <span className="text-muted-foreground">
                                {name === 'inflow_index' ? 'Inflow' : 'Outflow'}
                              </span>
                              <span className="font-mono font-medium">
                                {indexNumber(Number(value))} idx
                              </span>
                            </div>
                          )}
                        />
                      }
                    />
                    <ChartLegend content={<ChartLegendContent />} />
                    <Area
                      isAnimationActive={false}
                      type="monotone"
                      dataKey="inflow_index"
                      fill="url(#inflow-fill)"
                      stroke="var(--color-inflow_index)"
                      strokeWidth={2}
                    />
                    <Area
                      type="monotone"
                      dataKey="outflow_index"
                      isAnimationActive={false}
                      fill="transparent"
                      stroke="var(--color-outflow_index)"
                      strokeWidth={2}
                    />
                  </AreaChart>
                </ChartContainer>
              </CardContent>
              <CardFooter className="border-t py-3 text-xs text-muted-foreground">
                All values are amount indices. A currency conversion has not
                been declared.
              </CardFooter>
            </Card>
            <Card className="min-w-0 shadow-none">
              <CardHeader>
                <CardTitle className="text-base">Monthly surplus</CardTitle>
                <CardDescription>
                  Net inflow minus outflow. Observed data, before any loan
                  repayment.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ChartContainer
                  config={{
                    surplus_index: {
                      label: 'Net surplus',
                      color: 'var(--chart-1)',
                    },
                  }}
                  className="h-44 w-full"
                >
                  <BarChart
                    data={cashflow}
                    accessibilityLayer
                    margin={{ left: 0, right: 12 }}
                  >
                    <CartesianGrid vertical={false} strokeDasharray="3 3" />
                    <XAxis
                      dataKey="label"
                      tickLine={false}
                      axisLine={false}
                      minTickGap={24}
                    />
                    <YAxis
                      width={48}
                      tickLine={false}
                      axisLine={false}
                      tickFormatter={compactNumber}
                    />
                    <ReferenceLine y={0} stroke="var(--border)" />
                    <ChartTooltip
                      cursor={false}
                      content={<ChartTooltipContent />}
                    />
                    <Bar
                      isAnimationActive={false}
                      dataKey="surplus_index"
                      fill="var(--color-surplus_index)"
                      radius={[3, 3, 0, 0]}
                    />
                  </BarChart>
                </ChartContainer>
              </CardContent>
            </Card>
          </TabsContent>
          <TabsContent value="transactions">
            <Card className="gap-0 shadow-none">
              <CardHeader className="border-b pb-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="space-y-1.5">
                    <CardTitle className="text-base">
                      Transaction history
                    </CardTitle>
                    <CardDescription>
                      {business.transaction_count} synthetic transactions.
                      Amounts are indices.
                    </CardDescription>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => downloadTransactions(business)}
                  >
                    <Download />
                    Download transactions
                  </Button>
                </div>
                <div className="mt-3 flex flex-wrap items-end gap-3">
                  <div className="min-w-40 flex-1 space-y-2">
                    <Label
                      htmlFor="transaction-search"
                      className="text-xs text-muted-foreground"
                    >
                      Filter transactions
                    </Label>
                    <Input
                      id="transaction-search"
                      value={transactionSearch}
                      onChange={(event) => {
                        setTransactionSearch(event.target.value);
                        setTransactionPage(0);
                      }}
                      placeholder="Date, channel, or amount…"
                    />
                  </div>
                  <div className="w-32 space-y-2">
                    <Label
                      htmlFor="transaction-direction"
                      className="text-xs text-muted-foreground"
                    >
                      Direction
                    </Label>
                    <Select
                      value={direction}
                      onValueChange={(value) => {
                        setDirection(value);
                        setTransactionPage(0);
                      }}
                    >
                      <SelectTrigger
                        id="transaction-direction"
                        className="w-full"
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All flows</SelectItem>
                        <SelectItem value="in">Inflow</SelectItem>
                        <SelectItem value="out">Outflow</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="w-32 space-y-2">
                    <Label
                      htmlFor="transaction-channel"
                      className="text-xs text-muted-foreground"
                    >
                      Channel
                    </Label>
                    <Select
                      value={channel}
                      onValueChange={(value) => {
                        setChannel(value);
                        setTransactionPage(0);
                      }}
                    >
                      <SelectTrigger
                        id="transaction-channel"
                        className="w-full"
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All channels</SelectItem>
                        {['card', 'transfer', 'qr', 'cash_in', 'other'].map(
                          (value) => (
                            <SelectItem key={value} value={value}>
                              {value.replace('_', ' ')}
                            </SelectItem>
                          ),
                        )}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="px-0">
                {filteredTransactions.length === 0 ? (
                  <Empty>
                    <EmptyHeader>
                      <EmptyTitle>No matching transactions</EmptyTitle>
                      <EmptyDescription>
                        Try another date, amount, or channel.
                      </EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="pl-6">Timestamp</TableHead>
                        <TableHead>Direction</TableHead>
                        <TableHead>Channel</TableHead>
                        <TableHead className="pr-6 text-right">
                          Amount index
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {pagedTransactions.map((transaction, index) => (
                        <TableRow key={`${transaction.ts}-${index}`}>
                          <TableCell className="py-3 pl-6 text-xs tabular-nums">
                            {transaction.ts
                              .replace('T', ' ')
                              .replace(/Z$/, ' UTC')}
                          </TableCell>
                          <TableCell>
                            <Badge
                              variant="outline"
                              className={`font-normal ${transaction.direction === 'in' ? 'text-emerald-700' : 'text-muted-foreground'}`}
                            >
                              {transaction.direction === 'in'
                                ? 'Inflow'
                                : 'Outflow'}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-xs capitalize">
                            {transaction.channel.replace('_', ' ')}
                          </TableCell>
                          <TableCell className="pr-6 text-right text-sm tabular-nums">
                            {indexNumber(transaction.amount_index)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
              <CardFooter className="flex-wrap justify-between gap-3 border-t py-3">
                <p className="text-xs text-muted-foreground">
                  {filteredTransactions.length ? currentPage * 20 + 1 : 0}–
                  {Math.min(
                    (currentPage + 1) * 20,
                    filteredTransactions.length,
                  )}{' '}
                  of {filteredTransactions.length}
                </p>
                <div className="flex items-center gap-2">
                  <Button
                    size="icon"
                    variant="outline"
                    aria-label="Previous transaction page"
                    disabled={currentPage === 0}
                    onClick={() => setTransactionPage(currentPage - 1)}
                  >
                    <ChevronLeft />
                  </Button>
                  <span className="text-xs text-muted-foreground">
                    Page {currentPage + 1} of {totalPages}
                  </span>
                  <Button
                    size="icon"
                    variant="outline"
                    aria-label="Next transaction page"
                    disabled={currentPage + 1 >= totalPages}
                    onClick={() => setTransactionPage(currentPage + 1)}
                  >
                    <ChevronRight />
                  </Button>
                </div>
              </CardFooter>
            </Card>
          </TabsContent>
          <TabsContent value="assessments">
            <Card className="shadow-none">
              <CardHeader>
                <CardTitle className="text-base">Assessment attempts</CardTitle>
                <CardDescription>
                  Successful and failed requests are persisted. Select a
                  completed assessment to review its recommendation below.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {assessmentQuery.isPending ? (
                  <Skeleton className="h-28 w-full" />
                ) : assessmentQuery.isError ? (
                  <Alert variant="destructive">
                    <AlertTitle>History unavailable</AlertTitle>
                    <AlertDescription>
                      {assessmentQuery.error.message}
                      <Button
                        variant="outline"
                        onClick={() => void assessmentQuery.refetch()}
                      >
                        Retry
                      </Button>
                    </AlertDescription>
                  </Alert>
                ) : assessments.length === 0 ? (
                  <Empty>
                    <EmptyHeader>
                      <EmptyMedia variant="icon">
                        <ClipboardCheck />
                      </EmptyMedia>
                      <EmptyTitle>No assessments yet</EmptyTitle>
                      <EmptyDescription>
                        Run an assessment when the ML service is connected.
                        Every attempt is recorded here.
                      </EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Date · Tashkent</TableHead>
                        <TableHead>Capacity score</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>
                          <span className="sr-only">Select assessment</span>
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {assessments.map((item) => (
                        <TableRow
                          key={item.id}
                          data-state={
                            item.id === assessment?.id ? 'selected' : undefined
                          }
                        >
                          <TableCell className="py-4">
                            <p className="text-xs">
                              {timeLabel(item.created_at)}
                            </p>
                            <p
                              className="mt-1 max-w-36 truncate font-mono text-[10px] text-muted-foreground"
                              title={item.id}
                            >
                              {item.id}
                            </p>
                          </TableCell>
                          <TableCell className="tabular-nums">
                            {item.result
                              ? `${item.result.capacity_score} / 100`
                              : '—'}
                          </TableCell>
                          <TableCell>
                            <Badge variant="secondary" className="font-normal">
                              {assessmentLabel(item)}
                            </Badge>
                            {item.error && (
                              <p
                                className="mt-1 max-w-60 truncate text-xs text-muted-foreground"
                                title={item.error}
                              >
                                {item.error}
                              </p>
                            )}
                          </TableCell>
                          <TableCell>
                            <Button
                              variant={
                                item.id === assessment?.id
                                  ? 'secondary'
                                  : 'ghost'
                              }
                              size="sm"
                              onClick={() => {
                                selectAssessment(item.id);
                                setDecisionError(null);
                              }}
                            >
                              {item.id === assessment?.id ? 'Selected' : 'View'}
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          </TabsContent>
          <TabsContent value="audit">
            <Card className="shadow-none">
              <CardHeader>
                <CardTitle className="text-base">
                  Business audit trail
                </CardTitle>
                <CardDescription>
                  Recorded imports, assessment attempts, and officer decisions.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {auditQuery.isPending ? (
                  <Skeleton className="h-28 w-full" />
                ) : auditQuery.isError ? (
                  <Alert variant="destructive">
                    <AlertTitle>Audit unavailable</AlertTitle>
                    <AlertDescription>
                      {auditQuery.error.message}
                      <Button
                        variant="outline"
                        onClick={() => void auditQuery.refetch()}
                      >
                        Retry
                      </Button>
                    </AlertDescription>
                  </Alert>
                ) : !auditQuery.data.items.length ? (
                  <Empty>
                    <EmptyHeader>
                      <EmptyMedia variant="icon">
                        <FileClock />
                      </EmptyMedia>
                      <EmptyTitle>No events yet</EmptyTitle>
                      <EmptyDescription>
                        Activity for this business will appear here.
                      </EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Event</TableHead>
                        <TableHead>Actor</TableHead>
                        <TableHead>Time · Tashkent</TableHead>
                        <TableHead>
                          <span className="sr-only">Details</span>
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {auditQuery.data.items.map((event) => (
                        <TableRow key={event.id}>
                          <TableCell className="py-4 text-xs">
                            {eventLabel(event.event_type)}
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {event.actor}
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {timeLabel(event.created_at)}
                          </TableCell>
                          <TableCell>
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label={`View ${eventLabel(event.event_type)} details`}
                              onClick={() => setAuditDetails(event)}
                            >
                              Details
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
        <Card className="gap-5 shadow-none">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Play className="size-4 text-primary" />
              New assessment
            </CardTitle>
            <CardDescription>
              Send this business's history to your connected ML service.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              id="assessment-form"
              className="space-y-4"
              onSubmit={(event) => {
                event.preventDefault();
                setAssessmentError(null);
                setAssessmentRequestId(undefined);
                const parsed = CreateAssessmentSchema.safeParse({
                  business_id: businessId,
                  requested_amount:
                    requestedAmount.trim() === ''
                      ? null
                      : Number(requestedAmount),
                  as_of_date: assessmentDate,
                });
                if (!parsed.success) {
                  setAssessmentError(
                    parsed.error.issues
                      .map(
                        (issue) => `${issue.path.join('.')}: ${issue.message}`,
                      )
                      .join(' · '),
                  );
                  return;
                }
                assessMutation.mutate(parsed.data);
              }}
            >
              <div className="space-y-2">
                <Label htmlFor="requested-amount">
                  Requested amount (UZS, optional)
                </Label>
                <Input
                  id="requested-amount"
                  type="number"
                  min="0"
                  max="1000000000000000"
                  step="any"
                  value={requestedAmount}
                  onChange={(event) => setRequestedAmount(event.target.value)}
                  placeholder="No requested amount"
                  disabled={assessMutation.isPending}
                />
                <p className="text-xs leading-relaxed text-muted-foreground">
                  Forwarded as UZS in the ML request. Returned recommendations
                  remain amount indices.
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="assessment-date">Assessment date</Label>
                <Input
                  id="assessment-date"
                  type="date"
                  value={assessmentDate}
                  onChange={(event) => setAssessmentDate(event.target.value)}
                  required
                  disabled={assessMutation.isPending}
                />
                <p className="text-xs text-muted-foreground">
                  The service considers history on or before this date.
                </p>
              </div>
              {mlConfigured === false && (
                <Alert className="border-amber-200 bg-amber-50/70">
                  <Info className="text-amber-700" />
                  <AlertTitle className="text-xs">
                    ML is awaiting connection
                  </AlertTitle>
                  <AlertDescription className="text-xs">
                    No model output is simulated. Running an assessment now will
                    record an unavailable-service attempt.
                  </AlertDescription>
                </Alert>
              )}
              {assessmentError && (
                <Alert variant="destructive">
                  <AlertTitle>Assessment unavailable</AlertTitle>
                  <AlertDescription className="break-words text-xs">
                    {assessmentError}
                    {assessmentRequestId && (
                      <span className="mt-2 block font-mono text-[10px]">
                        Request: {assessmentRequestId}
                      </span>
                    )}
                  </AlertDescription>
                </Alert>
              )}
            </form>
          </CardContent>
          <CardFooter className="flex-col items-stretch gap-3">
            <Button
              type="submit"
              form="assessment-form"
              disabled={assessMutation.isPending}
            >
              {assessMutation.isPending ? (
                <Loader2 className="animate-spin" />
              ) : (
                <Play />
              )}
              {assessMutation.isPending
                ? 'Assessing business…'
                : 'Run assessment'}
            </Button>
            <p className="text-center text-[11px] leading-relaxed text-muted-foreground">
              Assessment recommendations require a human review. Every attempt
              is audited.
            </p>
          </CardFooter>
        </Card>
      </div>
      {selectedAssessmentId &&
        !assessment &&
        selectedAssessmentQuery.isPending && (
          <Skeleton className="h-64 w-full" />
        )}
      {selectedAssessmentId &&
        !assessment &&
        selectedAssessmentQuery.isError && (
          <Alert variant="destructive">
            <AlertTitle>Selected assessment unavailable</AlertTitle>
            <AlertDescription>
              {selectedAssessmentQuery.error.message}
              <Button
                variant="outline"
                size="sm"
                onClick={() => void selectedAssessmentQuery.refetch()}
              >
                Retry
              </Button>
            </AlertDescription>
          </Alert>
        )}
      {!result && (!selectedAssessmentId || !!assessment) && (
        <Card className="border-dashed bg-transparent shadow-none">
          <CardContent>
            <Empty className="py-8">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <ClipboardCheck />
                </EmptyMedia>
                <EmptyTitle>
                  {assessmentError || assessment?.status === 'failed'
                    ? 'This assessment did not produce a recommendation'
                    : 'Your recommendation will appear here'}
                </EmptyTitle>
                <EmptyDescription>
                  {assessmentError || assessment?.status === 'failed'
                    ? (assessmentError ?? assessment?.error)
                    : 'Connect the ML service and run an assessment to see payment capacity, a cash-flow forecast, and an adaptive repayment schedule.'}
                </EmptyDescription>
              </EmptyHeader>
              {assessments.some((item) => item.status === 'completed') && (
                <Button
                  variant="outline"
                  onClick={() => {
                    const completed = assessments.find(
                      (item) => item.status === 'completed',
                    );
                    if (completed) selectAssessment(completed.id);
                  }}
                >
                  View last completed assessment
                </Button>
              )}
            </Empty>
          </CardContent>
        </Card>
      )}
      {result && assessment && (
        <>
          <Separator />
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1.5">
              <p className="text-xs font-medium tracking-widest text-primary uppercase">
                Assessment recommendation
              </p>
              <h2 className="text-xl font-semibold tracking-tight">
                Understand the business's payment capacity
              </h2>
              <p className="text-xs text-muted-foreground">
                As of {dateLabel(result.as_of_date)} · Model{' '}
                {result.model_version} · Created{' '}
                {timeLabel(assessment.created_at)} Tashkent
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                downloadJson(
                  `${business.id}-${assessment.id}-assessment.json`,
                  assessment,
                )
              }
            >
              <Download />
              Export assessment
            </Button>
          </div>
          <div className="grid gap-5 lg:grid-cols-[300px_minmax(0,1fr)]">
            <Card className="shadow-none">
              <CardHeader>
                <CardTitle className="text-base">Payment capacity</CardTitle>
                <CardDescription>
                  Capacity score from the ML service
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-end justify-between">
                  <p className="text-5xl font-semibold tracking-tight tabular-nums">
                    {indexNumber(result.capacity_score)}
                    <span className="ml-1 text-lg font-normal text-muted-foreground">
                      /100
                    </span>
                  </p>
                  <Badge variant="secondary" className="mb-1 capitalize">
                    {result.score_band} capacity
                  </Badge>
                </div>
                <Progress
                  value={result.capacity_score}
                  aria-label={`Capacity score ${result.capacity_score} out of 100`}
                />
                <p className="text-xs leading-relaxed text-muted-foreground">
                  Measures ability to service debt. This score is not a
                  probability of default or an automatic approval.
                </p>
                <Separator />
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">
                    Forecast confidence
                  </span>
                  <span className="font-medium tabular-nums">
                    {indexNumber(result.confidence * 100)}%
                  </span>
                </div>
                <p className="text-[11px] text-muted-foreground">
                  Reported by the model; this is not an evaluation metric.
                </p>
              </CardContent>
            </Card>
            <Card className="shadow-none">
              <CardHeader>
                <CardTitle className="text-base">
                  Recommended loan structure
                </CardTitle>
                <CardDescription>
                  Amount indices are not currency amounts. No UZS conversion is
                  assumed.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-5">
                <div className="grid gap-5 sm:grid-cols-3">
                  <div>
                    <p className="text-xs text-muted-foreground">
                      Suggested principal
                    </p>
                    <p className="mt-2 text-2xl font-semibold tabular-nums">
                      {indexNumber(
                        result.recommended_loan.suggested_principal_index,
                      )}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      amount index
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">
                      Affordable installment
                    </p>
                    <p className="mt-2 text-2xl font-semibold tabular-nums">
                      {indexNumber(
                        result.recommended_loan
                          .max_affordable_installment_index,
                      )}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      amount index / month
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">
                      Suggested term
                    </p>
                    <p className="mt-2 text-2xl font-semibold tabular-nums">
                      {result.recommended_loan.suggested_term_months}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">months</p>
                  </div>
                </div>
                <Separator />
                <div className="space-y-2">
                  <p className="text-xs font-medium">Model rationale</p>
                  <p className="text-sm leading-relaxed text-muted-foreground">
                    {result.recommended_loan.rationale ||
                      'No rationale was supplied.'}
                  </p>
                </div>
              </CardContent>
            </Card>
          </div>
          <Card className="shadow-none">
            <CardHeader>
              <CardTitle role="heading" aria-level={3} className="text-base">
                Model cash-flow summary
              </CardTitle>
              <CardDescription>
                Returned by the ML service for this assessment. These figures
                are distinct from the observed portfolio statistics above.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
              <div>
                <p className="text-xs text-muted-foreground">
                  Model average monthly inflow
                </p>
                <p className="mt-2 text-2xl font-semibold tabular-nums">
                  {indexNumber(
                    result.cashflow_summary.avg_monthly_inflow_index,
                  )}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  amount index
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">
                  Model net monthly surplus
                </p>
                <p className="mt-2 text-2xl font-semibold tabular-nums">
                  {indexNumber(
                    result.cashflow_summary.net_monthly_surplus_index,
                  )}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  amount index
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">
                  Inflow volatility
                </p>
                <p className="mt-2 text-2xl font-semibold tabular-nums">
                  {indexNumber(result.cashflow_summary.inflow_volatility)}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  coefficient of variation (CV)
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">
                  Model inflow trend
                </p>
                <p className="mt-2 text-2xl font-semibold capitalize">
                  {result.cashflow_summary.trend}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  reported by the scoring service
                </p>
              </div>
            </CardContent>
          </Card>
          {result.flags.length > 0 && (
            <Alert className="border-amber-200 bg-amber-50/60">
              <TriangleAlert className="text-amber-700" />
              <AlertTitle>Consider these model flags</AlertTitle>
              <AlertDescription>
                <div className="flex flex-wrap gap-2">
                  {result.flags.map((flag, index) => (
                    <Badge
                      key={`${flag}-${index}`}
                      variant="outline"
                      className="font-normal"
                    >
                      {flag.replaceAll('_', ' ')}
                    </Badge>
                  ))}
                </div>
              </AlertDescription>
            </Alert>
          )}
          <div className="grid items-start gap-5 xl:grid-cols-2">
            <Card className="min-w-0 shadow-none">
              <CardHeader>
                <CardTitle className="text-base">
                  12-month surplus forecast
                </CardTitle>
                <CardDescription>
                  Net cash flow forecast in amount indices. M1–M12 preserve the
                  ML service's ordered forecast.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ChartContainer
                  config={{
                    surplus: {
                      label: 'Forecast surplus',
                      color: 'var(--chart-1)',
                    },
                  }}
                  className="h-60 w-full"
                >
                  <LineChart
                    data={forecast}
                    accessibilityLayer
                    margin={{ left: 0, right: 12 }}
                  >
                    <CartesianGrid vertical={false} strokeDasharray="3 3" />
                    <XAxis dataKey="month" tickLine={false} axisLine={false} />
                    <YAxis
                      width={48}
                      tickLine={false}
                      axisLine={false}
                      tickFormatter={compactNumber}
                    />
                    <ReferenceLine y={0} stroke="var(--border)" />
                    <ChartTooltip content={<ChartTooltipContent />} />
                    <Line
                      isAnimationActive={false}
                      type="monotone"
                      dataKey="surplus"
                      stroke="var(--color-surplus)"
                      strokeWidth={2}
                      dot={{ r: 3 }}
                    />
                  </LineChart>
                </ChartContainer>
                <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-xs">
                  <span className="text-muted-foreground">
                    Weak months:{' '}
                    <span className="text-foreground">
                      {result.seasonality.weak_months.length
                        ? result.seasonality.weak_months.join(', ')
                        : 'None reported'}
                    </span>
                  </span>
                  <span className="text-muted-foreground">
                    Strong months:{' '}
                    <span className="text-foreground">
                      {result.seasonality.strong_months.length
                        ? result.seasonality.strong_months.join(', ')
                        : 'None reported'}
                    </span>
                  </span>
                </div>
              </CardContent>
            </Card>
            <Card className="min-w-0 shadow-none">
              <CardHeader>
                <CardTitle className="text-base">
                  Adaptive repayment schedule
                </CardTitle>
                <CardDescription>
                  Adaptive payments versus an equal-payment comparison with the
                  same total and term. No interest rate is assumed.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {schedule.length === 0 ? (
                  <Empty>
                    <EmptyHeader>
                      <EmptyTitle>No repayment schedule</EmptyTitle>
                      <EmptyDescription>
                        The model did not recommend a positive principal.
                      </EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                ) : (
                  <>
                    <ChartContainer
                      config={{
                        installment_index: {
                          label: 'Adaptive payment',
                          color: 'var(--chart-1)',
                        },
                        equal_payment: {
                          label: 'Equal payment comparison',
                          color: 'var(--chart-3)',
                        },
                      }}
                      className="h-60 w-full"
                    >
                      <ComposedChart
                        data={schedule}
                        accessibilityLayer
                        margin={{ left: 0, right: 12 }}
                      >
                        <CartesianGrid vertical={false} strokeDasharray="3 3" />
                        <XAxis
                          dataKey="month"
                          tickLine={false}
                          axisLine={false}
                          minTickGap={15}
                        />
                        <YAxis
                          width={48}
                          tickLine={false}
                          axisLine={false}
                          tickFormatter={compactNumber}
                        />
                        <ChartTooltip
                          cursor={false}
                          content={<ChartTooltipContent />}
                        />
                        <Bar
                          isAnimationActive={false}
                          dataKey="installment_index"
                          fill="var(--color-installment_index)"
                          radius={[3, 3, 0, 0]}
                        />
                        <Line
                          isAnimationActive={false}
                          type="linear"
                          dataKey="equal_payment"
                          stroke="var(--color-equal_payment)"
                          strokeDasharray="5 4"
                          dot={false}
                          strokeWidth={2}
                        />
                        <ChartLegend content={<ChartLegendContent />} />
                      </ComposedChart>
                    </ChartContainer>
                    <div className="mt-4 max-h-64 overflow-auto rounded-md border">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Month offset</TableHead>
                            <TableHead className="text-right">
                              Installment index
                            </TableHead>
                            <TableHead>Adjustment</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {schedule.map((row) => (
                            <TableRow key={row.month_offset}>
                              <TableCell className="text-xs">
                                Month {row.month_offset}
                              </TableCell>
                              <TableCell className="text-right text-xs tabular-nums">
                                {indexNumber(row.installment_index)}
                              </TableCell>
                              <TableCell>
                                <Badge
                                  variant="outline"
                                  className="text-[10px] font-normal capitalize"
                                >
                                  {row.note}
                                </Badge>
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  </>
                )}
              </CardContent>
            </Card>
          </div>
          <div className="grid gap-5 lg:grid-cols-2">
            <Card className="shadow-none">
              <CardHeader>
                <CardTitle className="text-base">
                  What shaped this assessment
                </CardTitle>
                <CardDescription>
                  Explanation factors and weights returned by the model.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {result.explanation.top_factors.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No explanation factors were supplied.
                  </p>
                ) : (
                  <div className="space-y-4">
                    {result.explanation.top_factors.map((factor, index) => (
                      <div
                        key={index}
                        className="flex items-start justify-between gap-3 border-b pb-4 last:border-0 last:pb-0"
                      >
                        <div className="flex gap-2.5">
                          {factor.impact === 'positive' ? (
                            <TrendingUp className="mt-0.5 size-4 shrink-0 text-primary" />
                          ) : (
                            <TrendingDown className="mt-0.5 size-4 shrink-0 text-amber-600" />
                          )}
                          <div>
                            <p className="text-sm leading-relaxed">
                              {factor.factor}
                            </p>
                            <p className="mt-1 text-xs text-muted-foreground">
                              {factor.impact === 'positive'
                                ? 'Supports'
                                : 'Limits'}{' '}
                              payment capacity
                            </p>
                          </div>
                        </div>
                        <Badge
                          variant="outline"
                          className="shrink-0 font-mono font-normal"
                        >
                          {indexNumber(factor.weight)}
                        </Badge>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
            <Card className="shadow-none">
              <CardHeader>
                <CardTitle className="text-base">
                  Advice for the entrepreneur
                </CardTitle>
                <CardDescription>
                  Actionable guidance from this assessment.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {result.explanation.advisory.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No advisory notes were supplied.
                  </p>
                ) : (
                  <ul className="space-y-4">
                    {result.explanation.advisory.map((advice, index) => (
                      <li key={index} className="flex gap-3">
                        <Check className="mt-0.5 size-4 shrink-0 text-primary" />
                        <p className="text-sm leading-relaxed text-muted-foreground">
                          {advice}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>
          <Card className="shadow-none">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <ShieldCheck className="size-4 text-primary" />
                Officer decision
              </CardTitle>
              <CardDescription>
                A human records the final review outcome. The first decision is
                immutable and is stored with the assessment.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {assessment.decision ? (
                <div className="space-y-4">
                  <div className="flex flex-wrap items-center gap-3">
                    <Badge
                      variant={
                        assessment.decision.decision === 'approved'
                          ? 'default'
                          : 'secondary'
                      }
                    >
                      {assessmentLabel(assessment)}
                    </Badge>
                    <p className="text-sm text-muted-foreground">
                      Recorded by{' '}
                      <span className="font-medium text-foreground">
                        {assessment.decision.reviewer_name}
                      </span>{' '}
                      · {timeLabel(assessment.decision.created_at)} Tashkent
                    </p>
                  </div>
                  <div className="rounded-md border bg-muted/30 p-4">
                    <p className="text-xs font-medium">Review notes</p>
                    <p className="mt-2 text-sm leading-relaxed whitespace-pre-wrap text-muted-foreground">
                      {assessment.decision.notes}
                    </p>
                  </div>
                  <p className="flex items-center gap-2 text-xs text-muted-foreground">
                    <ShieldCheck className="size-3.5" />
                    This decision has been persisted and audited.
                  </p>
                </div>
              ) : (
                <form
                  className="space-y-4"
                  onSubmit={(event) => {
                    event.preventDefault();
                    setDecisionError(null);
                    const parsed = DecisionInputSchema.safeParse({
                      decision,
                      reviewer_name: reviewer,
                      notes,
                    });
                    if (!parsed.success) {
                      setDecisionError(
                        parsed.error.issues
                          .map(
                            (issue) =>
                              `${issue.path.join('.')}: ${issue.message}`,
                          )
                          .join(' · '),
                      );
                      return;
                    }
                    setPendingDecision({
                      assessmentId: assessment.id,
                      data: parsed.data,
                    });
                  }}
                >
                  <div className="grid gap-4 sm:grid-cols-2">
                    <div className="space-y-2">
                      <Label htmlFor="decision">Decision</Label>
                      <Select
                        value={decision}
                        onValueChange={(value) =>
                          setDecision(value as DecisionInput['decision'])
                        }
                        disabled={decisionMutation.isPending}
                      >
                        <SelectTrigger id="decision" className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="approved">Approved</SelectItem>
                          <SelectItem value="declined">Declined</SelectItem>
                          <SelectItem value="needs_information">
                            Needs more information
                          </SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="reviewer-name">Reviewer name</Label>
                      <Input
                        id="reviewer-name"
                        value={reviewer}
                        onChange={(event) => setReviewer(event.target.value)}
                        placeholder="Your full name"
                        required
                        minLength={2}
                        maxLength={100}
                        disabled={decisionMutation.isPending}
                      />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="review-notes">Review notes</Label>
                    <Textarea
                      id="review-notes"
                      value={notes}
                      onChange={(event) => setNotes(event.target.value)}
                      placeholder="Explain the evidence and reason for your decision…"
                      required
                      minLength={5}
                      maxLength={3000}
                      disabled={decisionMutation.isPending}
                    />
                    <p className="text-xs text-muted-foreground">
                      At least 5 characters. Your name and reason are included
                      in the audit record.
                    </p>
                  </div>
                  {decisionError && (
                    <Alert variant="destructive">
                      <AlertTitle>Decision could not be recorded</AlertTitle>
                      <AlertDescription>{decisionError}</AlertDescription>
                    </Alert>
                  )}
                  <div className="flex justify-end">
                    <Button type="submit" disabled={decisionMutation.isPending}>
                      <ClipboardCheck />
                      Record decision
                    </Button>
                  </div>
                </form>
              )}
            </CardContent>
            <CardFooter className="border-t py-3">
              <p
                className="max-w-full truncate font-mono text-[10px] text-muted-foreground"
                title={`Assessment ${assessment.id} · Input hash ${assessment.input_hash} · ML request ${result.request_id}`}
              >
                Assessment {assessment.id} · Input hash {assessment.input_hash}{' '}
                · ML request {result.request_id}
              </p>
            </CardFooter>
          </Card>
        </>
      )}
      <Dialog
        open={!!pendingDecision}
        onOpenChange={(open) => {
          if (!open && !decisionMutation.isPending) setPendingDecision(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Record this decision?</DialogTitle>
            <DialogDescription>
              This saves the first and final decision for this assessment. It
              cannot be edited afterward.
            </DialogDescription>
          </DialogHeader>
          {pendingDecision && (
            <div className="space-y-4">
              <div className="flex items-center justify-between gap-4">
                <p className="text-sm text-muted-foreground">Outcome</p>
                <Badge variant="secondary">
                  {pendingDecision.data.decision === 'needs_information'
                    ? 'Needs more information'
                    : pendingDecision.data.decision === 'approved'
                      ? 'Approved'
                      : 'Declined'}
                </Badge>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Reviewer</p>
                <p className="mt-1 text-sm font-medium">
                  {pendingDecision.data.reviewer_name}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Review notes</p>
                <p className="mt-1 max-h-48 overflow-auto text-sm whitespace-pre-wrap">
                  {pendingDecision.data.notes}
                </p>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              disabled={decisionMutation.isPending}
              onClick={() => setPendingDecision(null)}
            >
              Go back
            </Button>
            <Button
              disabled={decisionMutation.isPending}
              onClick={() => {
                if (pendingDecision) decisionMutation.mutate(pendingDecision);
              }}
            >
              {decisionMutation.isPending ? (
                <Loader2 className="animate-spin" />
              ) : (
                <ShieldCheck />
              )}
              Confirm decision
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!auditDetails}
        onOpenChange={(open) => {
          if (!open) setAuditDetails(null);
        }}
      >
        <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {auditDetails
                ? eventLabel(auditDetails.event_type)
                : 'Audit event'}
            </DialogTitle>
            <DialogDescription>
              Original persisted event with its request and assessment
              identifiers.
            </DialogDescription>
          </DialogHeader>
          <pre className="max-h-[55dvh] overflow-auto rounded-md bg-muted p-4 font-mono text-xs whitespace-pre-wrap break-all">
            {JSON.stringify(auditDetails, null, 2)}
          </pre>
        </DialogContent>
      </Dialog>
    </>
  );
}
