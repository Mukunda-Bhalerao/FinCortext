import type { DataStatusValue } from '../../types/api';

const LABELS: Record<DataStatusValue, string> = {
  LIVE: 'LIVE',
  CACHED: 'CACHED',
  IMPORTED_OFFICIAL: 'IMPORTED OFFICIAL DATA',
  SAMPLE: 'SAMPLE / DEMO',
  UNAVAILABLE: 'UNAVAILABLE',
  ERROR: 'ERROR',
};

/** Explicit data-status badge — never presents sample data as live. */
export default function StatusBadge({ status }: { status: DataStatusValue | string }) {
  const key = (status as DataStatusValue) in LABELS ? (status as DataStatusValue) : 'UNAVAILABLE';
  return <span className={`badge badge-status-${key.toLowerCase()}`}>{LABELS[key]}</span>;
}