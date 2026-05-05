const UI_TOKEN_STORAGE_KEY = 'agentic-ui.uiToken'
const UI_TOKEN_QUERY_PARAM = 'uiToken'
const UI_TOKEN_HEADER = 'X-Agentic-UI-Token'

let uiTokenCookiePromise: Promise<void> | null = null
let uiTokenCookieValue: string | null = null

export function initializeUiTokenFromUrl() {
  const url = new URL(window.location.href)
  const hashParams = new URLSearchParams(url.hash.startsWith('#') ? url.hash.slice(1) : '')
  const hashToken = hashParams.get(UI_TOKEN_QUERY_PARAM)
  const token = url.searchParams.get(UI_TOKEN_QUERY_PARAM) || hashToken
  if (!token) return

  writeUiToken(token)
  url.searchParams.delete(UI_TOKEN_QUERY_PARAM)
  if (hashToken !== null) {
    hashParams.delete(UI_TOKEN_QUERY_PARAM)
    url.hash = hashParams.toString()
  }
  window.history.replaceState(window.history.state, '', url)
}

export function uiAuthFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  const token = readUiToken()
  if (!token) return fetch(input, init)

  const headers = new Headers(init.headers)
  headers.set(UI_TOKEN_HEADER, token)
  return fetch(input, { ...init, headers, credentials: init.credentials ?? 'same-origin' })
}

export function ensureUiTokenCookie(): Promise<void> {
  const token = readUiToken()
  if (!token) return Promise.resolve()
  if (uiTokenCookiePromise && uiTokenCookieValue === token) return uiTokenCookiePromise

  uiTokenCookieValue = token
  uiTokenCookiePromise = uiAuthFetch('/api/auth/browser-cookie', {
    method: 'POST',
    credentials: 'same-origin',
  })
    .then(response => {
      if (!response.ok) throw new Error(`Failed to set browser auth cookie: ${response.status}`)
      clearUiToken()
    })
    .catch(() => {
      if (uiTokenCookieValue === token) {
        uiTokenCookieValue = null
        uiTokenCookiePromise = null
      }
    })
  return uiTokenCookiePromise
}

export function uiWebSocketUrl(path: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const url = new URL(path, `${protocol}//${window.location.host}`)
  return url.toString()
}

function readUiToken(): string | null {
  const token = window.sessionStorage.getItem(UI_TOKEN_STORAGE_KEY)?.trim()
    || window.localStorage.getItem(UI_TOKEN_STORAGE_KEY)?.trim()
  return token || null
}

function writeUiToken(token: string) {
  window.sessionStorage.setItem(UI_TOKEN_STORAGE_KEY, token)
  window.localStorage.removeItem(UI_TOKEN_STORAGE_KEY)
}

function clearUiToken() {
  window.sessionStorage.removeItem(UI_TOKEN_STORAGE_KEY)
  window.localStorage.removeItem(UI_TOKEN_STORAGE_KEY)
}
