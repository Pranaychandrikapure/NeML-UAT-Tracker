import axios from "axios";
import { toast } from "sonner";

export const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
export const api = axios.create({ baseURL: API });

api.interceptors.request.use(async (cfg) => {
  const token = await window.Clerk?.session?.getToken();
  if (token) cfg.headers.Authorization = `Bearer ${token}`;
  const actAs = localStorage.getItem("crems_act_as");
  if (actAs) cfg.headers["X-Act-As"] = actAs;
  return cfg;
});

export const errMsg = (e) => {
  const d = e?.response?.data?.detail;
  if (Array.isArray(d)) return d.map((x) => `${x.loc?.slice(-1)[0]}: ${x.msg}`).join(", ");
  return d || e?.message || "Something went wrong";
};

export const get = async (url, params) => (await api.get(url, { params })).data;

export async function act(fn, success) {
  try {
    const r = await fn();
    if (success) toast.success(success);
    return r;
  } catch (e) {
    toast.error(errMsg(e));
    throw e;
  }
}

export async function download(url, filename) {
  const r = await api.get(url, { responseType: "blob" });
  const href = URL.createObjectURL(r.data);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(href);
}
