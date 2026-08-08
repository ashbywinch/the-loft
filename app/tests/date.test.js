import { describe, expect, it } from "vitest";
import { ageInYears, dateLabel, daysFrom, monthDayDistance, sortByDate, yearOf } from "../date.js";

const exact = { date: "1963-05-14", date_precision: "exact" };
const month = { date: "1971-05-16", date_precision: "month" };
const year = { date: "1980", date_precision: "year" };
const approx = { date: "1972", date_precision: "approx" };

describe("dateLabel honours precision", () => {
  it('exact dates read as "14 May 1963"', () => {
    expect(dateLabel(exact)).toBe("14 May 1963");
  });
  it('month precision reads as "May 1971"', () => {
    expect(dateLabel(month)).toBe("May 1971");
  });
  it("year precision reads as the year", () => {
    expect(dateLabel(year)).toBe("1980");
  });
  it('approximate reads as "circa 1972"', () => {
    expect(dateLabel(approx)).toBe("circa 1972");
  });
});

describe("daysFrom", () => {
  it("computes signed day distance from a reference date", () => {
    expect(daysFrom(exact, new Date(1963, 4, 15))).toBe(-1);
    expect(daysFrom(exact, new Date(1963, 4, 14))).toBe(0);
    expect(daysFrom(exact, new Date(1963, 4, 13))).toBe(1);
  });
  it("returns null for non-exact precision", () => {
    expect(daysFrom(month, new Date())).toBeNull();
  });
});

describe("monthDayDistance — on-this-day matching across years", () => {
  it("measures the same calendar day as zero regardless of the year gap", () => {
    // 14 May 1963 vs 14 May 2026: same month/day -> 0, even though 63 years apart
    expect(monthDayDistance(exact, new Date(2026, 4, 14))).toBe(0);
    expect(monthDayDistance(exact, new Date(2026, 4, 15))).toBe(-1);
    expect(monthDayDistance(exact, new Date(2026, 4, 13))).toBe(1);
  });
  it("wraps around the year boundary", () => {
    const newYear = { date: "1977-01-02", date_precision: "exact" };
    expect(monthDayDistance(newYear, new Date(2026, 11, 30))).toBe(3); // Jan 2 is 3 days after Dec 30
  });
  it("wraps by the reference year length so leap years stay exact", () => {
    const newYear = { date: "1977-01-01", date_precision: "exact" };
    // 31 Dec 2028 is a leap year: Jan 1 is 1 day away, not "today"
    expect(monthDayDistance(newYear, new Date(2028, 11, 31))).toBe(1);
    expect(monthDayDistance(newYear, new Date(2026, 11, 31))).toBe(1);
  });
  it("returns null for non-exact precision", () => {
    expect(monthDayDistance(month, new Date())).toBeNull();
  });
  it("handles leap-day items only in leap years", () => {
    const leap = { date: "1976-02-29", date_precision: "exact" };
    expect(monthDayDistance(leap, new Date(2026, 0, 1))).toBeNull(); // 2026 is not a leap year
    expect(monthDayDistance(leap, new Date(2028, 1, 29))).toBe(0); // leap year, same day
  });
});

describe("sorting and years", () => {
  it("yearOf extracts the year", () => {
    expect(yearOf(exact)).toBe(1963);
  });
  it("sortByDate orders by ISO date", () => {
    const sorted = sortByDate([year, exact, month]);
    expect(sorted.map((i) => i.date)).toEqual(["1963-05-14", "1971-05-16", "1980"]);
  });
});

describe("dateLabel bound precisions (2026-08-06)", () => {
  it("labels before/after/between honestly", () => {
    expect(dateLabel({ date: "1917", date_precision: "after" })).toBe("after 1917");
    expect(dateLabel({ date: "1881", date_precision: "before" })).toBe("before 1881");
    expect(dateLabel({ date: "1880", date2: "1881", date_precision: "between" })).toBe("between 1880 and 1881");
  });
});

describe("ageInYears — calculated, never stored (2026-08-06)", () => {
  it("computes the exact age from exact dates, handling a 29-Feb birth", () => {
    expect(ageInYears({ date: "1896-02-29", precision: "exact" }, { date: "1982-05-16", precision: "exact" })).toEqual({ exact: 86 });
    expect(ageInYears({ date: "1896-02-29", precision: "exact" }, { date: "1900-02-28", precision: "exact" })).toEqual({ exact: 3 });
    expect(ageInYears({ date: "1896-02-29", precision: "exact" }, { date: "1900-03-01", precision: "exact" })).toEqual({ exact: 4 });
  });

  it("gives the honest range when either date is not exact", () => {
    expect(ageInYears({ date: "1892", precision: "year" }, { date: "1980", precision: "year" })).toEqual({ from: 87, to: 88 });
    expect(ageInYears({ date: "1896-02-29", precision: "exact" }, { date: "1980-05", precision: "month" })).toEqual({ from: 83, to: 84 });
  });

  it("returns null when a date is missing or not point-placed", () => {
    expect(ageInYears(null, { date: "1980", precision: "year" })).toBeNull();
    expect(ageInYears({ date: "1892", precision: "year" }, { date: "1917", precision: "after" })).toBeNull();
  });
});
