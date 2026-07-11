import { Badge } from '@/components/ui/Badge';
import { TeamNeedsResponse } from '@/lib/api';

function confidenceTone(confidence: TeamNeedsResponse['confidence']): 'confidence' | 'warning' | 'neutral' {
  return confidence === 'high' ? 'confidence' : confidence === 'medium' ? 'warning' : 'neutral';
}

export function RosterNeeds({
  before,
  after,
}: {
  before: TeamNeedsResponse;
  after?: TeamNeedsResponse;
}) {
  const afterByKey = new Map(after?.needs.map((need) => [need.key, need]) ?? []);

  return (
    <div className="siq-needs">
      <div className="siq-needs-meta">
        <span className="ds-tnum">
          {after?.profiled_player_count ?? before.profiled_player_count} of {after?.roster_player_count ?? before.roster_player_count} profiled
        </span>
        <Badge tone={confidenceTone(after?.confidence ?? before.confidence)} variant="outline" size="sm">
          {after?.confidence ?? before.confidence} confidence
        </Badge>
      </div>
      <div className="siq-needs-grid">
        {before.needs.map((need) => {
          const next = afterByKey.get(need.key);
          const display = next ?? need;
          const improvement = next ? Math.max(0, need.deficit_pct - next.deficit_pct) : 0;
          const barWidth = Math.min(100, display.coverage_pct);
          return (
            <div className="siq-need" key={need.key} title={display.caution ?? undefined}>
              <div className="siq-need-head">
                <span>{display.label}</span>
                <span className="ds-tnum">
                  {display.deficit_pct > 0 ? `${display.deficit_pct.toFixed(1)} pt gap` : 'covered'}
                </span>
              </div>
              <div
                className="siq-need-track"
                role="meter"
                aria-label={`${display.label} coverage versus league median`}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.min(100, display.coverage_pct)}
              >
                <span
                  className={`siq-need-fill siq-need-fill--${display.status}`}
                  style={{ width: `${barWidth}%` }}
                />
              </div>
              <div className="siq-need-foot">
                <span className="ds-tnum">{display.coverage_pct.toFixed(1)}% coverage</span>
                {improvement > 0 ? <span className="ds-tnum">+{improvement.toFixed(1)} pts filled</span> : null}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
