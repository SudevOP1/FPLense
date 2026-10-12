import { useEffect } from "react";

/** "Compare · FPLense" per route. */
export function useTitle(title: string | null): void {
  useEffect(() => {
    document.title = title ? `${title} · FPLense` : "FPLense · FPL points forecasts and the best squad";
  }, [title]);
}
