import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Intake from "./pages/Intake";
import ReviewQueue from "./pages/ReviewQueue";
import ReportDetail from "./pages/ReportDetail";
import Dashboard from "./pages/Dashboard";
import UserManagement from "./pages/UserManagement";
import AuditLog from "./pages/AuditLog";

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }
          >
            <Route path="/" element={<Dashboard />} />
            <Route path="/intake" element={<ProtectedRoute roles={["doctor", "admin"]}><Intake /></ProtectedRoute>} />
            <Route path="/queue" element={<ProtectedRoute roles={["pharmacist", "admin", "researcher"]}><ReviewQueue /></ProtectedRoute>} />
            <Route path="/reports/:id" element={<ReportDetail />} />
            <Route path="/audit-logs" element={<ProtectedRoute roles={["admin", "pharmacist"]}><AuditLog /></ProtectedRoute>} />
            <Route path="/users" element={<ProtectedRoute roles={["admin"]}><UserManagement /></ProtectedRoute>} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
