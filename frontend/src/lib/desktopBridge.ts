import { isDesktopRuntime } from './runtime';

export type DesktopWidgetDockState = {
  enabled: boolean;
  collapsed: boolean;
  edge: 'top' | 'right' | 'bottom' | 'left' | null;
};

const INACTIVE_DOCK_STATE: DesktopWidgetDockState = {
  enabled: false,
  collapsed: false,
  edge: null
};

async function invokeDesktop<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke } = await import('@tauri-apps/api/core');
  return invoke<T>(command, args);
}

export async function showDesktopMainWindow(route = '/'): Promise<void> {
  if (!isDesktopRuntime()) {
    window.location.assign(route);
    return;
  }
  await invokeDesktop('show_main_window', { route });
}

export async function hideDesktopWidgetWindow(): Promise<void> {
  if (!isDesktopRuntime()) {
    return;
  }
  await invokeDesktop('hide_widget_window');
}

export async function showDesktopWidgetWindow(): Promise<void> {
  if (!isDesktopRuntime()) {
    return;
  }
  await invokeDesktop('show_widget_window');
}

export async function startDesktopWidgetDragging(): Promise<DesktopWidgetDockState> {
  if (!isDesktopRuntime()) {
    return INACTIVE_DOCK_STATE;
  }
  return invokeDesktop<DesktopWidgetDockState>('start_widget_dragging');
}

export async function toggleDesktopWidgetAlwaysOnTop(): Promise<boolean> {
  if (!isDesktopRuntime()) {
    return false;
  }
  return invokeDesktop<boolean>('toggle_widget_always_on_top');
}

export async function getDesktopWidgetDockState(): Promise<DesktopWidgetDockState> {
  if (!isDesktopRuntime()) {
    return INACTIVE_DOCK_STATE;
  }
  return invokeDesktop<DesktopWidgetDockState>('get_widget_dock_state');
}

export async function toggleDesktopWidgetDock(): Promise<DesktopWidgetDockState> {
  if (!isDesktopRuntime()) {
    return INACTIVE_DOCK_STATE;
  }
  return invokeDesktop<DesktopWidgetDockState>('toggle_widget_dock');
}

export async function subscribeDesktopWidgetDockState(
  listener: (state: DesktopWidgetDockState) => void
): Promise<() => void> {
  if (!isDesktopRuntime()) {
    return () => undefined;
  }
  const { listen } = await import('@tauri-apps/api/event');
  return listen<DesktopWidgetDockState>('widget-dock-state-changed', (event) => listener(event.payload));
}
