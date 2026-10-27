// Calls to LazyLibrarian's /api/v1, with the login the page has

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// a list is sent as the name repeated, keys=a&keys=b
type Query = Record<string, string | number | boolean | string[] | null | undefined>;

interface ApiOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  query?: Query;
  body?: unknown;
}

export function urlBase() {
  return window.LazyLibrarian?.urlBase ?? '';
}

function errorMessage(status: number, data: unknown) {
  const detail = (data as { detail?: unknown } | null)?.detail;

  if (typeof detail === 'string') {
    return detail;
  }

  if (Array.isArray(detail)) {
    // FastAPI's validation errors
    return detail
      .map((error: { loc?: string[]; msg?: string }) =>
        [error.loc?.slice(1).join('.'), error.msg].filter(Boolean).join(': ')
      )
      .join('; ');
  }

  return `The request failed (${status})`;
}

export async function api<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const { method = 'GET', query, body } = options;
  const params = new URLSearchParams();

  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      value.forEach((one) => params.append(key, one));
    } else if (value !== null && value !== undefined && value !== '') {
      params.set(key, String(value));
    }
  });

  const search = params.toString();
  const response = await fetch(`${urlBase()}/api/v1${path}${search ? `?${search}` : ''}`, {
    method,
    credentials: 'same-origin',
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (response.status === 401) {
    // the login has expired, log in again and come back here
    const here = `${window.location.pathname}${window.location.search}`;
    window.location.href = `${urlBase()}/auth/login?from_page=${encodeURIComponent(here)}`;
  }

  const text = await response.text();
  const data = text ? JSON.parse(text) : undefined;

  if (!response.ok) {
    throw new ApiError(response.status, errorMessage(response.status, data));
  }

  return data as T;
}
