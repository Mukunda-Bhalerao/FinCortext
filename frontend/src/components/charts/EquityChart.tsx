import {
  ColorType,
  createChart,
  LineSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

export interface EquityLine {
  label: string;
  points: { time: number; value: number }[];
  tone: "accent" | "muted" | "faint";
  dashed?: boolean;
}

const TONE = { accent: "--accent", muted: "--text-muted", faint: "--text-faint" } as const;

function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

const fmt = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 1,
  minimumFractionDigits: 1,
});

/** Growth of 100 for a strategy and its benchmark. Point times are UTC midnight of the session date. */
export function EquityChart({ lines, height = 260 }: { lines: EquityLine[]; height?: number }) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Line">[]>([]);
  const tones = useRef<EquityLine["tone"][]>([]);

  useEffect(() => {
    if (!el.current) return;
    const c = createChart(el.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: token("--text-muted"),
        fontFamily: getComputedStyle(document.body).fontFamily,
        fontSize: 11,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: token("--chart-grid") },
        horzLines: { color: token("--chart-grid") },
      },
      rightPriceScale: { borderColor: token("--border") },
      timeScale: { borderColor: token("--border") },
      localization: { priceFormatter: (v: number) => fmt.format(v) },
      handleScroll: false,
      handleScale: false,
    });
    chart.current = c;
    const observer = new MutationObserver(() => {
      c.applyOptions({
        layout: { textColor: token("--text-muted") },
        grid: {
          vertLines: { color: token("--chart-grid") },
          horzLines: { color: token("--chart-grid") },
        },
      });
      series.current.forEach((s, i) => s.applyOptions({ color: token(TONE[tones.current[i] ?? "faint"]) }));
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    return () => {
      observer.disconnect();
      c.remove();
      chart.current = null;
      series.current = [];
    };
  }, []);

  useEffect(() => {
    const c = chart.current;
    if (!c) return;
    series.current.forEach((s) => c.removeSeries(s));
    tones.current = lines.map((l) => l.tone);
    series.current = lines.map((line) => {
      const s = c.addSeries(LineSeries, {
        color: token(TONE[line.tone]),
        lineWidth: line.tone === "accent" ? 2 : 1,
        lineStyle: line.dashed ? LineStyle.Dashed : LineStyle.Solid,
        priceLineVisible: false,
        lastValueVisible: true,
        title: line.label,
      });
      s.setData(
        line.points.map((p) => ({
          time: p.time as UTCTimestamp,
          value: p.value * 100,
        })),
      );
      return s;
    });
    c.timeScale().fitContent();
  }, [lines]);

  return <div ref={el} style={{ height }} className="w-full" />;
}
