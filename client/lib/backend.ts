/**
 * Thin client for the FastAPI backend. All server-side routes use this so the
 * browser never talks directly to FastAPI — keeps secrets server-side and lets
 * us layer auth checks in front of every backend call.
 */
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Backend ${path} returned ${res.status}: ${body.slice(0, 200)}`);
  }
  return res.json() as Promise<T>;
}

export type Role = "ADMIN" | "CLINICIAN" | "PATIENT" | "GUEST";

export type ChatResponse = {
  answer: string;
  blocked: boolean;
  block_reason: string | null;
  trace_id: string;
};

export type AuditLogEntry = {
  trace_id: string;
  user_id: string | null;
  timestamp: string;
  blocked: boolean;
  block_reason: string | null;
  input_security_flag: string | null;
  output_security_flag: string | null;
  is_medical: boolean;
  drugs_identified: string[];
  evidence_count: number;
  final_answer: string | null;
  pipeline_trace?: Array<{
    agent: string;
    action: string;
    summary: string;
    duration_seconds: number;
    error: string | null;
    metadata: Record<string, unknown>;
  }>;
  trail?: Array<Record<string, unknown>>;
  errors?: string[];
  warnings?: string[];
};

export type ProxyStatus = {
  proxy_endpoint: string;
  reachable: boolean;
  http_status: number | null;
  note: string;
};

export type AdminStats = {
  total_queries: number;
  blocked_queries: number;
  allowed_queries: number;
  medical_queries: number;
  queries_with_errors: number;
  unique_users: number;
  total_evidence_rows: number;
  block_breakdown: Record<string, number>;
};

export type Medication = {
  name: string;
  dose: string;
  frequency: string;
  indication: string;
};

export type Patient = {
  id: string;
  display_name: string;
  age: number;
  sex: "M" | "F";
  conditions: string[];
  allergies: string[];
  medications: Medication[];
};

export type PatientSummary = {
  id: string;
  display_name: string;
  age: number;
  sex: "M" | "F";
  medication_count: number;
  primary_condition: string | null;
};

export type UserPublic = {
  id: string;
  email: string;
  name: string;
  role: Role;
  created_at: number;
};

export const backend = {
  // ── Auth — frontend has no DB; these are the source of truth ───────────────
  registerUser: (payload: { email: string; name: string; password: string; role: Role }) =>
    call<UserPublic>("/auth/register", { method: "POST", body: JSON.stringify(payload) }),

  verifyUser: (payload: { email: string; password: string }) =>
    call<UserPublic | null>("/auth/verify", { method: "POST", body: JSON.stringify(payload) }),

  // ── Chat ───────────────────────────────────────────────────────────────────
  chat: (payload: { query: string; user_id: string; thread_id?: string; patient_id?: string }) =>
    call<ChatResponse>("/chat", { method: "POST", body: JSON.stringify(payload) }),

  // ── Admin ──────────────────────────────────────────────────────────────────
  listUsers: () => call<UserPublic[]>("/admin/users"),

  auditLogs: (limit = 50) => call<AuditLogEntry[]>(`/admin/audit-logs?limit=${limit}`),

  stats: () => call<AdminStats>("/admin/stats"),

  proxyStatus: () => call<ProxyStatus>("/health/proxy"),

  // ── Patients ───────────────────────────────────────────────────────────────
  listPatients: () => call<PatientSummary[]>("/patients"),

  getPatient: (id: string) => call<Patient>(`/patients/${encodeURIComponent(id)}`),

  addMedication: (patientId: string, medication: Medication) =>
    call<Patient>(`/patients/${encodeURIComponent(patientId)}/medications`, {
      method: "POST",
      body: JSON.stringify(medication),
    }),

  removeMedication: (patientId: string, medicationName: string) =>
    call<Patient>(
      `/patients/${encodeURIComponent(patientId)}/medications/${encodeURIComponent(
        medicationName,
      )}`,
      { method: "DELETE" },
    ),
};
