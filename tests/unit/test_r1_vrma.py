"""Unit tests verifying VRMC_vrm_animation 1.0 compliance, VRMA assets, and VFX manifest."""
from __future__ import annotations

import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest

from PIL import Image

from riko import tags

ROOT = Path(__file__).resolve().parents[2]
VRMA_DIR = ROOT / "client" / "animations" / "vrma"
VFX_DIR = ROOT / "client" / "vfx"

sys.path.insert(0, str(ROOT / "scripts"))
import generate_vrma  # noqa: E402


def parse_glb(raw: bytes) -> tuple[dict, bytes]:
    assert len(raw) >= 12
    magic, version, total_len = struct.unpack_from("<4sII", raw, 0)
    assert magic == b"glTF", f"Bad magic: {magic!r}"
    assert version == 2, f"Bad GLB version: {version}"
    assert total_len == len(raw), f"Length mismatch: {total_len} != {len(raw)}"

    offset = 12
    json_doc = None
    bin_bytes = b""
    chunk_idx = 0
    while offset < len(raw):
        chunk_len, chunk_type = struct.unpack_from("<II", raw, offset)
        offset += 8
        assert chunk_len % 4 == 0, "Chunk length not 4-byte aligned"
        payload = raw[offset : offset + chunk_len]
        assert len(payload) == chunk_len
        offset += chunk_len
        if chunk_idx == 0:
            assert chunk_type == 0x4E4F534A, "Chunk 0 must be JSON"
            json_doc = json.loads(payload.decode("utf-8"))
        elif chunk_idx == 1:
            assert chunk_type == 0x004E4942, "Chunk 1 must be BIN"
            bin_bytes = payload
        chunk_idx += 1
    assert json_doc is not None
    return json_doc, bin_bytes


class TestR1VrmaAndVfx(unittest.TestCase):
    def test_all_expected_vrma_files_present_and_valid(self):
        expected_names = ["idle", *tags.SIGNATURE_GESTURES]
        self.assertLessEqual(len(tags.SIGNATURE_GESTURES), 12)

        for name in expected_names:
            path = VRMA_DIR / f"{name}.vrma"
            self.assertTrue(path.exists(), f"Missing VRMA binary: {path}")
            doc, binary = parse_glb(path.read_bytes())

            self.assertEqual(doc["asset"]["version"], "2.0")
            self.assertIn("VRMC_vrm_animation", doc.get("extensionsUsed", []))
            ext = doc["extensions"]["VRMC_vrm_animation"]
            self.assertEqual(ext["specVersion"], "1.0")
            self.assertIsNone(ext.get("expressions"))

            human_bones = ext["humanoid"]["humanBones"]
            self.assertGreater(len(human_bones), 0)
            self.assertNotIn("leftEye", human_bones)
            self.assertNotIn("rightEye", human_bones)
            self.assertNotIn("jaw", human_bones)

            nodes = doc["nodes"]
            seen_nodes = set()
            for bone, entry in human_bones.items():
                idx = entry["node"]
                self.assertNotIn(idx, seen_nodes)
                self.assertTrue(0 <= idx < len(nodes))
                seen_nodes.add(idx)

            # Acyclic single-parent check
            parents = {}
            for p_idx, node in enumerate(nodes):
                for c_idx in node.get("children", []):
                    self.assertNotIn(c_idx, parents)
                    parents[c_idx] = p_idx
            self.assertEqual(nodes[human_bones["hips"]["node"]].get("translation"), [0.0, 1.0, 0.0])

            # Single animation, strictly increasing times, unit quaternions, no position/expression tracks
            anims = doc.get("animations", [])
            self.assertEqual(len(anims), 1)
            anim = anims[0]
            self.assertGreater(len(anim["samplers"]), 0)
            self.assertEqual(len(anim["samplers"]), len(anim["channels"]))

            for ch in anim["channels"]:
                self.assertEqual(ch["target"]["path"], "rotation")
                sampler = anim["samplers"][ch["sampler"]]
                in_acc = doc["accessors"][sampler["input"]]
                out_acc = doc["accessors"][sampler["output"]]
                self.assertIsNone(in_acc.get("sparse"))
                self.assertIsNone(out_acc.get("sparse"))
                self.assertEqual(in_acc["componentType"], 5126)
                self.assertEqual(in_acc["type"], "SCALAR")
                self.assertEqual(out_acc["componentType"], 5126)
                self.assertEqual(out_acc["type"], "VEC4")

                in_bv = doc["bufferViews"][in_acc["bufferView"]]
                in_off = in_bv.get("byteOffset", 0) + in_acc.get("byteOffset", 0)
                times = struct.unpack_from(f"<{in_acc['count']}f", binary, in_off)
                self.assertGreaterEqual(times[0], 0.0)
                for a, b in zip(times, times[1:]):
                    self.assertLess(a, b)

                out_bv = doc["bufferViews"][out_acc["bufferView"]]
                out_off = out_bv.get("byteOffset", 0) + out_acc.get("byteOffset", 0)
                quats = struct.unpack_from(f"<{out_acc['count'] * 4}f", binary, out_off)
                for i in range(0, len(quats), 4):
                    qx, qy, qz, qw = quats[i : i + 4]
                    self.assertTrue(all(math.isfinite(v) for v in (qx, qy, qz, qw)))
                    norm = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
                    self.assertAlmostEqual(norm, 1.0, places=4)

            for buf in doc.get("buffers", []):
                self.assertNotIn("uri", buf)

    def test_generator_deterministic_and_round_trips_relaxed_rest(self):
        bundle = json.loads((ROOT / "scripts" / "vrma_pose_data.json").read_text(encoding="utf-8"))
        for bone, val in bundle["relaxedRest"].items():
            res = generate_vrma.resolve_joint(bone)
            if not res:
                continue
            jtype, side, _ = res
            q0 = tuple(val["rotation"])
            vals = generate_vrma.decompose_joint_rotation(jtype, side, q0)
            q1 = generate_vrma.compose_joint_rotation(jtype, side, vals)
            dot = abs(sum(a * b for a, b in zip(q0, q1)))
            self.assertAlmostEqual(dot, 1.0, places=6, msg=f"Round-trip failed for {bone}")

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            written = generate_vrma.generate_all(out_dir=out_dir)
            self.assertEqual(len(written), 12)
            for p in written:
                self.assertEqual(p.read_bytes(), (VRMA_DIR / p.name).read_bytes())

    def test_vfx_manifest_and_rgba_assets_complete(self):
        self.assertTrue((VFX_DIR / "ATTRIBUTION.md").exists())
        manifest = json.loads((VFX_DIR / "manifest.json").read_text(encoding="utf-8"))
        effects = manifest["effects"]

        for emo, vfx_id in tags.EMOTION_VFX_MAP.items():
            if vfx_id is not None:
                self.assertIn(vfx_id, effects, f"Missing VFX '{vfx_id}' for emotion '{emo}'")

        for vfx_id, spec in effects.items():
            img_path = VFX_DIR / spec["image"]
            self.assertTrue(img_path.exists(), f"Missing VFX image {img_path}")
            with Image.open(img_path) as im:
                self.assertEqual(im.mode, "RGBA", f"Expected RGBA PNG for {img_path}")
            for alt in (spec.get("intensityImages") or {}).values():
                alt_path = VFX_DIR / alt
                self.assertTrue(alt_path.exists(), f"Missing intensity VFX image {alt_path}")
                with Image.open(alt_path) as im:
                    self.assertEqual(im.mode, "RGBA")


if __name__ == "__main__":
    unittest.main()
