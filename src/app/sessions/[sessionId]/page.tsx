import { SessionWorkspace } from "@/components/sessions/session-workspace";

export default async function SessionDetailsPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await params;
  return <SessionWorkspace sessionId={sessionId} />;
}
