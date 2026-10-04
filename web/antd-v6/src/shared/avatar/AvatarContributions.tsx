import entries from '@mss-admin-business/avatar';
import { hasPermission } from '@mss-admin-core/shared/auth/access';
import type { CurrentUser } from '@mss-admin-core/shared/auth/types';
import { useIntl } from '@umijs/max';
import { Alert } from 'antd';
import { IsolatedContribution } from '../contributions/IsolatedContribution';
import { type AvatarContribution, defineAvatarContributions } from './contract';

export const registeredAvatarContributions = defineAvatarContributions(entries);

export function getVisibleAvatarContributions(
  currentUser: CurrentUser | undefined,
  contributions: readonly AvatarContribution[] = registeredAvatarContributions,
): readonly AvatarContribution[] {
  if (!currentUser) return [];
  return contributions.filter((item) => hasPermission(currentUser, item.permission));
}

export function AvatarContributions({
  currentUser,
  open,
  close,
  contributions = registeredAvatarContributions,
}: {
  currentUser?: CurrentUser;
  open: boolean;
  close: () => void;
  contributions?: readonly AvatarContribution[];
}) {
  const intl = useIntl();
  if (!open || !currentUser) return null;
  return (
    <>
      {getVisibleAvatarContributions(currentUser, contributions).map((item) => {
        const HostContent = item.component;
        return (
          <IsolatedContribution
            key={`${currentUser.id}:${item.id}`}
            error={
              <Alert
                type="error"
                showIcon
                title={intl.formatMessage({ id: 'navigation.avatarContentUnavailable' })}
              />
            }
            loading={
              <div role="status" aria-busy="true">
                {intl.formatMessage({ id: 'navigation.avatarContentLoading' })}
              </div>
            }
          >
            <HostContent currentUser={currentUser} open={open} close={close} />
          </IsolatedContribution>
        );
      })}
    </>
  );
}
