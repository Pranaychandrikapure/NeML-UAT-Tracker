import { useState, useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Plus, X } from "lucide-react";
import { Button } from "../components/ui/button";
import { get, api, act } from "../lib/api";
import { useApp } from "../context/AppContext";
import { PageHeader, Card, Empty, Rows, Field, Inp, Txt, Sel, MultiCheck, StatusBadge } from "../components/common";

const STEPS = ["Select Project", "Eligible CRs / Bugs", "Release Details", "Technology & Services", "Preview", "Submit"];
const blank = { project_id: "", application_name: "", company_name: "", team_name: "", release_version: "", intended_prod_version: "", release_type: "Final", release_date: new Date().toISOString().slice(0, 10), environment: "UAT", tech_stack: [], impacted_modules: [], impacted_screens: [], supporting_services: [], items: [], bug_ids: [], description: "", summary: "", impact_details: "", testing_evidence: "", testing_instructions: "", deployment_instructions: "", rollback_instructions: "", build_ref: "", attachments: [] };

export default function SRNWizard() {
  const { id } = useParams();
  const { user, projectId } = useApp();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [step, setStep] = useState(0);
  const [f, setF] = useState({ ...blank, project_id: projectId });
  const [svc, setSvc] = useState("");
  const existing = useQuery({ queryKey: ["srn", id], queryFn: () => get(`/srns/${id}`), enabled: !!id });
  useEffect(() => {
    if (existing.data) { const s = existing.data; setF({ ...blank, ...Object.fromEntries(Object.keys(blank).map((k) => [k, s[k] ?? blank[k]])), items: s.items.map((i) => ({ cr_id: i.cr_id, task_ids: i.task_ids, description: i.description, impact: i.impact })) }); setStep(1); }
  }, [existing.data]);
  const el = useQuery({ queryKey: ["eligible", f.project_id], queryFn: () => get("/srns/eligible", { project_id: f.project_id }), enabled: !!f.project_id });
  const tech = useQuery({ queryKey: ["tech"], queryFn: () => get("/master/tech") });
  const proj = useQuery({ queryKey: ["project", f.project_id], queryFn: () => get(`/projects/${f.project_id}`), enabled: !!f.project_id });
  const s = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const crs = [...(el.data?.crs || []), ...(existing.data?.items || []).filter((i) => !(el.data?.crs || []).some((c) => c.cr_id === i.cr_id)).map((i) => ({ cr_id: i.cr_id, cr_number: i.cr_number, title: i.title, tasks: i.task_ids.map((t) => ({ id: t, number: "task", title: "" })), full_possible: i.scope === "full", remaining_tasks: 0, module: i.module }))];
  const bugs = [...(el.data?.bugs || [])];
  const toggleCR = (c) => {
    const on = f.items.some((i) => i.cr_id === c.cr_id);
    const items = on ? f.items.filter((i) => i.cr_id !== c.cr_id) : [...f.items, { cr_id: c.cr_id, task_ids: c.tasks.map((t) => t.id), description: c.title, impact: "Yes" }];
    const mods = new Set(f.impacted_modules); if (!on && c.module) c.module.split(", ").forEach((m) => mods.add(m));
    setF({ ...f, items, impacted_modules: [...mods].filter(Boolean) });
  };
  const canNext = [!!f.project_id, f.items.length + f.bug_ids.length > 0, !!f.release_version && !!f.summary, true, true, true][step];
  const save = async (submit) => {
    const body = { ...f, release_date: f.release_date || null };
    const r = await act(() => (id ? api.patch(`/srns/${id}`, body) : api.post("/srns", body)), id ? "SRN updated" : "SRN draft saved");
    if (submit && ["DRAFT", "REJECTED", "CHANGES_REQUESTED"].includes(r.data.status)) await act(() => api.post(`/srns/${r.data.id}/submit`), "Submitted for approval");
    qc.invalidateQueries();
    nav(`/srns/${r.data.id}`);
  };
  const projectName = user.projects.find((p) => p.id === f.project_id)?.name;
  return (
    <div>
      <PageHeader title={id ? `Edit ${existing.data?.number || "SRN"}` : "New Software Release Note"} subtitle="Guided release note — the DOCX/PDF is generated on the server from this data using your SRN template." />
      <ol className="mb-6 flex flex-wrap gap-2" data-testid="srn-wizard-steps">
        {STEPS.map((l, i) => <li key={l} className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium ${i === step ? "border-primary bg-primary text-primary-foreground" : i < step ? "border-emerald-300 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40" : "text-muted-foreground"}`}>{i < step ? <Check className="h-3 w-3" /> : `${i + 1}.`} {l}</li>)}
      </ol>
      <Card>
        {step === 0 && (
          <Field label="Project"><Sel data-testid="srn-project" disabled={!!id} value={f.project_id} onChange={(e) => setF({ ...blank, project_id: e.target.value, application_name: user.projects.find((p) => p.id === e.target.value)?.name || "" })} options={user.projects.map((p) => ({ value: p.id, label: p.name }))} placeholder="Select project" /></Field>
        )}
        {step === 1 && (el.isLoading ? <Rows /> : (
          <div className="space-y-6">
            <div>
              <h3 className="mb-2 text-sm font-semibold">Change Requests with SIT-passed work</h3>
              {!crs.length ? <Empty text="No CRs eligible" hint="Only tasks that passed SIT and are not in another active SRN appear here." /> : crs.map((c) => {
                const on = f.items.some((i) => i.cr_id === c.cr_id);
                return (
                  <button type="button" key={c.cr_id} onClick={() => toggleCR(c)} data-testid={`srn-cr-${c.cr_number}`} className={`mb-2 flex w-full items-start gap-3 rounded-lg border p-3 text-left transition-colors ${on ? "border-primary bg-primary/5" : "hover:bg-muted/50"}`}>
                    <span className={`mt-0.5 flex h-4 w-4 items-center justify-center rounded border ${on ? "border-primary bg-primary text-white" : ""}`}>{on && <Check className="h-3 w-3" />}</span>
                    <span className="flex-1"><span className="font-mono text-xs">{c.cr_number}</span> <span className="font-medium">{c.title}</span>
                      <span className="block text-xs text-muted-foreground">{c.tasks.length} SIT-passed task(s) · {c.full_possible ? "Full release scope" : `Partial release — ${c.remaining_tasks} task(s) still in progress, CR stays open`}</span></span>
                  </button>
                );
              })}
            </div>
            <div>
              <h3 className="mb-2 text-sm font-semibold">Bug fixes (SIT passed)</h3>
              {!bugs.length ? <Empty text="No bug fixes eligible" /> : <MultiCheck testid="srn-bugs" options={bugs.map((b) => ({ value: b.id, label: `${b.number} ${b.title}` }))} value={f.bug_ids} onChange={(v) => setF({ ...f, bug_ids: v })} />}
            </div>
          </div>
        ))}
        {step === 2 && (
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Company name"><Inp value={f.company_name} onChange={s("company_name")} placeholder="e.g. your organisation" /></Field>
            <Field label="Application / product name"><Inp value={f.application_name} onChange={s("application_name")} /></Field>
            <Field label="Team name"><Inp value={f.team_name} onChange={s("team_name")} /></Field>
            <Field label="Release version *"><Inp required data-testid="srn-version" value={f.release_version} onChange={s("release_version")} placeholder="V2.0.42U10" /></Field>
            <Field label="Intended production version"><Inp value={f.intended_prod_version} onChange={s("intended_prod_version")} placeholder="V2.0.42" /></Field>
            <Field label="Release type"><Sel value={f.release_type} onChange={s("release_type")} options={["Final", "Interim", "Hotfix", "Patch"]} /></Field>
            <Field label="Release date"><Inp type="date" value={f.release_date} onChange={s("release_date")} /></Field>
            <Field label="Environment"><Sel value={f.environment} onChange={s("environment")} options={["UAT", "Pre-Prod", "SIT"]} /></Field>
            <Field label="Git commit / build reference"><Inp value={f.build_ref} onChange={s("build_ref")} /></Field>
            <Field label="Release summary *" className="sm:col-span-3"><Txt data-testid="srn-summary" value={f.summary} onChange={s("summary")} /></Field>
            <Field label="Description of changes" className="sm:col-span-3"><Txt value={f.description} onChange={s("description")} /></Field>
            {f.items.map((it, i) => (
              <Field key={it.cr_id} label={`${crs.find((c) => c.cr_id === it.cr_id)?.cr_number} — description in release table`} className="sm:col-span-3">
                <div className="flex gap-2"><Inp value={it.description} onChange={(e) => setF({ ...f, items: f.items.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)) })} /><Sel className="w-24" value={it.impact} onChange={(e) => setF({ ...f, items: f.items.map((x, j) => (j === i ? { ...x, impact: e.target.value } : x)) })} options={["Yes", "No"]} /></div>
              </Field>
            ))}
            <Field label="Impact details"><Txt value={f.impact_details} onChange={s("impact_details")} /></Field>
            <Field label="Testing evidence"><Txt value={f.testing_evidence} onChange={s("testing_evidence")} /></Field>
            <Field label="Testing instructions for UAT"><Txt value={f.testing_instructions} onChange={s("testing_instructions")} /></Field>
            <Field label="Deployment instructions" className="sm:col-span-2"><Txt value={f.deployment_instructions} onChange={s("deployment_instructions")} /></Field>
            <Field label="Rollback instructions"><Txt value={f.rollback_instructions} onChange={s("rollback_instructions")} /></Field>
          </div>
        )}
        {step === 3 && (
          <div className="space-y-5">
            <Field label="Technology stack (from master data)"><MultiCheck testid="srn-tech" options={tech.data || []} value={f.tech_stack} onChange={(v) => setF({ ...f, tech_stack: v })} /></Field>
            <Field label="Impacted modules"><MultiCheck options={(proj.data?.modules || []).map((m) => m.name)} value={f.impacted_modules} onChange={(v) => setF({ ...f, impacted_modules: v })} /></Field>
            <Field label="Impacted screens"><MultiCheck options={(proj.data?.modules || []).flatMap((m) => m.screens.map((x) => x.name))} value={f.impacted_screens} onChange={(v) => setF({ ...f, impacted_screens: v })} /></Field>
            <Field label="Supporting services">
              <div className="flex gap-2"><Inp data-testid="srn-service-input" value={svc} onChange={(e) => setSvc(e.target.value)} placeholder="e.g. neml-upp-lot-v2-service" /><Button type="button" variant="outline" data-testid="srn-service-add" onClick={() => { if (svc) { setF({ ...f, supporting_services: [...f.supporting_services, { name: svc, impact: "Yes" }] }); setSvc(""); } }}><Plus className="h-4 w-4" /></Button></div>
              <div className="mt-2 flex flex-wrap gap-2">{f.supporting_services.map((x, i) => <span key={i} className="inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs">{x.name}<button type="button" onClick={() => setF({ ...f, supporting_services: f.supporting_services.filter((_, j) => j !== i) })}><X className="h-3 w-3" /></button></span>)}</div>
            </Field>
          </div>
        )}
        {step >= 4 && (
          <div className="mx-auto max-w-3xl rounded-lg border bg-white p-8 text-slate-900 shadow-sm" data-testid="srn-preview">
            <div className="text-center"><p className="text-lg font-bold text-blue-900">{f.company_name || "Company"}</p><p className="font-semibold text-blue-900">Software Release Note</p><p className="text-sm">Release for {f.application_name || projectName} {f.release_version}</p></div>
            <table className="mt-5 w-full border text-xs"><tbody>
              {[[`Product Name: ${f.application_name}`, `Module Name: ${f.impacted_modules.join(", ")}`], [`SRN No: ${existing.data?.number || "(assigned on save)"}`, `Author: ${existing.data?.author_name || user.name}`], [`Intended Prod Version: ${f.intended_prod_version}`, `Version: ${f.release_version}`], [`SRN Type: ${f.release_type}`, `Release Date: ${f.release_date}`]].map((r, i) => <tr key={i}>{r.map((c) => <td key={c} className="border p-1.5">{c}</td>)}</tr>)}
            </tbody></table>
            <p className="mt-4 text-sm font-semibold">Summary:</p><p className="whitespace-pre-wrap text-sm">{f.summary}</p>
            <p className="mt-4 text-sm font-semibold">1.1 Contents of this Release</p>
            <table className="mt-1 w-full border text-xs"><thead><tr className="bg-slate-100">{["Sr.No.", "CR's/Bugs", "Description", "Impact"].map((h) => <th key={h} className="border p-1.5 text-left">{h}</th>)}</tr></thead>
              <tbody>{f.items.map((it, i) => <tr key={it.cr_id}><td className="border p-1.5">{i + 1}</td><td className="border p-1.5">{crs.find((c) => c.cr_id === it.cr_id)?.cr_number}</td><td className="border p-1.5">{it.description}</td><td className="border p-1.5">{it.impact}</td></tr>)}
                {f.bug_ids.map((b, i) => { const bug = bugs.find((x) => x.id === b); return <tr key={b}><td className="border p-1.5">{f.items.length + i + 1}</td><td className="border p-1.5">{bug?.number}</td><td className="border p-1.5">{bug?.title}</td><td className="border p-1.5">Yes</td></tr>; })}</tbody></table>
            <p className="mt-4 text-xs text-slate-500">Prepared / Reviewed / Approved By rows are filled automatically from approval records. Tech: {f.tech_stack.join(", ") || "—"}</p>
          </div>
        )}
        {step === 5 && <p className="mt-4 text-center text-sm text-muted-foreground">Submitting routes this SRN through the project's approval stages. Any later material change invalidates approvals and restarts review.</p>}
        <div className="mt-6 flex justify-between border-t pt-4">
          <Button variant="outline" disabled={step === 0} onClick={() => setStep(step - 1)} data-testid="srn-wizard-back">Back</Button>
          <div className="flex gap-2">
            {step >= 2 && <Button variant="outline" disabled={!f.release_version || !f.summary} onClick={() => save(false)} data-testid="srn-save-draft">Save draft</Button>}
            {step < 5 ? <Button disabled={!canNext} onClick={() => setStep(step + 1)} data-testid="srn-wizard-next">Next</Button>
              : <Button onClick={() => save(true)} data-testid="srn-submit" disabled={existing.data && !["DRAFT", "REJECTED", "CHANGES_REQUESTED"].includes(existing.data.status) && false}>Save & submit for approval</Button>}
          </div>
        </div>
        {existing.data && <p className="mt-2 text-right text-xs text-muted-foreground">Current status: <StatusBadge s={existing.data.status} /></p>}
      </Card>
    </div>
  );
}
