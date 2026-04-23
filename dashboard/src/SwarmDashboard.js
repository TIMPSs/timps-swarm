import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, BarChart, Bar, Cell, PieChart, Pie
} from 'recharts';
import {
  Activity, Cpu, GitBranch, Shield, Zap, Box, Terminal,
  Clock, CheckCircle, Play, Pause, RotateCcw, Layers,
  AlertTriangle, Send, ChevronRight, X, Download
} from 'lucide-react';

// ── Constants ──────────────────────────────────────────────────────────────

const WS_URL = process.env.REACT_APP_WS_URL || 'ws://localhost:8000/ws';
const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

const AGENT_META = {
  orchestrator:          { color: '#818cf8', icon: '🎯', label: 'Orchestrator' },
  product_manager:       { color: '#a78bfa', icon: '📋', label: 'Product Mgr' },
  architect:             { color: '#22d3ee', icon: '🏗️', label: 'Architect' },
  code_generator:        { color: '#34d399', icon: '⚡', label: 'Code Gen' },
  code_reviewer:         { color: '#fbbf24', icon: '🔍', label: 'Reviewer' },
  qa_tester:             { color: '#f472b6', icon: '🧪', label: 'QA Tester' },
  security_auditor:      { color: '#f87171', icon: '🛡️', label: 'Security' },
  performance_optimizer: { color: '#fb923c', icon: '🚀', label: 'Perf Opt' },
  documentation_writer:  { color: '#a3e635', icon: '📝', label: 'Docs' },
  devops:                { color: '#94a3b8', icon: '🔧', label: 'DevOps' },
};

const STATUS_STYLE = {
  pending:   { color: '#64748b', bg: '#64748b15', pulse: false },
  running:   { color: '#3b82f6', bg: '#3b82f615', pulse: true  },
  completed: { color: '#10b981', bg: '#10b98115', pulse: false },
  failed:    { color: '#ef4444', bg: '#ef444415', pulse: false },
  retrying:  { color: '#f59e0b', bg: '#f59e0b15', pulse: true  },
};

// ── Mock data generator (used until backend connects) ─────────────────────

function makeMock() {
  const agents = Object.keys(AGENT_META).map((role, i) => ({
    id: `a${i}`, name: role, role,
    status: ['pending','running','completed','running','completed'][i % 5],
    current_task: i % 2 === 0 ? `Processing task-${10+i}` : null,
    adapter_loaded: i % 3 === 0 ? 'java_npe' : i % 3 === 1 ? 'python_keyerror' : 'base',
    latency_ms: 200 + i * 80,
    tokens_generated: i * 540,
    last_active: new Date().toISOString(),
    color: AGENT_META[role].color,
  }));

  const tasks = Array.from({ length: 30 }, (_, i) => ({
    id: `task-${i}`,
    description: ['Fix NullPointerException in AuthService','Write unit tests for API','Review PR #42 security','SQL injection audit','Optimise N+1 queries','Generate README','Build Dockerfile','Design DB schema'][i % 8],
    assigned_to: Object.keys(AGENT_META)[i % 10],
    status: ['pending','running','completed','failed'][i % 4],
    dependencies: i > 0 ? [`task-${i-1}`] : [],
    retry_count: 0,
  }));

  const metrics = {
    total_agents: 10, active_agents: 4, completed_tasks: 18,
    failed_tasks: 2, avg_latency: 420, throughput: 3.2, queue_depth: 5,
  };

  const history = Array.from({ length: 20 }, (_, i) => ({
    time: `${i}m`, throughput: +(2 + Math.sin(i/3)*1.5).toFixed(1),
    active: 2 + Math.floor(Math.random()*4), errors: i % 7 === 0 ? 1 : 0,
  }));

  return { agents, tasks, metrics, history, run_id: 'demo', iteration: 0, artifacts: [], completed: false };
}

// ── Sub-components ─────────────────────────────────────────────────────────

const css = {
  card: {
    background: 'rgba(15,23,42,0.7)',
    border: '1px solid rgba(99,102,241,0.15)',
    borderRadius: 14,
    padding: '20px 24px',
    backdropFilter: 'blur(12px)',
  },
};

function MetricCard({ title, value, icon: Icon, color, sub }) {
  return (
    <div style={{ ...css.card, display:'flex', alignItems:'center', gap:16, minWidth:180 }}>
      <div style={{ width:48, height:48, borderRadius:12, background:`${color}18`,
        display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0 }}>
        <Icon size={22} color={color} />
      </div>
      <div>
        <div style={{ fontSize:11, color:'#64748b', textTransform:'uppercase', letterSpacing:'0.08em', fontFamily:'Space Grotesk, sans-serif' }}>{title}</div>
        <div style={{ fontSize:26, fontWeight:800, color:'#f1f5f9', marginTop:2, fontFamily:'Space Grotesk, sans-serif' }}>{value}</div>
        {sub && <div style={{ fontSize:11, color:'#475569', marginTop:2 }}>{sub}</div>}
      </div>
    </div>
  );
}

function AgentCard({ agent, onClick }) {
  const meta = AGENT_META[agent.role] || {};
  const st   = STATUS_STYLE[agent.status] || STATUS_STYLE.pending;
  return (
    <div onClick={() => onClick(agent)} style={{
      ...css.card,
      cursor:'pointer', position:'relative', overflow:'hidden',
      borderColor: `${meta.color}30`,
      transition:'transform 0.15s, box-shadow 0.15s',
    }}
    onMouseEnter={e => { e.currentTarget.style.transform='translateY(-3px)'; e.currentTarget.style.boxShadow=`0 8px 24px ${meta.color}22`; }}
    onMouseLeave={e => { e.currentTarget.style.transform='translateY(0)';   e.currentTarget.style.boxShadow='none'; }}>
      {/* Glow bar */}
      <div style={{ position:'absolute', top:0, left:0, right:0, height:2, background:`linear-gradient(90deg, transparent, ${meta.color}, transparent)` }} />

      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:10 }}>
        <span style={{ fontSize:20 }}>{meta.icon}</span>
        {/* Status dot */}
        <div style={{
          width:8, height:8, borderRadius:'50%', background:st.color,
          boxShadow: st.pulse ? `0 0 0 3px ${st.color}30` : 'none',
          animation: st.pulse ? 'pulse 1.6s infinite' : 'none',
        }} />
      </div>

      <div style={{ fontSize:12, fontWeight:700, color:meta.color, marginBottom:4, fontFamily:'Space Grotesk, sans-serif' }}>
        {meta.label}
      </div>

      <div style={{ fontSize:10, color:'#475569', marginBottom:8, fontFamily:'JetBrains Mono, monospace' }}>
        {agent.name}
      </div>

      {agent.current_task && (
        <div style={{ fontSize:10, color:'#64748b', whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis',
          background:'rgba(99,102,241,0.07)', borderRadius:6, padding:'4px 8px' }}>
          ▶ {agent.current_task}
        </div>
      )}

      {agent.adapter_loaded && agent.adapter_loaded !== 'base' && (
        <div style={{ marginTop:8, display:'inline-block', fontSize:9, padding:'2px 7px',
          borderRadius:4, background:`${meta.color}20`, color:meta.color, fontWeight:700 }}>
          {agent.adapter_loaded}
        </div>
      )}
    </div>
  );
}

function TaskRow({ task }) {
  const meta = AGENT_META[task.assigned_to] || {};
  const st   = STATUS_STYLE[task.status]   || STATUS_STYLE.pending;
  return (
    <div style={{ display:'flex', alignItems:'center', gap:12, padding:'10px 14px',
      background:'rgba(15,23,42,0.5)', borderRadius:8, borderLeft:`3px solid ${st.color}` }}>
      <span style={{ fontSize:16 }}>{meta.icon || '📦'}</span>
      <div style={{ flex:1, minWidth:0 }}>
        <div style={{ fontSize:12, color:'#e2e8f0', fontWeight:600, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis' }}>
          {task.description}
        </div>
        <div style={{ fontSize:10, color:'#475569', marginTop:2 }}>
          {task.id} → <span style={{ color: meta.color || '#94a3b8' }}>{task.assigned_to}</span>
        </div>
      </div>
      <div style={{ fontSize:10, fontWeight:700, padding:'3px 10px', borderRadius:6,
        background:st.bg, color:st.color, whiteSpace:'nowrap' }}>
        {task.status}
      </div>
    </div>
  );
}

function AgentModal({ agent, onClose }) {
  if (!agent) return null;
  const meta = AGENT_META[agent.role] || {};
  const st   = STATUS_STYLE[agent.status] || STATUS_STYLE.pending;
  return (
    <div onClick={onClose} style={{
      position:'fixed', inset:0, background:'rgba(0,0,0,0.75)',
      display:'flex', alignItems:'center', justifyContent:'center', zIndex:1000,
      backdropFilter:'blur(6px)',
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        ...css.card, width:460, maxWidth:'90%',
        borderColor:`${meta.color}40`,
        boxShadow:`0 32px 64px rgba(0,0,0,0.6), 0 0 0 1px ${meta.color}30`,
      }}>
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:20 }}>
          <div style={{ display:'flex', alignItems:'center', gap:12 }}>
            <span style={{ fontSize:28 }}>{meta.icon}</span>
            <div>
              <div style={{ fontSize:18, fontWeight:800, color:'#f1f5f9', fontFamily:'Space Grotesk, sans-serif' }}>{meta.label}</div>
              <div style={{ fontSize:11, color:'#475569', fontFamily:'monospace' }}>{agent.name}</div>
            </div>
          </div>
          <button onClick={onClose} style={{ background:'none', border:'none', color:'#64748b', cursor:'pointer' }}>
            <X size={20} />
          </button>
        </div>

        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12, marginBottom:16 }}>
          {[
            ['Status', agent.status, st.color],
            ['Adapter', agent.adapter_loaded || 'base', meta.color],
            ['Latency', `${agent.latency_ms}ms`, '#22d3ee'],
            ['Tokens', (agent.tokens_generated||0).toLocaleString(), '#a78bfa'],
          ].map(([label, val, c]) => (
            <div key={label} style={{ background:'rgba(99,102,241,0.05)', borderRadius:8, padding:'10px 14px' }}>
              <div style={{ fontSize:10, color:'#475569', textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:4 }}>{label}</div>
              <div style={{ fontSize:15, fontWeight:700, color: c }}>{val}</div>
            </div>
          ))}
        </div>

        {agent.current_task && (
          <div style={{ background:'rgba(99,102,241,0.07)', borderRadius:8, padding:'10px 14px', fontSize:12, color:'#94a3b8', fontFamily:'monospace' }}>
            ▶ {agent.current_task}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Custom Tooltip ─────────────────────────────────────────────────────────
function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background:'#0d1626', border:'1px solid #1e3a5f', borderRadius:8, padding:'10px 14px', fontSize:11, fontFamily:'monospace' }}>
      <div style={{ color:'#64748b', marginBottom:4 }}>{label}</div>
      {payload.map(p => (
        <div key={p.dataKey} style={{ color: p.color }}>{p.dataKey}: {p.value}</div>
      ))}
    </div>
  );
}

// ── Run Request Form ───────────────────────────────────────────────────────
function RunForm({ onSubmit, loading }) {
  const [req, setReq] = useState('');
  const [lang, setLang] = useState('python');

  const submit = () => {
    if (!req.trim()) return;
    onSubmit(req, lang);
    setReq('');
  };

  return (
    <div style={{ ...css.card, display:'flex', gap:12, alignItems:'flex-end' }}>
      <div style={{ flex:1 }}>
        <div style={{ fontSize:11, color:'#64748b', marginBottom:6, textTransform:'uppercase', letterSpacing:'0.08em' }}>New Swarm Task</div>
        <textarea
          value={req}
          onChange={e => setReq(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && e.metaKey) submit(); }}
          placeholder='e.g. "Fix NullPointerException in my Spring Boot service and write tests"'
          rows={2}
          style={{
            width:'100%', background:'rgba(15,23,42,0.8)', border:'1px solid rgba(99,102,241,0.25)',
            borderRadius:8, padding:'10px 14px', color:'#e2e8f0', fontSize:13,
            fontFamily:'JetBrains Mono, monospace', resize:'none', outline:'none',
          }}
        />
      </div>
      <select value={lang} onChange={e => setLang(e.target.value)} style={{
        background:'rgba(15,23,42,0.8)', border:'1px solid rgba(99,102,241,0.25)',
        borderRadius:8, padding:'10px 14px', color:'#94a3b8', fontSize:12, fontFamily:'monospace',
        cursor:'pointer', height:44,
      }}>
        {['python','java','javascript','typescript','go','rust','cpp'].map(l => (
          <option key={l} value={l}>{l}</option>
        ))}
      </select>
      <button onClick={submit} disabled={loading || !req.trim()} style={{
        display:'flex', alignItems:'center', gap:8, padding:'10px 20px',
        borderRadius:8, border:'none', cursor: loading ? 'not-allowed' : 'pointer',
        background: loading ? '#1e293b' : 'linear-gradient(135deg, #6366f1, #818cf8)',
        color: loading ? '#475569' : '#fff', fontSize:13, fontWeight:700,
        fontFamily:'Space Grotesk, sans-serif', height:44, whiteSpace:'nowrap',
        transition:'opacity 0.2s',
      }}>
        {loading ? <Activity size={14} className="spin" /> : <Send size={14} />}
        {loading ? 'Running…' : 'Launch Swarm'}
      </button>
    </div>
  );
}

// ── Main Dashboard ─────────────────────────────────────────────────────────

export default function SwarmDashboard() {
  const [data, setData]           = useState(makeMock());
  const [live, setLive]           = useState(true);
  const [filter, setFilter]       = useState('all');
  const [selectedAgent, setAgent] = useState(null);
  const [loading, setLoading]     = useState(false);
  const [wsStatus, setWsStatus]   = useState('connecting');
  const [log, setLog]             = useState([]);
  const wsRef = useRef(null);
  const logRef = useRef(null);

  const addLog = useCallback((msg, color='#64748b') => {
    const ts = new Date().toLocaleTimeString();
    setLog(prev => [...prev.slice(-100), { ts, msg, color }]);
  }, []);

  // WebSocket
  useEffect(() => {
    if (!live) return;
    let reconnectTimer;

    const connect = () => {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => { setWsStatus('connected'); addLog('WebSocket connected', '#34d399'); };
      ws.onclose = () => {
        setWsStatus('disconnected');
        addLog('WebSocket disconnected — reconnecting…', '#f87171');
        reconnectTimer = setTimeout(connect, 3000);
      };
      ws.onerror = () => { setWsStatus('error'); addLog('WebSocket error', '#f87171'); };
      ws.onmessage = e => {
        try {
          const d = JSON.parse(e.data);
          setData(d);
          const done = d.metrics?.completed_tasks || 0;
          if (done > 0) addLog(`Tasks completed: ${done}`, '#34d399');
        } catch {}
      };
    };

    connect();
    return () => { wsRef.current?.close(); clearTimeout(reconnectTimer); };
  }, [live, addLog]);

  // Scroll log
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log]);

  // Launch swarm
  const launchSwarm = async (request, language) => {
    setLoading(true);
    addLog(`Launching swarm: "${request.slice(0,60)}…"`, '#818cf8');
    try {
      const res = await fetch(`${API_URL}/swarm/run`, {
        method:'POST',
        headers:{ 'Content-Type':'application/json' },
        body: JSON.stringify({ request, language, max_iterations:10 }),
      });
      const d = await res.json();
      addLog(`Run started: ${d.run_id}`, '#34d399');
    } catch (err) {
      addLog(`Launch failed: ${err.message}`, '#f87171');
    } finally {
      setLoading(false);
    }
  };

  const agents  = data.agents  || [];
  const tasks   = data.tasks   || [];
  const metrics = data.metrics || {};
  const history = data.history || [];

  const filtered = filter === 'all' ? agents
    : agents.filter(a => a.role === filter || a.status === filter);

  const roleDist = Object.entries(
    agents.reduce((acc, a) => ({ ...acc, [a.role]: (acc[a.role]||0)+1 }), {})
  ).map(([name, value]) => ({ name, value, fill: AGENT_META[name]?.color || '#64748b' }));

  const statusDist = Object.entries(
    tasks.reduce((acc, t) => ({ ...acc, [t.status]: (acc[t.status]||0)+1 }), {})
  ).map(([name, value]) => ({ name, value, fill: STATUS_STYLE[name]?.color || '#64748b' }));

  const wsColors = { connected:'#34d399', connecting:'#f59e0b', disconnected:'#ef4444', error:'#ef4444' };

  return (
    <div style={{ minHeight:'100vh', padding:'24px 28px', maxWidth:1600, margin:'0 auto' }}>
      <style>{`
        @keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:0.6;transform:scale(1.15)} }
        @keyframes spin  { to{transform:rotate(360deg)} }
        .spin { animation: spin 1s linear infinite; }
        * { transition: background 0.2s, border-color 0.2s; }
      `}</style>

      {/* ── Header ── */}
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:28 }}>
        <div>
          <div style={{ display:'flex', alignItems:'center', gap:12, marginBottom:4 }}>
            <Layers size={30} color="#818cf8" />
            <h1 style={{ fontSize:26, fontWeight:800, color:'#f1f5f9', fontFamily:'Space Grotesk, sans-serif', letterSpacing:'-0.03em' }}>
              TIMPS Swarm Control
            </h1>
            <div style={{ fontSize:10, padding:'3px 10px', borderRadius:20,
              background: `${wsColors[wsStatus]}18`, color: wsColors[wsStatus],
              fontWeight:700, fontFamily:'monospace', textTransform:'uppercase' }}>
              ● {wsStatus}
            </div>
          </div>
          <p style={{ fontSize:12, color:'#475569', fontFamily:'monospace' }}>
            {metrics.total_agents || 0} agents · {metrics.active_agents || 0} active · iteration {data.iteration || 0}
          </p>
        </div>
        <div style={{ display:'flex', gap:10 }}>
          <button onClick={() => setLive(l => !l)} style={{
            display:'flex', alignItems:'center', gap:6, padding:'8px 16px', borderRadius:8,
            border:`1px solid ${live ? '#34d399' : '#f87171'}40`,
            background: live ? '#34d39910' : '#f8717110',
            color: live ? '#34d399' : '#f87171',
            cursor:'pointer', fontSize:12, fontWeight:700, fontFamily:'Space Grotesk, sans-serif',
          }}>
            {live ? <Pause size={13}/> : <Play size={13}/>} {live ? 'LIVE' : 'PAUSED'}
          </button>
          <button onClick={() => setData(makeMock())} style={{
            display:'flex', alignItems:'center', gap:6, padding:'8px 14px', borderRadius:8,
            border:'1px solid rgba(99,102,241,0.2)', background:'transparent',
            color:'#64748b', cursor:'pointer', fontSize:12,
          }}>
            <RotateCcw size={13}/> Refresh
          </button>
        </div>
      </div>

      {/* ── Run Form ── */}
      <div style={{ marginBottom:24 }}>
        <RunForm onSubmit={launchSwarm} loading={loading} />
      </div>

      {/* ── Metric Cards ── */}
      <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(190px,1fr))', gap:14, marginBottom:24 }}>
        <MetricCard title="Active Agents"    value={metrics.active_agents||0}  icon={Cpu}         color="#3b82f6" sub={`of ${metrics.total_agents||0} total`}/>
        <MetricCard title="Completed Tasks"  value={metrics.completed_tasks||0} icon={CheckCircle} color="#10b981" sub={`${metrics.failed_tasks||0} failed`}/>
        <MetricCard title="Throughput"       value={`${metrics.throughput||0}/s`} icon={Zap}       color="#f59e0b" sub="tasks per second"/>
        <MetricCard title="Queue Depth"      value={metrics.queue_depth||0}     icon={Box}         color="#ec4899" sub="pending tasks"/>
        <MetricCard title="Avg Latency"      value={`${metrics.avg_latency||0}ms`} icon={Clock}   color="#22d3ee" sub="response time"/>
      </div>

      {/* ── Charts ── */}
      <div style={{ display:'grid', gridTemplateColumns:'2fr 1fr 1fr', gap:16, marginBottom:24 }}>
        <div style={{ ...css.card }}>
          <div style={{ fontSize:12, color:'#475569', marginBottom:14, fontFamily:'Space Grotesk, sans-serif', fontWeight:700, textTransform:'uppercase', letterSpacing:'0.06em' }}>
            Throughput History
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={history}>
              <CartesianGrid strokeDasharray="2 4" stroke="#0f172a" />
              <XAxis dataKey="time" stroke="#334155" fontSize={10} tick={{ fill:'#475569' }} />
              <YAxis stroke="#334155" fontSize={10} tick={{ fill:'#475569' }} />
              <Tooltip content={<ChartTooltip/>} />
              <Line type="monotone" dataKey="throughput" stroke="#818cf8" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="active"     stroke="#34d399" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="errors"     stroke="#f87171" strokeWidth={1.5} dot={false} strokeDasharray="4 2"/>
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div style={{ ...css.card }}>
          <div style={{ fontSize:12, color:'#475569', marginBottom:14, fontFamily:'Space Grotesk, sans-serif', fontWeight:700, textTransform:'uppercase', letterSpacing:'0.06em' }}>
            Agent Roles
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <PieChart>
              <Pie data={roleDist} cx="50%" cy="50%" innerRadius={45} outerRadius={72} paddingAngle={3} dataKey="value">
                {roleDist.map((entry,i) => <Cell key={i} fill={entry.fill} opacity={0.85}/>)}
              </Pie>
              <Tooltip content={<ChartTooltip/>} />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <div style={{ ...css.card }}>
          <div style={{ fontSize:12, color:'#475569', marginBottom:14, fontFamily:'Space Grotesk, sans-serif', fontWeight:700, textTransform:'uppercase', letterSpacing:'0.06em' }}>
            Task Status
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={statusDist} barSize={24}>
              <CartesianGrid strokeDasharray="2 4" stroke="#0f172a" />
              <XAxis dataKey="name" stroke="#334155" fontSize={9} tick={{ fill:'#475569' }} />
              <YAxis stroke="#334155" fontSize={10} tick={{ fill:'#475569' }} />
              <Tooltip content={<ChartTooltip/>} />
              <Bar dataKey="value" radius={[5,5,0,0]}>
                {statusDist.map((entry,i) => <Cell key={i} fill={entry.fill}/>)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* ── Agent Grid ── */}
      <div style={{ marginBottom:24 }}>
        <div style={{ display:'flex', gap:8, flexWrap:'wrap', marginBottom:14 }}>
          {['all','running','completed','failed',...Object.keys(AGENT_META)].map(f => (
            <button key={f} onClick={() => setFilter(f)} style={{
              padding:'5px 13px', borderRadius:6, border:'1px solid',
              borderColor: filter===f ? '#818cf8' : 'rgba(99,102,241,0.15)',
              background: filter===f ? '#818cf820' : 'transparent',
              color: filter===f ? '#818cf8' : '#475569',
              cursor:'pointer', fontSize:11, fontWeight:600, fontFamily:'monospace',
              textTransform:'capitalize',
            }}>
              {f.replace(/_/g,' ')}
            </button>
          ))}
        </div>

        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(170px,1fr))', gap:12 }}>
          {filtered.map(agent => (
            <AgentCard key={agent.id} agent={agent} onClick={setAgent}/>
          ))}
        </div>
      </div>

      {/* ── Active Tasks ── */}
      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16, marginBottom:24 }}>
        <div style={{ ...css.card }}>
          <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:14 }}>
            <GitBranch size={14} color="#818cf8"/>
            <span style={{ fontSize:12, color:'#475569', fontFamily:'Space Grotesk, sans-serif', fontWeight:700, textTransform:'uppercase', letterSpacing:'0.06em' }}>
              Active Pipeline
            </span>
          </div>
          <div style={{ display:'flex', flexDirection:'column', gap:8, maxHeight:320, overflowY:'auto' }}>
            {tasks.filter(t => t.status==='running' || t.status==='pending').slice(0,12).map(t => (
              <TaskRow key={t.id} task={t}/>
            ))}
            {tasks.filter(t => t.status==='running'||t.status==='pending').length === 0 && (
              <div style={{ color:'#334155', textAlign:'center', padding:24, fontSize:12 }}>No active tasks</div>
            )}
          </div>
        </div>

        <div style={{ ...css.card }}>
          <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:14 }}>
            <Terminal size={14} color="#34d399"/>
            <span style={{ fontSize:12, color:'#475569', fontFamily:'Space Grotesk, sans-serif', fontWeight:700, textTransform:'uppercase', letterSpacing:'0.06em' }}>
              Swarm Log
            </span>
          </div>
          <div ref={logRef} style={{ fontFamily:'JetBrains Mono, monospace', fontSize:11, maxHeight:320, overflowY:'auto', display:'flex', flexDirection:'column', gap:4 }}>
            {log.length === 0 && (
              <div style={{ color:'#334155', padding:8 }}>Waiting for swarm activity…</div>
            )}
            {log.map((entry, i) => (
              <div key={i} style={{ display:'flex', gap:10 }}>
                <span style={{ color:'#334155', flexShrink:0 }}>{entry.ts}</span>
                <span style={{ color: entry.color }}>{entry.msg}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Artifacts ── */}
      {data.artifacts?.length > 0 && (
        <div style={{ ...css.card, marginBottom:24 }}>
          <div style={{ fontSize:12, color:'#475569', marginBottom:12, fontFamily:'Space Grotesk, sans-serif', fontWeight:700, textTransform:'uppercase', letterSpacing:'0.06em' }}>
            Generated Artifacts
          </div>
          <div style={{ display:'flex', flexWrap:'wrap', gap:8 }}>
            {data.artifacts.map((path, i) => (
              <div key={i} style={{ display:'flex', alignItems:'center', gap:8, padding:'6px 14px',
                background:'rgba(99,102,241,0.07)', border:'1px solid rgba(99,102,241,0.15)',
                borderRadius:8, fontSize:11, fontFamily:'monospace', color:'#818cf8' }}>
                <Download size={11}/>
                {path}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Footer ── */}
      <div style={{ textAlign:'center', color:'#1e293b', fontSize:11, fontFamily:'monospace', paddingBottom:20 }}>
        TIMPS Swarm v1.0 · 10 Agents · 20 Specialised Adapters · {new Date().toLocaleString()}
      </div>

      {/* ── Agent Detail Modal ── */}
      <AgentModal agent={selectedAgent} onClose={() => setAgent(null)}/>
    </div>
  );
}
