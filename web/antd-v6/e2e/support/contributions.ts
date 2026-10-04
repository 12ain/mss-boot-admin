import type { Page } from '@playwright/test';

type ContributionProbeWindow = Window & { __mssThinHostContributionModules?: string[] };

// Fixture modules emit events on evaluation. Observing those events works with
// both utoo dev module URLs and Webpack production chunk names.
export async function trackContributionEvaluations(page: Page) {
  await page.addInitScript(() => {
    const modules: string[] = [];
    (window as ContributionProbeWindow).__mssThinHostContributionModules = modules;
    window.addEventListener('mss-thin-host-contribution-evaluated', (event) => {
      modules.push((event as CustomEvent<string>).detail);
    });
  });
}

export async function evaluatedContributions(page: Page): Promise<string[]> {
  return page.evaluate(
    () => (window as ContributionProbeWindow).__mssThinHostContributionModules ?? [],
  );
}
