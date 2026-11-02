import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, FolderKanban } from "lucide-react";
import { Button } from "../components/ui/button";
import { get, api, act } from "../lib/api";
import { useApp } from "../context/AppContext";
import { PageHeader, Empty, Rows, StatusBadge, FormDialog, Field, Inp, Txt, MultiCheck } from "../components/common";
import { fmtDate } from "../lib/status";

export default function Projects() {
  const { user, refreshMe } = useApp();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", code: "", description: "", owner_name: "", start_date: "", end_date: "", tech_stack: [] });
  const { data, isLoading } = useQuery({ queryKey: ["projects", q], queryFn: () => get("/projects", { q }) });
  const tech = useQuery({ queryKey: ["tech"], queryFn: () => get("/master/tech") });
  const s = (k) => (e) => setF({ ...f, [k]: e.target.value });
  return (
    <div>
      <PageHeader title="Projects" subtitle="Projects from Zoho sync or created in CReMS, with their modules, screens and teams.">
        <Inp data-testid="project-search" placeholder="Search projects" value={q} onChange={(e) => setQ(e.target.value)} className="w-56" />
        {user.can_create_projects && <Button data-testid="new-project-button" onClick={() => setOpen(true)}><Plus className="mr-2 h-4 w-4" />New project</Button>}
      </PageHeader>
      {isLoading ? <Rows n={6} /> : !data.length ? <Empty text="No projects available" hint="You'll see projects once you're assigned to one, or after Zoho sync." /> : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{data.map((p, i) => (
          <Link key={p.id} to={`/projects/${p.id}`} data-testid={`project-card-${p.code}`} style={{ animationDelay: `${i * 30}ms` }} className="fade-up rounded-xl border bg-card p-5 shadow-sm transition-[border-color,transform] hover:-translate-y-0.5 hover:border-primary/40">
            <div className="flex items-start justify-between gap-2"><div className="flex items-center gap-2"><FolderKanban className="h-5 w-5 text-primary" /><span className="font-mono text-xs text-muted-foreground">{p.code}</span></div><span className="rounded border px-1.5 py-0.5 text-[10px] font-semibold">{p.source}</span></div>
            <h3 className="mt-2 font-semibold">{p.name}</h3>
            <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{p.description || "—"}</p>
            <div className="mt-4 grid grid-cols-4 gap-2 text-center text-xs">{[["Open CRs", p.open_crs], ["Bugs", p.open_bugs], ["Modules", p.module_count], ["Members", p.member_count]].map(([k, v]) => <div key={k} className="rounded-md bg-muted/60 py-1.5"><p className="font-heading text-base font-bold">{v}</p><p className="text-muted-foreground">{k}</p></div>)}</div>
            <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground"><StatusBadge s={(p.status || "Active").toUpperCase() === "ACTIVE" ? "ACTIVE" : p.status} /><span>{fmtDate(p.start_date)} – {fmtDate(p.end_date)}</span></div>
          </Link>
        ))}</div>
      )}
      <FormDialog open={open} onOpenChange={setOpen} title="New project" testid="new-project-dialog" onSubmit={() => act(() => api.post("/projects", { ...f, start_date: f.start_date || null, end_date: f.end_date || null }), "Project created").then(() => { qc.invalidateQueries(); refreshMe(); })}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name *"><Inp required data-testid="project-form-name" value={f.name} onChange={s("name")} /></Field>
          <Field label="Code *"><Inp required data-testid="project-form-code" value={f.code} onChange={s("code")} /></Field>
          <Field label="Description" className="sm:col-span-2"><Txt value={f.description} onChange={s("description")} /></Field>
          <Field label="Owner"><Inp value={f.owner_name} onChange={s("owner_name")} /></Field><div />
          <Field label="Start"><Inp type="date" value={f.start_date} onChange={s("start_date")} /></Field>
          <Field label="End"><Inp type="date" value={f.end_date} onChange={s("end_date")} /></Field>
          <Field label="Technology stack" className="sm:col-span-2"><MultiCheck options={tech.data || []} value={f.tech_stack} onChange={(v) => setF({ ...f, tech_stack: v })} /></Field>
        </div>
      </FormDialog>
    </div>
  );
}
