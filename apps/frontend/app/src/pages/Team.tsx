import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { type AuthSession } from '@wiut/contracts';
import {
  Copy,
  Loader2,
  Mail,
  ShieldCheck,
  UserPlus,
  Users,
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
import { dateLabel, timeLabel } from '@/lib/format';

export function TeamPage({ session }: { session: AuthSession }) {
  const queryClient = useQueryClient();
  const team = useQuery({ queryKey: ['team'], queryFn: api.team });
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<'admin' | 'officer'>('officer');
  const [generated, setGenerated] = useState<{
    token: string;
    invitation_url: string;
    email: string;
  } | null>(null);
  const [revokeId, setRevokeId] = useState<string | null>(null);
  const isAdmin = session.tenant.role === 'admin';
  const invite = useMutation({
    mutationFn: () => api.createInvitation({ email, role }),
    onSuccess: (result) => {
      setGenerated({
        token: result.token,
        invitation_url: result.invitation_url,
        email: result.invitation.email,
      });
      setEmail('');
      void queryClient.invalidateQueries({ queryKey: ['team'] });
      toast.success('Invitation created', {
        description: 'Copy the private link and share it with your teammate.',
      });
    },
  });
  const revoke = useMutation({
    mutationFn: api.revokeInvitation,
    onSuccess: () => {
      setRevokeId(null);
      void queryClient.invalidateQueries({ queryKey: ['team'] });
      toast.success('Invitation revoked');
    },
  });
  const revokeInvitation = team.data?.invitations.find(
    (invitation) => invitation.id === revokeId,
  );

  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      toast.success('Copied to clipboard');
    } catch {
      toast.error('Clipboard unavailable', {
        description:
          'Select the invitation link or token and copy it manually.',
      });
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium tracking-widest text-primary uppercase">
            Workspace settings
          </p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
            Team & access
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Manage the people who review credit cases in {session.tenant.name}.
          </p>
        </div>
        <Badge variant="outline" className="gap-1.5">
          <ShieldCheck className="size-3.5" />
          {isAdmin ? 'Workspace admin' : 'Credit officer'}
        </Badge>
      </div>
      <div className="grid gap-6 xl:grid-cols-[1fr_360px]">
        <Card className="min-w-0 shadow-none">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Users className="size-4 text-primary" />
              Members
            </CardTitle>
            <CardDescription>
              Members can assess businesses and record human review decisions.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {team.isPending ? (
              <Skeleton className="h-36 w-full" />
            ) : team.isError ? (
              <Alert variant="destructive">
                <AlertTitle>Team unavailable</AlertTitle>
                <AlertDescription>
                  {team.error.message}
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void team.refetch()}
                  >
                    Retry team
                  </Button>
                </AlertDescription>
              </Alert>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Member</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead className="hidden sm:table-cell">
                      Joined
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {team.data.members.map((member) => (
                    <TableRow key={member.id}>
                      <TableCell className="py-4">
                        <div className="font-medium">
                          {member.display_name}
                          {member.id === session.user.id && (
                            <span className="ml-2 text-xs font-normal text-muted-foreground">
                              You
                            </span>
                          )}
                        </div>
                        <div
                          className="mt-1 max-w-[230px] truncate text-xs text-muted-foreground"
                          title={member.email}
                        >
                          {member.email}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={
                            member.role === 'admin' ? 'default' : 'secondary'
                          }
                        >
                          {member.role === 'admin' ? 'Admin' : 'Credit officer'}
                        </Badge>
                      </TableCell>
                      <TableCell className="hidden text-xs text-muted-foreground sm:table-cell">
                        {dateLabel(member.joined_at.slice(0, 10))}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <UserPlus className="size-4 text-primary" />
              Invite a teammate
            </CardTitle>
            <CardDescription>
              {isAdmin
                ? 'Create a private invitation for a specific email address.'
                : 'Ask a workspace admin to invite your teammates.'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {isAdmin ? (
              <form
                className="space-y-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  invite.mutate();
                }}
              >
                <div className="space-y-2">
                  <Label htmlFor="invite-email">Teammate email</Label>
                  <Input
                    id="invite-email"
                    type="email"
                    autoComplete="off"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    required
                    maxLength={254}
                    disabled={invite.isPending}
                    placeholder="teammate@example.com"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="invite-role">Team role</Label>
                  <Select
                    value={role}
                    onValueChange={(value) =>
                      setRole(value as 'admin' | 'officer')
                    }
                    disabled={invite.isPending}
                  >
                    <SelectTrigger id="invite-role" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="officer">Credit officer</SelectItem>
                      <SelectItem value="admin">Admin</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    {role === 'admin'
                      ? 'Admins can review cases, invite teammates, and revoke invitations.'
                      : 'Credit officers can review cases and record decisions.'}
                  </p>
                </div>
                {invite.isError && (
                  <Alert variant="destructive">
                    <AlertTitle>Invitation could not be created</AlertTitle>
                    <AlertDescription>{invite.error.message}</AlertDescription>
                  </Alert>
                )}
                <Button
                  type="submit"
                  className="w-full"
                  disabled={invite.isPending}
                >
                  {invite.isPending ? (
                    <Loader2 className="animate-spin" />
                  ) : (
                    <UserPlus />
                  )}
                  Create invitation
                </Button>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  Copy and share the link yourself. Invitations are bound to the
                  invited email address and expire after seven days.
                </p>
              </form>
            ) : (
              <Alert>
                <ShieldCheck />
                <AlertDescription>
                  Your credit-officer role gives you access to this workspace's
                  portfolio and reviews. Team invitations are managed by admins.
                </AlertDescription>
              </Alert>
            )}
          </CardContent>
        </Card>
      </div>
      {isAdmin && (
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle className="text-base">Invitations</CardTitle>
            <CardDescription>
              Pending invitation links can be used once. Revoke an unused link
              to remove access.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {team.isPending ? (
              <Skeleton className="h-32 w-full" />
            ) : team.data && !team.data.invitations.length ? (
              <Empty className="py-8">
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <Mail />
                  </EmptyMedia>
                  <EmptyTitle>No invitations yet</EmptyTitle>
                  <EmptyDescription>
                    Invite a teammate using the form above.
                  </EmptyDescription>
                </EmptyHeader>
              </Empty>
            ) : (
              team.data && (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Email</TableHead>
                      <TableHead>Role</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead className="hidden md:table-cell">
                        Expires · Tashkent
                      </TableHead>
                      <TableHead>
                        <span className="sr-only">Actions</span>
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {team.data.invitations.map((invitation) => (
                      <TableRow key={invitation.id}>
                        <TableCell
                          className="max-w-[200px] truncate py-4 text-sm"
                          title={invitation.email}
                        >
                          {invitation.email}
                        </TableCell>
                        <TableCell className="text-xs">
                          {invitation.role === 'admin'
                            ? 'Admin'
                            : 'Credit officer'}
                        </TableCell>
                        <TableCell>
                          <Badge variant="secondary" className="capitalize">
                            {invitation.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="hidden text-xs text-muted-foreground md:table-cell">
                          {timeLabel(invitation.expires_at)}
                        </TableCell>
                        <TableCell className="text-right">
                          {invitation.status === 'pending' && (
                            <Button
                              size="sm"
                              variant="outline"
                              aria-label={`Revoke invitation for ${invitation.email}`}
                              onClick={() => {
                                revoke.reset();
                                setRevokeId(invitation.id);
                              }}
                            >
                              Revoke
                            </Button>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )
            )}
          </CardContent>
        </Card>
      )}
      <Dialog
        open={Boolean(generated)}
        onOpenChange={(open) => {
          if (!open) setGenerated(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Share the invitation</DialogTitle>
            <DialogDescription>
              Send this private link to {generated?.email}. The secret is shown
              here once; create a new invitation if you lose it.
            </DialogDescription>
          </DialogHeader>
          {generated && (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="invitation-link">Invitation link</Label>
                <Input
                  id="invitation-link"
                  value={generated.invitation_url}
                  readOnly
                  onFocus={(event) => event.target.select()}
                />
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => void copy(generated.invitation_url)}
                >
                  <Copy />
                  Copy invitation link
                </Button>
              </div>
              <div className="space-y-2">
                <Label htmlFor="invitation-token">Invitation token</Label>
                <Input
                  id="invitation-token"
                  value={generated.token}
                  readOnly
                  className="font-mono text-xs"
                  onFocus={(event) => event.target.select()}
                />
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => void copy(generated.token)}
                >
                  <Copy />
                  Copy invitation token
                </Button>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button onClick={() => setGenerated(null)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={Boolean(revokeId)}
        onOpenChange={(open) => {
          if (!open && !revoke.isPending) setRevokeId(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Revoke this invitation?</DialogTitle>
            <DialogDescription>
              The invitation for {revokeInvitation?.email} will stop working
              immediately. You can create another invitation later.
            </DialogDescription>
          </DialogHeader>
          {revoke.isError && (
            <Alert variant="destructive">
              <AlertDescription>{revoke.error.message}</AlertDescription>
            </Alert>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setRevokeId(null)}
              disabled={revoke.isPending}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={revoke.isPending}
              onClick={() => {
                if (revokeId) revoke.mutate(revokeId);
              }}
            >
              {revoke.isPending && <Loader2 className="animate-spin" />}Revoke
              invitation
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export function InvitationPage({
  token,
  session,
  onAccepted,
  onBack,
}: {
  token: string;
  session: AuthSession;
  onAccepted: (session: AuthSession) => Promise<void>;
  onBack: () => void;
}) {
  const validToken = /^[A-Za-z0-9_-]{43}$/.test(token);
  const accept = useMutation({
    mutationFn: () => api.acceptInvitation({ token }),
    onSuccess: onAccepted,
  });
  return (
    <div className="mx-auto max-w-xl py-8">
      <Card className="shadow-none">
        <CardHeader>
          <UserPlus className="mb-2 size-8 text-primary" />
          <CardTitle role="heading" aria-level={1} className="text-2xl">
            Join a workspace
          </CardTitle>
          <CardDescription className="leading-relaxed">
            Accept the invitation as{' '}
            <span className="font-medium text-foreground">
              {session.user.email}
            </span>
            . You can switch between your workspaces after joining.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <Alert>
            <ShieldCheck />
            <AlertDescription>
              The invitation must match your account email and must still be
              active. Your existing workspace membership stays available.
            </AlertDescription>
          </Alert>
          {!validToken && (
            <Alert variant="destructive">
              <AlertTitle>Invitation link is incomplete</AlertTitle>
              <AlertDescription>
                Ask your workspace admin for the full invitation link, then open
                it again.
              </AlertDescription>
            </Alert>
          )}
          {accept.isError && (
            <Alert variant="destructive">
              <AlertTitle>Invitation could not be accepted</AlertTitle>
              <AlertDescription>{accept.error.message}</AlertDescription>
            </Alert>
          )}
          <div className="flex flex-wrap justify-end gap-3">
            <Button
              variant="outline"
              onClick={onBack}
              disabled={accept.isPending}
            >
              Back to workspace
            </Button>
            <Button
              onClick={() => accept.mutate()}
              disabled={accept.isPending || !validToken}
            >
              {accept.isPending ? (
                <Loader2 className="animate-spin" />
              ) : (
                <UserPlus />
              )}
              Accept invitation
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
