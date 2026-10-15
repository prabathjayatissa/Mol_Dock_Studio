import { existsSync } from "node:fs";
import { resolve } from "node:path";

import { expect, test } from "@playwright/test";

/**
 * Phase 1 acceptance test.
 *
 * It boots both servers, creates a project, imports a *real* PDB file from the
 * repository's redistributable reference set, and checks that the number of
 * atoms the viewer reports equals the number in the file. It then takes a
 * screenshot for the documentation.
 *
 * Deliberately no network: the fixture is `backend/app/data/1UBQ.pdb`.
 */

const REFERENCE_PDB = resolve(__dirname, "../../backend/app/data/1UBQ.pdb");

test.describe("MolDock Studio — Phase 1 acceptance", () => {
  test.skip(!existsSync(REFERENCE_PDB), `Missing reference file ${REFERENCE_PDB}. Run: cd backend && .venv/bin/python -m app.cli fetch-test-data`);

  test("import ubiquitin, render it and report its true atom count", async ({ page }) => {
    await page.goto("/");

    // The shell loads.
    await expect(page.getByRole("heading", { name: "MolDock Studio" })).toBeVisible();

    // The backend becomes reachable (health poll).
    await expect(page.getByText(/Backend ready|Connecting/).first()).toBeVisible();

    // Create a project.
    await page.getByPlaceholder("New project name").fill("Acceptance");
    await page.getByRole("button", { name: "Create" }).click();

    // Open the import dialog (only enabled once a project exists).
    await page.getByRole("button", { name: "Import", exact: true }).first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    await dialog.locator('input[type="file"]').setInputFiles(REFERENCE_PDB);
    await dialog.getByRole("button", { name: "Import", exact: true }).click();

    // The import result names the structure and reports its atom count.
    await expect(dialog.getByText(/Imported/)).toBeVisible({ timeout: 120_000 });

    // Close the dialog.
    await dialog.getByRole("button", { name: "Done" }).click();

    // The status bar reflects the loaded structure: 1UBQ has 660 atoms.
    await expect(page.getByText(/660 atoms/)).toBeVisible({ timeout: 60_000 });

    // A WebGL canvas exists.
    await expect(page.locator("canvas").first()).toBeVisible();

    // Leave a figure behind for the docs.
    await page.screenshot({ path: "e2e/artifacts/acceptance.png", fullPage: false });
  });
});
