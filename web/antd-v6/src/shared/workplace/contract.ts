import type { ComponentType } from 'react';
import type { CurrentUser } from '../auth/types';

export interface WorkplaceContext {
  currentUser: CurrentUser;
}

/** Trusted, compile-time business code. A UI permission is never API authorization. */
export interface WorkplaceContribution {
  id: string;
  permission: string;
  component: ComponentType<WorkplaceContext>;
}

const reactComponentMarkers = new Set([
  Symbol.for('react.memo'),
  Symbol.for('react.forward_ref'),
  Symbol.for('react.lazy'),
]);

function isWorkplaceComponent(component: unknown): boolean {
  return (
    typeof component === 'function' ||
    (component !== null &&
      typeof component === 'object' &&
      '$$typeof' in component &&
      reactComponentMarkers.has(component.$$typeof as symbol))
  );
}

export function defineWorkplaceContributions(
  entries: readonly WorkplaceContribution[],
): readonly WorkplaceContribution[] {
  if (!Array.isArray(entries) || entries.length > 12)
    throw new Error('Workplace contributions must be a bounded array');
  const ids = new Set<string>();
  for (const entry of entries) {
    if (
      !entry ||
      !/^[a-z][a-z0-9-]{0,63}$/.test(entry.id) ||
      ids.has(entry.id) ||
      typeof entry.permission !== 'string' ||
      !entry.permission.trim() ||
      !isWorkplaceComponent(entry.component)
    ) {
      throw new Error('Invalid or duplicate workplace contribution');
    }
    ids.add(entry.id);
  }
  return Object.freeze(entries.map((entry) => Object.freeze({ ...entry })));
}
