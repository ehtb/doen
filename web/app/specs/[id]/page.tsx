import { getSpec } from "@/lib/api";
import type { SpecItem } from "@/lib/types";

const page = { maxWidth: 760, margin: "2rem auto", padding: "0 1rem",
  fontFamily: "system-ui, sans-serif", lineHeight: 1.5 } as const;
const muted = { color: "#888" } as const;

function ItemList({ items }: { items: SpecItem[] }) {
  if (items.length === 0) return <p style={muted}>—</p>;
  return (
    <ul>
      {items.map((it) => (
        <li key={it.id}>
          {it.text} <span style={muted}>({it.status})</span>
        </li>
      ))}
    </ul>
  );
}

export default async function SpecPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const spec = await getSpec(id);

  if (!spec) {
    return (
      <main style={page}>
        <p>
          No spec found for <code>{id}</code>.
        </p>
      </main>
    );
  }

  return (
    <main style={page}>
      <h1>{spec.title}</h1>
      <p style={muted}>
        {spec.initiative_id} · stage {spec.stage} · v{spec.version}
      </p>

      <h2>Intent</h2>
      <p style={{ whiteSpace: "pre-wrap" }}>{spec.intent || "—"}</p>

      <h2>Constraints</h2>
      <ItemList items={spec.constraints} />

      <h2>Discretion</h2>
      <ItemList items={spec.discretion} />

      <h2>Acceptance criteria</h2>
      {spec.acceptance.length === 0 ? (
        <p style={muted}>—</p>
      ) : (
        <ul>
          {spec.acceptance.map((a) => (
            <li key={a.id}>
              {a.text}{" "}
              <span style={muted}>
                [{a.verify.kind}] ({a.status})
              </span>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
