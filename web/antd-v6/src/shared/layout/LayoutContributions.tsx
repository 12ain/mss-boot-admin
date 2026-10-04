import entries from '@mss-admin-business/layout';
import { useIntl } from '@umijs/max';
import { Alert } from 'antd';
import { hasPermission } from '../auth/access';
import type { CurrentUser, InitialState } from '../auth/types';
import { IsolatedContribution } from '../contributions/IsolatedContribution';
import { defineLayoutContributions, type LayoutContribution } from './contributionContract';

export const registeredLayoutContributions = defineLayoutContributions(entries);

export function getVisibleLayoutContributions(
  currentUser: CurrentUser | undefined,
  position: LayoutContribution['position'],
  contributions: readonly LayoutContribution[] = registeredLayoutContributions,
): readonly LayoutContribution[] {
  if (!currentUser) return [];
  return contributions.filter(
    (item) => item.position === position && hasPermission(currentUser, item.permission),
  );
}

export function LayoutContributions({
  initialState,
  position,
  compact = false,
  contributions = registeredLayoutContributions,
}: {
  initialState?: InitialState;
  position: LayoutContribution['position'];
  compact?: boolean;
  contributions?: readonly LayoutContribution[];
}) {
  const intl = useIntl();
  const currentUser = initialState?.currentUser;
  const visible = getVisibleLayoutContributions(currentUser, position, contributions);
  if (!currentUser || visible.length === 0) return null;
  return (
    <div
      className={
        position === 'header'
          ? 'flex min-w-0 max-w-[min(33vw,240px)] items-center gap-2 overflow-x-auto'
          : 'flex min-w-0 max-w-full flex-wrap items-center justify-center gap-2 break-words'
      }
      data-testid={`mss-layout-contributions-${position}`}
    >
      {visible.map((item) => {
        const HostContent = item.component;
        return (
          <div
            className={position === 'header' ? 'shrink-0' : 'min-w-0 max-w-full'}
            key={JSON.stringify([
              currentUser.id,
              initialState?.authSessionId,
              initialState?.authorizationVersion,
              item.id,
            ])}
          >
            <IsolatedContribution
              error={
                <Alert
                  type="error"
                  showIcon
                  title={intl.formatMessage({ id: 'navigation.customContentUnavailable' })}
                />
              }
              loading={
                <div role="status" aria-busy="true">
                  {intl.formatMessage({ id: 'navigation.customContentLoading' })}
                </div>
              }
            >
              <HostContent currentUser={currentUser} compact={position === 'header' && compact} />
            </IsolatedContribution>
          </div>
        );
      })}
    </div>
  );
}
