import json
import socket
import time

import bpy

SOCKET_HOST = "localhost"
SOCKET_PORT = 8083


class ERPTEngine(bpy.types.RenderEngine):
    # SECTION: Engine basic properties:
    # Name properties
    bl_idname = "ERPTENGINE"
    bl_label = "ERPT Render Engine Addon"

    bl_use_eevee_viewport = True
    bl_use_postprocess = True
    # bl_use_save_buffers = True    # Worth investigating
    bl_use_shading_nodes_custom = False

    # Init is called whenever a new render engine instance is created. Multiple
    # instances may exist at the same time, for example for a viewport and final
    # render.
    def __init__(self):
        self.size_y = 0
        self.size_x = 0

        self.scene_data = None
        self.draw_data = None

    # When the render engine instance is destroy, this is called. Clean up any
    # render engine data here, for example stopping running render threads.
    def __del__(self):
        pass

    # This is the method called by Blender for both final renders (F12) and
    # small preview for materials, world and lights.
    def render(self, depsgraph):
        scene = depsgraph.scene
        engine_exe = bpy.context.preferences.addons[__package__].preferences.engineExecutablePath
        scale = scene.render.resolution_percentage / 100.0
        self.size_y = int(scene.render.resolution_y * scale)
        self.size_x = int(scene.render.resolution_x * scale)

        # SECTION: Collect render data
        render_data = {}
        scene_data = {"MESHES": [], "LIGHTS": []}

        # Set Render Resolution
        render_data["RESOLUTION"] = [self.size_x, self.size_y]

        # Setting scene data
        for obj in bpy.data.objects:
            # Sort and interact by type
            if obj.type == "MESH":
                mesh_encode = {}

                # Extract object parts
                obj_eval = obj.evaluated_get(depsgraph)
                obj_mesh = obj_eval.to_mesh()  # Mesh
                obj_mat = obj_eval.matrix_world
                obj_vertices = obj_mesh.vertices  # Vertices
                obj_polys = obj_mesh.polygons  # Faces (polygons)

                # Loop vertices
                mesh_encode["VERTICES"] = [list(obj_mat @ vertex.co) for vertex in obj_vertices]

                # Loop faces
                mesh_encode["FACES"] = [{"NORMAL": list(face.normal), "VERTICES": list(face.vertices)} for face in
                                        obj_polys.values()]

                # Add to scene_data and clear mesh
                scene_data["MESHES"].append(mesh_encode)
                obj_eval.to_mesh_clear()
            elif obj.type == "LIGHT":
                light_encode = {"TYPE": obj.data.type, "LOCATION": list(obj.location), "COLOR": list(obj.data.color),
                                "ENERGY": obj.data.energy}
                scene_data["LIGHTS"].append(light_encode)
            elif obj.type == "CAMERA":
                if obj == scene.camera:  # Only encode the active camera
                    camera_matrix = obj.matrix_world
                    camera_data = obj.data
                    camera_clip = [camera_data.clip_start, camera_data.clip_end]

                    # noinspection PyUnresolvedReferences
                    scene_data["CAMERA"] = {"LOCATION": list(obj.location), "ROTATION": list(obj.rotation_euler),
                                            "DIRECTION": [-camera_matrix[0][2], -camera_matrix[1][2],
                                                          -camera_matrix[2][2]], "FOV": camera_data.angle,
                                            "CLIP": camera_clip}

        # Load in scene data
        render_data["SCENE"] = scene_data

        # Setup socket and connect to engine executable
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind((SOCKET_HOST, SOCKET_PORT))
        s.listen(1)

        print("Connecting to Engine")

        # _ = subprocess.Popen([engine_exe], shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        connection, address = s.accept()

        # SECTION: Send render data
        render_data_json = json.dumps(render_data, separators=(',', ':')).encode()
        render_data_len_rev = str(len(render_data_json))[::-1].encode()
        connection.sendall(render_data_len_rev + render_data_json)  # Send data
        print("Sent all data")

        # SECTION: Read in pixel data transfer and convert
        data_buffer = []
        while True:
            in_data = connection.recv(1024)
            if in_data:
                data_buffer.append(in_data.decode("utf8"))
            else:
                # Close off connection to engine once data is received
                connection.close()
                s.close()
                break

        print("Read render data")
        data_to_string = ''.join(data_buffer).strip()
        # print(data_to_string)

        parse_start = time.time()
        pix_data = json.loads(data_to_string)
        parse_end = time.time()

        print("Transfer took:", (parse_end - parse_start))

        # Here we write the pixel values to the RenderResult
        result = self.begin_result(0, 0, self.size_x, self.size_y)
        # noinspection PyTypeChecker
        layer = result.layers[0].passes["Combined"]
        layer.rect = pix_data
        self.end_result(result)


# RenderEngines also need to tell UI Panels that they are compatible with.
# We recommend to enable all panels marked as BLENDER_RENDER, and then
# exclude any panels that are replaced by custom panels registered by the
# render engine, or that are not supported.
def get_panels():
    exclude_panels = {
        'VIEWLAYER_PT_filter',
        'VIEWLAYER_PT_layer_passes',
    }

    panels = []
    for panel in bpy.types.Panel.__subclasses__():
        if hasattr(panel, 'COMPAT_ENGINES') and 'BLENDER_RENDER' in panel.COMPAT_ENGINES:
            if panel.__name__ not in exclude_panels:
                panels.append(panel)

    return panels


def register():
    # Register the RenderEngine
    bpy.utils.register_class(ERPTEngine)

    for panel in get_panels():
        panel.COMPAT_ENGINES.add('ERPTENGINE')

    print("ERPT Engine Registered")


def unregister():
    bpy.utils.unregister_class(ERPTEngine)

    for panel in get_panels():
        if 'ERPTENGINE' in panel.COMPAT_ENGINES:
            panel.COMPAT_ENGINES.remove('ERPTENGINE')


if __name__ == "__main__":
    register()
