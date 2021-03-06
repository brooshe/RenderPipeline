

from panda3d.core import Vec3, NodePath, LineSegs, Vec4
from panda3d.core import OmniBoundingVolume
from panda3d.core import PTAInt
from LightType import LightType
from DebugObject import DebugObject
from ShaderStructArray import ShaderStructElement


class Light(ShaderStructElement):

    """ Abstract light class. All light types are subclasses
    of this class. This class handles all generic properties
    of a light. """

    def __init__(self):
        """ Constructs a new Light, subclasses have to call this """

        DebugObject.__init__(self, "AbstractLight")
        ShaderStructElement.__init__(self)
        self.debugNode = NodePath("LightDebug")
        self.visualizationNumSteps = 16
        self.dataNeedsUpdate = False
        self.castShadows = False
        self.debugEnabled = False
        self.bounds = OmniBoundingVolume()
        self.shadowSources = []
        self.lightType = self._getLightType()
        self.position = Vec3(0)
        self.color = Vec3(1)
        self.posterIndex = -1
        self.direction = Vec3(0)
        self.radius = 10.0
        self.typeName = ""
        self.sourceIndexes = PTAInt.emptyArray(6)
        self.attached = False
        self.shadowResolution = 512
        self.ambient = Vec3(0.2, 0.5, 0.8)

        for i in range(6):
            self.sourceIndexes[i] = -1

    @classmethod
    def getExposedAttributes(self):
        """ Returns the exposed attributes, required for the
        ShaderStructArray """
        return {
            "position": "vec3",
            "color": "vec3",
            "direction": "vec3",
            "posterIndex": "int",
            "lightType": "int",
            "radius": "float",
            "sourceIndexes": "array<int>(6)",
            "ambient": "vec3"
        }

    def getTypeName(self):
        """ Returns the internal id of the light-type, e.g. "PointLight" """
        return self.typeName

    def setShadowMapResolution(self, resolution):
        """ Attempts to set the resolution of the shadow soures. You
        cannot call this after the light got attached to the LightManager,
        as the shadow sources might already have a position in the
        shadow atlas """
        if self.attached:
            raise Exception(
                "You cannot change the resolution after the light got attached")
        self.shadowResolution = resolution

    def setAmbientColor(self, ambientColor):
        """ Sets the ambient color for lighting. The default is a bluish-gray.
        The ambient color will be added to the final light contribution """
        self.ambient = ambientColor
        self.queueUpdate()

    def setDirection(self, direction):
        """ Sets the direction of the light. This stores from which vector the light
        comes from. If your sun comes from totally above for example, this vector would
        be (0.0,0.0,1.0). The vector will get normalized, so you can for example pass your
        sun position. Only affects DirectionalLights """
        copied = Vec3(direction)
        copied.normalize()
        self.direction = copied
        self.queueUpdate()
        self.queueShadowUpdate()

    def getDirection(self):
        """ Returns the direction of the light """
        return self.direction

    def setRadius(self, radius):
        """ Sets the radius of the light. Only affects PointLights """
        self.radius = max(0.01, radius)
        self.queueUpdate()

    def getShadowSources(self):
        """ Returns a list of assigned shadow sources for this light """
        return self.shadowSources

    def hasShadows(self):
        """ Returns wheter the light casts shadows """
        return self.castShadows

    def setCastsShadows(self, shadows=True):
        """ Sets wheter the light casts shadows or not """
        self.castShadows = shadows

        if self.castShadows:
            self._initShadowSources()
            self.shadowNeedsUpdate = True
        else:
            for source in self.shadowSources:
                del source
            self.shadowSources = []
            self.shadowNeedsUpdate = False

    def setPos(self, pos):
        """ Sets the position of the light. Does not affect
        directional lights """

        # If the position is very similar, don't update
        if (pos - self.position).length() > 0.001:
            self.position = pos
            self.queueUpdate()
            self.queueShadowUpdate()

    def getBounds(self):
        """ Returns the bounds of this light for culling """
        return self.bounds

    def setColor(self, col):
        """ Sets the color of the light """
        self.color = col
        self.queueUpdate()

    def needsUpdate(self):
        """ Wheter the light data is up-to-date or needs an update """
        return self.dataNeedsUpdate

    def needsShadowUpdate(self):
        """ Wheter the light shadow map is up-to-date or needs an update """

        # no update needed if we have no shadows
        if not self.castShadows:
            return False

        for source in self.shadowSources:
            if not source.isValid():
                return True

        return False

    def queueUpdate(self):
        """ Queues a light update, means in the next frame the light
        data will update """
        self.dataNeedsUpdate = True

    def queueShadowUpdate(self):
        """ Queues a shadow update, means invalidating all shadow sources and
        adding to the shadow-map update queue, beeing processed as fast as
        possible """
        self.shadowNeedsUpdate = True

        for source in self.shadowSources:
            source.invalidate()

    def performUpdate(self):
        """ Recomputes the light data """
        self.dataNeedsUpdate = False
        self._computeAdditionalData()
        self._computeLightBounds()

        if self.castShadows:
            self._updateShadowSources()

        if self.debugEnabled:
            self._updateDebugNode()

        self.onPropertyChanged()

    def performShadowUpdate(self):
        """ Computes which shadow sources need an update and returns these """
        self._updateShadowSources()
        queued = []
        for source in self.shadowSources:
            if not source.isValid():
                queued.append(source)
        self.shadowNeedsUpdate = not len(queued) < 1
        return queued

    def attachDebugNode(self, parent):
        """ Attachs a debug node to parent which shows the bounds of the light.
        VERY SLOW. USE ONLY FOR DEBUGGING """
        self.debugNode.reparentTo(parent)
        self.debugEnabled = True
        self._updateDebugNode()

    def setSourceIndex(self, sourceId, index):
        """ Sets the global shadow source index for the given source """
        self.sourceIndexes[sourceId] = index

    def _addShadowSource(self, source):
        """ Adds a shadow source to the list of updating shadow sources """
        if source in self.shadowSources:
            self.warning("Shadow source already exists!")
            return

        self.shadowSources.append(source)
        self.queueShadowUpdate()

    def _computeLightBounds(self):
        """ Child classes should compute the light bounds here """
        raise NotImplementedError()

    def _updateDebugNode(self):
        """ Child classes should update the debug node here """
        raise NotImplementedError()

    def _computeAdditionalData(self):
        """ If child classes need to compute anything fancy, do it here """
        raise NotImplementedError()

    def _getLightType(self):
        """ Child classes have to implement this and
        return the correct type """
        return LightType.NoType

    def _initShadowSources(self):
        """ Child classes should spawn their shadow sources here """
        raise NotImplementedError()

    def _updateShadowSources(self):
        """ Child classes should reposition their shadow sources here """
        raise NotImplementedError()

    def _createDebugLine(self, points, connectToEnd=False):
        """ Helper for visualizing the light bounds.
        Draws a line trough all points. When connectToEnd is true,
        the last point will get connected to the first point. """
        segs = LineSegs()
        segs.setThickness(1.0)
        segs.setColor(Vec4(1, 1, 0, 1))

        segs.moveTo(points[0])

        for point in points[1:]:
            segs.drawTo(point)

        if connectToEnd:
            segs.drawTo(points[0])

        return NodePath(segs.create())

    def __repr__(self):
        """ Generates a string representation of this instance """
        return "AbstractLight[]"
