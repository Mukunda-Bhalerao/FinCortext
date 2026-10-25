import { useState } from "react";

/** useState that remembers a UI preference in localStorage when available. */
export function useStoredState<T extends string>(key: string, initial: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      return (localStorage.getItem(key) as T | null) ?? initial;
    } catch {
      return initial;
    }
  });
  const set = (v: T) => {
    setValue(v);
    try {
      localStorage.setItem(key, v);
    } catch {
      /* preference not persisted */
    }
  };
  return [value, set];
}
