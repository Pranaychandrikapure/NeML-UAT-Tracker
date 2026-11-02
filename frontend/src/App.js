import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Show, SignIn, SignUp, useClerk } from "@clerk/react";
import { ShieldAlert, Layers, GitBranch, Rocket, FlaskConical } from "lucide-react";
import { Toaster } from "./components/ui/sonner";
import ClerkAuthProvider from "@/components/auth/ClerkAuthProvider";
import { AppProvider, useApp } from "./context/AppContext";
import Layout from "./components/Layout";
import { Rows } from "./components/common";
import Dashboard from "./pages/Dashboard";
import CRList from "./pages/CRList";
import CRDetail from "./pages/CRDetail";
import MyTasks from "./pages/MyTasks";
import Approvals from "./pages/Approvals";
import SRNList from "./pages/SRNList";
import SRNWizard from "./pages/SRNWizard";
import SRNDetail from "./pages/SRNDetail";
import UAT from "./pages/UAT";
import Bugs from "./pages/Bugs";
import Projects from "./pages/Projects";
import ProjectDetail from "./pages/ProjectDetail";
import Reports from "./pages/Reports";
import Admin from "./pages/Admin";
import SettingsPage from "./pages/Settings";

if (localStorage.getItem("crems_theme") === "dark") document.documentElement.classList.add("dark");
const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 10000, refetchOnWindowFocus: false } } });

const AuthShell = ({ children }) => (
  <div className="grid min-h-screen lg:grid-cols-2">
    <div className="relative hidden flex-col justify-between overflow-hidden bg-slate-900 p-12 text-white lg:flex">
      <div className="flex items-center gap-2"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600"><Layers className="h-5 w-5" /></div><span className="font-heading text-xl font-bold">CReMS</span></div>
      <div>
        <h1 className="font-heading text-4xl font-bold leading-tight">One place for every change, from request to release.</h1>
        <p className="mt-4 max-w-md text-slate-300">Change requests, development, SIT, release notes, approvals, UAT deployments and bug fixes — connected in a single governed workflow.</p>
        <div className="mt-10 grid max-w-md grid-cols-3 gap-4 text-sm">
          {[[GitBranch, "Tracked CR lifecycle"], [Rocket, "Approved SRN releases"], [FlaskConical, "UAT & bug retest"]].map(([I, t]) => (
            <div key={t} className="rounded-lg border border-slate-700 bg-slate-800/60 p-3"><I className="mb-2 h-5 w-5 text-blue-400" />{t}</div>
          ))}
        </div>
      </div>
      <p className="text-xs text-slate-500">Access is limited to provisioned CReMS accounts.</p>
    </div>
    <div className="flex items-center justify-center p-6">{children}</div>
  </div>
);

function NotAuthorized({ code }) {
  const { signOut } = useClerk();
  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="max-w-md rounded-xl border bg-card p-8 text-center shadow-sm" data-testid="not-authorized">
        <ShieldAlert className="mx-auto mb-3 h-10 w-10 text-amber-500" />
        <h1 className="text-xl font-bold">{code === "ACCOUNT_INACTIVE" ? "Your account is inactive" : "Account not provisioned"}</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {code === "ACCOUNT_INACTIVE" ? "Your CReMS access has been deactivated. Contact your administrator." : "You signed in successfully, but this email has not been given access to CReMS. Ask your manager or System Admin to create your account."}
        </p>
        <button data-testid="sign-out-button" onClick={() => signOut()} className="mt-6 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground">Sign out</button>
      </div>
    </div>
  );
}

function Gate() {
  const { me } = useApp();
  if (me.isLoading) return <div className="p-10"><Rows n={6} /></div>;
  if (me.isError) return <NotAuthorized code={me.error?.response?.data?.detail} />;
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/crs" element={<CRList />} />
        <Route path="/crs/:id" element={<CRDetail />} />
        <Route path="/tasks" element={<MyTasks />} />
        <Route path="/approvals" element={<Approvals />} />
        <Route path="/srns" element={<SRNList />} />
        <Route path="/srns/new" element={<SRNWizard />} />
        <Route path="/srns/:id" element={<SRNDetail />} />
        <Route path="/srns/:id/edit" element={<SRNWizard />} />
        <Route path="/uat" element={<UAT />} />
        <Route path="/bugs" element={<Bugs />} />
        <Route path="/projects" element={<Projects />} />
        <Route path="/projects/:id" element={<ProjectDetail />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}

function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <ClerkAuthProvider>
          <Routes>
            <Route path="/sign-in/*" element={<AuthShell><SignIn routing="path" path="/sign-in" signUpUrl="/sign-up" withSignUp /></AuthShell>} />
            <Route path="/sign-up/*" element={<AuthShell><SignUp routing="path" path="/sign-up" signInUrl="/sign-in" /></AuthShell>} />
            <Route path="/*" element={<>
              <Show when="signed-in"><AppProvider><Gate /></AppProvider></Show>
              <Show when="signed-out"><Navigate to="/sign-in" replace /></Show>
            </>} />
          </Routes>
        </ClerkAuthProvider>
      </BrowserRouter>
      <Toaster richColors position="top-right" />
    </QueryClientProvider>
  );
}

export default App;
