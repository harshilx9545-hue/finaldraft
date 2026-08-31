import { useMemo } from 'react';
import { useMe } from '@/session/SessionProvider';
import { PageHeader, PageSections } from '@/components/layout/AppShell';
import { Card, CardBody, CardHeader, CardTitle, CardDescription } from '@/components/ui/Card';
import { ReadOnlyField } from '@/components/ui/Field';
import { ActiveChip, SubscriptionStatusChip, VerifiedChip } from '@/components/ui/StatusChip';
import { Note } from '@/components/ui/Note';
import { TextLink } from '@/components/ui/TextLink';
import { ErrorState } from '@/components/data/States';
import { SkeletonFields } from '@/components/ui/Skeleton';
import { useAllPlansQuery, useMemberQuery } from '@/hooks/queries';

/**
 * A member's own record.
 *
 * This surface exists because of one small, approved backend addition:
 * `member_profile_id` on `MeSerializer`. Before it, `/api/me` returned the USER id
 * and nothing anywhere gave a member their MemberProfile id, so `GET
 * /api/members/{id}` was unreachable for them — the permission class already
 * admitted the request, only the identifier was missing. Guessing ids was never an
 * option.
 *
 * Read-only throughout: `MemberSelfScope` refuses a member's unsafe methods on every
 * view, and no view declares `member_writable`.
 */
export default function MyMembership(): JSX.Element {
  const me = useMe();
  const profileId = me.member_profile_id;
  const member = useMemberQuery(profileId);
  const plans = useAllPlansQuery();

  const planName = useMemo(() => {
    if (member.data?.plan === null || member.data === undefined) return null;
    const found = (plans.data?.items ?? []).find((plan) => plan.id === member.data.plan);
    return found?.name ?? `#${member.data.plan}`;
  }, [member.data, plans.data]);

  return (
    <PageSections>
      <PageHeader
        title="My membership"
        description={me.gym !== null ? me.gym.name : undefined}
      />

      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        <Card className="p-5">
          <p className="text-caption font-medium uppercase tracking-[0.08em] text-muted">
            Membership
          </p>
          <div className="mt-3">
            {me.is_active_member === null ? (
              <span className="text-body text-muted">Not reported</span>
            ) : (
              <ActiveChip active={me.is_active_member} />
            )}
          </div>
        </Card>
        <Card className="p-5">
          <p className="text-caption font-medium uppercase tracking-[0.08em] text-muted">
            Period ends
          </p>
          <p className="mt-3 text-body tabular text-ink">
            {me.current_period_end ?? 'No end date recorded'}
          </p>
        </Card>
        <Card className="p-5">
          <p className="text-caption font-medium uppercase tracking-[0.08em] text-muted">Email</p>
          <div className="mt-3">
            <VerifiedChip verified={me.email_verified} />
          </div>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-1">
            <CardTitle>Your details</CardTitle>
            <CardDescription>Maintained by your gym. Read-only for you.</CardDescription>
          </div>
        </CardHeader>
        <CardBody>
          {profileId === null ? (
            // Defensive: for a member the backend returns a non-null value, but the
            // field is nullable by design and this must not render a broken surface.
            <Note tone="warning">
              Your member record identifier was not supplied, so the assigned plan, trainer, join
              date, goal and photo cannot be retrieved.
            </Note>
          ) : member.isPending ? (
            <SkeletonFields fields={5} label="your details" />
          ) : member.isError ? (
            <ErrorState error={member.error} onRetry={() => void member.refetch()} />
          ) : (
            <div className="grid gap-6 sm:grid-cols-2">
              <ReadOnlyField label="Name" value={member.data.full_name} />
              <ReadOnlyField label="Email" value={member.data.email} />
              <ReadOnlyField label="Plan" value={planName ?? 'No plan'} />
              <ReadOnlyField
                label="Trainer"
                value={
                  member.data.trainer === null
                    ? 'No trainer assigned'
                    : `#${member.data.trainer}`
                }
                hint="The API does not let a member look up trainer names, so the identifier is shown as-is."
              />
              <ReadOnlyField
                label="Joined"
                value={<span className="tabular">{member.data.join_date}</span>}
              />
              <ReadOnlyField
                label="Goal"
                value={member.data.goal === '' ? 'Not set' : member.data.goal}
              />
              <ReadOnlyField
                label="Photo URL"
                value={member.data.photo_url === '' ? 'Not set' : member.data.photo_url}
                className="sm:col-span-2"
              />
            </div>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-1">
            <CardTitle>Gym subscription</CardTitle>
            <CardDescription>
              Your gym's own billing state, which affects what the API allows.
            </CardDescription>
          </div>
          <SubscriptionStatusChip status={me.subscription_status} />
        </CardHeader>
        <CardBody>
          <TextLink to="/invoices">See your invoices</TextLink>
        </CardBody>
      </Card>

      <Note>
        Membership periods cannot be started or renewed through the API, so nothing here can change
        your active state. Ask your gym to settle the relevant invoice.
      </Note>
    </PageSections>
  );
}
