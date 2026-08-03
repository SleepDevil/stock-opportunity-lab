import { Badge, Group, Text } from '@mantine/core';
import { ExternalLink, Send } from 'lucide-react';

import type { WatchlistCommentaryResponse } from '../../types/api';
import {
  desktopCommentarySegments,
  desktopStockAnalysisPath
} from '../desktop/desktopWidgetModel';
import './watchlistCommentary.css';

function signedPct(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return '-';
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function tone(value?: number | null): 'up' | 'down' | 'flat' {
  if ((value ?? 0) > 0) return 'up';
  if ((value ?? 0) < 0) return 'down';
  return 'flat';
}

export function WatchlistCommentaryPreview({ response }: { response: WatchlistCommentaryResponse }) {
  const segments = desktopCommentarySegments(response.commentary, response.stocks ?? []);
  const delivered = response.delivery.status === 'sent';

  return (
    <section className="web-commentary-preview" aria-label="本次自选锐评">
      <header>
        <div>
          <Text size="xs" fw={900} c="dimmed">本次生成结果</Text>
          <Text fw={950} size="lg">{response.title}</Text>
        </div>
        <Group gap="xs">
          <Badge color={delivered ? 'teal' : 'orange'} variant="light">
            {delivered ? '已推送' : '未推送'}
          </Badge>
        </Group>
      </header>

      <div className="web-commentary-metrics">
        <span><small>红盘</small><strong className="is-up">{response.summary.rising} 只</strong></span>
        <span><small>绿盘</small><strong className="is-down">{response.summary.falling} 只</strong></span>
        <span><small>平均涨跌</small><strong className={`is-${tone(response.summary.average_pct)}`}>{signedPct(response.summary.average_pct)}</strong></span>
      </div>

      <p className="web-commentary-copy">
        {segments.map((segment, index) => segment.stock ? (
          <a href={desktopStockAnalysisPath(segment.stock.code)} key={`${segment.stock.code}-${index}`}>
            {segment.text}
          </a>
        ) : <span key={`text-${index}`}>{segment.text}</span>)}
      </p>

      <div className="web-commentary-stock-links">
        {(response.stocks ?? []).map((stock) => (
          <a href={desktopStockAnalysisPath(stock.code)} key={stock.code}>
            <span>{stock.name}<small>{stock.code}</small></span>
            <strong className={`is-${tone(stock.pct_change)}`}>{signedPct(stock.pct_change)}</strong>
            <ExternalLink size={13} />
          </a>
        ))}
      </div>

      <footer>
        <span><Send size={13} />{response.delivery.message}</span>
        <small>{response.disclaimer}</small>
      </footer>
    </section>
  );
}
