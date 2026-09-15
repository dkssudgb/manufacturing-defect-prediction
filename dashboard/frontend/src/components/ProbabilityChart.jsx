function makePoints(records, width, height, padding) {
  if (!records.length) return "";
  const xRange = width - padding * 2;
  const yRange = height - padding * 2;
  return records
    .map((record, index) => {
      const x = padding + (records.length === 1 ? xRange / 2 : (index / (records.length - 1)) * xRange);
      const y = padding + (1 - record.defect_probability) * yRange;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

export function ProbabilityChart({ predictions, threshold, onSelect, emptyMessage }) {
  const records = [...predictions]
    .filter((item) => item.supported && item.defect_probability !== null)
    .reverse();
  const width = 760;
  const height = 214;
  const padding = 18;
  const thresholdY = padding + (1 - threshold) * (height - padding * 2);
  const points = makePoints(records, width, height, padding);

  return (
    <div className="chart-wrap">
      <div className="chart-y-labels" aria-hidden="true"><span>100%</span><span>50%</span><span>0%</span></div>
      <svg className="probability-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="최근 지원 제품의 불량확률 추이">
        <defs>
          <linearGradient id="riskFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#ff7557" stopOpacity="0.28" />
            <stop offset="100%" stopColor="#ff7557" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 0.5, 1].map((value) => {
          const y = padding + value * (height - padding * 2);
          return <line key={value} x1={padding} y1={y} x2={width - padding} y2={y} className="chart-grid" />;
        })}
        <line x1={padding} y1={thresholdY} x2={width - padding} y2={thresholdY} className="threshold-line" />
        <text x={width - padding} y={Math.max(14, thresholdY - 7)} textAnchor="end" className="threshold-label">TH {Math.round(threshold * 100)}%</text>
        {points && <polyline points={`${padding},${height - padding} ${points} ${width - padding},${height - padding}`} fill="url(#riskFill)" stroke="none" />}
        {points && <polyline points={points} fill="none" className="probability-line" />}
        {records.map((record, index) => {
          const x = padding + (records.length === 1 ? (width - padding * 2) / 2 : (index / (records.length - 1)) * (width - padding * 2));
          const y = padding + (1 - record.defect_probability) * (height - padding * 2);
          const risky = record.defect_probability >= threshold;
          const label = `${record.part_name || record.part || record.record_id} · ${Math.round(record.defect_probability * 1000) / 10}%`;
          return (
            <circle
              key={record.event_id || `${record.record_id}-${index}`}
              cx={x}
              cy={y}
              r={risky ? 4.5 : 3.5}
              className={`${risky ? "chart-dot risk" : "chart-dot"}${onSelect ? " clickable" : ""}`}
              onClick={onSelect ? () => onSelect(record.record_id) : undefined}
              tabIndex={onSelect ? 0 : undefined}
              role={onSelect ? "button" : undefined}
              onKeyDown={onSelect ? (event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect(record.record_id);
                }
              } : undefined}
            >
              <title>{label}</title>
            </circle>
          );
        })}
      </svg>
      {!records.length && <div className="chart-empty">{emptyMessage || "지원 제품을 수신하면 확률 추이가 표시됩니다."}</div>}
      <div className="chart-x-note">과거 <span>→</span> 최근</div>
    </div>
  );
}
