import "i18next";

import type en from "./en.json";
import type helpAdmin from "./helpAdmin.en.json";
import type vanRoutes from "./vanRoutes.en.json";

// Typed translation keys: t("risk.red") is checked against en.json.
declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: "translation";
    resources: { translation: typeof en; helpAdmin: typeof helpAdmin; vanRoutes: typeof vanRoutes };
  }
}
