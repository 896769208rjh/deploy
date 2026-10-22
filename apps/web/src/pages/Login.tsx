import { Sparkles } from "lucide-react";
import { FormEvent, useState } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth";

export function LoginPage() {
  const { user, login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  if (user) return <Navigate to="/workflows" replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setError("");
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, displayName);
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败，请重试");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <div className="auth-logo">
          <Sparkles size={20} color="#fff" />
        </div>
        <h1 className="auth-title">{mode === "login" ? "欢迎回来" : "创建账号"}</h1>
        <p className="auth-sub">
          {mode === "login"
            ? "登录后开始搭建你的 AI 工作流"
            : "注册后即可搭建工作流、生成视频、管理书签"}
        </p>

        <form className="auth-stack" onSubmit={submit}>
          {mode === "register" && (
            <label className="label">
              显示名称
              <input className="input" value={displayName} placeholder="你的名字"
                onChange={(e) => setDisplayName(e.target.value)} required />
            </label>
          )}
          <label className="label">
            邮箱
            <input className="input" type="email" value={email} placeholder="you@example.com"
              onChange={(e) => setEmail(e.target.value)} required />
          </label>
          <label className="label">
            密码
            <input className="input" type="password" minLength={8} value={password}
              placeholder="至少 8 位" onChange={(e) => setPassword(e.target.value)} required />
          </label>

          {error && <p className="msg-error"><span>⚠</span> {error}</p>}

          <button className="btn btn-primary" style={{ justifyContent: "center" }}
            disabled={pending} type="submit">
            {pending ? "请稍候…" : mode === "login" ? "登录" : "注册并进入"}
          </button>

          <p className="auth-divider">— 或 —</p>

          <button className="btn btn-secondary" style={{ justifyContent: "center" }} type="button"
            onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}>
            {mode === "login" ? "没有账号，去注册" : "已有账号，去登录"}
          </button>
        </form>
      </div>
    </div>
  );
}

