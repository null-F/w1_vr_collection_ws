#!/usr/bin/env python3
"""Single-threaded watchdog for rosbag. Parent loss gracefully closes only this bag."""
import argparse
import signal
import subprocess
import time
from storage import atomic_json, read_json, identity_alive, process_identity, signal_identity


def main():
    p=argparse.ArgumentParser();p.add_argument('--parent',required=True);p.add_argument('--result',required=True)
    p.add_argument('--child-state',required=True);p.add_argument('--grace',type=float,default=20)
    p.add_argument('command',nargs=argparse.REMAINDER);a=p.parse_args()
    command=a.command[1:] if a.command[:1]==['--'] else a.command
    parent=read_json(a.parent)['owner']; requested=[]
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda s,f:requested.append(s))
    proc=None;child=None;reason='worker_error';forced=False
    try:
        proc=subprocess.Popen(command,start_new_session=True)
        child=process_identity(proc.pid);atomic_json(a.child_state,child)
        while proc.poll() is None:
            if requested:reason='signal';break
            if not identity_alive(parent):reason='parent_lost';break
            time.sleep(.1)
        else:reason='child_exit'
    finally:
        if proc is not None and proc.poll() is None:
            signal_identity(child,signal.SIGINT,group=True)
            try:proc.wait(timeout=a.grace)
            except subprocess.TimeoutExpired:
                forced=True;signal_identity(child,signal.SIGTERM,group=True)
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    signal_identity(child,signal.SIGKILL,group=True);proc.wait(timeout=5)
        atomic_json(a.result,{'reason':reason,'returncode':None if proc is None else proc.returncode,
                              'forced':forced,'finished_time_ns':time.time_ns()})

if __name__=='__main__':main()
