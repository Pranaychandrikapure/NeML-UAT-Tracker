import { useState } from "react";
import { Loader2, Inbox } from "lucide-react";
import { Button } from "./ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "./ui/dialog";
import { Skeleton } from "./ui/skeleton";
import { statusClass, label, prioClass } from "../lib/status";

export const StatusBadge = ({ s, testid }) => (
  <span data-testid={testid} className={`inline-flex items-center whitespace-nowrap rounded-md border px-2 py-0.5 text-xs font-medium ${statusClass(s)}`}>{label(s)}</span>
);

export const PrioBadge = ({ p }) => (
  <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ${prioClass(p)}`}>{p}</span>
);

export const PageHeader = ({ title, subtitle, children }) => (
  <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between fade-up">
    <div>
      <h1 className="text-2xl font-bold tracking-tight" data-testid="page-title">{title}</h1>
      {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
    </div>
    <div className="flex flex-wrap gap-2">{children}</div>
  </div>
);

export const Card = ({ title, action, children, className = "", testid }) => (
  <section data-testid={testid} className={`rounded-xl border bg-card shadow-sm ${className}`}>
    {title && (
      <div className="flex items-center justify-between border-b px-4 py-3">
        <h3 className="text-sm font-semibold">{title}</h3>
        {action}
      </div>
    )}
    <div className="p-4">{children}</div>
  </section>
);

export const Empty = ({ text = "Nothing here yet", hint }) => (
  <div className="flex flex-col items-center justify-center py-10 text-center text-muted-foreground" data-testid="empty-state">
    <Inbox className="mb-2 h-8 w-8 opacity-50" />
    <p className="text-sm font-medium">{text}</p>
    {hint && <p className="mt-1 text-xs">{hint}</p>}
  </div>
);

export const Rows = ({ n = 4 }) => (
  <div className="space-y-2">{Array.from({ length: n }).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}</div>
);

export const Field = ({ label: l, children, hint, className = "" }) => (
  <label className={`block ${className}`}>
    <span className="mb-1 block text-xs font-medium text-muted-foreground">{l}</span>
    {children}
    {hint && <span className="mt-1 block text-xs text-muted-foreground">{hint}</span>}
  </label>
);

const base = "w-full rounded-md border bg-background px-3 py-2 text-sm outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-primary/20";
export const Inp = (p) => <input {...p} className={`${base} ${p.className || ""}`} />;
export const Txt = (p) => <textarea rows={3} {...p} className={`${base} ${p.className || ""}`} />;
export const Sel = ({ options, placeholder, ...p }) => (
  <select {...p} className={`${base} ${p.className || ""}`}>
    {placeholder !== undefined && <option value="">{placeholder}</option>}
    {options.map((o) => (typeof o === "string" ? <option key={o} value={o}>{label(o) === o.toUpperCase() ? o : o}</option> : <option key={o.value} value={o.value}>{o.label}</option>))}
  </select>
);

export const MultiCheck = ({ options, value, onChange, testid }) => (
  <div className="flex flex-wrap gap-2" data-testid={testid}>
    {options.map((o) => {
      const v = typeof o === "string" ? o : o.value;
      const on = value.includes(v);
      return (
        <button type="button" key={v} onClick={() => onChange(on ? value.filter((x) => x !== v) : [...value, v])}
          className={`rounded-full border px-3 py-1 text-xs transition-colors ${on ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted"}`}>
          {typeof o === "string" ? o : o.label}
        </button>
      );
    })}
  </div>
);

export function FormDialog({ open, onOpenChange, title, description, children, onSubmit, submitLabel = "Save", testid, wide }) {
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try { await onSubmit(); onOpenChange(false); } catch { } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={`${wide ? "max-w-3xl" : "max-w-lg"} max-h-[90vh] overflow-y-auto`} data-testid={testid}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          {children}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={busy} data-testid={`${testid}-submit`}>{busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}{submitLabel}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export const Kv = ({ k, v }) => (
  <div>
    <dt className="text-xs text-muted-foreground">{k}</dt>
    <dd className="mt-0.5 text-sm font-medium break-words">{v || "—"}</dd>
  </div>
);

export const Timeline = ({ items }) => !items?.length ? <Empty text="No activity yet" /> : (
  <ol className="relative ml-2 space-y-4 border-l pl-5" data-testid="activity-timeline">
    {items.map((a) => (
      <li key={a.id} className="relative">
        <span className="absolute -left-[26px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-background bg-primary" />
        <p className="text-sm"><span className="font-medium">{a.actor_name}</span> <span className="text-muted-foreground">· {label(a.action)}</span></p>
        {(a.before?.status || a.after?.status) && <p className="text-xs text-muted-foreground">{a.before?.status ? label(a.before.status) + " → " : ""}{label(a.after?.status)}</p>}
        {a.comment && <p className="mt-1 rounded-md bg-muted/60 px-2 py-1 text-xs">{a.comment}</p>}
        <p className="text-xs text-muted-foreground">{new Date(a.at).toLocaleString()}{a.real_user_id ? " · via admin act-as" : ""}</p>
      </li>
    ))}
  </ol>
);
