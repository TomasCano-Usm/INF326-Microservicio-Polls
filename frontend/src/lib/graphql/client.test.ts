import { afterEach, describe, expect, it, vi } from "vitest";
import { errorStatus, graphqlRequest } from "@/lib/graphql/client";

afterEach(() => vi.unstubAllGlobals());

describe("GraphQL client", () => {
  it("returns partial data and keeps GraphQL errors and extensions together", async () => {
    const payload = {
      data: { messages: [] },
      errors: [{ message: "partial field failure", extensions: { code: "UPSTREAM_ERROR", service: "reactions", status: 503 } }],
      extensions: { traceId: "trace-1" },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(payload)));

    const response = await graphqlRequest<{ messages: unknown[] }>("query { channels { id name } }");

    expect(response.data).toEqual(payload.data);
    expect(response.errors).toEqual(payload.errors);
    expect(response.extensions).toEqual(payload.extensions);
    expect(errorStatus(response.errors)).toBe(503);
    expect(response.httpStatus).toBe(200);
  });

  it("posts only to the same-origin Next route", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ data: { channels: [] } }));
    vi.stubGlobal("fetch", fetchMock);

    await graphqlRequest<{ channels: unknown[] }, { filter: string }>("query Channels { channels { id name } }", { filter: "all" });

    expect(fetchMock).toHaveBeenCalledWith("/api/graphql", expect.objectContaining({ method: "POST", cache: "no-store" }));
  });
});
