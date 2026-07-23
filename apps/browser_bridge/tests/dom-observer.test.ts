// @vitest-environment jsdom

import { afterEach, describe, expect, it } from "vitest";
import {
  TargetedQuoteObserver,
  findEurUsdQuoteTarget,
  readQuote,
} from "../src/dom-observer";

function table(
  headers: string[],
  cells: string[],
  attributes = "",
  extraCells = "",
): string {
  return `
    <table ${attributes}>
      <thead><tr>${headers.map((value) => `<th>${value}</th>`).join("")}</tr></thead>
      <tbody>
        <tr data-symbol="EURUSD">
          ${cells.map((value) => `<td>${value}</td>`).join("")}
          ${extraCells}
        </tr>
      </tbody>
    </table>
  `;
}

function currentQuote(): { bid: string; ask: string } | null {
  const target = findEurUsdQuoteTarget();
  return target ? readQuote(target) : null;
}

afterEach(() => {
  document.body.replaceChildren();
});

describe("targeted EURUSD market-watch observer", () => {
  it("uses header-mapped bid and ask cells despite extra decimal values", () => {
    document.body.innerHTML = table(
      ["Symbol", "Bid", "Ask", "Last", "High", "Low"],
      ["EURUSD", "1.13743", "1.13744", "1.13740", "1.14000", "1.13000"],
    );
    expect(currentQuote()).toEqual({ bid: "1.13743", ask: "1.13744" });
  });

  it("ignores hidden duplicate EURUSD layouts", () => {
    document.body.innerHTML = [
      table(["Symbol", "Bid", "Ask"], ["EURUSD", "1.13743", "1.13744"]),
      table(
        ["Symbol", "Bid", "Ask"],
        ["EURUSD", "1.10000", "1.20000"],
        "aria-hidden='true'",
      ),
    ].join("");
    expect(currentQuote()).toEqual({ bid: "1.13743", ask: "1.13744" });
  });

  it("rejects ambiguous visible duplicate rows", () => {
    document.body.innerHTML = [
      table(["Symbol", "Bid", "Ask"], ["EURUSD", "1.13743", "1.13744"]),
      table(["Symbol", "Bid", "Ask"], ["EURUSD", "1.13740", "1.13745"]),
    ].join("");
    expect(findEurUsdQuoteTarget()).toBeNull();
  });

  it("supports reordered columns by their exact headers", () => {
    document.body.innerHTML = table(
      ["Ask", "Symbol", "Daily Change", "Bid"],
      ["1.13744", "EURUSD", "-0.3%", "1.13743"],
    );
    expect(currentQuote()).toEqual({ bid: "1.13743", ask: "1.13744" });
  });

  it("accepts an equal bid and ask", () => {
    document.body.innerHTML = table(
      ["Symbol", "Bid", "Ask"],
      ["EURUSD", "1.13748", "1.13748"],
    );
    expect(currentQuote()).toEqual({ bid: "1.13748", ask: "1.13748" });
  });

  it.each([
    ["malformed bid", ["EURUSD", "not-a-price", "1.13744"]],
    ["crossed quote", ["EURUSD", "1.13745", "1.13744"]],
    ["missing ask precision", ["EURUSD", "1.13743", "1.13"]],
  ])("rejects %s", (_name, cells) => {
    document.body.innerHTML = table(["Symbol", "Bid", "Ask"], cells);
    expect(findEurUsdQuoteTarget()).toBeNull();
  });

  it("reacquires an EURUSD row after replacement", async () => {
    document.body.innerHTML = table(
      ["Symbol", "Bid", "Ask"],
      ["EURUSD", "1.13743", "1.13744"],
    );
    const quotes: Array<{ bid: string; ask: string }> = [];
    const observer = new TargetedQuoteObserver((quote) => quotes.push(quote));
    observer.start();
    expect(quotes).toEqual([{ bid: "1.13743", ask: "1.13744" }]);

    const oldRow = document.querySelector("tbody tr");
    oldRow?.replaceWith(
      Object.assign(document.createElement("tr"), {
        innerHTML: "<td>EURUSD</td><td>1.13745</td><td>1.13746</td>",
      }),
    );
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(quotes.at(-1)).toEqual({ bid: "1.13745", ask: "1.13746" });
    observer.stop();
  });
});
