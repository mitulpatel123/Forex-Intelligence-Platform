import { describe, expect, it } from "vitest";
import {
  browserIdentity,
  parseVisibleQuote,
  providerRequest,
} from "../src/bridge-protocol";
import { CHANNEL, type CapturedFrame } from "../src/schema";

describe("browser bridge protocol", () => {
  const frame: CapturedFrame = {
    channel: CHANNEL,
    frameType: "dom-visible-quote",
    receivedAt: "2026-07-23T18:09:12.681Z",
    payload: '{"instrument":"EURUSD","bid":"1.13743","ask":"1.13744"}',
  };

  it("creates account-free per-run, tab, frame, and document identities", () => {
    expect(browserIdentity("run-id", 12, 3, "document-id")).toEqual({
      connectionId: "browser-run-id-tab-12-frame-3",
      sessionId: "document-document-id",
    });
    const identities = [
      browserIdentity("run-id", 12, 0, "document-a"),
      browserIdentity("run-id", 13, 0, "document-b"),
      browserIdentity("run-id", 12, 2, "document-c"),
      browserIdentity("run-id", 12, 0, "document-after-reload"),
    ].map((identity) => `${identity.connectionId}:${identity.sessionId}`);
    expect(new Set(identities).size).toBe(identities.length);
  });

  it("qualifies visible observations as display quotes, not provider ticks", () => {
    const quote = parseVisibleQuote(frame);
    expect(quote).not.toBeNull();
    const request = providerRequest(
      "event-id",
      { connectionId: "connection", sessionId: "session" },
      frame,
      quote!,
    );
    expect(request).toMatchObject({
      event_id: "event-id",
      payload: {
        observation_source: "visible_dom",
        observation_level: "DISPLAY_QUOTE",
        is_provider_tick: false,
      },
      channel_metadata: {
        observation_level: "DISPLAY_QUOTE",
        is_provider_tick: false,
      },
    });
  });
});
