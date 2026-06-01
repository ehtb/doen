import { permanentRedirect } from "next/navigation";

export default async function ProjectRedirect({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  permanentRedirect(`/${id}`);
}
