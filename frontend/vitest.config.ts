import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Тесты интерфейса: элементы, связанные с безопасностью (docs/YUZABILITI.md, п. 2).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.tsx"],
    restoreMocks: true,
  },
});
