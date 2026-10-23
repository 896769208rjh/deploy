import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clapperboard, Eye, EyeOff, Film, Loader, Play, RefreshCw, Sparkles } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { VideoConfig, type MediaConfig } from "../components/VideoConfig";

type Post = { id: string; title: string; prompt: string; video_url: string; visibility: string };

export function Plaza() {
  const query = useQuery({ queryKey: ["plaza"], queryFn: () => api<Post[]>("/api/media/plaza") });

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">广场</h1>
          <p className="page-desc">所有公开的 AI 视频作品。</p>
        </div>
      </div>
      {query.isLoading && <p className="msg-muted">正在读取广场…</p>}
      {query.data?.length === 0 && (
        <div className="empty-state">
          <Sparkles size={40} />
          <p className="empty-state-title">广场还是空的</p>
          <p className="empty-state-desc">在个人空间生成视频并公开后会出现在这里。</p>
        </div>
      )}
      <VideoGrid posts={query.data || []} />
    </section>
  );
}

export function Profile() {
  const client = useQueryClient();
  const posts = useQuery({ queryKey: ["profile"], queryFn: () => api<Post[]>("/api/media/profile") });
  const configs = useQuery({ queryKey: ["media-config"], queryFn: () => api<MediaConfig[]>("/api/media/configs") });

  const [prompt, setPrompt] = useState("雨夜便利店，黄雨衣，推门");
  const [generateError, setGenerateError] = useState("");

  const currentConfig = configs.data?.[0];

  const generate = useMutation({
    mutationFn: (publish: boolean) =>
      api("/api/media/generate", {
        method: "POST",
        body: JSON.stringify({ prompt, title: prompt.slice(0, 40), publish, model: currentConfig?.model || "" }),
      }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["profile"] });
      client.invalidateQueries({ queryKey: ["plaza"] });
      setGenerateError("");
    },
    onError: (err) => setGenerateError(err instanceof Error ? err.message : "生成失败"),
  });

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">个人空间</h1>
          <p className="page-desc">配置视频接口，选择模型，生成并发布作品。</p>
        </div>
      </div>

      <VideoConfig current={currentConfig} />

      {/* Generate panel */}
      <div className="panel">
        <div className="panel-title">生成视频</div>
        {currentConfig ? (
          <div style={{ marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
            <span className="badge badge-blue">{currentConfig.base_url}</span>
            {currentConfig.model && <span className="badge badge-gray">{currentConfig.model}</span>}
            <button
              className="btn btn-ghost btn-sm"
              type="button"
              style={{ fontSize: 12 }}
              onClick={() => client.invalidateQueries({ queryKey: ["media-config"] })}
            >
              <RefreshCw size={12} />
            </button>
          </div>
        ) : (
          <p className="msg-muted" style={{ marginBottom: 12 }}>请先在上方配置并保存视频接口。</p>
        )}
        <form className="form-stack" onSubmit={(e) => { e.preventDefault(); setGenerateError(""); generate.mutate(false); }}>
          <label className="label">
            提示词
            <textarea className="input" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          </label>
          {generateError && <p className="msg-error"><span>⚠</span> {generateError}</p>}
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn btn-primary btn-sm" disabled={generate.isPending || !currentConfig} type="submit">
              {generate.isPending ? <><Loader size={13} className="animate-spin" /> 生成中…</> : <><Play size={13} /> 生成到个人空间</>}
            </button>
            <button
              className="btn btn-secondary btn-sm"
              type="button"
              disabled={generate.isPending || !currentConfig}
              onClick={() => { setGenerateError(""); generate.mutate(true); }}
            >
              <Sparkles size={13} /> 生成并公开
            </button>
          </div>
        </form>
      </div>

      {/* Video list */}
      {posts.isLoading && <p className="msg-muted">正在读取作品…</p>}
      {posts.data?.length === 0 && (
        <div className="empty-state">
          <Clapperboard size={40} />
          <p className="empty-state-title">还没有作品</p>
          <p className="empty-state-desc">生成第一个视频吧。</p>
        </div>
      )}
      <VideoGrid
        posts={posts.data || []}
        onToggle={async (post) => {
          await api(`/api/media/posts/${post.id}/visibility`, {
            method: "POST",
            body: JSON.stringify({ visibility: post.visibility === "public" ? "private" : "public" }),
          });
          await client.invalidateQueries({ queryKey: ["profile"] });
          await client.invalidateQueries({ queryKey: ["plaza"] });
        }}
      />
    </section>
  );
}

function VideoGrid({ posts, onToggle }: { posts: Post[]; onToggle?: (post: Post) => void }) {
  if (!posts.length) return null;
  return (
    <div className="video-grid">
      {posts.map((post) => (
        <div key={post.id} className="video-card">
          {post.video_url ? (
            <video className="video-thumb" src={post.video_url} controls />
          ) : (
            <div className="video-thumb-placeholder">
              <Film size={32} />
            </div>
          )}
          <div className="video-card-body">
            <div className="video-card-title">{post.title}</div>
            <div className="video-card-prompt">{post.prompt}</div>
          </div>
          {onToggle && (
            <div className="video-card-footer">
              <button className="btn btn-ghost btn-sm" type="button" onClick={() => onToggle(post)}>
                {post.visibility === "public"
                  ? <><EyeOff size={13} /> 设为私有</>
                  : <><Eye size={13} /> 公开到广场</>}
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
