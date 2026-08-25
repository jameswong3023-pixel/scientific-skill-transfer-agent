"use client";

import clsx from "clsx";
import { useEffect, useMemo, useState } from "react";

import { useSliceCount } from "@/hooks/useSliceCount";

const AXES = ["axial", "coronal", "sagittal"] as const;
export type Axis = (typeof AXES)[number];

export function SliceViewer({
  baseUrlFor, overlayUrlFor, title, initialAxis = "axial", compact = false,
}: {
  baseUrlFor: (axis: Axis, index: number) => string;
  overlayUrlFor?: ((axis: Axis, index: number, alpha: number) => string) | null;
  title?: string;
  initialAxis?: Axis;
  compact?: boolean;
}) {
  const [axis, setAxis] = useState<Axis>(initialAxis);
  const [index, setIndex] = useState(0);
  const [alpha, setAlpha] = useState(0.55);
  const [showOverlay, setShowOverlay] = useState(true);

  const probeUrl = useMemo(() => baseUrlFor(axis, 0), [axis, baseUrlFor]);
  const count = useSliceCount(probeUrl);

  // Re-centre when the axis changes: the middle slice is almost always the
  // informative one, and slice counts differ per axis.
  useEffect(() => {
    setIndex(Math.floor(count / 2));
  }, [axis, count]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "ArrowLeft") setIndex((i) => Math.max(0, i - 1));
      if (e.key === "ArrowRight") setIndex((i) => Math.min(count - 1, i + 1));
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [count]);

  const clamped = Math.min(index, Math.max(0, count - 1));

  return (
    <div className="space-y-3">
      {title && <p className="text-sm font-medium text-slate-200">{title}</p>}

      {count > 1 && (
        <div className="flex flex-wrap items-center gap-1">
          {AXES.map((a) => (
            <button
              key={a}
              onClick={() => setAxis(a)}
              className={clsx(
                "rounded px-2.5 py-1 text-xs capitalize transition",
                axis === a
                  ? "bg-violet-600 text-white"
                  : "border border-[var(--border)] text-slate-400 hover:text-slate-200",
              )}
            >
              {a}
            </button>
          ))}
        </div>
      )}

      <div
        className={clsx(
          "relative overflow-hidden rounded-lg border border-[var(--border)] bg-black",
          compact ? "aspect-square" : "aspect-square",
        )}
      >
        {/* Slices are server-rendered PNGs behind an API route, not static assets:
            next/image would add an optimizer hop for no benefit. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={baseUrlFor(axis, clamped)}
          alt={`${axis} slice ${clamped}`}
          className="absolute inset-0 h-full w-full object-contain"
        />
        {overlayUrlFor && showOverlay && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={overlayUrlFor(axis, clamped, alpha)}
            alt="segmentation overlay"
            className="pointer-events-none absolute inset-0 h-full w-full object-contain"
          />
        )}
        <span className="absolute bottom-2 right-2 rounded bg-black/70 px-2 py-0.5 text-xs text-slate-300">
          {axis} {clamped + 1}/{count}
        </span>
      </div>

      {count > 1 && (
        <input
          type="range"
          min={0}
          max={Math.max(0, count - 1)}
          value={clamped}
          onChange={(e) => setIndex(Number(e.target.value))}
          className="w-full accent-violet-500"
          aria-label="slice index"
        />
      )}

      {overlayUrlFor && (
        <div className="flex items-center gap-3 text-xs text-slate-400">
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={showOverlay}
              onChange={(e) => setShowOverlay(e.target.checked)}
              className="accent-violet-500"
            />
            overlay
          </label>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={alpha}
            onChange={(e) => setAlpha(Number(e.target.value))}
            disabled={!showOverlay}
            className="w-28 accent-violet-500"
            aria-label="overlay opacity"
          />
          <span>{Math.round(alpha * 100)}%</span>
        </div>
      )}
    </div>
  );
}
