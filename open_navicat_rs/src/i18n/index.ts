import { createContext, useContext } from "react";
import zh from "./zh.json";
import en from "./en.json";

const dicts: Record<string, Record<string, string>> = { zh, en };

function getDict(lang: string): Record<string, string> {
  return dicts[lang] || dicts.zh;
}

export function t(lang: string, key: string, fallback?: string): string {
  return getDict(lang)[key] || fallback || key;
}

export type Lang = "zh" | "en";

export const I18nCtx = createContext<Lang>("zh");

export function useT() {
  const lang = useContext(I18nCtx);
  return (key: string, fallback?: string) => t(lang, key, fallback);
}
