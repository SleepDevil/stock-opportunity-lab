import { useState } from 'react';
import { ActionIcon, Badge, Button, Group, Loader, Text, TextInput } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { useQuery } from '@tanstack/react-query';
import { ExternalLink, Plus, Search, Trash2 } from 'lucide-react';

import { fetchStockSearch } from '../../lib/api';
import { todayInputValue, toTradeDate } from '../../lib/format';
import {
  addDesktopWatchStock,
  DESKTOP_WATCHLIST_LIMIT,
  desktopStockAnalysisPath,
  type DesktopWatchStock
} from '../desktop/desktopWidgetModel';
import './watchlistCommentary.css';

export function WebWatchlistEditor({
  watchlist,
  onChange,
  disabled = false
}: {
  watchlist: DesktopWatchStock[];
  onChange: (watchlist: DesktopWatchStock[]) => void;
  disabled?: boolean;
}) {
  const [query, setQuery] = useState('');
  const trimmedQuery = query.trim();
  const [debouncedQuery] = useDebouncedValue(trimmedQuery, 350);
  const waitingForDebounce = Boolean(trimmedQuery && debouncedQuery !== trimmedQuery);
  const searchQuery = useQuery({
    queryKey: ['web-watchlist', 'stock-search', debouncedQuery],
    queryFn: ({ signal }) => fetchStockSearch({
      query: debouncedQuery,
      date: toTradeDate(todayInputValue()),
      limit: 6,
      signal,
      timeoutMs: 6_000
    }),
    enabled: Boolean(debouncedQuery) && !disabled,
    staleTime: 5 * 60_000,
    retry: false
  });

  const addStock = (stock: DesktopWatchStock) => {
    if (disabled) return;
    onChange(addDesktopWatchStock(watchlist, stock));
    setQuery('');
  };

  return (
    <section className="web-watchlist-editor" aria-label="Web 自选名单">
      <Group justify="space-between" align="flex-start" gap="md">
        <div>
          <Text fw={900}>服务端自选名单</Text>
          <Text size="xs" c="dimmed">添加或移除后立即同步，FaaS 定时读取同一份名单；最多 {DESKTOP_WATCHLIST_LIMIT} 只。</Text>
        </div>
        <Badge color={watchlist.length ? 'teal' : 'gray'} variant="light">{watchlist.length} 只</Badge>
      </Group>

      <TextInput
        mt="sm"
        value={query}
        leftSection={waitingForDebounce || searchQuery.isFetching ? <Loader size={14} /> : <Search size={15} />}
        placeholder={disabled ? '先保存账户邮箱，再维护自选名单' : '输入股票名称、代码或首字母添加自选'}
        disabled={disabled}
        onChange={(event) => setQuery(event.currentTarget.value)}
      />

      {trimmedQuery ? (
        <div className="web-watchlist-search-results">
          {waitingForDebounce ? <span>正在匹配名称、代码和拼音…</span> : null}
          {!waitingForDebounce && searchQuery.error ? <span>{searchQuery.error instanceof Error ? searchQuery.error.message : '搜索失败，请稍后重试。'}</span> : null}
          {!waitingForDebounce && !searchQuery.isFetching && !searchQuery.error && !(searchQuery.data?.results.length) ? <span>没有匹配的股票。</span> : null}
          {!waitingForDebounce && (searchQuery.data?.results ?? []).map((item) => {
            const selected = watchlist.some((stock) => stock.code === item.code);
            const full = watchlist.length >= DESKTOP_WATCHLIST_LIMIT;
            return (
              <button
                key={item.code}
                type="button"
                disabled={disabled || selected || full}
                onClick={() => addStock({ code: item.code, name: item.name })}
              >
                <span><strong>{item.name}</strong><small>{item.code}</small></span>
                {selected ? <Badge size="xs" color="gray">已添加</Badge> : full ? <Badge size="xs" color="orange">已满</Badge> : <Plus size={15} />}
              </button>
            );
          })}
        </div>
      ) : null}

      {watchlist.length ? (
        <div className="web-watchlist-stocks">
          {watchlist.map((stock) => (
            <div key={stock.code}>
              <span><strong>{stock.name}</strong><small>{stock.code}</small></span>
              <Group gap={4} wrap="nowrap">
                <Button
                  component="a"
                  href={desktopStockAnalysisPath(stock.code)}
                  size="compact-xs"
                  variant="subtle"
                  color="blue"
                  rightSection={<ExternalLink size={12} />}
                >
                  看走势
                </Button>
                <ActionIcon
                  size="sm"
                  variant="subtle"
                  color="gray"
                  aria-label={`移除 ${stock.name}`}
                  disabled={disabled}
                  onClick={() => onChange(watchlist.filter((item) => item.code !== stock.code))}
                >
                  <Trash2 size={14} />
                </ActionIcon>
              </Group>
            </div>
          ))}
        </div>
      ) : (
        <div className="web-watchlist-empty">
          <Plus size={16} />输入股票后添加，系统会自动同步，关闭浏览器也会继续巡场。
        </div>
      )}
    </section>
  );
}
