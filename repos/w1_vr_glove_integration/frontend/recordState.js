export const RECORD_STATE_RECORDING = "recording";
export const RECORD_STATE_PAUSED = "paused";
export const RECORD_STATE_STOPPED = "stopped";

export function isRecordState(recordState) {
  return recordState === RECORD_STATE_RECORDING
    || recordState === RECORD_STATE_PAUSED
    || recordState === RECORD_STATE_STOPPED;
}

export function isRecordStateActive(recordState) {
  return recordState === RECORD_STATE_RECORDING || recordState === RECORD_STATE_PAUSED;
}

// 统一两种录制消息格式，同时保留 start/resume 等事件语义供 UI 决定是否提示。
export function parseRecordMessage(msg) {
  if (msg?.type === "robot_status" && msg.message?.type === "linkerhand_mcap_record") {
    msg = { ...msg.message, type: "record" };
  }
  if (!msg) return null;
  const createUpdate = (state, action) => ({ state, action, reason: msg.reason });

  if (msg.type === "record_state") {
    return isRecordState(msg.record_state)
      ? createUpdate(msg.record_state, null)
      : null;
  }

  if (msg.type !== "record") return null;

  const action = typeof msg.action === "string" ? msg.action : "";
  if (action === "pause") return createUpdate(RECORD_STATE_PAUSED, action);
  if (action === "start" || action === "resume") {
    return createUpdate(RECORD_STATE_RECORDING, action);
  }
  if (action === "stop" || action === "cancel") return createUpdate(RECORD_STATE_STOPPED, action);

  if (msg.on === true || msg.recording === true) {
    return createUpdate(RECORD_STATE_RECORDING, "start");
  }
  if (msg.on === false || msg.recording === false) {
    return createUpdate(RECORD_STATE_STOPPED, "stop");
  }
  return null;
}
