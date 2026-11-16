import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react'
import type { Severity } from '../api/types'
import { SEVERITY_LABEL } from '../lib/format'

const cx = (...c: (string | false | undefined)[]) => c.filter(Boolean).join(' ')

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'
const VARIANTS: Record<Variant, string> = {
  primary: 'bg-indigo-600 text-white hover:bg-indigo-700 disabled:bg-indigo-300',
  secondary: 'bg-white text-slate-800 border border-slate-300 hover:bg-slate-50 disabled:text-slate-400',
  danger: 'bg-red-600 text-white hover:bg-red-700 disabled:bg-red-300',
  ghost: 'text-slate-600 hover:bg-slate-100',
}

export function Button({
  variant = 'primary',
  busy,
  className,
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  return (
    <button
      type="button"
      {...rest}
      disabled={disabled || busy}
      className={cx(
        'inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 disabled:cursor-not-allowed',
        VARIANTS[variant],
        className,
      )}
    >
      {busy && <Spinner small />}
      {children}
    </button>
  )
}

export function Spinner({ small }: { small?: boolean }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={cx(
        'inline-block animate-spin rounded-full border-2 border-current border-t-transparent',
        small ? 'h-4 w-4' : 'h-6 w-6',
      )}
    />
  )
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx('rounded-xl border border-slate-200 bg-white p-5 shadow-sm', className)}>{children}</div>
}

export function Banner({ tone, children }: { tone: 'error' | 'info' | 'success'; children: ReactNode }) {
  const tones = {
    error: 'border-red-200 bg-red-50 text-red-800',
    info: 'border-sky-200 bg-sky-50 text-sky-800',
    success: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  }
  return (
    <div role={tone === 'error' ? 'alert' : 'status'} className={cx('rounded-lg border px-4 py-3 text-sm', tones[tone])}>
      {children}
    </div>
  )
}

export function EmptyState({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <Card className="mx-auto max-w-lg py-12 text-center">
      <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
      <p className="mx-auto mt-2 max-w-sm text-sm text-slate-600">{body}</p>
      {action && <div className="mt-6">{action}</div>}
    </Card>
  )
}

export function Field({
  label,
  hint,
  error,
  ...input
}: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string; error?: string }) {
  const id = input.id ?? `f-${label.toLowerCase().replace(/\W+/g, '-')}`
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-slate-700">
        {label}
      </label>
      <input
        id={id}
        {...input}
        aria-invalid={Boolean(error)}
        aria-describedby={hint || error ? `${id}-d` : undefined}
        className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-indigo-600"
      />
      {(hint || error) && (
        <p id={`${id}-d`} className={cx('mt-1 text-xs', error ? 'text-red-700' : 'text-slate-500')}>
          {error ?? hint}
        </p>
      )}
    </div>
  )
}

const SEV_STYLE: Record<Severity, string> = {
  P0: 'bg-red-100 text-red-800 ring-red-300',
  P1: 'bg-orange-100 text-orange-800 ring-orange-300',
  P2: 'bg-amber-100 text-amber-800 ring-amber-300',
  P3: 'bg-slate-100 text-slate-700 ring-slate-300',
}

export function SeverityBadge({ severity, count }: { severity: Severity; count?: number }) {
  return (
    <span
      title={SEVERITY_LABEL[severity]}
      className={cx('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ring-1', SEV_STYLE[severity])}
    >
      {severity}
      {count !== undefined && <span className="font-normal">{count}</span>}
    </span>
  )
}

export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: { id: T; label: string }[]
  active: T
  onChange: (id: T) => void
}) {
  return (
    <div role="tablist" className="flex gap-1 border-b border-slate-200">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          type="button"
          aria-selected={t.id === active}
          onClick={() => onChange(t.id)}
          className={cx(
            '-mb-px border-b-2 px-4 py-2 text-sm font-medium',
            t.id === active ? 'border-indigo-600 text-indigo-700' : 'border-transparent text-slate-600 hover:text-slate-900',
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}
