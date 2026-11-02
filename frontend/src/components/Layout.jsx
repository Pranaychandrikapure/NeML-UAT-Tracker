import { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { UserButton } from "@clerk/react";
import { LayoutDashboard, FileText, ListTodo, CheckSquare, Rocket, FlaskConical, Bug, FolderKanban, BarChart3, Shield, Settings, Bell, Search, PanelLeftClose, PanelLeftOpen, Moon, Sun, UserCog, Layers } from "lucide-react";
import { useApp } from "../context/AppContext";
import { get, api } from "../lib/api";
import { label } from "../lib/status";
import { Popover, PopoverContent, PopoverTrigger } from "./ui/popover";

const NAV = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard", end: true },
  { to: "/crs", icon: FileText, label: "Change Requests" },
  { to: "/tasks", icon: ListTodo, label: "My Tasks" },
  { to: "/approvals", icon: CheckSquare, label: "Approvals" },
  { to: "/srns", icon: Rocket, label: "SRN / Releases" },
  { to: "/uat", icon: FlaskConical, label: "UAT Management" },
  { to: "/bugs", icon: Bug, label: "Bug Tracker" },
  { to: "/projects", icon: FolderKanban, label: "Projects" },
  { to: "/reports", icon: BarChart3, label: "Reports" },
  { to: "/admin", icon: Shield, label: "Administration", perm: "admin" },
  { to: "/settings", icon: Settings, label: "Settings" },
];

function Notifications() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const { data } = useQuery({ queryKey: ["notifications"], queryFn: () => get("/notifications"), refetchInterval: 30000 });
  const open = async (n) => {
    await api.post("/notifications/read", { ids: [n.id] });
    qc.invalidateQueries({ queryKey: ["notifications"] });
    nav(n.link);
  };
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button data-testid="notifications-button" className="relative rounded-md p-2 hover:bg-muted">
          <Bell className="h-5 w-5" />
          {data?.unread > 0 && <span data-testid="notifications-unread" className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-rose-600 px-1 text-[10px] font-bold text-white">{data.unread}</span>}
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 p-0">
        <div className="flex items-center justify-between border-b px-4 py-2.5">
          <span className="text-sm font-semibold">Notifications</span>
          <button className="text-xs text-primary" data-testid="notifications-mark-all" onClick={async () => { await api.post("/notifications/read", { ids: [] }); qc.invalidateQueries({ queryKey: ["notifications"] }); }}>Mark all read</button>
        </div>
        <div className="max-h-96 overflow-y-auto">
          {!data?.items?.length && <p className="p-6 text-center text-sm text-muted-foreground">You're all caught up</p>}
          {data?.items?.map((n) => (
            <button key={n.id} onClick={() => open(n)} className={`block w-full border-b px-4 py-2.5 text-left hover:bg-muted ${n.read ? "opacity-60" : ""}`}>
              <p className="text-sm font-medium">{!n.read && <span className="mr-1.5 inline-block h-2 w-2 rounded-full bg-primary" />}{n.title}</p>
              {n.body && <p className="truncate text-xs text-muted-foreground">{n.body}</p>}
              <p className="text-[11px] text-muted-foreground">{new Date(n.at).toLocaleString()}</p>
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function GlobalSearch() {
  const [q, setQ] = useState("");
  const nav = useNavigate();
  const { data } = useQuery({ queryKey: ["search", q], queryFn: () => get("/search", { q }), enabled: q.length > 1 });
  const go = (to) => { setQ(""); nav(to); };
  return (
    <div className="relative hidden w-full max-w-sm md:block">
      <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
      <input data-testid="global-search-input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search CRs, SRNs, bugs…" className="w-full rounded-md border bg-background py-2 pl-9 pr-3 text-sm outline-none focus:border-primary" />
      {q.length > 1 && data && (
        <div className="absolute z-50 mt-1 w-full rounded-md border bg-popover p-1 shadow-lg">
          {[...data.crs.map((x) => ["CR", x.number, x.title, `/crs/${x.id}`]), ...data.srns.map((x) => ["SRN", x.number, x.release_version, `/srns/${x.id}`]), ...data.bugs.map((x) => ["Bug", x.number, x.title, `/bugs?id=${x.id}`])].map(([t, n, d, to]) => (
            <button key={to} onClick={() => go(to)} className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-muted">
              <span className="w-9 text-xs text-muted-foreground">{t}</span><span className="font-mono text-xs">{n}</span><span className="truncate">{d}</span>
            </button>
          ))}
          {!data.crs.length && !data.srns.length && !data.bugs.length && <p className="p-2 text-sm text-muted-foreground">No matches</p>}
        </div>
      )}
    </div>
  );
}

export default function Layout({ children }) {
  const { user, projectId, setProjectId, actAs } = useApp();
  const [collapsed, setCollapsed] = useState(false);
  const [dark, setDark] = useState(document.documentElement.classList.contains("dark"));
  const toggleTheme = () => { document.documentElement.classList.toggle("dark"); localStorage.setItem("crems_theme", dark ? "light" : "dark"); setDark(!dark); };
  const realAdmin = user?.demo_users;
  return (
    <div className="flex min-h-screen">
      <aside className={`sticky top-0 hidden h-screen shrink-0 flex-col border-r bg-card transition-[width] duration-200 md:flex ${collapsed ? "w-16" : "w-64"}`} data-testid="sidebar">
        <div className="flex h-16 items-center gap-2 border-b px-4">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground"><Layers className="h-4 w-4" /></div>
          {!collapsed && <div><p className="font-heading text-base font-bold leading-none">CReMS</p><p className="text-[11px] text-muted-foreground">Change & Release</p></div>}
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto p-2">
          {NAV.filter((n) => n.perm !== "admin" || user?.role === "system_admin" || user?.grantable_roles?.length).map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} data-testid={`nav-${n.label.toLowerCase().replace(/[^a-z]+/g, "-")}`} title={n.label}
              className={({ isActive }) => `flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors ${isActive ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}>
              <n.icon className="h-4 w-4 shrink-0" />{!collapsed && n.label}
            </NavLink>
          ))}
        </nav>
        <button onClick={() => setCollapsed(!collapsed)} data-testid="sidebar-toggle" className="m-2 flex items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-muted">
          {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <><PanelLeftClose className="h-4 w-4" /> Collapse</>}
        </button>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        {user?.real_user_id && (
          <div className="flex items-center justify-between bg-amber-100 px-4 py-1.5 text-xs text-amber-900 dark:bg-amber-900/40 dark:text-amber-100" data-testid="act-as-banner">
            <span><b>Demo mode:</b> acting as {user.name} · {user.role_label}. Actions are audited against your admin account.</span>
            <button className="font-semibold underline" data-testid="act-as-exit" onClick={() => actAs("")}>Return to my account</button>
          </div>
        )}
        <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b bg-card/90 px-4 backdrop-blur">
          <select data-testid="project-selector" value={projectId} onChange={(e) => setProjectId(e.target.value)} className="max-w-[200px] rounded-md border bg-background px-2 py-2 text-sm">
            <option value="">All my projects</option>
            {user?.projects?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <GlobalSearch />
          <div className="ml-auto flex items-center gap-1">
            {realAdmin && (
              <select data-testid="act-as-select" value={user.real_user_id ? user.id : ""} onChange={(e) => actAs(e.target.value)} className="hidden max-w-[210px] rounded-md border bg-amber-50 px-2 py-2 text-xs dark:bg-amber-950 lg:block" title="Demo: view CReMS as another role">
                <option value="">View as: myself (Admin)</option>
                {user.demo_users.map((d) => <option key={d.id} value={d.id}>{d.name.replace(" (Demo)", "")} — {label(d.role)}</option>)}
              </select>
            )}
            <button onClick={toggleTheme} data-testid="theme-toggle" className="rounded-md p-2 hover:bg-muted">{dark ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}</button>
            <Notifications />
            <div className="ml-2 hidden text-right sm:block">
              <p className="text-sm font-medium leading-none" data-testid="header-user-name">{user?.name}</p>
              <p className="text-[11px] text-muted-foreground">{user?.role_label}</p>
            </div>
            <div className="ml-2"><UserButton /></div>
          </div>
        </header>
        <nav className="flex gap-1 overflow-x-auto border-b bg-card px-2 py-1.5 md:hidden">
          {NAV.filter((n) => n.perm !== "admin" || user?.role === "system_admin").map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs ${isActive ? "bg-primary/10 text-primary" : "text-muted-foreground"}`}><n.icon className="h-3.5 w-3.5" />{n.label}</NavLink>
          ))}
        </nav>
        <main className="mx-auto w-full max-w-[1500px] flex-1 p-4 md:p-8">{children}</main>
      </div>
    </div>
  );
}
