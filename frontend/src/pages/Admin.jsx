import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCw, Upload, ChevronRight, ChevronDown } from "lucide-react";
import { Button } from "../components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { get, api, act } from "../lib/api";
import { useApp } from "../context/AppContext";
import { PageHeader, Card, Empty, Rows, StatusBadge, FormDialog, Field, Inp, Sel, Txt } from "../components/common";
import { fmt, label } from "../lib/status";

const BRANCH = { root: "bg-slate-900 text-white", dev: "border-blue-300 bg-blue-50 dark:bg-blue-950/40", ba: "border-purple-300 bg-purple-50 dark:bg-purple-950/40", uat: "border-orange-300 bg-orange-50 dark:bg-orange-950/40" };

function TreeNode({ n, roles, depth = 0 }) {
  const [open, setOpen] = useState(depth < 3);
  const br = roles.find((r) => r.key === n.role)?.branch || "dev";
  return (
    <li className="mt-2">
      <div className="flex items-center gap-1">
        {n.children.length ? <button onClick={() => setOpen(!open)} className="p-0.5">{open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</button> : <span className="w-5" />}
        <div className={`rounded-lg border px-3 py-1.5 text-sm ${BRANCH[br]} ${n.active ? "" : "opacity-50"}`} data-testid={`org-node-${n.id}`}><b>{n.name}</b> <span className="text-xs opacity-80">· {n.role_label}</span></div>
      </div>
      {open && n.children.length > 0 && <ul className="ml-6 border-l pl-3">{n.children.map((c) => <TreeNode key={c.id} n={c} roles={roles} depth={depth + 1} />)}</ul>}
    </li>
  );
}

function UserDialog({ open, onOpenChange, edit }) {
  const { user } = useApp();
  const qc = useQueryClient();
  const users = useQuery({ queryKey: ["users-all"], queryFn: () => get("/users") });
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => get("/meta") });
  const [f, setF] = useState(edit ? { ...edit, projects: edit.memberships.map((m) => ({ project_id: m.project_id, project_role: m.project_role })) } : { name: "", email: "", role: user.grantable_roles[0] || "", reporting_manager_id: user.id, department: "", active: true, notify_email: true, projects: [], can_create_developers: false });
  const s = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const roleOpts = (meta.data?.roles || []).filter((r) => user.grantable_roles.includes(r.key)).map((r) => ({ value: r.key, label: r.label }));
  const toggleProj = (pid) => setF({ ...f, projects: f.projects.some((p) => p.project_id === pid) ? f.projects.filter((p) => p.project_id !== pid) : [...f.projects, { project_id: pid, project_role: f.role }] });
  const submit = () => {
    const body = { name: f.name, role: f.role, reporting_manager_id: f.reporting_manager_id || null, department: f.department, active: f.active, notify_email: f.notify_email, projects: f.projects, can_create_developers: f.can_create_developers };
    return act(() => (edit ? api.patch(`/users/${edit.id}`, body) : api.post("/users", { ...body, email: f.email })), edit ? "User updated" : "User created").then(() => qc.invalidateQueries());
  };
  return (
    <FormDialog open={open} onOpenChange={onOpenChange} title={edit ? `Edit ${edit.name}` : "Create user"} description="Users sign in with Google or email using exactly this address. Only roles you are allowed to grant are listed." onSubmit={submit} testid="user-dialog" wide>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Full name *"><Inp required data-testid="user-form-name" value={f.name} onChange={s("name")} /></Field>
        <Field label="Official email *"><Inp required type="email" disabled={!!edit} data-testid="user-form-email" value={f.email} onChange={s("email")} /></Field>
        <Field label="Organisational role *"><Sel required data-testid="user-form-role" value={f.role} onChange={s("role")} options={edit && !roleOpts.some((r) => r.value === f.role) ? [{ value: f.role, label: label(f.role) }, ...roleOpts] : roleOpts} /></Field>
        <Field label="Reporting manager"><Sel data-testid="user-form-manager" value={f.reporting_manager_id || ""} onChange={s("reporting_manager_id")} options={(users.data || []).filter((u) => u.id !== edit?.id).map((u) => ({ value: u.id, label: `${u.name} · ${label(u.role)}` }))} placeholder="None" /></Field>
        <Field label="Department / team"><Inp value={f.department} onChange={s("department")} /></Field>
        <div className="flex flex-col justify-end gap-2 text-sm">
          <label className="flex items-center gap-2"><input type="checkbox" checked={f.active} onChange={(e) => setF({ ...f, active: e.target.checked })} data-testid="user-form-active" />Active</label>
          <label className="flex items-center gap-2"><input type="checkbox" checked={f.notify_email} onChange={(e) => setF({ ...f, notify_email: e.target.checked })} />Email notifications</label>
          {f.role === "team_lead" && <label className="flex items-center gap-2"><input type="checkbox" checked={f.can_create_developers} onChange={(e) => setF({ ...f, can_create_developers: e.target.checked })} />Delegated: may create Developers</label>}
        </div>
        <Field label="Project assignments & project-specific role" className="sm:col-span-2">
          <div className="space-y-2" data-testid="user-form-projects">{user.projects.map((p) => {
            const m = f.projects.find((x) => x.project_id === p.id);
            return <div key={p.id} className="flex items-center gap-3 rounded-md border p-2"><label className="flex flex-1 items-center gap-2 text-sm"><input type="checkbox" checked={!!m} onChange={() => toggleProj(p.id)} />{p.name}</label>
              {m && <Sel className="w-52" value={m.project_role} onChange={(e) => setF({ ...f, projects: f.projects.map((x) => (x.project_id === p.id ? { ...x, project_role: e.target.value } : x)) })} options={(meta.data?.roles || []).filter((r) => r.key !== "system_admin").map((r) => ({ value: r.key, label: r.label }))} />}</div>;
          })}</div>
        </Field>
      </div>
    </FormDialog>
  );
}

function Users() {
  const { user } = useApp();
  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [dlg, setDlg] = useState(null);
  const { data, isLoading } = useQuery({ queryKey: ["users", q, role], queryFn: () => get("/users", { q, role }) });
  return (
    <Card title="Users" action={user.grantable_roles.length > 0 && <Button size="sm" data-testid="create-user-button" onClick={() => setDlg({})}><Plus className="mr-1 h-4 w-4" />Create user</Button>}>
      <div className="mb-3 flex gap-2"><Inp data-testid="user-search" placeholder="Search name or email" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-xs" /><Sel value={role} onChange={(e) => setRole(e.target.value)} options={["system_admin", "project_lead", "senior_pm", "pm", "team_lead", "developer", "ba_lead", "ba", "uat_lead", "uat_manager", "uat_member"].map((r) => ({ value: r, label: label(r) }))} placeholder="All roles" className="w-48" /></div>
      {isLoading ? <Rows /> : !data.length ? <Empty text="No users" /> : (
        <div className="overflow-x-auto"><table className="tbl w-full" data-testid="users-table"><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Projects</th><th>Status</th><th>Last login</th><th></th></tr></thead>
          <tbody>{data.map((u) => <tr key={u.id} data-testid={`user-row-${u.email}`}><td>{u.name}{u.is_demo && <span className="ml-1 rounded bg-amber-100 px-1 text-[10px] text-amber-800">DEMO</span>}</td><td className="text-xs">{u.email}</td><td>{label(u.role)}</td><td className="text-xs">{u.memberships.length}</td><td><StatusBadge s={u.active ? "ACTIVE" : "CANCELLED"} /></td><td className="text-xs">{fmt(u.last_login)}</td>
            <td>{u.can_manage && u.id !== user.id && <Button size="sm" variant="ghost" onClick={() => setDlg(u)} data-testid={`edit-user-${u.email}`}>Edit</Button>}</td></tr>)}</tbody></table></div>
      )}
      {dlg && <UserDialog open onOpenChange={() => setDlg(null)} edit={dlg.id ? dlg : null} />}
    </Card>
  );
}

function Zoho() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["zoho"], queryFn: () => get("/integrations/zoho") });
  const [cfg, setCfg] = useState(null);
  const [json, setJson] = useState("");
  const [imp, setImp] = useState(false);
  if (isLoading) return <Rows />;
  const c = cfg || data.config;
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card title="Zoho Projects connection" action={<span data-testid="zoho-connection-status" className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${data.connected ? "bg-emerald-100 text-emerald-800" : "bg-slate-200 text-slate-700"}`}>{data.connected ? "Configured" : "Not connected"}</span>}>
        <p className="mb-3 text-xs text-muted-foreground">OAuth credentials are server secrets: {Object.entries(data.credentials_present).map(([k, v]) => `${k} ${v ? "✓" : "missing"}`).join(" · ")}</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Data centre"><Sel value={c.dc} onChange={(e) => setCfg({ ...c, dc: e.target.value })} options={["in", "com", "eu", "com.au", "jp"]} /></Field>
          <Field label="Portal ID"><Inp data-testid="zoho-portal" value={c.portal_id} onChange={(e) => setCfg({ ...c, portal_id: e.target.value })} /></Field>
          <Field label="CR records come from"><Sel value={c.cr_entity} onChange={(e) => setCfg({ ...c, cr_entity: e.target.value })} options={[{ value: "tasks", label: "Tasks" }, { value: "bugs", label: "Issues / Bugs" }]} /></Field>
          <Field label="Match keyword (name / tasklist)"><Inp value={c.cr_match} onChange={(e) => setCfg({ ...c, cr_match: e.target.value })} /></Field>
          <Field label="Default BA email for new CRs" className="sm:col-span-2"><Inp value={c.default_ba_email} onChange={(e) => setCfg({ ...c, default_ba_email: e.target.value })} /></Field>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button size="sm" variant="outline" data-testid="zoho-save" onClick={() => act(() => api.put("/integrations/zoho", c), "Saved").then(() => { setCfg(null); qc.invalidateQueries({ queryKey: ["zoho"] }); })}>Save config</Button>
          <Button size="sm" data-testid="zoho-sync-now" onClick={() => act(() => api.post("/integrations/zoho/sync")).then(() => qc.invalidateQueries())}><RefreshCw className="mr-1.5 h-4 w-4" />Sync now</Button>
          <Button size="sm" variant="outline" data-testid="zoho-import-open" onClick={() => setImp(true)}><Upload className="mr-1.5 h-4 w-4" />Import Zoho JSON</Button>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">{data.zoho_projects} projects and {data.zoho_crs} CRs originate from Zoho. Sync never overwrites assignments, approvals or workflow status.</p>
      </Card>
      <Card title="Sync history & health" testid="zoho-jobs">{!data.jobs.length ? <Empty text="No sync runs yet" /> : data.jobs.map((j) => (
        <div key={j.id} className="border-b py-2 text-sm last:border-0"><div className="flex justify-between"><span>{fmt(j.started_at)} · {j.kind || "SYNC"} · {j.by}</span><StatusBadge s={j.status} /></div>
          <p className="text-xs text-muted-foreground">{j.projects} projects · {j.created} created · {j.updated} updated</p>{j.errors?.map((e, i) => <p key={i} className="text-xs text-rose-600">{e}</p>)}</div>
      ))}</Card>
      <FormDialog open={imp} onOpenChange={setImp} title="Import Zoho project list JSON" description="Paste a Zoho Projects list-view JSON export. Projects are upserted by Zoho ID (no duplicates)." onSubmit={() => act(() => api.post("/integrations/zoho/import", { payload: json }), "Import complete").then(() => qc.invalidateQueries())} testid="zoho-import-dialog">
        <Txt rows={10} data-testid="zoho-import-json" value={json} onChange={(e) => setJson(e.target.value)} className="font-mono text-xs" />
      </FormDialog>
    </div>
  );
}

function Emails() {
  const { data, isLoading } = useQuery({ queryKey: ["emails"], queryFn: () => get("/emails"), refetchInterval: 15000 });
  return <Card title="Email outbox">{isLoading ? <Rows /> : !data.length ? <Empty text="No emails yet" /> : (
    <table className="tbl w-full" data-testid="email-table"><thead><tr><th>Created</th><th>Subject</th><th>To / CC</th><th>Attempts</th><th>Status</th><th>Error</th></tr></thead>
      <tbody>{data.map((m) => <tr key={m.id}><td className="text-xs">{fmt(m.created_at)}</td><td className="text-sm">{m.subject}</td><td className="text-xs">{m.to.join(", ")}<br />{m.cc.join(", ")}</td><td>{m.attempts}</td><td><StatusBadge s={m.status} /></td><td className="max-w-[200px] text-xs text-rose-600">{m.last_error}</td></tr>)}</tbody></table>
  )}</Card>;
}

function Audit() {
  const [et, setEt] = useState("");
  const { data, isLoading } = useQuery({ queryKey: ["audit", et], queryFn: () => get("/audit", { entity_type: et }) });
  return <Card title="Audit log (read-only)" action={<Sel value={et} onChange={(e) => setEt(e.target.value)} options={["cr", "task", "srn", "bug", "uat", "user", "project", "integration", "settings"]} placeholder="All entities" className="h-8 w-40" />}>
    {isLoading ? <Rows /> : <div className="overflow-x-auto"><table className="tbl w-full" data-testid="audit-table"><thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Entity</th><th>Change</th><th>Comment</th></tr></thead>
      <tbody>{data.map((a) => <tr key={a.id}><td className="whitespace-nowrap text-xs">{fmt(a.at)}</td><td>{a.actor_name}<br /><span className="text-xs text-muted-foreground">{label(a.actor_role)}{a.real_user_id ? " · act-as" : ""}</span></td><td className="text-xs font-medium">{label(a.action)}</td><td className="text-xs">{a.entity_type}</td><td className="max-w-[260px] truncate font-mono text-[11px]">{a.after ? JSON.stringify(a.after) : ""}</td><td className="text-xs">{a.comment}</td></tr>)}</tbody></table></div>}
  </Card>;
}

function Grants() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["grants"], queryFn: () => get("/settings/grant-policies") });
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => get("/meta") });
  const [p, setP] = useState(null);
  const [dom, setDom] = useState(null);
  if (!data || !meta.data) return <Rows />;
  const pol = p || data.policies;
  const roles = meta.data.roles;
  return <Card title="Role-grant policies" action={<Button size="sm" data-testid="save-grants" onClick={() => act(() => api.put("/settings/grant-policies", { policies: pol, allowed_domains: (dom ?? data.allowed_domains.join(", ")).split(",").map((x) => x.trim()).filter(Boolean) }), "Policies saved").then(() => qc.invalidateQueries())}>Save</Button>}>
    <p className="mb-3 text-xs text-muted-foreground">Which roles each role may create. Enforced by the backend on every user API call.</p>
    <div className="overflow-x-auto"><table className="tbl w-full text-xs"><thead><tr><th>Creator ↓ / Can grant →</th>{roles.map((r) => <th key={r.key} className="!text-[10px]">{r.label}</th>)}</tr></thead>
      <tbody>{roles.filter((r) => r.key !== "system_admin").map((c) => <tr key={c.key}><td className="font-medium">{c.label}</td>{roles.map((r) => <td key={r.key} className="text-center"><input type="checkbox" checked={(pol[c.key] || []).includes(r.key)} onChange={(e) => setP({ ...pol, [c.key]: e.target.checked ? [...(pol[c.key] || []), r.key] : (pol[c.key] || []).filter((x) => x !== r.key) })} /></td>)}</tr>)}</tbody></table></div>
    <Field label="Organisation-approved email domains (comma separated, empty = any)" className="mt-4"><Inp data-testid="allowed-domains" value={dom ?? data.allowed_domains.join(", ")} onChange={(e) => setDom(e.target.value)} placeholder="neml.in" /></Field>
  </Card>;
}

export default function Admin() {
  const { user } = useApp();
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => get("/meta") });
  const tree = useQuery({ queryKey: ["org-tree"], queryFn: () => get("/org-tree") });
  const admin = user.role === "system_admin";
  return (
    <div>
      <PageHeader title="Administration" subtitle="Users, organisation hierarchy, integrations, email delivery and audit." />
      <Tabs defaultValue="users">
        <TabsList className="flex h-auto flex-wrap justify-start">{[["users", "Users"], ["tree", "Organisation tree"], ...(admin ? [["zoho", "Zoho integration"], ["emails", "Email outbox"], ["audit", "Audit log"], ["grants", "Role policies"]] : [])].map(([v, l]) => <TabsTrigger key={v} value={v} data-testid={`admin-tab-${v}`}>{l}</TabsTrigger>)}</TabsList>
        <TabsContent value="users" className="mt-4"><Users /></TabsContent>
        <TabsContent value="tree" className="mt-4"><Card title="Organisation hierarchy">{tree.isLoading || !meta.data ? <Rows /> : <ul data-testid="org-tree">{tree.data.map((n) => <TreeNode key={n.id} n={n} roles={meta.data.roles} />)}</ul>}</Card></TabsContent>
        {admin && <><TabsContent value="zoho" className="mt-4"><Zoho /></TabsContent><TabsContent value="emails" className="mt-4"><Emails /></TabsContent><TabsContent value="audit" className="mt-4"><Audit /></TabsContent><TabsContent value="grants" className="mt-4"><Grants /></TabsContent></>}
      </Tabs>
    </div>
  );
}
