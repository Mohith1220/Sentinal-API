import { UserRole, Permission } from '../types/api';

const ROLE_PERMISSIONS: Record<UserRole, Permission[]> = {
  [UserRole.SUPER_ADMIN]: Object.values(Permission),
  
  [UserRole.SECURITY_ADMIN]: [
    Permission.VIEW_DASHBOARD,
    Permission.VIEW_KPI,
    Permission.VIEW_API_INVENTORY,
    Permission.EDIT_API_INVENTORY,
    Permission.VIEW_DEPENDENCY_GRAPH,
    Permission.EXPORT_GRAPH,
    Permission.VIEW_ALERTS,
    Permission.ACKNOWLEDGE_ALERT,
    Permission.RESOLVE_ALERT,
    Permission.VIEW_RISK_HEATMAP,
    Permission.MANAGE_RISK,
    Permission.VIEW_REMEDIATION,
    Permission.CREATE_REMEDIATION,
    Permission.RESOLVE_REMEDIATION,
    Permission.VIEW_COMPLIANCE,
    Permission.VIEW_AUDIT_LOG,
  ],
  
  [UserRole.SECURITY_ANALYST]: [
    Permission.VIEW_DASHBOARD,
    Permission.VIEW_KPI,
    Permission.VIEW_API_INVENTORY,
    Permission.VIEW_DEPENDENCY_GRAPH,
    Permission.EXPORT_GRAPH,
    Permission.VIEW_ALERTS,
    Permission.ACKNOWLEDGE_ALERT,
    Permission.VIEW_RISK_HEATMAP,
    Permission.VIEW_REMEDIATION,
    Permission.VIEW_COMPLIANCE,
  ],
  
  [UserRole.API_GOVERNANCE_MANAGER]: [
    Permission.VIEW_DASHBOARD,
    Permission.VIEW_KPI,
    Permission.VIEW_API_INVENTORY,
    Permission.EDIT_API_INVENTORY,
    Permission.VIEW_DEPENDENCY_GRAPH,
    Permission.VIEW_RISK_HEATMAP,
    Permission.VIEW_COMPLIANCE,
    Permission.MANAGE_COMPLIANCE,
  ],
  
  [UserRole.COMPLIANCE_OFFICER]: [
    Permission.VIEW_DASHBOARD,
    Permission.VIEW_KPI,
    Permission.VIEW_API_INVENTORY,
    Permission.VIEW_RISK_HEATMAP,
    Permission.VIEW_COMPLIANCE,
    Permission.VIEW_AUDIT_LOG,
  ],
  
  [UserRole.VIEWER]: [
    Permission.VIEW_DASHBOARD,
    Permission.VIEW_KPI,
  ],
};

export const getRolePermissions = (role: UserRole): Permission[] => {
  return ROLE_PERMISSIONS[role] || [];
};

export const hasPermission = (role: UserRole, permission: Permission): boolean => {
  const permissions = getRolePermissions(role);
  return permissions.includes(permission);
};
