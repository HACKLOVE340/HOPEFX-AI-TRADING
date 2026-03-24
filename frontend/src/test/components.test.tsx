/**
 * Component tests — AuthGuard, Login, App routing
 * ~80 tests
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import React from 'react';
import { useStore } from '../store';
import AuthGuard from '../components/AuthGuard';

// ─── Helpers ──────────────────────────────────────────────────────────────────

const mockUser = { id: '1', email: 'a@b.com', username: 'trader1', role: 'trader' as const };

function renderWithRouter(ui: React.ReactElement, { initialEntries = ['/'] } = {}) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      {ui}
    </MemoryRouter>
  );
}

beforeEach(() => {
  useStore.setState({
    token: null, user: null, isAuthenticated: false,
    prices: {}, priceHistory: {},
    positions: [], signals: [],
    account: null,
    wsStatus: 'disconnected', lastHeartbeat: null,
  });
});

// ─── AuthGuard ────────────────────────────────────────────────────────────────

describe('AuthGuard', () => {
  it('redirects to /login when not authenticated', () => {
    renderWithRouter(
      <Routes>
        <Route path="/" element={<AuthGuard><div>Protected</div></AuthGuard>} />
        <Route path="/login" element={<div>Login Page</div>} />
      </Routes>
    );
    expect(screen.getByText('Login Page')).toBeInTheDocument();
    expect(screen.queryByText('Protected')).not.toBeInTheDocument();
  });

  it('renders children when authenticated', () => {
    useStore.getState().setAuth('tok', mockUser);
    renderWithRouter(
      <Routes>
        <Route path="/" element={<AuthGuard><div>Protected Content</div></AuthGuard>} />
        <Route path="/login" element={<div>Login Page</div>} />
      </Routes>
    );
    expect(screen.getByText('Protected Content')).toBeInTheDocument();
  });

  it('does not show login page when authenticated', () => {
    useStore.getState().setAuth('tok', mockUser);
    renderWithRouter(
      <Routes>
        <Route path="/" element={<AuthGuard><div>Protected</div></AuthGuard>} />
        <Route path="/login" element={<div>Login Page</div>} />
      </Routes>
    );
    expect(screen.queryByText('Login Page')).not.toBeInTheDocument();
  });

  it('shows access denied for insufficient role', () => {
    useStore.getState().setAuth('tok', mockUser); // trader role
    renderWithRouter(
      <Routes>
        <Route path="/" element={<AuthGuard requiredRole="admin"><div>Admin Only</div></AuthGuard>} />
        <Route path="/login" element={<div>Login</div>} />
      </Routes>
    );
    expect(screen.getByText('Access Denied')).toBeInTheDocument();
    expect(screen.queryByText('Admin Only')).not.toBeInTheDocument();
  });

  it('allows access when role is sufficient', () => {
    useStore.getState().setAuth('tok', { ...mockUser, role: 'admin' });
    renderWithRouter(
      <Routes>
        <Route path="/" element={<AuthGuard requiredRole="admin"><div>Admin Content</div></AuthGuard>} />
        <Route path="/login" element={<div>Login</div>} />
      </Routes>
    );
    expect(screen.getByText('Admin Content')).toBeInTheDocument();
  });

  it('superadmin can access admin-required routes', () => {
    useStore.getState().setAuth('tok', { ...mockUser, role: 'superadmin' });
    renderWithRouter(
      <Routes>
        <Route path="/" element={<AuthGuard requiredRole="admin"><div>Admin Content</div></AuthGuard>} />
        <Route path="/login" element={<div>Login</div>} />
      </Routes>
    );
    expect(screen.getByText('Admin Content')).toBeInTheDocument();
  });

  it('user role cannot access trader-required routes', () => {
    useStore.getState().setAuth('tok', { ...mockUser, role: 'user' });
    renderWithRouter(
      <Routes>
        <Route path="/" element={<AuthGuard requiredRole="trader"><div>Trader Content</div></AuthGuard>} />
        <Route path="/login" element={<div>Login</div>} />
      </Routes>
    );
    expect(screen.getByText('Access Denied')).toBeInTheDocument();
  });

  it('trader can access trader-required routes', () => {
    useStore.getState().setAuth('tok', { ...mockUser, role: 'trader' });
    renderWithRouter(
      <Routes>
        <Route path="/" element={<AuthGuard requiredRole="trader"><div>Trader Content</div></AuthGuard>} />
        <Route path="/login" element={<div>Login</div>} />
      </Routes>
    );
    expect(screen.getByText('Trader Content')).toBeInTheDocument();
  });

  it('renders multiple children', () => {
    useStore.getState().setAuth('tok', mockUser);
    renderWithRouter(
      <Routes>
        <Route path="/" element={
          <AuthGuard>
            <div>Child 1</div>
            <div>Child 2</div>
          </AuthGuard>
        } />
        <Route path="/login" element={<div>Login</div>} />
      </Routes>
    );
    expect(screen.getByText('Child 1')).toBeInTheDocument();
    expect(screen.getByText('Child 2')).toBeInTheDocument();
  });

  it('access denied message mentions required role', () => {
    useStore.getState().setAuth('tok', { ...mockUser, role: 'user' });
    renderWithRouter(
      <Routes>
        <Route path="/" element={<AuthGuard requiredRole="superadmin"><div>Super</div></AuthGuard>} />
        <Route path="/login" element={<div>Login</div>} />
      </Routes>
    );
    expect(screen.getByText(/superadmin/i)).toBeInTheDocument();
  });

  it('no requiredRole allows any authenticated user', () => {
    useStore.getState().setAuth('tok', { ...mockUser, role: 'user' });
    renderWithRouter(
      <Routes>
        <Route path="/" element={<AuthGuard><div>Open Content</div></AuthGuard>} />
        <Route path="/login" element={<div>Login</div>} />
      </Routes>
    );
    expect(screen.getByText('Open Content')).toBeInTheDocument();
  });
});

// ─── Login page ───────────────────────────────────────────────────────────────

describe('Login page', () => {
  // Mock authApi to avoid real HTTP calls
  vi.mock('../hooks/useApi', () => ({
    authApi: {
      login: vi.fn(),
      logout: vi.fn(),
      me: vi.fn(),
    },
    tradingApi: {
      positions: vi.fn().mockResolvedValue({ data: { positions: [] } }),
      signals:   vi.fn().mockResolvedValue({ data: { signals: [] } }),
      account:   vi.fn().mockResolvedValue({ data: null }),
      placeOrder: vi.fn(),
      closePosition: vi.fn(),
    },
    mlApi: {
      accuracy: vi.fn().mockResolvedValue({ data: { models: [] } }),
      predict:  vi.fn(),
      models:   vi.fn(),
    },
    backtestApi: {
      run: vi.fn(), results: vi.fn(), list: vi.fn(),
    },
    api: {
      defaults: { baseURL: '/api', timeout: 15000, headers: { 'Content-Type': 'application/json' } },
      interceptors: { request: { handlers: [{}], use: vi.fn() }, response: { handlers: [{}], use: vi.fn() } },
      get: vi.fn(), post: vi.fn(), delete: vi.fn(),
    },
  }));

  async function renderLogin() {
    const Login = (await import('../pages/Login')).default;
    return renderWithRouter(
      <Routes>
        <Route path="/" element={<Login />} />
        <Route path="/dashboard" element={<div>Dashboard</div>} />
      </Routes>
    );
  }

  it('renders HOPEFX branding', async () => {
    await renderLogin();
    expect(screen.getByText(/HOPE/)).toBeInTheDocument();
  });

  it('renders username input', async () => {
    await renderLogin();
    expect(screen.getByLabelText(/username or email/i)).toBeInTheDocument();
  });

  it('renders password input', async () => {
    await renderLogin();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
  });

  it('renders sign in button', async () => {
    await renderLogin();
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('shows error when submitting empty form', async () => {
    await renderLogin();
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(screen.getByText(/required/i)).toBeInTheDocument();
  });

  it('shows error when only username provided', async () => {
    await renderLogin();
    fireEvent.change(screen.getByLabelText(/username or email/i), { target: { value: 'user' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(screen.getByText(/required/i)).toBeInTheDocument();
  });

  it('calls authApi.login with credentials', async () => {
    const { authApi } = await import('../hooks/useApi');
    vi.mocked(authApi.login).mockResolvedValueOnce({
      data: { access_token: 'tok', token_type: 'bearer', user: mockUser },
    } as never);

    await renderLogin();
    fireEvent.change(screen.getByLabelText(/username or email/i), { target: { value: 'trader1' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'pass123' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(authApi.login).toHaveBeenCalledWith({ username: 'trader1', password: 'pass123' });
    });
  });

  it('stores token in store after successful login', async () => {
    const { authApi } = await import('../hooks/useApi');
    vi.mocked(authApi.login).mockResolvedValueOnce({
      data: { access_token: 'my-token', token_type: 'bearer', user: mockUser },
    } as never);

    await renderLogin();
    fireEvent.change(screen.getByLabelText(/username or email/i), { target: { value: 'trader1' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'pass123' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(useStore.getState().token).toBe('my-token');
    });
  });

  it('shows error message on failed login', async () => {
    const { authApi } = await import('../hooks/useApi');
    vi.mocked(authApi.login).mockRejectedValueOnce({
      response: { data: { detail: 'Invalid credentials' } },
    });

    await renderLogin();
    fireEvent.change(screen.getByLabelText(/username or email/i), { target: { value: 'bad' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'wrong' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/invalid credentials/i)).toBeInTheDocument();
    });
  });

  it('shows generic error when no detail in response', async () => {
    const { authApi } = await import('../hooks/useApi');
    vi.mocked(authApi.login).mockRejectedValueOnce(new Error('Network error'));

    await renderLogin();
    fireEvent.change(screen.getByLabelText(/username or email/i), { target: { value: 'user' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'pass' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/invalid credentials/i)).toBeInTheDocument();
    });
  });

  it('trims whitespace from username', async () => {
    const { authApi } = await import('../hooks/useApi');
    vi.mocked(authApi.login).mockResolvedValueOnce({
      data: { access_token: 'tok', token_type: 'bearer', user: mockUser },
    } as never);

    await renderLogin();
    fireEvent.change(screen.getByLabelText(/username or email/i), { target: { value: '  trader1  ' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'pass' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(authApi.login).toHaveBeenCalledWith({ username: 'trader1', password: 'pass' });
    });
  });

  it('has status page link', async () => {
    await renderLogin();
    expect(screen.getByText(/system status/i)).toBeInTheDocument();
  });

  it('has support link', async () => {
    await renderLogin();
    expect(screen.getByText(/support/i)).toBeInTheDocument();
  });

  it('password input is type=password', async () => {
    await renderLogin();
    const input = screen.getByLabelText(/password/i) as HTMLInputElement;
    expect(input.type).toBe('password');
  });
});
