import { BookMarked, Boxes, Clapperboard, GitBranch, LogOut, Sparkles } from "lucide-react";
import { NavLink, Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../auth";

const links = [
  { label: "工作流", href: "/workflows", icon: GitBranch },
  { label: "广场", href: "/plaza", icon: Sparkles },
  { label: "个人空间", href: "/profile", icon: Clapperboard },
  { label: "博客助手", href: "/blog", icon: BookMarked },
  { label: "书签", href: "/bookmarks", icon: Boxes },
];

export function Shell() {
  const { user, ready, logout } = useAuth();
  if (!ready)
    return (
      <div className="boot-screen">
        <span className="animate-spin">⏳</span>
        <span>正在确认登录状态</span>
      </div>
    );
  if (!user) return <Navigate to="/login" replace />;

  const initials = user.display_name.slice(0, 1).toUpperCase();

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <span className="sidebar-logo-icon">
            <Sparkles size={16} color="#fff" />
          </span>
          <span className="sidebar-logo-text">创作台</span>
        </div>

        <nav className="sidebar-nav">
          {links.map(({ label, href, icon: Icon }) => (
            <NavLink key={href} to={href} className={({ isActive }) => `sidebar-link ${isActive ? "active" : ""}`}>
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-footer">
          <span className="sidebar-avatar">{initials}</span>
          <div style={{ display: "flex", flexDirection: "column", minWidth: 0, flex: 1 }}>
            <span className="sidebar-user-name" style={{ overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis" }}>
              {user.display_name}
            </span>
            <span className="sidebar-user-role">{user.role === "admin" ? "管理员" : "创作者"}</span>
          </div>
          <button className="sidebar-logout" type="button" onClick={logout} aria-label="退出登录" title="退出登录">
            <LogOut size={15} />
          </button>
        </div>
      </aside>

      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
