// Подмена API для тестов интерфейса: любой метод — заглушка, возвращающая [];
// нужные тесту методы задаются явно. Класс ApiError — настоящий.
import { vi } from "vitest";

export type Fns = Record<string, ReturnType<typeof vi.fn>>;

export function makeApi(fns: Fns): object {
  return new Proxy(
    {},
    {
      get: (_t, key: string) => (fns[key] ??= vi.fn().mockResolvedValue([])),
    },
  );
}

export function setRoles(roles: string): void {
  localStorage.setItem("medviz.debug.subject", "test.user");
  localStorage.setItem("medviz.debug.roles", roles);
}
