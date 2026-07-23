export type VisibleQuote = {
  bid: string;
  ask: string;
};

export type QuoteTarget = {
  table: Element;
  row: Element;
  bidCell: Element;
  askCell: Element;
};

type QuoteCallback = (quote: VisibleQuote) => void;

const ROW_SELECTOR = "tr,[role='row']";
const CELL_SELECTOR = "td,[role='cell']";
const HEADER_SELECTOR = "th,[role='columnheader']";
const TABLE_SELECTOR = "table,[role='table'],[role='grid']";
const PRICE_PATTERN = /^\d+\.\d{4,6}$/;

function normalizedText(element: Element): string {
  return (element.textContent ?? "").replace(/\s+/g, " ").trim();
}

export function isElementVisible(element: Element): boolean {
  if (
    element.closest("[hidden],[aria-hidden='true']") ||
    element.getAttribute("data-fip-visible") === "false"
  ) {
    return false;
  }
  const style = window.getComputedStyle(element);
  return style.display !== "none" && style.visibility !== "hidden" && style.opacity !== "0";
}

function ownedDescendants(container: Element, selector: string, ownerSelector: string): Element[] {
  return Array.from(container.querySelectorAll(selector)).filter(
    (element) => element.closest(ownerSelector) === container,
  );
}

function columnIndexes(table: Element): { symbol: number; bid: number; ask: number } | null {
  const headers = ownedDescendants(table, HEADER_SELECTOR, TABLE_SELECTOR).filter(isElementVisible);
  const labels = headers.map((header) => normalizedText(header).toLowerCase());
  const symbol = labels.indexOf("symbol");
  const bid = labels.indexOf("bid");
  const ask = labels.indexOf("ask");
  return symbol >= 0 && bid >= 0 && ask >= 0 ? { symbol, bid, ask } : null;
}

function quoteFromCells(bidCell: Element, askCell: Element): VisibleQuote | null {
  if (!isElementVisible(bidCell) || !isElementVisible(askCell)) return null;
  const bid = normalizedText(bidCell);
  const ask = normalizedText(askCell);
  if (!PRICE_PATTERN.test(bid) || !PRICE_PATTERN.test(ask)) return null;
  const bidValue = Number(bid);
  const askValue = Number(ask);
  if (
    !Number.isFinite(bidValue) ||
    !Number.isFinite(askValue) ||
    bidValue <= 0.5 ||
    bidValue >= 2 ||
    askValue < bidValue ||
    askValue - bidValue > 0.01
  ) {
    return null;
  }
  return { bid, ask };
}

export function readQuote(target: QuoteTarget): VisibleQuote | null {
  if (
    !target.row.isConnected ||
    !target.bidCell.isConnected ||
    !target.askCell.isConnected ||
    !isElementVisible(target.row)
  ) {
    return null;
  }
  return quoteFromCells(target.bidCell, target.askCell);
}

export function findEurUsdQuoteTarget(root: ParentNode = document): QuoteTarget | null {
  const matches: Array<{ target: QuoteTarget; quote: VisibleQuote }> = [];
  for (const table of Array.from(root.querySelectorAll(TABLE_SELECTOR))) {
    if (!isElementVisible(table)) continue;
    const indexes = columnIndexes(table);
    if (!indexes) continue;
    const rows = ownedDescendants(table, ROW_SELECTOR, TABLE_SELECTOR);
    for (const row of rows) {
      if (!isElementVisible(row)) continue;
      const cells = ownedDescendants(row, CELL_SELECTOR, ROW_SELECTOR);
      const symbolCell = cells[indexes.symbol];
      const bidCell = cells[indexes.bid];
      const askCell = cells[indexes.ask];
      if (
        !symbolCell ||
        !bidCell ||
        !askCell ||
        normalizedText(symbolCell).toUpperCase() !== "EURUSD"
      ) {
        continue;
      }
      const quote = quoteFromCells(bidCell, askCell);
      if (quote) matches.push({ target: { table, row, bidCell, askCell }, quote });
    }
  }
  if (matches.length === 0) return null;
  const uniqueQuotes = new Set(matches.map(({ quote }) => `${quote.bid}:${quote.ask}`));
  return uniqueQuotes.size === 1 ? (matches[0]?.target ?? null) : null;
}

export class TargetedQuoteObserver {
  private target: QuoteTarget | null = null;
  private targetObserver: MutationObserver | null = null;
  private acquisitionObserver: MutationObserver | null = null;
  private lastQuote = "";

  constructor(
    private readonly onQuote: QuoteCallback,
    private readonly root: Document = document,
  ) {}

  start(): void {
    this.acquire();
  }

  stop(): void {
    this.targetObserver?.disconnect();
    this.acquisitionObserver?.disconnect();
    this.targetObserver = null;
    this.acquisitionObserver = null;
    this.target = null;
  }

  private emitCurrent(): void {
    if (!this.target) return;
    const quote = readQuote(this.target);
    if (!quote) {
      this.acquire();
      return;
    }
    const key = `${quote.bid}:${quote.ask}`;
    if (key === this.lastQuote) return;
    this.lastQuote = key;
    this.onQuote(quote);
  }

  private watchTarget(target: QuoteTarget): void {
    this.acquisitionObserver?.disconnect();
    this.acquisitionObserver = null;
    this.targetObserver?.disconnect();
    this.target = target;
    this.targetObserver = new MutationObserver(() => {
      if (!this.target?.row.isConnected) {
        this.acquire();
        return;
      }
      this.emitCurrent();
    });
    this.targetObserver.observe(target.table.parentElement ?? target.table, {
      childList: true,
      characterData: true,
      subtree: true,
    });
    this.emitCurrent();
  }

  private acquire(): void {
    this.targetObserver?.disconnect();
    this.targetObserver = null;
    this.target = null;
    const target = findEurUsdQuoteTarget(this.root);
    if (target) {
      this.watchTarget(target);
      return;
    }
    if (this.acquisitionObserver) return;
    const observationRoot = this.root.documentElement ?? this.root;
    this.acquisitionObserver = new MutationObserver(() => {
      const next = findEurUsdQuoteTarget(this.root);
      if (next) this.watchTarget(next);
    });
    this.acquisitionObserver.observe(observationRoot, {
      childList: true,
      characterData: true,
      subtree: true,
    });
  }
}
