import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, PieChart, Pie, Cell } from "recharts";
import { Button } from "../components/ui/button";
import { get } from "../lib/api";
import { useApp } from "../context/AppContext";
import { PageHeader, Card, Empty, Rows } from "../components/common";

const COLORS = ["#2563EB", "#0EA5E9", "#16A34A", "#D97706", "#DC2626", "#7C3AED"];

const BarC = ({ data }) => !data?.length ? <Empty text="No data" /> : (
  <ResponsiveContainer width="100%" height={220}><BarChart data={data}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="name" fontSize={11} /><YAxis allowDecimals={false} fontSize={11} /><Tooltip /><Bar dataKey="value" fill="#2563EB" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer>
);
const PieC = ({ data }) => !data?.length ? <Empty text="No data" /> : (
  <ResponsiveContainer width="100%" height={220}><PieChart><Pie data={data} dataKey="value" nameKey="name" innerRadius={50} outerRadius={80} label>{data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}</Pie><Tooltip /></PieChart></ResponsiveContainer>
);

export default function Reports() {
  const { projectId } = useApp();
  const { data: r, isLoading } = useQuery({ queryKey: ["reports", projectId], queryFn: () => get("/reports", { project_id: projectId }) });
  const exportJson = () => {
    const rows = Object.entries(r).filter(([, v]) => Array.isArray(v)).flatMap(([k, v]) => v.map((x) => [k, ...Object.values(x)]));
    const blob = new Blob([rows.map((x) => x.map((c) => `"${String(c ?? "").replace(/"/g, '""')}"`).join(",")).join("\n")], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "crems_report.csv"; a.click();
  };
  if (isLoading) return <Rows n={8} />;
  const stat = (t, v, unit, basis) => <div className="rounded-xl border bg-card p-4"><p className="text-xs text-muted-foreground">{t}</p><p className="mt-1 font-heading text-2xl font-bold">{v ?? "—"}{v != null && unit}</p><p className="text-[10px] uppercase tracking-wide text-muted-foreground">{basis}</p></div>;
  return (
    <div>
      <PageHeader title="Reports & Analytics" subtitle="Each metric is labelled as current state or historical (from audit/status history). Filtered by the selected project.">
        <Button variant="outline" onClick={exportJson} data-testid="reports-export"><Download className="mr-2 h-4 w-4" />Export CSV</Button>
      </PageHeader>
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7" data-testid="report-stats">
        {stat("Development pending", r.development_pending, "", "current")}
        {stat("SRN approvals pending", r.srn_approvals_pending, "", "current")}
        {stat("Avg development duration", r.avg_dev_hours, " h", "historical")}
        {stat("SIT failure rate", r.sit_failure_rate, "%", "historical")}
        {stat("UAT rejection rate", r.uat_rejection_rate, "%", "historical")}
        {stat("Avg bug resolution", r.avg_bug_resolution_hours, " h", "historical")}
        {stat("Approval turnaround", r.approval_turnaround_hours, " h", "historical")}
      </div>
      <div className="grid gap-5 lg:grid-cols-3">
        <Card title="CRs created by month · historical"><BarC data={r.crs_by_month} /></Card>
        <Card title="CRs by project · all"><BarC data={r.crs_by_project} /></Card>
        <Card title="CRs by priority · all"><PieC data={r.crs_by_priority} /></Card>
        <Card title="Open bugs by severity · current"><PieC data={r.open_bugs_by_severity} /></Card>
        <Card title="Developer workload (open tasks) · current"><BarC data={r.developer_workload} /></Card>
        <Card title="Project workload (open CRs) · current"><BarC data={r.project_workload} /></Card>
        <Card title="Release frequency (UAT deployments) · historical"><BarC data={r.release_frequency} /></Card>
        <Card title="Deadline slippages · historical">{!r.deadline_slippages.length ? <Empty text="No slippages" /> : r.deadline_slippages.map((s) => <p key={s.cr} className="border-b py-1.5 text-sm last:border-0"><span className="font-mono text-xs">{s.cr}</span> {s.requested} → <b>{s.approved}</b></p>)}</Card>
        <Card title="UAT holds & reasons · historical">{!r.uat_holds.length ? <Empty text="No holds" /> : r.uat_holds.map((h, i) => <p key={i} className="border-b py-1.5 text-sm last:border-0">{h.reason} <span className="text-xs text-muted-foreground">· {h.status}</span></p>)}</Card>
      </div>
    </div>
  );
}
