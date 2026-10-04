import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { forwardRef, lazy, memo, useEffect, useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CurrentUser } from '../auth/types';
import { AvatarContributions, getVisibleAvatarContributions } from './AvatarContributions';
import { type AvatarContext, type AvatarContribution, defineAvatarContributions } from './contract';

vi.mock('@umijs/max', () => ({
  useIntl: () => ({ formatMessage: ({ id }: { id: string }) => id }),
}));

const reader: CurrentUser = { id: 'reader', permissions: { 'example:read': true } };
const denied: CurrentUser = { id: 'reader', permissions: { 'example:read': false } };

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('avatar contribution registration', () => {
  const entry: AvatarContribution = { id: 'example', component: () => null };

  it('allows authenticated-self content and copies immutable registrations', () => {
    const input = [entry];
    const registered = defineAvatarContributions(input);
    input.length = 0;
    expect(registered).toHaveLength(1);
    expect(registered[0]).not.toBe(entry);
    expect(Object.isFrozen(registered)).toBe(true);
    expect(Object.isFrozen(registered[0])).toBe(true);
  });

  it('rejects duplicate or malformed IDs, blank permissions and invalid components', () => {
    expect(() => defineAvatarContributions([entry, entry])).toThrow();
    for (const id of ['', 'Example', 'example/key', 'a'.repeat(65)]) {
      expect(() => defineAvatarContributions([{ ...entry, id }])).toThrow();
    }
    for (const permission of ['', '   ']) {
      expect(() => defineAvatarContributions([{ ...entry, permission }])).toThrow();
    }
    expect(() =>
      defineAvatarContributions([{ ...entry, component: {} as typeof entry.component }]),
    ).toThrow();
    expect(() =>
      defineAvatarContributions(
        Array.from({ length: 13 }, (_, index) => ({ ...entry, id: `entry-${index}` })),
      ),
    ).toThrow();
  });

  it('uses existing permission semantics without mounting to determine visibility', () => {
    const entries = defineAvatarContributions([
      entry,
      { ...entry, id: 'restricted', permission: 'example:read' },
    ]);
    expect(getVisibleAvatarContributions(undefined, entries)).toEqual([]);
    expect(getVisibleAvatarContributions(denied, entries).map((item) => item.id)).toEqual([
      'example',
    ]);
    expect(getVisibleAvatarContributions(reader, entries)).toEqual(entries);
    expect(getVisibleAvatarContributions({ ...denied, role: { root: true } }, entries)).toEqual(
      entries,
    );
  });
});

describe('avatar contribution lifecycle', () => {
  it('does not mount while closed, without identity or without the declared permission', () => {
    const mounted = vi.fn(() => <p>Restricted content</p>);
    const entries = defineAvatarContributions([
      { id: 'restricted', permission: 'example:read', component: mounted },
    ]);
    const close = vi.fn();
    const view = render(
      <AvatarContributions
        currentUser={reader}
        open={false}
        close={close}
        contributions={entries}
      />,
    );
    expect(mounted).not.toHaveBeenCalled();
    view.rerender(<AvatarContributions open close={close} contributions={entries} />);
    expect(mounted).not.toHaveBeenCalled();
    view.rerender(
      <AvatarContributions currentUser={denied} open close={close} contributions={entries} />,
    );
    expect(mounted).not.toHaveBeenCalled();
    view.rerender(
      <AvatarContributions currentUser={reader} open close={close} contributions={entries} />,
    );
    expect(screen.getByText('Restricted content')).toBeTruthy();
    view.rerender(
      <AvatarContributions currentUser={denied} open close={close} contributions={entries} />,
    );
    expect(screen.queryByText('Restricted content')).toBeNull();
  });

  it('passes the verified identity, open state and close callback to host content', () => {
    const close = vi.fn();
    const entries = defineAvatarContributions([
      {
        id: 'self',
        component: ({ currentUser, open, close }: AvatarContext) => (
          <button type="button" onClick={close}>
            {currentUser.id}:{String(open)}
          </button>
        ),
      },
    ]);
    render(<AvatarContributions currentUser={reader} open close={close} contributions={entries} />);
    fireEvent.click(screen.getByRole('button', { name: 'reader:true' }));
    expect(close).toHaveBeenCalledOnce();
  });

  it('supports memo and forwardRef host components', () => {
    const entries = defineAvatarContributions([
      { id: 'memo', component: memo(() => <p>Memo content</p>) },
      {
        id: 'forward',
        component: forwardRef<HTMLDivElement, AvatarContext>(({ currentUser }, ref) => (
          <div ref={ref}>Forwarded {currentUser.id}</div>
        )),
      },
    ]);
    render(
      <AvatarContributions currentUser={reader} open close={vi.fn()} contributions={entries} />,
    );
    expect(screen.getByText('Memo content')).toBeTruthy();
    expect(screen.getByText('Forwarded reader')).toBeTruthy();
  });

  it('defers lazy imports until open and authorized, with isolated localized loading', async () => {
    let finishLoading: ((value: { default: () => React.JSX.Element }) => void) | undefined;
    const load = vi.fn(
      () =>
        new Promise<{ default: () => React.JSX.Element }>((resolve) => {
          finishLoading = resolve;
        }),
    );
    const entries = defineAvatarContributions([
      { id: 'lazy', permission: 'example:read', component: lazy(load) },
      { id: 'ready', component: () => <p>Ready content</p> },
    ]);
    const props = { contributions: entries, close: vi.fn() };
    const view = render(<AvatarContributions {...props} currentUser={reader} open={false} />);
    expect(load).not.toHaveBeenCalled();
    view.rerender(<AvatarContributions {...props} open />);
    expect(load).not.toHaveBeenCalled();
    view.rerender(<AvatarContributions {...props} currentUser={denied} open />);
    expect(load).not.toHaveBeenCalled();
    view.rerender(<AvatarContributions {...props} currentUser={reader} open />);
    expect(load).toHaveBeenCalledOnce();
    expect(screen.getByRole('status').textContent).toBe('navigation.avatarContentLoading');
    expect(screen.getByRole('status').getAttribute('aria-busy')).toBe('true');
    expect(screen.getByText('Ready content')).toBeTruthy();
    await act(async () => finishLoading?.({ default: () => <p>Lazy content</p> }));
    expect(await screen.findByText('Lazy content')).toBeTruthy();
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('isolates render failure without exposing thrown details and resets on identity change', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const entries = defineAvatarContributions([
      {
        id: 'conditional',
        component: ({ currentUser }: AvatarContext) => {
          if (currentUser.id === 'reader') throw new Error('private upstream detail');
          return <p>Recovered content</p>;
        },
      },
      { id: 'working', component: () => <p>Working content</p> },
    ]);
    const props = { contributions: entries, close: vi.fn(), open: true };
    const view = render(<AvatarContributions {...props} currentUser={reader} />);
    expect(screen.getByRole('alert').textContent).toContain('navigation.avatarContentUnavailable');
    expect(screen.getByText('Working content')).toBeTruthy();
    expect(screen.queryByText('private upstream detail')).toBeNull();
    view.rerender(
      <AvatarContributions {...props} currentUser={{ ...reader, id: 'another-user' }} />,
    );
    expect(screen.getByText('Recovered content')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('isolates a rejected lazy import', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const entries = defineAvatarContributions([
      {
        id: 'failed',
        component: lazy(async () => {
          throw new Error('private import failure');
        }),
      },
      { id: 'working', component: () => <p>Working content</p> },
    ]);
    render(
      <AvatarContributions currentUser={reader} open close={vi.fn()} contributions={entries} />,
    );
    expect(await screen.findByText('navigation.avatarContentUnavailable')).toBeTruthy();
    expect(screen.getByText('Working content')).toBeTruthy();
    expect(screen.queryByText('private import failure')).toBeNull();
  });

  it('unmounts on close or identity loss and resets local state for another identity', () => {
    const cleanupContent = vi.fn();
    const Stateful = () => {
      const [count, setCount] = useState(0);
      useEffect(() => cleanupContent, []);
      return (
        <button type="button" onClick={() => setCount((value) => value + 1)}>
          Count {count}
        </button>
      );
    };
    const entries = defineAvatarContributions([{ id: 'stateful', component: Stateful }]);
    const props = { contributions: entries, close: vi.fn() };
    const view = render(<AvatarContributions {...props} currentUser={reader} open />);
    fireEvent.click(screen.getByRole('button', { name: 'Count 0' }));
    expect(screen.getByRole('button', { name: 'Count 1' })).toBeTruthy();
    view.rerender(
      <AvatarContributions {...props} currentUser={{ ...reader, id: 'another-user' }} open />,
    );
    expect(cleanupContent).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Count 0' })).toBeTruthy();
    view.rerender(
      <AvatarContributions
        {...props}
        currentUser={{ ...reader, id: 'another-user' }}
        open={false}
      />,
    );
    expect(cleanupContent).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('button')).toBeNull();
    view.rerender(<AvatarContributions {...props} currentUser={reader} open />);
    expect(screen.getByRole('button', { name: 'Count 0' })).toBeTruthy();
    view.rerender(<AvatarContributions {...props} open />);
    expect(cleanupContent).toHaveBeenCalledTimes(3);
    expect(screen.queryByRole('button')).toBeNull();
  });
});
