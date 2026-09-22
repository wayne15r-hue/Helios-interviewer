import { useEffect, useRef, useState } from 'react';
import type { Segment, SessionDetail } from './types';

export type InterviewAudioState = 'idle' | 'connecting' | 'listening' | 'transcribing' | 'thinking' | 'speaking' | 'paused' | 'error';
export interface InterviewAudioOptions {
  sessionId?: string | null;
  pauseMs?: number;
  ignoreMicWhileSpeaking?: boolean;
  onSegment?: (segment: Segment) => void;
  onError?: (message: string) => void;
  onStatus?: (state: InterviewAudioState) => void;
}
interface Snapshot { state: InterviewAudioState; elapsedSeconds: number; recording: boolean; error: string | null; latestQuestion: string }
interface QueuedChunk { key: string; sessionId: string; seq: number; blob: Blob; duration: number }
interface QueueMeta { key: string; nextSeq: number; duration: number }
type Vad = { start(): Promise<void>; pause(): Promise<void>; destroy(): Promise<void> };
const initial: Snapshot = { state: 'idle', elapsedSeconds: 0, recording: false, error: null, latestQuestion: '' };

async function request<T>(path: string, body?: BodyInit, contentType?: string, refreshed = false): Promise<T> {
  const response = await fetch(`/api${path}`, { method: body === undefined ? 'GET' : 'POST', body, credentials: 'same-origin', headers: contentType ? { 'Content-Type': contentType } : undefined });
  if (response.status === 401 && !refreshed && path !== '/bootstrap') {
    await request('/bootstrap');
    return request<T>(path, body, contentType, true);
  }
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : `Request failed (${response.status}).`);
  }
  return response.json() as Promise<T>;
}
function post<T>(path: string, body: unknown = {}) { return request<T>(path, JSON.stringify(body), 'application/json'); }

/** Independently decodable little-endian PCM chunks avoid WebM header loss on reload. */
export function encodeWav(samples: Float32Array, sampleRate = 16000): ArrayBuffer {
  const data = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(data);
  const str = (offset: number, value: string) => { for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i)); };
  str(0, 'RIFF'); view.setUint32(4, data.byteLength - 8, true); str(8, 'WAVE'); str(12, 'fmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  str(36, 'data'); view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) { const value = Math.max(-1, Math.min(1, samples[i])); view.setInt16(44 + i * 2, value < 0 ? value * 32768 : value * 32767, true); }
  return data;
}
function base64(data: ArrayBuffer): string {
  const bytes = new Uint8Array(data); let result = '';
  for (let i = 0; i < bytes.length; i += 16384) result += String.fromCharCode(...bytes.subarray(i, i + 16384));
  return btoa(result);
}
function fromBase64(data: string): ArrayBuffer { const decoded = atob(data); return Uint8Array.from(decoded, c => c.charCodeAt(0)).buffer; }

function openQueue(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const opening = indexedDB.open('helios-recording-queue', 1);
    opening.onupgradeneeded = () => {
      const db = opening.result;
      db.createObjectStore('chunks', { keyPath: 'key' }).createIndex('session', 'sessionId');
      db.createObjectStore('meta', { keyPath: 'key' });
    };
    opening.onsuccess = () => resolve(opening.result);
    opening.onerror = () => reject(new Error('Local recording recovery storage is unavailable. Allow browser storage or use typed practice.'));
  });
}
function read<T>(db: IDBDatabase, store: string, key: string): Promise<T | undefined> {
  return new Promise((resolve, reject) => { const op = db.transaction(store).objectStore(store).get(key); op.onsuccess = () => resolve(op.result); op.onerror = () => reject(op.error); });
}
function chunks(db: IDBDatabase, id: string): Promise<QueuedChunk[]> {
  return new Promise((resolve, reject) => { const op = db.transaction('chunks').objectStore('chunks').index('session').getAll(id); op.onsuccess = () => resolve((op.result as QueuedChunk[]).sort((a, b) => a.seq - b.seq)); op.onerror = () => reject(op.error); });
}
function transaction(db: IDBDatabase, action: (tx: IDBTransaction) => void): Promise<void> {
  return new Promise((resolve, reject) => { const tx = db.transaction(['chunks', 'meta'], 'readwrite'); action(tx); tx.oncomplete = () => resolve(); tx.onerror = () => reject(tx.error); tx.onabort = () => reject(tx.error); });
}

class InterviewConnection {
  snapshot = { ...initial };
  private socket?: WebSocket;
  private context?: AudioContext;
  private microphone?: MediaStream;
  private mix?: GainNode;
  private capture?: AudioWorkletNode;
  private silence?: ConstantSourceNode;
  private playback?: AudioBufferSourceNode;
  private playbackMark?: { segmentId: string; start: number };
  private vad?: Vad;
  private db?: IDBDatabase;
  private recovered = false;
  private activeRequest = '';
  private paused = false;
  private stopped = false;
  private disposed = false;
  private suppressSpeech = false;
  private nextSeq = 0;
  private duration = 0;
  private offset = 0;
  private began = 0;
  private captureStart = 0;
  private timer?: ReturnType<typeof setInterval>;
  private saveChain: Promise<void> = Promise.resolve();
  private uploading?: Promise<void>;
  private starting?: Promise<void>;
  private ending?: Promise<void>;
  private flushWaiters = new Map<string, () => void>();
  constructor(readonly id: string, private options: () => InterviewAudioOptions, private notify: (snapshot: Snapshot) => void) {}
  private update(patch: Partial<Snapshot>) {
    this.snapshot = { ...this.snapshot, ...patch };
    if (!this.disposed) { this.notify(this.snapshot); if (patch.state) this.options().onStatus?.(patch.state); }
  }
  private fail(error: unknown) {
    const message = error instanceof Error ? error.message : String(error);
    this.update({ error: message }); if (!this.disposed) this.options().onError?.(message);
  }
  private now() {
    // The audio clock pauses when the browser/device suspends its AudioContext.
    // Wall time would put transcript links past the actual saved recording.
    if (this.capture && this.context) return this.offset + Math.max(0, this.context.currentTime - this.captureStart);
    return this.began ? this.offset + (performance.now() - this.began) / 1000 : this.offset;
  }
  private assertLive() { if (this.stopped || this.disposed) throw new Error('Session setup was cancelled.'); }
  private send(payload: object) {
    if (this.socket?.readyState !== WebSocket.OPEN) throw new Error('Interview connection is closed. Press Resume to reconnect; your recording is retained.');
    this.socket.send(JSON.stringify(payload));
  }
  private cancel() {
    const obsolete = this.activeRequest; this.activeRequest = crypto.randomUUID();
    if (this.playback) { this.playback.onended = null; try { this.playback.stop(); } catch { /* already ended */ } this.playback.disconnect(); this.playback = undefined; this.finishPlayback(); }
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify({ type: 'interrupt', request_id: obsolete }));
  }
  private finishPlayback() {
    if (this.playbackMark && this.socket?.readyState === WebSocket.OPEN) this.send({ type: 'playback', segment_id: this.playbackMark.segmentId, start: this.playbackMark.start, end: this.now() });
    this.playbackMark = undefined;
  }
  stopSpeaking = () => { this.cancel(); if (!this.paused) this.update({ state: 'listening' }); };
  private async upload() {
    if (this.uploading) return this.uploading;
    this.uploading = (async () => {
      if (!this.db) return;
      // New final chunks may arrive while an older upload is in flight.
      // Drain through them so a normal End never reports a spurious pending save.
      for (;;) {
        const pending = await chunks(this.db, this.id);
        if (!pending.length) break;
        for (const chunk of pending) {
          await request(`/sessions/${this.id}/chunks?seq=${chunk.seq}&duration_seconds=${chunk.duration}`, chunk.blob, 'audio/wav');
          await transaction(this.db, tx => tx.objectStore('chunks').delete(chunk.key));
        }
      }
    })().finally(() => { this.uploading = undefined; });
    return this.uploading;
  }
  private queue(samples: Float32Array, sampleRate: number) {
    if (!this.db || !samples.length) return;
    const seq = this.nextSeq++; this.duration += samples.length / sampleRate;
    const entry: QueuedChunk = { key: `${this.id}:${seq}`, sessionId: this.id, seq, duration: this.duration, blob: new Blob([encodeWav(samples, sampleRate)], { type: 'audio/wav' }) };
    this.saveChain = this.saveChain.then(async () => {
      await transaction(this.db!, tx => {
        tx.objectStore('chunks').put(entry);
        tx.objectStore('meta').put({ key: this.id, nextSeq: seq + 1, duration: entry.duration });
      });
    }).catch(error => { this.fail(new Error(`Recording recovery storage failed: ${String(error)}. End the session to avoid losing new audio.`)); throw error; });
    void this.saveChain.then(() => this.upload()).catch(error => this.fail(new Error(`Recording upload pending: ${error instanceof Error ? error.message : String(error)} Audio is queued locally and will retry.`)));
  }
  private async connect() {
    if (this.socket?.readyState === WebSocket.OPEN) return;
    // Refresh the HttpOnly local-session cookie after a backend restart.
    await request('/bootstrap');
    this.assertLive();
    const socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/sessions/${this.id}/live`);
    this.socket = socket;
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => { socket.close(); reject(new Error('Interview connection timed out. Check that Helios is running.')); }, 15000);
      socket.onopen = () => { clearTimeout(timeout); resolve(); };
      socket.onerror = () => { clearTimeout(timeout); reject(new Error('Could not connect to the local interview service.')); };
      socket.onclose = () => { clearTimeout(timeout); reject(new Error('Interview connection closed before it was ready.')); };
    });
    if (this.stopped || this.disposed) { socket.close(); this.assertLive(); }
    socket.onmessage = event => { void this.message(event).catch(error => this.fail(error)); };
    socket.onclose = () => { if (!this.stopped && !this.disposed) { this.pause(); this.fail(new Error('Connection lost. Audio continues saving locally. Press Resume when Helios is running again.')); } };
    socket.onerror = () => { /* onclose gives the actionable error */ };
  }
  private async message(event: MessageEvent) {
    const data = JSON.parse(event.data);
    if (data.request_id && data.request_id !== this.activeRequest) return;
    if (this.stopped || this.paused) return;
    if (data.type === 'error') { this.fail(new Error(data.message)); this.update({ state: 'listening' }); }
    if (data.type === 'state' && data.value !== 'speaking') this.update({ state: data.value });
    if (data.type === 'segment') this.options().onSegment?.(data.segment);
    if (data.type === 'question') {
      this.update({ latestQuestion: data.text });
      if (data.warning) this.fail(new Error(`Voice playback is unavailable: ${data.warning} The interview can continue with text.`));
      if (data.segment) this.options().onSegment?.(data.segment);
      if (!data.audio || !this.context || !this.mix) { this.update({ state: 'listening' }); return; }
      const requestId = this.activeRequest;
      try {
        const audio = await this.context.decodeAudioData(fromBase64(data.audio));
        if (requestId !== this.activeRequest || this.paused || this.stopped) return;
        await this.context.resume();
        if (requestId !== this.activeRequest || this.paused || this.stopped) return;
        const source = this.context.createBufferSource(); source.buffer = audio;
        source.connect(this.context.destination); source.connect(this.mix);
        source.onended = () => { source.disconnect(); if (this.playback === source) { this.playback = undefined; this.finishPlayback(); if (!this.paused && !this.stopped) this.update({ state: 'listening' }); } };
        this.playback = source; this.playbackMark = data.segment ? { segmentId: data.segment.id, start: this.now() } : undefined;
        this.update({ state: 'speaking' }); source.start();
      } catch (error) {
        if (requestId !== this.activeRequest || this.paused || this.stopped) return;
        this.playback?.disconnect(); this.playback = undefined; this.playbackMark = undefined;
        this.update({ state: 'listening' });
        this.fail(new Error(`Voice playback failed: ${error instanceof Error ? error.message : String(error)} You can answer the question shown in the transcript.`));
      }
    }
  }
  private answerAudio(samples: Float32Array) {
    if (this.paused || this.stopped || this.suppressSpeech) return;
    const end = this.now(); this.cancel(); this.activeRequest = crypto.randomUUID();
    try { this.send({ type: 'audio', audio: base64(encodeWav(samples)), request_id: this.activeRequest, start: Math.max(0, end - samples.length / 16000), end }); this.update({ state: 'transcribing' }); } catch (error) { this.fail(error); }
  }
  private async setupAudio(microphone: boolean) {
    if (!this.context) throw new Error('Audio is unavailable in this browser. Use Chrome or Edge on localhost.');
    await this.context.resume();
    this.assertLive();
    await this.context.audioWorklet.addModule('/vad/helios-capture-worklet.js');
    this.assertLive();
    this.mix = this.context.createGain();
    this.capture = new AudioWorkletNode(this.context, 'helios-capture');
    const silentOutput = this.context.createGain(); silentOutput.gain.value = 0;
    this.captureStart = this.context.currentTime;
    this.mix.connect(this.capture); this.capture.connect(silentOutput); silentOutput.connect(this.context.destination);
    this.silence = this.context.createConstantSource(); this.silence.offset.value = 0; this.silence.connect(this.mix); this.silence.start();
    this.capture.port.onmessage = event => {
      if (event.data.type === 'samples') this.queue(event.data.samples, event.data.sampleRate);
      if (event.data.type === 'flushed') { this.flushWaiters.get(event.data.id)?.(); this.flushWaiters.delete(event.data.id); }
    };
    this.began = performance.now(); this.update({ recording: true });
    if (!microphone) return;
    this.microphone = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    if (this.stopped || this.disposed) { this.microphone.getTracks().forEach(track => track.stop()); this.assertLive(); }
    this.context.createMediaStreamSource(this.microphone).connect(this.mix);
    for (const track of this.microphone.getTracks()) track.onended = () => { if (!this.stopped) this.fail(new Error('Microphone disconnected. Typed answers remain available. Reopen practice to reconnect your microphone.')); };
    const { MicVAD } = await import('@ricky0123/vad-web');
    this.assertLive();
    this.vad = await MicVAD.new({
      model: 'v5', baseAssetPath: '/vad/', onnxWASMBasePath: '/vad/',
      audioContext: this.context, startOnLoad: false,
      redemptionMs: this.options().pauseMs ?? 1800, preSpeechPadMs: 500, minSpeechMs: 350,
      positiveSpeechThreshold: 0.65, negativeSpeechThreshold: 0.4, submitUserSpeechOnPause: true,
      getStream: async () => this.microphone!, pauseStream: async () => {}, resumeStream: async () => this.microphone!,
      ortConfig: ort => { ort.env.wasm.numThreads = 1; ort.env.logLevel = 'error'; },
      onSpeechStart: () => {
        this.suppressSpeech = this.paused || this.stopped || Boolean(this.options().ignoreMicWhileSpeaking && this.playback);
        if (!this.suppressSpeech && ['speaking', 'thinking', 'transcribing'].includes(this.snapshot.state)) this.stopSpeaking();
      },
      onSpeechEnd: samples => this.answerAudio(samples),
    });
    this.assertLive();
    await this.vad.start();
  }
  start = (options: { microphone?: boolean } = {}): Promise<void> => {
    if (this.starting) return this.starting;
    if (this.socket?.readyState === WebSocket.OPEN && this.began && !this.stopped) return this.paused ? this.resume() : Promise.resolve();
    // Create/resume in the user gesture before the first await for autoplay policy.
    if (!this.context && !this.stopped) { try { this.context = new AudioContext({ sampleRate: 48000 }); void this.context.resume(); } catch (error) { this.fail(error); } }
    this.starting = this.begin(options.microphone !== false).finally(() => { this.starting = undefined; });
    return this.starting;
  };
  private async begin(microphone: boolean) {
    if (this.stopped) throw new Error('This interview has ended. Start a new session to practice again.');
    this.update({ state: 'connecting', error: null });
    try {
      if (!this.db) this.db = await openQueue();
      if (!this.recovered) {
        const [meta, pending, detail] = await Promise.all([read<QueueMeta>(this.db, 'meta', this.id), chunks(this.db, this.id), request<SessionDetail>(`/sessions/${this.id}`)]);
        this.nextSeq = Math.max(meta?.nextSeq ?? 0, ...pending.map(x => x.seq + 1), Number((detail.session as unknown as { next_seq?: number }).next_seq ?? 0));
        this.offset = this.duration = Math.max(meta?.duration ?? 0, detail.session.duration_seconds ?? 0, ...pending.map(x => x.duration));
        this.recovered = true;
        this.update({ elapsedSeconds: this.offset });
        void this.upload().catch(error => this.fail(error));
      }
      this.assertLive();
      await this.connect();
      if (!this.capture) { try { await this.setupAudio(microphone); } catch (error) { this.fail(new Error(`Voice setup unavailable: ${error instanceof Error ? error.message : String(error)} You can continue with typed answers.`)); } }
      this.assertLive();
      this.paused = false; this.suppressSpeech = false;
      if (this.vad) await this.vad.start();
      if (!this.began) this.began = performance.now();
      if (!this.timer) this.timer = setInterval(() => { this.update({ elapsedSeconds: this.now() }); void this.saveChain.then(() => this.upload()).catch(() => {}); }, 2000);
      this.activeRequest = crypto.randomUUID(); this.send({ type: 'start', request_id: this.activeRequest }); this.update({ state: 'thinking' });
    } catch (error) { this.update({ state: 'error' }); this.fail(error); throw error; }
  }
  pause = () => {
    this.paused = true; this.suppressSpeech = true; this.cancel();
    if (this.vad) void this.vad.pause().catch(error => this.fail(error));
    if (this.socket?.readyState === WebSocket.OPEN) this.send({ type: 'pause' });
    this.update({ state: 'paused' });
  };
  resume = async () => {
    if (this.socket?.readyState !== WebSocket.OPEN) return this.start({ microphone: Boolean(this.microphone) });
    this.paused = false; this.suppressSpeech = false; if (this.context) await this.context.resume(); if (this.vad) await this.vad.start();
    if (!this.snapshot.latestQuestion) { this.activeRequest = crypto.randomUUID(); this.send({type: 'start', request_id: this.activeRequest}); this.update({state: 'thinking'}); }
    else this.update({ state: 'listening' });
  };
  sendAnswer = (text?: string) => {
    if (this.paused || this.stopped) { this.fail(new Error('Resume your interview before sending an answer.')); return; }
    if (text?.trim()) {
      this.cancel(); this.activeRequest = crypto.randomUUID();
      try { this.send({ type: 'answer', text: text.trim(), request_id: this.activeRequest, start: this.now(), end: this.now() }); this.update({ state: 'thinking' }); } catch (error) { this.fail(error); }
    } else if (this.vad) {
      // Submit the current VAD utterance immediately, retaining the mic/recorder.
      void this.vad.pause().then(() => this.vad?.start()).catch(error => this.fail(error));
    } else this.fail(new Error('Type your answer, or enable the microphone to send a spoken answer.'));
  };
  private async stopCapture() {
    this.paused = true; this.suppressSpeech = true; this.cancel();
    if (this.timer) clearInterval(this.timer); this.timer = undefined;
    if (this.vad) { await this.vad.destroy().catch(() => {}); this.vad = undefined; }
    const recorded = Boolean(this.capture);
    let flushError: unknown;
    try {
      if (this.capture && this.context?.state !== 'closed') {
        await this.context?.resume().catch(() => {});
        await new Promise<void>((resolve, reject) => {
          const id = crypto.randomUUID(); const timeout = setTimeout(() => { this.flushWaiters.delete(id); reject(new Error('Audio recorder could not flush its final chunk. Earlier chunks are saved.')); }, 5000);
          this.flushWaiters.set(id, () => { clearTimeout(timeout); resolve(); }); this.capture!.port.postMessage({ type: 'flush', id });
        });
      }
    } catch (error) {
      flushError = error;
    } finally {
      // End must release the microphone even when the recorder cannot flush.
      this.capture?.disconnect(); this.capture = undefined;
      this.offset = recorded ? this.duration : this.now(); this.began = 0;
      this.silence?.stop(); this.silence = undefined;
      this.microphone?.getTracks().forEach(track => { track.onended = null; track.stop(); }); this.microphone = undefined;
      await this.context?.close().catch(() => {}); this.context = undefined;
      this.update({ recording: false, elapsedSeconds: this.offset });
    }
    await this.saveChain;
    if (flushError) throw flushError;
  }
  end = (): Promise<void> => {
    if (this.ending) return this.ending;
    this.ending = (async () => {
      this.stopped = true;
      await this.stopCapture();
      await this.upload();
      if (this.db && (await chunks(this.db, this.id)).length) throw new Error('Recording uploads are still pending. Keep this tab open and try End again.');
      if (this.nextSeq > 0) await post(`/sessions/${this.id}/finalize`, { duration_seconds: this.duration, mime_type: 'audio/wav' });
      if (this.socket?.readyState === WebSocket.OPEN) this.send({ type: 'end' });
      await post(`/sessions/${this.id}/end`);
      this.socket?.close(); this.update({ state: 'idle' });
    })().catch(error => { this.fail(error); throw error; }).finally(() => { this.ending = undefined; });
    return this.ending;
  };
  dispose = async () => {
    if (this.disposed) return;
    this.disposed = true; this.stopped = true;
    this.cancel(); this.socket?.close();
    await this.starting?.catch(() => {});
    try { await this.stopCapture(); await this.upload(); if (this.nextSeq) await post(`/sessions/${this.id}/finalize`, { duration_seconds: this.duration, mime_type: 'audio/wav' }); }
    catch { /* durable chunks are retried when this session is reopened */ }
    finally { this.socket?.close(); this.db?.close(); }
  };
}

export function useInterviewAudio(options: InterviewAudioOptions) {
  const optionsRef = useRef(options); optionsRef.current = options;
  const connection = useRef<InterviewConnection | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot>({ ...initial });
  useEffect(() => {
    setSnapshot({ ...initial });
    const current = options.sessionId ? new InterviewConnection(options.sessionId, () => optionsRef.current, setSnapshot) : null;
    connection.current = current;
    return () => { if (connection.current === current) connection.current = null; void current?.dispose(); };
  }, [options.sessionId]);
  return {
    ...snapshot,
    start: (config?: { microphone?: boolean }) => connection.current?.start(config) ?? Promise.reject(new Error('Create an interview session first.')),
    pause: () => connection.current?.pause(), resume: () => connection.current?.resume() ?? Promise.resolve(),
    sendAnswer: (text?: string) => connection.current?.sendAnswer(text), stopSpeaking: () => connection.current?.stopSpeaking(),
    end: () => connection.current?.end() ?? Promise.resolve(), dispose: () => connection.current?.dispose() ?? Promise.resolve(),
  };
}
