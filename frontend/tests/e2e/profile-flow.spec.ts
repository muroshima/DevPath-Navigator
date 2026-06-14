import { expect, test } from "@playwright/test";

// End-to-end smoke for the simple-mode profile → chat → tool-log flow.
//
// The dev server (`next dev`) double-mounts components under React Strict
// Mode, which races with Playwright's keystroke input and leaves the
// submit button stuck on its initial validation. The test runs against
// the production build via `npm run build && npm run start` (see
// playwright.config.ts) which avoids that path.
//
// Both API routes are mocked — the test does not need GCP credentials
// or a live agent.

const MAP_FIXTURE = {
  // Two clusters, six points — enough for the map to render without
  // SVG errors. The test doesn't assert on the map itself.
  points: [
    { employee_id: "E001", x: -1.0, y: 0.5, cluster_id: 0, archetype: "backend_to_sre" },
    { employee_id: "E002", x: -0.9, y: 0.4, cluster_id: 0, archetype: "backend_to_sre" },
    { employee_id: "E003", x: -0.8, y: 0.6, cluster_id: 0, archetype: "backend_to_sre" },
    { employee_id: "E004", x: 1.0, y: -0.5, cluster_id: 1, archetype: "ml_to_genai" },
    { employee_id: "E005", x: 0.9, y: -0.4, cluster_id: 1, archetype: "ml_to_genai" },
    { employee_id: "E006", x: 1.1, y: -0.6, cluster_id: 1, archetype: "ml_to_genai" },
  ],
  clusters: [
    {
      cluster_id: 0,
      size: 3,
      dominant_archetype: "backend_to_sre",
      archetype_purity: 1.0,
      centroid_x: -0.9,
      centroid_y: 0.5,
    },
    {
      cluster_id: 1,
      size: 3,
      dominant_archetype: "ml_to_genai",
      archetype_purity: 1.0,
      centroid_x: 1.0,
      centroid_y: -0.5,
    },
  ],
};

const CHAT_FIXTURE = {
  session_id: "e2e-session",
  response:
    "あなたのプロフィールは ml_to_genai に近いクラスタにいます。" +
    "似た軌跡を歩んだエンジニアの 11 名が GenAI Engineer に進んでいます。",
  tool_calls: [
    { name: "normalize_profile", args: { steps_roles: [["backend"]] } },
    { name: "locate_user", args: { steps_roles: [["backend"]] } },
    { name: "recommend_next_steps", args: { steps_roles: [["backend"]] } },
  ],
  tool_results: [
    {
      name: "normalize_profile",
      response: { corrections: { tech: {}, roles: {} } },
    },
    {
      name: "locate_user",
      response: { cluster_id: 1, dominant_archetype: "ml_to_genai" },
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
              { employee_id: "E004", trajectory: "ml_engineer(2y) → genai_engineer" },
            ],
          },
        ],
      },
    },
  ],
};

test("simple-mode profile submit surfaces tool log and GenAI response", async ({ page }) => {
  // Mock both API routes BEFORE navigating so the page never reaches a
  // real backend.
  await page.route("**/api/map", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MAP_FIXTURE),
    });
  });
  await page.route("**/api/chat", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(CHAT_FIXTURE),
    });
  });

  await page.goto("/");

  // Simple mode is the default. The textarea's placeholder starts with
  // "例: backend" — anchored on that prefix so future copy edits to the
  // rest of the placeholder don't break the test.
  const textarea = page.getByPlaceholder(/例: backend/);
  await expect(textarea).toBeVisible();

  const PROFILE_TEXT =
    "backend を 5 年（Java, Postgres, Go, Kubernetes）。SRE 寄りに進みたい。";
  await textarea.focus();
  await page.keyboard.insertText(PROFILE_TEXT);
  await expect(textarea).toHaveValue(PROFILE_TEXT);

  const submit = page.getByRole("button", {
    name: "現在地を特定して次の一手を提案",
  });
  await expect(submit).toBeEnabled();
  await submit.click();

  // Three tool calls land in the inference log. Each entry in ToolLog
  // renders as a <button> whose accessible name starts with the tool
  // name. Anchor on `name: /^toolname/` so we don't accidentally
  // collide with the user's echoed prompt or the agent prose — both
  // can contain the same tool-name strings.
  await expect(
    page.getByRole("button", { name: /^normalize_profile/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /^locate_user/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /^recommend_next_steps/ }),
  ).toBeVisible();

  // The agent's text response should appear. Match the distinguishing
  // word "GenAI" rather than the whole sentence — future copy edits
  // can change phrasing without breaking the test. `.first()` picks
  // any of the matches (user echo, tool args, agent prose all mention
  // the term).
  await expect(page.getByText(/GenAI/).first()).toBeVisible();
});
