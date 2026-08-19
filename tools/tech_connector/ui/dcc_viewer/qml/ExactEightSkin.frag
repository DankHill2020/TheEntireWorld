void MAIN()
{
    vec4 base = tcUseBaseColorTexture ? texture(tcBaseColorMap, UV0) : tcBaseColor;
    float opacity = tcOpacity * (tcUseOpacityTexture ? texture(tcOpacityMap, UV0).r : 1.0);
    BASE_COLOR = vec4(base.rgb, base.a * opacity);
    ROUGHNESS = tcUseRoughnessTexture ? texture(tcRoughnessMap, UV0).r : tcRoughness;
    METALNESS = tcUseMetalnessTexture ? texture(tcMetalnessMap, UV0).r : tcMetalness;
    EMISSIVE_COLOR = tcUseEmissionTexture ? texture(tcEmissionMap, UV0).rgb : tcEmission.rgb;
    if (tcUseNormalTexture) {
        vec3 tangentNormal = texture(tcNormalMap, UV0).xyz * 2.0 - 1.0;
        vec3 dpdx = dFdx(VAR_WORLD_POSITION);
        vec3 dpdy = dFdy(VAR_WORLD_POSITION);
        vec2 duvdx = dFdx(UV0);
        vec2 duvdy = dFdy(UV0);
        vec3 tangentRaw = dpdx * duvdy.y - dpdy * duvdx.y;
        vec3 binormalRaw = -dpdx * duvdy.x + dpdy * duvdx.x;
        if (dot(tangentRaw, tangentRaw) > 1.0e-12 && dot(binormalRaw, binormalRaw) > 1.0e-12) {
            vec3 tangent = normalize(tangentRaw);
            vec3 binormal = normalize(binormalRaw);
            NORMAL = normalize(mat3(tangent, binormal, normalize(NORMAL)) * tangentNormal);
        }
    }
}
