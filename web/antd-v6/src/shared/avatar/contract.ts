import type { ComponentType } from 'react';
import type { CurrentUser } from '../auth/types';
import { defineContributionEntries } from '../contributions/validation';

export interface AvatarContext {
  currentUser: CurrentUser;
  open: boolean;
  close: () => void;
}

/** Trusted, compile-time host content. UI visibility never grants API authorization. */
export interface AvatarContribution {
  id: string;
  /** Omit for authenticated-self content; supplied permissions use the existing access check. */
  permission?: string;
  component: ComponentType<AvatarContext>;
}

export function defineAvatarContributions(
  entries: readonly AvatarContribution[],
): readonly AvatarContribution[] {
  return defineContributionEntries(entries, { name: 'Avatar' });
}
