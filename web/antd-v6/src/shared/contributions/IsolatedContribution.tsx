import { Component, type ReactNode, Suspense } from 'react';

class ContributionBoundary extends Component<
  { children: ReactNode; fallback: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/** The caller owns visibility, identity keys, layout, and localized fallbacks. */
export function IsolatedContribution({
  children,
  loading,
  error,
}: {
  children: ReactNode;
  loading: ReactNode;
  error: ReactNode;
}) {
  return (
    <ContributionBoundary fallback={error}>
      <Suspense fallback={loading}>{children}</Suspense>
    </ContributionBoundary>
  );
}
