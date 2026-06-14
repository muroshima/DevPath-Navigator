// Shared API mocks for both demo recordings — keeps the visible state
// of the agent deterministic so the videos are reproducible.

export const MAP_FIXTURE = {
  points: [
    // Frontend cohort — left side of map
    { employee_id: "E001", x: -1.2, y: 0.6, cluster_id: 0, archetype: "frontend_to_em" },
    { employee_id: "E002", x: -1.1, y: 0.5, cluster_id: 0, archetype: "frontend_to_em" },
    { employee_id: "E003", x: -1.0, y: 0.7, cluster_id: 0, archetype: "frontend_to_em" },
    { employee_id: "E004", x: -1.3, y: 0.4, cluster_id: 0, archetype: "frontend_to_em" },
    // Backend → SRE cohort — bottom
    { employee_id: "E101", x: 0.2, y: -0.8, cluster_id: 1, archetype: "backend_to_sre" },
    { employee_id: "E102", x: 0.3, y: -0.7, cluster_id: 1, archetype: "backend_to_sre" },
    { employee_id: "E103", x: 0.1, y: -0.9, cluster_id: 1, archetype: "backend_to_sre" },
    { employee_id: "E104", x: 0.4, y: -0.6, cluster_id: 1, archetype: "backend_to_sre" },
    // ML → GenAI cohort — top right
    { employee_id: "E201", x: 1.1, y: 0.5, cluster_id: 2, archetype: "ml_to_genai" },
    { employee_id: "E202", x: 1.2, y: 0.6, cluster_id: 2, archetype: "ml_to_genai" },
    { employee_id: "E203", x: 1.0, y: 0.4, cluster_id: 2, archetype: "ml_to_genai" },
    { employee_id: "E204", x: 1.3, y: 0.7, cluster_id: 2, archetype: "ml_to_genai" },
    // Mobile cohort — top left
    { employee_id: "E301", x: -0.5, y: 1.1, cluster_id: 3, archetype: "mobile_to_backend" },
    { employee_id: "E302", x: -0.4, y: 1.2, cluster_id: 3, archetype: "mobile_to_backend" },
    { employee_id: "E303", x: -0.6, y: 1.0, cluster_id: 3, archetype: "mobile_to_backend" },
    // Data cohort — bottom right
    { employee_id: "E401", x: 0.8, y: -0.3, cluster_id: 4, archetype: "data_to_ml" },
    { employee_id: "E402", x: 0.7, y: -0.4, cluster_id: 4, archetype: "data_to_ml" },
    { employee_id: "E403", x: 0.9, y: -0.2, cluster_id: 4, archetype: "data_to_ml" },
  ],
  clusters: [
    { cluster_id: 0, size: 4, dominant_archetype: "frontend_to_em", archetype_purity: 1.0, centroid_x: -1.15, centroid_y: 0.55 },
    { cluster_id: 1, size: 4, dominant_archetype: "backend_to_sre", archetype_purity: 1.0, centroid_x: 0.25, centroid_y: -0.75 },
    { cluster_id: 2, size: 4, dominant_archetype: "ml_to_genai", archetype_purity: 1.0, centroid_x: 1.15, centroid_y: 0.55 },
    { cluster_id: 3, size: 3, dominant_archetype: "mobile_to_backend", archetype_purity: 1.0, centroid_x: -0.5, centroid_y: 1.1 },
    { cluster_id: 4, size: 3, dominant_archetype: "data_to_ml", archetype_purity: 1.0, centroid_x: 0.8, centroid_y: -0.3 },
  ],
};

// The user's profile lands inside the backend_to_sre cluster
// (cluster_id: 1). The recommendations point toward sre / platform /
// genai paths to make the arrows fan out across the map.
export const CHAT_FIXTURE = {
  session_id: "demo",
  response:
    "あなたの現在地は backend_to_sre クラスタ（cluster 1）です。" +
    "似た軌跡を歩んだ 12 名のエンジニアが platform に、" +
    "9 名が sre に、5 名が GenAI Engineer に進んでいます。" +
    "Kubernetes と Terraform の経験が次の一手の鍵になりそうです。",
  tool_calls: [
    { name: "normalize_profile", args: { steps_roles: [["backend"]], steps_role_years: [[5]] } },
    { name: "locate_user", args: { steps_roles: [["backend"]] } },
    { name: "find_similar_trajectories", args: { steps_roles: [["backend"]] } },
    { name: "recommend_next_steps", args: { steps_roles: [["backend"]] } },
  ],
  tool_results: [
    {
      name: "normalize_profile",
      response: { corrections: { tech: {}, roles: {} } },
    },
    {
      name: "locate_user",
      response: {
        cluster_id: 1,
        dominant_archetype: "backend_to_sre",
        // page.tsx expects `user_x` / `user_y` flat on the response,
        // not a nested `user_xy` object — without these the yellow
        // "you are here" marker doesn't render and the recommendation
        // arrows have no origin to project from.
        user_x: 0.25,
        user_y: -0.6,
        nearest_neighbors: [
          { employee_id: "E101" },
          { employee_id: "E102" },
          { employee_id: "E103" },
          { employee_id: "E104" },
        ],
      },
    },
    {
      name: "find_similar_trajectories",
      response: {
        similar_trajectories: [
          { employee_id: "E101" },
          { employee_id: "E102" },
          { employee_id: "E103" },
          { employee_id: "E104" },
        ],
      },
    },
    {
      name: "recommend_next_steps",
      response: {
        recommendations: [
          {
            next_role: "platform",
            support_count: 12,
            common_new_tech: [
              { tech: "lang.go", count: 9 },
              { tech: "infra.helm", count: 7 },
              { tech: "infra.kubernetes", count: 11 },
            ],
            representative_trajectories: [
              { employee_id: "E101", trajectory: "backend(4y) → backend+platform(1y) → platform" },
              { employee_id: "E102", trajectory: "backend(3y) → platform" },
              { employee_id: "E103", trajectory: "backend(5y) → platform" },
            ],
          },
          {
            next_role: "sre",
            support_count: 9,
            common_new_tech: [
              { tech: "infra.kubernetes", count: 8 },
              { tech: "infra.terraform", count: 6 },
              { tech: "ops.observability", count: 5 },
            ],
            representative_trajectories: [
              { employee_id: "E104", trajectory: "backend(5y) → sre" },
              { employee_id: "E201", trajectory: "backend(3y) → backend+sre(2y) → sre" },
            ],
          },
          {
            next_role: "genai_engineer",
            support_count: 5,
            common_new_tech: [
              { tech: "ml.langchain", count: 4 },
              { tech: "ml.pytorch", count: 3 },
            ],
            representative_trajectories: [
              { employee_id: "E201", trajectory: "backend(3y) → ml_engineer(2y) → genai_engineer" },
            ],
          },
        ],
      },
    },
  ],
};

export const EVAL_HISTORY_FIXTURE = {
  runs: [
    {
      run_id: "c00e836726dc",
      run_at: "2026-06-12T09:32:11Z",
      batches: ["initial", "drift"],
      recall_at_10: 0.812,
      min_recall_per_archetype: 0.78,
      n_clusters: 18,
      mean_archetype_purity: 0.96,
      archetypes_covered: [
        "backend_to_sre",
        "data_to_ml",
        "frontend_to_em",
        "jobhopper",
        "ml_to_genai",
        "mobile_to_backend",
      ],
      vocab_size: 71,
      decision: "pass",
      decision_reasons: [
        "recall@10 ok: 0.812 vs prev 0.744",
        "min recall per archetype ok: 0.780 vs prev 0.640",
      ],
    },
    {
      run_id: "b2a91e4f5d18",
      run_at: "2026-06-11T17:05:42Z",
      batches: ["initial", "drift"],
      recall_at_10: 0.744,
      min_recall_per_archetype: 0.640,
      n_clusters: 17,
      mean_archetype_purity: 0.94,
      archetypes_covered: [
        "backend_to_sre",
        "data_to_ml",
        "frontend_to_em",
        "jobhopper",
        "mobile_to_backend",
      ],
      vocab_size: 69,
      decision: "fail",
      decision_reasons: [
        "archetypes lost from clusters: ['ml_to_genai']",
        "min recall per archetype dropped: 0.640 < 0.820 - 0.15 (worst: ml_to_genai=0.640)",
      ],
    },
    {
      run_id: "a1c45e9b7c33",
      run_at: "2026-06-10T22:18:09Z",
      batches: ["initial"],
      recall_at_10: 0.820,
      min_recall_per_archetype: 0.820,
      n_clusters: 17,
      mean_archetype_purity: 0.94,
      archetypes_covered: [
        "backend_to_sre",
        "data_to_ml",
        "frontend_to_em",
        "jobhopper",
        "mobile_to_backend",
      ],
      vocab_size: 69,
      decision: "baseline",
      decision_reasons: [
        "baseline run (no prior); recall@10 = 0.820",
      ],
    },
  ],
};
