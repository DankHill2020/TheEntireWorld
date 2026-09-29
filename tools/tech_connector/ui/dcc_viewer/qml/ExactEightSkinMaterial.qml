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
    property var tcBaseColorTextureSource: ({})
    property bool tcUseBaseColorTexture: false
    property url tcNormalTexture: ""
    property var tcNormalTextureSource: ({})
    property bool tcUseNormalTexture: false
    property url tcRoughnessTexture: ""
    property var tcRoughnessTextureSource: ({})
    property bool tcUseRoughnessTexture: false
    property url tcMetalnessTexture: ""
    property var tcMetalnessTextureSource: ({})
    property bool tcUseMetalnessTexture: false
    property url tcEmissionTexture: ""
    property var tcEmissionTextureSource: ({})
    property bool tcUseEmissionTexture: false
    property url tcOpacityTexture: ""
    property var tcOpacityTextureSource: ({})
    property bool tcUseOpacityTexture: false
    property real tcMatrixHeight: 1
    property real tcInfluenceTextureWidth: 1
    property real tcInfluenceTextureHeight: 1
    property real tcMaxInfluencePairs: 1
    property DynamicRgba32TextureData tcInfluenceData
    property DynamicRgba32TextureData tcMatrixData
    property real tcMediaTimelineSeconds: 0.0
    property bool tcMediaTimelinePlaying: false

    MediaTextureSource { id: baseMedia; x: -10000; descriptor: tcBaseColorTextureSource; timelineSeconds: tcMediaTimelineSeconds; timelinePlaying: tcMediaTimelinePlaying }
    MediaTextureSource { id: normalMedia; x: -10000; descriptor: tcNormalTextureSource; timelineSeconds: tcMediaTimelineSeconds; timelinePlaying: tcMediaTimelinePlaying }
    MediaTextureSource { id: roughnessMedia; x: -10000; descriptor: tcRoughnessTextureSource; timelineSeconds: tcMediaTimelineSeconds; timelinePlaying: tcMediaTimelinePlaying }
    MediaTextureSource { id: metalnessMedia; x: -10000; descriptor: tcMetalnessTextureSource; timelineSeconds: tcMediaTimelineSeconds; timelinePlaying: tcMediaTimelinePlaying }
    MediaTextureSource { id: emissionMedia; x: -10000; descriptor: tcEmissionTextureSource; timelineSeconds: tcMediaTimelineSeconds; timelinePlaying: tcMediaTimelinePlaying }
    MediaTextureSource { id: opacityMedia; x: -10000; descriptor: tcOpacityTextureSource; timelineSeconds: tcMediaTimelineSeconds; timelinePlaying: tcMediaTimelinePlaying }

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
            source: baseMedia.animated ? "" : tcBaseColorTexture
            sourceItem: baseMedia.animated ? baseMedia : null
            generateMipmaps: true
            minFilter: Texture.LinearMipMapLinear
            magFilter: Texture.Linear
        }
    }
    property TextureInput tcNormalMap: TextureInput {
        enabled: tcUseNormalTexture
        texture: Texture { source: normalMedia.animated ? "" : tcNormalTexture; sourceItem: normalMedia.animated ? normalMedia : null; generateMipmaps: true; minFilter: Texture.LinearMipMapLinear; magFilter: Texture.Linear }
    }
    property TextureInput tcRoughnessMap: TextureInput {
        enabled: tcUseRoughnessTexture
        texture: Texture { source: roughnessMedia.animated ? "" : tcRoughnessTexture; sourceItem: roughnessMedia.animated ? roughnessMedia : null; generateMipmaps: true; minFilter: Texture.LinearMipMapLinear; magFilter: Texture.Linear }
    }
    property TextureInput tcMetalnessMap: TextureInput {
        enabled: tcUseMetalnessTexture
        texture: Texture { source: metalnessMedia.animated ? "" : tcMetalnessTexture; sourceItem: metalnessMedia.animated ? metalnessMedia : null; generateMipmaps: true; minFilter: Texture.LinearMipMapLinear; magFilter: Texture.Linear }
    }
    property TextureInput tcEmissionMap: TextureInput {
        enabled: tcUseEmissionTexture
        texture: Texture { source: emissionMedia.animated ? "" : tcEmissionTexture; sourceItem: emissionMedia.animated ? emissionMedia : null; generateMipmaps: true; minFilter: Texture.LinearMipMapLinear; magFilter: Texture.Linear }
    }
    property TextureInput tcOpacityMap: TextureInput {
        enabled: tcUseOpacityTexture
        texture: Texture { source: opacityMedia.animated ? "" : tcOpacityTexture; sourceItem: opacityMedia.animated ? opacityMedia : null; generateMipmaps: true; minFilter: Texture.LinearMipMapLinear; magFilter: Texture.Linear }
    }
}
