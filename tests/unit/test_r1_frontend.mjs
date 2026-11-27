import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { resolve } from 'node:path';

import {
  BLENDSHAPE_TABLE,
  EMOTION_VFX_MAP,
  SIGNATURE_GESTURES,
  SUPPORTED_EMOTIONS,
  computeBlendshapeTargets,
  resolveVfxSpec,
  selectActionPlaybackMode,
} from '../../client/js/visualState.js';

const ROOT = resolve(import.meta.dirname, '..', '..');

test('JS visualState matches Python riko/tags.py contract 1:1', () => {
  const pyJson = execFileSync(
    resolve(ROOT, '.venv', 'Scripts', 'python.exe'),
    [
      '-c',
      [
        'import json',
        'from riko import tags',
        'print(json.dumps({',
        '  "gestures": list(tags.SIGNATURE_GESTURES),',
        '  "emotions": list(tags.SUPPORTED_EMOTIONS),',
        '  "vfx": tags.EMOTION_VFX_MAP,',
        '  "blendshapes": {e: {str(k): v for k, v in tbl.items()} for e, tbl in tags._BLENDSHAPE_TABLE.items()},',
        '}))',
      ].join('\n'),
    ],
    { encoding: 'utf-8' },
  );
  const py = JSON.parse(pyJson);

  assert.deepEqual([...SIGNATURE_GESTURES], py.gestures);
  assert.ok(SIGNATURE_GESTURES.length <= 12);
  assert.deepEqual([...SUPPORTED_EMOTIONS], py.emotions);
  assert.deepEqual({ ...EMOTION_VFX_MAP }, py.vfx);

  for (const emo of SUPPORTED_EMOTIONS) {
    for (const lvl of [1, 2, 3]) {
      assert.deepEqual(computeBlendshapeTargets(emo, lvl), py.blendshapes[emo][String(lvl)]);
    }
  }
});

test('computeBlendshapeTargets scales monotonically 1 < 2 < 3 and clamps [0, 1]', () => {
  for (const emo of SUPPORTED_EMOTIONS) {
    const t1 = computeBlendshapeTargets(emo, 1);
    const t2 = computeBlendshapeTargets(emo, 2);
    const t3 = computeBlendshapeTargets(emo, 3);
    assert.deepEqual(computeBlendshapeTargets(emo, 0), t1);
    assert.deepEqual(computeBlendshapeTargets(emo, 9), t3);

    if (emo !== 'neutral') {
      for (const k of Object.keys(t1)) {
        assert.ok(t1[k] < t2[k], `${emo}.${k} level 1 < 2`);
        assert.ok(t2[k] < t3[k], `${emo}.${k} level 2 < 3`);
        assert.ok(t1[k] >= 0 && t3[k] <= 1);
      }
    } else {
      assert.equal(t1.neutral, 1.0);
      assert.equal(t3.neutral, 1.0);
    }
  }
});

test('resolveVfxSpec maps emotions deterministically and exists in manifest.json', () => {
  const manifest = JSON.parse(readFileSync(resolve(ROOT, 'client', 'vfx', 'manifest.json'), 'utf-8'));

  assert.equal(resolveVfxSpec('angry', 2).id, 'anger_vein');
  assert.equal(resolveVfxSpec('flustered', 2).id, 'blush_lines');
  assert.equal(resolveVfxSpec('happy', 3).id, 'sparkles');
  assert.equal(resolveVfxSpec('annoyed', 1).id, 'sweatdrop');
  assert.equal(resolveVfxSpec('neutral', 1).id, null);
  assert.equal(resolveVfxSpec('relaxed', 2).id, null);

  for (const emo of SUPPORTED_EMOTIONS) {
    const s1 = resolveVfxSpec(emo, 1);
    const s2 = resolveVfxSpec(emo, 2);
    const s3 = resolveVfxSpec(emo, 3);
    assert.equal(s1.id, EMOTION_VFX_MAP[emo]);
    if (s1.id !== null) {
      assert.ok(Object.hasOwn(manifest.effects, s1.id), `Missing manifest entry for ${s1.id}`);
      assert.ok(s1.scale < s2.scale && s2.scale < s3.scale);
      assert.ok(s1.opacity < s2.opacity && s2.opacity < s3.opacity);
    } else {
      assert.equal(s1.scale, 0);
      assert.equal(s1.opacity, 0);
    }
  }
});

test('selectActionPlaybackMode uses LoopRepeat for idle and LoopOnce for gestures', () => {
  assert.equal(selectActionPlaybackMode('idle'), 'LoopRepeat');
  for (const g of SIGNATURE_GESTURES) {
    assert.equal(selectActionPlaybackMode(g), 'LoopOnce');
  }
});
