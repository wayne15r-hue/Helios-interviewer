"""Offline speech boundaries, decoding, alignment and recoverable import failures."""
import io
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import wave

import numpy as np
import pytest

from server import speech


def wav_bytes(rate=8000, seconds=0.2):
    buffer = io.BytesIO()
    samples = (np.sin(np.arange(int(rate * seconds)) * 2 * np.pi * 220 / rate) * 1000).astype('<i2')
    with wave.open(buffer, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(samples.tobytes())
    return buffer.getvalue()


def segment(text, start, end, words=None):
    return SimpleNamespace(text=text, start=start, end=end, words=words)


def fake_transcription(monkeypatch, segments):
    monkeypatch.setattr(speech, '_require', lambda component, settings: Path('local-model'))
    monkeypatch.setattr(speech, '_decode_audio', lambda _: np.zeros(32000, dtype=np.float32))
    model = SimpleNamespace(transcribe=lambda *args, **kwargs: (iter(segments), None))
    monkeypatch.setattr(speech, '_whisper', lambda _: model)


def test_decode_uses_pyav_and_resamples_locally():
    result = speech._decode_audio(wav_bytes())
    assert result.dtype == np.float32
    assert len(result) == pytest.approx(3200, abs=2)
    assert np.isfinite(result).all()
    with pytest.raises(ValueError, match='Cannot decode'):
        speech._decode_audio(b'not a recording')


def test_readiness_missing_models_is_actionable(tmp_path, monkeypatch):
    monkeypatch.setattr(speech, '_has_package', lambda _: True)
    monkeypatch.setenv('HELIOS_MODELS_DIR', str(tmp_path))
    status = speech.readiness({})
    assert not any(value['ready'] for value in status.values())
    assert all('download' in value['message'].lower() for value in status.values())


def test_runtime_requires_complete_local_model(monkeypatch, tmp_path):
    monkeypatch.setattr(speech, '_has_package', lambda _: True)
    with pytest.raises(RuntimeError, match='missing or incomplete'):
        speech.transcribe(wav_bytes(), {'speech': {'stt_path': str(tmp_path)}})


def test_stt_filters_empty_segments_and_retains_timestamps(monkeypatch):
    fake_transcription(monkeypatch, [segment(' Answer ', .1, 1), segment(' ', 1, 2)])
    assert speech.transcribe(b'audio', {}) == [{'text': 'Answer', 'start': .1, 'end': 1.0}]


def test_speaker_alignment_splits_a_whisper_segment_at_speaker_change():
    words = [SimpleNamespace(start=0, end=.7, word='Hello'), SimpleNamespace(start=.8, end=1.2, word=' there'), SimpleNamespace(start=1.4, end=2, word='Welcome')]
    transcript = speech._align_words([segment('Hello there Welcome', 0, 2, words)], [(0, 1.3, 'SPEAKER_00'), (1.3, 2.1, 'SPEAKER_01')])
    assert [(part['speaker'], part['text']) for part in transcript] == [('SPEAKER_00', 'Hello there'), ('SPEAKER_01', 'Welcome')]
    assert all(part['role'] == 'unknown' for part in transcript)


def test_ambiguous_speaker_is_not_invented():
    assert speech._speaker_for_interval(0, 1, [(0, 1, 'A'), (0, 1, 'B')]) is None
    assert speech._speaker_for_interval(2, 3, [(0, 1, 'A')]) is None


def test_missing_diarization_retains_real_transcript_for_manual_labeling(monkeypatch):
    fake_transcription(monkeypatch, [segment('Question?', 0, 1), segment('My answer.', 1, 2)])
    monkeypatch.setattr(speech, 'readiness', lambda _: {'diarization': {'ready': False, 'message': 'Download Community-1.'}})
    events = []
    result = speech.process_upload('recording.wav', {}, lambda progress, message: events.append((progress, message)))
    assert len(result) == 2  # Preserve boundaries for manual labeling.
    assert [item['text'] for item in result] == ['Question?', 'My answer.']
    assert all(item['role'] == 'unknown' and item['speaker'] is None for item in result)
    assert events[-1][0] == 1
    assert 'manually' in events[-1][1]


def test_processing_cancellation_propagates(monkeypatch):
    fake_transcription(monkeypatch, [segment('Answer', 0, 1)])
    class Cancelled(Exception):
        pass
    def cancel(progress, _):
        if progress >= .15:
            raise Cancelled()
    with pytest.raises(Cancelled):
        speech.process_upload('recording.wav', {}, cancel)


def test_diarization_requires_explicit_temporary_token(tmp_path):
    with pytest.raises(ValueError, match='read token'):
        speech.download_model('diarization', None, {}, tmp_path, lambda *_: None)
    assert not list(tmp_path.iterdir())


def test_download_rejects_unknown_components(tmp_path):
    with pytest.raises(ValueError, match='Choose'):
        speech.download_model('anything', None, {}, tmp_path, lambda *_: None)


def test_browser_wav_encoding_recording_and_stale_playback():
    """Exercise browser audio logic with deterministic audio/transport doubles."""
    root = Path(__file__).resolve().parents[1]
    node = shutil.which('node')
    if not node or not (root / 'node_modules/typescript').exists():
        pytest.skip('Install frontend dependencies to run browser audio unit checks.')
    program = r'''
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const ts = require('typescript');
const source = fs.readFileSync('frontend/src/useInterviewAudio.ts', 'utf8');
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const sandbox = { require, exports: {}, performance, crypto, setTimeout, clearTimeout, setInterval, clearInterval, atob, btoa,
  WebSocket: { OPEN: 1 }, Float32Array, Uint8Array, ArrayBuffer, DataView, Blob };
vm.runInNewContext(js + '\nexports.Connection = InterviewConnection;', sandbox);
const wav = sandbox.exports.encodeWav(new Float32Array([-1, 0, 1]), 48000);
const view = new DataView(wav);
assert.equal(view.getUint32(24, true), 48000);
assert.equal(view.getUint32(40, true), 6);
assert.equal(view.getInt16(44, true), -32768);
assert.equal(view.getInt16(48, true), 32767);
(async () => {
  const events = []; let decoded = 0;
  const conn = new sandbox.exports.Connection('session', () => ({}), () => {});
  conn.socket = { readyState: 1, send: text => events.push(JSON.parse(text)) };
  conn.context = { decodeAudioData: async () => { decoded++; return {}; } };
  conn.mix = {}; conn.activeRequest = 'current';
  await conn.message({ data: JSON.stringify({type: 'question', request_id: 'stale', text: 'obsolete', audio: 'AA=='}) });
  assert.equal(decoded, 0, 'Obsolete questions must never play');
  let stopped = 0;
  conn.playback = { onended: () => {}, stop: () => stopped++, disconnect: () => {} };
  conn.playbackMark = { segmentId: 'question-1', start: 1.2 };
  conn.offset = 2.5;
  conn.stopSpeaking();
  assert.equal(stopped, 1);
  assert.notEqual(conn.activeRequest, 'current');
  assert.equal(conn.snapshot.state, 'listening');
  assert.deepEqual(events.find(event => event.type === 'playback'), {type:'playback',segment_id:'question-1',start:1.2,end:2.5});
  assert.equal(events.find(event => event.type === 'interrupt').request_id, 'current');
  // In-flight WAV decode is also invalidated by an interruption.
  let finishDecode;
  conn.context.decodeAudioData = () => new Promise(resolve => { finishDecode = resolve; });
  const requestId = conn.activeRequest;
  const inflight = conn.message({data: JSON.stringify({type:'question',request_id:requestId,text:'cancel while decoding',audio:'AA=='})});
  conn.stopSpeaking(); finishDecode({}); await inflight;
  assert.equal(conn.playback, undefined);
  // Transcript time follows recorded samples even if the OS suspends audio.
  conn.context = {currentTime:10}; conn.capture = {}; conn.captureStart = 8; conn.offset = 5;
  assert.equal(conn.now(), 7);
  conn.pause(); assert.equal(conn.now(), 7);
  conn.context.currentTime = 12; assert.equal(conn.now(), 9, 'Conversation pause retains the full recording clock');
  // Navigating away during asynchronous startup cannot open a microphone later.
  conn.stopped = true; let loaded = 0;
  conn.context = {resume:async()=>{},audioWorklet:{addModule:async()=>loaded++}};
  await assert.rejects(conn.setupAudio(true), /cancelled/);
  assert.equal(loaded, 0);
  // A corrupt/unsupported playback buffer must not strand the UI in Thinking.
  const brokenPlayback = new sandbox.exports.Connection('playback-failure', () => ({}), () => {});
  brokenPlayback.activeRequest = 'turn'; brokenPlayback.snapshot.state = 'thinking'; brokenPlayback.mix = {};
  brokenPlayback.context = {decodeAudioData:async()=>{throw new Error('invalid audio')}};
  await brokenPlayback.message({data:JSON.stringify({type:'question',request_id:'turn',text:'A question',audio:'AA=='})});
  assert.equal(brokenPlayback.snapshot.state, 'listening');
  assert.match(brokenPlayback.snapshot.error, /Voice playback failed/);
  // Recorder failure still releases the user's microphone and audio device.
  const brokenRecorder = new sandbox.exports.Connection('recorder-failure', () => ({}), () => {});
  let microphoneStopped = false, contextClosed = false;
  brokenRecorder.microphone = {getTracks:()=>[{stop:()=>{microphoneStopped=true}}]};
  brokenRecorder.context = {state:'running',resume:async()=>{},close:async()=>{contextClosed=true}};
  brokenRecorder.capture = {disconnect:()=>{},port:{postMessage:()=>{throw new Error('worklet failed')}}};
  await assert.rejects(brokenRecorder.stopCapture(), /worklet failed/);
  assert.equal(microphoneStopped, true); assert.equal(contextClosed, true);
  assert.equal(brokenRecorder.snapshot.recording, false);
  for (const done of brokenRecorder.flushWaiters.values()) done();
  // A failed initial server read must be retried before assigning chunk numbers.
  const recovery = new sandbox.exports.Connection('recovery', () => ({}), () => {});
  const operation = value => { const op = {}; queueMicrotask(()=>op.onsuccess()); op.result=value; return op; };
  recovery.db = {transaction:()=>({objectStore:()=>({get:()=>operation(undefined),index:()=>({getAll:()=>operation([])})})})};
  let reads = 0;
  sandbox.fetch = async () => { if (++reads === 1) throw new Error('server restarting'); return {ok:true,status:200,json:async()=>({session:{next_seq:7,duration_seconds:14}})}; };
  recovery.connect = async()=>{}; recovery.setupAudio = async()=>{}; recovery.send = ()=>{}; recovery.upload = async()=>{};
  await assert.rejects(recovery.begin(false), /server restarting/);
  await recovery.begin(false);
  assert.equal(recovery.nextSeq, 7); assert.equal(recovery.duration, 14);
  clearInterval(recovery.timer);
  console.log('audio unit checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
    result = subprocess.run([node, '-e', program], cwd=root, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_recording_worklet_keeps_silence_mixes_channels_and_flushes():
    root = Path(__file__).resolve().parents[1]
    node = shutil.which('node')
    worklet = root / 'frontend/public/vad/helios-capture-worklet.js'
    if not node or not worklet.is_file():
        pytest.skip('Run the frontend asset build for the recording worklet check.')
    program = r'''
const fs = require('node:fs'); const vm = require('node:vm'); const assert = require('node:assert/strict');
let Capture; const events = [];
vm.runInNewContext(fs.readFileSync('frontend/public/vad/helios-capture-worklet.js','utf8'), {
  sampleRate: 4, Float32Array, AudioWorkletProcessor: class { constructor() { this.port = {postMessage:event=>events.push(event)}; } },
  registerProcessor: (_, cls) => { Capture = cls; },
});
const capture = new Capture();
capture.process([[new Float32Array([.2,.4,0,0]), new Float32Array([.4,.2,0,0])]]);
capture.process([[new Float32Array([0,0,0,0])]]);
assert.equal(events.length, 1); assert.equal(events[0].samples.length, 8);
assert.ok(Math.abs(events[0].samples[0] - .3) < 1e-6);
assert.equal(events[0].samples[7], 0);
capture.process([[new Float32Array([.5])]]);
capture.port.onmessage({data:{type:'flush',id:'final'}});
assert.equal(events[1].samples.length, 1);
assert.equal(events[2].type, 'flushed'); assert.equal(events[2].id, 'final');
'''
    result = subprocess.run([node, '-e', program], cwd=root, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
