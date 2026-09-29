import QtQuick
import QtQuick3D
import QtQuick3D.Helpers
import TechConnector 1.0

Rectangle {
    id: root
    color: "#090e14"
    property color sceneClearColor: "#090e14"
    property color keyLightColor: "#fff2db"
    property real keyLightBrightness: 1.15
    property real keyLightEulerX: -38
    property real keyLightEulerY: -28
    property color fillLightColor: "#a9c9ff"
    property real fillLightBrightness: 0.45

    property vector3d cameraEye: Qt.vector3d(0, 1.2, 6)
    property vector3d cameraTarget: Qt.vector3d(0, 0, 0)
    property real cameraFov: 45
    property real cameraAspect: 0
    property color materialColor: "#7d91aa"
    property real materialRoughness: 0.5
    property real materialMetalness: 0.0
    property real materialOpacity: 1.0
    property real materialTransmission: 0.0
    property real materialIor: 1.5
    property real materialThickness: 0.0
    property real materialClearcoat: 0.0
    property color materialAttenuationColor: "#ffffff"
    property real materialAttenuationDistance: 1000.0
    property url baseColorTexture: ""
    property url normalTexture: ""
    property url roughnessTexture: ""
    property url metalnessTexture: ""
    property url emissionTexture: ""
    property url opacityTexture: ""
    property color materialEmission: "#000000"
    property url environmentTexture: ""
    property real environmentExposure: 1.0
    property bool skinReady: false
    property real skinMatrixHeight: 1
    property real skinInfluenceTextureWidth: 1
    property real skinInfluenceTextureHeight: 1
    property real skinMaxInfluencePairs: 1
    property var skinMaterialDescriptors: []
    property var skinMaterialObjects: []
    property real effectTransmission: 0.92
    property real effectIor: 1.33
    property real effectThickness: 0.18
    property real effectRoughness: 0.06
    property real effectClearcoat: 0.45
    property color effectAttenuationColor: "#b8e8ff"
    property real effectAttenuationDistance: 2.0

    function rebuildSkinMaterials() {
        for (let index = 0; index < skinMaterialObjects.length; ++index)
            skinMaterialObjects[index].destroy()
        let created = []
        let descriptors = skinMaterialDescriptors.length > 0 ? skinMaterialDescriptors : [{
            color: root.materialColor,
            roughness: root.materialRoughness,
            metalness: root.materialMetalness,
            opacity: 1.0,
            emission: "#000000",
            baseColorTexture: "",
            useBaseColorTexture: false,
            normalTexture: "", useNormalTexture: false,
            roughnessTexture: "", useRoughnessTexture: false,
            metalnessTexture: "", useMetalnessTexture: false,
            emissionTexture: "", useEmissionTexture: false,
            opacityTexture: "", useOpacityTexture: false
        }]
        for (let index = 0; index < descriptors.length; ++index) {
            let descriptor = descriptors[index]
            let material = skinMaterialFactory.createObject(skinModel, {
                tcBaseColor: descriptor.color,
                tcRoughness: descriptor.roughness,
                tcMetalness: descriptor.metalness,
                tcOpacity: descriptor.opacity,
                tcEmission: descriptor.emission,
                tcBaseColorTexture: descriptor.baseColorTexture,
                tcUseBaseColorTexture: descriptor.useBaseColorTexture,
                tcNormalTexture: descriptor.normalTexture,
                tcUseNormalTexture: descriptor.useNormalTexture,
                tcRoughnessTexture: descriptor.roughnessTexture,
                tcUseRoughnessTexture: descriptor.useRoughnessTexture,
                tcMetalnessTexture: descriptor.metalnessTexture,
                tcUseMetalnessTexture: descriptor.useMetalnessTexture,
                tcEmissionTexture: descriptor.emissionTexture,
                tcUseEmissionTexture: descriptor.useEmissionTexture,
                tcOpacityTexture: descriptor.opacityTexture,
                tcUseOpacityTexture: descriptor.useOpacityTexture,
                tcMatrixHeight: root.skinMatrixHeight,
                tcInfluenceTextureWidth: root.skinInfluenceTextureWidth,
                tcInfluenceTextureHeight: root.skinInfluenceTextureHeight,
                tcMaxInfluencePairs: root.skinMaxInfluencePairs,
                tcInfluenceData: skinInfluenceTextureData,
                tcMatrixData: skinMatrixTextureData
            })
            if (material)
                created.push(material)
        }
        skinMaterialObjects = created
        skinModel.materials = created
    }

    onSkinMaterialDescriptorsChanged: Qt.callLater(rebuildSkinMaterials)
    onSkinMatrixHeightChanged: {
        for (let index = 0; index < skinMaterialObjects.length; ++index)
            skinMaterialObjects[index].tcMatrixHeight = skinMatrixHeight
    }
    onSkinInfluenceTextureWidthChanged: {
        for (let index = 0; index < skinMaterialObjects.length; ++index)
            skinMaterialObjects[index].tcInfluenceTextureWidth = skinInfluenceTextureWidth
    }
    onSkinInfluenceTextureHeightChanged: {
        for (let index = 0; index < skinMaterialObjects.length; ++index)
            skinMaterialObjects[index].tcInfluenceTextureHeight = skinInfluenceTextureHeight
    }
    onSkinMaxInfluencePairsChanged: {
        for (let index = 0; index < skinMaterialObjects.length; ++index)
            skinMaterialObjects[index].tcMaxInfluencePairs = skinMaxInfluencePairs
    }

    View3D {
        objectName: "sceneView"
        anchors.centerIn: parent
        width: root.cameraAspect > 0 ? Math.min(root.width, root.height * root.cameraAspect) : root.width
        height: root.cameraAspect > 0 ? Math.min(root.height, root.width / root.cameraAspect) : root.height
        renderMode: View3D.Offscreen

        environment: ExtendedSceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: root.sceneClearColor
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
            tonemapMode: SceneEnvironment.TonemapModeAces
            temporalAAEnabled: true
            glowEnabled: true
            glowStrength: 1.25
            glowBloom: 0.35
            glowHDRMinimumValue: 0.8
            ditheringEnabled: true
            aoEnabled: true
            aoStrength: 35
            probeExposure: root.environmentExposure
            lightProbe: root.environmentTexture.toString().length > 0 ? environmentProbe : null
        }

        Texture {
            id: environmentProbe
            source: root.environmentTexture
            generateMipmaps: true
            minFilter: Texture.LinearMipMapLinear
            magFilter: Texture.Linear
        }

        Node {
            id: sceneRoot

            Node {
                id: cameraTargetNode
                position: root.cameraTarget
            }

            PerspectiveCamera {
                id: sceneCamera
                position: root.cameraEye
                fieldOfView: root.cameraFov
                fieldOfViewOrientation: PerspectiveCamera.Vertical
                clipNear: 0.01
                clipFar: 100000
                lookAtNode: cameraTargetNode
            }

            DirectionalLight {
                eulerRotation.x: root.keyLightEulerX
                eulerRotation.y: root.keyLightEulerY
                brightness: root.keyLightBrightness
                color: root.keyLightColor
                castsShadow: true
                shadowFactor: 35
            }

            DirectionalLight {
                eulerRotation.x: 35
                eulerRotation.y: 145
                brightness: root.fillLightBrightness
                color: root.fillLightColor
            }

            Model {
                geometry: DynamicSceneGeometry {
                    objectName: "sceneGeometry"
                }
                materials: [PrincipledMaterial {
                    baseColor: root.materialColor
                    roughness: root.materialRoughness
                    metalness: root.materialMetalness
                    opacity: root.materialOpacity
                    alphaMode: root.materialOpacity < 0.999 ? PrincipledMaterial.Blend : PrincipledMaterial.Opaque
                    transmissionFactor: root.materialTransmission
                    indexOfRefraction: root.materialIor
                    thicknessFactor: root.materialThickness
                    clearcoatAmount: root.materialClearcoat
                    attenuationColor: root.materialAttenuationColor
                    attenuationDistance: root.materialAttenuationDistance
                    cullMode: Material.BackFaceCulling
                    baseColorMap: Texture {
                        source: root.baseColorTexture
                        generateMipmaps: true
                        minFilter: Texture.LinearMipMapLinear
                        magFilter: Texture.Linear
                    }
                    normalMap: Texture {
                        source: root.normalTexture
                        generateMipmaps: true
                        minFilter: Texture.LinearMipMapLinear
                        magFilter: Texture.Linear
                    }
                    roughnessMap: Texture {
                        source: root.roughnessTexture
                        generateMipmaps: true
                        minFilter: Texture.LinearMipMapLinear
                        magFilter: Texture.Linear
                    }
                    metalnessMap: Texture {
                        source: root.metalnessTexture
                        generateMipmaps: true
                        minFilter: Texture.LinearMipMapLinear
                        magFilter: Texture.Linear
                    }
                    emissiveFactor: Qt.vector3d(root.materialEmission.r, root.materialEmission.g, root.materialEmission.b)
                    emissiveMap: Texture {
                        source: root.emissionTexture
                        generateMipmaps: true
                        minFilter: Texture.LinearMipMapLinear
                        magFilter: Texture.Linear
                    }
                    opacityMap: Texture {
                        source: root.opacityTexture
                        generateMipmaps: true
                        minFilter: Texture.LinearMipMapLinear
                        magFilter: Texture.Linear
                    }
                }]
            }

            Model {
                geometry: DynamicEffectGeometry {
                    objectName: "effectGeometry"
                }
                castsShadows: false
                receivesShadows: true
                materials: [PrincipledMaterial {
                    baseColor: "#ffffff"
                    vertexColorsEnabled: true
                    lighting: PrincipledMaterial.NoLighting
                    alphaMode: PrincipledMaterial.Blend
                    cullMode: Material.NoCulling
                    baseColorMap: Texture {
                        textureData: RadialEffectTextureData {}
                        generateMipmaps: true
                        minFilter: Texture.LinearMipMapLinear
                        magFilter: Texture.Linear
                    }
                }]
            }

            Model {
                geometry: DynamicEffectGeometry {
                    objectName: "effectAlphaGeometry"
                }
                castsShadows: false
                receivesShadows: true
                materials: [PrincipledMaterial {
                    baseColor: "#ffffff"
                    vertexColorsEnabled: true
                    lighting: PrincipledMaterial.NoLighting
                    alphaMode: PrincipledMaterial.Blend
                    cullMode: Material.NoCulling
                    baseColorMap: Texture {
                        textureData: RadialEffectTextureData {}
                        generateMipmaps: true
                        minFilter: Texture.LinearMipMapLinear
                        magFilter: Texture.Linear
                    }
                }]
            }

            Model {
                geometry: DynamicEffectGeometry {
                    objectName: "effectRefractiveGeometry"
                }
                castsShadows: false
                receivesShadows: true
                materials: [PrincipledMaterial {
                    baseColor: "#b8e8ff"
                    vertexColorsEnabled: true
                    lighting: PrincipledMaterial.FragmentLighting
                    alphaMode: PrincipledMaterial.Blend
                    cullMode: Material.NoCulling
                    roughness: root.effectRoughness
                    specularAmount: 1.0
                    transmissionFactor: root.effectTransmission
                    thicknessFactor: root.effectThickness
                    indexOfRefraction: root.effectIor
                    clearcoatAmount: root.effectClearcoat
                    attenuationColor: root.effectAttenuationColor
                    attenuationDistance: root.effectAttenuationDistance
                    baseColorMap: Texture {
                        textureData: RadialEffectTextureData {}
                        generateMipmaps: true
                        minFilter: Texture.LinearMipMapLinear
                        magFilter: Texture.Linear
                    }
                }]
            }

            Model {
                geometry: DynamicEffectMeshGeometry {
                    objectName: "effectMeshGeometry"
                }
                instancing: DynamicEffectInstancing {
                    objectName: "effectMeshInstancing"
                }
                castsShadows: true
                receivesShadows: true
                materials: [PrincipledMaterial {
                    baseColor: "#ffffff"
                    vertexColorsEnabled: true
                    lighting: PrincipledMaterial.FragmentLighting
                    roughness: 0.48
                    specularAmount: 0.7
                    cullMode: Material.NoCulling
                }]
            }

            Model {
                id: skinModel
                visible: root.skinReady
                geometry: DynamicSkinnedSceneGeometry {
                    objectName: "skinGeometry"
                }
                materials: []
            }

            DynamicRgba32TextureData {
                id: skinInfluenceTextureData
                objectName: "skinInfluenceTexture"
            }

            DynamicRgba32TextureData {
                id: skinMatrixTextureData
                objectName: "skinMatrixTexture"
            }

            Component {
                id: skinMaterialFactory
                ExactEightSkinMaterial {}
            }

        }
    }
}
