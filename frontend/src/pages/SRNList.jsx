import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { Button } from "../components/ui/button";
import { get } from "../lib/api";
import { useApp } from "../context/AppContext";
import { PageHeader, Card, Empty, Rows, StatusBadge } from "../components/common";
import { fmt, fmtDate } from "../lib/status";

export default function SRNList() {
  const { projectId, has } = useApp();
  const [sp] = useSearchParams();
  const { data, isLoading } = useQuery({ queryKey: ["srns", projectId, sp.get("status")], queryFn: () => get("/srns", { project_id: projectId, status: sp.get("status") || "" }) });
  return (
    <div>
      <PageHeader title="SRN / Releases" subtitle="Software Release Notes, their approval progress and UAT deployments.">
        {has("developer", "team_lead", "pm", "senior_pm", "system_admin") && <Link to="/srns/new"><Button data-testid="new-srn-button"><Plus className="mr-2 h-4 w-4" />New SRN</Button></Link>}
      </PageHeader>
      <Card>
        {isLoading ? <Rows n={6} /> : !data.length ? <Empty text="No release notes yet" hint="Create an SRN once CR tasks or bug fixes pass SIT." /> : (
          <div className="overflow-x-auto"><table className="tbl w-full" data-testid="srn-table">
            <thead><tr><th>SRN</th><th>Project</th><th>Version</th><th>Type</th><th>Contents</th><th>Author</th><th>Release date</th><th>Status</th><th>Updated</th></tr></thead>
            <tbody>{data.map((s) => (
              <tr key={s.id} data-testid={`srn-row-${s.number}`}>
                <td><Link className="font-mono text-xs font-medium text-primary hover:underline" to={`/srns/${s.id}`}>{s.number}</Link></td>
                <td>{s.project_name}</td><td className="font-mono text-xs">{s.release_version}</td><td>{s.release_type}</td>
                <td className="text-xs">{s.items.length} CR · {s.bug_items?.length || 0} bug</td><td>{s.author_name}</td><td>{fmtDate(s.release_date)}</td>
                <td><StatusBadge s={s.status} /></td><td className="text-xs">{fmt(s.updated_at)}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </Card>
    </div>
  );
}
