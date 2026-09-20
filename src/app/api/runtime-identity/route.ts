import { NextResponse } from "next/server";

import { readDashboardRuntimeIdentity } from "@/lib/runtime-identity";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(): Promise<NextResponse> {
  const identity = await readDashboardRuntimeIdentity();
  return NextResponse.json(identity, {
    headers: {
      "Cache-Control": "no-store, max-age=0",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
