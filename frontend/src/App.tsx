import { useCallback, useEffect, useState } from 'react';
import { ArrowRight, ArrowUpRight, AudioLines, BookOpen, BriefcaseBusiness, CalendarDays, CheckCircle2, ChevronRight, CircleDot, Clock3, Headphones, LayoutDashboard, LoaderCircle, Menu, Plus, Settings as SettingsIcon, ShieldCheck, Sparkles, Sun, Target, TrendingUp, X } from 'lucide-react';
import { api, date, label, latestAssessments, patch, post, time } from './api';
import { AppContext, errorMessage, useApp } from './context';
import type { Bootstrap, Page, Task } from './types';
import { Badge, Button, Empty, SectionTitle } from './ui';
import Jobs from './Jobs';
import Preparation from './Preparation';
import Practice from './Practice';
import Recordings from './Recordings';
import Settings from './Settings';

const navigation = [
  { page: 'Dashboard', icon: LayoutDashboard }, { page: 'Jobs', icon: BriefcaseBusiness },
  { page: 'Preparation', icon: BookOpen }, { page: 'Practice', icon: AudioLines },
  { page: 'Recordings', icon: Headphones }, { page: 'Progress', icon: TrendingUp },
  { page: 'Settings', icon: SettingsIcon },
] as const;
const descriptions: Record<Page, string> = {
  Dashboard: 'Your next opportunity starts with preparation.', Jobs: 'Give every opportunity a clear plan.',
  Preparation: 'Build understanding. Practice with purpose.', Practice: 'A little more prepared, every conversation.',
  Recordings: 'Listen back. Find the moments that matter.', Progress: 'Small improvements. Stronger interviews.', Settings: 'Your coach, on your terms.',
};

export default function App() {
  const [data, setData] = useState<Bootstrap | null>(null);
  const [page, setPage] = useState<Page>('Dashboard');
  const [selectedJob, setSelectedJob] = useState('');
  const [selectedSession, setSelectedSession] = useState('');
  const [menu, setMenu] = useState(false);
  const [toast, setToast] = useState<{message: string; error?: boolean} | null>(null);
  const [loadError, setLoadError] = useState('');
  const [tasksOpen, setTasksOpen] = useState(false);
  const notify = useCallback((message: string, error = false) => setToast({message, error}), []);
  const refresh = useCallback(async () => {
    try { setData(await api<Bootstrap>('/bootstrap')); setLoadError(''); }
    catch (error) { setLoadError(errorMessage(error)); throw error; }
  }, []);
  useEffect(() => { void refresh().catch(() => {}); const timer = setInterval(() => void refresh().catch(() => {}), 6000); return () => clearInterval(timer); }, [refresh]);
  useEffect(() => { if (!toast) return; const timer = setTimeout(() => setToast(null), toast.error ? 12000 : 6000); return () => clearTimeout(timer); }, [toast]);
  const navigate = (next: Page) => { setPage(next); setMenu(false); };
  if (!data) return <div className="boot-screen"><Sun size={44} /><h1>Helios<span>.</span></h1>{loadError ? <><p>{loadError}</p><Button onClick={() => void refresh().catch(() => {})}>Reconnect</Button></> : <p><LoaderCircle className="spin" size={16} /> Opening your workspace…</p>}</div>;
  const activeTasks = data.tasks.filter(t => ['running','queued'].includes(t.status));
  const context = { data, refresh, notify, navigate, selectedJob, setSelectedJob, selectedSession, setSelectedSession };
  return <AppContext.Provider value={context}><div className="app-shell">
    {menu && <div className="sidebar-scrim" onClick={() => setMenu(false)} />}
    <aside className={`sidebar ${menu ? 'open' : ''}`}>
      <a className="brand" href="#" onClick={e => { e.preventDefault(); navigate('Dashboard'); }}><span className="brand-mark"><Sun size={27} strokeWidth={1.5} /></span><span>helios<span className="amber">.</span></span></a>
      <div className="workspace-label"><span className="workspace-avatar">Y</span><div>Your workspace<small>PERSONAL INTERVIEW COACH</small></div></div>
      <p className="nav-label">WORKSPACE</p>
      <nav>{navigation.slice(0,6).map(({page: item, icon: Icon}) => <button key={item} className={`nav-item ${page === item ? 'active' : ''}`} onClick={() => navigate(item)}><Icon size={18} strokeWidth={1.6} /><span>{item}</span>{item === 'Jobs' && data.jobs.length > 0 && <span className="nav-count">{data.jobs.length}</span>}{page === item && <span className="nav-dot" />}</button>)}</nav>
      <div className="sidebar-bottom"><div className="private-card"><ShieldCheck size={20} /><strong>Your space. Your pace.</strong><p>Your interview history stays on this device.</p><span><i /> {data.settings.offline ? 'Offline mode enabled' : 'Cloud connections enabled'}</span></div><button className={`nav-item ${page === 'Settings' ? 'active' : ''}`} onClick={() => navigate('Settings')}><SettingsIcon size={18} strokeWidth={1.6} />Settings</button><div className="sidebar-footer"><span className="tiny-sun">✳</span> BUILT FOR YOUR NEXT CHAPTER</div></div>
    </aside>
    <main className="main-shell"><header className="topbar"><div className="breadcrumb"><button className="icon-button mobile-menu" aria-label="Open navigation" onClick={() => setMenu(true)}><Menu size={20} /></button><span>Workspace</span><ChevronRight size={14} /><strong>{page}</strong></div><div className="topbar-right"><button className="task-trigger" onClick={() => setTasksOpen(!tasksOpen)}>{activeTasks.length ? <LoaderCircle size={13} className="spin" /> : <CircleDot size={13} />}<span>{activeTasks.length ? `${activeTasks.length} processing` : 'Local workspace'}</span></button><span className="profile-avatar">Y</span></div></header>
      <div className="page-content"><div className="page-heading"><div><div className="eyebrow">{page === 'Dashboard' ? 'MAKE YOUR NEXT MOVE COUNT' : 'YOUR INTERVIEW WORKSPACE'}</div><h1>{page === 'Dashboard' ? 'Welcome to your next chapter.' : page}</h1><p>{descriptions[page]}</p></div>{page === 'Dashboard' && <Button onClick={() => navigate('Practice')}><Plus size={17} />Start a practice</Button>}</div>
      {loadError && <div className="notice error-notice">Connection interrupted: {loadError} Your saved work remains on disk.</div>}
      {page === 'Dashboard' && <Dashboard />}{page === 'Jobs' && <Jobs />}{page === 'Preparation' && <Preparation />}{page === 'Practice' && <Practice />}{page === 'Recordings' && <Recordings />}{page === 'Progress' && <Progress />}{page === 'Settings' && <Settings />}
      <footer className="page-footer"><span><Sun size={13} />Helios · A little more ready, every day.</span><span>{data.settings.offline ? 'Local first. Private by design.' : 'Cloud AI enabled in Settings.'}</span></footer></div>
    </main>
    {tasksOpen && <TaskPanel onClose={() => setTasksOpen(false)} />}
    {toast && <div role={toast.error ? 'alert' : 'status'} className={`toast ${toast.error ? 'error' : ''}`}><span>{toast.message}</span><button className="icon-button" onClick={() => setToast(null)} aria-label="Dismiss notification"><X size={17} /></button></div>}
  </div></AppContext.Provider>;
}

function Dashboard() {
  const {data, navigate, setSelectedJob, setSelectedSession} = useApp();
  const complete = data.sessions.filter(s => s.source === 'practice' && ['completed','reviewed'].includes(s.status));
  const upcoming = data.rounds.filter(r => ['scheduled','upcoming'].includes(r.status)).sort((a,b) => a.scheduled_at.localeCompare(b.scheduled_at));
  const scores = latestAssessments(data.assessments).map(a => a.report.overall_score).filter((s): s is number => s != null);
  const ready = data.readiness.llm.ready;
  return <>
    <div className="hero-card"><div className="hero-copy"><div className="hero-kicker"><span className="live-dot" /> YOUR PERSONAL INTERVIEW COACH</div><h2>Meet the opportunity.<br /><span>Become the candidate.</span></h2><p>From the first “tell me about yourself” to the toughest follow-up. Build your confidence, one conversation at a time.</p><div className="hero-actions"><Button onClick={() => navigate(data.jobs.length ? 'Preparation' : 'Jobs')}>{data.jobs.length ? 'Explore your preparation' : 'Add your first opportunity'}<ArrowRight size={16} /></Button><button className="text-link" onClick={() => navigate('Practice')}>Meet Helios<ArrowUpRight size={15} /></button></div><div className="hero-footnote"><ShieldCheck size={14} />Private practice. Honest feedback. Real progress.</div></div><div className="solar-art" aria-hidden="true"><div className="orbit orbit-one" /><div className="orbit orbit-two" /><div className="orbit orbit-three" /><div className="solar-core"><Sun size={52} strokeWidth={.8} /></div><span className="orbit-star star-one" /><span className="orbit-star star-two" /><span className="solar-caption">YOUR POTENTIAL, IN ORBIT</span></div></div>
    <div className="stat-grid">{[{label:'Active opportunities',value:data.jobs.filter(j=>j.status !== 'archived').length,icon:BriefcaseBusiness,foot:'Every role, one place'}, {label:'Practice sessions',value:complete.length,icon:AudioLines,foot:`${Math.round(complete.reduce((n,s)=>n+s.duration_seconds,0)/60)} minutes invested in you`}, {label:'Upcoming rounds',value:upcoming.length,icon:CalendarDays,foot:upcoming[0] ? `Next · ${date(upcoming[0].scheduled_at)}` : 'Your next chapter awaits'}, {label:'Average practice score',value:scores.length ? (scores.reduce((a,b)=>a+b,0)/scores.length).toFixed(1) : '—',icon:TrendingUp,foot:scores.length ? 'Across assessed sessions · out of 5' : 'Complete a session to see your score'}].map(stat => <div className="stat-card" key={stat.label}><div className="stat-top"><span>{stat.label}</span><stat.icon size={17} /></div><strong>{stat.value}</strong><small>{stat.foot}</small></div>)}</div>
    {!ready && <div className="setup-banner"><span className="setup-icon"><Sparkles size={20} /></span><div><h3>Make Helios your own</h3><p>Connect a local model to create your first preparation plan. Voice can be set up whenever you’re ready.</p></div><Button variant="secondary" onClick={() => navigate('Settings')}>Set up your coach<ArrowRight size={15} /></Button></div>}
    <div className="dashboard-grid"><section className="card dashboard-opportunities"><SectionTitle title="Your opportunities" subtitle="A focused place for every next step." action={<button className="text-link" onClick={() => navigate('Jobs')}>View all<ArrowUpRight size={14} /></button>} />{!data.jobs.length ? <Empty icon={BriefcaseBusiness} title="A new role. A fresh start." text="Add a job description and let Helios turn it into a personal preparation plan." compact><Button variant="secondary" onClick={() => navigate('Jobs')}><Plus size={15} />Add opportunity</Button></Empty> : data.jobs.slice(0,4).map((job,i) => <button className="opportunity-row" key={job.id} onClick={() => {setSelectedJob(job.id);navigate('Jobs');}}><span className={`company-avatar color-${i%3}`}>{(job.company || job.title).slice(0,1).toUpperCase()}</span><span className="opportunity-copy"><strong>{job.title}</strong><small>{job.company || 'Personal preparation'} · {label(job.seniority)}</small></span><Badge color="amber">{label(job.status)}</Badge><ChevronRight size={15} /></button>)}</section>
    <section className="card next-round"><SectionTitle title="On the horizon" action={<CalendarDays size={18} />} />{upcoming[0] ? <div className="upcoming-detail"><Badge color="amber">UPCOMING ROUND</Badge><h3>{upcoming[0].title}</h3><p>{data.jobs.find(j=>j.id===upcoming[0].job_id)?.company}</p><div className="round-date"><CalendarDays size={17} />{date(upcoming[0].scheduled_at,true)}</div><Button variant="secondary" onClick={() => {setSelectedJob(upcoming[0].job_id);navigate('Practice');}}>Prepare for this round<ArrowRight size={15} /></Button></div> : <Empty icon={CalendarDays} title="Room for something great" text="Add an interview round to keep your next conversation in view." compact><button className="text-link" onClick={() => navigate('Jobs')}>Plan a round<Plus size={14} /></button></Empty>}</section></div>
    <section className="card"><SectionTitle title="Recent practice" subtitle="Every session is a step forward." action={<button className="text-link" onClick={() => navigate('Recordings')}>All recordings<ArrowUpRight size={14} /></button>} />{!data.sessions.length ? <div className="recent-empty"><span className="audio-bars"><i/><i/><i/><i/><i/></span><div><h3>Your first conversation is the hardest part.</h3><p>Helios will ask the questions. You bring the potential.</p></div><Button variant="secondary" onClick={() => navigate('Practice')}>Let’s practice<ArrowRight size={15} /></Button></div> : <div className="session-list">{data.sessions.slice(0,4).map(session => <button className="session-row" key={session.id} onClick={() => {setSelectedSession(session.id);navigate('Recordings');}}><span className="session-icon"><Headphones size={18} /></span><span className="session-copy"><strong>{session.title}</strong><small>{label(session.kind)} · {date(session.created_at)}</small></span><span className="session-duration"><Clock3 size={13} />{time(session.duration_seconds)}</span><Badge color={['completed','reviewed'].includes(session.status)?'green':'neutral'}>{label(session.status)}</Badge><ChevronRight size={16} /></button>)}</div>}</section>
  </>;
}

function TaskPanel({onClose}:{onClose:()=>void}) {
  const {data,refresh,notify}=useApp();
  const run=async(task:Task, action:string)=>{try{await post(`/tasks/${task.id}/${action}`);await refresh();}catch(e){notify(errorMessage(e),true);}};
  return <div className="task-panel card"><div className="row-between"><h3>Background activity</h3><button className="icon-button" onClick={onClose} aria-label="Close activity"><X size={18}/></button></div>{!data.tasks.length?<p className="muted">Nothing processing. Your next step is up to you.</p>:<div className="task-list">{data.tasks.slice(0,12).map(task=><div className="task-item" key={task.id}><div className="row-between"><strong>{label(task.kind)}</strong><Badge color={task.status==='failed'?'red':task.status==='completed'?'green':'neutral'}>{label(task.status)}</Badge></div><p>{task.error || task.message}</p>{['running','queued'].includes(task.status)&&<div className="score-track"><span style={{width:`${task.progress<=1?task.progress*100:task.progress}%`}}/></div>}<div className="task-actions">{task.status==='failed'||task.status==='cancelled'?<button className="text-link" onClick={()=>void run(task,'retry')}>Retry</button>:['running','queued'].includes(task.status)?<button className="text-link" onClick={()=>void run(task,'cancel')}>Cancel</button>:null}</div></div>)}</div>}</div>;
}

function Progress() {
  const {data,refresh,notify,navigate}=useApp();
  const assessments=latestAssessments(data.assessments).sort((a,b)=>a.created_at.localeCompare(b.created_at));
  const pending=data.drills.filter(d=>!d.completed);
  const toggle=async(id:string,completed:boolean)=>{try{await patch(`/drills/${id}`,{completed});await refresh();}catch(e){notify(errorMessage(e),true);}};
  return <>{!assessments.length?<div className="card"><Empty icon={TrendingUp} title="Progress starts with one conversation" text="Complete and assess a practice session to see your strengths, trends, and focused exercises."><Button onClick={()=>navigate('Practice')}>Start practicing<ArrowRight size={15}/></Button></Empty></div>:<section className="card progress-card"><SectionTitle title="Your practice over time" subtitle="Scores are a reflection tool, not a hiring prediction. Different roles and difficulties may not be directly comparable."/><div className="chart" role="img" aria-label="Practice scores from oldest to newest">{assessments.slice(-12).map((assessment,i)=><div className="chart-column" key={assessment.id}><strong>{assessment.report.overall_score ?? '—'}</strong><div className="chart-bar" style={{height:`${(assessment.report.overall_score??0)*30}px`}}/><span>{i+1}</span><small>{date(assessment.created_at)}</small></div>)}</div></section>}
    <section><SectionTitle title="Your practice toolkit" subtitle={`${pending.length} focused ${pending.length===1?'drill':'drills'} to work through. Make the improvement tangible.`}/>{!data.drills.length?<div className="card"><Empty compact icon={Target} title="Practice with a purpose" text="Your session reviews will turn improvement areas into exercises you can come back to."/></div>:<div className="drill-grid">{data.drills.map(drill=><article className={`card drill-card ${drill.completed?'done':''}`} key={drill.id}><div className="row-between"><Badge color={drill.completed?'green':'amber'}>{drill.completed?'Completed':drill.skill}</Badge><Target size={18}/></div><h3>{drill.title}</h3><p>{drill.instruction}</p><button className="text-link" onClick={()=>void toggle(drill.id,!drill.completed)}><CheckCircle2 size={16}/>{drill.completed?'Mark as unfinished':'Mark as practiced'}</button></article>)}</div>}</section></>;
}
