/** NSE regular session timing in IST, for countdowns. Exchange holidays are not known here,
 * so a countdown names the next regular weekday session. */

const OPEN_MIN = 9 * 60 + 15;
const CLOSE_MIN = 15 * 60 + 30;
const PRE_OPEN_MIN = 9 * 60;

function istParts(now: Date): { day: number; minutes: number; seconds: number } {
  const ist = new Date(now.getTime() + (330 + now.getTimezoneOffset()) * 60_000);
  return { day: ist.getDay(), minutes: ist.getHours() * 60 + ist.getMinutes(), seconds: ist.getSeconds() };
}

function span(totalMinutes: number): string {
  const d = Math.floor(totalMinutes / 1440);
  const h = Math.floor((totalMinutes % 1440) / 60);
  const m = Math.floor(totalMinutes % 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  return `${Math.max(1, m)}m`;
}

export interface SessionClock {
  phase: "open" | "pre_open" | "closed";
  label: string; // "Closes in 2h 10m"
  progress: number | null; // share of today's session elapsed, while open
}

export function sessionClock(now: Date, state?: "open" | "pre_open" | "closed"): SessionClock {
  const { day, minutes, seconds } = istParts(now);
  const t = minutes + seconds / 60;
  const weekday = day >= 1 && day <= 5;
  if (state === "open" || (state === undefined && weekday && t >= OPEN_MIN && t < CLOSE_MIN)) {
    return {
      phase: "open",
      label: `Closes in ${span(Math.max(0, CLOSE_MIN - t))}`,
      progress: Math.min(1, Math.max(0, (t - OPEN_MIN) / (CLOSE_MIN - OPEN_MIN))),
    };
  }
  if (state === "pre_open" || (weekday && t >= PRE_OPEN_MIN && t < OPEN_MIN)) {
    return { phase: "pre_open", label: `Pre-open · opens in ${span(OPEN_MIN - t)}`, progress: null };
  }
  // Minutes until the next weekday 09:15.
  let wait = weekday && t < OPEN_MIN ? OPEN_MIN - t : 1440 - t + OPEN_MIN;
  let d = (day + (weekday && t < OPEN_MIN ? 0 : 1)) % 7;
  while (d === 0 || d === 6) {
    wait += 1440;
    d = (d + 1) % 7;
  }
  return { phase: "closed", label: `Opens in ${span(wait)}`, progress: null };
}

export function greeting(now: Date): string {
  const h = Math.floor(istParts(now).minutes / 60);
  if (h < 5) return "Up late";
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}
