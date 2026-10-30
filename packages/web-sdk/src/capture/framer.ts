// Cuts a sample stream into fixed frames and numbers them from 0.
export class Framer {
  private pending = new Int16Array(0);
  private sequence = 0;
  private readonly size: number;

  constructor(size: number) {
    this.size = size;
  }

  push(x: Int16Array): { sequence: number; samples: Int16Array }[] {
    const all = new Int16Array(this.pending.length + x.length);
    all.set(this.pending);
    all.set(x, this.pending.length);
    const frames = [];
    let i = 0;
    for (; i + this.size <= all.length; i += this.size) frames.push({ sequence: this.sequence++, samples: all.slice(i, i + this.size) });
    this.pending = all.slice(i);
    return frames;
  }
}
