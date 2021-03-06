
from panda3d.core import Vec3
from panda3d.core import Shader
from BetterShader import BetterShader
from DebugObject import DebugObject
from Globals import Globals
from RenderTarget import RenderTarget
from TextureDebugger import TextureDebugger
from panda3d.core import PTAFloat, PTALVecBase3f

from direct.stdpy.file import isdir

# need legacy makedirs here
from os import makedirs


class Scattering(DebugObject):

    """ This class provides functions to precompute and apply
    atmospheric scattering """

    def __init__(self):
        """ Creates a new Scattering object with default settings """
        DebugObject.__init__(self, "AtmosphericScattering")

        self.settings = {
            "radiusGround": 6360.0,
            "radiusAtmosphere": 6420.0,
            "averageGroundReflectance": 0.1,   # AVERAGE_GROUND_REFLECTANCE
            "rayleighFactor": 8.0,  # HR
            "betaRayleigh": Vec3(5.8e-3, 1.35e-2, 3.31e-2),  # betaR
            "mieFactor": 1.2,  # HM
            "betaMieScattering": Vec3(4e-3),  # betaMSca
            "betaMieScatteringAdjusted": (Vec3(2e-3) * (1.0 / 0.9)),
            "mieG": 0.8,  # mieG
            "transmittanceNonLinear": True,
            "inscatterNonLinear": True,

            # Parameters to adjust rendering of the atmosphere.
            # The position is computed by:
            # (inputPosition-atmosphereOffset) * atmosphereScale
            "atmosphereOffset": Vec3(0),
            "atmosphereScale": Vec3(1)

        }
        self.settingsPTA = {}
        self.targets = {}
        self.textures = {}
        self.writeOutput = False
        self.precomputed = False

        if self.writeOutput and not isdir("ScatteringDump"):
            try:
                makedirs("ScatteringDump")
            except:
                self.debug("Failed to create dump dir!")
                self.writeOutput = False

    def _generatePTAs(self):
        self.debug("Generating PTAs ..")
        for settingName, settingValue in self.settings.items():
            if type(settingValue) == float:
                self.settingsPTA[settingName] = PTAFloat.emptyArray(1)
                self.settingsPTA[settingName][0] = settingValue
            elif type(settingValue) == Vec3:
                self.settingsPTA[settingName] = PTALVecBase3f.emptyArray(1)
                self.settingsPTA[settingName][0] = settingValue
            elif type(settingValue) == bool:
                # no pta bool yet
                self.settingsPTA[settingName] = settingValue
            else:
                self.warn("Unkown type:", settingName, type(settingValue))

    def adjustSetting(self, name, value):
        """ This can be used to adjust a setting after precomputing """

        if not self.precomputed:
            self.warn("Cannot use adjustSetting when not precomputed yet")
            return

        if name in self.settingsPTA:
            if type(value) not in [float, Vec3]:
                self.warn("You cannot change this value in realtime. "
                          "Only floats and vec3 are supported.")
                return
            self.settingsPTA[name][0] = value

    def _executePrecompute(self):
        """ Executes the precomputation for the scattering """

        # Disable all display regions - otherwise the shader inputs are
        # required too early
        disabledWindows = []
        for window in Globals.base.graphicsEngine.getWindows():
            window.setActive(False)
            disabledWindows.append(window)

        # create ptas
        self._generatePTAs()

        self.debug(
            "Disabled", len(disabledWindows), " windows while rendering")

        # Transmittance
        self.targets['transmittance'] = self._createRT(
            "Transmittance", 256, 64, aux=False, shaderName="Transmittance",
            layers=1)
        self._renderOneShot('transmittance')

        # Irradiance1 (Produces DeltaE Texture)
        self.targets['irradiance1'] = self._createRT(
            "Irradiance1", 64, 16, aux=False, shaderName="Irradiance1",
            layers=1)
        self._renderOneShot('irradiance1')

        # Delta Scattering (Rayleigh + Mie)
        self.targets['deltaScattering'] = self._createRT(
            "DeltaScattering", 256, 128, aux=True, shaderName="Inscatter1",
            layers=32)
        self._renderOneShot('deltaScattering')

        # IrradianceE (Produces E Texture)
        self.targets['irradianceE'] = self._createRT(
            "IrradianceE", 64, 16, aux=False, shaderName="Combine2DTextures",
            layers=1)
        self.targets['irradianceE'].setShaderInput('factor1', 0.0)
        self.targets['irradianceE'].setShaderInput('factor2', 0.0)
        self._renderOneShot('irradianceE')

        # Copy delta scattering into inscatter texture S
        self.targets['combinedDeltaScattering'] = self._createRT(
            "CombinedDeltaScattering", 256, 128, aux=False,
            shaderName="CombineDeltaScattering", layers=32)
        self._renderOneShot('combinedDeltaScattering')

        for i in xrange(3):
            first = i == 0
            passIndex = "Pass" + str(i)

            # Compute Delta J texture
            inscatterSName = 'inscatterS' + passIndex
            self.targets[inscatterSName] = self._createRT(
                inscatterSName, 256, 128, aux=False, shaderName="InscatterS",
                layers=32)
            self.targets[inscatterSName].setShaderInput("first", first)
            self._renderOneShot(inscatterSName)

            # Compute the new Delta E Texture
            irradianceNName = 'irradianceN' + passIndex
            self.targets[irradianceNName] = self._createRT(
                irradianceNName, 64, 16, aux=False, shaderName="IrradianceN",
                layers=1)
            self.targets[irradianceNName].setShaderInput('first', first)
            self._renderOneShot(irradianceNName)

            # Replace old delta E texture
            self.textures['irradiance1Color'] = self.textures[
                irradianceNName + "Color"]

            # Compute new deltaSR
            inscatterNName = 'inscatterN' + passIndex
            self.targets[inscatterNName] = self._createRT(
                inscatterNName, 256, 128, aux=False, shaderName="InscatterN",
                layers=32)
            self.targets[inscatterNName].setShaderInput("first", first)
            self.targets[inscatterNName].setShaderInput(
                "deltaJSampler", self.textures[inscatterSName + "Color"])
            self._renderOneShot(inscatterNName)

            # Replace old deltaSR texture
            self.textures['deltaScatteringColor'] = self.textures[
                inscatterNName + "Color"]

            # Add deltaE into irradiance texture E
            irradianceAddName = 'irradianceAdd' + passIndex
            self.targets[irradianceAddName] = self._createRT(
                irradianceAddName, 64, 16, aux=False,
                shaderName="Combine2DTextures", layers=1)
            self.targets[irradianceAddName].setShaderInput('first', first)
            self.targets[irradianceAddName].setShaderInput(
                'source1', self.textures['irradianceEColor'])
            self.targets[irradianceAddName].setShaderInput(
                'source2', self.textures['irradiance1Color'])
            self.targets[irradianceAddName].setShaderInput('factor1', 1.0)
            self.targets[irradianceAddName].setShaderInput('factor2', 1.0)
            self._renderOneShot(irradianceAddName)

            self.textures['irradianceEColor'] = self.textures[
                irradianceAddName + "Color"]

            # Add deltaS into inscatter texture S
            inscatterAddName = 'inscatterAdd' + passIndex
            self.targets[inscatterAddName] = self._createRT(
                inscatterAddName, 256, 128, aux=False,
                shaderName="InscatterAdd", layers=32)
            self.targets[inscatterAddName].setShaderInput("first", first)
            self.targets[inscatterAddName].setShaderInput(
                "deltaSSampler", self.textures["deltaScatteringColor"])
            self.targets[inscatterAddName].setShaderInput(
                "addSampler", self.textures["combinedDeltaScatteringColor"])
            self._renderOneShot(inscatterAddName)

            self.textures['combinedDeltaScatteringColor'] = self.textures[
                inscatterAddName + "Color"]

        self.inscatterResult = self.textures['combinedDeltaScatteringColor']
        self.irradianceResult = self.textures['irradianceEColor']
        self.transmittanceResult = self.textures['transmittanceColor']

        # reenable windows
        for window in disabledWindows:
            window.setActive(True)

        self.debug("Finished precomputing, also reenabled windows.")
        self.precomputed = True

        # if self.writeOutput:
        #     base.graphicsEngine.extract_texture_data(
        #         self.irradianceResult, Globals.base.win.getGsg())
        #     self.irradianceResult.write(
        # "Data/Scattering/Result_Irradiance.png")
        #     base.graphicsEngine.extract_texture_data(
        #         self.inscatterResult, Globals.base.win.getGsg())
        # self.inscatterResult.write("Data/Scattering/Result_Inscatter.png")

    def getInscatterTexture(self):
        if not self.precomputed:
            self.error("Inscatter texture is not available yet! Precompute "
                       "the scattering first, with precompute()!")
            return
        return self.inscatterResult

    def getIrradianceTexture(self):
        if not self.precomputed:
            self.error("Irradiance texture is not available yet! Precompute "
                       "the scattering first, with precompute()!")
            return
        return self.irradianceResult

    def getTransmittanceResult(self):
        if not self.precomputed:
            self.error("Transmittance texture is not available yet! Precompute "
                       "the scattering first, with precompute()!")
            return
        return self.transmittanceResult

    def _renderOneShot(self, targetName):
        """ Renders a target and then deletes the target """
        target = self.targets[targetName]
        target.setActive(True)

        Globals.base.graphicsEngine.renderFrame()
        target.setActive(False)

        write = [(targetName + "Color", target.getColorTexture())]

        if target.hasAuxTextures():
            write.append((targetName + "Aux", target.getAuxTexture(0)))

        if self.writeOutput:
            for texname, tex in write:
                Globals.base.graphicsEngine.extract_texture_data(
                    tex, Globals.base.win.getGsg())

                dest = "ScatteringDump/" + texname + ".png"
                if tex.getZSize() > 1:
                    self.debg.debug3DTexture(tex, dest)
                else:
                    tex.write(dest)

        target.deleteBuffer()

    def _createRT(self, name, w, h, aux=False, shaderName="", layers=1):
        """ Internal shortcut to create a new render target """
        rt = RenderTarget("Scattering" + name)
        rt.setSize(w, h)
        rt.addColorTexture()
        rt.setColorBits(16)
        # rt.setEngine(self.engine)s

        if aux:
            rt.addAuxTextures(1)
            rt.setAuxBits(16)

        if layers > 1:
            rt.setLayers(layers)
        rt.prepareOffscreenBuffer()

        # self._engine.openWindows()

        sArgs = [
            "Scattering/DefaultVertex.vertex",
            "Scattering/" + shaderName + ".fragment"
        ]

        if layers > 1:
            sArgs.append("Scattering/DefaultGeometry.geometry")
        shader = Shader.load(Shader.SLGLSL, *sArgs)
        rt.setShader(shader)

        self._setInputs(rt, "options")

        lc = lambda x: x[0].lower() + x[1:]

        for key, tex in self.textures.items():
            rt.setShaderInput(lc(key), tex)

        self.textures[lc(name) + "Color"] = rt.getColorTexture()

        if aux:
            self.textures[lc(name) + "Aux"] = rt.getAuxTexture(0)

        return rt

    def bindTo(self, node, prefix):
        """ Sets all necessary inputs on a render target """
        if not self.precomputed:
            self.warn("You can only call bindTo after the scattering got "
                      "precomputed!")
            return

        self._setInputs(node, prefix)

    def _setInputs(self, node, prefix):
        """ Internal method to set necessary inputs on a render target """
        for key, val in self.settingsPTA.items():
            node.setShaderInput(prefix + "." + key, val)

    def precompute(self):
        """ Precomputes the scattering. This is required before you
        can use it """
        if self.precomputed:
            self.error("Scattering is already computed! You can only do this "
                       "once")
            return
        self.debug("Precomputing ..")

        if self.writeOutput:
            self.debg = TextureDebugger()
        self._executePrecompute()

        # write out transmittance tex

    def setSettings(self, settings):
        """ Sets the settings used for the precomputation. If a setting is not
        specified, the default is used """

        if self.precomputed:
            self.warn("You cannot use setSettings after precomputing! Use "
                      "adjustSetting instead!")
            return

        for key, val in settings.items():
            if key in self.settings:
                if type(val) == type(self.settings[key]):
                    self.settings[key] = val
                else:
                    self.warn(
                        "Wrong type for", key, "- should be", type(self.settings[key]))
            else:
                self.warn("Unrecognized setting:", key)
