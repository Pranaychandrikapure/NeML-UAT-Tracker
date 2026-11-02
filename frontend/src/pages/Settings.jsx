import { useQueryClient } from "@tanstack/react-query";
import { useApp } from "../context/AppContext";
import { api, act } from "../lib/api";
import { PageHeader, Card, Kv } from "../components/common";
import { label } from "../lib/status";

export default function SettingsPage() {
  const { user, refreshMe } = useApp();
  const qc = useQueryClient();
  const setTheme = (t) => { document.documentElement.classList.toggle("dark", t === "dark"); localStorage.setItem("crems_theme", t); };
  return (
    <div>
      <PageHeader title="Settings" subtitle="Your profile, project access and display preferences." />
      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Profile"><dl className="grid grid-cols-2 gap-4"><Kv k="Name" v={user.name} /><Kv k="Email" v={user.email} /><Kv k="Organisational role" v={user.role_label} /><Kv k="Department" v={user.department} /></dl></Card>
        <Card title="Project access" testid="settings-memberships">{user.memberships.length ? user.memberships.map((m) => (
          <p key={m.project_id} className="flex justify-between border-b py-1.5 text-sm last:border-0"><span>{user.projects.find((p) => p.id === m.project_id)?.name}</span><span className="text-muted-foreground">{label(m.project_role)}</span></p>
        )) : <p className="text-sm text-muted-foreground">{user.role === "system_admin" ? "System Admin — access to all projects." : "No projects assigned."}</p>}</Card>
        <Card title="Appearance"><div className="flex gap-2">{["light", "dark"].map((t) => <button key={t} data-testid={`theme-${t}`} onClick={() => setTheme(t)} className="rounded-md border px-4 py-2 text-sm capitalize hover:bg-muted">{t}</button>)}</div></Card>
        <Card title="Notifications">{!user.real_user_id ? (
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" data-testid="notify-email-toggle" checked={user.notify_email !== false}
            onChange={(e) => act(() => api.patch("/me/preferences", { notify_email: e.target.checked }), "Saved").then(() => { refreshMe(); qc.invalidateQueries(); })} />Receive release emails (SRN notifications)</label>
        ) : <p className="text-sm text-muted-foreground">Preferences are personal — return to your own account to edit them.</p>}
          <p className="mt-2 text-xs text-muted-foreground">In-app notifications are always on.</p></Card>
      </div>
    </div>
  );
}
