import { motion, useReducedMotion } from 'framer-motion';
import { useMe } from '@/session/SessionProvider';
import { PageHeader, PageSections } from '@/components/layout/AppShell';
import { StatCard } from '@/components/data/StatCard';
import { Note } from '@/components/ui/Note';
import { TextLink } from '@/components/ui/TextLink';
import { Card, CardBody } from '@/components/ui/Card';
import {
  ActiveChip,
  SubscriptionStatusChip,
  VerifiedChip,
} from '@/components/ui/StatusChip';
import {
  useInvoicesQuery,
  useMembersQuery,
  usePlansQuery,
  useTrainersQuery,
} from '@/hooks/queries';
import { cardListVariants, cardVariants } from '@/lib/motion';

/**
 * The first screen, per role.
 *
 * Every figure is either a `count` from page 1 of a list the role may read, or a
 * scalar from /api/me. The backend has no aggregate, statistics or reporting route,
 * so there is no revenue total, no outstanding balance, no attendance figure, no
 * growth percentage and no trend. Those are not omissions of taste — there is no
 * data behind any of them.
 *
 * Counts request page 1 only. `count` is on every page, so walking further would be
 * requests for nothing.
 */
export default function Overview(): JSX.Element {
  const me = useMe();
  const reduced = useReducedMotion() ?? false;

  const isOwner = me.role === 'owner';
  const isTrainer = me.role === 'trainer';
  const isMember = me.role === 'member';

  const members = useMembersQuery(1, isOwner || isTrainer);
  const trainers = useTrainersQuery(1, isOwner);
  const plans = usePlansQuery(1, isOwner || isTrainer);
  const invoices = useInvoicesQuery(1, isOwner || isMember);

  const greeting = me.first_name.trim().length > 0 ? `Welcome back, ${me.first_name}` : 'Overview';

  return (
    <PageSections>
      <PageHeader
        title={greeting}
        description={
          me.gym !== null
            ? `${me.gym.name} · signed in as ${me.role}`
            : `Signed in as ${me.role}`
        }
      />

      <motion.div
        variants={cardListVariants(reduced)}
        initial="hidden"
        animate="visible"
        className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4"
      >
        {isOwner ? (
          <>
            <motion.div variants={cardVariants(reduced)}>
              <StatCard
                label="Members"
                value={members.data?.count}
                loading={members.isPending}
                error={members.error ?? undefined}
                onRetry={() => void members.refetch()}
              />
            </motion.div>
            <motion.div variants={cardVariants(reduced)}>
              <StatCard
                label="Trainers"
                value={trainers.data?.count}
                loading={trainers.isPending}
                error={trainers.error ?? undefined}
                onRetry={() => void trainers.refetch()}
              />
            </motion.div>
            <motion.div variants={cardVariants(reduced)}>
              <StatCard
                label="Membership plans"
                value={plans.data?.count}
                loading={plans.isPending}
                error={plans.error ?? undefined}
                onRetry={() => void plans.refetch()}
              />
            </motion.div>
            <motion.div variants={cardVariants(reduced)}>
              <StatCard
                label="Invoices"
                value={invoices.data?.count}
                loading={invoices.isPending}
                error={invoices.error ?? undefined}
                onRetry={() => void invoices.refetch()}
              />
            </motion.div>
            <motion.div variants={cardVariants(reduced)} className="sm:col-span-2">
              <StatCard
                label="Subscription"
                display={<SubscriptionStatusChip status={me.subscription_status} />}
                hint={
                  me.subscription_status === null
                    ? 'Members cannot be added until a subscription exists.'
                    : undefined
                }
              />
            </motion.div>
          </>
        ) : null}

        {isTrainer ? (
          <>
            <motion.div variants={cardVariants(reduced)}>
              <StatCard
                label="Members assigned to you"
                value={members.data?.count}
                loading={members.isPending}
                error={members.error ?? undefined}
                onRetry={() => void members.refetch()}
                hint="Scoped by the API to members whose trainer is you."
              />
            </motion.div>
            <motion.div variants={cardVariants(reduced)}>
              <StatCard
                label="Membership plans"
                value={plans.data?.count}
                loading={plans.isPending}
                error={plans.error ?? undefined}
                onRetry={() => void plans.refetch()}
              />
            </motion.div>
          </>
        ) : null}

        {isMember ? (
          <>
            <motion.div variants={cardVariants(reduced)}>
              <StatCard
                label="Membership"
                display={
                  me.is_active_member === null ? (
                    <span className="text-body text-muted">Not reported</span>
                  ) : (
                    <ActiveChip active={me.is_active_member} />
                  )
                }
              />
            </motion.div>
            <motion.div variants={cardVariants(reduced)}>
              <StatCard
                label="Period ends"
                display={
                  <span className="tabular text-body">
                    {me.current_period_end ?? 'No end date recorded'}
                  </span>
                }
              />
            </motion.div>
            <motion.div variants={cardVariants(reduced)}>
              <StatCard label="Email" display={<VerifiedChip verified={me.email_verified} />} />
            </motion.div>
            <motion.div variants={cardVariants(reduced)}>
              <StatCard
                label="Your invoices"
                value={invoices.data?.count}
                loading={invoices.isPending}
                error={invoices.error ?? undefined}
                onRetry={() => void invoices.refetch()}
                hint="Only invoices payable by you."
              />
            </motion.div>
          </>
        ) : null}
      </motion.div>

      <div className="flex flex-col gap-4">
        {isOwner ? (
          <Note>
            Loading this page reads the invoice list, which can cause the backend to issue the
            upcoming subscription invoice. That is the API's behaviour, not an action taken here.
          </Note>
        ) : null}

        {me.subscription_status !== 'trialing' && me.subscription_status !== 'active' ? (
          <Note tone="warning">
            {me.subscription_status === null
              ? 'This gym has no subscription, so the API refuses every create and update request.'
              : `This gym's subscription is ${me.subscription_status}. The API is read-only until the outstanding invoice is settled.`}
          </Note>
        ) : null}

        {isMember && me.is_active_member === false ? (
          <Note tone="warning">
            Your membership is not active. Settle the outstanding invoice to regain write access.
          </Note>
        ) : null}
      </div>

      <Card>
        <CardBody className="pt-5">
          <h2 className="font-display text-subhead font-bold text-ink">Where to go next</h2>
          <ul className="mt-4 flex list-none flex-col gap-3 p-0">
            {isOwner ? (
              <>
                <li>
                  <TextLink to="/members">Add and maintain members</TextLink>
                </li>
                <li>
                  <TextLink to="/trainers">Invite a trainer</TextLink>
                </li>
                <li>
                  <TextLink to="/membership-plans">Define the plans you sell</TextLink>
                </li>
                <li>
                  <TextLink to="/invoices">Review and pay invoices</TextLink>
                </li>
              </>
            ) : null}
            {isTrainer ? (
              <>
                <li>
                  <TextLink to="/members">Members assigned to you</TextLink>
                </li>
                <li>
                  <TextLink to="/membership-plans">Plans this gym offers</TextLink>
                </li>
              </>
            ) : null}
            {isMember ? (
              <>
                <li>
                  <TextLink to="/my-membership">Your membership details</TextLink>
                </li>
                <li>
                  <TextLink to="/invoices">Your invoices</TextLink>
                </li>
              </>
            ) : null}
          </ul>
        </CardBody>
      </Card>
    </PageSections>
  );
}
