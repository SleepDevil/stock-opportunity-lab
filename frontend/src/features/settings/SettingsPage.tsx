import { useEffect, useState } from 'react';
import { Badge, Button, Checkbox, Group, Paper, SimpleGrid, Stack, Switch, Text, TextInput, ThemeIcon } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from '@tanstack/react-router';
import { Mail, Send, Settings2 } from 'lucide-react';

import { ConfigPanel } from '../../components/ConfigPanel';
import { fetchNotificationSettings, saveNotificationSettings, sendTestNotification } from '../../lib/api';
import type { AppConfig } from '../../types/api';
import {
  boardOptions,
  defaultScreenPreferences,
  normalizeEmailInput,
  presetMainBoardOnly,
  sanitizeBoards,
  type ScreenPreferences
} from './settingsModel';

type SettingsPageProps = {
  screenPreferences: ScreenPreferences;
  setScreenPreferences: (value: ScreenPreferences) => void;
  userEmail: string;
  setUserEmail: (value: string) => void;
  config?: AppConfig;
  configLoading: boolean;
};

export function SettingsPage({
  screenPreferences,
  setScreenPreferences,
  userEmail,
  setUserEmail,
  config,
  configLoading
}: SettingsPageProps) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const notificationQuery = useQuery({
    queryKey: ['notification-settings', userEmail],
    queryFn: () => fetchNotificationSettings(userEmail || undefined)
  });
  const [notificationEmail, setNotificationEmail] = useState(normalizeEmailInput(userEmail));
  const saveNotificationMutation = useMutation({
    mutationFn: saveNotificationSettings,
    onSuccess: (result) => {
      const savedEmail = result.user_email ?? '';
      setNotificationEmail(normalizeEmailInput(savedEmail));
      setUserEmail(savedEmail);
      setScreenPreferences({
        boardExclusionEnabled: Boolean(result.board_exclusion_enabled),
        excludedBoards: sanitizeBoards(result.excluded_boards)
      });
      queryClient.setQueryData(['notification-settings', savedEmail], result);
      notifications.show({
        color: 'teal',
        title: '账户设置已保存',
        message: result.user_email ? `后续任务会按 ${result.user_email} 的偏好运行并通知。` : '请填写邮箱作为登录标识。'
      });
    },
    onError: (error) => {
      notifications.show({
        color: 'red',
        title: '账户设置保存失败',
        message: error instanceof Error ? error.message : '请检查邮箱格式'
      });
    }
  });
  const testNotificationMutation = useMutation({
    mutationFn: sendTestNotification,
    onSuccess: (result) => {
      notifications.show({
        color: result.ok ? 'teal' : 'orange',
        title: result.ok ? '测试通知已发送' : '测试通知未发送',
        message: result.message
      });
    },
    onError: (error) => {
      notifications.show({
        color: 'red',
        title: '测试通知失败',
        message: error instanceof Error ? error.message : '通知接口返回异常'
      });
    }
  });
  const activeLabels = boardOptions.filter((item) => screenPreferences.excludedBoards.includes(item.value)).map((item) => item.label);
  const requestPreview = screenPreferences.boardExclusionEnabled ? screenPreferences.excludedBoards : [];
  const effectiveNotificationEmail = normalizeEmailInput(userEmail || notificationEmail);

  useEffect(() => {
    if (!userEmail) {
      return;
    }
    setNotificationEmail(normalizeEmailInput(userEmail));
  }, [userEmail]);

  useEffect(() => {
    const data = notificationQuery.data;
    if (!data?.user_email) {
      return;
    }
    setNotificationEmail(normalizeEmailInput(data.user_email));
    setScreenPreferences({
      boardExclusionEnabled: Boolean(data.board_exclusion_enabled),
      excludedBoards: sanitizeBoards(data.excluded_boards)
    });
  }, [notificationQuery.data, setScreenPreferences]);

  function update(patch: Partial<ScreenPreferences>) {
    setScreenPreferences({
      ...screenPreferences,
      ...patch,
      excludedBoards: patch.excludedBoards ? sanitizeBoards(patch.excludedBoards) : screenPreferences.excludedBoards
    });
  }

  return (
    <Stack className="settings-page" gap="md">
      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md">
        <Paper className="settings-card" withBorder>
          <Group justify="space-between" align="flex-start" mb="md">
            <div>
              <Text fw={900}>账户权限过滤</Text>
              <Text size="sm" c="dimmed">控制扫描时是否排除暂时不可交易的市场板块。</Text>
            </div>
            <Badge color={screenPreferences.boardExclusionEnabled ? 'teal' : 'gray'} variant="light">
              {screenPreferences.boardExclusionEnabled ? '已启用' : '已关闭'}
            </Badge>
          </Group>

          <Switch
            label="启用板块排除"
            checked={screenPreferences.boardExclusionEnabled}
            onChange={(event) => update({ boardExclusionEnabled: event.currentTarget.checked })}
          />

          <Checkbox.Group
            mt="md"
            label="排除范围"
            description="双创由创业板和科创板组成；北交所单独控制。"
            value={screenPreferences.excludedBoards}
            onChange={(values) => update({ excludedBoards: values })}
          >
            <Stack gap="xs" mt="xs">
              {boardOptions.map((item) => (
                <div className={screenPreferences.boardExclusionEnabled ? 'board-option-card' : 'board-option-card disabled'} key={item.value}>
                  <Checkbox value={item.value} label={item.label} disabled={!screenPreferences.boardExclusionEnabled} />
                  <span>{item.detail}</span>
                </div>
              ))}
            </Stack>
          </Checkbox.Group>

          <Group gap="xs" mt="md">
            <Button size="xs" variant="light" color="teal" onClick={() => setScreenPreferences(presetMainBoardOnly)}>
              排除双创+北交所
            </Button>
            <Button size="xs" variant="light" color="blue" onClick={() => setScreenPreferences({ boardExclusionEnabled: true, excludedBoards: ['bse'] })}>
              只排除北交所
            </Button>
            <Button size="xs" variant="subtle" color="dark" onClick={() => setScreenPreferences(defaultScreenPreferences)}>
              清空排除
            </Button>
          </Group>
        </Paper>

        <Paper className="settings-card" withBorder>
          <Group justify="space-between" align="flex-start" mb="md">
            <div>
              <Text fw={900}>当前生效状态</Text>
              <Text size="sm" c="dimmed">下一次扫描会读取这里的设置。</Text>
            </div>
            <Button size="xs" color="dark" variant="filled" onClick={() => navigate({ to: '/' })}>
              回到扫描
            </Button>
          </Group>

          <div className="settings-preview">
            <span>板块过滤</span>
            <strong>{screenPreferences.boardExclusionEnabled ? (activeLabels.join(' / ') || '未选择板块') : '关闭'}</strong>
          </div>
          <div className="settings-preview">
            <span>请求参数</span>
            <code>{JSON.stringify({ exclude_boards: requestPreview })}</code>
          </div>
          <div className="settings-preview">
            <span>报告影响</span>
            <strong>{screenPreferences.boardExclusionEnabled ? '新扫描报告按设置落盘' : '新扫描报告不做板块排除'}</strong>
          </div>
        </Paper>
      </SimpleGrid>

      <Paper className="settings-card" withBorder>
        <Group justify="space-between" align="flex-start" mb="md">
          <div>
            <Text fw={900}>账户邮箱与通知</Text>
            <Text size="sm" c="dimmed">邮箱作为当前配置的简单登录标识，也用于后台任务完成后的飞书通知。</Text>
          </div>
          <Badge color={userEmail ? 'teal' : 'gray'} variant="light">
            {userEmail ? '已登录' : '未登录'}
          </Badge>
        </Group>
        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="sm">
          <TextInput
            label="通知邮箱"
            placeholder="name@example.com"
            value={notificationEmail}
            leftSection={<Mail size={15} />}
            disabled={notificationQuery.isLoading}
            onChange={(event) => setNotificationEmail(event.currentTarget.value)}
          />
          <div className="notification-actions">
            <Button
              color="dark"
              variant="filled"
              leftSection={<Settings2 size={16} />}
              loading={saveNotificationMutation.isPending}
              disabled={!normalizeEmailInput(notificationEmail)}
              onClick={() => saveNotificationMutation.mutate({
                user_email: normalizeEmailInput(notificationEmail),
                board_exclusion_enabled: screenPreferences.boardExclusionEnabled,
                excluded_boards: requestPreview
              })}
            >
              保存账户设置
            </Button>
            <Button
              variant="light"
              color="teal"
              leftSection={<Send size={16} />}
              loading={testNotificationMutation.isPending}
              disabled={!effectiveNotificationEmail}
              onClick={() => testNotificationMutation.mutate(effectiveNotificationEmail)}
            >
              发送测试
            </Button>
          </div>
        </SimpleGrid>
      </Paper>

      <Paper className="settings-card" withBorder>
        <Group justify="space-between" align="flex-start" mb="md">
          <div>
            <Text fw={900}>策略参数快照</Text>
            <Text size="sm" c="dimmed">这里展示后端当前数值过滤和仓位参数，板块过滤由上方账户权限过滤控制。</Text>
          </div>
          <ThemeIcon color="dark" variant="light"><Settings2 size={18} /></ThemeIcon>
        </Group>
        {configLoading ? <Text size="sm" c="dimmed">正在加载策略参数...</Text> : <ConfigPanel config={config} />}
      </Paper>
    </Stack>
  );
}
