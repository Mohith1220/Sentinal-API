import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { RequireRole } from '../RequireRole';
import * as AuthContext from '../../contexts/AuthContext';

// Mock the useAuth hook
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: vi.fn(),
}));

describe('RequireRole', () => {
  const renderWithRouter = (component: React.ReactElement) => {
    return render(<BrowserRouter>{component}</BrowserRouter>);
  };

  it('renders children when user has required role', () => {
    vi.mocked(AuthContext.useAuth).mockReturnValue({
      isAuthenticated: true,
      role: 'admin',
      login: vi.fn(),
      logout: vi.fn(),
      isLoading: false,
    });

    renderWithRouter(
      <RequireRole roles={['admin']}>
        <div>Protected Content</div>
      </RequireRole>
    );

    expect(screen.getByText('Protected Content')).toBeInTheDocument();
  });

  it('renders children when user has one of multiple required roles', () => {
    vi.mocked(AuthContext.useAuth).mockReturnValue({
      isAuthenticated: true,
      role: 'analyst',
      login: vi.fn(),
      logout: vi.fn(),
      isLoading: false,
    });

    renderWithRouter(
      <RequireRole roles={['admin', 'analyst', 'viewer']}>
        <div>Protected Content</div>
      </RequireRole>
    );

    expect(screen.getByText('Protected Content')).toBeInTheDocument();
  });

  it('displays authorization error when user lacks required role', () => {
    vi.mocked(AuthContext.useAuth).mockReturnValue({
      isAuthenticated: true,
      role: 'viewer',
      login: vi.fn(),
      logout: vi.fn(),
      isLoading: false,
    });

    renderWithRouter(
      <RequireRole roles={['admin']}>
        <div>Protected Content</div>
      </RequireRole>
    );

    expect(screen.queryByText('Protected Content')).not.toBeInTheDocument();
    expect(screen.getByText('Authorization Error')).toBeInTheDocument();
    expect(screen.getByText(/You do not have permission/i)).toBeInTheDocument();
    expect(screen.getByText(/Required role: admin/i)).toBeInTheDocument();
    expect(screen.getByText(/Your role: viewer/i)).toBeInTheDocument();
  });

  it('displays authorization error when analyst tries to access admin route', () => {
    vi.mocked(AuthContext.useAuth).mockReturnValue({
      isAuthenticated: true,
      role: 'analyst',
      login: vi.fn(),
      logout: vi.fn(),
      isLoading: false,
    });

    renderWithRouter(
      <RequireRole roles={['admin']}>
        <div>Admin Panel</div>
      </RequireRole>
    );

    expect(screen.queryByText('Admin Panel')).not.toBeInTheDocument();
    expect(screen.getByText('Authorization Error')).toBeInTheDocument();
  });

  it('displays authorization error when viewer tries to access admin route', () => {
    vi.mocked(AuthContext.useAuth).mockReturnValue({
      isAuthenticated: true,
      role: 'viewer',
      login: vi.fn(),
      logout: vi.fn(),
      isLoading: false,
    });

    renderWithRouter(
      <RequireRole roles={['admin']}>
        <div>Admin Panel</div>
      </RequireRole>
    );

    expect(screen.queryByText('Admin Panel')).not.toBeInTheDocument();
    expect(screen.getByText('Authorization Error')).toBeInTheDocument();
  });

  it('displays loading state while authentication is being checked', () => {
    vi.mocked(AuthContext.useAuth).mockReturnValue({
      isAuthenticated: false,
      role: null,
      login: vi.fn(),
      logout: vi.fn(),
      isLoading: true,
    });

    renderWithRouter(
      <RequireRole roles={['admin']}>
        <div>Protected Content</div>
      </RequireRole>
    );

    expect(screen.getByText('Loading...')).toBeInTheDocument();
    expect(screen.queryByText('Protected Content')).not.toBeInTheDocument();
  });
});
