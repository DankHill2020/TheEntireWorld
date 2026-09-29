import QtQuick
import QtQuick3D
import TechConnector 1.0

CustomMaterial {
    property color tcBaseColor: "#7d91aa"
    property real tcRoughness: 0.5
    property real tcMetalness: 0.0
    property real tcOpacity: 1.0
    property color tcEmission: "#000000"
    property url tcBaseColorTexture: ""
    property bool tcUseBaseColorTexture: false
    property url tcNormalTexture: ""
    property bool tcUseNormalTexture: false
    property url tcRoughnessTexture: ""
    property bool tcUseRoughnessTexture: false
    property url tcMetalnessTexture: ""
    property bool tcUseMetalnessTexture: false
    property url tcEmissionTexture: ""
    property bool tcUseEmissionTexture: false
    property url tcOpacityTexture: ""
    property bool tcUseOpacityTexture: false
    property real tcMatrixHeight: 1
    property real tcInfluenceTextureWidth: 1
    property real tcInfluenceTextureHeight: 1
    property real tcMaxInfluencePairs: 1
    property DynamicRgba32TextureData tcInfluenceData
    property DynamicRgba32TextureData tcMatrixData

    shadingMode: CustomMaterial.Shaded
    cullMode: Material.BackFaceCulling
    sourceBlend: tcOpacity < 1.0 ? CustomMaterial.SrcAlpha : CustomMaterial.NoBlend
    destinationBlend: tcOpacity < 1.0 ? CustomMaterial.OneMinusSrcAlpha : CustomMaterial.NoBlend
    vertexShader: "ExactEightSkin.vert"
    fragmentShader: "ExactEightSkin.frag"

    property TextureInput tcInfluenceTexture: TextureInput {
        texture: Texture {
            minFilter: Texture.Nearest
            magFilter: Texture.Nearest
            generateMipmaps: false
            textureData: tcInfluenceData
        }
    }
    property TextureInput tcMatrixTexture: TextureInput {
        texture: Texture {
            minFilter: Texture.Nearest
            magFilter: Texture.Nearest
            generateMipmaps: false
            textureData: tcMatrixData
        }
    }
    property TextureInput tcBaseColorMap: TextureInput {
        enabled: tcUseBaseColorTexture
        texture: Texture {
            source: tcBaseColorTexture
            generateMipmaps: true
            minFilter: Texture.LinearMipMapLinear
            magFilter: Texture.Linear
        }
    }
    property TextureInput tcNormalMap: TextureInput {
        enabled: tcUseNormalTexture
        texture: Texture { source: tcNormalTexture; generateMipmaps: true; minFilter: Texture.LinearMipMapLinear; magFilter: Texture.Linear }
    }
    property TextureInput tcRoughnessMap: TextureInput {
        enabled: tcUseRoughnessTexture
        texture: Texture { source: tcRoughnessTexture; generateMipmaps: true; minFilter: Texture.LinearMipMapLinear; magFilter: Texture.Linear }
    }
    property TextureInput tcMetalnessMap: TextureInput {
        enabled: tcUseMetalnessTexture
        texture: Texture { source: tcMetalnessTexture; generateMipmaps: true; minFilter: Texture.LinearMipMapLinear; magFilter: Texture.Linear }
    }
    property TextureInput tcEmissionMap: TextureInput {
        enabled: tcUseEmissionTexture
        texture: Texture { source: tcEmissionTexture; generateMipmaps: true; minFilter: Texture.LinearMipMapLinear; magFilter: Texture.Linear }
    }
    property TextureInput tcOpacityMap: TextureInput {
        enabled: tcUseOpacityTexture
        texture: Texture { source: tcOpacityTexture; generateMipmaps: true; minFilter: Texture.LinearMipMapLinear; magFilter: Texture.Linear }
    }
}
