import StatusBadge from './StatusBadge';
import { deltaClass, fmtPrice, fmtSigned, type PeerQuote } from '../../features/company/priceStats';
import type { MarketStatusResponse, UniverseEntry } from '../../types/api';

interface PeerTableProps {
  peers: UniverseEntry[];
  marketStatus: MarketStatusResponse | null;
  /** Latest quotes per symbol; a missing entry with quotesLoading means "still loading". */
  quotes: Record<string, PeerQuote | undefined>;
  quotesLoading: boolean;
  current: string;
  onSelect: (symbol: string) => void;
}

/** Sector peer table with real stored prices. Every cell renders backend data
 *  or an honest unavailable marker — peers are never invented. */
export default function PeerTable({
  peers,
  marketStatus,
  quotes,
  quotesLoading,
  current,
  onSelect,
}: PeerTableProps) {
  if (peers.length === 0) {
    return <p className="muted">Sector information is unavailable.</p>;
  }
  const bySymbol = new Map((marketStatus?.symbols ?? []).map((s) => [s.symbol, s]));
  return (
    <table className="data-table peer-table">
      <thead>
        <tr>
          <th>Peer</th>
          <th className="num">Price</th>
          <th className="num">Day change</th>
          <th className="num">Stored days</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {peers.map((peer) => {
          const status = bySymbol.get(peer.symbol) ?? null;
          const quote = quotes[peer.symbol];
          const isCurrent = peer.symbol === current;
          return (
            <tr key={peer.symbol} className={isCurrent ? 'peer-self' : undefined}>
              <td>
                <button
                  className="peer-link"
                  onClick={() => onSelect(peer.symbol)}
                  disabled={isCurrent}
                  title={isCurrent ? 'This company' : `Switch to ${peer.symbol}`}
                >
                  {peer.symbol}
                </button>{' '}
                <span className="muted">{peer.name}</span>
              </td>
              <td className="num">
                {quote?.close !== undefined && quote?.close !== null ? (
                  `₹${fmtPrice(quote.close)}`
                ) : quotesLoading && quote === undefined ? (
                  <span className="muted">…</span>
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
              <td className={`num ${deltaClass(quote?.dayChangePct ?? null)}`}>
                {quote?.dayChangePct !== undefined && quote?.dayChangePct !== null ? (
                  `${fmtSigned(quote.dayChangePct)}%`
                ) : quotesLoading && quote === undefined ? (
                  <span className="muted">…</span>
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
              <td className="num">{status ? status.rows : '—'}</td>
              <td>
                {status ? (
                  <StatusBadge status={status.status} />
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
