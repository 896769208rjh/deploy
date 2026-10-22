import { useQuery } from "@tanstack/react-query";
import { GitBranch, Plus } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api";

type Definition = { id: string; name: string; updated_at: string };

export function WorkflowList() {
  const query = useQuery({
    queryKey: ["definitions"],
    queryFn: () => api<Definition[]>("/api/workflow/definitions"),
  });

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">工作流</h1>
          <p className="page-desc">把模型、判断、人工确认连成一条流水线。</p>
        </div>
        <Link className="btn btn-primary" to="/workflows/new">
          <Plus size={15} /> 新建
        </Link>
      </div>

      {query.isLoading && <p className="msg-muted">正在读取工作流…</p>}
      {query.error && <p className="msg-error"><span>⚠</span> {(query.error as Error).message}</p>}

      {query.data && query.data.length === 0 && (
        <div className="empty-state">
          <GitBranch size={40} />
          <p className="empty-state-title">还没有工作流</p>
          <p className="empty-state-desc">新建一条，先放进一个模型节点试试。</p>
        </div>
      )}

      <div className="card-grid">
        {query.data?.map((item) => (
          <Link className="wf-card" key={item.id} to={`/workflows/${item.id}`}>
            <div className="wf-card-name">{item.name}</div>
            <div className="wf-card-hint">打开画布编辑</div>
            <div className="wf-card-meta">
              <GitBranch size={12} />
              <span>{item.id.slice(0, 8)}</span>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
