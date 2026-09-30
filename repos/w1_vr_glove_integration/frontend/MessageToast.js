import * as THREE from "./three.module.js";
import { makeTextSprite } from "./utils/common.js";
import { createMessageCardSprite, syncHudGroup } from "./utils/hudCanvas.js";
import {
  createDeleteConfirmationDescriptor,
  resolveMessageDescriptor,
} from "./utils/messageToastImgMap.js";
import {
  createDataDeleteFlow,
  DATA_DELETE_STATES,
} from "./utils/dataDeleteFlow.js";
import { audioQueueManager } from "./AudioQueueManager.js";
import {
  isRecordStateActive,
  parseRecordMessage,
} from "./utils/recordState.js";
import { createCollisionAlertThrottle } from "./utils/collisionAlertThrottle.js";

export function MessageToast(renderer, sendLowFreqMessage) {
  function sendLowFreq(payload) {
    return typeof sendLowFreqMessage === "function" && sendLowFreqMessage(payload);
  }

  const msgToast = new THREE.Group();
  msgToast.matrixAutoUpdate = true;

  let l1TopCard = null;
  let l1BottomCard = null;
  let l2Card = null;
  let l2TextCard = null;
  let toastCard = null;
  let serverErrorCard = null;
  let dataSavingProgress = null;

  let l2MessageType = null;
  let l1TopTimer = null;
  let l1BottomTimer = null;
  let l2Timer = null;
  let toastTimer = null;
  let leftGesture = null;
  let rightGesture = null;
  let chassisMode = null;

  let isRecording = false;
  let isSavingData = false;
  let isReturningToPosition = false;
  let dataDeleteFlow = null;

  const DELETE_L2_MESSAGE_TYPES = new Set([
    "record_delete_previewing",
    "record_delete_confirm",
    "record_in_del",
  ]);

  const msgTip = makeTextSprite("", "red");
  msgTip.position.set(0, 0.3, 0);
  msgToast.add(msgTip);

  function debounce(func, delay, context) {
    let timer = null;
    return function debounced(...args) {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        func.apply(context || this, args);
        timer = null;
      }, delay);
    };
  }

  const debouncedShowL1TopMsg = debounce(showL1TopMsg, 300, this);
  const debouncedPlayAudio = debounce(audioQueueManager.playAudio, 300, audioQueueManager);
  const jointCollisionAlertThrottle = createCollisionAlertThrottle(() => {
    showL1BottomMsg("joint_collision", true, 2000);
    audioQueueManager.playAudio("./audio/joint_collision.wav");
  });

  function clearTimer(timer) {
    if (timer) clearTimeout(timer);
    return null;
  }

  function clearCard(card) {
    if (!card) return null;
    msgToast.remove(card.sprite);
    card.dispose();
    return null;
  }

  function clearDataSavingProgress() {
    dataSavingProgress = null;
  }

  function mountCard(descriptor, slot) {
    const card = createMessageCardSprite(descriptor, slot);
    card.sprite.userData.position = slot;
    msgToast.add(card.sprite);
    msgToast.updateMatrixWorld(true);
    return card;
  }

  function showL1TopMsg(key, autoHide = true, time = 2000, hidecb = () => {}) {
    l1TopTimer = clearTimer(l1TopTimer);
    l1TopCard = clearCard(l1TopCard);
    const descriptor = resolveMessageDescriptor(key, "l1Interaction");
    descriptor.variant = "l1Interaction";
    l1TopCard = mountCard(descriptor, "l1Top");

    if (autoHide) {
      l1TopTimer = setTimeout(() => {
        l1TopCard = clearCard(l1TopCard);
        l1TopTimer = null;
        hidecb();
      }, time);
    }
  }

  function showL1BottomMsg(
    keyOrText,
    autoHide = true,
    time = 2000,
    hidecb = () => {},
    fallbackLevel = "success",
  ) {
    const descriptor = resolveMessageDescriptor(keyOrText, "l1Warning", fallbackLevel);
    if (descriptor.slot === "l2") {
      showL2Msg(keyOrText, autoHide, time, hidecb);
      return;
    }

    if (toastCard?.sprite.userData.position === "l1Bottom") {
      toastTimer = clearTimer(toastTimer);
      toastCard = clearCard(toastCard);
    }
    l1BottomTimer = clearTimer(l1BottomTimer);
    l1BottomCard = clearCard(l1BottomCard);
    clearDataSavingProgress();

    l1BottomCard = mountCard(descriptor, "l1Bottom");
    if (descriptor.progress !== undefined) dataSavingProgress = l1BottomCard;

    if (autoHide) {
      l1BottomTimer = setTimeout(() => {
        l1BottomCard = clearCard(l1BottomCard);
        clearDataSavingProgress();
        l1BottomTimer = null;
        hidecb();
      }, time);
    }
  }

  function cancelPendingDeleteForL2(messageType) {
    if (DELETE_L2_MESSAGE_TYPES.has(messageType)) return;
    const deleteState = dataDeleteFlow?.getState();
    if (
      deleteState === DATA_DELETE_STATES.PREVIEWING
      || deleteState === DATA_DELETE_STATES.CONFIRMING
    ) {
      dataDeleteFlow.reset("l2_interrupted");
    }
  }

  function showL2Descriptor(descriptor, messageType, autoHide = true, time = 3500, hidecb = () => {}) {
    if (toastCard?.sprite.userData.position === "l2") {
      toastTimer = clearTimer(toastTimer);
      toastCard = clearCard(toastCard);
    }
    l2Timer = clearTimer(l2Timer);
    l2Card = clearCard(l2Card);
    l2TextCard = clearCard(l2TextCard);
    l2MessageType = messageType;

    descriptor.variant = "l2";
    l2Card = mountCard(descriptor, "l2");

    if (autoHide) {
      l2Timer = setTimeout(() => {
        l2Card = clearCard(l2Card);
        l2MessageType = null;
        l2Timer = null;
        hidecb();
      }, time);
    }
  }

  function showL2Msg(key, autoHide = true, time = 3500, hidecb = () => {}) {
    cancelPendingDeleteForL2(key);
    showL2Descriptor(resolveMessageDescriptor(key, "l2"), key, autoHide, time, hidecb);
  }

  function showL2TextMsg(text, autoHide = true, time = 3500, messageType = "text") {
    cancelPendingDeleteForL2(messageType);
    l2Timer = clearTimer(l2Timer);
    l2Card = clearCard(l2Card);
    l2TextCard = clearCard(l2TextCard);
    l2MessageType = messageType;
    l2TextCard = mountCard({
      variant: "l2",
      level: "error",
      title: text,
      body: "",
    }, "l2");

    if (autoHide) {
      l2Timer = setTimeout(() => {
        l2TextCard = clearCard(l2TextCard);
        l2MessageType = null;
        l2Timer = null;
      }, time);
    }
  }

  function showMsgToast(options, autoHide = true, time = 2000) {
    toastTimer = clearTimer(toastTimer);
    toastCard = clearCard(toastCard);
    const isL2 = options.position === "l2";
    const slot = isL2 ? "l2" : "l1Bottom";

    if (isL2) {
      cancelPendingDeleteForL2("runtime_toast");
      l2Timer = clearTimer(l2Timer);
      l2Card = clearCard(l2Card);
      l2TextCard = clearCard(l2TextCard);
    } else {
      l1BottomTimer = clearTimer(l1BottomTimer);
      l1BottomCard = clearCard(l1BottomCard);
      clearDataSavingProgress();
    }

    const descriptor = isL2
      ? {
          variant: "l2",
          level: options.level,
          title: options.title || "消息提醒",
          body: options.error_msg || "",
        }
      : {
          variant: "l1Warning",
          level: options.level,
          text: [options.title, options.error_msg].filter(Boolean).join("："),
        };
    toastCard = mountCard(descriptor, slot);

    if (autoHide) {
      toastTimer = setTimeout(() => {
        toastCard = clearCard(toastCard);
        toastTimer = null;
      }, time);
    }
  }

  function hideL1TopMsg() {
    l1TopTimer = clearTimer(l1TopTimer);
    l1TopCard = clearCard(l1TopCard);
  }

  function hideL1BottomMsg() {
    l1BottomTimer = clearTimer(l1BottomTimer);
    l1BottomCard = clearCard(l1BottomCard);
    clearDataSavingProgress();
  }

  function hideL2Msg(messageType = null) {
    if (messageType && l2MessageType !== messageType) return;
    if (DELETE_L2_MESSAGE_TYPES.has(l2MessageType)) {
      const deleteState = dataDeleteFlow?.getState();
      if (
        deleteState === DATA_DELETE_STATES.PREVIEWING
        || deleteState === DATA_DELETE_STATES.CONFIRMING
      ) {
        dataDeleteFlow.reset("l2_hidden");
        return;
      }
    }
    l2Timer = clearTimer(l2Timer);
    l2Card = clearCard(l2Card);
    l2TextCard = clearCard(l2TextCard);
    l2MessageType = null;
  }

  function hideDeleteL2IfVisible() {
    if (DELETE_L2_MESSAGE_TYPES.has(l2MessageType)) hideL2Msg();
  }

  function showDeleteError(title, errorMessage) {
    showMsgToast({
      position: "l1Bottom",
      title,
      error_msg: errorMessage,
      level: "error",
    }, true, 5000);
  }

  function handleDataDeleteEvent(event) {
    if (event.type === "previewing") {
      showL2Msg("record_delete_previewing", false);
      return;
    }
    if (event.type === "confirming") {
      showL2Descriptor(
        createDeleteConfirmationDescriptor(event.folderName),
        "record_delete_confirm",
        false,
      );
      audioQueueManager.playAudio("./audio/record_del_tip.wav");
      return;
    }
    if (event.type === "deleting") {
      showL2Msg("record_in_del", false);
      return;
    }
    if (event.type === "ack") {
      if (DELETE_L2_MESSAGE_TYPES.has(l2MessageType)) showL2Msg("record_in_del", false);
      return;
    }

    hideDeleteL2IfVisible();
    if (event.type === "empty") {
      showL1BottomMsg("record_data_empty", true, 2000);
    } else if (event.type === "invalid_folder_name") {
      showDeleteError("服务端返回数据异常", "folder_name 格式无效");
    } else if (event.type === "preview_failed") {
      showDeleteError("无法获取待删除数据", event.errorCode);
    } else if (event.type === "invalid_preview") {
      showDeleteError("服务端返回数据异常", "缺少有效的 session_id");
    } else if (event.type === "preview_send_failed") {
      showDeleteError("数据服务连接不可用", "请稍后重试");
    } else if (event.type === "preview_timeout") {
      showDeleteError("查询待删除数据超时", "请稍后重试");
    } else if (event.type === "delete_send_failed") {
      showDeleteError("删除请求发送失败", "请稍后重试");
    } else if (event.type === "success") {
      showL1BottomMsg("record_del_success", true, 2000);
      audioQueueManager.playAudio("./audio/record_del_success.wav");
    } else if (event.type === "failure") {
      showDeleteError("数据删除失败", event.errorCode);
      audioQueueManager.playAudio("./audio/record_del_error.wav");
    }
  }

  dataDeleteFlow = createDataDeleteFlow({
    send: sendLowFreq,
    onEvent: handleDataDeleteEvent,
  });

  function handleOpStatus(opStatus) {
    if (!opStatus) return;
    if (opStatus.enable) {
      hideL2Msg("op_status");
    } else {
      showL2TextMsg("关节运行状态异常，请检查机器人", false, 2000, "op_status");
      debouncedPlayAudio("./audio/joint_status_error.wav");
    }
  }

  function showServerErrorLabel() {
    serverErrorCard = clearCard(serverErrorCard);
    serverErrorCard = mountCard({
      variant: "l1Warning",
      level: "warning",
      text: isRecording
        ? "服务已断开，录制数据已自动保存，请删除"
        : "服务连接已断开",
    }, "l1Bottom");
  }

  function hideServerErrorLabel() {
    serverErrorCard = clearCard(serverErrorCard);
  }

  function isTimeoutReason(reason) {
    return typeof reason === "string" && reason.toLowerCase().includes("timeout");
  }

  function applyRecordUpdate({ state, action, reason }) {
    const wasRecording = isRecording;
    isRecording = isRecordStateActive(state);

    if (isRecording) {
      isSavingData = false;
      dataDeleteFlow.reset("recording_started");
      if (action === "start") {
        showL1BottomMsg("record_data_start", true, 2000);
        // MCAP recording speech is played by the robot voice agent.
      }
      return;
    }

    isReturningToPosition = false;
    if (isTimeoutReason(reason)) {
      isSavingData = false;
      showL1BottomMsg(
        "离合状态超过1分钟，录制已自动停止并保存",
        true,
        3000,
        undefined,
        "warning",
      );
    } else if (wasRecording) {
      isSavingData = true;
      showL1BottomMsg("record_saving", false, 2000);
    }
  }

  function socketMessageHandler(msg) {
    if (!msg) return;

    if (
      msg.type === "data_delete_preview_result"
      || msg.type === "data_delete_ack"
      || msg.type === "data_delete_result"
    ) {
      dataDeleteFlow.handleMessage(msg);
      return;
    }

    if (msg.type === "record_end_pose") {
      if (msg.success) showL1BottomMsg("回归位姿已记录", true, 2000);
      return;
    }

    const recordUpdate = parseRecordMessage(msg);
    if (recordUpdate) {
      applyRecordUpdate(recordUpdate);
      if (msg.type === "record_state") return;
    }

    if (msg.type === "robot_status" && msg.message) {
      if (msg.message.type === "return_to_position_status") {
        if (msg.message.status === "started") {
          isReturningToPosition = true;
          showL1BottomMsg("正在自动归位...", false, 30000);
        } else if (msg.message.status === "failed") {
          isReturningToPosition = false;
          showL1BottomMsg(
            msg.message.message || "自动归位失败",
            true,
            5000,
            undefined,
            "warning",
          );
        } else if (msg.message.status === "completed") {
          isReturningToPosition = false;
          hideL1BottomMsg();
        }
      }

      if (msg.message.type === "data_save") {
        isSavingData = false;
        if (msg.message.success) {
          showL1BottomMsg("record_save_success", true, 2000);
          // MCAP recording speech is played by the robot voice agent.
        } else {
          showL1BottomMsg("record_save_error", true, 2000);
          // MCAP recording speech is played by the robot voice agent.
        }
      }
      if (msg.message.type === "data_save_progress" && dataSavingProgress) {
        const progress = Number(msg.message.progress);
        if (Number.isFinite(progress)) dataSavingProgress.setProgress(progress / 100);
      }

      if (msg.message.type === "collision_status" && msg.message.collision_detected) {
        jointCollisionAlertThrottle.trigger();
      }
      if (msg.message.type === "motor_status") {
        if (msg.message.enable) hideL2Msg("joint_moto_alarm");
        else {
          showL2Msg("joint_moto_alarm", false, 2000);
          debouncedPlayAudio("./audio/joint_moto_alarm.wav");
        }
      }
      if (msg.message.type === "op_status") handleOpStatus(msg.message);
      if (msg.message.type === "chassis_status" && !msg.message.enable) {
        showL1BottomMsg("chassis_disabled", true, 2000);
      }
      if (msg.message.type === "storage_status") {
        showL2Msg("storage_warning", true, 3500);
        if (msg.message.phase === "before_recording") {
          audioQueueManager.playAudio("./audio/storage_warning1.wav");
        }
        if (msg.message.phase === "recording") {
          audioQueueManager.playAudio("./audio/storage_warning2.wav");
        }
      }
      if (msg.message.type === "record_start_incomplete") {
        const missing = msg.message.missing_cameras || [];
        console.warn(`[MessageToast] 录制启动不完整，未响应相机: ${missing.join(", ")}`);
        showL1BottomMsg("record_sync_warning", true, 3000);
      }
    }

    if (msg.type === "state" && msg.op_status) handleOpStatus(msg.op_status);
    if (msg.type === "state" && msg.gesture) {
      if (typeof msg.gesture.left === "string") leftGesture = msg.gesture.left;
      if (typeof msg.gesture.right === "string") rightGesture = msg.gesture.right;
    }
    if (msg.type === "state" && typeof msg.is_recording === "boolean") {
      isRecording = msg.is_recording;
      if (!isRecording) isSavingData = false;
    }

    if (msg.type === "chassis_mode") {
      if (chassisMode !== msg.mode) {
        showL1TopMsg(msg.mode === "parking" ? "chassis_parking" : "chassis_exercise", true, 2000);
      }
      chassisMode = msg.mode;
    }

    if (msg.type === "teleop_state" && typeof msg.on === "boolean") {
      debouncedShowL1TopMsg(msg.on ? "enter_operation" : "exit_operation", true, 2000);
      audioQueueManager.playAudio(msg.on ? "./audio/remote_controll_on.mp3" : "./audio/remote_controll_off.mp3");
    }

    if (msg.type === "leg_mode") {
      const keys = new Set(["joy_lift", "tele_bend", "tele_lift", "height_lock"]);
      if (keys.has(msg.mode)) {
        debouncedShowL1TopMsg(msg.mode, true, 2000);
        debouncedPlayAudio(`./audio/${msg.mode}.wav`);
      }
    }

    if (msg.type === "gesture") {
      const left = typeof msg.left === "string" ? msg.left : "normal1";
      const right = typeof msg.right === "string" ? msg.right : "normal1";
      if (leftGesture !== left) {
        debouncedShowL1TopMsg(`left_${left}`, true, 2000);
        debouncedPlayAudio(`./audio/${left}.wav`);
      }
      if (rightGesture !== right) {
        debouncedShowL1TopMsg(`right_${right}`, true, 2000);
        debouncedPlayAudio(`./audio/${right}.wav`);
      }
      leftGesture = left;
      rightGesture = right;
    }

    if (msg.message?.type === "toast") {
      if (msg.message.success) {
        toastCard = clearCard(toastCard);
        toastTimer = clearTimer(toastTimer);
      } else {
        showMsgToast({
          position: msg.message.position,
          title: msg.message.title || "消息提醒",
          error_msg: msg.message.error_msg,
          level: msg.message.level,
        }, msg.message.level === "warning", 2000);
      }
    }
  }

  function toastOnXRFrame(cameraWorldPosition, cameraWorldQuaternion) {
    syncHudGroup(msgToast, cameraWorldPosition, cameraWorldQuaternion);
  }

  function handleLeftYEdgeDown() {
    if (window.VRMode === "calibration") return;
    if (l2MessageType === "op_status") hideL2Msg("op_status");
  }

  function handleReturnToPosition() {
    if (window.VRMode === "calibration") return;
    if (!isReturningToPosition) {
      isReturningToPosition = true;
      if (!sendLowFreq({ type: "return_to_position" })) isReturningToPosition = false;
    }
  }

  function handleRightThumbstickDown() {
    if (window.VRMode === "calibration") return;
    if (isSavingData || !window.VRMode) return;
    if (isRecording) {
      handleReturnToPosition();
      return;
    }
    dataDeleteFlow.trigger();
  }

  function resetDeleteState(reason = "transport_reset") {
    dataDeleteFlow.reset(reason);
  }

  function resetState() {
    resetDeleteState("toast_reset");
    jointCollisionAlertThrottle.reset();
    hideL1TopMsg();
    hideL1BottomMsg();
    hideL2Msg();
    hideServerErrorLabel();
    toastTimer = clearTimer(toastTimer);
    toastCard = clearCard(toastCard);
    isReturningToPosition = false;
    isSavingData = false;
    isRecording = false;
  }

  function resetRecordingState() {
    isRecording = false;
    isSavingData = false;
  }

  return {
    msgToast,
    msgTip,
    toastOnXRFrame,
    toastSocketMsg: socketMessageHandler,
    resetMessageToastState: resetState,
    resetRecordingState,
    resetDeleteState,
    handleRightThumbstickDown,
    handleLeftYEdgeDown,
    handleReturnToPosition,
    msgToastFn: {
      showL2Msg,
      hideL2Msg,
      showL1BottomMsg,
      hideL1BottomMsg,
      showServerErrorLabel,
      hideServerErrorLabel,
      getL2MessageType: () => l2MessageType,
      resetDeleteState,
    },
  };
}
