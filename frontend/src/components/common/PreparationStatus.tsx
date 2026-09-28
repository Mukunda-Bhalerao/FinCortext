import { useEffect } from 'react';
import { useFinCortext } from '../../app/FinCortextContext';

/** Component-level readiness labels for the preparation strip. */
const COMPONENT_LABELS: Record<string, string> = {
  market: 'Market',
  fundamentals: 'Fundamentals',
  company_metadata: 'Company info',
  industry: 'Industry',
  peers: 'Peers',
  news: 'News',
  web_research: 'Web research',
};

function componentClass(status: string | undefined): string {
  if (status === 'READY') return 'prep-ready';
  if (status === 'PARTIAL') return 'prep-partial';
  return 'prep-missing';
}

/** Company readiness strip: "Preparing company data…" while the central
 *  preparation flow runs, then per-component readiness (market, fundamentals,
 *  company info, industry, peers, news, web research) so agent tabs know
 *  what is actually usable instead of racing ahead with blank cards. */
export default function PreparationStatus({ symbol }: { symbol: string }) {
  const { preparationOf, preparationErrorOf, ensurePreparation } = useFinCortext();

  useEffect(() => {
    ensurePreparation(symbol).catch(() => undefined);
  }, [symbol, ensurePreparation]);

  const prep = preparationOf(symbol);
  const error = preparationErrorOf(symbol);

  if (prep === undefined && error === null) {
    return (
      <p className="muted preparation-status" role="status">
        Preparing company data for {symbol}…
      </p>
    );
  }
  if (!prep) {
    return (
      <p className="muted preparation-status" role="status">
        Company preparation unavailable for {symbol}
        {error ? ` — ${error}` : ' — showing whatever stored data exists.'}
      </p>
    );
  }
  const components = prep.components ?? {};
  const keys = Object.keys(COMPONENT_LABELS).filter((k) => k in components);
  const readyKeys = keys.filter((k) => components[k] === 'READY');
  // (Area-level UNAVAILABLE/ERROR details stay visible on each analyst tab
  // as limitations; the strip reports the component rollup.)
  const missingKeys = keys.filter((k) => components[k] !== 'READY');
  // "Company data ready" ONLY when the minimum downstream data is actually
  // prepared (market + fundamentals + company info). Anything less names
  // exactly what is ready and what is not — never a blanket "ready".
  const fullyReady =
    components.market === 'READY' &&
    components.fundamentals === 'READY' &&
    components.company_metadata === 'READY' &&
    missingKeys.length === 0;
  const label = (k: string) => COMPONENT_LABELS[k] ?? k;
  return (
    <div className="preparation-status" role="status">
      <p className="muted">
        {fullyReady
          ? `Company data ready for ${symbol} — quote, history, fundamentals, news and peers prepared.`
          : `Company data partially ready for ${symbol}${
              readyKeys.length > 0
                ? ` — ready: ${readyKeys.map(label).join(', ')}`
                : ''
            }${
              missingKeys.length > 0
                ? `; unavailable: ${missingKeys.map(label).join(', ')}`
                : ''
            } — available views are shown below, genuinely missing inputs are listed as limitations.`}
      </p>
      {keys.length > 0 && (
        <ul className="prep-components" aria-label="Data readiness by area">
          {keys.map((k) => (
            <li key={k} className={`prep-component ${componentClass(components[k])}`}>
              <span className="prep-component-name">{COMPONENT_LABELS[k]}</span>
              <span className="prep-component-state">{components[k]}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
