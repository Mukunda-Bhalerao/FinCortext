import { render, screen } from '@testing-library/react';
import StatusBadge from './StatusBadge';

describe('StatusBadge', () => {
  it('renders each known status with its explicit label', () => {
    const cases: Array<[string, string]> = [
      ['LIVE', 'LIVE'],
      ['CACHED', 'CACHED'],
      ['IMPORTED_OFFICIAL', 'IMPORTED OFFICIAL DATA'],
      ['SAMPLE', 'SAMPLE / DEMO'],
      ['UNAVAILABLE', 'UNAVAILABLE'],
      ['ERROR', 'ERROR'],
    ];
    for (const [status, label] of cases) {
      render(<StatusBadge status={status} />);
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it('falls back to UNAVAILABLE for unknown statuses (never fakes LIVE)', () => {
    render(<StatusBadge status="SOMETHING_ELSE" />);
    expect(screen.getByText('UNAVAILABLE')).toBeInTheDocument();
  });
});