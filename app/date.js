/**
 * Date helpers — pure functions, fully unit-tested.
 * Every date carries a precision (PRD §6): exact | month | year | approx.
 */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const FULL_MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

export function yearOf(item) {
  return Number.parseInt(item.date.slice(0, 4), 10);
}

export function monthIndex(item) {
  return Number.parseInt(item.date.slice(5, 7), 10) - 1;
}

export function dayOf(item) {
  return Number.parseInt(item.date.slice(8, 10), 10);
}

/** The age in years between two dated facts ({date, precision, date2}) —
 *  calculated at render, never stored. Exact dates give the exact age (a
 *  29-Feb birthday rolls over on 1 Mar in common years); anything coarser
 *  gives the honest possible range. Null when a date is missing or not
 *  point-placed ("after 1917" has no age) (2026-08-06). */
export function ageInYears(birth, death) {
  if (!birth || !death) return null;
  const yb = yearOf({ date: birth.date });
  const yd = yearOf({ date: death.date });
  if (!Number.isFinite(yb) || !Number.isFinite(yd)) return null;
  if (birth.precision !== "exact" || death.precision !== "exact") {
    if (birth.precision === "after" || birth.precision === "before" || birth.precision === "between") return null;
    if (death.precision === "after" || death.precision === "before" || death.precision === "between") return null;
    return { from: yd - yb - 1, to: yd - yb };
  }
  const [by, bm, bd] = birth.date.split("-").map(Number);
  const [dy, dm, dd] = death.date.split("-").map(Number);
  let age = dy - by;
  if (dm < bm || (dm === bm && dd < bd)) age -= 1;
  return { exact: age };
}

/** Human label honouring precision: "14 May 1963" / "May 1963" / "1963" / "circa 1963". */
export function dateLabel(item) {  const year = yearOf(item);
  switch (item.date_precision) {
    case "exact":
      return `${dayOf(item)} ${MONTHS[monthIndex(item)]} ${year}`;
    case "month":
      return `${FULL_MONTHS[monthIndex(item)]} ${year}`;
    case "approx":
      return `circa ${year}`;
    case "before":
      return `before ${year}`;
    case "after":
      return `after ${year}`;
    case "between":
      return `between ${year} and ${item.date2 ? yearOf({ date: item.date2 }) : "?"}`;
    default:
      return String(year);
  }
}

/** Days between an exact date and a reference date (signed). */
export function daysFrom(item, reference) {
  if (item.date_precision !== "exact") return null;
  const [y, m, d] = item.date.split("-").map(Number);
  const at = new Date(y, m - 1, d);
  const ref = new Date(reference.getFullYear(), reference.getMonth(), reference.getDate());
  return Math.round((at - ref) / 86_400_000);
}

/**
 * Signed day distance from an item's month/day to a reference date's
 * month/day, in the reference's year — with wrap-around (Dec 30 vs Jan 2 is 3
 * days). Used by the on-this-day moment (PRD §9 F1). Returns null for
 * non-exact precision.
 */
export function monthDayDistance(item, reference) {
  if (item.date_precision !== "exact") return null;
  const year = reference.getFullYear();
  const month = monthIndex(item);
  const day = dayOf(item);
  // 29 Feb only exists in leap years — otherwise Date rolls silently to 1 Mar
  if (month === 1 && day === 29 && !isLeapYear(year)) return null;
  const at = new Date(year, month, day);
  const ref = new Date(year, reference.getMonth(), reference.getDate());
  let raw = Math.round((at - ref) / 86_400_000);
  // Wrap by the reference year's actual length: 365 vs 366 keeps the
  // year-boundary distance exact in leap years (Dec 31 leap -> Jan 1 is 1).
  const yearDays = isLeapYear(year) ? 366 : 365;
  if (raw > 183) raw -= yearDays;
  if (raw < -183) raw += yearDays;
  return raw;
}

function isLeapYear(year) {
  return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
}

export function sortByDate(items) {
  return [...items].sort((a, b) => a.date.localeCompare(b.date));
}

/** Recently added, not recently dated: the archive's own recorded/created
 *  stamp decides the "recent" feed — a story about 1963 recorded today is
 *  recent (user, 2026-08-03). created_at (full timestamp) breaks the tie
 *  between the stories added on the same day. */
export function sortByRecorded(items) {
  const stamp = (item) => item.created_at ?? item.recorded ?? item.created ?? item.date;
  return [...items].sort((a, b) => stamp(b).localeCompare(stamp(a)));
}
