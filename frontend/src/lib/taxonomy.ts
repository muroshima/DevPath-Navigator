// Mirror of data-gen/taxonomy.yaml v1 (frozen 2026-06-10).
// Keep this file in sync with the backend taxonomy file — both are consumed
// from a single source in production, but the frontend doesn't need YAML
// parsing for a dropdown.

export const ROLES = [
  "backend",
  "frontend",
  "fullstack",
  "mobile",
  "sre",
  "platform",
  "data_engineer",
  "ml_engineer",
  "genai_engineer",
  "security",
  "em",
  "pm",
] as const;

export const SENIORITY = ["junior", "mid", "senior", "staff", "manager"] as const;

export const TECH_BY_CATEGORY: Record<string, string[]> = {
  lang: ["java", "kotlin", "python", "typescript", "javascript", "go", "rust", "scala", "ruby", "swift", "csharp"],
  web: ["react", "nextjs", "vue", "nodejs", "rails", "django", "fastapi", "spring", "dotnet", "graphql"],
  infra: ["kubernetes", "docker", "terraform", "ansible", "gcp", "aws", "azure", "linux", "helm"],
  data: ["postgres", "mysql", "mongodb", "redis", "kafka", "snowflake", "bigquery", "dbt", "airflow", "spark"],
  ml: ["pytorch", "tensorflow", "scikit_learn", "huggingface", "langchain", "vertex_ai", "mlflow"],
  mobile: ["react_native", "flutter", "swift_ui", "jetpack_compose"],
  security: ["oauth", "owasp", "iam", "vault"],
};

export const ALL_TECH_TOKENS: string[] = Object.entries(TECH_BY_CATEGORY).flatMap(
  ([cat, items]) => items.map((item) => `${cat}.${item}`),
);
