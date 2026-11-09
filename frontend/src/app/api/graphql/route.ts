import { ALLOWED_GRAPHQL_DOCUMENTS } from "../../../lib/graphql/operations";

const MAX_REQUEST_BYTES = 128 * 1024;
const UPSTREAM_TIMEOUT_MS = 12_000;
const GRAPHQL_KEYS = new Set(["query", "variables", "operationName", "extensions"]);
const ALLOWED_QUERY_DOCUMENTS = new Set<string>(ALLOWED_GRAPHQL_DOCUMENTS);

type JsonRecord = Record<string, unknown>;

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function graphqlError(status: number, code: string, message: string): Response {
  return Response.json(
    {
      errors: [{ message, extensions: { code, status } }],
    },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}

function configuredGatewayUrl(): URL | null {
  const value = process.env.GATEWAY_GRAPHQL_URL?.trim();
  if (!value) return null;

  try {
    const url = new URL(value);
    if (
      !["http:", "https:"].includes(url.protocol) ||
      !url.hostname ||
      url.username ||
      url.password ||
      url.search ||
      url.hash
    ) {
      return null;
    }
    return url;
  } catch {
    return null;
  }
}

function validGraphqlRequest(value: unknown): value is JsonRecord & { query: string } {
  if (!isRecord(value)) return false;
  if (Object.keys(value).some((key) => !GRAPHQL_KEYS.has(key))) return false;
  if (typeof value.query !== "string" || value.query.trim().length === 0) return false;
  if ("operationName" in value && value.operationName !== null && typeof value.operationName !== "string") {
    return false;
  }
  for (const key of ["variables", "extensions"] as const) {
    if (key in value && value[key] !== null && !isRecord(value[key])) return false;
  }
  return true;
}

function validGraphqlResponse(value: unknown): value is JsonRecord {
  if (!isRecord(value)) return false;
  return "data" in value || Array.isArray(value.errors) || "extensions" in value;
}

export async function POST(request: Request): Promise<Response> {
  const contentType = request.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().startsWith("application/json")) {
    return graphqlError(415, "UNSUPPORTED_MEDIA_TYPE", "Envía la operación GraphQL como JSON.");
  }

  const declaredLength = Number(request.headers.get("content-length") ?? 0);
  if (declaredLength > MAX_REQUEST_BYTES) {
    return graphqlError(413, "REQUEST_TOO_LARGE", "La operación GraphQL excede el tamaño permitido.");
  }

  let rawBody: string;
  let body: unknown;
  try {
    rawBody = await request.text();
    if (new TextEncoder().encode(rawBody).byteLength > MAX_REQUEST_BYTES) {
      return graphqlError(413, "REQUEST_TOO_LARGE", "La operación GraphQL excede el tamaño permitido.");
    }
    body = JSON.parse(rawBody);
  } catch {
    return graphqlError(400, "INVALID_JSON", "El cuerpo de la solicitud no contiene JSON válido.");
  }

  if (!validGraphqlRequest(body)) {
    return graphqlError(400, "INVALID_GRAPHQL_REQUEST", "La solicitud debe contener una operación GraphQL válida.");
  }
  if (!ALLOWED_QUERY_DOCUMENTS.has(body.query)) {
    return graphqlError(403, "GRAPHQL_OPERATION_NOT_ALLOWED", "El proxy solo acepta operaciones GraphQL de la interfaz.");
  }

  const gatewayUrl = configuredGatewayUrl();
  if (!gatewayUrl) {
    return graphqlError(503, "GATEWAY_NOT_CONFIGURED", "Configura GATEWAY_GRAPHQL_URL en el servidor Next.js.");
  }

  const controller = new AbortController();
  const timeout = setTimeout(
    () => controller.abort(new DOMException("La solicitud al Gateway excedió el tiempo límite.", "TimeoutError")),
    UPSTREAM_TIMEOUT_MS,
  );
  const cancelUpstream = () => controller.abort(new DOMException("El cliente canceló la solicitud.", "AbortError"));
  request.signal.addEventListener("abort", cancelUpstream, { once: true });

  try {
    const upstream = await fetch(gatewayUrl, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
      cache: "no-store",
      redirect: "manual",
      signal: controller.signal,
    });

    if (upstream.status >= 300 && upstream.status < 400) {
      return graphqlError(502, "GATEWAY_REDIRECT", "El Gateway GraphQL respondió con una redirección inesperada.");
    }

    let payload: unknown;
    try {
      payload = await upstream.json();
    } catch {
      return graphqlError(502, "INVALID_GATEWAY_RESPONSE", "El Gateway no devolvió una respuesta GraphQL JSON válida.");
    }

    if (!validGraphqlResponse(payload)) {
      return graphqlError(502, "INVALID_GATEWAY_RESPONSE", "El Gateway devolvió un cuerpo que no corresponde a GraphQL.");
    }

    return Response.json(payload, {
      status: upstream.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    if (controller.signal.reason instanceof DOMException && controller.signal.reason.name === "TimeoutError") {
      return graphqlError(504, "GATEWAY_TIMEOUT", "El Gateway GraphQL no respondió dentro del tiempo permitido.");
    }
    if (request.signal.aborted) {
      return new Response(null, { status: 499, headers: { "Cache-Control": "no-store" } });
    }
    return graphqlError(502, "GATEWAY_UNAVAILABLE", "No fue posible conectar con el Gateway GraphQL.");
  } finally {
    clearTimeout(timeout);
    request.signal.removeEventListener("abort", cancelUpstream);
  }
}
