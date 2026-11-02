import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { get } from "../lib/api";
import { useApp } from "../context/AppContext";
import { PageHeader, Card, Empty, Rows, StatusBadge, PrioBadge } from "../components/common";
import { fmtDate } from "../lib/status";

const GROUPS = [
  ["To start", ["ASSIGNED", "SIT_FAILED"]], ["In development", ["IN_DEVELOPMENT", "BLOCKED"]], ["SIT pending", ["DEVELOPMENT_COMPLETED", "SIT_IN_PROGRESS"]],
  ["Ready for release", ["SIT_PASSED"]], ["Released to UAT", ["READY_FOR_UAT"]],
];

export default function MyTasks() {
  const { projectId } = useApp();
  const { data, isLoading } = useQuery({ queryKey: ["tasks", projectId], queryFn: () => get("/tasks", { mine: true, project_id: projectId }) });
  const bugs = useQuery({ queryKey: ["mybugs", projectId], queryFn: () => get("/bugs", { mine: true, project_id: projectId }) });
  return (
    <div>
      <PageHeader title="My Tasks" subtitle="Development tasks and bug fixes assigned to you. Open a task's CR to start, complete or record SIT." />
      {isLoading ? <Rows n={6} /> : (
        <div className="grid gap-4 lg:grid-cols-5">
          {GROUPS.map(([g, sts]) => {
            const items = data.filter((t) => sts.includes(t.status));
            return (
              <Card key={g} title={`${g} (${items.length})`} testid={`tasks-col-${g.toLowerCase().replace(/ /g, "-")}`}>
                {!items.length ? <p className="py-4 text-center text-xs text-muted-foreground">None</p> : items.map((t) => (
                  <Link key={t.id} to={`/crs/${t.cr_id}`} data-testid={`my-task-${t.number}`} className="mb-2 block rounded-lg border p-3 transition-colors hover:border-primary/50">
                    <p className="font-mono text-[11px] text-muted-foreground">{t.number} · {t.cr_number}</p>
                    <p className="text-sm font-medium">{t.title}</p>
                    <div className="mt-2 flex items-center justify-between"><StatusBadge s={t.status} /><span className="text-[11px] text-muted-foreground">{fmtDate(t.planned_end)}</span></div>
                  </Link>
                ))}
              </Card>
            );
          })}
        </div>
      )}
      <Card title="My Bugs" className="mt-6" testid="my-bugs">
        {bugs.isLoading ? <Rows /> : !bugs.data.length ? <Empty text="No bugs assigned to you" /> : bugs.data.map((b) => (
          <Link key={b.id} to={`/bugs?id=${b.id}`} className="flex items-center justify-between border-b py-2 last:border-0">
            <span className="text-sm"><span className="font-mono text-xs">{b.number}</span> {b.title}</span><span className="flex gap-2"><PrioBadge p={b.severity} /><StatusBadge s={b.status} /></span>
          </Link>
        ))}
      </Card>
    </div>
  );
}
