import { createContext, useContext, useLayoutEffect } from "react";

export const PageLoadingContext = createContext<(() => () => void) | null>(null);

export function usePageLoading(loading: boolean) {
  const register = useContext(PageLoadingContext);
  useLayoutEffect(() => {
    if (loading) return register?.();
  }, [loading, register]);
}
