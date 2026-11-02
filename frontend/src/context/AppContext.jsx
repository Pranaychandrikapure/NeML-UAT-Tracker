import { createContext, useContext, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { get } from "../lib/api";

const Ctx = createContext(null);
export const useApp = () => useContext(Ctx);

export function AppProvider({ children }) {
  const qc = useQueryClient();
  const [projectId, setProjectIdState] = useState(localStorage.getItem("crems_project") || "");
  const me = useQuery({ queryKey: ["me"], queryFn: () => get("/me"), retry: false });
  const setProjectId = (v) => { localStorage.setItem("crems_project", v); setProjectIdState(v); };
  const actAs = (id) => {
    if (id) localStorage.setItem("crems_act_as", id); else localStorage.removeItem("crems_act_as");
    setProjectId("");
    qc.clear();
    me.refetch();
  };
  const user = me.data;
  const roles = new Set([user?.role, ...(user?.memberships || []).map((m) => m.project_role)]);
  const has = (...rs) => rs.some((r) => roles.has(r));
  return <Ctx.Provider value={{ me, user, projectId, setProjectId, actAs, has, refreshMe: me.refetch }}>{children}</Ctx.Provider>;
}
