import { Term } from "../../components/Term";
import { cx } from "../../components/ui/primitives";
import type { ConditionKind, ConditionOp, RuleCondition, StrategyRules } from "../../lib/types";

export const field =
  "h-8 rounded-md border border-line bg-surface-2 px-2 text-sm text-fg placeholder:text-faint focus:border-accent focus:outline-none";

const KINDS: { value: ConditionKind; label: string }[] = [
  { value: "price_vs_sma", label: "Price vs moving average" },
  { value: "sma_cross", label: "Moving average crossover" },
  { value: "rsi", label: "RSI" },
  { value: "return", label: "Return over N days" },
  { value: "from_high", label: "Distance from 52-week high" },
];

const OPS: { value: ConditionOp; label: string }[] = [
  { value: "above", label: "is above" },
  { value: "below", label: "is below" },
  { value: "crosses_above", label: "crosses above" },
  { value: "crosses_below", label: "crosses below" },
];

export const PRESETS: { name: string; about: string; rules: StrategyRules }[] = [
  {
    name: "Buy dips in an uptrend",
    about: "Buy a stock in a long uptrend when it has sold off for a few days; sell when it recovers.",
    rules: {
      entry: [
        { kind: "price_vs_sma", op: "above", n: 200 },
        { kind: "rsi", op: "below", n: 14, value: 35 },
      ],
      exit: [{ kind: "rsi", op: "above", n: 14, value: 65 }],
      stop_loss: 0.08,
      take_profit: null,
      max_days: 60,
    },
  },
  {
    name: "Golden cross",
    about: "Buy when the 50-day average rises through the 200-day average; sell on the reverse cross.",
    rules: {
      entry: [{ kind: "sma_cross", op: "crosses_above", n: 50, m: 200 }],
      exit: [{ kind: "sma_cross", op: "crosses_below", n: 50, m: 200 }],
      stop_loss: null,
      take_profit: null,
      max_days: null,
    },
  },
  {
    name: "Momentum",
    about: "Buy stocks up strongly over six months and above their 50-day average; sell when that trend breaks.",
    rules: {
      entry: [
        { kind: "return", op: "above", n: 126, value: 0.2 },
        { kind: "price_vs_sma", op: "above", n: 50 },
      ],
      exit: [{ kind: "price_vs_sma", op: "crosses_below", n: 50 }],
      stop_loss: 0.1,
      take_profit: null,
      max_days: null,
    },
  },
  {
    name: "52-week high breakout",
    about: "Buy near a one-year high, aiming for a 20% gain with an 8% stop.",
    rules: {
      entry: [{ kind: "from_high", op: "above", n: 252, value: 0.02 }],
      exit: [],
      stop_loss: 0.08,
      take_profit: 0.2,
      max_days: 120,
    },
  },
];

function defaults(kind: ConditionKind): RuleCondition {
  switch (kind) {
    case "price_vs_sma":
      return { kind, op: "above", n: 200 };
    case "sma_cross":
      return { kind, op: "crosses_above", n: 50, m: 200 };
    case "rsi":
      return { kind, op: "below", n: 14, value: 30 };
    case "return":
      return { kind, op: "above", n: 20, value: 0.1 };
    case "from_high":
      return { kind, op: "below", n: 252, value: 0.2 };
  }
}

function NumberBox({
  value,
  onChange,
  label,
  min = 1,
  max = 250,
  step = 1,
  width = "w-16",
}: {
  value: number | null | undefined;
  onChange: (v: number) => void;
  label: string;
  min?: number;
  max?: number;
  step?: number;
  width?: string;
}) {
  return (
    <input
      type="number"
      aria-label={label}
      title={label}
      min={min}
      max={max}
      step={step}
      value={value ?? ""}
      onChange={(e) => onChange(Number(e.target.value))}
      className={cx(field, width)}
    />
  );
}

function ConditionRow({
  c,
  onChange,
  onRemove,
}: {
  c: RuleCondition;
  onChange: (c: RuleCondition) => void;
  onRemove?: () => void;
}) {
  const ops = c.kind === "from_high" ? OPS.slice(0, 2) : OPS;
  const pctValue = c.kind === "return" || c.kind === "from_high";
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
      <select
        value={c.kind}
        onChange={(e) => onChange(defaults(e.target.value as ConditionKind))}
        className={cx(field, "w-52")}
        aria-label="Condition"
      >
        {KINDS.map((k) => (
          <option key={k.value} value={k.value}>
            {k.label}
          </option>
        ))}
      </select>
      {c.kind === "price_vs_sma" && (
        <>
          <span>price</span>
          <select
            value={c.op}
            onChange={(e) => onChange({ ...c, op: e.target.value as ConditionOp })}
            className={field}
          >
            {ops.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <span>its</span>
          <NumberBox label="Days" value={c.n} onChange={(n) => onChange({ ...c, n })} />
          <span>
            -day <Term k="moving average">average</Term>
          </span>
        </>
      )}
      {c.kind === "sma_cross" && (
        <>
          <NumberBox label="Fast average days" value={c.n} onChange={(n) => onChange({ ...c, n })} />
          <span>-day average</span>
          <select
            value={c.op}
            onChange={(e) => onChange({ ...c, op: e.target.value as ConditionOp })}
            className={field}
          >
            {ops.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <span>the</span>
          <NumberBox label="Slow average days" value={c.m} onChange={(m) => onChange({ ...c, m })} />
          <span>-day average</span>
        </>
      )}
      {c.kind === "rsi" && (
        <>
          <span>
            <Term k="RSI">RSI</Term> (
          </span>
          <NumberBox label="RSI days" value={c.n} onChange={(n) => onChange({ ...c, n })} width="w-14" />
          <span>)</span>
          <select
            value={c.op}
            onChange={(e) => onChange({ ...c, op: e.target.value as ConditionOp })}
            className={field}
          >
            {ops.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <NumberBox
            label="RSI level"
            value={c.value}
            min={1}
            max={99}
            onChange={(value) => onChange({ ...c, value })}
          />
        </>
      )}
      {c.kind === "return" && (
        <>
          <NumberBox label="Days" value={c.n} onChange={(n) => onChange({ ...c, n })} />
          <span>-day return</span>
          <select
            value={c.op}
            onChange={(e) => onChange({ ...c, op: e.target.value as ConditionOp })}
            className={field}
          >
            {ops.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </>
      )}
      {c.kind === "from_high" && (
        <>
          <span>price is</span>
          <select
            value={c.op}
            onChange={(e) => onChange({ ...c, op: e.target.value as ConditionOp })}
            className={field}
          >
            <option value="below">at least</option>
            <option value="above">within</option>
          </select>
        </>
      )}
      {pctValue && (
        <>
          <NumberBox
            label="Percent"
            value={c.value != null ? Math.round(c.value * 1000) / 10 : null}
            min={-100}
            max={1000}
            step={0.5}
            onChange={(v) => onChange({ ...c, value: v / 100 })}
          />
          <span>%</span>
          {c.kind === "from_high" && (
            <span>
              {c.op === "below" ? "below" : "of"} its <Term k="52-week high">52-week high</Term>
            </span>
          )}
        </>
      )}
      {onRemove && (
        <button type="button" onClick={onRemove} className="ml-1 text-faint hover:text-down" aria-label="Remove">
          ✕
        </button>
      )}
    </div>
  );
}

function ConditionList({
  title,
  items,
  onChange,
  min,
}: {
  title: string;
  items: RuleCondition[];
  onChange: (items: RuleCondition[]) => void;
  min: number;
}) {
  return (
    <div className="flex flex-col gap-2">
      <h3 className="text-2xs font-semibold tracking-wide text-faint uppercase">{title}</h3>
      {items.map((c, i) => (
        <ConditionRow
          key={i}
          c={c}
          onChange={(nc) => onChange(items.map((x, j) => (j === i ? nc : x)))}
          onRemove={items.length > min ? () => onChange(items.filter((_, j) => j !== i)) : undefined}
        />
      ))}
      {items.length < 4 && (
        <button
          type="button"
          onClick={() => onChange([...items, defaults("rsi")])}
          className="self-start text-xs text-accent hover:underline"
        >
          + Add condition
        </button>
      )}
    </div>
  );
}

function PctInput({
  label,
  value,
  onChange,
  term,
}: {
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
  term?: string;
}) {
  return (
    <label className="flex flex-col gap-1 text-2xs text-faint">
      {term ? <Term k={term}>{label}</Term> : label}
      <input
        type="number"
        min={0}
        step={0.5}
        value={value != null ? Math.round(value * 1000) / 10 : ""}
        placeholder="off"
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value) / 100)}
        className={cx(field, "w-24")}
      />
    </label>
  );
}

export function RuleBuilder({ rules, onChange }: { rules: StrategyRules; onChange: (r: StrategyRules) => void }) {
  return (
    <div className="flex flex-col gap-4">
      <ConditionList
        title="Buy when all of these are true (checked at the close)"
        items={rules.entry}
        min={1}
        onChange={(entry) => onChange({ ...rules, entry })}
      />
      <ConditionList
        title="Sell when any of these is true"
        items={rules.exit}
        min={0}
        onChange={(exit) => onChange({ ...rules, exit })}
      />
      <div className="flex flex-wrap gap-4">
        <PctInput
          label="Stop-loss %"
          term="stop-loss"
          value={rules.stop_loss}
          onChange={(stop_loss) => onChange({ ...rules, stop_loss })}
        />
        <PctInput
          label="Target %"
          term="target"
          value={rules.take_profit}
          onChange={(take_profit) => onChange({ ...rules, take_profit })}
        />
        <label className="flex flex-col gap-1 text-2xs text-faint">
          Sell after (days)
          <input
            type="number"
            min={1}
            value={rules.max_days ?? ""}
            placeholder="off"
            onChange={(e) => onChange({ ...rules, max_days: e.target.value === "" ? null : Number(e.target.value) })}
            className={cx(field, "w-24")}
          />
        </label>
      </div>
    </div>
  );
}
