/**
 * AdminPanel.tsx
 * Redirects to /superadmin — the legacy /admin dual-system has been removed.
 * All user management, audit log, and feature flags are now in SuperAdminDashboard.
 */
import React from 'react';
import { Navigate } from 'react-router-dom';

const AdminPanel: React.FC = () => <Navigate to="/superadmin" replace />;
export default AdminPanel;
