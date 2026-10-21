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
    llm_used: boolean;
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
