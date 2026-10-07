import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { qk } from "../keys";
import {
  createAdminUser,
  getAdminClock,
  getAdminOverview,
  getAssumptions,
  getDataSummary,
  getDrift,
  getLlmUsage,
  getModels,
  getOrg,
  listAdminUsers,
  listAudit,
  listJobs,
  listLlmLogs,
  rejectAdminUser,
  requestTick,
  startJob,
  updateAdminUser,
} from "../services/admin";
import type { AdminUserCreate, AdminUserQuery, AdminUserReject, AdminUserUpdate, AuditQuery, JobKind, JobList, LlmLogQuery } from "../types";

/** How often a running job's progress is re-read. */
export const JOB_POLL_MS = 1500;

export function useAdminOverview() {
  return useQuery({ queryKey: qk.admin.overview, queryFn: getAdminOverview, refetchInterval: 30_000 });
}

/** Data clock card: re-read often so a requested tick shows up without a reload. */
export function useAdminClock() {
  return useQuery({ queryKey: qk.admin.clock, queryFn: getAdminClock, refetchInterval: 15_000 });
}

export function useRunTick() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: requestTick,
    onSettled: () => client.invalidateQueries({ queryKey: qk.admin.clock }),
  });
}

export function useAdminUsers(q: AdminUserQuery) {
  return useQuery({ queryKey: qk.admin.users.list(q), queryFn: () => listAdminUsers(q), placeholderData: keepPreviousData });
}

export function useOrg(enabled = true) {
  return useQuery({ queryKey: qk.admin.org, queryFn: getOrg, enabled, staleTime: 5 * 60_000 });
}

export function useCreateUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: AdminUserCreate) => createAdminUser(body),
    onSettled: () => client.invalidateQueries({ queryKey: qk.admin.all }),
  });
}

export function useUpdateUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: AdminUserUpdate }) => updateAdminUser(id, body),
    onSettled: () => client.invalidateQueries({ queryKey: qk.admin.all }),
  });
}

export function useRejectUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: AdminUserReject }) => rejectAdminUser(id, body),
    onSettled: () => client.invalidateQueries({ queryKey: qk.admin.all }),
  });
}

export function useAudit(q: AuditQuery) {
  return useQuery({ queryKey: qk.admin.audit(q), queryFn: () => listAudit(q), placeholderData: keepPreviousData });
}

export function useDataSummary() {
  return useQuery({ queryKey: qk.admin.data, queryFn: getDataSummary });
}

export function useAssumptions() {
  return useQuery({ queryKey: qk.admin.assumptions, queryFn: getAssumptions, staleTime: Infinity });
}

export function useModels() {
  return useQuery({ queryKey: qk.admin.models, queryFn: getModels });
}

export function useDrift() {
  return useQuery({ queryKey: qk.admin.drift, queryFn: getDrift, staleTime: 5 * 60_000 });
}

function hasRunning(data: JobList | undefined): boolean {
  return data?.running !== null && data?.running !== undefined;
}

/** Recent jobs; polls while one is running, then refreshes everything a job can change. */
export function useJobs() {
  const client = useQueryClient();
  return useQuery({
    queryKey: qk.admin.jobs,
    queryFn: async () => {
      const prev = client.getQueryData<JobList>(qk.admin.jobs);
      const next = await listJobs();
      if (hasRunning(prev) && !hasRunning(next)) {
        void client.invalidateQueries({ predicate: (query) => query.queryKey[0] === "admin" && query.queryKey[1] !== "jobs" });
      }
      return next;
    },
    refetchInterval: (query) => (hasRunning(query.state.data) ? JOB_POLL_MS : false),
  });
}

export function useStartJob() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (kind: JobKind) => startJob(kind),
    onSettled: () => client.invalidateQueries({ queryKey: qk.admin.jobs }),
  });
}

export function useLlmLogs(q: LlmLogQuery) {
  return useQuery({ queryKey: qk.admin.llmLogs(q), queryFn: () => listLlmLogs(q), placeholderData: keepPreviousData });
}

export function useLlmUsage(days: number) {
  return useQuery({ queryKey: qk.admin.llmUsage(days), queryFn: () => getLlmUsage(days), refetchInterval: 60_000 });
}
