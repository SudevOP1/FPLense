import { QueryClient } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { createMemoryRouter, MemoryRouter, RouterProvider } from "react-router-dom";
import { Providers, ROUTER_FUTURE } from "@/App";
import { routes } from "@/routes";

export function testClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
}

/** Render the whole app (layout + lazy page) at a URL, against the mocked API. */
export function renderRoute(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path], future: ROUTER_FUTURE });
  const user = userEvent.setup();
  const utils = render(
    <Providers client={testClient()}>
      <RouterProvider router={router} future={{ v7_startTransition: true }} />
    </Providers>,
  );
  return { ...utils, router, user };
}

/** Render one component inside the providers and a router. */
export function renderWithProviders(ui: ReactElement) {
  const user = userEvent.setup();
  const utils = render(
    <Providers client={testClient()}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>{ui}</MemoryRouter>
    </Providers>,
  );
  return { ...utils, user };
}
