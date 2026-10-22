import { customFetch } from '@workspace/api-client-react';

export type ApolloCitation = {
  n: number;
  title: string;
  url: string | null;
  domain: string;
  retrieved_at: string | null;
  origin: 'tinyfish_live' | 'offline';
};

export type ApolloCall = {
  kind: string;
  status: string;
  detail: string;
  result_count: number;
  elapsed_ms: number;
  query: string;
};

export type ApolloReply = {
  answer: string;
  citations: ApolloCitation[];
  needs_doctor: boolean;
  escalation: string | null;
  red_flags: string[];
  guidance: {
    mode: 'live' | 'cached' | 'offline';
    topic: string;
    query_sent: string | null;
    source_count: number;
    domain_count: number;
  };
  calls: ApolloCall[];
};

export type TinyFishActivity = {
  ts: string;
  kind: string;
  topic: string;
  query: string;
  status: string;
  detail: string;
  result_count: number;
  elapsed_ms: number;
};

const CHAT_TIMEOUT_MS = 70_000;

export async function askApollo(message: string, language: 'en' | 'hi'): Promise<ApolloReply> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), CHAT_TIMEOUT_MS);
  try {
    return await customFetch<ApolloReply>('/api/apollo/chat', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ message, language }),
      responseType: 'json',
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}

export function getTinyFishActivity(limit = 15): Promise<TinyFishActivity[]> {
  return customFetch<TinyFishActivity[]>(`/api/tinyfish/activity?limit=${limit}`, {
    responseType: 'json',
  });
}

export type CarePlace = { name: string; address: string; phone: string; open_status: string };
export type CareReply = {
  places: CarePlace[];
  mode: 'live' | 'cached';
  area: string;
  retrieved_at: string;
  source: string;
};

export type HistoryPoint = {
  ts: string;
  ph: number | null;
  skin_temp_c: number | null;
  moisture_pct: number | null;
  status: string;
};
export type HistoryReply = {
  points: HistoryPoint[];
  total: number;
  first_ts: string | null;
  last_ts: string | null;
  status_counts: Record<string, number>;
};
export type TrendReply = {
  available: boolean;
  level: 'low' | 'watch' | 'rising' | null;
  risk: number | null;
  reason: string | null;
  have: number | null;
  need: number | null;
};

const CARE_TIMEOUT_MS = 130_000;

/** Short error code from the API ("no_key", "timeout", ...), or "other". */
export function errorCode(error: unknown): string {
  const data = (error as { data?: { detail?: { code?: unknown } } } | null)?.data;
  const code = data?.detail?.code;
  return typeof code === 'string' ? code : 'other';
}

export async function findCare(area: string): Promise<CareReply> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), CARE_TIMEOUT_MS);
  try {
    return await customFetch<CareReply>('/api/apollo/find-care', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ area }),
      responseType: 'json',
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}

export function getHistory(limit = 60): Promise<HistoryReply> {
  return customFetch<HistoryReply>(`/api/readings/history?limit=${limit}`, { responseType: 'json' });
}

export function getTrend(): Promise<TrendReply> {
  return customFetch<TrendReply>('/api/trend', { responseType: 'json' });
}
