import { Brain, ChevronDown, ChevronRight, Lightbulb } from "lucide-react";
import { useState } from "react";
import type { NodeLive } from "./run-live";

export function ThinkingPanel({ nodes, live }: { nodes: { id: string; label: string }[]; live: Record<string, NodeLive> }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const visible = nodes.filter((node) => live[node.id]?.thinking || live[node.id]?.content);

  if (!visible.length) return <p className="thinking-empty">运行后，思考过程会出现在这里。</p>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {visible.map((node) => {
        const item = live[node.id];
        const expanded = open[node.id] ?? item.status === "running";
        return (
          <div className="thinking-item" key={node.id}>
            <button
              type="button"
              className="thinking-header"
              onClick={() => setOpen((c) => ({ ...c, [node.id]: !expanded }))}
            >
              <span style={{ display: "flex", alignItems: "center", gap: 7 }}>
                {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <Brain size={13} color={item.status === "running" ? "#2563eb" : "#64748b"} />
                {node.label}
                {item.status === "running" && (
                  <span className="badge badge-blue" style={{ marginLeft: 2 }}>
                    <span className="animate-pulse" style={{ width: 5, height: 5, borderRadius: "50%", background: "#2563eb", display: "inline-block" }} />
                    运行中
                  </span>
                )}
                {item.metrics && (
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "#94a3b8", marginLeft: 4 }}>
                    {(item.metrics.duration_ms / 1000).toFixed(1)}s · {(item.metrics.prompt_tokens + item.metrics.completion_tokens + item.metrics.reasoning_tokens)} tok
                  </span>
                )}
              </span>
            </button>
            {expanded && (
              <div className="thinking-body">
                {item.thinking && (
                  <div>
                    <div className="thinking-section-label"><Lightbulb size={11} style={{ display: "inline", marginRight: 3 }} />思考过程</div>
                    <p className="thinking-text thinking-thinking">{item.thinking}</p>
                  </div>
                )}
                {item.content && (
                  <div>
                    <div className="thinking-section-label">输出</div>
                    <p className="thinking-text">{item.content}</p>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

