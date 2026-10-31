import { render, screen } from "@testing-library/react";

import { App } from "./App";

test("renders the application title as the heading", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: "To-do list" })).toBeTruthy();
});
