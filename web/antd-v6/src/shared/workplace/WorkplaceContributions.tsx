import entries from '@mss-admin-business/workplace';
import { hasPermission } from '@mss-admin-core/shared/auth/access';
import type { InitialState } from '@mss-admin-core/shared/auth/types';
import { PageLoading } from '@mss-admin-core/shared/design-system/PageState';
import { useIntl, useModel } from '@umijs/max';
import { Alert } from 'antd';
import { IsolatedContribution } from '../contributions/IsolatedContribution';
import { defineWorkplaceContributions, type WorkplaceContribution } from './contract';

const registered = defineWorkplaceContributions(entries);

export function WorkplaceContributions({
  contributions = registered,
}: {
  contributions?: readonly WorkplaceContribution[];
}) {
  const intl = useIntl();
  const { initialState } = useModel('@@initialState') as { initialState?: InitialState };
  const user = initialState?.currentUser;
  if (!user) return null;
  return (
    <>
      {contributions
        .filter((item) => hasPermission(user, item.permission))
        .map((item) => {
          const BusinessContent = item.component;
          return (
            <div className="mb-4" key={`${user.id}:${item.id}`}>
              <IsolatedContribution
                loading={<PageLoading rows={2} />}
                error={
                  <Alert
                    type="error"
                    showIcon
                    title={intl.formatMessage({ id: 'pages.workplace.businessUnavailable' })}
                  />
                }
              >
                <BusinessContent currentUser={user} />
              </IsolatedContribution>
            </div>
          );
        })}
    </>
  );
}
