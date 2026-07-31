import {
  fetchMarketIndex,
  fetchStockQuotes,
  fetchWatchlistCommentary
} from '../../lib/api';
import type { WatchlistCommentaryResponse } from '../../types/api';
import {
  buildDesktopWatchlistCommentaryRequest,
  type DesktopWatchStock
} from '../desktop/desktopWidgetModel';

export async function generateWebWatchlistCommentary(input: {
  watchlist: DesktopWatchStock[];
  userEmail: string;
  manual: boolean;
  slot?: string;
}): Promise<WatchlistCommentaryResponse> {
  if (!input.watchlist.length) {
    throw new Error('请先在 Web 页面添加自选股');
  }

  const symbols = input.watchlist.map((stock) => stock.code);
  const [quotes, market] = await Promise.all([
    fetchStockQuotes({ symbols, refresh: true }),
    fetchMarketIndex({ refresh: true })
  ]);

  return fetchWatchlistCommentary(buildDesktopWatchlistCommentaryRequest({
    watchlist: input.watchlist,
    quotes,
    market,
    userEmail: input.userEmail,
    manual: input.manual,
    slot: input.slot
  }));
}
