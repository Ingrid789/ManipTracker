"""Export the 3D scene of the first screen (hero.js) from the ManipSynth washer-door demonstration.

Reads   <src>/g1_open_door/{scene_g1.xml, motion.npz, grasps.json}, <src>/placement.json and the room's Gaussian splat.
Writes  media/hero/scene.glb   the G1 + Revo2 robot and the washer: one node per MuJoCo body, decimated meshes,
                               the motion baked as world-space translation and rotation tracks (clips "robot", "door")
        media/hero/room.spz    the part of the room's splat that the scene needs: the machine row with its counter and
                               shelf, the wall it is set into, the floor in front of it. The ceiling, the other three
                               walls, the far side of the room and the splats of the replaced machine are left out.
        media/hero/scene.json  phases, wrist and root paths, the grasp anchors on the door

Everything is put into one frame for three.js (metres, y up): x along the machine row (to the right when facing the
machines), y up from the floor, z from the machines into the room.

Needs mujoco, trimesh, fast_simplification, numpy:
    /home/lenovo/miniconda3/envs/robosim/bin/python tools/export_hero.py [--only glb|splat|meta]
"""
import argparse
import gzip
import json
import struct
from pathlib import Path

import numpy as np

PAGE = Path(__file__).resolve().parents[1]
SRC = Path("/home/lenovo/runyi/ManipSynth/output/laundry_washer_swap")
SPLAT = Path("/home/lenovo/runyi/ManipSynth/asset/gs_scenes/0020_hotel_laundry/aligned.ply")
OUT = PAGE / "media/hero"
FLOOR_Z = -0.025           # the floor drawn by the splats in front of the machines (common.py)
STEP = 2                   # keep every STEP-th frame of the 50 fps motion
GLASS = ("door_glass", "Material_28", "material__225")

P = json.load(open(SRC / "placement.json"))
O, U, N = (np.array(P[k]) for k in ("row_origin", "row_u", "row_n"))
M = np.stack([U, [0, 0, 1.0], N])                      # world (z up) -> page (y up); a proper rotation
assert abs(np.linalg.det(M) - 1) < 1e-3


def to_page(p):
    return (np.asarray(p) - O) @ M.T - np.array([0, FLOOR_Z, 0])


# --------------------------------------------------------------------------------------------- the splat
# regions in row coordinates: u along the row, n into the room, z up
ROW = dict(u=(-2.3, 3.66), n=(-0.12, 1.42), z=(0.0, 2.62))     # machines, counter, shelf, and the wall they are set into
FLOOR = dict(u=(-2.3, 3.5), n=(0.55, 3.25), z=(-0.2, 0.07), fade=0.7)


def read_ply(path):
    with open(path, "rb") as f:
        props, n = [], 0
        while True:
            line = f.readline().strip()
            if line.startswith(b"element vertex"):
                n = int(line.split()[-1])
            elif line.startswith(b"property"):
                props.append(line.split()[-1].decode())
            elif line == b"end_header":
                break
        a = np.fromfile(f, dtype=np.float32, count=n * len(props)).reshape(n, len(props))
    return {p: i for i, p in enumerate(props)}, a


def inside(c, box):
    return np.logical_and.reduce([(c[k] > box[k][0]) & (c[k] < box[k][1]) for k in "unz"])


def quat_mul(a, b):                                     # wxyz
    w1, x1, y1, z1 = a.T; w2, x2, y2, z2 = b.T
    return np.stack([w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                     w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2], 1)


def mat2quat(R):
    import mujoco as mj
    q = np.zeros(4); mj.mju_mat2Quat(q, np.ascontiguousarray(R, dtype=float).reshape(-1))
    return q


def export_splat():
    c, a = read_ply(SPLAT)
    xyz = a[:, [c["x"], c["y"], c["z"]]].astype(np.float64)
    q = xyz - O
    co = dict(u=q @ U, n=q @ N, z=xyz[:, 2])
    alpha = 1 / (1 + np.exp(-a[:, c["opacity"]].astype(np.float64)))
    scale = a[:, [c["scale_0"], c["scale_1"], c["scale_2"]]]

    # the machine that the MuJoCo washer replaces (render_door_open.old_machine_mask)
    (u0, u1), (z0, z1), (n0, _) = P["bay_u"], P["bay_z"], P["bay_n"]
    old = ((co["u"] > u0) & (co["u"] < u1) & (co["z"] > z0 - 0.005) & (co["z"] < z1) & (co["n"] > n0) & (co["n"] < 0.86)) | \
          ((co["u"] > -0.14) & (co["u"] < 0.33) & (co["n"] > 0.735) & (co["n"] < 1.32) & (co["z"] > 0.17) & (co["z"] < 0.88))

    row = inside(co, ROW)
    floor = inside(co, FLOOR) & ~row
    # the floor patch fades out towards its border, so that it ends in the page's background and not in an edge
    f = FLOOR["fade"]
    du = np.minimum(co["u"] - FLOOR["u"][0], FLOOR["u"][1] - co["u"])
    dn = np.minimum(co["n"] - (FLOOR["n"][0] - 9), FLOOR["n"][1] - co["n"])     # no fade on the machines' side
    t = np.clip(np.minimum(du, dn) / f, 0, 1)
    fade = np.where(floor, t * t * (3 - 2 * t), 1.0)
    t = np.clip((co["u"] - ROW["u"][0]) / 0.8, 0, 1)                           # and so does the wall left of the machines
    alpha = alpha * fade * np.where(row, t * t * (3 - 2 * t), 1.0)
    keep = (row | floor) & ~old & (alpha > 0.04) & (np.exp(scale.max(1)) < 0.45)
    print(f"splats: row {int((row & keep).sum())}, floor {int((floor & keep).sum())}, "
          f"kept {int(keep.sum())} of {len(a)}")

    a, alpha = a[keep], alpha[keep]
    pos = to_page(a[:, [c["x"], c["y"], c["z"]]].astype(np.float64))
    rot = a[:, [c["rot_0"], c["rot_1"], c["rot_2"], c["rot_3"]]].astype(np.float64)
    rot /= np.linalg.norm(rot, axis=1, keepdims=True)
    rot = quat_mul(np.repeat(mat2quat(M)[None], len(rot), 0), rot)
    rot *= np.where(rot[:, :1] < 0, -1, 1)
    dc = a[:, [c["f_dc_0"], c["f_dc_1"], c["f_dc_2"]]]
    scale = a[:, [c["scale_0"], c["scale_1"], c["scale_2"]]]
    order = np.lexsort((pos[:, 0], pos[:, 2], pos[:, 1]))            # a spatial order compresses a little better
    pos, rot, dc, scale, alpha = pos[order], rot[order], dc[order], scale[order], alpha[order]

    # .spz version 2 (Niantic): header, then positions (24 bit fixed point), alphas, colours, scales, rotations
    n, bits = len(pos), 12
    fixed = np.round(pos * (1 << bits)).astype(np.int32)
    p3 = np.stack([(fixed >> s) & 0xFF for s in (0, 8, 16)], -1).astype(np.uint8).reshape(n, 9)
    u8 = lambda x: np.clip(np.round(x), 0, 255).astype(np.uint8)
    body = b"".join([
        struct.pack("<IIIBBBB", 0x5053474E, 2, n, 0, bits, 0, 0), p3.tobytes(), u8(alpha * 255).tobytes(),
        u8((dc * 0.15 + 0.5) * 255).tobytes(), u8((scale + 10) * 16).tobytes(), u8(rot[:, 1:] * 127.5 + 127.5).tobytes()])
    (OUT / "room.spz").write_bytes(gzip.compress(body, 9, mtime=0))
    print(f"room.spz {(OUT / 'room.spz').stat().st_size / 1e6:.2f} MB, {n} splats, bounds {pos.min(0).round(2)} {pos.max(0).round(2)}")


# --------------------------------------------------------------------------------------------- robot and washer
def srgb_to_linear(c):
    c = np.asarray(c, float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def ratio_for(body, mat):
    """Fraction of the triangles to keep. The right hand and the door are seen from close by."""
    if body.startswith("right_revo2"):
        return 0.34
    if body.startswith("left_revo2"):
        return 0.10
    if body == "washer_door":
        return 0.18 if "Material_28" in mat else 0.45
    if body == "washer_drum":
        return 0.14
    if body.startswith("washer"):
        return 0.20
    return 0.20


def load_model():
    import mujoco as mj
    m = mj.MjModel.from_xml_path(str(SRC / "g1_open_door/scene_g1.xml"))
    return mj, m, mj.MjData(m)


def body_meshes(mj, m):
    """{body id: {material key: (vertices, faces)}} in the body's frame, decimated."""
    import fast_simplification
    import trimesh
    out, mats, before, after = {}, {}, 0, 0
    for g in range(m.ngeom):
        if m.geom_group[g] not in (0, 2) or m.geom_contype[g] or m.geom_conaffinity[g]:
            continue
        b, t = int(m.geom_bodyid[g]), m.geom_type[g]
        body = m.body(b).name
        if m.geom_matid[g] >= 0:
            i = m.geom_matid[g]; key = m.material(i).name
            metal, rough = float(m.mat_metallic[i]), float(m.mat_roughness[i])
            rgba = m.mat_rgba[i].copy()
            if metal < 0:
                metal, rough = 0.0, 0.45
        else:
            rgba = m.geom_rgba[g].copy(); key = "rgba_%d_%d_%d" % tuple(np.round(rgba[:3] * 100))
            metal, rough = (0.0, 0.92) if body == "world" else (0.15, 0.5)
        mats[key] = dict(rgba=rgba, metal=metal, rough=max(rough, 0.06), glass=key.endswith(GLASS))
        if t == mj.mjtGeom.mjGEOM_MESH:
            i = m.geom_dataid[g]
            v = m.mesh_vert[m.mesh_vertadr[i]:m.mesh_vertadr[i] + m.mesh_vertnum[i]].astype(np.float64)
            f = m.mesh_face[m.mesh_faceadr[i]:m.mesh_faceadr[i] + m.mesh_facenum[i]]
            tm = trimesh.Trimesh(v, f, process=True)
            before += len(tm.faces)
            keep = ratio_for(body, key)
            if len(tm.faces) > 400:
                target = max(300, int(len(tm.faces) * keep))
                v2, f2 = fast_simplification.simplify(np.asarray(tm.vertices, np.float32), np.asarray(tm.faces), target_count=target, agg=5)
                tm = trimesh.Trimesh(v2, f2, process=True)
        elif t == mj.mjtGeom.mjGEOM_BOX:
            tm = trimesh.creation.box(extents=2 * m.geom_size[g])
        else:
            continue
        tm.update_faces(tm.nondegenerate_faces()); tm.remove_unreferenced_vertices()
        after += len(tm.faces)
        tm = trimesh.graph.smooth_shade(tm, angle=np.deg2rad(38))
        R = np.zeros(9); mj.mju_quat2Mat(R, m.geom_quat[g]); R = R.reshape(3, 3)
        v = np.asarray(tm.vertices) @ R.T + m.geom_pos[g]
        nrm = np.asarray(tm.vertex_normals) @ R.T
        slot = out.setdefault(b, {}).setdefault(key, [[], [], [], 0])
        slot[0].append(v); slot[1].append(nrm); slot[2].append(np.asarray(tm.faces) + slot[3]); slot[3] += len(v)
    print(f"triangles: {before} -> {after}")
    return {b: {k: (np.vstack(s[0]), np.vstack(s[1]), np.vstack(s[2])) for k, s in d.items()} for b, d in out.items()}, mats


class Glb:
    def __init__(self):
        self.bin, self.views, self.accessors = bytearray(), [], []

    def add(self, arr, ctype, kind, target=None, normalized=False, minmax=False):
        arr = np.ascontiguousarray(arr)
        while len(self.bin) % 4:
            self.bin.append(0)
        view = dict(buffer=0, byteOffset=len(self.bin), byteLength=arr.nbytes)
        if target:
            view["target"] = target
            if target == 34962 and arr.itemsize * arr.shape[-1] % 4:
                raise ValueError("vertex attributes must be 4 byte aligned")
        self.bin += arr.tobytes(); self.views.append(view)
        acc = dict(bufferView=len(self.views) - 1, componentType=ctype, count=len(arr), type=kind)
        if normalized:
            acc["normalized"] = True
        if minmax:
            acc["min"], acc["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        self.accessors.append(acc)
        return len(self.accessors) - 1

    def write(self, path, doc):
        while len(self.bin) % 4:
            self.bin.append(0)
        doc.update(buffers=[dict(byteLength=len(self.bin))], bufferViews=self.views, accessors=self.accessors)
        js = json.dumps(doc, separators=(",", ":")).encode()
        js += b" " * (-len(js) % 4)
        with open(path, "wb") as f:
            f.write(struct.pack("<III", 0x46546C67, 2, 28 + len(js) + len(self.bin)))
            f.write(struct.pack("<II", len(js), 0x4E4F534A)); f.write(js)
            f.write(struct.pack("<II", len(self.bin), 0x004E4942)); f.write(self.bin)


def poses(mj, m, d, q):
    """World pose of every body in the page's frame: translations [F, B, 3], quaternions xyzw [F, B, 4]."""
    Mq = mat2quat(M)
    T, Q = np.zeros((len(q), m.nbody, 3)), np.zeros((len(q), m.nbody, 4))
    for i, qi in enumerate(q):
        d.qpos[:] = qi; mj.mj_kinematics(m, d)
        T[i] = to_page(d.xpos)
        Q[i] = quat_mul(np.repeat(Mq[None], m.nbody, 0), d.xquat)[:, [1, 2, 3, 0]]
    for i in range(1, len(q)):                           # keep the sign continuous, for the interpolation
        Q[i] *= np.where((Q[i] * Q[i - 1]).sum(1, keepdims=True) < 0, -1, 1)
    return T, Q


def export_glb():
    mj, m, d = load_model()
    mo = np.load(SRC / "g1_open_door/motion.npz")
    q, fps = mo["qpos"], int(mo["fps"])
    frames = np.arange(0, len(q), STEP)
    if frames[-1] != len(q) - 1:
        frames = np.append(frames, len(q) - 1)
    T, Q = poses(mj, m, d, q[frames])
    meshes, mats = body_meshes(mj, m)
    g = Glb()
    names = list(mats)
    materials = []
    for k in names:
        s = mats[k]
        rgba = [*srgb_to_linear(s["rgba"][:3]).round(4).tolist(), round(float(s["rgba"][3]), 3)]
        mat = dict(name=k, pbrMetallicRoughness=dict(baseColorFactor=rgba, metallicFactor=s["metal"], roughnessFactor=s["rough"]))
        if s["glass"]:
            mat.update(alphaMode="BLEND", doubleSided=True)
        materials.append(mat)
    pelvis = m.body("pelvis").id
    is_robot = lambda b: b == pelvis or (b != 0 and is_robot(int(m.body_parentid[b])))
    nodes, gl_meshes, robot_kids, fixture_kids, channels, samplers = [], [], [], [], {"robot": [], "door": []}, {"robot": [], "door": []}
    t_acc = g.add((frames / fps).astype(np.float32), 5126, "SCALAR", minmax=True)
    tris = 0
    for b in range(m.nbody):
        if b not in meshes:
            continue
        prims = []
        for key, (v, nrm, f) in meshes[b].items():
            tris += len(f)
            nrm = nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
            n8 = np.zeros((len(nrm), 4), np.int8); n8[:, :3] = np.round(nrm * 127)
            idx = f.astype(np.uint16 if len(v) < 65536 else np.uint32).reshape(-1)
            prims.append(dict(attributes=dict(POSITION=g.add(v.astype(np.float32), 5126, "VEC3", 34962, minmax=True),
                                              NORMAL=g.add(n8, 5120, "VEC3", 34962, normalized=True)),
                              indices=g.add(idx, 5123 if idx.dtype == np.uint16 else 5125, "SCALAR", 34963), material=names.index(key)))
            g.views[g.accessors[prims[-1]["attributes"]["NORMAL"]]["bufferView"]]["byteStride"] = 4
        gl_meshes.append(dict(name=m.body(b).name, primitives=prims))
        node = dict(name=m.body(b).name, mesh=len(gl_meshes) - 1, translation=T[0, b].round(5).tolist(), rotation=Q[0, b].round(6).tolist())
        nodes.append(node)
        (robot_kids if is_robot(b) else fixture_kids).append(len(nodes) - 1)
        if np.ptp(T[:, b], 0).max() > 1e-6 or np.abs(Q[:, b] - Q[0, b]).max() > 1e-6:
            clip = "robot" if is_robot(b) else "door"
            for path, arr, kind in (("translation", T[:, b], "VEC3"), ("rotation", Q[:, b], "VEC4")):
                samplers[clip].append(dict(input=t_acc, output=g.add(arr.astype(np.float32), 5126, kind), interpolation="LINEAR"))
                channels[clip].append(dict(sampler=len(samplers[clip]) - 1, target=dict(node=len(nodes) - 1, path=path)))
    nodes += [dict(name="robot", children=robot_kids), dict(name="fixture", children=fixture_kids)]
    doc = dict(asset=dict(version="2.0", generator="tools/export_hero.py"), scene=0, scenes=[dict(nodes=[len(nodes) - 2, len(nodes) - 1])],
               nodes=nodes, meshes=gl_meshes, materials=materials, extensionsUsed=["KHR_mesh_quantization"], extensionsRequired=["KHR_mesh_quantization"],
               animations=[dict(name=k, channels=channels[k], samplers=samplers[k]) for k in ("robot", "door")])
    g.write(OUT / "scene.glb", doc)
    print(f"scene.glb {(OUT / 'scene.glb').stat().st_size / 1e6:.2f} MB, {tris} triangles, {len(nodes) - 2} bodies, "
          f"{len(channels['robot']) // 2} + {len(channels['door']) // 2} animated, {len(frames)} keys")


def export_meta():
    mj, m, d = load_model()
    mo = np.load(SRC / "g1_open_door/motion.npz")
    q, fps, phase = mo["qpos"], int(mo["fps"]), mo["phase"].astype(str)
    grasps = json.load(open(SRC / "g1_open_door/grasps.json"))
    track = dict(root="pelvis", left="left_wrist_yaw_link", right="right_wrist_yaw_link")
    ids = {k: m.body(v).id for k, v in track.items()}
    every = 5
    paths = {k: [] for k in track}
    for i in range(0, len(q), every):
        d.qpos[:] = q[i]; mj.mj_kinematics(m, d)
        for k, b in ids.items():
            paths[k].append(to_page(d.xpos[b]).round(4).tolist())
    phases, order = {}, []
    for i, p in enumerate(phase):
        if p not in phases:
            phases[p] = [i, i]; order.append(p)
        phases[p][1] = i
    d.qpos[:] = q[0]; mj.mj_kinematics(m, d)
    hinge = m.joint("washer_door_joint")
    # the grasp anchors: where the fingers of the two fitted grasps touch the lip of the pull recess. They are given
    # in the door's frame (x out of the machine, y towards the free edge, z up), which is the frame of the node "washer_door".
    anchors = {name: [dict(finger=f, r=round(g["report"][f]["r_mm"] / 1000, 4), phi=round(g["report"][f]["phi_deg"], 2)) for f in g["contact_fingers"]]
               for name, g in grasps.items()}
    meta = dict(fps=fps, frames=len(q), duration=(len(q) - 1) / fps, phases={p: phases[p] for p in order}, path_every=every, paths=paths,
                door=dict(node="washer_door", rim_centre=[0.0, 0.0, 0.50221], lip_x=0.3578, face_x=0.364, rim_r=0.2705, recess_phi=[12.0, 44.0],
                          hinge=m.jnt_pos[hinge.id].round(5).tolist(), open_deg=float(np.rad2deg(q[-1, 0]))),
                anchors=anchors, anchor_frames=dict(tip=phases["insert_tip"][1], hook=phases["insert_hook"][1]),
                right_hand_prefix="right_revo2", frame="x along the machine row, y up from the floor, z into the room; metres")
    (OUT / "scene.json").write_text(json.dumps(meta, separators=(",", ":")))
    print(f"scene.json {(OUT / 'scene.json').stat().st_size / 1e3:.1f} kB, phases {meta['phases']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=["glb", "splat", "meta"])
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in (("splat", export_splat), ("glb", export_glb), ("meta", export_meta)):
        if args.only in (None, name):
            fn()
