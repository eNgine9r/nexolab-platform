import { Activity } from "lucide-react";

import { PlatformPlaceholderScreen } from "@/components/dashboard/platform-placeholder-screen";

export default function LivePage() {
  return (
    <PlatformPlaceholderScreen
      title="Live дані"
      eyebrow="Realtime telemetry"
      description="Оперативний потік телеметрії відкривається всередині основного інтерфейсу NEXOLAB із постійною боковою навігацією."
      icon={<Activity className="h-7 w-7" />}
    />
  );
}
