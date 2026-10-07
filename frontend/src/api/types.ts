// Friendly names over the generated OpenAPI types (schema.d.ts: `scripts/gen-api.ps1` regenerates it).
import type { components, operations } from "./schema";

type S = components["schemas"];

/** JSON body of an operation's success (200/201) response. */
export type Ok<Op extends keyof operations> = operations[Op]["responses"] extends infer R
  ? R extends { 200: { content: { "application/json": infer B } } }
    ? B
    : R extends { 201: { content: { "application/json": infer B } } }
      ? B
      : never
  : never;

/** Query parameters of an operation. */
export type QueryOf<Op extends keyof operations> = operations[Op]["parameters"] extends { query?: infer Q }
  ? NonNullable<Q>
  : never;

export type RiskLevel = S["RiskLevelCode"];
export type FloatType = S["FloatType"];
export type GeneratedBy = S["GeneratedBy"];
export type Lang = S["Lang"];
export type Theme = S["Theme"];

export type AgentSummary = S["AgentSummary"];
export type FloatSummary = S["FloatSummary"];
export type HorizonRisk = S["HorizonRisk"];
export type AgentForecast = S["AgentForecast"];
export type ForecastPoint = S["ForecastPoint"];
export type AgentStockout = S["AgentStockout"];
export type AgentRisk = S["AgentRisk"];
export type AgentRiskPage = S["AgentRiskPage"];
export type AgentRiskRow = S["AgentRiskRow"];
export type AgentExplanation = S["AgentExplanation"];
export type Reason = S["Reason"];
export type AgentRecommendation = S["AgentRecommendation"];
export type WhatIfIn = S["WhatIfIn"];
export type WhatIfOut = S["WhatIfOut"];
export type BalancePoint = S["BalancePoint"];
export type WhatIfScenario = S["WhatIfScenario"];
/** One float's cached 0..72h balance projection (what-if `before`) with its response metadata. */
export type Runway = WhatIfScenario &
  Pick<WhatIfOut, "float_type" | "capacity" | "as_of" | "model_version" | "generated_at">;
export type RecommendationItem = S["RecommendationItem"];
export type RequestItem = S["RequestItem"];
export type RequestPage = S["RequestPage"];
export type RequestStatus = S["RequestStatus"];
export type RecommendationChannel = S["RecommendationChannel"];
export type EventType = S["EventType"];
export type EventItem = S["EventItem"];
export type EventPage = S["EventPage"];
export type LlmText = S["LlmText"];
export type CopilotSuggestions = S["CopilotSuggestions"];
export type CopilotChatIn = S["CopilotChatIn"];
export type NarrateIn = S["NarrateIn"];

export type SwapItem = S["SwapItem"];
export type SwapPage = S["SwapPage"];
export type SwapDecisionIn = S["SwapDecisionIn"];
export type SwapRespondIn = S["SwapRespondIn"];
export type SwapParty = S["SwapParty"];

export type MapAgents = S["MapAgents"];
export type MapAgent = S["MapAgent"];
export type MapSwap = S["MapSwap"];

export type AnomalyPage = S["AnomalyPage"];
export type AnomalyDetail = S["AnomalyDetail"];
export type AnomalyReviewIn = S["AnomalyReviewIn"];

export type NotificationPage = S["NotificationPage"];
export type NotificationItem = S["NotificationItem"];

export type SystemStatus = S["SystemStatus"];
export type Freshness = S["Freshness"];
export type LlmStatus = S["LlmStatus"];
export type UserOut = S["UserOut"];
export type PreferencesUpdate = S["PreferencesUpdate"];
export type ProfileOut = S["ProfileOut"];
export type ProfileUpdate = S["ProfileUpdate"];
export type AvatarColor = NonNullable<ProfileOut["avatar_color"]>;
export type ImpactSummary = S["ImpactSummary"];
export type PainPoints = S["PainPointsOut"];
export type SearchResponse = S["SearchResponse"];
export type SearchHit = S["SearchHit"];
export type ModelCard = S["ModelCard"];
export type ImpactComparison = S["ImpactComparison"];
export type ImpactDay = S["ImpactDay"];
export type ScenarioTotals = S["ScenarioTotals"];
export type FairnessReport = S["FairnessReport"];
export type FairnessGroup = S["FairnessGroup"];
export type GroupBy = S["GroupBy"];
export type AnomalyItem = S["AnomalyItem"];
export type AnomalyStatus = S["AnomalyStatus"];
export type PeerFeature = S["PeerFeature"];
export type SwapStatus = S["SwapStatus"];
export type RiskSort = NonNullable<RiskListQuery["sort"]>;

// Admin console
export type UserRole = S["UserRole"];
export type AdminOverview = S["AdminOverview"];
export type AdminClock = S["AdminClock"];
export type ClockInfo = S["ClockInfo"];
export type TickRequestOut = S["TickRequestOut"];
export type AdminUser = S["AdminUser"];
export type AdminUserPage = S["AdminUserPage"];
export type AdminUserCreate = S["AdminUserCreate"];
export type AdminUserUpdate = S["AdminUserUpdate"];
export type AdminUserReject = S["AdminUserReject"];
export type OrgDirectory = S["OrgDirectory"];
export type AuditItem = S["AuditItem"];
export type AuditPage = S["AuditPage"];
export type DataSummary = S["DataSummary"];
export type AssumptionsDoc = S["AssumptionsDoc"];
export type ModelRegistry = S["ModelRegistry"];
export type ModelVersionItem = S["ModelVersionItem"];
export type DriftReport = S["DriftReport"];
export type DriftFloat = S["DriftFloat"];
export type DriftStatus = DriftReport["status"];
export type JobOut = S["JobOut"];
export type JobList = S["JobList"];
export type JobKind = JobOut["kind"];
export type JobStatus = JobOut["status"];
export type LlmLogItem = S["LlmLogItem"];
export type LlmLogPage = S["LlmLogPage"];
export type LlmUsage = S["LlmUsage"];
export type LlmIntent = S["LlmIntent"];
export type GuardResult = S["GuardResult"];
export type EventIn = S["EventIn"];
export type AdminUserQuery = QueryOf<"list_users_api_v1_admin_users_get">;
export type AuditQuery = QueryOf<"list_audit_api_v1_admin_audit_log_get">;
export type LlmLogQuery = QueryOf<"llm_logs_api_v1_admin_llm_logs_get">;

export type RiskListQuery = QueryOf<"list_risk_api_v1_agents_risk_get">;
export type SwapListQuery = QueryOf<"list_swaps_api_v1_swaps_get">;
export type RequestListQuery = QueryOf<"list_requests_api_v1_recommendation_requests_get">;
export type AnomalyListQuery = QueryOf<"list_anomalies_api_v1_anomalies_get">;
export type NotificationListQuery = QueryOf<"list_notifications_api_v1_notifications_get">;
export type ExplanationQuery = QueryOf<"get_explanations_api_v1_agents__agent_id__explanations_get">;
export type ForecastQuery = QueryOf<"get_forecast_api_v1_agents__agent_id__forecast_get">;
export type ImpactQuery = QueryOf<"get_summary_api_v1_impact_summary_get">;
export type EventListQuery = QueryOf<"list_events_api_v1_events_get">;
export type ImpactComparisonQuery = QueryOf<"get_comparison_api_v1_impact_comparison_get">;

export type HelpRequestItem = S["HelpRequestItem"];
export type HelpRequestPage = S["HelpRequestPage"];
export type HelpRecipientOut = S["HelpRecipientOut"];
export type HelpStatus = S["HelpStatus"];
export type HelpResponse = S["HelpResponse"];
export type HelpRequester = S["HelpRequester"];
export type HelpSettingsOut = S["HelpSettingsOut"];
export type HelpSettingsIn = S["HelpSettingsIn"];
export type HelpNoteIn = S["HelpNoteIn"];
export type HelpSweepOut = S["HelpSweepOut"];
export type TriggerSettingsOut = S["TriggerSettingsOut"];
export type TriggerSettingsIn = S["TriggerSettingsIn"];
export type DryRunOut = S["DryRunOut"];
export type PlanItemOut = S["PlanItemOut"];
export type SimulateIn = S["SimulateIn"];
export type SimulateOut = S["SimulateOut"];
export type DemoHelpInfo = S["DemoHelpInfo"];
export type OptOutOut = S["OptOutOut"];
export type TriggerRunOut = S["TriggerRunOut"];
export type DemoResetOut = S["DemoResetOut"];
export type AgentProfile = S["AgentProfile"];
export type HelpRequestListQuery = QueryOf<"list_mine_api_v1_liquidity_requests_mine_get">;
