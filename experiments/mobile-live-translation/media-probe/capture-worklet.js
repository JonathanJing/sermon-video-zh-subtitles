// Same 16 kHz / 100 ms box-average framing contract as the isolated caption POC.
class ProbeCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.phase = 0;
    this.sum = 0;
    this.count = 0;
    this.frame = new Int16Array(1600);
    this.offset = 0;
    this.enabled = true;
    this.port.onmessage = ({ data }) => { if (data?.type === "stop") this.enabled = false; };
  }
  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel || !this.enabled) return true;
    for (let index = 0; index < channel.length; index += 1) {
      this.sum += channel[index];
      this.count += 1;
      this.phase += 16000;
      if (this.phase < sampleRate) continue;
      this.phase -= sampleRate;
      const sample = Math.max(-1, Math.min(1, this.sum / this.count));
      this.frame[this.offset++] = sample < 0 ? sample * 32768 : sample * 32767;
      this.sum = 0;
      this.count = 0;
      if (this.offset !== 1600) continue;
      const frame = this.frame;
      this.port.postMessage(frame.buffer, [frame.buffer]);
      this.frame = new Int16Array(1600);
      this.offset = 0;
    }
    return true;
  }
}
registerProcessor("media-probe-capture", ProbeCapture);
