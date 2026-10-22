import { useQuery } from "@tanstack/react-query";
import {
  Background,
  Controls,
  ReactFlow,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { BrainCircuit, GitBranch, Globe, Play, Save, User, Video } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { nodeTypes } from "../components/nodes";

type Definition = { id: string; name: string; graph_json: { nodes: Node[]; edges: Edge[] } };

const starters: Record<string, Record<string, unknown>> = {
  llm: { label: "写提示词", model: "mock", apiBase: "https://api.deepseek.com/v1", apiKey: "", systemPrompt: "把想法写成一条视频提示词。", userPrompt: "{{input}}" },
  human: { label: "确认提示词" },
  http: { label: "外部请求", method: "GET", url: "https://example.com", body: "" },
  condition: { label: "是否包含", equals: "" },
  media: { label: "生成视频", prompt: "{{prev}}" },
};

const addButtons = [
  { type: "llm", label: "模型", icon: BrainCircuit },
  { type: "human", label: "确认", icon: User },
  { type: "http", label: "请求", icon: Globe },
  { type: "condition", label: "条件", icon: GitBranch },
  { type: "media", label: "视频", icon: Video },
];

export function WorkflowEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [name, setName] = useState("未命名工作流");
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const query = useQuery({
    queryKey: ["definition", id],
    enabled: Boolean(id),
    queryFn: () => api<Definition>(`/api/workflow/definitions/${id}`),
  });

  useEffect(() => {
    if (!query.data) return;
    setName(query.data.name);
    setNodes(query.data.graph_json.nodes || []);
    setEdges(query.data.graph_json.edges || []);
  }, [query.data, setEdges, setNodes]);

  function addNode(type: string) {
    const nodeId = crypto.randomUUID();
    setNodes((current) => [
      ...current,
      { id: nodeId, type, position: { x: 80 + current.length * 40, y: 80 + current.length * 30 }, data: { ...starters[type] } },
    ]);
    setSelected(nodeId);
  }

  async function save(event?: FormEvent) {
    event?.preventDefault();
    setSaving(true);
    setError("");
    try {
      const body = { name, graph_json: { nodes, edges } };
      if (id) {
        await api(`/api/workflow/definitions/${id}`, { method: "PUT", body: JSON.stringify(body) });
      } else {
        const created = await api<Definition>("/api/workflow/definitions", { method: "POST", body: JSON.stringify(body) });
        navigate(`/workflows/${created.id}`, { replace: true });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  const current = nodes.find((node) => node.id === selected);

  function patch(partial: Record<string, unknown>) {
    if (!current) return;
    setNodes((items) => items.map((node) => (node.id === current.id ? { ...node, data: { ...node.data, ...partial } } : node)));
  }

  return (
    <section className="editor-page">
      <form className="editor-topbar" onSubmit={save}>
        <Link className="btn btn-ghost btn-sm" to="/workflows">← 返回</Link>
        <input className="input" aria-label="工作流名称" value={name} onChange={(e) => setName(e.target.value)} />
        <button className="btn btn-primary btn-sm" type="submit" disabled={saving}>
          <Save size={14} /> {saving ? "保存中" : "保存"}
        </button>
        {id && (
          <Link className="btn btn-secondary btn-sm" to={`/workflows/${id}/run`}>
            <Play size={14} /> 运行
          </Link>
        )}
        {error && <span className="msg-error"><span>⚠</span> {error}</span>}
      </form>

      <div className="editor-body">
        <div className="editor-canvas">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={(connection: Connection) => setEdges((items) => addEdge(connection, items))}
            nodeTypes={nodeTypes}
            onSelectionChange={({ nodes: picked }) => setSelected(picked[0]?.id || null)}
            fitView
          >
            <Background />
            <Controls />
          </ReactFlow>
        </div>

        <aside className="editor-panel">
          <div className="editor-panel-title">添加节点</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {addButtons.map(({ type, label, icon: Icon }) => (
              <button key={type} className="btn btn-secondary btn-sm" type="button" onClick={() => addNode(type)}>
                <Icon size={13} /> {label}
              </button>
            ))}
          </div>

          <div className="editor-panel-title" style={{ marginTop: 8 }}>节点配置</div>
          {!current && <p className="msg-muted">选中画布上的节点后编辑它。模型填 mock 可在没有密钥时演练流式输出。</p>}
          {current && (
            <div className="form-stack">
              <label className="label">
                名称
                <input className="input" value={String(current.data.label || "")} onChange={(e) => patch({ label: e.target.value })} />
              </label>
              {current.type === "llm" && (
                <>
                  <label className="label">模型
                    <input className="input" value={String(current.data.model || "")} onChange={(e) => patch({ model: e.target.value })} placeholder="mock / deepseek-chat" />
                  </label>
                  <label className="label">接口地址
                    <input className="input" value={String(current.data.apiBase || "")} onChange={(e) => patch({ apiBase: e.target.value })} />
                  </label>
                  <label className="label">密钥
                    <input className="input" type="password" value={String(current.data.apiKey || "")} placeholder={current.data.hasApiKey ? "已保存，留空则保持原密钥" : "sk-..."} onChange={(e) => patch({ apiKey: e.target.value })} />
                  </label>
                  <label className="label">系统提示
                    <textarea className="input" value={String(current.data.systemPrompt || "")} onChange={(e) => patch({ systemPrompt: e.target.value })} />
                  </label>
                  <label className="label">用户提示
                    <textarea className="input" value={String(current.data.userPrompt || "")} onChange={(e) => patch({ userPrompt: e.target.value })} />
                  </label>
                </>
              )}
              {current.type === "http" && (
                <>
                  <label className="label">方法
                    <select className="select" value={String(current.data.method || "GET")} onChange={(e) => patch({ method: e.target.value })}>
                      <option>GET</option><option>POST</option><option>PUT</option><option>DELETE</option>
                    </select>
                  </label>
                  <label className="label">网址
                    <input className="input" value={String(current.data.url || "")} onChange={(e) => patch({ url: e.target.value })} />
                  </label>
                  <label className="label">请求体
                    <textarea className="input" value={String(current.data.body || "")} onChange={(e) => patch({ body: e.target.value })} />
                  </label>
                </>
              )}
              {current.type === "condition" && (
                <label className="label">包含文本
                  <input className="input" value={String(current.data.equals || "")} onChange={(e) => patch({ equals: e.target.value })} />
                </label>
              )}
              {current.type === "media" && (
                <label className="label">提示词
                  <textarea className="input" value={String(current.data.prompt || "")} onChange={(e) => patch({ prompt: e.target.value })} />
                </label>
              )}
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}
