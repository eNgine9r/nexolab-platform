import { Camera } from "lucide-react";

import { PlatformPlaceholderScreen } from "@/components/dashboard/platform-placeholder-screen";

export default function CamerasPage() {
  return (
    <PlatformPlaceholderScreen
      title="Камери"
      eyebrow="Video monitoring"
      description="Відеомоніторинг відкривається у межах основної платформи з незмінною боковою панеллю та загальною навігацією."
      icon={<Camera className="h-7 w-7" />}
    />
  );
}
