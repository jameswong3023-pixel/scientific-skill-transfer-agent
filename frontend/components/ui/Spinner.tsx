export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="loading"
      className={`inline-block h-4 w-4 animate-spin rounded-full border-2 border-slate-500 border-t-transparent ${className}`}
    />
  );
}
