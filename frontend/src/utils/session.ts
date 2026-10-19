import { AxiosError } from "axios"

export function isSessionError(error: unknown, currentUserRequest = false) {
  if (!(error instanceof AxiosError)) return false

  const status = error.response?.status
  if (status === 401) return true

  if (currentUserRequest && [400, 403, 404].includes(status ?? 0)) {
    return true
  }

  return (
    status === 403 &&
    error.response?.data?.detail === "Could not validate credentials"
  )
}
