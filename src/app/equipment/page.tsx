import { Cpu } from "lucide-react";

import { PlatformPlaceholderScreen } from "@/components/dashboard/platform-placeholder-screen";

export default function EquipmentPage() {
  return (
    <PlatformPlaceholderScreen
      title="Обладнання"
      eyebrow="Asset registry"
      description="Паспорти та життєвий цикл обладнання відкриваються у спільному shell платформи, без переходу в окреме вікно."
      icon={<Cpu className="h-7 w-7" />}
    />
  );
}
