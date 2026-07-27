import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const outDir = join(root, '.tmp-tests', 'wechat-knowledge-model');

async function loadWechatKnowledgeModel() {
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });
  execFileSync(
    join(root, 'node_modules', '.bin', 'tsc'),
    [
      'src/features/alerts/wechatKnowledgeModel.ts',
      '--ignoreConfig',
      '--outDir',
      outDir,
      '--module',
      'ES2022',
      '--target',
      'ES2022',
      '--moduleResolution',
      'Bundler',
      '--strict',
      '--skipLibCheck'
    ],
    { cwd: root, stdio: 'pipe' }
  );
  return import(pathToFileURL(join(outDir, 'features', 'alerts', 'wechatKnowledgeModel.js')).href);
}

const model = await loadWechatKnowledgeModel();

test('does not show a stale subscription name for an unrelated article URL', () => {
  const source = model.resolveWechatSourceLabel({
    articleUrl: 'https://mp.weixin.qq.com/s/current-article',
    detectedSource: '',
    subscriptions: [
      {
        source_name: '芯片观察',
        sample_url: 'https://mp.weixin.qq.com/s/old-test-article',
        feed_url: null
      }
    ]
  });

  assert.equal(source, '');
});

test('shows the subscription name only when it belongs to the current URL or latest ingest', () => {
  assert.equal(
    model.resolveWechatSourceLabel({
      articleUrl: 'https://mp.weixin.qq.com/s/current-article',
      detectedSource: '',
      subscriptions: [
        {
          source_name: '21世纪经济报道',
          sample_url: 'https://mp.weixin.qq.com/s/current-article',
          feed_url: null
        }
      ]
    }),
    '21世纪经济报道'
  );
  assert.equal(
    model.resolveWechatSourceLabel({
      articleUrl: 'https://mp.weixin.qq.com/s/current-article',
      detectedSource: '财联社',
      subscriptions: []
    }),
    '财联社'
  );
});

test('detects whether any subscription can sync later articles', () => {
  assert.equal(model.hasSyncableWechatFeed({ subscriptions: [], articles: [], capability_note: '' }), false);
  assert.equal(
    model.hasSyncableWechatFeed({
      subscriptions: [{ source_name: '21世纪经济报道', sample_url: null, feed_url: 'https://feeds.example/rss.xml' }],
      articles: [],
      capability_note: ''
    }),
    true
  );
});

test('describes sync prerequisites based on gateway status', () => {
  assert.equal(
    model.getWechatSyncTooltip({
      subscriptions: [],
      articles: [],
      capability_note: '',
      gateway: { configured: false, label: '未配置公众号网关' }
    }),
    '未配置公众号网关时，需要先填写并保存 Feed/API URL，或配置公众号网关。'
  );
  assert.equal(
    model.getWechatSyncTooltip({
      subscriptions: [],
      articles: [],
      capability_note: '',
      gateway: { configured: true, label: 'wechat-download-api' }
    }),
    '先解析一篇文章完成自动订阅，随后可同步该公众号的新文章。'
  );
  assert.equal(
    model.getWechatSyncTooltip({
      subscriptions: [{ source_name: '21世纪经济报道', sample_url: null, feed_url: 'https://feeds.example/rss.xml' }],
      articles: [],
      capability_note: '',
      gateway: { configured: true, label: 'wechat-download-api' }
    }),
    ''
  );
});

test('shows sync hover help only while sync is unavailable', () => {
  assert.equal(
    model.shouldShowWechatSyncHelp({
      subscriptions: [],
      articles: [],
      capability_note: '',
      gateway: { configured: false, label: '未配置公众号网关' }
    }),
    true
  );
  assert.equal(
    model.shouldShowWechatSyncHelp({
      subscriptions: [{ source_name: '21世纪经济报道', sample_url: null, feed_url: 'https://feeds.example/rss.xml' }],
      articles: [],
      capability_note: '',
      gateway: { configured: false, label: '未配置公众号网关' }
    }),
    false
  );
});

test('explains how feed urls are obtained without making users find one manually', () => {
  const missingGatewayGuide = model.getWechatFeedSetupGuide({
    subscriptions: [],
    articles: [],
    capability_note: '',
    gateway: { configured: false, label: '未配置公众号网关' }
  });

  assert.equal(missingGatewayGuide.title, '自动获取后续文章还差一步');
  assert.match(missingGatewayGuide.description, /不用自己从文章 URL 里找 Feed/);
  assert.deepEqual(missingGatewayGuide.steps, [
    '在项目根目录运行 npm run dev，它会同时启动主应用和 wechat-download-api。',
    '打开 http://127.0.0.1:5500/admin.html 扫码登录微信公众平台账号。',
    '回到这里粘贴公众号文章 URL，点击“解析此文并订阅”，系统会自动生成 Feed URL。'
  ]);
  assert.equal(missingGatewayGuide.manualFeedDescription, '已有 WeWe RSS、zlzchat 或其他工具生成的 RSS/JSON 时才需要手动填写。');

  const configuredGuide = model.getWechatFeedSetupGuide({
    subscriptions: [],
    articles: [],
    capability_note: '',
    gateway: { configured: true, label: 'wechat-download-api' }
  });

  assert.equal(configuredGuide.title, '已启用自动获取 Feed');
  assert.match(configuredGuide.description, /系统会通过 wechat-download-api 自动创建后续文章 Feed/);
  assert.equal(configuredGuide.manualFeedDescription, '通常不用填写；只有想覆盖自动生成的 Feed/API URL 时才需要手动填。');
});

test('formats article publication dates for cards', () => {
  assert.equal(model.formatWechatPublishTime('2026-06-15T06:00:00+00:00'), '发布 2026-06-15 14:00');
  assert.equal(model.getWechatArticleTradeDate('2026-06-15T06:00:00+00:00'), '20260615');
  assert.equal(model.formatWechatPublishTime(''), '');
  assert.equal(model.formatWechatPublishTime(null), '');
});

test('uses the market observation date for article stock kline previews', () => {
  assert.equal(model.getWechatKlineTradeDate('20260615', '2026-06-05T15:29:22+00:00'), '20260615');
  assert.equal(model.getWechatKlineTradeDate('2026-06-15', '2026-06-05T15:29:22+00:00'), '20260615');
  assert.equal(model.getWechatKlineTradeDate('', '2026-06-05T15:29:22+00:00'), '20260605');
});

test('normalizes safe original article links for card actions', () => {
  assert.equal(
    model.normalizeExternalArticleUrl(' https://mp.weixin.qq.com/s/aPgU_HtBTNUrqoyrBVxgkA '),
    'https://mp.weixin.qq.com/s/aPgU_HtBTNUrqoyrBVxgkA'
  );
  assert.equal(model.normalizeExternalArticleUrl('http://example.com/news?id=1#top'), 'http://example.com/news?id=1#top');
  assert.equal(model.normalizeExternalArticleUrl('javascript:alert(1)'), '');
  assert.equal(model.normalizeExternalArticleUrl(''), '');
  assert.equal(model.normalizeExternalArticleUrl(null), '');
});

test('collects unique wechat stock targets for bounded kline preloading', () => {
  const articles = [
    {
      id: 'a1',
      publish_time: '2026-06-05T15:29:22+00:00',
      knowledge: {
        stocks: [
          { code: '688017', name: '绿的谐波' },
          { code: '920578', name: '巨能股份' },
          { code: '688017', name: '绿的谐波' },
          { code: '', name: '未识别' }
        ]
      }
    },
    {
      id: 'a2',
      publish_time: '2026-06-06T15:29:22+00:00',
      knowledge: {
        stocks: [
          { code: '301112', name: '信邦智能' },
          { code: '300276', name: '三丰智能' }
        ]
      }
    }
  ];

  assert.deepEqual(model.collectWechatKlinePrefetchTargets(articles, '20260616', 3), [
    { code: '688017', name: '绿的谐波', tradeDate: '20260616' },
    { code: '920578', name: '巨能股份', tradeDate: '20260616' },
    { code: '301112', name: '信邦智能', tradeDate: '20260616' }
  ]);
});

test('groups wechat kline preload targets into bounded concurrent batches', () => {
  const targets = [
    { code: '688017', name: '绿的谐波', tradeDate: '20260616' },
    { code: '920578', name: '巨能股份', tradeDate: '20260616' },
    { code: '301112', name: '信邦智能', tradeDate: '20260616' },
    { code: '300276', name: '三丰智能', tradeDate: '20260616' },
    { code: '600958', name: '东方证券', tradeDate: '20260616' }
  ];

  assert.deepEqual(model.chunkWechatKlinePrefetchTargets(targets, 2), [
    targets.slice(0, 2),
    targets.slice(2, 4),
    targets.slice(4)
  ]);
});

test('builds wechat query params from a single date range picker value', () => {
  assert.deepEqual(model.resolveWechatRangeParams(['2026-06-16', '2026-06-16']), {
    from_date: '2026-06-16',
    to_date: '2026-06-16',
    limit: 100
  });
  assert.deepEqual(model.resolveWechatRangeParams(['2026-06-05', '2026-06-15']), {
    from_date: '2026-06-05',
    to_date: '2026-06-15',
    limit: 100
  });
  assert.deepEqual(model.resolveWechatRangeParams(['2026-06-15', '2026-06-05']), {
    from_date: '2026-06-05',
    to_date: '2026-06-15',
    limit: 100
  });
  assert.deepEqual(model.resolveWechatRangeParams([null, null]), {
    from_date: null,
    to_date: null,
    limit: 100
  });
});

test('summarizes multiple wechat subscriptions with article counts and feed state', () => {
  const subscriptions = [
    {
      id: 's1',
      source_name: '21世纪经济报道',
      sample_url: 'https://mp.weixin.qq.com/s/a',
      feed_url: 'http://127.0.0.1/feed/s1',
      capability: 'rss',
      status: 'active',
      created_at: '2026-06-01T00:00:00',
      updated_at: '2026-06-16T08:00:00'
    },
    {
      id: 's2',
      source_name: '芯片观察',
      sample_url: null,
      feed_url: null,
      capability: 'manual',
      status: 'active',
      created_at: '2026-06-02T00:00:00',
      updated_at: '2026-06-15T08:00:00'
    }
  ];
  const articles = [
    { source_name: '21世纪经济报道' },
    { source_name: '21世纪经济报道' },
    { source_name: '芯片观察' }
  ];

  assert.deepEqual(model.summarizeWechatSubscriptions(subscriptions, articles), [
    {
      id: 's1',
      sourceName: '21世纪经济报道',
      articleCount: 2,
      feedConfigured: true,
      status: 'active',
      updatedAt: '2026-06-16T08:00:00'
    },
    {
      id: 's2',
      sourceName: '芯片观察',
      articleCount: 1,
      feedConfigured: false,
      status: 'active',
      updatedAt: '2026-06-15T08:00:00'
    }
  ]);
});

test('filters wechat articles by selected subscription source', () => {
  const articles = [
    { id: 'a1', source_name: '财联社' },
    { id: 'a2', source_name: '21世纪经济报道' },
    { id: 'a3', source_name: '财联社' }
  ];

  assert.deepEqual(model.filterWechatArticlesBySource(articles, ''), articles);
  assert.deepEqual(model.filterWechatArticlesBySource(articles, '财联社'), [articles[0], articles[2]]);
  assert.deepEqual(model.filterWechatArticlesBySource(articles, '不存在'), []);
});

test('keeps wechat sync loading state on a single visible action', () => {
  const source = readFileSync(join(root, 'src', 'features', 'alerts', 'AlertsPage.tsx'), 'utf8');
  const loadingBindings = source.match(/loading=\{syncMutation\.isPending\}/g) ?? [];

  assert.equal(loadingBindings.length, 1);
});

test('auto-syncs wechat knowledge only when todays cache is empty', () => {
  const syncableData = {
    subscriptions: [{ source_name: '财联社', sample_url: null, feed_url: 'http://127.0.0.1/feed/rss' }],
    articles: []
  };

  assert.equal(
    model.shouldAutoSyncWechatKnowledge({
      data: syncableData,
      fromDate: '2026-06-17',
      toDate: '2026-06-17',
      today: '2026-06-17',
      isSyncing: false
    }),
    true
  );
  assert.equal(
    model.shouldAutoSyncWechatKnowledge({
      data: { ...syncableData, articles: [{ source_name: '财联社' }] },
      fromDate: '2026-06-17',
      toDate: '2026-06-17',
      today: '2026-06-17',
      isSyncing: false
    }),
    false
  );
  assert.equal(
    model.shouldAutoSyncWechatKnowledge({
      data: syncableData,
      fromDate: '2026-06-16',
      toDate: '2026-06-16',
      today: '2026-06-17',
      isSyncing: false
    }),
    false
  );
  assert.equal(
    model.shouldAutoSyncWechatKnowledge({
      data: syncableData,
      fromDate: '2026-06-17',
      toDate: '2026-06-17',
      today: '2026-06-17',
      isSyncing: true
    }),
    false
  );
});
