import { notFound } from "next/navigation";

import { RefrigerationLayoutEditorScreen } from "@/components/refrigeration/refrigeration-layout-editor-screen";
import { getRefrigerationEquipment } from "@/data/refrigeration";

export default async function RefrigerationLayoutPage({
  params,
}: {
  params: Promise<{ equipmentId: string }>;
}) {
  const { equipmentId } = await params;
  const equipment = getRefrigerationEquipment(equipmentId);

  if (!equipment) {
    notFound();
  }

  return <RefrigerationLayoutEditorScreen equipment={equipment} />;
}
