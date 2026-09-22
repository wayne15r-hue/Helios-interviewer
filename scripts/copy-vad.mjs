import { copyFile, mkdir, readdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

// Every speech asset is served by Helios. There is no CDN fallback.
const target = resolve('frontend/public/vad');
await mkdir(target, { recursive: true });
for (const [folder, matches] of [
  ['node_modules/@ricky0123/vad-web/dist', name => name.endsWith('.onnx') || name === 'vad.worklet.bundle.min.js'],
  ['node_modules/onnxruntime-web/dist', name => name.endsWith('.wasm') || name.endsWith('.mjs')],
]) {
  const files = (await readdir(resolve(folder))).filter(matches);
  if (!files.length) throw new Error(`Local speech assets are missing from ${folder}. Run npm install.`);
  await Promise.all(files.map(name => copyFile(resolve(folder, name), resolve(target, name))));
}

// Recording is separate from VAD: silence, interruptions and actual voice playback
// are retained. Each message is independently decodable PCM, including after reload.
await writeFile(resolve(target, 'helios-capture-worklet.js'), `
class HeliosCapture extends AudioWorkletProcessor {
  constructor() {
    super(); this.parts = []; this.count = 0;
    this.port.onmessage = event => {
      if (event.data.type === 'flush') { this.flush(); this.port.postMessage({type: 'flushed', id: event.data.id}); }
    };
  }
  flush() {
    if (!this.count) return;
    const samples = new Float32Array(this.count); let offset = 0;
    for (const part of this.parts) { samples.set(part, offset); offset += part.length; }
    this.parts = []; this.count = 0;
    this.port.postMessage({type: 'samples', samples, sampleRate}, [samples.buffer]);
  }
  process(inputs) {
    const channels = inputs[0];
    // A connected silent source keeps this clock continuous even without a mic.
    if (channels?.length) {
      const mono = new Float32Array(channels[0].length);
      for (const channel of channels) for (let i = 0; i < mono.length; i++) mono[i] += channel[i] / channels.length;
      this.parts.push(mono); this.count += mono.length;
      if (this.count >= sampleRate * 2) this.flush();
    }
    return true;
  }
}
registerProcessor('helios-capture', HeliosCapture);
`);
console.log('Local Silero, ONNX and recording assets copied.');
