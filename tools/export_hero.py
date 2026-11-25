"""Export the 3D scene of the first screen (hero.js) from the ManipSynth laundry demonstration.

Reads   <src>/g1_laundry/{scene_laundry.xml, motion.npz}, <src>/g1_open_door/grasps.json, <src>/placement.json
        and the room's Gaussian splat.
Writes  media/hero/scene.glb   the G1 + Revo2 robot, the washer, the plush toy, the jug and its cap: one node per MuJoCo
                               body in the bodies' own hierarchy, decimated meshes, the motion baked as joint tracks
                               (clips "robot" and "scene"), then packed by gltfpack (meshopt compression)
        media/hero/room.spz    the part of the room's splat that the scene needs: the machine row with its counter and
                               shelf, the wall it is set into, the floor in front of it, the garment rack opposite. The ceiling, the other three
                               walls, both ends of the room, the splats of the replaced machine and of the scanned jug
                               are left out, and so are the splats that add least to the picture.
        media/hero/scene.json  phases, steps, root and wrist paths, the grasp anchors on the objects

Everything is put into one frame for three.js (metres, y up): x along the machine row (to the right when facing the
machines), y up from the floor, z from the machines into the room.

Needs mujoco, trimesh, fast_simplification, numpy, pillow, and gltfpack (npm install gltfpack; GLTFPACK=/path/to/it):
    /home/lenovo/miniconda3/envs/robosim/bin/python tools/export_hero.py [--only glb|splat|meta]
"""
import argparse
import gzip
import io
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np

PAGE = Path(__file__).resolve().parents[1]
SRC = Path("/home/lenovo/runyi/ManipSynth/output/laundry_washer_swap")
JUG = SRC.parent / "laundry_bottle_swap"
RUN = SRC / "g1_laundry"
SPLAT = Path("/home/lenovo/runyi/ManipSynth/asset/gs_scenes/0020_hotel_laundry/aligned.ply")
OUT = PAGE / "media/hero"
GLTFPACK = os.environ.get("GLTFPACK") or shutil.which("gltfpack") or "/tmp/hero/node_modules/.bin/gltfpack"   # npm install gltfpack
FLOOR_Z = -0.025           # the floor drawn by the splats in front of the machines (common.py)
STEP = 2                   # keys handed to gltfpack: every STEP-th frame of the 50 fps motion
KEY_RATE = 15              # keys per second that gltfpack keeps; hero.js interpolates between them
GLASS = ("door_glass", "Material_28", "material__225")
WRAPPED = ("toy",)          # bodies whose texture wraps the whole mesh
TEX_HEIGHT = dict(toy_dirty=320)   # pixels; the jug's label keeps 560

P = json.load(open(SRC / "placement.json"))
O, U, N = (np.array(P[k]) for k in ("row_origin", "row_u", "row_n"))
M = np.stack([U, [0, 0, 1.0], N])                      # world (z up) -> page (y up); a proper rotation
assert abs(np.linalg.det(M) - 1) < 1e-3


def to_page(p):
    return (np.asarray(p) - O) @ M.T - np.array([0, FLOOR_Z, 0])


# --------------------------------------------------------------------------------------------- the splat
# regions in row coordinates: u along the row, n into the room, z up. `fade` is the width over which a region's
# splats thin out towards its border, so that the room ends in the page's background and not in an edge.
ROW = dict(u=(-1.75, 3.05), n=(-0.12, 1.42), z=(0.0, 2.30))     # machines, counter, shelf, and the wall they are set into
FLOOR = dict(u=(-1.75, 3.05), n=(0.55, 3.40), z=(-0.2, 0.07))   # reaches below the rack
# the garment rack opposite the machines, which carries the plush toy: its thin tubes and wire shelves only (small
# splats), without the cabinets behind it, so that a camera on the far side still sees the machines through it
RACK = dict(u=(-0.75, 1.85), n=(2.36, 2.84), z=(0.05, 1.72))
RACK_SIZE = 0.08                    # largest splat radius that counts as part of the rack, in metres
FADE = 0.7
KEEP = dict(row=0.50, floor=0.30, rack=0.42)   # share of each region's splats that is kept, those that add most to the picture first
BITS = 9                            # fractional bits of a position: 2 mm steps
# The other attributes are bytes in the file. Rounding them to a coarser step leaves fewer distinct values, which gzip
# stores in fewer bits. Steps for opacity, colour, log size and rotation; chosen by comparing screenshots.
COARSE = dict(alpha=8, colour=3, scale=2, rot=8)


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
    return props, a


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


def morton(pos, bits=10):
    """Order along a space-filling curve: neighbours in the file are neighbours in space, which gzip likes."""
    g = ((pos - pos.min(0)) / np.ptp(pos, 0).max() * ((1 << bits) - 1)).astype(np.uint64)
    code = np.zeros(len(pos), np.uint64)
    for b in range(bits):
        for k in range(3):
            code |= ((g[:, k] >> np.uint64(b)) & np.uint64(1)) << np.uint64(3 * b + k)
    return np.argsort(code, kind="stable")


def export_splat():
    sys.path.insert(0, str(JUG))
    from splat_edit import edit_splats                   # the scanned jug is removed and the hole behind it filled
    props, a = read_ply(SPLAT)
    total = len(a)
    a, removed, added = edit_splats(props, a)
    c = {p: i for i, p in enumerate(props)}
    xyz = a[:, [c["x"], c["y"], c["z"]]].astype(np.float64)
    q = xyz - O
    co = dict(u=q @ U, n=q @ N, z=xyz[:, 2])
    alpha = 1 / (1 + np.exp(-a[:, c["opacity"]].astype(np.float64)))
    scale = a[:, [c["scale_0"], c["scale_1"], c["scale_2"]]].astype(np.float64)

    # the machine that the MuJoCo washer replaces (render_door_open.old_machine_mask)
    (u0, u1), (z0, z1), (n0, _) = P["bay_u"], P["bay_z"], P["bay_n"]
    old = ((co["u"] > u0) & (co["u"] < u1) & (co["z"] > z0 - 0.005) & (co["z"] < z1) & (co["n"] > n0) & (co["n"] < 0.86)) | \
          ((co["u"] > -0.14) & (co["u"] < 0.33) & (co["n"] > 0.735) & (co["n"] < 1.32) & (co["z"] > 0.17) & (co["z"] < 0.88))

    row = inside(co, ROW)
    floor = inside(co, FLOOR) & ~row
    rack = inside(co, RACK) & ~row & ~floor & (np.exp(scale.max(1)) < RACK_SIZE)
    s = lambda t: np.clip(t, 0, 1) ** 2 * (3 - 2 * np.clip(t, 0, 1))
    ends = s(np.minimum(co["u"] - ROW["u"][0], ROW["u"][1] - co["u"]) / FADE)        # both ends of the row
    top = s((ROW["z"][1] - co["z"]) / 0.45)                                           # the wall above the shelf
    front = s((FLOOR["n"][1] - co["n"]) / FADE)                                       # the floor towards the room
    alpha = alpha * ends * np.where(row, top, np.where(rack, 1.0, front))
    ok = (row | floor | rack) & ~old & (alpha > 0.05) & (np.exp(scale.max(1)) < 0.45)
    # what a splat adds to the picture: its opacity times the area of its disc
    area = np.exp(np.sort(scale, 1)[:, 1:].sum(1))
    score = alpha * np.minimum(area, np.quantile(area[ok], 0.98))
    keep = np.zeros(len(a), bool)
    for name, region in (("row", row), ("floor", floor), ("rack", rack)):
        idx = np.where(region & ok)[0]
        idx = idx[np.argsort(-score[idx])][:int(len(idx) * KEEP[name])]
        keep[idx] = True
        print(f"splats {name}: {len(idx)} kept of {int((region & ok).sum())}")
    print(f"kept {int(keep.sum())} of {total} (scanned jug: {removed} removed, {added} added)")

    a, alpha = a[keep], alpha[keep]
    pos = to_page(a[:, [c["x"], c["y"], c["z"]]].astype(np.float64))
    rot = a[:, [c["rot_0"], c["rot_1"], c["rot_2"], c["rot_3"]]].astype(np.float64)
    rot /= np.linalg.norm(rot, axis=1, keepdims=True)
    rot = quat_mul(np.repeat(mat2quat(M)[None], len(rot), 0), rot)
    rot *= np.where(rot[:, :1] < 0, -1, 1)
    dc = a[:, [c["f_dc_0"], c["f_dc_1"], c["f_dc_2"]]]
    scale = a[:, [c["scale_0"], c["scale_1"], c["scale_2"]]]
    order = morton(pos)
    pos, rot, dc, scale, alpha = pos[order], rot[order], dc[order], scale[order], alpha[order]

    # .spz version 2 (Niantic): header, then positions (24 bit fixed point), alphas, colours, scales, rotations.
    # Each attribute is written one component after the other (all x, then all y, ...) where the format allows it;
    # it does not for positions, whose three bytes are stored together.
    n = len(pos)
    fixed = np.round(pos * (1 << BITS)).astype(np.int32)
    p3 = np.stack([(fixed >> s8) & 0xFF for s8 in (0, 8, 16)], -1).astype(np.uint8).reshape(n, 9)
    u8 = lambda x, key: np.clip(np.round(x / COARSE[key]) * COARSE[key], 0, 255).astype(np.uint8)
    body = b"".join([
        struct.pack("<IIIBBBB", 0x5053474E, 2, n, 0, BITS, 0, 0), p3.tobytes(), u8(alpha * 255, "alpha").tobytes(),
        u8((dc * 0.15 + 0.5) * 255, "colour").tobytes(), u8((scale + 10) * 16, "scale").tobytes(), u8(rot[:, 1:] * 127.5 + 127.5, "rot").tobytes()])
    (OUT / "room.spz").write_bytes(gzip.compress(body, 9, mtime=0))
    size = (OUT / "room.spz").stat().st_size
    print(f"room.spz {size / 1e6:.2f} MB, {n} splats, {size / n:.1f} bytes each, bounds {pos.min(0).round(2)} {pos.max(0).round(2)}")


# --------------------------------------------------------------------------------------------- robot, washer, jug
def srgb_to_linear(c):
    c = np.asarray(c, float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def ratio_for(body, mat):
    """Fraction of the triangles to keep. The hands, the door, the drawer and the jug are seen from close by."""
    if "revo2" in body:
        return 0.13
    if body == "washer_door":
        return 0.10 if "Material_28" in mat else 0.26
    if body == "washer_drum":
        return 0.045
    if body == "washer_drawer":
        return 0.16
    if body == "washer":
        # the front panel and the door seal surround the porthole; with fewer triangles they close over it
        return 0.20 if mat == "w_white_m" else 0.30 if mat == "w_gasket_blue" else 0.085
    if body == "bottle":
        return 0.03 if "label" in mat else 0.07
    if body == "bottle_cap":
        return 0.08
    if body == "toy":
        return 0.5
    return 0.10


def open_holes(full, small, far=0.012):
    """Simplifying a mesh that has an opening can leave triangles across the opening: the washer's front panel and
    its door seal closed the porthole, and the drum behind it could not be seen. Triangles of `small` that lie
    further than `far` metres from the surface of `full` are taken out."""
    import trimesh
    from scipy.spatial import cKDTree
    tree = cKDTree(np.asarray(trimesh.sample.sample_surface(full, 400000, seed=0)[0]))
    tri = np.asarray(small.vertices)[np.asarray(small.faces)]
    cen = tri.mean(1)
    probes = np.concatenate([cen[:, None], (tri + cen[:, None]) / 2], 1)          # the centre and three points around it
    off = tree.query(probes.reshape(-1, 3))[0].reshape(-1, 4)
    keep = (off > far).sum(1) < 2
    if keep.all():
        return small
    out = trimesh.Trimesh(np.asarray(small.vertices), np.asarray(small.faces)[keep], process=False)
    out.remove_unreferenced_vertices()
    return out


def load_model():
    import mujoco as mj
    m = mj.MjModel.from_xml_path(str(RUN / "scene_laundry.xml"))
    return mj, m, mj.MjData(m)


def body_meshes(mj, m):
    """{body id: {material key: (vertices, normals, faces, uv or None)}} in the body's frame, decimated."""
    import fast_simplification
    import trimesh
    from scipy.spatial import cKDTree
    out, mats, before, after = {}, {}, 0, 0
    for g in range(m.ngeom):
        if m.geom_group[g] not in (0, 2) or m.geom_contype[g] or m.geom_conaffinity[g]:
            continue
        b, t = int(m.geom_bodyid[g]), m.geom_type[g]
        body = m.body(b).name
        tex = -1
        if m.geom_matid[g] >= 0:
            i = m.geom_matid[g]; key = m.material(i).name
            metal, rough = float(m.mat_metallic[i]), float(m.mat_roughness[i])
            rgba = m.mat_rgba[i].copy()
            tex = int(m.mat_texid[i].max())
            if metal < 0:
                metal, rough = 0.0, 0.45
        else:
            rgba = m.geom_rgba[g].copy(); key = "rgba_%d_%d_%d" % tuple(np.round(rgba[:3] * 100))
            metal, rough = (0.0, 0.92) if body == "world" else (0.15, 0.5)
        mats[key] = dict(rgba=rgba, metal=metal, rough=max(rough, 0.06), glass=key.endswith(GLASS), tex=tex)
        uv = None
        if t == mj.mjtGeom.mjGEOM_MESH:
            i = m.geom_dataid[g]
            v = m.mesh_vert[m.mesh_vertadr[i]:m.mesh_vertadr[i] + m.mesh_vertnum[i]].astype(np.float64)
            f = m.mesh_face[m.mesh_faceadr[i]:m.mesh_faceadr[i] + m.mesh_facenum[i]]
            if tex >= 0 and m.mesh_texcoordnum[i]:
                # one texture coordinate per vertex: the one of the last face corner that uses it
                tc = m.mesh_texcoord[m.mesh_texcoordadr[i]:m.mesh_texcoordadr[i] + m.mesh_texcoordnum[i]]
                ft = m.mesh_facetexcoord[m.mesh_faceadr[i]:m.mesh_faceadr[i] + m.mesh_facenum[i]]
                uv0 = np.zeros((len(v), 2)); uv0[f.reshape(-1)] = tc[ft.reshape(-1)]
            tm = trimesh.Trimesh(v, f, process=tex < 0)
            before += len(tm.faces)
            if body in WRAPPED and tex >= 0 and m.mesh_texcoordnum[i]:
                # a texture that wraps the whole mesh has seams, where a vertex has two texture coordinates: the mesh
                # is simplified first, then every corner looks up the coordinate of the nearest original corner in
                # its own triangle's neighbourhood, and vertices are split where the corners disagree
                target = max(300, int(len(f) * ratio_for(body, key)))
                v2, f2 = fast_simplification.simplify(v.astype(np.float32), f, target_count=target, agg=3)
                v2, f2 = np.asarray(v2, np.float64), np.asarray(f2)
                cen = v[f].mean(1)
                near = cKDTree(cen).query(v2[f2].mean(1))[1]                 # the original triangle closest to each new one
                # coordinates of the new corners in the plane of that original triangle (barycentric, clamped)
                A, B, C = (v[f[near, k]] for k in range(3))
                tA, tB, tC = (tc[ft[near, k]] for k in range(3))
                corner_uv = np.zeros((len(f2), 3, 2))
                for k in range(3):
                    p = v2[f2[:, k]]
                    e0, e1, e2 = B - A, C - A, p - A
                    d00, d01, d11 = (e0 * e0).sum(1), (e0 * e1).sum(1), (e1 * e1).sum(1)
                    d20, d21 = (e2 * e0).sum(1), (e2 * e1).sum(1)
                    den = np.maximum(d00 * d11 - d01 * d01, 1e-18)
                    bv, bw = (d11 * d20 - d01 * d21) / den, (d00 * d21 - d01 * d20) / den
                    bv, bw = np.clip(bv, -0.5, 1.5), np.clip(bw, -0.5, 1.5)
                    corner_uv[:, k] = tA + bv[:, None] * (tB - tA) + bw[:, None] * (tC - tA)
                nrm_v = np.asarray(trimesh.Trimesh(v2, f2, process=False).vertex_normals)
                keyed = np.concatenate([f2.reshape(-1, 1), np.round(corner_uv.reshape(-1, 2) * 512)], 1)
                _, first, inv = np.unique(keyed, axis=0, return_index=True, return_inverse=True)
                idx = f2.reshape(-1)[first]
                tm = trimesh.Trimesh(v2[idx], inv.reshape(-1, 3), vertex_normals=nrm_v[idx], process=False)
                uv = np.clip(corner_uv.reshape(-1, 2)[first], 0, 1)
            elif len(tm.faces) > 400:
                target = max(300, int(len(tm.faces) * ratio_for(body, key)))
                v2, f2 = fast_simplification.simplify(np.asarray(tm.vertices, np.float32), np.asarray(tm.faces), target_count=target, agg=3 if body == "washer" and key in ("w_white_m", "w_gasket_blue") else 5)
                tm = trimesh.Trimesh(v2, f2, process=tex < 0)
                if body.startswith("washer"):
                    tm = open_holes(trimesh.Trimesh(v, f, process=False), tm)
            if uv is None and tex >= 0 and m.mesh_texcoordnum[i]:
                uv = uv0[cKDTree(v).query(np.asarray(tm.vertices))[1]]
        elif t == mj.mjtGeom.mjGEOM_BOX:
            tm = trimesh.creation.box(extents=2 * m.geom_size[g])
        else:
            continue
        if uv is None:
            tm.update_faces(tm.nondegenerate_faces()); tm.remove_unreferenced_vertices()
            tm = trimesh.graph.smooth_shade(tm, angle=np.deg2rad(38))
        after += len(tm.faces)
        R = np.zeros(9); mj.mju_quat2Mat(R, m.geom_quat[g]); R = R.reshape(3, 3)
        v = np.asarray(tm.vertices) @ R.T + m.geom_pos[g]
        nrm = np.asarray(tm.vertex_normals) @ R.T
        slot = out.setdefault(b, {}).setdefault(key, [[], [], [], 0, []])
        slot[0].append(v); slot[1].append(nrm); slot[2].append(np.asarray(tm.faces) + slot[3]); slot[3] += len(v)
        if uv is not None:
            slot[4].append(uv)
    print(f"triangles: {before} -> {after}")
    return {b: {k: (np.vstack(s[0]), np.vstack(s[1]), np.vstack(s[2]), np.vstack(s[4]) if s[4] else None) for k, s in d.items()}
            for b, d in out.items()}, mats


class Glb:
    def __init__(self):
        self.bin, self.views, self.accessors = bytearray(), [], []

    def view(self, data, target=None):
        while len(self.bin) % 4:
            self.bin.append(0)
        v = dict(buffer=0, byteOffset=len(self.bin), byteLength=len(data))
        if target:
            v["target"] = target
        self.bin += data; self.views.append(v)
        return len(self.views) - 1

    def add(self, arr, ctype, kind, target=None, minmax=False):
        arr = np.ascontiguousarray(arr)
        acc = dict(bufferView=self.view(arr.tobytes(), target), componentType=ctype, count=len(arr), type=kind)
        if minmax:
            acc["min"], acc["max"] = np.atleast_1d(arr.min(0)).tolist(), np.atleast_1d(arr.max(0)).tolist()
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


def local_poses(mj, m, d, q):
    """Pose of every body in its parent's frame: translations [F, B, 3], quaternions xyzw [F, B, 4]."""
    T, Q = np.zeros((len(q), m.nbody, 3)), np.zeros((len(q), m.nbody, 4))
    par = m.body_parentid
    for i, qi in enumerate(q):
        d.qpos[:] = qi; mj.mj_kinematics(m, d)
        R = d.xmat.reshape(-1, 3, 3)
        T[i] = np.einsum("bji,bj->bi", R[par], d.xpos - d.xpos[par])
        Rl = np.einsum("bji,bjk->bik", R[par], R)
        for b in range(1, m.nbody):
            Q[i, b] = mat2quat(Rl[b])[[1, 2, 3, 0]]
    Q[:, 0, 3] = 1
    for i in range(1, len(q)):                           # keep the sign continuous, for the interpolation
        Q[i] *= np.where((Q[i] * Q[i - 1]).sum(1, keepdims=True) < 0, -1, 1)
    return T, Q


def texture_jpeg(m, t, height=560):
    from PIL import Image
    w, h, adr = int(m.tex_width[t]), int(m.tex_height[t]), int(m.tex_adr[t])
    img = Image.fromarray(m.tex_data[adr:adr + w * h * 3].reshape(h, w, 3))
    img = img.resize((round(w * height / h), height), Image.LANCZOS)
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=82, optimize=True)
    return buf.getvalue()


def export_glb():
    mj, m, d = load_model()
    mo = np.load(RUN / "motion.npz")
    q, fps = mo["qpos"], int(mo["fps"])
    frames = np.arange(0, len(q), STEP)
    if frames[-1] != len(q) - 1:
        frames = np.append(frames, len(q) - 1)
    T, Q = local_poses(mj, m, d, q[frames])
    meshes, mats = body_meshes(mj, m)
    g = Glb()
    names = list(mats)
    materials, images, textures = [], [], []
    for k in names:
        s = mats[k]
        rgba = [*srgb_to_linear(s["rgba"][:3]).round(4).tolist(), round(float(s["rgba"][3]), 3)]
        pbr = dict(baseColorFactor=rgba, metallicFactor=s["metal"], roughnessFactor=s["rough"])
        if s["tex"] >= 0:
            images.append(dict(bufferView=g.view(texture_jpeg(m, s["tex"], TEX_HEIGHT.get(k, 560))), mimeType="image/jpeg"))
            textures.append(dict(source=len(images) - 1, sampler=0))
            pbr.update(baseColorTexture=dict(index=len(textures) - 1), baseColorFactor=[1, 1, 1, 1])
        mat = dict(name=k, pbrMetallicRoughness=pbr)
        if s["glass"]:
            mat.update(alphaMode="BLEND", doubleSided=True)
        materials.append(mat)
    pelvis = m.body("pelvis").id
    is_robot = lambda b: b == pelvis or (b != 0 and is_robot(int(m.body_parentid[b])))
    # the two groups carry the change of frame; below them the nodes are MuJoCo's bodies in MuJoCo's coordinates
    Mq = mat2quat(M)[[1, 2, 3, 0]].round(7).tolist()
    Mt = (-(O @ M.T) - np.array([0, FLOOR_Z, 0])).round(6).tolist()
    nodes = [dict(name="robot", children=[], rotation=Mq, translation=Mt), dict(name="fixture", children=[], rotation=Mq, translation=Mt)]
    gl_meshes, node_of = [], {}
    channels, samplers = {"robot": [], "scene": []}, {"robot": [], "scene": []}
    t_acc = g.add((frames / fps).astype(np.float32), 5126, "SCALAR", minmax=True)
    tris = 0
    for b in range(m.nbody):
        if b == 0 and b not in meshes:
            continue
        name = m.body(b).name if b else "bay"
        node = dict(name=name, children=[])
        if b:
            node.update(translation=T[0, b].round(6).tolist(), rotation=Q[0, b].round(7).tolist())
        if b in meshes:
            prims = []
            for key, (v, nrm, f, uv) in meshes[b].items():
                tris += len(f)
                nrm = nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
                attr = dict(POSITION=g.add(v.astype(np.float32), 5126, "VEC3", 34962, minmax=True),
                            NORMAL=g.add(nrm.astype(np.float32), 5126, "VEC3", 34962))
                if uv is not None:
                    attr["TEXCOORD_0"] = g.add(uv.astype(np.float32), 5126, "VEC2", 34962)   # MuJoCo has flipped v already
                prims.append(dict(attributes=attr, indices=g.add(f.astype(np.uint32).reshape(-1), 5125, "SCALAR", 34963), material=names.index(key)))
            gl_meshes.append(dict(name=name, primitives=prims))
            # the mesh hangs below the body's node, so that gltfpack's scale for its packed positions stays off the body
            nodes.append(dict(name=name + "_geo", mesh=len(gl_meshes) - 1))
            node["children"].append(len(nodes) - 1)
        nodes.append(node); node_of[b] = len(nodes) - 1
        parent = int(m.body_parentid[b])
        nodes[node_of[parent] if parent in node_of and parent else (0 if is_robot(b) else 1)]["children"].append(node_of[b])
        if not b:
            continue
        clip = "robot" if is_robot(b) else "scene"
        for path, arr, kind, tol in (("translation", T[:, b], "VEC3", 2e-5), ("rotation", Q[:, b], "VEC4", 2e-5)):
            if np.abs(arr - arr[0]).max() > tol:
                samplers[clip].append(dict(input=t_acc, output=g.add(arr.astype(np.float32), 5126, kind), interpolation="LINEAR"))
                channels[clip].append(dict(sampler=len(samplers[clip]) - 1, target=dict(node=node_of[b], path=path)))
    for n in nodes:
        if not n.get("children"):
            n.pop("children", None)
    doc = dict(asset=dict(version="2.0", generator="tools/export_hero.py"), scene=0, scenes=[dict(nodes=[0, 1])],
               nodes=nodes, meshes=gl_meshes, materials=materials,
               animations=[dict(name=k, channels=channels[k], samplers=samplers[k]) for k in ("robot", "scene")])
    if images:
        doc.update(images=images, textures=textures, samplers=[dict(magFilter=9729, minFilter=9987, wrapS=33071, wrapT=33071)])
    raw = Path("/tmp/hero/raw.glb"); raw.parent.mkdir(exist_ok=True)
    g.write(raw, doc)
    # gltfpack: 14 bit positions inside each mesh, 8 bit normals, keys at KEY_RATE with 16 bit rotations, meshopt
    # compression (-cc). It keeps named nodes and materials (-kn -km), which hero.js looks up.
    subprocess.run([GLTFPACK, "-i", str(raw), "-o", str(OUT / "scene.glb"), "-cc", "-kn", "-km", "-vp", "14", "-vn", "8", "-vt", "12",
                    "-af", str(KEY_RATE), "-at", "16", "-ar", "16", "-as", "16"], check=True)
    size = (OUT / "scene.glb").stat().st_size
    wire = len(gzip.compress((OUT / "scene.glb").read_bytes(), 9))
    print(f"scene.glb {size / 1e6:.2f} MB ({wire / 1e6:.2f} MB gzipped; {raw.stat().st_size / 1e6:.1f} MB before gltfpack), {tris} triangles, "
          f"{len(channels['robot'])} + {len(channels['scene'])} tracks, {len(frames)} keys in")


STEPS = [("Open the washer door", "open_door:stand", "open_door:stand_end"), ("Load the plush toy", "walk_to_rack", "retract_toy"),
         ("Fetch the detergent", "walk_to_counter", "raise_jug"),
         ("Unscrew the cap", "reach_cap", "release_cap"), ("Open the drawer", "walk_to_washer", "release_drawer"),
         ("Pour", "reach_pour", "retract_pour"), ("Close the drawer", "reach_push", "release_push"), ("Close the door", "walk_to_door", "stand")]


def export_meta():
    mj, m, d = load_model()
    mo = np.load(RUN / "motion.npz")
    q, fps, phase = mo["qpos"], int(mo["fps"]), mo["phase"].astype(str)
    grasps = json.load(open(SRC / "g1_open_door/grasps.json"))
    track = dict(root="pelvis", left="left_wrist_yaw_link", right="right_wrist_yaw_link")
    ids = {k: m.body(v).id for k, v in track.items()}
    every = 5                                            # the paths cover the first step, which is the one hero.js draws
    paths = {k: [] for k in track}
    for i in range(0, int(np.where(phase == "walk_to_rack")[0][0]), every):
        d.qpos[:] = q[i]; mj.mj_kinematics(m, d)
        for k, b in ids.items():
            paths[k].append(to_page(d.xpos[b]).round(3).tolist())
    # phases as [first frame, last frame]; the door-opening part starts and ends with "open_door:stand"
    phases, order, prev = {}, [], None
    for i, p in enumerate(phase):
        if p != prev:
            name = p if p not in phases else p + "_end"
            phases[name] = [i, i]; order.append(name)
        phases[order[-1]][1] = i
        prev = p
    steps = [dict(name=n, frames=[phases[a][0], phases[b][1]]) for n, a, b in STEPS]

    # the grasp anchors. On the door: where the fingers of the fitted hook grasp touch the lip of the pull recess, in
    # the door's frame (x out of the machine, y towards the free edge, z up). On the jug, its cap and the drawer: the
    # fingertips at the moment the hand takes hold, in the frame of the object's node.
    anchors = {name: [dict(finger=f, r=round(g["report"][f]["r_mm"] / 1000, 4), phi=round(g["report"][f]["phi_deg"], 2)) for f in g["contact_fingers"]]
               for name, g in grasps.items()}
    held = []
    for node, side, key, fingers in (("toy", "right", "lift_toy", "thumb index middle ring pinky"), ("bottle", "right", "lift_jug", "thumb index middle ring pinky"), ("bottle_cap", "left", "unscrew_cap", "thumb index middle"),
                                     ("washer_drawer", "left", "pull_drawer", "index middle ring pinky")):
        f0 = phases[key][0]
        d.qpos[:] = q[f0]; mj.mj_kinematics(m, d)
        o = m.body(node).id; R = d.xmat[o].reshape(3, 3)
        pts = [((d.xpos[m.body(f"{side}_revo2_{f}_touch_link").id] - d.xpos[o]) @ R).round(4).tolist() for f in fingers.split()]
        held.append(dict(node=node, hand=side, frame=f0, points=pts))
    hinge = m.joint("washer_door_joint")
    meta = dict(fps=fps, frames=len(q), duration=(len(q) - 1) / fps, phases={p: phases[p] for p in order}, steps=steps, path_every=every, paths=paths,
                door=dict(node="washer_door", rim_centre=[0.0, 0.0, 0.50221], lip_x=0.3578, face_x=0.364, rim_r=0.2705, recess_phi=[12.0, 44.0],
                          hinge=m.jnt_pos[hinge.id].round(5).tolist(), open_deg=float(np.rad2deg(q[:, 0].max()))),
                anchors=anchors, held=held, frame="x along the machine row, y up from the floor, z into the room; metres")
    (OUT / "scene.json").write_text(json.dumps(meta, separators=(",", ":")))
    print(f"scene.json {(OUT / 'scene.json').stat().st_size / 1e3:.1f} kB, steps {[(s['name'], s['frames']) for s in steps]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=["glb", "splat", "meta"])
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in (("splat", export_splat), ("glb", export_glb), ("meta", export_meta)):
        if args.only in (None, name):
            fn()
