export { getRequestErrorMessage, getRequestStatus } from '../src/shared/api/errors';
export { canAccessRoute, hasPermission, isRootIdentity } from '../src/shared/auth/access';
export type {
  AuthorizedMenuItem,
  CurrentUser,
  InitialState,
} from '../src/shared/auth/types';
export type { AvatarContext, AvatarContribution } from '../src/shared/avatar/contract';
export { defineAvatarContributions } from '../src/shared/avatar/contract';
export { PageContainer } from '../src/shared/design-system/PageContainer';
export {
  PageEmpty,
  PageError,
  PageForbidden,
  PageLoading,
} from '../src/shared/design-system/PageState';
export type { LayoutContext, LayoutContribution } from '../src/shared/layout/contributionContract';
export { defineLayoutContributions } from '../src/shared/layout/contributionContract';
export { queryClient, queryKeys } from '../src/shared/query/client';
export type { RouteRegistration } from '../src/shared/routes/registry';
export type { WorkplaceContext, WorkplaceContribution } from '../src/shared/workplace/contract';
export { defineWorkplaceContributions } from '../src/shared/workplace/contract';
