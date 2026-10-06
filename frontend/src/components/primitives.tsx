import type { ButtonHTMLAttributes, ReactNode } from "react";

/* Press-room primitives: square edges, hairline rules, mono labels.

   Nothing here is rounded and nothing floats. Elevation is expressed with a
   hard 2px offset stamp when it is needed at all. */

export function Panel({
  children,
  className = "",
  padded = true,
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <section className={`border border-line bg-surface ${padded ? "p-4" : ""} ${className}`}>
      {children}
    </section>
  );
}

export function SectionLabel({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <header className="mb-3 flex items-baseline justify-between gap-3 border-b border-line pb-2">
      <h2 className="label-mono text-ink">{children}</h2>
      {right ? <span className="label-mono text-ink-3">{right}</span> : null}
    </header>
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost";
  size?: "sm" | "md";
  icon?: ReactNode;
};

export function Button({
  variant = "secondary",
  size = "md",
  icon,
  children,
  className = "",
  ...rest
}: ButtonProps) {
  const base =
    "inline-flex items-center justify-center gap-2 whitespace-nowrap font-mono uppercase tracking-[0.1em] transition-colors duration-150 active:translate-y-[1px] disabled:pointer-events-none disabled:opacity-45";
  const sizes = size === "sm" ? "h-8 px-2.5 text-[10.5px]" : "h-9 px-4 text-[11px]";
  const variants = {
    primary: "bg-accent text-accent-ink hover:bg-accent-hover",
    secondary: "border border-line bg-surface text-ink-2 hover:border-line-strong hover:text-ink",
    ghost: "text-ink-3 hover:bg-surface-2 hover:text-ink",
  }[variant];

  return (
    <button className={`${base} ${sizes} ${variants} ${className}`} {...rest}>
      {icon}
      {children}
    </button>
  );
}

export function Chip({
  children,
  onClick,
  active = false,
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  active?: boolean;
  title?: string;
}) {
  const shared =
    "inline-flex max-w-full items-center gap-1.5 truncate border px-2 py-[3px] font-mono text-[10px] uppercase tracking-[0.1em] transition-colors duration-150";
  if (!onClick) {
    return (
      <span className={`${shared} border-line bg-surface text-ink-2`} title={title}>
        {children}
      </span>
    );
  }
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className={`${shared} active:translate-y-[1px] ${
        active
          ? "border-accent bg-accent text-accent-ink"
          : "border-line bg-surface text-ink-2 hover:border-line-strong hover:text-ink"
      }`}
    >
      {children}
    </button>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string; hint?: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label="Search mode"
      className="inline-flex items-center border border-line bg-surface"
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            role="tab"
            type="button"
            aria-selected={selected}
            title={option.hint}
            onClick={() => onChange(option.value)}
            className={`border-r border-line px-3 py-[7px] font-mono text-[10.5px] uppercase tracking-[0.1em] transition-colors duration-150 last:border-r-0 ${
              selected ? "bg-ink text-[rgb(250_250_247)]" : "text-ink-3 hover:bg-surface-2 hover:text-ink"
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`rl-skeleton ${className}`} aria-hidden="true" />;
}

export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon: ReactNode;
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-start gap-3 border border-dashed border-line bg-surface px-6 py-8">
      <span className="text-accent">{icon}</span>
      <div className="space-y-1.5">
        <p className="text-[17px] font-semibold tracking-[-0.01em] text-ink">{title}</p>
        <p className="prose-serif max-w-[58ch] text-ink-2">{body}</p>
      </div>
      {action}
    </div>
  );
}

export function ErrorNote({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-3 border border-danger bg-danger-soft px-4 py-3"
    >
      <p className="font-mono text-[11px] uppercase tracking-[0.08em] text-danger">{message}</p>
      {retry ? (
        <Button size="sm" onClick={retry}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}
