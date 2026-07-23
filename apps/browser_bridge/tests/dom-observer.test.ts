// @vitest-environment jsdom

import { afterEach, describe, expect, it } from "vitest";
import {
  MultiQuoteObserver,
  findQuoteTargets,
  readQuote,
  type VisibleQuote,
} from "../src/dom-observer";

type Row = [symbol: string, bid: string, ask: string, last?: string];

const FOUR_ROWS: Row[] = [
  ["EURUSD", "1.13743", "1.13744", "1.13740"],
  ["GBPUSD", "1.33155", "1.33157", "1.33150"],
  ["USDJPY", "163.832", "163.833", "163.800"],
  ["AUDUSD", "0.69689", "0.69690", "0.69680"],
];

function table(
  rows: Row[],
  headers = ["Symbol", "Bid", "Ask", "Last"],
  attributes = "",
): string {
  const values = (row: Row): Record<string, string> => ({
    Symbol: row[0],
    Bid: row[1],
    Ask: row[2],
    Last: row[3] ?? row[1],
    High: "999.99999",
    Low: "0.00001",
    "Daily Change": "-0.3%",
  });
  return `
    <table ${attributes}>
      <thead><tr>${headers.map((value) => `<th>${value}</th>`).join("")}</tr></thead>
      <tbody>
        ${rows
          .map(
            (row) =>
              `<tr data-symbol="${row[0]}">${headers
                .map((header) => `<td>${values(row)[header] ?? ""}</td>`)
                .join("")}</tr>`,
          )
          .join("")}
      </tbody>
    </table>
  `;
}

function discoveredQuotes(): Record<string, VisibleQuote | null> {
  return Object.fromEntries(
    Object.entries(findQuoteTargets()).map(([instrument, result]) => [
      instrument,
      result.target ? readQuote(result.target) : null,
    ]),
  );
}

async function reacquire(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 150));
}

afterEach(() => {
  document.body.replaceChildren();
});

describe("four-pair targeted market-watch observer", () => {
  it("finds four valid rows and uses exact headers despite extra decimal columns", () => {
    document.body.innerHTML = table(FOUR_ROWS, [
      "High",
      "Ask",
      "Symbol",
      "Last",
      "Bid",
      "Low",
    ]);
    expect(discoveredQuotes()).toEqual({
      EURUSD: { instrument: "EURUSD", bid: "1.13743", ask: "1.13744" },
      GBPUSD: { instrument: "GBPUSD", bid: "1.33155", ask: "1.33157" },
      USDJPY: { instrument: "USDJPY", bid: "163.832", ask: "163.833" },
      AUDUSD: { instrument: "AUDUSD", bid: "0.69689", ask: "0.69690" },
    });
  });

  it("supports reordered rows and columns", () => {
    document.body.innerHTML = table(
      [...FOUR_ROWS].reverse(),
      ["Ask", "Daily Change", "Symbol", "Bid"],
    );
    expect(Object.values(discoveredQuotes()).every((quote) => quote !== null)).toBe(true);
  });

  it("ignores hidden and responsive duplicates", () => {
    document.body.innerHTML = [
      table(FOUR_ROWS),
      table(
        FOUR_ROWS.map(([symbol]) => [symbol, "1.00000", "2.00000"]),
        undefined,
        "aria-hidden='true'",
      ),
      table(FOUR_ROWS, undefined, "style='display:none'"),
    ].join("");
    expect(findQuoteTargets().EURUSD.status).toBe("FOUND");
    expect(findQuoteTargets().USDJPY.status).toBe("FOUND");
  });

  it("accepts identical visible duplicates", () => {
    document.body.innerHTML = table(FOUR_ROWS) + table(FOUR_ROWS);
    expect(Object.values(findQuoteTargets()).every(({ status }) => status === "FOUND")).toBe(
      true,
    );
  });

  it("isolates a conflicting duplicate to the affected pair", () => {
    document.body.innerHTML =
      table(FOUR_ROWS) + table([["GBPUSD", "1.40000", "1.40001"]]);
    const results = findQuoteTargets();
    expect(results.GBPUSD.status).toBe("AMBIGUOUS");
    expect(results.EURUSD.status).toBe("FOUND");
    expect(results.USDJPY.status).toBe("FOUND");
    expect(results.AUDUSD.status).toBe("FOUND");
  });

  it("isolates one missing or malformed pair", () => {
    document.body.innerHTML = table([
      FOUR_ROWS[0]!,
      ["GBPUSD", "not-a-price", "1.33157"],
      FOUR_ROWS[2]!,
    ]);
    const results = findQuoteTargets();
    expect(results.GBPUSD.status).toBe("MISSING");
    expect(results.AUDUSD.status).toBe("MISSING");
    expect(results.EURUSD.status).toBe("FOUND");
    expect(results.USDJPY.status).toBe("FOUND");
  });

  it.each([
    ["crossed quote", ["EURUSD", "1.13745", "1.13744"] as Row],
    ["negative quote", ["EURUSD", "-1.13743", "1.13744"] as Row],
    ["missing precision", ["EURUSD", "1.13", "1.14"] as Row],
    ["out-of-range quote", ["EURUSD", "9.13743", "9.13744"] as Row],
  ])("rejects %s", (_name, row) => {
    document.body.innerHTML = table([row]);
    expect(findQuoteTargets().EURUSD.status).toBe("MISSING");
  });

  it("uses USDJPY precision and rejects EURUSD-style two decimals", () => {
    document.body.innerHTML = table([["USDJPY", "163.83", "163.84"]]);
    expect(readQuote(findQuoteTargets().USDJPY.target!)).toEqual({
      instrument: "USDJPY",
      bid: "163.83",
      ask: "163.84",
    });
    document.body.innerHTML = table([["USDJPY", "163.83211", "163.83212"]]);
    expect(findQuoteTargets().USDJPY.status).toBe("MISSING");
  });

  it("reacquires rows and tables after replacement", async () => {
    document.body.innerHTML = table(FOUR_ROWS);
    const quotes: VisibleQuote[] = [];
    const observer = new MultiQuoteObserver((quote) => quotes.push(quote));
    observer.start();

    const replacementRow = document.createElement("tr");
    replacementRow.dataset.symbol = "EURUSD";
    replacementRow.innerHTML =
      "<td>EURUSD</td><td>1.13745</td><td>1.13746</td><td>1.13745</td>";
    document.querySelector("[data-symbol='EURUSD']")?.replaceWith(replacementRow);
    await reacquire();
    expect(quotes.at(-1)).toEqual({
      instrument: "EURUSD",
      bid: "1.13745",
      ask: "1.13746",
    });

    document.querySelector("table")?.replaceWith(
      Object.assign(document.createElement("div"), { innerHTML: table(FOUR_ROWS) })
        .firstElementChild!,
    );
    await reacquire();
    expect(observer.snapshot().EURUSD.status).toBe("READY");
    observer.stop();
  });

  it("reacquires after a symbol is removed and re-added", async () => {
    document.body.innerHTML = table(FOUR_ROWS);
    const observer = new MultiQuoteObserver(() => undefined);
    observer.start();
    document.querySelector("[data-symbol='AUDUSD']")?.remove();
    await reacquire();
    expect(observer.snapshot().AUDUSD.status).toBe("MISSING");
    document.querySelector("tbody")?.insertAdjacentHTML(
      "beforeend",
      "<tr data-symbol='AUDUSD'><td>AUDUSD</td><td>0.69691</td><td>0.69692</td><td>0.69690</td></tr>",
    );
    await reacquire();
    expect(observer.snapshot().AUDUSD.status).toBe("READY");
    observer.stop();
  });

  it("reacquires a row when initially empty prices hydrate as text", async () => {
    document.body.innerHTML = table([
      ["EURUSD", "loading", "loading"],
      FOUR_ROWS[1]!,
      FOUR_ROWS[2]!,
      FOUR_ROWS[3]!,
    ]);
    const quotes: VisibleQuote[] = [];
    const observer = new MultiQuoteObserver((quote) => quotes.push(quote));
    observer.start();
    expect(observer.snapshot().EURUSD.status).toBe("MISSING");

    const eurusd = document.querySelector("[data-symbol='EURUSD']");
    const bidText = eurusd?.children[1]?.firstChild;
    const askText = eurusd?.children[2]?.firstChild;
    expect(bidText).toBeInstanceOf(Text);
    expect(askText).toBeInstanceOf(Text);
    (bidText as Text).data = "1.13743";
    (askText as Text).data = "1.13744";
    await reacquire();

    expect(observer.snapshot().EURUSD.status).toBe("READY");
    expect(quotes.at(-1)).toEqual({
      instrument: "EURUSD",
      bid: "1.13743",
      ask: "1.13744",
    });
    observer.stop();
  });

  it("emits only the changed pair", async () => {
    document.body.innerHTML = table(FOUR_ROWS);
    const quotes: VisibleQuote[] = [];
    const observer = new MultiQuoteObserver((quote) => quotes.push(quote));
    observer.start();
    expect(quotes).toHaveLength(4);
    const eurusd = document.querySelector("[data-symbol='EURUSD']");
    eurusd?.children[1]?.replaceChildren("1.13746");
    eurusd?.children[2]?.replaceChildren("1.13747");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(quotes).toHaveLength(5);
    expect(quotes.at(-1)?.instrument).toBe("EURUSD");
    observer.stop();
  });

  it("bounds discovery to the documented table limit", () => {
    document.body.innerHTML =
      Array.from({ length: 32 }, () => table([])).join("") +
      table([FOUR_ROWS[0]!]);
    expect(findQuoteTargets().EURUSD.status).toBe("MISSING");
  });
});
