'use client';

import { useState } from 'react';
import { Database, TriangleAlert } from 'lucide-react';
import { getDataProvenance, type DatasetProvenance, type ProvenanceResponse } from '@/lib/provenanceApi';
import { useApi } from '@/lib/useApi';
import { Panel } from '@/components/ui/Panel';
import { Badge } from '@/components/ui/Badge';
import { StatTile } from '@/components/ui/StatTile';
import { EmptyState } from '@/components/ui/EmptyState';
import { Alert } from '@/components/ui/Alert';
import { LoadingNote } from '@/components/ui/LoadingNote';
import { Button } from '@/components/ui/Button';

function fmtDateTime(iso: string): string {
  return new Date(iso).toLocaleString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit',
  });
}

function coverageStats(dataset: DatasetProvenance): { label: string; value: string }[] {
  const stats: { label: string; value: string }[] = [];
  if (dataset.record_count != null) stats.push({ label: 'Records', value: dataset.record_count.toLocaleString() });
  if (dataset.player_count != null) stats.push({ label: 'Players', value: dataset.player_count.toLocaleString() });
  if (dataset.season_count != null) stats.push({ label: 'Seasons', value: dataset.season_count.toLocaleString() });
  return stats;
}

function FreshnessFact({ dataset }: { dataset: DatasetProvenance }) {
  if (!dataset.last_updated_utc) {
    return (
      <div className="siq-data-freshness">
        <Badge tone="neutral" variant="outline" size="sm">Not tracked</Badge>
        <span className="ds-note">No ingestion timestamp is stored for this dataset.</span>
      </div>
    );
  }
  return (
    <div className="siq-data-freshness">
      <Badge tone="confidence" variant="outline" size="sm">{fmtDateTime(dataset.last_updated_utc)}</Badge>
      <span className="ds-note">{dataset.last_updated_basis ? `via ${dataset.last_updated_basis}` : 'Latest known refresh'}</span>
    </div>
  );
}

function DatasetCard({ dataset }: { dataset: DatasetProvenance }) {
  const failed = dataset.record_count == null;
  const stats = failed ? [] : coverageStats(dataset);
  const seasonRange = dataset.earliest_season && dataset.latest_season
    ? (dataset.earliest_season === dataset.latest_season
      ? dataset.earliest_season
      : `${dataset.earliest_season} – ${dataset.latest_season}`)
    : null;

  return (
    <Panel
      variant="card"
      padded
      icon={<Database size={15} />}
      eyebrow={dataset.name}
      action={
        <span className="siq-data-source-tag">
          <span className="ds-note">Source</span>
          <Badge tone="accent" variant="outline" size="sm">{dataset.source}</Badge>
        </span>
      }
    >
      <div className="siq-data-card-body">
        {failed ? (
          <Alert tone="warning" title="Currently unavailable" icon={<TriangleAlert size={15} />}>
            {dataset.caveat}
          </Alert>
        ) : (
          <>
            <span className="ds-eyebrow">Coverage</span>
            {stats.length > 0 ? (
              <div className="siq-data-stat-row">
                {stats.map((s) => <StatTile key={s.label} label={s.label} value={s.value} size="sm" />)}
              </div>
            ) : (
              <p className="ds-note">No coverage facts tracked for this dataset.</p>
            )}
            {seasonRange && <p className="ds-note siq-data-season-range">Seasons on file: {seasonRange}</p>}
            {dataset.record_count === 0 && <p className="ds-note">No rows on file yet.</p>}
            {dataset.source_breakdown.length > 0 && (
              <p className="ds-note">{dataset.source_breakdown.map((b) => `${b.source} ${b.count}`).join(' · ')}</p>
            )}

            <span className="ds-eyebrow siq-data-freshness-label">Last updated</span>
            <FreshnessFact dataset={dataset} />

            <p className="ds-note siq-data-caveat">{dataset.caveat}</p>
          </>
        )}
      </div>
    </Panel>
  );
}

export default function DataProvenancePage() {
  const [retryCount, setRetryCount] = useState(0);
  const { data, loading, error } = useApi<ProvenanceResponse>(
    (signal) => getDataProvenance(signal),
    [retryCount],
    { fallback: 'Failed to load data provenance.' },
  );

  return (
    <div className="siq-stack">
      <header className="siq-data-heading">
        <span className="ds-eyebrow">Where ScoutIQ&apos;s data comes from</span>
        <h1>Data provenance center</h1>
        <p>
          Source, coverage, and freshness for every dataset behind the model — not a data-quality
          guarantee. A missing timestamp means no ingestion date is stored for that dataset, never
          that the data is stale or current.
        </p>
      </header>

      {error && (
        <Alert tone="negative" icon={<TriangleAlert size={16} />}>
          {error} — is the FastAPI server running?{' '}
          <Button size="sm" variant="secondary" onClick={() => setRetryCount((v) => v + 1)}>Retry</Button>
        </Alert>
      )}

      {loading && !data && !error && <LoadingNote>Loading data provenance…</LoadingNote>}

      {!loading && !error && data && data.datasets.length === 0 && (
        <EmptyState
          title="No datasets reported."
          description="The data-provenance endpoint returned no records."
        />
      )}

      {data && data.datasets.length > 0 && (
        <>
          <p className="ds-note siq-data-generated">
            {data.data_as_of_utc ? `Data as of ${fmtDateTime(data.data_as_of_utc)}` : 'Freshness not tracked'}
          </p>
          <div className="siq-data-grid">
            {data.datasets.map((dataset) => <DatasetCard key={dataset.key} dataset={dataset} />)}
          </div>
          <Alert tone="neutral">{data.caveat}</Alert>
        </>
      )}
    </div>
  );
}
