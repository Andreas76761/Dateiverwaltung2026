import { defineConfig, devices } from "@playwright/test";

// Oberflächen-Tests gegen die echte App mit Demo-Daten (Server: scripts/e2e_server.py)
export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: "http://127.0.0.1:8899", trace: "retain-on-failure", screenshot: "only-on-failure", locale: "de-DE" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: {
    command: `${process.env.PYTHON || "python3"} ../scripts/e2e_server.py --port 8899`,
    url: "http://127.0.0.1:8899/api/health",
    timeout: 600_000,
    reuseExistingServer: !process.env.CI,
    stdout: "pipe",
  },
});
