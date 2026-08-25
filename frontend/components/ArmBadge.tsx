import clsx from "clsx";

import { ARM_LABEL, ARM_STYLE } from "@/lib/format";
import type { Arm } from "@/lib/types";

export function ArmBadge({ arm, className }: { arm: Arm; className?: string }) {
  const style = ARM_STYLE[arm];
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-2 rounded-md border px-2.5 py-1 text-sm font-medium",
        style.bg, style.border, style.text, className,
      )}
    >
      <span className={clsx("h-2 w-2 rounded-full", style.dot)} />
      {ARM_LABEL[arm]}
    </span>
  );
}
