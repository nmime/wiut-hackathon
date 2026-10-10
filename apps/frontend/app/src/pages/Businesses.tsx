import { useState } from 'react';
import type { UseQueryResult } from '@tanstack/react-query';
import {
  ArrowUpRight,
  Building2,
  Import,
  Search,
  TrendingDown,
  TrendingUp,
  Minus,
} from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
} from '@/components/ui/card';
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
import { assessmentLabel, compactNumber, dateLabel } from '@/lib/format';

export function BusinessesPage({
  businesses,
  onOpen,
  onImport,
}: {
  businesses: UseQueryResult<Awaited<ReturnType<typeof api.businesses>>, Error>;
  onOpen: (id: string) => void;
  onImport: () => void;
}) {
  const [search, setSearch] = useState('');
  const [sector, setSector] = useState('all');
  const [status, setStatus] = useState('all');
  const items = businesses.data?.items ?? [];
  const filtered = items.filter(
    (business) =>
      `${business.name} ${business.id} ${business.location}`
        .toLowerCase()
        .includes(search.toLowerCase()) &&
      (sector === 'all' || business.sector === sector) &&
      (status === 'all' ||
        (status === 'unassessed' && !business.latest_assessment) ||
        (status === 'review' &&
          business.latest_assessment?.status === 'completed' &&
          !business.latest_assessment.decision) ||
        (status === 'decided' && business.latest_assessment?.decision) ||
        (status === 'failed' &&
          business.latest_assessment?.status === 'failed')),
  );
  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            Businesses
          </h1>
          <p className="text-sm text-muted-foreground">
            Your synthetic business portfolio, ready for a closer look.
          </p>
        </div>
        <Button onClick={onImport}>
          <Import />
          Import business
        </Button>
      </div>
      <Card className="gap-0 shadow-none">
        <CardHeader className="border-b pb-5">
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-[200px] flex-1 space-y-2">
              <Label
                htmlFor="business-search"
                className="text-xs text-muted-foreground"
              >
                Find a business
              </Label>
              <div className="relative">
                <Search className="pointer-events-none absolute top-2.5 left-3 size-4 text-muted-foreground" />
                <Input
                  id="business-search"
                  className="pl-9"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search name, location, or ID…"
                />
              </div>
            </div>
            <div className="w-full space-y-2 sm:w-44">
              <Label
                htmlFor="sector-filter"
                className="text-xs text-muted-foreground"
              >
                Sector
              </Label>
              <Select value={sector} onValueChange={setSector}>
                <SelectTrigger id="sector-filter" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All sectors</SelectItem>
                  {Array.from(new Set(items.map((item) => item.sector))).map(
                    (value) => (
                      <SelectItem key={value} value={value}>
                        {value}
                      </SelectItem>
                    ),
                  )}
                </SelectContent>
              </Select>
            </div>
            <div className="w-full space-y-2 sm:w-44">
              <Label
                htmlFor="status-filter"
                className="text-xs text-muted-foreground"
              >
                Review status
              </Label>
              <Select value={status} onValueChange={setStatus}>
                <SelectTrigger id="status-filter" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All statuses</SelectItem>
                  <SelectItem value="unassessed">Awaiting analysis</SelectItem>
                  <SelectItem value="review">Review required</SelectItem>
                  <SelectItem value="decided">Decision recorded</SelectItem>
                  <SelectItem value="failed">Analysis failed</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardHeader>
        <CardContent className="px-0">
          <div className="overflow-x-auto">
            {businesses.isPending ? (
              <div className="space-y-4 p-6">
                {Array.from({ length: 5 }, (_, i) => (
                  <Skeleton key={i} className="h-14 w-full" />
                ))}
              </div>
            ) : businesses.isError ? (
              <div className="p-6">
                <Alert variant="destructive">
                  <AlertTitle>Businesses could not be loaded</AlertTitle>
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
              </div>
            ) : filtered.length === 0 ? (
              <Empty className="py-20">
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <Building2 />
                  </EmptyMedia>
                  <EmptyTitle>
                    {items.length === 0
                      ? 'Start with a business'
                      : 'No matching businesses'}
                  </EmptyTitle>
                  <EmptyDescription>
                    {items.length === 0
                      ? 'Import synthetic transactions to create your first case.'
                      : 'Try another search or reset your filters.'}
                  </EmptyDescription>
                </EmptyHeader>
                {items.length === 0 ? (
                  <Button onClick={onImport}>Import business</Button>
                ) : (
                  <Button
                    variant="outline"
                    onClick={() => {
                      setSearch('');
                      setSector('all');
                      setStatus('all');
                    }}
                  >
                    Reset filters
                  </Button>
                )}
              </Empty>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-6">Business</TableHead>
                    <TableHead>Sector</TableHead>
                    <TableHead>History</TableHead>
                    <TableHead>Transactions</TableHead>
                    <TableHead>Inflow trend</TableHead>
                    <TableHead>Review status</TableHead>
                    <TableHead className="pr-6 text-right">
                      <span className="sr-only">Open business</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((business) => (
                    <TableRow key={business.id}>
                      <TableCell className="py-5 pl-6">
                        <Button
                          variant="link"
                          className="h-auto p-0 font-medium text-foreground"
                          onClick={() => onOpen(business.id)}
                        >
                          {business.name}
                        </Button>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {business.location} · {business.id}
                        </p>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {business.sector}
                      </TableCell>
                      <TableCell>
                        <p className="text-sm">
                          {business.history_months} months
                        </p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          To {dateLabel(business.last_activity_date)}
                        </p>
                      </TableCell>
                      <TableCell className="tabular-nums">
                        {compactNumber(business.transaction_count)}
                      </TableCell>
                      <TableCell>
                        <span className="inline-flex items-center gap-1.5 text-xs capitalize">
                          {business.trend === 'growing' ? (
                            <TrendingUp className="size-3.5 text-primary" />
                          ) : business.trend === 'declining' ? (
                            <TrendingDown className="size-3.5 text-amber-600" />
                          ) : (
                            <Minus className="size-3.5 text-muted-foreground" />
                          )}
                          {business.trend}
                        </span>
                      </TableCell>
                      <TableCell>
                        <Badge
                          className="font-normal"
                          variant={
                            business.latest_assessment?.decision?.decision ===
                            'approved'
                              ? 'default'
                              : business.latest_assessment?.status === 'failed'
                                ? 'outline'
                                : 'secondary'
                          }
                        >
                          {assessmentLabel(business.latest_assessment)}
                        </Badge>
                      </TableCell>
                      <TableCell className="pr-6 text-right">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => onOpen(business.id)}
                          aria-label={`Open ${business.name}`}
                        >
                          <span className="hidden lg:inline">Open case</span>
                          <ArrowUpRight />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </div>
        </CardContent>
        <CardFooter className="justify-between border-t py-4 text-xs text-muted-foreground">
          <span>
            {filtered.length} of {items.length} businesses
          </span>
          <span>Synthetic data only</span>
        </CardFooter>
      </Card>
    </>
  );
}
