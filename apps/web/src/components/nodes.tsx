import type { Node, NodeProps } from "@xyflow/react";
import { Handle, Position } from "@xyflow/react";
import { CheckCircle, Circle, Loader, Globe, GitBranch, Video, User, BrainCircuit } from "lucide-react";
import { useRunLive } from "./run-live";

export type FlowNode = Node<Record<string, unknown>, string>;

const nodeLabels: Record<string, string> = {
  llm: "模型",
  human: "确认",
  http: "请求",
  condition: "条件",
  media: "视频",
};

const nodeIcons: Record<string, React.ComponentType<{ size?: number; color?: string }>> = {
  llm: BrainCircuit,
  human: User,
  http: Globe,
  condition: GitBranch,
  media: Video,
};

const nodeAccent: Record<string, string> = {
  llm: "#2563eb",
  human: "#7c3aed",
  http: "#0891b2",
  condition: "#d97706",
  media: "#dc2626",
};

export function StudioNode({ id, data, type }: NodeProps<FlowNode>) {
  const live = useRunLive(id);
  const metrics = live?.metrics;
  const nodeType = type || "llm";
  const Icon = nodeIcons[nodeType] || Circle;
  const accent = nodeAccent[nodeType] || "#2563eb";
  const status = live?.status;

  return (
    <article className={`flow-node ${status || ""}`}>
      <Handle type="target" position={Position.Left} style={{ background: "#94a3b8", borderColor: "#94a3b8" }} />

      {/* Header row: icon + type badge */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
        <span style={{
          width: 22, height: 22, borderRadius: 6,
          background: `${accent}18`, display: "flex",
          alignItems: "center", justifyContent: "center", flexShrink: 0,
        }}>
          <Icon size={13} color={accent} />
        </span>
        <span className="flow-node-kind">{nodeLabels[nodeType] || nodeType}</span>

        {/* Status dot */}
        {status === "running" && (
          <span style={{ marginLeft: "auto", color: "#2563eb" }}>
            <Loader size={12} className="animate-spin" />
          </span>
        )}
        {status === "done" && (
          <span style={{ marginLeft: "auto", color: "#16a34a" }}>
            <CheckCircle size={12} />
          </span>
        )}
      </div>

      <div className="flow-node-name">{String(data.label || "未命名")}</div>

      {status === "running" && (
        <div className="flow-node-status">
          <span className="animate-pulse" style={{ width: 6, height: 6, borderRadius: "50%", background: "#2563eb", display: "inline-block" }} />
          正在输出
        </div>
      )}

      {metrics && (
        <div className="flow-node-metrics">
          <span className="metric-chip">{(metrics.duration_ms / 1000).toFixed(1)}s</span>
          <span className="metric-chip">{metrics.prompt_tokens + metrics.completion_tokens + metrics.reasoning_tokens} tok</span>
          <span className="metric-chip">{metrics.tokens_per_second}/s</span>
        </div>
      )}

      {/* Source handle(s) */}
      {type === "condition" ? (
        <>
          <Handle id="true" type="source" position={Position.Right} style={{ top: "35%", background: "#16a34a", borderColor: "#16a34a" }} />
          <Handle id="false" type="source" position={Position.Right} style={{ top: "70%", background: "#dc2626", borderColor: "#dc2626" }} />
        </>
      ) : (
        <Handle type="source" position={Position.Right} style={{ background: "#94a3b8", borderColor: "#94a3b8" }} />
      )}
    </article>
  );
}

export const nodeTypes = {
  llm: StudioNode,
  human: StudioNode,
  http: StudioNode,
  condition: StudioNode,
  media: StudioNode,
};

