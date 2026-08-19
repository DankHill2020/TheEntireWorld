#include "tc_gpu_renderer.h"

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <limits>
#include <sstream>
#include <unordered_map>
#include <vector>

#if defined(_WIN32)
#include <d3d11.h>
#include <d3dcompiler.h>
#include <DirectXMath.h>
#include <wincodec.h>
#include <wrl/client.h>
#endif

namespace tc::runtime {

#if defined(_WIN32)
using Microsoft::WRL::ComPtr;
using namespace DirectX;

namespace {

struct Vertex { XMFLOAT3 position; XMFLOAT3 normal; XMFLOAT2 uv; };
struct Constants {
    XMFLOAT4X4 world;
    XMFLOAT4X4 view_projection;
    XMFLOAT4X4 light_view_projection;
    XMFLOAT4X4 previous_world;
    XMFLOAT4X4 previous_view_projection;
    XMFLOAT4 base_metallic;
    XMFLOAT4 light_roughness;
    XMFLOAT4 sun_color_intensity;
    XMFLOAT4 camera;
    XMFLOAT4 environment;
    XMFLOAT4 sky;
    XMFLOAT4 ground;
    XMFLOAT4 style;
    std::array<XMFLOAT4,8> bounce_position_radius;
    std::array<XMFLOAT4,8> bounce_color_intensity;
    XMFLOAT4 bounce_settings;
};

struct PostConstants {
    XMFLOAT4 temporal;
    XMFLOAT4 display;
};

struct SkyConstants {
    XMFLOAT4X4 inverse_view_projection;
    XMFLOAT4 camera;
    XMFLOAT4 sun_direction_radius;
    XMFLOAT4 sun_color_intensity;
    XMFLOAT4 sky;
    XMFLOAT4 ground;
    XMFLOAT4 atmosphere;
};

struct SkinConstants { std::uint32_t enabled{0}; std::uint32_t padding[3]{}; };
struct GpuSkinVertex {
    XMUINT4 joints0{};
    XMFLOAT4 weights0{};
    XMUINT4 joints1{};
    XMFLOAT4 weights1{};
    XMFLOAT4 rest_position{};
};

constexpr Vertex vertices[] = {
    {{-0.5F,-0.5F,-0.5F},{0,0,-1},{0,1}},{{0.5F,-0.5F,-0.5F},{0,0,-1},{1,1}},{{0.5F,0.5F,-0.5F},{0,0,-1},{1,0}},{{-0.5F,0.5F,-0.5F},{0,0,-1},{0,0}},
    {{-0.5F,-0.5F,0.5F},{0,0,1},{0,1}},{{0.5F,-0.5F,0.5F},{0,0,1},{1,1}},{{0.5F,0.5F,0.5F},{0,0,1},{1,0}},{{-0.5F,0.5F,0.5F},{0,0,1},{0,0}},
    {{-0.5F,-0.5F,-0.5F},{-1,0,0},{0,1}},{{-0.5F,0.5F,-0.5F},{-1,0,0},{1,1}},{{-0.5F,0.5F,0.5F},{-1,0,0},{1,0}},{{-0.5F,-0.5F,0.5F},{-1,0,0},{0,0}},
    {{0.5F,-0.5F,-0.5F},{1,0,0},{0,1}},{{0.5F,0.5F,-0.5F},{1,0,0},{1,1}},{{0.5F,0.5F,0.5F},{1,0,0},{1,0}},{{0.5F,-0.5F,0.5F},{1,0,0},{0,0}},
    {{-0.5F,-0.5F,-0.5F},{0,-1,0},{0,1}},{{-0.5F,-0.5F,0.5F},{0,-1,0},{1,1}},{{0.5F,-0.5F,0.5F},{0,-1,0},{1,0}},{{0.5F,-0.5F,-0.5F},{0,-1,0},{0,0}},
    {{-0.5F,0.5F,-0.5F},{0,1,0},{0,1}},{{-0.5F,0.5F,0.5F},{0,1,0},{1,1}},{{0.5F,0.5F,0.5F},{0,1,0},{1,0}},{{0.5F,0.5F,-0.5F},{0,1,0},{0,0}},
};
constexpr std::uint16_t indices[] = {0,2,1,0,3,2,4,5,6,4,6,7,8,10,9,8,11,10,12,13,14,12,14,15,16,18,17,16,19,18,20,21,22,20,22,23};

constexpr const char* shader_source = R"(
cbuffer Scene : register(b0) { matrix world; matrix viewProjection; matrix lightViewProjection; matrix previousWorld; matrix previousViewProjection; float4 baseMetallic; float4 lightRoughness; float4 sunColorIntensity; float4 cameraPosition; float4 environmentSettings; float4 skySettings; float4 groundSettings; float4 styleSettings; float4 bouncePositionRadius[8]; float4 bounceColorIntensity[8]; float4 bounceSettings; };
cbuffer Post : register(b1) { float4 temporalSettings; float4 displaySettings; };
cbuffer Sky : register(b2) { matrix inverseViewProjection; float4 skyCamera; float4 skySunDirectionRadius; float4 skySunColorIntensity; float4 authoredSky; float4 authoredGround; float4 atmosphereSettings; };
cbuffer Skin : register(b3) { uint skinEnabled; uint3 skinPadding; };
struct SkinVertex { uint4 joints0; float4 weights0; uint4 joints1; float4 weights1; float4 restPosition; };
StructuredBuffer<SkinVertex> skinVertices : register(t10);
StructuredBuffer<float4x4> skinPalette : register(t11);
struct VSIn { float3 position:POSITION; float3 normal:NORMAL; float2 uv:TEXCOORD0; uint vertexId:SV_VertexID; };
struct VSOut { float4 position:SV_POSITION; float3 worldPosition:TEXCOORD0; float3 normal:TEXCOORD1; float4 lightPosition:TEXCOORD2; float2 uv:TEXCOORD3; float4 currentClip:TEXCOORD4; float4 previousClip:TEXCOORD5; };
void ResolveSkin(VSIn input,out float3 position,out float3 normal){position=input.position;normal=input.normal;if(skinEnabled==0)return;SkinVertex skin=skinVertices[input.vertexId];float4 source=float4(skin.restPosition.xyz,1);float4 skinned=0;float3 skinnedNormal=0;float total=0;[unroll]for(uint i=0;i<4;i++){float weight=skin.weights0[i];if(weight>0){float4x4 joint=skinPalette[skin.joints0[i]];skinned+=mul(source,joint)*weight;skinnedNormal+=mul(float4(input.normal,0),joint).xyz*weight;total+=weight;}}[unroll]for(uint i=0;i<4;i++){float weight=skin.weights1[i];if(weight>0){float4x4 joint=skinPalette[skin.joints1[i]];skinned+=mul(source,joint)*weight;skinnedNormal+=mul(float4(input.normal,0),joint).xyz*weight;total+=weight;}}if(total>0.000001){position=skinned.xyz/total;normal=normalize(skinnedNormal/total);}}
VSOut VSMain(VSIn input) { VSOut o;float3 localPosition,localNormal;ResolveSkin(input,localPosition,localNormal);float4 wp=mul(float4(localPosition,1),world); o.position=mul(wp,viewProjection); o.currentClip=o.position; o.previousClip=mul(mul(float4(localPosition,1),previousWorld),previousViewProjection); o.worldPosition=wp.xyz; o.normal=normalize(mul(float4(localNormal,0),world).xyz); o.lightPosition=mul(wp,lightViewProjection); o.uv=input.uv; return o; }
float DistributionGGX(float3 N,float3 H,float r){float a=r*r;float a2=a*a;float n=max(dot(N,H),0);float d=n*n*(a2-1)+1;return a2/max(0.001,3.14159265*d*d);}
float GeometrySchlick(float n,float r){float k=(r+1)*(r+1)/8;return n/(n*(1-k)+k);}
float3 ACES(float3 x){float a=2.51,b=0.03,c=2.43,d=0.59,e=0.14;return saturate((x*(a*x+b))/(x*(c*x+d)+e));}
float2 LatLong(float3 d){d=normalize(d);return float2(atan2(d.z,d.x)/6.2831853+0.5,acos(clamp(d.y,-1,1))/3.14159265);}
Texture2D shadowMap:register(t0); Texture2D baseMap:register(t1); Texture2D normalMap:register(t2); Texture2D roughnessMap:register(t3); Texture2D metallicMap:register(t4); Texture2D emissionMap:register(t5); Texture2D environmentMap:register(t6);
Texture2D currentFrame:register(t7); Texture2D motionMap:register(t8); Texture2D historyMap:register(t9);
SamplerComparisonState shadowSampler:register(s0); SamplerState materialSampler:register(s1);
float FilterShadow(float4 lightPosition,float ndl){float3 p=lightPosition.xyz/lightPosition.w;float2 uv=float2(p.x*0.5+0.5,-p.y*0.5+0.5);if(any(uv<0)||any(uv>1)||p.z<0||p.z>1)return 1;float bias=max(0.0008*(1-ndl),0.00018);float result=0,filterRadius=max(1,styleSettings.w);[unroll]for(int y=-2;y<=2;y++){[unroll]for(int x=-2;x<=2;x++){result+=shadowMap.SampleCmpLevelZero(shadowSampler,uv+float2(x,y)*filterRadius/2048.0,p.z-bias);}}return result/25.0;}
struct SurfaceOut { float4 color:SV_TARGET0; float2 motion:SV_TARGET1; };
float3 IndirectLight(float3 base,float3 N,float3 V,float3 worldPosition,float rough,float metal,float3 F){
    if(environmentSettings.z<0.5)return 0;
    float hemisphereWeight=saturate(N.y*0.5+0.5);
    float3 hemisphere=lerp(groundSettings.rgb,skySettings.rgb,hemisphereWeight)*base*(1-metal);
    float3 dynamicBounce=0;[unroll]for(int source=0;source<8;source++){if(source>=int(bounceSettings.x))break;float3 delta=bouncePositionRadius[source].xyz-worldPosition;float distanceSquared=dot(delta,delta);if(distanceSquared>1e-6){float distance=sqrt(distanceSquared),radius=max(0.001,bouncePositionRadius[source].w);float attenuation=pow(saturate(1-distance/radius),2);dynamicBounce+=bounceColorIntensity[source].rgb*max(dot(N,delta/distance),0)*attenuation*bounceColorIntensity[source].w;}}
    if(environmentSettings.z<1.5)return hemisphere*environmentSettings.w+dynamicBounce;
    float3 envDiffuse=environmentMap.SampleLevel(materialSampler,LatLong(N),rough*5).rgb*base*(1-metal);
    float3 envSpec=environmentMap.SampleLevel(materialSampler,LatLong(reflect(-V,N)),rough*5).rgb*F;
    return (hemisphere*0.35+(envDiffuse+envSpec)*environmentSettings.x)*environmentSettings.w+dynamicBounce;
}
float3 ShadeSurface(float3 base,float3 N,float3 V,float3 worldPosition,float rough,float metal,float shadow,float3 emission){
    if(environmentSettings.y>2.5)return base+emission;
    float3 L=normalize(-lightRoughness.xyz),H=normalize(V+L);
    float rawNdl=dot(N,L),ndl=max(rawNdl,0),ndv=max(dot(N,V),0.001),ndh=max(dot(N,H),0),hdv=max(dot(H,V),0);
    float3 F0=lerp(0.04.xxx,base,metal),F=F0+(1-F0)*pow(1-hdv,5);
    float3 indirect=IndirectLight(base,N,V,worldPosition,rough,metal,F);
    if(environmentSettings.y>1.5){
        float bands=max(2,styleSettings.x),band=floor(saturate(rawNdl)*bands)/(bands-1);
        float graphicShadow=lerp(0.3,1.0,step(0.55,shadow));
        float3 direct=base*band*graphicShadow*sunColorIntensity.rgb*sunColorIntensity.w;
        float3 specular=step(0.82+rough*0.12,ndh)*F*sunColorIntensity.rgb*sunColorIntensity.w;
        float rim=step(0.62,1-ndv)*styleSettings.y;
        return indirect+direct+specular+rim*skySettings.rgb+emission;
    }
    float distribution=DistributionGGX(N,H,rough);
    float geometry=GeometrySchlick(ndv,rough)*GeometrySchlick(ndl,rough);
    float3 specular=F*distribution*geometry/max(0.004,4*ndv*ndl);
    float3 diffuse=base*(1-metal)/3.14159265;
    if(environmentSettings.y>0.5){
        float wrapped=smoothstep(-0.2,0.85,rawNdl),rim=pow(saturate(1-ndv),3)*styleSettings.y;
        float3 direct=(base*(1-metal)*wrapped+specular*ndl)*sunColorIntensity.rgb*sunColorIntensity.w*shadow;
        return indirect+direct+rim*skySettings.rgb+emission;
    }
    return indirect+(diffuse+specular)*ndl*sunColorIntensity.rgb*sunColorIntensity.w*shadow+emission;
}
SurfaceOut PSMain(VSOut input) {
    SurfaceOut output;float3 base=baseMetallic.xyz*baseMap.Sample(materialSampler,input.uv).rgb;
    float3 N=normalize(input.normal),mapN=normalMap.Sample(materialSampler,input.uv).xyz*2-1;
    float3 dp1=ddx(input.worldPosition),dp2=ddy(input.worldPosition);float2 duv1=ddx(input.uv),duv2=ddy(input.uv);
    float3 T=normalize(dp1*duv2.y-dp2*duv1.y),B=normalize(-dp1*duv2.x+dp2*duv1.x);N=normalize(T*mapN.x+B*mapN.y+N*mapN.z);
    float3 V=normalize(cameraPosition.xyz-input.worldPosition);float rough=max(lightRoughness.w*roughnessMap.Sample(materialSampler,input.uv).r,0.045);
    float metal=saturate(baseMetallic.w*metallicMap.Sample(materialSampler,input.uv).r),ndl=max(dot(N,normalize(-lightRoughness.xyz)),0);
    float shadow=lerp(1.0,FilterShadow(input.lightPosition,ndl),styleSettings.z);float3 emission=emissionMap.Sample(materialSampler,input.uv).rgb;
    output.color=float4(ShadeSurface(base,N,V,input.worldPosition,rough,metal,shadow,emission)*cameraPosition.w,1);
    float2 current=input.currentClip.xy/max(input.currentClip.w,0.0001),previous=input.previousClip.xy/max(input.previousClip.w,0.0001);
    output.motion=(current-previous)*float2(0.5,-0.5);return output;
}
struct PostOut { float4 position:SV_POSITION; float2 uv:TEXCOORD0; };
PostOut VSPost(uint vertexId:SV_VertexID){PostOut output;float2 uv=float2((vertexId<<1)&2,vertexId&2);output.uv=uv;output.position=float4(uv*float2(2,-2)+float2(-1,1),0,1);return output;}
float4 PSAtmosphere(PostOut input):SV_TARGET {
    float2 ndc=float2(input.uv.x*2-1,1-input.uv.y*2);float4 farPoint=mul(float4(ndc,1,1),inverseViewProjection);
    float3 direction=normalize(farPoint.xyz/max(1e-6,farPoint.w)-skyCamera.xyz);float up=direction.y;
    float3 sunDirection=normalize(-skySunDirectionRadius.xyz);float sunAmount=saturate(dot(direction,sunDirection));
    float density=max(0.01,atmosphereSettings.x),haze=max(0,atmosphereSettings.y),falloff=max(0.5,atmosphereSettings.z);
    float horizon=pow(saturate(1-abs(up)),falloff);float airMass=1/max(0.06,up+0.16);
    float3 rayleigh=float3(0.16,0.36,1.0)*(1-exp(-density*airMass*0.22));
    float mie=pow(sunAmount,8)*horizon*haze+pow(sunAmount,64)*haze*0.2;
    float day=saturate(sunDirection.y*4+0.35);float3 skyColor=authoredSky.rgb*(0.22+0.78*day)+rayleigh*skySunColorIntensity.rgb;
    skyColor+=mie*float3(1.0,0.58,0.28)*skySunColorIntensity.w;
    float sunRadius=radians(max(0.01,skySunDirectionRadius.w));float sunDisk=smoothstep(cos(sunRadius*1.8),cos(sunRadius*0.45),sunAmount);
    skyColor+=sunDisk*skySunColorIntensity.rgb*skySunColorIntensity.w*12.0;
    float groundBlend=smoothstep(-0.12,0.02,up);float3 groundColor=authoredGround.rgb*(0.35+0.65*day)+horizon*authoredSky.rgb*0.25;
    return float4(lerp(groundColor,skyColor,groundBlend)*skyCamera.w,1);
}
float4 PSTemporal(PostOut input):SV_TARGET {float2 velocity=motionMap.SampleLevel(materialSampler,input.uv,0).xy;float3 current=currentFrame.SampleLevel(materialSampler,input.uv,0).rgb;float3 minimum=current,maximum=current;[unroll]for(int y=-1;y<=1;y++){[unroll]for(int x=-1;x<=1;x++){float3 sampleValue=currentFrame.SampleLevel(materialSampler,input.uv+float2(x,y)*temporalSettings.xy,0).rgb;minimum=min(minimum,sampleValue);maximum=max(maximum,sampleValue);}}float2 historyUv=input.uv-velocity;float valid=temporalSettings.z*step(0,historyUv.x)*step(historyUv.x,1)*step(0,historyUv.y)*step(historyUv.y,1);float3 history=clamp(historyMap.SampleLevel(materialSampler,historyUv,0).rgb,minimum,maximum);return float4(lerp(current,history,temporalSettings.w*valid),1);}
float4 PSDisplay(PostOut input):SV_TARGET {float3 center=historyMap.SampleLevel(materialSampler,input.uv,0).rgb;float3 neighbors=0.25*(historyMap.SampleLevel(materialSampler,input.uv+float2(displaySettings.x,0),0).rgb+historyMap.SampleLevel(materialSampler,input.uv-float2(displaySettings.x,0),0).rgb+historyMap.SampleLevel(materialSampler,input.uv+float2(0,displaySettings.y),0).rgb+historyMap.SampleLevel(materialSampler,input.uv-float2(0,displaySettings.y),0).rgb);float3 sharpened=max(0,center+(center-neighbors)*displaySettings.z);return float4(pow(ACES(sharpened),1/2.2),1);}
float4 VSShadow(VSIn input):SV_POSITION { float3 position,normal;ResolveSkin(input,position,normal);return mul(mul(float4(position,1),world),lightViewProjection); }
)";

bool compile_shader(const char* entry, const char* profile, ComPtr<ID3DBlob>& blob, std::string& error) {
    ComPtr<ID3DBlob> messages;
    const HRESULT status = D3DCompile(shader_source, std::strlen(shader_source), "tc_runtime.hlsl", nullptr, nullptr, entry, profile,
                                      D3DCOMPILE_ENABLE_STRICTNESS, 0, &blob, &messages);
    if (FAILED(status)) {
        error = messages ? std::string(static_cast<const char*>(messages->GetBufferPointer()), messages->GetBufferSize()) : "D3D shader compilation failed.";
        return false;
    }
    return true;
}

}  // namespace

class GpuRenderer::Implementation {
public:
    explicit Implementation(RenderBackend requested):requested_backend_(requested){}
    RenderBackend backend()const noexcept{return requested_backend_==RenderBackend::automatic?RenderBackend::d3d11:requested_backend_;}
    RenderBackendCapabilities capabilities()const{switch(backend()){case RenderBackend::d3d11:return {RenderBackend::d3d11,"Direct3D 11",true,true,true,true,false};case RenderBackend::d3d12:return {RenderBackend::d3d12,"Direct3D 12",false,false,false,false,false};case RenderBackend::vulkan:return {RenderBackend::vulkan,"Vulkan",false,false,false,false,false};case RenderBackend::metal:return {RenderBackend::metal,"Metal",false,false,false,false,false};default:return {RenderBackend::null_backend,"Null",true,false,false,false,false};}}
    bool initialize(void* window, int width, int height, std::string& error) {
        if(requested_backend_!=RenderBackend::automatic&&requested_backend_!=RenderBackend::d3d11){error="Requested renderer backend is not available in this build.";return false;}
        DXGI_SWAP_CHAIN_DESC description{}; description.BufferCount=2; description.BufferDesc.Width=width; description.BufferDesc.Height=height;
        description.BufferDesc.Format=DXGI_FORMAT_B8G8R8A8_UNORM; description.BufferUsage=DXGI_USAGE_RENDER_TARGET_OUTPUT;
        description.OutputWindow=static_cast<HWND>(window); description.SampleDesc.Count=1; description.Windowed=TRUE; description.SwapEffect=DXGI_SWAP_EFFECT_FLIP_DISCARD;
        D3D_FEATURE_LEVEL level{};
        HRESULT status=D3D11CreateDeviceAndSwapChain(nullptr,D3D_DRIVER_TYPE_HARDWARE,nullptr,0,nullptr,0,D3D11_SDK_VERSION,&description,&swap_chain_,&device_,&level,&context_);
        if(FAILED(status)){error="D3D11 hardware device creation failed.";return false;}
        ComPtr<ID3DBlob> vs_blob,ps_blob,shadow_blob,post_vs_blob,temporal_blob,display_blob,atmosphere_blob;
        if(!compile_shader("VSMain","vs_5_0",vs_blob,error)||!compile_shader("PSMain","ps_5_0",ps_blob,error)||
           !compile_shader("VSShadow","vs_5_0",shadow_blob,error)||!compile_shader("VSPost","vs_5_0",post_vs_blob,error)||
           !compile_shader("PSTemporal","ps_5_0",temporal_blob,error)||!compile_shader("PSDisplay","ps_5_0",display_blob,error)||
           !compile_shader("PSAtmosphere","ps_5_0",atmosphere_blob,error))return false;
        device_->CreateVertexShader(vs_blob->GetBufferPointer(),vs_blob->GetBufferSize(),nullptr,&vertex_shader_);
        device_->CreatePixelShader(ps_blob->GetBufferPointer(),ps_blob->GetBufferSize(),nullptr,&pixel_shader_);
        device_->CreateVertexShader(shadow_blob->GetBufferPointer(),shadow_blob->GetBufferSize(),nullptr,&shadow_shader_);
        device_->CreateVertexShader(post_vs_blob->GetBufferPointer(),post_vs_blob->GetBufferSize(),nullptr,&post_vertex_shader_);
        device_->CreatePixelShader(temporal_blob->GetBufferPointer(),temporal_blob->GetBufferSize(),nullptr,&temporal_shader_);
        device_->CreatePixelShader(display_blob->GetBufferPointer(),display_blob->GetBufferSize(),nullptr,&display_shader_);
        device_->CreatePixelShader(atmosphere_blob->GetBufferPointer(),atmosphere_blob->GetBufferSize(),nullptr,&atmosphere_shader_);
        D3D11_INPUT_ELEMENT_DESC layout[]={{"POSITION",0,DXGI_FORMAT_R32G32B32_FLOAT,0,0,D3D11_INPUT_PER_VERTEX_DATA,0},{"NORMAL",0,DXGI_FORMAT_R32G32B32_FLOAT,0,12,D3D11_INPUT_PER_VERTEX_DATA,0},{"TEXCOORD",0,DXGI_FORMAT_R32G32_FLOAT,0,24,D3D11_INPUT_PER_VERTEX_DATA,0}};
        device_->CreateInputLayout(layout,3,vs_blob->GetBufferPointer(),vs_blob->GetBufferSize(),&layout_);
        D3D11_BUFFER_DESC buffer{};buffer.Usage=D3D11_USAGE_IMMUTABLE;buffer.BindFlags=D3D11_BIND_VERTEX_BUFFER;buffer.ByteWidth=sizeof(vertices);D3D11_SUBRESOURCE_DATA data{vertices};device_->CreateBuffer(&buffer,&data,&vertex_buffer_);
        buffer.BindFlags=D3D11_BIND_INDEX_BUFFER;buffer.ByteWidth=sizeof(indices);data.pSysMem=indices;device_->CreateBuffer(&buffer,&data,&index_buffer_);
        buffer.Usage=D3D11_USAGE_DYNAMIC;buffer.CPUAccessFlags=D3D11_CPU_ACCESS_WRITE;buffer.BindFlags=D3D11_BIND_CONSTANT_BUFFER;buffer.ByteWidth=sizeof(Constants);device_->CreateBuffer(&buffer,nullptr,&constants_);
        buffer.ByteWidth=sizeof(PostConstants);device_->CreateBuffer(&buffer,nullptr,&post_constants_);
        buffer.ByteWidth=sizeof(SkyConstants);device_->CreateBuffer(&buffer,nullptr,&sky_constants_);
        buffer.ByteWidth=sizeof(SkinConstants);device_->CreateBuffer(&buffer,nullptr,&skin_constants_);
        D3D11_SAMPLER_DESC sampler{};sampler.Filter=D3D11_FILTER_COMPARISON_MIN_MAG_LINEAR_MIP_POINT;sampler.AddressU=sampler.AddressV=sampler.AddressW=D3D11_TEXTURE_ADDRESS_BORDER;sampler.ComparisonFunc=D3D11_COMPARISON_LESS_EQUAL;sampler.BorderColor[0]=sampler.BorderColor[1]=sampler.BorderColor[2]=sampler.BorderColor[3]=1;device_->CreateSamplerState(&sampler,&shadow_sampler_);
        sampler={};sampler.Filter=D3D11_FILTER_ANISOTROPIC;sampler.AddressU=sampler.AddressV=sampler.AddressW=D3D11_TEXTURE_ADDRESS_WRAP;sampler.MaxAnisotropy=8;sampler.MaxLOD=D3D11_FLOAT32_MAX;device_->CreateSamplerState(&sampler,&material_sampler_);
        D3D11_RASTERIZER_DESC raster{};raster.FillMode=D3D11_FILL_SOLID;raster.CullMode=D3D11_CULL_BACK;raster.DepthClipEnable=TRUE;device_->CreateRasterizerState(&raster,&default_rasterizer_);
        raster.DepthBias=600;raster.SlopeScaledDepthBias=1.5F;raster.DepthBiasClamp=0.01F;device_->CreateRasterizerState(&raster,&shadow_rasterizer_);
        CoCreateInstance(CLSID_WICImagingFactory2,nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&wic_));
        create_solid(0xFFFFFFFF,white_texture_);create_solid(0xFFFF8080,normal_texture_);create_solid(0xFF000000,black_texture_);
        if(!create_shadow(error)||!create_gpu_timers(error))return false;return resize(width,height,error);
    }
    bool resize(int width,int height,std::string& error){
        if(!swap_chain_)return false;
        context_->OMSetRenderTargets(0,nullptr,nullptr);
        render_target_.Reset();
        if(FAILED(swap_chain_->ResizeBuffers(0,width,height,DXGI_FORMAT_UNKNOWN,0))){error="Could not resize the swap chain.";return false;}
        ComPtr<ID3D11Texture2D> back;
        if(FAILED(swap_chain_->GetBuffer(0,IID_PPV_ARGS(&back)))||FAILED(device_->CreateRenderTargetView(back.Get(),nullptr,&render_target_))){error="Could not create the display target.";return false;}
        width_=width;height_=height;
        return create_frame_resources(current_render_scale_,error);
    }
    bool render(const World& world,std::string& error){
        if(!ready())return false;
        gpu_skinned_draws_=cpu_skinned_draws_=0;
        resolve_gpu_timing(world.render_settings);
        if(world.render_settings.dynamic_resolution&&!dynamic_resolution_active_){
            adaptive_render_scale_=std::clamp(world.render_settings.render_scale,world.render_settings.minimum_render_scale,world.render_settings.maximum_render_scale);
        }
        dynamic_resolution_active_=world.render_settings.dynamic_resolution;
        temporal_enabled_=world.render_settings.upscaler!="native";
        const float requested_scale=dynamic_resolution_active_?adaptive_render_scale_:std::clamp(world.render_settings.render_scale,0.25F,1.0F);
        if(std::abs(requested_scale-current_render_scale_)>0.001F&&!create_frame_resources(requested_scale,error))return false;
        begin_gpu_timing();
        const WorldVector3 camera_world=active_camera(world);
        const WorldVector3 camera_target_world=active_camera_target(world);
        current_render_origin_=render_origin_for(camera_world,world.simulation_settings);
        if(!previous_render_origin_valid_)previous_render_origin_=current_render_origin_;
        const XMVECTOR eye=XMVectorSet(static_cast<float>(camera_world.x-current_render_origin_.x),
                                      static_cast<float>(camera_world.y-current_render_origin_.y),
                                      static_cast<float>(camera_world.z-current_render_origin_.z),world.render_settings.exposure);
        const XMVECTOR camera_target=XMVectorSet(static_cast<float>(camera_target_world.x-current_render_origin_.x),
                                                static_cast<float>(camera_target_world.y-current_render_origin_.y),
                                                static_cast<float>(camera_target_world.z-current_render_origin_.z),1);
        const XMMATRIX view=XMMatrixLookAtLH(eye,camera_target,XMVectorSet(0,1,0,0));
        XMMATRIX projection=XMMatrixPerspectiveFovLH(XMConvertToRadians(active_fov(world)),float(width_)/float(std::max(1,height_)),0.05F,5000);
        if(temporal_enabled_){
            const float jitter_x=halton(frame_index_+1,2)-0.5F,jitter_y=halton(frame_index_+1,3)-0.5F;
            projection.r[2]=XMVectorAdd(projection.r[2],XMVectorSet(jitter_x*2.0F/render_width_,-jitter_y*2.0F/render_height_,0,0));
        }
        const XMMATRIX view_projection=view*projection;
        current_sun_=active_sun(world);current_render_settings_=world.render_settings;build_dynamic_gi_sources(world);
        const XMVECTOR light_direction=XMVector3Normalize(XMVectorSet(current_sun_.direction.x,current_sun_.direction.y,current_sun_.direction.z,0));
        const XMVECTOR light_target=camera_target,light_position=XMVectorSubtract(light_target,XMVectorScale(light_direction,45.0F));
        const XMVECTOR world_up=std::abs(XMVectorGetY(light_direction))>0.98F?XMVectorSet(0,0,1,0):XMVectorSet(0,1,0,0);
        const XMMATRIX light_view=XMMatrixLookAtLH(light_position,light_target,world_up);
        const XMMATRIX light_projection=XMMatrixOrthographicLH(60,60,0.1F,100);
        draw_shadow(world,light_view*light_projection);
        const float clear[]={world.render_settings.sky_color.x*world.render_settings.exposure,
                             world.render_settings.sky_color.y*world.render_settings.exposure,
                             world.render_settings.sky_color.z*world.render_settings.exposure,1};
        context_->ClearRenderTargetView(scene_target_.Get(),clear);
        const float clear_motion[]={0,0,0,0};context_->ClearRenderTargetView(motion_target_.Get(),clear_motion);
        context_->ClearDepthStencilView(depth_view_.Get(),D3D11_CLEAR_DEPTH|D3D11_CLEAR_STENCIL,1,0);
        D3D11_VIEWPORT viewport{0,0,float(render_width_),float(render_height_),0,1};context_->RSSetViewports(1,&viewport);
        if(world.render_settings.atmosphere_enabled){
            context_->OMSetRenderTargets(1,scene_target_.GetAddressOf(),nullptr);context_->IASetInputLayout(nullptr);context_->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
            context_->VSSetShader(post_vertex_shader_.Get(),nullptr,0);context_->PSSetShader(atmosphere_shader_.Get(),nullptr,0);
            update_sky_constants(XMMatrixInverse(nullptr,view_projection),eye);context_->Draw(3,0);
        }
        ID3D11RenderTargetView* scene_targets[]={scene_target_.Get(),motion_target_.Get()};
        context_->OMSetRenderTargets(2,scene_targets,depth_view_.Get());
        bind_geometry();context_->VSSetShader(vertex_shader_.Get(),nullptr,0);context_->PSSetShader(pixel_shader_.Get(),nullptr,0);
        context_->PSSetShaderResources(0,1,shadow_srv_.GetAddressOf());context_->PSSetSamplers(0,1,shadow_sampler_.GetAddressOf());context_->PSSetSamplers(1,1,material_sampler_.GetAddressOf());
        for(const auto& [entity,material]:world.renderables){
            if(!world.transforms.contains(entity))continue;
            const auto environment=reflection_environment(world,world.transforms.at(entity).position);
            current_environment_intensity_=environment.second;
            GpuMesh* render_mesh=imported_mesh(world,material.mesh_asset);bind_skinning(world,material.skin_binding,render_mesh);
            const UINT index_count=bind_geometry(render_mesh);
            ID3D11ShaderResourceView* maps[]={
                material_texture(world,material.base_color_texture,white_texture_.Get(),true),
                material_texture(world,material.normal_texture,normal_texture_.Get(),false),
                material_texture(world,material.roughness_texture,white_texture_.Get(),false),
                material_texture(world,material.metallic_texture,white_texture_.Get(),false),
                material_texture(world,material.emission_texture,black_texture_.Get(),true),
                material_texture(world,environment.first,black_texture_.Get(),true),
            };
            context_->PSSetShaderResources(1,6,maps);
            const auto previous=previous_transforms_.find(entity);
            const Transform& previous_transform=previous==previous_transforms_.end()?world.transforms.at(entity):previous->second;
            update_constants(world.transforms.at(entity),previous_transform,material,view_projection,
                             previous_view_projection_valid_?previous_view_projection_:view_projection,light_view*light_projection,eye);
            context_->DrawIndexed(index_count,0,0);
            unbind_skinning();
            previous_transforms_[entity]=world.transforms.at(entity);
        }
        ID3D11ShaderResourceView* none[10]={};context_->PSSetShaderResources(0,10,none);
        const int write_history=1-history_index_;
        context_->OMSetRenderTargets(1,history_target_[write_history].GetAddressOf(),nullptr);
        D3D11_VIEWPORT output_viewport{0,0,float(width_),float(height_),0,1};context_->RSSetViewports(1,&output_viewport);
        context_->IASetInputLayout(nullptr);context_->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        context_->VSSetShader(post_vertex_shader_.Get(),nullptr,0);context_->PSSetShader(temporal_shader_.Get(),nullptr,0);
        update_post_constants(world.render_settings.sharpness);
        ID3D11ShaderResourceView* temporal_inputs[]={scene_resource_.Get(),motion_resource_.Get(),history_resource_[history_index_].Get()};
        context_->PSSetShaderResources(7,3,temporal_inputs);context_->Draw(3,0);
        context_->PSSetShaderResources(7,3,none);
        context_->OMSetRenderTargets(1,render_target_.GetAddressOf(),nullptr);
        context_->ClearRenderTargetView(render_target_.Get(),clear);
        context_->PSSetShader(display_shader_.Get(),nullptr,0);
        context_->PSSetShaderResources(9,1,history_resource_[write_history].GetAddressOf());context_->Draw(3,0);
        context_->PSSetShaderResources(9,1,none);
        history_index_=write_history;history_valid_=true;previous_view_projection_=view_projection;previous_view_projection_valid_=true;
        previous_render_origin_=current_render_origin_;previous_render_origin_valid_=true;
        end_gpu_timing();
        ++frame_index_;swap_chain_->Present(1,0);error.clear();return true;
    }
    bool capture(const std::filesystem::path& path,std::string& error){ComPtr<ID3D11Texture2D> back;swap_chain_->GetBuffer(0,IID_PPV_ARGS(&back));D3D11_TEXTURE2D_DESC desc{};back->GetDesc(&desc);desc.Usage=D3D11_USAGE_STAGING;desc.BindFlags=0;desc.CPUAccessFlags=D3D11_CPU_ACCESS_READ;desc.MiscFlags=0;ComPtr<ID3D11Texture2D> staging;device_->CreateTexture2D(&desc,nullptr,&staging);context_->CopyResource(staging.Get(),back.Get());D3D11_MAPPED_SUBRESOURCE mapped{};if(FAILED(context_->Map(staging.Get(),0,D3D11_MAP_READ,0,&mapped))){error="Could not read the GPU back buffer.";return false;}const DWORD row=(desc.Width*3+3)&~3U;std::vector<unsigned char> pixels(static_cast<std::size_t>(row)*desc.Height);for(UINT y=0;y<desc.Height;++y){const auto* source=static_cast<const unsigned char*>(mapped.pData)+(desc.Height-1-y)*mapped.RowPitch;auto* target=pixels.data()+y*row;for(UINT x=0;x<desc.Width;++x){target[x*3]=source[x*4];target[x*3+1]=source[x*4+1];target[x*3+2]=source[x*4+2];}}context_->Unmap(staging.Get(),0);BITMAPFILEHEADER file{};BITMAPINFOHEADER info{};file.bfType=0x4D42;file.bfOffBits=sizeof(file)+sizeof(info);file.bfSize=file.bfOffBits+static_cast<DWORD>(pixels.size());info.biSize=sizeof(info);info.biWidth=static_cast<LONG>(desc.Width);info.biHeight=static_cast<LONG>(desc.Height);info.biPlanes=1;info.biBitCount=24;info.biCompression=BI_RGB;std::ofstream stream(path,std::ios::binary);stream.write(reinterpret_cast<char*>(&file),sizeof(file));stream.write(reinterpret_cast<char*>(&info),sizeof(info));stream.write(reinterpret_cast<char*>(pixels.data()),static_cast<std::streamsize>(pixels.size()));return bool(stream);}
    bool ready()const noexcept{return device_&&swap_chain_&&render_target_;}
    GpuRenderProfile profile()const noexcept{return {average_gpu_ms_,current_render_scale_,render_width_,render_height_,temporal_enabled_,dynamic_resolution_active_,gpu_skinned_draws_,cpu_skinned_draws_};}
private:
    struct GpuMesh{ComPtr<ID3D11Buffer> vertices;ComPtr<ID3D11Buffer> indices;UINT index_count{};std::vector<Vertex> source_vertices;std::vector<std::uint32_t> source_position_indices;std::uint64_t skin_frame{std::numeric_limits<std::uint64_t>::max()};};
    struct CpuSkinData{std::vector<XMFLOAT3> rest_positions;std::vector<std::uint32_t> offsets,joint_indices;std::vector<float> weights;bool valid{false};};
    struct GpuSkinData{ComPtr<ID3D11Buffer> vertices,palette;ComPtr<ID3D11ShaderResourceView> vertex_srv,palette_srv;std::size_t joint_count{};std::uint64_t frame{std::numeric_limits<std::uint64_t>::max()};bool valid{false};};
    struct GpuTimingFrame{ComPtr<ID3D11Query> disjoint,start,end;bool pending{false};};
    static float halton(std::uint64_t index,std::uint32_t base){float result=0,fraction=1.0F;while(index){fraction/=base;result+=fraction*(index%base);index/=base;}return result;}
    GpuMesh* imported_mesh(const World& world,const std::string& id){
        if(id.empty())return nullptr;
        if(const auto found=mesh_cache_.find(id);found!=mesh_cache_.end())return &found->second;
        const auto asset=world.assets.find(id);if(asset==world.assets.end()||asset->second.source.extension()!=L".obj")return nullptr;
        std::ifstream stream(asset->second.source);if(!stream)return nullptr;
        std::vector<XMFLOAT3> positions,normals;std::vector<XMFLOAT2> uvs;std::vector<Vertex> output;std::vector<std::uint32_t> output_indices,source_position_indices;std::string line;
        auto resolve=[](int index,std::size_t count)->std::size_t{return index>0?static_cast<std::size_t>(index-1):static_cast<std::size_t>(static_cast<int>(count)+index);};
        while(std::getline(stream,line)){std::istringstream row(line);std::string type;row>>type;
            if(type=="v"){XMFLOAT3 value{};row>>value.x>>value.y>>value.z;positions.push_back(value);}
            else if(type=="vn"){XMFLOAT3 value{};row>>value.x>>value.y>>value.z;normals.push_back(value);}
            else if(type=="vt"){XMFLOAT2 value{};row>>value.x>>value.y;value.y=1.0F-value.y;uvs.push_back(value);}
            else if(type=="f"){std::vector<std::pair<Vertex,std::uint32_t>> face;std::string token;while(row>>token){std::replace(token.begin(),token.end(),'/',' ');std::istringstream values(token);int p=0,t=0,n=0;values>>p;if(!values.eof())values>>t;if(!values.eof())values>>n;const auto position_index=p==0?positions.size():resolve(p,positions.size());if(position_index>=positions.size())continue;Vertex vertex{};vertex.position=positions[position_index];vertex.uv=t!=0&&resolve(t,uvs.size())<uvs.size()?uvs[resolve(t,uvs.size())]:XMFLOAT2{};vertex.normal=n!=0&&resolve(n,normals.size())<normals.size()?normals[resolve(n,normals.size())]:XMFLOAT3{0,1,0};face.push_back({vertex,static_cast<std::uint32_t>(position_index)});}for(std::size_t corner=1;corner+1<face.size();++corner){for(const auto index:{std::size_t(0),corner,corner+1}){output_indices.push_back(static_cast<std::uint32_t>(output.size()));output.push_back(face[index].first);source_position_indices.push_back(face[index].second);}}}
        }
        if(output.empty()||output_indices.empty()||output.size()>10000000)return nullptr;
        GpuMesh mesh;D3D11_BUFFER_DESC desc{};desc.Usage=D3D11_USAGE_DYNAMIC;desc.CPUAccessFlags=D3D11_CPU_ACCESS_WRITE;desc.BindFlags=D3D11_BIND_VERTEX_BUFFER;desc.ByteWidth=static_cast<UINT>(output.size()*sizeof(Vertex));D3D11_SUBRESOURCE_DATA data{output.data()};if(FAILED(device_->CreateBuffer(&desc,&data,&mesh.vertices)))return nullptr;desc.Usage=D3D11_USAGE_IMMUTABLE;desc.CPUAccessFlags=0;desc.BindFlags=D3D11_BIND_INDEX_BUFFER;desc.ByteWidth=static_cast<UINT>(output_indices.size()*sizeof(std::uint32_t));data.pSysMem=output_indices.data();if(FAILED(device_->CreateBuffer(&desc,&data,&mesh.indices)))return nullptr;mesh.index_count=static_cast<UINT>(output_indices.size());mesh.source_vertices=std::move(output);mesh.source_position_indices=std::move(source_position_indices);mesh_cache_[id]=std::move(mesh);return &mesh_cache_[id];
    }
    template<typename Value>static bool read_binary(const std::filesystem::path& path,std::size_t count,std::vector<Value>& output){if(count>320000000U)return false;std::ifstream stream(path,std::ios::binary|std::ios::ate);if(!stream)return false;const auto size=stream.tellg();if(size<0||static_cast<std::uint64_t>(size)<count*sizeof(Value))return false;stream.seekg(0);output.resize(count);stream.read(reinterpret_cast<char*>(output.data()),static_cast<std::streamsize>(count*sizeof(Value)));return bool(stream);}
    CpuSkinData& cpu_skin_data(const World& world,const SkinBinding& skin){
        if(const auto found=cpu_skin_cache_.find(skin.id);found!=cpu_skin_cache_.end())return found->second;CpuSkinData data;const auto asset_path=[&world](const std::string& id){const auto found=world.assets.find(id);return found==world.assets.end()?std::filesystem::path{}:found->second.source;};
        std::vector<float> rest;if(!read_binary(asset_path(skin.rest_positions_asset),skin.vertex_count*3U,rest)||!read_binary(asset_path(skin.influence_offsets_asset),skin.vertex_count+1U,data.offsets)){cpu_skin_cache_[skin.id]=std::move(data);return cpu_skin_cache_[skin.id];}
        const std::size_t influence_count=data.offsets.empty()?0U:static_cast<std::size_t>(data.offsets.back());if(influence_count>skin.vertex_count*std::max<std::size_t>(1U,skin.maximum_influences)||!read_binary(asset_path(skin.joint_indices_asset),influence_count,data.joint_indices)||!read_binary(asset_path(skin.weights_asset),influence_count,data.weights)){cpu_skin_cache_[skin.id]=std::move(data);return cpu_skin_cache_[skin.id];}
        data.rest_positions.resize(skin.vertex_count);for(std::size_t index=0;index<skin.vertex_count;++index)data.rest_positions[index]={rest[index*3],rest[index*3+1],rest[index*3+2]};data.valid=true;for(std::size_t index=0;index<skin.vertex_count;++index)if(data.offsets[index]>data.offsets[index+1]||data.offsets[index+1]-data.offsets[index]>skin.maximum_influences){data.valid=false;break;}cpu_skin_cache_[skin.id]=std::move(data);return cpu_skin_cache_[skin.id];
    }
    bool update_skinned_mesh(const World& world,const std::string& skin_id,GpuMesh& mesh){
        if(mesh.skin_frame==frame_index_)return true;const auto skin_found=world.skin_bindings.find(skin_id);if(skin_found==world.skin_bindings.end())return false;auto& data=cpu_skin_data(world,skin_found->second);if(!data.valid||mesh.source_vertices.size()!=mesh.source_position_indices.size())return false;std::vector<Matrix4> palette;std::string error;if(!build_skin_matrix_palette(world,skin_id,palette,error))return false;std::vector<Vertex> deformed=mesh.source_vertices;
        for(std::size_t render_index=0;render_index<deformed.size();++render_index){const std::size_t source_index=mesh.source_position_indices[render_index];if(source_index>=data.rest_positions.size())return false;const auto& point=data.rest_positions[source_index];XMFLOAT3 position{};double total=0.0;for(std::size_t influence=data.offsets[source_index];influence<data.offsets[source_index+1];++influence){const auto joint=data.joint_indices[influence];if(joint>=palette.size())return false;const double weight=data.weights[influence];const auto& matrix=palette[joint];position.x+=static_cast<float>((point.x*matrix[0]+point.y*matrix[4]+point.z*matrix[8]+matrix[12])*weight);position.y+=static_cast<float>((point.x*matrix[1]+point.y*matrix[5]+point.z*matrix[9]+matrix[13])*weight);position.z+=static_cast<float>((point.x*matrix[2]+point.y*matrix[6]+point.z*matrix[10]+matrix[14])*weight);total+=weight;}if(total>1.0e-8){position.x/=static_cast<float>(total);position.y/=static_cast<float>(total);position.z/=static_cast<float>(total);deformed[render_index].position=position;}}
        D3D11_MAPPED_SUBRESOURCE mapped{};if(FAILED(context_->Map(mesh.vertices.Get(),0,D3D11_MAP_WRITE_DISCARD,0,&mapped)))return false;std::memcpy(mapped.pData,deformed.data(),deformed.size()*sizeof(Vertex));context_->Unmap(mesh.vertices.Get(),0);mesh.skin_frame=frame_index_;return true;
    }
    template<typename Value>bool create_structured_buffer(const std::vector<Value>& values,bool dynamic,ComPtr<ID3D11Buffer>& buffer,ComPtr<ID3D11ShaderResourceView>& view){if(values.empty()||values.size()>10000000U)return false;D3D11_BUFFER_DESC desc{};desc.ByteWidth=static_cast<UINT>(values.size()*sizeof(Value));desc.Usage=dynamic?D3D11_USAGE_DYNAMIC:D3D11_USAGE_IMMUTABLE;desc.CPUAccessFlags=dynamic?D3D11_CPU_ACCESS_WRITE:0;desc.BindFlags=D3D11_BIND_SHADER_RESOURCE;desc.MiscFlags=D3D11_RESOURCE_MISC_BUFFER_STRUCTURED;desc.StructureByteStride=sizeof(Value);D3D11_SUBRESOURCE_DATA initial{values.data()};if(FAILED(device_->CreateBuffer(&desc,dynamic?nullptr:&initial,&buffer)))return false;D3D11_SHADER_RESOURCE_VIEW_DESC srv{};srv.Format=DXGI_FORMAT_UNKNOWN;srv.ViewDimension=D3D11_SRV_DIMENSION_BUFFER;srv.Buffer.NumElements=static_cast<UINT>(values.size());return SUCCEEDED(device_->CreateShaderResourceView(buffer.Get(),&srv,&view));}
    GpuSkinData& gpu_skin_data(const World& world,const std::string& skin_id,GpuMesh& mesh){const std::string key=skin_id+":"+std::to_string(reinterpret_cast<std::uintptr_t>(&mesh));if(const auto found=gpu_skin_cache_.find(key);found!=gpu_skin_cache_.end())return found->second;GpuSkinData gpu;const auto skin_found=world.skin_bindings.find(skin_id);if(skin_found==world.skin_bindings.end()||skin_found->second.maximum_influences>8U){gpu_skin_cache_[key]=std::move(gpu);return gpu_skin_cache_[key];}auto& cpu=cpu_skin_data(world,skin_found->second);if(!cpu.valid||mesh.source_position_indices.size()!=mesh.source_vertices.size()){gpu_skin_cache_[key]=std::move(gpu);return gpu_skin_cache_[key];}std::vector<GpuSkinVertex> vertices_data(mesh.source_vertices.size());for(std::size_t render_index=0;render_index<vertices_data.size();++render_index){const std::size_t source=mesh.source_position_indices[render_index];if(source>=cpu.rest_positions.size()){gpu_skin_cache_[key]=std::move(gpu);return gpu_skin_cache_[key];}auto& target=vertices_data[render_index];target.rest_position={cpu.rest_positions[source].x,cpu.rest_positions[source].y,cpu.rest_positions[source].z,1};auto* joints0=&target.joints0.x;auto* joints1=&target.joints1.x;auto* weights0=&target.weights0.x;auto* weights1=&target.weights1.x;const auto begin=cpu.offsets[source],end=cpu.offsets[source+1];if(end-begin>8U){gpu_skin_cache_[key]=std::move(gpu);return gpu_skin_cache_[key];}for(std::uint32_t influence=begin;influence<end;++influence){const std::uint32_t slot=influence-begin;if(slot<4U){joints0[slot]=cpu.joint_indices[influence];weights0[slot]=cpu.weights[influence];}else{joints1[slot-4U]=cpu.joint_indices[influence];weights1[slot-4U]=cpu.weights[influence];}}}std::vector<XMFLOAT4X4> empty_palette(skin_found->second.joint_ids.size());if(!create_structured_buffer(vertices_data,false,gpu.vertices,gpu.vertex_srv)||!create_structured_buffer(empty_palette,true,gpu.palette,gpu.palette_srv)){gpu_skin_cache_[key]=std::move(gpu);return gpu_skin_cache_[key];}gpu.joint_count=empty_palette.size();gpu.valid=true;gpu_skin_cache_[key]=std::move(gpu);return gpu_skin_cache_[key];}
    bool bind_skinning(const World& world,const std::string& skin_id,GpuMesh* mesh){SkinConstants constants{};if(mesh&&!skin_id.empty()){auto& gpu=gpu_skin_data(world,skin_id,*mesh);if(gpu.valid){if(gpu.frame!=frame_index_){std::vector<Matrix4> palette;std::string error;if(build_skin_matrix_palette(world,skin_id,palette,error)&&palette.size()==gpu.joint_count){D3D11_MAPPED_SUBRESOURCE mapped{};if(SUCCEEDED(context_->Map(gpu.palette.Get(),0,D3D11_MAP_WRITE_DISCARD,0,&mapped))){auto* output=static_cast<XMFLOAT4X4*>(mapped.pData);for(std::size_t index=0;index<palette.size();++index){auto* values=reinterpret_cast<float*>(&output[index]);for(std::size_t row=0;row<4;++row)for(std::size_t column=0;column<4;++column)values[column*4+row]=static_cast<float>(palette[index][row*4+column]);}context_->Unmap(gpu.palette.Get(),0);gpu.frame=frame_index_;}}}if(gpu.frame==frame_index_){ID3D11ShaderResourceView* resources[]={gpu.vertex_srv.Get(),gpu.palette_srv.Get()};context_->VSSetShaderResources(10,2,resources);constants.enabled=1;++gpu_skinned_draws_;}}if(constants.enabled==0&&update_skinned_mesh(world,skin_id,*mesh))++cpu_skinned_draws_;}
        D3D11_MAPPED_SUBRESOURCE mapped{};if(SUCCEEDED(context_->Map(skin_constants_.Get(),0,D3D11_MAP_WRITE_DISCARD,0,&mapped))){std::memcpy(mapped.pData,&constants,sizeof(constants));context_->Unmap(skin_constants_.Get(),0);}context_->VSSetConstantBuffers(3,1,skin_constants_.GetAddressOf());return constants.enabled!=0;}
    void unbind_skinning(){ID3D11ShaderResourceView* none[2]={};context_->VSSetShaderResources(10,2,none);}
    void create_solid(std::uint32_t rgba,ComPtr<ID3D11ShaderResourceView>& output){D3D11_TEXTURE2D_DESC desc{};desc.Width=desc.Height=1;desc.MipLevels=desc.ArraySize=1;desc.Format=DXGI_FORMAT_R8G8B8A8_UNORM;desc.SampleDesc.Count=1;desc.BindFlags=D3D11_BIND_SHADER_RESOURCE;D3D11_SUBRESOURCE_DATA data{&rgba,4,0};ComPtr<ID3D11Texture2D> texture;device_->CreateTexture2D(&desc,&data,&texture);device_->CreateShaderResourceView(texture.Get(),nullptr,&output);}
    ID3D11ShaderResourceView* material_texture(
        const World& world,
        const std::string& id,
        ID3D11ShaderResourceView* fallback,
        bool srgb) {
        if (id.empty()) return fallback;
        if (const auto cached = texture_cache_.find(id); cached != texture_cache_.end()) return cached->second.Get();
        const auto asset = world.assets.find(id);
        if (asset == world.assets.end() || !wic_) return fallback;

        ComPtr<IWICBitmapDecoder> decoder;
        if (FAILED(wic_->CreateDecoderFromFilename(
                asset->second.source.c_str(), nullptr, GENERIC_READ, WICDecodeMetadataCacheOnDemand, &decoder))) {
            return fallback;
        }
        ComPtr<IWICBitmapFrameDecode> frame;
        ComPtr<IWICFormatConverter> converter;
        if (FAILED(decoder->GetFrame(0, &frame)) || FAILED(wic_->CreateFormatConverter(&converter)) ||
            FAILED(converter->Initialize(
                frame.Get(), GUID_WICPixelFormat32bppRGBA, WICBitmapDitherTypeNone, nullptr, 0,
                WICBitmapPaletteTypeCustom))) {
            return fallback;
        }

        UINT width = 0;
        UINT height = 0;
        converter->GetSize(&width, &height);
        if (width == 0 || height == 0 || width > 16384 || height > 16384) return fallback;
        std::vector<std::uint8_t> pixels(static_cast<std::size_t>(width) * height * 4);
        if (FAILED(converter->CopyPixels(nullptr, width * 4, static_cast<UINT>(pixels.size()), pixels.data()))) {
            return fallback;
        }

        D3D11_TEXTURE2D_DESC desc{};
        desc.Width = width;
        desc.Height = height;
        desc.MipLevels = 0;
        desc.ArraySize = 1;
        desc.Format = srgb ? DXGI_FORMAT_R8G8B8A8_UNORM_SRGB : DXGI_FORMAT_R8G8B8A8_UNORM;
        desc.SampleDesc.Count = 1;
        desc.Usage = D3D11_USAGE_DEFAULT;
        desc.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_RENDER_TARGET;
        desc.MiscFlags = D3D11_RESOURCE_MISC_GENERATE_MIPS;
        ComPtr<ID3D11Texture2D> texture;
        if (FAILED(device_->CreateTexture2D(&desc, nullptr, &texture))) return fallback;
        context_->UpdateSubresource(texture.Get(), 0, nullptr, pixels.data(), width * 4, 0);

        D3D11_SHADER_RESOURCE_VIEW_DESC view_desc{};
        view_desc.Format = desc.Format;
        view_desc.ViewDimension = D3D11_SRV_DIMENSION_TEXTURE2D;
        view_desc.Texture2D.MostDetailedMip = 0;
        view_desc.Texture2D.MipLevels = UINT(-1);
        ComPtr<ID3D11ShaderResourceView> view;
        if (FAILED(device_->CreateShaderResourceView(texture.Get(), &view_desc, &view))) return fallback;
        context_->GenerateMips(view.Get());
        texture_cache_[id] = view;
        return view.Get();
    }
    bool create_render_texture(
        UINT width,UINT height,DXGI_FORMAT format,ComPtr<ID3D11Texture2D>& texture,
        ComPtr<ID3D11RenderTargetView>& target,ComPtr<ID3D11ShaderResourceView>& resource){
        D3D11_TEXTURE2D_DESC desc{};desc.Width=width;desc.Height=height;desc.MipLevels=desc.ArraySize=1;
        desc.Format=format;desc.SampleDesc.Count=1;desc.BindFlags=D3D11_BIND_RENDER_TARGET|D3D11_BIND_SHADER_RESOURCE;
        return SUCCEEDED(device_->CreateTexture2D(&desc,nullptr,&texture))&&
               SUCCEEDED(device_->CreateRenderTargetView(texture.Get(),nullptr,&target))&&
               SUCCEEDED(device_->CreateShaderResourceView(texture.Get(),nullptr,&resource));
    }
    bool create_gpu_timers(std::string& error){
        for(auto& frame:gpu_timing_){
            D3D11_QUERY_DESC desc{D3D11_QUERY_TIMESTAMP_DISJOINT,0};
            if(FAILED(device_->CreateQuery(&desc,&frame.disjoint))){error="GPU timing query allocation failed.";return false;}
            desc.Query=D3D11_QUERY_TIMESTAMP;
            if(FAILED(device_->CreateQuery(&desc,&frame.start))||FAILED(device_->CreateQuery(&desc,&frame.end))){error="GPU timestamp allocation failed.";return false;}
        }
        return true;
    }
    void begin_gpu_timing(){
        timing_started_=false;auto& frame=gpu_timing_[timing_cursor_];if(frame.pending)return;
        context_->Begin(frame.disjoint.Get());context_->End(frame.start.Get());timing_started_=true;
    }
    void end_gpu_timing(){
        if(!timing_started_)return;auto& frame=gpu_timing_[timing_cursor_];
        context_->End(frame.end.Get());context_->End(frame.disjoint.Get());frame.pending=true;
        timing_cursor_=(timing_cursor_+1)%gpu_timing_.size();timing_started_=false;
    }
    void resolve_gpu_timing(const RenderSettings& settings){
        for(auto& frame:gpu_timing_){
            if(!frame.pending)continue;D3D11_QUERY_DATA_TIMESTAMP_DISJOINT disjoint{};
            if(context_->GetData(frame.disjoint.Get(),&disjoint,sizeof(disjoint),D3D11_ASYNC_GETDATA_DONOTFLUSH)!=S_OK)continue;
            UINT64 start=0,end=0;const bool valid=!disjoint.Disjoint&&
                context_->GetData(frame.start.Get(),&start,sizeof(start),D3D11_ASYNC_GETDATA_DONOTFLUSH)==S_OK&&
                context_->GetData(frame.end.Get(),&end,sizeof(end),D3D11_ASYNC_GETDATA_DONOTFLUSH)==S_OK;
            frame.pending=false;if(!valid||end<=start)continue;
            const float milliseconds=static_cast<float>((end-start)*1000.0/static_cast<double>(disjoint.Frequency));
            average_gpu_ms_=gpu_timing_samples_==0?milliseconds:average_gpu_ms_*0.9F+milliseconds*0.1F;++gpu_timing_samples_;
        }
        if(!settings.dynamic_resolution||gpu_timing_samples_<15)return;
        const float minimum=std::clamp(std::min(settings.minimum_render_scale,settings.maximum_render_scale),0.25F,1.0F);
        const float maximum=std::clamp(std::max(settings.minimum_render_scale,settings.maximum_render_scale),minimum,1.0F);
        const float target=std::max(1.0F,settings.target_frame_ms);
        if(average_gpu_ms_>target*1.05F)adaptive_render_scale_=std::max(minimum,adaptive_render_scale_-0.05F);
        else if(average_gpu_ms_<target*0.82F)adaptive_render_scale_=std::min(maximum,adaptive_render_scale_+0.025F);
        gpu_timing_samples_=0;
    }
    bool create_frame_resources(float scale,std::string& error){
        if(width_<1||height_<1)return false;
        context_->OMSetRenderTargets(0,nullptr,nullptr);
        scene_texture_.Reset();scene_target_.Reset();scene_resource_.Reset();
        motion_texture_.Reset();motion_target_.Reset();motion_resource_.Reset();
        depth_texture_.Reset();depth_view_.Reset();
        for(int index=0;index<2;++index){history_texture_[index].Reset();history_target_[index].Reset();history_resource_[index].Reset();}
        current_render_scale_=std::clamp(scale,0.25F,1.0F);
        render_width_=std::max(1,static_cast<int>(std::lround(width_*current_render_scale_)));
        render_height_=std::max(1,static_cast<int>(std::lround(height_*current_render_scale_)));
        if(!create_render_texture(render_width_,render_height_,DXGI_FORMAT_R16G16B16A16_FLOAT,scene_texture_,scene_target_,scene_resource_)||
           !create_render_texture(render_width_,render_height_,DXGI_FORMAT_R16G16_FLOAT,motion_texture_,motion_target_,motion_resource_)||
           !create_render_texture(width_,height_,DXGI_FORMAT_R16G16B16A16_FLOAT,history_texture_[0],history_target_[0],history_resource_[0])||
           !create_render_texture(width_,height_,DXGI_FORMAT_R16G16B16A16_FLOAT,history_texture_[1],history_target_[1],history_resource_[1])){
            error="Temporal render-target allocation failed.";return false;
        }
        D3D11_TEXTURE2D_DESC depth{};depth.Width=render_width_;depth.Height=render_height_;depth.MipLevels=depth.ArraySize=1;
        depth.Format=DXGI_FORMAT_D24_UNORM_S8_UINT;depth.SampleDesc.Count=1;depth.BindFlags=D3D11_BIND_DEPTH_STENCIL;
        if(FAILED(device_->CreateTexture2D(&depth,nullptr,&depth_texture_))||FAILED(device_->CreateDepthStencilView(depth_texture_.Get(),nullptr,&depth_view_))){
            error="Internal depth-target allocation failed.";return false;
        }
        history_valid_=false;history_index_=0;error.clear();return true;
    }
    bool create_shadow(std::string& error){D3D11_TEXTURE2D_DESC desc{};desc.Width=2048;desc.Height=2048;desc.MipLevels=1;desc.ArraySize=1;desc.Format=DXGI_FORMAT_R32_TYPELESS;desc.SampleDesc.Count=1;desc.BindFlags=D3D11_BIND_DEPTH_STENCIL|D3D11_BIND_SHADER_RESOURCE;if(FAILED(device_->CreateTexture2D(&desc,nullptr,&shadow_texture_))){error="Shadow-map allocation failed.";return false;}D3D11_DEPTH_STENCIL_VIEW_DESC dsv{};dsv.Format=DXGI_FORMAT_D32_FLOAT;dsv.ViewDimension=D3D11_DSV_DIMENSION_TEXTURE2D;device_->CreateDepthStencilView(shadow_texture_.Get(),&dsv,&shadow_view_);D3D11_SHADER_RESOURCE_VIEW_DESC srv{};srv.Format=DXGI_FORMAT_R32_FLOAT;srv.ViewDimension=D3D11_SRV_DIMENSION_TEXTURE2D;srv.Texture2D.MipLevels=1;device_->CreateShaderResourceView(shadow_texture_.Get(),&srv,&shadow_srv_);return true;}
    UINT bind_geometry(GpuMesh* mesh=nullptr){UINT stride=sizeof(Vertex),offset=0;context_->IASetInputLayout(layout_.Get());ID3D11Buffer* vertices_buffer=mesh?mesh->vertices.Get():vertex_buffer_.Get();context_->IASetVertexBuffers(0,1,&vertices_buffer,&stride,&offset);context_->IASetIndexBuffer(mesh?mesh->indices.Get():index_buffer_.Get(),mesh?DXGI_FORMAT_R32_UINT:DXGI_FORMAT_R16_UINT,0);context_->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);context_->VSSetConstantBuffers(0,1,constants_.GetAddressOf());context_->PSSetConstantBuffers(0,1,constants_.GetAddressOf());return mesh?mesh->index_count:static_cast<UINT>(std::size(indices));}
    XMMATRIX transform_matrix(const Transform& transform,const WorldVector3& origin)const{
        return XMMatrixScaling(transform.scale.x,transform.scale.y,transform.scale.z)*
               XMMatrixRotationRollPitchYaw(XMConvertToRadians(transform.rotation.x),XMConvertToRadians(transform.rotation.y),XMConvertToRadians(transform.rotation.z))*
               XMMatrixTranslation(static_cast<float>(transform.position.x-origin.x),static_cast<float>(transform.position.y-origin.y),static_cast<float>(transform.position.z-origin.z));
    }
    static std::string normalized_name(std::string value){
        std::transform(value.begin(),value.end(),value.begin(),[](unsigned char character){return static_cast<char>(std::tolower(character));});
        return value;
    }
    static float lighting_model_code(const std::string& value){
        const auto mode=normalized_name(value);
        if(mode=="stylized"||mode=="stylized_pbr")return 1.0F;
        if(mode=="toon"||mode=="toony"||mode=="cel")return 2.0F;
        if(mode=="unlit"||mode=="flat")return 3.0F;
        return 0.0F;
    }
    static float gi_mode_code(const std::string& value){
        const auto mode=normalized_name(value);
        if(mode=="off"||mode=="none")return 0.0F;
        if(mode=="hemisphere"||mode=="sky")return 1.0F;
        return 2.0F;
    }
    void update_constants(const Transform& transform,const Transform& previous_transform,const Renderable& material,
                          XMMATRIX vp,XMMATRIX previous_vp,XMMATRIX lvp,XMVECTOR eye){
        const XMMATRIX world=transform_matrix(transform,current_render_origin_);
        const XMMATRIX previous_world=transform_matrix(previous_transform,previous_render_origin_);
        D3D11_MAPPED_SUBRESOURCE mapped{};context_->Map(constants_.Get(),0,D3D11_MAP_WRITE_DISCARD,0,&mapped);
        auto* c=static_cast<Constants*>(mapped.pData);
        XMStoreFloat4x4(&c->world,XMMatrixTranspose(world));XMStoreFloat4x4(&c->view_projection,XMMatrixTranspose(vp));
        XMStoreFloat4x4(&c->light_view_projection,XMMatrixTranspose(lvp));XMStoreFloat4x4(&c->previous_world,XMMatrixTranspose(previous_world));
        XMStoreFloat4x4(&c->previous_view_projection,XMMatrixTranspose(previous_vp));
        c->base_metallic={material.base_color.x,material.base_color.y,material.base_color.z,material.metallic};
        c->light_roughness={current_sun_.direction.x,current_sun_.direction.y,current_sun_.direction.z,material.roughness};
        c->sun_color_intensity={current_sun_.color.x,current_sun_.color.y,current_sun_.color.z,current_sun_.intensity};
        XMStoreFloat4(&c->camera,eye);
        c->environment={current_environment_intensity_,lighting_model_code(current_render_settings_.lighting_model),
                        gi_mode_code(current_render_settings_.global_illumination),current_render_settings_.indirect_intensity};
        c->sky={current_render_settings_.sky_color.x,current_render_settings_.sky_color.y,current_render_settings_.sky_color.z,0};
        c->ground={current_render_settings_.ground_color.x,current_render_settings_.ground_color.y,current_render_settings_.ground_color.z,0};
        c->style={std::max(2.0F,current_render_settings_.toon_bands),std::max(0.0F,current_render_settings_.rim_intensity),
                  current_sun_.casts_shadow?1.0F:0.0F,std::max(1.0F,current_sun_.angular_radius_degrees/0.266F)};
        c->bounce_position_radius=current_bounce_positions_;c->bounce_color_intensity=current_bounce_colors_;
        const XMFLOAT3 local_center{static_cast<float>(transform.position.x-current_render_origin_.x),
                                    static_cast<float>(transform.position.y-current_render_origin_.y),
                                    static_cast<float>(transform.position.z-current_render_origin_.z)};
        for(std::size_t index=0;index<current_bounce_count_;++index){const auto& source=current_bounce_positions_[index];
            const float dx=source.x-local_center.x,dy=source.y-local_center.y,dz=source.z-local_center.z;
            if(dx*dx+dy*dy+dz*dz<1.0e-6F)c->bounce_color_intensity[index].w=0.0F;
        }
        c->bounce_settings={static_cast<float>(current_bounce_count_),0,0,0};
        context_->Unmap(constants_.Get(),0);
    }
    void update_post_constants(float sharpness){
        D3D11_MAPPED_SUBRESOURCE mapped{};context_->Map(post_constants_.Get(),0,D3D11_MAP_WRITE_DISCARD,0,&mapped);
        auto* constants=static_cast<PostConstants*>(mapped.pData);
        constants->temporal={1.0F/render_width_,1.0F/render_height_,history_valid_&&temporal_enabled_?1.0F:0.0F,0.9F};
        constants->display={1.0F/width_,1.0F/height_,std::clamp(sharpness,0.0F,1.0F),0};
        context_->Unmap(post_constants_.Get(),0);context_->PSSetConstantBuffers(1,1,post_constants_.GetAddressOf());
    }
    void update_sky_constants(XMMATRIX inverse_view_projection,XMVECTOR eye){
        D3D11_MAPPED_SUBRESOURCE mapped{};context_->Map(sky_constants_.Get(),0,D3D11_MAP_WRITE_DISCARD,0,&mapped);auto* constants=static_cast<SkyConstants*>(mapped.pData);
        XMStoreFloat4x4(&constants->inverse_view_projection,XMMatrixTranspose(inverse_view_projection));XMStoreFloat4(&constants->camera,eye);
        constants->sun_direction_radius={current_sun_.direction.x,current_sun_.direction.y,current_sun_.direction.z,current_sun_.angular_radius_degrees};
        constants->sun_color_intensity={current_sun_.color.x,current_sun_.color.y,current_sun_.color.z,current_sun_.intensity};
        constants->sky={current_render_settings_.sky_color.x,current_render_settings_.sky_color.y,current_render_settings_.sky_color.z,0};
        constants->ground={current_render_settings_.ground_color.x,current_render_settings_.ground_color.y,current_render_settings_.ground_color.z,0};
        constants->atmosphere={current_render_settings_.atmosphere_density,current_render_settings_.atmospheric_haze,current_render_settings_.horizon_falloff,0};
        context_->Unmap(sky_constants_.Get(),0);context_->PSSetConstantBuffers(2,1,sky_constants_.GetAddressOf());
    }
    void draw_shadow(const World& world,XMMATRIX lvp){context_->ClearDepthStencilView(shadow_view_.Get(),D3D11_CLEAR_DEPTH,1,0);if(!current_sun_.casts_shadow)return;context_->OMSetRenderTargets(0,nullptr,shadow_view_.Get());context_->RSSetState(shadow_rasterizer_.Get());D3D11_VIEWPORT viewport{0,0,2048,2048,0,1};context_->RSSetViewports(1,&viewport);context_->VSSetShader(shadow_shader_.Get(),nullptr,0);context_->PSSetShader(nullptr,nullptr,0);for(const auto& [entity,material]:world.renderables){if(!material.casts_shadow||!world.transforms.contains(entity))continue;GpuMesh* mesh=imported_mesh(world,material.mesh_asset);bind_skinning(world,material.skin_binding,mesh);const UINT count=bind_geometry(mesh);update_constants(world.transforms.at(entity),world.transforms.at(entity),material,XMMatrixIdentity(),XMMatrixIdentity(),lvp,XMVectorZero());context_->DrawIndexed(count,0,0);unbind_skinning();}context_->RSSetState(default_rasterizer_.Get());}
    std::pair<std::string,float> reflection_environment(const World& world,const WorldVector3& position)const{
        const ReflectionProbe* selected=nullptr;
        double selected_distance=std::numeric_limits<double>::max();
        for(const auto& [entity,probe]:world.reflection_probes){
            const auto transform=world.transforms.find(entity);if(transform==world.transforms.end())continue;
            const double x=std::abs(position.x-transform->second.position.x)/std::max(0.001,static_cast<double>(probe.half_extents.x));
            const double y=std::abs(position.y-transform->second.position.y)/std::max(0.001,static_cast<double>(probe.half_extents.y));
            const double z=std::abs(position.z-transform->second.position.z)/std::max(0.001,static_cast<double>(probe.half_extents.z));
            if(x>1||y>1||z>1)continue;
            const double distance=x*x+y*y+z*z;
            if(!selected||probe.priority>selected->priority||(probe.priority==selected->priority&&distance<selected_distance)){
                selected=&probe;selected_distance=distance;
            }
        }
        if(selected&&!selected->environment_texture.empty())return {selected->environment_texture,selected->intensity};
        return {world.render_settings.environment_texture,world.render_settings.environment_intensity};
    }
    DirectionalLight active_sun(const World& world)const{
        DirectionalLight result{};float best=-1.0F;
        for(const auto& [unused,light]:world.lights){static_cast<void>(unused);if(light.intensity>best){result=light;best=light.intensity;}}
        return result;
    }
    void build_dynamic_gi_sources(const World& world){
        current_bounce_count_=0;current_bounce_positions_.fill({0,0,0,0});current_bounce_colors_.fill({0,0,0,0});
        if(!current_render_settings_.dynamic_diffuse_gi)return;
        struct Candidate{XMFLOAT4 position;XMFLOAT4 color;float score;};std::vector<Candidate> candidates;
        for(const auto& [entity,material]:world.renderables){
            const auto transform=world.transforms.find(entity);if(transform==world.transforms.end())continue;
            const float scale=std::max({std::abs(transform->second.scale.x),std::abs(transform->second.scale.y),std::abs(transform->second.scale.z),0.1F});
            const float strength=std::max(0.0F,current_render_settings_.dynamic_gi_intensity)*0.15F;
            Candidate candidate{
                {static_cast<float>(transform->second.position.x-current_render_origin_.x),static_cast<float>(transform->second.position.y-current_render_origin_.y),static_cast<float>(transform->second.position.z-current_render_origin_.z),std::max(scale*2.0F,current_render_settings_.dynamic_gi_distance)},
                {material.base_color.x*current_sun_.color.x,material.base_color.y*current_sun_.color.y,material.base_color.z*current_sun_.color.z,strength*current_sun_.intensity},
                scale*scale*(material.base_color.x+material.base_color.y+material.base_color.z),
            };candidates.push_back(candidate);
        }
        std::sort(candidates.begin(),candidates.end(),[](const Candidate& left,const Candidate& right){return left.score>right.score;});
        current_bounce_count_=std::min<std::size_t>({candidates.size(),current_bounce_positions_.size(),static_cast<std::size_t>(std::max(0,current_render_settings_.maximum_dynamic_gi_sources))});
        for(std::size_t index=0;index<current_bounce_count_;++index){current_bounce_positions_[index]=candidates[index].position;current_bounce_colors_[index]=candidates[index].color;}
    }
    static WorldVector3 render_origin_for(const WorldVector3& camera,const SimulationSettings& settings){
        const double threshold=std::max(1.0e-12,settings.render_origin_threshold_world_units);
        return {std::nearbyint(camera.x/threshold)*threshold,
                std::nearbyint(camera.y/threshold)*threshold,
                std::nearbyint(camera.z/threshold)*threshold};
    }
    WorldVector3 active_camera(const World& world){for(const auto& [entity,camera]:world.cameras)if(camera.active&&world.transforms.contains(entity))return world.transforms.at(entity).position;return {0,4,-14};}
    WorldVector3 active_camera_target(const World& world){for(const auto& [unused,camera]:world.cameras){static_cast<void>(unused);if(camera.active)return camera.look_at;}return {0,1,0};}
    float active_fov(const World& world){for(const auto& [unused,camera]:world.cameras){static_cast<void>(unused);if(camera.active)return camera.field_of_view_degrees;}return 55;}
    int width_{},height_{},render_width_{},render_height_{};
    float current_environment_intensity_{1.0F},current_render_scale_{1.0F};
    DirectionalLight current_sun_{};RenderSettings current_render_settings_{};
    std::array<XMFLOAT4,8> current_bounce_positions_{},current_bounce_colors_{};std::size_t current_bounce_count_{0};
    WorldVector3 current_render_origin_{},previous_render_origin_{};bool previous_render_origin_valid_{false};
    bool history_valid_{false},previous_view_projection_valid_{false};int history_index_{0};XMMATRIX previous_view_projection_{};
    bool dynamic_resolution_active_{false},timing_started_{false},temporal_enabled_{false};float adaptive_render_scale_{1.0F},average_gpu_ms_{0.0F};
    std::size_t timing_cursor_{0},gpu_timing_samples_{0};std::uint64_t frame_index_{0};std::array<GpuTimingFrame,4> gpu_timing_;
    std::size_t gpu_skinned_draws_{0},cpu_skinned_draws_{0};
    ComPtr<ID3D11Device> device_;ComPtr<ID3D11DeviceContext> context_;ComPtr<IDXGISwapChain> swap_chain_;
    ComPtr<ID3D11RenderTargetView> render_target_,scene_target_,motion_target_;
    std::array<ComPtr<ID3D11RenderTargetView>,2> history_target_;
    ComPtr<ID3D11Texture2D> depth_texture_,shadow_texture_,scene_texture_,motion_texture_;
    std::array<ComPtr<ID3D11Texture2D>,2> history_texture_;
    ComPtr<ID3D11DepthStencilView> depth_view_,shadow_view_;
    ComPtr<ID3D11ShaderResourceView> shadow_srv_,white_texture_,normal_texture_,black_texture_,scene_resource_,motion_resource_;
    std::array<ComPtr<ID3D11ShaderResourceView>,2> history_resource_;
    ComPtr<ID3D11VertexShader> vertex_shader_,shadow_shader_,post_vertex_shader_;
    ComPtr<ID3D11PixelShader> pixel_shader_,temporal_shader_,display_shader_,atmosphere_shader_;
    RenderBackend requested_backend_{RenderBackend::automatic};
    ComPtr<ID3D11InputLayout> layout_;ComPtr<ID3D11Buffer> vertex_buffer_,index_buffer_,constants_,post_constants_,sky_constants_,skin_constants_;
    ComPtr<ID3D11SamplerState> shadow_sampler_,material_sampler_;ComPtr<IWICImagingFactory> wic_;
    ComPtr<ID3D11RasterizerState> default_rasterizer_,shadow_rasterizer_;
    std::unordered_map<std::string,ComPtr<ID3D11ShaderResourceView>> texture_cache_;std::unordered_map<std::string,GpuMesh> mesh_cache_;
    std::unordered_map<std::string,CpuSkinData> cpu_skin_cache_;
    std::unordered_map<std::string,GpuSkinData> gpu_skin_cache_;
    std::unordered_map<EntityId,Transform> previous_transforms_;
};

#else
class GpuRenderer::Implementation { public: explicit Implementation(RenderBackend requested):requested_(requested){}bool initialize(void*,int,int,std::string& e){e="No native presentation backend is available on this platform build.";return false;}bool resize(int,int,std::string& e){return initialize(nullptr,0,0,e);}bool render(const World&,std::string& e){return initialize(nullptr,0,0,e);}bool capture(const std::filesystem::path&,std::string& e){return initialize(nullptr,0,0,e);}bool ready()const noexcept{return false;}GpuRenderProfile profile()const noexcept{return {};}RenderBackend backend()const noexcept{return requested_==RenderBackend::automatic?RenderBackend::null_backend:requested_;}RenderBackendCapabilities capabilities()const{return {backend(),backend()==RenderBackend::metal?"Metal":backend()==RenderBackend::vulkan?"Vulkan":backend()==RenderBackend::d3d12?"Direct3D 12":"Null",backend()==RenderBackend::null_backend,false,false,false,false};}RenderBackend requested_; };
#endif

GpuRenderer::GpuRenderer(RenderBackend requested):implementation_(std::make_unique<Implementation>(requested)){}
GpuRenderer::~GpuRenderer()=default;
bool GpuRenderer::initialize(void* w,int x,int y,std::string& e){return implementation_->initialize(w,x,y,e);}bool GpuRenderer::resize(int x,int y,std::string& e){return implementation_->resize(x,y,e);}bool GpuRenderer::render(const World& w,std::string& e){return implementation_->render(w,e);}bool GpuRenderer::capture_bmp(const std::filesystem::path& p,std::string& e){return implementation_->capture(p,e);}bool GpuRenderer::ready()const noexcept{return implementation_->ready();}
GpuRenderProfile GpuRenderer::profile()const noexcept{return implementation_->profile();}
RenderBackend GpuRenderer::backend()const noexcept{return implementation_->backend();}
RenderBackendCapabilities GpuRenderer::capabilities()const{return implementation_->capabilities();}

}  // namespace tc::runtime
