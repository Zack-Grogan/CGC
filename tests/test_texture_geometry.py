"""Optional numeric tests for the texture boundary; no model inference."""
import unittest
import io
from cgc.trellis_texture import world_source,restore_scene


class TextureGeometry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import numpy as np
            import trimesh
            import scipy
        except ImportError:raise unittest.SkipTest('Run with .backends/model-quality-test/bin/python for numeric texture tests')
        cls.np=np;cls.trimesh=trimesh

    def fixture(self):
        np=self.np;trimesh=self.trimesh
        scene=trimesh.Scene()
        group=np.eye(4);group[:3,3]=[.2,.3,.4];scene.graph.update(frame_to='assembly',matrix=group)
        transform=trimesh.transformations.rotation_matrix(.3,[0,0,1]);transform[:3,:3]=transform[:3,:3]@np.diag([1.,2.,.7]);transform[:3,3]=[2.,3.,-1.]
        scene.add_geometry(trimesh.creation.box(),geom_name='box_a',node_name='first',parent_node_name='assembly',transform=transform)
        other=np.eye(4);other[:3,3]=[-3.,0.,1.]
        scene.add_geometry(trimesh.creation.box(),geom_name='box_b',node_name='second',transform=other)
        source,owners=world_source(scene);vertices=np.asarray(source.vertices);center=(vertices.min(axis=0)+vertices.max(axis=0))/2;scale=.99999/np.ptp(vertices,axis=0).max()
        # A UV unwrap can duplicate each triangle corner without changing the surface.
        unwrapped=trimesh.Trimesh(vertices=(vertices[source.faces].reshape(-1,3)-center)*scale,faces=np.arange(len(source.faces)*3).reshape(-1,3),process=False)
        uv=(unwrapped.vertices[:,:2]+.5)
        unwrapped.visual=trimesh.visual.TextureVisuals(uv=uv)
        return scene,source,unwrapped,owners,center,scale

    def test_unwrap_restores_world_geometry_hierarchy_and_nonuniform_transforms(self):
        np=self.np;scene,source,textured,owners,center,scale=self.fixture()
        result,audit=restore_scene(scene,source,textured,owners,center,scale)
        self.assertTrue(audit['world_geometry_restored'])
        self.assertEqual(result.graph.transforms.parents,scene.graph.transforms.parents)
        for node in scene.graph.nodes_geometry:np.testing.assert_allclose(result.graph[node][0],scene.graph[node][0],atol=1e-12)
        actual,_=world_source(result)
        def triangles(mesh):return sorted(tuple(sorted(tuple(np.round(v,10)) for v in triangle)) for triangle in mesh.triangles)
        self.assertEqual(triangles(actual),triangles(source))
        self.assertTrue(all(mesh.visual.uv is not None for mesh in result.geometry.values()))
        # Engine consumers read serialized float32 GLB data, not the Python scene.
        reloaded=self.trimesh.load(io.BytesIO(result.export(file_type='glb')),file_type='glb',force='scene',process=False)
        for node in scene.graph.nodes_geometry:
            np.testing.assert_allclose(reloaded.graph[node][0],scene.graph[node][0],atol=1e-7)
        actual,_=world_source(reloaded)
        from scipy.spatial import cKDTree
        distances,_=cKDTree(source.vertices).query(actual.vertices)
        self.assertLess(float(distances.max()),1e-6)
        self.assertEqual(len(actual.faces),len(source.faces))
        self.assertTrue(all(mesh.visual.uv is not None for mesh in reloaded.geometry.values()))

    def test_changed_surface_is_rejected_instead_of_silently_passing(self):
        scene,source,textured,owners,center,scale=self.fixture()
        textured.vertices[0]+=.01
        with self.assertRaisesRegex(RuntimeError,'source surface'):restore_scene(scene,source,textured,owners,center,scale)

    def test_removed_triangles_are_rejected(self):
        scene,source,textured,owners,center,scale=self.fixture()
        textured.update_faces(self.np.arange(len(textured.faces)-1))
        with self.assertRaisesRegex(RuntimeError,'source triangles'):restore_scene(scene,source,textured,owners,center,scale)

    def test_reversed_winding_is_rejected(self):
        scene,source,textured,owners,center,scale=self.fixture()
        faces=textured.faces.copy();faces[0]=faces[0][::-1];textured.faces=faces
        with self.assertRaisesRegex(RuntimeError,'source triangles'):restore_scene(scene,source,textured,owners,center,scale)

    def test_duplicate_faces_within_same_node_retain_multiplicity(self):
        np=self.np;scene,source,textured,owners,center,scale=self.fixture()
        source.faces=np.vstack([source.faces,source.faces[0]])
        textured.faces=np.vstack([textured.faces,textured.faces[0]])
        owners.append(owners[0])
        result,audit=restore_scene(scene,source,textured,owners,center,scale)
        self.assertEqual(audit['output_faces'],len(source.faces))

    def test_coincident_different_nodes_fail_before_native_compute(self):
        scene=self.trimesh.Scene()
        scene.add_geometry(self.trimesh.creation.box(),node_name='first')
        scene.add_geometry(self.trimesh.creation.box(),node_name='second')
        with self.assertRaisesRegex(ValueError,'different nodes'):world_source(scene)


if __name__=='__main__':unittest.main()
