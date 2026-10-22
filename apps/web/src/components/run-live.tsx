import { createContext, useContext, type ReactNode } from "react";

export type Metrics = {
  prompt_tokens: number;
  completion_tokens: number;
  reasoning_tokens: number;
  duration_ms: number;
  tokens_per_second: number;
};

export type NodeLive = {
  status?: string;
  thinking?: string;
  content?: string;
  metrics?: Metrics;
};

const RunLiveContext = createContext<Record<string, NodeLive>>({});

export function RunLiveProvider({ value, children }: { value: Record<string, NodeLive>; children: ReactNode }) {
  return <RunLiveContext.Provider value={value}>{children}</RunLiveContext.Provider>;
}

export function useRunLive(id: string) {
  return useContext(RunLiveContext)[id];
}
