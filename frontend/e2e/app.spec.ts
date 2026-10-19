import { expect, test } from "@playwright/test";

// Die Tests laufen in fester Reihenfolge gegen eine Demo-Datenbank (scripts/e2e_server.py).
test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }) => {
  page.on("pageerror", (e) => { throw e; });  // jeder JavaScript-Fehler lässt den Test scheitern
});

test("Übersicht zeigt Kennzahlen, Pipeline und Demo-Hinweis", async ({ page }) => {
  await page.goto("/#/dashboard");
  await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
  await expect(page.locator(".kpi").first()).toContainText("Dateien erfasst");
  await expect(page.getByText("Read-only", { exact: false })).toBeVisible();
  await expect(page.getByText("Demo-Daten.", { exact: false })).toBeVisible();
});

test("Explorer: Suche, Detail mit Seiten-Miniaturen, Filter und Ansichten", async ({ page }) => {
  await page.goto("/#/explorer");
  await page.getByPlaceholder("Suche in Name, Pfad, Inhalt").fill("Mietvertrag");
  const row = page.locator("tr", { hasText: "Mietvertrag_Lindenstr_12.pdf" }).first();
  await expect(row).toBeVisible();
  await row.click();
  const detail = page.locator(".detail");
  await expect(detail).toContainText("Wohnen & Miete");
  await expect(detail.locator(".page-thumb img").first()).toBeVisible();
  await expect(detail.locator(".tabs")).toContainText("Duplikate (1)");
  // Seitenansicht: alle Seiten als Miniaturen
  await page.getByRole("button", { name: "Seiten", exact: true }).click();
  await expect(page.locator(".pv-strip img").first()).toBeVisible();
  // Filter „ähnliche Dateien“
  await page.getByPlaceholder("Suche in Name, Pfad, Inhalt").fill("");
  await page.getByRole("button", { name: "Liste" }).click();
  await page.locator("select", { hasText: "Ähnliche: alle" }).selectOption("Versionen");
  await expect(page.locator("tbody tr", { hasText: "Angebot_Lagerregale" }).first()).toBeVisible();
});

test("Ähnliche Dateien: Gruppen mit Empfehlung", async ({ page }) => {
  await page.goto("/#/similar");
  await expect(page.locator(".sim-group").first()).toBeVisible();
  await expect(page.locator(".sim-card.best").first()).toBeVisible();
  await expect(page.getByText("Angebot_Lagerregale_final.pdf").first()).toBeVisible();
});

test("Vorschlag freigeben, Trockenlauf und Export", async ({ page, request }) => {
  await page.goto("/#/proposal");
  await expect(page.getByText("Neue Cloud-Struktur")).toBeVisible();
  await page.getByRole("button", { name: "Ordner freigeben" }).click();
  await page.goto("/#/copy");
  await expect(page.getByText("Bereit zum Kopieren")).toBeVisible();
  await page.getByRole("button", { name: "Trockenlauf" }).click();
  await expect(page.getByText("Trockenlauf – es wurde nichts kopiert")).toBeVisible({ timeout: 30_000 });
  const xlsx = await request.get("/api/export/vorschlag.xlsx");
  expect(xlsx.status()).toBe(200);
  expect((await xlsx.body()).subarray(0, 2).toString()).toBe("PK");
});

test("Einrichtungs-Assistent: Schritte und Prüfung (ohne zu speichern)", async ({ page }) => {
  await page.goto("/#/setup");
  await expect(page.getByText("Dieser Computer").first()).toBeVisible();
  await page.locator("button.btn.primary", { hasText: "Weiter" }).click();
  await page.getByRole("button", { name: "Computer hinzufügen" }).click();
  await page.getByPlaceholder("Name, z. B. Laptop").fill("Laptop");
  await page.locator("button.btn.primary", { hasText: "Weiter" }).click();
  await expect(page.getByText("Zielordner für die neue Struktur")).toBeVisible();
  await page.locator("button.btn.primary", { hasText: "Weiter" }).click();
  await expect(page.getByText("Zusammenfassung")).toBeVisible();
  await expect(page.getByText("Laptop").first()).toBeVisible();
  await page.getByRole("button", { name: "Datensicherung" }).click();
  await page.getByRole("button", { name: "Jetzt sichern" }).click();
  await expect(page.locator("table").getByText("manuell").first()).toBeVisible({ timeout: 20_000 });
});

test("Programme, Automatik und Einstellungen öffnen ohne Fehler", async ({ page }) => {
  for (const [route, text] of [["programs", "Programme & LLM-Lösungen"], ["automation", "Zeitplan"], ["settings", "Zugang & Sicherheit"],
                               ["sources", "Quellen"]]) {
    await page.goto(`/#/${route}`);
    await expect(page.getByText(text).first()).toBeVisible();
  }
});

test("Navigation einklappen bleibt gespeichert, Dunkelmodus schaltet um", async ({ page }) => {
  await page.goto("/#/dashboard");
  await page.locator(".side .collapse-btn").click();
  await expect(page.locator(".app")).toHaveClass(/collapsed/);
  await page.reload();
  await expect(page.locator(".app")).toHaveClass(/collapsed/);
  await page.locator(".side .collapse-btn").click();
  await page.getByTitle("Hell/Dunkel").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", /dark|light/);
});

test("Handy-Breite: kein waagrechtes Scrollen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const route of ["dashboard", "explorer", "similar", "proposal", "copy", "setup", "sources", "automation", "programs", "settings"]) {
    await page.goto(`/#/${route}`);
    await page.waitForTimeout(500);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `waagrechtes Scrollen auf ${route}`).toBeLessThanOrEqual(1);
  }
});

test("Anmeldung: erstes Konto, falsches Passwort, Abmelden", async ({ page, request }) => {
  // Läuft zuletzt: ab jetzt ist die Anmeldung für alle Pflicht
  const r = await request.post("/api/auth/bootstrap", { data: { username: "andreas", password: "sehr-geheim-123" }, headers: { "X-FDV-Request": "1" } });
  expect(r.status()).toBe(200);
  await page.context().clearCookies();
  await page.goto("/#/dashboard");
  await expect(page.getByRole("button", { name: "Anmelden" })).toBeVisible();
  await page.locator('input[autocomplete="username"]').fill("andreas");
  await page.locator('input[type="password"]').fill("falsch-falsch");
  await page.getByRole("button", { name: "Anmelden" }).click();
  await expect(page.getByText("Benutzername oder Passwort falsch")).toBeVisible();
  await page.locator('input[type="password"]').fill("sehr-geheim-123");
  await page.getByRole("button", { name: "Anmelden" }).click();
  await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
  await page.getByRole("button", { name: "andreas" }).click();
  await page.getByText("Abmelden").click();
  await expect(page.getByRole("button", { name: "Anmelden" })).toBeVisible();
});
