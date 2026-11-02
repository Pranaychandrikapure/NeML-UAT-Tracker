import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { get } from "../lib/api";
import { PageHeader, Card, Empty, Rows, StatusBadge } from "../components/common";
import { fmt, fmtDate } from "../lib/status";

export default function Approvals() {
  const q = useQuery({ queryKey: ["approvals"], queryFn: () => get("/approvals/queue") });
  const dl = useQuery({ queryKey: ["deadlines"], queryFn: () => get("/deadline-requests") });
  return (
    <div>
      <PageHeader title="Approvals" subtitle="Release notes awaiting your decision at their current stage, and pending deadline negotiations." />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title={`SRN approvals (${q.data?.length || 0})`} className="lg:col-span-2" testid="srn-approval-queue">
          {q.isLoading ? <Rows /> : !q.data.length ? <Empty text="No SRNs waiting for you" hint="Segregation-of-duties rules hide SRNs you authored or developed." /> : q.data.map((s) => (
            <Link key={s.id} to={`/srns/${s.id}`} data-testid={`approval-item-${s.number}`} className="mb-3 block rounded-lg border p-4 transition-colors hover:border-primary/50">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-medium"><span className="font-mono text-xs">{s.number}</span> · {s.release_version} <span className="text-sm text-muted-foreground">({s.project_name || s.application_name})</span></p>
                <StatusBadge s={s.status} />
              </div>
              <p className="mt-1 text-sm text-muted-foreground">Stage: <b>{s.stage_label}</b> · by {s.author_name} · submitted {fmt(s.submitted_at)} · R{s.revision}</p>
              <p className="mt-1 text-xs">{s.items.length} CR(s): {s.items.map((i) => i.cr_number).join(", ")} {s.bug_items?.length ? `· ${s.bug_items.length} bug fix(es)` : ""}</p>
            </Link>
          ))}
        </Card>
        <Card title={`Deadline requests (${dl.data?.length || 0})`} testid="deadline-queue">
          {dl.isLoading ? <Rows /> : !dl.data.length ? <Empty text="No pending deadline requests" /> : dl.data.map((d) => (
            <Link key={d.id} to={`/crs/${d.cr_id}`} className="mb-2 block rounded-lg border p-3 hover:border-primary/50">
              <p className="font-mono text-xs">{d.cr_number}</p>
              <p className="text-sm">{fmtDate(d.original_deadline)} → <b>{fmtDate(d.proposed_deadline)}</b></p>
              <p className="truncate text-xs text-muted-foreground">{d.requested_by_name}: {d.reason}</p>
            </Link>
          ))}
        </Card>
      </div>
    </div>
  );
}
