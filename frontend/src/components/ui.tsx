/** Small, unstyled-by-default UI primitives shared across the shell panels. */

import type { ButtonHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";

type ButtonVariant = "primary" | "subtle" | "ghost" | "danger";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  active?: boolean;
}

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-accent text-surface-0 hover:brightness-110",
  subtle: "bg-surface-3 text-gray-100 hover:bg-surface-2",
  ghost: "bg-transparent text-gray-300 hover:bg-surface-2",
  danger: "bg-red-600/90 text-white hover:bg-red-500",
};

export function Button({ variant = "subtle", active = false, className = "", ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      className={`inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
        active ? "bg-accent text-surface-0" : BUTTON_VARIANTS[variant]
      } ${className}`}
      {...rest}
    />
  );
}

export function Panel({
  title,
  children,
  actions,
  className = "",
}: {
  title?: string;
  children: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`flex min-h-0 flex-col rounded-lg border border-border-subtle bg-surface-1 ${className}`}>
      {title ? (
        <header className="flex items-center justify-between border-b border-border-subtle px-3 py-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-wider text-gray-400">{title}</h2>
          {actions}
        </header>
      ) : null}
      <div className="min-h-0 flex-1 overflow-y-auto p-3">{children}</div>
    </section>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] font-medium uppercase tracking-wide text-gray-400">{label}</span>
      {children}
      {hint ? <span className="text-[11px] text-gray-500">{hint}</span> : null}
    </label>
  );
}

export function Select({ className = "", ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={`rounded-md border border-border-subtle bg-surface-2 px-2 py-1.5 text-xs text-gray-100 outline-none focus:border-accent ${className}`}
      {...rest}
    />
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string; title?: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div className="inline-flex rounded-md border border-border-subtle bg-surface-2 p-0.5">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          title={option.title}
          onClick={() => onChange(option.value)}
          className={`rounded px-2 py-1 text-[11px] font-medium transition-colors ${
            value === option.value ? "bg-accent text-surface-0" : "text-gray-400 hover:text-gray-100"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Row({ label, value, mono = false }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-0.5 text-xs">
      <span className="text-gray-500">{label}</span>
      <span className={`text-right text-gray-200 ${mono ? "font-mono" : ""}`}>{value}</span>
    </div>
  );
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "good" | "warn" | "bad" }) {
  const tones = {
    neutral: "bg-surface-3 text-gray-300",
    good: "bg-emerald-500/20 text-emerald-300",
    warn: "bg-amber-500/20 text-amber-300",
    bad: "bg-red-500/20 text-red-300",
  } as const;
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-xs text-gray-400">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-surface-3 border-t-accent" />
      {label}
    </span>
  );
}
