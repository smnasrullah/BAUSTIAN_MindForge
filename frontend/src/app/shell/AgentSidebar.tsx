import { useTranslation } from "react-i18next";

import { useHelpUnread } from "../../api/hooks/notifications";
import { formatNumber } from "../../lib/format";
import { useLocale } from "../../lib/prefs";
import { AGENT_SIDE_NAV } from "./nav";
import { Sidebar } from "./Sidebar";

/** Agent desktop (1024px+): the control-room sidebar with the bottom-nav destinations; Help carries the unread count. */
export function AgentSidebar() {
  const { t } = useTranslation();
  const { digits } = useLocale();
  const helpUnread = useHelpUnread();
  const badge =
    helpUnread > 0
      ? { to: "/agent/help", text: formatNumber(Math.min(helpUnread, 99), digits), label: t("nav.helpUnread", { n: formatNumber(helpUnread, digits) }) }
      : undefined;
  return <Sidebar items={AGENT_SIDE_NAV} area={t("role.agent")} badge={badge} />;
}
