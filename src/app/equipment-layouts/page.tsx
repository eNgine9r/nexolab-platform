import { Boxes } from "lucide-react";

import { PlatformPlaceholderScreen } from "@/components/dashboard/platform-placeholder-screen";

export default function EquipmentLayoutsPage() {
  return (
    <PlatformPlaceholderScreen
      title="Схеми обладнання"
      eyebrow="Digital layouts"
      description="Каталог цифрових схем обладнання відкривається як внутрішній маршрут платформи, без окремого вікна та втрати бокової панелі."
      icon={<Boxes className="h-7 w-7" />}
    />
  );
}
