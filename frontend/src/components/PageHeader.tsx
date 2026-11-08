import type { ComponentType, CSSProperties, ReactNode, SVGProps } from "react";
import {
  IconBook,
  IconBriefcase,
  IconDashboard,
  IconFlask,
  IconMarkets,
  IconPortfolio,
  IconResearch,
  IconRocket,
  IconWatchlist,
} from "./ui/icons";
import { cx } from "./ui/primitives";

export type Section =
  "dashboard" | "markets" | "watchlist" | "portfolios" | "lab" | "ipos" | "research" | "planner" | "learn";

export const SECTION_ICON: Record<Section, ComponentType<SVGProps<SVGSVGElement>>> = {
  dashboard: IconDashboard,
  markets: IconMarkets,
  watchlist: IconWatchlist,
  portfolios: IconBriefcase,
  lab: IconFlask,
  ipos: IconRocket,
  research: IconResearch,
  planner: IconPortfolio,
  learn: IconBook,
};

/** CSS custom property carrying a section's colour, for any element inside it. */
export const secStyle = (s: Section) => ({ "--sec": `var(--sec-${s})` }) as CSSProperties;

export function SectionTile({ section, size = 40 }: { section: Section; size?: number }) {
  const Icon = SECTION_ICON[section];
  return (
    <span
      className="fc-sec-tile inline-flex shrink-0 items-center justify-center rounded-xl"
      style={{ ...secStyle(section), width: size, height: size }}
      aria-hidden
    >
      <Icon width={size * 0.48} height={size * 0.48} />
    </span>
  );
}

/** The top of every page: what it is, in one line, with its own colour and any actions. */
export function PageHeader({
  section,
  title,
  subtitle,
  eyebrow,
  children,
  className,
}: {
  section: Section;
  title: ReactNode;
  subtitle?: ReactNode;
  eyebrow?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cx("fc-panel relative flex flex-wrap items-center gap-x-4 gap-y-3 py-1", className)}
      style={secStyle(section)}
    >
      <SectionTile section={section} size={44} />
      <div className="min-w-0 flex-1">
        {eyebrow && <div className="fc-sec-text text-2xs font-semibold tracking-wider uppercase">{eyebrow}</div>}
        <h1 className="text-xl leading-tight font-semibold tracking-tight text-fg">{title}</h1>
        {subtitle && <p className="mt-0.5 max-w-3xl text-xs leading-relaxed text-muted">{subtitle}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </header>
  );
}

/** A small labelled figure for page headers: "Return +2.4%". */
export function HeaderStat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-surface/70 px-3 py-1.5">
      <div className="text-2xs tracking-wide text-faint uppercase">{label}</div>
      <div className="num text-sm font-semibold text-fg">{children}</div>
    </div>
  );
}
