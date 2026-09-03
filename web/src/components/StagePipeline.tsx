export type StageStatus = "pending" | "running" | "done" | "failed" | "awaiting";

const ORDER: { id: string; label: string }[] = [
  { id: "planning", label: "Plan" },
  { id: "cleaning", label: "Clean" },
  { id: "training", label: "Train" },
  { id: "evaluating", label: "Evaluate" },
];

type Props = {
  stageStatus: Record<string, StageStatus>;
  finalState?: string | null;
  showAgentic?: boolean;
  agenticStatus?: StageStatus;
};

export function StagePipeline({ stageStatus, finalState, showAgentic = false, agenticStatus }: Props) {
  const stages = showAgentic
    ? [...ORDER, { id: "agentic_round", label: "Agent round" }]
    : ORDER;
  return (
    <div className="exp-stages">
      {stages.map((stage, i) => {
        let status: StageStatus =
          stage.id === "agentic_round" ? (agenticStatus ?? stageStatus[stage.id] ?? "pending") : stageStatus[stage.id] ?? "pending";
        if (stage.id === "agentic_round") {
          if (finalState === "awaiting_approval") status = "awaiting";
          else if (finalState === "completed" && status === "running") status = "done";
        } else if (finalState === "completed") {
          status = "done";
        } else if (finalState === "failed" && status === "running") {
          status = "failed";
        }
        return (
          <span key={stage.id} style={{ display: "contents" }}>
            {i > 0 && <span className="exp-arrow">→</span>}
            <span className={`exp-stage ${status === "running" ? "active" : ""}`}>
              <span className="exp-stage-node">{stage.label}</span>
              <span className={`exp-stage-status ${status}`}>{status}</span>
            </span>
          </span>
        );
      })}
    </div>
  );
}
