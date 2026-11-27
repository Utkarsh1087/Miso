/**
 * Pure ES module defining deterministic emotion/intensity blendshape weights,
 * anime VFX mappings, and .vrma gesture playback modes matching riko/tags.py 1:1.
 */

export const DEFAULT_EMOTION = 'neutral';
export const DEFAULT_INTENSITY = 2;

export const SIGNATURE_GESTURES = Object.freeze([
  'shrug',
  'cross_arms',
  'facepalm',
  'head_tilt',
  'point',
  'wave',
  'nod',
  'shake_head',
  'smug',
  'sigh',
  'think',
]);

export const SUPPORTED_EMOTIONS = Object.freeze([
  'neutral',
  'happy',
  'angry',
  'sad',
  'surprised',
  'relaxed',
  'flustered',
  'annoyed',
  'jealous',
  'smug',
  'caring',
]);

export const EMOTION_VFX_MAP = Object.freeze({
  neutral: null,
  relaxed: null,
  angry: 'anger_vein',
  flustered: 'blush_lines',
  happy: 'sparkles',
  annoyed: 'sweatdrop',
  sad: 'gloom_lines',
  surprised: 'shock_marks',
  caring: 'heart_pop',
  smug: 'kira_star',
  jealous: 'annoyed_scribble',
});

export const BLENDSHAPE_TABLE = Object.freeze({
  neutral: {
    1: { neutral: 1.0 },
    2: { neutral: 1.0 },
    3: { neutral: 1.0 },
  },
  happy: {
    1: { happy: 0.45 },
    2: { happy: 0.75 },
    3: { happy: 1.0 },
  },
  angry: {
    1: { angry: 0.45 },
    2: { angry: 0.75 },
    3: { angry: 1.0 },
  },
  sad: {
    1: { sad: 0.35 },
    2: { sad: 0.60 },
    3: { sad: 0.85 },
  },
  surprised: {
    1: { surprised: 0.40 },
    2: { surprised: 0.70 },
    3: { surprised: 1.0 },
  },
  relaxed: {
    1: { relaxed: 0.35 },
    2: { relaxed: 0.65 },
    3: { relaxed: 0.95 },
  },
  flustered: {
    1: { happy: 0.30, surprised: 0.20 },
    2: { happy: 0.50, surprised: 0.35 },
    3: { happy: 0.70, surprised: 0.50 },
  },
  annoyed: {
    1: { angry: 0.25, sad: 0.15 },
    2: { angry: 0.45, sad: 0.25 },
    3: { angry: 0.65, sad: 0.35 },
  },
  jealous: {
    1: { angry: 0.35, sad: 0.20 },
    2: { angry: 0.60, sad: 0.35 },
    3: { angry: 0.85, sad: 0.50 },
  },
  smug: {
    1: { relaxed: 0.40, happy: 0.20 },
    2: { relaxed: 0.65, happy: 0.35 },
    3: { relaxed: 0.90, happy: 0.50 },
  },
  caring: {
    1: { relaxed: 0.35, happy: 0.25 },
    2: { relaxed: 0.60, happy: 0.45 },
    3: { relaxed: 0.85, happy: 0.65 },
  },
});

const VFX_SCALE_BY_INTENSITY = Object.freeze({ 1: 0.75, 2: 1.0, 3: 1.25 });
const VFX_OPACITY_BY_INTENSITY = Object.freeze({ 1: 0.65, 2: 0.85, 3: 1.0 });

export function clampIntensity(value, defaultValue = DEFAULT_INTENSITY) {
  if (typeof value === 'boolean' || value === null || value === undefined || value === '') {
    return Math.max(1, Math.min(3, Math.trunc(defaultValue)));
  }
  const num = Number(value);
  if (!Number.isFinite(num)) {
    return Math.max(1, Math.min(3, Math.trunc(defaultValue)));
  }
  return Math.max(1, Math.min(3, Math.trunc(num)));
}

export function normalizeEmotion(emotion, defaultEmotion = DEFAULT_EMOTION) {
  const fallback = SUPPORTED_EMOTIONS.includes(defaultEmotion) ? defaultEmotion : DEFAULT_EMOTION;
  if (typeof emotion !== 'string') return fallback;
  const key = emotion.trim().toLowerCase().replace(/[\s-]+/g, '_');
  return SUPPORTED_EMOTIONS.includes(key) ? key : fallback;
}

export function normalizeGesture(gesture) {
  if (typeof gesture !== 'string') return null;
  const key = gesture.trim().toLowerCase().replace(/[\s-]+/g, '_');
  return SIGNATURE_GESTURES.includes(key) ? key : null;
}

export function computeBlendshapeTargets(emotion, intensity = DEFAULT_INTENSITY) {
  const emo = normalizeEmotion(emotion, DEFAULT_EMOTION);
  const lvl = clampIntensity(intensity, emo === 'neutral' ? 1 : DEFAULT_INTENSITY);
  const row = BLENDSHAPE_TABLE[emo][lvl];
  const result = {};
  for (const [k, v] of Object.entries(row)) {
    result[k] = Math.max(0.0, Math.min(1.0, v));
  }
  return result;
}

export function resolveVfxSpec(emotion, intensity = DEFAULT_INTENSITY, explicitVfx = undefined) {
  const emo = normalizeEmotion(emotion, DEFAULT_EMOTION);
  const lvl = clampIntensity(intensity, emo === 'neutral' ? 1 : DEFAULT_INTENSITY);
  const vfxId = explicitVfx !== undefined ? explicitVfx : EMOTION_VFX_MAP[emo];
  if (!vfxId) {
    return { id: null, emotion: emo, intensity: lvl, scale: 0.0, opacity: 0.0 };
  }
  return {
    id: vfxId,
    emotion: emo,
    intensity: lvl,
    scale: VFX_SCALE_BY_INTENSITY[lvl],
    opacity: VFX_OPACITY_BY_INTENSITY[lvl],
  };
}

export function selectActionPlaybackMode(gesture) {
  if (gesture === 'idle') return 'LoopRepeat';
  return 'LoopOnce';
}
