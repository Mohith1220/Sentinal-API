import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { Shield, Key, User, Terminal } from 'lucide-react';
import { UserRole } from '../types/api';

export const Login: React.FC = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const justRegistered = (location.state as any)?.registered === true;

  // Matrix Digital Rain effect on Canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const resizeCanvas = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);

    const columns = Math.floor(canvas.width / 20) + 1;
    const ypos = Array(columns).fill(0);

    const drawMatrix = () => {
      ctx.fillStyle = 'rgba(5, 10, 15, 0.15)'; // Deep background fade
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      ctx.fillStyle = 'rgba(6, 182, 212, 0.35)'; // Cyan matrix rain
      ctx.font = '11px monospace';

      ypos.forEach((y, index) => {
        const char = Math.random() > 0.5 ? '1' : '0';
        const x = index * 20;
        ctx.fillText(char, x, y);

        if (y > 100 + Math.random() * 10000) {
          ypos[index] = 0;
        } else {
          ypos[index] = y + 12;
        }
      });
    };

    const interval = setInterval(drawMatrix, 45);

    return () => {
      clearInterval(interval);
      window.removeEventListener('resize', resizeCanvas);
    };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      await login(username, password);
      // Wait briefly for state synchronization
      setTimeout(() => {
        navigate('/');
      }, 100);
    } catch (err) {
      setError('AUTHENTICATION FAILED: Invalid credentials matching bank directory');
    } finally {
      setIsLoading(false);
    }
  };

  // Quick autofill helper
  const handleAutofill = (roleKey: UserRole) => {
    setError('');
    
    // Default usernames based on enums matching seeded database records
    switch (roleKey) {
      case UserRole.SUPER_ADMIN:
        setUsername('admin');
        setPassword('admin123');
        break;
      case UserRole.SECURITY_ADMIN:
        setUsername('security_admin');
        setPassword('admin123');
        break;
      case UserRole.SECURITY_ANALYST:
        setUsername('analyst');
        setPassword('admin123');
        break;
      case UserRole.API_GOVERNANCE_MANAGER:
        setUsername('governance');
        setPassword('admin123');
        break;
      case UserRole.COMPLIANCE_OFFICER:
        setUsername('compliance');
        setPassword('admin123');
        break;
      case UserRole.VIEWER:
        setUsername('viewer');
        setPassword('admin123');
        break;
    }
  };

  return (
    <div className="min-h-screen w-full relative flex items-center justify-center font-mono scanlines overflow-x-hidden py-10 px-4 bg-cyber-bg">
      {/* Background Matrix animation */}
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full block pointer-events-none z-0 opacity-40" />

      {/* Main card */}
      <div className="w-full max-w-xl glass-panel border border-cyber-border-hover/30 p-8 shadow-[0_0_60px_rgba(6,182,212,0.15)] relative z-10 flex flex-col md:flex-row gap-8">
        
        {/* Left Side: Form */}
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-8 h-8 rounded bg-cyber-cyan/15 border border-cyber-cyan/35 flex items-center justify-center">
              <Shield className="w-4 h-4 text-cyber-cyan animate-pulse" />
            </div>
            <div className="flex flex-col">
              <span className="font-bold text-sm tracking-wider text-gray-200">SENTINEL_API</span>
              <span className="text-[10px] text-gray-500 font-mono tracking-tighter">SECURE ACCESS</span>
            </div>
          </div>

          <h1 className="text-lg font-bold tracking-widest text-cyber-cyan uppercase mb-6">
            SOC PORTAL SIGN IN
          </h1>

          {justRegistered && (
            <div className="mb-4 p-2 bg-cyber-green/10 border border-cyber-green/45 text-cyber-green text-[10px] rounded animate-pulse">
              ACCOUNT VERIFIED: You may now perform a secure sign in.
            </div>
          )}

          {error && (
            <div className="mb-4 p-2.5 bg-cyber-red/10 border border-cyber-red/45 text-cyber-red text-[10px] rounded leading-relaxed">
              [ALERT] {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="flex flex-col gap-4 text-xs">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="username" className="text-gray-500 font-bold flex items-center gap-1.5">
                <User className="w-3.5 h-3.5 text-cyber-cyan" />
                <span>OPERATOR_USERNAME:</span>
              </label>
              <input
                id="username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                placeholder="operator_id"
                className="w-full bg-black/45 border border-cyber-border rounded px-3 py-2 text-gray-200 placeholder-gray-700 focus:outline-none focus:border-cyber-cyan transition-all text-xs"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <label htmlFor="password" className="text-gray-500 font-bold flex items-center gap-1.5">
                <Key className="w-3.5 h-3.5 text-cyber-cyan" />
                <span>SECURITY_ACCESS_KEY:</span>
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                placeholder="••••••••"
                className="w-full bg-black/45 border border-cyber-border rounded px-3 py-2 text-gray-200 placeholder-gray-700 focus:outline-none focus:border-cyber-cyan transition-all text-xs"
              />
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="mt-4 w-full bg-cyber-cyan/15 hover:bg-cyber-cyan/35 border border-cyber-cyan/45 hover:border-cyber-cyan text-cyber-cyan hover:text-white transition-all py-2.5 rounded font-bold cursor-pointer disabled:opacity-40 disabled:pointer-events-none"
            >
              {isLoading ? 'INITIATING SECURE SESSION...' : 'DECRYPT & ACCESS'}
            </button>
          </form>
        </div>

        {/* Right Side: Role Selector */}
        <div className="w-full md:w-56 border-t md:border-t-0 md:border-l border-cyber-border pt-6 md:pt-0 md:pl-6 flex flex-col gap-4">
          <div className="flex items-center gap-1.5 text-cyber-purple font-bold">
            <Terminal className="w-4 h-4 text-cyber-purple" />
            <span className="text-[11px] tracking-wider">FAST_TRACK_HUD</span>
          </div>
          
          <div className="text-[9px] text-gray-500 leading-relaxed font-sans mb-1">
            Bypass credential forms in development using pre-authorized banking SOC mock keys:
          </div>

          <div className="flex flex-col gap-2">
            {Object.values(UserRole).map((roleVal) => {
              const getBadgeColor = (r: UserRole) => {
                switch (r) {
                  case UserRole.SUPER_ADMIN: return 'border-cyber-red/30 hover:border-cyber-red hover:bg-cyber-red/5 text-cyber-red';
                  case UserRole.SECURITY_ADMIN: return 'border-cyber-amber/30 hover:border-cyber-amber hover:bg-cyber-amber/5 text-cyber-amber';
                  case UserRole.SECURITY_ANALYST: return 'border-cyber-blue/30 hover:border-cyber-blue hover:bg-cyber-blue/5 text-cyber-blue';
                  case UserRole.API_GOVERNANCE_MANAGER: return 'border-cyber-purple/30 hover:border-cyber-purple hover:bg-cyber-purple/5 text-cyber-purple';
                  case UserRole.COMPLIANCE_OFFICER: return 'border-cyber-yellow/30 hover:border-cyber-yellow hover:bg-cyber-yellow/5 text-cyber-yellow';
                  default: return 'border-cyber-green/30 hover:border-cyber-green hover:bg-cyber-green/5 text-cyber-green';
                }
              };
              return (
                <button
                  key={roleVal}
                  type="button"
                  onClick={() => handleAutofill(roleVal)}
                  className={`w-full text-left px-2.5 py-1.5 border rounded text-[10px] font-bold tracking-wide transition-all uppercase cursor-pointer ${getBadgeColor(roleVal)}`}
                >
                  ● {roleVal.replace('_', ' ')}
                </button>
              );
            })}
          </div>
        </div>

      </div>
    </div>
  );
};
