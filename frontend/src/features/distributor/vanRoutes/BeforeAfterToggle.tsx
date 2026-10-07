import { Route, Split } from "lucide-react";
import { useTranslation } from "react-i18next";

import { SegmentedControl } from "../../../components/ui/SegmentedControl";
import { VAN_NS } from "../../../i18n/vanRoutes";
import type { MapView } from "./vanRoutesModel";

interface BeforeAfterToggleProps {
  value: MapView;
  onChange: (view: MapView) => void;
}

/** Separate trips (before) versus the optimised routes (after), drawn on the same map. */
export function BeforeAfterToggle({ value, onChange }: BeforeAfterToggleProps) {
  const { t: tv } = useTranslation(VAN_NS);
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1" data-testid="before-after">
      <SegmentedControl<MapView>
        label={tv("view.label")}
        value={value}
        onChange={onChange}
        options={[
          { value: "optimised", label: tv("view.optimised"), icon: Route },
          { value: "separate", label: tv("view.separate"), icon: Split },
        ]}
      />
      {value === "separate" ? (
        <p className="max-w-md text-xs text-muted" data-testid="before-after-hint">
          {tv("view.hint")}
        </p>
      ) : null}
    </div>
  );
}
