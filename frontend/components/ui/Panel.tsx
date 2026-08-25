import clsx from "clsx";

export function Panel({
  title, subtitle, actions, children, className,
}: {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={clsx("panel", className)}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-4 border-b border-[var(--border)] px-5 py-3">
          <div>
            {title && <h2 className="font-medium text-slate-100">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-sm text-slate-400">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 gap-2">{actions}</div>}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}
