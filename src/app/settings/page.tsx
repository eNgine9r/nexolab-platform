import { Settings } from "lucide-react";

import { PlatformPlaceholderScreen } from "@/components/dashboard/platform-placeholder-screen";

export default function SettingsPage() {
  return (
    <PlatformPlaceholderScreen
      title="Налаштування"
      eyebrow="Platform configuration"
      description="Конфігурація платформи відкривається всередині основної оболонки NEXOLAB із постійною боковою панеллю."
      icon={<Settings className="h-7 w-7" />}
    />
  );
}
