export interface MapPoint {
  employee_id: string;
  x: number;
  y: number;
  cluster_id: number;
  archetype: string | null;
}

export interface MapCluster {
  cluster_id: number;
  size: number;
  dominant_archetype: string | null;
  archetype_purity: number | null;
  centroid_x: number;
  centroid_y: number;
}

export interface MapResponse {
  points: MapPoint[];
  clusters: MapCluster[];
}

export interface ToolCall {
  name: string;
  args?: Record<string, unknown> | null;
}

export interface ToolResult {
  name: string;
  response?: Record<string, unknown> | null;
}

export interface ChatResponse {
  session_id: string;
  response: string;
  tool_calls: ToolCall[];
  tool_results: ToolResult[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "agent";
  text: string;
  toolCalls?: ToolCall[];
  toolResults?: ToolResult[];
}

export interface RoleEntry {
  role: string;
  years: number;
}

export interface Step {
  roles: RoleEntry[];
  techStack: string[];
  seniority: string;
}
