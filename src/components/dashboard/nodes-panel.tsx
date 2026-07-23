import { Cpu, Database, Server } from "lucide-react";

import { edgeNodes as demoEdgeNodes, type EdgeNode } from "@/data/dashboard";

import { Sparkline } from "./sparkline";

function stateLabel(node: EdgeNode): string {
  if (node.state === "standby") {
    return "Standby";
  }
  if (node.state === "warning") {
    return "Warning";
  }
  if (node.state === "offline") {
    return "Offline";
  }
  return "Online";
}

function stateColor(node: EdgeNode): string {
  if (node.state === "warning") {
    return "text-amber-400";
  }
  if (node.state === "offline") {
    return "text-slate-500";
  }
  return "text-emerald-400";
}

export function NodesPanel({ nodes = demoEdgeNodes }: { nodes?: EdgeNode[] }) {
  return (
    <div className="divide-y divide-white/[0.045] px-4 py-1 sm:px-5">
      {nodes.map((node) => (
        <article key={node.id} className="group flex items-center gap-3 py-3">
          <div className="relative grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-white/[0.075] bg-white/[0.025] text-slate-400 transition group-hover:border-blue-400/25 group-hover:text-cyan-300">
            <Server className="h-[19px] w-[19px]" strokeWidth={1.6} />
            <span
              className={`absolute right-1 bottom-1 h-2 w-2 rounded-full border-2 border-[#0b213f] ${
                node.state === "warning"
                  ? "bg-amber-400"
                  : node.state === "offline"
                    ? "bg-slate-600"
                    : "bg-emerald-400"
              }`}
            />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h3 className="text-[11px] font-semibold text-slate-100">{node.id}</h3>
              <span className={`text-[8px] font-medium ${stateColor(node)}`}>
                {stateLabel(node)}
              </span>
            </div>
            <p className="mt-0.5 truncate text-[9px] text-slate-500">
              {node.name} · {node.channels}
            </p>
          </div>
          {node.spark.length > 0 && (
            <div className="hidden w-24 shrink-0 xl:block">
              <Sparkline
                points={node.spark}
                stroke={node.state === "warning" ? "#f5b301" : "#0077ff"}
              />
            </div>
          )}
          <div className="w-[68px] shrink-0 space-y-1 text-[8px] text-slate-500">
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1">
                <Cpu className="h-2.5 w-2.5" />
                CPU
              </span>
              <span className="text-slate-300">
                {node.cpu === null ? "—" : `${node.cpu}%`}
              </span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1">
                <Database className="h-2.5 w-2.5" />
                RAM
              </span>
              <span className="text-slate-300">
                {node.ram === null ? "—" : `${node.ram}%`}
              </span>
            </div>
          </div>
        </article>
      ))}
    </div>
  );
}
