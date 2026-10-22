import { useQuery } from "@tanstack/react-query";
import { Background, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ArrowLeft, Brain, Play, RotateCcw } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, streamUrl } from "../api";
import { ThinkingPanel } from "../components/ThinkingPanel";
import { nodeTypes } from "../components/nodes";
import { RunLiveProvider, type Metrics, type NodeLive } from "../components/run-live";

type Definition = { id: string; name: string; graph_json: { nodes: Node[]; edges: Edge[] } };
type RunEvent = {
  type: string;
  node_id?: string;
  content?: string;
  metrics?: Metrics;
  payload?: { node_id?: string; output?: string };
  detail?: string;
};

export function WorkflowRun() {
  const { id } = useParams();
  const definition = useQuery({
    queryKey: ["definition", id],
    queryFn: () => api<Definition>(`/api/workflow/definitions/${id}`),
  });
  const [input, setInput] = useState("雨夜的便利店，一个穿黄雨衣的人推门进来");
  const [live, setLive] = useState<Record<string, NodeLive>>({});
  const [status, setStatus] = useState<"idle" | "running" | "done" | "failed" | "interrupted">("idle");
  const [error, setError] = useState("");
  const [interrupt, setInterrupt] = useState<{ runId: string; nodeId: string; output: string; value: string } | null>(null);

  const labels = useMemo(
    () => (definition.data?.graph_json.nodes || []).map((n) => ({ id: n.id, label: String(n.data?.label || n.id) })),
    [definition.data],
  );

  function apply(event: RunEvent, runId: string) {
    if (event.type === "node_start" && event.node_id)
      setLive((c) => ({ ...c, [event.node_id!]: { ...c[event.node_id!], status: "running" } }));
    if ((event.type === "thinking_token" || event.type === "content_token") && event.node_id) {
      const key = event.type === "thinking_token" ? "thinking" : "content";
      setLive((c) => {
        const prev = c[event.node_id!] || {};
        return { ...c, [event.node_id!]: { ...prev, [key]: `${prev[key as keyof NodeLive] || ""}${event.content || ""}` } };
      });
    }
    if (event.type === "node_end" && event.node_id)
      setLive((c) => ({ ...c, [event.node_id!]: { ...c[event.node_id!], status: "done", metrics: event.metrics } }));
    if (event.type === "workflow_done") setStatus("done");
    if (event.type === "workflow_failed") { setStatus("failed"); setError(event.detail || "运行失败"); }
    if (event.type === "interrupt") {
      setStatus("interrupted");
      const output = event.payload?.output || "";
      setInterrupt({ runId, nodeId: event.payload?.node_id || event.node_id || "", output, value: output });
    }
  }

  function openStream(runId: string) {
    setLive({});
    setError("");
    const source = new EventSource(streamUrl(`/api/workflow/runs/${runId}/stream`));
    source.onmessage = (msg) => {
      const event = JSON.parse(msg.data) as RunEvent;
      apply(event, runId);
      if (["workflow_done", "workflow_failed", "interrupt"].includes(event.type)) source.close();
    };
    source.onerror = () => { setError("运行连接中断"); source.close(); };
  }

  async function start(e: FormEvent) {
    e.preventDefault();
    setStatus("running");
    setInterrupt(null);
    const created = await api<{ run_id: string }>("/api/workflow/runs", {
      method: "POST",
      body: JSON.stringify({ definition_id: id, inputs: { input } }),
    });
    openStream(created.run_id);
  }

  async function resume(decision: "approve" | "reject") {
    if (!interrupt) return;
    setStatus("running");
    await api(`/api/workflow/runs/${interrupt.runId}/resume`, {
      method: "POST",
      body: JSON.stringify({ node_id: interrupt.nodeId, decision, value: interrupt.value }),
    });
    const runId = interrupt.runId;
    setInterrupt(null);
    openStream(runId);
  }

  const isRunning = status === "running";

  return (
    <section className="run-page">
      <form className="run-topbar" onSubmit={start}>
        <Link className="btn btn-ghost btn-sm" to={`/workflows/${id}`}>
          <ArrowLeft size={14} /> 画布
        </Link>
        <span className="msg-muted" style={{ fontSize: 13, fontWeight: 500 }}>{definition.data?.name}</span>
        <input className="input" aria-label="运行输入" value={input} onChange={(e) => setInput(e.target.value)} />
        <button className="btn btn-primary btn-sm" type="submit" disabled={isRunning}>
          {isRunning ? <><RotateCcw size={13} className="animate-spin" /> 运行中</> : <><Play size={13} /> 运行</>}
        </button>
        {status === "done" && <span className="badge badge-green">完成</span>}
        {status === "failed" && <span className="badge badge-red">失败</span>}
      </form>

      <div className="run-body">
        <div className="run-canvas">
          <RunLiveProvider value={live}>
            <ReactFlow
              nodes={definition.data?.graph_json.nodes || []}
              edges={definition.data?.graph_json.edges || []}
              nodeTypes={nodeTypes}
              fitView
              nodesDraggable={false}
              nodesConnectable={false}
            >
              <Background />
            </ReactFlow>
          </RunLiveProvider>
        </div>

        <aside className="run-side">
          <div className="run-side-title" style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <Brain size={15} /> 思考过程
          </div>

          {error && <p className="msg-error"><span>⚠</span> {error}</p>}

          <ThinkingPanel nodes={labels} live={live} />

          {interrupt && (
            <div className="interrupt-box">
              <p className="interrupt-title">⏸ 等待确认</p>
              <p style={{ fontSize: 13, color: "#78350f" }}>这一步暂停，等你查看后继续。</p>
              <textarea
                className="input"
                value={interrupt.value}
                onChange={(e) => setInterrupt({ ...interrupt, value: e.target.value })}
                style={{ fontSize: 13 }}
              />
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn btn-primary btn-sm" type="button" onClick={() => void resume("approve")}>
                  继续执行
                </button>
                <button className="btn btn-danger btn-sm" type="button" onClick={() => void resume("reject")}>
                  停止
                </button>
              </div>
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}
