export type Page = 'Dashboard' | 'Jobs' | 'Preparation' | 'Practice' | 'Recordings' | 'Progress' | 'Settings';
export interface RecordBase { id: string; created_at: string; updated_at: string }
export interface Job extends RecordBase {
  title: string; company: string; description: string; resume_text: string;
  requirements: string[]; seniority: string; status: string;
}
export interface Round extends RecordBase {
  job_id: string; title: string; kind: string; scheduled_at: string;
  status: string; outcome: string; notes: string;
}
export interface Session extends RecordBase {
  job_id: string; round_id?: string; kind: string; mode: 'learning' | 'mock';
  difficulty: string; duration_minutes: number; status: string; source: 'practice' | 'upload';
  title: string; speakers_confirmed?: boolean; recording_url?: string; candidate_speaker?: string; duration_seconds: number;
}
export interface Segment extends RecordBase {
  session_id: string; role: 'candidate' | 'interviewer' | 'unknown' | 'other';
  speaker?: string; text: string; start: number; end: number;
}
export interface PreparationPlan {
  summary: string; skills: string[];
  gap_analysis: { skill: string; current_evidence: string; gap: string; priority: string }[];
  levels: { level: string; title: string; objectives: string[]; topics: { title: string; explanation: string; exercise: string }[]; questions: string[] }[];
  rounds: { kind: string; focus: string; practice_questions: string[] }[];
  next_steps: string[];
}
export interface Report {
  summary: string; overall_score: number | null;
  dimensions: { key: string; label: string; score: number | null; feedback: string; evidence: { segment_id: string; start: number; end: number; quote: string }[] }[];
  strengths: string[]; improvements: { title: string; why: string; action: string; example_answer?: string | null }[];
  drills: { title: string; instruction: string; skill: string }[]; limitations: string[];
}
export interface Preparation extends RecordBase { job_id: string; plan: PreparationPlan }
export interface Assessment extends RecordBase { session_id: string; report: Report; stale?: boolean }
export interface Drill extends RecordBase { job_id: string; session_id: string; title: string; instruction: string; skill: string; completed: boolean }
export interface Task extends RecordBase {
  kind: string; target_id: string; status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress: number; message: string; error?: string;
}
export interface Provider { kind: 'ollama' | 'lmstudio' | 'openai_compatible' | 'openai' | 'codex'; base_url: string; model: string }
export interface Settings {
  offline: boolean; provider: Provider; pause_ms: number; ignore_mic_while_speaking: boolean;
  speech: { stt_path: string; tts_path: string; diarization_path: string };
}
export type Readiness = Record<'llm' | 'stt' | 'tts' | 'diarization' | 'vad', { ready: boolean; message: string }>;
export interface Bootstrap {
  jobs: Job[]; rounds: Round[]; sessions: Session[]; preparations: Preparation[];
  assessments: Assessment[]; drills: Drill[]; tasks: Task[]; settings: Settings; readiness: Readiness;
}
export interface SessionDetail { session: Session; segments: Segment[]; assessments: Assessment[] }
