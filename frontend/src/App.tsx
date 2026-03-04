import { useEffect, useMemo, useRef, useState } from 'react'

type Note = { start_s: number; dur_s: number; midi: number; name: string; confidence: number }
type Candidate = { chord_name: string; roman: string; quality: string; score: number }
type Progression = { id: string; score: number; chords: { segment: number; chord_name: string; roman: string }[] }
type Result = {
  bpm: number
  bpm_confidence: number
  time_signature: string
  key_candidates: { key: string; mode: string; confidence: number }[]
  melody_notes: Note[]
  segments: { bar_index: number; start_s: number; end_s: number }[]
  chord_candidates_by_segment: Record<string, Candidate[]>
  progressions: Progression[]
  confidence: Record<string, number>
  warnings: string[]
}

const major = [0, 4, 7]
const minor = [0, 3, 7]
const PITCHES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

const readOnly = (v: number) => Number(v.toFixed(2))

export default function App() {
  const [audioUrl, setAudioUrl] = useState('')
  const [jobId, setJobId] = useState('')
  const [logs, setLogs] = useState<string[]>([])
  const [result, setResult] = useState<Result | null>(null)
  const [bpm, setBpm] = useState(110)
  const [timeSig, setTimeSig] = useState('4/4')
  const [key, setKey] = useState('C')
  const [mode, setMode] = useState('major')
  const [grid, setGrid] = useState('1/8')
  const [selectedProg, setSelectedProg] = useState(0)
  const [recording, setRecording] = useState(false)
  const [metronomeOn, setMetronomeOn] = useState(false)
  const [countInBars, setCountInBars] = useState(1)
  const [tapTimes, setTapTimes] = useState<number[]>([])

  const mediaRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const metroTimer = useRef<number | null>(null)

  useEffect(() => {
    if (!jobId) return
    const interval = window.setInterval(async () => {
      const j = await (await fetch(`/api/job/${jobId}`)).json()
      setLogs(j.logs || [])
      if (j.status === 'done') {
        setResult(j.result)
        setBpm(j.result.bpm)
        setTimeSig(j.result.time_signature)
        setKey(j.result.key_candidates[0].key)
        setMode(j.result.key_candidates[0].mode)
        window.clearInterval(interval)
      }
      if (j.status === 'error') {
        alert(j.error)
        window.clearInterval(interval)
      }
    }, 1000)
    return () => window.clearInterval(interval)
  }, [jobId])

  const click = (accent = false) => {
    const ctx = new AudioContext()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.frequency.value = accent ? 1400 : 920
    gain.gain.value = 0.08
    osc.connect(gain).connect(ctx.destination)
    osc.start()
    osc.stop(ctx.currentTime + 0.04)
  }

  const stopMetronome = () => {
    if (metroTimer.current) window.clearInterval(metroTimer.current)
    metroTimer.current = null
    setMetronomeOn(false)
  }

  const startMetronome = () => {
    stopMetronome()
    setMetronomeOn(true)
    const beats = Number(timeSig.split('/')[0] || 4)
    let beat = 0
    click(true)
    metroTimer.current = window.setInterval(() => {
      beat = (beat + 1) % beats
      click(beat === 0)
    }, (60 / bpm) * 1000)
  }

  const startAnalysis = async (f: File) => {
    const fd = new FormData()
    fd.append('file', f)
    const data = await (await fetch('/api/analyze', { method: 'POST', body: fd })).json()
    setJobId(data.job_id)
    setResult(null)
    setLogs(['job queued'])
  }

  const startRecord = async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const recorder = new MediaRecorder(stream)
    chunksRef.current = []
    recorder.ondataavailable = (event) => chunksRef.current.push(event.data)
    recorder.onstop = () => {
      const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
      setAudioUrl(URL.createObjectURL(blob))
      startAnalysis(new File([blob], 'recording.webm', { type: 'audio/webm' }))
    }
    mediaRef.current = recorder
    const beats = Number(timeSig.split('/')[0] || 4)
    const countInMs = (60 / bpm) * 1000 * beats * countInBars
    startMetronome()
    setRecording(true)
    window.setTimeout(() => recorder.start(), countInMs)
  }

  const stopRecord = () => {
    mediaRef.current?.stop()
    stopMetronome()
    setRecording(false)
  }

  const progression = result?.progressions[selectedProg]

  const tapTempo = () => {
    const now = performance.now()
    const arr = [...tapTimes.slice(-5), now]
    setTapTimes(arr)
    if (arr.length >= 2) {
      const intervals = arr.slice(1).map((t, i) => t - arr[i])
      const avg = intervals.reduce((a, b) => a + b, 0) / intervals.length
      setBpm(Math.max(40, Math.min(220, Math.round(60000 / avg))))
    }
  }

  const swapChord = (segment: number, chordName: string) => {
    if (!result || !progression) return
    const progs = [...result.progressions]
    progs[selectedProg] = {
      ...progression,
      chords: progression.chords.map((c) => (c.segment === segment ? { ...c, chord_name: chordName } : c)),
    }
    setResult({ ...result, progressions: progs })
  }

  const moveChord = (index: number, dir: -1 | 1) => {
    if (!result || !progression) return
    const next = index + dir
    if (next < 0 || next >= progression.chords.length) return
    const chords = [...progression.chords]
    ;[chords[index], chords[next]] = [chords[next], chords[index]]
    const progs = [...result.progressions]
    progs[selectedProg] = { ...progression, chords }
    setResult({ ...result, progressions: progs })
  }

  const exportMidi = async () => {
    if (!result || !progression) return
    const payload = {
      bpm,
      time_signature: timeSig,
      melody_notes: result.melody_notes,
      progression: progression.chords,
    }
    const data = await (
      await fetch('/api/export/midi', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
    ).json()
    Object.values(data).forEach((url) => window.open(url as string, '_blank'))
  }

  const playChords = () => {
    if (!progression) return
    const ctx = new AudioContext()
    const beat = 60 / bpm
    const now = ctx.currentTime
    progression.chords.forEach((c, i) => {
      const root = PITCHES.indexOf(c.chord_name.replace(/m7|maj7|m|dim|7/g, ''))
      const ints = c.chord_name.includes('m') && !c.chord_name.includes('maj') ? minor : major
      ints.forEach((iv) => {
        const osc = ctx.createOscillator()
        const gain = ctx.createGain()
        gain.gain.value = 0.045
        osc.frequency.value = 220 * Math.pow(2, (root + iv - 9) / 12)
        osc.connect(gain).connect(ctx.destination)
        osc.start(now + i * 2 * beat)
        osc.stop(now + (i + 1) * 2 * beat)
      })
    })
  }

  const analysisProgress = useMemo(() => Math.min(100, logs.length * 14), [logs])

  return (
    <div className="app">
      <header className="hero">
        <div>
          <h1>🎵 Melody Launchpad</h1>
          <p>Record or upload a clean melody to detect BPM/key and build export-ready chord progressions.</p>
        </div>
        <div className="pill">Mobile friendly</div>
      </header>

      <section className="card">
        <h2>Record / Upload</h2>
        <div className="controls-grid">
          <button className="btn accent" onClick={metronomeOn ? stopMetronome : startMetronome}>
            {metronomeOn ? 'Stop metronome' : 'Start metronome'}
          </button>
          <button className="btn" onClick={tapTempo}>Tap tempo</button>
          <label>BPM <input type="number" value={bpm} onChange={(e) => setBpm(Number(e.target.value))} /></label>
          <label>Time sig
            <select value={timeSig} onChange={(e) => setTimeSig(e.target.value)}><option>4/4</option><option>3/4</option><option>6/8</option></select>
          </label>
          <label>Count-in bars
            <select value={countInBars} onChange={(e) => setCountInBars(Number(e.target.value))}><option value={1}>1</option><option value={2}>2</option></select>
          </label>
          <button className="btn record" onClick={recording ? stopRecord : startRecord}>{recording ? 'Stop recording' : 'Record after count-in'}</button>
        </div>

        <label className="file-input">Upload audio<input type="file" accept="audio/*" onChange={(e) => {
          const f = e.target.files?.[0]
          if (!f) return
          setAudioUrl(URL.createObjectURL(f))
          startAnalysis(f)
        }} /></label>
        <p className="muted">Tips: mono melody only, low noise, headphones, avoid reverb-heavy rooms.</p>
        {audioUrl && <audio controls src={audioUrl} className="player" />}
      </section>

      {jobId && !result && (
        <section className="card">
          <h3>Analyzing… {analysisProgress}%</h3>
          <div className="progress"><span style={{ width: `${analysisProgress}%` }} /></div>
          <ul className="log-list">{logs.map((l) => <li key={l}>{l}</li>)}</ul>
        </section>
      )}

      {result && (
        <>
          <section className="card split">
            <div>
              <h3>Detected info</h3>
              <div className="controls-grid compact">
                <label>BPM <input type="number" value={bpm} onChange={(e) => setBpm(Number(e.target.value))} /></label>
                <label>Key <select value={key} onChange={(e) => setKey(e.target.value)}>{PITCHES.map((k) => <option key={k}>{k}</option>)}</select></label>
                <label>Mode <select value={mode} onChange={(e) => setMode(e.target.value)}><option>major</option><option>minor</option></select></label>
                <label>Time signature <input value={timeSig} onChange={(e) => setTimeSig(e.target.value)} /></label>
                <label>Quantize grid <select value={grid} onChange={(e) => setGrid(e.target.value)}><option>1/4</option><option>1/8</option><option>1/16</option></select></label>
              </div>
              <p className="muted">Tempo confidence: {readOnly(result.bpm_confidence * 100)}%</p>
            </div>
            <div>
              <h3>Confidence panel</h3>
              {Object.entries(result.confidence).map(([k, v]) => <div key={k} className="stat"><span>{k}</span><strong>{readOnly(v * 100)}%</strong></div>)}
              {result.warnings.map((w) => <div className="warn" key={w}>{w}</div>)}
            </div>
          </section>

          <section className="card">
            <h3>Melody + chord timeline</h3>
            <div className="timeline">
              {result.melody_notes.map((n, i) => (
                <div key={i} className="note" style={{ left: `${n.start_s * 34}px`, width: `${Math.max(14, n.dur_s * 34)}px`, top: `${220 - n.midi * 1.8}px` }}>
                  {n.name}
                </div>
              ))}
              {progression?.chords.map((c, idx) => (
                <div key={`${c.segment}-${idx}`} className="chord" style={{ left: `${idx * 86}px` }}>
                  <strong>{c.chord_name}</strong>
                  <select value={c.chord_name} onChange={(e) => swapChord(c.segment, e.target.value)}>
                    {(result.chord_candidates_by_segment[String(c.segment)] || []).map((opt) => <option key={opt.chord_name}>{opt.chord_name}</option>)}
                  </select>
                  <div className="row">
                    <button className="btn mini" onClick={() => moveChord(idx, -1)}>←</button>
                    <button className="btn mini" onClick={() => moveChord(idx, 1)}>→</button>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="card">
            <h3>Progressions</h3>
            <div className="chip-row">
              {result.progressions.map((p, i) => (
                <button key={p.id} className={`chip ${i === selectedProg ? 'active' : ''}`} onClick={() => setSelectedProg(i)}>
                  {p.id} · {readOnly(p.score)}
                </button>
              ))}
            </div>

            <div className="row wrap">
              <button className="btn" onClick={playChords}>Play chord synth</button>
              <button className="btn accent" onClick={exportMidi}>Export MIDI + chart</button>
              <button className="btn" onClick={() => {
                const bundle = new Blob([JSON.stringify({ ...result, bpm, key, mode, timeSig }, null, 2)], { type: 'application/json' })
                const a = document.createElement('a')
                a.href = URL.createObjectURL(bundle)
                a.download = 'session.json'
                a.click()
              }}>Download session JSON</button>
              <label className="file-input inline">Open session JSON
                <input type="file" accept="application/json" onChange={async (e) => {
                  const f = e.target.files?.[0]
                  if (!f) return
                  const fd = new FormData()
                  fd.append('file', f)
                  const data = await (await fetch('/api/session/open', { method: 'POST', body: fd })).json()
                  setResult(data)
                }} />
              </label>
            </div>
            {audioUrl && <audio controls src={audioUrl} className="player" />}
          </section>
        </>
      )}
    </div>
  )
}
