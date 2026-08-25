"use client";

import { useEffect, useState } from "react";

/** The backend reports the slice count for an axis in a response header, so the
 *  client never needs to parse the volume itself. */
export function useSliceCount(url: string | null): number {
  const [count, setCount] = useState(1);

  useEffect(() => {
    if (!url) return;
    let cancelled = false;
    fetch(url, { method: "HEAD" })
      .then((r) => {
        const header = r.headers.get("X-Slice-Count");
        if (!cancelled && header) setCount(Math.max(1, parseInt(header, 10)));
      })
      .catch(() => {
        /* fall back to 1 */
      });
    return () => {
      cancelled = true;
    };
  }, [url]);

  return count;
}
