#!/usr/bin/env python3
"""Export shared robot GLBs + all 48 clips (props GLB + gzipped motion bin + manifest.json)
for ManipTracker's interactive 3D Viewer (#results).

Run with Blender 4.0.2:

    /home/yufeizhu/blender-4.0.2-linux-x64/blender -b --python \
        /home/yufeizhu/repos/ManipTracker/tools/export_viewer.py -- \
        --out /home/yufeizhu/repos/ManipTracker/media/viewer [--skip-robots]
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import pickle
import struct
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

BLENDER_REPO = Path("/home/yufeizhu/repos/ECCV2026_blender")
SMPLX_MESH_DIR = BLENDER_REPO / "asset" / "smplx_humanoid_plasticbox"
FOOTFIX_DIR = Path("/home/yufeizhu/repos/instantTrack-upstream/data/stick_footfix")

SMPLX_52_NAMES = [
    "Pelvis", "L_Hip", "L_Knee", "L_Ankle", "L_Toe", "R_Hip", "R_Knee", "R_Ankle", "R_Toe",
    "Torso", "Spine", "Chest", "Neck", "Head",
    "L_Thorax", "L_Shoulder", "L_Elbow", "L_Wrist",
    "L_Index1", "L_Index2", "L_Index3", "L_Middle1", "L_Middle2", "L_Middle3",
    "L_Pinky1", "L_Pinky2", "L_Pinky3", "L_Ring1", "L_Ring2", "L_Ring3",
    "L_Thumb1", "L_Thumb2", "L_Thumb3",
    "R_Thorax", "R_Shoulder", "R_Elbow", "R_Wrist",
    "R_Index1", "R_Index2", "R_Index3", "R_Middle1", "R_Middle2", "R_Middle3",
    "R_Pinky1", "R_Pinky2", "R_Pinky3", "R_Ring1", "R_Ring2", "R_Ring3",
    "R_Thumb1", "R_Thumb2", "R_Thumb3",
]

MJGEOM_SPHERE = 2
MJGEOM_CAPSULE = 3
MJGEOM_ELLIPSOID = 4
MJGEOM_CYLINDER = 5
MJGEOM_BOX = 6
MJGEOM_MESH = 7


class _CompatUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if module.startswith("numpy._core"):
            module = "numpy.core" + module[len("numpy._core"):]
        return super().find_class(module, name)


def load_pkl(path: Path) -> dict:
    with path.open("rb") as f:
        return _CompatUnpickler(f).load()


def srgb_to_linear(c: float) -> float:
    c = max(0.0, min(1.0, float(c)))
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def make_pbr_mat(cache: dict, rgba, role: str):
    r, g, b, a = [round(float(x), 3) for x in rgba]
    key = (role, r, g, b, a)
    if key in cache:
        return cache[key]
    mat = bpy.data.materials.new(name=f"M_{role}_{len(cache):02d}")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b), a)
    if role == "smplx":
        bsdf.inputs["Metallic"].default_value = 0.08
        bsdf.inputs["Roughness"].default_value = 0.42
    elif role == "robot":
        luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
        is_green = (g > 0.75 and r < 0.35 and b < 0.35)
        if is_green:
            bsdf.inputs["Metallic"].default_value = 0.0
            bsdf.inputs["Roughness"].default_value = 0.55
        elif luma < 0.35:
            bsdf.inputs["Metallic"].default_value = 0.42
            bsdf.inputs["Roughness"].default_value = 0.38
        elif luma > 0.82:
            bsdf.inputs["Metallic"].default_value = 0.05
            bsdf.inputs["Roughness"].default_value = 0.34
        else:
            bsdf.inputs["Metallic"].default_value = 0.22
            bsdf.inputs["Roughness"].default_value = 0.34
    elif role == "object":
        bsdf.inputs["Metallic"].default_value = 0.06
        bsdf.inputs["Roughness"].default_value = 0.40
    else:
        bsdf.inputs["Metallic"].default_value = 0.0
        bsdf.inputs["Roughness"].default_value = 0.60
    if a < 0.99:
        bsdf.inputs["Alpha"].default_value = a
        mat.blend_method = "BLEND"
    cache[key] = mat
    return mat


def decimate_object(obj, target_ratio: float, min_faces: int = 1200):
    mesh = obj.data
    n_faces = len(mesh.polygons)
    if n_faces <= min_faces or target_ratio >= 0.99:
        return

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    non_manifold = sum(1 for e in bm.edges if len(e.link_faces) != 2)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    n_faces = len(mesh.polygons)
    if n_faces <= min_faces:
        return
    if non_manifold > max(20, int(0.01 * n_faces)):
        return

    ratio = max(min_faces / n_faces, target_ratio)
    if ratio >= 0.95:
        return
    mod = obj.modifiers.new(name="Decimate", type="DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = ratio
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=mod.name)
    obj.select_set(False)


def build_mj_mesh(name: str, gtype: int, size, mesh_data, smooth: bool = True):
    mesh = bpy.data.meshes.new(name)
    if gtype == MJGEOM_MESH and mesh_data is not None:
        verts, faces = mesh_data
        mesh.from_pydata(verts.tolist(), [], faces.tolist())
        mesh.update()
        if smooth and len(mesh.polygons) > 0:
            mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
            if hasattr(mesh, "use_auto_smooth"):
                mesh.use_auto_smooth = True
                mesh.auto_smooth_angle = math.radians(38.0)
        return mesh

    bm = bmesh.new()
    if gtype == MJGEOM_BOX:
        hx, hy, hz = float(size[0]), float(size[1]), float(size[2])
        bmesh.ops.create_cube(bm, size=2.0)
        bmesh.ops.scale(bm, vec=(hx, hy, hz), verts=bm.verts)
    elif gtype == MJGEOM_CYLINDER:
        r, hh = float(size[0]), float(size[1])
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=24, radius1=r, radius2=r, depth=2.0 * hh)
    elif gtype == MJGEOM_SPHERE:
        r = float(size[0])
        bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=14, radius=r)
    elif gtype == MJGEOM_ELLIPSOID:
        rx, ry, rz = float(size[0]), float(size[1]), float(size[2])
        bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=14, radius=1.0)
        bmesh.ops.scale(bm, vec=(rx, ry, rz), verts=bm.verts)
    elif gtype == MJGEOM_CAPSULE:
        r, hl = float(size[0]), float(size[1])
        bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=r)
        for v in bm.verts:
            if v.co.z > 0.0:
                v.co.z += hl
            elif v.co.z < 0.0:
                v.co.z -= hl
    else:
        bmesh.ops.create_cube(bm, size=0.05)

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    if gtype in (MJGEOM_CYLINDER, MJGEOM_SPHERE, MJGEOM_ELLIPSOID, MJGEOM_CAPSULE):
        mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
    return mesh


def import_obj_clean(path: Path, name: str, mat):
    bpy.ops.object.select_all(action="DESELECT")
    if path.suffix.lower() == ".obj":
        bpy.ops.wm.obj_import(filepath=str(path), forward_axis="Y", up_axis="Z")
    elif path.suffix.lower() == ".stl":
        bpy.ops.wm.stl_import(filepath=str(path), forward_axis="Y", up_axis="Z")
    else:
        raise RuntimeError(f"Unsupported mesh: {path}")
    imported = [o for o in bpy.context.selected_objects if o.type == "MESH"]
    obj = imported[0]
    if len(imported) > 1:
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.join()
    obj.name = name
    obj.data.name = name
    obj.location = (0.0, 0.0, 0.0)
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    obj.scale = (1.0, 1.0, 1.0)
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return obj


def export_glb(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format="GLB",
        export_yup=True,
        export_apply=True,
        export_normals=True,
        export_materials="EXPORT",
        export_animations=False,
    )
    kb = path.stat().st_size / 1024
    print(f"[GLB] {path.name} ({kb:.1f} KB)")


# ---------------------------------------------------------------- Z-up -> Y-up math

def zup_pos_to_yup(pos: np.ndarray) -> np.ndarray:
    out = np.empty_like(pos, dtype=np.float32)
    out[..., 0] = pos[..., 0]
    out[..., 1] = pos[..., 2]
    out[..., 2] = -pos[..., 1]
    return out


def zup_quat_wxyz_to_yup_xyzw(q_wxyz: np.ndarray) -> np.ndarray:
    q = np.asarray(q_wxyz, dtype=np.float64)
    n = np.linalg.norm(q, axis=-1, keepdims=True)
    n[n < 1e-12] = 1.0
    q = q / n
    out = np.empty_like(q, dtype=np.float32)
    out[..., 0] = q[..., 1]
    out[..., 1] = q[..., 3]
    out[..., 2] = -q[..., 2]
    out[..., 3] = q[..., 0]
    return out


def zup_quat_xyzw_to_yup_xyzw(q_xyzw: np.ndarray) -> np.ndarray:
    q = np.asarray(q_xyzw, dtype=np.float64)
    n = np.linalg.norm(q, axis=-1, keepdims=True)
    n[n < 1e-12] = 1.0
    q = q / n
    out = np.empty_like(q, dtype=np.float32)
    out[..., 0] = q[..., 0]
    out[..., 1] = q[..., 2]
    out[..., 2] = -q[..., 1]
    out[..., 3] = q[..., 3]
    return out


def write_motion_bin_gz(path: Path, fps: float, pos_yup: np.ndarray, quat_yup_xyzw: np.ndarray,
                        root_focus: np.ndarray, hand_focus: np.ndarray):
    n_frames, n_nodes, _ = pos_yup.shape
    q = quat_yup_xyzw.astype(np.float32).copy()
    for t in range(1, n_frames):
        dot = np.sum(q[t] * q[t - 1], axis=-1, keepdims=True)
        q[t] = np.where(dot < 0.0, -q[t], q[t])
    q_i16 = np.clip(np.round(q * 32767.0), -32767, 32767).astype("<i2")
    p_f32 = np.ascontiguousarray(pos_yup, dtype="<f4")
    rf_f32 = np.ascontiguousarray(root_focus, dtype="<f4")
    hf_f32 = np.ascontiguousarray(hand_focus, dtype="<f4")

    header = struct.pack("<IIIf", 0x314D544D, n_frames, n_nodes, float(fps))
    payload = header + p_f32.tobytes() + q_i16.tobytes() + rf_f32.tobytes() + hf_f32.tobytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(payload, compresslevel=9, mtime=0))
    kb = path.stat().st_size / 1024
    print(f"[MOT] {path.name} ({n_frames}f x {n_nodes} nodes @ {fps:.1f}fps, {kb:.1f} KB gz)")


# ---------------------------------------------------------------- shared robots

def export_smplx_robot(out_dir: Path):
    reset_scene()
    mat_cache = {}
    mat = make_pbr_mat(mat_cache, (0.18, 0.34, 0.80, 1.0), "smplx")
    for idx, name in enumerate(SMPLX_52_NAMES):
        obj = import_obj_clean(SMPLX_MESH_DIR / f"{name}.obj", f"r{idx:02d}", mat)
        if obj.data.polygons:
            obj.data.polygons.foreach_set("use_smooth", [True] * len(obj.data.polygons))
    export_glb(out_dir / "robots" / "smplx.glb")


def export_mj_robot(robot_name: str, sample_pkl: Path, out_dir: Path):
    data = load_pkl(sample_pkl)
    reset_scene()
    mat_cache = {}
    meshes = data["meshes"]
    rob_geoms = [g for g in data["dynamic_geoms"] if g["is_robot"]]
    for idx, dg in enumerate(rob_geoms):
        mdata = meshes.get(dg["mesh_id"]) if dg["mesh_id"] >= 0 else None
        mesh = build_mj_mesh(f"r{idx:02d}", dg["gtype"], dg["size"], mdata, smooth=True)
        mesh.materials.append(make_pbr_mat(mat_cache, dg["rgba"], "robot"))
        obj = bpy.data.objects.new(f"r{idx:02d}", mesh)
        bpy.context.scene.collection.objects.link(obj)
        bname = dg["body_name"].lower()
        is_hand = any(k in bname for k in ("revo2", "thumb", "index", "middle", "ring", "pinky", "palm", "hand"))
        decimate_object(obj, 0.28 if is_hand else 0.18, min_faces=450)
    export_glb(out_dir / "robots" / f"{robot_name}.glb")
    return len(rob_geoms)


# ---------------------------------------------------------------- clip exporters

def build_basketball_hoop(hoop_pos, shooter_xy, mat_cache):
    """Build a regulation basketball hoop (pole, base, arm, white backboard, orange rim, net) in Z-up."""
    hx, hy, hz = [float(v) for v in hoop_pos]
    # Direction from shooter toward hoop (unit xy)
    dx, dy = hx - float(shooter_xy[0]), hy - float(shooter_xy[1])
    norm = math.hypot(dx, dy)
    ux, uy = (dx / norm, dy / norm) if norm > 1e-3 else (0.0, 1.0)
    yaw = math.atan2(uy, ux)  # +x local points away from shooter (behind backboard)
    q_yaw = Quaternion((0.0, 0.0, 1.0), yaw)

    pole_mat = make_pbr_mat(mat_cache, (0.20, 0.22, 0.25, 1.0), "static")
    board_mat = make_pbr_mat(mat_cache, (0.94, 0.95, 0.97, 1.0), "static")
    rim_mat = make_pbr_mat(mat_cache, (0.92, 0.36, 0.10, 1.0), "static")
    net_mat = make_pbr_mat(mat_cache, (0.95, 0.95, 0.95, 1.0), "static")

    def add_box(name, local_pos, half_size, mat):
        mesh = build_mj_mesh(name, MJGEOM_BOX, half_size, None, smooth=False)
        mesh.materials.append(mat)
        obj = bpy.data.objects.new(name, mesh)
        wpos = Vector((hx, hy, 0.0)) + (q_yaw @ Vector(local_pos))
        obj.location = wpos
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = q_yaw
        bpy.context.scene.collection.objects.link(obj)
        return list(wpos)

    pts = []
    rim_r = 0.2286
    # Rim (16 segments around (hx, hy, hz))
    n_seg = 16
    seg_len = 2.0 * math.pi * rim_r / n_seg
    for i in range(n_seg):
        ang = 2.0 * math.pi * i / n_seg
        rx = hx + rim_r * math.cos(ang)
        ry = hy + rim_r * math.sin(ang)
        mesh = build_mj_mesh(f"hoop_rim_{i:02d}", MJGEOM_BOX, (0.010, seg_len * 0.55, 0.010), None, smooth=False)
        mesh.materials.append(rim_mat)
        obj = bpy.data.objects.new(mesh.name, mesh)
        obj.location = (rx, ry, hz)
        obj.rotation_euler = (0.0, 0.0, ang)
        bpy.context.scene.collection.objects.link(obj)
    # Net cords (12 slender white vertical-ish tapering cords below rim)
    for i in range(12):
        ang = 2.0 * math.pi * i / 12
        r_top, r_bot, net_h = rim_r * 0.94, rim_r * 0.58, 0.42
        p_top = Vector((hx + r_top * math.cos(ang), hy + r_top * math.sin(ang), hz - 0.01))
        p_bot = Vector((hx + r_bot * math.cos(ang + 0.15), hy + r_bot * math.sin(ang + 0.15), hz - net_h))
        mid = 0.5 * (p_top + p_bot)
        diff = p_bot - p_top
        mesh = build_mj_mesh(f"hoop_net_{i:02d}", MJGEOM_CYLINDER, (0.0035, diff.length * 0.5), None, smooth=True)
        mesh.materials.append(net_mat)
        obj = bpy.data.objects.new(mesh.name, mesh)
        obj.location = mid
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = diff.normalized().to_track_quat("Z", "X")
        bpy.context.scene.collection.objects.link(obj)

    # Backboard behind rim (+0.38m along ux, uy), arm, vertical pole (+0.95m), base
    pts.append(add_box("hoop_board", (rim_r + 0.15, 0.0, hz + 0.35), (0.025, 0.72, 0.48), board_mat))
    pts.append(add_box("hoop_bracket", (rim_r + 0.075, 0.0, hz), (0.075, 0.04, 0.015), rim_mat))
    pts.append(add_box("hoop_arm", (rim_r + 0.48, 0.0, hz + 0.35), (0.33, 0.045, 0.045), pole_mat))
    pts.append(add_box("hoop_pole", (rim_r + 0.78, 0.0, (hz + 0.35) * 0.5), (0.055, 0.055, (hz + 0.35) * 0.5), pole_mat))
    pts.append(add_box("hoop_base", (rim_r + 0.78, 0.0, 0.06), (0.38, 0.38, 0.06), pole_mat))
    return pts


def export_pulse_clip(clip_id: str, pkl_path: Path, out_dir: Path, frame_step: int = 2,
                      hand_mode: str = "R_Wrist") -> dict:
    m = load_pkl(pkl_path)
    body_pos = np.asarray(m["rigid_body_pos"], dtype=np.float32)[::frame_step]
    body_rot = np.asarray(m["rigid_body_rot"], dtype=np.float32)[::frame_step]
    fps = float(m.get("fps", 30.0)) / frame_step
    n_frames = len(body_pos)

    has_obj = "object_pos" in m and "object_rot" in m
    obj_pos = np.asarray(m["object_pos"], dtype=np.float32).reshape(-1, 3)[::frame_step][:n_frames] if has_obj else None
    obj_rot = np.asarray(m["object_rot"], dtype=np.float32).reshape(-1, 4)[::frame_step][:n_frames] if has_obj else None

    reset_scene()
    mat_cache = {}
    furn_mat = make_pbr_mat(mat_cache, (0.76, 0.66, 0.54, 1.0), "static")
    terr_mat = make_pbr_mat(mat_cache, (0.78, 0.80, 0.84, 1.0), "static")
    obj_mat = make_pbr_mat(mat_cache, (0.86, 0.42, 0.34, 1.0), "object")

    static_pts = []
    for i, box in enumerate(m.get("scene_boxes") or []):
        hx, hy = float(box["half"][0]), float(box["half"][1])
        z0, z1 = float(box["z0"]), float(box["z1"])
        hz = 0.5 * (z1 - z0)
        mesh = build_mj_mesh(f"s_box_{i:02d}", MJGEOM_BOX, (hx, hy, hz), None, smooth=False)
        mesh.materials.append(furn_mat)
        obj = bpy.data.objects.new(mesh.name, mesh)
        obj.location = (float(box["center"][0]), float(box["center"][1]), 0.5 * (z0 + z1))
        obj.rotation_euler = (0.0, 0.0, float(box["yaw"]))
        bpy.context.scene.collection.objects.link(obj)
        static_pts.append([box["center"][0], box["center"][1], z1])

    tm = m.get("terrain_mesh")
    if isinstance(tm, dict) and "vertices" in tm and "triangles" in tm:
        mesh = bpy.data.meshes.new("s_terrain")
        mesh.from_pydata(tm["vertices"].tolist(), [], tm["triangles"].tolist())
        mesh.update()
        mesh.materials.append(terr_mat)
        obj = bpy.data.objects.new("s_terrain", mesh)
        bpy.context.scene.collection.objects.link(obj)
        static_pts.extend(tm["vertices"].tolist()[::max(1, len(tm["vertices"]) // 16)])

    for i, sm in enumerate(m.get("static_meshes") or []):
        mp = Path(sm["mesh"])
        if not mp.exists():
            continue
        mat = terr_mat if sm.get("kind") == "terrain" else furn_mat
        obj = import_obj_clean(mp, f"s_mesh_{i:02d}", mat)
        decimate_object(obj, 0.35, min_faces=400)
        obj.location = tuple(float(v) for v in sm.get("pos", (0.0, 0.0, 0.0)))
        qx, qy, qz, qw = [float(v) for v in sm.get("rot_xyzw", (0.0, 0.0, 0.0, 1.0))]
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = (qw, qx, qy, qz)
        static_pts.append(list(obj.location))

    if m.get("hoop_pos") is not None:
        shooter_xy = body_pos[0, 0, :2]
        static_pts.extend(build_basketball_hoop(m["hoop_pos"], shooter_xy, mat_cache))

    n_obj = 0
    if has_obj and m.get("object_mesh"):
        mp = Path(m["object_mesh"])
        if mp.exists():
            omat = make_pbr_mat(mat_cache, (0.86, 0.38, 0.12, 1.0), "object") if "basketball" in mp.stem.lower() else obj_mat
            obj = import_obj_clean(mp, "o00", omat)
            decimate_object(obj, 0.30, min_faces=300)
            n_obj = 1

    has_props = len(bpy.data.objects) > 0
    if has_props:
        export_glb(out_dir / "clips" / f"{clip_id}_props.glb")

    p_all = [zup_pos_to_yup(body_pos)]
    q_all = [zup_quat_xyzw_to_yup_xyzw(body_rot)]
    if n_obj == 1:
        p_all.append(zup_pos_to_yup(obj_pos)[:, None, :])
        q_all.append(zup_quat_xyzw_to_yup_xyzw(obj_rot)[:, None, :])
    pos_yup = np.concatenate(p_all, axis=1)
    quat_yup = np.concatenate(q_all, axis=1)

    pelvis_yup = zup_pos_to_yup(body_pos[:, 0])
    pelvis_yup[:, 1] = np.maximum(0.88, pelvis_yup[:, 1])

    # Auto-pick whichever wrist gets closer to the object (e.g. stairs_carry uses left hand!)
    l_idx = SMPLX_52_NAMES.index("L_Wrist")
    r_idx = SMPLX_52_NAMES.index("R_Wrist")
    if has_obj:
        dl = np.linalg.norm(obj_pos - body_pos[:, l_idx], axis=-1).min()
        dr = np.linalg.norm(obj_pos - body_pos[:, r_idx], axis=-1).min()
        w_idx = l_idx if dl < dr else r_idx
        h_zup = body_pos[:, w_idx].copy()
        d = np.linalg.norm(obj_pos - h_zup, axis=-1)
        h_zup = np.where((d < 0.35)[:, None], 0.5 * (h_zup + obj_pos), h_zup)
        hand_yup = zup_pos_to_yup(h_zup)
    else:
        hand_yup = zup_pos_to_yup(body_pos[:, SMPLX_52_NAMES.index(hand_mode)])

    write_motion_bin_gz(out_dir / "clips" / f"{clip_id}_motion.bin.gz", fps, pos_yup, quat_yup, pelvis_yup, hand_yup)

    all_pts = [zup_pos_to_yup(body_pos.reshape(-1, 3))]
    if has_obj:
        all_pts.append(zup_pos_to_yup(obj_pos))
    if static_pts:
        all_pts.append(zup_pos_to_yup(np.asarray(static_pts, dtype=np.float32)))
    pts = np.concatenate(all_pts, axis=0)
    bmin, bmax = pts.min(0).tolist(), pts.max(0).tolist()
    bmin[1] = min(0.0, bmin[1])
    bmax[1] += 0.25

    return {
        "robot": "smplx",
        "fps": round(fps, 3),
        "frames": int(n_frames),
        "duration": round(n_frames / fps, 2),
        "n_robot": 52,
        "n_obj": n_obj,
        "has_props": has_props,
        "bounds": [bmin, bmax],
    }


def export_mj_clip(clip_id: str, pkl_path: Path, out_dir: Path) -> dict:
    data = load_pkl(pkl_path)
    robot_name = data["robot"]
    fps = float(data["fps"])
    n_frames = int(data["n_frames"])
    meshes = data["meshes"]

    rob_geoms = [g for g in data["dynamic_geoms"] if g["is_robot"]]
    obj_geoms = [g for g in data["dynamic_geoms"] if g["is_object"]]

    # Group multi-part object geoms by body_id so a rigid object with 54 parts uses only 1 animated node!
    obj_groups: list[list[dict]] = []
    bid_map: dict[int, int] = {}
    for og in obj_geoms:
        bid = int(og["body_id"])
        if bid not in bid_map:
            bid_map[bid] = len(obj_groups)
            obj_groups.append([])
        obj_groups[bid_map[bid]].append(og)

    reset_scene()
    mat_cache = {}
    static_pts = []
    for i, sg in enumerate(data["static_geoms"]):
        mdata = meshes.get(sg["mesh_id"]) if sg["mesh_id"] >= 0 else None
        smooth = (sg["gtype"] != MJGEOM_BOX)
        mesh = build_mj_mesh(f"s{i:03d}", sg["gtype"], sg["size"], mdata, smooth=smooth)
        mesh.materials.append(make_pbr_mat(mat_cache, sg["rgba"], "static"))
        obj = bpy.data.objects.new(mesh.name, mesh)
        obj.location = tuple(float(v) for v in sg["pos"])
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = tuple(float(v) for v in sg["quat_wxyz"])
        bpy.context.scene.collection.objects.link(obj)
        static_pts.append(sg["pos"])

    # Build one root node o{g:02d} per rigid object body; sub-parts become children with constant local transform!
    group_leaders = []
    for g_idx, grp in enumerate(obj_groups):
        lead = grp[0]
        group_leaders.append(lead)
        p0 = Vector([float(v) for v in lead["pos"][0]])
        q0 = Quaternion([float(v) for v in lead["quat_wxyz"][0]])
        q0_inv = q0.inverted()

        if len(grp) == 1:
            mdata = meshes.get(lead["mesh_id"]) if lead["mesh_id"] >= 0 else None
            mesh = build_mj_mesh(f"o{g_idx:02d}", lead["gtype"], lead["size"], mdata, smooth=True)
            mesh.materials.append(make_pbr_mat(mat_cache, lead["rgba"], "object"))
            obj = bpy.data.objects.new(f"o{g_idx:02d}", mesh)
            bpy.context.scene.collection.objects.link(obj)
            if lead["gtype"] == MJGEOM_MESH:
                decimate_object(obj, 0.25, min_faces=400)
        else:
            root_empty = bpy.data.objects.new(f"o{g_idx:02d}", None)
            bpy.context.scene.collection.objects.link(root_empty)
            for k, og in enumerate(grp):
                mdata = meshes.get(og["mesh_id"]) if og["mesh_id"] >= 0 else None
                mesh = build_mj_mesh(f"o{g_idx:02d}_p{k:02d}", og["gtype"], og["size"], mdata, smooth=True)
                mesh.materials.append(make_pbr_mat(mat_cache, og["rgba"], "object"))
                part = bpy.data.objects.new(mesh.name, mesh)
                bpy.context.scene.collection.objects.link(part)
                if og["gtype"] == MJGEOM_MESH and len(grp) <= 6:
                    decimate_object(part, 0.30, min_faces=400)
                pk = Vector([float(v) for v in og["pos"][0]])
                qk = Quaternion([float(v) for v in og["quat_wxyz"][0]])
                part.parent = root_empty
                part.location = q0_inv @ (pk - p0)
                part.rotation_mode = "QUATERNION"
                part.rotation_quaternion = q0_inv @ qk

    has_props = len(bpy.data.objects) > 0
    if has_props:
        export_glb(out_dir / "clips" / f"{clip_id}_props.glb")

    all_dyn = rob_geoms + group_leaders
    pos_zup = np.stack([g["pos"] for g in all_dyn], axis=1)
    quat_wxyz = np.stack([g["quat_wxyz"] for g in all_dyn], axis=1)
    pos_yup = zup_pos_to_yup(pos_zup)
    quat_yup = zup_quat_wxyz_to_yup_xyzw(quat_wxyz)

    rp = np.asarray(data["root_pos"], dtype=np.float32)
    root_yup = zup_pos_to_yup(rp)
    root_yup[:, 1] = np.maximum(0.85 if robot_name == "h2" else 0.68, root_yup[:, 1])

    wrist_idx = next((i for i, g in enumerate(rob_geoms) if "right_wrist_yaw" in g["body_name"] or "right_revo2_hand" in g["body_name"] or "right_palm" in g["body_name"]), 0)
    h_zup = rob_geoms[wrist_idx]["pos"].copy()
    if data.get("obj_pos") is not None:
        op = np.asarray(data["obj_pos"], dtype=np.float32)
        d = np.linalg.norm(op - h_zup, axis=-1)
        h_zup = np.where((d < 0.6)[:, None], 0.5 * (h_zup + op), h_zup)
    hand_yup = zup_pos_to_yup(h_zup)

    write_motion_bin_gz(out_dir / "clips" / f"{clip_id}_motion.bin.gz", fps, pos_yup, quat_yup, root_yup, hand_yup)

    all_pts = [zup_pos_to_yup(rp)]
    h_top = 1.05 if robot_name == "h2" else 0.75
    all_pts.append(zup_pos_to_yup(rp + np.array([0.0, 0.0, h_top], dtype=np.float32)))
    if data.get("obj_pos") is not None:
        all_pts.append(zup_pos_to_yup(np.asarray(data["obj_pos"], dtype=np.float32)))
    if static_pts:
        all_pts.append(zup_pos_to_yup(np.asarray(static_pts, dtype=np.float32)))
    pts = np.concatenate(all_pts, axis=0)
    bmin, bmax = pts.min(0).tolist(), pts.max(0).tolist()
    bmin[1] = min(0.0, bmin[1])
    bmax[1] += 0.35

    return {
        "robot": robot_name,
        "fps": round(fps, 3),
        "frames": int(n_frames),
        "duration": round(n_frames / fps, 2),
        "n_robot": len(rob_geoms),
        "n_obj": len(group_leaders),
        "has_props": has_props,
        "bounds": [bmin, bmax],
    }


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--skip-robots", action="store_true", help="Keep existing shared robot GLBs")
    ap.add_argument("--only", default=None, help="Comma-separated clip IDs to re-export (merges into existing manifest)")
    args = ap.parse_args(argv)
    out_dir = args.out.resolve()
    only_ids = set(x.strip() for x in args.only.split(",") if x.strip()) if args.only else None

    pulse_dir = BLENDER_REPO / "data" / "pulse_all"
    mj_dir = BLENDER_REPO / "data" / "mujoco_all"

    if not args.skip_robots:
        print("=== Exporting shared robot GLBs ===")
        export_smplx_robot(out_dir)
        export_mj_robot("g1", mj_dir / "01_pickplace_g1.pkl", out_dir)
        export_mj_robot("h2", mj_dir / "01_pickplace_h2.pkl", out_dir)

    print("=== Exporting all 48 clips ===")
    specs = [
        # ---- SMPL-X humanoid (19 clips: 17 tasks + 2 in-hand)
        ("human", "hum_01_pickplace",       "Camera, table to table",        "Pick and place",        "overview", -50,  "pulse", pulse_dir / "01_pickplace.pkl", dict(frame_step=2)),
        ("human", "hum_19_inhand_flip270",  "Cube 270° palm flip",           "In-hand manipulation",  "hand",      45,  "pulse", pulse_dir / "19_inhand_flip270.pkl", dict(frame_step=2)),
        ("human", "hum_20_inhand_translate","Bar finger-gaiting",            "In-hand manipulation",  "hand",      45,  "pulse", pulse_dir / "20_inhand_translate.pkl", dict(frame_step=2)),
        ("human", "hum_02_handover",        "Mug, hand to hand",             "Handover",              "follow",   -50,  "pulse", pulse_dir / "02_handover.pkl", dict(frame_step=2)),
        ("human", "hum_03_chair_overhead",  "Wood chair overhead carry",     "Bimanual carry",        "follow",   -45,  "pulse", pulse_dir / "03_chair_overhead_carry.pkl", dict(frame_step=2)),
        ("human", "hum_04_large_object",    "Trash can two-hand carry",      "Large object carry",    "follow",   -45,  "pulse", pulse_dir / "04_large_object_carry.pkl", dict(frame_step=2)),
        ("human", "hum_05_pole_carry",      "Floor lamp carry",              "Pole carry",            "follow",   -50,  "pulse", pulse_dir / "05_pole_carry.pkl", dict(frame_step=2)),
        ("human", "hum_06_box_push",        "Plastic box push on table",     "Push",                  "follow",   -55,  "pulse", pulse_dir / "06_box_push.pkl", dict(frame_step=2)),
        ("human", "hum_07_stairs_walk",     "Up the stairs",                 "Terrain",               "follow",   -50,  "pulse", pulse_dir / "07_stairs_walk.pkl", dict(frame_step=2)),
        ("human", "hum_08_stairs_carry",    "Water bottle over stairs",      "Carry on terrain",      "follow",   -50,  "pulse", pulse_dir / "08_stairs_carry.pkl", dict(frame_step=2)),
        ("human", "hum_09_balance_beam",    "Walk across balance beam",      "Terrain",               "follow",   -55,  "pulse", pulse_dir / "09_balance_beam.pkl", dict(frame_step=2)),
        ("human", "hum_10_chair_sit",       "Pull out chair and sit",        "Sit",                   "follow",   -50,  "pulse", pulse_dir / "10_chair_sit.pkl", dict(frame_step=2)),
        ("human", "hum_11_chair_spin",      "Spin wooden chair",             "Spin",                  "follow",   -45,  "pulse", pulse_dir / "11_chair_spin.pkl", dict(frame_step=2)),
        ("human", "hum_12_soccer_kick",     "Kick soccer ball",              "Football",              "follow",   -50,  "pulse", pulse_dir / "12_soccer_kick.pkl", dict(frame_step=2)),
        ("human", "hum_13_mop",             "Floor mopping",                 "Tool use",              "follow",   -50,  "pulse", pulse_dir / "13_mop.pkl", dict(frame_step=2)),
        ("human", "hum_14_yogamat",         "Yoga mat on shoulder",          "Whole-body carry",      "follow",   -45,  "pulse", pulse_dir / "14_yogamat.pkl", dict(frame_step=2)),
        ("human", "hum_15_throw",           "Tennis ball overhand throw",    "Throw",                 "follow",   -55,  "pulse", pulse_dir / "15_throw.pkl", dict(frame_step=2)),
        ("human", "hum_16_basketball",      "Basketball jump shot",          "Basketball",            "overview", -30,  "pulse", pulse_dir / "16_basketball.pkl", dict(frame_step=2)),
        ("human", "hum_17_undertable",      "Pick ball under table",         "Kneel and pick",        "follow",   -50,  "pulse", pulse_dir / "17_undertable_pick.pkl", dict(frame_step=2)),

        # ---- G1 + Revo2 (17 clips)
        ("g1", "g1_01_pickplace",       "Apple into a hutch",            "Pick and place",        "follow",  -125,  "mj", mj_dir / "01_pickplace_g1.pkl", {}),
        ("g1", "g1_02_handover",        "Bowl, hand to hand",            "Handover",              "follow",   -50,  "mj", mj_dir / "02_handover_g1.pkl", {}),
        ("g1", "g1_03_chair_overhead",  "Wood chair overhead carry",     "Bimanual carry",        "follow",   -45,  "mj", mj_dir / "03_chair_overhead_carry_g1.pkl", {}),
        ("g1", "g1_04_large_object",    "Trash can two-hand carry",      "Large object carry",    "follow",   -45,  "mj", mj_dir / "04_large_object_carry_g1.pkl", {}),
        ("g1", "g1_05_pole_carry",      "Floor lamp carry",              "Pole carry",            "follow",   -50,  "mj", mj_dir / "05_pole_carry_g1.pkl", {}),
        ("g1", "g1_06_box_push",        "Plastic box push on table",     "Push",                  "follow",   -55,  "mj", mj_dir / "06_box_push_g1.pkl", {}),
        ("g1", "g1_07_stairs_walk",     "Up the stairs",                 "Terrain",               "follow",   -50,  "mj", mj_dir / "07_stairs_walk_g1.pkl", {}),
        ("g1", "g1_08_stairs_carry",    "Water bottle over stairs",      "Carry on terrain",      "follow",   -50,  "mj", mj_dir / "08_stairs_carry_g1.pkl", {}),
        ("g1", "g1_10_chair_sit",       "Pull out chair and sit",        "Sit",                   "follow",   -50,  "mj", mj_dir / "10_chair_sit_g1.pkl", {}),
        ("g1", "g1_11_chair_spin",      "Spin wooden chair",             "Spin",                  "follow",   -45,  "mj", mj_dir / "11_chair_spin_g1.pkl", {}),
        ("g1", "g1_12_soccer_kick",     "Kick into a goal",              "Football",              "follow",  -125,  "mj", mj_dir / "12_soccer_kick_g1.pkl", {}),
        ("g1", "g1_13_mop",             "Floor mopping",                 "Tool use",              "follow",   -50,  "mj", mj_dir / "13_mop_g1.pkl", {}),
        ("g1", "g1_14_yogamat",         "Yoga mat on shoulder",          "Whole-body carry",      "follow",   -45,  "mj", mj_dir / "14_yogamat_g1.pkl", {}),
        ("g1", "g1_15_throw",           "Tennis ball overhand throw",    "Throw",                 "overview", -55,  "mj", mj_dir / "15_throw_g1.pkl", {}),
        ("g1", "g1_16_basketball",      "Shot at a hoop",                "Basketball",            "overview", -55,  "mj", mj_dir / "16_basketball_g1.pkl", {}),
        ("g1", "g1_17_undertable",      "Pick ball under table",         "Kneel and pick",        "follow",   -50,  "mj", mj_dir / "17_undertable_pick_g1.pkl", {}),
        ("g1", "g1_18_parkour",         "Obstacle vault course",         "Parkour",               "follow",   -55,  "mj", mj_dir / "18_parkour_g1.pkl", {}),

        # ---- H2 + Sharpa Wave (12 clips)
        ("h2", "h2_01_pickplace",       "Pepper grinder into a hutch",   "Pick and place",        "follow",  -125,  "mj", mj_dir / "01_pickplace_h2.pkl", {}),
        ("h2", "h2_03_chair_overhead",  "Wood chair overhead carry",     "Bimanual carry",        "follow",   -45,  "mj", mj_dir / "03_chair_overhead_carry_h2.pkl", {}),
        ("h2", "h2_04_large_object",    "Trash can two-hand carry",      "Large object carry",    "follow",   -45,  "mj", mj_dir / "04_large_object_carry_h2.pkl", {}),
        ("h2", "h2_05_pole_carry",      "Floor lamp carry",              "Pole carry",            "follow",   -50,  "mj", mj_dir / "05_pole_carry_h2.pkl", {}),
        ("h2", "h2_06_box_push",        "Crate push on table",           "Push",                  "follow",   -55,  "mj", mj_dir / "06_box_push_h2.pkl", {}),
        ("h2", "h2_07_stairs_walk",     "Up the stairs",                 "Terrain",               "follow",   -50,  "mj", mj_dir / "07_stairs_walk_h2.pkl", {}),
        ("h2", "h2_08_stairs_carry",    "Water bottle over stairs",      "Carry on terrain",      "follow",   -50,  "mj", mj_dir / "08_stairs_carry_h2.pkl", {}),
        ("h2", "h2_10_chair_sit",       "Pull out chair and sit",        "Sit",                   "follow",   -50,  "mj", mj_dir / "10_chair_sit_h2.pkl", {}),
        ("h2", "h2_11_chair_spin",      "Spin wooden chair",             "Spin",                  "follow",   -45,  "mj", mj_dir / "11_chair_spin_h2.pkl", {}),
        ("h2", "h2_12_soccer_kick",     "Kick into a goal",              "Football",              "follow",  -125,  "mj", mj_dir / "12_soccer_kick_h2.pkl", {}),
        ("h2", "h2_14_yogamat",         "Yoga mat on shoulder",          "Whole-body carry",      "follow",   -45,  "mj", mj_dir / "14_yogamat_h2.pkl", {}),
        ("h2", "h2_15_throw",           "Tennis ball overhand throw",    "Throw",                 "overview", -55,  "mj", mj_dir / "15_throw_h2.pkl", {}),
    ]

    tabs = {
        "human": {
            "label": "SMPL-X humanoid",
            "note": "Interactive 3D viewer of all 19 synthesized SMPL-X demonstrations (17 whole-body loco-manipulation tasks + 2 in-hand dexterous manipulation skills). Drag to orbit, click + scroll to zoom, or switch to Hand Close-up.",
            "clips": [],
        },
        "g1": {
            "label": "G1 + Revo2",
            "note": "Beyond the paper: interactive 3D viewer of all 17 synthesized demonstrations for the Unitree G1 with Revo2 dexterous hands.",
            "clips": [],
        },
        "h2": {
            "label": "H2 + Sharpa Wave",
            "note": "Beyond the paper: interactive 3D viewer of all 12 synthesized demonstrations for the Unitree H2 with Sharpa Wave dexterous hands.",
            "clips": [],
        },
    }

    mf_path = out_dir / "manifest.json"
    existing_by_id = {}
    if only_ids and mf_path.exists():
        old_mf = json.loads(mf_path.read_text())
        for t in old_mf.get("tabs", {}).values():
            for c in t.get("clips", []):
                existing_by_id[c["id"]] = c

    for tab, cid, title, kind, cam, az, ctype, pkl_p, extra in specs:
        if only_ids and cid not in only_ids and cid in existing_by_id:
            tabs[tab]["clips"].append(existing_by_id[cid])
            continue
        if not pkl_p.exists():
            raise SystemExit(f"Missing pkl: {pkl_p}")
        if ctype == "pulse":
            # the stick figure's clips with the foot skate cleaned up (instantTrack-upstream tools/fix_stick_feet.py,
            # 2026-11-26) where there is one; the rest as converted from PULSE
            fixed = FOOTFIX_DIR / pkl_p.name
            if fixed.exists():
                print(f"[FOOTFIX] {cid}: {fixed}")
                pkl_p = fixed
            meta = export_pulse_clip(cid, pkl_p, out_dir, **extra)
        else:
            meta = export_mj_clip(cid, pkl_p, out_dir)
        meta.update({
            "id": cid,
            "title": title,
            "kind": kind,
            "default_cam": cam,
            "azimuth": az,
            "thumb": f"media/viewer/thumbs/{cid}.jpg",
        })
        tabs[tab]["clips"].append(meta)

    manifest = {
        "robots": {
            "smplx": "media/viewer/robots/smplx.glb",
            "g1": "media/viewer/robots/g1.glb",
            "h2": "media/viewer/robots/h2.glb",
        },
        "tabs": tabs,
    }
    mf_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"[OK] Wrote {mf_path} ({sum(len(t['clips']) for t in tabs.values())} clips)")


if __name__ == "__main__":
    main()
