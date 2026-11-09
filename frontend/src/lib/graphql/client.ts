import type { GraphqlError, GraphqlResponse } from "@/lib/graphql/types";

type GraphqlPayload<TData> = Omit<GraphqlResponse<TData>, "httpStatus">;

function isGraphqlPayload<TData>(value: unknown): value is GraphqlPayload<TData> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export class GraphqlTransportError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "GraphqlTransportError";
    this.status = status;
  }
}

export async function graphqlRequest<TData, TVariables extends Record<string, unknown> = Record<string, never>>(
  query: string,
  variables?: TVariables,
  signal?: AbortSignal,
): Promise<GraphqlResponse<TData>> {
  const response = await fetch("/api/graphql", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, ...(variables ? { variables } : {}) }),
    cache: "no-store",
    signal,
  });

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new GraphqlTransportError("El proxy GraphQL devolvió una respuesta no válida.", response.status);
  }

  if (!isGraphqlPayload<TData>(payload)) {
    throw new GraphqlTransportError("El proxy GraphQL devolvió una respuesta inesperada.", response.status);
  }

  if (!response.ok && !Array.isArray(payload.errors)) {
    throw new GraphqlTransportError(`La solicitud GraphQL falló (HTTP ${response.status}).`, response.status);
  }

  return { ...payload, httpStatus: response.status };
}

export function errorStatus(errors: GraphqlError[] | undefined): number | undefined {
  for (const error of errors ?? []) {
    const status = error.extensions?.status;
    if (typeof status === "number") return status;
  }
  return undefined;
}
