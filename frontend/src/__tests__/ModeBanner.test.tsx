// Баннер режима на каждом экране (YUZABILITI.md: U-5; R-16).
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ModeBanner } from "../components/ModeBanner";

afterEach(cleanup);

describe("режим работы виден и объяснён", () => {
  it.each([
    ["RESEARCH", "не для клинического применения"],
    ["SHADOW", "результаты моделей врачу не отображаются"],
    ["ASSIST", "требуют подтверждения врача"],
  ] as const)("%s", (mode, text) => {
    render(<ModeBanner mode={mode} />);
    const el = screen.getByText(new RegExp(text));
    expect(el.textContent).toContain(mode);
    expect(el.className).toContain(`mode-${mode}`);
  });
});
