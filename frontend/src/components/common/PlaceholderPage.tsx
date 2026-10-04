interface PlaceholderPageProps {
  title: string;
  note?: string;
}

/** Explicit "not implemented yet" placeholder for future modules. */
export default function PlaceholderPage({ title, note }: PlaceholderPageProps) {
  return (
    <section className="page">
      <h2>{title}</h2>
      <div className="placeholder-card">
        <span className="badge badge-coming-soon">Coming soon</span>
        <p>{note ?? 'This module is not implemented yet.'}</p>
        <p className="muted">
          FinCortext implements the Firm, Industry, Sentiment and Macro
          Analysts behind the platform sections. Future modules will integrate
          through the standardized agent output contract.
        </p>
      </div>
    </section>
  );
}