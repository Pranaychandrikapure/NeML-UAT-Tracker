import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "../components/ui/button";
import { get, api, act } from "../lib/api";
import { useApp } from "../context/AppContext";
import { usePrompt } from "../components/Prompt";
import { PageHeader, Card, Empty, Rows, StatusBadge } from "../components/common";
import { fmt, label } from "../lib/status";

const COLS = [["New / pending", ["PENDING", "RETEST_PENDING"]], ["Testing", ["IN_PROGRESS", "RETEST_IN_PROGRESS"]], ["On hold", ["ON_HOLD"]], ["Failed", ["FAILED"]], ["Completed", ["PASSED", "RETEST_PASSED"]]];

export default function UAT() {
  const { projectId, has } = useApp();
  const qc = useQueryClient();
  const [ask, promptEl] = usePrompt();
  const { data, isLoading } = useQuery({ queryKey: ["uat", projectId], queryFn: () => get("/uat/assignments", { project_id: projectId }) });
  const verify = useQuery({ queryKey: ["bugs-verify", projectId], queryFn: () => get("/bugs", { project_id: projectId, status: "UAT_DEPLOYED,RETEST_IN_PROGRESS" }) });
  const isUat = has("uat_lead", "uat_manager", "uat_member");
  const refresh = () => qc.invalidateQueries();
  const run = (a, action, body = {}, msg) => act(() => api.post(`/uat/assignments/${a.id}/action/${action}`, body), msg || label(action)).then(refresh);
  const members = async (pid) => (await get(`/projects/${pid}`)).members.map((m) => ({ value: m.user_id, label: `${m.name} · ${label(m.project_role)}` }));
  const actions = (a) => {
    if (!isUat) return null;
    const b = [];
    if (["PENDING", "RETEST_PENDING"].includes(a.status)) b.push(["Start testing", () => run(a, "start", {}, "Testing started")]);
    if (["IN_PROGRESS", "RETEST_IN_PROGRESS"].includes(a.status)) {
      b.push(["Record test case", () => ask({ title: `Test case · ${a.cr_number}`, fields: [{ key: "title", label: "Scenario", required: true }, { key: "result", label: "Result", type: "select", required: true, options: ["PASS", "FAIL", "BLOCKED"] }, { key: "evidence", label: "Evidence", type: "textarea" }], onSubmit: (v) => run(a, "add_case", v, "Test result saved") })]);
      b.push(["Report bug", () => ask({ title: `Report bug on ${a.cr_number}`, fields: [{ key: "title", label: "Title", required: true }, { key: "severity", label: "Severity", type: "select", options: ["Critical", "High", "Medium", "Low"], default: "Medium" }, { key: "steps", label: "Steps to reproduce", type: "textarea" }, { key: "expected", label: "Expected behaviour", type: "textarea" }, { key: "actual", label: "Actual behaviour", type: "textarea" }], onSubmit: (v) => act(() => api.post("/bugs", { ...v, cr_id: a.cr_id, uat_assignment_id: a.id }), "Bug reported").then(refresh) })]);
      b.push(["Pass", () => ask({ title: "Accept UAT", fields: [{ key: "comment", label: "Acceptance note", type: "textarea" }], onSubmit: (v) => run(a, "pass", v, "UAT passed") })]);
      b.push(["Fail", () => ask({ title: "Fail UAT", fields: [{ key: "comment", label: "Reason", type: "textarea", required: true }], onSubmit: (v) => run(a, "fail", v, "UAT failed") })]);
    }
    if (["PENDING", "IN_PROGRESS", "RETEST_PENDING", "RETEST_IN_PROGRESS"].includes(a.status)) b.push(["Hold", async () => { const opts = await members(a.project_id); ask({ title: "Place UAT on hold", description: "BA is notified to coordinate a revised timeline.", fields: [{ key: "reason", label: "Reason", type: "textarea", required: true }, { key: "responsible_id", label: "Responsible user", type: "select", required: true, options: opts }, { key: "expected_date", label: "Expected resolution", type: "date", required: true }, { key: "comment", label: "Notes", type: "textarea" }], onSubmit: (v) => run(a, "hold", v, "On hold") }); }]);
    if (a.status === "ON_HOLD") b.push(["Resume", () => run(a, "resume", {}, "Resumed")]);
    return b;
  };
  return (
    <div>
      <PageHeader title="UAT Management" subtitle="Deployed releases waiting for testing, active test runs, holds and bug verification." />
      {isLoading ? <Rows n={6} /> : !data.length ? <Card><Empty text="No UAT assignments" hint="Assignments are created automatically when a release is confirmed deployed to UAT." /></Card> : (
        <div className="grid gap-4 lg:grid-cols-5">{COLS.map(([t, sts]) => {
          const items = data.filter((a) => sts.includes(a.status));
          return <Card key={t} title={`${t} (${items.length})`}>{!items.length ? <p className="py-3 text-center text-xs text-muted-foreground">None</p> : items.map((a) => (
            <div key={a.id} className="mb-3 rounded-lg border p-3" data-testid={`uat-card-${a.cr_number}-${a.srn_number}`}>
              <p className="font-mono text-[11px] text-muted-foreground"><Link to={`/srns/${a.srn_id}`} className="hover:underline">{a.srn_number}</Link> · {a.kind === "BUG_RETEST" ? "Retest" : a.scope}</p>
              <Link to={`/crs/${a.cr_id}`} className="text-sm font-medium hover:text-primary">{a.cr_number} {a.title}</Link>
              <div className="mt-1.5 flex items-center gap-2"><StatusBadge s={a.status} />{a.open_bugs > 0 && <span className="text-[11px] text-rose-600">{a.open_bugs} open bug(s)</span>}</div>
              {a.hold && a.status === "ON_HOLD" && <p className="mt-1 text-[11px] text-amber-700">Hold: {a.hold.reason}</p>}
              {a.test_cases?.length > 0 && <p className="mt-1 text-[11px] text-muted-foreground">{a.test_cases.filter((c) => c.result === "PASS").length}/{a.test_cases.length} cases passed</p>}
              <div className="mt-2 flex flex-wrap gap-1">{actions(a)?.map(([l, fn]) => <Button key={l} size="sm" variant={l === "Start testing" || l === "Pass" ? "default" : "outline"} className="h-7 px-2 text-xs" onClick={fn} data-testid={`uat-${a.cr_number}-${l.toLowerCase().replace(/ /g, "-")}`}>{l}</Button>)}</div>
            </div>
          ))}</Card>;
        })}</div>
      )}
      <Card title="Bugs awaiting verification" className="mt-6" testid="bugs-awaiting-verification">
        {verify.isLoading ? <Rows /> : !verify.data.length ? <Empty text="No bug fixes awaiting retest" /> : verify.data.map((b) => (
          <div key={b.id} className="flex flex-wrap items-center justify-between gap-2 border-b py-2 last:border-0">
            <span className="text-sm"><span className="font-mono text-xs">{b.number}</span> {b.title} <span className="text-xs text-muted-foreground">· {b.cr_number} · fixed: {b.fix_notes}</span></span>
            <span className="flex items-center gap-2"><StatusBadge s={b.status} />{isUat && b.status === "RETEST_IN_PROGRESS" && <>
              <Button size="sm" className="h-7 text-xs" data-testid={`verify-${b.number}`} onClick={() => act(() => api.post(`/bugs/${b.id}/action/verify`, {}), "Bug verified").then(refresh)}>Verify</Button>
              <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => ask({ title: "Reopen bug", fields: [{ key: "comment", label: "Reason", type: "textarea", required: true }], onSubmit: (v) => act(() => api.post(`/bugs/${b.id}/action/reopen`, v), "Reopened").then(refresh) })}>Reopen</Button></>}
              {isUat && b.status === "UAT_DEPLOYED" && <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => act(() => api.post(`/bugs/${b.id}/action/retest_start`, {}), "Retest started").then(refresh)}>Start retest</Button>}
            </span>
          </div>
        ))}
      </Card>
      <p className="mt-3 text-xs text-muted-foreground">Last refreshed {fmt(new Date().toISOString())}</p>
      {promptEl}
    </div>
  );
}
