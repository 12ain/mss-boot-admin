import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const require = createRequire(import.meta.url);
const { defineBusinessAdmin } = require('../package/business.cjs');

describe('workplace package bridge', () => {
  it('defaults to no contributions in the reference application', () => {
    const config = defineBusinessAdmin();
    expect(config.alias['@mss-admin-business/workplace']).toBe(
      resolve(import.meta.dirname, '../package/empty-workplace.ts'),
    );
    expect(config.mssAdmin.workplaceContributions).toBe(
      config.alias['@mss-admin-business/workplace'],
    );
  });
  it('accepts an explicit trusted compile-time module without replacing core routes', () => {
    const config = defineBusinessAdmin({ workplaceContributions: './src/example-workplace.ts' });
    expect(config.alias['@mss-admin-business/workplace']).toBe(resolve('src/example-workplace.ts'));
    expect(() => defineBusinessAdmin({ workplaceContributions: 42 })).toThrow();
    expect(() => defineBusinessAdmin({ routes: [] })).toThrow();
  });
  it('uses the host configuration for the installed-package test bridge', () => {
    const root = resolve(import.meta.dirname, '../../..');
    const fixtures = resolve(root, '.mss/reports/workplace-test-fixtures');
    mkdirSync(fixtures, { recursive: true });
    const host = mkdtempSync(`${fixtures}/host-`);
    try {
      mkdirSync(resolve(host, 'config'));
      writeFileSync(
        resolve(host, 'config/config.ts'),
        `export default { mssAdmin: { workplaceContributions: ${JSON.stringify(resolve(host, 'src/custom-workplace.ts'))} } };`,
      );
      const config = resolve(import.meta.dirname, '../package/vitest.config.mjs');
      const output = execFileSync(
        process.execPath,
        [
          '--input-type=module',
          '-e',
          `const { default: config } = await import(${JSON.stringify(config)}); console.log(config.resolve.alias.find(item => item.find === '@mss-admin-business/workplace').replacement);`,
        ],
        { cwd: host, encoding: 'utf8' },
      );
      expect(output.trim()).toBe(resolve(host, 'src/custom-workplace.ts'));
    } finally {
      rmSync(host, { recursive: true, force: true });
    }
  }, 30_000);
});
