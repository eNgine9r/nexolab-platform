import { notFound } from "next/navigation";

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

  return <RefrigerationDetailScreen equipment={equipment} />;
}
