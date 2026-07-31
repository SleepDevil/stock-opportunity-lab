import { useEffect, useState } from 'react';
import { Badge, Button, Checkbox, Group, Paper, SimpleGrid, Stack, Switch, Text, TextInput, ThemeIcon } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from '@tanstack/react-router';
import { Bot, Link2, Mail, MessageSquareText, Send, Settings2 } from 'lucide-react';

import { ConfigPanel } from '../../components/ConfigPanel';
import {
  fetchNotificationSettings,
  fetchServerWatchlist,
  saveNotificationSettings,
  saveServerWatchlist,
  sendTestNotification
} from '../../lib/api';
import { isDesktopRuntime } from '../../lib/runtime';
import type { AppConfig, NotificationSettings } from '../../types/api';
import {
  readDesktopWatchlist
} from '../desktop/desktopWatchlist';
import {
  normalizeDesktopWatchlist,
  type DesktopWatchStock
} from '../desktop/desktopWidgetModel';
import { generateWebWatchlistCommentary } from '../watchlist/watchlistCommentary';
import { WatchlistCommentaryPreview } from '../watchlist/WatchlistCommentaryPreview';
import { WebWatchlistEditor } from '../watchlist/WebWatchlistEditor';
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
  const desktopRuntime = isDesktopRuntime();
  const [notificationEmail, setNotificationEmail] = useState(normalizeEmailInput(userEmail));
  const [watchlistFeishuEnabled, setWatchlistFeishuEnabled] = useState(false);
  const [watchlistFeishuChatId, setWatchlistFeishuChatId] = useState('');
  const [watchlistPlatformUrl, setWatchlistPlatformUrl] = useState('');
  const [watchlist, setWatchlist] = useState<DesktopWatchStock[]>(readDesktopWatchlist);
  const savedAccountEmail = normalizeEmailInput(userEmail);
  const effectiveNotificationEmail = normalizeEmailInput(userEmail || notificationEmail);
  const notificationQuery = useQuery({
    queryKey: ['notification-settings', userEmail],
    queryFn: () => fetchNotificationSettings(userEmail || undefined)
  });
  const watchlistQuery = useQuery({
    queryKey: ['server-watchlist', savedAccountEmail],
    queryFn: () => fetchServerWatchlist(savedAccountEmail),
    enabled: !desktopRuntime && Boolean(savedAccountEmail),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false
  });
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
        title: '设置已保存',
        message: result.watchlist_commentary_feishu_enabled
          ? `自选锐评会推送到群 ${result.watchlist_commentary_feishu_chat_id}。`
          : `后续任务会按 ${result.user_email} 的偏好运行。`
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
  const saveWatchlistSubscriptionMutation = useMutation({
    mutationFn: async () => {
      const settings = await saveNotificationSettings(notificationSettingsPayload());
      const email = normalizeEmailInput(settings.user_email ?? notificationEmail);
      if (!email) {
        throw new Error('请先填写邮箱作为登录标识');
      }
      const savedWatchlist = await saveServerWatchlist({
        user_email: email,
        stocks: normalizeDesktopWatchlist(watchlist)
      });
      return { settings, savedWatchlist };
    },
    onSuccess: ({ settings, savedWatchlist }) => {
      const savedEmail = settings.user_email ?? '';
      setNotificationEmail(normalizeEmailInput(savedEmail));
      setUserEmail(savedEmail);
      setScreenPreferences({
        boardExclusionEnabled: Boolean(settings.board_exclusion_enabled),
        excludedBoards: sanitizeBoards(settings.excluded_boards)
      });
      setWatchlist(normalizeDesktopWatchlist(savedWatchlist.stocks));
      queryClient.setQueryData(['notification-settings', savedEmail], settings);
      queryClient.setQueryData(['server-watchlist', normalizeEmailInput(savedEmail)], savedWatchlist);
      notifications.show({
        color: 'teal',
        title: '自选与群订阅已保存',
        message: watchlistFeishuEnabled
          ? `服务端定时器会按 ${savedWatchlist.stocks.length} 只自选推送到群聊。`
          : '自选名单已持久化到服务端，自动群推送保持关闭。'
      });
    },
    onError: (error) => {
      notifications.show({
        color: 'red',
        title: '自选订阅保存失败',
        message: error instanceof Error ? error.message : '请检查自选名单、邮箱与群订阅配置'
      });
    }
  });
  const manualWatchlistNotificationMutation = useMutation({
    mutationFn: (email: string) => generateWebWatchlistCommentary({
      watchlist,
      userEmail: email,
      manual: true
    }),
    onSuccess: (result) => {
      notifications.show({
        color: result.delivery.status === 'sent' ? 'teal' : 'orange',
        title: result.delivery.status === 'sent' ? '真实自选锐评已发送' : '锐评已生成，但未推送',
        message: `${result.title} · ${result.delivery.message}`
      });
    },
    onError: (error) => {
      notifications.show({
        color: 'red',
        title: '真实锐评发送失败',
        message: error instanceof Error ? error.message : '请检查自选行情、订阅配置与机器人权限'
      });
    }
  });
  const activeLabels = boardOptions.filter((item) => screenPreferences.excludedBoards.includes(item.value)).map((item) => item.label);
  const requestPreview = screenPreferences.boardExclusionEnabled ? screenPreferences.excludedBoards : [];
  const aiConfigured = Boolean(config?.ai?.configured);
  const aiModelLabel = config?.ai?.model || (config?.ai?.provider === 'external_command' ? '外部 AI' : '智谱 GLM');
  const savedWatchlistConfigMatches = Boolean(
    notificationQuery.data?.user_email === effectiveNotificationEmail
    && Boolean(notificationQuery.data.watchlist_commentary_feishu_enabled) === watchlistFeishuEnabled
    && (notificationQuery.data.watchlist_commentary_feishu_chat_id ?? '') === watchlistFeishuChatId.trim()
    && (notificationQuery.data.watchlist_commentary_platform_url ?? '') === watchlistPlatformUrl.trim()
  );
  const serverWatchlistKey = normalizeDesktopWatchlist(watchlistQuery.data?.stocks ?? [])
    .map((stock) => `${stock.code}:${stock.name}`)
    .join('|');
  const currentWatchlistKey = normalizeDesktopWatchlist(watchlist)
    .map((stock) => `${stock.code}:${stock.name}`)
    .join('|');
  const savedWatchlistMatches = Boolean(
    watchlistQuery.data
    && watchlistQuery.data.user_email === effectiveNotificationEmail
    && serverWatchlistKey === currentWatchlistKey
  );

  useEffect(() => {
    if (!userEmail) {
      return;
    }
    setNotificationEmail(normalizeEmailInput(userEmail));
  }, [userEmail]);

  useEffect(() => {
    if (!watchlistQuery.data) {
      return;
    }
    setWatchlist(normalizeDesktopWatchlist(watchlistQuery.data.stocks));
  }, [watchlistQuery.data]);

  useEffect(() => {
    const data = notificationQuery.data;
    if (!data) {
      return;
    }
    setWatchlistFeishuEnabled(Boolean(data.watchlist_commentary_feishu_enabled));
    setWatchlistFeishuChatId(data.watchlist_commentary_feishu_chat_id ?? '');
    setWatchlistPlatformUrl(data.watchlist_commentary_platform_url ?? '');
    if (!data.user_email) return;
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

  function notificationSettingsPayload(): NotificationSettings {
    return {
      user_email: normalizeEmailInput(notificationEmail),
      board_exclusion_enabled: screenPreferences.boardExclusionEnabled,
      excluded_boards: requestPreview,
      watchlist_commentary_feishu_enabled: watchlistFeishuEnabled,
      watchlist_commentary_feishu_chat_id: watchlistFeishuChatId.trim() || null,
      watchlist_commentary_platform_url: watchlistPlatformUrl.trim() || null
    };
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
              disabled={notificationQuery.isLoading || !normalizeEmailInput(notificationEmail)}
              onClick={() => saveNotificationMutation.mutate(notificationSettingsPayload())}
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

      {!desktopRuntime ? (
      <Paper className="settings-card watchlist-feishu-settings" withBorder>
        <Group justify="space-between" align="flex-start" mb="md">
          <Group gap="sm" align="flex-start" wrap="nowrap">
            <ThemeIcon color="teal" variant="light" size="lg"><Bot size={19} /></ThemeIcon>
            <div>
              <Text fw={900}>自选锐评群订阅</Text>
              <Text size="sm" c="dimmed">在 Web 工作台维护自选、生成锐评，并以飞书 Card 2.0 推送到指定群聊。</Text>
            </div>
          </Group>
          <Group gap="xs">
            <Badge color={aiConfigured ? 'violet' : 'orange'} variant="light">
              {configLoading ? '检测模型配置' : aiConfigured ? `${aiModelLabel} 已接入` : '规则兜底'}
            </Badge>
            <Badge color={watchlistFeishuEnabled ? 'teal' : 'gray'} variant="light">
              {watchlistFeishuEnabled ? '自动推送' : '仅本地展示'}
            </Badge>
            <Badge color={savedWatchlistMatches ? 'blue' : 'orange'} variant="light">
              {watchlistQuery.isLoading ? '读取服务端' : savedWatchlistMatches ? '服务端已保存' : '有未保存变更'}
            </Badge>
          </Group>
        </Group>

        <WebWatchlistEditor
          watchlist={watchlist}
          onChange={(nextWatchlist) => setWatchlist(normalizeDesktopWatchlist(nextWatchlist))}
        />

        <div className="watchlist-feishu-switch-row">
          <Switch
            label="开启自选锐评飞书群推送"
            description="由服务端 FaaS 在 A 股交易日的 10 个半小时槽位自动触发；关闭 Web 页面也会继续运行。"
            checked={watchlistFeishuEnabled}
            onChange={(event) => setWatchlistFeishuEnabled(event.currentTarget.checked)}
          />
        </div>

        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="sm" mt="md">
          <TextInput
            label="订阅群 ID"
            description="支持数字群 ID 或 oc_ 开头的 open_chat_id；发送时会自动转换。"
            placeholder="7650… 或 oc_xxxxxxxxxxxxxxxx"
            value={watchlistFeishuChatId}
            leftSection={<MessageSquareText size={15} />}
            onChange={(event) => setWatchlistFeishuChatId(event.currentTarget.value)}
          />
          <TextInput
            label="平台访问地址"
            description="群成员可访问的网站根地址，用于拼接个股详情链接。"
            placeholder="https://stock.example.com"
            value={watchlistPlatformUrl}
            leftSection={<Link2 size={15} />}
            onChange={(event) => setWatchlistPlatformUrl(event.currentTarget.value)}
          />
        </SimpleGrid>

        <div className="watchlist-feishu-flow" aria-label="锐评群推送流程">
          <span>FaaS 定时巡场</span><i>→</i><span>完整分时 + AI 锐评</span><i>→</i><span>飞书群卡片</span><i>→</i><span>点击股票看走势</span>
        </div>
        <Text size="xs" c="dimmed" mt="xs">
          当前生成引擎：{aiConfigured ? aiModelLabel : '行情规则代笔'}。模型 API Key 仅从服务端环境变量读取，不会保存到页面或下发到浏览器。
        </Text>

        <Group justify="space-between" align="flex-end" mt="md" gap="md">
          <Text size="xs" c="dimmed" className="watchlist-feishu-permission-note">
            机器人需已加入目标群，并具备 im:message 发送消息权限；自选和订阅会一起保存到服务端，Web 无需保持打开。
          </Text>
          <Group gap="xs" wrap="nowrap">
            <Button
              color="dark"
              leftSection={<Settings2 size={16} />}
              loading={saveWatchlistSubscriptionMutation.isPending}
              disabled={notificationQuery.isLoading || !normalizeEmailInput(notificationEmail) || (watchlistFeishuEnabled && (!watchlistFeishuChatId.trim() || !watchlistPlatformUrl.trim()))}
              onClick={() => saveWatchlistSubscriptionMutation.mutate()}
            >
              保存自选与订阅
            </Button>
            <Button
              color="teal"
              variant="light"
              leftSection={<Send size={16} />}
              loading={manualWatchlistNotificationMutation.isPending}
              disabled={!watchlist.length || !watchlistFeishuEnabled || !effectiveNotificationEmail || !watchlistFeishuChatId.trim() || !watchlistPlatformUrl.trim() || !savedWatchlistConfigMatches || !savedWatchlistMatches}
              onClick={() => manualWatchlistNotificationMutation.mutate(effectiveNotificationEmail)}
            >
              立即推送真实锐评
            </Button>
          </Group>
        </Group>
        {manualWatchlistNotificationMutation.data ? (
          <WatchlistCommentaryPreview response={manualWatchlistNotificationMutation.data} />
        ) : null}
      </Paper>
      ) : null}

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
