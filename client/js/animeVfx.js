import * as THREE from 'three';
import { resolveVfxSpec } from './visualState.js';

/**
 * Head/eye landmark-anchored anime VFX billboard & cheek sprite controller.
 * Clean vanilla JS implementation driven deterministically by (emotion, intensity 1..3).
 */
export class AnimeVfxController {
  constructor(vrm, camera, basePath = 'vfx') {
    this.vrm = vrm;
    this.camera = camera;
    this.basePath = basePath.replace(/\/+$/, '');
    this.manifest = null;
    this.textures = new Map();
    this.textureLoader = new THREE.TextureLoader();

    this.headNode = vrm?.humanoid?.getNormalizedBoneNode('head') || null;
    this.group = new THREE.Group();
    this.group.name = 'MisoAnimeVfxGroup';
    if (this.headNode) {
      this.headNode.add(this.group);
    } else if (vrm?.scene) {
      vrm.scene.add(this.group);
    }

    this.landmarks = this._computeLandmarks();
    this.activeSpec = null;
    this.activeMeshes = [];
    this.elapsed = 0;
    this.disposed = false;

    this._manifestReady = this._loadManifest();
  }

  async _loadManifest() {
    try {
      const res = await fetch(`${this.basePath}/manifest.json`);
      if (!res.ok) return;
      this.manifest = await res.json();
      if (!this.disposed && this.activeSpec?.id) {
        this._rebuildMeshes();
      }
    } catch {
      // Manifest unavailable in offline/headless context
    }
  }

  _computeLandmarks() {
    const defaults = {
      eyeMidY: 0.045,
      eyeSepX: 0.036,
      eyeZ: 0.088,
    };
    if (!this.headNode || !this.vrm?.humanoid) return defaults;

    const leftEye = this.vrm.humanoid.getNormalizedBoneNode('leftEye');
    const rightEye = this.vrm.humanoid.getNormalizedBoneNode('rightEye');
    if (!leftEye || !rightEye) return defaults;

    this.vrm.scene.updateMatrixWorld(true);
    const lPos = new THREE.Vector3();
    const rPos = new THREE.Vector3();
    leftEye.getWorldPosition(lPos);
    rightEye.getWorldPosition(rPos);
    this.headNode.worldToLocal(lPos);
    this.headNode.worldToLocal(rPos);

    const eyeMidY = (lPos.y + rPos.y) * 0.5;
    const eyeSepX = Math.max(0.025, Math.abs(lPos.x - rPos.x) * 0.5);
    const eyeZ = Math.max(0.06, Math.max(lPos.z, rPos.z));
    return { eyeMidY, eyeSepX, eyeZ };
  }

  _getTexture(imageFile) {
    if (this.textures.has(imageFile)) {
      return this.textures.get(imageFile);
    }
    const tex = this.textureLoader.load(`${this.basePath}/${imageFile}`);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.minFilter = THREE.LinearFilter;
    tex.magFilter = THREE.LinearFilter;
    tex.wrapS = THREE.ClampToEdgeWrapping;
    tex.wrapT = THREE.ClampToEdgeWrapping;
    this.textures.set(imageFile, tex);
    return tex;
  }

  setEmotion(emotion, intensity = 2, explicitVfx = undefined) {
    const nextSpec = resolveVfxSpec(emotion, intensity, explicitVfx);
    const same =
      this.activeSpec &&
      this.activeSpec.id === nextSpec.id &&
      this.activeSpec.intensity === nextSpec.intensity;
    if (same) return;

    this.activeSpec = nextSpec;
    this.elapsed = 0;
    this._rebuildMeshes();
  }

  clear() {
    this.activeSpec = null;
    this.elapsed = 0;
    this._clearMeshes();
  }

  _clearMeshes() {
    for (const item of this.activeMeshes) {
      this.group.remove(item.mesh);
      item.mesh.geometry?.dispose();
      item.mesh.material?.dispose();
    }
    this.activeMeshes = [];
  }

  _anchorPosition(def) {
    const lm = this.landmarks;
    const [ox, oy, oz] = def.offset || [0, 0, 0];
    switch (def.anchor) {
      case 'forehead_left':
        return new THREE.Vector3(-lm.eyeSepX * 1.15, lm.eyeMidY + 0.042, lm.eyeZ + 0.018);
      case 'forehead_right':
        return new THREE.Vector3(lm.eyeSepX * 1.22, lm.eyeMidY + 0.042, lm.eyeZ + 0.018);
      case 'forehead_center':
        return new THREE.Vector3(0, lm.eyeMidY + 0.032, lm.eyeZ + 0.02);
      case 'cheeks':
        return new THREE.Vector3(lm.eyeSepX * 1.25, lm.eyeMidY - 0.032, lm.eyeZ + 0.012);
      default:
        return new THREE.Vector3(ox, oy, oz);
    }
  }

  _rebuildMeshes() {
    this._clearMeshes();
    if (this.disposed || !this.activeSpec?.id || !this.manifest?.effects) return;

    const def = this.manifest.effects[this.activeSpec.id];
    if (!def) return;

    const imgFile =
      (def.intensityImages && def.intensityImages[String(this.activeSpec.intensity)]) ||
      def.image;
    const baseTex = this._getTexture(imgFile);
    const tex = baseTex.clone();
    if (tex.image) {
      tex.needsUpdate = true;
    }

    const fb = def.flipbook;
    if (fb && fb.columns > 1 || fb && fb.rows > 1) {
      tex.repeat.set(1 / fb.columns, 1 / fb.rows);
      tex.offset.set(0, 1 - 1 / fb.rows);
    }

    const size = (def.size || 0.08) * this.activeSpec.scale;
    const isCheek = def.anchor === 'cheeks';
    const basePos = this._anchorPosition(def);
    const sides = def.mirror ? [-1, 1] : [1];

    sides.forEach((sideSign) => {
      const geo = new THREE.PlaneGeometry(size, size * (isCheek ? 0.72 : 1.0));
      const mat = new THREE.MeshBasicMaterial({
        map: tex,
        transparent: true,
        opacity: this.activeSpec.opacity,
        depthWrite: false,
        depthTest: isCheek,
        toneMapped: false,
        side: THREE.DoubleSide,
      });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.renderOrder = isCheek ? 950 : 960;

      const pos = basePos.clone();
      if (def.mirror) {
        pos.x = Math.abs(pos.x) * sideSign;
      }
      mesh.position.copy(pos);
      if (def.rotationDeg) {
        mesh.rotation.z = THREE.MathUtils.degToRad(def.rotationDeg * sideSign);
      }

      this.group.add(mesh);
      this.activeMeshes.push({
        mesh,
        tex,
        def,
        basePos: pos.clone(),
        baseScale: 1.0,
        billboard: !isCheek,
        sideSign,
      });
    });
  }

  update(delta) {
    if (this.disposed || this.activeMeshes.length === 0 || !this.activeSpec) return;
    this.elapsed += delta;

    // Pop-in curve over first 0.22s
    const popT = Math.min(1.0, this.elapsed / 0.22);
    const popScale = popT < 0.7 ? 0.4 + (popT / 0.7) * 0.75 : 1.15 - ((popT - 0.7) / 0.3) * 0.15;

    const headWorldQuat = new THREE.Quaternion();
    const camWorldQuat = new THREE.Quaternion();
    if (this.headNode && this.camera) {
      this.headNode.getWorldQuaternion(headWorldQuat);
      this.camera.getWorldQuaternion(camWorldQuat);
    }

    for (const item of this.activeMeshes) {
      const { mesh, tex, def, basePos, billboard, sideSign } = item;

      // Flipbook UV progression
      const fb = def.flipbook;
      if (fb && fb.frames > 1) {
        const rawIdx = Math.floor(this.elapsed * (fb.fps || 8));
        let frame = 0;
        if (fb.loop === 'once') {
          frame = Math.min(fb.frames - 1, rawIdx);
        } else if (fb.loop === 'pingpong') {
          const cycle = Math.max(1, (fb.frames - 1) * 2);
          const pos = rawIdx % cycle;
          frame = pos < fb.frames ? pos : cycle - pos;
        } else {
          frame = rawIdx % fb.frames;
        }
        const col = frame % fb.columns;
        const row = Math.floor(frame / fb.columns);
        tex.repeat.set(1 / fb.columns, 1 / fb.rows);
        tex.offset.set(col / fb.columns, 1 - (row + 1) / fb.rows);
      }

      // Motion (pulse, bob, slide)
      let scaleMod = popScale;
      if (def.pulseHz) {
        scaleMod *= 1.0 + Math.sin(this.elapsed * Math.PI * 2 * def.pulseHz) * (def.pulseAmp || 0.08);
      }
      mesh.scale.setScalar(scaleMod);

      mesh.position.copy(basePos);
      if (def.bobHz) {
        mesh.position.y += Math.sin(this.elapsed * Math.PI * 2 * def.bobHz) * (def.bobAmp || 0.01);
      }
      if (def.slideY && def.slidePeriod) {
        const slideProgress =
          def.flipbook?.loop === 'once'
            ? Math.min(1.0, this.elapsed / def.slidePeriod)
            : (this.elapsed % def.slidePeriod) / def.slidePeriod;
        mesh.position.y += def.slideY * slideProgress;
      }

      if (billboard && this.headNode && this.camera) {
        mesh.quaternion.copy(headWorldQuat).invert().multiply(camWorldQuat);
        if (def.rotationDeg) {
          mesh.rotateZ(THREE.MathUtils.degToRad(def.rotationDeg * sideSign));
        }
      }
    }
  }

  dispose() {
    this.disposed = true;
    this._clearMeshes();
    for (const tex of this.textures.values()) {
      tex.dispose();
    }
    this.textures.clear();
    if (this.group.parent) {
      this.group.parent.remove(this.group);
    }
  }
}
