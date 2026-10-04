import request from '@/utils/request'

export const getAdminUsers = (params) => request.get('/auth/users', { params })
export const activateUser = (userId) => request.post(`/auth/users/${userId}/activate`)
export const deactivateUser = (userId) => request.post(`/auth/users/${userId}/deactivate`)
export const deleteUser = (userId) => request.delete(`/auth/users/${userId}`)
export const adminResetPassword = (userId, newPassword) => request.post(`/auth/users/${userId}/password-reset`, { new_password: newPassword })
export const getOperationLogs = (params) => request.get('/operation-logs', { params })
export const getErrorSummary = (params) => request.get('/operation-logs/summary', { params })
export const exportOperationLogs = (params) => request.get('/operation-logs/export', { params, responseType: 'blob' })
export const getResourceStatus = () => request.get('/auth/resource-status')
