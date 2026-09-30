"use client";
import { createContext, createElement, useCallback, useContext, useMemo, type ReactNode } from "react";
import { ko } from "./locales/ko";
import { en } from "./locales/en";

export type Locale = "ko" | "en";
export type Dict = Record<string, string>;
const dicts: Record<Locale, Dict> = { ko, en };

export function translate(locale: Locale, key: string, vars?: Record<string, string | number>): string {
  let s = dicts[locale][key] ?? dicts.ko[key] ?? key;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, String(v));
  return s;
}

interface Ctx { locale: Locale; setLocale?: (l: Locale) => void }
const LocaleCtx = createContext<Ctx>({ locale: "ko" });

export function LocaleProvider({ locale, setLocale, children }: { locale: Locale; setLocale?: (l: Locale) => void; children: ReactNode }) {
  const v = useMemo(() => ({ locale, setLocale }), [locale, setLocale]);
  return createElement(LocaleCtx.Provider, { value: v }, children);
}

export function useLocale(): Locale { return useContext(LocaleCtx).locale; }
export function useSetLocale() { return useContext(LocaleCtx).setLocale; }

export type TFn = (key: string, vars?: Record<string, string | number>) => string;
export function useT(): TFn {
  const { locale } = useContext(LocaleCtx);
  return useCallback((key: string, vars?: Record<string, string | number>) => translate(locale, key, vars), [locale]);
}
