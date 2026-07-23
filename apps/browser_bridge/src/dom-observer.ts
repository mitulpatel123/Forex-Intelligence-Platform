import {
  INSTRUMENT_SPECS,
  SUPPORTED_INSTRUMENTS,
  type SupportedInstrument,
  isSupportedInstrument,
} from "./instruments.generated";

export type VisibleQuote = {
  instrument: SupportedInstrument;
  bid: string;
  ask: string;
};

export type QuoteTarget = {
  instrument: SupportedInstrument;
  table: Element;
  row: Element;
  bidCell: Element;
  askCell: Element;
};

export type PairTargetStatus = "FOUND" | "READY" | "MISSING" | "AMBIGUOUS" | "STALE";

export type PairObserverState = {
  status: PairTargetStatus;
  lastObservationAt: string | null;
};

export type PairObserverSnapshot = Record<SupportedInstrument, PairObserverState>;

type DiscoveryResult =
  | { status: "MISSING" | "AMBIGUOUS"; target: null }
  | { status: "FOUND"; target: QuoteTarget };

type QuoteCallback = (quote: VisibleQuote) => void;
type StatusCallback = (status: PairObserverSnapshot) => void;

const ROW_SELECTOR = "tr,[role='row']";
const CELL_SELECTOR = "td,[role='cell']";
const HEADER_SELECTOR = "th,[role='columnheader']";
const TABLE_SELECTOR = "table,[role='table'],[role='grid']";
const MAX_TABLES = 32;
const MAX_ROWS = 512;

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

function quoteFromCells(
  instrument: SupportedInstrument,
  bidCell: Element,
  askCell: Element,
): VisibleQuote | null {
  if (!isElementVisible(bidCell) || !isElementVisible(askCell)) return null;
  const bid = normalizedText(bidCell);
  const ask = normalizedText(askCell);
  const spec = INSTRUMENT_SPECS[instrument];
  const pattern = new RegExp(
    `^\\d+\\.\\d{${spec.display_decimal_min},${spec.display_decimal_max}}$`,
  );
  if (!pattern.test(bid) || !pattern.test(ask)) return null;
  const bidValue = Number(bid);
  const askValue = Number(ask);
  const minimum = Number(spec.broad_min_price);
  const maximum = Number(spec.broad_max_price);
  if (
    !Number.isFinite(bidValue) ||
    !Number.isFinite(askValue) ||
    bidValue < minimum ||
    askValue > maximum ||
    askValue < bidValue
  ) {
    return null;
  }
  return { instrument, bid, ask };
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
  return quoteFromCells(target.instrument, target.bidCell, target.askCell);
}

export function findQuoteTargets(
  root: ParentNode = document,
): Record<SupportedInstrument, DiscoveryResult> {
  const matches = Object.fromEntries(
    SUPPORTED_INSTRUMENTS.map((instrument) => [instrument, []]),
  ) as unknown as Record<
    SupportedInstrument,
    Array<{ target: QuoteTarget; quote: VisibleQuote }>
  >;
  let visitedRows = 0;
  for (const table of Array.from(root.querySelectorAll(TABLE_SELECTOR)).slice(0, MAX_TABLES)) {
    if (!isElementVisible(table)) continue;
    const indexes = columnIndexes(table);
    if (!indexes) continue;
    const rows = ownedDescendants(table, ROW_SELECTOR, TABLE_SELECTOR);
    for (const row of rows) {
      visitedRows += 1;
      if (visitedRows > MAX_ROWS) break;
      if (!isElementVisible(row)) continue;
      const cells = ownedDescendants(row, CELL_SELECTOR, ROW_SELECTOR);
      const symbolCell = cells[indexes.symbol];
      const symbol = symbolCell ? normalizedText(symbolCell).toUpperCase() : "";
      if (!isSupportedInstrument(symbol)) continue;
      const bidCell = cells[indexes.bid];
      const askCell = cells[indexes.ask];
      if (!bidCell || !askCell) continue;
      const quote = quoteFromCells(symbol, bidCell, askCell);
      if (quote) {
        matches[symbol].push({
          target: { instrument: symbol, table, row, bidCell, askCell },
          quote,
        });
      }
    }
    if (visitedRows > MAX_ROWS) break;
  }
  return Object.fromEntries(
    SUPPORTED_INSTRUMENTS.map((instrument) => {
      const candidates = matches[instrument];
      if (candidates.length === 0) {
        return [instrument, { status: "MISSING", target: null }];
      }
      const quotes = new Set(candidates.map(({ quote }) => `${quote.bid}:${quote.ask}`));
      if (quotes.size !== 1) {
        return [instrument, { status: "AMBIGUOUS", target: null }];
      }
      return [instrument, { status: "FOUND", target: candidates[0]!.target }];
    }),
  ) as Record<SupportedInstrument, DiscoveryResult>;
}

export function findEurUsdQuoteTarget(root: ParentNode = document): QuoteTarget | null {
  return findQuoteTargets(root).EURUSD.target;
}

export class MultiQuoteObserver {
  private targets = new Map<SupportedInstrument, QuoteTarget>();
  private targetObserver: MutationObserver | null = null;
  private acquisitionObserver: MutationObserver | null = null;
  private staleTimer: number | null = null;
  private acquireTimer: number | null = null;
  private lastQuotes = new Map<SupportedInstrument, string>();
  private states = Object.fromEntries(
    SUPPORTED_INSTRUMENTS.map((instrument) => [
      instrument,
      { status: "MISSING", lastObservationAt: null },
    ]),
  ) as PairObserverSnapshot;

  constructor(
    private readonly onQuote: QuoteCallback,
    private readonly onStatus: StatusCallback = () => undefined,
    private readonly root: Document = document,
    private readonly staleAfterMs = 10_000,
  ) {}

  start(): void {
    this.acquire();
    this.staleTimer = window.setInterval(() => this.markStale(), 1_000);
  }

  stop(): void {
    this.targetObserver?.disconnect();
    this.acquisitionObserver?.disconnect();
    if (this.staleTimer !== null) window.clearInterval(this.staleTimer);
    if (this.acquireTimer !== null) window.clearTimeout(this.acquireTimer);
    this.targetObserver = null;
    this.acquisitionObserver = null;
    this.staleTimer = null;
    this.acquireTimer = null;
    this.targets.clear();
  }

  snapshot(): PairObserverSnapshot {
    return structuredClone(this.states);
  }

  private publishStatus(): void {
    this.onStatus(this.snapshot());
  }

  private emitCurrent(): void {
    let reacquire = false;
    for (const instrument of SUPPORTED_INSTRUMENTS) {
      const target = this.targets.get(instrument);
      if (!target) continue;
      const quote = readQuote(target);
      if (!quote) {
        reacquire = true;
        continue;
      }
      const key = `${quote.bid}:${quote.ask}`;
      if (key === this.lastQuotes.get(instrument)) continue;
      const observedAt = new Date().toISOString();
      this.lastQuotes.set(instrument, key);
      this.states[instrument] = { status: "READY", lastObservationAt: observedAt };
      this.onQuote(quote);
    }
    this.publishStatus();
    if (reacquire) this.scheduleAcquire();
  }

  private watchTargets(): void {
    this.targetObserver?.disconnect();
    this.targetObserver = new MutationObserver(() => this.emitCurrent());
    const roots = new Set(
      Array.from(this.targets.values()).map(
        (target) => target.table.parentElement ?? target.table,
      ),
    );
    for (const root of roots) {
      this.targetObserver.observe(root, {
        childList: true,
        characterData: true,
        subtree: true,
      });
    }
  }

  private scheduleAcquire(): void {
    if (this.acquireTimer !== null) return;
    this.acquireTimer = window.setTimeout(() => {
      this.acquireTimer = null;
      this.acquire();
    }, 100);
  }

  private acquire(): void {
    const results = findQuoteTargets(this.root);
    this.targets.clear();
    for (const instrument of SUPPORTED_INSTRUMENTS) {
      const result = results[instrument];
      if (result.target) {
        this.targets.set(instrument, result.target);
        this.states[instrument] = {
          status: "FOUND",
          lastObservationAt: this.states[instrument].lastObservationAt,
        };
      } else {
        this.states[instrument] = {
          status: result.status,
          lastObservationAt: this.states[instrument].lastObservationAt,
        };
      }
    }
    this.watchTargets();
    if (!this.acquisitionObserver) {
      const observationRoot = this.root.documentElement ?? this.root;
      this.acquisitionObserver = new MutationObserver(() => {
        const targetRemoved = Array.from(this.targets.values()).some(
          (target) => !target.row.isConnected || !target.table.isConnected,
        );
        const incomplete = SUPPORTED_INSTRUMENTS.some(
          (instrument) =>
            this.states[instrument].status === "MISSING" ||
            this.states[instrument].status === "AMBIGUOUS",
        );
        if (targetRemoved || incomplete) this.scheduleAcquire();
      });
      this.acquisitionObserver.observe(observationRoot, {
        childList: true,
        subtree: true,
      });
    }
    this.emitCurrent();
  }

  private markStale(): void {
    const now = Date.now();
    let changed = false;
    for (const instrument of SUPPORTED_INSTRUMENTS) {
      const state = this.states[instrument];
      if (
        state.status === "READY" &&
        state.lastObservationAt &&
        now - Date.parse(state.lastObservationAt) > this.staleAfterMs
      ) {
        this.states[instrument] = { ...state, status: "STALE" };
        changed = true;
      }
    }
    if (changed) this.publishStatus();
  }
}

export class TargetedQuoteObserver {
  private readonly observer: MultiQuoteObserver;

  constructor(onQuote: (quote: { bid: string; ask: string }) => void, root = document) {
    this.observer = new MultiQuoteObserver((quote) => {
      if (quote.instrument === "EURUSD") onQuote({ bid: quote.bid, ask: quote.ask });
    }, undefined, root);
  }

  start(): void {
    this.observer.start();
  }

  stop(): void {
    this.observer.stop();
  }
}
