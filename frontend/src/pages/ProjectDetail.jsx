import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Archive, Check } from "lucide-react";
import { Button } from "../components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { get, api, act } from "../lib/api";
import { usePrompt } from "../components/Prompt";
import { Card, Empty, Rows, StatusBadge, Kv, Field, Inp, MultiCheck } from "../components/common";
import { fmtDate, label } from "../lib/status";

export default function ProjectDetail() {
  const { id } = useParams();
  const qc = useQueryClient();
  const [ask, promptEl] = usePrompt();
  const [q, setQ] = useState("");
  const { data: p, isLoading } = useQuery({ queryKey: ["project", id], queryFn: () => get(`/projects/${id}`) });
  const users = useQuery({ queryKey: ["users-all"], queryFn: () => get("/users") });
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => get("/meta") });
  const [cfg, setCfg] = useState(null);
  if (isLoading || !p) return <Rows n={8} />;
  const refresh = () => qc.invalidateQueries();
  const pr = p.my_project_role;
  const canManage = ["system_admin", "project_lead", "senior_pm", "pm"].includes(pr);
  const canAdd = canManage || ["team_lead", "developer"].includes(pr);
  const c = cfg || p.config;
  const roleOpts = (meta.data?.roles || []).filter((r) => r.key !== "system_admin").map((r) => ({ value: r.key, label: r.label }));
  const mods = p.modules.filter((m) => !q || m.name.toLowerCase().includes(q.toLowerCase()) || m.screens.some((s) => s.name.toLowerCase().includes(q.toLowerCase())));
  return (
    <div className="space-y-5">
      <div className="fade-up"><p className="font-mono text-xs text-muted-foreground">{p.code} · {p.source}{p.zoho_id ? ` · Zoho ${p.zoho_id}` : ""}</p><h1 className="text-2xl font-bold tracking-tight" data-testid="project-title">{p.name}</h1><p className="text-sm text-muted-foreground">{p.description}</p></div>
      <Tabs defaultValue="modules">
        <TabsList>{[["modules", "Modules & Screens"], ["team", `Team (${p.members.length})`], ["overview", "Overview"], ...(canManage ? [["config", "Release configuration"]] : [])].map(([v, l]) => <TabsTrigger key={v} value={v} data-testid={`project-tab-${v}`}>{l}</TabsTrigger>)}</TabsList>
        <TabsContent value="modules" className="mt-4">
          <Card title="Modules" action={<div className="flex gap-2"><Inp placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} className="h-8 w-40" />{canAdd && <Button size="sm" data-testid="add-module" onClick={() => ask({ title: "New module", description: pr === "developer" || pr === "team_lead" ? "Will be proposed for PM approval." : "", fields: [{ key: "name", label: "Module name", required: true }, { key: "description", label: "Description", type: "textarea" }], onSubmit: (v) => act(() => api.post(`/projects/${id}/modules`, v), "Module added").then(refresh) })}><Plus className="mr-1 h-4 w-4" />Module</Button>}</div>}>
            {!mods.length ? <Empty text="No modules yet" /> : <div className="grid gap-4 lg:grid-cols-2">{mods.map((m) => (
              <div key={m.id} className={`rounded-lg border p-4 ${m.archived ? "opacity-60" : ""}`} data-testid={`module-${m.name}`}>
                <div className="flex items-start justify-between gap-2">
                  <div><p className="font-semibold">{m.name} {m.archived && <span className="text-xs">(archived)</span>}</p><p className="text-xs text-muted-foreground">{m.cr_count} CRs · {m.open_bugs} open bugs · Devs: {m.developers.join(", ") || "—"}</p></div>
                  <div className="flex items-center gap-1">{m.status === "PROPOSED" && <StatusBadge s="PROPOSED" />}
                    {canManage && m.status === "PROPOSED" && <Button size="sm" variant="ghost" title="Approve" onClick={() => act(() => api.patch(`/modules/${m.id}`, { status: "ACTIVE" }), "Approved").then(refresh)}><Check className="h-4 w-4" /></Button>}
                    {canManage && <Button size="sm" variant="ghost" title={m.archived ? "Restore" : "Archive"} onClick={() => act(() => api.patch(`/modules/${m.id}`, { archived: !m.archived }), m.archived ? "Restored" : "Archived").then(refresh)}><Archive className="h-4 w-4" /></Button>}</div>
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">{m.screens.map((s) => <span key={s.id} className={`rounded-md border px-2 py-0.5 text-xs ${s.archived ? "line-through opacity-60" : ""}`}>{s.name}{s.status === "PROPOSED" ? " (proposed)" : ""}</span>)}
                  {canAdd && !m.archived && <button className="rounded-md border border-dashed px-2 py-0.5 text-xs text-primary" data-testid={`add-screen-${m.name}`} onClick={() => ask({ title: `New screen in ${m.name}`, fields: [{ key: "name", label: "Screen name", required: true }], onSubmit: (v) => act(() => api.post(`/modules/${m.id}/screens`, v), "Screen added").then(refresh) })}>+ Screen</button>}</div>
              </div>
            ))}</div>}
          </Card>
        </TabsContent>
        <TabsContent value="team" className="mt-4">
          <Card title="Project members" action={canManage && <Button size="sm" data-testid="add-member" onClick={() => ask({ title: "Add member", description: "Project role can differ from organisational role.", fields: [{ key: "user_id", label: "User", type: "select", required: true, options: (users.data || []).filter((u) => u.role !== "system_admin" && !p.members.some((m) => m.user_id === u.id)).map((u) => ({ value: u.id, label: `${u.name} · ${label(u.role)}` })) }, { key: "project_role", label: "Project role", type: "select", options: roleOpts }], onSubmit: (v) => act(() => api.post(`/projects/${id}/members`, { ...v, project_role: v.project_role || null }), "Member added").then(refresh) })}><Plus className="mr-1 h-4 w-4" />Member</Button>}>
            <table className="tbl w-full"><thead><tr><th>Name</th><th>Email</th><th>Project role</th><th>Org role</th><th></th></tr></thead>
              <tbody>{p.members.map((m) => <tr key={m.user_id}><td>{m.name}</td><td className="text-xs">{m.email}</td><td><StatusBadge s={m.project_role.toUpperCase()} /></td><td className="text-xs">{label(m.role)}</td><td>{canManage && <Button size="sm" variant="ghost" onClick={() => act(() => api.delete(`/projects/${id}/members/${m.user_id}`), "Removed").then(refresh)}>Remove</Button>}</td></tr>)}</tbody></table>
          </Card>
        </TabsContent>
        <TabsContent value="overview" className="mt-4"><Card><dl className="grid gap-4 sm:grid-cols-3">
          <Kv k="Owner" v={p.owner_name} /><Kv k="Owner email" v={p.owner_email} /><Kv k="Status" v={p.status} /><Kv k="Start" v={fmtDate(p.start_date)} /><Kv k="End" v={fmtDate(p.end_date)} /><Kv k="Technology" v={(p.tech_stack || []).join(", ")} /><Kv k="Created" v={fmtDate(p.created_at)} /><Kv k="Last synced" v={fmtDate(p.synced_at)} />
        </dl></Card></TabsContent>
        {canManage && <TabsContent value="config" className="mt-4">
          <Card title="SRN approval stages & email routing" action={<Button size="sm" data-testid="save-project-config" onClick={() => act(() => api.put(`/projects/${id}/config`, c), "Configuration saved").then(() => { setCfg(null); refresh(); })}>Save</Button>}>
            <div className="space-y-4">
              {c.approval_stages.map((st, i) => (
                <div key={st.key} className="rounded-lg border p-3"><p className="text-sm font-semibold">Stage {i + 1}: {st.label}</p>
                  <MultiCheck options={roleOpts} value={st.roles} onChange={(v) => setCfg({ ...c, approval_stages: c.approval_stages.map((x, j) => (j === i ? { ...x, roles: v } : x)) })} />
                  <label className="mt-2 flex items-center gap-2 text-xs"><input type="checkbox" checked={st.all_roles} onChange={(e) => setCfg({ ...c, approval_stages: c.approval_stages.map((x, j) => (j === i ? { ...x, all_roles: e.target.checked } : x)) })} />Every selected role assigned to the project must approve</label></div>
              ))}
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={c.allow_self_approval} onChange={(e) => setCfg({ ...c, allow_self_approval: e.target.checked })} />Allow self-approval (authorised exception — not recommended)</label>
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={c.require_module_approval} onChange={(e) => setCfg({ ...c, require_module_approval: e.target.checked })} />Modules proposed by Team Leads / Developers need PM approval</label>
              <Field label="SRN email — To roles"><MultiCheck options={roleOpts} value={c.email_to_roles} onChange={(v) => setCfg({ ...c, email_to_roles: v })} /></Field>
              <Field label="SRN email — CC roles"><MultiCheck options={roleOpts} value={c.email_cc_roles} onChange={(v) => setCfg({ ...c, email_cc_roles: v })} /></Field>
              <Field label="Additional To (comma separated)"><Inp value={(c.email_extra_to || []).join(", ")} onChange={(e) => setCfg({ ...c, email_extra_to: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} /></Field>
              <Field label="Additional CC (comma separated)"><Inp value={(c.email_extra_cc || []).join(", ")} onChange={(e) => setCfg({ ...c, email_extra_cc: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} /></Field>
            </div>
          </Card>
        </TabsContent>}
      </Tabs>
      {promptEl}
    </div>
  );
}
