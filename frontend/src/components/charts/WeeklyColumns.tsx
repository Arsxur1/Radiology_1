// Недельные столбцы (одна серия, один оттенок). Малые мультипликаторы на панели пилота:
// каждая метрика — свой график с общей осью недель, без второй оси Y.

import { useState } from "react";

const fmtWeek = (iso: string) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`;

export function WeeklyColumns({ title, weeks, values }: { title: string; weeks: string[]; values: number[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 320;
  const H = 120;
  const padL = 26;
  const padB = 18;
  const plotW = W - padL - 4;
  const plotH = H - padB - 8;
  const max = Math.max(1, ...values);
  const step = plotW / Math.max(1, values.length);
  const barW = Math.max(3, step - 2); // 2px зазор между столбцами
  const y = (v: number) => 8 + plotH - (v / max) * plotH;

  return (
    <div style={{ position: "relative" }}>
      <div style={{ fontSize: 13, marginBottom: 4 }}>
        {title}: <strong>{values.reduce((a, b) => a + b, 0)}</strong>
        <span className="muted"> за {weeks.length} нед.</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={title}>
        {[0, max].map((g) => (
          <g key={g}>
            <line x1={padL} x2={W} y1={y(g)} y2={y(g)} stroke="var(--border)" strokeWidth={1} />
            <text x={padL - 4} y={y(g) + 4} fill="var(--muted)" fontSize="10" textAnchor="end">
              {g}
            </text>
          </g>
        ))}
        {values.map((v, i) => {
          const x = padL + i * step + 1;
          const top = y(v);
          const h = 8 + plotH - top;
          const r = Math.min(4, h, barW / 2);
          return (
            <g key={weeks[i]} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              {/* Зона наведения больше столбца. */}
              <rect x={x - 1} y={8} width={step} height={plotH} fill="transparent" />
              {v > 0 && (
                <path
                  d={`M${x},${8 + plotH} V${top + r} Q${x},${top} ${x + r},${top} H${x + barW - r} Q${x + barW},${top} ${x + barW},${top + r} V${8 + plotH} Z`}
                  fill="var(--accent)"
                  opacity={hover === null || hover === i ? 1 : 0.55}
                />
              )}
              {i % 2 === values.length % 2 && (
                <text x={x + barW / 2} y={H - 4} fill="var(--muted)" fontSize="9" textAnchor="middle">
                  {fmtWeek(weeks[i])}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      {hover !== null && (
        <div
          className="card"
          style={{ position: "absolute", top: 24, right: 0, padding: "4px 8px", fontSize: 12, margin: 0 }}
        >
          неделя с {fmtWeek(weeks[hover])}: <strong>{values[hover]}</strong>
        </div>
      )}
    </div>
  );
}
