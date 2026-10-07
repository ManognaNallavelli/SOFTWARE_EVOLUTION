export type Project = {
  id: string
  owner_user_id: string
  name: string
  github_url: string
  normalized_github_url: string
  github_repo_id: number
  github_full_name: string
  technologies: string[]
  description: string | null
  status: string
  last_error?: string | null
  last_error_code?: string | null
  created_at: string
  updated_at: string
}

export type ProjectCreateInput = {
  name?: string
  github_url: string
  technologies?: string[]
  description?: string
}

export type ApiErrorBody = {
  detail?:
    | string
    | {
        code?: string
        message?: string
        existing_project_id?: string
      }
}
