import type { ComponentType } from 'react';
import type { CurrentUser } from '../auth/types';
import { defineContributionEntries } from '../contributions/validation';

export interface WorkplaceContext {
  currentUser: CurrentUser;
}

/** Trusted, compile-time business code. A UI permission is never API authorization. */
export interface WorkplaceContribution {
  id: string;
  permission: string;
  component: ComponentType<WorkplaceContext>;
}

export function defineWorkplaceContributions(
  entries: readonly WorkplaceContribution[],
): readonly WorkplaceContribution[] {
  return defineContributionEntries(entries, { name: 'Workplace', requirePermission: true });
}
