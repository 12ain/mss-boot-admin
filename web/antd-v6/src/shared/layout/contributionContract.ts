import type { ComponentType } from 'react';
import type { CurrentUser } from '../auth/types';
import { defineContributionEntries } from '../contributions/validation';

export interface LayoutContext {
  currentUser: CurrentUser;
  /** True in the condensed mobile header; always false in the footer. */
  compact: boolean;
}

/** Trusted, additive host content. UI visibility never grants API authorization. */
export interface LayoutContribution {
  id: string;
  position: 'header' | 'footer';
  /** Omit for authenticated-self content; supplied permissions use the existing access check. */
  permission?: string;
  component: ComponentType<LayoutContext>;
}

export function defineLayoutContributions(
  entries: readonly LayoutContribution[],
): readonly LayoutContribution[] {
  return defineContributionEntries(entries, {
    name: 'Layout',
    validate: (entry) => entry.position === 'header' || entry.position === 'footer',
  });
}
