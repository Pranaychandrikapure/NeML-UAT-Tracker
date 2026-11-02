import { useParams, Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, AlertTriangle, ExternalLink } from "lucide-react";
import { Button } from "../components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { get, api, act } from "../lib/api";
import { useApp } from "../context/AppContext";
import { usePrompt } from "../components/Prompt";
import { Card, Empty, Rows, StatusBadge, PrioBadge, Kv, Timeline } from "../components/common";
import { CR_STAGES, fmt, fmtDate, label, PRIORITIES } from "../lib/status";

const MGR = ["project_lead", "senior_pm", "pm", "team_lead", "system_admin"];
const BA = ["ba", "ba_lead", "system_admin"];

function Stepper({ status }) {
  const idx = CR_STAGES.findIndex((s) => s.s.includes(status));
  return (
    <ol className="flex w-full overflow-x-auto rounded-xl border bg-card p-3" data-testid="cr-stepper">
      {CR_STAGES.map((s, i) => {
        const done = idx > i || status === "CLOSED", cur = idx === i && status !== "CLOSED";
        return (
          <li key={s.label} className="flex min-w-[110px] flex-1 items-center gap-2">
            <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${done ? "bg-emerald-600 text-white" : cur ? "bg-primary text-white ring-4 ring-primary/20" : "bg-muted text-muted-foreground"}`}>{done ? <Check className="h-3.5 w-3.5" /> : i + 1}</span>
            <span className={`text-xs font-medium ${cur ? "text-primary" : done ? "" : "text-muted-foreground"}`}>{s.label}</span>
            {i < CR_STAGES.length - 1 && <span className={`mx-1 h-px flex-1 ${done ? "bg-emerald-500" : "bg-border"}`} />}
          </li>
        );
      })}
    </ol>
  );
}

const TASK_NEXT = { ASSIGNED: ["start", "Start development"], SIT_FAILED: ["start", "Rework"], IN_DEVELOPMENT: ["complete_dev", "Complete development"], DEVELOPMENT_COMPLETED: ["start_sit", "Start SIT"] };

export default function CRDetail() {
  const { id } = useParams();
  const { user } = useApp();
  const qc = useQueryClient();
  const [ask, promptEl] = usePrompt();
  const { data: cr, isLoading } = useQuery({ queryKey: ["cr", id], queryFn: () => get(`/crs/${id}`) });
  const proj = useQuery({ queryKey: ["project", cr?.project_id], queryFn: () => get(`/projects/${cr.project_id}`), enabled: !!cr });
  if (isLoading || !cr) return <Rows n={10} />;
  const pr = cr.my_project_role, st = cr.status;
  const isBA = BA.includes(pr), isMgr = MGR.includes(pr);
  const members = proj.data?.members || [];
  const opt = (roles) => members.filter((m) => roles.includes(m.project_role)).map((m) => ({ value: m.user_id, label: `${m.name} · ${label(m.project_role)}` }));
  const modules = proj.data?.modules || [];
  const refresh = () => qc.invalidateQueries();
  const doAction = (a, body = {}, msg = "Done") => act(() => api.post(`/crs/${id}/actions/${a}`, body), msg).then(refresh);
  const taskAct = (t, a, body = {}, msg = "Task updated") => act(() => api.post(`/tasks/${t.id}/actions/${a}`, body), msg).then(refresh);
  const pendingDl = cr.deadline_requests.find((d) => d.status === "PENDING");
  const mine = (t) => t.developer_id === user.id || t.collaborator_ids?.includes(user.id);

  const addTask = () => ask({
    title: "Add development task", submitLabel: "Assign task",
    fields: [
      { key: "title", label: "Task title", required: true },
      { key: "developer_id", label: "Owner (PM / TL can self-assign)", type: "select", required: true, options: opt(["pm", "team_lead", "developer", "senior_pm"]), default: "" },
      { key: "module_id", label: "Module", type: "select", options: modules.map((m) => ({ value: m.id, label: m.name })) },
      { key: "description", label: "Description", type: "textarea" },
      { key: "planned_end", label: "Planned completion", type: "date" },
      { key: "estimated_hours", label: "Estimated hours", type: "number" },
      { key: "priority", label: "Priority", type: "select", options: PRIORITIES, default: cr.priority },
    ],
    onSubmit: (v) => act(() => api.post(`/crs/${id}/tasks`, { ...v, module_id: v.module_id || null, planned_end: v.planned_end || null, estimated_hours: Number(v.estimated_hours || 0) }), "Task assigned").then(refresh),
  });

  const actions = [];
  if (st === "DRAFT" && isBA) actions.push(["Submit CR", () => doAction("submit", {}, "Submitted"), "default"]);
  if (st === "NEW" && isBA) actions.push(["Start BA review", () => doAction("start_review", {}, "Review started"), "outline"]);
  if (["NEW", "BA_REVIEW"].includes(st) && isBA) {
    actions.push(["Approve & assign", () => ask({
      title: "Approve for impact analysis", description: "Assign the Senior PM / PM who will analyse impact and plan development.", submitLabel: "Approve",
      fields: [{ key: "manager_id", label: "Development manager", type: "select", required: true, options: opt(["senior_pm", "pm", "team_lead", "project_lead"]) },
        { key: "priority", label: "Priority", type: "select", options: PRIORITIES, default: cr.priority },
        { key: "requested_deadline", label: "Requested deadline", type: "date", required: true, default: cr.requested_deadline || "" },
        { key: "comment", label: "Comment", type: "textarea" }],
      onSubmit: (v) => doAction("ba_approve", v, "CR approved and assigned"),
    }), "default"]);
    actions.push(["Request clarification", () => ask({ title: "Request clarification", fields: [{ key: "comment", label: "What needs clarification?", type: "textarea", required: true }], onSubmit: (v) => doAction("request_clarification", v, "Clarification requested") }), "outline"]);
    actions.push(["Reject", () => ask({ title: "Reject CR", fields: [{ key: "comment", label: "Reason", type: "textarea", required: true }], submitLabel: "Reject", onSubmit: (v) => doAction("reject", v, "CR rejected") }), "destructive"]);
  }
  const devPhase = ["IMPACT_ANALYSIS", "ASSIGNED", "IN_DEVELOPMENT", "SIT_IN_PROGRESS", "READY_FOR_UAT", "UAT_FAILED"].includes(st);
  if (devPhase && isMgr) actions.push(["Add task", addTask, st === "IMPACT_ANALYSIS" ? "outline" : "default"]);
  if (st === "IMPACT_ANALYSIS" && isMgr) actions.push(["Confirm assignments", () => doAction("confirm_assignment", {}, "Assignments confirmed"), "default"]);
  if (["IMPACT_ANALYSIS", "ASSIGNED", "IN_DEVELOPMENT", "SIT_IN_PROGRESS"].includes(st) && isMgr && !pendingDl) actions.push(["Request deadline revision", () => ask({
    title: "Deadline revision request", description: `BA requested ${fmtDate(cr.requested_deadline)}. The original deadline is never overwritten.`, submitLabel: "Send to BA",
    fields: [{ key: "proposed_deadline", label: "Proposed deadline", type: "date", required: true }, { key: "reason", label: "Reason for extension", type: "textarea", required: true },
      { key: "dev_hours", label: "Estimated development hours", type: "number" }, { key: "sit_hours", label: "Estimated SIT hours", type: "number" },
      { key: "dependencies", label: "Technical dependencies", type: "textarea" }, { key: "comments", label: "Supporting comments", type: "textarea" }],
    onSubmit: (v) => act(() => api.post(`/crs/${id}/deadline-requests`, { ...v, dev_hours: Number(v.dev_hours || 0), sit_hours: Number(v.sit_hours || 0) }), "Deadline request sent").then(refresh),
  }), "outline"]);
  if (isMgr && devPhase) actions.push(["Reassign manager", () => ask({ title: "Reassign CR", fields: [{ key: "manager_id", label: "New manager", type: "select", required: true, options: opt(["senior_pm", "pm", "team_lead", "project_lead"]) }, { key: "comment", label: "Comment", type: "textarea" }], onSubmit: (v) => doAction("reassign", v, "Reassigned") }), "ghost"]);
  if (isBA && devPhase) actions.push(["Notify UAT early", () => ask({ title: "Give UAT a heads-up", description: "Notifies UAT Lead/Manager. Does not mark anything deployed.", fields: [{ key: "comment", label: "Message", type: "textarea" }], onSubmit: (v) => doAction("notify_uat", v, "UAT notified") }), "ghost"]);
  if (st === "UAT_PASSED" && isBA) actions.push(["Close CR (business acceptance)", () => doAction("close", {}, "CR closed"), "default"]);

  const imp = cr.impact || {};
  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between fade-up">
        <div>
          <p className="font-mono text-xs text-muted-foreground"><Link to="/crs" className="hover:underline">Change Requests</Link> / {cr.number}</p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight" data-testid="cr-title">{cr.title}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2"><StatusBadge s={st} testid="cr-status" /><PrioBadge p={cr.priority} /><span className="rounded-md border px-2 py-0.5 text-xs">{cr.source}</span><span className="text-xs text-muted-foreground">{cr.project_name} · Rev {cr.revision}</span></div>
        </div>
        <div className="flex flex-wrap gap-2">{actions.map(([l, fn, v]) => <Button key={l} variant={v} size="sm" onClick={fn} data-testid={`cr-action-${l.toLowerCase().replace(/[^a-z]+/g, "-")}`}>{l}</Button>)}</div>
      </div>
      <Stepper status={st} />
      {cr.needs_impact_review && <div className="flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-200"><AlertTriangle className="h-4 w-4" />Requirements changed after approval (rev {cr.revision}). Development manager must re-save impact analysis.</div>}
      {cr.clarification_requested && <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">Clarification requested by BA — see activity history.</div>}
      {pendingDl && (
        <Card title="Pending deadline decision" testid="pending-deadline-card">
          <div className="grid gap-3 sm:grid-cols-4"><Kv k="Original BA deadline" v={fmtDate(pendingDl.original_deadline)} /><Kv k="Proposed by PM" v={fmtDate(pendingDl.proposed_deadline)} /><Kv k="Dev / SIT hours" v={`${pendingDl.dev_hours} / ${pendingDl.sit_hours}`} /><Kv k="Requested by" v={pendingDl.requested_by_name} /></div>
          <p className="mt-3 text-sm"><b>Reason:</b> {pendingDl.reason}</p>
          {isBA && <div className="mt-3 flex gap-2">
            <Button size="sm" data-testid="deadline-approve" onClick={() => act(() => api.post(`/deadline-requests/${pendingDl.id}/decide`, { decision: "APPROVE" }), "Deadline approved").then(refresh)}>Approve</Button>
            <Button size="sm" variant="outline" data-testid="deadline-revise" onClick={() => ask({ title: "Request further revision", fields: [{ key: "comment", label: "Comment", type: "textarea", required: true }], onSubmit: (v) => act(() => api.post(`/deadline-requests/${pendingDl.id}/decide`, { decision: "REVISE", ...v })).then(refresh) })}>Request revision</Button>
            <Button size="sm" variant="destructive" data-testid="deadline-reject" onClick={() => ask({ title: "Reject deadline request", fields: [{ key: "comment", label: "Comment", type: "textarea", required: true }], onSubmit: (v) => act(() => api.post(`/deadline-requests/${pendingDl.id}/decide`, { decision: "REJECT", ...v })).then(refresh) })}>Reject</Button>
          </div>}
        </Card>
      )}
      <Tabs defaultValue="overview">
        <TabsList className="flex h-auto flex-wrap justify-start">
          {[["overview", "Overview"], ["impact", "Impact Analysis"], ["tasks", `Tasks (${cr.tasks.length})`], ["bugs", `Bugs (${cr.bugs.length})`], ["srns", `SRNs (${cr.srns.length})`], ["approvals", "Approvals"], ["activity", "Activity History"], ["attachments", "Attachments"]].map(([v, l]) => <TabsTrigger key={v} value={v} data-testid={`cr-tab-${v}`}>{l}</TabsTrigger>)}
        </TabsList>
        <TabsContent value="overview" className="mt-4 grid gap-5 lg:grid-cols-3">
          <Card title="Requirement" className="lg:col-span-2">
            <div className="space-y-4 text-sm">{[["Description", cr.description], ["Business requirements", cr.business_requirements], ["Expected result", cr.expected_result], ["Business justification", cr.justification], ["Acceptance criteria", cr.acceptance_criteria]].map(([k, v]) => <div key={k}><p className="text-xs font-semibold text-muted-foreground">{k}</p><p className="mt-1 whitespace-pre-wrap">{v || "—"}</p></div>)}</div>
          </Card>
          <Card title="Details"><dl className="grid grid-cols-2 gap-4">
            <Kv k="BA" v={cr.ba_name} /><Kv k="Manager" v={cr.manager_name} /><Kv k="Requested deadline" v={fmtDate(cr.requested_deadline)} /><Kv k="Approved deadline" v={fmtDate(cr.approved_deadline)} />
            <Kv k="Business owner" v={cr.business_owner} /><Kv k="Dev progress" v={`${cr.task_done}/${cr.task_total} tasks SIT passed`} /><Kv k="Modules" v={cr.impacted_modules.map((m) => m.name).join(", ")} /><Kv k="UAT status" v={label(cr.uat_status)} />
            <Kv k="Created" v={`${fmt(cr.created_at)} by ${cr.created_by_name}`} /><Kv k="External ID" v={cr.external_id} />
          </dl></Card>
          <Card title="Deadline revision history" className="lg:col-span-3">{!cr.deadline_requests.length ? <Empty text="No deadline revisions" /> : (
            <table className="tbl w-full"><thead><tr><th>Requested</th><th>Original</th><th>Proposed</th><th>Reason</th><th>Status</th><th>Decision</th></tr></thead>
              <tbody>{cr.deadline_requests.map((d) => <tr key={d.id}><td>{d.requested_by_name}<br /><span className="text-xs text-muted-foreground">{fmt(d.created_at)}</span></td><td>{fmtDate(d.original_deadline)}</td><td>{fmtDate(d.proposed_deadline)}</td><td>{d.reason}</td><td><StatusBadge s={d.status} /></td><td className="text-xs">{d.decided_by_name ? `${d.decided_by_name}: ${d.decision_comment || ""}` : "—"}</td></tr>)}</tbody></table>
          )}</Card>
        </TabsContent>
        <TabsContent value="impact" className="mt-4">
          <Card title="Technical impact analysis" action={isMgr && devPhase && <Button size="sm" data-testid="impact-edit" onClick={() => ask({
            title: "Impact analysis", submitLabel: "Save analysis",
            fields: [["complexity", "Complexity (Low/Medium/High)"], ["business_impact", "Business impact", "textarea"], ["technical_impact", "Technical impact", "textarea"], ["dependencies", "System dependencies", "textarea"], ["dev_hours", "Estimated development hours", "number"], ["sit_hours", "Estimated SIT hours", "number"], ["required_developers", "Required developers", "number"], ["proposed_deadline", "Proposed completion", "date"], ["risks", "Technical risks", "textarea"]].map(([key, l, type]) => ({ key, label: l, type, default: imp[key] ?? "" })),
            onSubmit: (v) => doAction("save_impact", { impact: v }, "Impact analysis saved"),
          })}>Edit analysis</Button>}>
            {!imp.by ? <Empty text="Impact analysis not recorded yet" /> : <dl className="grid gap-4 sm:grid-cols-3">{[["Complexity", imp.complexity], ["Dev hours", imp.dev_hours], ["SIT hours", imp.sit_hours], ["Required developers", imp.required_developers], ["Proposed completion", fmtDate(imp.proposed_deadline)], ["Business impact", imp.business_impact], ["Technical impact", imp.technical_impact], ["Dependencies", imp.dependencies], ["Risks", imp.risks]].map(([k, v]) => <Kv key={k} k={k} v={v} />)}</dl>}
          </Card>
        </TabsContent>
        <TabsContent value="tasks" className="mt-4">
          <Card title="Development tasks">{!cr.tasks.length ? <Empty text="No tasks yet" hint={isMgr ? "Use “Add task” to split work by module/screen." : ""} /> : (
            <div className="overflow-x-auto"><table className="tbl w-full" data-testid="cr-tasks-table"><thead><tr><th>Task</th><th>Owner</th><th>Module</th><th>Due</th><th>Status</th><th>SIT evidence</th><th></th></tr></thead>
              <tbody>{cr.tasks.map((t) => (
                <tr key={t.id} data-testid={`task-row-${t.number}`}>
                  <td><span className="font-mono text-xs">{t.number}</span><br />{t.title}{t.git_ref && <p className="font-mono text-[11px] text-muted-foreground">{t.git_ref}</p>}</td>
                  <td>{t.developer_name}{t.self_assigned && <span className="ml-1 text-[10px] text-muted-foreground">(self)</span>}</td>
                  <td className="text-xs">{modules.find((m) => m.id === t.module_id)?.name || "—"}</td><td className="text-xs">{fmtDate(t.planned_end)}</td>
                  <td><StatusBadge s={t.status} />{t.block_reason && t.status === "BLOCKED" && <p className="text-[11px] text-rose-600">{t.block_reason}</p>}</td>
                  <td className="max-w-[220px] text-xs">{t.sit_results[0] ? `${t.sit_results[0].result}: ${t.sit_results[0].evidence}` : "—"}</td>
                  <td><div className="flex flex-wrap justify-end gap-1">
                    {mine(t) && TASK_NEXT[t.status] && <Button size="sm" data-testid={`task-${t.number}-next`} onClick={() => taskAct(t, TASK_NEXT[t.status][0])}>{TASK_NEXT[t.status][1]}</Button>}
                    {mine(t) && t.status === "SIT_IN_PROGRESS" && <Button size="sm" data-testid={`task-${t.number}-sit`} onClick={() => ask({ title: `Record SIT result · ${t.number}`, fields: [{ key: "result", label: "Result", type: "select", required: true, options: ["PASS", "FAIL"] }, { key: "evidence", label: "Evidence (test cases, screenshots link)", type: "textarea", required: true }, { key: "git_ref", label: "Git branch / commit", default: t.git_ref }, { key: "actual_hours", label: "Actual effort (hours)", type: "number" }], onSubmit: (v) => taskAct(t, "sit_result", { ...v, actual_hours: v.actual_hours ? Number(v.actual_hours) : null }, "SIT recorded") })}>Record SIT</Button>}
                    {(mine(t) || isMgr) && !["BLOCKED", "CANCELLED", "SIT_PASSED", "READY_FOR_UAT"].includes(t.status) && <Button size="sm" variant="ghost" onClick={() => ask({ title: "Mark blocked", fields: [{ key: "reason", label: "Reason", type: "textarea", required: true }], onSubmit: (v) => taskAct(t, "block", v) })}>Block</Button>}
                    {t.status === "BLOCKED" && (mine(t) || isMgr) && <Button size="sm" variant="outline" onClick={() => taskAct(t, "unblock")}>Unblock</Button>}
                  </div></td>
                </tr>
              ))}</tbody></table></div>
          )}</Card>
        </TabsContent>
        <TabsContent value="bugs" className="mt-4"><Card title="Bugs">{!cr.bugs.length ? <Empty text="No bugs reported" /> : cr.bugs.map((b) => (
          <Link key={b.id} to={`/bugs?id=${b.id}`} className="flex items-center justify-between border-b py-2 last:border-0"><span className="text-sm"><span className="font-mono text-xs">{b.number}</span> {b.title} <span className="text-xs text-muted-foreground">· {b.severity}</span></span><StatusBadge s={b.status} /></Link>
        ))}</Card></TabsContent>
        <TabsContent value="srns" className="mt-4"><Card title="Release notes including this CR">{!cr.srns.length ? <Empty text="Not part of any SRN yet" /> : cr.srns.map((s) => (
          <Link key={s.id} to={`/srns/${s.id}`} className="flex items-center justify-between border-b py-2 last:border-0"><span className="text-sm"><span className="font-mono text-xs">{s.number}</span> · {s.release_version}</span><StatusBadge s={s.status} /></Link>
        ))}
          {cr.uat.length > 0 && <div className="mt-4"><p className="mb-2 text-xs font-semibold text-muted-foreground">UAT results per release</p>{cr.uat.map((a) => <div key={a.id} className="flex justify-between border-b py-1.5 text-sm"><span>{a.srn_number} · {a.scope}</span><StatusBadge s={a.status} /></div>)}</div>}
        </Card></TabsContent>
        <TabsContent value="approvals" className="mt-4"><Card title="SRN approval decisions">{!cr.approvals.length ? <Empty text="No approval decisions yet" /> : (
          <table className="tbl w-full"><thead><tr><th>When</th><th>Approver</th><th>Stage</th><th>Decision</th><th>Comment</th><th>Valid</th></tr></thead>
            <tbody>{cr.approvals.map((a) => <tr key={a.id}><td className="text-xs">{fmt(a.at)}</td><td>{a.approver_name}<br /><span className="text-xs text-muted-foreground">{a.role_label}</span></td><td>{a.stage} · R{a.revision}</td><td><StatusBadge s={a.decision} /></td><td className="text-xs">{a.comment}</td><td className="text-xs">{a.valid ? "Yes" : "No"}</td></tr>)}</tbody></table>
        )}</Card></TabsContent>
        <TabsContent value="activity" className="mt-4 grid gap-5 lg:grid-cols-2">
          <Card title="Activity history"><Timeline items={cr.activity} /></Card>
          <Card title="Comments & revisions">
            <Button size="sm" variant="outline" className="mb-3" data-testid="cr-add-comment" onClick={() => ask({ title: "Add comment", fields: [{ key: "text", label: "Comment", type: "textarea", required: true }], onSubmit: (v) => act(() => api.post(`/crs/${id}/comments`, v), "Comment added").then(refresh) })}>Add comment</Button>
            {cr.comments?.map((c) => <div key={c.id} className="mb-2 rounded-md bg-muted/50 p-2 text-sm"><b>{c.by_name}</b> <span className="text-xs text-muted-foreground">{fmt(c.at)}</span><p>{c.text}</p></div>)}
            <p className="mt-4 text-xs font-semibold text-muted-foreground">Requirement revisions</p>
            {cr.revisions.map((r) => <p key={r.id} className="text-xs">Rev {r.revision} · {fmt(r.at)} {r.changed ? `· changed ${r.changed.join(", ")}` : ""}</p>)}
          </Card>
        </TabsContent>
        <TabsContent value="attachments" className="mt-4"><Card title="Attachments">{!cr.attachments?.length ? <Empty text="No attachments" hint="Attachments are stored as links." /> : cr.attachments.map((a, i) => (
          <a key={i} href={a.url} target="_blank" rel="noreferrer" className="flex items-center gap-2 py-1.5 text-sm text-primary hover:underline"><ExternalLink className="h-3.5 w-3.5" />{a.name}</a>
        ))}</Card></TabsContent>
      </Tabs>
      {promptEl}
    </div>
  );
}
