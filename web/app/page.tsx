"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export default function Home() {
  const [id, setId] = useState("");
  const router = useRouter();

  return (
    <main
      style={{
        maxWidth: 760,
        margin: "2rem auto",
        padding: "0 1rem",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <h1>Doen</h1>
      <p>Open a spec by its initiative id.</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const v = id.trim();
          if (v) router.push(`/specs/${v}`);
        }}
      >
        <input
          value={id}
          onChange={(e) => setId(e.target.value)}
          placeholder="init_…"
          style={{ padding: "0.4rem", width: 280 }}
        />
        <button type="submit" style={{ marginLeft: 8, padding: "0.4rem 0.8rem" }}>
          View
        </button>
      </form>
    </main>
  );
}
