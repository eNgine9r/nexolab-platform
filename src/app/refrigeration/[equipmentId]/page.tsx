import { notFound } from "next/navigation";

import { OperatorSessionBanner } from "@/components/operator/operator-session-banner";
import { RefrigerationDetailScreen } from "@/components/refrigeration/refrigeration-detail-screen";
import { getRefrigerationEquipment } from "@/data/refrigeration";

export default async function RefrigerationEquipmentPage({
  params,
}: {
  params: Promise<{ equipmentId: string }>;
}) {
  const { equipmentId } = await params;
  const equipment = getRefrigerationEquipment(equipmentId);

  if (!equipment) {
    notFound();
  }

  return (
    <div className="space-y-3">
      <OperatorSessionBanner />
      <RefrigerationDetailScreen equipment={equipment} />
    </div>
  );
}
