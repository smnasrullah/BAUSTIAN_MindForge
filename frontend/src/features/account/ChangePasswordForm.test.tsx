import { act, fireEvent, render, screen } from "@testing-library/react";
import { AxiosError, AxiosHeaders } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { usePrefsStore } from "../../lib/prefs";
import { changePassword } from "../auth/authApi";
import { ChangePasswordForm } from "./ChangePasswordForm";
import { passwordStrength } from "./passwordStrength";

vi.mock("../auth/authApi", () => ({ changePassword: vi.fn() }));

function fill(oldPw: string, newPw: string, confirm = newPw) {
  fireEvent.change(screen.getByLabelText("Current password"), { target: { value: oldPw } });
  fireEvent.change(screen.getByLabelText("New password"), { target: { value: newPw } });
  fireEvent.change(screen.getByLabelText("Confirm new password"), { target: { value: confirm } });
  fireEvent.click(screen.getByRole("button", { name: "Change password" }));
}

describe("ChangePasswordForm", () => {
  beforeEach(() => {
    vi.mocked(changePassword).mockReset();
  });

  it("changes the password and reports revoked sessions", async () => {
    vi.mocked(changePassword).mockResolvedValue(2);
    render(<ChangePasswordForm />);
    fill("old-password", "new-password-1");
    expect(await screen.findByRole("status")).toHaveTextContent("2 other sessions were signed out");
    expect(changePassword).toHaveBeenCalledWith("old-password", "new-password-1");
  });

  it("validates length and confirmation without calling the API", async () => {
    render(<ChangePasswordForm />);
    fill("old-password", "short", "other");
    expect(await screen.findByText("Use at least 8 characters")).toBeInTheDocument();
    expect(screen.getByText("Passwords do not match")).toBeInTheDocument();
    expect(changePassword).not.toHaveBeenCalled();
  });

  it("shows a clear error for a wrong current password", async () => {
    const headers = new AxiosHeaders();
    vi.mocked(changePassword).mockRejectedValue(
      new AxiosError("400", "ERR_BAD_REQUEST", { headers }, null, {
        status: 400,
        statusText: "Bad Request",
        data: { detail: "wrong_password" },
        headers: {},
        config: { headers },
      }),
    );
    render(<ChangePasswordForm />);
    fill("bad-password", "new-password-1");
    expect(await screen.findByRole("alert")).toHaveTextContent("Current password is incorrect.");
  });

  it("rates password strength", () => {
    expect(passwordStrength("abc")).toBe("too short");
    expect(passwordStrength("abcdefgh")).toBe("weak");
    expect(passwordStrength("abcdefg1")).toBe("fair");
    expect(passwordStrength("Abcdefg1!x")).toBe("strong");
  });

  it("speaks Bangla with Bangla digits when the user reads Bangla", async () => {
    act(() => usePrefsStore.setState({ lang: "bn", digits: "bn" }));
    vi.mocked(changePassword).mockResolvedValue(1);
    render(<ChangePasswordForm />);
    expect(screen.getByRole("heading", { name: "পাসওয়ার্ড বদলান" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("বর্তমান পাসওয়ার্ড"), { target: { value: "old-password" } });
    fireEvent.change(screen.getByLabelText("নতুন পাসওয়ার্ড"), { target: { value: "short" } });
    fireEvent.click(screen.getByRole("button", { name: "পাসওয়ার্ড বদলান" }));
    expect(await screen.findByText("কমপক্ষে ৮ অক্ষর দিন")).toBeInTheDocument();
  });
});
