import type { UseQueryResult } from '@tanstack/react-query';
import {
  ArrowRight,
  ArrowUpRight,
  Building2,
  ChartNoAxesCombined,
  ClipboardCheck,
  Clock3,
  Import,
  Info,
  ShieldCheck,
} from 'lucide-react';
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts';
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
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart';
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty';
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
import { api } from '@/lib/api';
import { assessmentLabel, compactNumber, dateLabel } from '@/lib/format';

export function OverviewPage({
  businesses,
  assessments,
  mlConfigured,
  onOpen,
  onViewBusinesses,
  onImport,
}: {
  businesses: UseQueryResult<Awaited<ReturnType<typeof api.businesses>>, Error>;
  assessments: UseQueryResult<
    Awaited<ReturnType<typeof api.assessments>>,
    Error
  >;
  mlConfigured: boolean | undefined;
  onOpen: (id: string) => void;
  onViewBusinesses: () => void;
  onImport: () => void;
}) {
  const items = businesses.data?.items ?? [];
  const history = assessments.data?.items ?? [];
  const waiting = history.filter(
    (item) => item.status === 'completed' && !item.decision,
  ).length;
  const sectors = Array.from(new Set(items.map((item) => item.sector))).map(
    (sector) => ({
      sector,
      businesses: items.filter((item) => item.sector === sector).length,
    }),
  );
  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <p className="text-xs font-medium tracking-widest text-primary uppercase">
            Portfolio overview
          </p>
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            A clearer view of business cash flow.
          </h1>
          <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
            Review transaction history, understand payment capacity, and record
            an informed human decision.
          </p>
        </div>
        <Button onClick={onImport} variant="outline">
          <Import />
          Import business
        </Button>
      </div>
      {mlConfigured === false && (
        <Alert className="border-amber-200 bg-amber-50/60">
          <Info className="text-amber-700" />
          <AlertTitle>ML service is awaiting connection</AlertTitle>
          <AlertDescription>
            You can explore cases and transactions now. Recommendations become
            available when your team's scoring service is connected. No model
            outputs are simulated.
          </AlertDescription>
        </Alert>
      )}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card className="gap-4 shadow-none">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardDescription>Businesses in portfolio</CardDescription>
            <Building2 className="size-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {businesses.isPending ? (
              <Skeleton className="h-9 w-16" />
            ) : (
              <p className="text-3xl font-semibold tabular-nums">
                {businesses.isError ? '—' : items.length}
              </p>
            )}
            <p className="mt-2 text-xs text-muted-foreground">
              Active business cases
            </p>
          </CardContent>
        </Card>
        <Card className="gap-4 shadow-none">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardDescription>Transactions available</CardDescription>
            <ChartNoAxesCombined className="size-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {businesses.isPending ? (
              <Skeleton className="h-9 w-16" />
            ) : (
              <p className="text-3xl font-semibold tabular-nums">
                {businesses.isError
                  ? '—'
                  : compactNumber(
                      items.reduce(
                        (sum, item) => sum + item.transaction_count,
                        0,
                      ),
                    )}
              </p>
            )}
            <p className="mt-2 text-xs text-muted-foreground">
              Observed inflows and outflows
            </p>
          </CardContent>
        </Card>
        <Card className="gap-4 shadow-none">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardDescription>Awaiting human review</CardDescription>
            <Clock3 className="size-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {assessments.isPending ? (
              <Skeleton className="h-9 w-16" />
            ) : (
              <p className="text-3xl font-semibold tabular-nums">
                {assessments.isError ? '—' : waiting}
              </p>
            )}
            <p className="mt-2 text-xs text-muted-foreground">
              Completed assessments without a decision
            </p>
          </CardContent>
        </Card>
        <Card className="gap-4 shadow-none">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardDescription>Decisions recorded</CardDescription>
            <ClipboardCheck className="size-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {assessments.isPending ? (
              <Skeleton className="h-9 w-16" />
            ) : (
              <p className="text-3xl font-semibold tabular-nums">
                {assessments.isError
                  ? '—'
                  : history.filter((item) => item.decision).length}
              </p>
            )}
            <p className="mt-2 text-xs text-muted-foreground">
              Persisted officer reviews
            </p>
          </CardContent>
        </Card>
      </div>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card className="min-w-0 shadow-none">
          <CardHeader className="flex flex-wrap flex-row items-center justify-between gap-3">
            <div className="space-y-1.5">
              <CardTitle className="text-base">
                Your business portfolio
              </CardTitle>
              <CardDescription>
                Select a case to explore its cash-flow history.
              </CardDescription>
            </div>
            <Button variant="ghost" size="sm" onClick={onViewBusinesses}>
              View all
              <ArrowUpRight />
            </Button>
          </CardHeader>
          <CardContent>
            {businesses.isPending ? (
              <div className="space-y-4">
                {Array.from({ length: 4 }, (_, i) => (
                  <Skeleton key={i} className="h-14 w-full" />
                ))}
              </div>
            ) : businesses.isError ? (
              <Alert variant="destructive">
                <AlertTitle>Portfolio unavailable</AlertTitle>
                <AlertDescription>
                  {businesses.error.message}
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
              <Empty>
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <Building2 />
                  </EmptyMedia>
                  <EmptyTitle>No businesses yet</EmptyTitle>
                  <EmptyDescription>
                    Add a business and upload its transaction history in UZS to
                    start a review.
                  </EmptyDescription>
                </EmptyHeader>
                <Button onClick={onImport}>
                  <Import />
                  Import first business
                </Button>
              </Empty>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Business</TableHead>
                    <TableHead className="hidden md:table-cell">
                      History
                    </TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="w-12">
                      <span className="sr-only">Open</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.slice(0, 6).map((business) => (
                    <TableRow key={business.id} className="group">
                      <TableCell>
                        <Button
                          variant="link"
                          className="h-auto p-0 text-left font-medium text-foreground"
                          onClick={() => onOpen(business.id)}
                        >
                          {business.name}
                        </Button>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {business.sector} · {business.location}
                        </p>
                      </TableCell>
                      <TableCell className="hidden text-muted-foreground md:table-cell">
                        {business.history_months} months
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={
                            business.latest_assessment?.decision?.decision ===
                            'approved'
                              ? 'default'
                              : 'secondary'
                          }
                          className="font-normal"
                        >
                          {assessmentLabel(business.latest_assessment)}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => onOpen(business.id)}
                          aria-label={`Open ${business.name}`}
                        >
                          <ArrowUpRight className="size-4 text-muted-foreground" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
          {items.length > 0 && (
            <CardFooter className="border-t py-3 text-xs text-muted-foreground">
              {items.length} active business cases in this workspace.
            </CardFooter>
          )}
        </Card>
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle className="text-base">
              A transparent review process
            </CardTitle>
            <CardDescription>
              Evidence first. Human judgment last.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="flex gap-3">
              <Building2 className="mt-0.5 size-4 shrink-0 text-primary" />
              <div>
                <p className="text-sm font-medium">1. Explore the business</p>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                  Inspect observed transactions and monthly cash flow.
                </p>
              </div>
            </div>
            <div className="flex gap-3">
              <ChartNoAxesCombined className="mt-0.5 size-4 shrink-0 text-primary" />
              <div>
                <p className="text-sm font-medium">
                  2. Assess payment capacity
                </p>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                  The connected ML service returns a forecast and affordable
                  repayment plan.
                </p>
              </div>
            </div>
            <div className="flex gap-3">
              <ShieldCheck className="mt-0.5 size-4 shrink-0 text-primary" />
              <div>
                <p className="text-sm font-medium">3. Record your decision</p>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                  An officer records the outcome, name, and reason in the audit
                  trail.
                </p>
              </div>
            </div>
            <Separator />
            <p className="text-xs leading-relaxed text-muted-foreground">
              A capacity score measures ability to make payments. It does not
              represent default probability.
            </p>
          </CardContent>
          <CardFooter>
            <Button
              variant="outline"
              className="w-full"
              onClick={onViewBusinesses}
            >
              Explore businesses
              <ArrowRight />
            </Button>
          </CardFooter>
        </Card>
      </div>
      {items.length > 0 && (
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle className="text-base">Portfolio mix</CardTitle>
            <CardDescription>
              Business count by sector, derived from the current portfolio.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ChartContainer
              config={{
                businesses: { label: 'Businesses', color: 'var(--chart-1)' },
              }}
              className="h-48 w-full"
            >
              <BarChart
                data={sectors}
                accessibilityLayer
                margin={{ left: -15, right: 10 }}
              >
                <CartesianGrid vertical={false} strokeDasharray="3 3" />
                <XAxis
                  dataKey="sector"
                  tickLine={false}
                  axisLine={false}
                  tickMargin={10}
                />
                <YAxis
                  allowDecimals={false}
                  tickLine={false}
                  axisLine={false}
                />
                <ChartTooltip
                  cursor={false}
                  content={<ChartTooltipContent />}
                />
                <Bar
                  isAnimationActive={false}
                  dataKey="businesses"
                  fill="var(--color-businesses)"
                  radius={[4, 4, 0, 0]}
                  maxBarSize={48}
                />
              </BarChart>
            </ChartContainer>
          </CardContent>
        </Card>
      )}
    </>
  );
}
