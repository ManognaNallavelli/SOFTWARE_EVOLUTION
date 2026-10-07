export type User = {
  id: string
  email: string
  name: string
  picture?: string | null
  created_at: string
}

export type AuthMeResponse = {
  authenticated: boolean
  user: User | null
}
