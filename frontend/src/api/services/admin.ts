import { api } from "../../lib/api";
import type {
  AdminClock,
  AdminOverview,
  AdminUser,
  AdminUserCreate,
  AdminUserPage,
  AdminUserQuery,
  AdminUserReject,
  AdminUserUpdate,
  AssumptionsDoc,
  AuditPage,
  AuditQuery,
  DataSummary,
  DriftReport,
  JobKind,
  JobList,
  JobOut,
  LlmLogPage,
  LlmLogQuery,
  LlmUsage,
  ModelRegistry,
  OrgDirectory,
  TickRequestOut,
} from "../types";

export async function getAdminOverview(): Promise<AdminOverview> {
  return (await api.get<AdminOverview>("/admin/overview")).data;
}

export async function getAdminClock(): Promise<AdminClock> {
  return (await api.get<AdminClock>("/admin/clock")).data;
}

export async function requestTick(): Promise<TickRequestOut> {
  return (await api.post<TickRequestOut>("/admin/clock/tick")).data;
}

export async function listAdminUsers(params: AdminUserQuery = {}): Promise<AdminUserPage> {
  return (await api.get<AdminUserPage>("/admin/users", { params })).data;
}

export async function createAdminUser(body: AdminUserCreate): Promise<AdminUser> {
  return (await api.post<AdminUser>("/admin/users", body)).data;
}

export async function updateAdminUser(id: string, body: AdminUserUpdate): Promise<AdminUser> {
  return (await api.patch<AdminUser>(`/admin/users/${id}`, body)).data;
}

export async function rejectAdminUser(id: string, body: AdminUserReject): Promise<AdminUser> {
  return (await api.post<AdminUser>(`/admin/users/${id}/reject`, body)).data;
}

export async function getOrg(): Promise<OrgDirectory> {
  return (await api.get<OrgDirectory>("/admin/org")).data;
}

export async function listAudit(params: AuditQuery = {}): Promise<AuditPage> {
  return (await api.get<AuditPage>("/admin/audit-log", { params })).data;
}

export async function getDataSummary(): Promise<DataSummary> {
  return (await api.get<DataSummary>("/admin/data")).data;
}

export async function getAssumptions(): Promise<AssumptionsDoc> {
  return (await api.get<AssumptionsDoc>("/admin/data/assumptions")).data;
}

export async function getModels(): Promise<ModelRegistry> {
  return (await api.get<ModelRegistry>("/admin/models")).data;
}

export async function getDrift(): Promise<DriftReport> {
  return (await api.get<DriftReport>("/admin/drift")).data;
}

export async function listJobs(): Promise<JobList> {
  return (await api.get<JobList>("/admin/jobs")).data;
}

export async function startJob(kind: JobKind): Promise<JobOut> {
  return (await api.post<JobOut>("/admin/jobs", { kind })).data;
}

export async function listLlmLogs(params: LlmLogQuery = {}): Promise<LlmLogPage> {
  return (await api.get<LlmLogPage>("/admin/llm/logs", { params })).data;
}

export async function getLlmUsage(days: number): Promise<LlmUsage> {
  return (await api.get<LlmUsage>("/admin/llm/usage", { params: { days } })).data;
}
