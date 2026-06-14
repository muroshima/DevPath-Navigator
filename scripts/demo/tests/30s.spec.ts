import { expect, test } from "@playwright/test";
import { CHAT_FIXTURE, EVAL_HISTORY_FIXTURE, MAP_FIXTURE } from "./fixtures";

// 30-second README hero. The README target stays focused on the
// product's core moment — profile in, recommendations out, hover for
// detail — and intentionally leaves the retrain dashboard for the 90s
// submission video.
//
// Story beats:
//   00:00 – 00:03  Title + map
//   00:03 – 00:15  Type the profile slowly
//   00:15 – 00:18  Submit, watch tool log fill
//   00:18 – end    Focus a recommendation arrow → tooltip stays up

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

test("30s home → tool log → hover", async ({ page }) => {
  // ── 00:00 — 00:03 : title + map ──────────────────────────────────────
  await page.goto("/");
  await expect(page.getByText("あなたのキャリア")).toBeVisible();
  await page.waitForTimeout(3000);

  // ── 00:03 — 00:15 : type the profile slowly ──────────────────────────
  const textarea = page.getByPlaceholder(/例: backend/);
  await textarea.focus();
  await page.keyboard.type(
    "backend を 5 年（Java、Postgres、Go、Kubernetes）。",
    { delay: 110 },
  );
  await page.waitForTimeout(900);
  await page.keyboard.type("SRE 寄りに進みたい。", { delay: 110 });
  await page.waitForTimeout(1200);

  // ── 00:15 — 00:17 : submit, settle on the response ───────────────────
  // Hold here so the tooltip doesn't pop on before cue 2 ("推薦パスに
  // カーソルを合わせると…", starts ~17.5s) has begun. Without this
  // longer wait, the focus call below fires at ~16s and the tooltip
  // appears 1.5s before the narration mentions it.
  const submit = page.getByRole("button", {
    name: "現在地を特定して次の一手を提案",
  });
  await submit.click();
  await expect(
    page.getByRole("button", { name: /^recommend_next_steps/ }),
  ).toBeVisible();
  await page.waitForTimeout(5500);

  // ── 00:17 — 00:25 : focus the first recommendation arrow ─────────────
  // Dwell here for the duration of cue 2 ("推薦パスにカーソルを合わ
  // せると…", ~7s starting at 17.5s).
  const firstPath = page.locator('g[aria-label^="推奨パス 1:"]');
  await expect(firstPath).toBeVisible();
  await firstPath.focus();
  await expect(page.getByText(/次にすること:/)).toBeVisible();
  await page.waitForTimeout(7000);

  // ── 00:25 — end : show that the detailed mode also exists ────────────
  // Click the 詳細 tab so the viewer sees the structured step form is
  // available as an alternative to free-text input. Cue 3 narrates
  // this transition over ~7s starting at 25s.
  await page.getByRole("button", { name: "詳細" }).click();
  await expect(page.getByText("＋ ステップ追加")).toBeVisible();
  await page.waitForTimeout(7500);
});
