import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "../components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "../components/ui/sheet";
import { get, api, act } from "../lib/api";
import { useApp } from "../context/AppContext";
import { usePrompt } from "../components/Prompt";
import { PageHeader, Card, Empty, Rows, StatusBadge, PrioBadge, Sel, Kv } from "../components/common";
import { fmt, fmtDate, label } from "../lib/status";

const STATUSES = ["OPEN", "ASSIGNED", "IN_DEVELOPMENT", "FIXED", "SIT_IN_PROGRESS", "SIT_FAILED", "SIT_PASSED", "FIXED_AWAITING_RELEASE", "UAT_DEPLOYED", "RETEST_IN_PROGRESS", "VERIFIED", "REOPENED", "CLOSED"];
const DEV = { ASSIGNED: ["start", "Start fix"], SIT_FAILED: ["start", "Rework"], FIXED: ["start_sit", "Start SIT"] };

export default function Bugs() {
  const { projectId, user } = useApp();
  const [sp, setSp] = useSearchParams();
  const [f, setF] = useState({ status: "", severity: "" });
  const qc = useQueryClient();
  const [ask, promptEl] = usePrompt();
  const { data, isLoading } = useQuery({ queryKey: ["bugs", projectId, f], queryFn: () => get("/bugs", { project_id: projectId, ...f }) });
  const sel = data?.find((b) => b.id === sp.get("id"));
  const proj = useQuery({ queryKey: ["project", sel?.project_id], queryFn: () => get(`/projects/${sel.project_id}`), enabled: !!sel });
  const myRole = proj.data?.my_project_role;
  const refresh = () => qc.invalidateQueries();
  const run = (b, a, body = {}, msg) => act(() => api.post(`/bugs/${b.id}/action/${a}`, body), msg || label(a)).then(refresh);
  const devs = (proj.data?.members || []).filter((m) => ["developer", "team_lead", "pm"].includes(m.project_role)).map((m) => ({ value: m.user_id, label: `${m.name} · ${label(m.project_role)}` }));
  return (
    <div>
      <PageHeader title="Bug Tracker" subtitle="UAT bugs traced to their CR and release. Fixes must pass SIT and ship in a new approved SRN before UAT verifies them.">
        <Sel data-testid="bug-filter-status" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })} options={STATUSES.map((s) => ({ value: s, label: label(s) }))} placeholder="All statuses" className="w-48" />
        <Sel data-testid="bug-filter-severity" value={f.severity} onChange={(e) => setF({ ...f, severity: e.target.value })} options={["Critical", "High", "Medium", "Low"]} placeholder="All severities" className="w-36" />
      </PageHeader>
      <Card>
        {isLoading ? <Rows n={6} /> : !data.length ? <Empty text="No bugs" hint="UAT reports bugs from the UAT Management screen." /> : (
          <div className="overflow-x-auto"><table className="tbl w-full" data-testid="bug-table"><thead><tr><th>Bug</th><th>Title</th><th>CR</th><th>Found in</th><th>Severity</th><th>Developer</th><th>Due</th><th>Status</th></tr></thead>
            <tbody>{data.map((b) => (
              <tr key={b.id} className="cursor-pointer" onClick={() => setSp({ id: b.id })} data-testid={`bug-row-${b.number}`}>
                <td className="font-mono text-xs font-medium text-primary">{b.number}</td><td>{b.title}{b.reopen_count ? <span className="ml-1 text-[11px] text-rose-600">reopened ×{b.reopen_count}</span> : null}</td>
                <td className="font-mono text-xs">{b.cr_number}</td><td className="font-mono text-xs">{b.found_in_srn_number || "—"}</td><td><PrioBadge p={b.severity} /></td><td>{b.developer_name || "—"}</td><td className="text-xs">{fmtDate(b.due_date)}</td><td><StatusBadge s={b.status} /></td>
              </tr>
            ))}</tbody></table></div>
        )}
      </Card>
      <Sheet open={!!sel} onOpenChange={(o) => !o && setSp({})}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-xl" data-testid="bug-drawer">
          {sel && <>
            <SheetHeader><SheetTitle>{sel.number} · {sel.title}</SheetTitle></SheetHeader>
            <div className="mt-3 flex flex-wrap gap-2"><StatusBadge s={sel.status} testid="bug-status" /><PrioBadge p={sel.severity} />{sel.blocking && <span className="rounded-md border border-rose-200 px-2 py-0.5 text-xs text-rose-700">Blocking</span>}</div>
            <div className="mt-4 flex flex-wrap gap-2">
              {["pm", "team_lead", "senior_pm", "project_lead", "system_admin"].includes(myRole) && ["OPEN", "REOPENED", "ASSIGNED"].includes(sel.status) && <Button size="sm" data-testid="bug-assign" onClick={() => ask({ title: "Assign developer", fields: [{ key: "developer_id", label: "Developer", type: "select", required: true, options: devs }, { key: "due_date", label: "Due date", type: "date" }], onSubmit: (v) => run(sel, "assign", { ...v, due_date: v.due_date || null }, "Bug assigned") })}>Assign developer</Button>}
              {sel.developer_id === user.id && DEV[sel.status] && <Button size="sm" data-testid="bug-dev-next" onClick={() => run(sel, DEV[sel.status][0])}>{DEV[sel.status][1]}</Button>}
              {sel.developer_id === user.id && sel.status === "IN_DEVELOPMENT" && <Button size="sm" data-testid="bug-fixed" onClick={() => ask({ title: "Mark fixed", fields: [{ key: "fix_notes", label: "Fix notes", type: "textarea", required: true }], onSubmit: (v) => run(sel, "fixed", v, "Marked fixed") })}>Mark fixed</Button>}
              {sel.developer_id === user.id && sel.status === "SIT_IN_PROGRESS" && <>
                <Button size="sm" data-testid="bug-sit-pass" onClick={() => ask({ title: "SIT passed", fields: [{ key: "evidence", label: "SIT evidence", type: "textarea", required: true }], onSubmit: (v) => run(sel, "sit_pass", v, "SIT passed — eligible for next SRN") })}>SIT pass</Button>
                <Button size="sm" variant="outline" onClick={() => ask({ title: "SIT failed", fields: [{ key: "evidence", label: "SIT evidence", type: "textarea", required: true }], onSubmit: (v) => run(sel, "sit_fail", v, "SIT failed") })}>SIT fail</Button></>}
              {sel.status === "SIT_PASSED" && sel.developer_id === user.id && <Link to="/srns/new"><Button size="sm" variant="outline">Include in new SRN</Button></Link>}
              {["uat_lead", "ba", "ba_lead"].includes(myRole) && sel.status === "VERIFIED" && <Button size="sm" variant="outline" data-testid="bug-close" onClick={() => run(sel, "close", {}, "Bug closed")}>Close bug</Button>}
            </div>
            <dl className="mt-5 grid grid-cols-2 gap-4">
              <Kv k="CR" v={<Link className="text-primary" to={`/crs/${sel.cr_id}`}>{sel.cr_number}</Link>} /><Kv k="Found in SRN" v={sel.found_in_srn_number} /><Kv k="Reported by" v={sel.reported_by_name} /><Kv k="Developer" v={sel.developer_name} />
              <Kv k="Priority" v={sel.priority} /><Kv k="Due" v={fmtDate(sel.due_date)} /><Kv k="SIT result" v={sel.sit_result ? `${sel.sit_result.result}: ${sel.sit_result.evidence}` : null} /><Kv k="UAT verification" v={sel.uat_verification ? `${label(sel.uat_verification.result)} by ${sel.uat_verification.by}` : null} />
            </dl>
            {[["Steps to reproduce", sel.steps], ["Expected", sel.expected], ["Actual", sel.actual], ["Fix notes", sel.fix_notes]].map(([k, v]) => <div key={k} className="mt-4 text-sm"><p className="text-xs font-semibold text-muted-foreground">{k}</p><p className="whitespace-pre-wrap">{v || "—"}</p></div>)}
            <p className="mt-6 text-xs font-semibold text-muted-foreground">History</p>
            <ol className="mt-2 space-y-1.5 border-l pl-4">{sel.history?.map((h, i) => <li key={i} className="text-xs"><b>{label(h.to)}</b> · {h.by} · {fmt(h.at)}{h.comment ? ` — ${h.comment}` : ""}</li>)}</ol>
          </>}
        </SheetContent>
      </Sheet>
      {promptEl}
    </div>
  );
}
