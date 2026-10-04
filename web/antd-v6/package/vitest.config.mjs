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
const ownedAvatar = resolve(projectRoot, 'src/business/avatar.ts');
const configuredAvatar = hostConfig.mssAdmin?.avatarContributions;
if (
  configuredAvatar !== undefined &&
  (typeof configuredAvatar !== 'string' || !configuredAvatar.trim())
) {
  throw new TypeError('avatarContributions must name a compile-time module.');
}
const avatarContributions = configuredAvatar
  ? resolve(projectRoot, configuredAvatar)
  : existsSync(ownedAvatar)
    ? ownedAvatar
    : resolve(packageRoot, 'package/empty-avatar.ts');
const ownedLayout = resolve(projectRoot, 'src/business/layout.ts');
const configuredLayout = hostConfig.mssAdmin?.layoutContributions;
if (
  configuredLayout !== undefined &&
  (typeof configuredLayout !== 'string' || !configuredLayout.trim())
) {
  throw new TypeError('layoutContributions must name a compile-time module.');
}
const layoutContributions = configuredLayout
  ? resolve(projectRoot, configuredLayout)
  : existsSync(ownedLayout)
    ? ownedLayout
    : resolve(packageRoot, 'package/empty-layout.ts');
const managedRouteRegistrations = `${projectRoot}/src/route-registrations.ts`;
const generatedRouteRegistrations = `${projectRoot}/src/generated/routes.ts`;
const routeRegistrations = existsSync(managedRouteRegistrations)
  ? managedRouteRegistrations
  : generatedRouteRegistrations;

export default defineConfig({
  resolve: {
    alias: [
      {
        find: '@mss-admin-business/layout',
        replacement: layoutContributions,
      },
      {
        find: '@mss-admin-business/avatar',
        replacement: avatarContributions,
      },
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
