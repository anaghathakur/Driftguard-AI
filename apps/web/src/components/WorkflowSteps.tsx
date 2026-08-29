const steps = [
  ["Detect", "Contract drift"],
  ["Understand", "Code impact & risk"],
  ["Fix", "Guidance & patch"],
  ["Validate", "Static checks"],
  ["Review", "GitHub PR"],
] as const;

export function WorkflowSteps() {
  return (
    <ol aria-label="DriftGuard workflow" className="workflow-steps">
      {steps.map(([label, detail], index) => (
        <li key={label}>
          <span className="workflow-number">{index + 1}</span>
          <span><strong>{label}</strong><small>{detail}</small></span>
          {index < steps.length - 1 && <span aria-hidden="true" className="workflow-arrow">→</span>}
        </li>
      ))}
    </ol>
  );
}
