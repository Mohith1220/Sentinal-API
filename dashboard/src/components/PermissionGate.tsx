import React from 'react';
import { useAuth } from '../contexts/AuthContext';
import type { Permission } from '../types/api';

interface PermissionGateProps {
  children: React.ReactElement;
  permission: Permission;
  fallbackBehavior?: 'hide' | 'disable';
  tooltipMessage?: string;
}

export const PermissionGate: React.FC<PermissionGateProps> = ({
  children,
  permission,
  fallbackBehavior = 'hide',
  tooltipMessage = 'Access Restricted: Requires elevated SOC clearance',
}) => {
  const { hasPermission } = useAuth();

  if (hasPermission(permission)) {
    return <>{children}</>;
  }

  if (fallbackBehavior === 'hide') {
    return null;
  }

  const childProps = children.props as any;

  // Clone children element to inject disabled styling & security tooltip
  return React.cloneElement(children, {
    disabled: true,
    title: `${tooltipMessage} [Code: ${permission}]`,
    style: {
      ...(childProps.style || {}),
      opacity: 0.35,
      cursor: 'not-allowed',
      pointerEvents: 'none',
    },
    className: `${childProps.className || ''} cursor-not-allowed select-none opacity-35 relative group`,
  } as any);
};
