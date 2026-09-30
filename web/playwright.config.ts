import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
    // Safari's engine, for faults that only show there. Only e2e/safari.spec.ts runs in it.
    // CI installs WebKit and always runs this. Locally it runs when SPAN_E2E_WEBKIT is set,
    // after `npx playwright install webkit`.
    ...(process.env.CI || process.env.SPAN_E2E_WEBKIT
      ? [{ name: "safari", use: { ...devices["Desktop Safari"] }, testMatch: /safari\.spec\.ts/ }]
      : []),
  ],
  webServer: {
    command: "npm run preview -- --port 4173",
    port: 4173,
    reuseExistingServer: !process.env.CI,
  },
});
