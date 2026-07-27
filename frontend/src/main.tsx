import { StrictMode, useEffect, useState, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { Button, Center, Loader, MantineProvider, Paper, Stack, Text, Title, createTheme } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from '@tanstack/react-router';
import '@mantine/core/styles.css';
import '@mantine/dates/styles.css';
import '@mantine/notifications/styles.css';
import 'dayjs/locale/zh-cn';

import { router } from './App';
import { DesktopUpdateProvider } from './features/desktop/DesktopUpdate';
import { isDesktopRuntime, waitForDesktopBackend } from './lib/runtime';

const theme = createTheme({
  fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  primaryColor: 'blue',
  defaultRadius: 'md',
  headings: {
    fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
  }
});

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false
    }
  }
});

function DesktopBootstrap({ children }: { children: ReactNode }) {
  const desktop = isDesktopRuntime();
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<'checking' | 'ready' | 'error'>(desktop ? 'checking' : 'ready');
  const [message, setMessage] = useState('正在连接行情与策略服务...');

  useEffect(() => {
    if (!desktop) {
      return;
    }
    let active = true;
    setStatus('checking');
    setMessage('正在连接行情与策略服务...');
    void waitForDesktopBackend()
      .then(() => {
        if (active) {
          setStatus('ready');
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setMessage(error instanceof Error ? error.message : String(error));
          setStatus('error');
        }
      });
    return () => {
      active = false;
    };
  }, [attempt, desktop]);

  if (status === 'ready') {
    return children;
  }

  return (
    <Center mih="100vh" p="xl" bg="gray.0">
      <Paper withBorder radius="md" p="xl" maw={520} w="100%">
        <Stack gap="md" align="flex-start">
          {status === 'checking' ? <Loader size="sm" /> : null}
          <Title order={2} size="h3">Stock Opportunity Lab</Title>
          <Text c="dimmed">{message}</Text>
          {status === 'error' ? (
            <Button onClick={() => setAttempt((value) => value + 1)}>重新连接</Button>
          ) : null}
        </Stack>
      </Paper>
    </Center>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <MantineProvider defaultColorScheme="light" theme={theme}>
        <Notifications position="top-right" />
        <DesktopUpdateProvider>
          <DesktopBootstrap>
            <RouterProvider router={router} />
          </DesktopBootstrap>
        </DesktopUpdateProvider>
      </MantineProvider>
    </QueryClientProvider>
  </StrictMode>
);
