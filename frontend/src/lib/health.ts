import { useEffect, useState } from 'react';
import { getHealth } from './api';
import type { Health } from './api';

let cache: Health | null = null;
let inflight: Promise<Health> | null = null;

export function useHealth(): Health | null {
  const [h, setH] = useState<Health | null>(cache);
  useEffect(() => {
    if (cache) return;
    inflight ??= getHealth();
    let alive = true;
    inflight.then((v) => { cache = v; if (alive) setH(v); }).catch(() => { inflight = null; });
    return () => { alive = false; };
  }, []);
  return h;
}
