import type { ReactNode } from "react";

export function MetricCard({
  label,
  value,
  detail,
  tone = "default",
}: {
  label: string;
  value: ReactNode;
  detail?: string;
  tone?: "default" | "danger" | "warning" | "success";
}) {
  return (
    <article className={`metric-card metric-card-${tone}`}>
      <p>{label}</p>
      <strong>{value}</strong>
      {detail && <span>{detail}</span>}
    </article>
  );
}
