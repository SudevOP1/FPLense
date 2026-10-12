import { lazy } from "react";
import type { RouteObject } from "react-router-dom";
import { Layout } from "./components/layout/Layout";

// Route-level code splitting: each page is its own chunk.
const Home = lazy(() => import("./pages/Home"));
const BestTeam = lazy(() => import("./pages/BestTeam"));
const SeasonReplay = lazy(() => import("./pages/SeasonReplay"));
const MyTeam = lazy(() => import("./pages/MyTeam"));
const Compare = lazy(() => import("./pages/Compare"));
const Builder = lazy(() => import("./pages/Builder"));
const Players = lazy(() => import("./pages/Players"));
const ModelCard = lazy(() => import("./pages/ModelCard"));
const NotFound = lazy(() => import("./pages/NotFound"));
// dev builds only; import.meta.env.DEV is false in production, so the chunk is never built
const KitchenSink = import.meta.env.DEV ? lazy(() => import("./pages/KitchenSink")) : null;

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Home /> },
      { path: "best", element: <BestTeam /> },
      { path: "season", element: <SeasonReplay /> },
      { path: "me", element: <MyTeam /> },
      { path: "me/:teamId", element: <MyTeam /> },
      { path: "me/:teamId/transfers", element: <MyTeam tab="transfers" /> },
      { path: "compare", element: <Compare /> },
      { path: "builder", element: <Builder /> },
      { path: "players", element: <Players /> },
      { path: "model", element: <ModelCard /> },
      // dev builds only: every component in every state, both themes
      ...(KitchenSink ? [{ path: "dev/kitchen-sink", element: <KitchenSink /> }] : []),
      { path: "*", element: <NotFound /> },
    ],
  },
];
