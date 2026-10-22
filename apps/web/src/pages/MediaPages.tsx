import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clapperboard, ChevronDown, Eye, EyeOff, Film, Loader, Play, RefreshCw, Save, Sparkles, Zap } from "lucide-react";
import { FormEvent, useState } from "react";
import { api } from "../api";

type Post = { id: string; title: string; prompt: string; video_url: string; visibility: string };
type MediaConfig = { id: string; base_url: string; has_api_key: boolean; model: string };
type ProbeModel = { id: string; name: string; owned_by?: string };
type ProbeResult = { models: ProbeModel[]; endpoint_type: string; hint?: string };

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

  const [baseUrl, setBaseUrl] = useState("mock");
  const [apiKey, setApiKey] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [probeResult, setProbeResult] = useState<ProbeResult | null>(null);
  const [probing, setProbing] = useState(false);
  const [probeError, setProbeError] = useState("");
  const [saveError, setSaveError] = useState("");

  const [prompt, setPrompt] = useState("雨夜便利店，黄雨衣，推门");
  const [generateError, setGenerateError] = useState("");

  const currentConfig = configs.data?.[0];

  const saveConfig = useMutation({
    mutationFn: () => api("/api/media/configs", {
      method: "POST",
      body: JSON.stringify({ base_url: baseUrl, api_key: apiKey, model: selectedModel }),
    }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["media-config"] });
      setSaveError("");
    },
    onError: (err) => setSaveError(err instanceof Error ? err.message : "保存失败"),
  });

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

  async function handleProbe() {
    if (!baseUrl.trim() || baseUrl.trim().toLowerCase() === "mock") {
      setProbeResult({ models: [{ id: "mock", name: "样片（mock）" }], endpoint_type: "mock" });
      setSelectedModel("mock");
      return;
    }
    if (!apiKey.trim()) { setProbeError("请先填写密钥再探测模型"); return; }
    setProbing(true);
    setProbeError("");
    setProbeResult(null);
    try {
      const result = await api<ProbeResult>("/api/media/configs/probe", {
        method: "POST",
        body: JSON.stringify({ base_url: baseUrl, api_key: apiKey }),
      });
      setProbeResult(result);
      if (result.models.length > 0) setSelectedModel(result.models[0].id);
    } catch (err) {
      setProbeError(err instanceof Error ? err.message : "探测失败");
    } finally {
      setProbing(false);
    }
  }

  function onSave(e: FormEvent) {
    e.preventDefault();
    saveConfig.mutate();
  }

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">个人空间</h1>
          <p className="page-desc">配置视频接口，选择模型，生成并发布作品。</p>
        </div>
      </div>

      {/* API config panel */}
      <div className="panel">
        <div className="panel-title">视频接口配置</div>
        <div className="panel-desc">
          填写接口地址和密钥，点击<strong>探测模型</strong>获取可用的生成模型列表，再选择后保存。地址填{" "}
          <code style={{ fontFamily: "var(--font-mono)", fontSize: 12, background: "#f1f5f9", padding: "1px 6px", borderRadius: 4 }}>mock</code>{" "}
          直接使用样片。
        </div>
        <form className="form-stack" onSubmit={onSave}>
          {/* URL + Key row */}
          <div className="form-row">
            <label className="label" style={{ flex: "1 1 0" }}>
              接口地址
              <input
                className="input"
                value={baseUrl}
                placeholder="mock 或 https://api.example.com/v1/generate"
                onChange={(e) => { setBaseUrl(e.target.value); setProbeResult(null); setSelectedModel(""); }}
              />
            </label>
            <label className="label" style={{ flex: "1 1 0" }}>
              密钥
              <input
                className="input"
                type="password"
                value={apiKey}
                placeholder="sk-..."
                onChange={(e) => { setApiKey(e.target.value); setProbeResult(null); setSelectedModel(""); }}
              />
            </label>
          </div>

          {/* Probe button */}
          <div>
            <button
              className="btn btn-secondary btn-sm"
              type="button"
              disabled={probing || !baseUrl.trim()}
              onClick={handleProbe}
            >
              {probing
                ? <><Loader size={13} className="animate-spin" /> 探测中…</>
                : <><Zap size={13} /> 探测可用模型</>}
            </button>
            {probeError && <p className="msg-error" style={{ marginTop: 6 }}><span>⚠</span> {probeError}</p>}
          </div>

          {/* Model select — shown only after probe */}
          {probeResult && (
            <div className="animate-fade-in">
              {probeResult.models.length > 0 ? (
                <label className="label">
                  选择模型
                  <div style={{ position: "relative" }}>
                    <select
                      className="select"
                      value={selectedModel}
                      onChange={(e) => setSelectedModel(e.target.value)}
                      style={{ paddingRight: 36, appearance: "none" }}
                    >
                      {probeResult.models.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name !== m.id ? `${m.name} (${m.id})` : m.id}
                          {m.owned_by ? ` · ${m.owned_by}` : ""}
                        </option>
                      ))}
                    </select>
                    <ChevronDown
                      size={15}
                      style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", pointerEvents: "none", color: "var(--color-text-faint)" }}
                    />
                  </div>
                  <span className="msg-muted" style={{ marginTop: 2 }}>
                    探测到 {probeResult.models.length} 个模型
                    {probeResult.endpoint_type === "openai" && " · OpenAI 兼容接口"}
                  </span>
                </label>
              ) : (
                <div style={{ padding: "10px 12px", background: "#fffbeb", border: "1px solid #fbbf24", borderRadius: 8, fontSize: 13, color: "#92400e" }}>
                  <strong>提示：</strong>{probeResult.hint || "未探测到标准模型列表，可直接手动填写模型名称后保存。"}
                  <div style={{ marginTop: 8 }}>
                    <label className="label">
                      手动填写模型名称
                      <input
                        className="input"
                        value={selectedModel}
                        placeholder="例如 wanx-v1、stable-video ..."
                        onChange={(e) => setSelectedModel(e.target.value)}
                      />
                    </label>
                  </div>
                </div>
              )}
            </div>
          )}

          {saveError && <p className="msg-error"><span>⚠</span> {saveError}</p>}

          {/* Save button */}
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <button
              className="btn btn-primary btn-sm"
              type="submit"
              disabled={saveConfig.isPending || (!selectedModel && baseUrl.trim().toLowerCase() !== "mock" && !!probeResult)}
            >
              <Save size={13} /> {saveConfig.isPending ? "保存中…" : "保存配置"}
            </button>
            {currentConfig && (
              <span className="msg-muted">
                当前：<strong>{currentConfig.base_url}</strong>
                {currentConfig.model && <> · 模型：<strong>{currentConfig.model}</strong></>}
              </span>
            )}
          </div>
        </form>
      </div>

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
