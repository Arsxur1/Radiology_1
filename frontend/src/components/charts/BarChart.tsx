// Горизонтальные бары (inline SVG). Для доли отклонений по аппаратам (FR-11).

export interface Bar {
  label: string;
  value: number; // 0..1 (доля)
  caption?: string; // напр. "3/20"
}

export function BarChart({ bars, warnThreshold = 0.15 }: { bars: Bar[]; warnThreshold?: number }) {
  if (bars.length === 0) return <div className="muted">Нет данных</div>;
  const rowH = 30;
  const W = 520;
  const labelW = 150;
  const barW = W - labelW - 60;

  return (
    <svg viewBox={`0 0 ${W} ${bars.length * rowH + 10}`} width="100%" role="img" aria-label="Доля отклонений">
      {bars.map((b, i) => {
        const y = i * rowH + 6;
        const w = Math.max(2, b.value * barW);
        // Выше порога — предупреждающий цвет (сигнал деградации).
        const color = b.value > warnThreshold ? "#b5443b" : "#2f9e5a";
        return (
          <g key={i}>
            <text x={0} y={y + 14} fill="#e6eaf0" fontSize="12">
              {b.label.length > 20 ? b.label.slice(0, 19) + "…" : b.label}
            </text>
            <rect x={labelW} y={y} width={barW} height={18} fill="#171c23" stroke="#2a323d" />
            <rect x={labelW} y={y} width={w} height={18} fill={color} />
            <text x={labelW + barW + 6} y={y + 14} fill="#97a3b4" fontSize="11">
              {(b.value * 100).toFixed(0)}%{b.caption ? ` (${b.caption})` : ""}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
