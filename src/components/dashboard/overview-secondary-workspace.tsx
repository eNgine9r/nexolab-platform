import type { ReactNode } from "react";

import type { CameraInventoryResult } from "@/features/cameras/domain";

import { CamerasPanel } from "./cameras-panel";
import { Panel } from "./panel";

interface OverviewSecondaryWorkspaceProps {
  sessions: ReactNode;
  layouts: ReactNode;
  cameraInventory: CameraInventoryResult;
  cameraAction?: ReactNode;
}

export function OverviewSecondaryWorkspace({
  sessions,
  layouts,
  cameraInventory,
  cameraAction,
}: OverviewSecondaryWorkspaceProps) {
  const hasCameras = cameraInventory.items.length > 0;

  return (
    <section className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-12" data-testid="overview-context-grid">
      <div className={hasCameras ? "min-w-0 xl:col-span-4" : "min-w-0 xl:col-span-6"}>{sessions}</div>
      <div className={hasCameras ? "min-w-0 xl:col-span-5" : "min-w-0 xl:col-span-6"}>{layouts}</div>
      {hasCameras ? (
        <Panel title="Камери" action={cameraAction} className="min-w-0 xl:col-span-3">
          <CamerasPanel inventory={cameraInventory} />
        </Panel>
      ) : null}
    </section>
  );
}
