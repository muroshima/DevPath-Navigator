import { expect, test, type Page } from "@playwright/test";

// E2E coverage for #34: navigating to /dashboard and back to / used to wipe
// the chat history, tool log, and map anchor points because the state was
// React-only. The fix in page.tsx mirrors those fields into sessionStorage
// on every change and restores them on mount. These tests prove both
// directions of that round-trip and the reset button that explicitly
// clears the snapshot.

const MAP_FIXTURE = {
  points: [
    { employee_id: "E001", x: -1.0, y: 0.5, cluster_id: 0, archetype: "backend_to_sre" },
    { employee_id: "E002", x: -0.9, y: 0.4, cluster_id: 0, archetype: "backend_to_sre" },
    { employee_id: "E003", x: 1.0, y: -0.5, cluster_id: 1, archetype: "ml_to_genai" },
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
      size: 1,
      dominant_archetype: "ml_to_genai",
      archetype_purity: 1.0,
      centroid_x: 1.0,
      centroid_y: -0.5,
    },
  ],
};

const CHAT_FIXTURE = {
  session_id: "persist-e2e",
  response: "似た軌跡を歩んだエンジニアの 11 名が GenAI Engineer に進んでいます。",
  tool_calls: [
    { name: "normalize_profile", args: { steps_roles: [["backend"]] } },
    { name: "locate_user", args: { steps_roles: [["backend"]] } },
    { name: "recommend_next_steps", args: { steps_roles: [["backend"]] } },
  ],
  tool_results: [
    { name: "normalize_profile", response: { corrections: { tech: {}, roles: {} } } },
    {
      name: "locate_user",
      response: {
        cluster_id: 1,
        dominant_archetype: "ml_to_genai",
        user_x: 1.0,
        user_y: -0.5,
      },
    },
    {
      name: "recommend_next_steps",
      response: {
        recommendations: [
          {
            next_role: "genai_engineer",
            support_count: 11,
            common_new_tech: [{ tech: "ml.langchain", count: 7 }],
            representative_trajectories: [
              { employee_id: "E003", trajectory: "ml_engineer(2y) → genai_engineer" },
            ],
          },
        ],
      },
    },
  ],
};

const EVAL_HISTORY_FIXTURE = {
  records: [
    {
      run_id: "r1",
      ts_utc: "2026-06-15T00:00:00Z",
      batches: ["initial"],
      decision: "baseline",
      recall_at_10: 0.82,
      n_clusters: 12,
      mean_archetype_purity: 1.0,
      archetypes_covered: ["backend_to_sre"],
      reasons: ["baseline"],
    },
  ],
};

async function mockApis(page: Page) {
  await page.route("**/api/map", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MAP_FIXTURE) }),
  );
  await page.route("**/api/chat", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(CHAT_FIXTURE) }),
  );
  await page.route("**/api/eval-history", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(EVAL_HISTORY_FIXTURE),
    }),
  );
}

async function submitProfile(page: Page) {
  const textarea = page.getByPlaceholder(/例: backend/);
  await textarea.focus();
  await page.keyboard.insertText(
    "backend を 5 年（Java, Postgres）。SRE か ML に進みたい。",
  );
  await page.getByRole("button", { name: "現在地を特定して次の一手を提案" }).click();
  // Wait for the chat response to appear so we know the round-trip completed
  // before any navigation happens.
  await expect(page.getByText(/GenAI Engineer/).first()).toBeVisible();
}

test("dashboard round-trip preserves chat history, tool log, and recommended path", async ({ page }) => {
  await mockApis(page);
  await page.goto("/");
  await submitProfile(page);

  // Sanity-check the snapshot is in sessionStorage before we navigate.
  const snapshotBefore = await page.evaluate(() =>
    window.sessionStorage.getItem("devpath:chat:v1"),
  );
  expect(snapshotBefore).toContain("GenAI Engineer");

  // Cross over to /dashboard and back, the way the bug reproduces in the UI.
  await page.getByRole("link", { name: /再学習ダッシュボード/ }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  await page.getByRole("link", { name: /マップに戻る/ }).click();
  await expect(page).toHaveURL(/\/$/);

  // The chat message, the tool-log entries, and the recommendation are all
  // restored from sessionStorage rather than being re-fetched.
  await expect(page.getByText(/GenAI Engineer/).first()).toBeVisible();
  await expect(page.getByRole("button", { name: /^normalize_profile/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /^locate_user/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /^recommend_next_steps/ })).toBeVisible();

  // The "会話履歴 / リセット" header only shows when there's history to clear,
  // so its presence after the round-trip also proves messages.length > 0.
  await expect(page.getByRole("button", { name: "リセット" })).toBeVisible();
});

test("リセット clears messages, tool log, and sessionStorage snapshot", async ({ page }) => {
  await mockApis(page);
  await page.goto("/");
  await submitProfile(page);

  await expect(page.getByRole("button", { name: "リセット" })).toBeVisible();
  await page.getByRole("button", { name: "リセット" }).click();

  // After reset: header (and its リセット button) disappears because
  // messages.length === 0, tool-log entries are gone, and the
  // sessionStorage snapshot reflects the empty state.
  await expect(page.getByRole("button", { name: "リセット" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^normalize_profile/ })).toHaveCount(0);

  const snapshotAfter = await page.evaluate(() =>
    window.sessionStorage.getItem("devpath:chat:v1"),
  );
  expect(snapshotAfter).not.toContain("GenAI Engineer");
});
