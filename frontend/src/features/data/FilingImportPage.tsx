import { useCallback, useEffect, useState } from 'react';
import CompanySelector from '../../components/common/CompanySelector';
import StatusBadge from '../../components/common/StatusBadge';
import { api, ApiRequestError } from '../../services/api';
import type { FilingImportResult, FilingsListResponse } from '../../types/api';

const SUPPORTED = 'Supported: .csv, .xbrl, .xml (full parsing) · .pdf (LIMITED text-extraction fallback)';

/** Official Filing Import — upload, validation result, provenance, honest limits. */
export default function FilingImportPage() {
  const [symbol, setSymbol] = useState('TCS');
  const [file, setFile] = useState<File | null>(null);
  const [sourceName, setSourceName] = useState('');
  const [filingDate, setFilingDate] = useState('');
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<FilingImportResult | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [documents, setDocuments] = useState<FilingsListResponse | null>(null);
  const [listError, setListError] = useState<string | null>(null);

  const loadDocuments = useCallback((sym: string) => {
    if (!sym) return;
    api.filings
      .list(sym)
      .then(setDocuments)
      .catch((e: Error) => setListError(e instanceof ApiRequestError ? e.message : e.message));
  }, []);

  useEffect(() => {
    loadDocuments(symbol);
  }, [symbol, loadDocuments]);

  const submit = async () => {
    if (!file || !symbol) return;
    setImporting(true);
    setResult(null);
    setImportError(null);
    try {
      const res = await api.filings.import(
        file,
        symbol,
        sourceName || 'manual-upload',
        filingDate || undefined,
      );
      setResult(res);
      loadDocuments(symbol);
    } catch (e) {
      setImportError(e instanceof ApiRequestError ? e.message : String(e));
    } finally {
      setImporting(false);
    }
  };

  return (
    <section className="page">
      <h2>Official Filing Import</h2>
      <p className="muted page-description">
        Ingest official financial statements. Content-hash deduplication,
        raw-file archiving, point-in-time metadata, and provenance events are
        applied automatically. Ingested filings are the primary truth for the
        Firm Analyst.
      </p>

      <div className="card">
        <h3>Upload a filing</h3>
        <p className="muted">{SUPPORTED}</p>
        <p className="muted">
          PDF limitation: extraction is a best-effort text fallback with
          explicit quality warnings — arbitrary PDFs cannot be parsed reliably.
        </p>

        <div className="form-grid">
          <CompanySelector value={symbol} onChange={setSymbol} />
          <label className="field">
            <span className="muted">File</span>
            <input
              type="file"
              accept=".csv,.xbrl,.xml,.pdf"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <label className="field">
            <span className="muted">Source name (provenance)</span>
            <input
              type="text"
              placeholder="e.g. Annual Report FY2024"
              value={sourceName}
              onChange={(e) => setSourceName(e.target.value)}
            />
          </label>
          <label className="field">
            <span className="muted">Filing date (optional, ISO)</span>
            <input
              type="date"
              value={filingDate}
              onChange={(e) => setFilingDate(e.target.value)}
            />
          </label>
          <button className="btn btn-primary" onClick={submit} disabled={!file || importing}>
            {importing ? 'Ingesting…' : 'Ingest filing'}
          </button>
        </div>

        {importError && <p className="error-text">Ingestion failed: {importError}</p>}

        {result && (
          <div className="result-box">
            <h4>
              Ingestion result <StatusBadge status="IMPORTED_OFFICIAL" />
            </h4>
            {result.document_id && (
              <p>
                Document <code>{result.document_id}</code> for {result.entity_id}
                {result.observations_stored !== undefined && (
                  <> — {result.observations_stored} financial observation(s) stored.</>
                )}
              </p>
            )}
            {result.message && <p>{result.message}</p>}
            {result.warnings && result.warnings.length > 0 && (
              <>
                <h4>Validation warnings</h4>
                <ul className="limitations-list">
                  {result.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}
      </div>

      <div className="card">
        <h3>Ingested documents for {symbol}</h3>
        {listError && <p className="error-text">{listError}</p>}
        {!documents && <p className="muted">Loading…</p>}
        {documents && documents.count === 0 && (
          <p className="muted">No filings ingested for this symbol yet.</p>
        )}
        {documents && documents.count > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th>File</th>
                <th>Type</th>
                <th>Observations</th>
                <th>Ingested</th>
                <th>Warnings</th>
              </tr>
            </thead>
            <tbody>
              {documents.documents.map((d) => (
                <tr key={d.document_id}>
                  <td>{d.file_name}</td>
                  <td>{d.document_type}</td>
                  <td>{d.observation_count}</td>
                  <td>{new Date(d.ingested_at).toLocaleString()}</td>
                  <td>{d.parse_warnings?.length ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}