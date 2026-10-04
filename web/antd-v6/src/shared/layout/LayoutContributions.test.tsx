import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { forwardRef, lazy, memo, useEffect, useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CurrentUser, InitialState } from '../auth/types';
import {
  defineLayoutContributions,
  type LayoutContext,
  type LayoutContribution,
} from './contributionContract';
import { getVisibleLayoutContributions, LayoutContributions } from './LayoutContributions';

vi.mock('@umijs/max', () => ({
  useIntl: () => ({ formatMessage: ({ id }: { id: string }) => id }),
}));

const reader: CurrentUser = { id: 'reader', permissions: { 'example:read': true } };
const denied: CurrentUser = { id: 'reader', permissions: { 'example:read': false } };
function state(currentUser?: CurrentUser, updates: Partial<InitialState> = {}): InitialState {
  return {
    currentUser,
    authorizedMenu: [],
    settings: {},
    fetchCurrentUser: async () => currentUser,
    authSessionId: 'session-one',
    authorizationVersion: 1,
    ...updates,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('layout contribution registration', () => {
  const entry: LayoutContribution = {
    id: 'example',
    position: 'header',
    component: () => null,
  };

  it('accepts header/footer self content and returns immutable copies', () => {
    const input = [entry, { ...entry, id: 'footer', position: 'footer' as const }];
    const registered = defineLayoutContributions(input);
    input.length = 0;
    expect(registered).toHaveLength(2);
    expect(registered[0]).not.toBe(entry);
    expect(Object.isFrozen(registered)).toBe(true);
    expect(Object.isFrozen(registered[0])).toBe(true);
  });

  it('rejects unknown positions, IDs duplicated across positions and malformed registrations', () => {
    expect(() =>
      defineLayoutContributions([
        { ...entry, position: 'sidebar' } as unknown as LayoutContribution,
      ]),
    ).toThrow();
    expect(() => defineLayoutContributions([entry, { ...entry, position: 'footer' }])).toThrow();
    expect(() => defineLayoutContributions([{ ...entry, permission: '   ' }])).toThrow();
    expect(() => defineLayoutContributions([{ ...entry, id: 'a'.repeat(65) }])).toThrow();
    expect(() =>
      defineLayoutContributions([{ ...entry, component: {} as typeof entry.component }]),
    ).toThrow();
    expect(() =>
      defineLayoutContributions(
        Array.from({ length: 13 }, (_, index) => ({ ...entry, id: `entry-${index}` })),
      ),
    ).toThrow();
  });

  it('selects only the requested position and preserves root permission semantics', () => {
    const entries = defineLayoutContributions([
      entry,
      { ...entry, id: 'restricted', permission: 'example:read' },
      { ...entry, id: 'footer', position: 'footer' },
    ]);
    expect(getVisibleLayoutContributions(undefined, 'header', entries)).toEqual([]);
    expect(getVisibleLayoutContributions(denied, 'header', entries).map((item) => item.id)).toEqual(
      ['example'],
    );
    expect(getVisibleLayoutContributions(reader, 'footer', entries).map((item) => item.id)).toEqual(
      ['footer'],
    );
    expect(
      getVisibleLayoutContributions({ ...denied, role: { root: true } }, 'header', entries).map(
        (item) => item.id,
      ),
    ).toEqual(['example', 'restricted']);
  });
});

describe('layout contribution lifecycle', () => {
  it('does not mount without identity or permission and removes content on permission loss', () => {
    const component = vi.fn(() => <p>Restricted header</p>);
    const entries = defineLayoutContributions([
      { id: 'restricted', position: 'header', permission: 'example:read', component },
    ]);
    const view = render(<LayoutContributions position="header" contributions={entries} />);
    expect(component).not.toHaveBeenCalled();
    expect(screen.queryByTestId('mss-layout-contributions-header')).toBeNull();
    view.rerender(
      <LayoutContributions
        initialState={state(denied)}
        position="header"
        contributions={entries}
      />,
    );
    expect(component).not.toHaveBeenCalled();
    view.rerender(
      <LayoutContributions
        initialState={state(reader)}
        position="header"
        contributions={entries}
      />,
    );
    expect(screen.getByText('Restricted header')).toBeTruthy();
    view.rerender(
      <LayoutContributions
        initialState={state(denied)}
        position="header"
        contributions={entries}
      />,
    );
    expect(screen.queryByText('Restricted header')).toBeNull();
  });

  it('passes current identity and compact state only to the chosen position', () => {
    const Content = ({ currentUser, compact }: LayoutContext) => (
      <p>
        {currentUser.id}:{String(compact)}
      </p>
    );
    const entries = defineLayoutContributions([
      { id: 'header', position: 'header', component: Content },
      { id: 'footer', position: 'footer', component: Content },
    ]);
    const view = render(
      <LayoutContributions
        initialState={state(reader)}
        position="header"
        compact
        contributions={entries}
      />,
    );
    expect(screen.getAllByText('reader:true')).toHaveLength(1);
    view.rerender(
      <LayoutContributions
        initialState={state(reader)}
        position="header"
        contributions={entries}
      />,
    );
    expect(screen.getAllByText('reader:false')).toHaveLength(1);
    view.rerender(
      <LayoutContributions
        initialState={state(reader)}
        position="footer"
        compact
        contributions={entries}
      />,
    );
    expect(screen.getAllByText('reader:false')).toHaveLength(1);
    expect(screen.queryByTestId('mss-layout-contributions-header')).toBeNull();
    expect(screen.getByTestId('mss-layout-contributions-footer')).toBeTruthy();
  });

  it('supports memo and forwardRef components', () => {
    const entries = defineLayoutContributions([
      { id: 'memo', position: 'footer', component: memo(() => <p>Memo content</p>) },
      {
        id: 'forward',
        position: 'footer',
        component: forwardRef<HTMLDivElement, LayoutContext>(({ currentUser }, ref) => (
          <div ref={ref}>Forwarded {currentUser.id}</div>
        )),
      },
    ]);
    render(
      <LayoutContributions
        initialState={state(reader)}
        position="footer"
        contributions={entries}
      />,
    );
    expect(screen.getByText('Memo content')).toBeTruthy();
    expect(screen.getByText('Forwarded reader')).toBeTruthy();
  });

  it('defers lazy imports until identity, permission and position match', async () => {
    let finishLoading: ((value: { default: () => React.JSX.Element }) => void) | undefined;
    const load = vi.fn(
      () =>
        new Promise<{ default: () => React.JSX.Element }>((resolve) => {
          finishLoading = resolve;
        }),
    );
    const entries = defineLayoutContributions([
      { id: 'lazy', position: 'header', permission: 'example:read', component: lazy(load) },
      { id: 'ready', position: 'header', component: () => <p>Ready content</p> },
    ]);
    const view = render(<LayoutContributions position="header" contributions={entries} />);
    expect(load).not.toHaveBeenCalled();
    view.rerender(
      <LayoutContributions
        initialState={state(denied)}
        position="header"
        contributions={entries}
      />,
    );
    expect(load).not.toHaveBeenCalled();
    view.rerender(
      <LayoutContributions
        initialState={state(reader)}
        position="footer"
        contributions={entries}
      />,
    );
    expect(load).not.toHaveBeenCalled();
    view.rerender(
      <LayoutContributions
        initialState={state(reader)}
        position="header"
        contributions={entries}
      />,
    );
    expect(load).toHaveBeenCalledOnce();
    expect(screen.getByRole('status').textContent).toBe('navigation.customContentLoading');
    expect(screen.getByRole('status').getAttribute('aria-busy')).toBe('true');
    expect(screen.getByText('Ready content')).toBeTruthy();
    await act(async () => finishLoading?.({ default: () => <p>Lazy content</p> }));
    expect(await screen.findByText('Lazy content')).toBeTruthy();
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('isolates render failures without displaying upstream details', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const entries = defineLayoutContributions([
      {
        id: 'failed',
        position: 'header',
        component: () => {
          throw new Error('private upstream detail');
        },
      },
      { id: 'working', position: 'header', component: () => <p>Working content</p> },
    ]);
    render(
      <LayoutContributions
        initialState={state(reader)}
        position="header"
        contributions={entries}
      />,
    );
    expect(screen.getByRole('alert').textContent).toContain('navigation.customContentUnavailable');
    expect(screen.getByText('Working content')).toBeTruthy();
    expect(screen.queryByText('private upstream detail')).toBeNull();
  });

  it('isolates a rejected lazy import', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const entries = defineLayoutContributions([
      {
        id: 'failed',
        position: 'footer',
        component: lazy(async () => {
          throw new Error('private import failure');
        }),
      },
      { id: 'working', position: 'footer', component: () => <p>Working content</p> },
    ]);
    render(
      <LayoutContributions
        initialState={state(reader)}
        position="footer"
        contributions={entries}
      />,
    );
    expect(await screen.findByText('navigation.customContentUnavailable')).toBeTruthy();
    expect(screen.getByText('Working content')).toBeTruthy();
    expect(screen.queryByText('private import failure')).toBeNull();
  });

  it('resets local state across user, session and authorization changes and unmounts on logout', () => {
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
    const entries = defineLayoutContributions([
      { id: 'stateful', position: 'header', component: Stateful },
    ]);
    const props = { position: 'header' as const, contributions: entries };
    const view = render(<LayoutContributions {...props} initialState={state(reader)} />);
    const changedStates = [
      state({ ...reader, id: 'another-user' }),
      state({ ...reader, id: 'another-user' }, { authSessionId: 'session-two' }),
      state(
        { ...reader, id: 'another-user' },
        { authSessionId: 'session-two', authorizationVersion: 2 },
      ),
    ];
    for (const changed of changedStates) {
      fireEvent.click(screen.getByRole('button', { name: 'Count 0' }));
      expect(screen.getByRole('button', { name: 'Count 1' })).toBeTruthy();
      view.rerender(<LayoutContributions {...props} initialState={changed} />);
      expect(screen.getByRole('button', { name: 'Count 0' })).toBeTruthy();
    }
    expect(cleanupContent).toHaveBeenCalledTimes(3);
    view.rerender(<LayoutContributions {...props} initialState={state()} />);
    expect(cleanupContent).toHaveBeenCalledTimes(4);
    expect(screen.queryByRole('button')).toBeNull();
  });
});
