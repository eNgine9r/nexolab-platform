import { Zap } from "lucide-react";

import { PlatformPlaceholderScreen } from "@/components/dashboard/platform-placeholder-screen";

export default function EnergyPage() {
  return (
    <PlatformPlaceholderScreen
      title="Енергомоніторинг"
      eyebrow="Energy telemetry"
      description="Показники електроживлення та енергоспоживання відкриваються як внутрішня сторінка NEXOLAB із боковою панеллю."
      icon={<Zap className="h-7 w-7" />}
    />
  );
}
