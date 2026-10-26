import { useEffect, useState } from 'react'

// Callback ref: the observed element may mount after the first render (e.g. after a loading state).
export function useWidth<T extends HTMLElement>(): [(el: T | null) => void, number] {
  const [el, setEl] = useState<T | null>(null)
  const [w, setW] = useState(900)
  useEffect(() => {
    if (!el) return
    setW(Math.max(320, Math.floor(el.clientWidth)))
    const ro = new ResizeObserver((e) => setW(Math.max(320, Math.floor(e[0].contentRect.width))))
    ro.observe(el)
    return () => ro.disconnect()
  }, [el])
  return [setEl, w]
}

export function useTheme(): [string, () => void] {
  const [t, setT] = useState<string>(() => {
    try { return localStorage.getItem('theme') || 'auto' } catch { return 'auto' }
  })
  useEffect(() => {
    const el = document.documentElement
    if (t === 'auto') el.removeAttribute('data-theme'); else el.setAttribute('data-theme', t)
    try { localStorage.setItem('theme', t) } catch { /* private window */ }
  }, [t])
  return [t, () => setT((x) => (x === 'auto' ? 'dark' : x === 'dark' ? 'light' : 'auto'))]
}

export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}
