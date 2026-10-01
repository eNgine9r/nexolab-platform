import { RefrigerationEquipmentRoute } from "@/components/refrigeration/refrigeration-equipment-route";
import { getRefrigerationEquipment } from "@/data/refrigeration";
import { readSchemeNavigation } from "@/features/equipment-layouts/scheme-navigation";

export default async function RefrigerationEquipmentPage({
  params,
  searchParams,
}: {
  params: Promise<{ equipmentId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { equipmentId } = await params;
  const navigation = readSchemeNavigation(await searchParams);

  return (
    <RefrigerationEquipmentRoute
      equipmentId={equipmentId}
      initialEquipment={getRefrigerationEquipment(equipmentId) ?? null}
      navigation={navigation}
    />
  );
}
