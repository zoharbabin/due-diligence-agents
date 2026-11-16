import { useEffect, useState } from 'react'
import { HashRouter, Route, Routes } from 'react-router-dom'
import { api, loadToken } from './api/client'
import { Layout } from './components/Layout'
import { Banner, Spinner } from './components/ui'
import { NewProjectPage } from './pages/NewProject'
import { ProjectPage } from './pages/ProjectPage'
import { ProjectsPage } from './pages/Projects'

type Gate = 'checking' | 'ready' | 'offline'

export default function App() {
  const [gate, setGate] = useState<Gate>('checking')
  useEffect(() => {
    loadToken()
      .then(() => api('/health'))
      .then(
        () => setGate('ready'),
        () => setGate('offline'),
      )
  }, [])

  if (gate === 'checking')
    return (
      <div className="flex h-screen items-center justify-center">
        <Spinner />
      </div>
    )
  if (gate === 'offline')
    return (
      <div className="mx-auto mt-24 max-w-md">
        <Banner tone="error">The local service is not reachable. Close and reopen the app.</Banner>
      </div>
    )
  return (
    <HashRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<ProjectsPage />} />
          <Route path="/new" element={<NewProjectPage />} />
          <Route path="/p/:slug" element={<ProjectPage />} />
          <Route path="*" element={<Banner tone="info">Page not found.</Banner>} />
        </Routes>
      </Layout>
    </HashRouter>
  )
}
