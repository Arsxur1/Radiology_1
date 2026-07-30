// Баннер режима работы (ТЗ, раздел 2). В RESEARCH/SHADOW явно маркирует
// «не для клинического применения».

import type { OperatingMode } from "../api/types";

const TEXT: Record<OperatingMode, string> = {
  RESEARCH: "Режим RESEARCH — не для клинического применения",
  SHADOW: "Режим SHADOW — результаты моделей врачу не отображаются",
  ASSIST: "Режим ASSIST — результаты ИИ являются черновиком и требуют подтверждения врача",
};

export function ModeBanner({ mode }: { mode: OperatingMode }) {
  return <div className={`mode-banner mode-${mode}`}>{TEXT[mode]}</div>;
}
