import { useState } from 'react';
import type { UseQueryResult } from '@tanstack/react-query';
import type { AuditEvent, Business } from '@wiut/contracts';
import { Download, FileClock, Info } from 'lucide-react';
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
  Dialog,
  DialogContent,
  DialogDescription,
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
import { downloadJson, eventLabel, timeLabel } from '@/lib/format';

export function AuditPage({
  audit,
  businesses,
  onOpen,
}: {
  audit: UseQueryResult<Awaited<ReturnType<typeof api.audit>>, Error>;
  businesses: Business[];
  onOpen: (id: string) => void;
}) {
  const [businessId, setBusinessId] = useState('all');
  const [eventType, setEventType] = useState('all');
  const [selected, setSelected] = useState<AuditEvent | null>(null);
  const items = audit.data?.items ?? [];
  const filtered = items.filter(
    (item) =>
      (businessId === 'all' || item.business_id === businessId) &&
      (eventType === 'all' || item.event_type === eventType),
  );
  return (
    <>
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          Audit trail
        </h1>
        <p className="text-sm text-muted-foreground">
          A traceable record of imports, assessments, validation failures, and
          human decisions.
        </p>
      </div>
      <Alert>
        <Info />
        <AlertDescription>
          Timestamps are displayed in Tashkent time (UTC+5). Each event includes
          a request ID for tracing API and ML activity.
        </AlertDescription>
      </Alert>
      <Card className="gap-0 shadow-none">
        <CardHeader className="border-b pb-5">
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-48 space-y-2">
              <Label
                htmlFor="audit-business"
                className="text-xs text-muted-foreground"
              >
                Business
              </Label>
              <Select value={businessId} onValueChange={setBusinessId}>
                <SelectTrigger id="audit-business" className="w-full">
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
            <div className="min-w-48 space-y-2">
              <Label
                htmlFor="audit-event"
                className="text-xs text-muted-foreground"
              >
                Event type
              </Label>
              <Select value={eventType} onValueChange={setEventType}>
                <SelectTrigger id="audit-event" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All events</SelectItem>
                  {Array.from(
                    new Set(items.map((item) => item.event_type)),
                  ).map((event) => (
                    <SelectItem key={event} value={event}>
                      {eventLabel(event)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="ml-auto"
              onClick={() => downloadJson('flowcredit-audit.json', filtered)}
              disabled={!filtered.length}
            >
              <Download />
              Export audit
            </Button>
          </div>
        </CardHeader>
        <CardContent className="px-0">
          {audit.isPending ? (
            <div className="space-y-4 p-6">
              {Array.from({ length: 4 }, (_, i) => (
                <Skeleton key={i} className="h-14 w-full" />
              ))}
            </div>
          ) : audit.isError ? (
            <div className="p-6">
              <Alert variant="destructive">
                <AlertTitle>Audit unavailable</AlertTitle>
                <AlertDescription>
                  {audit.error.message}
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void audit.refetch()}
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
                  <FileClock />
                </EmptyMedia>
                <EmptyTitle>No audit events to show</EmptyTitle>
                <EmptyDescription>
                  Events appear as businesses are imported, assessments are
                  attempted, and decisions are recorded.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-6">Event</TableHead>
                  <TableHead>Business</TableHead>
                  <TableHead>Actor</TableHead>
                  <TableHead>Time · Tashkent</TableHead>
                  <TableHead>Request ID</TableHead>
                  <TableHead>
                    <span className="sr-only">Details</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell className="py-5 pl-6">
                      <Badge variant="outline" className="font-normal">
                        {eventLabel(item.event_type)}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {businesses.some(
                        (business) => business.id === item.business_id,
                      ) ? (
                        <Button
                          variant="link"
                          className="h-auto p-0 text-xs text-foreground"
                          onClick={() => onOpen(item.business_id)}
                        >
                          {
                            businesses.find(
                              (business) => business.id === item.business_id,
                            )!.name
                          }
                        </Button>
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          {item.business_id}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {item.actor}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {timeLabel(item.created_at)}
                    </TableCell>
                    <TableCell>
                      <span
                        className="block max-w-32 truncate font-mono text-[10px] text-muted-foreground"
                        title={item.request_id}
                      >
                        {item.request_id}
                      </span>
                    </TableCell>
                    <TableCell className="pr-6">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setSelected(item)}
                        aria-label={`View ${eventLabel(item.event_type)} details`}
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
        <CardFooter className="border-t py-4 text-xs text-muted-foreground">
          {filtered.length} audit events
        </CardFooter>
      </Card>
      <Dialog
        open={!!selected}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
      >
        <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {selected ? eventLabel(selected.event_type) : 'Audit event'}
            </DialogTitle>
            <DialogDescription>
              Original persisted event. All identifiers are preserved.
            </DialogDescription>
          </DialogHeader>
          <pre className="max-h-[55dvh] overflow-auto rounded-md bg-muted p-4 font-mono text-xs whitespace-pre-wrap break-all">
            {JSON.stringify(selected, null, 2)}
          </pre>
        </DialogContent>
      </Dialog>
    </>
  );
}
