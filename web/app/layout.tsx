import type { ReactNode } from "react";

export const metadata = {
  title: "Doen",
  description: "The intent layer above agentic executors.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
