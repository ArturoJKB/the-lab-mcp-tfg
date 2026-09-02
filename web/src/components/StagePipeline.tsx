export type StageStatus = "pending" | "running" | "done" | "failed";

const ORDER: { id: string; label: string }[] = [
  { id: "planning", label: "Plan" },
  { id: "cleaning", label: "Clean" },
  { id: "training", label: "Train" },
  { id: "evaluating", label: "Evaluate" },
];

type Props = {
  stageStatus: Record<string, StageStatus>;
  finalState?: string | null;
};

export function StagePipeline({ stageStatus, finalState }: Props) {
  return (
    <div className="exp-stages">
      {ORDER.map((stage, i) => {
        const status = finalState === "completed" ? "done" : stageStatus[stage.id] ?? "pending";
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
