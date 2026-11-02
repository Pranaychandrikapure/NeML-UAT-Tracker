const C = {
  slate: "bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700",
  amber: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/50 dark:text-amber-300 dark:border-amber-800",
  blue: "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950/50 dark:text-blue-300 dark:border-blue-800",
  indigo: "bg-indigo-50 text-indigo-700 border-indigo-200 dark:bg-indigo-950/50 dark:text-indigo-300 dark:border-indigo-800",
  sky: "bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/50 dark:text-sky-300 dark:border-sky-800",
  teal: "bg-teal-50 text-teal-700 border-teal-200 dark:bg-teal-950/50 dark:text-teal-300 dark:border-teal-800",
  purple: "bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-950/50 dark:text-purple-300 dark:border-purple-800",
  orange: "bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-950/50 dark:text-orange-300 dark:border-orange-800",
  green: "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/50 dark:text-emerald-300 dark:border-emerald-800",
  red: "bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/50 dark:text-rose-300 dark:border-rose-800",
};

const MAP = {
  DRAFT: "slate", NEW: "amber", BA_REVIEW: "amber", IMPACT_ANALYSIS: "indigo", DEADLINE_APPROVAL_PENDING: "amber",
  ASSIGNED: "blue", IN_DEVELOPMENT: "sky", DEVELOPMENT_COMPLETED: "sky", SIT_IN_PROGRESS: "indigo", SIT_PASSED: "teal",
  SIT_FAILED: "red", READY_FOR_UAT: "teal", RELEASE_APPROVAL_PENDING: "purple", UAT_DEPLOYMENT_PENDING: "purple",
  UAT_DEPLOYED: "orange", UAT_IN_PROGRESS: "orange", UAT_HOLD: "amber", UAT_FAILED: "red", UAT_PASSED: "green",
  CLOSED: "green", CANCELLED: "slate", BLOCKED: "red", IN_REVIEW: "purple", CHANGES_REQUESTED: "amber", REJECTED: "red",
  ON_HOLD: "amber", APPROVED: "teal", DEPLOYMENT_PENDING: "purple", DEPLOYMENT_IN_PROGRESS: "sky", DEPLOYMENT_FAILED: "red",
  PENDING: "amber", IN_PROGRESS: "sky", PASSED: "green", FAILED: "red", RETEST_PENDING: "amber", RETEST_IN_PROGRESS: "sky",
  RETEST_PASSED: "green", OPEN: "red", FIXED: "sky", FIXED_AWAITING_RELEASE: "purple", VERIFIED: "green", REOPENED: "red",
  QUEUED: "slate", SENDING: "sky", SENT: "green", SUCCESS: "green", RUNNING: "sky", PROPOSED: "amber", ACTIVE: "green",
  REVISION_REQUESTED: "amber", APPROVE: "green", REJECT: "red", REQUEST_CHANGES: "amber", HOLD: "amber", RESUME: "blue",
};

export const statusClass = (s) => C[MAP[s] || "slate"];
export const label = (s) => (s || "").replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase()).replace(/\bUat\b/g, "UAT").replace(/\bSit\b/g, "SIT").replace(/\bBa\b/g, "BA").replace(/\bSrn\b/g, "SRN").replace(/\bCr\b/g, "CR");
export const prioClass = (p) => ({ Critical: C.red, High: C.orange, Medium: C.blue, Low: C.slate }[p] || C.slate);

export const CR_STAGES = [
  { label: "Submitted", s: ["DRAFT", "NEW"] },
  { label: "BA Review", s: ["BA_REVIEW"] },
  { label: "Impact & Plan", s: ["IMPACT_ANALYSIS", "DEADLINE_APPROVAL_PENDING"] },
  { label: "Development", s: ["ASSIGNED", "IN_DEVELOPMENT"] },
  { label: "SIT", s: ["SIT_IN_PROGRESS", "READY_FOR_UAT"] },
  { label: "Release Approval", s: ["RELEASE_APPROVAL_PENDING", "UAT_DEPLOYMENT_PENDING"] },
  { label: "UAT", s: ["UAT_DEPLOYED", "UAT_IN_PROGRESS", "UAT_HOLD", "UAT_FAILED", "UAT_PASSED"] },
  { label: "Closed", s: ["CLOSED"] },
];

export const CR_STATUSES = CR_STAGES.flatMap((x) => x.s).concat(["CANCELLED"]);
export const PRIORITIES = ["Critical", "High", "Medium", "Low"];
export const fmt = (d) => (d ? new Date(d).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—");
export const fmtDate = (d) => (d ? new Date(d.length === 10 ? d + "T00:00:00" : d).toLocaleDateString(undefined, { dateStyle: "medium" }) : "—");
