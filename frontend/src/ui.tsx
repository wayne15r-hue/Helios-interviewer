import { useEffect, useRef, type ReactNode } from 'react';
import { ArrowUpRight, Check, ChevronDown, LoaderCircle, Play, Sparkles, Target, X, type LucideIcon } from 'lucide-react';
import { label, time } from './api';
import type { PreparationPlan, Report } from './types';

export function Button({ children, onClick, variant = 'primary', type = 'button', disabled, busy, className = '', title }: {
  children: ReactNode; onClick?: () => void; variant?: 'primary' | 'secondary' | 'ghost' | 'danger'; type?: 'button' | 'submit'; disabled?: boolean; busy?: boolean; className?: string; title?: string;
}) { return <button type={type} className={`button ${variant} ${className}`} onClick={onClick} disabled={disabled || busy} title={title}>{busy && <LoaderCircle size={15} className="spin" />}{children}</button>; }

export function Badge({ children, color = 'neutral' }: { children: ReactNode; color?: 'green' | 'amber' | 'red' | 'neutral' }) {
  return <span className={`badge ${color}`}>{children}</span>;
}

export function Field({ label, children, hint, className = '' }: { label: string; children: ReactNode; hint?: string; className?: string }) {
  return <label className={`field ${className}`}><span className="field-label">{label}</span>{children}{hint && <span className="field-hint">{hint}</span>}</label>;
}

export function Empty({ icon: Icon = Target, title, text, children, compact = false }: { icon?: LucideIcon; title: string; text: string; children?: ReactNode; compact?: boolean }) {
  return <div className={`empty ${compact ? 'compact' : ''}`}><span className="empty-icon"><Icon size={23} strokeWidth={1.4} /></span><h3>{title}</h3><p>{text}</p>{children}</div>;
}

export function Modal({ title, subtitle, children, onClose, wide = false }: { title: string; subtitle?: string; children: ReactNode; onClose: () => void; wide?: boolean }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { const current = dialog.current; current?.showModal(); return () => current?.close(); }, []);
  return <dialog ref={dialog} className={`modal ${wide ? 'wide' : ''}`} onCancel={onClose} onClick={e => { if (e.target === e.currentTarget) onClose(); }} aria-labelledby="dialog-title">
    <div className="modal-body"><div className="modal-heading"><div><h2 id="dialog-title">{title}</h2>{subtitle && <p>{subtitle}</p>}</div><button className="icon-button" onClick={onClose} aria-label="Close dialog"><X size={20} /></button></div>{children}</div>
  </dialog>;
}

export function SectionTitle({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return <div className="section-heading"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>;
}

export function PlanView({ plan }: { plan: PreparationPlan }) {
  return <div className="plan-view">
    <div className="callout"><Sparkles size={21} /><div><h3>Your preparation direction</h3><p>{plan.summary}</p></div></div>
    <div className="tags">{plan.skills?.map(skill => <Badge key={skill}>{skill}</Badge>)}</div>
    {!!plan.gap_analysis?.length && <section><SectionTitle title="Where to focus" subtitle="A starting assessment based on the experience you shared." /><div className="gap-grid">{plan.gap_analysis.map((gap, i) => <article className="card gap-card" key={i}><div className="row-between"><h3>{gap.skill}</h3><Badge color={gap.priority === 'high' ? 'amber' : 'neutral'}>{gap.priority} priority</Badge></div><p>{gap.gap}</p><small>{gap.current_evidence}</small></article>)}</div></section>}
    <section><SectionTitle title="Your learning path" subtitle="Build the foundations, then put them under interview pressure." /><div className="learning-path">{plan.levels?.map((level, i) => <details className="level-card" key={level.level} open={i === 0}><summary><span className="level-number">0{i + 1}</span><div><span className="eyebrow">{level.level}</span><h3>{level.title}</h3></div><ChevronDown size={18} /></summary><div className="level-content"><div className="objective-list">{level.objectives?.map((objective, n) => <p key={n}><Check size={15} />{objective}</p>)}</div>{level.topics?.map((topic, n) => <article className="topic" key={n}><h4>{topic.title}</h4><p>{topic.explanation}</p><div className="exercise"><span className="eyebrow">TRY THIS</span><p>{topic.exercise}</p></div></article>)}{!!level.questions?.length && <div className="practice-questions"><h4>Check your understanding</h4><ol>{level.questions.map((question, n) => <li key={n}>{question}</li>)}</ol></div>}</div></details>)}</div></section>
    {!!plan.rounds?.length && <section><SectionTitle title="Round-by-round preparation" /><div className="gap-grid">{plan.rounds.map((round, i) => <article className="card gap-card" key={i}><Badge>{label(round.kind)}</Badge><p>{round.focus}</p><ul>{round.practice_questions?.map((question, n) => <li key={n}>{question}</li>)}</ul></article>)}</div></section>}
    {!!plan.next_steps?.length && <div className="card next-steps"><h3>Next steps</h3>{plan.next_steps.map((step, i) => <p key={i}><ArrowUpRight size={16} />{step}</p>)}</div>}
  </div>;
}

export function ReportView({ report, onSeek }: { report: Report; onSeek?: (seconds: number) => void }) {
  return <div className="report-view"><div className="report-summary"><div className="score-ring"><strong>{report.overall_score == null ? '—' : Number(report.overall_score).toFixed(1)}</strong><span>out of 5</span></div><div><span className="eyebrow">YOUR SESSION REVIEW</span><h3>A clearer picture of your performance.</h3><p>{report.summary}</p><small>Practice feedback, not a prediction of hiring outcomes.</small></div></div>
    <div className="dimensions">{report.dimensions?.map(dimension => <article key={dimension.key} className="dimension"><div className="row-between"><h4>{dimension.label}</h4><strong>{dimension.score ?? '—'}<small> / 5</small></strong></div><div className="score-track"><span style={{ width: `${dimension.score == null ? 0 : dimension.score * 20}%` }} /></div><p>{dimension.feedback}</p>{dimension.evidence?.map((evidence, i) => <button className="evidence" key={i} onClick={() => onSeek?.(evidence.start)} disabled={!onSeek}><Play size={13} /><span className="mono">{time(evidence.start)}</span><span>“{evidence.quote}”</span></button>)}</article>)}</div>
    {!!report.strengths?.length && <section><SectionTitle title="Keep doing this" /><div className="strengths">{report.strengths.map((strength, i) => <p key={i}><Check size={17} />{strength}</p>)}</div></section>}
    {!!report.improvements?.length && <section><SectionTitle title="Your next three improvements" subtitle="Specific changes to practice in your next round." /><div className="improvements">{report.improvements.map((improvement, i) => <article className="card improvement" key={i}><span className="level-number">0{i + 1}</span><div><h3>{improvement.title}</h3><p>{improvement.why}</p><div className="exercise"><span className="eyebrow">PUT IT INTO PRACTICE</span><p>{improvement.action}</p></div>{improvement.example_answer && <details className="sample-answer"><summary>A stronger way to answer<ChevronDown size={15} /></summary><p>{improvement.example_answer}</p></details>}</div></article>)}</div></section>}
    {!!report.limitations?.length && <div className="notice"><strong>Context for this review</strong><ul>{report.limitations.map((limitation, i) => <li key={i}>{limitation}</li>)}</ul></div>}
  </div>;
}
