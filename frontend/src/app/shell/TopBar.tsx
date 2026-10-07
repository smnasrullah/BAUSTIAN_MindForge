import { Clock, Search, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { useSavePreferences } from "../../api/hooks/users";
import { PulseLine } from "../../components/signature/PulseLine";
import { ThemeToggle } from "../../components/ui/ThemeToggle";
import { toast } from "../../components/ui/toastStore";
import { NotificationBell } from "../../features/notifications/NotificationBell";
import { cn } from "../../lib/cn";
import { AvatarMenu } from "./AvatarMenu";
import { Breadcrumbs } from "./Breadcrumbs";
import { LanguageSwitch } from "./LanguageSwitch";
import type { Crumb } from "./nav";
import { RouteProgress } from "./RouteProgress";
import { useShellStore } from "./shellStore";

function Brand({ home }: { home: string }) {
  const { t } = useTranslation();
  return (
    <Link to={home} aria-label={t("shell.home")} data-tour="brand" className="flex shrink-0 items-center gap-2 rounded-xl pr-1">
      <span className="w-12">
        <PulseLine className="h-7" />
      </span>
      {/* Phones: icon only, in every layout (the full bar was 515 px wide on a 390 px screen). */}
      <span className="sr-only font-display text-lg font-bold sm:not-sr-only">AgentPulse</span>
    </Link>
  );
}

interface TopBarProps {
  home: string;
  crumbs: Crumb[];
  /** Agent (mobile, one-thumb) vs Control Room (desktop). */
  compact: boolean;
}

export function TopBar({ home, crumbs, compact }: TopBarProps) {
  const { t } = useTranslation();
  const openPalette = useShellStore((s) => s.setPaletteOpen);
  const save = useSavePreferences();

  return (
    <header className="glass sticky top-0 z-(--z-sticky) border-b border-line">
      <div className={cn("flex min-h-16 items-center gap-2", compact ? "px-3" : "px-4 md:px-6")}>
        <Brand home={home} />
        {compact ? null : <Breadcrumbs crumbs={crumbs} className="ml-2 hidden flex-1 lg:block" />}
        <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
          <div
            className="hidden sm:flex items-center gap-2 rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-xs font-medium text-amber-600 dark:text-amber-400"
            title="System operates on a fixed simulated timeline for reproducible judging"
          >
            <Clock className="h-3.5 w-3.5 shrink-0" />
            <span>Simulated Time: 30 Apr 2026, 20:00</span>
            <span className="text-muted/60">·</span>
            <span className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
              <ShieldCheck className="h-3 w-3" />
              <span>Inputs Fresh</span>
            </span>
          </div>
          <button
            type="button"
            onClick={() => openPalette(true)}
            aria-label={t("shell.searchHint")}
            aria-keyshortcuts="Control+K"
            data-tour="search"
            data-testid="search-button"
            className={cn(
              "flex min-h-11 items-center gap-2 rounded-full border border-line bg-surface text-muted hover:bg-surface-2 hover:text-fg",
              compact ? "w-11 justify-center" : "w-11 justify-center md:w-64 md:justify-start md:px-3",
            )}
          >
            <Search aria-hidden className="size-5 shrink-0" />
            {compact ? null : (
              <>
                <span className="hidden flex-1 text-left text-small md:inline">{t("shell.search")}</span>
                <kbd className="num hidden rounded-md border border-line px-1.5 text-xs md:inline">Ctrl K</kbd>
              </>
            )}
          </button>
          <NotificationBell />
          <LanguageSwitch className={compact ? "px-2.5" : "max-sm:px-2.5"} />
          <ThemeToggle
            className="hidden sm:grid"
            onSwitch={(theme) => save.mutate({ theme }, { onError: () => toast({ tone: "error", title: t("settings.saveFailed") }) })}
          />
          <AvatarMenu />
        </div>
      </div>
      <RouteProgress />
    </header>
  );
}
