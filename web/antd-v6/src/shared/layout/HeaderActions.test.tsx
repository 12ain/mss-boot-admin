import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { ConfigProvider, DatePicker, Modal, Select, TimePicker } from 'antd';
import dayjs from 'dayjs';
import { type ReactNode, useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { InitialState } from '../auth/types';
import { defineAvatarContributions } from '../avatar/contract';
import { AvatarMenu } from './HeaderActions';

const session = vi.hoisted(() => ({
  clear: vi.fn(),
  clearIdentity: vi.fn(() => 'session-a'),
  clearServer: vi.fn(async () => undefined),
  clearTheme: vi.fn(),
  publish: vi.fn(),
  replace: vi.fn(),
}));
vi.mock('@umijs/max', () => ({
  history: { replace: session.replace },
  Link: ({ to, children }: { to: string; children: ReactNode }) => <a href={to}>{children}</a>,
  useIntl: () => ({ formatMessage: ({ id }: { id: string }) => id }),
}));
vi.mock('../navigation/HeaderNotice', () => ({ default: () => null }));
vi.mock('../navigation/LocaleSwitcher', () => ({ default: () => null }));
vi.mock('../navigation/MenuSearch', () => ({ default: () => null }));
vi.mock('../auth/session', () => ({ clearServerSession: session.clearServer }));
vi.mock('../query/client', () => ({ queryClient: { clear: session.clear } }));
vi.mock('../theme/runtime', () => ({ clearUserThemeRuntime: session.clearTheme }));
vi.mock('../theme/snapshot', () => ({ clearThemeIdentitySession: session.clearIdentity }));
vi.mock('../theme/sync', () => ({ publishThemeIdentityCleared: session.publish }));

const initialState: InitialState = {
  currentUser: { id: 'reader', name: 'Reader', permissions: {} },
  authSessionId: 'session-a',
  settings: {},
  authorizedMenu: [],
  fetchCurrentUser: async () => undefined,
};

const contributions = defineAvatarContributions([
  {
    id: 'example',
    component: ({ close, currentUser, open }) => {
      const [count, setCount] = useState(0);
      return (
        <>
          <p>
            {currentUser.id}:{String(open)}
          </p>
          <input aria-label="Custom note" />
          <button type="button" onClick={() => setCount(count + 1)}>
            Count {count}
          </button>
          <button type="button" onClick={close}>
            Close panel
          </button>
        </>
      );
    },
  },
]);

afterEach(cleanup);

describe('shared avatar panel', () => {
  it('retains the official menu and complete logout cleanup with no registration', async () => {
    render(<AvatarMenu initialState={initialState} />);
    const trigger = screen.getByRole('button', { name: 'navigation.accountMenu' });
    expect(trigger.getAttribute('aria-haspopup')).toBe('menu');
    fireEvent.click(trigger);
    expect(
      (await screen.findByRole('link', { name: 'menu.account-center' })).getAttribute('href'),
    ).toBe('/account/center');
    expect(screen.getByRole('link', { name: 'menu.account-settings' }).getAttribute('href')).toBe(
      '/account/settings',
    );
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.click(screen.getByText('menu.logout'));
    await waitFor(() => expect(session.replace).toHaveBeenCalledWith('/user/login'));
    expect(session.clearIdentity).toHaveBeenCalledWith({
      broadcast: false,
      expectedSessionId: 'session-a',
    });
    expect(session.clear).toHaveBeenCalledOnce();
    expect(session.clearTheme).toHaveBeenCalledOnce();
    expect(session.clearServer).toHaveBeenCalledOnce();
    await waitFor(() => expect(session.publish).toHaveBeenCalledWith('session-a'));
  });

  it.each([false, true])(
    'keeps custom controls interactive in the shared panel (compact=%s)',
    async (compact) => {
      render(
        <AvatarMenu compact={compact} contributions={contributions} initialState={initialState} />,
      );
      const trigger = screen.getByRole('button', { name: 'navigation.accountMenu' });
      expect(trigger.getAttribute('aria-expanded')).toBe('false');
      expect(screen.queryByRole('textbox')).toBeNull();
      fireEvent.click(trigger);
      const input = await screen.findByRole('textbox', { name: 'Custom note' });
      expect(screen.getByRole('dialog').contains(input)).toBe(true);
      expect(screen.getByRole('dialog').contains(screen.getByText('menu.logout'))).toBe(true);
      fireEvent.change(input, { target: { value: 'owned content' } });
      fireEvent.click(screen.getByRole('button', { name: 'Count 0' }));
      expect(screen.getByRole('button', { name: 'Count 1' })).toBeTruthy();
      expect(trigger.getAttribute('aria-expanded')).toBe('true');
      fireEvent.keyDown(input, { key: 'Tab', keyCode: 9 });
      expect(trigger.getAttribute('aria-expanded')).toBe('true');
      fireEvent.click(screen.getByRole('button', { name: 'Close panel' }));
      await waitFor(() => expect(screen.queryByRole('textbox')).toBeNull());
      expect(document.activeElement).toBe(trigger);
      fireEvent.click(trigger);
      expect(await screen.findByRole('button', { name: 'Count 0' })).toBeTruthy();
    },
  );

  it('supports arrow opening, Escape dismissal and outside focus without stealing it', async () => {
    render(
      <>
        <AvatarMenu contributions={contributions} initialState={initialState} />
        <button type="button">Outside</button>
      </>,
    );
    const trigger = screen.getByRole('button', { name: 'navigation.accountMenu' });
    fireEvent.keyDown(trigger, { key: 'ArrowDown', keyCode: 40 });
    const input = await screen.findByRole('textbox');
    fireEvent.keyDown(input, { key: 'Escape', keyCode: 27 });
    await waitFor(() => expect(screen.queryByRole('textbox')).toBeNull());
    expect(document.activeElement).toBe(trigger);
    fireEvent.click(trigger);
    const reopened = await screen.findByRole('textbox');
    reopened.focus();
    const outside = screen.getByRole('button', { name: 'Outside' });
    outside.focus();
    await waitFor(() => expect(trigger.getAttribute('aria-expanded')).toBe('false'));
    expect(document.activeElement).toBe(outside);
  });

  it('closes and resets the panel when identity or session changes', async () => {
    const view = render(<AvatarMenu contributions={contributions} initialState={initialState} />);
    fireEvent.click(screen.getByRole('button', { name: 'navigation.accountMenu' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Count 0' }));
    view.rerender(
      <AvatarMenu
        contributions={contributions}
        initialState={{ ...initialState, authSessionId: 'session-b' }}
      />,
    );
    await waitFor(() => expect(screen.queryByRole('textbox')).toBeNull());
    fireEvent.click(screen.getByRole('button', { name: 'navigation.accountMenu' }));
    expect(await screen.findByRole('button', { name: 'Count 0' })).toBeTruthy();
    view.rerender(
      <AvatarMenu
        contributions={contributions}
        initialState={{ ...initialState, currentUser: undefined }}
      />,
    );
    await waitFor(() => expect(screen.queryByRole('textbox')).toBeNull());
  });

  it('keeps a host modal portal interactive when focus leaves the popup DOM', async () => {
    const portalEntries = defineAvatarContributions([
      {
        id: 'modal',
        component: () => {
          const [shown, setShown] = useState(false);
          return (
            <>
              <button type="button" onClick={() => setShown(true)}>
                Open host modal
              </button>
              <Modal
                open={shown}
                title="Host modal"
                onCancel={() => setShown(false)}
                onOk={() => setShown(false)}
                destroyOnHidden
                transitionName=""
                maskTransitionName=""
              >
                <input aria-label="Modal note" />
              </Modal>
            </>
          );
        },
      },
    ]);
    render(<AvatarMenu contributions={portalEntries} initialState={initialState} />);
    const trigger = screen.getByRole('button', { name: 'navigation.accountMenu' });
    fireEvent.click(trigger);
    const panel = await screen.findByTestId('mss-avatar-panel');
    await waitFor(() => expect(document.activeElement).toBe(panel));
    fireEvent.click(screen.getByRole('button', { name: 'Open host modal' }));
    const input = await screen.findByRole('textbox', { name: 'Modal note' });
    expect(panel.contains(input)).toBe(false);
    act(() => input.focus());
    fireEvent.pointerDown(input);
    fireEvent.mouseDown(input);
    fireEvent.click(input);
    await waitFor(() => expect(trigger.getAttribute('aria-expanded')).toBe('true'));
    expect(screen.getByRole('textbox', { name: 'Modal note' })).toBe(input);
    fireEvent.click(screen.getByRole('button', { name: 'OK' }));
    await waitFor(() => expect(screen.queryByRole('textbox', { name: 'Modal note' })).toBeNull());
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'Open host modal' }));
    const reopened = await screen.findByRole('textbox', { name: 'Modal note' });
    act(() => reopened.focus());
    fireEvent.keyDown(reopened, { key: 'Escape', keyCode: 27 });
    await waitFor(() => expect(screen.queryByRole('textbox', { name: 'Modal note' })).toBeNull());
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    fireEvent.keyDown(panel, { key: 'Escape', keyCode: 27 });
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Open host modal' })).toBeNull(),
    );
    expect(document.activeElement).toBe(trigger);
  });

  it.each(['date', 'time'] as const)(
    'lets a nested %s input close its popup before Escape closes the avatar panel',
    async (kind) => {
      const onOpenChange = vi.fn();
      const Picker = kind === 'date' ? DatePicker : TimePicker;
      const entries = defineAvatarContributions([
        {
          id: 'picker-form',
          component: () => (
            <>
              <input aria-label="Draft note" />
              <Picker
                aria-label="Nested picker"
                onOpenChange={onOpenChange}
                classNames={() => ({ popup: { root: 'explicit-popup' } })}
                suffixIcon={<span>Explicit picker icon</span>}
              />
            </>
          ),
        },
      ]);
      const inheritedClasses = { root: 'inherited-picker', popup: { root: 'inherited-popup' } };
      render(
        <ConfigProvider
          datePicker={{
            classNames: () => inheritedClasses,
            suffixIcon: <span>Inherited picker icon</span>,
          }}
          timePicker={{
            classNames: inheritedClasses,
            suffixIcon: <span>Inherited picker icon</span>,
          }}
        >
          <AvatarMenu contributions={entries} initialState={initialState} />
        </ConfigProvider>,
      );
      const trigger = screen.getByRole('button', { name: 'navigation.accountMenu' });
      fireEvent.click(trigger);
      const panel = await screen.findByTestId('mss-avatar-panel');
      await waitFor(() => expect(document.activeElement).toBe(panel));
      const note = screen.getByRole('textbox', { name: 'Draft note' });
      fireEvent.change(note, { target: { value: 'Keep this draft' } });
      const input = screen.getByRole('textbox', { name: 'Nested picker' });
      expect(panel.getElementsByClassName('inherited-picker')[0]?.contains(input)).toBe(true);
      expect(screen.getByText('Explicit picker icon')).toBeTruthy();
      expect(screen.queryByText('Inherited picker icon')).toBeNull();
      act(() => input.focus());
      fireEvent.click(input);
      await waitFor(() => expect(onOpenChange).toHaveBeenLastCalledWith(true));
      const nestedPopup = document.getElementsByClassName('explicit-popup')[0];
      if (!(nestedPopup instanceof HTMLElement)) throw new Error('Picker popup did not open');
      expect(nestedPopup.classList.contains('inherited-popup')).toBe(true);
      fireEvent.keyDown(input, { key: 'Escape', keyCode: 27 });
      await waitFor(() => expect(onOpenChange).toHaveBeenLastCalledWith(false));
      // Closing popups disable interaction immediately, before their exit animation ends.
      await waitFor(() => expect(nestedPopup.style.pointerEvents).toBe('none'));
      expect(trigger.getAttribute('aria-expanded')).toBe('true');
      expect(screen.getByRole('textbox', { name: 'Draft note' })).toBe(note);
      expect((note as HTMLInputElement).value).toBe('Keep this draft');
      expect(document.activeElement).toBe(input);
      fireEvent.keyDown(input, { key: 'Escape', keyCode: 27 });
      await waitFor(() => expect(screen.queryByRole('textbox', { name: 'Draft note' })).toBeNull());
      expect(document.activeElement).toBe(trigger);
    },
  );

  it.each(['select', 'date'] as const)(
    'keeps host %s popup selection inside the panel lifecycle',
    async (kind) => {
      const entries = defineAvatarContributions([
        {
          id: 'popup-control',
          component: () =>
            kind === 'select' ? (
              <Select
                aria-label="Host choice"
                defaultOpen
                options={[{ value: 'first', label: 'First choice' }]}
                virtual={false}
              />
            ) : (
              <DatePicker
                aria-label="Host date"
                defaultOpen
                defaultPickerValue={dayjs('2026-10-04')}
              />
            ),
        },
      ]);
      render(<AvatarMenu contributions={entries} initialState={initialState} />);
      const trigger = screen.getByRole('button', { name: 'navigation.accountMenu' });
      fireEvent.click(trigger);
      const panel = await screen.findByTestId('mss-avatar-panel');
      const choice =
        kind === 'select'
          ? await screen.findByRole('option', { name: 'First choice' })
          : await screen.findByTitle('2026-10-05');
      expect(panel.contains(choice)).toBe(false);
      fireEvent.pointerDown(choice);
      fireEvent.mouseDown(choice);
      fireEvent.click(choice);
      await waitFor(() => expect(trigger.getAttribute('aria-expanded')).toBe('true'));
      if (kind === 'select') {
        expect(within(panel).getByTitle('First choice')).toBeTruthy();
      } else {
        expect((screen.getByRole('textbox', { name: 'Host date' }) as HTMLInputElement).value).toBe(
          '2026-10-05',
        );
      }
    },
  );
});
