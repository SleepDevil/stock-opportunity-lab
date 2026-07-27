import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Button, Tooltip } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Download, LoaderCircle, RotateCcw } from 'lucide-react';
import type { DownloadEvent, Update } from '@tauri-apps/plugin-updater';

import { isDesktopRuntime } from '../../lib/runtime';

const CHECK_FOR_UPDATES_EVENT = 'app-check-for-updates';
const BACKGROUND_CHECK_DELAY_MS = 3_000;
const BACKGROUND_CHECK_INTERVAL_MS = 4 * 60 * 60 * 1_000;
const UPDATE_REQUEST_TIMEOUT_MS = 30_000;

type DesktopUpdatePhase = 'idle' | 'checking' | 'available' | 'downloading' | 'ready';

type DesktopUpdateRelease = {
  version: string;
  currentVersion: string;
  notes?: string;
};

type DesktopUpdateContextValue = {
  phase: DesktopUpdatePhase;
  release: DesktopUpdateRelease | null;
  progress: number | null;
  checkForUpdates: (manual?: boolean) => Promise<void>;
  installUpdate: () => Promise<void>;
  restartApp: () => Promise<void>;
};

const INACTIVE_UPDATE_CONTEXT: DesktopUpdateContextValue = {
  phase: 'idle',
  release: null,
  progress: null,
  checkForUpdates: async () => undefined,
  installUpdate: async () => undefined,
  restartApp: async () => undefined
};

const DesktopUpdateContext = createContext<DesktopUpdateContextValue>(INACTIVE_UPDATE_CONTEXT);

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isMainDesktopWindow(): boolean {
  return isDesktopRuntime() && !/\/desktop-widget\/?$/.test(window.location.pathname);
}

export function DesktopUpdateProvider({ children }: { children: ReactNode }) {
  const enabled = isMainDesktopWindow();
  const pendingUpdateRef = useRef<Update | null>(null);
  const checkInFlightRef = useRef<Promise<void> | null>(null);
  const installInFlightRef = useRef(false);
  const [phase, setPhase] = useState<DesktopUpdatePhase>('idle');
  const [release, setRelease] = useState<DesktopUpdateRelease | null>(null);
  const [progress, setProgress] = useState<number | null>(null);

  const checkForUpdates = useCallback(async (manual = false) => {
    if (!enabled) {
      return;
    }

    if (pendingUpdateRef.current) {
      if (manual) {
        notifications.show({
          color: 'orange',
          title: `新版本 v${pendingUpdateRef.current.version} 已可用`,
          message: '点击主窗口右上角的更新按钮即可下载并安装。'
        });
      }
      return;
    }

    if (checkInFlightRef.current) {
      if (manual) {
        notifications.show({
          color: 'blue',
          title: '正在检查更新',
          message: '版本服务器正在响应，请稍候。'
        });
      }
      return checkInFlightRef.current;
    }

    const request = (async () => {
      setPhase('checking');
      if (manual) {
        notifications.show({
          color: 'blue',
          title: '正在检查更新',
          message: '正在向版本服务器查询最新版本。',
          autoClose: 1_800
        });
      }

      try {
        const { check } = await import('@tauri-apps/plugin-updater');
        const update = await check({ timeout: UPDATE_REQUEST_TIMEOUT_MS });

        if (!update) {
          setPhase('idle');
          if (manual) {
            const { getVersion } = await import('@tauri-apps/api/app');
            const currentVersion = await getVersion();
            notifications.show({
              color: 'teal',
              title: '已是最新版本',
              message: `当前版本 v${currentVersion}，暂无可用更新。`
            });
          }
          return;
        }

        pendingUpdateRef.current = update;
        setRelease({
          version: update.version,
          currentVersion: update.currentVersion,
          notes: update.body
        });
        setPhase('available');
        notifications.show({
          color: 'orange',
          title: `发现新版本 v${update.version}`,
          message: '更新按钮已显示在主窗口右上角，可在方便时安装。',
          autoClose: 8_000
        });
      } catch (error) {
        setPhase('idle');
        if (manual) {
          notifications.show({
            color: 'red',
            title: '检查更新失败',
            message: errorMessage(error)
          });
        } else {
          console.warn('Background update check failed:', error);
        }
      }
    })();

    checkInFlightRef.current = request;
    try {
      await request;
    } finally {
      checkInFlightRef.current = null;
    }
  }, [enabled]);

  const installUpdate = useCallback(async () => {
    const update = pendingUpdateRef.current;
    if (!update || installInFlightRef.current || phase === 'downloading') {
      return;
    }

    installInFlightRef.current = true;
    setPhase('downloading');
    setProgress(0);
    let downloadedBytes = 0;
    let totalBytes: number | undefined;

    try {
      await update.downloadAndInstall((event: DownloadEvent) => {
        if (event.event === 'Started') {
          totalBytes = event.data.contentLength;
          downloadedBytes = 0;
          setProgress(totalBytes ? 0 : null);
          return;
        }
        if (event.event === 'Progress') {
          downloadedBytes += event.data.chunkLength;
          setProgress(totalBytes ? Math.min(100, Math.round(downloadedBytes / totalBytes * 100)) : null);
          return;
        }
        setProgress(100);
      }, { timeout: 10 * 60 * 1_000 });

      setPhase('ready');
      notifications.show({
        color: 'teal',
        title: `v${update.version} 已安装`,
        message: '点击“重启完成更新”即可切换到新版本。',
        autoClose: false
      });
    } catch (error) {
      setPhase('available');
      setProgress(null);
      notifications.show({
        color: 'red',
        title: '更新安装失败',
        message: `${errorMessage(error)}。可以稍后点击更新按钮重试。`
      });
    } finally {
      installInFlightRef.current = false;
    }
  }, [phase]);

  const restartApp = useCallback(async () => {
    if (!enabled) {
      return;
    }
    try {
      const { relaunch } = await import('@tauri-apps/plugin-process');
      await relaunch();
    } catch (error) {
      notifications.show({
        color: 'red',
        title: '自动重启失败',
        message: `${errorMessage(error)}。请手动退出并重新打开客户端。`
      });
    }
  }, [enabled]);

  useEffect(() => {
    if (!enabled) {
      return undefined;
    }

    let unlisten: (() => void) | undefined;
    let disposed = false;
    void import('@tauri-apps/api/event')
      .then(({ listen }) => listen(CHECK_FOR_UPDATES_EVENT, () => void checkForUpdates(true)))
      .then((stopListening) => {
        if (disposed) {
          stopListening();
        } else {
          unlisten = stopListening;
        }
      })
      .catch((error) => console.warn('Failed to listen for update menu events:', error));

    const initialCheck = import.meta.env.PROD
      ? window.setTimeout(() => void checkForUpdates(false), BACKGROUND_CHECK_DELAY_MS)
      : undefined;
    const periodicCheck = import.meta.env.PROD
      ? window.setInterval(() => void checkForUpdates(false), BACKGROUND_CHECK_INTERVAL_MS)
      : undefined;

    return () => {
      disposed = true;
      if (initialCheck != null) {
        window.clearTimeout(initialCheck);
      }
      if (periodicCheck != null) {
        window.clearInterval(periodicCheck);
      }
      unlisten?.();
    };
  }, [checkForUpdates, enabled]);

  const value = useMemo<DesktopUpdateContextValue>(() => ({
    phase,
    release,
    progress,
    checkForUpdates,
    installUpdate,
    restartApp
  }), [checkForUpdates, installUpdate, phase, progress, release, restartApp]);

  return <DesktopUpdateContext.Provider value={value}>{children}</DesktopUpdateContext.Provider>;
}

export function useDesktopUpdate(): DesktopUpdateContextValue {
  return useContext(DesktopUpdateContext);
}

export function DesktopUpdateButton() {
  const { phase, release, progress, installUpdate, restartApp } = useDesktopUpdate();
  if (!release || !['available', 'downloading', 'ready'].includes(phase)) {
    return null;
  }

  const downloading = phase === 'downloading';
  const ready = phase === 'ready';
  const label = ready
    ? '重启完成更新'
    : downloading
      ? progress == null ? '正在下载更新' : `正在下载 ${progress}%`
      : `更新至 v${release.version}`;
  const Icon = ready ? RotateCcw : downloading ? LoaderCircle : Download;

  return (
    <Tooltip label={ready ? `重启并启用 v${release.version}` : `从 v${release.currentVersion} 更新到 v${release.version}`}>
      <Button
        className="desktop-update-button"
        color="orange"
        variant={ready ? 'filled' : 'light'}
        leftSection={<Icon className={downloading ? 'desktop-update-icon is-spinning' : 'desktop-update-icon'} size={16} />}
        disabled={downloading}
        onClick={() => void (ready ? restartApp() : installUpdate())}
      >
        {label}
      </Button>
    </Tooltip>
  );
}
