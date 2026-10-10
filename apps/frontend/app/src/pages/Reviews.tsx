import { useState } from 'react';
import type { UseQueryResult } from '@tanstack/react-query';
import type { Business } from '@wiut/contracts';
import { ArrowUpRight, ClipboardCheck, Download } from 'lucide-react';
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
import { assessmentLabel, downloadJson, timeLabel } from '@/lib/format';

export function ReviewsPage({
  assessments,
  businesses,
  onOpen,
}: {
  assessments: UseQueryResult<
    Awaited<ReturnType<typeof api.assessments>>,
    Error
  >;
  businesses: Business[];
  onOpen: (id: string, assessmentId?: string) => void;
}) {
  const [status, setStatus] = useState('all');
  const [businessId, setBusinessId] = useState('all');
  const items = assessments.data?.items ?? [];
  const filtered = items.filter(
    (item) =>
      (businessId === 'all' || item.business_id === businessId) &&
      (status === 'all' ||
        (status === 'failed' && item.status === 'failed') ||
        (status === 'waiting' &&
          item.status === 'completed' &&
          !item.decision) ||
        (status === 'decided' && item.decision)),
  );
  return (
    <>
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          Review history
        </h1>
        <p className="text-sm text-muted-foreground">
          Every assessment attempt and final officer decision, preserved for
          review.
        </p>
      </div>
      <Card className="gap-0 shadow-none">
        <CardHeader className="border-b pb-5">
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-48 space-y-2">
              <Label
                htmlFor="review-business"
                className="text-xs text-muted-foreground"
              >
                Business
              </Label>
              <Select value={businessId} onValueChange={setBusinessId}>
                <SelectTrigger id="review-business" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All businesses</SelectItem>
                  {businesses.map((item) => (
                    <SelectItem key={item.id} value={item.id}>
                      {item.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="min-w-44 space-y-2">
              <Label
                htmlFor="review-status"
                className="text-xs text-muted-foreground"
              >
                Assessment status
              </Label>
              <Select value={status} onValueChange={setStatus}>
                <SelectTrigger id="review-status" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All assessments</SelectItem>
                  <SelectItem value="waiting">Awaiting decision</SelectItem>
                  <SelectItem value="decided">Decision recorded</SelectItem>
                  <SelectItem value="failed">Analysis failed</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="ml-auto"
              onClick={() =>
                downloadJson('flowcredit-assessments.json', filtered)
              }
              disabled={!filtered.length}
            >
              <Download />
              Export history
            </Button>
          </div>
        </CardHeader>
        <CardContent className="px-0">
          {assessments.isPending ? (
            <div className="space-y-4 p-6">
              {Array.from({ length: 4 }, (_, i) => (
                <Skeleton key={i} className="h-14 w-full" />
              ))}
            </div>
          ) : assessments.isError ? (
            <div className="p-6">
              <Alert variant="destructive">
                <AlertTitle>History unavailable</AlertTitle>
                <AlertDescription>
                  {assessments.error.message}
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void assessments.refetch()}
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
                  <ClipboardCheck />
                </EmptyMedia>
                <EmptyTitle>
                  {items.length === 0
                    ? 'No assessments yet'
                    : 'No matching assessments'}
                </EmptyTitle>
                <EmptyDescription>
                  {items.length === 0
                    ? 'Open a business and run an assessment. Its result or failure will appear here.'
                    : 'Choose another business or assessment status.'}
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-6">Business / assessment</TableHead>
                  <TableHead>Created · Tashkent</TableHead>
                  <TableHead>Capacity score</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Reviewer</TableHead>
                  <TableHead>
                    <span className="sr-only">Open case</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell className="py-5 pl-6">
                      <Button
                        variant="link"
                        className="h-auto p-0 font-medium text-foreground"
                        onClick={() => onOpen(item.business_id, item.id)}
                      >
                        {businesses.find(
                          (business) => business.id === item.business_id,
                        )?.name ?? item.business_id}
                      </Button>
                      <p
                        className="mt-1 max-w-44 truncate font-mono text-[10px] text-muted-foreground"
                        title={item.id}
                      >
                        {item.id}
                      </p>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {timeLabel(item.created_at)}
                    </TableCell>
                    <TableCell className="tabular-nums">
                      {item.result ? (
                        <>
                          <span className="font-medium">
                            {item.result.capacity_score}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {' '}
                            / 100
                          </span>
                        </>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          item.decision?.decision === 'approved'
                            ? 'default'
                            : 'secondary'
                        }
                        className="font-normal"
                      >
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
                    <TableCell className="text-xs text-muted-foreground">
                      {item.decision?.reviewer_name ?? '—'}
                    </TableCell>
                    <TableCell className="pr-6">
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Open assessment for ${businesses.find((business) => business.id === item.business_id)?.name ?? item.business_id}`}
                        onClick={() => onOpen(item.business_id, item.id)}
                      >
                        <ArrowUpRight />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
        <CardFooter className="border-t py-4 text-xs text-muted-foreground">
          {filtered.length} assessment attempts · Scores measure payment
          capacity, not default probability.
        </CardFooter>
      </Card>
    </>
  );
}
