export type ProviderInfo = {
  name: string;
  configured: boolean;
  env: string[];
  note: string;
  reachable?: boolean;
  models?: { id: string; name: string }[];
};

export type ToolTrace = { tool: string; ok: boolean; error?: string | null; proposal_id?: string | null };
