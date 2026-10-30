// Control event codec. Event list and required fields: ../SPEC.md section 2.
export const REQUIRED: Record<string, string[]> = {
  "hello": ["version", "token", "mic", "playout"],
  "ping": ["t_client_us"],
  "text.input": ["text"],
  "mic.revoked": [],
  "client.paused": [],
  "client.resumed_playout": [],
  "playout.started": ["gen", "t_us"],
  "playout.stopped": ["gen", "reason", "t_us"],
  "cancel.ack": ["gen", "played_until_seq"],
  "welcome": ["session_id", "resume_key", "resume_window_ms", "resumed"],
  "pong": ["t_client_us", "t_server_us"],
  "user.speech_started": ["turn_id"],
  "transcript.partial": ["turn_id", "text"],
  "transcript.final": ["turn_id", "text"],
  "agent.generation_started": ["turn_id", "gen"],
  "agent.text": ["gen", "text"],
  "agent.cancel": ["gen"],
  "answer.sources": ["gen", "sources"],
  "session.ended": ["reason"],
  "client.resumed": [],
};

export type Event = { type: string; [field: string]: unknown };

export function decodeEvent(text: string): Event {
  const e: unknown = JSON.parse(text);
  if (typeof e !== "object" || e === null || Array.isArray(e)) throw new Error("event is not an object");
  const type = (e as Event).type;
  const required = typeof type === "string" && Object.hasOwn(REQUIRED, type) ? REQUIRED[type] : undefined;
  if (!required) throw new Error(`unknown event type: ${String(type)}`);
  for (const field of required) if (!(field in e)) throw new Error(`${type}: missing ${field}`);
  return e as Event;
}

export const encodeEvent = (e: Event): string => JSON.stringify(e);
