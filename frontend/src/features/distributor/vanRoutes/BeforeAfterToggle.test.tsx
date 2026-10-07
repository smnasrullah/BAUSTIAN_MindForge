import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BeforeAfterToggle } from "./BeforeAfterToggle";

describe("BeforeAfterToggle", () => {
  it("marks the current view and switches to separate trips", () => {
    const onChange = vi.fn();
    render(<BeforeAfterToggle value="optimised" onChange={onChange} />);
    expect(screen.getByRole("radio", { name: "Optimised" })).toBeChecked();
    expect(screen.queryByTestId("before-after-hint")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Separate trips" }));
    expect(onChange).toHaveBeenCalledWith("separate");
  });

  it("explains what separate trips means when that view is on", () => {
    render(<BeforeAfterToggle value="separate" onChange={() => undefined} />);
    expect(screen.getByRole("radio", { name: "Separate trips" })).toBeChecked();
    expect(screen.getByTestId("before-after-hint")).toHaveTextContent("one out-and-back van trip for each agent");
  });

  it("ignores a click on the view that is already on", () => {
    const onChange = vi.fn();
    render(<BeforeAfterToggle value="optimised" onChange={onChange} />);
    fireEvent.click(screen.getByRole("radio", { name: "Optimised" }));
    expect(onChange).not.toHaveBeenCalled();
  });
});
