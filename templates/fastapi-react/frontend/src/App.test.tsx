import { render, screen } from "@testing-library/react";

import { App } from "./App";

test("renders the project heading", () => {
  render(<App />);
  expect(screen.getByRole("heading")).toBeTruthy();
});
