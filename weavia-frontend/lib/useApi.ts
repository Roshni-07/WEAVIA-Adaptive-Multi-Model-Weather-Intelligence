import { useEffect, useState } from "react";
export function useApi<T>(fn: () => Promise<T>, deps: any[], enabled = true) {
  const [data, setData] = useState<T | undefined>();
  const [error, setError] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    setLoading(true);
    fn().then((d) => { if (live) { setData(d); setError(undefined); setLoading(false); } })
      .catch((e) => { if (live) { setError(e.message); setLoading(false); } });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, enabled]);
  return { data, error, loading };
}
