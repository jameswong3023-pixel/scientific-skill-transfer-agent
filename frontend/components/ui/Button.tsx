import clsx from "clsx";

type Props = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "danger";
  size?: "sm" | "md";
};

export function Button({ variant = "primary", size = "md", className, ...rest }: Props) {
  return (
    <button
      {...rest}
      className={clsx(
        "inline-flex items-center gap-2 rounded-lg font-medium transition disabled:cursor-not-allowed disabled:opacity-40",
        size === "sm" ? "px-2.5 py-1.5 text-sm" : "px-4 py-2",
        variant === "primary" && "bg-violet-600 text-white hover:bg-violet-500",
        variant === "ghost" && "border border-[var(--border)] text-slate-200 hover:bg-white/5",
        variant === "danger" && "bg-red-600 text-white hover:bg-red-500",
        className,
      )}
    />
  );
}
