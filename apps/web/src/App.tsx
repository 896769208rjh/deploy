import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth";
import { Shell } from "./components/Shell";
import { BlogChat } from "./pages/BlogChat";
import { Bookmarks } from "./pages/Bookmarks";
import { LoginPage } from "./pages/Login";
import { Plaza, Profile } from "./pages/MediaPages";
import { WorkflowEditor } from "./pages/WorkflowEditor";
import { WorkflowList } from "./pages/WorkflowList";
import { WorkflowRun } from "./pages/WorkflowRun";

const queryClient = new QueryClient();

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<Shell />}>
              <Route path="/" element={<Navigate to="/workflows" replace />} />
              <Route path="/workflows" element={<WorkflowList />} />
              <Route path="/workflows/new" element={<WorkflowEditor />} />
              <Route path="/workflows/:id" element={<WorkflowEditor />} />
              <Route path="/workflows/:id/run" element={<WorkflowRun />} />
              <Route path="/plaza" element={<Plaza />} />
              <Route path="/profile" element={<Profile />} />
              <Route path="/blog" element={<BlogChat />} />
              <Route path="/bookmarks" element={<Bookmarks />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}
