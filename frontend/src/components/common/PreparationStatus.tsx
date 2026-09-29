/** Company readiness strip — hidden per product decision (no UI change to
 *  data, fetching, or backend status; the preparation flow itself is
 *  untouched and every analyst tab reads the same prepared data).
 *
 *  Renders nothing on all tabs where it is mounted (Dashboard, Company
 *  Analysis, analyst pages).
 */
export default function PreparationStatus({ symbol }: { symbol: string }) {
  void symbol;
  return null;
}
