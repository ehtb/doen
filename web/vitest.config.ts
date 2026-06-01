import { defineConfig } from "vitest/config";

// Unit tests for browser-local logic (spec uvama). fake-indexeddb/auto installs a working
// IndexedDB into the Node test environment so the conversation store runs unmodified.
export default defineConfig({
  test: {
    environment: "node",
    setupFiles: ["fake-indexeddb/auto"],
    include: ["lib/**/*.test.ts"],
  },
});
