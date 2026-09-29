import QtQuick
import QtQuick3D

CustomMaterial {
    property url tcFragmentShader: ""
    property real tcTime: 0.0

    shadingMode: CustomMaterial.Shaded
    cullMode: Material.BackFaceCulling
    fragmentShader: tcFragmentShader
}
