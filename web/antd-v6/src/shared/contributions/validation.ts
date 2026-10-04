interface ContributionEntry {
  id: string;
  permission?: string;
  component: unknown;
}

const reactComponentMarkers = new Set([
  Symbol.for('react.memo'),
  Symbol.for('react.forward_ref'),
  Symbol.for('react.lazy'),
]);

function isContributionComponent(component: unknown): boolean {
  return (
    typeof component === 'function' ||
    (component !== null &&
      typeof component === 'object' &&
      '$$typeof' in component &&
      reactComponentMarkers.has(component.$$typeof as symbol))
  );
}

/** Internal validation shared by the distinct public contribution contracts. */
export function defineContributionEntries<T extends ContributionEntry>(
  entries: readonly T[],
  {
    name,
    requirePermission = false,
    validate = () => true,
  }: {
    name: string;
    requirePermission?: boolean;
    validate?: (entry: T) => boolean;
  },
): readonly T[] {
  if (!Array.isArray(entries) || entries.length > 12)
    throw new Error(`${name} contributions must be a bounded array`);
  const ids = new Set<string>();
  for (const entry of entries) {
    if (
      !entry ||
      typeof entry.id !== 'string' ||
      !/^[a-z][a-z0-9-]{0,63}$/.test(entry.id) ||
      ids.has(entry.id) ||
      ((requirePermission || entry.permission !== undefined) &&
        (typeof entry.permission !== 'string' || !entry.permission.trim())) ||
      !isContributionComponent(entry.component) ||
      !validate(entry)
    ) {
      throw new Error(`Invalid or duplicate ${name.toLowerCase()} contribution`);
    }
    ids.add(entry.id);
  }
  return Object.freeze(entries.map((entry) => Object.freeze({ ...entry })));
}
