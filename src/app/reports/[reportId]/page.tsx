import { ReportOutputScreen } from "@/components/reports/report-output-screen";

export default async function ReportOutputPage({
  params,
}: {
  params: Promise<{ reportId: string }>;
}) {
  const { reportId } = await params;
  return <ReportOutputScreen reportId={reportId} />;
}
