import { useState } from "react";
import { FormDialog, Field, Inp, Txt, Sel } from "./common";

// prompt = { title, description, fields: [{key,label,type,options,required}], submitLabel, onSubmit(values) }
export function PromptDialog({ prompt, onClose }) {
  const [v, setV] = useState(() => Object.fromEntries((prompt?.fields || []).map((f) => [f.key, f.default ?? ""])));
  if (!prompt) return null;
  return (
    <FormDialog open onOpenChange={(o) => !o && onClose()} title={prompt.title} description={prompt.description} submitLabel={prompt.submitLabel || "Confirm"}
      testid="prompt-dialog" onSubmit={() => prompt.onSubmit(v)}>
      {prompt.fields.map((f) => (
        <Field key={f.key} label={f.label + (f.required ? " *" : "")}>
          {f.type === "textarea" ? <Txt required={f.required} data-testid={`prompt-${f.key}`} value={v[f.key]} onChange={(e) => setV({ ...v, [f.key]: e.target.value })} />
            : f.type === "select" ? <Sel required={f.required} data-testid={`prompt-${f.key}`} value={v[f.key]} onChange={(e) => setV({ ...v, [f.key]: e.target.value })} options={f.options} placeholder="Select…" />
              : <Inp required={f.required} type={f.type || "text"} data-testid={`prompt-${f.key}`} value={v[f.key]} onChange={(e) => setV({ ...v, [f.key]: e.target.value })} />}
        </Field>
      ))}
    </FormDialog>
  );
}

export function usePrompt() {
  const [prompt, setPrompt] = useState(null);
  const el = prompt ? <PromptDialog key={prompt.title} prompt={prompt} onClose={() => setPrompt(null)} /> : null;
  return [setPrompt, el];
}
