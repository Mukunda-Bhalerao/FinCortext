import { useEffect, useState } from 'react';
import StatusBadge from '../../components/common/StatusBadge';
import { useFinCortext } from '../../app/FinCortextContext';
import { api } from '../../services/api';
import type { NewsArticleSummary, NewsListResponse, NewsStatusResponse, ResearchItem } from '../../types/api';

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return 'date unavailable';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 'date unavailable';
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
}

/** News — stored articles with explicit status, plus the labeled
 *  web-research digest when stored articles are missing. */
export default function NewsPage() {
  const { symbol, entryFor, newsOf, ensureNews, invalidateNews, newsErrorOf } = useFinCortext();
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [newsStatus, setNewsStatus] = useState<NewsStatusResponse | null>(null);
  const [digest, setDigest] = useState<ResearchItem[]>([]);
  const entry = entryFor(symbol);

  const news = newsOf(symbol) as NewsListResponse | null | undefined;
  const newsError = newsErrorOf(symbol);
  const loading = news === undefined && newsError === null;

  useEffect(() => {
    ensureNews(symbol).catch(() => undefined);
    api.news.status().then(setNewsStatus).catch(() => setNewsStatus(null));
    api.research
      .list(symbol, 'news_digest')
      .then((r) => {
        const latest = r.reports?.[0];
        setDigest((latest?.payload?.items as ResearchItem[]) ?? []);
      })
      .catch(() => setDigest([]));
  }, [symbol, ensureNews]);

  const refresh = () => {
    setRefreshing(true);
    setRefreshError(null);
    api.news
      .refresh(symbol)
      .then(() => {
        invalidateNews(symbol);
        return ensureNews(symbol, true);
      })
      .then(() => setRefreshing(false))
      .catch((e: Error) => {
        setRefreshError(e.message);
        setRefreshing(false);
      });
  };

  const articles: NewsArticleSummary[] = news?.articles ?? [];

  return (
    <section className="page">
      <header className="card dash-head fade-in">
        <div className="dash-identity">
          <div className="term-symbol">{symbol}</div>
          <div>
            <div className="term-name">{entry?.name ?? symbol}</div>
            <div className="term-chips">
              <span className="chip">Recent financial news</span>
              {newsStatus && (
                <span className="chip">
                  {newsStatus.configured ? 'Live news configured' : 'Stored news only'}
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="dash-pricecol">
          <div className="muted">Stored articles</div>
          <div className="term-price" style={{ fontSize: '1.4rem' }}>
            {loading ? '…' : `${news?.count ?? 0}`}
          </div>
          {news && <StatusBadge status={news.status} />}
        </div>
        <button className="btn btn-primary btn-analyze" onClick={refresh} disabled={refreshing}>
          {refreshing ? 'Fetching…' : '↻ Fetch News'}
        </button>
      </header>

      {refreshError && <p className="error-text fade-in">{refreshError}</p>}

      <div className="card fade-in" style={{ animationDelay: '0.04s' }}>
        <h3>Stored News</h3>
        {loading ? (
          <div className="skeleton skeleton-line" />
        ) : articles.length === 0 ? (
          <div className="dash-empty">
            <p><StatusBadge status={news?.status ?? 'UNAVAILABLE'} /></p>
            <p className="muted">
              {`No stored news for ${symbol} yet — nothing is shown until real articles are collected.`}
            </p>
          </div>
        ) : (
          <ul className="news-list-live">
            {articles.map((a) => (
              <li key={a.article_id} className="news-item-live">
                <div className="news-item-head">
                  <a href={a.source_url ?? '#'} target="_blank" rel="noreferrer" className="news-item-title">
                    {a.title}
                  </a>
                </div>
                {a.description && <p className="muted news-item-desc">{a.description}</p>}
                <p className="muted news-item-meta">
                  {a.source ?? 'source unavailable'} · {fmtDate(a.published_at)}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>

      {digest.length > 0 && (
        <div className="card fade-in" style={{ animationDelay: '0.08s' }}>
          <div className="dash-heading">
            <h3>Web-research developments</h3>
            <StatusBadge status="WEB_RESEARCH" />
          </div>
          <p className="muted dash-section-note">
            Labeled web research — not stored articles, not scored by the
            Sentiment Analyst. Shown here as context only.
          </p>
          <ul className="news-list-live">
            {digest.map((item, i) => (
              <li key={i} className="news-item-live">
                <a href={item.url ?? '#'} target="_blank" rel="noreferrer" className="news-item-title">
                  {item.title}
                </a>
                {item.summary && <p className="muted news-item-desc">{item.summary}</p>}
                <p className="muted news-item-meta">
                  {item.source ?? 'web research'} · {fmtDate(item.published_at)}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
