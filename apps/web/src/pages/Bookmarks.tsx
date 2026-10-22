import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, Globe, Link2, Trash2 } from "lucide-react";
import { FormEvent, useState } from "react";
import { api } from "../api";

type Bookmark = { id: string; url: string; title: string; favicon_url: string };

export function Bookmarks() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["bookmarks"], queryFn: () => api<Bookmark[]>("/api/bookmarks") });
  const [url, setUrl] = useState("https://github.com");
  const create = useMutation({
    mutationFn: () => api("/api/bookmarks", { method: "POST", body: JSON.stringify({ url }) }),
    onSuccess: () => { client.invalidateQueries({ queryKey: ["bookmarks"] }); setUrl(""); },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/bookmarks/${id}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["bookmarks"] }),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    create.mutate();
  }

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">书签</h1>
          <p className="page-desc">添加网址，自动抓取图标，点击即可跳转。</p>
        </div>
      </div>

      <form className="panel" onSubmit={submit} style={{ padding: 16 }}>
        <div style={{ display: "flex", gap: 10 }}>
          <div style={{ position: "relative", flex: 1 }}>
            <Link2 size={15} style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--color-text-faint)" }} />
            <input
              className="input"
              style={{ paddingLeft: 34 }}
              aria-label="网址"
              value={url}
              placeholder="https://example.com"
              onChange={(e) => setUrl(e.target.value)}
            />
          </div>
          <button className="btn btn-primary" disabled={create.isPending} type="submit">
            {create.isPending ? "抓取中…" : "添加"}
          </button>
        </div>
        {create.error && <p className="msg-error" style={{ marginTop: 8 }}><span>⚠</span> {(create.error as Error).message}</p>}
      </form>

      {query.data && query.data.length === 0 && (
        <div className="empty-state">
          <Boxes size={40} />
          <p className="empty-state-title">还没有书签</p>
          <p className="empty-state-desc">添加一个网址，这里会显示它的图标。点击图标即可打开。</p>
        </div>
      )}

      <div className="bookmark-grid">
        {query.data?.map((item) => (
          <a key={item.id} className="bookmark-item" href={item.url} target="_blank" rel="noreferrer">
            {item.favicon_url ? (
              <img className="bookmark-favicon" src={item.favicon_url} alt="" />
            ) : (
              <span className="bookmark-favicon-fallback"><Globe size={15} /></span>
            )}
            <div className="bookmark-info">
              <div className="bookmark-title">{item.title || item.url}</div>
              <div className="bookmark-url">{item.url}</div>
            </div>
            <button
              className="btn btn-ghost btn-sm bookmark-delete"
              type="button"
              onClick={(e) => { e.preventDefault(); remove.mutate(item.id); }}
              aria-label="删除"
              title="删除"
            >
              <Trash2 size={14} />
            </button>
          </a>
        ))}
      </div>
    </section>
  );
}
