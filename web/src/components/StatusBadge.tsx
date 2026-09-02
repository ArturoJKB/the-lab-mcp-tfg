type Props = { status: string };

export function StatusBadge({ status }: Props) {
  return <span className={`badge ${status}`}>{status}</span>;
}
