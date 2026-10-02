import { existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

const packageRoot = fileURLToPath(new URL('..', import.meta.url));
const projectRoot = process.cwd();
const require = createRequire(import.meta.url);
const { Config } = require(
  require.resolve('@umijs/core/dist/config/config', {
    paths: [dirname(require.resolve('@umijs/max/package.json'))],
  }),
);
const { config: hostConfig } = new Config({
  cwd: projectRoot,
  env: 'test',
  specifiedEnv: process.env.UMI_ENV,
  defaultConfigFiles: ['.umirc.ts', '.umirc.js', 'config/config.ts', 'config/config.js'],
}).getUserConfig();
const ownedWorkplace = `${projectRoot}/src/business/workplace.ts`;
const workplaceContributions = hostConfig.mssAdmin?.workplaceContributions
  ? resolve(projectRoot, hostConfig.mssAdmin.workplaceContributions)
  : existsSync(ownedWorkplace)
    ? ownedWorkplace
    : `${packageRoot}/package/empty-workplace.ts`;
const managedRouteRegistrations = `${projectRoot}/src/route-registrations.ts`;
const generatedRouteRegistrations = `${projectRoot}/src/generated/routes.ts`;
const routeRegistrations = existsSync(managedRouteRegistrations)
  ? managedRouteRegistrations
  : generatedRouteRegistrations;

export default defineConfig({
  resolve: {
    alias: [
      {
        find: '@mss-admin-business/workplace',
        replacement: workplaceContributions,
      },
      {
        find: '@mss-admin-business/routes',
        replacement: routeRegistrations,
      },
      { find: '@mss-admin-core', replacement: `${packageRoot}/src` },
      { find: '@', replacement: `${projectRoot}/src` },
    ],
  },
  test: {
    environment: 'happy-dom',
    globals: true,
    passWithNoTests: true,
    setupFiles: [`${packageRoot}/tests/setup.ts`],
    include: ['src/**/*.test.{ts,tsx}', 'tests/**/*.test.{ts,tsx}'],
    maxWorkers: 2,
    clearMocks: true,
    restoreMocks: true,
  },
});
