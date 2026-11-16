import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'

export function Layout({ children }: { children: ReactNode }) {
  const link = ({ isActive }: { isActive: boolean }) =>
    `block rounded-lg px-3 py-2 text-sm font-medium ${isActive ? 'bg-indigo-50 text-indigo-700' : 'text-slate-600 hover:bg-slate-100'}`
  return (
    <div className="flex min-h-screen">
      <nav aria-label="Main" className="w-56 shrink-0 border-r border-slate-200 bg-white p-4">
        <div className="mb-6 px-3 text-sm font-semibold text-slate-900">Due Diligence Agents</div>
        <NavLink to="/" end className={link}>
          Projects
        </NavLink>
        <NavLink to="/settings" className={link}>
          Settings
        </NavLink>
      </nav>
      <main className="flex-1 overflow-y-auto p-8">
        <div className="mx-auto max-w-5xl">{children}</div>
      </main>
    </div>
  )
}
