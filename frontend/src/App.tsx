import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { AppLayout } from "./components/layout/AppLayout";
import { LoadingState } from "./components/feedback";
import Setup from "./pages/Setup";
import Login from "./pages/Login";
import Overview from "./pages/Overview";
import Services from "./pages/Services";
import ServiceDetail from "./pages/ServiceDetail";
import Containers from "./pages/Containers";
import Ports from "./pages/Ports";
import Deployments from "./pages/Deployments";
import DeploymentDetail from "./pages/DeploymentDetail";
import Resources from "./pages/Resources";
import Events from "./pages/Events";
import Settings from "./pages/Settings";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "loading") {
    return (
      <div className="flex h-full items-center justify-center">
        <LoadingState label="세션 확인 중…" />
      </div>
    );
  }
  if (status === "setup") return <Navigate to="/setup" replace />;
  if (status === "anonymous") {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return <>{children}</>;
}

function RedirectIfAuthenticated({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  if (status === "loading") {
    return (
      <div className="flex h-full items-center justify-center">
        <LoadingState label="세션 확인 중…" />
      </div>
    );
  }
  if (status === "authenticated") return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route
          path="/setup"
          element={
            <RedirectIfAuthenticated>
              <Setup />
            </RedirectIfAuthenticated>
          }
        />
        <Route
          path="/login"
          element={
            <RedirectIfAuthenticated>
              <Login />
            </RedirectIfAuthenticated>
          }
        />
        <Route
          element={
            <RequireAuth>
              <AppLayout />
            </RequireAuth>
          }
        >
          <Route path="/" element={<Overview />} />
          <Route path="/services" element={<Services />} />
          <Route path="/services/:serviceId" element={<ServiceDetail />} />
          <Route path="/containers" element={<Containers />} />
          <Route path="/ports" element={<Ports />} />
          <Route path="/deployments" element={<Deployments />} />
          <Route path="/deployments/:deploymentId" element={<DeploymentDetail />} />
          <Route path="/resources" element={<Resources />} />
          <Route path="/events" element={<Events />} />
          <Route path="/settings" element={<Settings />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}
