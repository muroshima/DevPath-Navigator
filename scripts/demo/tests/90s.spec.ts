import { expect, test } from "@playwright/test";
import { CHAT_FIXTURE, EVAL_HISTORY_FIXTURE, MAP_FIXTURE } from "./fixtures";

// The 90-second submission walk-through is recorded as TWO separate
// Playwright tests, one per page:
//
//   1. `90s home → tool log → hover`   (~30s)
//   2. `90s dashboard tour`             (~45s)
//
// Why split? Playwright's `recordVideo` writes one .webm per Page, and
// when the same Page does a hard navigation to another URL on the same
// origin (clicking <a href> / page.goto), the resulting video only
// contains frames from the first URL — the new URL renders correctly
// for assertions but doesn't appear in the recording. Two tests give
// us two clean videos that `render.py` concatenates before muxing
// audio, sidestepping the bug entirely.

test.beforeEach(async ({ page }) => {
  await page.route("**/api/map", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MAP_FIXTURE),
    }),
  );
  await page.route("**/api/chat", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(CHAT_FIXTURE),
    }),
  );
  await page.route("**/api/eval-history**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(EVAL_HISTORY_FIXTURE),
    }),
  );
});

test("90s part 1: home → tool log → hover", async ({ page }) => {
  // ── 00:00 — 00:11 : title + map ──────────────────────────────────────
  await page.goto("/");
  await expect(page.getByText("あなたのキャリア")).toBeVisible();
  await page.waitForTimeout(7500);

  // ── 00:11 — 00:20 : type profile, submit (cue 1 plays) ───────────────
  const textarea = page.getByPlaceholder(/例: backend/);
  await textarea.focus();
  await page.keyboard.type(
    "backend を 5 年（Java、Postgres、Go、Kubernetes）。",
    { delay: 110 },
  );
  await page.waitForTimeout(700);
  await page.keyboard.type("SRE 寄りに進みたい。", { delay: 110 });
  const submit = page.getByRole("button", {
    name: "現在地を特定して次の一手を提案",
  });
  await submit.click();
  await expect(
    page.getByRole("button", { name: /^recommend_next_steps/ }),
  ).toBeVisible();
  await page.waitForTimeout(2500);

  // ── 00:20 — 00:30 : focus the first recommendation arrow ─────────────
  // Dwell long enough that the cue describing the hover behavior
  // (~9s, starting at ~20s in the combined video) finishes before the
  // tab switch. Otherwise the viewer hears "推薦パスにカーソルを合わ
  // せると…" while looking at the detailed form.
  const firstPath = page.locator('g[aria-label^="推奨パス 1:"]');
  await expect(firstPath).toBeVisible();
  await firstPath.focus();
  await expect(page.getByText(/次にすること:/)).toBeVisible();
  await page.waitForTimeout(10500);

  // ── 00:30 — 00:38 : show that the detailed mode also exists ──────────
  // Click the 詳細 tab to surface the structured step form. The form
  // renders role / years / seniority / tech-stack picker — viewers see
  // there's an alternative to free-text input for power users.
  await page.getByRole("button", { name: "詳細" }).click();
  await expect(page.getByText("＋ ステップ追加")).toBeVisible();
  await page.waitForTimeout(9500);
});

test("90s part 2: dashboard tour", async ({ page }) => {
  // Dashboard chart + table dwell while cues 4-8 narrate the eval gate
  // story. The combined video lands at ~38s when this clip starts, and
  // cue 8 ends at ~80s — so this clip needs at least 42s of useful
  // content. 40s here plus the navigation + expect overhead lands at
  // ~43s, leaving 1s of silent tail.
  await page.goto("/dashboard");
  await expect(
    page.getByRole("heading", { name: "再学習ダッシュボード", level: 1 }),
  ).toBeVisible();
  await expect(page.getByText("Recall@10 の推移")).toBeVisible();
  await page.waitForTimeout(44000);
});
