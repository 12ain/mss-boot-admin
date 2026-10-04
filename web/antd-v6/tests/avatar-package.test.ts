import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import type { BusinessAdminOptions } from '../package/business';
import emptyAvatar from '../package/empty-avatar';

const require = createRequire(import.meta.url);
const { defineBusinessAdmin } = require('../package/business.cjs') as {
  defineBusinessAdmin: (options?: Record<string, unknown>) => {
    alias: Record<string, string>;
    mssAdmin: { avatarContributions: string };
  };
};
const packageRoot = resolve(import.meta.dirname, '..');
const emptyModule = resolve(packageRoot, 'package/empty-avatar.ts');

describe('avatar package bridge', () => {
  it('keeps the reference application empty by default', () => {
    const config = defineBusinessAdmin();
    expect(config.alias['@mss-admin-business/avatar']).toBe(emptyModule);
    expect(config.mssAdmin.avatarContributions).toBe(emptyModule);
    expect(emptyAvatar).toEqual([]);
    expect(Object.isFrozen(emptyAvatar)).toBe(true);
  });

  it('accepts a typed explicit module and rejects invalid configuration', () => {
    const options = {
      avatarContributions: './src/custom-avatar.ts',
    } satisfies BusinessAdminOptions;
    expect(defineBusinessAdmin(options).alias['@mss-admin-business/avatar']).toBe(
      resolve(options.avatarContributions),
    );
    for (const avatarContributions of [null, 42, '', '  ', []]) {
      expect(() => defineBusinessAdmin({ avatarContributions })).toThrow(
        'avatarContributions must name a compile-time module.',
      );
    }
    expect(() => defineBusinessAdmin({ ...options, routes: [] })).toThrow(
      'Admin core routes are immutable',
    );
  });

  it.each(['empty', 'conventional', 'relative', 'absolute'] as const)(
    'resolves %s registration consistently in builds, TypeScript, watchers and installed tests',
    (mode) => {
      const fixtures = resolve(packageRoot, '../../.mss/reports/avatar-package-fixtures');
      mkdirSync(fixtures, { recursive: true });
      const host = mkdtempSync(`${fixtures}/host-`);
      try {
        mkdirSync(resolve(host, 'config'));
        mkdirSync(resolve(host, 'src/business'), { recursive: true });
        if (mode !== 'empty') {
          writeFileSync(resolve(host, 'src/business/avatar.ts'), 'export default [];\n');
        }
        const configured =
          mode === 'relative'
            ? './src/custom-avatar.ts'
            : mode === 'absolute'
              ? resolve(host, 'src/custom-avatar.ts')
              : undefined;
        if (configured) {
          writeFileSync(resolve(host, 'src/custom-avatar.ts'), 'export default [];\n');
        }
        const options = configured ? { avatarContributions: configured } : {};
        writeFileSync(
          resolve(host, 'config/config.ts'),
          `export default { mssAdmin: ${JSON.stringify(options)} };\n`,
        );
        const output = execFileSync(
          process.execPath,
          [
            '--input-type=module',
            '-e',
            `
              import { createRequire } from 'node:module';
              import { resolve } from 'node:path';
              import { pathToFileURL } from 'node:url';
              const { packageRoot, options } = JSON.parse(process.argv[1]);
              const require = createRequire(resolve(packageRoot, 'package/business.cjs'));
              const config = require('./business.cjs').defineBusinessAdmin(options);
              const hooks = {};
              const businessAlias = { '@': ['host-owned/*'] };
              require('./mssAdminPlugin.cjs')({
                cwd: process.cwd(),
                config: { mssAdmin: options },
                paths: { absSrcPath: resolve(packageRoot, 'src') },
                EnableBy: { config: 'config' },
                describe() {},
                modifyConfig(callback) { hooks.config = callback; },
                modifyTSConfig(callback) { hooks.types = callback; },
                addBeforeMiddlewares() {},
                addTmpGenerateWatcherPaths(callback) { hooks.watchers = callback; },
              });
              const plugin = hooks.config({ mssAdmin: options, alias: { '@': 'host-owned' } });
              const types = hooks.types({ compilerOptions: { paths: businessAlias } });
              const { default: tests } = await import(pathToFileURL(resolve(packageRoot, 'package/vitest.config.mjs')));
              console.log(JSON.stringify({
                build: config.alias['@mss-admin-business/avatar'],
                configured: config.mssAdmin.avatarContributions,
                plugin: plugin.alias['@mss-admin-business/avatar'],
                types: types.compilerOptions.paths['@mss-admin-business/avatar'],
                watchers: hooks.watchers(),
                tests: tests.resolve.alias.find(item => item.find === '@mss-admin-business/avatar').replacement,
                hostAlias: plugin.alias['@'],
                hostTypes: types.compilerOptions.paths['@'],
              }));
            `,
            JSON.stringify({ packageRoot, options }),
          ],
          { cwd: host, encoding: 'utf8' },
        );
        const result = JSON.parse(output.trim());
        const expected = configured
          ? resolve(host, configured)
          : mode === 'conventional'
            ? resolve(host, 'src/business/avatar.ts')
            : emptyModule;
        expect(result).toMatchObject({
          build: expected,
          configured: expected,
          plugin: expected,
          types: [expected],
          tests: expected,
          hostAlias: 'host-owned',
          hostTypes: ['host-owned/*'],
        });
        expect(result.watchers).toContain(expected);
      } finally {
        rmSync(host, { recursive: true, force: true });
      }
    },
    30_000,
  );
});
