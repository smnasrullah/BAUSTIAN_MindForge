import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useSingleFlight } from "./useSingleFlight";

describe("useSingleFlight", () => {
  it("ignores a second start until the first is done, then allows the next", () => {
    const { result } = renderHook(() => useSingleFlight());
    const once = result.current;
    let starts = 0;
    let finish = () => undefined as void;
    const start = (done: () => void) => {
      starts += 1;
      finish = done;
    };
    once(start);
    once(start); // the second click of a double-click
    expect(starts).toBe(1);
    finish();
    once(start);
    expect(starts).toBe(2);
  });
});
