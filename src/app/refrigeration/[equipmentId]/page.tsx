import { RefrigerationEquipmentRoute } from "@/components/refrigeration/refrigeration-equipment-route";
import { getRefrigerationEquipment } from "@/data/refrigeration";

export default async function RefrigerationEquipmentPage({
  params,
}: {
  params: Promise<{ equipmentId: string }>;
}) {
  const { equipmentId } = await params;

  return (
    <RefrigerationEquipmentRoute
      equipmentId={equipmentId}
      initialEquipment={getRefrigerationEquipment(equipmentId) ?? null}
    />
  );
}
