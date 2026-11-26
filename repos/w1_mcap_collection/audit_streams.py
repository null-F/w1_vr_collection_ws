#!/usr/bin/env python3
"""Full offline readback of the ten chassis streams, optionally by operator stage."""
import argparse
from bisect import bisect_right
import json
from pathlib import Path

from mcap.reader import make_reader
import yaml


def counters():
    return dict(count=0, first_ns=None, last_ns=None, max_gap_ns=None, backwards=0)


def sample(stats, ns):
    if stats['count']:
        gap = ns - stats['last_ns']
        stats['backwards'] += int(gap < 0)
        stats['max_gap_ns'] = max(stats['max_gap_ns'] or 0, gap)
    else:
        stats['first_ns'] = ns
    stats['count'] += 1
    stats['last_ns'] = ns


def stats(topics):
    return {t: counters() for t in topics}


def audit(episode):
    config = yaml.safe_load(Path(__file__).with_name('topics.yaml').read_text())
    session_file = episode / 'episode.json'
    chosen = json.loads(session_file.read_text()).get('topics', config['continuous']) if session_file.is_file() else config['continuous']
    topics = [t for t in chosen if t.startswith(('/laser_scan/', '/orbbec/'))]
    totals = stats(topics)
    stages = []
    stage_file = episode / 'operator_events.jsonl'
    if stage_file.is_file():
        stages = [json.loads(line) for line in stage_file.read_text().splitlines()]
        if any(b['wall_ns'] < a['wall_ns'] for a, b in zip(stages, stages[1:])):
            raise ValueError('Operator event wall clock moved backwards')
    windows = [dict(start_ns=a['wall_ns'], end_ns=b['wall_ns'], event=a, topics=stats(topics))
               for a, b in zip(stages, stages[1:])]
    starts = [w['start_ns'] for w in windows]
    bag = (episode / 'raw').resolve()
    meta = yaml.safe_load((bag / 'metadata.yaml').read_text())['rosbag2_bagfile_information']
    for name in meta['relative_file_paths']:
        path = (bag / name).resolve()
        if not path.is_relative_to(bag) or path.suffix != '.mcap':
            raise ValueError('Invalid MCAP volume path')
        with path.open('rb') as f:
            for _, channel, msg in make_reader(f, validate_crcs=True).iter_messages(topics=topics):
                ns = msg.log_time
                sample(totals[channel.topic], ns)
                i = bisect_right(starts, ns) - 1
                if i >= 0 and ns < windows[i]['end_ns']:
                    sample(windows[i]['topics'][channel.topic], ns)
    for group in [totals] + [w['topics'] for w in windows]:
        for row in group.values():
            span = (row['last_ns'] or 0) - (row['first_ns'] or 0)
            row['mean_hz'] = (row['count']-1)*1e9/span if span > 0 else None
    for window in windows:
        for row in window['topics'].values():
            row['max_gap_including_edges_ns'] = (max(row['first_ns'] - window['start_ns'],
                window['end_ns'] - row['last_ns'], row['max_gap_ns'] or 0) if row['count']
                else window['end_ns'] - window['start_ns'])
    return dict(clock='mcap_log_time_ns', topics=totals, operator_windows=windows)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('episode', type=Path)
    print(json.dumps(audit(parser.parse_args().episode), indent=2))
