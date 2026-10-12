import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { makeQueryClient } from "./api/hooks";
import { CompareTrayProvider } from "./lib/compareTray";
import { SettingsProvider } from "./lib/settings";
import { ToastProvider } from "./lib/toast";
import { routes } from "./routes";

/** Every provider the pages need (also used by the tests around a memory router). */
export function Providers({ children, client }: { children: ReactNode; client?: QueryClient }) {
  const [qc] = useState(() => client ?? makeQueryClient());
  return (
    <SettingsProvider>
      <QueryClientProvider client={qc}>
        <ToastProvider>
          <CompareTrayProvider>{children}</CompareTrayProvider>
        </ToastProvider>
      </QueryClientProvider>
    </SettingsProvider>
  );
}

// opt in to React Router v7 behaviour now (silences the v6 deprecation warnings)
export const ROUTER_FUTURE = {
  v7_relativeSplatPath: true,
  v7_fetcherPersist: true,
  v7_normalizeFormMethod: true,
  v7_partialHydration: true,
  v7_skipActionErrorRevalidation: true,
} as const;

const router = createBrowserRouter(routes, { future: ROUTER_FUTURE });

export function App() {
  return (
    <Providers>
      <RouterProvider router={router} future={{ v7_startTransition: true }} />
    </Providers>
  );
}
