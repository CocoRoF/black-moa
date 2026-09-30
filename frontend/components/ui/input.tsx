"use client";
import { Children, forwardRef, isValidElement, useMemo, useState, type InputHTMLAttributes, type ReactElement, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { Selector, type SelectorGroup, type SelectorItems, type SelectorOption } from "@cocorof/react-selector";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

//: 고른 칸의 테두리 색은 **칸 안쪽**에 그린다.
//:
//: 밖으로 그리면 위아래에 여백이 없는 자리에서 바로 윗줄과 겹치고, 스크롤되는
//: 상자 안에서는 그 선이 잘려 나간다. 안쪽에 그리면 어디에 놓아도 제자리에 있다.
const base = "w-full rounded-xl border border-border bg-input px-3.5 text-fg placeholder:text-muted-fg/70 focus-visible:outline-none focus-visible:border-accent focus-visible:shadow-[inset_0_0_0_1px_var(--accent)] disabled:opacity-50 transition-colors";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }>(function Input({ className, invalid, ...p }, ref) {
  return <input ref={ref} aria-invalid={invalid || undefined} className={cn(base, "h-10 text-[15px]", invalid && "border-danger", className)} {...p} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }>(function Textarea({ className, invalid, ...p }, ref) {
  return <textarea ref={ref} aria-invalid={invalid || undefined} className={cn(base, "min-h-[96px] py-2.5 text-[15px] leading-relaxed resize-y", invalid && "border-danger", className)} {...p} />;
});

/** Reads the `<option>` children a native select would have had.
 *
 *  Keeping that call shape is deliberate: it is what let every existing select switch to
 *  the themed control at once, instead of thirty hand edits that would each have to be
 *  reviewed. Nested <optgroup> becomes a group; anything else is ignored. */
function readOptions(children: ReactNode): SelectorItems {
  const flat: SelectorOption[] = [];
  const groups: SelectorGroup[] = [];
  Children.forEach(children, (child) => {
    if (!isValidElement(child)) return;
    const el = child as ReactElement<{ value?: string; children?: ReactNode; disabled?: boolean; label?: string }>;
    if (el.type === "option") {
      flat.push({ value: String(el.props.value ?? ""), label: el.props.children as ReactNode, disabled: el.props.disabled });
    } else if (el.type === "optgroup") {
      const inner = readOptions(el.props.children);
      groups.push({ label: el.props.label ?? "", options: Array.isArray(inner) && !("options" in (inner[0] ?? {})) ? (inner as SelectorOption[]) : [] });
    }
  });
  return groups.length ? groups : flat;
}

/** The app's select. A themed listbox rather than the browser's own: a native dropdown
 *  paints itself from the OS scheme, so an app in light mode on a dark desktop opened a
 *  black menu over a white page — and it could not show counts, hints or a search box. */
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement> & {
  /** For lists that cannot be written as <option> children — a rich label, search keywords.
   *  Same control either way, so every select in a form is the same width and height. */
  options?: SelectorItems;
  searchThreshold?: number;
}>(function Select(
  { className, children, value, defaultValue, onChange, disabled, name, id, "aria-label": ariaLabel,
    options: given, searchThreshold, ...p }, _ref) {
  const t = useT();
  const fromChildren = useMemo(() => readOptions(children), [children]);
  const options = given ?? fromChildren;
  const [inner, setInner] = useState(String(defaultValue ?? ""));
  const current = value !== undefined ? String(value) : inner;
  const emit = (next: string) => {
    if (value === undefined) setInner(next);
    // The call sites were written against a change event, so one is handed back to them.
    onChange?.({ target: { value: next, name: name ?? "" }, currentTarget: { value: next, name: name ?? "" } } as never);
  };
  return (
    <Selector
      className={cn("rsel-app w-full", className)} id={id} name={name} ariaLabel={ariaLabel}
      value={current} onChange={(v) => emit(String(v))} options={options} disabled={disabled}
      searchThreshold={searchThreshold ?? 10} size="lg" placeholder={(p as { placeholder?: string }).placeholder ?? ""}
      labels={{ search: t("common.search"), empty: t("common.no_results") }}
    />
  );
});

export function Label({ children, htmlFor, className, hint }: { children: ReactNode; htmlFor?: string; className?: string; hint?: ReactNode }) {
  return (
    <label htmlFor={htmlFor} className={cn("block text-sm font-medium text-fg mb-1.5", className)}>
      {children}{hint ? <span className="ml-1.5 font-normal text-muted-fg text-xs">{hint}</span> : null}
    </label>
  );
}

export function Field({ label, htmlFor, error, hint, children, className }: { label?: ReactNode; htmlFor?: string; error?: string | null; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={cn("space-y-0", className)}>
      {label ? <Label htmlFor={htmlFor}>{label}</Label> : null}
      {children}
      {error ? <p role="alert" className="mt-1.5 text-xs text-danger">{error}</p> : hint ? <p className="mt-1.5 text-xs text-muted-fg">{hint}</p> : null}
    </div>
  );
}

export function Checkbox({ checked, onChange, label, disabled, className }: { checked: boolean; onChange: (v: boolean) => void; label?: ReactNode; disabled?: boolean; className?: string }) {
  return (
    <label className={cn("inline-flex items-center gap-2.5 cursor-pointer select-none min-h-[36px] md:min-h-0 text-sm", disabled && "opacity-50 cursor-not-allowed", className)}>
      <input type="checkbox" className="h-[18px] w-[18px] rounded accent-[var(--accent)]" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      {label ? <span>{label}</span> : null}
    </label>
  );
}
