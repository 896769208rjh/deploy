import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader, Save, Zap } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";

export type MediaConfig = { id: string; base_url: string; has_api_key: boolean; model: string; provider?: string };
type Provider = { id: string; name: string; base_url: string; hint: string };
type Model = { id: string; name: string; owned_by?: string; source: "discovered" | "preset" };
type ProbeResult = { models: Model[]; endpoint_type: string; source: string; filtered_count: number; hint?: string };

export function VideoConfig({ current }: { current?: MediaConfig }) {
  const client = useQueryClient();
  const providers = useQuery({ queryKey: ["video-providers"], queryFn: () => api<Provider[]>("/api/media/providers") });
  const [baseUrl, setBaseUrl] = useState("mock");
  const [provider, setProvider] = useState("auto");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("mock");
  const [manual, setManual] = useState(false);
  const [result, setResult] = useState<ProbeResult | null>(null);
  const [probing, setProbing] = useState(false);
  const [probeError, setProbeError] = useState("");

  useEffect(() => {
    if (!current) return;
    setBaseUrl(current.base_url);
    setProvider(current.provider || "auto");
    setModel(current.model);
    setApiKey("");
    setManual(Boolean(current.model));
    setResult(null);
  }, [current?.id, current?.base_url, current?.provider, current?.model]);

  const isMock = baseUrl.trim().toLowerCase() === "mock";
  const canReuseKey = Boolean(current?.has_api_key && current.base_url === baseUrl.trim() && (current.provider || "auto") === provider);
  const selectedProvider = providers.data?.find((item) => item.id === provider);
  const canSave = Boolean(baseUrl.trim() && (isMock || apiKey.trim() || canReuseKey) && (isMock || model.trim() || provider === "custom"));

  function resetDiscovery() {
    setResult(null);
    setModel("");
    setProbeError("");
    setManual(false);
  }

  const save = useMutation({
    mutationFn: () => api(current ? `/api/media/configs/${current.id}` : "/api/media/configs", {
      method: current ? "PUT" : "POST",
      body: JSON.stringify({ base_url: baseUrl.trim(), api_key: apiKey.trim(), model: isMock ? "mock" : model.trim(), provider }),
    }),
    onSuccess: () => {
      setApiKey("");
      void client.invalidateQueries({ queryKey: ["media-config"] });
    },
  });

  async function probe() {
    setProbing(true);
    setProbeError("");
    setResult(null);
    try {
      const next = await api<ProbeResult>("/api/media/configs/probe", {
        method: "POST",
        body: JSON.stringify({ base_url: baseUrl.trim(), api_key: apiKey.trim(), provider, config_id: canReuseKey ? current?.id : undefined }),
      });
      setResult(next);
      setModel(next.models.some((item) => item.id === model) ? model : next.models[0]?.id || "");
      setManual(next.models.length === 0);
    } catch (err) {
      setProbeError(err instanceof Error ? err.message : "探测失败");
    } finally {
      setProbing(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <div className="panel">
      <div className="panel-title">视频接口配置</div>
      <p className="panel-desc">选择平台或中转商的接口类型，读取并筛选文生视频模型。地址填 mock 可使用样片。</p>
      <form className="form-stack" onSubmit={submit}>
        <label className="label">
          接口类型
          <select className="select" value={provider} disabled={probing || save.isPending} onChange={(event) => {
            const value = event.target.value;
            setProvider(value);
            const preset = providers.data?.find((item) => item.id === value);
            if (preset) setBaseUrl(preset.base_url);
            setApiKey("");
            resetDiscovery();
          }}>
            <option value="auto">自动识别（按接口地址）</option>
            {providers.data?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
          <span className="msg-muted">中转服务请按其文档选择协议，模型品牌不决定接口类型。</span>
        </label>
        {selectedProvider?.hint && <p className="msg-muted">{selectedProvider.hint}</p>}
        {providers.error && <p className="msg-error">平台目录加载失败，可刷新重试。</p>}
        <div className="form-row">
          <label className="label">
            接口地址
            <input className="input" value={baseUrl} disabled={probing || save.isPending} placeholder="mock 或平台 API 地址" onChange={(event) => { setBaseUrl(event.target.value); resetDiscovery(); }} />
          </label>
          <label className="label">
            {provider === "kling" ? "AccessKey:SecretKey 或 JWT" : provider === "tencent" ? "SecretId:SecretKey" : "密钥"}
            <input className="input" type="password" autoComplete="off" value={apiKey} disabled={probing || save.isPending} placeholder={canReuseKey ? "已保存，留空可继续使用" : "填写该平台的 API Key"} onChange={(event) => { setApiKey(event.target.value); setResult(null); setProbeError(""); }} />
          </label>
        </div>
        <div>
          <button className="btn btn-secondary btn-sm" type="button" disabled={probing || save.isPending || !baseUrl.trim() || (!isMock && !apiKey.trim() && !canReuseKey)} onClick={() => void probe()}>
            {probing ? <><Loader size={13} className="animate-spin" /> 读取中…</> : <><Zap size={13} /> 读取文生视频模型</>}
          </button>
          {probeError && <p className="msg-error" style={{ marginTop: 6 }}>{probeError}</p>}
        </div>
        {result && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <p className="msg-muted">
              {result.source === "preset" ? "官方预设" : "接口返回"}：{result.models.length} 个文生视频模型
              {result.filtered_count > 0 && <>，已过滤 {result.filtered_count} 个其他模型</>}
            </p>
            {result.hint && <p className="msg-muted">{result.hint}</p>}
            {!manual && result.models.length > 0 && (
              <label className="label">选择模型
                <select className="select" value={model} disabled={save.isPending} onChange={(event) => setModel(event.target.value)}>
                  {result.models.map((item) => <option key={item.id} value={item.id}>{item.name !== item.id ? `${item.name} (${item.id})` : item.id}</option>)}
                </select>
              </label>
            )}
          </div>
        )}
        {!isMock && (
          <>
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
              <input type="checkbox" checked={manual} onChange={(event) => {
                setManual(event.target.checked);
                if (!event.target.checked && result?.models.length) setModel(result.models[0].id);
              }} /> 手动填写模型 ID / 接入点 ID
            </label>
            {manual && <label className="label">文生视频模型 ID
              <input className="input" value={model} disabled={save.isPending || probing} placeholder="填写平台控制台中已开通的模型 ID" onChange={(event) => setModel(event.target.value)} />
            </label>}
          </>
        )}
        {save.error && <p className="msg-error">{(save.error as Error).message}</p>}
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <button className="btn btn-primary btn-sm" type="submit" disabled={!canSave || save.isPending || probing}>
            <Save size={13} /> {save.isPending ? "保存中…" : "保存配置"}
          </button>
          {save.isSuccess && <span className="msg-muted" role="status">配置已保存</span>}
          {current && <span className="msg-muted">当前：{current.base_url}{current.model && ` · ${current.model}`}</span>}
        </div>
      </form>
    </div>
  );
}
