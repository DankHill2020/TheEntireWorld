mat4 tcBoneMatrix(int jointIndex)
{
    float y = (float(jointIndex) + 0.5) / tcMatrixHeight;
    return mat4(
        texture(tcMatrixTexture, vec2(0.125, y)),
        texture(tcMatrixTexture, vec2(0.375, y)),
        texture(tcMatrixTexture, vec2(0.625, y)),
        texture(tcMatrixTexture, vec2(0.875, y))
    );
}

vec4 tcInfluenceTexel(int texelIndex)
{
    int width = max(1, int(tcInfluenceTextureWidth));
    int x = texelIndex % width;
    int y = texelIndex / width;
    return texture(
        tcInfluenceTexture,
        vec2(
            (float(x) + 0.5) / tcInfluenceTextureWidth,
            (float(y) + 0.5) / tcInfluenceTextureHeight
        )
    );
}

void MAIN()
{
    mat4 skin = mat4(0.0);
    int texelOffset = int(UV1.x + 0.5);
    int influenceCount = int(UV1.y + 0.5);
    for (int pairIndex = 0; pairIndex < 16; ++pairIndex) {
        if (pairIndex >= int(tcMaxInfluencePairs) || pairIndex * 2 >= influenceCount)
            break;
        vec4 pair = tcInfluenceTexel(texelOffset + pairIndex);
        if (pair.y > 0.0)
            skin += pair.y * tcBoneMatrix(int(pair.x + 0.5));
        if (pairIndex * 2 + 1 < influenceCount && pair.w > 0.0)
            skin += pair.w * tcBoneMatrix(int(pair.z + 0.5));
    }
    vec4 skinned = skin * vec4(VERTEX, 1.0);
    VERTEX = skinned.xyz;
    NORMAL = normalize(transpose(inverse(mat3(skin))) * NORMAL);
}
