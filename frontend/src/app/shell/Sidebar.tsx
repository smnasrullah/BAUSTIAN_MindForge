import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "../../lib/cn";
import { useMediaQuery } from "../../lib/useMediaQuery";
import type { NavBadge, NavItem } from "./nav";
import { SidebarDrawer } from "./SidebarDrawer";
import { SideNavList, Tip } from "./SideNavList";
import { PHONE_QUERY, useShellStore } from "./shellStore";

/** Distributor/admin navigation: collapsible to icons, with tooltips when collapsed; phones open a drawer. */
export function Sidebar({ items, area, badge }: { items: NavItem[]; area: string; badge?: NavBadge }) {
  const { t } = useTranslation();
  const stored = useShellStore((s) => s.sidebarCollapsed);
  const toggle = useShellStore((s) => s.toggleSidebar);
  // Phones get the icon rail; the menu button opens the full list as an overlay.
  const narrow = useMediaQuery(PHONE_QUERY);
  const collapsed = stored || narrow;
  const ToggleIcon = collapsed ? PanelLeftOpen : PanelLeftClose;
  const toggleLabel = collapsed ? t("shell.expand") : t("shell.collapse");

  return (
    <aside
      data-collapsed={collapsed}
      className={cn(
        "glass sticky top-0 flex h-screen shrink-0 flex-col border-r border-line",
        collapsed ? "w-16 md:w-[76px]" : "w-64",
      )}
    >
      <div className={cn("flex min-h-16 items-center px-3 pb-2 pt-4", collapsed ? "justify-center" : "justify-between")}>
        {collapsed ? null : <p className="px-1 ap-eyebrow">{area}</p>}
        {narrow ? (
          <SidebarDrawer items={items} area={area} />
        ) : (
          <Tip label={toggleLabel} enabled>
            <button
              type="button"
              onClick={toggle}
              aria-label={toggleLabel}
              aria-expanded={!collapsed}
              data-testid="sidebar-toggle"
              className="ap-press grid size-10 place-items-center rounded-xl text-muted hover:bg-surface-2 hover:text-fg"
            >
              <ToggleIcon aria-hidden className="size-5" />
            </button>
          </Tip>
        )}
      </div>
      <SideNavList items={items} collapsed={collapsed} layoutId="sidebar-active" tour badge={badge} />
    </aside>
  );
}
