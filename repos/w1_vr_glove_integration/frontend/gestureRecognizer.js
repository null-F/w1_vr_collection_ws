// ============================================================
// GestureRecognizer 手势识别引擎
// 输入：每帧双手 ControllerSnapshot + 注入时钟 + 运行时上下文 ctx
// 输出：语义 Action 列表（交由 dispatcher 执行副作用）
//
// 单引擎内化全部边沿/长按/组合键状态机，取代 index.html 原先的 4 套并行实现。
// 规则按 priority 降序匹配：
//   - hold ：成员同时按下且 not 列表均未按下，按住达阈值即触发并消费成员
//   - edge ：成员「按下瞬间」即触发（不等松开，一次性）
//   - doubleTap：同一成员完成两次快速按下/松开后触发；等待期间暂缓同键 tap
//   - tap  ：成员「松开」、且按住时长 < 短按上限、且未被其他规则消费时触发
// 组合键触发后消费成员，成员松开不再回退 tap；重叠组合取最高优先级。
//
// ============================================================
// 【如何新增一个事件】—— 只需在下方 GESTURE_RULES 数组里加一行，用助手函数构造：
//
//   1) 短按（松开<2s 触发）：
//        tap('left.grip', (c) => sendLowFreq({ type: 'foo' }))
//      · 第一个参数是语义键名，形如 'left.x' / 'right.a' / 'right.thumbstick'
//        （左手：x/y/thumbstick/trigger/grip；右手：a/b/thumbstick/trigger/grip）
//      · 第二个参数 action：返回一个 Action（用下方的 sendLowFreq/callLocal/... 工厂），
//        返回 null 则本次不触发（可用于条件判断，c 是运行时上下文）。
//
//   2) 双击（每次按住 <=300ms，第一次松开后 300ms 内开始第二次点击）：
//        doubleTap('left.x', () => sendLowFreq({ type: 'foo_double' }))
//      · 只有配置了 doubleTap 的按键，其 tap 才会暂缓确认；双击成功后不会再触发 tap。
//
//   3) 长按（按住达阈值触发）：
//        hold('right.b', () => callLocal('poseResetGuide.onToggleOverlayLongPress'))
//      可选第二参 opts：{ thresholdMs, not, context, consume, inhibitShortPress }
//        · not：这些键必须未按下（用于区分「单键」vs「组合成员」）
//        · context:(c)=>bool：额外守卫，返回 false 时本规则不生效
//
//   4) 组合键（多键同时按住达阈值）：
//        combo(['left.x','right.b'], () => sendLowFreq({ type:'record_end_pose' }))
//      阈值从「最后一个按下的成员」开始计时；触发后默认消费全部成员。
//
//   5) 按下边沿（按下瞬间触发，不等松开）：
//        edge('right.thumbstick', () => thumbRDown(), { context:(c)=>c.vrMode!=='calibration' })
//
//   所有助手都可选最后传 opts 覆盖默认值；priority 已按事件类别预设（combo>hold>edge>doubleTap>tap），
//   冲突时可在 opts 里传 priority 手动调整。
//
//   规则写完后无需注册——引擎启动时自动收集 GESTURE_RULES。
// ============================================================

import { keyDownInSnapshot } from './controllerSnapshot.js';

// ---- 阈值常量 ----
export const GESTURE_LONG_THRESHOLD_MS = 2000;  // 通用长按阈值
export const GESTURE_DOUBLE_TAP_PRESS_MAX_MS = 300; // 双击中每次按下到松开的最长时间
export const GESTURE_DOUBLE_TAP_GAP_MS = 300;       // 第一次松开到第二次按下的最长间隔
const GESTURE_EXIT_XR_MS = 2500;                // 左X+右A 退出 XR（阶段 2 启用）
const GESTURE_DEBUG_PANEL_MS = 6500;            // 右A 切调试面板（阶段 2 启用）
const GESTURE_TAP_MAX_MS = 2000;                // 短按上限
// 单键 hold 达阈值后的「组合伙伴宽限期」：先进入 pending 不立即触发，
// 宽限期内若组合伙伴按下使本规则离开候选（notOk 翻转或被更高优先级 combo 占用），
// 则丢弃 pending、永不触发本单键（让位组合）；宽限期到仍未被取消才真正触发。
// 这样「先按一个键、2s 后再按组合伙伴」也不会被单键长按抢跑，单键单独长按仅延迟 GRACE。
const HOLD_GRACE_MS = 300;

/**
 * 运行时上下文。action / context 守卫通过它读取最新状态。
 * @typedef {Object} GestureContext
 * @property {boolean} isGripper      - 当前末端是否夹爪（true 时切手势规则不发）
 * @property {boolean} motorHasError  - 电机是否报警（左Y 短按据此清错/切腿）
 * @property {boolean} isTeleopOn     - 是否正在遥操（退出XR 规则仅未遥操时生效）
 * @property {string}  vrMode         - 当前 VR 模式（'headset'/'wearing'/'calibration'/''）
 * @property {string|null} l2MessageType - 当前 L2 提示类型
 */

/**
 * 语义 Action，交由 dispatcher 执行。
 * @typedef {Object} Action
 */

/**
 * 手势规则。
 * @typedef {Object} Rule
 * @property {string} id            - 规则唯一标识
 * @property {number} priority      - 大者优先匹配
 * @property {'tap'|'doubleTap'|'hold'|'edge'} kind
 * @property {string[]} combo       - 成员语义键名（如 ['left.x','right.b']）
 * @property {string[]} [not]       - 这些键必须未按下
 * @property {string[]} [consume]   - 触发后消费这些键（成员松开不再回退 tap）
 * @property {number} [thresholdMs] - hold 的触发阈值 / tap 的上限
 * @property {number} [tapTimeMs] - doubleTap 中每次按下到松开的上限
 * @property {number} [tapDelayMs] - doubleTap 第一次松开到第二次按下的上限
 * @property {boolean} [inhibitShortPress] - hold 触发后是否抑制成员短按
 * @property {boolean} [calibAllowed] - 标定模式下是否放行（默认 false；退出XR/调试面板/标定摇杆为 true）
 * @property {(c:GestureContext)=>boolean} [context] - 额外守卫
 * @property {(c:GestureContext)=>Action|null} action - 触发时返回 Action（null=不触发）
 */

// ---- Action 工厂（在 action 回调里 return 这些）----
// 发 8864 低频控制消息（绝大多数按键事件用这个）
export const sendLowFreq = (payload) => ({ type: 'SEND_LOWFREQ', payload });
// 发 8764 pose 通道消息（仅 data_delete 等历史例外）
export const sendPose    = (payload) => ({ type: 'SEND_POSE', payload });
// 调用某模块方法，target 形如 'poseResetGuide.onCaptureBaselineLongPress'
export const callLocal   = (target, args) => ({ type: 'CALL', target, args: args || [] });
// 退出 XR 会话
export const exitXR      = () => ({ type: 'EXIT_XR' });
// 切换调试面板可见性
export const toggleDebug = () => ({ type: 'TOGGLE_DEBUG_PANEL' });
// 右摇杆按下：归位/删除二段（阶段 2 启用）
export const thumbRDown  = () => ({ type: 'THUMBSTICK_RIGHT_DOWN' });
// 标定步骤触发/回退（阶段 2 启用）
export const calibTrigger = (hand) => ({ type: 'CALIB_STEP_TRIGGER', hand });
export const calibBack    = () => ({ type: 'CALIB_STEP_BACK' });

// ---- 规则构造助手（新增事件用这些，不用手写 kind/priority/thresholdMs 等样板）----
// 默认优先级：组合键 90 > 长按 60 > 边沿 35 > 双击 30 > 短按 20；可在 opts.priority 覆盖。
const PRIO = { combo: 90, hold: 60, edge: 35, doubleTap: 30, tap: 20 };

/**
 * 短按：松开 < thresholdMs 且未被消费时触发。
 * @param {string} key       - 语义键名 'left.x' / 'right.a' ...
 * @param {(c:GestureContext)=>Action|null} action
 * @param {Partial<Rule>} [opts] - 可选覆盖 { not, context, priority, thresholdMs, calibAllowed }
 */
export function tap(key, action, opts = {}) {
    return { id: `tap_${key}`, priority: opts.priority ?? PRIO.tap, kind: 'tap',
        combo: [key], not: opts.not || [], thresholdMs: opts.thresholdMs ?? GESTURE_TAP_MAX_MS,
        context: opts.context, calibAllowed: opts.calibAllowed, action };
}

/**
 * 双击：同一按键连续完成两次快速按下/松开后触发。
 * 第一次松开后，同键 tap 会暂缓到 tapDelayMs 到期；第二次点击成功则只触发 doubleTap。
 * @param {string} key
 * @param {(c:GestureContext)=>Action|null} action
 * @param {Partial<Rule>} [opts] - { tapTimeMs, tapDelayMs, not, context, priority, calibAllowed }
 */
export function doubleTap(key, action, opts = {}) {
    return { id: `double_tap_${key}`, priority: opts.priority ?? PRIO.doubleTap, kind: 'doubleTap',
        combo: [key], not: opts.not || [],
        tapTimeMs: opts.tapTimeMs ?? GESTURE_DOUBLE_TAP_PRESS_MAX_MS,
        tapDelayMs: opts.tapDelayMs ?? GESTURE_DOUBLE_TAP_GAP_MS,
        context: opts.context, calibAllowed: opts.calibAllowed, action };
}

/**
 * 长按：单键按住达 thresholdMs 触发，默认消费该键（松开不再回退短按）。
 * @param {string} key
 * @param {(c:GestureContext)=>Action|null} action
 * @param {Partial<Rule>} [opts] - { thresholdMs, not, context, consume, inhibitShortPress, priority, calibAllowed }
 */
export function hold(key, action, opts = {}) {
    return { id: `hold_${key}`, priority: opts.priority || PRIO.hold, kind: 'hold',
        combo: [key], not: opts.not, thresholdMs: opts.thresholdMs || GESTURE_LONG_THRESHOLD_MS,
        consume: opts.consume || [key], inhibitShortPress: opts.inhibitShortPress,
        context: opts.context, calibAllowed: opts.calibAllowed, action };
}

/**
 * 组合键：多键同时按住达 thresholdMs 触发，默认消费全部成员。
 * 阈值从「最后一个按下的成员」开始计时。
 * @param {string[]} keys     - 成员语义键名
 * @param {(c:GestureContext)=>Action|null} action
 * @param {Partial<Rule>} [opts] - { thresholdMs, context, consume, priority, calibAllowed }
 */
export function combo(keys, action, opts = {}) {
    return { id: `combo_${keys.join('+')}`, priority: opts.priority || PRIO.combo, kind: 'hold',
        combo: keys, thresholdMs: opts.thresholdMs || GESTURE_LONG_THRESHOLD_MS,
        consume: opts.consume || keys, context: opts.context, calibAllowed: opts.calibAllowed, action };
}

/**
 * 按下边沿：成员按下瞬间触发（不等松开，一次性）。
 * @param {string} key
 * @param {(c:GestureContext)=>Action|null} action
 * @param {Partial<Rule>} [opts] - { not, context, priority, calibAllowed }
 */
export function edge(key, action, opts = {}) {
    return { id: `edge_${key}`, priority: opts.priority || PRIO.edge, kind: 'edge',
        combo: [key], not: opts.not, context: opts.context, calibAllowed: opts.calibAllowed, action };
}

// ---- 规则表（用上方助手构造，priority 大者优先）----
// 标定上下文屏蔽（PLAN 第 34 行）：vrMode==='calibration' 时，只放行标定摇杆动作、退出XR、调试快捷键，
// 其余操作类面键（切手势/腿模式/底盘/时间戳/位姿/基准）全部不触发。由下方 update() 内的
// calibMode 守卫 + 各规则 context 共同保证。
export const GESTURE_RULES = [
    // —— 组合键（多键同按达阈值，触发后消费全部成员）——
    // 左X + 右A 长按 2.5s（仅未遥操）→ 退出 XR（最高优先级，标定模式下也生效）
    combo(['left.x', 'right.a'], () => exitXR(),
        { thresholdMs: GESTURE_EXIT_XR_MS, context: (c) => !c.isTeleopOn, priority: 100, calibAllowed: true }),
    // 左X + 右B 长按 2s → 记录回归位姿（走 8864）
    combo(['left.x', 'right.b'], () => sendLowFreq({ type: 'record_end_pose' })),
    // 左Y + 右B 长按 2s → 捕获基准画面
    combo(['left.y', 'right.b'], () => callLocal('poseResetGuide.onCaptureBaselineLongPress'),
        { priority: 85 }),

    // —— 长按（单键按住达阈值，默认消费该键）——
    // 右A 长按 6.5s → 切调试面板（2~6.5s 空档无动作，inhibitShortPress 抑制短按；标定模式也生效）
    hold('right.a', () => toggleDebug(),
        { thresholdMs: GESTURE_DEBUG_PANEL_MS, inhibitShortPress: true, priority: 60, calibAllowed: true }),
    // 左X 单独长按 2s（右B 未按）→ 切换时间戳
    hold('left.x', () => callLocal('timeStamp.toggleTimestamp'),
        { not: ['right.b'], priority: 70 }),
    // 右B 单独长按 2s（左Y 未按）→ 切换基准图层 overlay
    hold('right.b', () => callLocal('poseResetGuide.onToggleOverlayLongPress'),
        { not: ['left.y'], priority: 65 }),
    // 左Y 单独长按 2s（右B 未按，与「左Y+右B 捕获基准」互斥）→ 自动归位（任何时候都触发）
    hold('left.y', () => callLocal('messageToast.handleReturnToPosition'),
        { not: ['right.b'] }),

    // —— 按下边沿（按下瞬间触发，一次性）——
    // 右摇杆按下（正常模式）→ 归位/删除二段
    edge('right.thumbstick', () => thumbRDown(),
        { context: (c) => c.vrMode !== 'calibration' }),
    // 右摇杆按下（标定模式）→ 标定步骤回退
    edge('right.thumbstick', () => calibBack(),
        { context: (c) => c.vrMode === 'calibration', priority: 34, calibAllowed: true }),
    // 左摇杆按下（标定模式）→ 标定步骤触发
    edge('left.thumbstick', () => calibTrigger('left'),
        { context: (c) => c.vrMode === 'calibration', priority: 33, calibAllowed: true }),

    // —— 双击（两次快速按下/松开，只触发相机切换）——
    // 左X 双击 → 切换左腕相机
    doubleTap('left.x', () => callLocal('wristProjection.toggle', ['left'])),
    // 右A 双击 → 切换右腕相机
    doubleTap('right.a', () => callLocal('wristProjection.toggle', ['right'])),

    // —— 短按（松开 <2s 且未被消费）——
    // 左X 短按（非夹爪）→ 切左手手势
    tap('left.x', () => sendLowFreq({ type: 'linkerhand_glove_control', action: 'toggle', request_id: 'vr-x-' + Date.now() + '-' + Math.random().toString(16).slice(2) }),
        { not: ['right.b'], calibAllowed: true }),
    // 右A 短按（非夹爪）→ 切右手手势
    tap('right.a', (c) => c.isGripper ? null : sendLowFreq({ type: 'gesture_switch', side: 'right' })),
    // 左Y 短按（错误优先仲裁，按错误类型分发到对应清除动作）：
    //   电机报警(motor_status) → 发 clear_motor_error
    //   否则若正在显示 op_status 提示 → 关闭该提示（关节状态异常）
    //   都没有 → 切腿模式
    tap('left.y', (c) => {
        if (c.motorHasError) return sendLowFreq({ type: 'clear_motor_error' });
        if (c.l2MessageType === 'op_status') return callLocal('messageToast.handleLeftYEdgeDown');
        return sendLowFreq({ type: 'leg_mode_switch' });
    }, { not: ['right.b'] }),
    // 右B 短按 → 切底盘模式
    tap('right.b', () => sendLowFreq({ type: 'chassis_mode_switch' }),
        { not: ['left.x', 'left.y'] }),
];
// 降序排列（priority 大优先）
GESTURE_RULES.sort((a, b) => b.priority - a.priority);

// 收集规则表中出现的全部语义键名（用于遍历每键边沿状态）
function allRuleKeys(rules) {
    const set = new Set();
    for (const r of rules) {
        for (const k of r.combo) set.add(k);
        if (r.not) for (const k of r.not) set.add(k);
        if (r.consume) for (const k of r.consume) set.add(k);
    }
    return set;
}

function evalRuleCombo(snapshots, rule) {
    return rule.combo.every(k => {
        const hand = k.slice(0, k.indexOf('.'));
        const s = snapshots[hand];
        return s && keyDownInSnapshot(s, k);
    });
}

function evalRuleNot(snapshots, rule) {
    if (!rule.not || rule.not.length === 0) return true;
    return rule.not.every(k => {
        const hand = k.slice(0, k.indexOf('.'));
        const s = snapshots[hand];
        return !(s && keyDownInSnapshot(s, k));
    });
}

/**
 * 创建一个手势引擎实例（持有自身按键/组合状态）。
 * 多次创建互相隔离；cancel 用于会话结束/控制器消失时清空状态。
 */
export function createGestureRecognizer(ruleList = GESTURE_RULES) {
    // 实例持有自己的有序规则视图，便于测试或按产品配置装配规则，同时不修改调用方数组。
    const rules = [...ruleList].sort((a, b) => b.priority - a.priority);
    const keyState = {};   // semKey -> { pressStartMs, longFired, consumed, lastPressed }
    const comboState = {}; // ruleId -> { startMs, fired }
    // key -> { phase, doubleRule, firstAction, deadlineMs, secondPressStartMs }
    const multiTapState = {};
    const RULE_KEYS = allRuleKeys(rules);

    const ensure = (k) => {
        if (!keyState[k]) keyState[k] = { pressStartMs: 0, longFired: false, consumed: false, lastPressed: false };
        return keyState[k];
    };

    const clearMultiTap = (k) => {
        delete multiTapState[k];
    };

    /**
     * 每帧调用，返回本帧产生的 Action 列表。
     * @param {Object} snapshots - { left?: Snapshot, right?: Snapshot }
     * @param {number} nowMs - performance.now()
     * @param {Object} ctx - { isGripper, motorHasError, isTeleopOn, vrMode, l2MessageType }
     */
    function update(snapshots, nowMs, ctx) {
        const actions = [];
        // 标定上下文屏蔽：标定模式下只放行 calibAllowed 的规则（退出XR/调试面板/标定摇杆）
        const calibMode = ctx.vrMode === 'calibration';
        const allowed = (rule) => !calibMode || rule.calibAllowed === true;
        const eligible = (rule) => allowed(rule)
            && (!rule.context || rule.context(ctx))
            && evalRuleNot(snapshots, rule);

        // 1. 计算每键边沿
        const edges = {}; // key -> 'down' | 'up'
        for (const k of RULE_KEYS) {
            const st = ensure(k);
            const hand = k.slice(0, k.indexOf('.'));
            const s = snapshots[hand];
            const down = !!(s && keyDownInSnapshot(s, k));
            if (down && !st.lastPressed) edges[k] = 'down';
            else if (!down && st.lastPressed) edges[k] = 'up';
            st.lastPressed = down;
        }

        // 2. down 边沿：记录起始时间、清状态
        for (const k of RULE_KEYS) {
            if (edges[k] === 'down') {
                const st = ensure(k);
                st.pressStartMs = nowMs;
                st.longFired = false;
                st.consumed = false;
            }
        }

        // 2.1 双击第二次 down / 单击确认超时。
        // 先看本帧边沿，再处理 deadline，保证恰好落在截止时刻的第二次 down 仍可进入双击。
        for (const k of RULE_KEYS) {
            const mts = multiTapState[k];
            if (!mts || mts.phase !== 'waitingSecond') continue;
            if (edges[k] === 'down' && nowMs <= mts.deadlineMs) {
                if (eligible(mts.doubleRule)) {
                    mts.phase = 'secondPressed';
                    mts.secondPressStartMs = nowMs;
                    continue;
                }
                // 上下文已不允许该双击：确认第一次单击，并把当前 down 作为新序列起点。
                if (mts.firstAction) actions.push(mts.firstAction);
                clearMultiTap(k);
                continue;
            }
            if (nowMs >= mts.deadlineMs) {
                if (mts.firstAction) actions.push(mts.firstAction);
                clearMultiTap(k);
            }
        }

        // 3. 每帧 hold/combo 判定（按 priority 降序）
        // 占用守卫：按 priority 降序遍历，一条规则「进入候选」即认领其成员键；
        // 后续更低优先级规则若任一成员已被认领，则跳过其计时与触发——
        // 防止组合键与其成员键的单键长按在同帧双触发，或单键长按在组合伙伴补按前抢跑。
        const claimedThisFrame = new Set();
        for (const rule of rules) {
            if (rule.kind !== 'hold') continue;
            if (!allowed(rule)) continue;
            if (rule.context && !rule.context(ctx)) continue;
            const cs = comboState[rule.id] || (comboState[rule.id] = { startMs: 0, fired: false, pendingUntil: 0 });
            const comboAllDown = evalRuleCombo(snapshots, rule);
            const notOk = evalRuleNot(snapshots, rule);
            const blockedByClaim = rule.combo.some(k => claimedThisFrame.has(k));
            if (comboAllDown && notOk && !blockedByClaim) {
                // 进入候选即认领成员键（不等达阈值），阻止单键长按抢跑
                for (const k of rule.combo) claimedThisFrame.add(k);
                // 阈值起算点：成员中最大的 pressStartMs（最后一个按下的时刻）
                const startMs = Math.max(...rule.combo.map(k => ensure(k).pressStartMs)) || nowMs;
                if (!cs.startMs) cs.startMs = startMs;
                const reached = !cs.fired && (nowMs - cs.startMs) >= rule.thresholdMs;
                if (rule.combo.length > 1) {
                    // 组合键：已达阈值立即触发（它已是高优先级，无需让位）
                    if (reached) {
                        cs.fired = true;
                        if (rule.consume) for (const k of rule.consume) {
                            ensure(k).consumed = true;
                            ensure(k).longFired = true;
                            clearMultiTap(k);
                        }
                        const a = rule.action(ctx);
                        if (a) actions.push(a);
                    }
                } else {
                    // 单键 hold：达阈值后不立即触发，先进入 pending 宽限期，给组合伙伴留补按窗口。
                    if (reached && !cs.pendingUntil) cs.pendingUntil = nowMs + HOLD_GRACE_MS;
                    if (cs.pendingUntil && !cs.fired && nowMs >= cs.pendingUntil) {
                        cs.fired = true;
                        cs.pendingUntil = 0;
                        if (rule.consume) for (const k of rule.consume) {
                            ensure(k).consumed = true;
                            ensure(k).longFired = true;
                            clearMultiTap(k);
                        }
                        const a = rule.action(ctx);
                        if (a) actions.push(a);
                    }
                }
            } else {
                // 离开候选：伙伴按下(notOk 翻转) 或被更高优先级 combo 占用。
                // 若此前已达阈值进 pending，此刻直接丢弃——组合接管，绝不补发单键 action。
                cs.startMs = 0;
                cs.fired = false;
                cs.pendingUntil = 0;
            }
        }

        // 4. edge 规则：down 边沿即触发（一次性）
        for (const rule of rules) {
            if (rule.kind !== 'edge') continue;
            if (!allowed(rule)) continue;
            const memberDown = rule.combo.some(k => edges[k] === 'down');
            if (!memberDown) continue;
            if (rule.context && !rule.context(ctx)) continue;
            if (!evalRuleNot(snapshots, rule)) continue;
            const a = rule.action(ctx);
            if (a) actions.push(a);
        }

        // 5. up 边沿：tap 判定（成员未被消费、未达长按）
        for (const k of RULE_KEYS) {
            if (edges[k] !== 'up') continue;
            const st = ensure(k);
            if (st.consumed || st.longFired) {
                // 已被 hold/combo 消费或已长按 → 不回退 tap
                clearMultiTap(k);
                st.pressStartMs = 0; st.longFired = false; st.consumed = false;
                continue;
            }
            const duration = st.pressStartMs ? (nowMs - st.pressStartMs) : 0;
            st.pressStartMs = 0;

            const mts = multiTapState[k];
            if (mts && mts.phase === 'secondPressed') {
                const doubleRule = mts.doubleRule;
                const secondDuration = nowMs - mts.secondPressStartMs;
                const doubleMatched = secondDuration <= doubleRule.tapTimeMs && eligible(doubleRule);
                clearMultiTap(k);
                if (doubleMatched) {
                    const a = doubleRule.action(ctx);
                    if (a) actions.push(a);
                }
                st.longFired = false; st.consumed = false;
                continue;
            }

            // 按 priority 找同键、not 满足、context 通过且时长合格的 tap/doubleTap 规则。
            const tapRule = rules.find(rule => rule.kind === 'tap'
                && rule.combo.includes(k)
                && duration < rule.thresholdMs
                && eligible(rule));
            const doubleRule = rules.find(rule => rule.kind === 'doubleTap'
                && rule.combo.includes(k)
                && duration <= rule.tapTimeMs
                && eligible(rule));
            const tapAction = tapRule ? tapRule.action(ctx) : null;

            if (doubleRule) {
                // 仅配置了双击的键进入等待；保存已按第一次松开上下文计算出的纯 Action。
                multiTapState[k] = {
                    phase: 'waitingSecond',
                    doubleRule,
                    firstAction: tapAction,
                    deadlineMs: nowMs + doubleRule.tapDelayMs,
                    secondPressStartMs: 0,
                };
            } else if (tapAction) {
                actions.push(tapAction);
            }
            st.longFired = false; st.consumed = false;
        }

        return actions;
    }

    /** 清空所有按压/组合状态，不产生 tap（用于会话结束/控制器消失/上下文切换）。 */
    function cancel(/* reason */) {
        for (const k of Object.keys(keyState)) {
            keyState[k].pressStartMs = 0;
            keyState[k].longFired = false;
            keyState[k].consumed = false;
            keyState[k].lastPressed = false;
        }
        for (const id of Object.keys(comboState)) {
            comboState[id].startMs = 0;
            comboState[id].fired = false;
            comboState[id].pendingUntil = 0;
        }
        for (const k of Object.keys(multiTapState)) clearMultiTap(k);
    }

    return { update, cancel };
}
