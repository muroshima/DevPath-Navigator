import { expect, test, type Page } from "@playwright/test";

// E2E coverage for the responsive sidebar work introduced in #44 (and
// captured as a follow-up in #45). The layout has two distinct modes:
//
//   - Desktop (>= 768px): in-flow aside next to the map, with a draggable
//     resize handle, localStorage-persisted width, double-click reset to
//     440px, and keyboard control via arrow keys.
//   - Mobile (< 768px): aside collapses into a FAB-triggered drawer
//     (role="dialog"). Escape closes it, and crossing the breakpoint while
//     it's open auto-closes the drawer.
//
// API routes are mocked so the page renders without a live agent or GCP
// credentials, matching the pattern in profile-flow.spec.ts.

const MAP_FIXTURE = {
  points: [
    { employee_id: "E001", x: -1.0, y: 0.5, cluster_id: 0, archetype: "backend_to_sre" },
    { employee_id: "E002", x: -0.9, y: 0.4, cluster_id: 0, archetype: "backend_to_sre" },
    { employee_id: "E003", x: 1.0, y: -0.5, cluster_id: 1, archetype: "ml_to_genai" },
    { employee_id: "E004", x: 1.1, y: -0.6, cluster_id: 1, archetype: "ml_to_genai" },
  ],
  clusters: [
    {
      cluster_id: 0,
      size: 2,
      dominant_archetype: "backend_to_sre",
      archetype_purity: 1.0,
      centroid_x: -0.95,
      centroid_y: 0.45,
    },
    {
      cluster_id: 1,
      size: 2,
      dominant_archetype: "ml_to_genai",
      archetype_purity: 1.0,
      centroid_x: 1.05,
      centroid_y: -0.55,
    },
  ],
};

async function mockApis(page: Page) {
  await page.route("**/api/map", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MAP_FIXTURE),
    });
  });
  // The drawer / resize tests never submit the form, but stub the chat
  // route too so an accidental click doesn't hang on a real network.
  await page.route("**/api/chat", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        session_id: "e2e",
        response: "",
        tool_calls: [],
        tool_results: [],
      }),
    });
  });
}

// In-flow desktop aside vs the mobile drawer aside need distinct selectors
// because both are `<aside>`. The desktop one has the shrink-0 class from
// the resizable layout; the mobile one carries role="dialog".
const DESKTOP_ASIDE = 'aside.shrink-0';
const MOBILE_DRAWER = 'aside[role="dialog"]';
const RESIZE_HANDLE = '[role="separator"][aria-orientation="vertical"]';

test.describe("Desktop: resizable sidebar", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("drag resize updates width and persists to localStorage", async ({ page }) => {
    await mockApis(page);
    await page.goto("/");

    const handle = page.locator(RESIZE_HANDLE);
    await expect(handle).toBeVisible();

    const aside = page.locator(DESKTOP_ASIDE);
    await expect(aside).toHaveCSS("width", "440px");

    // The aside is right-anchored, so dragging the handle LEFT widens
    // the sidebar. 100px move → 540px wide.
    const box = await handle.boundingBox();
    if (!box) throw new Error("resize handle has no bounding box");
    const startX = box.x + box.width / 2;
    const startY = box.y + box.height / 2;
    await page.mouse.move(startX, startY);
    await page.mouse.down();
    await page.mouse.move(startX - 100, startY, { steps: 10 });
    await page.mouse.up();

    await expect(aside).toHaveCSS("width", "540px");
    const stored = await page.evaluate(() => window.localStorage.getItem("devpath:sidebarWidth"));
    expect(stored).toBe("540");
  });

  test("double-click resets the sidebar to the 440px default", async ({ page }) => {
    // Seed localStorage so the page boots with a non-default width and we
    // can prove the dblclick actually changed something.
    await page.addInitScript(() => {
      window.localStorage.setItem("devpath:sidebarWidth", "600");
    });
    await mockApis(page);
    await page.goto("/");

    const aside = page.locator(DESKTOP_ASIDE);
    await expect(aside).toHaveCSS("width", "600px");

    await page.locator(RESIZE_HANDLE).dblclick();

    await expect(aside).toHaveCSS("width", "440px");
    const stored = await page.evaluate(() => window.localStorage.getItem("devpath:sidebarWidth"));
    expect(stored).toBe("440");
  });

  test("ArrowLeft on the focused handle widens the sidebar and updates aria-valuenow", async ({
    page,
  }) => {
    await mockApis(page);
    await page.goto("/");

    const handle = page.locator(RESIZE_HANDLE);
    await handle.focus();
    await expect(handle).toBeFocused();

    // The hook's keyboard step is 24px. ArrowLeft widens (aside is right-
    // anchored, so "left" = "bigger sidebar"), so 440 + 24 = 464.
    await page.keyboard.press("ArrowLeft");

    const aside = page.locator(DESKTOP_ASIDE);
    await expect(aside).toHaveCSS("width", "464px");
    await expect(handle).toHaveAttribute("aria-valuenow", "464");
  });
});

test.describe("Mobile: drawer", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("loads with the FAB only — the drawer aside is not in the DOM", async ({ page }) => {
    await mockApis(page);
    await page.goto("/");

    await expect(page.getByRole("button", { name: "サイドバーを開く" })).toBeVisible();
    // The drawer is conditionally rendered; when closed it is removed
    // from the tree (not just hidden), so a count of 0 is the right
    // assertion.
    await expect(page.locator(MOBILE_DRAWER)).toHaveCount(0);
    // And on the mobile breakpoint the desktop in-flow aside is not
    // rendered at all.
    await expect(page.locator(DESKTOP_ASIDE)).toHaveCount(0);
  });

  test("tapping the FAB opens the drawer; Escape closes it", async ({ page }) => {
    await mockApis(page);
    await page.goto("/");

    await page.getByRole("button", { name: "サイドバーを開く" }).click();

    const drawer = page.locator(MOBILE_DRAWER);
    await expect(drawer).toBeVisible();
    await expect(drawer).toHaveAttribute("aria-modal", "true");

    await page.keyboard.press("Escape");
    await expect(drawer).toHaveCount(0);
  });
});

test("resizing the viewport from mobile to desktop closes an open drawer", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApis(page);
  await page.goto("/");

  await page.getByRole("button", { name: "サイドバーを開く" }).click();
  const drawer = page.locator(MOBILE_DRAWER);
  await expect(drawer).toBeVisible();

  await page.setViewportSize({ width: 1440, height: 900 });

  // The drawer should unmount once isMobile flips to false.
  await expect(drawer).toHaveCount(0);
  // And the in-flow desktop aside should appear in its place.
  await expect(page.locator(DESKTOP_ASIDE)).toBeVisible();
});
