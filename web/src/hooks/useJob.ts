import { useEffect, useRef, useState } from "react";
import { api, type ApiResult } from "../api";

export type JobEvent = {
  timestamp: string;
  level: string;
  message: string;
  data?: Record<string, unknown>;
};

export type JobState = {
  job_id: string;
  job_type: string;
  status: string;
  events: JobEvent[];
  result?: Record<string, unknown>;
  error?: string | null;
  cancel_requested?: boolean;
};

/** Submit a job and follow it via SSE until it reaches a terminal state. */
export function useJob(): {
  job: JobState | null;
  events: JobEvent[];
  submit: (type: string, payload: Record<string, unknown>) => Promise<ApiResult<{ job_id: string }>>;
  cancel: () => Promise<void>;
} {
  const [job, setJob] = useState<JobState | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const sourceRef = useRef<EventSource | null>(null);

  const stop = () => {
    sourceRef.current?.close();
    sourceRef.current = null;
  };

  useEffect(() => stop, []);

  const submit = async (type: string, payload: Record<string, unknown>) => {
    setEvents([]);
    setJob(null);
    const res = await api<{ job_id: string; status: string }>("POST", "/jobs", { type, payload });
    if (!res.ok || !res.data) return res as ApiResult<{ job_id: string }>;

    const job_id = res.data.job_id;
    setJob({
      job_id,
      job_type: type,
      status: res.data.status,
      events: [],
    });

    const es = new EventSource(`/jobs/${encodeURIComponent(job_id)}/events`);
    sourceRef.current = es;
    es.onmessage = (event) => {
      let parsed: JobEvent;
      try {
        parsed = JSON.parse(event.data);
      } catch {
        return;
      }
      setEvents((prev) => [...prev, parsed]);
      if (parsed.level === "done") {
        stop();
        api<JobState>("GET", `/jobs/${encodeURIComponent(job_id)}`).then((r) => {
          if (r.ok && r.data) setJob(r.data);
        });
      }
    };
    es.onerror = () => {
      // Fall back to polling once if the stream breaks.
      stop();
      api<JobState>("GET", `/jobs/${encodeURIComponent(job_id)}`).then((r) => {
        if (r.ok && r.data) setJob(r.data);
      });
    };
    return res;
  };

  const cancel = async () => {
    if (!job) return;
    await api("POST", `/jobs/${encodeURIComponent(job.job_id)}/cancel`);
  };

  return { job, events, submit, cancel };
}
