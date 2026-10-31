import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Markdown } from "./Markdown";

describe("Markdown", () => {
  it("renders formatting but never raw HTML or script URLs", () => {
    const { container } = render(
      <Markdown>
        {
          "**bold** <script>alert(1)</script> <img src=x onerror=alert(1)>\n\n[bad](javascript:alert(1)) [ok](https://example.com)"
        }
      </Markdown>,
    );
    expect(screen.getByText("bold").tagName).toBe("STRONG");
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    const bad = screen.getByText("bad");
    expect(bad.getAttribute("href") ?? "").not.toContain("javascript");
    const ok = screen.getByRole("link", { name: "ok" });
    expect(ok).toHaveAttribute("rel", "noopener noreferrer nofollow");
    expect(ok).toHaveAttribute("target", "_blank");
  });
});
