import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ClipboardCheck, Code2, TestTube2, PackageCheck, FileSignature, Truck, FlaskConical, PauseCircle, Flame, Bug, AlarmClock, CheckCircle2, ArrowRight } from "lucide-react";
import { get } from "../lib/api";
import { useApp } from "../context/AppContext";
import { PageHeader, Card, Empty, Rows, StatusBadge, PrioBadge, Inp, Sel } from "../components/common";
import { fmt, fmtDate, label, PRIORITIES } from "../lib/status";

const KPIS = [
  ["crs_pending_approval", "CRs Pending Approval", ClipboardCheck, "text-amber-600", "/crs?status=NEW,BA_REVIEW,DEADLINE_APPROVAL_PENDING"],
  ["development_pending", "Development Pending", Code2, "text-sky-600", "/crs?status=IMPACT_ANALYSIS,ASSIGNED,IN_DEVELOPMENT"],
  ["sit_pending", "SIT Pending", TestTube2, "text-indigo-600", "/crs?status=SIT_IN_PROGRESS"],
  ["ready_for_uat", "Ready for UAT", PackageCheck, "text-teal-600", "/crs?status=READY_FOR_UAT"],
  ["srn_approval_pending", "SRN Approval Pending", FileSignature, "text-purple-600", "/srns?status=IN_REVIEW,ON_HOLD"],
  ["uat_deployment_pending", "UAT Deployment Pending", Truck, "text-violet-600", "/crs?status=UAT_DEPLOYMENT_PENDING"],
  ["uat_pending", "UAT Pending", FlaskConical, "text-orange-600", "/crs?status=UAT_DEPLOYED,UAT_IN_PROGRESS"],
  ["uat_hold", "UAT Hold", PauseCircle, "text-amber-600", "/crs?status=UAT_HOLD"],
  ["high_priority", "High Priority CRs", Flame, "text-rose-600", "/crs?priority=Critical,High"],
  ["open_bugs", "Open Bugs", Bug, "text-red-600", "/bugs"],
  ["overdue", "Overdue CRs", AlarmClock, "text-rose-700", "/crs"],
  ["completed", "Completed CRs", CheckCircle2, "text-emerald-600", "/crs?status=CLOSED"],
];

export default function Dashboard() {
  const { user, projectId } = useApp();
  const [f, setF] = useState({ priority: "", source: "", date_from: "", date_to: "" });
  const { data, isLoading } = useQuery({ queryKey: ["dashboard", projectId, f], queryFn: () => get("/dashboard", { project_id: projectId, ...f }) });
  const k = data?.kpis || {};
  return (
    <div>
      <PageHeader title={`Welcome, ${user?.name?.split(" ")[0] || ""}`} subtitle={`${user?.role_label} · Your consolidated view across ${projectId ? "the selected project" : "all your projects"}`}>
        <Sel data-testid="dash-filter-priority" value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value })} options={PRIORITIES} placeholder="Any priority" className="w-36" />
        <Sel data-testid="dash-filter-source" value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })} options={[{ value: "ZOHO", label: "Zoho" }, { value: "INTERNAL", label: "Internal" }]} placeholder="Any source" className="w-32" />
        <Inp type="date" data-testid="dash-filter-from" value={f.date_from} onChange={(e) => setF({ ...f, date_from: e.target.value })} className="w-40" />
        <Inp type="date" data-testid="dash-filter-to" value={f.date_to} onChange={(e) => setF({ ...f, date_to: e.target.value })} className="w-40" />
      </PageHeader>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
        {KPIS.map(([key, t, I, c, to], i) => (
          <Link key={key} to={to} data-testid={`kpi-${key}`} style={{ animationDelay: `${i * 30}ms` }}
            className="fade-up group rounded-xl border bg-card p-4 shadow-sm transition-[border-color,transform] hover:-translate-y-0.5 hover:border-primary/40">
            <div className="flex items-center justify-between"><I className={`h-5 w-5 ${c}`} /><ArrowRight className="h-3.5 w-3.5 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" /></div>
            <p className="mt-3 font-heading text-3xl font-bold" data-testid={`kpi-${key}-value`}>{isLoading ? "–" : k[key] ?? 0}</p>
            <p className="mt-0.5 text-xs font-medium text-muted-foreground">{t}</p>
          </Link>
        ))}
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card title={`My Pending Actions (${data?.pending_actions?.length || 0})`} className="lg:col-span-2" testid="pending-actions">
          {isLoading ? <Rows /> : !data.pending_actions.length ? <Empty text="No pending actions" hint="New work assigned to you will appear here." /> : (
            <ul className="divide-y">
              {data.pending_actions.map((a, i) => (
                <li key={i}><Link to={a.link} data-testid={`pending-action-${i}`} className="flex items-center gap-3 py-2.5 hover:text-primary">
                  <span className="w-32 shrink-0 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{label(a.kind)}</span>
                  <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{a.title}</span><span className="block truncate text-xs text-muted-foreground">{a.subtitle}</span></span>
                  <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                </Link></li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Upcoming Deadlines" testid="upcoming-deadlines">
          {isLoading ? <Rows /> : !data.upcoming_deadlines.length ? <Empty text="No upcoming deadlines" /> : data.upcoming_deadlines.map((c) => (
            <Link key={c.id} to={`/crs/${c.id}`} className="flex items-center justify-between gap-2 border-b py-2 last:border-0 hover:text-primary">
              <span className="min-w-0"><span className="block font-mono text-xs">{c.number}</span><span className="block truncate text-sm">{c.title}</span></span>
              <span className="shrink-0 text-right text-xs"><span className="block font-medium">{fmtDate(c.approved_deadline || c.requested_deadline)}</span><PrioBadge p={c.priority} /></span>
            </Link>
          ))}
        </Card>
        <Card title="My Assigned CRs" testid="my-crs">
          {isLoading ? <Rows /> : !data.my_crs.length ? <Empty text="No CRs assigned to you" /> : data.my_crs.map((c) => (
            <Link key={c.id} to={`/crs/${c.id}`} className="flex items-center justify-between gap-2 border-b py-2 last:border-0 hover:text-primary">
              <span className="min-w-0 truncate text-sm"><span className="mr-2 font-mono text-xs">{c.number}</span>{c.title}</span><StatusBadge s={c.status} />
            </Link>
          ))}
        </Card>
        <Card title="UAT Deployments" testid="uat-deployments">
          {isLoading ? <Rows /> : !data.deployments.length ? <Empty text="No deployments yet" /> : data.deployments.map((d) => (
            <Link key={d.id} to={`/srns/${d.srn_id}`} className="flex items-center justify-between border-b py-2 last:border-0">
              <span className="text-sm"><span className="font-mono text-xs">{d.srn_number}</span> · {d.version}</span><StatusBadge s={d.status} />
            </Link>
          ))}
        </Card>
        <Card title="Open Bugs" testid="open-bugs">
          {isLoading ? <Rows /> : !data.open_bugs.length ? <Empty text="No open bugs" /> : data.open_bugs.map((b) => (
            <Link key={b.id} to={`/bugs?id=${b.id}`} className="flex items-center justify-between gap-2 border-b py-2 last:border-0">
              <span className="min-w-0 truncate text-sm"><span className="mr-2 font-mono text-xs">{b.number}</span>{b.title}</span><StatusBadge s={b.status} />
            </Link>
          ))}
        </Card>
        <Card title="Recent Activity" className="lg:col-span-2" testid="recent-activity">
          {isLoading ? <Rows /> : !data.recent_activity.length ? <Empty text="No activity yet" /> : (
            <ul className="divide-y">{data.recent_activity.map((a) => (
              <li key={a.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                <span className="min-w-0 truncate"><b className="font-medium">{a.actor_name}</b> <span className="text-muted-foreground">{label(a.action)}</span>{a.after?.status && <> → {label(a.after.status)}</>}</span>
                <span className="shrink-0 text-xs text-muted-foreground">{fmt(a.at)}</span>
              </li>
            ))}</ul>
          )}
        </Card>
        <Card title="Release History" testid="release-history">
          {isLoading ? <Rows /> : !data.release_history.length ? <Empty text="No releases deployed" /> : data.release_history.map((s) => (
            <Link key={s.id} to={`/srns/${s.id}`} className="flex justify-between border-b py-2 text-sm last:border-0"><span className="font-mono text-xs">{s.number} · {s.release_version}</span><span className="text-xs text-muted-foreground">{fmtDate(s.deployed_at)}</span></Link>
          ))}
        </Card>
      </div>
    </div>
  );
}
