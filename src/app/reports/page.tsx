import { ReportsScreen } from "@/components/reports/reports-screen";
import { parseReportSessionTarget } from "@/lib/reports/session-navigation";

export default async function ReportsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  return <ReportsScreen target={parseReportSessionTarget(params.session)} />;
}
