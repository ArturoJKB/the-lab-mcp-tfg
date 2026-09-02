import { useEffect, useRef, useState } from "react";

export type ExperimentEvent = {
  timestamp: string;
  level: string;
  message: string;
  data?: { stage?: string; experiment_id?: string; model?: string };
};

/**
 * Subscribe to an experiment's SSE stream. The stream replays history, so
 * stage state can be rebuilt by the consumer; `onDone` fires when the backing
 * job reaches its terminal marker.
 */
export function useExperimentStream(
  experimentId: string | null,
  onDone?: () => void,
): { events: ExperimentEvent[]; connected: boolean } {
  const [events, setEvents] = useState<ExperimentEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  useEffect(() => {
    if (!experimentId) {
      setEvents([]);
      return;
    }
    setEvents([]);
    const es = new EventSource(`/experiment/${encodeURIComponent(experimentId)}/events`);
    es.onopen = () => setConnected(true);
    es.onmessage = (event) => {
      let parsed: ExperimentEvent;
      try {
        parsed = JSON.parse(event.data);
      } catch {
        return;
      }
      setEvents((prev) => [...prev, parsed]);
      if (parsed.level === "done") {
        es.close();
        setConnected(false);
        doneRef.current?.();
      }
    };
    es.onerror = () => {
      es.close();
      setConnected(false);
    };
    return () => es.close();
  }, [experimentId]);

  return { events, connected };
}
