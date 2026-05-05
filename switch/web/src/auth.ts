const UI_TOKEN_STORAGE_KEY = 'agentic-ui.uiToken'
const UI_TOKEN_QUERY_PARAM = 'uiToken'
const UI_TOKEN_HEADER = 'X-Agentic-UI-Token'

export function initializeUiTokenFromUrl() {
  const url = new URL(window.location.href)
  const token = url.searchParams.get(UI_TOKEN_QUERY_PARAM)
  if (!token) return

  window.localStorage.setItem(UI_TOKEN_STORAGE_KEY, token)
  url.searchParams.delete(UI_TOKEN_QUERY_PARAM)
  window.history.replaceState(window.history.state, '', url)
}

export function uiAuthFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  const token = readUiToken()
  if (!token) return fetch(input, init)

  const headers = new Headers(init.headers)
  headers.set(UI_TOKEN_HEADER, token)
  return fetch(input, { ...init, headers })
}

export function uiWebSocketUrl(path: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const url = new URL(path, `${protocol}//${window.location.host}`)
  const token = readUiToken()
  if (token) {
    url.searchParams.set(UI_TOKEN_QUERY_PARAM, token)
  }
  return url.toString()
}

function readUiToken(): string | null {
  const token = window.localStorage.getItem(UI_TOKEN_STORAGE_KEY)?.trim()
  return token || null
}
