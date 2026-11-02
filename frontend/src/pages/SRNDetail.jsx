import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileDown, FileText, Check, Clock, Pencil } from "lucide-react";
import { Button } from "../components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { get, api, act, download } from "../lib/api";
import { usePrompt } from "../components/Prompt";
import { useApp } from "../context/AppContext";
import { Card, Empty, Rows, StatusBadge, Kv, Timeline } from "../components/common";
import { fmt, fmtDate, label } from "../lib/status";

export default function SRNDetail() {
  const { id } = useParams();
  const { user } = useApp();
  const qc = useQueryClient();
  const [ask, promptEl] = usePrompt();
  const { data: s, isLoading } = useQuery({ queryKey: ["srn", id], queryFn: () => get(`/srns/${id}`), refetchInterval: 15000 });
  const proj = useQuery({ queryKey: ["project", s?.project_id], queryFn: () => get(`/projects/${s.project_id}`), enabled: !!s });
  if (isLoading || !s) return <Rows n={10} />;
  const refresh = () => qc.invalidateQueries();
  const decide = (decision, body = {}) => act(() => api.post(`/srns/${id}/decision`, { decision, ...body }), `${label(decision)} recorded`).then(refresh);
  const withComment = (decision, title) => ask({ title, fields: [{ key: "comment", label: "Comments", type: "textarea", required: decision !== "APPROVE" }], onSubmit: (v) => decide(decision, v) });
  const members = (proj.data?.members || []).map((m) => ({ value: m.user_id, label: `${m.name} · ${label(m.project_role)}` }));
  const isAuthor = s.author_id === user.id;
  const canDeploy = ["pm", "team_lead", "senior_pm", "project_lead", "system_admin"].includes(s.my_project_role);
  const dep = s.deployments[0];
  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between fade-up">
        <div>
          <p className="font-mono text-xs text-muted-foreground"><Link to="/srns" className="hover:underline">Releases</Link> / {s.number}</p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight" data-testid="srn-title">{s.application_name} · {s.release_version}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2"><StatusBadge s={s.status} testid="srn-status" /><span className="text-xs text-muted-foreground">{s.project_name} · {s.release_type} · Revision R{s.revision} · by {s.author_name}</span></div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" data-testid="srn-download-pdf" onClick={() => act(() => download(`/srns/${id}/document?format=pdf`, `${s.number}.pdf`))}><FileDown className="mr-1.5 h-4 w-4" />PDF</Button>
          <Button variant="outline" size="sm" data-testid="srn-download-docx" onClick={() => act(() => download(`/srns/${id}/document?format=docx`, `${s.number}.docx`))}><FileText className="mr-1.5 h-4 w-4" />DOCX</Button>
          {isAuthor && ["DRAFT", "REJECTED", "CHANGES_REQUESTED", "IN_REVIEW", "ON_HOLD"].includes(s.status) && <Link to={`/srns/${id}/edit`}><Button variant="outline" size="sm" data-testid="srn-edit"><Pencil className="mr-1.5 h-4 w-4" />Edit</Button></Link>}
          {isAuthor && ["DRAFT", "REJECTED", "CHANGES_REQUESTED"].includes(s.status) && <Button size="sm" data-testid="srn-submit-approval" onClick={() => act(() => api.post(`/srns/${id}/submit`), "Submitted for approval").then(refresh)}>Submit for approval</Button>}
          {s.can_approve && <>
            <Button size="sm" data-testid="srn-approve" onClick={() => withComment("APPROVE", "Approve release")}>Approve</Button>
            <Button size="sm" variant="outline" data-testid="srn-request-changes" onClick={() => withComment("REQUEST_CHANGES", "Request changes")}>Request changes</Button>
            <Button size="sm" variant="outline" data-testid="srn-hold" onClick={() => ask({ title: "Put release on hold", description: "BA and the responsible user are notified so the timeline can be coordinated.", fields: [{ key: "hold_reason", label: "Hold reason", type: "textarea", required: true }, { key: "responsible_id", label: "Responsible user", type: "select", required: true, options: members }, { key: "expected_date", label: "Expected resolution date", type: "date", required: true }, { key: "comment", label: "Notes", type: "textarea" }], onSubmit: (v) => decide("HOLD", v) })}>Hold</Button>
            <Button size="sm" variant="destructive" data-testid="srn-reject" onClick={() => withComment("REJECT", "Reject release — returns to author")}>Reject</Button>
          </>}
          {s.status === "ON_HOLD" && [s.hold?.by, s.hold?.responsible_id].includes(user.id) && <Button size="sm" data-testid="srn-resume" onClick={() => decide("RESUME")}>Resume review</Button>}
          {canDeploy && ["APPROVED", "DEPLOYMENT_FAILED"].includes(s.status) && <Button size="sm" data-testid="srn-authorize-deploy" onClick={() => ask({ title: "Authorize UAT deployment", fields: [{ key: "environment", label: "Environment", default: s.environment || "UAT" }, { key: "build_id", label: "Build identifier", default: s.build_ref }, { key: "notes", label: "Notes", type: "textarea" }], onSubmit: (v) => act(() => api.post(`/srns/${id}/deployments`, v), "Deployment authorized").then(refresh) })}>Authorize deployment</Button>}
          {canDeploy && s.status === "DEPLOYMENT_PENDING" && dep && <Button size="sm" data-testid="srn-start-deploy" onClick={() => act(() => api.post(`/deployments/${dep.id}/start`), "Deployment started").then(refresh)}>Start deployment</Button>}
          {canDeploy && s.status === "DEPLOYMENT_IN_PROGRESS" && dep && <>
            <Button size="sm" data-testid="srn-confirm-deploy" onClick={() => ask({ title: "Confirm successful UAT deployment", description: "This updates CR/bug states, creates UAT assignments and queues the SRN email.", fields: [{ key: "build_id", label: "Build identifier", default: dep.build_id }, { key: "notes", label: "Deployment notes", type: "textarea" }], onSubmit: (v) => act(() => api.post(`/deployments/${dep.id}/confirm`, { ...v, success: true }), "Deployment confirmed").then(refresh) })}>Confirm deployed</Button>
            <Button size="sm" variant="destructive" data-testid="srn-fail-deploy" onClick={() => ask({ title: "Record failed deployment", fields: [{ key: "failure_details", label: "Failure details", type: "textarea", required: true }, { key: "rollback_result", label: "Rollback result", type: "textarea" }], onSubmit: (v) => act(() => api.post(`/deployments/${dep.id}/confirm`, { ...v, success: false }), "Failure recorded").then(refresh) })}>Deployment failed</Button>
          </>}
        </div>
      </div>
      {!s.can_approve && s.status === "IN_REVIEW" && s.approve_block_reason && <p className="text-xs text-muted-foreground" data-testid="srn-approve-block-reason">You cannot approve: {s.approve_block_reason}</p>}
      {s.hold && s.status === "ON_HOLD" && <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-200" data-testid="srn-hold-banner"><b>On hold</b> by {s.hold.by_name}: {s.hold.reason} · expected {fmtDate(s.hold.expected_date)}</div>}
      <ol className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5" data-testid="srn-approval-stages">
        <li className="rounded-xl border bg-card p-3"><p className="text-xs text-muted-foreground">Author</p><p className="text-sm font-medium">{s.author_name}</p><p className="text-xs">{s.submitted_at ? `Submitted ${fmt(s.submitted_at)}` : "Not submitted"}</p></li>
        {s.stages.map((st) => {
          const cur = s.status === "IN_REVIEW" && s.current_stage === st.index;
          const appr = s.approvals.filter((a) => a.stage === st.key && a.valid && a.decision === "APPROVE");
          return (
            <li key={st.key} className={`rounded-xl border bg-card p-3 ${cur ? "border-primary ring-2 ring-primary/20" : ""}`}>
              <p className="flex items-center gap-1.5 text-xs text-muted-foreground">{st.complete ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Clock className="h-3.5 w-3.5" />}Stage {st.index + 1}</p>
              <p className="text-sm font-medium">{st.label}</p>
              <p className="text-[11px] text-muted-foreground">{st.all_roles ? `All of: ${(st.required_roles || []).map(label).join(", ")}` : `Any: ${st.roles.map(label).join(", ")}`}</p>
              {appr.map((a) => <p key={a.id} className="text-xs text-emerald-700 dark:text-emerald-400">✓ {a.approver_name}</p>)}
            </li>
          );
        })}
        <li className="rounded-xl border bg-card p-3"><p className="text-xs text-muted-foreground">Deployment</p><p className="text-sm font-medium">{dep ? label(dep.status) : "Not started"}</p>{dep?.completed_at && <p className="text-xs">{fmt(dep.completed_at)}</p>}</li>
      </ol>
      <Tabs defaultValue="contents">
        <TabsList className="flex h-auto flex-wrap justify-start">{[["contents", "Contents"], ["details", "Release details"], ["approvals", "Approval history"], ["deploy", "Deployments & email"], ["history", "Revisions & activity"]].map(([v, l]) => <TabsTrigger key={v} value={v} data-testid={`srn-tab-${v}`}>{l}</TabsTrigger>)}</TabsList>
        <TabsContent value="contents" className="mt-4"><Card title="Contents of this release">
          <table className="tbl w-full"><thead><tr><th>#</th><th>CR / Bug</th><th>Module</th><th>Description</th><th>Scope</th><th>Impact</th></tr></thead>
            <tbody>{s.items.map((it, i) => <tr key={it.cr_id}><td>{i + 1}</td><td><Link className="font-mono text-xs text-primary" to={`/crs/${it.cr_id}`}>{it.cr_number}</Link><br />{it.title}</td><td className="text-xs">{it.module}</td><td>{it.description}</td><td><StatusBadge s={it.scope === "full" ? "ACTIVE" : "PROPOSED"} /> <span className="text-xs">{it.scope}</span></td><td>{it.impact}</td></tr>)}
              {s.bug_items?.map((b, i) => <tr key={b.id}><td>{s.items.length + i + 1}</td><td><span className="font-mono text-xs">{b.number}</span><br />{b.title}</td><td></td><td>{b.fix_notes}</td><td className="text-xs">bug fix</td><td>Yes</td></tr>)}</tbody></table>
        </Card></TabsContent>
        <TabsContent value="details" className="mt-4"><Card><dl className="grid gap-4 sm:grid-cols-3">
          {[["Company", s.company_name], ["Intended prod version", s.intended_prod_version], ["Release date", fmtDate(s.release_date)], ["Environment", s.environment], ["Technology", s.tech_stack.join(", ")], ["Modules", s.impacted_modules.join(", ")], ["Screens", s.impacted_screens.join(", ")], ["Supporting services", s.supporting_services.map((x) => x.name).join(", ")], ["Build ref", s.build_ref]].map(([k, v]) => <Kv key={k} k={k} v={v} />)}
        </dl><div className="mt-5 grid gap-4 sm:grid-cols-2 text-sm">{[["Summary", s.summary], ["Description", s.description], ["Impact", s.impact_details], ["Testing evidence", s.testing_evidence], ["Testing instructions", s.testing_instructions], ["Deployment instructions", s.deployment_instructions], ["Rollback instructions", s.rollback_instructions]].map(([k, v]) => <div key={k}><p className="text-xs font-semibold text-muted-foreground">{k}</p><p className="whitespace-pre-wrap">{v || "—"}</p></div>)}</div></Card></TabsContent>
        <TabsContent value="approvals" className="mt-4"><Card>{!s.approvals.length ? <Empty text="No decisions yet" /> : (
          <table className="tbl w-full" data-testid="srn-approvals-table"><thead><tr><th>When</th><th>Approver</th><th>Stage</th><th>Decision</th><th>Comment</th><th>Rev</th><th>Status change</th><th>Valid</th></tr></thead>
            <tbody>{s.approvals.map((a) => <tr key={a.id}><td className="text-xs">{fmt(a.at)}</td><td>{a.approver_name}<br /><span className="text-xs text-muted-foreground">{a.role_label}</span></td><td>{a.stage_label || a.stage}</td><td><StatusBadge s={a.decision} /></td><td className="text-xs">{a.comment}</td><td>R{a.revision}</td><td className="text-xs">{label(a.before)}{a.after ? ` → ${label(a.after)}` : ""}</td><td className="text-xs">{a.valid ? "Yes" : a.invalidated_reason ? `No (${label(a.invalidated_reason)})` : "—"}</td></tr>)}</tbody></table>
        )}</Card></TabsContent>
        <TabsContent value="deploy" className="mt-4 grid gap-5 lg:grid-cols-2">
          <Card title="Deployments">{!s.deployments.length ? <Empty text="No deployments" /> : s.deployments.map((d) => (
            <div key={d.id} className="mb-3 rounded-lg border p-3 text-sm"><div className="flex justify-between"><b>{d.environment} · {d.version}</b><StatusBadge s={d.status} /></div>
              <p className="text-xs text-muted-foreground">Authorized by {d.authorized_by_name} · Deployed by {d.deployed_by_name || "—"} · Build {d.build_id || "—"}</p>
              <p className="text-xs">Start {fmt(d.started_at)} · Done {fmt(d.completed_at)}</p>{d.failure_details && <p className="text-xs text-rose-600">Failure: {d.failure_details} · Rollback: {d.rollback_result || "—"}</p>}{d.notes && <p className="text-xs">{d.notes}</p>}</div>
          ))}</Card>
          <Card title="SRN email dispatch">{!s.emails.length ? <Empty text="No emails yet" hint="Queued automatically after deployment is confirmed." /> : s.emails.map((m) => (
            <div key={m.id} className="mb-3 rounded-lg border p-3 text-sm" data-testid="srn-email-item"><div className="flex justify-between gap-2"><b className="truncate">{m.subject}</b><StatusBadge s={m.status} /></div>
              <p className="text-xs">To: {m.to.join(", ") || "—"}</p><p className="text-xs">CC: {m.cc.join(", ") || "—"}</p>
              <p className="text-xs text-muted-foreground">Attempts {m.attempts} · {m.provider_message_id ? `Provider ID ${m.provider_message_id}` : "not sent yet"} {m.last_error ? `· ${m.last_error}` : ""}</p>
              {m.status === "FAILED" && canDeploy && <Button size="sm" variant="outline" className="mt-2" onClick={() => act(() => api.post(`/emails/${m.id}/retry`), "Retry queued").then(refresh)}>Retry</Button>}
            </div>
          ))}</Card>
        </TabsContent>
        <TabsContent value="history" className="mt-4 grid gap-5 lg:grid-cols-2">
          <Card title="Activity"><Timeline items={s.activity} /></Card>
          <Card title="Revisions & generated documents">{s.revisions.map((r) => <p key={r.id} className="text-sm">R{r.revision} · {fmt(r.at)}</p>)}<p className="mt-3 text-xs font-semibold text-muted-foreground">Generated artifacts</p>{s.artifacts.map((a) => <p key={a.id} className="text-xs">{a.format.toUpperCase()} · R{a.revision} · template {a.template_version} · {a.by} · {fmt(a.at)}</p>)}</Card>
        </TabsContent>
      </Tabs>
      {promptEl}
    </div>
  );
}
