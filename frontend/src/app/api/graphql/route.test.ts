import { afterEach, describe, expect, it, vi } from "vitest";
import { POST } from "@/app/api/graphql/route";
import { CHANNELS_QUERY } from "@/lib/graphql/operations";

function makeRequest(body: unknown): Request {
  return new Request("http://localhost:3000/api/graphql", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("Next GraphQL proxy", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.useRealTimers();
  });

  it("forwards only an allowlisted GraphQL operation and preserves extensions", async () => {
    vi.stubEnv("GATEWAY_GRAPHQL_URL", "http://localhost:5000/graphql/");
    const graphqlResponse = {
      data: { channels: null },
      errors: [{ message: "upstream unavailable", extensions: { code: "UPSTREAM_ERROR", service: "channels", status: 503 } }],
      extensions: { requestId: "test-id" },
    };
    const fetchMock = vi.fn().mockResolvedValue(Response.json(graphqlResponse));
    vi.stubGlobal("fetch", fetchMock);

    const response = await POST(makeRequest({ query: CHANNELS_QUERY, variables: {} }));

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0][0]).toEqual(new URL("http://localhost:5000/graphql/"));
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "POST", cache: "no-store" });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(graphqlResponse);
  });

  it("preserves a non-success HTTP status when the Gateway returns a GraphQL envelope", async () => {
    vi.stubEnv("GATEWAY_GRAPHQL_URL", "http://localhost:5000/graphql/");
    const graphqlResponse = {
      errors: [{ message: "poll closed", extensions: { code: "UPSTREAM_ERROR", service: "polls", status: 409 } }],
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(graphqlResponse, { status: 503 })));

    const response = await POST(makeRequest({ query: CHANNELS_QUERY }));

    expect(response.status).toBe(503);
    expect(await response.json()).toEqual(graphqlResponse);
  });

  it("rejects arbitrary GraphQL documents and request fields without contacting the Gateway", async () => {
    vi.stubEnv("GATEWAY_GRAPHQL_URL", "http://localhost:5000/graphql/");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const unsupportedDocument = await POST(makeRequest({ query: "query { __schema { types { name } } }" }));
    const genericProxyBody = await POST(makeRequest({ query: CHANNELS_QUERY, target: "http://example.invalid" }));

    expect(unsupportedDocument.status).toBe(403);
    expect(genericProxyBody.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("reports a missing server-side Gateway URL without forwarding", async () => {
    vi.stubEnv("GATEWAY_GRAPHQL_URL", "");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await POST(makeRequest({ query: CHANNELS_QUERY }));

    expect(response.status).toBe(503);
    expect((await response.json()).errors[0].extensions.code).toBe("GATEWAY_NOT_CONFIGURED");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("maps connection failures to a GraphQL 502 response", async () => {
    vi.stubEnv("GATEWAY_GRAPHQL_URL", "http://localhost:5000/graphql/");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("connection refused")));

    const response = await POST(makeRequest({ query: CHANNELS_QUERY }));

    expect(response.status).toBe(502);
    expect((await response.json()).errors[0].extensions.code).toBe("GATEWAY_UNAVAILABLE");
  });

  it("maps the proxy timeout to HTTP 504", async () => {
    vi.useFakeTimers();
    vi.stubEnv("GATEWAY_GRAPHQL_URL", "http://localhost:5000/graphql/");
    const fetchMock = vi.fn((_url: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(init.signal?.reason), { once: true });
    }));
    vi.stubGlobal("fetch", fetchMock);

    const responsePromise = POST(makeRequest({ query: CHANNELS_QUERY }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    await vi.advanceTimersByTimeAsync(12_000);
    const response = await responsePromise;

    expect(response.status).toBe(504);
    expect((await response.json()).errors[0].extensions.code).toBe("GATEWAY_TIMEOUT");
  });
});
