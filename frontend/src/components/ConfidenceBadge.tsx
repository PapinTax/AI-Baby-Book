import clsx from "clsx";

interface Props {
  confidence: number;
  showLabel?: boolean;
}

export default function ConfidenceBadge({ confidence, showLabel = true }: Props) {
  const pct = Math.round(confidence * 100);
  const color =
    confidence >= 0.85
      ? "bg-green-100 text-green-700"
      : confidence >= 0.65
      ? "bg-yellow-100 text-yellow-700"
      : "bg-orange-100 text-orange-700";

  return (
    <span className={clsx("text-xs font-medium px-2 py-0.5 rounded-full", color)}>
      {showLabel ? `${pct}% confidence` : `${pct}%`}
    </span>
  );
}
