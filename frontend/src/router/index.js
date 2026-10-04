import { createRouter, createWebHistory } from 'vue-router'

const APP_TITLE = '钢铁表面缺陷检测智能体平台'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginPage.vue'),
    meta: { title: '登录', requiresAuth: false },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/RegisterPage.vue'),
    meta: { title: '注册', requiresAuth: false },
  },
  {
    path: '/',
    component: () => import('@/components/layout/MainLayout.vue'),
    redirect: '/chat',
    meta: { requiresAuth: true },
    children: [
      {
        path: 'chat',
        name: 'Chat',
        component: () => import('@/views/ChatPage.vue'),
        meta: { title: '智能对话', icon: 'ChatDotRound' },
      },
      {
        path: 'detection',
        name: 'Detection',
        component: () => import('@/views/DetectionPage.vue'),
        meta: { title: '检测工作台', icon: 'Camera' },
      },
      {
        path: 'training',
        name: 'Training',
        component: () => import('@/views/TrainingPage.vue'),
        meta: { title: '模型训练', icon: 'Cpu' },
      },
      {
        path: 'tasks',
        name: 'TaskCenter',
        component: () => import('@/views/TaskCenterPage.vue'),
        meta: { title: '任务中心', icon: 'List' },
      },
      {
        path: 'files',
        name: 'Files',
        redirect: '/training',
        meta: { title: '文件查看', icon: 'FolderOpened' },
      },
      {
        path: 'history',
        name: 'History',
        component: () => import('@/views/HistoryPage.vue'),
        meta: { title: '历史记录', icon: 'Clock' },
      },
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/DashboardPage.vue'),
        meta: { title: '数据看板', icon: 'DataAnalysis' },
      },
      {
        path: 'help',
        name: 'Help',
        component: () => import('@/views/HelpPage.vue'),
        meta: { title: '帮助与引导', icon: 'QuestionFilled' },
      },
      {
        path: 'admin',
        name: 'Admin',
        component: () => import('@/views/AdminPage.vue'),
        meta: { title: '管理中心', icon: 'Setting', requiresAdmin: true },
      },
      {
        path: 'files',
        name: 'Files',
        component: () => import('@/views/FilesPage.vue'),
        meta: { title: '文件生命周期', icon: 'FolderOpened' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/login',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, from, next) => {
  document.title = to.meta.title ? `${to.meta.title} - ${APP_TITLE}` : APP_TITLE

  const token = localStorage.getItem('ssdd_token')
  const requiresAuth = to.matched.some((record) => record.meta.requiresAuth !== false)
  const requiresAdmin = to.matched.some((record) => record.meta.requiresAdmin)
  let isSuperuser = false
  try { isSuperuser = JSON.parse(localStorage.getItem('ssdd_user') || 'null')?.is_superuser === true } catch { /* user info will be refreshed after login */ }

  if (requiresAuth && !token) {
    next({ path: '/login', query: { redirect: to.fullPath } })
  } else if (requiresAdmin && !isSuperuser) {
    next('/dashboard')
  } else if ((to.path === '/login' || to.path === '/register') && token) {
    next('/')
  } else {
    next()
  }
})

export default router
