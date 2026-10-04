import type { DataStatusValue } from '../../types/api';

const LABELS: Record<DataStatusValue, string> = {
  LIVE: 'LIVE',
  CACHED: 'CACHED',
  IMPORTED_OFFICIAL: 'IMPORTED OFFICIAL DATA',
  SAMPLE: 'SAMPLE / DEMO',
  UNAVAILABLE: 'UNAVAILABLE',
  ERROR: 'ERROR',
};

/** Explicit data-status badge — never presents sample data as live.
 *  `WEB_RESEARCH` marks web-researched values (the lowest reliability tier;
 *  always visually distinct from provider/official data). */
export default function StatusBadge({ status }: { status: DataStatusValue | string }) {
  const known = (status as DataStatusValue) in LABELS || status === 'WEB_RESEARCH';
  const key = known ? ((status === 'WEB_RESEARCH' ? 'WEB_RESEARCH' : status) as DataStatusValue) : 'UNAVAILABLE';
  const label = status === 'WEB_RESEARCH' ? 'WEB-RESEARCHED' : LABELS[key];
  return <span className={`badge badge-status-${key.toLowerCase()}`}>{label}</span>;
}