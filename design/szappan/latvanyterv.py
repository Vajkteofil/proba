"""Látványterv: kézműves szappan világos, szálcsiszolt rozsdamentes műhelypulton, három nézetből.

Futtatás:  python3 latvanyterv.py   (előbb a szappan.py-nak le kell futnia)
Kimenet: latvany_1_haromnegyed.png, latvany_2_felulnezet.png, latvany_3_furat_kozeli.png
"""
import math
import os

import bpy

OUT = os.path.dirname(os.path.abspath(__file__))
H = 24.0

bpy.ops.wm.open_mainfile(filepath=os.path.join(OUT, "szappan.blend"))
scene = bpy.context.scene
soap = bpy.data.objects["Szappan"]
for obj in list(scene.objects):
    if obj is not soap:
        bpy.data.objects.remove(obj)


def node(nt, kind, loc=(0, 0), **inputs):
    n = nt.nodes.new(kind)
    n.location = loc
    for k, v in inputs.items():
        n.inputs[k].default_value = v
    return n


# --- Kézműves szappan anyag: meleg mézes-krém szín, márványos tónus, apró pöttyök, enyhe felületi egyenetlenség ---
mat = bpy.data.materials.new("KezmuvesSzappan")
mat.use_nodes = True
nt = mat.node_tree
nt.nodes.clear()
outp = node(nt, "ShaderNodeOutputMaterial", (900, 0))
bsdf = node(nt, "ShaderNodeBsdfPrincipled", (600, 0),
            **{"Roughness": 0.55, "Subsurface Weight": 0.35, "Subsurface Scale": 2.5,
               "Subsurface Radius": (1.8, 1.0, 0.6)})
nt.links.new(bsdf.outputs["BSDF"], outp.inputs["Surface"])
coord = node(nt, "ShaderNodeTexCoord", (-1000, 0))

# márványos színátmenet
marble = node(nt, "ShaderNodeTexNoise", (-700, 200), Scale=0.035, Detail=6.0, Roughness=0.6, Distortion=1.5)
nt.links.new(coord.outputs["Object"], marble.inputs["Vector"])
ramp = node(nt, "ShaderNodeValToRGB", (-450, 200))
ramp.color_ramp.elements[0].position = 0.35
ramp.color_ramp.elements[0].color = (0.50, 0.17, 0.03, 1)   # karamell
ramp.color_ramp.elements[1].position = 0.70
ramp.color_ramp.elements[1].color = (0.93, 0.52, 0.14, 1)   # méz
nt.links.new(marble.outputs["Fac"], ramp.inputs["Fac"])

# apró sötét pöttyök (zab / gyógynövény)
speck = node(nt, "ShaderNodeTexNoise", (-700, -150), Scale=0.9, Detail=2.0)
nt.links.new(coord.outputs["Object"], speck.inputs["Vector"])
speck_ramp = node(nt, "ShaderNodeValToRGB", (-450, -150))
speck_ramp.color_ramp.interpolation = 'CONSTANT'
speck_ramp.color_ramp.elements[0].color = (0, 0, 0, 1)
speck_ramp.color_ramp.elements[1].position = 0.70
speck_ramp.color_ramp.elements[1].color = (1, 1, 1, 1)
nt.links.new(speck.outputs["Fac"], speck_ramp.inputs["Fac"])
mix = node(nt, "ShaderNodeMix", (100, 100))
mix.data_type = 'RGBA'
mix.inputs["B"].default_value = (0.20, 0.10, 0.04, 1)
nt.links.new(speck_ramp.outputs["Color"], mix.inputs["Factor"])
nt.links.new(ramp.outputs["Color"], mix.inputs["A"])
nt.links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
nt.links.new(ramp.outputs["Color"], bsdf.inputs["Subsurface Radius"])

# kézzel vágott hatású finom egyenetlenség
bump_tex = node(nt, "ShaderNodeTexNoise", (-700, -450), Scale=0.25, Detail=8.0, Roughness=0.65)
nt.links.new(coord.outputs["Object"], bump_tex.inputs["Vector"])
bump = node(nt, "ShaderNodeBump", (300, -300), Strength=0.25, Distance=0.6)
nt.links.new(bump_tex.outputs["Fac"], bump.inputs["Height"])
nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
soap.data.materials.clear()
soap.data.materials.append(mat)

# --- Szálcsiszolt rozsdamentes pult ---
bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 0, -H / 2))
counter = bpy.context.object
counter.scale = (1400, 800, 1)
bpy.ops.object.transform_apply(scale=True)
steel = bpy.data.materials.new("Rozsdamentes")
steel.use_nodes = True
nt = steel.node_tree
sb = nt.nodes["Principled BSDF"]
sb.inputs["Base Color"].default_value = (0.86, 0.87, 0.88, 1)
sb.inputs["Metallic"].default_value = 1.0
tc = node(nt, "ShaderNodeTexCoord", (-900, 0))
mp = node(nt, "ShaderNodeMapping", (-700, 0))
mp.inputs["Scale"].default_value = (0.02, 3.0, 1.0)          # x irányú csiszolási csíkok
nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
brush = node(nt, "ShaderNodeTexNoise", (-500, 0), Scale=1.0, Detail=10.0)
nt.links.new(mp.outputs["Vector"], brush.inputs["Vector"])
rr = node(nt, "ShaderNodeMapRange", (-300, 0))
rr.inputs["To Min"].default_value = 0.28
rr.inputs["To Max"].default_value = 0.40
nt.links.new(brush.outputs["Fac"], rr.inputs["Value"])
nt.links.new(rr.outputs["Result"], sb.inputs["Roughness"])
sbump = node(nt, "ShaderNodeBump", (-100, -250), Strength=0.08)
nt.links.new(brush.outputs["Fac"], sbump.inputs["Height"])
nt.links.new(sbump.outputs["Normal"], sb.inputs["Normal"])
counter.data.materials.append(steel)

# háttérfal (csempés műhelyfal hatás, életlenben)
bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 380, 300), rotation=(math.pi / 2, 0, 0))
wall = bpy.context.object
wall.scale = (1600, 700, 1)
wm = bpy.data.materials.new("Fal")
wm.use_nodes = True
wm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.62, 0.70, 0.66, 1)
wm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.4
wall.data.materials.append(wm)

# --- Fények ---
def area(loc, energy, size, color=(1, 1, 1)):
    bpy.ops.object.light_add(type='AREA', location=loc)
    light = bpy.context.object
    light.data.energy = energy
    light.data.size = size
    light.data.color = color
    light.constraints.new('TRACK_TO').target = soap
    return light


area((-250, -200, 350), 9e5, 300, (1.0, 0.95, 0.88))   # meleg fő fény
area((300, -100, 150), 2.5e5, 250, (0.9, 0.95, 1.0))   # hideg derítő
area((0, 300, 250), 3e5, 300)                          # hátsó kontúrfény
area((0, 0, 700), 1.2e6, 900)                          # nagy felső softbox, ettől világos a pult

world = bpy.data.worlds.new("Muhely")
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs["Color"].default_value = (0.85, 0.87, 0.9, 1)
bg.inputs["Strength"].default_value = 1.4
scene.world = world

# --- Render beállítások: élénk, nem fakó ---
scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 160
scene.cycles.use_denoising = True
scene.render.resolution_x, scene.render.resolution_y = 2048, 1408
scene.view_settings.view_transform = 'AgX'
try:
    scene.view_settings.look = 'AgX - Punchy'
except TypeError:
    pass

# --- Nézetek ---
VIEWS = [
    ("latvany_1_haromnegyed", (230, -280, 190), 60, (0, 0, 0), 4.0),
    ("latvany_2_felulnezet", (0, -60, 420), 50, (0, 0, 0), 8.0),
    ("latvany_3_furat_kozeli", (150, -95, 45), 85, (60.5, 0, H / 2), 2.8),
]
target = bpy.data.objects.new("Cel", None)
scene.collection.objects.link(target)

for name, loc, lens, aim, fstop in VIEWS:
    bpy.ops.object.camera_add(location=loc)
    cam = bpy.context.object
    cam.data.lens = lens
    cam.data.clip_end = 10000
    target.location = aim
    cam.constraints.new('TRACK_TO').target = target
    cam.data.dof.use_dof = True
    cam.data.dof.focus_object = target
    cam.data.dof.aperture_fstop = fstop
    scene.camera = cam
    scene.render.filepath = os.path.join(OUT, name + ".png")
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(cam)
