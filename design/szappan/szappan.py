"""Szappan modell: 145 x 78 x 24 mm, 7 mm élkerekítés, Ø6 mm kötélfurat 2 mm-es élkerekítéssel.

Futtatás:  python3 szappan.py   (pip install bpy szükséges)
Kimenet ugyanebbe a mappába: szappan.blend, szappan.stl, szappan_render.png
Mértékegység: 1 Blender egység = 1 mm.
"""
import math
import os

import bpy
import bmesh  # a bpy importja után érhető el

OUT = os.path.dirname(os.path.abspath(__file__))

# --- Méretek (mm) ---
L, W, H = 145.0, 78.0, 24.0   # hossz, szélesség, vastagság
EDGE_R = 7.0                  # élkerekítés
HOLE_D = 6.0                  # furat átmérő
HOLE_FROM_END = 12.0          # furat középpontja a keskeny oldaltól
HOLE_EDGE_R = 2.0             # furat élkerekítése mindkét oldalon
DENSITY = 1.08                # g/cm³, tipikus szilárd szappan (1.0–1.15)

SEG_EDGE = 16                 # kerekítés szegmensei
SEG_HOLE = 96                 # furat kerületi felbontása
SEG_HOLE_FILLET = 12

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.scale_length = 0.001
scene.unit_settings.length_unit = 'MILLIMETERS'


def apply_all(obj):
    bpy.context.view_layer.objects.active = obj
    for m in list(obj.modifiers):
        bpy.ops.object.modifier_apply(modifier=m.name)


# --- Lekerekített test ---
bpy.ops.mesh.primitive_cube_add(size=1)
soap = bpy.context.object
soap.name = "Szappan"
soap.scale = (L, W, H)
bpy.ops.object.transform_apply(scale=True)
bev = soap.modifiers.new("Kerekites", 'BEVEL')
bev.width = EDGE_R
bev.segments = SEG_EDGE
bev.limit_method = 'NONE'
apply_all(soap)

# --- Furat vágószerszám: forgástest, kerekített peremmel ---
# Profil (r, z): a furat fala r = 3, a peremen 2 mm sugarú negyedkör kifelé.
r0, half = HOLE_D / 2, H / 2
profile = []
for i in range(SEG_HOLE_FILLET + 1):            # alsó perem
    t = math.pi / 2 * (1 - i / SEG_HOLE_FILLET)
    profile.append((r0 + HOLE_EDGE_R - HOLE_EDGE_R * math.cos(t),
                    -half + HOLE_EDGE_R - HOLE_EDGE_R * math.sin(t)))
for i in range(SEG_HOLE_FILLET + 1):            # felső perem
    t = math.pi / 2 * i / SEG_HOLE_FILLET
    profile.append((r0 + HOLE_EDGE_R - HOLE_EDGE_R * math.cos(t),
                    half - HOLE_EDGE_R + HOLE_EDGE_R * math.sin(t)))
# a lapon túlnyúló rész, hogy a boolean ne legyen síkban egybeeső
profile = [(profile[0][0], -half - 1)] + profile + [(profile[-1][0], half + 1)]

bm = bmesh.new()
rings = []
for k in range(SEG_HOLE):
    a = 2 * math.pi * k / SEG_HOLE
    rings.append([bm.verts.new((r * math.cos(a), r * math.sin(a), z)) for r, z in profile])
for k in range(SEG_HOLE):
    r1, r2 = rings[k], rings[(k + 1) % SEG_HOLE]
    for j in range(len(profile) - 1):
        bm.faces.new((r1[j], r2[j], r2[j + 1], r1[j + 1]))
bm.faces.new([r[0] for r in reversed(rings)])
bm.faces.new([r[-1] for r in rings])
bm.normal_update()
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
cutter_me = bpy.data.meshes.new("Furat")
bm.to_mesh(cutter_me)
bm.free()
cutter = bpy.data.objects.new("Furat", cutter_me)
scene.collection.objects.link(cutter)
cutter.location = (L / 2 - HOLE_FROM_END, 0, 0)

boo = soap.modifiers.new("Furat", 'BOOLEAN')
boo.operation = 'DIFFERENCE'
boo.solver = 'EXACT'
boo.object = cutter
apply_all(soap)
bpy.data.objects.remove(cutter)

bpy.ops.object.shade_auto_smooth(angle=math.radians(40))

# --- Ellenőrzés: térfogat, tömeg, zártság ---
bm = bmesh.new()
bm.from_mesh(soap.data)
vol_mm3 = bm.calc_volume()
non_manifold = sum(1 for e in bm.edges if not e.is_manifold)
bm.free()
vol_cm3 = vol_mm3 / 1000
print(f"Méret: {tuple(round(d, 2) for d in soap.dimensions)} mm")
print(f"Térfogat: {vol_cm3:.1f} cm³  |  Tömeg ~{vol_cm3 * DENSITY:.0f} g (ρ={DENSITY} g/cm³)")
print(f"Nem zárt élek: {non_manifold}")

# --- Anyag ---
mat = bpy.data.materials.new("Szappan")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.93, 0.86, 0.74, 1)
bsdf.inputs["Roughness"].default_value = 0.45
bsdf.inputs["Subsurface Weight"].default_value = 0.3
bsdf.inputs["Subsurface Radius"].default_value = (2.0, 1.2, 0.8)
bsdf.inputs["Subsurface Scale"].default_value = 3.0
soap.data.materials.append(mat)

# --- Export ---
bpy.ops.object.select_all(action='DESELECT')
soap.select_set(True)
bpy.ops.wm.stl_export(filepath=os.path.join(OUT, "szappan.stl"),
                      export_selected_objects=True, global_scale=1.0)

# --- Render jelenet ---
bpy.ops.mesh.primitive_plane_add(size=2000, location=(0, 0, -H / 2))
floor = bpy.context.object
fm = bpy.data.materials.new("Padlo")
fm.use_nodes = True
fm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.55, 0.6, 0.62, 1)
floor.data.materials.append(fm)

bpy.ops.object.camera_add(location=(230, -300, 260))
cam = bpy.context.object
cam.data.lens = 70
cam.data.clip_end = 5000
track = cam.constraints.new('TRACK_TO')
track.target = soap
scene.camera = cam

bpy.ops.object.light_add(type='AREA', location=(-120, -150, 260))
key = bpy.context.object
key.data.energy = 6e5
key.data.size = 200
key.constraints.new('TRACK_TO').target = soap
bpy.ops.object.light_add(type='AREA', location=(250, 120, 120))
fill = bpy.context.object
fill.data.energy = 1.5e5
fill.data.size = 200
fill.constraints.new('TRACK_TO').target = soap

world = bpy.data.worlds.new("World")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.8, 0.82, 0.85, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.3
scene.world = world

scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 128
scene.render.resolution_x, scene.render.resolution_y = 1280, 900
scene.render.filepath = os.path.join(OUT, "szappan_render.png")
bpy.ops.render.render(write_still=True)

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "szappan.blend"))
