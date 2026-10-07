import i18n from "i18next";

import bn from "./vanRoutes.bn.json";
import en from "./vanRoutes.en.json";

// Van routes wording lives in its own namespace, bundled with the page chunk, so it never weighs on
// the first load (bundle budget). Same pattern as helpAdmin.
export const VAN_NS = "vanRoutes";

for (const [lang, dict] of [["en", en], ["bn", bn]] as const) {
  if (!i18n.hasResourceBundle(lang, VAN_NS)) i18n.addResourceBundle(lang, VAN_NS, dict, true, true);
}
