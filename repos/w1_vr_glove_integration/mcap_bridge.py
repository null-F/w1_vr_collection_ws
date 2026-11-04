"""Asynchronous MCAP control; every VR input is observed before any slow RPC."""
import asyncio
import json
from pathlib import Path
import subprocess
import time
from glove_manager import Voice

HERE=Path(__file__).resolve().parent
OWNER=Path('/home/dexforce/linkerhand/runtime/vr_mcap_owner.json')
_bridge=None


def request_cancel():
    if _bridge is not None:_bridge.ask_cancel()


def rpc(command):
    p=subprocess.run(['bash',str(HERE/'mcap_rpc.sh'),command],capture_output=True,text=True,timeout=105)
    try:value=json.loads(p.stdout)
    except ValueError:raise RuntimeError('MCAP RPC invalid output: '+(p.stderr+p.stdout)[-500:])
    if not value.get('success'):raise RuntimeError(str(value))
    return value['result']


class Bridge:
    def __init__(self,controller,message_class,runner=rpc,voice=None):
        self.controller=controller;self.message_class=message_class;self.runner=runner
        self.voice=voice if voice is not None else Voice()
        self.want=False;self.previous=False;self.grip=False;self.last_input=0.0
        self.episode=None;self.ws=None;self.worker=None;self.closed=False
        self.phase='idle';self.reason='button';self.error_at=0.0;self.last_poll=0.0
        self.cancel_flag=False;self.recover=OWNER.exists()
        global _bridge;_bridge=self

    def ensure_worker(self):
        if self.worker is None or self.worker.done():self.worker=asyncio.create_task(self.run())

    def ask_cancel(self):
        # Low-frequency dispatch runs on another thread. Only set the flag;
        # the pose-server loop already polls it while a recording is active.
        self.cancel_flag=True;self.want=False;self.reason='cancel'

    def observe(self,ws,pressed,grip):
        if self.cancel_flag or self.phase=='cancelling' or self.reason=='cancel':
            self.last_input=time.monotonic();self.previous=bool(pressed);self.ensure_worker();return
        if self.ws is not None and ws is not None and ws is not self.ws and (self.want or self.episode):return
        self.last_input=time.monotonic();self.grip=bool(grip)
        if pressed and not self.previous:
            if self.want:self.want=False;self.reason='button'
            elif self.grip and self.phase=='idle':self.want=True;self.ws=ws
        self.previous=bool(pressed)
        if not self.grip:self.want=False;self.reason='grip_release'
        self.ensure_worker()

    def stop(self,reason):
        self.want=False;self.reason=reason;self.ensure_worker()

    async def ui(self,kind,**fields):
        try:await self.controller.broadcast_callback(self.message_class(message=dict(type=kind,**fields)))
        except Exception as exc:print('MCAP_UI_FAILED',repr(exc),flush=True)

    async def finish(self):
        self.phase='saving'
        await self.ui('linkerhand_mcap_record',action='stop',reason=self.reason)
        try:
            result=await asyncio.to_thread(self.runner,'stop')
            good=result.get('save_status')=='saved'
            if not good:raise RuntimeError(str(result))
            await self.ui('data_save',success=True,file_path=result.get('episode_dir',''))
            self.voice.say('数据采集已保存。')
            if result.get('missing_topics'):
                print('MCAP_MISSING_TOPICS',result['missing_topics'],flush=True)
            print('MCAP_SAVED',json.dumps(result,ensure_ascii=False),flush=True)
            self.episode=None;self.recover=False;self.phase='idle';self.ws=None
        except Exception as exc:
            self.want=False
            await self.ui('data_save',success=False,error=str(exc))
            self.voice.say('数据采集保存失败，请检查采集日志。')
            print('MCAP_SAVE_FAILED',repr(exc),flush=True)
            self.phase='error';self.episode=None;self.recover=OWNER.exists();self.error_at=time.monotonic()

    async def discard(self):
        self.phase='cancelling';self.want=False;self.reason='cancel'
        await self.ui('linkerhand_mcap_record',action='cancel',reason='cancel')
        try:
            result=await asyncio.to_thread(self.runner,'cancel')
            if result.get('save_status')!='cancelled':raise RuntimeError(str(result))
            self.voice.say('本次采集任务已取消。')
            print('MCAP_CANCELLED',json.dumps(result,ensure_ascii=False),flush=True)
            self.episode=None;self.recover=False;self.phase='idle';self.ws=None;self.reason='button'
        except Exception as exc:
            self.want=False;self.reason='button'
            await self.ui('data_save',success=False,error=str(exc))
            self.voice.say('数据采集取消失败，请检查采集日志。')
            print('MCAP_CANCEL_FAILED',repr(exc),flush=True)
            if self.episode:self.phase='recording'
            else:self.phase='error';self.recover=OWNER.exists();self.error_at=time.monotonic()
        finally:
            self.cancel_flag=False

    async def run(self):
        while not self.closed:
            if self.cancel_flag and self.phase not in ('cancelling','saving','starting'):
                self.want=False;self.reason='cancel'
                if self.episode:
                    await self.discard();continue
                self.cancel_flag=False
            if self.reason!='cancel' and self.want and time.monotonic()-self.last_input>3:
                self.want=False;self.reason='vr_input_lost'
            if self.phase=='error' and time.monotonic()-self.error_at<5:
                await asyncio.sleep(.1);continue
            if self.recover and self.reason!='cancel':
                await self.finish()
            elif self.episode and not self.want and self.reason!='cancel':
                await self.finish()
            elif self.reason=='cancel' and self.episode:
                await self.discard()
            elif self.want and not self.episode:
                self.phase='starting'
                try:
                    result=await asyncio.to_thread(self.runner,'start')
                    self.episode=result['episode_dir'];self.phase='recording'
                    if self.cancel_flag or self.reason=='cancel':
                        await self.discard()
                    elif self.want and self.grip and time.monotonic()-self.last_input<=3:
                        await self.ui('linkerhand_mcap_record',action='start',session_id=self.episode)
                        self.voice.say('数据采集已开启。')
                    else:self.want=False
                except Exception as exc:
                    self.want=False;self.cancel_flag=False;self.recover=OWNER.exists();self.phase='error';self.error_at=time.monotonic()
                    self.voice.say('数据采集启动失败，请检查采集日志。')
                    await self.ui('data_status',error_msg='MCAP采集启动失败：'+str(exc))
                    print('MCAP_START_FAILED',repr(exc),flush=True)
            elif self.episode and time.monotonic()-self.last_poll>2:
                self.last_poll=time.monotonic()
                try:
                    state=await asyncio.to_thread(self.runner,'status')
                    if self.cancel_flag or self.reason=='cancel':
                        await self.discard()
                    elif not state.get('recording') or state.get('episode_dir')!=self.episode:
                        self.want=False;self.reason='recorder_exit';await self.finish()
                except Exception as exc:
                    print('MCAP_MONITOR_ERROR',repr(exc),flush=True)
                    self.want=False;self.reason='recorder_unavailable'
            elif self.phase=='error' and not self.recover:self.phase='idle'
            await asyncio.sleep(.1)

    async def close(self):
        if not (self.cancel_flag or self.reason=='cancel' or self.phase=='cancelling'):
            self.want=False;self.reason='vr_shutdown'
        self.ensure_worker()
        deadline=time.monotonic()+110
        while (self.phase in ('starting','saving','cancelling') or self.episode or self.recover) and time.monotonic()<deadline:
            await asyncio.sleep(.1)
        self.closed=True
        if self.worker and not self.worker.done():
            self.worker.cancel()
            try:await self.worker
            except asyncio.CancelledError:pass
        close_voice=getattr(self.voice,'close',None)
        if close_voice is not None:await asyncio.to_thread(close_voice)


def patch_buttons(module):
    cls=module.RecordingButtonController
    init=cls.__init__
    def initialize(self,*args,**kwargs):
        init(self,*args,**kwargs)
        self.linker_mcap=Bridge(self,module.RobotStatusMessage)
        self.state._linker_mcap_bridge=self.linker_mcap
        bind_pose_lifecycle(self)
    cls.__init__=initialize
    def schedule(self,ws,vr_msg,left_enable_button_state,dual_enable_pressed):
        self.linker_mcap.observe(ws,left_enable_button_state,dual_enable_pressed)
    cls.schedule_recording_controls=schedule
    async def stop(self,reason):self.linker_mcap.stop(reason)
    cls.stop_recording_if_active=stop
    async def process(self,left_enable_button_state,dual_enable_pressed):
        self.linker_mcap.observe(self.linker_mcap.ws,left_enable_button_state,dual_enable_pressed)
    cls.process_button_state=process
    async def toggle(self):
        b=self.linker_mcap;b.observe(b.ws,False,b.grip);b.observe(b.ws,True,b.grip)
    cls.handle_record_button_press=toggle
    cls.record_frame=lambda *args,**kwargs:None
    print('LINKERHAND_MCAP_PATCH VR recording buttons use MCAP only',flush=True)


def bind_pose_lifecycle(controller):
    # The -m entrypoint is __main__; hook its existing instance, not its loader.
    pose=getattr(controller.broadcast_callback,'__self__',None)
    if pose is None or not hasattr(pose,'_abort_recording_for_disconnected_client'):return
    bridge=controller.linker_mcap
    disconnected_original=pose._abort_recording_for_disconnected_client
    async def disconnected(ws,client_addr):
        if bridge.ws is ws:bridge.stop('client_disconnected')
        return await disconnected_original(ws,client_addr)
    pose._abort_recording_for_disconnected_client=disconnected
    shutdown_original=pose.shutdown
    async def shutdown():
        await bridge.close()
        return await shutdown_original()
    pose.shutdown=shutdown


def patch_handlers(module):
    cls=module.MessageHandlers
    async def toggle(self,state,data_manager,broadcast_callback):
        bridge=getattr(state,'_linker_mcap_bridge',None)
        if bridge:
            bridge.observe(bridge.ws,False,bridge.grip)
            bridge.observe(bridge.ws,True,bridge.grip)
    cls.handle_record_button_press=toggle
    async def stop(self,state,data_manager):
        bridge=getattr(state,'_linker_mcap_bridge',None)
        if bridge:bridge.stop('legacy_stop')
    cls.stop_recording_if_active=stop
    async def preview(self,ws,msg,client_addr):
        await ws.send(module.encode_message(module.DataDeletePreviewResultMessage(
            success=False,session_id='',folder_name='',folder_path='',
            error_code='MCAP数据删除尚未接入VR，请使用采集目录管理。')))
    cls.handle_data_delete_preview=preview
    async def delete(self,ws,msg,client_addr,broadcast_callback):
        data=msg.to_dict() if hasattr(msg,'to_dict') else msg
        await broadcast_callback(module.DataDeleteResultMessage(success=False,file_path='',
            error_code='MCAP数据删除尚未接入VR。',session_id=data.get('session_id'),msg_id=data.get('msg_id')))
    cls.handle_data_delete=delete
