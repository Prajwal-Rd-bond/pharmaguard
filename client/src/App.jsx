import { BrowserRouter, Routes, Route, useLocation, Navigate, useNavigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import Layout from "./components/Layout";
import IntroScreen from "./components/intro/IntroScreen";
import React, { Suspense, useEffect } from "react";
import { AnimatePresence } from "framer-motion";
import PageTransition from "./components/PageTransition";

import Intake from "./pages/Intake";
import ReviewQueue from "./pages/ReviewQueue";
import ReportDetail from "./pages/ReportDetail";
import Dashboard from "./pages/Dashboard";
import UserManagement from "./pages/UserManagement";
import AuditLog from "./pages/AuditLog";

const Login = React.lazy(() => import("./pages/Login"));

// Guard to ensure they see the intro before accessing login directly
function IntroGuard({ children }) {
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    console.log("IntroGuard running", { pathname: location.pathname, pg_intro_seen: sessionStorage.getItem('pg_intro_seen') });
    // If they haven't seen the intro and they try to load /login, send them to the intro first
    // Note: We bypass this check if ?intro=1 is in the URL for testing
    const params = new URLSearchParams(location.search);
    if (sessionStorage.getItem('pg_intro_seen') !== '1' && !params.has('intro') && location.pathname === '/login') {
      navigate('/', { replace: true });
    }
  }, [navigate, location.pathname, location.search]);

  return children;
}

function AnimatedRoutes() {
  const location = useLocation();

  return (
    <IntroGuard>
      <AnimatePresence mode="wait">
        <Routes location={location} key={location.pathname}>
          <Route path="/" element={<IntroScreen />} />
          
          <Route 
            path="/login" 
            element={
              <PageTransition>
                <Suspense fallback={<div className="min-h-screen bg-ink-50" />}>
                  <Login />
                </Suspense>
              </PageTransition>
            } 
          />
          
          <Route
            element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }
          >
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/intake" element={<ProtectedRoute roles={["doctor", "admin"]}><Intake /></ProtectedRoute>} />
            <Route path="/queue" element={<ProtectedRoute roles={["pharmacist", "admin", "researcher"]}><ReviewQueue /></ProtectedRoute>} />
            <Route path="/reports/:id" element={<ReportDetail />} />
            <Route path="/audit-logs" element={<ProtectedRoute roles={["admin", "pharmacist"]}><AuditLog /></ProtectedRoute>} />
            <Route path="/users" element={<ProtectedRoute roles={["admin"]}><UserManagement /></ProtectedRoute>} />
          </Route>
        </Routes>
      </AnimatePresence>
    </IntroGuard>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AnimatedRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
