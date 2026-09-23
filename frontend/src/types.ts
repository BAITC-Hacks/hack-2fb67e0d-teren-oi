export type Step = 'import' | 'analysis' | 'results'
export type DocumentSide = 'before' | 'after'

export interface HealthResponse {
  ai_available: boolean
  model: string
  supported_extensions: string[]
}

export interface Summary {
  added: number
  removed: number
  modified: number
  unchanged: number
  units_changed: number
  duplicate_count: number
  loss_count: number
}

export interface ClauseChange {
  clause_id: string
  status: string
  before: string | null
  after: string | null
  before_source: string | null
  after_source: string | null
}

export interface Unit {
  name: string
  status: string
  clause_ids: string[]
}

export interface Citation {
  document_label: string
  clause_id: string
  quote: string
  source?: string | null
  location?: string | null
}

export interface Finding {
  kind: string
  title: string
  explanation: string
  confidence: number | string | null
  citations: Citation[]
}

export interface AnalysisResponse {
  summary: Summary
  changes: ClauseChange[]
  units: Unit[]
  findings: Finding[]
  report_markdown: string
  source_names: { before: string; after: string }
  ai_error?: string | null
  warnings?: string[]
}

export interface AnalysisInput {
  beforeFile: File | null
  afterFile: File | null
  beforeText: string
  afterText: string
  useAi: boolean
  demo: boolean
}
