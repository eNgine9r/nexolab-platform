import { LockKeyhole } from "lucide-react";

import { PlatformPlaceholderScreen } from "@/components/dashboard/platform-placeholder-screen";

export default function LockersPage() {
  return (
    <PlatformPlaceholderScreen
      title="Поштомати"
      eyebrow="Smart lockers"
      description="Керування поштоматами працює у спільному shell NEXOLAB із постійною боковою навігацією."
      icon={<LockKeyhole className="h-7 w-7" />}
    />
  );
}
