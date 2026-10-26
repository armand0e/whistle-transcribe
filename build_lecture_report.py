"""Build an auditable side-by-side comparison; independent ASR is not truth."""
import html
import argparse
import hashlib
import json
import re
from pathlib import Path
from evaluate_lecture import OUT, SOURCE

def tokens(text):
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text.lower())

def distance(a, b):
    previous = list(range(len(b) + 1))
    for i, token in enumerate(a, 1):
        current = [i]
        for j, other in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (token != other)))
        previous = current
    return previous[-1]

def extract(results, start=0, end=1e6, mode='stream'):
    parts = []
    for result in results:
        words = result.get('words') or []
        if words:
            offset = result.get('section_start', 0) if mode == 'long' else 0
            parts.extend(word['word'] for word in words if start <= word['start'] + offset < end)
        else:
            position = result.get('start', result.get('received', 0))
            if start <= position < end and result.get('text', '').strip():
                parts.append(result['text'].strip())
    return ' '.join(parts)

def main():
    global SOURCE, OUT
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--score-from', type=float, default=7)
    args = parser.parse_args()
    SOURCE = args.source.resolve()
    OUT = SOURCE / 'quality-comparison'
    experiment = json.loads((OUT / 'experiment.json').read_text(encoding='utf-8'))
    duration = experiment['duration_seconds']
    assert hashlib.sha256((SOURCE / 'Audio.wav').read_bytes()).hexdigest() == experiment['source_sha256'], 'Source audio changed'
    assert hashlib.sha256((SOURCE / 'Transcript.txt').read_bytes()).hexdigest() == experiment['original_transcript_sha256'], 'Original transcript changed'
    spans = experiment['sections_seconds']
    assert spans[0][0] == 0 and spans[-1][1] == duration
    assert all(left[1] == right[0] for left, right in zip(spans, spans[1:])), 'Section gap or overlap'
    original = [json.loads(line) for line in (SOURCE / 'segments.jsonl').read_text(encoding='utf-8').splitlines()]
    variants = {'Original live': (original, 'stream')}
    timings = {}
    for name in ['stream_auto', 'stream_english', 'stream_english_biology', 'long_auto', 'long_english', 'long_english_biology']:
        result = json.loads((OUT / f'{name}.json').read_text(encoding='utf-8'))
        variants[name] = (result['results'], name.split('_')[0])
        timings[name] = round(result['elapsed_seconds'], 2)
    independent = json.loads((OUT / 'independent_whisper_small_en.json').read_text(encoding='utf-8'))
    reference = independent['segments']
    # Skip the initial interrupted/restarted fragment for the numerical comparison.
    reference_tokens = tokens(extract(reference, start=args.score_from))
    stats = {}
    for name, (results, mode) in variants.items():
        candidate = tokens(extract(results, start=args.score_from, mode=mode))
        edits = distance(reference_tokens, candidate)
        stats[name] = {'token_edits_vs_independent': edits, 'independent_tokens': len(reference_tokens),
                       'disagreement_percent': round(100 * edits / len(reference_tokens), 2),
                       'candidate_tokens': len(candidate), 'elapsed_seconds': timings.get(name)}
    (OUT / 'comparison-metrics.json').write_text(json.dumps({
        'warning': 'ASR-to-ASR disagreement, NOT word error rate against verified ground truth. Lower is stronger agreement only.',
        'scored_audio_seconds': [args.score_from, duration], 'independent_model': independent['model'], 'variants': stats
    }, indent=2), encoding='utf-8')

    rows = []
    for name, metric in stats.items():
        elapsed = metric['elapsed_seconds']
        elapsed_text = f'{elapsed:.1f} s' if elapsed is not None else 'live recording'
        rows.append(f'<tr><td>{html.escape(name)}</td><td>{metric["token_edits_vs_independent"]}/{len(reference_tokens)}</td><td>{metric["disagreement_percent"]}%</td><td>{elapsed_text}</td></tr>')
    sections = []
    chosen = ['Original live', 'stream_english', 'stream_english_biology', 'long_english', 'long_english_biology']
    for start in range(0, int(duration), 20):
        blocks = []
        for name in chosen:
            results, mode = variants[name]
            text = extract(results, start, start + 20, mode)
            blocks.append(f'<article><h3>{html.escape(name)}</h3><p>{html.escape(text)}</p></article>')
        text = extract(reference, start, start + 20)
        blocks.append(f'<article class="reference"><h3>Independent Whisper small.en hypothesis</h3><p>{html.escape(text)}</p></article>')
        sections.append(f'<section><h2>{start // 60:02}:{start % 60:02}–{(start+20)//60:02}:{(start+20)%60:02}</h2><audio controls preload="none" src="../Audio.wav#t={start},{min(start+20,duration)}"></audio><div class="grid">'+''.join(blocks)+'</div></section>')
    document = '''<!doctype html><html lang="en"><meta charset="utf-8"><title>Lecture transcription comparison</title>
<style>body{font:16px/1.5 system-ui;max-width:1500px;margin:40px auto;padding:0 24px;color:#1d2a33;background:#f6f8fa}h1{font-size:32px}h2{margin-top:36px}table{border-collapse:collapse;background:white}th,td{padding:10px 18px;text-align:left;border:1px solid #d4dce3}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}article{background:white;border:1px solid #d4dce3;padding:16px;border-radius:12px}h3{font-size:15px;color:#356556}.reference{background:#edf2fb}a{color:#145e83}.note{padding:18px;background:#fff0d4;border-radius:10px}@media(max-width:900px){.grid{grid-template-columns:1fr}}</style>
<h1>Lecture transcription comparison</h1><p>One saved recording · 340.4 seconds · local inference · original files preserved</p>
<p class="note"><strong>These percentages are disagreement with an independent ASR model, not verified accuracy.</strong> Whisper small.en can also make mistakes. No human-verified reference is available. The glossary is lecture-informed, so this is a development comparison rather than a held-out evaluation. The initial interrupted fragment (0–7 s) is excluded from numerical comparisons. Playback-speed changes are baked into the source; this does not validate performance on the original video at normal speed.</p>
<p>Streaming replays use one-second input chunks. Final passes use the same contiguous 18–28 second sections, cut near quiet regions, with no missing or duplicated source samples. English and the fixed biology glossary are varied separately. Independent Whisper uses English, five beams, CPU int8, and no glossary.</p>
<p>Inference times are observations under concurrent evaluation workloads, not isolated speed benchmarks.</p>
<p><a href="long_english_biology.txt">Long-section biology transcript</a> · <a href="experiment.json">Fixed glossary and source hashes</a> · <a href="comparison-metrics.json">Metrics and timing data</a> · <a href="../Transcript.txt">Original transcript</a> · <a href="../Audio.wav">Original audio</a></p>
<table><tr><th>Variant</th><th>Token edits / independent words</th><th>Disagreement</th><th>Inference time</th></tr>'''+''.join(rows)+'''</table>
<p>Twenty-second excerpts below use token timestamps for Whistle. Independent ASR segments are assigned by their start time, so its excerpt boundaries are approximate.</p>'''+''.join(sections)+'</html>'
    document = document.replace('340.4 seconds', f'{duration:.2f} seconds')
    if args.score_from == 0:
        document = document.replace('The initial interrupted fragment (0–7 s) is excluded from numerical comparisons.', 'The full recording is included in numerical comparisons.')
        document = document.replace('Playback-speed changes are baked into the source; this does not validate performance on the original video at normal speed.', 'The user identifies this recording as normal-speed playback. The biology glossary is unchanged from the first lecture, including terms absent from this clip.')
    (OUT / 'Comparison.html').write_text(document, encoding='utf-8')
    print(json.dumps(stats, indent=2))

if __name__ == '__main__':
    main()
