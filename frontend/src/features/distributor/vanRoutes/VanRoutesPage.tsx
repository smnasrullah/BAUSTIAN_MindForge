import { CircleCheck, Truck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import { useCreateVanPlan, useVanPlan, useVanPlans, type VanPlanCreate } from "../../../api/vanPlans";
import { LiquidButton } from "../../../components/ui/LiquidButton";
import { PageHeader } from "../../../components/ui/PageHeader";
import { Skeleton, SkeletonCard, SkeletonText } from "../../../components/ui/Skeleton";
import { EmptyState, ErrorState } from "../../../components/ui/StatePanel";
import { toast } from "../../../components/ui/toastStore";
import { errorCode } from "../../../lib/apiError";
import { useReducedMotionPref } from "../../../lib/motionPrefs";
import { VAN_NS } from "../../../i18n/vanRoutes";
import { ApproveDialog } from "./ApproveDialog";
import { BeforeAfterToggle } from "./BeforeAfterToggle";
import { FairnessPanel } from "./FairnessPanel";
import { NarrativePanel } from "./NarrativePanel";
import { PlanControls } from "./PlanControls";
import { PlanStatusBar } from "./PlanStatusBar";
import { RouteMapPane } from "./RouteMapPane";
import { SavingsPanel } from "./SavingsPanel";
import { StopList } from "./StopList";
import { allStops, controlsOf, type Controls, type MapView } from "./vanRoutesModel";

/** Wait this long after the last control change before solving again. */
const RESOLVE_DELAY_MS = 600;
const DEFAULT_CONTROLS: Controls = { vehicles: 2, capacityBdt: 1_500_000, cashCapBdt: 1_500_000 };
const MAP_HEIGHT = "h-[360px] sm:h-[460px] lg:h-[560px]";

function bodyFor(controls: Controls | null): VanPlanCreate {
  return controls
    ? { vehicles: { count: controls.vehicles, capacity_bdt: controls.capacityBdt, cash_cap_bdt: controls.cashCapBdt } }
    : {};
}

function PageSkeleton() {
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]" data-testid="van-skeleton">
      <div className="space-y-4">
        <Skeleton className={`${MAP_HEIGHT} rounded-[var(--radius-card)]`} />
        <SkeletonCard />
      </div>
      <div className="space-y-4">
        <SkeletonCard />
        <SkeletonCard />
        <div className="ap-card p-4">
          <SkeletonText lines={4} />
        </div>
      </div>
    </div>
  );
}

/** Van routes (F14): create a plan, see it on the map, compare it with separate trips, approve with a note. */
export function VanRoutesPage() {
  const { t: tv } = useTranslation(VAN_NS);
  const [params, setParams] = useSearchParams();
  const urlId = Number(params.get("plan")) || null;
  const latest = useVanPlans({ status: "pending", page_size: 1 });
  const planId = urlId ?? latest.data?.items[0]?.id ?? null;
  const planQ = useVanPlan(planId);
  const plan = planQ.data;
  const create = useCreateVanPlan();

  const [view, setView] = useState<MapView>("optimised");
  const [selected, setSelected] = useState<number | null>(null);
  const [controls, setControls] = useState<Controls | null>(null);
  const [approving, setApproving] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  const mapTop = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotionPref();
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const shown = controls ?? (plan ? controlsOf(plan) : DEFAULT_CONTROLS);
  const selectedId = plan && selected !== null && allStops(plan).some((s) => s.id === selected) ? selected : null;
  const isEmptyPlan = plan !== undefined && plan.routes.length === 0 && plan.unrouted.length === 0;

  function showPlan(id: number): void {
    const next = new URLSearchParams(params);
    next.set("plan", String(id));
    setParams(next, { replace: true });
  }

  function solve(next: Controls | null): void {
    window.clearTimeout(timer.current);
    create.mutate(bodyFor(next), {
      onSuccess: (created) => {
        showPlan(created.id);
        setControls(null);
        setSelected(null);
      },
      onError: (err) => toast({ tone: "error", title: tv(errorCode(err) === "van_not_ready" ? "error.notReady" : "error.createFailed") }),
    });
  }

  /** The list sits under the map: bring the map back into view so the pan and the stop card are seen. */
  function selectFromList(id: number): void {
    setSelected(id);
    const el = mapTop.current;
    if (el && el.getBoundingClientRect().top < 0) el.scrollIntoView({ block: "start", behavior: reduced ? "auto" : "smooth" });
  }

  function changeControls(next: Controls): void {
    setControls(next);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => solve(next), RESOLVE_DELAY_MS);
  }

  const loading = planId === null ? latest.isPending : planQ.isPending;
  const failed = planId === null ? latest.isError : planQ.isError;
  const retry = () => void (planId === null ? latest.refetch() : planQ.refetch());
  const pending = plan?.status === "pending";

  return (
    <div className="space-y-4" data-testid="van-routes-page" data-plan-id={plan?.id ?? ""}>
      <PageHeader
        title={tv("title")}
        description={tv("lead")}
        actions={
          <>
            {plan ? (
              <LiquidButton variant="secondary" icon={Truck} loading={create.isPending} onClick={() => solve(controls)} data-testid="van-replan">
                {tv("replan")}
              </LiquidButton>
            ) : null}
            {pending ? (
              <LiquidButton icon={CircleCheck} onClick={() => setApproving(true)} data-testid="van-decide">
                {tv("decide")}
              </LiquidButton>
            ) : null}
          </>
        }
      >
        {plan ? <PlanStatusBar plan={plan} /> : null}
      </PageHeader>

      <PlanControls value={shown} onChange={changeControls} busy={create.isPending} />

      {loading ? (
        <PageSkeleton />
      ) : failed ? (
        <ErrorState onRetry={retry} retrying={planId === null ? latest.isFetching : planQ.isFetching} />
      ) : !plan ? (
        <div data-testid="van-empty">
          <EmptyState
            title={tv("empty.title")}
            body={tv("empty.body")}
            action={{ label: create.isPending ? tv("solving") : tv("create"), icon: Truck, onClick: () => solve(controls) }}
          />
        </div>
      ) : isEmptyPlan ? (
        <EmptyState
          title={tv("stops.none")}
          body={tv("stops.noneBody")}
          action={{ label: tv("replan"), icon: Truck, onClick: () => solve(controls) }}
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
          <div className="min-w-0 space-y-4">
            <div ref={mapTop} className="scroll-mt-20 space-y-4">
              <BeforeAfterToggle value={view} onChange={setView} />
              <RouteMapPane
                plan={plan}
                status="ready"
                onRetry={retry}
                retrying={false}
                view={view}
                selectedStopId={selectedId}
                onSelect={setSelected}
                onClear={() => setSelected(null)}
                busy={create.isPending}
                className={MAP_HEIGHT}
              />
            </div>
            <section aria-labelledby="stops-title" className="ap-card space-y-3 p-4">
              <h2 id="stops-title" className="font-display text-h3 font-bold">
                {tv("stops.title")}
              </h2>
              <StopList plan={plan} selectedStopId={selectedId} onSelect={selectFromList} />
            </section>
          </div>
          <div className="min-w-0 space-y-4">
            <SavingsPanel plan={plan} />
            <FairnessPanel plan={plan} />
            <NarrativePanel planId={plan.id} />
          </div>
        </div>
      )}

      {plan ? <ApproveDialog plan={plan} open={approving} onOpenChange={setApproving} onDecided={showPlan} /> : null}
    </div>
  );
}
