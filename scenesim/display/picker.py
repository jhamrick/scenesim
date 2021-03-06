"""
``scenesim.display.picker``
==========================+

Picker: view and click objects in a scene.

"""
##
from direct.directtools.DirectGeometry import LineNodePath
from libpanda import BitMask32, Point3, Vec3, Vec4
import networkx as nx
import numpy as np
from panda3d.core import (CollisionHandlerQueue, CollisionNode, CollisionRay,
                          CollisionTraverser, GeomNode,
                          RenderModeAttrib, TransparencyAttrib)
##
from scenesim.display.viewer import Viewer
from scenesim.objects.gso import GSO
from scenesim.objects.pso import CPSO, PSO
from scenesim.physics.bulletbase import JointManager
from scenesim.physics.contact import ContactDetector, Parser
##
from pdb import set_trace as BP


class Picker(Viewer):
    """ View and click objects in a scene."""

    def __init__(self):
        # Parent init.
        super(Picker, self).__init__()
        self.disableMouse()
        # Picker stuff.
        self.contact_margin = Vec3(0.01, 0.01, 0.01)
        self.parser = None
        self.marked = None
        self.attached_pairs = set()
        self.contacts = None
        self.contact_points = None
        self.contact_bottoms = None
        self.compound_components = []
        self.compound_objects = []
        self.joints = JointManager()
        self.wire_attrib = RenderModeAttrib.make(
            RenderModeAttrib.MWireframe, 4.)
        self.attachment_colors = (Vec4(0.1, 0.1, 1., 1.),
                                  Vec4(0.1, 0.8, 0.1, 1.),
                                  Vec4(1., 0.1, 1., 1.),
                                  Vec4(1., 0.5, 0.1, 1.),
                                  Vec4(1., 1., 1., 1.))
        self.max_attach = 999
        self.permanent_events += ["mouse1"]
        # Make cursor dot.
        self.cursor = self._build_cursor("cross")
        s = 0.08
        self.cursor.setScale(s, s, s)
        self.cursor.setColor(1, 1, 1, 1)
        self.cursor.reparentTo(self.aspect2d)
        self.taskMgr.add(self.draw_cursor2d, "draw_cursor2d")
        self.permanent_tasks.append("draw_cursor2d")

    def init_ssos(self, *args, **kwargs):
        super(Picker, self).init_ssos(*args, **kwargs)

    def init_physics(self, *args, **kwargs):
        super(Picker, self).init_physics(*args, **kwargs)
        self.joints.bbase = self.bbase

    def init_picker(self):
        # Collision traverser
        self.traverser = CollisionTraverser("traverser")
        # Collision handler
        self.handler = CollisionHandlerQueue()
        # Initialize and set up picker ray node and NodePath
        self.picker = CollisionNode("mouse_ray")
        self.pickerNP = self.camera.attachNewNode(self.picker)
        self.picker.setFromCollideMask(GeomNode.getDefaultCollideMask())
        self.picker_ray = CollisionRay()
        self.picker.addSolid(self.picker_ray)
        self.traverser.addCollider(self.pickerNP, self.handler)
        mark_color = (1, 1, 1, 0.3)
        self.base_mark = self.create_mark(color=mark_color)
        connector_color = (1, 1, 1, 1)
        self.base_connector = self.create_connector(color=connector_color)

    def _build_cursor(self, shape="sphere"):
        if shape == "sphere":
            cursor = self._load("sphere.bam")
        elif shape == "cross":
            cursor = LineNodePath()
            lines = [[Point3(-0.5, 0, 0), Point3(0.5, 0, 0)],
                     [Point3(0, 0, -0.5), Point3(0, 0, 0.5)]]
            cursor.drawLines(lines)
            cursor.setThickness(1)
            cursor.create()
            # cursor = NodePath("cross")
            # S = {"cylinderX.bam": ((0., 0., 0.), (1., 0.1, 0.1)),
            #      "cylinderY.bam": ((0., 0., 0.), (0.1, 1., 0.1)),
            #      "cylinderZ.bam": ((0., 0., 0.), (0.1, 0.1, 1.))}
            # for k, v in S.iteritems():
            #     m = self._load(k)
            #     m.setName(k)
            #     m.setPos(*v[0])
            #     m.setScale(*v[1])
            #     m.reparentTo(cursor)
        #BP()
        return cursor

    def create_mark(self, color):
        """ Makes a graphical mark object."""
        # Make a graphical box.
        props = dict(name="mark", color=color, model="box-round.egg")
        obj = GSO(props=props)
        return obj

    def create_connector(self, color):
        """ Makes a graphical connector object."""
        # Make a graphical box.
        props = dict(name="connector", color=color, model="connector.egg")
        obj = GSO(props=props)
        return obj

    def start_picker(self, pickables):
        # Set pickable objs.
        for i, obj in enumerate(pickables):
            obj.setTag("pickable", str(i))
        # Add mouse events.
        self.accept("mouse1", self.clicked, extraArgs=[1])
        # Start contact detector.
        detector = ContactDetector(self.bbase.world, self.scene,
                                   margin=self.contact_margin)
        self.contacts = detector.contacts
        self.contact_bodies = detector.bodies
        self.contact_points = detector.points
        parser = Parser(self.contacts, self.contact_bodies)
        self.contact_bottoms = parser.bottom_bodies
        self.connectors = {}

    def stop_picker(self):
        self.removeTask("mouse1")

    def goto_sso(self, *args, **kwargs):
        self.clear_attachments()
        self.stop_picker()
        super(Picker, self).goto_sso(*args, **kwargs)
        self.remove_physics()
        # Start picker.
        pickables = self.sso.descendants(type_=PSO)
        self.start_picker(pickables)
        self.attach_physics()

    def get_picked_obj(self):
        mpos = self.mouseWatcherNode.getMouse()
        self.picker_ray.setFromLens(self.cam.node(), mpos.getX(), mpos.getY())
        self.traverser.traverse(self.render)
        if self.handler.getNumEntries() > 0:
            # This is so we get the closest object
            self.handler.sortEntries()
            entries = self.handler.getEntries()
            for entry in entries:
                picked_obj = entry.getIntoNodePath().findNetTag("pickable")
                if not picked_obj.isEmpty():
                    break
            if picked_obj.isEmpty():
                picked_obj = None
        else:
            picked_obj = None
        return picked_obj

    def clicked(self, button):
        """ Mouse click handler."""
        if self.mouseWatcherNode.hasMouse():
            # Get picked object
            picked_obj = self.get_picked_obj()
            if picked_obj is not None:
                if self.marked is None:
                    # New mark activated.
                    self.marked = picked_obj
                    self.show_marked(picked_obj, True)
                    event = "mark"
                elif picked_obj == self.marked:
                    # Existing mark deactivated.
                    self.show_marked(picked_obj, False)
                    self.marked = None
                    event = "unmark"
                else:
                    # New attachment or detachment.
                    pair = tuple(sorted((self.marked, picked_obj)))
                    ij = tuple(sorted((self.contact_bodies.index(pair[0]),
                                       self.contact_bodies.index(pair[1]))))
                    if ij in self.contacts:
                        f_add = (ij, pair) not in self.attached_pairs
                        if (not f_add or len(self.attached_pairs) <
                            self.max_attach):
                            self.store_attachment(ij, pair, f_add)
                            self.show_marked(self.marked, False)
                            self.marked = None
                            event = "attach" if f_add else "detach"
                        else:
                            print("Max attachments already reached.")
                            event = "max-attach"
                    else:
                        event = "non-contact"
            else:
                event = "non-pick"
            return picked_obj, event

    def store_attachment(self, ij, pair, f_add):
        """ Stores the attached objects, and draws them."""
        if f_add:
            self.attached_pairs.add((ij, pair))
            self.show_attachment(ij, True)
            self.attach_pair(pair, True)
        else:
            try:
                self.attached_pairs.remove((ij, pair))
            except KeyError:
                pass
            else:
                self.attach_pair(pair, False)
                self.show_attachment(ij, False)

    def clear_attachments(self):
        """ Clear all attachments."""
        if self.marked:
            self.show_marked(self.marked, False)
            self.marked = None
            self.mark = None
        for ij, pair in self.attached_pairs:
            self.attach_pair(pair, False)
            self.show_attachment(ij, False)
        self.attached_pairs = set()
        #
        self.reset_compounds()
        self.contacts = None
        self.contact_bodies = None
        self.contact_points = None
        self.contact_bottoms = None

    def _make_mark(self, node, extent, name):
        """ Makes a mark GSO."""
        mark = self.base_mark.copy()
        mat = node.getMat(self.scene)
        mark.apply_prop(dict(name=name), other=self.scene)
        mark.setMat(self.scene, mat)
        mark.setScale(self.scene, mark.getScale(self.scene) + extent)
        mark.wrtReparentTo(node)
        return mark

    def show_marked(self, node, f_on):
        """ Turns on/off marked graphic."""
        if f_on:
            extent = Vec3(0.15, 0.15, 0.15)
            name = "mark"
            self.mark = self._make_mark(node, extent, name)
            self.mark.init_tree(tags=("model",))
            # Exclude object from casting shadows
            self.mark.hide(self.shadow_mask)
            self.mark.setTransparency(TransparencyAttrib.MAlpha)
            self.mark.setDepthWrite(False)
            self.mark.setBin("fixed", 0, priority=5)
        else:
            self.mark.removeNode()

    def _make_connector(self, parent, points, extent, name):
        """ Makes connector object."""
        connector = self.base_connector.copy()
        scale = Vec3(*(np.ptp(points, axis=0)))
        scale_extended = scale + extent
        pos = Point3(*(np.min(points, axis=0) + scale / 2.))
        connector.apply_prop(dict(name=name, scale=scale_extended, pos=pos),
                             other=self.scene)
        connector.wrtReparentTo(parent)
        return connector

    def show_attachment(self, ij, f_on):
        """ Turns on/off attachment graphic."""
        if f_on:
            parent = self.contact_bottoms[ij]
            points = self.contact_points[ij]
            extent = Vec3(0.15, 0.15, 0.15)
            name = "connector_%d-%d" % ij
            self.connectors[ij] = self._make_connector(parent, points,
                                                       extent, name)
            self.connectors[ij].init_tree(tags=("model",))
        else:
            self.connectors.pop(ij).removeNode()

    # def attach_pair(self, pair, f_on):
    #     """ Adds/removes physical attachment between a pair of nodes."""
    #     key = tuple(sorted(p.node() for p in pair))
    #     # key = frozenset(pair)
    #     if f_on:
    #         # Create the joint and add it.
    #         self.joints[key] = self.joints.make_fixed(*pair)
    #     else:
    #         # Remove it.
    #         del self.joints[key]

    def attach_physics(self):
        # Attach `self.scene` to the physics world.
        try:
            exclude = zip(*self.compound_components)[0]
        except IndexError:
            exclude = []
        bnodes = [bnode for bnode in self.scene.descendants(type_=PSO)
                  if bnode not in exclude]
        for bnode in bnodes:
            bnode.init_resources(tags=("shape",))
            bnode.setCollideMask(BitMask32.allOn())
            bnode.node().setDeactivationEnabled(False)
        self.bbase.attach(bnodes)

    def reset_compounds(self):
        for n, p in self.compound_components:
            n.wrtReparentTo(p)
        self.compound_components = []
        for cnode in self.compound_objects:
            cnode.destroy_resources()
            cnode.removeNode()
        self.compound_objects = []

    def make_attachment_graph(self):
        if not self.contact_bodies:
            return None
        n = len(self.contact_bodies)
        mtx = np.zeros((n, n), dtype="i")
        for (i, j), _ in self.attached_pairs:
            # i = self.contact_bodies.index(pair[0])
            # j = self.contact_bodies.index(pair[1])
            mtx[i, j] = 1
            # mtx[j, i] = 1
        graph = nx.from_numpy_matrix(mtx)
        return graph

    def attach_pair(self, pair, f_on):
        """ Adds/removes physical attachment between a pair of nodes."""
        # Get the connected subgroups.
        graph = self.make_attachment_graph()
        sgs = [sg for sg in nx.connected_components(graph) if len(sg) > 1]
        self.reset_compounds()
        # Iterate over subgroups, creating compound shapes.
        for sg in sgs:
            nodes = [self.contact_bodies[i] for i in sg]
            parents = [c.getParent() for c in nodes]
            self.compound_components.extend(zip(nodes, parents))
            cname = "+".join([str(i) for i in sorted(sg)])
            cnode = CPSO(cname)
            cnode.reparentTo(self.scene)
            cnode.add(nodes)
            cnode.init_tree(tags=("shape",))
            cnode.destroy_component_shapes()
            self.compound_objects.append(cnode)
