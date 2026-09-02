export type ApiResult<T> = {
  ok: boolean;
  data?: T;
  error?: string;
  detail?: string;
  message?: string;
};

export async function api<T = unknown>(
  method: string,
  path: string,
  body?: unknown,
): Promise<ApiResult<T>> {
  try {
    const res = await fetch(path, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    const payload = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    return {
      ok: res.ok && payload.ok !== false,
      ...(payload as object),
    } as ApiResult<T>;
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}
