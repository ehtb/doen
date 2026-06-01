"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export default function Home() {
  const [id, setId] = useState("");
  const router = useRouter();

  return (
    <main className="relative z-10 mx-auto flex min-h-screen max-w-2xl flex-col justify-center px-5 py-16">
      <div className="animate-rise">
        <span className="font-mono text-[11px] font-semibold tracking-[0.18em] text-accent-deep uppercase">
          Doen
        </span>
        <h1 className="mt-3 font-serif text-[clamp(2rem,5vw,3rem)] leading-[1.05] font-medium tracking-tight">
          The intent layer above your executors.
        </h1>
        <p className="mt-3 max-w-[46ch] text-muted-foreground">
          Open a living spec by its initiative id — author it, confirm what governs, and steer the
          decisions agents raise.
        </p>
      </div>

      <form
        className="animate-rise [animation-delay:120ms] mt-7 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          const v = id.trim();
          if (v) router.push(`/specs/${v}`);
        }}
      >
        <Input
          value={id}
          onChange={(e) => setId(e.target.value)}
          placeholder="build-doen-0002-spec-editing"
          className="max-w-sm font-mono"
        />
        <Button type="submit">
          Open <ArrowRight />
        </Button>
      </form>
    </main>
  );
}
