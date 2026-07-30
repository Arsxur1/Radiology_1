// Линейный график временного ряда (inline SVG, без зависимостей).
// Визуализация динамики находки (FR-7) — не источник истины, только отображение.

export interface LinePoint {
  label: string; // подпись по оси X (напр. дата)
  value: number;
}

export function LineChart({ points, unit = "" }: { points: LinePoint[]; unit?: string }) {
  const W = 520;
  const H = 200;
  const pad = { l: 48, r: 16, t: 16, b: 36 };
  const iw = W - pad.l - pad.r;
  const ih = H - pad.t - pad.b;

  if (points.length === 0) return <div className="muted">Нет данных</div>;

  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;

  const x = (i: number) => pad.l + (points.length === 1 ? iw / 2 : (i / (points.length - 1)) * iw);
  const y = (v: number) => pad.t + ih - ((v - min) / span) * ih;

  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="График динамики">
      {/* оси */}
      <line x1={pad.l} y1={pad.t} x2={pad.l} y2={pad.t + ih} stroke="#2a323d" />
      <line x1={pad.l} y1={pad.t + ih} x2={pad.l + iw} y2={pad.t + ih} stroke="#2a323d" />
      {/* подписи min/max по Y */}
      <text x={pad.l - 6} y={pad.t + 4} textAnchor="end" fill="#97a3b4" fontSize="11">
        {max}
        {unit}
      </text>
      <text x={pad.l - 6} y={pad.t + ih} textAnchor="end" fill="#97a3b4" fontSize="11">
        {min}
        {unit}
      </text>
      {/* линия */}
      <path d={path} fill="none" stroke="#3b82f6" strokeWidth="2" />
      {/* точки и подписи X */}
      {points.map((p, i) => (
        <g key={i}>
          <circle cx={x(i)} cy={y(p.value)} r="3.5" fill="#3b82f6" />
          <text x={x(i)} y={pad.t + ih + 16} textAnchor="middle" fill="#97a3b4" fontSize="10">
            {p.label}
          </text>
        </g>
      ))}
    </svg>
  );
}
