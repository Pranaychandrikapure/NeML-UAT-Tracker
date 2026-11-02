import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Download, ArrowUpDown, Columns3 } from "lucide-react";
import { Button } from "../components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "../components/ui/popover";
import { get, api, act } from "../lib/api";
import { useApp } from "../context/AppContext";
import { PageHeader, Card, Empty, Rows, StatusBadge, PrioBadge, Inp, Sel, Field, Txt, FormDialog, MultiCheck } from "../components/common";
import { fmtDate, fmt, CR_STATUSES, PRIORITIES, label } from "../lib/status";

const COLS = [
  ["number", "CR Number"], ["title", "Title"], ["project_name", "Project"], ["ba_name", "BA"], ["manager_name", "Assigned PM"], ["priority", "Priority"],
  ["status", "Current Status"], ["requested_deadline", "Requested Deadline"], ["approved_deadline", "Approved Deadline"], ["progress", "Dev Progress"],
  ["uat_status", "UAT Status"], ["updated_at", "Last Updated"],
];

export function NewCRDialog({ open, onOpenChange }) {
  const { user, projectId } = useApp();
  const qc = useQueryClient();
  const [f, setF] = useState({ project_id: projectId, title: "", description: "", business_requirements: "", expected_result: "", justification: "", priority: "Medium", requested_deadline: "", business_owner: "", acceptance_criteria: "", impacted_module_ids: [], attachments: [] });
  const [link, setLink] = useState("");
  const proj = useQuery({ queryKey: ["project", f.project_id], queryFn: () => get(`/projects/${f.project_id}`), enabled: !!f.project_id && open });
  const s = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const submit = (asDraft) => act(() => api.post("/crs", { ...f, requested_deadline: f.requested_deadline || null, submit: !asDraft }), asDraft ? "Draft saved" : "CR submitted").then(() => qc.invalidateQueries());
  return (
    <FormDialog open={open} onOpenChange={onOpenChange} title="New Change Request" description="Internal CRs follow the same BA → development → release workflow as Zoho CRs." onSubmit={() => submit(false)} submitLabel="Submit CR" testid="new-cr-dialog" wide>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Project *"><Sel required data-testid="cr-form-project" value={f.project_id} onChange={s("project_id")} options={(user.projects || []).map((p) => ({ value: p.id, label: p.name }))} placeholder="Select project" /></Field>
        <Field label="Priority"><Sel data-testid="cr-form-priority" value={f.priority} onChange={s("priority")} options={PRIORITIES} /></Field>
        <Field label="Title *" className="sm:col-span-2"><Inp required data-testid="cr-form-title" value={f.title} onChange={s("title")} /></Field>
        <Field label="Description" className="sm:col-span-2"><Txt data-testid="cr-form-description" value={f.description} onChange={s("description")} /></Field>
        <Field label="Business requirements"><Txt value={f.business_requirements} onChange={s("business_requirements")} /></Field>
        <Field label="Expected result"><Txt value={f.expected_result} onChange={s("expected_result")} /></Field>
        <Field label="Business justification"><Txt value={f.justification} onChange={s("justification")} /></Field>
        <Field label="Acceptance criteria"><Txt value={f.acceptance_criteria} onChange={s("acceptance_criteria")} /></Field>
        <Field label="Requested deadline"><Inp type="date" data-testid="cr-form-deadline" value={f.requested_deadline} onChange={s("requested_deadline")} /></Field>
        <Field label="Business owner"><Inp value={f.business_owner} onChange={s("business_owner")} /></Field>
        {proj.data?.modules?.length > 0 && <Field label="Impacted modules" className="sm:col-span-2"><MultiCheck options={proj.data.modules.filter((m) => !m.archived).map((m) => ({ value: m.id, label: m.name }))} value={f.impacted_module_ids} onChange={(v) => setF({ ...f, impacted_module_ids: v })} /></Field>}
        <Field label="Attachment links" className="sm:col-span-2" hint={f.attachments.map((a) => a.name).join(", ")}>
          <div className="flex gap-2"><Inp placeholder="https://…" value={link} onChange={(e) => setLink(e.target.value)} /><Button type="button" variant="outline" onClick={() => { if (link) { setF({ ...f, attachments: [...f.attachments, { name: link.split("/").pop() || link, url: link }] }); setLink(""); } }}>Add</Button></div>
        </Field>
      </div>
      <Button type="button" variant="ghost" size="sm" data-testid="cr-form-save-draft" onClick={async () => { await submit(true); onOpenChange(false); }}>Save as draft instead</Button>
    </FormDialog>
  );
}

export default function CRList() {
  const { projectId, has } = useApp();
  const [sp] = useSearchParams();
  const [f, setF] = useState({ q: "", status: sp.get("status") || "", priority: sp.get("priority") || "", source: "" });
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("-updated_at");
  const [hidden, setHidden] = useState([]);
  const [open, setOpen] = useState(false);
  const params = { ...f, project_id: projectId, page, page_size: 20, sort };
  const { data, isLoading } = useQuery({ queryKey: ["crs", params], queryFn: () => get("/crs", params) });
  const cols = COLS.filter(([k]) => !hidden.includes(k));
  const cell = (c, k) => ({
    number: <Link to={`/crs/${c.id}`} className="font-mono text-xs font-medium text-primary hover:underline" data-testid={`cr-link-${c.number}`}>{c.number}</Link>,
    title: <span className="line-clamp-2 min-w-[180px]">{c.title}</span>, priority: <PrioBadge p={c.priority} />, status: <StatusBadge s={c.status} />,
    uat_status: c.uat_status ? <StatusBadge s={c.uat_status} /> : "—", requested_deadline: fmtDate(c.requested_deadline), approved_deadline: fmtDate(c.approved_deadline),
    updated_at: <span className="whitespace-nowrap text-xs">{fmt(c.updated_at)}</span>,
    progress: <div className="w-24"><div className="h-1.5 rounded-full bg-muted"><div className="h-1.5 rounded-full bg-primary" style={{ width: `${c.task_total ? (100 * c.task_done) / c.task_total : 0}%` }} /></div><span className="text-[11px] text-muted-foreground">{c.task_done}/{c.task_total} SIT passed</span></div>,
  }[k] ?? (c[k] || "—"));
  const exportCsv = async () => {
    const all = await get("/crs", { ...params, page: 1, page_size: 500 });
    const rows = [COLS.map((c) => c[1]), ...all.items.map((c) => COLS.map(([k]) => k === "progress" ? `${c.task_done}/${c.task_total}` : c[k] ?? ""))];
    const blob = new Blob([rows.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n")], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "change_requests.csv"; a.click();
  };
  const total = data?.total || 0;
  return (
    <div>
      <PageHeader title="Change Requests" subtitle={`${total} CRs in your scope`}>
        <Button variant="outline" onClick={exportCsv} data-testid="cr-export-csv"><Download className="mr-2 h-4 w-4" />Export CSV</Button>
        {has("ba", "ba_lead", "system_admin") && <Button onClick={() => setOpen(true)} data-testid="new-cr-button"><Plus className="mr-2 h-4 w-4" />New CR</Button>}
      </PageHeader>
      <Card>
        <div className="mb-4 flex flex-wrap gap-2">
          <Inp data-testid="cr-search" placeholder="Search number or title" value={f.q} onChange={(e) => { setF({ ...f, q: e.target.value }); setPage(1); }} className="max-w-xs" />
          <Sel data-testid="cr-filter-status" value={f.status} onChange={(e) => { setF({ ...f, status: e.target.value }); setPage(1); }} options={CR_STATUSES.map((s) => ({ value: s, label: label(s) }))} placeholder="All statuses" className="w-52" />
          <Sel data-testid="cr-filter-priority" value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value })} options={PRIORITIES} placeholder="All priorities" className="w-40" />
          <Sel data-testid="cr-filter-source" value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })} options={[{ value: "ZOHO", label: "Zoho" }, { value: "INTERNAL", label: "Internal" }]} placeholder="All sources" className="w-36" />
          <Popover>
            <PopoverTrigger asChild><Button variant="outline" data-testid="cr-columns-button"><Columns3 className="mr-2 h-4 w-4" />Columns</Button></PopoverTrigger>
            <PopoverContent className="w-56 space-y-1">{COLS.map(([k, l]) => (
              <label key={k} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!hidden.includes(k)} onChange={() => setHidden(hidden.includes(k) ? hidden.filter((x) => x !== k) : [...hidden, k])} />{l}</label>
            ))}</PopoverContent>
          </Popover>
        </div>
        {isLoading ? <Rows n={8} /> : !data.items.length ? <Empty text="No change requests match" hint="Adjust filters or create a new CR." /> : (
          <div className="overflow-x-auto rounded-lg border">
            <table className="tbl w-full" data-testid="cr-table">
              <thead><tr>{cols.map(([k, l]) => (
                <th key={k}><button className="inline-flex items-center gap-1" onClick={() => setSort(sort === k ? `-${k}` : k)}>{l}{["number", "priority", "status", "requested_deadline", "updated_at"].includes(k) && <ArrowUpDown className="h-3 w-3" />}</button></th>
              ))}<th>Action</th></tr></thead>
              <tbody>{data.items.map((c) => (
                <tr key={c.id} data-testid={`cr-row-${c.number}`}>{cols.map(([k]) => <td key={k}>{cell(c, k)}</td>)}<td><Link to={`/crs/${c.id}`} className="text-xs font-medium text-primary">Open</Link></td></tr>
              ))}</tbody>
            </table>
          </div>
        )}
        {total > 20 && (
          <div className="mt-3 flex items-center justify-end gap-2 text-sm">
            <Button variant="outline" size="sm" disabled={page === 1} onClick={() => setPage(page - 1)} data-testid="cr-prev-page">Previous</Button>
            <span>Page {page} of {Math.ceil(total / 20)}</span>
            <Button variant="outline" size="sm" disabled={page * 20 >= total} onClick={() => setPage(page + 1)} data-testid="cr-next-page">Next</Button>
          </div>
        )}
      </Card>
      {open && <NewCRDialog open={open} onOpenChange={setOpen} />}
    </div>
  );
}
