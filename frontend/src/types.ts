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
  id: string
  clause_id: string
  before_clause_id: string | null
  after_clause_id: string | null
  match_method?: 'number' | 'exact_text' | 'occurrence'
  status: string
  before: string | null
  after: string | null
  before_source: string | null
  after_source: string | null
}

export interface Unit {
  name: string
  status: string
  change_ids: string[]
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
  id: string
  origin: 'ai' | 'local'
  kind: string
  title: string
  explanation: string
  confidence: number | string | null
  citations: Citation[]
}

export interface AiAnalysis {
  status: 'disabled' | 'unavailable' | 'succeeded' | 'failed' | 'skipped'
  requested: boolean
  model: string
  summary: string | null
  summary_origin: 'verified_findings' | null
  finding_ids: string[]
  error: string | null
  coverage: { total_clauses: number; included_clauses: number; omitted_clauses: number; truncated_clauses: number; before_complete?: boolean; after_complete?: boolean }
  omitted_refs?: string[]
  truncated_refs?: string[]
  rejected_findings: number
}

export interface DocumentCoverage {
  clauses: number
  unnumbered_blocks: number
  synthetic_ids: boolean
}

export interface AnalysisResponse {
  analysis_id: string
  ai: AiAnalysis
  coverage: { before: DocumentCoverage; after: DocumentCoverage }
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
