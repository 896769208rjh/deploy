import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookMarked, ExternalLink, Loader, Plus, RefreshCw, Send, Sparkles } from "lucide-react";
import { FormEvent, useRef, useState } from "react";
import { api, token } from "../api";
import { useAuth } from "../auth";

type Source = { id: string; type: string; uri: string; last_ingested_at: string | null };
type ChatMessage = { role: "user" | "ai"; content: string };

export function BlogChat() {
  const { user } = useAuth();
  const client = useQueryClient();
  const sources = useQuery({ queryKey: ["sources"], queryFn: () => api<Source[]>("/api/blog/sources") });
  const [type, setType] = useState("rss");
  const [uri, setUri] = useState("");
  const [message, setMessage] = useState("有没有适合雨夜场景的描述？");
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const [thinking, setThinking] = useState("");
  const [hits, setHits] = useState<{ title: string; url: string }[]>([]);
  const [error, setError] = useState("");
  const [asking, setAsking] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const addSource = useMutation({
    mutationFn: () => api("/api/blog/sources", { method: "POST", body: JSON.stringify({ type, uri }) }),
    onSuccess: () => { client.invalidateQueries({ queryKey: ["sources"] }); setUri(""); },
  });
  const ingest = useMutation({
    mutationFn: () => api<{ chunks: number }>("/api/blog/ingest", { method: "POST" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["sources"] }),
  });

  async function ask(e: FormEvent) {
    e.preventDefault();
    if (!message.trim()) return;
    const userMsg = message;
    setMessage("");
    setHistory((h) => [...h, { role: "user", content: userMsg }]);
    setThinking("");
    setHits([]);
    setError("");
    setAsking(true);

    let aiContent = "";
    try {
      const response = await fetch("/api/blog/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token()}` },
        body: JSON.stringify({ message: userMsg, session_id: crypto.randomUUID() }),
      });
      if (!response.ok || !response.body) { setError("回答没有开始"); setAsking(false); return; }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const part of parts) {
          const line = part.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;
          const payload = JSON.parse(line.slice(6));
          if (payload.type === "sources") setHits(payload.items || []);
          if (payload.type === "thinking_token") setThinking((v) => v + payload.content);
          if (payload.type === "content_token") { aiContent += payload.content; setHistory((h) => { const updated = [...h]; if (updated[updated.length - 1]?.role === "ai") { updated[updated.length - 1] = { role: "ai", content: aiContent }; } else { updated.push({ role: "ai", content: aiContent }); } return updated; }); }
          if (payload.type === "error") setError(payload.detail || "回答失败");
        }
      }
    } catch {
      setError("网络错误，请重试");
    } finally {
      setAsking(false);
      setThinking("");
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 100);
    }
  }

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">博客助手</h1>
          <p className="page-desc">基于 DeepSeek 和本地向量检索，帮你找到相关文章。</p>
        </div>
      </div>

      {/* Admin: data sources panel */}
      {user?.role === "admin" && (
        <div className="panel">
          <div className="panel-title">数据源管理</div>
          <div className="panel-desc">添加 RSS 或文章地址，摄取后才能检索。</div>
          <form className="form-stack" onSubmit={(e) => { e.preventDefault(); addSource.mutate(); }}>
            <div className="form-row">
              <label className="label" style={{ flex: "0 0 auto", width: 100 }}>
                类型
                <select className="select" value={type} onChange={(e) => setType(e.target.value)}>
                  <option value="rss">RSS</option>
                  <option value="url">URL</option>
                  <option value="internal">内部</option>
                </select>
              </label>
              <label className="label">
                地址
                <input className="input" value={uri} placeholder="https://..." onChange={(e) => setUri(e.target.value)} />
              </label>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn btn-primary btn-sm" type="submit" disabled={addSource.isPending}>
                <Plus size={13} /> 添加数据源
              </button>
              <button className="btn btn-secondary btn-sm" type="button" onClick={() => ingest.mutate()} disabled={ingest.isPending}>
                {ingest.isPending ? <><Loader size={13} className="animate-spin" /> 摄取中</> : <><RefreshCw size={13} /> 重新摄取</>}
              </button>
            </div>
            {addSource.error && <p className="msg-error">⚠ {(addSource.error as Error).message}</p>}
            {ingest.data && <p className="msg-muted">✓ 写入 {ingest.data.chunks} 个片段</p>}
          </form>

          {sources.data && sources.data.length > 0 && (
            <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 6 }}>
              {sources.data.map((item) => (
                <div className="source-item" key={item.id}>
                  <span className="source-type-badge">{item.type}</span>
                  <span style={{ flex: 1, overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis", color: "var(--color-text-muted)", marginLeft: 8 }}>{item.uri}</span>
                  {item.last_ingested_at && <span style={{ fontSize: 11, color: "var(--color-text-faint)" }}>已摄取</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Chat history */}
      {history.length > 0 && (
        <div className="panel" style={{ padding: "16px" }}>
          <div className="chat-history">
            {history.map((msg, i) => (
              <div key={i} className={`chat-bubble ${msg.role === "user" ? "chat-bubble-user" : "chat-bubble-ai"}`}>
                {msg.role === "ai" && (
                  <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 4, fontSize: 12, color: "var(--color-text-faint)" }}>
                    <Sparkles size={11} /> DeepSeek
                  </div>
                )}
                {msg.content}
              </div>
            ))}
            {asking && thinking && (
              <div className="chat-thinking">
                <Sparkles size={11} style={{ display: "inline", marginRight: 4 }} />
                思考中…
              </div>
            )}
            {error && <p className="msg-error"><span>⚠</span> {error}</p>}
          </div>

          {hits.length > 0 && (
            <div className="chat-sources" style={{ marginTop: 12 }}>
              <div className="chat-source-label"><BookMarked size={11} style={{ display: "inline", marginRight: 4 }} />相关文章</div>
              {hits.map((hit) => (
                <a key={hit.url + hit.title} className="chat-source-link" href={hit.url} target="_blank" rel="noreferrer">
                  <ExternalLink size={11} /> {hit.title}
                </a>
              ))}
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      )}

      {/* Input */}
      <form onSubmit={ask}>
        <div className="chat-input-row">
          <textarea
            className="input"
            value={message}
            placeholder="问点什么…"
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void ask(e as unknown as FormEvent); } }}
          />
          <button className="btn btn-primary" type="submit" disabled={asking} style={{ alignSelf: "flex-end" }}>
            {asking ? <Loader size={15} className="animate-spin" /> : <Send size={15} />}
          </button>
        </div>
        <p className="msg-muted" style={{ marginTop: 6 }}>Enter 发送，Shift+Enter 换行</p>
      </form>
    </section>
  );
}
