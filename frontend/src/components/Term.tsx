import { useId, useState, type ReactNode } from "react";
import { GLOSSARY } from "../lib/glossary";

/** A term with a dotted underline; hover, focus or tap shows its plain-language meaning. */
export function Term({ k, children }: { k: string; children?: ReactNode }) {
  const entry = GLOSSARY[k];
  const [open, setOpen] = useState(false);
  const id = useId();
  if (!entry) return <>{children ?? k}</>;
  return (
    <span className="relative inline-block">
      <span
        role="button"
        tabIndex={0}
        aria-describedby={open ? id : undefined}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="cursor-help underline decoration-dotted decoration-1 underline-offset-2"
      >
        {children ?? entry.term}
      </span>
      {open && (
        <span
          id={id}
          role="tooltip"
          className="absolute bottom-full left-0 z-30 mb-1.5 w-64 rounded-md border border-line bg-surface p-2.5 text-left text-xs leading-relaxed font-normal tracking-normal text-muted normal-case shadow-lg"
        >
          <span className="mb-0.5 block font-semibold text-fg">{entry.term}</span>
          {entry.text}
        </span>
      )}
    </span>
  );
}
